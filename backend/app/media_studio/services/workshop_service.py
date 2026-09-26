"""Versioned workshop commands. AI writes candidates; apply is the only commit."""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import uuid

from ..db import query_one, query_all, execute_sql, transaction_cursor, now_str
from . import workshop_contract as contract
from .workshop_group_prompts import is_director, expand_groups, generate_group
from .workshop_references import resolve_state, assert_ready, assert_reference_snapshot


class WorkshopService:
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="workshop")
    lock = threading.RLock()
    JOB_TYPES = ("workshop_planning", "workshop_prompt")

    @staticmethod
    def reference_assets(project_id):
        from .project_detail_service import ProjectDetailService
        return [ProjectDetailService._hydrate_asset(dict(a)) for a in query_all(
            "SELECT * FROM ai_project_assets WHERE project_id=%s", (project_id,))]

    @classmethod
    def resolved_data(cls, project_id, data):
        if ((data.get("prompt_authoring") or {}).get("director_plan") or {}).get("schema_version") != 7:
            return data
        return resolve_state(data, cls.reference_assets(project_id))

    @staticmethod
    def row(project_id, episode_id):
        row = query_one("SELECT * FROM ai_project_episodes WHERE id=%s AND project_id=%s", (episode_id, project_id))
        if not row:
            raise ValueError("分集不存在")
        return row, WorkshopService.resolved_data(project_id, json.loads(row.get("data_json") or "{}"))

    @staticmethod
    def source(project_id, row, data):
        doc_id = data.get("source_document_id")
        doc = query_one("SELECT * FROM ai_project_documents WHERE id=%s AND project_id=%s", (doc_id, project_id)) if doc_id else None
        analysis = json.loads((doc or {}).get("analysis_json") or "{}")
        adopted = analysis.get("script_development") or {}
        episode = next((e for e in analysis.get("episodes", []) if e.get("episode_num") == row["episode_num"]), None)
        text = str((episode or {}).get("body") or "")
        if not text:
            text = str(row.get("script_text") or "")
        revision = adopted.get("revision") or data.get("script_revision") or 0
        return {"document_id": doc_id, "revision": revision, "text": text,
                "fingerprint": contract.digest([doc_id, revision, text]), "unlinked": not bool(episode),
                "episode": {**(episode or {}), "body": text, "episode_num": row["episode_num"], "title": row.get("title")}}

    @classmethod
    def view(cls, project_id, episode_id):
        row, data = cls.row(project_id, episode_id)
        plan = (data.get("prompt_authoring") or {}).get("director_plan") or {}
        source = cls.source(project_id, row, data)
        jobs = []
        for job in query_all("SELECT id,status,job_type,payload_json,error_message FROM ai_project_jobs WHERE project_id=%s AND job_type IN (%s,%s) ORDER BY created_at DESC", (project_id, *cls.JOB_TYPES)):
            payload = json.loads(job.get("payload_json") or "{}")
            if payload.get("episode_id") == episode_id:
                jobs.append({"id": job["id"], "status": job["status"], "kind": job["job_type"], "error": job.get("error_message"), "payload": payload})
                if len(jobs) >= 12:
                    break
        return {"plan": plan if plan.get("schema_version") == 7 else None, "source": source,
                "history": data.get("workshop_history") or [],
                "historical_media": [m for state in ((data.get("production") or {}).get("modes") or {}).values() for m in state.get("materials") or []],
                "legacy_plan": plan if plan and plan.get("schema_version") != 7 else None,
                "legacy_prompts": data.get("workshop_legacy_prompts") or contract.legacy_candidates(data.get("beats") or [], plan),
                "jobs": jobs, "source_changed": bool(plan.get("schema_version") == 7 and source["fingerprint"] != plan.get("source_fingerprint"))}

    @classmethod
    def bind_adopted(cls, cursor, project_id, doc_id, analysis):
        """Called in the adoption transaction; never copies parser shots into the workshop."""
        adopted = analysis["script_development"]
        cursor.execute("SELECT * FROM ai_project_episodes WHERE project_id=%s FOR UPDATE", (project_id,))
        rows = list(cursor.fetchall())
        for episode in analysis.get("episodes") or []:
            num = int(episode.get("episode_num") or 1)
            linked = next((r for r in rows if r["episode_num"] == num and json.loads(r.get("data_json") or "{}").get("source_document_id") == doc_id), None)
            if linked:
                data = json.loads(linked.get("data_json") or "{}")
                data["script_stale"] = {"document_id": doc_id, "revision": adopted["revision"]}
                cursor.execute("UPDATE ai_project_episodes SET data_json=%s,updated_at=%s WHERE id=%s", (json.dumps(data, ensure_ascii=False), now_str(), linked["id"]))
            elif not any(r["episode_num"] == num for r in rows):
                data = {"beats": [], "workshop_flow": 7, "source_document_id": doc_id,
                        "script_revision": adopted["revision"], "dramatic_design": episode.get("dramatic_design") or {}}
                cursor.execute("INSERT INTO ai_project_episodes (id,project_id,episode_num,title,status,script_text,shots_count,data_json,created_at,updated_at) VALUES (%s,%s,%s,%s,'script_ready',%s,0,%s,%s,%s)",
                               ("ep-" + uuid.uuid4().hex[:12], project_id, num, episode.get("title") or f"第 {num} 集", episode.get("body") or "", json.dumps(data, ensure_ascii=False), now_str(), now_str()))

    @classmethod
    def mutate(cls, project_id, episode_id, expected, operation):
        with transaction_cursor() as cursor:
            cursor.execute("SELECT * FROM ai_project_episodes WHERE id=%s AND project_id=%s FOR UPDATE", (episode_id, project_id))
            row = cursor.fetchone()
            if not row:
                raise ValueError("分集不存在")
            data = cls.resolved_data(project_id, json.loads(row.get("data_json") or "{}"))
            plan = (data.get("prompt_authoring") or {}).get("director_plan") or {}
            current = int(plan.get("revision") or 0)
            if type(expected) is not int or expected != current:
                raise ValueError("VERSION_CONFLICT: 制作内容已变化，请刷新后重试")
            operation(data, plan, row)
            data = cls.resolved_data(project_id, data)
            cursor.execute("UPDATE ai_project_episodes SET data_json=%s,script_text=%s,shots_count=%s,updated_at=%s WHERE id=%s AND project_id=%s",
                           (json.dumps(data, ensure_ascii=False), row.get("script_text") or "", len(data.get("beats") or []), now_str(), episode_id, project_id))
        return cls.view(project_id, episode_id)

    @classmethod
    def create(cls, project_id, episode_id, kind, request):
        if kind not in cls.JOB_TYPES:
            raise ValueError("未知工坊任务")
        row, data = cls.row(project_id, episode_id)
        plan = (data.get("prompt_authoring") or {}).get("director_plan") or {}
        expected = request.get("expected_revision")
        if type(expected) is not int or expected != int(plan.get("revision") or 0):
            raise ValueError("VERSION_CONFLICT: 请刷新后重新提交")
        assert_reference_snapshot(plan, request)
        source = cls.source(project_id, row, data)
        if not source["text"].strip():
            raise ValueError("请先在内容库采纳本集剧本")
        if kind == "workshop_planning":
            from ...workflow_registry import workflow_for
            definition = workflow_for(request.get("workflow_id") or "")
            maximum = request.get("max_shots_per_group", 3)
            if type(maximum) is not int or not 1 <= maximum <= (definition.max_segments or 1):
                raise ValueError("每组镜头数超过所选工作流能力")
            target = request.get("target_shot_count")
            if target is not None and (type(target) is not int or not 1 <= target <= 500):
                raise ValueError("目标镜头数应为 1～500 的整数")
            if request.get("aspect_ratio", "16:9") not in {"16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9"}:
                raise ValueError("无效画幅")
            total = request.get("target_duration_seconds")
            if total is not None and (type(total) is not int or not 1 <= total <= 7200):
                raise ValueError("目标时长应为 1～7200 秒")
        if kind == "workshop_prompt" and plan.get("schema_version") != 7:
            raise ValueError("请先确认镜头规划")
        if kind == "workshop_prompt" and plan.get("source_fingerprint") != source["fingerprint"]:
            raise ValueError("采纳剧本已更新，请先调整镜头规划")
        payload = {"episode_id": episode_id, "source": source, "request": deepcopy(request),
                   "base_plan": deepcopy(plan), "beats": deepcopy(data.get("beats") or []), "candidates": {},
                   "message": "等待执行", "failures": {}, "applied_ids": []}
        if kind == "workshop_prompt":
            ids = request.get("beat_ids") or [b["id"] for b in payload["beats"]]
            if not ids or set(ids) - {b["id"] for b in payload["beats"]}:
                raise ValueError("请选择有效镜头")
            assert_ready(plan, ids)
            payload["request"]["beat_ids"] = list(dict.fromkeys(ids))
            if is_director(plan):
                if request.get("prompt_scope") == "shot_revision":
                    if len(ids) != 1 or not str(request.get("revision_note") or "").strip() or len(str(request.get("revision_note"))) > 4000:
                        raise ValueError("请选择一个镜头并填写 1～4000 字返修意见")
                    for bid in expand_groups(plan, ids):
                        beat = next(b for b in payload["beats"] if b["id"] == bid)
                        group = next(g for g in plan["groups"] if bid in g["beat_ids"])
                        record = plan.get("shot_prompts", {}).get(bid) or {}
                        if record.get("fingerprint") != contract.prompt_fingerprint(beat, group, plan):
                            raise ValueError("请先为整组生成并采纳有效提示词，再返修单镜")
                    payload["prompt_scope"] = "shot_revision"
                else:
                    payload["request"]["beat_ids"] = expand_groups(plan, ids)
                    payload["prompt_scope"] = "group"
        with cls.lock:
            for job in cls.view(project_id, episode_id)["jobs"]:
                if job["status"] in {"queued", "running"} and job["kind"] == kind and job["payload"]["request"] == payload["request"]:
                    return {"job_id": job["id"], "status": job["status"]}
            jid = "job-" + uuid.uuid4().hex[:12]
            execute_sql("INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,payload_json,created_at,updated_at) VALUES (%s,%s,%s,%s,'queued',0,%s,%s,%s)",
                        (jid, project_id, kind, ("规划镜头" if kind == "workshop_planning" else "生成 H3 提示词") + f" · 第 {row['episode_num']} 集", json.dumps(payload, ensure_ascii=False), now_str(), now_str()))
            cls.executor.submit(cls.run, project_id, jid)
        return {"job_id": jid, "status": "queued"}

    @classmethod
    def run(cls, project_id, jid):
        if not execute_sql("UPDATE ai_project_jobs SET status='running' WHERE id=%s AND project_id=%s AND status='queued'", (jid, project_id)):
            return
        job = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (jid, project_id))
        payload = json.loads(job["payload_json"])
        def checkpoint(message, status="running", error=None):
            payload["message"] = message
            changed = execute_sql("UPDATE ai_project_jobs SET payload_json=%s,status=%s,error_message=%s,progress=%s,updated_at=%s WHERE id=%s AND project_id=%s AND status='running'",
                                 (json.dumps(payload, ensure_ascii=False), status, error, 100 if status == "completed" else 50, now_str(), jid, project_id))
            if not changed:
                raise ValueError("任务已取消")
        try:
            from .llm_service import LlmService
            from .project_detail_service import ProjectDetailService, asset_name_id_map
            from .prompt_templates import build_full_reference_prompts, parse_full_reference
            request = payload["request"]
            if job["job_type"] == "workshop_planning":
                checkpoint("正在规划镜头结构；不会生成 H3 提示词")
                if request.get("reuse_existing"):
                    beats = deepcopy(payload["beats"])
                    if not beats:
                        raise ValueError("没有可以保留的镜头，请选择重新规划")
                else:
                    source = deepcopy(payload["source"]["episode"])
                    source["target_shot_count"] = request.get("target_shot_count")
                    source["target_duration_seconds"] = request.get("target_duration_seconds")
                    shots = LlmService.plan_episode_shots(source, aspect_ratio=request.get("aspect_ratio") or "16:9")
                    assets = ProjectDetailService.list_assets(project_id)
                    beats = ProjectDetailService._beats_from_document_shots(payload["episode_id"], shots,
                        asset_name_id_map(assets, "character"), asset_name_id_map(assets, "scene"), asset_name_id_map(assets, "prop"))
                    # Reuse an ID only for a unique exact structural match, never by array position.
                    for beat in beats:
                        matches = [b for b in payload["beats"] if contract.shot_fingerprint(b) == contract.shot_fingerprint(beat)]
                        beat["id"] = matches[0]["id"] if len(matches) == 1 else "shot-" + uuid.uuid4().hex[:12]
                plan = contract.new_plan(beats, request["workflow_id"], payload["source"], payload["base_plan"], int(request.get("max_shots_per_group") or 3))
                plan["aspect_ratio"] = request.get("aspect_ratio") or "16:9"
                plan["target_shot_count"] = request.get("target_shot_count")
                plan["target_duration_seconds"] = request.get("target_duration_seconds")
                resolved = resolve_state({"beats": beats, "prompt_authoring": {"director_plan": plan}}, cls.reference_assets(project_id))
                beats, plan = resolved["beats"], resolved["prompt_authoring"]["director_plan"]
                payload["candidate"] = {"beats": beats, "plan": plan}
                target = request.get("target_shot_count")
                payload["count_note"] = f"目标 {target} 镜，建议 {len(beats)} 镜；请检查剧情和对白覆盖后采纳" if target and target != len(beats) else "请检查镜头和分组后确认"
            else:
                plan = payload["base_plan"]
                if is_director(plan) and payload.get("prompt_scope") != "shot_revision":
                    payload["prompt_scope"] = "group"
                    for group in plan["groups"]:
                        if not set(group["beat_ids"]).intersection(request["beat_ids"]):
                            continue
                        if all(bid in payload["candidates"] for bid in group["beat_ids"]):
                            continue
                        checkpoint(f"正在统筹生成镜头组 {group['id']}（{len(group['beat_ids'])} 镜）")
                        for bid in group["beat_ids"]:
                            payload["candidates"].pop(bid, None)
                        try:
                            generated = generate_group(plan, group, payload["beats"], source_text=payload.get("source", {}).get("text", ""))
                            payload["candidates"].update(generated)
                            for bid in group["beat_ids"]:
                                payload["failures"].pop(bid, None)
                        except Exception as err:
                            for bid in group["beat_ids"]:
                                payload["failures"][bid] = str(err)
                        checkpoint(f"已生成 {len(payload['candidates'])} 镜；失败 {len(payload['failures'])} 镜")
                for bid in request["beat_ids"]:
                    if is_director(plan) and payload.get("prompt_scope") != "shot_revision":
                        break
                    if bid in payload["candidates"]:
                        continue
                    checkpoint(f"正在生成镜头 {bid} 的 H3 候选稿")
                    beat = next(b for b in payload["beats"] if b["id"] == bid)
                    group = next(g for g in plan["groups"] if bid in g["beat_ids"])
                    try:
                        if is_director(plan):
                            payload["candidates"].update(generate_group(plan, group, payload["beats"],
                                revision_beat_id=bid, revision_note=request.get("revision_note", ""), source_text=payload.get("source", {}).get("text", "")))
                            payload["failures"].pop(bid, None)
                            checkpoint(f"已生成 {len(payload['candidates'])} 镜；失败 {len(payload['failures'])} 镜")
                            continue
                        system, user = build_full_reference_prompts(language="zh-CN", rewrite_mode="strict", aspect_ratio=plan["aspect_ratio"],
                            duration_seconds=contract.duration(beat), source_text=json.dumps({"镜头": beat, "组公共设定": group.get("common_prompt"),
                            "同组镜头": [b for b in payload["beats"] if b["id"] in group["beat_ids"]]}, ensure_ascii=False), reference_slots=group.get("reference_slots") or [])
                        system += "\n只写当前镜头。保留导演意图与可执行表演，禁止改写剧情、对白、镜头数或时长。只使用 [Shot 1]，从 0 秒开始，台词末尾留安全余量。组公共主体及声音设定保持不变，不要另写另一套主体。"
                        system += "\nSubject 编号只能引用组公共设定中已有的定义，不能新增、重新编号或改变对应人物。若公共设定没有 Subject 编号，正文直接使用人物姓名。"
                        from ...llm_minimax_skills import load_h3_prompt_writing_skill_excerpt, H3_REF2VA_LABEL_DISCIPLINE
                        system += "\n" + load_h3_prompt_writing_skill_excerpt() + "\n" + H3_REF2VA_LABEL_DISCIPLINE
                        seconds = contract.duration(beat)
                        user += f"\n本次详细描述必须以如下行开始（不要更换为秒数区间或补充 Shot）：[Shot 1] 00:00.00–{int(seconds // 60):02}:{seconds % 60:05.2f}。"
                        if payload.get("prompt_scope") == "shot_revision":
                            user += "\n本次为单镜定点返修。只修改当前镜头，前后镜头不可更改，保持与其动作起止、视线、空间和声音衔接。不可修改时长、剧情或组公共设定。"
                            user += "\n返修意见：" + request["revision_note"]
                            user += "\n整组已采纳正文（按镜头顺序）：" + json.dumps([
                                {"beat_id": target, "prompt": plan["shot_prompts"][target]["h3_prompt"]}
                                for target in group["beat_ids"]], ensure_ascii=False)
                        images = [s["image_url"] for s in group.get("reference_slots") or []]
                        writing = beat.get("workshop_writing_refs") or []
                        if writing:
                            user += "\n后附写稿参考仅供构图/动作参考，不分配 Picture 编号，不作为视频提交素材。"
                        images += writing
                        raw = (LlmService.chat_vision(system, user, images, max_tokens=7000, temperature=0.2) if images else
                               LlmService.chat_text(system, user, max_tokens=7000, temperature=0.2))
                        parsed = parse_full_reference(raw, "zh-CN", group.get("reference_slots") or [])
                        from .prompt_templates import ZH_FULL_SECTIONS
                        body = "\n\n".join(f"{label}：{parsed['sections'][key]}" for key, label in ZH_FULL_SECTIONS if key != "subject_definitions")
                        errors = contract.prompt_checks(body, beat, group, ordered_beats=[b for b in payload["beats"] if b["id"] in group["beat_ids"]])
                        if errors:
                            payload.setdefault("rejected_candidates", {})[bid] = {"h3_prompt": body, "errors": errors}
                            raise ValueError("；".join(errors))
                        payload["candidates"][bid] = {"h3_prompt": body, "fingerprint": contract.prompt_fingerprint(beat, group, plan)}
                        payload["failures"].pop(bid, None)
                    except Exception as err:
                        payload["failures"][bid] = str(err)
                    checkpoint(f"已生成 {len(payload['candidates'])} 镜；失败 {len(payload['failures'])} 镜")
            if job["job_type"] == "workshop_prompt" and not payload["candidates"]:
                checkpoint("未生成可用候选，请查看失败原因", "failed", "；".join(dict.fromkeys(payload["failures"].values())) or "未生成可用候选")
            else:
                checkpoint("候选已生成，请检查后采纳" if not payload["failures"] else "部分镜头失败，成功候选已保留", "completed")
        except Exception as err:
            try:
                checkpoint("执行失败，当前制作版本未改变", "failed", str(err))
            except ValueError:
                pass

    @classmethod
    def job_action(cls, project_id, episode_id, jid, request):
        job = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (jid, project_id))
        if not job or job["job_type"] not in cls.JOB_TYPES:
            raise ValueError("工坊任务不存在")
        payload = json.loads(job["payload_json"])
        if payload.get("episode_id") != episode_id:
            raise ValueError("任务不属于此分集")
        action = request.get("action")
        if action == "cancel":
            execute_sql("UPDATE ai_project_jobs SET status='cancelled',updated_at=%s WHERE id=%s AND status IN ('queued','running')", (now_str(), jid))
        elif action == "retry":
            if job["status"] not in {"failed", "cancelled", "completed"}:
                raise ValueError("任务仍在执行")
            changed = execute_sql("UPDATE ai_project_jobs SET status='queued',error_message=NULL,updated_at=%s WHERE id=%s AND project_id=%s AND status IN ('failed','cancelled','completed')", (now_str(), jid, project_id))
            if changed:
                cls.executor.submit(cls.run, project_id, jid)
        elif action == "apply":
            if job["status"] != "completed":
                raise ValueError("任务尚未完成")
            def apply(data, current, row):
                assert_reference_snapshot(current, request)
                if cls.source(project_id, row, data)["fingerprint"] != payload["source"]["fingerprint"]:
                    raise ValueError("SOURCE_CONFLICT: 采纳剧本已变化，请重新规划")
                if job["job_type"] == "workshop_planning":
                    from . import production_state
                    previous_detail = {"data": deepcopy(data), "beats": deepcopy(data.get("beats") or []), "prompt_authoring": deepcopy(data.get("prompt_authoring") or {}), "script_text": row.get("script_text")}
                    previous_production = production_state.hydrate(previous_detail)
                    candidate = deepcopy(payload["candidate"])
                    plan = candidate["plan"]
                    beats = candidate["beats"]
                    if int(current.get("revision") or 0) != int(payload["base_plan"].get("revision") or 0):
                        raise ValueError("VERSION_CONFLICT: 规划期间已有编辑，请重新生成候选")
                    if request.get("groups") is not None:
                        plan["groups"] = request["groups"]
                    if request.get("shot_updates"):
                        updates = request["shot_updates"]
                        if not isinstance(updates, dict) or set(updates) - {b["id"] for b in beats}:
                            raise ValueError("候选镜头不存在")
                        for beat in beats:
                            fields = updates.get(beat["id"]) or {}
                            if set(fields) - {"camera", "video_duration", "heading"}:
                                raise ValueError("候选中只能调整拍摄意图、标题和时长；剧情修改请回内容库")
                            if any(beat.get(k) != v for k,v in fields.items()):
                                beat.update(fields)
                        plan["shot_fingerprints"] = {b["id"]: contract.shot_fingerprint(b) for b in beats}
                    contract.validate_groups(beats, plan["groups"], plan["workflow_id"], plan["max_shots_per_group"])
                    data.setdefault("workshop_history", []).append({"beats": deepcopy(data.get("beats") or []), "prompt_authoring": deepcopy(data.get("prompt_authoring") or {}), "script_text": row.get("script_text")})
                    if current.get("schema_version") != 7:
                        data["workshop_legacy_prompts"] = contract.legacy_candidates(data.get("beats") or [], current)
                    else:
                        for group in plan["groups"]:
                            old = next((g for g in current["groups"] if g["beat_ids"] == group["beat_ids"]), None)
                            if old:
                                group.update(id=old["id"], common_prompt=old.get("common_prompt", ""), reference_slots=old.get("reference_slots") or [], reference_policy=old.get("reference_policy", "manual"))
                        for beat in beats:
                            group = next(g for g in plan["groups"] if beat["id"] in g["beat_ids"])
                            record = current.get("shot_prompts", {}).get(beat["id"])
                            if record and record.get("fingerprint") == contract.prompt_fingerprint(beat, group, plan):
                                plan["shot_prompts"][beat["id"]] = record
                    for beat in beats:
                        beat.pop("h3_prompt", None)
                    data.update(beats=beats, workshop_flow=7, script_revision=payload["source"]["revision"])
                    data.pop("script_stale", None)
                    data.setdefault("prompt_authoring", {})["director_plan"] = plan
                    row["script_text"] = payload["source"]["text"]
                    current_detail = {"data": data, "beats": beats, "prompt_authoring": data["prompt_authoring"], "script_text": row["script_text"]}
                    data["production"] = production_state.carry_workshop_materials(previous_production, previous_detail, current_detail)
                else:
                    ids = request.get("beat_ids") or list(payload["candidates"])
                    assert_ready(current, ids)
                    if is_director(current):
                        context_ids = expand_groups(payload["base_plan"], ids)
                        for context_id in context_ids:
                            old_group = next(g for g in payload["base_plan"]["groups"] if context_id in g["beat_ids"])
                            new_group = next((g for g in current.get("groups", []) if context_id in g["beat_ids"]), None)
                            context_beat = next((b for b in data["beats"] if b["id"] == context_id), None)
                            old_beat = next((b for b in payload.get("beats", data["beats"]) if b["id"] == context_id), None)
                            if not new_group or any(new_group.get(k) != old_group.get(k) for k in ("id", "beat_ids", "common_prompt", "reference_slots")) or not context_beat or not old_beat or contract.prompt_fingerprint(context_beat, new_group, current) != contract.prompt_fingerprint(old_beat, old_group, payload["base_plan"]):
                                raise ValueError("VERSION_CONFLICT: 同组镜头或公共设定已变化，请重新生成候选")
                        if payload.get("prompt_scope") == "shot_revision":
                            if ids != payload["request"]["beat_ids"]:
                                raise ValueError("单镜返修只能采纳指定镜头")
                            context_ids = expand_groups(payload["base_plan"], ids)
                            for context_id in context_ids:
                                if current.get("shot_prompts", {}).get(context_id) != payload["base_plan"].get("shot_prompts", {}).get(context_id):
                                    raise ValueError("VERSION_CONFLICT: 同组提示词已变化，请基于最新内容重新返修")
                        elif payload.get("prompt_scope") != "group":
                            raise ValueError("旧逐镜候选仅供参考，请重新生成整组候选")
                        else:
                            expanded = expand_groups(payload["base_plan"], ids)
                            if not expanded or set(expanded) != set(ids):
                                raise ValueError("导演台工作流必须整组采纳候选")
                    for bid in ids:
                        record = payload["candidates"].get(bid)
                        beat = next((b for b in data["beats"] if b["id"] == bid), None)
                        group = next((g for g in current.get("groups", []) if bid in g["beat_ids"]), None)
                        if not record or not beat or not group or record["fingerprint"] != contract.prompt_fingerprint(beat, group, current):
                            raise ValueError("VERSION_CONFLICT: 候选的镜头或参考素材已变化")
                        if bid in current.get("applied_candidates", {}).get(jid, []):
                            raise ValueError("此候选已采纳；再次编辑请生成新候选")
                        if current.get("shot_prompts", {}).get(bid) != payload["base_plan"].get("shot_prompts", {}).get(bid):
                            raise ValueError("VERSION_CONFLICT: 当前镜头已有新稿，不能覆盖")
                        errors = contract.prompt_checks(record.get("h3_prompt", ""), beat, group, h3=is_director(current),
                                                        ordered_beats=[b for b in data["beats"] if b["id"] in group["beat_ids"]])
                        if errors:
                            raise ValueError("候选不符合当前 H3 要求，请重新生成：" + "；".join(errors))
                        current.setdefault("prompt_history", []).append({"beat_id": bid, "record": deepcopy(current.get("shot_prompts", {}).get(bid))})
                        current.setdefault("shot_prompts", {})[bid] = record
                        current.setdefault("applied_candidates", {}).setdefault(jid, []).append(bid)
                        payload["applied_ids"] = list(set(payload["applied_ids"]) | {bid})
                    current["revision"] += 1
            cls.mutate(project_id, episode_id, request.get("expected_revision"), apply)
            execute_sql("UPDATE ai_project_jobs SET payload_json=%s,updated_at=%s WHERE id=%s AND project_id=%s", (json.dumps(payload, ensure_ascii=False), now_str(), jid, project_id))
        else:
            raise ValueError("未知任务操作")
        return cls.view(project_id, episode_id)

    @classmethod
    def update(cls, project_id, episode_id, request):
        def change(data, plan, row):
            assert_reference_snapshot(plan, request)
            if plan.get("schema_version") != 7:
                raise ValueError("请先确认镜头规划")
            previous = {"data": deepcopy(data), "beats": deepcopy(data["beats"]), "prompt_authoring": deepcopy(data["prompt_authoring"]), "script_text": row.get("script_text")}
            if "groups" in request:
                contract.validate_groups(data["beats"], request["groups"], plan["workflow_id"], plan["max_shots_per_group"])
                groups = deepcopy(request["groups"])
                for group in groups:
                    old = next((g for g in plan["groups"] if g["id"] == group["id"]), {})
                    if not old:
                        group["reference_policy"] = "auto" if group.get("reference_policy") == "auto" else "manual"
                    else:
                        group["reference_policy"] = "manual" if group.get("reference_slots") != old.get("reference_slots") else old.get("reference_policy", "auto")
                plan["groups"] = groups
            if "auto_reference_group_ids" in request:
                ids = request["auto_reference_group_ids"]
                if not isinstance(ids, list) or set(ids) - {g["id"] for g in plan["groups"]}:
                    raise ValueError("请选择有效镜头组")
                for group in plan["groups"]:
                    if group["id"] in ids:
                        group["reference_policy"] = "auto"
            if "beat_id" in request:
                bid = request["beat_id"]
                beat = next((b for b in data["beats"] if b["id"] == bid), None)
                if not beat:
                    raise ValueError("镜头不存在")
                if request.get("shot_updates"):
                    allowed = {"heading", "camera", "video_duration", "character_ids", "character_look_ids", "prop_ids", "scene_id"}
                    if set(request["shot_updates"]) - allowed:
                        raise ValueError("剧情与对白请在内容库修改；这里只调整拍摄设置")
                    beat.update(request["shot_updates"])
                    manual = set(beat.get("workshop_manual_bindings") or [])
                    manual.update(set(request["shot_updates"]) & {"character_ids", "prop_ids"})
                    beat["workshop_manual_bindings"] = sorted(manual)
                    contract.validate_groups(data["beats"], plan["groups"], plan["workflow_id"], plan["max_shots_per_group"])
                if "writing_reference_urls" in request:
                    urls = request["writing_reference_urls"]
                    if not isinstance(urls, list) or len(urls) > 9 or any(not isinstance(u, str) or not u.startswith(("http://", "https://", "/api/")) for u in urls):
                        raise ValueError("写稿参考最多 9 张有效图片")
                    beat["workshop_writing_refs"] = list(dict.fromkeys(urls))
                if "h3_prompt" in request:
                    assert_ready(plan, [bid])
                    group = next(g for g in plan["groups"] if bid in g["beat_ids"])
                    body = str(request["h3_prompt"]).strip()
                    errors = contract.prompt_checks(body, beat, group, h3=is_director(plan),
                                                    ordered_beats=[b for b in data["beats"] if b["id"] in group["beat_ids"]])
                    if errors:
                        raise ValueError("；".join(errors))
                    old = plan.setdefault("shot_prompts", {}).get(bid)
                    plan.setdefault("prompt_history", []).append({"beat_id": bid, "record": old})
                    plan["shot_prompts"][bid] = {"h3_prompt": body, "fingerprint": contract.prompt_fingerprint(beat, group, plan), "origin": "manual"}
            plan["revision"] += 1
            plan["shot_fingerprints"] = {b["id"]: contract.shot_fingerprint(b) for b in data["beats"]}
            if request.get("shot_updates"):
                from . import production_state
                current = {"data": data, "beats": data["beats"], "prompt_authoring": data["prompt_authoring"], "script_text": row.get("script_text")}
                data["production"] = production_state.carry_workshop_materials(production_state.hydrate(previous), previous, current)
        return cls.mutate(project_id, episode_id, request.get("expected_revision"), change)

    @classmethod
    def recover(cls):
        for job in query_all("SELECT id,project_id FROM ai_project_jobs WHERE job_type IN (%s,%s) AND status IN ('queued','running')", cls.JOB_TYPES):
            execute_sql("UPDATE ai_project_jobs SET status='failed',error_message=%s WHERE id=%s", ("服务重启，已完成候选保留，可从检查点重试", job["id"]))
