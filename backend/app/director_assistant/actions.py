from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .protocol import ArtifactDraft, MediaDraft
from .repository import AssistantConflict, AssistantNotFound, AssistantRepository, dumps, identifier, timestamp

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
            docs = conn.execute("SELECT id,filename,raw_text,updated_at FROM ai_project_documents WHERE project_id=? ORDER BY updated_at DESC LIMIT 2", (project_id,)).fetchall()
            assets = conn.execute("SELECT id,kind,name,role,description,visual_prompt,image_url,voice_id FROM ai_project_assets WHERE project_id=? LIMIT 100", (project_id,)).fetchall()
            episodes = conn.execute("SELECT * FROM ai_project_episodes WHERE project_id=? ORDER BY episode_num LIMIT 100", (project_id,)).fetchall()
            legacy = conn.execute("SELECT id,status FROM ai_project_jobs WHERE project_id=? AND job_type='ai_pipeline' AND status IN ('queued','running','clarifying','revising','awaiting_review') LIMIT 1", (project_id,)).fetchone()
        from ..media_studio.services.episode_video_service import EpisodeVideoService
        from ..workflow_registry import workflow_for
        definition = workflow_for(EpisodeVideoService.DEFAULTS["workflow"])
        with self.repo.store.connection() as conn:
            image_models = conn.execute("SELECT provider_model AS id,display_name AS name FROM grs_image_models WHERE enabled=1 ORDER BY is_default DESC,sort_order LIMIT 100").fetchall()
        return {"project": {"id": project["id"], "name": project["name"], "description": project.get("description"), "settings": json.loads(project.get("settings_json") or "{}")},
                "documents": [{**d, "raw_text": str(d.get("raw_text") or "")[:24000]} for d in docs],
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
        with self.repo.project_transaction(project_id) as (conn, project):
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

            if artifact["artifact_type"] == "script":
                from ..media_studio.services.script_parser import StandardScriptParser
                content = artifact["content"]
                change("document", "document", artifact["title"], {
                    "filename": artifact["title"], "file_size": len(content.encode()), "input_mode": "assistant_v2",
                    "status": "ready", "spine_template": "drama", "visual_style": "",
                    "raw_text": content, "analysis_json": dumps(StandardScriptParser.parse(content)),
                })
            elif artifact["artifact_type"] == "assets":
                for index, asset in enumerate(artifact["data"]["assets"]):
                    change("asset", f"asset:{index}", asset["name"], asset)
            else:
                known_assets = {a["id"]: a["kind"] for a in conn.execute("SELECT id,kind FROM ai_project_assets WHERE project_id=?", (project_id,)).fetchall()}
                for episode in artifact["data"]["episodes"]:
                    key = f"episode:{episode['episode_num']}"
                    target_id = mapping[key] if key in mapping else episode.get("episode_id")
                    existing = conn.execute("SELECT * FROM ai_project_episodes WHERE id=? AND project_id=?", (target_id, project_id)).fetchone() if target_id else None
                    if not target_id:
                        same_number = conn.execute("SELECT id FROM ai_project_episodes WHERE project_id=? AND episode_num=? LIMIT 1", (project_id, episode["episode_num"])).fetchone()
                        if same_number:
                            raise AssistantConflict(f"第{episode['episode_num']}集已存在，请明确选择更新目标，或选择新工程")
                    old_data = json.loads(existing.get("data_json") or "{}") if existing else {}
                    data = {**old_data, "summary": episode["summary"]}
                    if artifact["artifact_type"] == "storyboard":
                        old_beats = {b.get("id"): b for b in old_data.get("beats", [])}
                        beats = []
                        for index, beat in enumerate(episode["beats"]):
                            for aid in beat["character_ids"]:
                                if known_assets.get(aid) != "character":
                                    raise ValueError("镜头引用了不属于本工程的角色")
                            for aid in beat["prop_ids"]:
                                if known_assets.get(aid) != "prop":
                                    raise ValueError("镜头引用了不属于本工程的道具")
                            if beat["scene_id"] and known_assets.get(beat["scene_id"]) != "scene":
                                raise ValueError("镜头引用了不属于本工程的场景")
                            bid = beat["id"] if beat["id"] in old_beats else identifier("beat")[:64]
                            beats.append({**old_beats.get(bid, {}), **beat, "id": bid, "sequence": index + 1,
                                          "description": beat["action"], "promptText": beat["prompt"], "video_prompt": beat["prompt"],
                                          "duration_sec": beat["duration"], "title": f"镜头 {index + 1}"})
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
        with self.repo.project_transaction(preview["project_id"], replay_id=preview["artifact_id"], replay_owner=owner) as (conn, project):
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
                values = dict(item["values"])
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
            if artifact["artifact_type"] == "script":
                self._sync_project_info(conn, project, artifact)
            else:
                conn.execute("UPDATE ai_projects SET updated_at=? WHERE id=?", (now, project["id"]))
            result = self.repo.update(owner, preview, {}, status="applied", conn=conn)
        return result

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
        if media_type in {"asset_image", "storyboard_image"}:
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
        if proposal["media_type"] in {"asset_image", "storyboard_image"}:
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
                elif kind == "storyboard_image":
                    result = ProjectDetailService.generate_beat_sketch(pid, eid, bid, options)
                elif kind == "video":
                    result = EpisodeVideoService.create_job(pid, eid, beat_id=bid, render_scope="shot", options=options) if bid else EpisodeVideoService.generate_episode_videos(pid, eid, options=options)
                elif kind == "voice":
                    result = TtsGenerationJobService.enqueue(pid, eid)
                else:
                    result = EpisodeVideoService.create_compose_job(pid, eid, options=options)
            self.repo.update(owner, execution, {"result": result}, status="succeeded")
        except Exception as exc:
            self.repo.update(owner, execution, {"error": str(exc)[:1000]}, status="failed")
