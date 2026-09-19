from __future__ import annotations

import copy
import uuid
from typing import Any

from ...dialogue_timing import resolve_shot_duration_sec
from ...director_craft.coverage import TAKE_ROLE_LABELS, fidelity_conflict, plan_production_takes
from .h3_prompt_builder import H3PromptBuilder


SNAPSHOT_KEYS = (
    "heading",
    "speaker",
    "dialogue",
    "action",
    "camera",
    "audio",
    "visual_prompt",
    "video_prompt_zh",
    "video_duration",
    "narration",
    "h3_prompt",
    "h3_prompt_source",
)

SHARED_KEYS = (
    "kind",
    "characters",
    "character_ids",
    "character_look_id",
    "character_look_ids",
    "scene",
    "scene_id",
    "props",
    "prop_ids",
    "time_of_day",
    "audio",
)


def story_shot_number(beat: dict[str, Any]) -> int:
    try:
        value = int(beat.get("story_shot") or beat.get("sequence") or 1)
    except (TypeError, ValueError):
        value = 1
    return value if value > 0 else 1


def take_role_label(role: str) -> str:
    return TAKE_ROLE_LABELS.get(str(role or "").strip(), "")


def beat_has_split_takes(beat: dict[str, Any], beats: list[dict[str, Any]] | None = None) -> bool:
    if str(beat.get("take_role") or "").strip() or str(beat.get("parent_beat_id") or "").strip():
        return True
    beat_id = str(beat.get("id") or "")
    if not beat_id:
        return False
    return any(str(item.get("parent_beat_id") or "") == beat_id for item in (beats or []))


def should_split_beat(beat: dict[str, Any], beats: list[dict[str, Any]] | None = None) -> bool:
    if not isinstance(beat, dict):
        return False
    if beat.get("merge_as_one"):
        return False
    if beat_has_split_takes(beat, beats):
        return False
    events = H3PromptBuilder.ordered_speech_events(beat)
    return fidelity_conflict(beat, events)


def split_group_id(beat: dict[str, Any]) -> str:
    return str(beat.get("parent_beat_id") or beat.get("id") or "").strip()


def split_episode_beats(beats: list[dict[str, Any]], beat_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    items = [copy.deepcopy(item) for item in beats if isinstance(item, dict)]
    index = next((pos for pos, item in enumerate(items) if str(item.get("id") or "") == beat_id), -1)
    if index < 0:
        raise ValueError("分镜不存在")
    original = items[index]
    if not should_split_beat(original, items):
        return items, [str(original.get("id") or "")]
    events = H3PromptBuilder.ordered_speech_events(original)
    plans = plan_production_takes(original, events)
    if len(plans) < 2:
        return items, [str(original.get("id") or "")]
    snapshot = {key: copy.deepcopy(original.get(key)) for key in SNAPSHOT_KEYS if key in original}
    story_shot = story_shot_number(original)
    parent_id = str(original.get("id") or "")
    takes: list[dict[str, Any]] = []
    take_ids: list[str] = []
    for offset, plan in enumerate(plans):
        if offset == 0:
            take = dict(original)
        else:
            take = {key: copy.deepcopy(original.get(key)) for key in SHARED_KEYS if key in original}
            take["id"] = f"beat-{uuid.uuid4().hex[:12]}"
            take["heading"] = original.get("heading") or ""
            take["sketch_url"] = None
            take["sketch_job_id"] = None
            take["render_url"] = None
            take["render_job_id"] = None
            take["render_status"] = ""
            take["visible_text"] = original.get("visible_text") or ""
        take["dialogue"] = plan.dialogue
        take["action"] = plan.action
        take["camera"] = plan.camera
        take["speaker"] = plan.speaker
        take["take_role"] = plan.role
        take["story_shot"] = story_shot
        take["parent_beat_id"] = "" if offset == 0 else parent_id
        take["merge_as_one"] = False
        take["h3_prompt"] = ""
        take["h3_prompt_source"] = ""
        take["video_url"] = None
        take["upscaled_video_url"] = None
        take["video_prompt_zh"] = " ".join(
            part for part in (
                plan.action,
                f"运镜：{plan.camera}" if plan.camera else "",
            ) if part
        )
        if offset == 0:
            take["take_source"] = snapshot
            take["visual_prompt"] = original.get("visual_prompt") or ""
        else:
            take["visual_prompt"] = ""
            take.pop("take_source", None)
        take["video_duration"] = str(resolve_shot_duration_sec(take))
        takes.append(take)
        take_ids.append(str(take.get("id") or ""))
    next_beats = items[:index] + takes + items[index + 1:]
    return _resequence(next_beats), take_ids


def merge_episode_beats(beats: list[dict[str, Any]], beat_id: str) -> tuple[list[dict[str, Any]], str]:
    items = [copy.deepcopy(item) for item in beats if isinstance(item, dict)]
    current = next((item for item in items if str(item.get("id") or "") == beat_id), None)
    if not current:
        raise ValueError("分镜不存在")
    group_id = split_group_id(current) or beat_id
    parent = next((item for item in items if str(item.get("id") or "") == group_id), current)
    children = [item for item in items if str(item.get("parent_beat_id") or "") == group_id]
    snapshot = parent.get("take_source") if isinstance(parent.get("take_source"), dict) else {}
    restored = dict(parent)
    if snapshot:
        restored.update({key: copy.deepcopy(value) for key, value in snapshot.items()})
    else:
        ordered = [parent, *children]
        restored["dialogue"] = " ".join(
            str(item.get("dialogue") or "").strip() for item in ordered if str(item.get("dialogue") or "").strip()
        )
        restored["action"] = str(parent.get("action") or "")
        restored["camera"] = str(parent.get("camera") or "")
    restored["id"] = group_id
    restored["parent_beat_id"] = ""
    restored["take_role"] = ""
    restored["merge_as_one"] = True
    restored["h3_prompt"] = ""
    restored["h3_prompt_source"] = ""
    restored.pop("take_source", None)
    restored["story_shot"] = story_shot_number(parent)
    drop = {str(item.get("id") or "") for item in children}
    next_beats: list[dict[str, Any]] = []
    replaced = False
    for item in items:
        item_id = str(item.get("id") or "")
        if item_id in drop:
            continue
        if item_id == group_id:
            next_beats.append(restored)
            replaced = True
            continue
        next_beats.append(item)
    if not replaced:
        next_beats.append(restored)
    return _resequence(next_beats), group_id


def _resequence(beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, beat in enumerate(beats, start=1):
        beat["sequence"] = index
        if not beat.get("story_shot"):
            beat["story_shot"] = index
    return beats
