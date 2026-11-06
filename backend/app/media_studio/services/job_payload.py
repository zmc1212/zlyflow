"""Serialize director2 job rows without shipping LONGTEXT drafts on list endpoints."""

from __future__ import annotations

import json
from typing import Any

JOB_LIST_COLUMNS = (
    "id, project_id, job_type, title, status, progress, result_url, "
    "error_message, completed_at, created_at, updated_at, payload_json"
)

_JOB_LIST_KEYS = {
    "reference_urls",
    "images",
    "target_type",
    "asset_id",
    "identity_id",
    "episode_id",
    "beat_id",
    "beat_ids",
    "render_scope",
    "strategy",
    "gap_fill",
    "segment_index",
    "segment_total",
    "segment_count",
    "anchor_beat_id",
    "anchor_sequence",
    "anchor_prefix_urls",
    "anchor_warning",
    "runtime_stage",
    "source_job_id",
    "source_video_url",
    "upscaled_video_url",
    "upscale_warning",
    "shot_video_urls",
    "h3_prompt",
    "result_prompt",
    "timestamped_zh_prompt",
    "vision_status",
    "vision_model",
    "vision_image_count",
    "vision_source",
    "author_errors",
    "document_id",
    "filename",
    "transferred",
    "total",
    "skipped",
    "skipped_count",
    "planned_episodes",
    "episode_total",
    "failed_episodes",
    "current_episode_num",
    "current_episode_index",
    "identity_anchor",
    "scope",
    "line_ids",
    "completed_ids",
    "failed_ids",
    "episode_number",
    "episode_title",
    "shot_count",
    "total_duration_seconds",
    "fps",
    "width",
    "height",
    "quality",
    "aspect_ratio",
    "steps",
    "weight_profile",
    "audio_mode",
    "prompt_id",
    "queue_number",
    "prompt_source",
    "prompt_warning",
    "preparation",
    "prompt_generation_progress",
    "api_url",
    "model",
    "image_size",
    "reply_type",
    "character_references",
}

_STREAM_KEYS = (
    "phase",
    "message",
    "reasoning",
    "text",
    "episode_num",
    "episode_index",
    "episode_total",
)
_STREAM_TEXT_LIMIT = 8000

_JOB_PUBLIC_COLUMNS = (
    "id",
    "project_id",
    "job_type",
    "title",
    "status",
    "progress",
    "result_url",
    "error_message",
    "completed_at",
    "created_at",
    "updated_at",
)


def parse_job_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _trim_text(value: Any, limit: int = _STREAM_TEXT_LIMIT) -> Any:
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return value[:limit]


def _slim_shots(value: Any, *, include_prompt: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    slim: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        beat_id = item.get("beat_id")
        video_url = item.get("video_url")
        if beat_id or video_url:
            entry = {"beat_id": beat_id, "video_url": video_url}
            if include_prompt:
                entry["sequence"] = item.get("sequence")
                entry["prompt"] = item.get("prompt")
            slim.append(entry)
    return slim


def _slim_episodes_done(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    slim: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        shots = item.get("shots")
        shot_count = item.get("shots_count")
        if shot_count is None and isinstance(shots, list):
            shot_count = len(shots)
        slim.append(
            {
                "episode_num": item.get("episode_num"),
                "shots_count": shot_count,
                "shots_source": item.get("shots_source"),
                "error": item.get("error"),
            }
        )
    return slim


_CHUNK_SHOT_STATUS = {
    "succeeded": "succeeded",
    "awaiting_refine": "awaiting_refine",
    "submitted": "running",
    "running": "running",
}


def _shot_render_status(chunks: list[dict[str, Any]]) -> dict[str, str]:
    """逐镜渲染阶段，让工坊在整批完成前就能区分已出片 / 正在生成 / 排队。"""
    status: dict[str, str] = {}
    for chunk in chunks:
        stage = _CHUNK_SHOT_STATUS.get(str(chunk.get("status") or ""), "queued")
        for beat_id in chunk.get("shot_ids") or []:
            key = str(beat_id or "").strip()
            if key:
                status[key] = stage
    return status


def slim_job_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload or {}
    slim = {key: source[key] for key in _JOB_LIST_KEYS if key in source}
    plan = source.get("render_plan")
    raw_chunks = plan.get("chunks") if isinstance(plan, dict) else None
    chunks = [item for item in raw_chunks if isinstance(item, dict)] if isinstance(raw_chunks, list) else []
    if chunks:
        completed = sum(item.get("status") == "succeeded" for item in chunks)
        current = next((index + 1 for index, item in enumerate(chunks) if item.get("status") != "succeeded"), len(chunks))
        slim["render_progress"] = {"total": len(chunks), "completed": completed, "current": current}
        shot_status = _shot_render_status(chunks)
        if shot_status:
            slim["shot_status"] = shot_status
    include_prompt = source.get("prompt_source") == "program_preview"
    shots = _slim_shots(source.get("shots"), include_prompt=include_prompt)
    if shots:
        slim["shots"] = shots
    source_shots = _slim_shots(source.get("source_shots"))
    if source_shots:
        slim["source_shots"] = source_shots
    if "episodes_done" in source:
        slim["episodes_done"] = _slim_episodes_done(source.get("episodes_done"))
    stream = source.get("stream")
    if isinstance(stream, dict):
        slim["stream"] = {
            key: _trim_text(stream[key]) if key in {"text", "reasoning"} else stream[key]
            for key in _STREAM_KEYS
            if key in stream
        }
    return slim


def parse_asset_extra(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def infer_reference_urls(
    payload: dict[str, Any],
    assets_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    refs = [
        url
        for url in (payload.get("reference_urls") or payload.get("images") or [])
        if isinstance(url, str) and url.startswith(("http://", "https://"))
    ]
    if refs:
        return refs
    asset_id = str(payload.get("asset_id") or "").strip()
    asset = (assets_by_id or {}).get(asset_id) if asset_id else None
    if not asset:
        return []
    extra = parse_asset_extra(asset.get("extra_json"))
    target = str(payload.get("target_type") or "")
    if target == "identity":
        inferred = str(extra.get("avatar_url") or asset.get("image_url") or "").strip()
        return [inferred] if inferred else []
    if target in {"scene_reverse", "scene_pano"}:
        master = str(extra.get("master_url") or asset.get("image_url") or "").strip()
        reverse = str(extra.get("reverse_url") or "").strip()
        if not master:
            return []
        return [master, reverse] if target == "scene_pano" and reverse else [master]
    if target in {"prop_turnaround", "prop_detail"}:
        master = str(extra.get("reference_url") or asset.get("image_url") or "").strip()
        return [master] if master else []
    return []


def attach_reference_urls(
    payload: dict[str, Any],
    assets_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    refs = infer_reference_urls(payload, assets_by_id)
    if refs and not (payload.get("reference_urls") or payload.get("images")):
        payload["reference_urls_inferred"] = True
    payload["reference_urls"] = refs
    request_body = payload.get("request_body")
    if isinstance(request_body, dict) and not request_body.get("images"):
        request_body["images"] = refs
    return payload


def serialize_job_row(
    row: dict[str, Any] | None,
    *,
    slim: bool = True,
    assets_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source = row or {}
    result = {key: source.get(key) for key in _JOB_PUBLIC_COLUMNS}
    payload = parse_job_payload(source.get("payload_json") if "payload_json" in source else source.get("payload"))
    if slim:
        payload = slim_job_payload(payload)
    result["payload"] = attach_reference_urls(payload, assets_by_id)
    # Absolute export paths are owner-only; project job endpoints are shared.
    result["payload"].pop("output_path", None)
    return result


def collect_infer_asset_ids(payloads: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for payload in payloads:
        refs = payload.get("reference_urls") or payload.get("images") or []
        has_http = any(isinstance(url, str) and url.startswith(("http://", "https://")) for url in refs)
        if has_http:
            continue
        asset_id = str(payload.get("asset_id") or "").strip()
        target = str(payload.get("target_type") or "")
        if not asset_id or target not in {
            "identity",
            "scene_reverse",
            "scene_pano",
            "prop_turnaround",
            "prop_detail",
        }:
            continue
        if asset_id in seen:
            continue
        seen.add(asset_id)
        ids.append(asset_id)
    return ids
