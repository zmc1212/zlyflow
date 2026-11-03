"""Prepare a submitted video's prompt and optional keyframes outside the GPU lock."""
from __future__ import annotations

import copy
import hashlib
import json
import time
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
        "triptych_url", "triptych_panels",
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
        "triptych_url": shot.get("triptych_url") or "",
        "triptych_panels": shot.get("triptych_panels") or {},
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


def prepare_video_keyframes(
    shot: dict[str, Any], payload: dict[str, Any], checkpoint: Callable[[], None],
) -> dict[str, Any]:
    """Reuse an existing plan or await its real image job; never enqueue twice on polling."""
    from ...skill_packs.aspect import WORKSHOP_ASPECT_KEY
    from .storyboard_image_service import StoryboardImageService

    project_id, episode_id, beat_id = payload["project_id"], payload["episode_id"], shot["beat_id"]
    if shot.get("triptych_url") or (shot.get("triptych_panels") or {}).get("start"):
        return shot
    jobs = payload.setdefault("keyframe_jobs", {})
    job_id = jobs.get(beat_id) or shot.get("triptych_job_id")
    job = ProjectDetailService.get_job(project_id, job_id) if job_id else None
    if job and job.get("status") == "failed":
        result = StoryboardImageService.retry(project_id, job_id)
        job_id = result["job_id"]
    elif not job:
        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        current = next((beat for beat in detail.get("beats", []) if beat.get("id") == beat_id), {})
        if snapshot_prompt_inputs(current) != shot.get("prompt_cache_base"):
            raise ValueError("片段内容已修改，请按当前正文重新生成视频")
        result = StoryboardImageService.enqueue(
            project_id, episode_id, beat_id,
            {WORKSHOP_ASPECT_KEY: payload.get("aspect_ratio") or "16:9"}, "triptych",
        )
        job_id = result["job_id"]
    jobs[beat_id] = job_id
    checkpoint()
    deadline = time.monotonic() + 1800
    while True:
        job = ProjectDetailService.get_job(project_id, job_id) or {}
        status = job.get("status")
        if status in {"completed", "succeeded"}:
            detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
            beat = next((item for item in detail.get("beats", []) if item.get("id") == beat_id), {})
            if snapshot_prompt_inputs(beat) != shot.get("prompt_cache_base"):
                raise ValueError("关键帧已保留，但片段内容已修改，请按当前正文重新生成视频")
            if not beat.get("triptych_url"):
                raise ValueError("关键帧任务完成但画面未回填，请在任务中心查看")
            return beat
        if status in {"failed", "cancelled", "interrupted"} or not job:
            raise ValueError("关键帧规划失败：" + str(job.get("error_message") or "任务未完成"))
        if time.monotonic() >= deadline:
            raise ValueError("关键帧仍在准备，任务已保留；稍后重试将继续等待原任务")
        time.sleep(1)
