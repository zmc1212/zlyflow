from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ...dialogue_timing import resolve_shot_duration_sec
from ...director_craft.coverage import TAKE_ROLE_LABELS
from ...director_stream import DirectorOperationEventBus, terminal_event_for_status
from ...llm_client import LlmStreamHook
from ..db import execute_sql, now_str, query_all, query_one
from .h3_prompt_builder import H3PromptBuilder
from .llm_service import AUTHOR_DRAFT_LIMIT, DualShotAuthorError, LlmService


_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="h3-prompt")
_DISPATCH_LOCK = threading.Lock()
_ACTIVE: set[str] = set()
_ACTIVE_LOCK = threading.Lock()
_EVENTS = DirectorOperationEventBus()
_STREAM_LOCK = threading.Lock()
_STREAM_STATE: dict[str, dict[str, Any]] = {}
_STREAM_FLUSH_AT: dict[str, float] = {}
_STREAM_FLUSH_INTERVAL = 0.45


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
            look_url = ""
            if isinstance(selected_look, dict):
                look_url = str(selected_look.get("image_url") or "").strip()
            name = asset.get("name") or "角色"
            extra_names.append(str(name))
            beat_chars.append({
                "id": cid,
                "name": name,
                "url": look_url,
            })

        scene_id = beat.get("scene_id")
        scene_asset = assets_by_id.get(str(scene_id)) if scene_id else None
        if not scene_asset and beat.get("scene"):
            scene_asset = next(
                (item for item in assets if item.get("kind") == "scene" and item.get("name") == beat.get("scene")),
                None,
            )
        scene_name = (scene_asset or {}).get("name") or beat.get("scene") or "场景"
        scene_url = ""
        if isinstance(scene_asset, dict):
            extra = scene_asset.get("extra") if isinstance(scene_asset.get("extra"), dict) else {}
            scene_url = str(
                extra.get("master_url")
                or extra.get("image_url")
                or scene_asset.get("image_url")
                or ""
            ).strip()

        beat_props: list[dict[str, Any]] = []
        for pid in beat.get("prop_ids") or []:
            asset = assets_by_id.get(str(pid))
            if not asset:
                continue
            beat_props.append({
                "id": pid,
                "name": asset.get("name") or "道具",
            })

        from ...skill_packs import resolve_skill_pack_id
        from ...skill_packs.handlers import bind_r2v_slot_images
        from ...skill_packs.recipe import get_pack

        pack_id = resolve_skill_pack_id(payload=req, beat=beat, project_id=project_id)
        recipe = get_pack(pack_id)
        bind_beat = {
            **beat,
            "character_ids": [],
            "characters": beat_chars,
            "scene": scene_name,
            "scene_id": str(scene_id or beat.get("scene_id") or ""),
        }
        if not recipe.is_default and recipe.r2v_slots:
            ref_images = bind_r2v_slot_images(recipe, bind_beat, assets)
        elif "ref_images" in req:
            ref_images = req.get("ref_images") or []
        else:
            ref_images = []
            for index, character in enumerate(beat_chars, 1):
                ref_images.append({
                    "index": index,
                    "name": character["name"],
                    "category": "character",
                    "character_id": character.get("id") or "",
                    "url": character.get("url") or "",
                })
            if scene_name:
                ref_images.append({
                    "index": len(ref_images) + 1,
                    "name": scene_name,
                    "category": "scene",
                    "url": scene_url,
                })
            for prop in beat_props:
                ref_images.append({
                    "index": len(ref_images) + 1,
                    "name": prop["name"],
                    "category": "prop",
                    "prop_id": prop.get("id") or "",
                })
        full_triptych = str(beat.get("triptych_url") or "").strip()
        if full_triptych:
            cleaned = []
            for item in ref_images:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if url == full_triptych and item.get("source") != "triptych.start" and item.get("role") != "start":
                    continue
                cleaned.append(item)
            ref_images = cleaned

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

        from ...skill_packs import resolve_skill_pack_id

        pack_id = resolve_skill_pack_id(payload=req, beat=beat, project_id=project_id)
        beat_info = H3PromptBuilder.sanitize_beat_draft({
            "sequence": beat.get("sequence") or 1,
            "heading": beat.get("heading") or "",
            "action": beat.get("action") or "",
            "camera": beat.get("camera") or "",
            "take_role": beat.get("take_role") or "",
            "dialogue": beat.get("dialogue") or "",
            "speaker": beat.get("speaker") or "",
            "duration_seconds": duration_sec,
            "time_of_day": beat.get("time_of_day") or "日间",
            "scene_name": scene_name,
            "scene": scene_name,
            "scene_id": scene_id or "",
            "character_ids": list(beat.get("character_ids") or []),
            "characters": beat_chars,
            "props": beat_props,
            "ref_images": ref_images,
            "ref_videos": req.get("ref_videos") or [],
            "dialogue_turns": spoken_turns,
            "visible_text": beat.get("visible_text") or "",
            "narration": narration,
            "triptych_url": beat.get("triptych_url") or "",
            "triptych_panels": beat.get("triptych_panels") or {},
            "timestamped_zh_prompt": beat.get("timestamped_zh_prompt") or "",
            "skill_pack_id": pack_id,
            "project_id": project_id,
            "episode_id": episode_id,
            "beat_id": beat_id,
            **cls._beat_context_fields(beat),
        })

        seq = beat.get("sequence") or 1
        story_shot = beat.get("story_shot") or seq
        heading = beat.get("heading") or scene_name or ""
        role_label = TAKE_ROLE_LABELS.get(str(beat.get("take_role") or "").strip(), "")
        title = f"生成H3提示词: 第{detail.get('number') or 1}集 镜头{story_shot}"
        if role_label:
            title += f" · {role_label}"
        if heading:
            title += f" · {heading}"
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
    def bind_loop(cls) -> None:
        try:
            _EVENTS.bind_loop()
        except RuntimeError:
            pass

    @classmethod
    async def stream(cls, job_id: str, project_id: str, request: Any, since: int = 0):
        cls.bind_loop()
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (job_id, project_id)) or {}
        if not row or row.get("job_type") != "h3_prompt":
            raise ValueError("H3 提示词任务不存在")
        queue, replay = _EVENTS.subscribe(job_id, since=max(0, since))
        try:
            if not replay:
                snapshot = cls._public_stream_snapshot(row)
                if snapshot:
                    yield snapshot
                    if snapshot.get("terminal"):
                        return
            for event in replay:
                yield event
                if event.get("terminal"):
                    return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    current = query_one(
                        "SELECT status,error_message,payload_json FROM ai_project_jobs WHERE id=%s AND project_id=%s",
                        (job_id, project_id),
                    ) or {}
                    status = str(current.get("status") or "")
                    if status in {"completed", "succeeded", "failed"}:
                        yield cls._terminal_from_row(current)
                        return
                    yield {"event": "keep-alive", "data": {}}
                    continue
                if event is None:
                    return
                yield event
                if event.get("terminal"):
                    return
        finally:
            _EVENTS.unsubscribe(job_id, queue)

    @classmethod
    def _public_stream_snapshot(cls, row: dict[str, Any]) -> dict[str, Any] | None:
        payload = cls._payload(row)
        stream = payload.get("stream") if isinstance(payload.get("stream"), dict) else {}
        status = str(row.get("status") or "")
        if status in {"completed", "succeeded"}:
            return cls._terminal_from_row(row)
        if status == "failed":
            return cls._terminal_from_row(row)
        if not stream and status not in {"queued", "preparing", "running"}:
            return None
        return {
            "event": "status",
            "data": {
                "phase": stream.get("phase") or "write",
                "message": stream.get("message") or "正在生成提示词",
                "reset": False,
                "reasoning": stream.get("reasoning") or "",
                "text": stream.get("text") or "",
            },
        }

    @classmethod
    def _terminal_from_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        payload = cls._payload(row)
        status = str(row.get("status") or "")
        if status == "failed":
            return terminal_event_for_status("failed", message=str(row.get("error_message") or "生成失败"))
        prompt = str(payload.get("h3_prompt") or payload.get("result_prompt") or "").strip()
        return {
            "event": "done",
            "terminal": True,
            "data": {"status": "succeeded", "prompt": prompt},
        }

    @classmethod
    def _emit(cls, job_id: str, event: dict[str, Any]) -> None:
        _EVENTS.emit(job_id, event)

    @classmethod
    def _patch_stream(cls, job_id: str, updates: dict[str, Any], *, force: bool = False) -> None:
        with _STREAM_LOCK:
            state = _STREAM_STATE.setdefault(job_id, {
                "phase": "write",
                "message": "正在生成提示词",
                "reasoning": "",
                "text": "",
            })
            if updates.get("reset"):
                state["reasoning"] = ""
                state["text"] = ""
            for key in ("phase", "message", "reasoning", "text"):
                if key in updates and updates[key] is not None:
                    state[key] = updates[key]
            now = time.monotonic()
            last = _STREAM_FLUSH_AT.get(job_id) or 0.0
            if not force and now - last < _STREAM_FLUSH_INTERVAL:
                return
            _STREAM_FLUSH_AT[job_id] = now
            snapshot = dict(state)
        row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        payload = cls._payload(row)
        payload["stream"] = snapshot
        execute_sql(
            "UPDATE ai_project_jobs SET payload_json=%s,updated_at=%s WHERE id=%s",
            (json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )

    @classmethod
    def _clear_stream_state(cls, job_id: str) -> None:
        with _STREAM_LOCK:
            _STREAM_STATE.pop(job_id, None)
            _STREAM_FLUSH_AT.pop(job_id, None)

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
            cls._emit(job_id, {"event": "status", "data": {"phase": "write", "message": "正在生成提示词", "reset": False}})
            cls._patch_stream(job_id, {"phase": "write", "message": "正在生成提示词"}, force=True)

            def on_delta(kind: str, piece: str) -> None:
                with _STREAM_LOCK:
                    state = _STREAM_STATE.setdefault(job_id, {
                        "phase": "write",
                        "message": "正在生成提示词",
                        "reasoning": "",
                        "text": "",
                    })
                    if kind == "reasoning":
                        state["reasoning"] = str(state.get("reasoning") or "") + piece
                        snapshot = str(state["reasoning"])
                        event_name = "reasoning"
                    else:
                        state["text"] = str(state.get("text") or "") + piece
                        snapshot = str(state["text"])
                        event_name = "delta"
                cls._emit(job_id, {"event": event_name, "data": {"text": snapshot}})
                cls._patch_stream(job_id, {})

            def on_status(info: dict[str, Any]) -> None:
                phase = str(info.get("phase") or "write")
                message = str(info.get("message") or "正在生成提示词")
                reset = bool(info.get("reset"))
                cls._emit(job_id, {"event": "status", "data": {"phase": phase, "message": message, "reset": reset}})
                cls._patch_stream(job_id, {"phase": phase, "message": message, "reset": reset}, force=True)

            with LlmStreamHook(on_delta=on_delta, on_status=on_status):
                prompt = cls._finalize_prompt(payload, LlmService.generate_h3_prompt(payload.get("beat_info") or {}))
            duration_sec = (payload.get("beat_info") or {}).get("duration_seconds")
            updates = {"h3_prompt": prompt, "h3_prompt_source": "generated"}
            if duration_sec not in (None, ""):
                updates["video_duration"] = str(duration_sec)
            beat_info = payload.get("beat_info") if isinstance(payload.get("beat_info"), dict) else {}
            zh_prompt = str(beat_info.get("timestamped_zh_prompt") or "").strip()
            if zh_prompt:
                updates["timestamped_zh_prompt"] = zh_prompt
                if not str(beat_info.get("video_prompt_zh") or "").strip():
                    updates["video_prompt_zh"] = zh_prompt
            for key in ("vision_status", "vision_model", "vision_image_count", "vision_source", "authored_en_valid"):
                if beat_info.get(key) not in (None, ""):
                    updates[key] = beat_info[key]
                    payload[key] = beat_info[key]
            ProjectDetailService._update_episode_beat_atomic(
                payload["project_id"],
                payload["episode_id"],
                payload["beat_id"],
                updates,
            )
            payload["h3_prompt"] = prompt
            payload.pop("stream", None)
            execute_sql(
                "UPDATE ai_project_jobs SET status='completed',progress=100,payload_json=%s,error_message=NULL,updated_at=%s WHERE id=%s",
                (json.dumps(payload, ensure_ascii=False), now_str(), job_id),
            )
            cls._emit(job_id, {"event": "done", "terminal": True, "data": {"status": "succeeded", "prompt": prompt}})
        except Exception as err:
            latest = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
            failed_payload = cls._attach_failure_payload(cls._payload(latest) or payload, err)
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,payload_json=%s,updated_at=%s WHERE id=%s",
                (str(err)[:1000], json.dumps(failed_payload, ensure_ascii=False), now_str(), job_id),
            )
            cls._emit(job_id, terminal_event_for_status("failed", message=str(err)[:1000]))
        finally:
            cls._clear_stream_state(job_id)
            with _ACTIVE_LOCK:
                _ACTIVE.discard(job_id)
            cls.kick()

    @classmethod
    def _attach_failure_payload(cls, payload: dict[str, Any], err: BaseException) -> dict[str, Any]:
        failed = dict(payload or {})
        beat_info = failed.get("beat_info") if isinstance(failed.get("beat_info"), dict) else {}
        if isinstance(err, DualShotAuthorError):
            failed.update(err.payload_fields(limit=AUTHOR_DRAFT_LIMIT))
        else:
            message = str(err).strip()
            failed["author_errors"] = [message] if message else ["生成失败"]
            zh_draft = str(beat_info.get("timestamped_zh_prompt") or failed.get("author_zh_draft") or "")
            en_draft = str(beat_info.get("authored_en_prompt") or failed.get("author_en_draft") or "")
            if zh_draft:
                failed["author_zh_draft"] = zh_draft[:AUTHOR_DRAFT_LIMIT]
            if en_draft:
                failed["author_en_draft"] = en_draft[:AUTHOR_DRAFT_LIMIT]
        for key in ("vision_status", "vision_model", "vision_image_count", "vision_source"):
            if failed.get(key) not in (None, ""):
                continue
            value = beat_info.get(key)
            if value not in (None, ""):
                failed[key] = value
        if not failed.get("author_errors"):
            failed["author_errors"] = [str(err)]
        return failed

    @classmethod
    def _finalize_prompt(cls, payload: dict[str, Any], prompt: str) -> str:
        from ...skill_packs import skip_program_pack_enabled

        beat_info = payload.get("beat_info") if isinstance(payload.get("beat_info"), dict) else {}
        pack_id = str(beat_info.get("skill_pack_id") or payload.get("skill_pack_id") or "").strip()
        if skip_program_pack_enabled(pack_id):
            return H3PromptBuilder.canonicalize_reference_tags(prompt)
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
            "video_prompt_zh": str(beat.get("video_prompt_zh") or beat.get("timestamped_zh_prompt") or "").strip(),
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
