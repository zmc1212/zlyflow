from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from ...dialogue_timing import resolve_shot_duration_sec
from ...director_stream import DirectorOperationEventBus, terminal_event_for_status
from ...llm_client import LlmStreamHook
from ...workflow_registry import WorkflowDefinition, workflow_for
from ..db import execute_sql, now_str, query_all, query_one, transaction_cursor
from .llm_service import LlmService
from .prompt_templates import (
    DIRECTOR_TEMPLATE_VERSION,
    DIRECTOR_UNIT_PLANNER_VERSION,
    FULL_REFERENCE_TEMPLATE_VERSION,
    PromptTemplateError,
    build_director_prompts,
    build_director_unit_planning_prompts,
    build_full_reference_prompts,
    normalize_language,
    parse_director_output,
    parse_director_unit_plan,
    parse_full_reference,
)


JOB_TYPE = "prompt_expansion"
_FPS = 24
_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="prompt-expansion")
_DISPATCH_LOCK = threading.Lock()
_ACTIVE: set[str] = set()
_ACTIVE_LOCK = threading.Lock()
_EVENTS = DirectorOperationEventBus()
_STREAM_LOCK = threading.Lock()
_STREAM_STATE: dict[str, dict[str, Any]] = {}
_STREAM_FLUSH_AT: dict[str, float] = {}
_STREAM_FLUSH_INTERVAL = 0.45
_DIRECTOR_PLAN_SCHEMA_VERSION = 2
_DIRECTOR_REPLAY_TERMS = (
    "再次", "重新", "回响", "时间回响", "感知回响", "回放", "倒放", "重演", "重新醒来", "再次醒来", "再次说", "再次重复",
    "time echo", "sensory echo", "replay", "rewind", "relive", "again wakes", "repeat the dialogue",
)


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("payload_json")
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _shot_number(value: Any, fallback: int) -> int:
    match = re.search(r"\d+", _clean(value))
    return int(match.group(0)) if match else fallback


class PromptExpansionService:
    """Preview-first Prompt Master authoring for the director workshop."""

    @classmethod
    def enqueue(cls, project_id: str, episode_id: str, request: dict[str, Any] | None = None) -> dict[str, Any]:
        req = dict(request or {})
        source = cls._load_source(project_id, episode_id)
        workflow_id = _clean(req.get("workflow_id"))
        if not workflow_id:
            raise ValueError("请选择视频工作流")
        definition = workflow_for(workflow_id)
        profile = str(definition.prompt_profile or "none")
        target = req.get("target") if isinstance(req.get("target"), dict) else {}
        target_kind = _clean(target.get("kind"))
        if profile == "full_reference" and target_kind != "beat":
            raise ValueError("当前工作流只能针对单个分镜生成六段式提示词")
        if profile == "director_segments" and target_kind != "director_episode":
            raise ValueError("当前 Director 工作流必须生成整集 Director 出片方案")
        if profile not in {"full_reference", "director_segments"}:
            raise ValueError("当前工作流未启用 H3 提示词模板")

        beat_id = _clean(target.get("beat_id"))
        if target_kind == "beat" and not any(_clean(item.get("id")) == beat_id for item in source["beats"]):
            raise ValueError("分镜不存在")
        language = normalize_language(req.get("language"))
        rewrite_mode = _clean(req.get("rewrite_mode")) or ("strict" if profile == "full_reference" else "expand")
        if rewrite_mode not in {"strict", "expand"}:
            raise ValueError("改写模式必须是 strict 或 expand")
        aspect_ratio = _clean(req.get("aspect_ratio")) or "16:9"
        slots = cls._normalize_reference_slots(
            req.get("reference_slots"), source["assets"], definition,
            target_kind=target_kind, beat_id=beat_id, beats=source["beats"],
        )
        target_segment_count = None
        planned_parts: list[dict[str, Any]] = []
        if profile == "director_segments":
            raw_count = req.get("target_segment_count")
            target_segment_count = int(raw_count) if raw_count not in (None, "") else None
            planned_parts = cls.plan_director_parts(source["beats"], definition, target_segment_count)
            target_segment_count = sum(len(item["segments"]) for item in planned_parts)

        normalized_request = {
            "workflow_id": workflow_id,
            "prompt_profile": profile,
            "template_version": FULL_REFERENCE_TEMPLATE_VERSION if profile == "full_reference" else DIRECTOR_TEMPLATE_VERSION,
            "target": {"kind": target_kind, **({"beat_id": beat_id} if beat_id else {})},
            "language": language,
            "rewrite_mode": rewrite_mode,
            "aspect_ratio": aspect_ratio,
            "target_segment_count": target_segment_count,
            "reference_slots": slots,
        }
        fingerprint = cls.source_fingerprint(source, normalized_request)
        for row in query_all(
            "SELECT id,status,payload_json FROM ai_project_jobs WHERE project_id=%s AND job_type=%s "
            "AND status IN ('queued','preparing','running') ORDER BY created_at DESC",
            (project_id, JOB_TYPE),
        ):
            existing = _payload(row)
            if existing.get("episode_id") == episode_id and existing.get("source_fingerprint") == fingerprint:
                return {"job_id": row["id"], "status": row["status"], "duplicate": True}

        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        title_prefix = "六段式提示词预览" if profile == "full_reference" else "Director 出片方案预览"
        job_payload = {
            "target_type": "prompt_preview",
            "project_id": project_id,
            "episode_id": episode_id,
            "beat_id": beat_id or None,
            "prompt_profile": profile,
            "template_version": normalized_request["template_version"],
            "source_fingerprint": fingerprint,
            "reference_urls": [item["image_url"] for item in slots if item.get("image_url")],
            "request": normalized_request,
            "source_snapshot": cls._source_snapshot(source, target_kind, beat_id),
            "planned_parts": planned_parts,
        }
        execute_sql(
            "INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,'queued',0,NULL,%s,%s,%s)",
            (
                jid, project_id, JOB_TYPE,
                f"{title_prefix} · {source['episode'].get('title') or episode_id}",
                json.dumps(job_payload, ensure_ascii=False), timestamp, timestamp,
            ),
        )
        cls.kick()
        return {
            "job_id": jid,
            "status": "queued",
            "source_fingerprint": fingerprint,
            "prompt_profile": profile,
            "recommended_segment_count": target_segment_count,
        }

    @classmethod
    def _load_source(cls, project_id: str, episode_id: str) -> dict[str, Any]:
        from .project_detail_service import ProjectDetailService

        row = query_one("SELECT * FROM ai_project_episodes WHERE id=%s AND project_id=%s", (episode_id, project_id))
        if not row:
            raise ValueError("分集不存在")
        data = _json_dict(row.get("data_json"))
        beats = data.get("beats") if isinstance(data.get("beats"), list) else []
        if not beats:
            detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
            row = query_one("SELECT * FROM ai_project_episodes WHERE id=%s AND project_id=%s", (episode_id, project_id)) or row
            data = _json_dict(row.get("data_json"))
            beats = detail.get("beats") if isinstance(detail.get("beats"), list) else []
        return {
            "episode": dict(row),
            "data": data,
            "beats": beats,
            "assets": ProjectDetailService.list_assets(project_id),
        }

    @staticmethod
    def _asset_image_url(asset: dict[str, Any], look_id: str = "") -> str:
        extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else _json_dict(asset.get("extra_json"))
        if look_id:
            for look in (extra.get("identities") or extra.get("looks") or []):
                if isinstance(look, dict) and _clean(look.get("id")) == look_id:
                    return _clean(look.get("image_url") or look.get("url"))
        return _clean(
            extra.get("master_url") or extra.get("reference_url") or extra.get("image_url")
            or extra.get("avatar_url") or asset.get("image_url")
        )

    @classmethod
    def _default_asset_order(
        cls,
        assets: list[dict[str, Any]],
        *,
        target_kind: str,
        beat_id: str,
        beats: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        target_beats = beats if target_kind == "director_episode" else [
            item for item in beats if _clean(item.get("id")) == beat_id
        ]
        linked: list[str] = []
        for beat in target_beats:
            linked.extend(_clean(value) for value in beat.get("character_ids") or [])
            if beat.get("scene_id"):
                linked.append(_clean(beat.get("scene_id")))
            linked.extend(_clean(value) for value in beat.get("prop_ids") or [])
        linked_rank = {value: idx for idx, value in enumerate(dict.fromkeys(value for value in linked if value))}
        kind_rank = {"character": 0, "scene": 1, "prop": 2}
        return sorted(
            assets,
            key=lambda item: (
                0 if _clean(item.get("id")) in linked_rank else 1,
                linked_rank.get(_clean(item.get("id")), 9999),
                kind_rank.get(_clean(item.get("kind")), 9),
                _clean(item.get("name")),
            ),
        )

    @classmethod
    def _normalize_reference_slots(
        cls,
        raw_slots: Any,
        assets: list[dict[str, Any]],
        definition: WorkflowDefinition,
        *,
        target_kind: str,
        beat_id: str,
        beats: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        assets_by_id = {_clean(item.get("id")): item for item in assets if item.get("id")}
        candidates = raw_slots if isinstance(raw_slots, list) else []
        if not candidates:
            candidates = [
                {"asset_id": item.get("id")}
                for item in cls._default_asset_order(
                    assets, target_kind=target_kind, beat_id=beat_id, beats=beats,
                )
                if cls._asset_image_url(item)
            ][: int(definition.max_references or 0)]
        if len(candidates) > int(definition.max_references or 0):
            raise ValueError(f"参考图最多允许 {definition.max_references} 张")
        slots: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for idx, item in enumerate(candidates, start=1):
            if not isinstance(item, dict):
                raise ValueError("参考图槽位格式无效")
            asset_id = _clean(item.get("asset_id"))
            look_id = _clean(item.get("look_id"))
            asset = assets_by_id.get(asset_id)
            if not asset:
                raise ValueError(f"参考资产不存在或不属于当前项目：{asset_id}")
            if (asset_id, look_id) in seen:
                raise ValueError("同一个参考资产造型不能重复绑定")
            seen.add((asset_id, look_id))
            image_url = cls._asset_image_url(asset, look_id)
            if not image_url:
                raise ValueError(f"资产“{asset.get('name') or asset_id}”没有可用参考图")
            token = _clean(item.get("token")) or f"<Picture {idx}>"
            if token.lower() not in {f"<picture {idx}>", f"<subject {idx}>"}:
                raise ValueError("参考槽位 token 必须与当前排序序号一致")
            slots.append({
                "index": idx,
                "token": token,
                "asset_id": asset_id,
                "look_id": look_id or None,
                "image_url": image_url,
                "kind": _clean(asset.get("kind")) or "asset",
                "name": _clean(item.get("name") or asset.get("name")) or f"参考图 {idx}",
            })
        if len(slots) < int(definition.min_references or 0):
            raise ValueError(f"当前工作流至少需要 {definition.min_references} 张参考图")
        return slots

    @staticmethod
    def _source_snapshot(source: dict[str, Any], target_kind: str, beat_id: str) -> dict[str, Any]:
        episode = source["episode"]
        selected = source["beats"] if target_kind == "director_episode" else [
            item for item in source["beats"] if _clean(item.get("id")) == beat_id
        ]
        beat_fields = (
            "id", "sequence", "story_shot", "heading", "scene", "action", "camera", "dialogue",
            "speaker", "visual_prompt", "audio", "video_duration", "character_ids", "scene_id", "prop_ids",
        )
        return {
            "episode": {"id": episode.get("id"), "title": episode.get("title"), "script_text": episode.get("script_text") or ""},
            "beats": [{key: beat.get(key) for key in beat_fields} for beat in selected],
            "assets": [
                {
                    "id": item.get("id"), "kind": item.get("kind"), "name": item.get("name"),
                    "description": item.get("description"), "visual_prompt": item.get("visual_prompt"),
                    "image_url": item.get("image_url"), "extra": item.get("extra") or _json_dict(item.get("extra_json")),
                }
                for item in source["assets"]
            ],
        }

    @classmethod
    def source_fingerprint(cls, source: dict[str, Any], request: dict[str, Any]) -> str:
        target = request.get("target") if isinstance(request.get("target"), dict) else {}
        body = {
            "template_version": request.get("template_version"), "workflow_id": request.get("workflow_id"),
            "language": request.get("language"), "rewrite_mode": request.get("rewrite_mode"),
            "aspect_ratio": request.get("aspect_ratio"), "target_segment_count": request.get("target_segment_count"),
            "reference_slots": request.get("reference_slots") or [],
            "source": cls._source_snapshot(source, _clean(target.get("kind")), _clean(target.get("beat_id"))),
        }
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def recommended_segment_count(cls, beats: list[dict[str, Any]], definition: WorkflowDefinition) -> int:
        max_segments = int(definition.max_segments or 6)
        max_frames = int(definition.max_total_frames or 1152)
        preferred = max(1, max_frames // max_segments)
        total_frames = sum(max(1, round(resolve_shot_duration_sec(item) * _FPS)) for item in beats) or preferred * 2
        return max(2, math.ceil(total_frames / preferred))

    @classmethod
    def plan_director_parts(
        cls,
        beats: list[dict[str, Any]],
        definition: WorkflowDefinition,
        requested_count: int | None,
    ) -> list[dict[str, Any]]:
        if not beats:
            raise ValueError("当前分集没有可用于连续剧情的分镜")
        max_segments = int(definition.max_segments or 6)
        max_frames = int(definition.max_total_frames or 1152)
        preferred = max(1, max_frames // max_segments)
        total_frames = sum(max(1, round(resolve_shot_duration_sec(item) * _FPS)) for item in beats)
        count = int(requested_count or cls.recommended_segment_count(beats, definition))
        if count < 2:
            raise ValueError("Director 方案至少需要 2 段")
        part_count = max(math.ceil(count / max_segments), math.ceil(total_frames / max_frames), 1)
        count = max(count, part_count * 2)
        part_count = max(part_count, math.ceil(count / max_segments))

        units: list[dict[str, Any]] = []
        generated_shot_number = 1
        for seq, beat in enumerate(beats, start=1):
            frames = max(1, round(resolve_shot_duration_sec(beat) * _FPS))
            split_count = max(1, math.ceil(frames / preferred))
            base, remainder = divmod(frames, split_count)
            start_frame = 0
            source_shot_number = _shot_number(beat.get("story_shot") or beat.get("sequence"), seq)
            for chunk in range(split_count):
                chunk_frames = base + (1 if chunk < remainder else 0)
                units.append({
                    "id": f"unit-{seq}-{chunk + 1}",
                    "source_beat_id": _clean(beat.get("id")),
                    "source_shot_number": source_shot_number,
                    "generated_shot_number": generated_shot_number,
                    "chunk_index": chunk,
                    "chunk_count": split_count,
                    "start_frame": start_frame,
                    "end_frame": start_frame + chunk_frames,
                    "frames": chunk_frames,
                })
                generated_shot_number += 1
                start_frame += chunk_frames
        while len(units) < count:
            pos = max(range(len(units)), key=lambda index: units[index]["frames"])
            item = units[pos]
            if item["frames"] < 2:
                raise ValueError("Director 目标段数超过可安全拆分的动作单元数量")
            left = max(1, item["frames"] // 2)
            right = item["frames"] - left
            units[pos:pos + 1] = [
                {
                    **item,
                    "id": f"{item['id']}-a",
                    "end_frame": item["start_frame"] + left,
                    "frames": left,
                },
                {
                    **item,
                    "id": f"{item['id']}-b",
                    "start_frame": item["start_frame"] + left,
                    "end_frame": item["end_frame"],
                    "frames": right,
                },
            ]

        by_beat: dict[str, list[dict[str, Any]]] = {}
        for generated_number, item in enumerate(units, start=1):
            item["generated_shot_number"] = generated_number
            by_beat.setdefault(item["source_beat_id"], []).append(item)
        for beat_units in by_beat.values():
            beat_units.sort(key=lambda item: (item["start_frame"], item["end_frame"], item["id"]))
            for chunk_index, item in enumerate(beat_units):
                item["chunk_index"] = chunk_index
                item["chunk_count"] = len(beat_units)
                item["unit_id"] = item["id"]

        segment_units: list[list[dict[str, Any]]] = []
        offset = 0
        remaining_frames = sum(item["frames"] for item in units)
        for segment_index in range(count):
            remaining_segments = count - segment_index
            remaining_units = len(units) - offset
            take = 1
            target_frames = remaining_frames / remaining_segments
            current = units[offset]["frames"]
            while take < remaining_units - (remaining_segments - 1):
                next_frames = units[offset + take]["frames"]
                if current + next_frames > target_frames:
                    break
                current += next_frames
                take += 1
            selected = units[offset:offset + take]
            segment_units.append(selected)
            remaining_frames -= sum(item["frames"] for item in selected)
            offset += take

        base_count, remainder = divmod(count, part_count)
        part_counts = [base_count + (1 if index < remainder else 0) for index in range(part_count)]
        if any(value < 2 or value > max_segments for value in part_counts):
            raise ValueError("无法在当前工作流能力内生成合法的 Director Part")
        parts: list[dict[str, Any]] = []
        cursor = 0
        for part_index, segment_count in enumerate(part_counts, start=1):
            segments = []
            for local_index in range(segment_count):
                selected = segment_units[cursor]
                frame_count = sum(item["frames"] for item in selected)
                source_ids = list(dict.fromkeys(item["source_beat_id"] for item in selected if item.get("source_beat_id")))
                source_units = []
                for item in selected:
                    source_units.append({
                        "id": item["id"],
                        "source_beat_id": item["source_beat_id"],
                        "source_shot_number": item["source_shot_number"],
                        "generated_shot_number": item["generated_shot_number"],
                        "chunk_index": item["chunk_index"],
                        "chunk_count": item["chunk_count"],
                        "start_sec": round(item["start_frame"] / _FPS, 3),
                        "end_sec": round(item["end_frame"] / _FPS, 3),
                        "duration_seconds": round(item["frames"] / _FPS, 3),
                        "required_events": [],
                        "dialogue_owner": [],
                        "start_state": "",
                        "handoff_state": "",
                    })
                segments.append({
                    "id": f"segment-{uuid.uuid4().hex[:12]}", "index": local_index + 1,
                    "title": f"Part {part_index} · 段 {local_index + 1}", "frame_count": frame_count,
                    "duration_seconds": round(frame_count / _FPS, 3), "source_beat_ids": source_ids,
                    "source_units": source_units,
                })
                cursor += 1
            frame_count = sum(item["frame_count"] for item in segments)
            if frame_count > max_frames:
                raise ValueError("建议段数过少，单个 Director Part 超过工作流总帧上限")
            parts.append({
                "id": f"part-{uuid.uuid4().hex[:12]}", "index": part_index,
                "frame_count": frame_count, "segments": segments,
            })
        return parts

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
        if not row or row.get("job_type") != JOB_TYPE:
            raise ValueError("提示词预览任务不存在")
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
                    if current.get("status") in {"completed", "succeeded", "failed"}:
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
    def _public_stream_snapshot(cls, row: dict[str, Any]) -> dict[str, Any]:
        if row.get("status") in {"completed", "succeeded", "failed"}:
            return cls._terminal_from_row(row)
        stream = _payload(row).get("stream")
        stream = stream if isinstance(stream, dict) else {}
        return {
            "event": "status",
            "data": {
                "phase": stream.get("phase") or "write",
                "message": stream.get("message") or "正在生成提示词预览",
                "reset": False,
                "reasoning": stream.get("reasoning") or "",
                "text": stream.get("text") or "",
            },
        }

    @staticmethod
    def _terminal_from_row(row: dict[str, Any]) -> dict[str, Any]:
        if row.get("status") == "failed":
            return terminal_event_for_status("failed", message=_clean(row.get("error_message")) or "生成失败")
        return {
            "event": "done", "terminal": True,
            "data": {"status": "succeeded", "preview": _payload(row).get("preview")},
        }

    @classmethod
    def _patch_stream(cls, job_id: str, updates: dict[str, Any], *, force: bool = False) -> None:
        with _STREAM_LOCK:
            state = _STREAM_STATE.setdefault(
                job_id,
                {"phase": "write", "message": "正在生成提示词预览", "reasoning": "", "text": ""},
            )
            if updates.get("reset"):
                state["reasoning"] = ""
                state["text"] = ""
            for key in ("phase", "message", "reasoning", "text"):
                if key in updates and updates[key] is not None:
                    state[key] = updates[key]
            current_time = time.monotonic()
            if not force and current_time - (_STREAM_FLUSH_AT.get(job_id) or 0.0) < _STREAM_FLUSH_INTERVAL:
                return
            _STREAM_FLUSH_AT[job_id] = current_time
            snapshot = dict(state)
        row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        payload = _payload(row)
        payload["stream"] = snapshot
        execute_sql(
            "UPDATE ai_project_jobs SET payload_json=%s,updated_at=%s WHERE id=%s",
            (json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )

    @classmethod
    def kick(cls) -> None:
        if not _DISPATCH_LOCK.acquire(blocking=False):
            return
        try:
            with _ACTIVE_LOCK:
                capacity = max(0, 3 - len(_ACTIVE))
            if not capacity:
                return
            rows = query_all(
                "SELECT id FROM ai_project_jobs WHERE job_type=%s AND status='queued' ORDER BY created_at ASC LIMIT 20",
                (JOB_TYPE,),
            )
            for row in rows:
                if capacity <= 0:
                    break
                job_id = row["id"]
                if execute_sql(
                    "UPDATE ai_project_jobs SET status='preparing',progress=10,updated_at=%s WHERE id=%s AND status='queued'",
                    (now_str(), job_id),
                ) != 1:
                    continue
                with _ACTIVE_LOCK:
                    _ACTIVE.add(job_id)
                _EXECUTOR.submit(cls._run, job_id)
                capacity -= 1
        finally:
            _DISPATCH_LOCK.release()

    @classmethod
    def recover_interrupted_jobs(cls) -> None:
        for row in query_all(
            "SELECT id,status FROM ai_project_jobs WHERE job_type=%s AND status IN ('queued','preparing','running')",
            (JOB_TYPE,),
        ):
            if row.get("status") == "queued":
                continue
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,updated_at=%s WHERE id=%s",
                ("服务重启时提示词预览任务已中断，请重试。", now_str(), row["id"]),
            )
        cls.kick()

    @classmethod
    def retry(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (job_id, project_id)) or {}
        if not row or row.get("job_type") != JOB_TYPE:
            raise ValueError("提示词预览任务不存在")
        if row.get("status") not in {"failed", "completed", "succeeded"}:
            raise ValueError("只有失败或已完成的任务可以重试")
        payload = _payload(row)
        return cls.enqueue(project_id, payload["episode_id"], payload.get("request") or {})

    @classmethod
    def _generate_with_one_retry(
        cls,
        system_prompt: str,
        user_prompt: str,
        parser: Callable[[str], dict[str, Any]],
        retry_instruction: str = "仍使用同一模板完整重写一次；不要解释错误。",
    ) -> tuple[dict[str, Any], str, bool]:
        first = LlmService.chat_text(system_prompt, user_prompt, max_tokens=16000, temperature=0.25, timeout=300)
        try:
            return parser(first), first, False
        except PromptTemplateError as err:
            retry_user = (
                f"{user_prompt}\n\n上一次输出未通过结构校验：{err}\n"
                f"{retry_instruction}\n不要解释错误。\n\n上一次输出：\n"
                f"{first}"
            )
            second = LlmService.chat_text(system_prompt, retry_user, max_tokens=16000, temperature=0.2, timeout=300)
            return parser(second), second, True

    @classmethod
    def _run(cls, job_id: str) -> None:
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        payload = _payload(row)
        try:
            execute_sql(
                "UPDATE ai_project_jobs SET status='running',progress=30,updated_at=%s WHERE id=%s",
                (now_str(), job_id),
            )
            request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
            source = payload.get("source_snapshot") if isinstance(payload.get("source_snapshot"), dict) else {}

            def on_delta(kind: str, piece: str) -> None:
                with _STREAM_LOCK:
                    state = _STREAM_STATE.setdefault(
                        job_id,
                        {"phase": "write", "message": "正在生成提示词预览", "reasoning": "", "text": ""},
                    )
                    key = "reasoning" if kind == "reasoning" else "text"
                    state[key] = str(state.get(key) or "") + piece
                    snapshot = state[key]
                _EVENTS.emit(job_id, {"event": "reasoning" if key == "reasoning" else "delta", "data": {"text": snapshot}})
                cls._patch_stream(job_id, {})

            def on_status(info: dict[str, Any]) -> None:
                update = {
                    "phase": info.get("phase") or "write",
                    "message": info.get("message") or "正在生成提示词预览",
                    "reset": bool(info.get("reset")),
                }
                _EVENTS.emit(job_id, {"event": "status", "data": update})
                cls._patch_stream(job_id, update, force=True)

            with LlmStreamHook(on_delta=on_delta, on_status=on_status):
                if request.get("prompt_profile") == "full_reference":
                    beat = (source.get("beats") or [{}])[0]
                    episode = source.get("episode") if isinstance(source.get("episode"), dict) else {}
                    system, user = build_full_reference_prompts(
                        language=request.get("language"),
                        rewrite_mode=request.get("rewrite_mode"),
                        aspect_ratio=request.get("aspect_ratio"),
                        duration_seconds=resolve_shot_duration_sec(beat),
                        source_text=cls._beat_source_text(episode, beat, cls._assets_text(source.get("assets") or [])),
                        reference_slots=request.get("reference_slots") or [],
                    )
                    parsed, raw, retried = cls._generate_with_one_retry(
                        system, user,
                        lambda value: parse_full_reference(value, request.get("language"), request.get("reference_slots") or []),
                    )
                    preview = {
                        "kind": "full_reference", "template_version": request.get("template_version"),
                        "language": request.get("language"), "source_fingerprint": payload.get("source_fingerprint"),
                        "reference_slots": request.get("reference_slots") or [],
                        "beat_id": request.get("target", {}).get("beat_id"),
                        "sections": parsed["sections"], "prompt_text": parsed["prompt_text"],
                        "raw_output": raw, "retried": retried,
                    }
                elif request.get("prompt_profile") == "director_segments":
                    preview = cls._generate_director_preview(payload, request)
                else:
                    raise ValueError("提示词任务类型无效")

            latest = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
            completed = _payload(latest) or payload
            completed["preview"] = preview
            completed.pop("stream", None)
            timestamp = now_str()
            execute_sql(
                "UPDATE ai_project_jobs SET status='completed',progress=100,payload_json=%s,error_message=NULL,completed_at=%s,updated_at=%s WHERE id=%s",
                (json.dumps(completed, ensure_ascii=False), timestamp, timestamp, job_id),
            )
            _EVENTS.emit(job_id, {"event": "done", "terminal": True, "data": {"status": "succeeded", "preview": preview}})
        except Exception as err:
            latest = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
            failed = _payload(latest) or payload
            failed.pop("stream", None)
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,payload_json=%s,updated_at=%s WHERE id=%s",
                (str(err)[:1000], json.dumps(failed, ensure_ascii=False), now_str(), job_id),
            )
            _EVENTS.emit(job_id, terminal_event_for_status("failed", message=str(err)[:1000]))
        finally:
            with _STREAM_LOCK:
                _STREAM_STATE.pop(job_id, None)
                _STREAM_FLUSH_AT.pop(job_id, None)
            with _ACTIVE_LOCK:
                _ACTIVE.discard(job_id)
            cls.kick()

    @staticmethod
    def _assets_text(assets: list[dict[str, Any]]) -> str:
        return "\n".join(
            f"- {item.get('kind') or 'asset'}｜{item.get('name') or '未命名'}：{item.get('description') or item.get('visual_prompt') or ''}"
            for item in assets
        )

    @staticmethod
    def _beat_source_text(episode: dict[str, Any], beat: dict[str, Any], assets_text: str) -> str:
        return (
            f"分集：{episode.get('title') or ''}\n原剧本：\n{episode.get('script_text') or ''}\n\n"
            f"当前分镜：{beat.get('heading') or beat.get('scene') or ''}\n"
            f"动作：{beat.get('action') or beat.get('visual_prompt') or ''}\n机位：{beat.get('camera') or ''}\n"
            f"对白：{beat.get('dialogue') or ''}\n声音：{beat.get('audio') or ''}\n\n"
            f"项目资产文字设定：\n{assets_text}"
        )

    @staticmethod
    def _director_unit_specs(planned_parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            unit
            for part in planned_parts
            for segment in part.get("segments") or []
            for unit in segment.get("source_units") or []
        ]

    @staticmethod
    def _normalized_match_text(value: Any) -> str:
        text = str(value or "").lower()
        text = re.sub(r"\[shot\s+\d+\]", "", text, flags=re.I)
        text = re.sub(r"\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?", "", text)
        text = re.sub(r"\s+", "", text)
        return text

    @classmethod
    def _validate_atomic_unit_allocation(
        cls,
        parsed: dict[str, dict[str, Any]],
        units: list[dict[str, Any]],
        beats: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        by_id = {str(item.get("id") or ""): item for item in units}
        beat_by_id = {str(item.get("id") or ""): item for item in beats}
        if set(parsed) != set(by_id):
            raise PromptTemplateError("动作单元规划与计划单元不一致")
        dialogue_owners: dict[str, list[str]] = {}
        events_by_beat: dict[str, list[tuple[str, str]]] = {}
        for unit_id, allocation in parsed.items():
            source_beat_id = str(by_id[unit_id].get("source_beat_id") or "")
            beat = beat_by_id.get(source_beat_id) or {}
            source_dialogue = str(beat.get("dialogue") or "").strip()
            for dialogue in allocation.get("dialogue_owner") or []:
                if source_dialogue and dialogue != source_dialogue:
                    raise PromptTemplateError(f"动作单元 {unit_id} 的对白不是原始对白")
                dialogue_owners.setdefault(dialogue, []).append(unit_id)
            for event in allocation.get("required_events") or []:
                normalized = cls._normalized_match_text(event)
                if not normalized:
                    raise PromptTemplateError(f"动作单元 {unit_id} 包含空动作事件")
                events_by_beat.setdefault(source_beat_id, []).append((unit_id, normalized))
        for beat_id, beat in beat_by_id.items():
            source_dialogue = str(beat.get("dialogue") or "").strip()
            if source_dialogue:
                owners = dialogue_owners.get(source_dialogue, [])
                if len(owners) != 1:
                    raise PromptTemplateError(f"Beat {beat_id} 的对白必须且只能归属一个动作单元")
        for beat_id, events in events_by_beat.items():
            for index, (unit_id, event) in enumerate(events):
                for other_unit_id, other_event in events[index + 1:]:
                    if unit_id == other_unit_id:
                        continue
                    if event == other_event or (
                        min(len(event), len(other_event)) >= 6
                        and (event in other_event or other_event in event)
                    ):
                        raise PromptTemplateError(f"Beat {beat_id} 的动作事件跨单元重复")
        units_by_beat: dict[str, list[dict[str, Any]]] = {}
        for unit in units:
            units_by_beat.setdefault(str(unit.get("source_beat_id") or ""), []).append(unit)
        for beat_id, beat_units in units_by_beat.items():
            ordered = sorted(beat_units, key=lambda item: (float(item.get("start_sec") or 0), str(item.get("id") or "")))
            for previous, current in zip(ordered, ordered[1:]):
                previous_state = cls._normalized_match_text(parsed[previous["id"]].get("handoff_state"))
                current_state = cls._normalized_match_text(parsed[current["id"]].get("start_state"))
                if not previous_state or previous_state != current_state:
                    raise PromptTemplateError(f"Beat {beat_id} 的相邻动作单元交接状态不一致")
        return parsed

    @classmethod
    def _validate_director_groups(
        cls,
        planned_segments: list[dict[str, Any]],
        groups: list[dict[str, Any]],
    ) -> None:
        if len(planned_segments) != len(groups):
            raise PromptTemplateError("Director 段数量与模型输出不一致")
        all_shot_numbers: list[int] = []
        unit_text: dict[str, str] = {}
        unit_segment: dict[str, int] = {}
        for segment_index, (segment, group) in enumerate(zip(planned_segments, groups), start=1):
            prompt_text = str(group.get("prompt_text") or "")
            all_shot_numbers.extend(int(value) for value in re.findall(r"\[Shot\s+(\d+)]", prompt_text, flags=re.I))
            for unit in segment.get("source_units") or []:
                unit_id = str(unit.get("id") or "")
                if not unit_id:
                    raise PromptTemplateError("Director 段缺少 source_unit_id")
                unit_text[unit_id] = prompt_text
                unit_segment[unit_id] = segment_index
                for dialogue in unit.get("dialogue_owner") or []:
                    value = str(dialogue or "").strip()
                    if not value:
                        continue
                    owners = [
                        index for index, other in enumerate(planned_segments)
                        if value in str(groups[index].get("prompt_text") or "")
                    ]
                    if owners != [segment_index - 1]:
                        raise PromptTemplateError(f"对白在多个 Director 段重复或未落地：{value}")
                for event in unit.get("required_events") or []:
                    value = str(event or "").strip()
                    if not value:
                        continue
                    owners = [
                        index for index, other in enumerate(planned_segments)
                        if value and value in str(groups[index].get("prompt_text") or "")
                    ]
                    if owners != [segment_index - 1]:
                        raise PromptTemplateError(f"原始动作事件重复、遗漏或未原样落地：{value}")
            if segment_index > 1 and any(term.lower() in prompt_text.lower() for term in _DIRECTOR_REPLAY_TERMS):
                raise PromptTemplateError(f"第 {segment_index} 段包含禁止的重播语义")
        if len(all_shot_numbers) != len(set(all_shot_numbers)):
            raise PromptTemplateError("generated_shot_number 在 Director 方案中重复")
        if set(unit_text) != {
            str(unit.get("id") or "")
            for segment in planned_segments
            for unit in segment.get("source_units") or []
        }:
            raise PromptTemplateError("source_unit_id 未被完整覆盖")

        # A high overlap in adjacent summaries for the same source Beat is a
        # useful local signal for replayed prose without blocking normal
        # continuity language shared by all segments.
        for index in range(1, len(planned_segments)):
            previous = planned_segments[index - 1]
            current = planned_segments[index]
            previous_beats = {str(item.get("source_beat_id") or "") for item in previous.get("source_units") or []}
            current_beats = {str(item.get("source_beat_id") or "") for item in current.get("source_units") or []}
            if not previous_beats.intersection(current_beats):
                continue
            left = cls._normalized_match_text(groups[index - 1].get("sections", {}).get("summary"))
            right = cls._normalized_match_text(groups[index].get("sections", {}).get("summary"))
            if len(left) >= 12 and len(right) >= 12:
                left_pairs = {left[pos:pos + 2] for pos in range(len(left) - 1)}
                right_pairs = {right[pos:pos + 2] for pos in range(len(right) - 1)}
                overlap = len(left_pairs & right_pairs) / max(1, min(len(left_pairs), len(right_pairs)))
                if overlap >= 0.82:
                    raise PromptTemplateError("相邻 Director 段摘要高度重复，疑似重演原始动作")

    @classmethod
    def _populate_director_atomic_units(
        cls,
        payload: dict[str, Any],
        request: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], bool]:
        planned_parts = payload.get("planned_parts") if isinstance(payload.get("planned_parts"), list) else []
        source = payload.get("source_snapshot") if isinstance(payload.get("source_snapshot"), dict) else {}
        beats = [dict(item) for item in source.get("beats") or [] if isinstance(item, dict)]
        units = cls._director_unit_specs(planned_parts)
        if not units:
            raise PromptTemplateError("Director 方案没有可规划的动作单元")
        for beat in beats:
            beat["source_shot_number"] = _shot_number(beat.get("story_shot") or beat.get("sequence"), beat.get("sequence") or 1)
        system, user = build_director_unit_planning_prompts(
            language=request.get("language"), beats=beats, units=units,
        )
        parsed, _raw, retried = cls._generate_with_one_retry(
            system,
            user,
            lambda value: cls._validate_atomic_unit_allocation(
                parse_director_unit_plan(value, units), units, beats,
            ),
            retry_instruction="只修复动作单元归属 JSON；保持 unit_id、时间范围和原始对白不变，不增加事件。",
        )
        for unit in units:
            unit.update(parsed[unit["id"]])
        return planned_parts, retried

    @classmethod
    def _parse_and_validate_director_output(
        cls,
        value: str,
        request: dict[str, Any],
        segments: list[dict[str, Any]],
        expected_shots: list[list[int]],
        expected_groups: int,
    ) -> dict[str, Any]:
        parsed = parse_director_output(
            value,
            request.get("language"),
            request.get("reference_slots") or [],
            expected_groups=expected_groups,
            expected_shots=expected_shots,
        )
        cls._validate_director_groups(segments, parsed["groups"])
        return parsed

    @classmethod
    def _generate_director_preview(cls, payload: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        planned_parts = payload.get("planned_parts") if isinstance(payload.get("planned_parts"), list) else []
        planned_parts, planning_retried = cls._populate_director_atomic_units(payload, request)
        parts: list[dict[str, Any]] = []
        common_setting: dict[str, Any] | None = None
        previous_handoff = ""
        retried = planning_retried
        raw_outputs: list[str] = []
        all_planned_segments: list[dict[str, Any]] = []
        all_groups: list[dict[str, Any]] = []
        for part in planned_parts:
            part_handoff = previous_handoff
            system, user = build_director_prompts(
                language=request.get("language"), rewrite_mode=request.get("rewrite_mode"),
                aspect_ratio=request.get("aspect_ratio"), segment_sources=part.get("segments") or [],
                reference_slots=request.get("reference_slots") or [], previous_handoff=previous_handoff,
            )
            expected_shots = [
                [int(unit.get("generated_shot_number")) for unit in segment.get("source_units") or []]
                for segment in part.get("segments") or []
            ]
            parsed, raw, part_retried = cls._generate_with_one_retry(
                system, user,
                lambda value, expected=len(part.get("segments") or []): cls._parse_and_validate_director_output(
                    value, request, part.get("segments") or [], expected_shots, expected,
                ),
                retry_instruction="只修复重复动作/对白或连续性冲突；严格保持动作单元分配表、Shot 编号和时长不变。",
            )
            retried = retried or part_retried
            raw_outputs.append(raw)
            all_planned_segments.extend(part.get("segments") or [])
            all_groups.extend(parsed["groups"])
            if common_setting is None:
                common_setting = parsed["common_setting"]
            segments = []
            for idx, (planned, group) in enumerate(zip(part.get("segments") or [], parsed["groups"]), start=1):
                source_ids = list(planned.get("source_beat_ids") or [])
                units_by_shot = {
                    int(unit.get("generated_shot_number")): str(unit.get("source_beat_id") or "") or None
                    for unit in planned.get("source_units") or []
                }
                segments.append({
                    "id": planned["id"], "index": idx, "title": planned.get("title") or f"段 {idx}",
                    "frame_count": planned.get("frame_count"), "duration_seconds": planned.get("duration_seconds"),
                    "source_beat_ids": source_ids,
                    "source_units": planned.get("source_units") or [],
                    "shots": [
                        {"shot_number": number, "source_beat_id": units_by_shot.get(number)}
                        for number in group.get("shot_numbers") or []
                    ],
                    "sections": group["sections"], "prompt_text": group["prompt_text"],
                    "continuity_from_prev": idx > 1,
                })
            previous_handoff = {
                "segment_id": segments[-1]["id"],
                "state": (segments[-1].get("source_units") or [{}])[-1].get("handoff_state") or "",
                "description_tail": segments[-1]["sections"]["detailed_description"][-240:],
            }
            parts.append({
                "id": part["id"], "index": part["index"], "frame_count": part["frame_count"],
                "segments": segments,
                "handoff_from_previous_part": part_handoff if isinstance(part_handoff, dict) else {},
            })
        cls._validate_director_groups(all_planned_segments, all_groups)
        return {
            "kind": "director_segments", "id": f"director-plan-{uuid.uuid4().hex[:12]}", "revision": 1,
            "schema_version": _DIRECTOR_PLAN_SCHEMA_VERSION,
            "planning_strategy": "atomic_units",
            "unit_planner_version": DIRECTOR_UNIT_PLANNER_VERSION,
            "template_version": request.get("template_version"), "workflow_id": request.get("workflow_id"),
            "language": request.get("language"), "rewrite_mode": request.get("rewrite_mode"),
            "aspect_ratio": request.get("aspect_ratio"), "source_fingerprint": payload.get("source_fingerprint"),
            "reference_slots": request.get("reference_slots") or [], "common_setting": common_setting or {},
            "parts": parts, "raw_outputs": raw_outputs, "retried": retried, "status": "current",
        }

    @classmethod
    def apply_preview(
        cls,
        project_id: str,
        episode_id: str,
        job_id: str,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        req = request or {}
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (job_id, project_id)) or {}
        payload = _payload(row)
        preview = payload.get("preview") if isinstance(payload.get("preview"), dict) else None
        if not row or row.get("job_type") != JOB_TYPE or row.get("status") not in {"completed", "succeeded"} or not preview:
            raise ValueError("提示词预览尚未完成")
        if payload.get("episode_id") != episode_id:
            raise ValueError("提示词预览不属于当前分集")
        expected = _clean(req.get("expected_source_fingerprint"))
        if expected and expected != _clean(payload.get("source_fingerprint")):
            raise RuntimeError("SOURCE_CONFLICT: 预览来源指纹不匹配")
        timestamp = now_str()
        with transaction_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM ai_project_episodes WHERE id=%s AND project_id=%s FOR UPDATE",
                (episode_id, project_id),
            )
            episode_row = cursor.fetchone()
            if not episode_row:
                raise ValueError("分集不存在")
            data = _json_dict(episode_row.get("data_json"))
            beats = data.get("beats") if isinstance(data.get("beats"), list) else []
            cursor.execute(
                "SELECT * FROM ai_project_assets WHERE project_id=%s ORDER BY updated_at DESC FOR UPDATE",
                (project_id,),
            )
            asset_rows = cursor.fetchall() or []
            locked_source = {
                "episode": dict(episode_row),
                "data": data,
                "beats": beats,
                "assets": [dict(item) for item in asset_rows],
            }
            current = cls.source_fingerprint(locked_source, payload.get("request") or {})
            if current != payload.get("source_fingerprint"):
                raise RuntimeError("SOURCE_CONFLICT: 剧本、分镜、资产或工作流已变化，请重新生成预览")
            authoring = data.get("prompt_authoring") if isinstance(data.get("prompt_authoring"), dict) else {}
            authoring["schema_version"] = _DIRECTOR_PLAN_SCHEMA_VERSION if preview.get("kind") == "director_segments" else max(
                1, int(authoring.get("schema_version") or 1)
            )
            if preview.get("kind") == "full_reference":
                beat_id = _clean(preview.get("beat_id"))
                beat = next((item for item in beats if _clean(item.get("id")) == beat_id), None)
                if not beat:
                    raise ValueError("分镜不存在")
                existing_prompt = _clean(beat.get("h3_prompt"))
                existing_source = _clean(beat.get("h3_prompt_source"))
                manual = bool(existing_prompt and existing_source not in {"generated", "prompt_master_full_reference"})
                if manual and not bool(req.get("overwrite_manual")):
                    raise RuntimeError("MANUAL_CONFLICT: 当前分镜包含手写提示词，请确认覆盖")
                records = authoring.get("full_reference") if isinstance(authoring.get("full_reference"), dict) else {}
                record = {
                    **preview,
                    "status": "current", "origin": "prompt_master",
                    "workflow_id": payload.get("request", {}).get("workflow_id"),
                    "rewrite_mode": payload.get("request", {}).get("rewrite_mode"),
                    "aspect_ratio": payload.get("request", {}).get("aspect_ratio"),
                    "applied_from_job_id": job_id, "updated_at": timestamp,
                }
                record.pop("raw_output", None)
                records[beat_id] = record
                authoring["full_reference"] = records
                beat.update({
                    "h3_prompt": preview["prompt_text"],
                    "h3_prompt_source": "prompt_master_full_reference",
                    "h3_prompt_template_version": preview.get("template_version"),
                    "h3_prompt_context_fingerprint": preview.get("source_fingerprint"),
                })
                data["beats"] = beats
            else:
                plan = dict(preview)
                plan.pop("raw_outputs", None)
                plan.update({
                    "status": "current", "origin": "prompt_master",
                    "applied_from_job_id": job_id, "updated_at": timestamp,
                })
                cls.validate_director_plan(plan)
                authoring["director_plan"] = plan
            data["prompt_authoring"] = authoring
            cursor.execute(
                "UPDATE ai_project_episodes SET data_json=%s,updated_at=%s WHERE id=%s AND project_id=%s",
                (json.dumps(data, ensure_ascii=False), timestamp, episode_id, project_id),
            )
            payload["applied_at"] = timestamp
            cursor.execute(
                "UPDATE ai_project_jobs SET payload_json=%s,updated_at=%s WHERE id=%s AND project_id=%s",
                (json.dumps(payload, ensure_ascii=False), timestamp, job_id, project_id),
            )
        return {"status": "applied", "prompt_authoring": authoring}

    @classmethod
    def patch_director_plan(
        cls,
        project_id: str,
        episode_id: str,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        req = request or {}
        expected_revision = int(req.get("expected_revision") or 0)
        with transaction_cursor() as cursor:
            cursor.execute(
                "SELECT data_json FROM ai_project_episodes WHERE id=%s AND project_id=%s FOR UPDATE",
                (episode_id, project_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("分集不存在")
            data = _json_dict(row.get("data_json"))
            authoring = data.get("prompt_authoring") if isinstance(data.get("prompt_authoring"), dict) else {}
            current = authoring.get("director_plan") if isinstance(authoring.get("director_plan"), dict) else None
            if not current:
                raise ValueError("当前分集还没有 Director 出片方案")
            if int(current.get("revision") or 0) != expected_revision:
                raise RuntimeError("REVISION_CONFLICT: Director 方案已被其他操作更新")
            plan = dict(current)
            for key in ("common_setting", "parts", "reference_slots"):
                if key in req:
                    plan[key] = req[key]
            cls.validate_director_plan(plan)
            plan["revision"] = expected_revision + 1
            plan["origin"] = "manual_edit"
            plan["updated_at"] = now_str()
            authoring["director_plan"] = plan
            data["prompt_authoring"] = authoring
            cursor.execute(
                "UPDATE ai_project_episodes SET data_json=%s,updated_at=%s WHERE id=%s AND project_id=%s",
                (json.dumps(data, ensure_ascii=False), plan["updated_at"], episode_id, project_id),
            )
        return plan

    @staticmethod
    def validate_director_plan(plan: dict[str, Any]) -> None:
        definition = workflow_for(_clean(plan.get("workflow_id")))
        if int(plan.get("schema_version") or 0) != _DIRECTOR_PLAN_SCHEMA_VERSION:
            raise ValueError("Director 方案结构已升级，请重新生成")
        if _clean(plan.get("planning_strategy")) != "atomic_units":
            raise ValueError("Director 方案缺少动作单元规划，请重新生成")
        max_segments = int(definition.max_segments or 6)
        max_frames = int(definition.max_total_frames or 1152)
        common = plan.get("common_setting") if isinstance(plan.get("common_setting"), dict) else {}
        if not _clean(common.get("subject_definitions")):
            raise ValueError("Director 公共设定不能为空")
        reference_slots = plan.get("reference_slots") if isinstance(plan.get("reference_slots"), list) else []
        if len(reference_slots) > int(definition.max_references or 0):
            raise ValueError("Director 参考图数量超过当前工作流容量")
        if [int(item.get("index") or 0) for item in reference_slots] != list(range(1, len(reference_slots) + 1)):
            raise ValueError("Director 参考图编号必须从 1 连续递增")
        language = normalize_language(plan.get("language"))
        public_label = "subject_definitions" if language == "en" else "主体定义"
        public_prompt = _clean(common.get("prompt_text")) or f"{public_label}: {_clean(common.get('subject_definitions'))}"
        parts = plan.get("parts") if isinstance(plan.get("parts"), list) else []
        if not parts:
            raise ValueError("Director 方案至少需要一个 Part")
        part_ids: set[str] = set()
        segment_ids: set[str] = set()
        unit_ids: set[str] = set()
        generated_shots: set[int] = set()
        units_by_beat: dict[str, list[dict[str, Any]]] = {}
        all_segments: list[dict[str, Any]] = []
        all_groups: list[dict[str, Any]] = []
        for part in parts:
            part_id = _clean(part.get("id"))
            if not part_id or part_id in part_ids:
                raise ValueError("Director Part ID 为空或重复")
            part_ids.add(part_id)
            segments = part.get("segments") if isinstance(part.get("segments"), list) else []
            if len(segments) < 2 or len(segments) > max_segments:
                raise ValueError(f"每个 Director Part 必须包含 2–{max_segments} 段")
            frame_total = 0
            group_prompts: list[str] = []
            expected_shots: list[list[int]] = []
            for segment in segments:
                segment_id = _clean(segment.get("id"))
                if not segment_id or segment_id in segment_ids:
                    raise ValueError("Director 段 ID 为空或重复")
                segment_ids.add(segment_id)
                frames = int(segment.get("frame_count") or round(float(segment.get("duration_seconds") or 0) * _FPS))
                if frames <= 0:
                    raise ValueError("Director 段时长必须大于 0")
                frame_total += frames
                source_units = segment.get("source_units") if isinstance(segment.get("source_units"), list) else []
                if not source_units:
                    raise ValueError("Director 段缺少 source_units，请重新生成")
                for unit in source_units:
                    unit_id = _clean(unit.get("id"))
                    if not unit_id or unit_id in unit_ids:
                        raise ValueError("Director source_unit_id 为空或重复")
                    unit_ids.add(unit_id)
                    source_beat_id = _clean(unit.get("source_beat_id"))
                    generated_shot = int(unit.get("generated_shot_number") or 0)
                    start_sec = float(unit.get("start_sec") or 0)
                    end_sec = float(unit.get("end_sec") or 0)
                    if not source_beat_id or generated_shot <= 0 or end_sec <= start_sec:
                        raise ValueError("Director source_units 的来源、镜头号或时间范围无效")
                    if generated_shot in generated_shots:
                        raise ValueError("Director generated_shot_number 重复")
                    generated_shots.add(generated_shot)
                    units_by_beat.setdefault(source_beat_id, []).append(unit)
                sections = segment.get("sections") if isinstance(segment.get("sections"), dict) else {}
                for key in ("summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music"):
                    if not _clean(sections.get(key)):
                        raise ValueError(f"Director 段缺少 {key}")
                prompt_text = _clean(segment.get("prompt_text"))
                if not prompt_text:
                    raise ValueError("Director 段提示词不能为空")
                group_prompts.append(prompt_text)
                expected_shots.append([
                    int(item.get("generated_shot_number"))
                    for item in source_units
                ])
            if frame_total > max_frames:
                raise ValueError(f"单个 Director Part 不能超过 {max_frames} 帧")
            public_separator = "===== Public Settings =====" if language == "en" else "===== 公共设定 ====="
            group_name = "Prompt Group" if language == "en" else "提示词组"
            combined = [public_separator, public_prompt]
            for index, prompt_text in enumerate(group_prompts, start=1):
                combined.extend([f"===== {group_name} {index} =====", prompt_text])
            parsed = parse_director_output(
                "\n".join(combined),
                language,
                reference_slots,
                expected_groups=len(segments),
                expected_shots=expected_shots,
            )
            for segment, group in zip(segments, parsed["groups"]):
                stored = segment.get("sections") if isinstance(segment.get("sections"), dict) else {}
                if any(_clean(stored.get(key)) != _clean(group["sections"].get(key)) for key in group["sections"]):
                    raise ValueError("Director 段结构化正文与提示词不一致")
            all_segments.extend(segments)
            all_groups.extend(parsed["groups"])
        for source_beat_id, items in units_by_beat.items():
            ordered = sorted(items, key=lambda item: float(item.get("start_sec") or 0))
            previous_end = 0.0
            for index, item in enumerate(ordered):
                start_sec = float(item.get("start_sec") or 0)
                end_sec = float(item.get("end_sec") or 0)
                duration_seconds = float(item.get("duration_seconds") or 0)
                if abs(duration_seconds - (end_sec - start_sec)) > 0.02:
                    raise ValueError(f"Beat {source_beat_id} 的 source_unit 时长与时间范围不一致")
                if index == 0 and abs(start_sec) > 0.01:
                    raise ValueError(f"Beat {source_beat_id} 的 source_units 未从 0 秒开始")
                if index and start_sec < previous_end - 0.01:
                    raise ValueError(f"Beat {source_beat_id} 的 source_units 时间范围重叠")
                if index and abs(start_sec - previous_end) > 0.01:
                    raise ValueError(f"Beat {source_beat_id} 的 source_units 时间范围存在缺口")
                previous_end = max(previous_end, end_sec)
        try:
            PromptExpansionService._validate_director_groups(all_segments, all_groups)
        except PromptTemplateError as err:
            raise ValueError(str(err)) from err

    @classmethod
    def hydrated_authoring_state(
        cls,
        project_id: str,
        episode: dict[str, Any],
        data: dict[str, Any],
        beats: list[dict[str, Any]],
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        del project_id
        state = json.loads(json.dumps(data.get("prompt_authoring") or {}, ensure_ascii=False))
        source = {"episode": episode, "data": data, "beats": beats, "assets": assets}
        records = state.get("full_reference") if isinstance(state.get("full_reference"), dict) else {}
        for beat_id, record in records.items():
            if not isinstance(record, dict):
                continue
            request = {
                "template_version": record.get("template_version"), "workflow_id": record.get("workflow_id"),
                "language": record.get("language"), "rewrite_mode": record.get("rewrite_mode"),
                "aspect_ratio": record.get("aspect_ratio"), "target_segment_count": None,
                "reference_slots": record.get("reference_slots") or [],
                "target": {"kind": "beat", "beat_id": beat_id},
            }
            record["status"] = "current" if cls.source_fingerprint(source, request) == record.get("source_fingerprint") else "stale"
        plan = state.get("director_plan") if isinstance(state.get("director_plan"), dict) else None
        if plan:
            missing_units = any(
                not isinstance(segment.get("source_units"), list) or not segment.get("source_units")
                for part in plan.get("parts") or []
                for segment in part.get("segments") or []
            )
            if (
                int(plan.get("schema_version") or 0) != _DIRECTOR_PLAN_SCHEMA_VERSION
                or _clean(plan.get("planning_strategy")) != "atomic_units"
                or missing_units
            ):
                plan["status"] = "stale"
                plan["invalid_reason"] = "DIRECTOR_PLAN_SCHEMA_OUTDATED"
                return state
            request = {
                "template_version": plan.get("template_version"), "workflow_id": plan.get("workflow_id"),
                "language": plan.get("language"), "rewrite_mode": plan.get("rewrite_mode") or "expand",
                "aspect_ratio": plan.get("aspect_ratio") or "16:9",
                "target_segment_count": sum(len(part.get("segments") or []) for part in plan.get("parts") or []),
                "reference_slots": plan.get("reference_slots") or [], "target": {"kind": "director_episode"},
            }
            plan["status"] = "current" if cls.source_fingerprint(source, request) == plan.get("source_fingerprint") else "stale"
            if plan["status"] == "stale":
                plan["invalid_reason"] = "SOURCE_CHANGED"
            else:
                plan.pop("invalid_reason", None)
        return state
