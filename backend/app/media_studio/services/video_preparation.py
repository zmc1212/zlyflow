"""Prepare a submitted video's prompt outside the GPU lock."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable

from ...llm_client import LlmStreamHook
from .h3_prompt_builder import H3PromptBuilder
from .h3_prompt_job_service import H3PromptJobService
from .llm_service import LlmService
from .project_detail_service import BeatInputChangedError, ProjectDetailService


PROMPT_INPUT_FIELDS = (
    "heading", "action", "camera", "dialogue", "dialogue_turns", "speaker", "narration", "voiceover",
    "visible_text", "audio", "soundscape", "time_of_day", "video_prompt_zh", "visual_prompt",
    "video_duration", "character_ids", "character_look_id", "character_look_ids", "scene_id", "scene",
    "prop_ids", "props", "skill_pack_id", "take_role", "workshop_prompt_document", "h3_prompt",
)


def snapshot_prompt_inputs(beat: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(beat.get(key)) for key in PROMPT_INPUT_FIELDS}


def video_prompt_signature(shot: dict[str, Any]) -> str:
    fields = (
        "action", "camera", "dialogue", "dialogue_turns", "speaker", "narration", "visible_text", "audio",
        "scene_description", "character_references", "reference_urls", "skill_pack_id", "aspect_ratio", "duration_sec",
    )
    raw = json.dumps({key: shot.get(key) for key in fields}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def author_video_prompt(
    shot: dict[str, Any], payload: dict[str, Any], on_status: Callable[[dict[str, Any]], None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    info = H3PromptBuilder.beat_info_from_shot(shot)
    info.update({
        "project_id": payload["project_id"], "episode_id": payload["episode_id"],
        "character_ids": [item["character_id"] for item in shot.get("character_references", []) if item.get("character_id")],
        "character_look_ids": {item["character_id"]: item.get("look_id") for item in shot.get("character_references", []) if item.get("character_id") and item.get("look_id")},
        "characters": [{"id": item.get("character_id"), "name": item.get("character_name"), "url": item.get("url"), "look_desc": item.get("description") or ""} for item in shot.get("character_references", [])],
        "scene_id": shot.get("scene_id") or "", "scene": shot.get("scene") or "",
        "prop_ids": shot.get("prop_ids") or [],
        "skill_pack_id": shot.get("skill_pack_id") or "",
        "aspect_ratio": str(payload.get("aspect_ratio") or ""),
        "timestamped_zh_prompt": shot.get("timestamped_zh_prompt") or "",
    })
    # Use exactly the references that will be uploaded, in the same Picture order.
    slots = {str(item.get("url") or ""): item for item in (shot.get("ref_images") or []) if isinstance(item, dict)}
    characters = {str(item.get("url") or ""): item for item in (shot.get("character_references") or [])}
    refs = []
    for index, url in enumerate(shot.get("reference_urls") or [], 1):
        character = characters.get(url)
        ref = slots.get(url) or ({
            "name": character.get("character_name"), "category": "character",
            "character_id": character.get("character_id"),
        } if character else {"name": shot.get("scene") or "场景", "category": "scene"})
        refs.append({**ref, "index": index, "url": url})
    info["ref_images"] = refs
    with LlmStreamHook(on_status=on_status):
        prompt = H3PromptJobService._finalize_prompt(
            {"beat_info": info, "beat_id": shot["beat_id"], "beat_sequence": shot["sequence"]},
            LlmService.generate_h3_prompt(info),
        )
    updates: dict[str, Any] = {
        "h3_prompt": prompt, "h3_prompt_source": "generated",
        "h3_prompt_input_signature": video_prompt_signature(shot),
    }
    for key in ("timestamped_zh_prompt", "vision_status", "vision_model", "vision_image_count", "vision_source", "authored_en_valid"):
        if info.get(key) not in (None, ""):
            updates[key] = info[key]
    return {**shot, **updates}, updates


def cache_video_prompt(shot: dict[str, Any], payload: dict[str, Any], updates: dict[str, Any]) -> bool:
    # An edit or a manually saved prompt during preparation must never be overwritten.
    expected = shot.get("prompt_cache_base")
    if not isinstance(expected, dict):
        return False  # Old queued tasks have no edit snapshot; keep the prompt in their task only.
    try:
        ProjectDetailService._update_episode_beat_atomic(
            payload["project_id"], payload["episode_id"], shot["beat_id"], updates, expected_fields=expected,
        )
        return True
    except BeatInputChangedError:
        return False
