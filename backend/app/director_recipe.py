from __future__ import annotations

import uuid
from typing import Any

from .director_catalog import art_style_ref_for_recipe, find_art_style
from .director_compiler import snap_h3_duration_sec
from .workflow_registry import DEFAULT_DIRECTOR_WORKFLOW_FAMILY


PAYLOAD_KIND_TIMELINE = "timeline"
PAYLOAD_KIND_RECIPE = "director_recipe"
PAYLOAD_KIND_BATCH = "batch_run"
PAYLOAD_KINDS = (PAYLOAD_KIND_TIMELINE, PAYLOAD_KIND_RECIPE, PAYLOAD_KIND_BATCH)

AGENT_IDS = (
    "research",
    "script",
    "art_style",
    "storyboard",
    "characters",
    "locations",
    "voice",
    "music",
    "media",
)
AGENT_STATUSES = ("pending", "running", "completed", "failed")
CHARACTER_TYPES = ("character", "object")
GENDERS = ("", "male", "female", "nonbinary", "unspecified")

_RENDER_KEYS = (
    "aspectRatio",
    "canvasTier",
    "previewQuality",
    "previewSpeed",
    "finalQuality",
    "finalSpeed",
    "videoWorkflowFamily",
    "width",
    "height",
    "fps",
    "refsMode",
    "globalSoundscape",
    "globalMusic",
    "manualPromptOverrideEnabled",
    "manualPromptOverrideText",
)


class DirectorPayloadError(ValueError):
    """Invalid director Recipe / batch payload."""


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any, fallback: Any = "") -> str:
    if value is not None:
        text = str(value).strip()
        if text:
            return text
    if fallback is None:
        return ""
    return str(fallback).strip()


def contains_cjk(text: str) -> bool:
    return any("\u3400" <= ch <= "\u9fff" for ch in text or "")


def split_display_and_prompt(
    *,
    title: str = "",
    description: str = "",
    prompt_text: str = "",
    fallback_zh: str = "",
) -> tuple[str, str]:
    """Keep Chinese copy for cards; keep English (or original) text for H3/GRS submit."""
    desc = (description or "").strip()
    prompt = (prompt_text or "").strip()
    title_text = (title or "").strip()
    fallback = (fallback_zh or "").strip()
    if not prompt and desc and not contains_cjk(desc):
        prompt = desc
    display_candidates = [desc]
    if prompt and contains_cjk(prompt):
        display_candidates.append(prompt)
    display_candidates.extend([title_text, fallback])
    display = next((item for item in display_candidates if item and contains_cjk(item)), "")
    if not display:
        display = title_text or fallback or desc
    return display, prompt


def payload_kind(payload: dict[str, Any] | None) -> str:
    raw = _as_dict(payload)
    kind = _text(raw.get("kind"))
    if kind in (PAYLOAD_KIND_RECIPE, PAYLOAD_KIND_BATCH):
        return kind
    return PAYLOAD_KIND_TIMELINE


def empty_agent_status() -> list[dict[str, Any]]:
    return [{"id": agent_id, "status": "pending", "error": None} for agent_id in AGENT_IDS]


def empty_recipe_payload(
    *,
    title: str = "",
    summary: str = "",
    full_story: str = "",
) -> dict[str, Any]:
    return {
        "kind": PAYLOAD_KIND_RECIPE,
        "script": {
            "title": title,
            "summary": summary,
            "fullStory": full_story,
        },
        "artStyle": None,
        "characters": [],
        "locations": [],
        "scenes": [],
        "agentStatus": empty_agent_status(),
        "globalMusic": "",
        "globalSoundscape": "电影级空间环境声",
        "aspectRatio": "16:9",
        "canvasTier": "native",
        "previewQuality": "0.4",
        "previewSpeed": "fast",
        "finalQuality": "1.0",
        "finalSpeed": "balanced",
        "videoWorkflowFamily": DEFAULT_DIRECTOR_WORKFLOW_FAMILY,
        "width": 1344,
        "height": 768,
        "fps": 24,
        "refsMode": "refs_on",
        "manualPromptOverrideEnabled": False,
        "manualPromptOverrideText": "",
    }


def resolve_recipe_art_style(value: Any, *, required: bool = False) -> dict[str, Any] | None:
    if value is None or value == "" or value == {}:
        if required:
            raise DirectorPayloadError("画风必须选自目录")
        return None
    found = find_art_style(value)
    if found is None:
        raise DirectorPayloadError("画风必须选自目录，禁止自造风格名")
    return art_style_ref_for_recipe(found)


def _normalize_agent_status(value: Any) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        agent_id = _text(item.get("id"))
        if agent_id not in AGENT_IDS:
            continue
        status = _text(item.get("status"), "pending")
        if status not in AGENT_STATUSES:
            status = "pending"
        error = item.get("error")
        by_id[agent_id] = {
            "id": agent_id,
            "status": status,
            "error": None if error in (None, "") else str(error),
        }
    return [
        by_id.get(agent_id, {"id": agent_id, "status": "pending", "error": None})
        for agent_id in AGENT_IDS
    ]


def _normalize_character(raw: Any, index: int) -> dict[str, Any]:
    item = _as_dict(raw)
    char_type = _text(item.get("type"), "character")
    if char_type not in CHARACTER_TYPES:
        char_type = "object" if char_type in {"prop", "道具"} else "character"
    gender = _text(item.get("gender"))
    if gender not in GENDERS:
        gender = "unspecified"
    name = _text(item.get("name")) or f"角色 {index + 1}"
    description, prompt_text = split_display_and_prompt(
        title=name,
        description=_text(item.get("description")),
        prompt_text=_text(item.get("promptText"), item.get("prompt_text") or ""),
        fallback_zh=name,
    )
    return {
        "id": _text(item.get("id")) or _new_id("char"),
        "name": name,
        "description": description,
        "promptText": prompt_text or _text(item.get("promptText"), item.get("prompt_text") or item.get("description") or ""),
        "gender": gender,
        "type": char_type,
        "imageJobId": _text(item.get("imageJobId"), item.get("image_job_id") or "") or None,
        "imageUrl": _text(item.get("imageUrl"), item.get("image_url") or "") or None,
    }


def _normalize_location(raw: Any, index: int) -> dict[str, Any]:
    item = _as_dict(raw)
    name = _text(item.get("name")) or f"场景 {index + 1}"
    description, prompt_text = split_display_and_prompt(
        title=name,
        description=_text(item.get("description")),
        prompt_text=_text(item.get("promptText"), item.get("prompt_text") or ""),
        fallback_zh=name,
    )
    return {
        "id": _text(item.get("id")) or _new_id("loc"),
        "name": name,
        "description": description,
        "promptText": prompt_text or _text(item.get("promptText"), item.get("prompt_text") or item.get("description") or ""),
        "imageJobId": _text(item.get("imageJobId"), item.get("image_job_id") or "") or None,
        "imageUrl": _text(item.get("imageUrl"), item.get("image_url") or "") or None,
    }


def _normalize_shot(raw: Any, index: int, *, scene_location: str = "") -> dict[str, Any]:
    item = _as_dict(raw)
    names = item.get("characterNames")
    if names is None:
        names = item.get("character_names")
    character_names = [str(name).strip() for name in _as_list(names) if str(name).strip()]
    compiled = _text(item.get("compiledPrompt"), item.get("compiled_prompt") or "")
    status = _text(item.get("status"), "idle") or "idle"
    duration = snap_h3_duration_sec(item.get("durationSec", item.get("duration_sec", 5)))
    location_name = _text(item.get("locationName"), item.get("location_name") or "") or scene_location
    title = _text(item.get("title")) or f"分镜 {index + 1}"
    description, prompt_text = split_display_and_prompt(
        title=title,
        description=_text(item.get("description")),
        prompt_text=_text(item.get("promptText"), item.get("prompt_text") or item.get("prompt") or ""),
        fallback_zh=title,
    )
    shot: dict[str, Any] = {
        "id": _text(item.get("id")) or _new_id("shot"),
        "shotNumber": int(item.get("shotNumber") or item.get("shot_number") or index + 1),
        "title": title,
        "description": description,
        "promptText": prompt_text,
        "dialogue": _text(item.get("dialogue")),
        "characterNames": character_names,
        "locationName": location_name,
        "durationSec": duration,
        "compiledPrompt": compiled,
        "jobId": _text(item.get("jobId"), item.get("job_id") or "") or None,
        "status": status,
        "outputVideoUrl": _text(item.get("outputVideoUrl"), item.get("output_video_url") or "") or None,
        "progress": item.get("progress") if isinstance(item.get("progress"), (int, float)) else 0,
        "takes": [take for take in _as_list(item.get("takes")) if isinstance(take, dict)],
    }
    camera = item.get("camera")
    if isinstance(camera, dict):
        shot["camera"] = camera
    soundscape = _text(item.get("soundscape"))
    if soundscape:
        shot["soundscape"] = soundscape
    return shot


def _normalize_scene(raw: Any, index: int) -> dict[str, Any]:
    item = _as_dict(raw)
    location_name = _text(item.get("locationName"), item.get("location_name") or "")
    nested = item.get("shots")
    if isinstance(nested, list) and nested:
        shots_raw = nested
    else:
        shots_raw = [item]
    shots = [_normalize_shot(shot, shot_index, scene_location=location_name) for shot_index, shot in enumerate(shots_raw)]
    title = _text(item.get("title")) or (shots[0]["title"] if shots else f"场 {index + 1}")
    description = _text(item.get("description"))
    if not description and shots:
        description = shots[0].get("description") or ""
    if not location_name and shots:
        location_name = shots[0].get("locationName") or ""
    return {
        "id": _text(item.get("id")) or _new_id("scene"),
        "sceneNumber": int(item.get("sceneNumber") or item.get("scene_number") or index + 1),
        "title": title,
        "description": description,
        "locationName": location_name,
        "shots": shots,
    }


def _copy_render_settings(source: dict[str, Any], target: dict[str, Any]) -> None:
    for key in _RENDER_KEYS:
        if key in source and source[key] is not None:
            target[key] = source[key]
    family = _text(source.get("videoWorkflowFamily"), source.get("video_workflow_family") or "")
    if family:
        target["videoWorkflowFamily"] = family


def flatten_recipe_shots(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw = _as_dict(payload)
    kind = payload_kind(raw)
    if kind == PAYLOAD_KIND_BATCH:
        shots: list[dict[str, Any]] = []
        for item in _as_list(raw.get("items")):
            if isinstance(item, dict):
                shots.append(item)
        return shots
    if kind == PAYLOAD_KIND_RECIPE:
        shots = []
        for scene in _as_list(raw.get("scenes")):
            if not isinstance(scene, dict):
                continue
            nested = scene.get("shots")
            if isinstance(nested, list) and nested:
                shots.extend(shot for shot in nested if isinstance(shot, dict))
            else:
                shots.append(scene)
        return shots
    top = raw.get("shots")
    if isinstance(top, list):
        return [shot for shot in top if isinstance(shot, dict)]
    return []


def normalize_recipe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = _as_dict(payload)
    script_raw = _as_dict(raw.get("script"))
    normalized = empty_recipe_payload(
        title=_text(script_raw.get("title"), raw.get("title") or ""),
        summary=_text(script_raw.get("summary"), raw.get("summary") or ""),
        full_story=_text(script_raw.get("fullStory"), script_raw.get("full_story") or raw.get("fullStory") or ""),
    )
    _copy_render_settings(raw, normalized)
    normalized["artStyle"] = resolve_recipe_art_style(raw.get("artStyle") or raw.get("art_style"))
    normalized["characters"] = [
        _normalize_character(item, index) for index, item in enumerate(_as_list(raw.get("characters")))
    ]
    normalized["locations"] = [
        _normalize_location(item, index) for index, item in enumerate(_as_list(raw.get("locations")))
    ]
    scenes_raw = raw.get("scenes")
    if isinstance(scenes_raw, list) and scenes_raw:
        normalized["scenes"] = [_normalize_scene(item, index) for index, item in enumerate(scenes_raw)]
    elif isinstance(raw.get("shots"), list) and raw["shots"]:
        normalized["scenes"] = [
            _normalize_scene({"shots": [shot], "title": _as_dict(shot).get("title")}, index)
            for index, shot in enumerate(raw["shots"])
            if isinstance(shot, dict)
        ]
    normalized["agentStatus"] = _normalize_agent_status(raw.get("agentStatus") or raw.get("agent_status"))
    return normalized


def _normalize_batch_item(raw: Any, index: int) -> dict[str, Any]:
    item = _as_dict(raw)
    status = _text(item.get("status"), "idle") or "idle"
    title = _text(item.get("title")) or f"版本 {index + 1}"
    script = _text(item.get("script"), item.get("prompt") or "")
    raw_description = _text(item.get("description"))
    if raw_description == script:
        raw_description = ""
    description, _prompt = split_display_and_prompt(
        title=title,
        description=raw_description,
        prompt_text=script,
        fallback_zh=title,
    )
    return {
        "id": _text(item.get("id")) or _new_id("batch"),
        "title": title,
        "description": description,
        "script": script,
        "jobId": _text(item.get("jobId"), item.get("job_id") or "") or None,
        "status": status,
        "outputVideoUrl": _text(item.get("outputVideoUrl"), item.get("output_video_url") or "") or None,
        "error": _text(item.get("error")) or None,
    }


def normalize_batch_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = _as_dict(payload)
    count_raw = raw.get("count", len(_as_list(raw.get("items"))) or 1)
    try:
        count = max(1, min(20, int(count_raw)))
    except (TypeError, ValueError):
        count = 1
    duration = snap_h3_duration_sec(raw.get("durationSec", raw.get("duration_sec", 8)))
    aspect = _text(raw.get("aspectRatio"), raw.get("aspect_ratio") or "9:16") or "9:16"
    normalized: dict[str, Any] = {
        "kind": PAYLOAD_KIND_BATCH,
        "theme": _text(raw.get("theme")),
        "count": count,
        "aspectRatio": aspect,
        "durationSec": duration,
        "artStyle": resolve_recipe_art_style(raw.get("artStyle") or raw.get("art_style")),
        "items": [_normalize_batch_item(item, index) for index, item in enumerate(_as_list(raw.get("items")))],
        "agentStatus": _normalize_agent_status(raw.get("agentStatus") or raw.get("agent_status")),
    }
    _copy_render_settings(raw, normalized)
    if not _text(normalized.get("videoWorkflowFamily")):
        normalized["videoWorkflowFamily"] = DEFAULT_DIRECTOR_WORKFLOW_FAMILY
    return normalized


def normalize_director_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = _as_dict(payload)
    kind = payload_kind(raw)
    if kind == PAYLOAD_KIND_RECIPE:
        return normalize_recipe_payload(raw)
    if kind == PAYLOAD_KIND_BATCH:
        return normalize_batch_payload(raw)
    return raw


def _slot_to_character(slot: dict[str, Any], index: int) -> dict[str, Any]:
    kind = _text(slot.get("kind"), "character")
    char_type = "object" if kind in {"prop", "object", "style", "action"} else "character"
    image_url = _text(slot.get("previewUrl"), slot.get("preview_url") or "") or None
    name = _text(slot.get("name")) or f"角色 {index + 1}"
    original = _text(slot.get("description"))
    description, prompt_text = split_display_and_prompt(
        title=name,
        description=original,
        prompt_text="",
        fallback_zh=name,
    )
    return {
        "id": _text(slot.get("id")) or _new_id("char"),
        "name": name,
        "description": description,
        "promptText": prompt_text or original,
        "gender": "unspecified",
        "type": char_type,
        "imageJobId": None,
        "imageUrl": image_url,
    }


def _slot_to_location(slot: dict[str, Any], index: int) -> dict[str, Any]:
    image_url = _text(slot.get("previewUrl"), slot.get("preview_url") or "") or None
    name = _text(slot.get("name")) or f"场景 {index + 1}"
    original = _text(slot.get("description"))
    description, prompt_text = split_display_and_prompt(
        title=name,
        description=original,
        prompt_text="",
        fallback_zh=name,
    )
    return {
        "id": _text(slot.get("id")) or _new_id("loc"),
        "name": name,
        "description": description,
        "promptText": prompt_text or original,
        "imageJobId": None,
        "imageUrl": image_url,
    }


def timeline_to_recipe(
    payload: dict[str, Any] | None,
    *,
    title: str = "",
    summary: str = "",
    source_script: str = "",
) -> dict[str, Any]:
    raw = _as_dict(payload)
    if payload_kind(raw) == PAYLOAD_KIND_RECIPE:
        recipe = normalize_recipe_payload(raw)
        script = _as_dict(recipe.get("script"))
        if title and not script.get("title"):
            script["title"] = title
        if summary and not script.get("summary"):
            script["summary"] = summary
        if source_script and not script.get("fullStory"):
            script["fullStory"] = source_script
        recipe["script"] = script
        return recipe
    if payload_kind(raw) == PAYLOAD_KIND_BATCH:
        raise DirectorPayloadError("批量任务不能转为 Recipe")

    slots = [slot for slot in _as_list(raw.get("subjectSlots")) if isinstance(slot, dict)]
    slot_by_id = {_text(slot.get("id")): slot for slot in slots if _text(slot.get("id"))}
    characters: list[dict[str, Any]] = []
    locations: list[dict[str, Any]] = []
    for index, slot in enumerate(slots):
        has_content = bool(
            _text(slot.get("name")) not in {"", f"主体 {index + 1}"}
            or _text(slot.get("description"))
            or slot.get("previewUrl")
            or slot.get("hasImage")
        )
        if not has_content:
            continue
        kind = _text(slot.get("kind"), "character")
        if kind == "scene":
            locations.append(_slot_to_location(slot, len(locations)))
        else:
            characters.append(_slot_to_character(slot, len(characters)))

    scenes: list[dict[str, Any]] = []
    for index, shot in enumerate(_as_list(raw.get("shots"))):
        if not isinstance(shot, dict):
            continue
        referenced = [
            str(item).strip()
            for item in _as_list(shot.get("referencedSubjectIds") or shot.get("referencedCastIds"))
            if str(item).strip()
        ]
        character_names: list[str] = []
        location_name = ""
        for ref_id in referenced:
            slot = slot_by_id.get(ref_id)
            if not isinstance(slot, dict):
                continue
            name = _text(slot.get("name"))
            if _text(slot.get("kind")) == "scene":
                location_name = location_name or name
            elif name:
                character_names.append(name)
        shot_title = _text(shot.get("title")) or f"分镜 {index + 1}"
        description, prompt_text = split_display_and_prompt(
            title=shot_title,
            description=_text(shot.get("description")),
            prompt_text=_text(shot.get("prompt")),
            fallback_zh=shot_title,
        )
        scenes.append(
            _normalize_scene(
                {
                    "id": _text(shot.get("id")) or _new_id("scene"),
                    "sceneNumber": index + 1,
                    "title": shot_title,
                    "description": description,
                    "locationName": location_name,
                    "shots": [
                        {
                            **shot,
                            "shotNumber": shot.get("shotNumber") or index + 1,
                            "title": shot_title,
                            "description": description,
                            "promptText": prompt_text,
                            "compiledPrompt": _text(shot.get("prompt")),
                            "characterNames": character_names,
                            "locationName": location_name,
                        }
                    ],
                },
                index,
            )
        )

    recipe = empty_recipe_payload(
        title=title or _text(raw.get("title")),
        summary=summary or _text(raw.get("summary")),
        full_story=source_script,
    )
    _copy_render_settings(raw, recipe)
    style_vibe = _text(raw.get("styleVibe"), raw.get("style_vibe") or "")
    if style_vibe:
        try:
            recipe["artStyle"] = resolve_recipe_art_style(style_vibe)
        except DirectorPayloadError:
            recipe["artStyle"] = None
    recipe["characters"] = characters
    recipe["locations"] = locations
    recipe["scenes"] = scenes
    agent_status = empty_agent_status()
    if recipe["script"].get("fullStory") or recipe["script"].get("title"):
        agent_status[1]["status"] = "completed"
    if scenes:
        agent_status[3]["status"] = "completed"
    if characters:
        agent_status[4]["status"] = "completed"
    if locations:
        agent_status[5]["status"] = "completed"
    recipe["agentStatus"] = agent_status
    return recipe


def empty_batch_payload(
    *,
    theme: str = "",
    count: int = 3,
    aspect_ratio: str = "9:16",
    duration_sec: int = 8,
    video_workflow_family: str | None = None,
) -> dict[str, Any]:
    return normalize_batch_payload({
        "kind": PAYLOAD_KIND_BATCH,
        "theme": theme,
        "count": count,
        "aspectRatio": aspect_ratio,
        "durationSec": duration_sec,
        "videoWorkflowFamily": video_workflow_family or DEFAULT_DIRECTOR_WORKFLOW_FAMILY,
        "items": [],
    })


def set_agent_status(
    recipe: dict[str, Any],
    agent_id: str,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    statuses = _normalize_agent_status(recipe.get("agentStatus"))
    for item in statuses:
        if item["id"] == agent_id:
            item["status"] = status if status in AGENT_STATUSES else "pending"
            item["error"] = None if not error else str(error)
    recipe["agentStatus"] = statuses
    return recipe


def find_recipe_shot(recipe: dict[str, Any], shot_id: str) -> dict[str, Any] | None:
    needle = str(shot_id or "").strip()
    if not needle:
        return None
    for scene in _as_list(recipe.get("scenes")):
        if not isinstance(scene, dict):
            continue
        for shot in _as_list(scene.get("shots")):
            if isinstance(shot, dict) and str(shot.get("id") or "") == needle:
                return shot
    return None
