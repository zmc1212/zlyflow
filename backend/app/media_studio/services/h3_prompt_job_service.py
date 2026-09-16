from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ...dialogue_timing import resolve_shot_duration_sec
from ..db import execute_sql, now_str, query_all, query_one
from .h3_prompt_builder import H3PromptBuilder
from .llm_service import LlmService


_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="h3-prompt")
_DISPATCH_LOCK = threading.Lock()
_ACTIVE: set[str] = set()
_ACTIVE_LOCK = threading.Lock()


class H3PromptJobService:
    @classmethod
    def enqueue(
        cls,
        project_id: str,
        episode_id: str,
        beat_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .project_detail_service import ProjectDetailService

        req = payload or {}
        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        beats = detail.get("beats") or []
        beat = next((item for item in beats if item.get("id") == beat_id), None)
        if not beat:
            raise ValueError(f"未找到指定分镜: {beat_id}")

        for row in query_all(
            "SELECT id, status, payload_json FROM ai_project_jobs WHERE project_id = %s AND job_type = 'h3_prompt' "
            "AND status IN ('queued','preparing','running') ORDER BY created_at DESC",
            (project_id,),
        ):
            existing = cls._payload(row)
            if existing.get("episode_id") == episode_id and existing.get("beat_id") == beat_id:
                return {"job_id": row["id"], "beat_id": beat_id, "status": row["status"], "duplicate": True}

        assets = ProjectDetailService.list_assets(project_id)
        assets_by_id = {str(item.get("id") or ""): item for item in assets if item.get("id")}
        beat_chars: list[dict[str, Any]] = []
        extra_names: list[str] = []
        for cid in beat.get("character_ids") or []:
            asset = assets_by_id.get(str(cid))
            if not asset:
                continue
            extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
            identities = extra.get("identities") if isinstance(extra.get("identities"), list) else []
            look_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
            selected_look_id = look_ids.get(str(cid)) or beat.get("character_look_id")
            selected_look = next((item for item in identities if item.get("id") == selected_look_id), None)
            look_desc = ""
            if isinstance(selected_look, dict):
                look_desc = selected_look.get("appearance_details") or selected_look.get("description") or selected_look.get("name") or ""
            name = asset.get("name") or "角色"
            extra_names.append(str(name))
            beat_chars.append({
                "id": cid,
                "name": name,
                "desc": extra.get("appearance") or asset.get("description") or "",
                "look_desc": look_desc,
            })

        scene_id = beat.get("scene_id")
        scene_asset = assets_by_id.get(str(scene_id)) if scene_id else None
        if not scene_asset and beat.get("scene"):
            scene_asset = next(
                (item for item in assets if item.get("kind") == "scene" and item.get("name") == beat.get("scene")),
                None,
            )
        scene_name = (scene_asset or {}).get("name") or beat.get("scene") or "场景"
        scene_extra = (scene_asset or {}).get("extra") if isinstance((scene_asset or {}).get("extra"), dict) else {}
        scene_desc = scene_extra.get("environment_prompt") or scene_extra.get("visual_prompt") or (scene_asset or {}).get("description") or ""

        beat_props: list[dict[str, Any]] = []
        for pid in beat.get("prop_ids") or []:
            asset = assets_by_id.get(str(pid))
            if not asset:
                continue
            extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
            beat_props.append({
                "id": pid,
                "name": asset.get("name") or "道具",
                "desc": extra.get("visual_prompt") or extra.get("detail_prompt") or asset.get("description") or "",
            })

        if "ref_images" in req:
            ref_images = req.get("ref_images") or []
        else:
            ref_images = []
            for index, character in enumerate(beat_chars, 1):
                ref_images.append({"index": index, "name": character["name"], "category": "character"})
            if scene_name:
                ref_images.append({"index": len(ref_images) + 1, "name": scene_name, "category": "scene"})
            for prop in beat_props:
                ref_images.append({"index": len(ref_images) + 1, "name": prop["name"], "category": "prop"})

        duration_sec = resolve_shot_duration_sec(beat)
        if str(beat.get("video_duration") or "") != str(duration_sec):
            beat["video_duration"] = str(duration_sec)
            ProjectDetailService._update_episode_beat_atomic(
                project_id,
                episode_id,
                beat_id,
                {"video_duration": str(duration_sec)},
            )

        dialogue_turns = beat.get("dialogue_turns") if isinstance(beat.get("dialogue_turns"), list) else []
        speech_shot = {
            "dialogue": beat.get("dialogue"),
            "speaker": beat.get("speaker"),
            "dialogue_turns": dialogue_turns,
            "narration": beat.get("narration"),
            "characters": extra_names,
        }
        spoken_turns, inner_turns = H3PromptBuilder.split_spoken_and_inner(speech_shot)
        if not spoken_turns:
            spoken_turns = H3PromptBuilder._dialogue_turns(speech_shot)
        narration = str(beat.get("narration") or "").strip()
        inner_text = " ".join(
            str(turn.get("text") or "").strip()
            for turn in inner_turns
            if str(turn.get("text") or "").strip()
        )
        if inner_text and inner_text not in narration:
            narration = f"{narration} {inner_text}".strip() if narration else inner_text

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
            "dialogue_turns": spoken_turns,
            "visible_text": beat.get("visible_text") or "",
            "narration": narration,
            **cls._beat_context_fields(beat),
        }

        seq = beat.get("sequence") or 1
        heading = beat.get("heading") or scene_name or ""
        title = f"生成H3提示词: 第{detail.get('number') or 1}集 镜头{seq}" + (f" · {heading}" if heading else "")
        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        job_payload = {
            "target_type": "h3_prompt",
            "project_id": project_id,
            "episode_id": episode_id,
            "beat_id": beat_id,
            "beat_sequence": seq,
            "beat_heading": heading,
            "beat_info": beat_info,
            "reference_urls": [item.get("url") for item in ref_images if isinstance(item, dict) and item.get("url")],
        }
        execute_sql(
            "INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at) "
            "VALUES (%s,%s,'h3_prompt',%s,'queued',0,NULL,%s,%s,%s)",
            (jid, project_id, title, json.dumps(job_payload, ensure_ascii=False), timestamp, timestamp),
        )
        cls.kick()
        return {"job_id": jid, "beat_id": beat_id, "status": "queued"}

    @classmethod
    def kick(cls) -> None:
        if not _DISPATCH_LOCK.acquire(blocking=False):
            return
        try:
            with _ACTIVE_LOCK:
                capacity = max(0, 4 - len(_ACTIVE))
            if not capacity:
                return
            rows = query_all(
                "SELECT id FROM ai_project_jobs WHERE job_type = 'h3_prompt' AND status = 'queued' "
                "ORDER BY created_at ASC LIMIT 20"
            )
            for row in rows:
                if capacity <= 0:
                    break
                jid = row["id"]
                if execute_sql(
                    "UPDATE ai_project_jobs SET status='preparing',progress=10,updated_at=%s WHERE id=%s AND status='queued'",
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
    def recover_interrupted_jobs(cls) -> None:
        for row in query_all(
            "SELECT id,status FROM ai_project_jobs WHERE job_type='h3_prompt' "
            "AND status IN ('queued','preparing','running')"
        ):
            if row["status"] == "queued":
                continue
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,updated_at=%s WHERE id=%s",
                ("服务重启时提示词任务已中断，请点击重试。", now_str(), row["id"]),
            )
        cls.kick()

    @classmethod
    def retry(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (job_id, project_id))
        payload = cls._payload(row or {})
        if not row or row.get("job_type") != "h3_prompt":
            raise ValueError("H3 提示词任务不存在")
        if row.get("status") not in {"failed", "completed", "succeeded"}:
            raise ValueError("只有失败或已完成的任务可以重试")
        return cls.enqueue(project_id, payload["episode_id"], payload["beat_id"], payload.get("beat_info") or payload)

    @classmethod
    def _run(cls, job_id: str) -> None:
        from .project_detail_service import ProjectDetailService

        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        payload = cls._payload(row)
        try:
            execute_sql(
                "UPDATE ai_project_jobs SET status='running',progress=40,updated_at=%s WHERE id=%s",
                (now_str(), job_id),
            )
            prompt = cls._finalize_prompt(payload, LlmService.generate_h3_prompt(payload.get("beat_info") or {}))
            duration_sec = (payload.get("beat_info") or {}).get("duration_seconds")
            updates = {"h3_prompt": prompt}
            if duration_sec not in (None, ""):
                updates["video_duration"] = str(duration_sec)
            ProjectDetailService._update_episode_beat_atomic(
                payload["project_id"],
                payload["episode_id"],
                payload["beat_id"],
                updates,
            )
            payload["h3_prompt"] = prompt
            execute_sql(
                "UPDATE ai_project_jobs SET status='completed',progress=100,payload_json=%s,error_message=NULL,updated_at=%s WHERE id=%s",
                (json.dumps(payload, ensure_ascii=False), now_str(), job_id),
            )
        except Exception as err:
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,updated_at=%s WHERE id=%s",
                (str(err)[:1000], now_str(), job_id),
            )
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE.discard(job_id)
            cls.kick()

    @classmethod
    def _finalize_prompt(cls, payload: dict[str, Any], prompt: str) -> str:
        shot = cls._beat_info_shot(payload)
        speaker_map = H3PromptBuilder._speaker_map([shot])
        return H3PromptBuilder.prepare_generated_prompt(prompt, shot, speaker_map)

    @staticmethod
    def _beat_info_shot(payload: dict[str, Any]) -> dict[str, Any]:
        beat_info = payload.get("beat_info") if isinstance(payload.get("beat_info"), dict) else {}
        return H3PromptBuilder.shot_from_beat_info(
            beat_info,
            beat_id=str(payload.get("beat_id") or beat_info.get("beat_id") or "beat"),
            sequence=int(payload.get("beat_sequence") or beat_info.get("sequence") or 1),
        )

    @staticmethod
    def _beat_context_fields(beat: dict[str, Any]) -> dict[str, str]:
        return {
            "visual_prompt": str(beat.get("visual_prompt") or "").strip(),
            "audio": str(beat.get("audio") or beat.get("soundscape") or "").strip(),
            "video_prompt_zh": str(beat.get("video_prompt_zh") or "").strip(),
        }

    @staticmethod
    def _payload(row: dict[str, Any]) -> dict[str, Any]:
        raw = row.get("payload_json")
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
