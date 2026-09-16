from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..db import execute_sql, now_str, query_all, query_one
from .cast_resolver import match_look_id, resolve_mention
from .character_import_service import (
    character_asset_extra,
    complete_character_locally,
    merge_character_fill,
)
from .llm_service import LlmService

JOB_TYPE = "llm_analysis"
SUPPORTED_JOB_TYPES = ("llm_analysis", "h3_prompt")
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="llm-fill")
logger = logging.getLogger("server.llm")
_DISPATCH_LOCK = threading.Lock()
_ACTIVE_LOCK = threading.Lock()
_ACTIVE: set[str] = set()
_MAX_ACTIVE = 2


class LlmFillJobService:
    @classmethod
    def enqueue(cls, project_id: str, title: str, payload: dict[str, Any], job_type: str = JOB_TYPE) -> dict[str, Any]:
        try:
            cls._supersede(project_id, payload, job_type=job_type)
        except Exception:
            pass
        jid = f"job-{uuid.uuid4().hex[:12]}"
        ts = now_str()
        body = {
            **payload,
            "project_id": project_id,
        }
        payload_text = json.dumps(body, ensure_ascii=False)
        params = (jid, project_id, job_type, title[:250], payload_text, ts, ts)
        try:
            execute_sql(
                """
                INSERT INTO ai_project_jobs
                (id, project_id, job_type, title, status, progress, result_url, payload_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'queued', 0, NULL, %s, %s, %s)
                """,
                params,
            )
        except Exception as err:
            if "payload_json" not in str(err) and "Unknown column" not in str(err):
                raise
            execute_sql(
                "ALTER TABLE ai_project_jobs ADD COLUMN payload_json LONGTEXT DEFAULT NULL AFTER error_message",
            )
            execute_sql(
                """
                INSERT INTO ai_project_jobs
                (id, project_id, job_type, title, status, progress, result_url, payload_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'queued', 0, NULL, %s, %s, %s)
                """,
                params,
            )
        cls.kick()
        return {"job_id": jid, "status": "queued", "title": title}

    @classmethod
    def enqueue_character(cls, project_id: str, asset_id: str, character: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        name = character.get("name") or "角色"
        compact = {
            "name": character.get("name"),
            "aliases": character.get("aliases"),
            "role": character.get("role"),
            "description": (character.get("description") or "")[:1200],
            "looks": character.get("looks") or [],
        }
        return cls.enqueue(
            project_id,
            f"补全角色档案: {name}",
            {
                "target_type": "character_profile",
                "asset_id": asset_id,
                "character": compact,
                "context": context,
            },
        )

    @classmethod
    def enqueue_scene(cls, project_id: str, asset_id: str, scene: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        name = scene.get("name") or "场景"
        return cls.enqueue(
            project_id,
            f"补全场景档案: {name}",
            {
                "target_type": "scene_profile",
                "asset_id": asset_id,
                "scene": scene,
                "context": context,
            },
        )

    @classmethod
    def enqueue_prop(cls, project_id: str, asset_id: str, prop: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        name = prop.get("name") or "道具"
        return cls.enqueue(
            project_id,
            f"补全道具档案: {name}",
            {
                "target_type": "prop_profile",
                "asset_id": asset_id,
                "prop": prop,
                "context": context,
            },
        )

    @classmethod
    def enqueue_shot(
        cls,
        project_id: str,
        episode_id: str,
        beat_id: str,
        shot: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        seq = shot.get("shot_num") or shot.get("sequence") or ""
        ep_num = context.get("episode_num") or ""
        return cls.enqueue(
            project_id,
            f"补全分镜: 第{ep_num}集 镜头{seq}",
            {
                "target_type": "shot_beat",
                "episode_id": episode_id,
                "beat_id": beat_id,
                "shot": shot,
                "context": context,
            },
        )

    @classmethod
    def enqueue_h3_prompt(
        cls,
        project_id: str,
        episode_id: str,
        beat_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .project_detail_service import ProjectDetailService

        req = payload or {}
        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        ep_num = int(detail.get("number") or 1)
        ep_title = str(detail.get("title") or "")
        beats = detail.get("beats") or []
        beat = next((b for b in beats if b.get("id") == beat_id), None)
        if not beat:
            raise ValueError(f"未找到指定分镜: {beat_id}")

        assets = ProjectDetailService.list_assets(project_id)
        assets_by_id = {str(a.get("id") or ""): a for a in assets if a.get("id")}

        # 1. 提取出场角色信息
        beat_chars = []
        for cid in (beat.get("character_ids") or []):
            asset = assets_by_id.get(str(cid))
            if not asset:
                continue
            name = asset.get("name") or "角色"
            extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
            identities = extra.get("identities") if isinstance(extra.get("identities"), list) else []
            look_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
            selected_look_id = look_ids.get(str(cid)) or beat.get("character_look_id")
            selected_look = next((item for item in identities if item.get("id") == selected_look_id), None)

            look_desc = ""
            if selected_look:
                look_desc = selected_look.get("appearance_details") or selected_look.get("description") or selected_look.get("name") or ""
            char_desc = extra.get("appearance") or asset.get("description") or ""

            beat_chars.append({
                "id": cid,
                "name": name,
                "desc": char_desc,
                "look_desc": look_desc,
            })

        # 2. 提取场景信息
        scene_id = beat.get("scene_id")
        scene_asset = assets_by_id.get(str(scene_id)) if scene_id else None
        if not scene_asset and beat.get("scene"):
            scene_asset = next((a for a in assets if a.get("kind") == "scene" and a.get("name") == beat.get("scene")), None)
        scene_name = (scene_asset or {}).get("name") or beat.get("scene") or "场景"
        scene_extra = (scene_asset or {}).get("extra") if isinstance((scene_asset or {}).get("extra"), dict) else {}
        scene_desc = scene_extra.get("environment_prompt") or scene_extra.get("visual_prompt") or (scene_asset or {}).get("description") or ""

        # 3. 提取出场道具信息
        beat_props = []
        beat_prop_ids = beat.get("prop_ids") or []
        beat_prop_names = beat.get("props") or []
        for pid in beat_prop_ids:
            asset = assets_by_id.get(str(pid))
            if not asset:
                continue
            name = asset.get("name") or "道具"
            extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
            desc = extra.get("visual_prompt") or extra.get("detail_prompt") or asset.get("description") or ""
            beat_props.append({
                "id": pid,
                "name": name,
                "desc": desc,
            })
        for pname in beat_prop_names:
            if not any(p["name"] == pname for p in beat_props):
                asset = next((a for a in assets if a.get("kind") == "prop" and a.get("name") == pname), None)
                if asset:
                    extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
                    desc = extra.get("visual_prompt") or extra.get("detail_prompt") or asset.get("description") or ""
                    beat_props.append({
                        "id": asset.get("id"),
                        "name": pname,
                        "desc": desc,
                    })
                else:
                    beat_props.append({
                        "id": "",
                        "name": pname,
                        "desc": "",
                    })

        # 4. 参考图列表。前端明确传入时（含空列表）不再补造 Picture 标签。
        if "ref_images" in req:
            ref_images = req.get("ref_images") or []
        else:
            ref_images = None
        if ref_images is None:
            ref_images = []
            for i, c in enumerate(beat_chars, 1):
                ref_images.append({
                    "index": i,
                    "name": c["name"],
                    "category": "character",
                })
            scene_idx = len(ref_images) + 1
            ref_images.append({
                "index": scene_idx,
                "name": scene_name,
                "category": "scene",
            })
            for p in beat_props:
                ref_images.append({
                    "index": len(ref_images) + 1,
                    "name": p["name"],
                    "category": "prop",
                })

        duration_sec = beat.get("video_duration") or 10
        try:
            duration_sec = int(duration_sec)
        except Exception:
            duration_sec = 10

        beat_info = {
            "sequence": beat.get("sequence") or 1,
            "heading": beat.get("heading") or "",
            "action": beat.get("action") or "",
            "camera": beat.get("camera") or "",
            "dialogue": beat.get("dialogue") or "",
            "speaker": beat.get("speaker") or "",
            "duration_seconds": duration_sec,
            "time_of_day": beat.get("time_of_day") or "日间",
            "scene_name": scene_name,
            "scene_desc": scene_desc,
            "characters": beat_chars,
            "props": beat_props,
            "ref_images": ref_images,
            "ref_videos": req.get("ref_videos") or [],
            "ref_audios": req.get("ref_audios") or [],
            "prompt_mode": req.get("prompt_mode") or "",
            "dialogue_turns": beat.get("dialogue_turns") or [],
            "visible_text": beat.get("visible_text") or "",
            "narration": beat.get("narration") or "",
            "existing_prompt": req.get("existing_prompt") or beat.get("h3_prompt") or "",
        }

        seq = beat.get("sequence") or 1
        heading = beat.get("heading") or scene_name or ""
        title = f"生成H3提示词: 第{ep_num}集 镜头{seq}" + (f" · {heading}" if heading else "")
        ref_urls = [img.get("url") for img in ref_images if isinstance(img, dict) and img.get("url")]

        job_payload = {
            "target_type": "h3_prompt",
            "project_id": project_id,
            "episode_id": episode_id,
            "episode_number": ep_num,
            "episode_title": ep_title,
            "beat_id": beat_id,
            "beat_sequence": seq,
            "beat_heading": heading,
            "beat_info": beat_info,
            "reference_urls": ref_urls,
            "model": getattr(LlmService, "MODEL", "MiniMax H3 / 大模型"),
            "existing_prompt": beat_info["existing_prompt"],
        }
        return cls.enqueue(project_id, title, job_payload, job_type="h3_prompt")

    @classmethod
    def retry(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one(
            "SELECT id, status FROM ai_project_jobs WHERE id = %s AND project_id = %s AND job_type IN ('llm_analysis', 'h3_prompt')",
            (job_id, project_id),
        )
        if not row:
            raise ValueError("任务不存在")
        execute_sql(
            """
            UPDATE ai_project_jobs
            SET status = 'queued', progress = 0, error_message = NULL, updated_at = %s
            WHERE id = %s
            """,
            (now_str(), job_id),
        )
        cls.kick()
        return query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}

    @classmethod
    def kick(cls) -> None:
        if not _DISPATCH_LOCK.acquire(blocking=False):
            return
        try:
            with _ACTIVE_LOCK:
                capacity = max(0, _MAX_ACTIVE - len(_ACTIVE))
            if not capacity:
                return
            rows = query_all(
                """
                SELECT id FROM ai_project_jobs
                WHERE job_type IN ('llm_analysis', 'h3_prompt') AND status = 'queued'
                ORDER BY created_at ASC LIMIT 50
                """,
            )
            for row in rows:
                if capacity <= 0:
                    break
                jid = row["id"]
                if execute_sql(
                    "UPDATE ai_project_jobs SET status='preparing', progress=10, updated_at=%s WHERE id=%s AND status='queued'",
                    (now_str(), jid),
                ) != 1:
                    continue
                with _ACTIVE_LOCK:
                    _ACTIVE.add(jid)
                _EXECUTOR.submit(cls._run, jid)
                capacity -= 1
        finally:
            _DISPATCH_LOCK.release()

    @classmethod
    def _run(cls, job_id: str) -> None:
        logger.info("llm job start %s", job_id)
        try:
            row = query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}
            payload = json.loads(row.get("payload_json") or "{}")
            cls._set_state(job_id, payload, "running", 35)
            target = str(payload.get("target_type") or "")
            if target == "character_profile":
                result = cls._fill_character(payload)
            elif target == "scene_profile":
                result = cls._fill_scene(payload)
            elif target == "prop_profile":
                result = cls._fill_prop(payload)
            elif target == "shot_beat":
                result = cls._fill_shot(payload)
            elif target == "h3_prompt":
                result = cls._generate_h3_prompt(payload)
            else:
                raise ValueError(f"未知补全类型: {target}")
            payload["result"] = result
            cls._set_state(job_id, payload, "completed", 100)
            logger.info("llm job completed %s target=%s", job_id, target)
        except Exception as err:
            logger.exception("llm job failed %s: %s", job_id, err)
            try:
                row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}
                payload = json.loads(row.get("payload_json") or "{}")
            except Exception:
                payload = {}
            payload["error"] = str(err)
            execute_sql(
                """
                UPDATE ai_project_jobs
                SET status='failed', progress=0, error_message=%s, payload_json=%s, updated_at=%s
                WHERE id=%s AND status <> 'cancelled'
                """,
                (str(err)[:500], json.dumps(payload, ensure_ascii=False), now_str(), job_id),
            )
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE.discard(job_id)
            cls.kick()

    @classmethod
    def _fill_character(cls, payload: dict[str, Any]) -> dict[str, Any]:
        asset_id = payload.get("asset_id")
        project_id = payload.get("project_id")
        context = payload.get("context") or {}
        draft = payload.get("character") or {}
        row = query_one(
            "SELECT name, role, description, visual_prompt, extra_json FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not row:
            raise ValueError("角色资产不存在")
        if not draft.get("name"):
            draft["name"] = row.get("name")
        if not draft.get("description"):
            draft["description"] = row.get("description")
        if not draft.get("role"):
            draft["role"] = row.get("role")
        from .cast_resolver import ensure_character_looks
        ensure_character_looks(draft)
        filled = LlmService.enrich_one_character(draft, context)
        merged = complete_character_locally(
            merge_character_fill(draft, filled),
            project_style=str(context.get("project_style") or ""),
            genre=str(context.get("genre") or ""),
            visual_style_desc=str(context.get("visual_style") or ""),
            fill_defaults=True,
        )
        existing = {}
        if row.get("extra_json"):
            try:
                existing = json.loads(row["extra_json"]) or {}
            except Exception:
                existing = {}
        extra = character_asset_extra(merged, str(asset_id), existing)
        execute_sql(
            """
            UPDATE ai_project_assets
            SET role=%s, description=%s, visual_prompt=%s, extra_json=%s, updated_at=%s
            WHERE id=%s AND project_id=%s
            """,
            (
                merged.get("role") or "主要角色",
                merged.get("description") or "",
                merged.get("visual_prompt") or "",
                json.dumps(extra, ensure_ascii=False),
                now_str(),
                asset_id,
                project_id,
            ),
        )
        return {"asset_id": asset_id, "name": merged.get("name"), "face_prompt": merged.get("face_prompt")}

    @classmethod
    def _fill_scene(cls, payload: dict[str, Any]) -> dict[str, Any]:
        asset_id = payload.get("asset_id")
        project_id = payload.get("project_id")
        filled = LlmService.enrich_one_scene(payload.get("scene") or {}, payload.get("context") or {})
        row = query_one(
            "SELECT extra_json, description FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not row:
            raise ValueError("场景资产不存在")
        extra = {}
        if row.get("extra_json"):
            try:
                extra = json.loads(row["extra_json"]) or {}
            except Exception:
                extra = {}
        description = str(filled.get("description") or row.get("description") or "")
        extra["environment_prompt"] = str(filled.get("environment_prompt") or extra.get("environment_prompt") or description)
        extra["scene_type"] = str(filled.get("scene_type") or extra.get("scene_type") or "exterior")
        extra["visual_style"] = str(filled.get("visual_style") or extra.get("visual_style") or "")
        execute_sql(
            "UPDATE ai_project_assets SET description=%s, extra_json=%s, updated_at=%s WHERE id=%s AND project_id=%s",
            (description, json.dumps(extra, ensure_ascii=False), now_str(), asset_id, project_id),
        )
        return {"asset_id": asset_id, "description": description}

    @classmethod
    def _fill_prop(cls, payload: dict[str, Any]) -> dict[str, Any]:
        asset_id = payload.get("asset_id")
        project_id = payload.get("project_id")
        filled = LlmService.enrich_one_prop(payload.get("prop") or {}, payload.get("context") or {})
        row = query_one(
            "SELECT extra_json, description FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not row:
            raise ValueError("道具资产不存在")
        extra = {}
        if row.get("extra_json"):
            try:
                extra = json.loads(row["extra_json"]) or {}
            except Exception:
                extra = {}
        description = str(filled.get("description") or row.get("description") or "")
        extra["visual_prompt"] = str(filled.get("visual_prompt") or extra.get("visual_prompt") or description)
        extra["prop_type"] = str(filled.get("prop_type") or extra.get("prop_type") or "object")
        extra["owner"] = str(filled.get("owner") or extra.get("owner") or "")
        execute_sql(
            "UPDATE ai_project_assets SET description=%s, visual_prompt=%s, extra_json=%s, updated_at=%s WHERE id=%s AND project_id=%s",
            (
                description,
                extra["visual_prompt"],
                json.dumps(extra, ensure_ascii=False),
                now_str(),
                asset_id,
                project_id,
            ),
        )
        return {"asset_id": asset_id, "description": description}

    @classmethod
    def _fill_shot(cls, payload: dict[str, Any]) -> dict[str, Any]:
        from .project_detail_service import ProjectDetailService, resolve_shot_scene

        project_id = payload.get("project_id")
        episode_id = payload.get("episode_id")
        beat_id = payload.get("beat_id")
        filled = LlmService.enrich_one_shot(payload.get("shot") or {}, payload.get("context") or {})
        assets = query_all(
            "SELECT id, kind, name, extra_json FROM ai_project_assets WHERE project_id = %s",
            (project_id,),
        )
        char_assets = [item for item in assets if item.get("kind") == "character"]
        characters = []
        for row in char_assets:
            extra = {}
            if row.get("extra_json"):
                try:
                    extra = json.loads(row["extra_json"]) or {}
                except Exception:
                    extra = {}
            aliases = extra.get("aliases") or ""
            alias_list = [part.strip() for part in str(aliases).split(",") if part.strip()]
            characters.append({
                "id": row["id"],
                "name": row["name"],
                "aliases": alias_list,
                "looks": extra.get("identities") or [],
            })
        scene_map = {item["name"]: item["id"] for item in assets if item.get("kind") == "scene"}
        prop_map = {item["name"]: item["id"] for item in assets if item.get("kind") == "prop"}

        names = [str(item) for item in (filled.get("characters") or []) if str(item).strip()]
        resolved_ids = []
        look_ids: dict[str, str] = {}
        resolved_names = []
        for mention in names:
            matched = resolve_mention(mention, characters)
            if not matched or matched["id"] in resolved_ids:
                continue
            resolved_ids.append(matched["id"])
            resolved_names.append(matched["name"])
            looks_map = filled.get("character_looks") if isinstance(filled.get("character_looks"), dict) else {}
            look_name = str(looks_map.get(matched["name"]) or looks_map.get(mention) or "")
            look_id = match_look_id(matched.get("looks") or [], look_name, mention, filled.get("action") or "", filled.get("visual_prompt") or "")
            if look_id:
                look_ids[str(matched["id"])] = look_id

        speaker_mention = str(filled.get("speaker") or "")
        speaker = ""
        if speaker_mention:
            matched = resolve_mention(speaker_mention, characters)
            speaker = matched["name"] if matched else ""
            if matched and matched["id"] not in resolved_ids:
                resolved_ids.insert(0, matched["id"])
                resolved_names.insert(0, matched["name"])
        if not speaker and resolved_names:
            speaker = resolved_names[0]

        scene_name, scene_id = resolve_shot_scene(str(filled.get("scene") or ""), scene_map)
        props = [str(item) for item in (filled.get("props") or []) if str(item).strip()]
        prop_ids = []
        for name in props:
            for key, aid in prop_map.items():
                if key in name or name in key:
                    if aid not in prop_ids:
                        prop_ids.append(aid)

        updates = {
            "heading": str(filled.get("heading") or "").strip(),
            "speaker": speaker,
            "dialogue": str(filled.get("dialogue") or "").strip(),
            "action": str(filled.get("action") or "").strip(),
            "camera": str(filled.get("camera") or "中景").strip(),
            "scene": scene_name,
            "scene_id": scene_id,
            "time_of_day": str(filled.get("time_of_day") or "").strip(),
            "characters": resolved_names,
            "character_ids": resolved_ids,
            "character_look_ids": look_ids,
            "props": props,
            "prop_ids": prop_ids,
            "visual_prompt": str(filled.get("visual_prompt") or "").strip(),
            "sketch_prompt": str(filled.get("visual_prompt") or "").strip(),
            "video_prompt_zh": str(filled.get("video_prompt_zh") or filled.get("action") or "").strip(),
            "video_duration": str(filled.get("video_duration") or "10").strip() or "10",
            "status": "script_ready",
        }
        ProjectDetailService._update_episode_beat_atomic(project_id, episode_id, beat_id, updates)
        return {"beat_id": beat_id, "speaker": speaker, "heading": updates.get("heading")}

    @classmethod
    def _generate_h3_prompt(cls, payload: dict[str, Any]) -> dict[str, Any]:
        from .project_detail_service import ProjectDetailService

        project_id = payload.get("project_id")
        episode_id = payload.get("episode_id")
        beat_id = payload.get("beat_id")
        beat_info = payload.get("beat_info") or {}

        # 1. 调用大模型生成符合规范的 H3 视频提示词
        prompt = LlmService.generate_h3_prompt(beat_info)

        # 2. 持久化写回数据库该分镜的 h3_prompt 字段
        ProjectDetailService._update_episode_beat_atomic(
            project_id,
            episode_id,
            beat_id,
            {"h3_prompt": prompt},
        )

        # 3. 将生成的提示词写入 payload，以便在任务详情中查看和一键复制
        payload["h3_prompt"] = prompt
        payload["result_prompt"] = prompt
        return {"beat_id": beat_id, "prompt": prompt}

    @classmethod
    def _set_state(cls, job_id: str, payload: dict[str, Any], status: str, progress: int) -> None:
        completed_clause = ", completed_at=%s" if status == "completed" else ""
        params = [status, progress, json.dumps(payload, ensure_ascii=False), now_str()]
        if status == "completed":
            params.append(now_str())
        params.append(job_id)
        execute_sql(
            f"""
            UPDATE ai_project_jobs SET status=%s, progress=%s, payload_json=%s, updated_at=%s{completed_clause}
            WHERE id=%s AND status <> 'cancelled'
            """,
            tuple(params),
        )

    @classmethod
    def _supersede(cls, project_id: str, payload: dict[str, Any], job_type: str = JOB_TYPE) -> None:
        target = payload.get("target_type")
        rows = query_all(
            """
            SELECT id, payload_json FROM ai_project_jobs
            WHERE project_id = %s AND job_type = %s AND status IN ('queued', 'preparing')
            """,
            (project_id, job_type),
        )
        for row in rows:
            try:
                old = json.loads(row.get("payload_json") or "{}")
            except Exception:
                continue
            same = old.get("target_type") == target
            if target in {"character_profile", "scene_profile", "prop_profile"}:
                same = same and old.get("asset_id") == payload.get("asset_id")
            elif target in {"shot_beat", "h3_prompt"}:
                same = same and old.get("beat_id") == payload.get("beat_id")
            if same:
                execute_sql(
                    "UPDATE ai_project_jobs SET status='failed', error_message=%s, updated_at=%s WHERE id=%s",
                    ("已被新的任务替代", now_str(), row["id"]),
                )

