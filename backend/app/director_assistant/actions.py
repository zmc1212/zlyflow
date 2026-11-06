from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .protocol import ArtifactDraft, MediaDraft
from .repository import AssistantConflict, AssistantNotFound, AssistantRepository, dumps, identifier, timestamp
from .script_documents import document_analysis, ensure_document_idle, ensure_locked_bodies_unchanged, locked_episodes, primary_document, remove_script_episode, script_values

_MEDIA_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="assistant-media")
TABLES = {"document": "ai_project_documents", "asset": "ai_project_assets", "episode": "ai_project_episodes"}


def fingerprint(row: Any) -> str:
    return hashlib.sha256(json.dumps(dict(row or {}), ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


class ProjectActions:
    def __init__(self, repo: AssistantRepository):
        self.repo = repo

    def recipe_snapshot(self, project_id: str | None, *, conn=None) -> dict:
        if not project_id:
            return {}
        from contextlib import nullcontext
        from ..skill_packs.context import craft_overlay_for_stage
        from ..skill_packs.recipe import get_pack
        with nullcontext(conn) if conn is not None else self.repo.store.connection() as db:
            row = db.execute("SELECT settings_json FROM ai_projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise AssistantNotFound("关联工程不存在")
        settings = json.loads(row.get("settings_json") or "{}")
        extra = settings.get("extra") or {}
        recipe = get_pack(str(extra.get("skill_pack_id") or ""))
        if recipe.is_default:
            return {"id": "", "name": recipe.name, "stages": {}}
        return {"id": recipe.id, "name": recipe.name, "stages": {
            stage: craft_overlay_for_stage(stage, recipe.id, extra=extra, project_id=project_id)
            for stage in recipe.director2_overlay
        }}

    def context(self, project_id: str | None) -> dict:
        if not project_id:
            return {"project": None, "message": "尚未关联工程，可先在对话中创作，采纳时选择或创建工程"}
        with self.repo.store.connection() as conn:
            project = conn.execute("SELECT * FROM ai_projects WHERE id=?", (project_id,)).fetchone()
            if not project:
                raise AssistantNotFound("关联工程不存在")
            docs = conn.execute("SELECT * FROM ai_project_documents WHERE project_id=? AND COALESCE(status,'')<>'merged' ORDER BY created_at,id", (project_id,)).fetchall()
            assets = conn.execute("SELECT id,kind,name,role,description,visual_prompt,image_url,voice_id FROM ai_project_assets WHERE project_id=? LIMIT 100", (project_id,)).fetchall()
            episodes = conn.execute("SELECT * FROM ai_project_episodes WHERE project_id=? ORDER BY episode_num LIMIT 100", (project_id,)).fetchall()
            legacy = conn.execute("SELECT id,status FROM ai_project_jobs WHERE project_id=? AND job_type='ai_pipeline' AND status IN ('queued','running','clarifying','revising','awaiting_review') LIMIT 1", (project_id,)).fetchone()
        from ..media_studio.services.episode_video_service import EpisodeVideoService
        from ..workflow_registry import workflow_for
        definition = workflow_for(EpisodeVideoService.DEFAULTS["workflow"])
        main_script = primary_document(docs)
        with self.repo.store.connection() as conn:
            image_models = conn.execute("SELECT provider_model AS id,display_name AS name FROM grs_image_models WHERE enabled=1 ORDER BY sort_order,provider_model LIMIT 100").fetchall()
        return {"project": {"id": project["id"], "name": project["name"], "description": project.get("description"), "settings": json.loads(project.get("settings_json") or "{}")},
                "documents": [{"id": d["id"], "filename": d["filename"], "raw_text": str(d.get("raw_text") or "")[:24000],
                               "is_primary": d["id"] == (main_script or {}).get("id"),
                               "script_episodes": [{"episode_num": e["episode_num"], "title": e.get("title"), "summary": e.get("summary")} for e in document_analysis(d).get("episodes", [])],
                               "episode_outlines": document_analysis(d).get("episode_outlines", []),
                               "latest_episode_text": str(max(document_analysis(d).get("episodes") or [{}], key=lambda e: int(e.get("episode_num") or 0)).get("body") or "")[-12000:],
                               "story_setting_text": document_analysis(d).get("story_setting_text", "")} for d in docs],
                "assets": [dict(a) for a in assets], "episodes": [{**e, "data_json": dumps({**json.loads(e.get("data_json") or "{}"), "beats": json.loads(e.get("data_json") or "{}").get("beats", [])[:50]})} for e in episodes],
                "legacy_operation": dict(legacy) if legacy else None,
                "media_capabilities": {"image_models": [dict(m) for m in image_models], "default_video_workflow": {"id": definition.id, "name": definition.name,
                    "parameters": {key: value for key, value in ((definition.option_schema or {}).get("properties") or {}).items() if value.get("ui_group") in {"primary", "advanced"}}}}}

    def create_draft(self, owner: str, session: dict, arguments: dict, run_id: str) -> dict:
        draft = ArtifactDraft.model_validate(arguments).model_dump()
        previous = None
        if draft["revises_id"]:
            previous = self.repo.get(owner, draft["revises_id"], "artifact")
            if previous["session_id"] != session["id"]:
                raise ValueError("只能修订当前会话的草稿")
        return self.repo.insert(owner, "artifact", {**draft, "session_id": session["id"], "project_id": session.get("project_id"),
                                "run_id": run_id, "revision": int(previous.get("revision", 0)) + 1 if previous else 1}, parent=session["id"])

    def preview(self, owner: str, artifact_id: str, project_id: str, mapping: dict | None = None) -> dict:
        artifact = self.repo.get(owner, artifact_id, "artifact")
        if artifact["artifact_type"] in {"prompt", "plan"}:
            raise ValueError("此产物可复制或导出，无需写入内容库")
        session = self.repo.get(owner, artifact["session_id"], "session")
        if session.get("project_id") and session["project_id"] != project_id:
            raise ValueError("该会话已关联其他工程，请在新会话中使用目标工程")
        mapping = mapping or {}
        script_draft = artifact["artifact_type"] == "script" or (artifact["artifact_type"] == "episodes" and not any(key.startswith("episode:") for key in mapping))
        script_action = mapping.get("script_action") or ("replace_document" if mapping.get("document") else "append_episodes")
        if script_action not in {"append_episodes", "update_episodes", "replace_document", "new_document"}:
            raise ValueError("剧本写入方式无效")
        script_body_write = artifact["artifact_type"] == "script" and artifact.get("data", {}).get("section", "body") == "body" and script_action in {"append_episodes", "update_episodes", "new_document"}
        with self.repo.project_transaction(project_id, allow_generation_jobs=script_body_write) as (conn, project):
            plans = []

            def change(kind: str, key: str, label: str, values: dict, target_id=None):
                target_id = mapping.get(key) or target_id
                table = TABLES[kind]
                existing = None
                if target_id:
                    existing = conn.execute(f"SELECT * FROM {table} WHERE id=? AND project_id=?", (target_id, project_id)).fetchone()
                    if not existing:
                        raise ValueError(f"更新目标不存在：{label}")
                plans.append({"entity": kind, "key": key, "label": label, "target_id": target_id or identifier(kind),
                              "operation": "update" if existing else "add", "base_hash": fingerprint(existing), "values": values})
                return existing

            if script_draft:
                docs = conn.execute("SELECT * FROM ai_project_documents WHERE project_id=? AND COALESCE(status,'')<>'merged' ORDER BY created_at,id", (project_id,)).fetchall()
                target = next((doc for doc in docs if doc["id"] == mapping.get("document")), None) if mapping.get("document") else primary_document(docs)
                if mapping.get("document") and not target:
                    raise AssistantNotFound("当前剧本不存在或已合并，请刷新后重试")
                if script_action == "new_document":
                    target = None
                ensure_document_idle(conn, project_id, target)
                values, label = script_values(target, artifact, script_action)
                if target:
                    ensure_locked_bodies_unchanged(target, values, locked_episodes(conn, project_id, target))
                change("document", "document", label, values, (target or {}).get("id"))
                plans[-1].update(script_write_action=script_action,
                                 script_section="outline" if artifact["artifact_type"] == "episodes" else artifact.get("data", {}).get("section", "body"),
                                 initial_body=artifact["artifact_type"] == "script" and artifact.get("data", {}).get("section", "body") == "body" and not document_analysis(target).get("episodes"),
                                 initial_script=not docs and script_action != "new_document")
            elif artifact["artifact_type"] == "assets":
                for index, asset in enumerate(artifact["data"]["assets"]):
                    change("asset", f"asset:{index}", asset["name"], asset)
            else:
                asset_rows = conn.execute("SELECT id,kind,name FROM ai_project_assets WHERE project_id=?", (project_id,)).fetchall()
                known_assets = {a["id"]: a["kind"] for a in asset_rows}
                character_names = [a["name"] for a in asset_rows if a["kind"] == "character"]
                invalid_refs: list[str] = []
                for episode in artifact["data"]["episodes"]:
                    for beat in episode["beats"]:
                        for aid in beat["character_ids"]:
                            if known_assets.get(aid) != "character":
                                invalid_refs.append(f"角色 {aid}")
                        if beat["scene_id"] and known_assets.get(beat["scene_id"]) != "scene":
                            invalid_refs.append(f"场景 {beat['scene_id']}")
                        for aid in beat["prop_ids"]:
                            if known_assets.get(aid) != "prop":
                                invalid_refs.append(f"道具 {aid}")
                if invalid_refs:
                    # 列出无效引用与全部有效资产 ID，模型可在同一轮重建草稿而不是反复试错。
                    catalog = [{"id": aid, "kind": kind, "name": name} for aid, kind, name in
                               ((a["id"], a["kind"], a["name"]) for a in asset_rows)]
                    raise ValueError("镜头引用了不属于本工程的资产：" + "、".join(invalid_refs)
                                     + "。有效资产（必须逐字使用以下 id）：" + json.dumps(catalog, ensure_ascii=False))
                for episode in artifact["data"]["episodes"]:
                    key = f"episode:{episode['episode_num']}"
                    target_id = mapping[key] if key in mapping else None
                    if target_id is None and episode.get("episode_id"):
                        # 模型常自造占位 episode_id（如 ep-001）或引用上一版草稿里
                        # 从未采纳的 ID：指向不存在的分集时按新建处理；
                        # 采纳映射里显式给出的无效目标仍由下方 existing 校验拦截。
                        exists = conn.execute("SELECT id FROM ai_project_episodes WHERE id=? AND project_id=?", (str(episode["episode_id"]), project_id)).fetchone()
                        target_id = str(episode["episode_id"]) if exists else None
                    existing = conn.execute("SELECT * FROM ai_project_episodes WHERE id=? AND project_id=?", (target_id, project_id)).fetchone() if target_id else None
                    if not target_id:
                        same_number = conn.execute("SELECT id FROM ai_project_episodes WHERE project_id=? AND episode_num=? LIMIT 1", (project_id, episode["episode_num"])).fetchone()
                        if same_number:
                            raise AssistantConflict(f"第{episode['episode_num']}集已存在，请明确选择更新目标，或选择新工程")
                    old_data = json.loads(existing.get("data_json") or "{}") if existing else {}
                    data = {**old_data, "summary": episode["summary"]}
                    if artifact["artifact_type"] == "storyboard":
                        from ..media_studio.services.h3_prompt_builder import H3PromptBuilder

                        old_beats = {b.get("id"): b for b in old_data.get("beats", [])}
                        beats = []
                        for index, beat in enumerate(episode["beats"]):
                            bid = beat["id"] if beat["id"] in old_beats else identifier("beat")[:64]
                            merged = {**old_beats.get(bid, {}), **beat, "id": bid, "sequence": index + 1,
                                      "description": beat["action"], "promptText": beat["prompt"], "video_prompt": beat["prompt"],
                                      "duration_sec": beat["duration"], "title": f"镜头 {index + 1}"}
                            # 分镜草稿的多人台词只写在 dialogue 文本里，落库时补出说话人，
                            # 否则剧集工坊出片前置检查会判定「有对白但缺少说话人」。
                            merged.update(H3PromptBuilder.resolve_beat_speakers(merged, character_names))
                            beats.append(merged)
                        data["beats"] = beats
                    change("episode", key, f"第{episode['episode_num']}集 · {episode['title']}", {
                        "episode_num": episode["episode_num"], "title": episode["title"], "status": "script_ready",
                        "script_text": episode["script_text"] or episode["summary"], "shots_count": len(data.get("beats", [])), "data_json": dumps(data),
                    }, target_id)
            application = self.repo.insert(owner, "application", {"artifact_id": artifact_id, "artifact_version": artifact["version"],
                        "session_id": session["id"], "project_id": project_id, "project_name": project["name"], "changes": plans},
                        parent=artifact_id, status="previewed", conn=conn)
        return application

    def apply(self, owner: str, application_id: str) -> dict:
        preview = self.repo.get(owner, application_id, "application")
        if preview["status"] == "applied":
            return preview
        previous_artifact = self.repo.get(owner, preview["artifact_id"], "artifact")
        if previous_artifact.get("application_id"):
            return self.repo.get(owner, previous_artifact["application_id"], "application")
        # Scoped body writes can run beside other episodes' generation jobs;
        # recheck per-episode production locks below.
        script_body_write = previous_artifact["artifact_type"] == "script" and previous_artifact.get("data", {}).get("section", "body") == "body" and bool(preview["changes"]) and all(
            item["entity"] == "document" and (item["operation"] == "add" or item.get("script_write_action") in {"append_episodes", "update_episodes"}) for item in preview["changes"]
        )
        with self.repo.project_transaction(
            preview["project_id"], replay_id=preview["artifact_id"], replay_owner=owner,
            allow_generation_jobs=script_body_write,
        ) as (conn, project):
            preview = self.repo.get(owner, application_id, "application", conn=conn, lock=True)
            if preview["status"] == "applied":
                return preview
            artifact = self.repo.get(owner, preview["artifact_id"], "artifact", conn=conn, lock=True)
            # A draft can have several previews; adopting a second preview must
            # return the first receipt, never add a second set of entities.
            if artifact.get("application_id"):
                return self.repo.get(owner, artifact["application_id"], "application", conn=conn)
            if artifact["version"] != preview["artifact_version"]:
                raise AssistantConflict("草稿已变化，请重新预览")
            now = timestamp()
            for item in preview["changes"]:
                table = TABLES[item["entity"]]
                row = conn.execute(f"SELECT * FROM {table} WHERE id=? AND project_id=?", (item["target_id"], project["id"]), for_update=True).fetchone()
                if fingerprint(row) != item["base_hash"]:
                    raise AssistantConflict(f"{item['label']} 已被修改，请重新预览变更")
                if item["entity"] == "document":
                    ensure_document_idle(conn, project["id"], row)
                    if item.get("initial_script") and conn.execute("SELECT id FROM ai_project_documents WHERE project_id=? AND COALESCE(status,'')<>'merged' LIMIT 1", (project["id"],)).fetchone():
                        raise AssistantConflict("当前剧本已创建，请重新预览并追加分集")
                    if row:
                        self.repo.insert(owner, "script_revision", {"project_id": project["id"], "document": dict(row), "application_id": application_id}, parent=row["id"], conn=conn)
                values = dict(item["values"])
                if item["entity"] == "document" and row:
                    ensure_locked_bodies_unchanged(row, values, locked_episodes(conn, project["id"], row))
                if item["entity"] == "episode":
                    collision = conn.execute("SELECT id FROM ai_project_episodes WHERE project_id=? AND episode_num=? AND id<>? LIMIT 1", (project["id"], values["episode_num"], item["target_id"])).fetchone()
                    if collision:
                        raise AssistantConflict(f"第{values['episode_num']}集已被创建，请重新预览并明确更新目标")
                values["updated_at"] = now
                if item["operation"] == "update":
                    assignment = ",".join(f"{k}=?" for k in values)
                    conn.execute(f"UPDATE {table} SET {assignment} WHERE id=? AND project_id=?", (*values.values(), item["target_id"], project["id"]))
                else:
                    values.update(id=item["target_id"], project_id=project["id"], created_at=now)
                    conn.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
            session = self.repo.get(owner, preview["session_id"], "session", conn=conn, lock=True)
            if session.get("project_id") not in (None, project["id"]):
                raise AssistantConflict("会话已关联其他工程，请重新选择")
            if not session.get("project_id"):
                self.repo.update(owner, session, {"project_id": project["id"]}, conn=conn)
            self.repo.update(owner, artifact, {"application_id": application_id, "applied_project_id": project["id"]}, conn=conn)
            if artifact["artifact_type"] == "script" and any(item.get("initial_body") for item in preview["changes"]):
                self._sync_project_info(conn, project, artifact)
            else:
                conn.execute("UPDATE ai_projects SET updated_at=? WHERE id=?", (now, project["id"]))
            result = self.repo.update(owner, preview, {}, status="applied", conn=conn)
        return result

    def consolidate_scripts(self, owner: str, project_id: str, target_id: str, source_ids: list[str]) -> dict:
        """Explicitly recover legacy per-episode documents; retain source rows."""
        if not source_ids or target_id in source_ids:
            raise ValueError("请选择要并入当前剧本的独立分集稿")
        with self.repo.project_transaction(project_id, allow_generation_jobs=True) as (conn, project):
            target = conn.execute("SELECT * FROM ai_project_documents WHERE id=? AND project_id=?", (target_id, project_id), for_update=True).fetchone()
            if not target:
                raise AssistantNotFound("当前剧本不存在")
            ensure_document_idle(conn, project_id, target)
            for source_id in dict.fromkeys(source_ids):
                source = conn.execute("SELECT * FROM ai_project_documents WHERE id=? AND project_id=?", (source_id, project_id), for_update=True).fetchone()
                if not source:
                    raise AssistantNotFound("待合并的分集稿不存在")
                if source.get("status") == "merged" and document_analysis(source).get("merged_into_document_id") == target_id:
                    continue
                ensure_document_idle(conn, project_id, source)
                values, _ = script_values(dict(target), {"artifact_type": "script", "title": source["filename"], "content": source["raw_text"], "data": {}}, "append_episodes")
                analysis = json.loads(values["analysis_json"])
                analysis["source_document_ids"] = list(dict.fromkeys([*analysis.get("source_document_ids", []), source_id]))
                values["analysis_json"] = dumps(analysis)
                self.repo.insert(owner, "script_revision", {"project_id": project_id, "document": dict(target), "source_document": dict(source)}, parent=target_id, conn=conn)
                conn.execute("UPDATE ai_project_documents SET " + ",".join(f"{key}=?" for key in values) + ",updated_at=? WHERE id=? AND project_id=?", (*values.values(), timestamp(), target_id, project_id))
                source_analysis = document_analysis(source)
                source_analysis["merged_into_document_id"] = target_id
                conn.execute("UPDATE ai_project_documents SET status='merged',analysis_json=?,updated_at=? WHERE id=? AND project_id=?", (dumps(source_analysis), timestamp(), source_id, project_id))
                target = {**dict(target), **values}
            conn.execute("UPDATE ai_projects SET updated_at=? WHERE id=?", (timestamp(), project_id))
        return {"document_id": target_id, "source_document_ids": source_ids, "status": "merged"}

    def edit_script_episode(self, owner: str, project_id: str, document_id: str, number: int, text: str, base_text: str) -> dict:
        from .script_documents import episode_spans
        if [value for value, _, _ in episode_spans(text)] != [number]:
            raise ValueError(f"本次只编辑第{number}集，请保留该集标题及编号")
        with self.repo.project_transaction(project_id, allow_generation_jobs=True) as (conn, _):
            row = conn.execute("SELECT * FROM ai_project_documents WHERE id=? AND project_id=?", (document_id, project_id), for_update=True).fetchone()
            if not row:
                raise AssistantNotFound("当前剧本不存在")
            if str(row.get("raw_text") or "") != base_text:
                raise AssistantConflict("剧本已更新，请重新加载后再保存；本地修改已保留")
            ensure_document_idle(conn, project_id, row)
            locks = locked_episodes(conn, project_id, row)
            if number in locks:
                raise AssistantConflict(f"第{number}集：{locks[number]}")
            analysis = document_analysis(row)
            has_body = any(int(ep["episode_num"]) == number for ep in analysis.get("episodes", []))
            if not has_body and not any(int(ep["episode_num"]) == number for ep in analysis.get("episode_outlines", [])):
                raise ValueError("请先新建本集，再填写正文")
            if not text.split("\n", 1)[-1].strip() or "\n" not in text:
                raise ValueError("请填写本集正文")
            values, _ = script_values(dict(row), {"artifact_type": "script", "title": row["filename"], "content": text, "data": {}}, "update_episodes" if has_body else "append_episodes")
            self.repo.insert(owner, "script_revision", {"project_id": project_id, "document": dict(row)}, parent=document_id, conn=conn)
            conn.execute("UPDATE ai_project_documents SET " + ",".join(f"{key}=?" for key in values) + ",updated_at=? WHERE id=? AND project_id=?", (*values.values(), timestamp(), document_id, project_id))
            conn.execute("UPDATE ai_projects SET updated_at=? WHERE id=?", (timestamp(), project_id))
        return {**dict(row), **values, "analysis": json.loads(values["analysis_json"]), "shot_plan_job_id": None}

    def create_script_episode(self, owner: str, project_id: str, document_id: str, base_text: str) -> dict:
        with self.repo.project_transaction(project_id, allow_generation_jobs=True) as (conn, _):
            row = conn.execute("SELECT * FROM ai_project_documents WHERE id=? AND project_id=?", (document_id, project_id), for_update=True).fetchone()
            if not row:
                raise AssistantNotFound("当前剧本不存在")
            if str(row.get("raw_text") or "") != base_text:
                raise AssistantConflict("剧本已更新，请重新加载后再新建分集")
            ensure_document_idle(conn, project_id, row)
            analysis = document_analysis(row)
            numbers = {int(ep["episode_num"]) for ep in [*analysis.get("episodes", []), *analysis.get("episode_outlines", [])]}
            number = max(numbers, default=0) + 1
            if number > 1000:
                raise ValueError("单部短剧最多1000集")
            analysis.setdefault("episode_outlines", []).append({"episode_num": number, "title": "未命名", "summary": ""})
            self.repo.insert(owner, "script_revision", {"project_id": project_id, "document": dict(row)}, parent=document_id, conn=conn)
            conn.execute("UPDATE ai_project_documents SET analysis_json=?,updated_at=? WHERE id=? AND project_id=?", (dumps(analysis), timestamp(), document_id, project_id))
            conn.execute("UPDATE ai_projects SET updated_at=? WHERE id=?", (timestamp(), project_id))
        return {"episode_num": number, "document_id": document_id}

    def delete_script_episode(self, owner: str, project_id: str, document_id: str, number: int, base_text: str) -> dict:
        with self.repo.project_transaction(project_id, allow_generation_jobs=True) as (conn, _):
            row = conn.execute("SELECT * FROM ai_project_documents WHERE id=? AND project_id=?", (document_id, project_id), for_update=True).fetchone()
            if not row:
                raise AssistantNotFound("当前剧本不存在")
            if str(row.get("raw_text") or "") != base_text:
                raise AssistantConflict("剧本已更新，请重新加载后再删除分集")
            ensure_document_idle(conn, project_id, row)
            locks = locked_episodes(conn, project_id, row)
            if number in locks:
                raise AssistantConflict(f"第{number}集：{locks[number]}")
            values = remove_script_episode(dict(row), number)
            ensure_locked_bodies_unchanged(row, values, locks)
            self.repo.insert(owner, "script_revision", {"project_id": project_id, "document": dict(row), "deleted_episode_num": number}, parent=document_id, conn=conn)
            conn.execute("UPDATE ai_project_documents SET raw_text=?,analysis_json=?,file_size=?,updated_at=? WHERE id=? AND project_id=?", (values["raw_text"], values["analysis_json"], values["file_size"], timestamp(), document_id, project_id))
            conn.execute("UPDATE ai_projects SET updated_at=? WHERE id=?", (timestamp(), project_id))
        return {"document_id": document_id, "episode_num": number, "status": "deleted"}

    @staticmethod
    def _sync_project_info(conn, project: dict, artifact: dict):
        settings = json.loads(project.get("settings_json") or "{}")
        extra = settings.setdefault("extra", {})
        name, description = project["name"], project.get("description") or ""
        if extra.get("name_source") != "manual" and (not name or name.startswith("未命名") or name == extra.get("ai_generated_name")):
            name = artifact["title"]
            extra.update(name_source="ai", ai_generated_name=name)
        summary = artifact["data"].get("summary") or ""
        if summary and extra.get("description_source") != "manual" and (not description or description == extra.get("ai_generated_description")):
            description = summary
            extra.update(description_source="ai", ai_generated_description=description)
        conn.execute("UPDATE ai_projects SET name=?,description=?,settings_json=?,updated_at=? WHERE id=?", (name, description, dumps(settings), timestamp(), project["id"]))

    def set_project_extra(self, project_id: str, values: dict, *, conn=None) -> dict:
        from contextlib import nullcontext
        with nullcontext(conn) if conn is not None else self.repo.store.connection() as db:
            row = db.execute("SELECT settings_json FROM ai_projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise AssistantNotFound("关联工程不存在")
            settings = json.loads(row.get("settings_json") or "{}")
            if not isinstance(settings, dict):
                settings = {}
            extra = settings.get("extra")
            if not isinstance(extra, dict):
                extra = settings["extra"] = {}
            extra.update(values)
            db.execute("UPDATE ai_projects SET settings_json=?,updated_at=? WHERE id=?", (dumps(settings), timestamp(), project_id))
        return extra

    def propose_media(self, owner: str, session: dict, arguments: dict, run_id: str) -> dict:
        draft = MediaDraft.model_validate(arguments).model_dump()
        project_id = session.get("project_id")
        if not project_id:
            raise ValueError("请先关联工程并采纳相关内容，再提出媒体任务")
        context = self.context(project_id)
        target_name, options, creation_parameters = "", dict(draft["options"]), []
        if draft["media_type"] == "asset_image":
            asset = next((a for a in context["assets"] if a["id"] == draft["asset_id"]), None)
            if not asset:
                raise ValueError("生图目标资产不存在")
            target_name = asset["name"]
        else:
            episode = next((e for e in context["episodes"] if e["id"] == draft["episode_id"]), None)
            if not episode:
                raise ValueError("媒体目标分集不存在")
            target_name = f"第{episode['episode_num']}集 · {episode['title']}"
            if draft["beat_id"]:
                with self.repo.store.connection() as conn:
                    full_episode = conn.execute("SELECT data_json FROM ai_project_episodes WHERE id=? AND project_id=?", (draft["episode_id"], project_id)).fetchone()
                beat = next((b for b in json.loads(full_episode.get("data_json") or "{}").get("beats", []) if b["id"] == draft["beat_id"]), None)
                if not beat:
                    raise ValueError("媒体目标镜头不存在")
                target_name += f" / 镜头{beat.get('sequence', '')}"
        media_type = draft["media_type"]
        if media_type == "asset_image":
            with self.repo.store.connection() as conn:
                rows = conn.execute("SELECT provider_model,display_name FROM grs_image_models WHERE enabled=1 ORDER BY is_default DESC,sort_order,provider_model").fetchall()
            chosen = next((row for row in rows if row["provider_model"] == options.get("model")), None) if options.get("model") else (rows[0] if rows else None)
            if not chosen:
                raise ValueError("该生图模型未启用，请在管理设置开放模型后重试")
            options["model"] = chosen["provider_model"]
            options.setdefault("aspect_ratio", "16:9")
            model_name = chosen["display_name"]
            creation_parameters = [{"label": "画面比例", "value": options["aspect_ratio"]}]
        elif media_type == "video":
            from ..media_studio.services.episode_video_service import EpisodeVideoService
            from ..workflow_registry import workflow_for
            options = EpisodeVideoService.apply_confirmed_video_resolution(project_id, options)
            resolved = EpisodeVideoService.resolve_generation_options(options)
            if resolved.get("workflow_fallback"):
                raise ValueError("所选视频工作流不可用，请重新选择")
            definition = workflow_for(resolved["workflow_id"])
            options = {**options, **resolved}
            model_name = definition.name
            creation_parameters = [{"label": spec.get("label", key), "value": resolved.get(key, spec.get("default"))} for key, spec in ((definition.option_schema or {}).get("properties") or {}).items() if spec.get("ui_group") in {"primary", "advanced"}]
        elif media_type == "voice":
            with self.repo.store.connection() as conn:
                row = conn.execute("SELECT model FROM tts_provider_settings WHERE id=1").fetchone()
            model_name = str((row or {}).get("model") or "当前配音供应商")
        else:
            model_name = "工作台成片合成"
        draft["options"] = options
        table, target_id = ("ai_project_assets", draft["asset_id"]) if media_type == "asset_image" else ("ai_project_episodes", draft["episode_id"])
        with self.repo.store.connection() as conn:
            target_row = conn.execute(f"SELECT * FROM {table} WHERE id=? AND project_id=?", (target_id, project_id)).fetchone()
        return self.repo.insert(owner, "media_proposal", {**draft, "session_id": session["id"], "project_id": project_id,
                               "project_name": context["project"]["name"], "model_id": session["selections"]["model_id"],
                               "model_name": model_name, "target_name": target_name, "creation_parameters": creation_parameters,
                               "target_fingerprint": fingerprint(target_row),
                               "run_id": run_id, "quantity": 1}, parent=session["id"], status="awaiting_approval")

    def confirm_media(self, owner: str, proposal_id: str) -> dict:
        proposal = self.repo.get(owner, proposal_id, "media_proposal")
        if proposal.get("execution_id"):
            return self.repo.get(owner, proposal["execution_id"], "media_execution")
        with self.repo.project_transaction(proposal["project_id"], replay_id=proposal_id, replay_owner=owner) as (conn, _):
            proposal = self.repo.get(owner, proposal_id, "media_proposal", conn=conn, lock=True)
            if proposal.get("execution_id"):
                return self.repo.get(owner, proposal["execution_id"], "media_execution", conn=conn)
            self._validate_proposal(proposal, conn)
            execution = self.repo.insert(owner, "media_execution", {"proposal_id": proposal_id, "project_id": proposal["project_id"],
                                       "session_id": proposal["session_id"], "title": proposal["title"]}, parent=proposal["project_id"], status="queued", conn=conn)
            self.repo.update(owner, proposal, {"execution_id": execution["id"]}, status="approved", conn=conn)
        _MEDIA_EXECUTOR.submit(self._dispatch_media, owner, execution["id"])
        return execution

    @staticmethod
    def _validate_proposal(proposal: dict, conn):
        table, target_id = ("ai_project_assets", proposal["asset_id"]) if proposal["media_type"] == "asset_image" else ("ai_project_episodes", proposal["episode_id"])
        row = conn.execute(f"SELECT * FROM {table} WHERE id=? AND project_id=?", (target_id, proposal["project_id"])).fetchone()
        if not row or fingerprint(row) != proposal["target_fingerprint"]:
            raise AssistantConflict("目标素材已变化，请按最新内容重新生成执行提案")
        if proposal["media_type"] == "asset_image":
            model = conn.execute("SELECT provider_model FROM grs_image_models WHERE provider_model=? AND enabled=1", (proposal["options"]["model"],)).fetchone()
            if not model:
                raise AssistantConflict("提案中的生图模型已停用，请重新选择")

    def _dispatch_media(self, owner: str, execution_id: str):
        execution = self.repo.get(owner, execution_id, "media_execution")
        proposal = self.repo.get(owner, execution["proposal_id"], "media_proposal")
        try:
            with self.repo.store.connection() as conn:
                self._validate_proposal(proposal, conn)
            execution = self.repo.update(owner, execution, {}, status="running")
            from ..media_studio.services.project_detail_service import ProjectDetailService
            from ..media_studio.services.episode_video_service import EpisodeVideoService
            from ..media_studio.services.tts_generation_job_service import TtsGenerationJobService
            from .model_context import model_scope
            options = dict(proposal["options"])
            options["assistant_model_id"] = proposal["model_id"]
            with model_scope(proposal["model_id"]):
                kind, pid, eid, bid = proposal["media_type"], proposal["project_id"], proposal.get("episode_id"), proposal.get("beat_id")
                if kind == "asset_image":
                    result = ProjectDetailService.generate_asset_image(pid, proposal["asset_id"], options)
                elif kind == "video":
                    result = EpisodeVideoService.create_job(pid, eid, beat_id=bid, render_scope="shot", options=options) if bid else EpisodeVideoService.generate_episode_videos(pid, eid, options=options)
                elif kind == "voice":
                    result = TtsGenerationJobService.enqueue(pid, eid)
                else:
                    result = EpisodeVideoService.create_compose_job(pid, eid, options=options)
            self.repo.update(owner, execution, {"result": result}, status="succeeded")
        except Exception as exc:
            self.repo.update(owner, execution, {"error": str(exc)[:1000]}, status="failed")
