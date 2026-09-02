from __future__ import annotations

import uuid
from typing import Any

from .director_catalog import art_style_ref_for_recipe, find_art_style
from .director_compiler import snap_h3_duration_sec
from .tts_provider import voice_for_gender
from .llm_client import repair_utf8_mojibake
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
PIPELINE_AGENT_ORDER = (
    "research", "script", "art_style", "characters", "locations", "storyboard", "voice", "music", "media",
)
AGENT_STATUSES = ("pending", "running", "completed", "failed")
AGENT_RUNNING_MESSAGES = {
    "research": "正在核对故事设定",
    "script": "正在根据创意写剧本",
    "art_style": "正在选择美术风格",
    "storyboard": "正在按已确认资产拆分镜头",
    "characters": "正在建立角色与道具设定",
    "locations": "正在建立场景设定",
    "voice": "正在配置配音",
    "music": "正在配置配乐",
    "media": "正在编译出片参数",
}
AGENT_DONE_MESSAGES = {
    "research": "研究完成",
    "script": "剧本已写好",
    "art_style": "画风已选定",
    "storyboard": "分镜方案已写好",
    "characters": "人物方案已抽出，定妆图待生成",
    "locations": "场景方案已抽出，定妆图待生成",
    "voice": "配音方案已写好，音频待生成",
    "music": "配乐方案已写好，音频待上传",
    "media": "出片参数已编译，视频待生成",
}
CHARACTER_TYPES = ("character", "object")
GENDERS = ("", "male", "female", "nonbinary", "unspecified")
CAMERA_SCALES = {"ELS", "WS", "MS", "CU", "ECU"}
CAMERA_MOVEMENTS = {
    "zoom_in", "zoom_out", "pan_left", "pan_right", "tilt_up", "tilt_down",
    "orbit", "tracking", "static",
}
CAMERA_ANGLES = {"eye_level", "low_angle", "high_angle", "dutch", "pov"}
CAMERA_SPEEDS = {"smooth", "dynamic", "slow"}
CAMERA_LIGHTING = {
    "cinematic_soft", "cyberpunk", "golden_hour", "dramatic_low_key", "studio",
}

_RENDER_KEYS = (
    "aspectRatio",
    "canvasTier",
    "previewQuality",
    "previewSpeed",
    "finalQuality",
    "finalSpeed",
    "weightProfile",
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
        text = repair_utf8_mojibake(str(value).strip())
        if text:
            return text
    if fallback is None:
        return ""
    return repair_utf8_mojibake(str(fallback).strip())


def normalize_dialogue(value: Any) -> str:
    text = _text(value)
    lowered = text.lower()
    if lowered.startswith("<d>") and lowered.endswith("</d>"):
        inner = text[3:-4].strip()
        if inner.startswith("[") and "]" in inner[:32]:
            inner = inner.split("]", 1)[1].strip()
        return inner
    return text


def default_audio_mix() -> dict[str, Any]:
    return {
        "bgmUrl": None,
        "bgmPath": None,
        "bgmVolume": 0.25,
        "bgmFadeInSec": 1.0,
        "bgmFadeOutSec": 2.0,
    }


def default_subtitle_style() -> dict[str, Any]:
    return {
        "enabled": False,
        "position": "bottom",
        "fontSize": 28,
        "strokeWidth": 2,
        "textColor": "#ffffff",
        "strokeColor": "#000000",
    }


def empty_export_state() -> dict[str, Any]:
    return {
        "muxStatus": "idle",
        "muxUrl": None,
        "muxPath": None,
        "muxDurationSec": None,
        "muxError": None,
        "muxAt": None,
        "burnSubtitles": False,
    }


def _audio_float(value: Any, default: float, *, minimum: float = 0.0, maximum: float = 100.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _audio_int(value: Any, default: int, *, minimum: int = 0, maximum: int = 200) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def normalize_voice_id(value: Any, *, gender: str = "") -> str:
    voice = _text(value)
    if voice:
        return voice
    return voice_for_gender(gender)


def normalize_audio_mix(raw: Any) -> dict[str, Any]:
    item = raw if isinstance(raw, dict) else {}
    base = default_audio_mix()
    bgm_url = _text(item.get("bgmUrl") or item.get("bgm_url"))
    bgm_path = _text(item.get("bgmPath") or item.get("bgm_path"))
    return {
        "bgmUrl": bgm_url or None,
        "bgmPath": bgm_path or None,
        "bgmVolume": _audio_float(item.get("bgmVolume", item.get("bgm_volume", base["bgmVolume"])), 0.25, maximum=1.0),
        "bgmFadeInSec": _audio_float(item.get("bgmFadeInSec", item.get("bgm_fade_in_sec", base["bgmFadeInSec"])), 1.0, maximum=15.0),
        "bgmFadeOutSec": _audio_float(item.get("bgmFadeOutSec", item.get("bgm_fade_out_sec", base["bgmFadeOutSec"])), 2.0, maximum=15.0),
    }


def normalize_subtitle_style(raw: Any) -> dict[str, Any]:
    item = raw if isinstance(raw, dict) else {}
    base = default_subtitle_style()
    position = _text(item.get("position"), base["position"]).lower()
    if position not in {"top", "center", "bottom"}:
        position = "bottom"
    enabled = item.get("enabled")
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in {"1", "true", "yes", "on"}
    return {
        "enabled": bool(enabled) if enabled is not None else False,
        "position": position,
        "fontSize": _audio_int(item.get("fontSize", item.get("font_size", base["fontSize"])), 28, minimum=12, maximum=72),
        "strokeWidth": _audio_int(item.get("strokeWidth", item.get("stroke_width", base["strokeWidth"])), 2, minimum=0, maximum=8),
        "textColor": _text(item.get("textColor") or item.get("text_color"), base["textColor"]) or "#ffffff",
        "strokeColor": _text(item.get("strokeColor") or item.get("stroke_color"), base["strokeColor"]) or "#000000",
    }


def normalize_export_state(raw: Any) -> dict[str, Any]:
    item = raw if isinstance(raw, dict) else {}
    base = empty_export_state()
    status = _text(item.get("muxStatus") or item.get("mux_status"), base["muxStatus"]) or "idle"
    if status not in {"idle", "queued", "running", "succeeded", "failed"}:
        status = "idle"
    duration = item.get("muxDurationSec", item.get("mux_duration_sec"))
    try:
        duration_sec = float(duration) if duration not in (None, "") else None
    except (TypeError, ValueError):
        duration_sec = None
    return {
        "muxStatus": status,
        "muxUrl": _text(item.get("muxUrl") or item.get("mux_url")) or None,
        "muxPath": _text(item.get("muxPath") or item.get("mux_path")) or None,
        "muxDurationSec": duration_sec,
        "muxError": _text(item.get("muxError") or item.get("mux_error")) or None,
        "muxAt": _text(item.get("muxAt") or item.get("mux_at")) or None,
        "burnSubtitles": bool(item.get("burnSubtitles", item.get("burn_subtitles", False))),
    }


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
    return [{"id": agent_id, "status": "pending", "error": None, "message": None} for agent_id in AGENT_IDS]


def empty_pipeline_run() -> dict[str, Any]:
    return {"agents": [], "active": False}


def empty_recipe_payload(
    *,
    title: str = "",
    summary: str = "",
    full_story: str = "",
) -> dict[str, Any]:
    return {
        "kind": PAYLOAD_KIND_RECIPE,
        "assetSchemaVersion": 2,
        "script": {
            "title": title,
            "summary": summary,
            "fullStory": full_story,
        },
        "artStyle": None,
        "characters": [],
        "props": [],
        "locations": [],
        "scenes": [],
        "agentStatus": empty_agent_status(),
        "pipelineRun": empty_pipeline_run(),
        "globalMusic": "",
        "globalSoundscape": "电影级空间环境声",
        "aspectRatio": "16:9",
        "canvasTier": "native",
        "previewQuality": "0.4",
        "previewSpeed": "fast",
        "finalQuality": "1.0",
        "finalSpeed": "balanced",
        "weightProfile": "full",
        "videoWorkflowFamily": DEFAULT_DIRECTOR_WORKFLOW_FAMILY,
        "width": 1344,
        "height": 768,
        "fps": 24,
        "refsMode": "refs_on",
        "manualPromptOverrideEnabled": False,
        "manualPromptOverrideText": "",
        "audio": default_audio_mix(),
        "subtitles": default_subtitle_style(),
        "export": empty_export_state(),
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
        message = _text(item.get("message")) or None
        by_id[agent_id] = {
            "id": agent_id,
            "status": status,
            "error": None if error in (None, "") else str(error),
            "message": message,
        }
    return [
        by_id.get(agent_id, {"id": agent_id, "status": "pending", "error": None, "message": None})
        for agent_id in AGENT_IDS
    ]


def _normalize_pipeline_run(value: Any) -> dict[str, Any]:
    raw = _as_dict(value)
    agents: list[str] = []
    for item in _as_list(raw.get("agents")):
        agent_id = _text(item)
        if agent_id in AGENT_IDS and agent_id not in agents:
            agents.append(agent_id)
    return {"agents": agents, "active": bool(raw.get("active")) and bool(agents)}


def agent_done_message(agent_id: str, recipe: dict[str, Any] | None = None) -> str:
    if agent_id == "storyboard":
        count = len(flatten_recipe_shots(recipe)) if recipe else 0
        return f"已写出 {count} 个镜头" if count else AGENT_DONE_MESSAGES[agent_id]
    return AGENT_DONE_MESSAGES.get(agent_id, "已完成")


CHARACTER_IDENTITY_SPEC_FIELDS = (
    "ageRange",
    "regionalAppearance",
    "faceFeatures",
    "hair",
    "skinTone",
    "bodyBuild",
    "distinguishingMarks",
    "immutableAccessories",
    "avoidChanges",
)
ASSET_VERSION_STATUSES = {"queued", "running", "succeeded", "failed", "interrupted", "cancelled"}


def _string_list(value: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(value):
        text = _text(item)
        if text and text not in result:
            result.append(text)
    return result


def _normalize_asset_version(raw: Any, index: int) -> dict[str, Any]:
    item = _as_dict(raw)
    status = _text(item.get("status"), "queued") or "queued"
    if status not in ASSET_VERSION_STATUSES:
        status = "queued"
    version_id = _text(item.get("id")) or _new_id("assetv")
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    return {
        "id": version_id,
        "jobId": _text(item.get("jobId"), item.get("job_id") or "") or None,
        "imageUrl": _text(item.get("imageUrl"), item.get("image_url") or "") or None,
        "status": status,
        "promptSnapshot": _text(item.get("promptSnapshot"), item.get("prompt_snapshot") or ""),
        "workflowId": _text(item.get("workflowId"), item.get("workflow_id") or "") or None,
        "options": dict(options),
        "createdAt": _text(item.get("createdAt"), item.get("created_at") or ""),
        "autoApprove": bool(item.get("autoApprove", item.get("auto_approve", False))),
    }


def _normalize_asset_rendition(
    raw: Any,
    *,
    legacy_job_id: Any = None,
    legacy_image_url: Any = None,
    legacy_prompt: str = "",
) -> dict[str, Any]:
    item = _as_dict(raw)
    versions = [
        _normalize_asset_version(version, index)
        for index, version in enumerate(_as_list(item.get("versions")))
        if isinstance(version, dict)
    ]
    legacy_job = _text(legacy_job_id) or None
    legacy_url = _text(legacy_image_url) or None
    if not versions and (legacy_job or legacy_url):
        legacy_id = f"legacy-{legacy_job or 'image'}"
        versions = [{
            "id": legacy_id,
            "jobId": legacy_job,
            "imageUrl": legacy_url,
            "status": "succeeded" if legacy_url else "queued",
            "promptSnapshot": legacy_prompt,
            "workflowId": None,
            "options": {},
            "createdAt": "",
            "autoApprove": True,
        }]
    version_ids = {version["id"] for version in versions}
    active_id = _text(item.get("activeVersionId"), item.get("active_version_id") or "") or None
    approved_id = _text(item.get("approvedVersionId"), item.get("approved_version_id") or "") or None
    if active_id not in version_ids:
        active_id = versions[-1]["id"] if versions else None
    if approved_id not in version_ids:
        approved_id = None
    if approved_id is None and legacy_url and versions:
        approved_id = versions[-1]["id"]
    return {
        "versions": versions,
        "activeVersionId": active_id,
        "approvedVersionId": approved_id,
    }


def rendition_version(rendition: Any, version_id: Any) -> dict[str, Any] | None:
    wanted = _text(version_id)
    if not wanted:
        return None
    return next(
        (
            version for version in _as_list(_as_dict(rendition).get("versions"))
            if isinstance(version, dict) and _text(version.get("id")) == wanted
        ),
        None,
    )


def approved_rendition_version(rendition: Any) -> dict[str, Any] | None:
    item = _as_dict(rendition)
    return rendition_version(item, item.get("approvedVersionId"))


def active_rendition_version(rendition: Any) -> dict[str, Any] | None:
    item = _as_dict(rendition)
    return rendition_version(item, item.get("activeVersionId"))


def _normalize_identity_spec(raw: Any) -> dict[str, str]:
    item = _as_dict(raw)
    return {
        field: _text(item.get(field), item.get(_camel_to_snake(field)) or "")
        for field in CHARACTER_IDENTITY_SPEC_FIELDS
    }


def _camel_to_snake(value: str) -> str:
    output = ""
    for character in value:
        if character.isupper():
            output += "_" + character.lower()
        else:
            output += character
    return output


def _normalize_character_look(
    raw: Any,
    index: int,
    *,
    legacy_job_id: Any = None,
    legacy_image_url: Any = None,
    legacy_prompt: str = "",
) -> dict[str, Any]:
    item = _as_dict(raw)
    status = _text(item.get("status"), "draft") or "draft"
    if status not in {"draft", "approved"}:
        status = "draft"
    return {
        "id": _text(item.get("id")) or ("look-default" if index == 0 else _new_id("look")),
        "name": _text(item.get("name")) or ("基础造型" if index == 0 else f"造型 {index + 1}"),
        "appearanceDetails": _text(item.get("appearanceDetails"), item.get("appearance_details") or ""),
        "promptText": _text(item.get("promptText"), item.get("prompt_text") or ""),
        "status": status,
        "sheet": _normalize_asset_rendition(
            item.get("sheet"),
            legacy_job_id=legacy_job_id,
            legacy_image_url=legacy_image_url,
            legacy_prompt=legacy_prompt,
        ),
    }


def character_look(character: Any, look_id: Any = None) -> dict[str, Any] | None:
    item = _as_dict(character)
    looks = [look for look in _as_list(item.get("looks")) if isinstance(look, dict)]
    wanted = _text(look_id)
    if wanted:
        matched = next((look for look in looks if _text(look.get("id")) == wanted), None)
        if matched is not None:
            return matched
    return looks[0] if looks else None


def character_approved_look_version(character: Any, look_id: Any = None) -> dict[str, Any] | None:
    look = character_look(character, look_id)
    return approved_rendition_version(_as_dict(look).get("sheet")) if look else None


def character_approved_portrait_version(character: Any) -> dict[str, Any] | None:
    return approved_rendition_version(_as_dict(character).get("portrait"))


def _normalize_prop(raw: Any, index: int) -> dict[str, Any]:
    item = _as_dict(raw)
    name = _text(item.get("name")) or f"道具 {index + 1}"
    description, prompt_text = split_display_and_prompt(
        title=name,
        description=_text(item.get("description")),
        prompt_text=_text(item.get("promptText"), item.get("prompt_text") or ""),
        fallback_zh=name,
    )
    rendition = _normalize_asset_rendition(
        item.get("turnaround"),
        legacy_job_id=item.get("imageJobId") or item.get("image_job_id"),
        legacy_image_url=item.get("imageUrl") or item.get("image_url"),
        legacy_prompt=prompt_text,
    )
    active = active_rendition_version(rendition)
    approved = approved_rendition_version(rendition)
    return {
        "id": _text(item.get("id")) or _new_id("prop"),
        "name": name,
        "description": description,
        "promptText": prompt_text or _text(item.get("description")),
        "turnaround": rendition,
        "imageJobId": _text((active or {}).get("jobId")) or None,
        "imageUrl": _text((approved or {}).get("imageUrl")) or None,
        "libraryAssetId": _text(item.get("libraryAssetId"), item.get("library_asset_id") or "") or None,
    }


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
    legacy_job_id = item.get("imageJobId") or item.get("image_job_id")
    legacy_image_url = item.get("imageUrl") or item.get("image_url")
    looks_raw = _as_list(item.get("looks"))
    if not looks_raw:
        looks_raw = [{
            "id": "look-default",
            "name": "基础造型",
            "appearanceDetails": description,
            "promptText": prompt_text,
            "status": "approved" if legacy_image_url else "draft",
        }]
    looks = [
        _normalize_character_look(
            look,
            look_index,
            legacy_job_id=legacy_job_id if look_index == 0 else None,
            legacy_image_url=legacy_image_url if look_index == 0 else None,
            legacy_prompt=prompt_text if look_index == 0 else "",
        )
        for look_index, look in enumerate(looks_raw)
        if isinstance(look, dict)
    ]
    if not looks:
        looks = [_normalize_character_look({}, 0)]
    portrait = _normalize_asset_rendition(item.get("portrait"))
    active_look = character_look({"looks": looks})
    active_version = active_rendition_version(_as_dict(active_look).get("sheet"))
    approved_version = approved_rendition_version(_as_dict(active_look).get("sheet"))
    active_version = active_version or active_rendition_version(portrait)
    approved_version = approved_version or approved_rendition_version(portrait)
    spec_status = _text(item.get("specStatus"), item.get("spec_status") or "draft") or "draft"
    if spec_status not in {"draft", "approved"}:
        spec_status = "draft"
    if legacy_image_url and not item.get("specStatus") and not item.get("spec_status"):
        spec_status = "approved"
    return {
        "id": _text(item.get("id")) or _new_id("char"),
        "name": name,
        "description": description,
        "promptText": prompt_text or _text(item.get("promptText"), item.get("prompt_text") or item.get("description") or ""),
        "role": _text(item.get("role")),
        "gender": gender,
        "type": char_type,
        "identitySpec": _normalize_identity_spec(item.get("identitySpec") or item.get("identity_spec")),
        "specStatus": spec_status,
        "aiAssumptions": _string_list(item.get("aiAssumptions") or item.get("ai_assumptions")),
        "portrait": portrait,
        "looks": looks,
        "imageJobId": _text((active_version or {}).get("jobId")) or None,
        "imageUrl": _text((approved_version or {}).get("imageUrl")) or None,
        "libraryAssetId": _text(item.get("libraryAssetId"), item.get("library_asset_id") or "") or None,
        "voiceId": normalize_voice_id(item.get("voiceId") or item.get("voice_id"), gender=gender),
        "voicePreviewUrl": _text(item.get("voicePreviewUrl"), item.get("voice_preview_url") or "") or None,
    }


def default_camera_direction() -> dict[str, str]:
    return {
        "scale": "MS",
        "movement": "zoom_in",
        "angle": "eye_level",
        "speed": "smooth",
        "lighting": "cinematic_soft",
        "sfx": "",
    }


def _persistable_media_url(value: Any) -> str | None:
    text = _text(value)
    if not text or text.startswith("data:"):
        return None
    return text


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_camera(raw: Any) -> dict[str, str]:
    item = raw if isinstance(raw, dict) else {}
    base = default_camera_direction()
    scale = _text(item.get("scale"), base["scale"])
    movement = _text(item.get("movement"), base["movement"])
    angle = _text(item.get("angle"), base["angle"])
    speed = _text(item.get("speed"), base["speed"])
    lighting = _text(item.get("lighting"), base["lighting"])
    return {
        "scale": scale if scale in CAMERA_SCALES else base["scale"],
        "movement": movement if movement in CAMERA_MOVEMENTS else base["movement"],
        "angle": angle if angle in CAMERA_ANGLES else base["angle"],
        "speed": speed if speed in CAMERA_SPEEDS else base["speed"],
        "lighting": lighting if lighting in CAMERA_LIGHTING else base["lighting"],
        "sfx": _text(item.get("sfx")),
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
    rendition = _normalize_asset_rendition(
        item.get("plate"),
        legacy_job_id=item.get("imageJobId") or item.get("image_job_id"),
        legacy_image_url=item.get("imageUrl") or item.get("image_url"),
        legacy_prompt=prompt_text,
    )
    active = active_rendition_version(rendition)
    approved = approved_rendition_version(rendition)
    return {
        "id": _text(item.get("id")) or _new_id("loc"),
        "name": name,
        "description": description,
        "promptText": prompt_text or _text(item.get("promptText"), item.get("prompt_text") or item.get("description") or ""),
        "plate": rendition,
        "imageJobId": _text((active or {}).get("jobId")) or None,
        "imageUrl": _text((approved or {}).get("imageUrl")) or None,
        "libraryAssetId": _text(item.get("libraryAssetId"), item.get("library_asset_id") or "") or None,
    }


def _normalize_character_bindings(value: Any) -> list[dict[str, str]]:
    bindings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in _as_list(value):
        if isinstance(raw, str):
            character_id = _text(raw)
            look_id = "look-default"
        elif isinstance(raw, dict):
            character_id = _text(raw.get("characterId"), raw.get("character_id") or raw.get("id") or "")
            look_id = _text(raw.get("lookId"), raw.get("look_id") or "look-default") or "look-default"
        else:
            continue
        key = (character_id, look_id)
        if character_id and key not in seen:
            bindings.append({"characterId": character_id, "lookId": look_id})
            seen.add(key)
    return bindings


def _normalize_shot_take(raw: Any, index: int) -> dict[str, Any]:
    item = _as_dict(raw)
    status = _text(item.get("status"), "queued") or "queued"
    if status not in {"idle", "queued", "running", "succeeded", "failed", "interrupted", "cancelled"}:
        status = "queued"
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    render_pass = _text(item.get("renderPass"), item.get("render_pass") or "")
    if render_pass not in {"preview", "final"}:
        render_pass = None
    try:
        progress = int(item.get("progress") or 0)
    except (TypeError, ValueError):
        progress = 0
    return {
        "id": _text(item.get("id")) or _new_id("take"),
        "takeNumber": int(item.get("takeNumber") or item.get("take_number") or index + 1),
        "jobId": _text(item.get("jobId"), item.get("job_id") or "") or None,
        "videoUrl": _persistable_media_url(item.get("videoUrl") or item.get("video_url")),
        "coverUrl": _persistable_media_url(item.get("coverUrl") or item.get("cover_url")),
        "outputPath": _text(item.get("outputPath"), item.get("output_path") or "") or None,
        "status": status,
        "progress": max(0, min(100, progress)),
        "error": _text(item.get("error")) or None,
        "createdAt": _text(item.get("createdAt"), item.get("created_at") or ""),
        "promptSnapshot": _text(item.get("promptSnapshot"), item.get("prompt_snapshot") or ""),
        "renderPass": render_pass,
        "workflowId": _text(item.get("workflowId"), item.get("workflow_id") or "") or None,
        "videoWorkflowFamily": _text(
            item.get("videoWorkflowFamily"), item.get("video_workflow_family") or "",
        ) or None,
        "options": dict(options),
    }


def _normalize_shot(raw: Any, index: int, *, scene_location: str = "") -> dict[str, Any]:
    item = _as_dict(raw)
    explicit_bindings = item.get("characterBindings") is not None or item.get("character_bindings") is not None
    explicit_location = item.get("locationId") is not None or item.get("location_id") is not None
    explicit_props = item.get("propIds") is not None or item.get("prop_ids") is not None
    names = item.get("characterNames")
    if names is None:
        names = item.get("character_names")
    character_names = [repair_utf8_mojibake(str(name).strip()) for name in _as_list(names) if str(name).strip()]
    bindings = _normalize_character_bindings(
        item.get("characterBindings") if item.get("characterBindings") is not None else item.get("character_bindings")
    )
    prop_ids = _string_list(item.get("propIds") if item.get("propIds") is not None else item.get("prop_ids"))
    prop_names = _string_list(item.get("propNames") if item.get("propNames") is not None else item.get("prop_names"))
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
    try:
        active_take = int(item.get("activeTakeIndex") if item.get("activeTakeIndex") is not None else item.get("active_take_index") or 0)
    except (TypeError, ValueError):
        active_take = 0
    shot: dict[str, Any] = {
        "id": _text(item.get("id")) or _new_id("shot"),
        "shotNumber": int(item.get("shotNumber") or item.get("shot_number") or index + 1),
        "title": title,
        "description": description,
        "promptText": prompt_text,
        "dialogue": normalize_dialogue(item.get("dialogue")),
        "characterNames": character_names,
        "characterBindings": bindings,
        "assetBindingMode": "stable" if explicit_bindings or explicit_location or explicit_props else "legacy",
        "locationName": location_name,
        "locationId": _text(item.get("locationId"), item.get("location_id") or "") or None,
        "propIds": prop_ids,
        "propNames": prop_names,
        "durationSec": duration,
        "compiledPrompt": compiled,
        "jobId": _text(item.get("jobId"), item.get("job_id") or "") or None,
        "status": status,
        "outputVideoUrl": _persistable_media_url(item.get("outputVideoUrl") or item.get("output_video_url")),
        "progress": item.get("progress") if isinstance(item.get("progress"), (int, float)) else 0,
        "takes": [
            _normalize_shot_take(take, take_index)
            for take_index, take in enumerate(_as_list(item.get("takes")))
            if isinstance(take, dict)
        ],
        "camera": _normalize_camera(item.get("camera")),
        "error": _text(item.get("error")) or None,
        "firstFrameUrl": _persistable_media_url(item.get("firstFrameUrl") or item.get("first_frame_url")),
        "firstFramePath": _text(item.get("firstFramePath"), item.get("first_frame_path") or "") or None,
        "firstFrameJobId": _text(item.get("firstFrameJobId"), item.get("first_frame_job_id") or "") or None,
        "endFrameUrl": _persistable_media_url(item.get("endFrameUrl") or item.get("end_frame_url")),
        "endFramePath": _text(item.get("endFramePath"), item.get("end_frame_path") or "") or None,
        "endFrameJobId": _text(item.get("endFrameJobId"), item.get("end_frame_job_id") or "") or None,
        "stillUrl": _persistable_media_url(item.get("stillUrl") or item.get("still_url")),
        "stillJobId": _text(item.get("stillJobId"), item.get("still_job_id") or "") or None,
        "stillStatus": _text(item.get("stillStatus"), item.get("still_status") or "") or None,
        "usePreviousEndFrame": _as_bool(item.get("usePreviousEndFrame", item.get("use_previous_end_frame"))),
        "approvedTakeId": _text(item.get("approvedTakeId"), item.get("approved_take_id") or "") or None,
        "activeTakeIndex": max(0, active_take),
        "speakerName": _text(item.get("speakerName"), item.get("speaker_name") or "") or None,
        "voiceId": _text(item.get("voiceId"), item.get("voice_id") or "") or None,
        "ttsStatus": _text(item.get("ttsStatus"), item.get("tts_status") or "idle") or "idle",
        "ttsUrl": _persistable_media_url(item.get("ttsUrl") or item.get("tts_url")),
        "ttsPath": _text(item.get("ttsPath"), item.get("tts_path") or "") or None,
        "ttsError": _text(item.get("ttsError"), item.get("tts_error") or "") or None,
    }
    soundscape = _text(item.get("soundscape"))
    if soundscape:
        shot["soundscape"] = soundscape
    soundscape_en = _text(item.get("soundscapeEn"), item.get("soundscape_en") or "")
    if soundscape_en:
        shot["soundscapeEn"] = soundscape_en
    timing_note = _text(item.get("timingNote"), item.get("timing_note") or "")
    if timing_note:
        shot["timingNote"] = timing_note
    continuity_in = _text(item.get("continuityIn"), item.get("continuity_in") or "")
    if continuity_in:
        shot["continuityIn"] = continuity_in
    continuity_out = _text(item.get("continuityOut"), item.get("continuity_out") or "")
    if continuity_out:
        shot["continuityOut"] = continuity_out
    transition_note = _text(item.get("transitionNote"), item.get("transition_note") or "")
    if transition_note:
        shot["transitionNote"] = transition_note
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
    profile = _text(target.get("weightProfile"), source.get("weight_profile") or "")
    target["weightProfile"] = profile if profile in {"full", "pruned"} else "full"


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


def _asset_name_key(value: Any) -> str:
    return "".join(_text(value).lower().split())


def _resolve_recipe_asset_bindings(recipe: dict[str, Any]) -> None:
    characters = [item for item in _as_list(recipe.get("characters")) if isinstance(item, dict)]
    props = [item for item in _as_list(recipe.get("props")) if isinstance(item, dict)]
    locations = [item for item in _as_list(recipe.get("locations")) if isinstance(item, dict)]
    characters_by_id = {_text(item.get("id")): item for item in characters if _text(item.get("id"))}
    characters_by_name = {_asset_name_key(item.get("name")): item for item in characters if _asset_name_key(item.get("name"))}
    props_by_id = {_text(item.get("id")): item for item in props if _text(item.get("id"))}
    props_by_name = {_asset_name_key(item.get("name")): item for item in props if _asset_name_key(item.get("name"))}
    locations_by_id = {_text(item.get("id")): item for item in locations if _text(item.get("id"))}
    locations_by_name = {_asset_name_key(item.get("name")): item for item in locations if _asset_name_key(item.get("name"))}

    for shot in flatten_recipe_shots(recipe):
        resolved_bindings: list[dict[str, str]] = []
        seen_characters: set[str] = set()
        for binding in _normalize_character_bindings(shot.get("characterBindings")):
            character = characters_by_id.get(binding["characterId"])
            if character is None or binding["characterId"] in seen_characters:
                continue
            look = character_look(character, binding.get("lookId"))
            resolved_bindings.append({
                "characterId": binding["characterId"],
                "lookId": _text(_as_dict(look).get("id"), "look-default"),
            })
            seen_characters.add(binding["characterId"])
        for name in _string_list(shot.get("characterNames")):
            character = characters_by_name.get(_asset_name_key(name))
            character_id = _text(_as_dict(character).get("id"))
            if not character_id or character_id in seen_characters:
                continue
            look = character_look(character)
            resolved_bindings.append({
                "characterId": character_id,
                "lookId": _text(_as_dict(look).get("id"), "look-default"),
            })
            seen_characters.add(character_id)
        shot["characterBindings"] = resolved_bindings
        canonical_names = [
            _text(_as_dict(characters_by_id.get(binding["characterId"])).get("name"))
            for binding in resolved_bindings
        ]
        unmatched_names = [
            name for name in _string_list(shot.get("characterNames"))
            if _asset_name_key(name) not in characters_by_name
        ]
        shot["characterNames"] = [name for name in canonical_names + unmatched_names if name]

        location = locations_by_id.get(_text(shot.get("locationId")))
        if location is None:
            location = locations_by_name.get(_asset_name_key(shot.get("locationName")))
        shot["locationId"] = _text(_as_dict(location).get("id")) or None
        if location is not None:
            shot["locationName"] = _text(location.get("name"))

        resolved_prop_ids: list[str] = []
        for prop_id in _string_list(shot.get("propIds")):
            if prop_id in props_by_id and prop_id not in resolved_prop_ids:
                resolved_prop_ids.append(prop_id)
        for name in _string_list(shot.get("propNames")):
            prop_id = _text(_as_dict(props_by_name.get(_asset_name_key(name))).get("id"))
            if prop_id and prop_id not in resolved_prop_ids:
                resolved_prop_ids.append(prop_id)
        shot["propIds"] = resolved_prop_ids
        shot["propNames"] = [_text(props_by_id[prop_id].get("name")) for prop_id in resolved_prop_ids]


def normalize_recipe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = _as_dict(payload)
    script_raw = _as_dict(raw.get("script"))
    normalized = empty_recipe_payload(
        title=_text(script_raw.get("title"), raw.get("title") or ""),
        summary=_text(script_raw.get("summary"), raw.get("summary") or ""),
        full_story=_text(script_raw.get("fullStory"), script_raw.get("full_story") or raw.get("fullStory") or ""),
    )
    _copy_render_settings(raw, normalized)
    normalized["assetSchemaVersion"] = 2
    normalized["artStyle"] = resolve_recipe_art_style(raw.get("artStyle") or raw.get("art_style"))
    normalized["characters"] = [
        _normalize_character(item, index) for index, item in enumerate(_as_list(raw.get("characters")))
    ]
    normalized["props"] = [
        _normalize_prop(item, index) for index, item in enumerate(_as_list(raw.get("props")))
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
    _resolve_recipe_asset_bindings(normalized)
    normalized["agentStatus"] = _normalize_agent_status(raw.get("agentStatus") or raw.get("agent_status"))
    normalized["pipelineRun"] = _normalize_pipeline_run(raw.get("pipelineRun") or raw.get("pipeline_run"))
    normalized["audio"] = normalize_audio_mix(raw.get("audio"))
    normalized["subtitles"] = normalize_subtitle_style(raw.get("subtitles"))
    normalized["export"] = normalize_export_state(raw.get("export"))
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
    *,
    message: str | None = None,
) -> dict[str, Any]:
    statuses = _normalize_agent_status(recipe.get("agentStatus"))
    resolved = status if status in AGENT_STATUSES else "pending"
    for item in statuses:
        if item["id"] != agent_id:
            continue
        item["status"] = resolved
        item["error"] = None if not error else str(error)
        if message is not None:
            item["message"] = str(message).strip() or None
        elif resolved == "pending":
            item["message"] = None
        elif resolved == "running":
            item["message"] = AGENT_RUNNING_MESSAGES.get(agent_id)
        elif resolved == "completed":
            item["message"] = agent_done_message(agent_id, recipe)
    recipe["agentStatus"] = statuses
    return recipe


STALE_PIPELINE_INTERRUPT = "服务已重启，生成中断。请重新点生成。"


def interrupt_stale_pipeline(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Clear a Recipe left `running` after the process died mid-request."""
    if not isinstance(payload, dict) or payload_kind(payload) != PAYLOAD_KIND_RECIPE:
        return None
    recipe = normalize_recipe_payload(payload)
    run = recipe.get("pipelineRun") if isinstance(recipe.get("pipelineRun"), dict) else {}
    running_ids = [item["id"] for item in recipe.get("agentStatus") or [] if item.get("status") == "running"]
    if not run.get("active") and not running_ids:
        return None
    for agent_id in running_ids:
        set_agent_status(recipe, agent_id, "failed", STALE_PIPELINE_INTERRUPT, message="")
    recipe["pipelineRun"] = {"agents": list(run.get("agents") or []), "active": False}
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
