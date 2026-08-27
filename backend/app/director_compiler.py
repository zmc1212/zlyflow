from __future__ import annotations

from typing import Any

from .workflow_registry import (
    DEFAULT_DIRECTOR_WORKFLOW_FAMILY, H3_DURATION_MAX_SEC, H3_DURATION_MIN_SEC, H3_FPS,
    h3_length, resolve_director_workflow,
)

H3_MIN_DURATION_SEC = H3_DURATION_MIN_SEC
H3_MAX_DURATION_SEC = H3_DURATION_MAX_SEC
H3_MAX_REFERENCE_IMAGES = 9
H3_WORD_COUNT_WARN = 500

WORKFLOW_T2V = "minimax-h3-t2v"
WORKFLOW_I2V = "minimax-h3-i2v"
WORKFLOW_R2V = "minimax-h3-r2v"

H3_SCALE_PHRASES = {
    "ELS": "an extreme long shot",
    "WS": "a wide shot",
    "MS": "a medium shot",
    "CU": "a close-up",
    "ECU": "an extreme close-up",
}
H3_ANGLE_PHRASES = {
    "eye_level": "eye-level",
    "low_angle": "low-angle",
    "high_angle": "high-angle",
    "dutch": "dutch-angle",
    "pov": "POV",
}
H3_LIGHTING_PHRASES = {
    "cinematic_soft": "soft cinematic lighting",
    "cyberpunk": "neon cyberpunk lighting",
    "golden_hour": "golden-hour backlight",
    "dramatic_low_key": "dramatic low-key lighting",
    "studio": "clean studio lighting",
}
H3_CAMERA_ACTIONS = {
    "zoom_in": "pushes in",
    "zoom_out": "pulls out",
    "pan_left": "pans left",
    "pan_right": "pans right",
    "tilt_up": "tilts up",
    "tilt_down": "tilts down",
    "orbit": "moves in an arc shot around the subject",
    "tracking": "follows with a tracking shot",
    "static": "holds a static shot",
}


def _get(obj: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not isinstance(obj, dict):
        return default
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return default


def snap_h3_duration_sec(value: Any) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return H3_MIN_DURATION_SEC
    if numeric != numeric or numeric in {float("inf"), float("-inf")}:
        return H3_MIN_DURATION_SEC
    return max(H3_MIN_DURATION_SEC, min(H3_MAX_DURATION_SEC, int(round(numeric))))


def h3_aligned_frames(duration_sec: Any, fps: int = H3_FPS) -> int:
    return h3_length({"duration": snap_h3_duration_sec(duration_sec)})


DIRECTOR_QUALITIES = {"0.4", "0.7", "1.0", "2.0"}
DIRECTOR_SPEEDS = {"fast", "balanced", "quality"}
DIRECTOR_PREVIEW_QUALITY = "0.4"
DIRECTOR_PREVIEW_SPEED = "fast"
DIRECTOR_FINAL_QUALITY = "1.0"
DIRECTOR_FINAL_SPEED = "balanced"


def registry_quality_for_canvas(tier: str | None) -> str:
    if tier == "fast":
        return "0.4"
    if tier == "past_native":
        return "2.0"
    return "1.0"


def _normalize_quality(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text in DIRECTOR_QUALITIES else fallback


def _normalize_speed(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text in DIRECTOR_SPEEDS else fallback


def director_job_options(
    render_pass: str | None,
    canvas_tier: str | None = None,
    project: dict[str, Any] | None = None,
) -> dict[str, str]:
    canvas = canvas_tier or (_get(project, "canvasTier", "canvas_tier") if project else None)
    if render_pass == "preview":
        return {
            "quality": _normalize_quality(_get(project, "previewQuality", "preview_quality") if project else None, DIRECTOR_PREVIEW_QUALITY),
            "speed": _normalize_speed(_get(project, "previewSpeed", "preview_speed") if project else None, DIRECTOR_PREVIEW_SPEED),
            "renderPass": "preview",
        }
    final_quality = _get(project, "finalQuality", "final_quality") if project else None
    return {
        "quality": _normalize_quality(final_quality, registry_quality_for_canvas(canvas)),
        "speed": _normalize_speed(_get(project, "finalSpeed", "final_speed") if project else None, DIRECTOR_FINAL_SPEED),
        "renderPass": "final",
    }


def picture_tag(index: int) -> str:
    return f"<Picture {index}>"


def count_words(text: str) -> int:
    return len([part for part in (text or "").split() if part])


def h3_timecode(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000)))
    minutes, rest = divmod(total_ms, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text or "")


def _dialogue_language_tag(text: str) -> str:
    return "Chinese" if _contains_cjk(text) else "English"


def _camera_amplitude_speed(speed: str) -> tuple[str, str]:
    if speed == "dynamic":
        return "with large amplitude", "at fast speed"
    return "with small amplitude", "at slow speed"


def h3_camera_sentence(camera: dict[str, Any] | None) -> str:
    item = camera if isinstance(camera, dict) else {}
    movement = str(_get(item, "movement", default="zoom_in") or "zoom_in")
    speed = str(_get(item, "speed", default="smooth") or "smooth")
    action = H3_CAMERA_ACTIONS.get(movement, H3_CAMERA_ACTIONS["zoom_in"])
    if movement == "static":
        return "The camera holds a static shot."
    if movement == "pov":
        return "The camera holds a POV shot."
    amplitude, tempo = _camera_amplitude_speed(speed)
    if movement in {"orbit", "tracking"}:
        return f"The camera {action} {amplitude} {tempo}."
    return f"The camera {action} {amplitude} {tempo}."


def _has_camera_prose(text: str) -> bool:
    lowered = (text or "").casefold()
    return "the camera" in lowered or "a static shot" in lowered or "tracking shot" in lowered


def _has_scale_prose(text: str) -> bool:
    lowered = (text or "").casefold()
    markers = (
        "extreme long shot", "wide shot", "medium-wide", "medium shot", "medium-close",
        "close-up", "extreme close-up", "close up", "establishing shot",
    )
    return any(marker in lowered for marker in markers)


def _wrap_dialogue(text: str, shot: dict[str, Any]) -> str:
    dialogue = str(_get(shot, "dialogue", default="") or "").strip()
    if not dialogue:
        return text
    if "<d>" in (text or ""):
        return text
    names = [str(name).strip() for name in (_get(shot, "characterNames", "character_names", default=[]) or []) if str(name).strip()]
    speaker = names[0] if names else "the on-screen speaker"
    tag = _dialogue_language_tag(dialogue)
    line = f" {speaker} (S1) says: <d>[{tag}] {dialogue}</d>"
    base = text.rstrip(". ")
    return f"{base}.{line}"


def build_h3_shot_body(shot: dict[str, Any]) -> str:
    camera = _get(shot, "camera", default={}) or {}
    visual = str(_get(shot, "prompt", "description", default="") or "").strip()
    scale = str(_get(camera, "scale", default="MS") or "MS")
    angle = str(_get(camera, "angle", default="eye_level") or "eye_level")
    lighting = str(_get(camera, "lighting", default="cinematic_soft") or "cinematic_soft")
    if visual and not _has_scale_prose(visual):
        scale_phrase = H3_SCALE_PHRASES.get(scale, H3_SCALE_PHRASES["MS"])
        angle_phrase = H3_ANGLE_PHRASES.get(angle, H3_ANGLE_PHRASES["eye_level"])
        visual = f"{scale_phrase} at {angle_phrase} frames the scene. {visual}".strip()
    if visual and not _has_camera_prose(visual):
        visual = f"{visual.rstrip('. ')}. {h3_camera_sentence(camera)}".strip()
    lighting_phrase = H3_LIGHTING_PHRASES.get(lighting, "")
    if lighting_phrase and lighting_phrase.casefold() not in (visual or "").casefold():
        visual = f"{visual.rstrip('. ')}. {lighting_phrase[0].upper() + lighting_phrase[1:]}.".strip()
    visual = _wrap_dialogue(visual, shot)
    return visual.strip()


def build_formatted_shot_prompt(shot: dict[str, Any]) -> str:
    return build_h3_shot_body(shot)


def _slot_has_image(slot: dict[str, Any]) -> bool:
    return bool(
        _get(slot, "file", "hasImage", "previewUrl", "preview_url")
        or _get(slot, "has_image")
    )


def _shot_has_first_frame(shot: dict[str, Any] | None) -> bool:
    return bool(_get(shot, "firstFrameFile", "firstFrameUrl", "first_frame_file", "first_frame_url", "hasFirstFrame"))


def _shot_has_last_frame(shot: dict[str, Any] | None) -> bool:
    return bool(_get(shot, "endFrameFile", "endFrameUrl", "end_frame_file", "end_frame_url", "hasLastFrame"))


def active_subject_slots(project: dict[str, Any]) -> list[dict[str, Any]]:
    refs_mode = _get(project, "refsMode", "refs_mode", default="refs_on")
    if refs_mode != "refs_on":
        return []
    slots = list(_get(project, "subjectSlots", "subject_slots", default=[]) or [])
    active = [slot for slot in slots if isinstance(slot, dict) and _slot_has_image(slot)]
    return sorted(active, key=lambda slot: int(_get(slot, "slotIndex", "slot_index", default=0) or 0))


def sum_shot_duration_sec(shots: list[dict[str, Any]] | None) -> int:
    return sum(snap_h3_duration_sec(_get(shot, "durationSec", "duration_sec", default=5)) for shot in (shots or []))


def clip_duration_sec(shots: list[dict[str, Any]] | None) -> tuple[int, bool]:
    duration = sum_shot_duration_sec(shots)
    return duration, H3_MIN_DURATION_SEC <= duration <= H3_MAX_DURATION_SEC


def _route_kind(subject_count: int, has_first: bool, has_last: bool) -> str:
    if subject_count > 0:
        return "r2v"
    if has_first or has_last:
        return "i2v"
    return "t2v"


def _project_workflow_family(project: dict[str, Any] | None) -> str:
    return str(_get(project, "videoWorkflowFamily", "video_workflow_family", default="") or DEFAULT_DIRECTOR_WORKFLOW_FAMILY)


def _route_workflow(subject_count: int, has_first: bool, has_last: bool, family: str | None = None) -> str:
    return resolve_director_workflow(family, _route_kind(subject_count, has_first, has_last))


def build_reference_plan(project: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []
    subjects = active_subject_slots(project)
    items: list[dict[str, Any]] = []
    picture_index = 1

    if _shot_has_first_frame(shot):
        items.append({
            "pictureIndex": picture_index,
            "role": "first_frame",
            "label": f"首帧 → {picture_tag(picture_index)}",
            "hasImage": True,
        })
        picture_index += 1

    if not subjects and _shot_has_last_frame(shot):
        items.append({
            "pictureIndex": picture_index,
            "role": "last_frame",
            "label": f"尾帧 → {picture_tag(picture_index)}",
            "hasImage": True,
        })
        picture_index += 1

    for slot in subjects:
        slot_id = str(_get(slot, "id", default=f"@ref{picture_index}"))
        slot_index = int(_get(slot, "slotIndex", "slot_index", default=picture_index) or picture_index)
        items.append({
            "pictureIndex": picture_index,
            "role": "subject",
            "label": f"{slot_id} → {picture_tag(picture_index)}",
            "slotId": slot_id,
            "slotIndex": slot_index,
            "hasImage": True,
        })
        picture_index += 1

    if len(items) > H3_MAX_REFERENCE_IMAGES:
        errors.append(f"参考图总数 ({len(items)}) 超过 MiniMax H3 上限 {H3_MAX_REFERENCE_IMAGES} 张")

    family = _project_workflow_family(project)
    route = _route_kind(len(subjects), _shot_has_first_frame(shot), _shot_has_last_frame(shot))
    return {
        "items": items,
        "route": route,
        "workflowId": resolve_director_workflow(family, route),
        "warnings": warnings,
        "errors": errors,
    }


def build_clip_reference_plan(project: dict[str, Any]) -> dict[str, Any]:
    shots = list(_get(project, "shots", default=[]) or [])
    if not shots:
        return {"items": [], "route": "t2v", "workflowId": resolve_director_workflow(_project_workflow_family(project), "t2v"), "warnings": [], "errors": []}
    first = dict(shots[0])
    last = shots[-1]
    first["endFrameFile"] = _get(last, "endFrameFile", "end_frame_file")
    first["endFrameUrl"] = _get(last, "endFrameUrl", "end_frame_url")
    first["hasLastFrame"] = _shot_has_last_frame(last)
    return build_reference_plan(project, first)


def replace_ref_tags(text: str, plan: dict[str, Any]) -> str:
    result = text or ""
    for item in plan.get("items") or []:
        if item.get("role") != "subject" or not item.get("slotId"):
            continue
        result = result.replace(str(item["slotId"]), picture_tag(int(item["pictureIndex"])))
    return result


def _subject_definition_lines(project: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    slots = {str(_get(slot, "id")): slot for slot in (_get(project, "subjectSlots", "subject_slots", default=[]) or []) if isinstance(slot, dict)}
    lines: list[str] = []
    for item in plan.get("items") or []:
        role = item.get("role")
        tag = picture_tag(int(item["pictureIndex"]))
        if role == "first_frame":
            lines.append(f"{tag} is the first frame of [Shot 1].")
            continue
        if role == "last_frame":
            lines.append(f"{tag} is the last frame of the final shot.")
            continue
        if role != "subject" or not item.get("slotId"):
            continue
        slot = slots.get(str(item["slotId"]))
        if not slot:
            continue
        description = str(_get(slot, "description", default="") or "").strip()
        desc_part = f" {description}" if description else ""
        kind = _get(slot, "kind", default="character")
        slot_index = _get(slot, "slotIndex", "slot_index", default=item.get("slotIndex"))
        lines.append(f"<Subject {slot_index}> is the {kind}{desc_part} shown in {tag}.")
    return lines


def _subject_definitions(project: dict[str, Any], plan: dict[str, Any]) -> str:
    lines = _subject_definition_lines(project, plan)
    if not lines:
        return ""
    return "subject_definitions:\n" + "\n".join(lines)


def _english_audio_text(*candidates: str, fallback: str) -> str:
    for text in candidates:
        value = (text or "").strip()
        if value and not _contains_cjk(value) and value.casefold() != "n/a":
            return value
        if value.casefold() == "n/a":
            return "N/A"
    return fallback


def _shot_soundscape(project: dict[str, Any], shots: list[dict[str, Any]]) -> str:
    shot_texts: list[str] = []
    for shot in shots:
        shot_texts.append(str(_get(shot, "soundscape", default="") or "").strip())
        camera = _get(shot, "camera", default={}) or {}
        shot_texts.append(str(_get(camera, "sfx", default="") or "").strip())
    global_sound = str(_get(project, "globalSoundscape", "global_soundscape", default="") or "").strip()
    return _english_audio_text(*shot_texts, global_sound, fallback="Natural room tone and physical action sounds matching the on-screen movement.")


def _non_diegetic_music(project: dict[str, Any]) -> str:
    music = str(_get(project, "globalMusic", "global_music", default="") or "").strip()
    return _english_audio_text(music, fallback="N/A")


def _is_r2v(plan: dict[str, Any]) -> bool:
    return plan.get("route") == "r2v" or str(plan.get("workflowId") or "").endswith("-r2v")


def _is_i2v(plan: dict[str, Any]) -> bool:
    return plan.get("route") == "i2v" or str(plan.get("workflowId") or "").endswith("-i2v")


def _keyframe_alignment(plan: dict[str, Any], duration_sec: float) -> str:
    first = next((item for item in plan.get("items") or [] if item.get("role") == "first_frame"), None)
    last = next((item for item in plan.get("items") or [] if item.get("role") == "last_frame"), None)
    if first and last:
        end = f"{float(duration_sec):.2f}"
        return (
            "How the reference pictures align with the target video — "
            f"Picture {int(first['pictureIndex'])} (from Shot 1) aligns with the 0.00-second mark of the target video; "
            f"Picture {int(last['pictureIndex'])} (from Shot 1) aligns with the {end}-second mark of the target video."
        )
    if first:
        return (
            "For the target video, at 0.00 seconds into the target video, "
            f"{picture_tag(int(first['pictureIndex']))} (from [Shot 1]) is fully referenced."
        )
    if last:
        end = f"{float(duration_sec):.2f}"
        return (
            "How the reference pictures align with the target video — "
            f"{picture_tag(int(last['pictureIndex']))} (from [Shot 1]) aligns with the {end}-second mark of the target video."
        )
    return ""


def _shot_visual_body(shot: dict[str, Any], plan: dict[str, Any]) -> str:
    body = replace_ref_tags(build_h3_shot_body(shot), plan)
    first_frame = next((item for item in plan.get("items") or [] if item.get("role") == "first_frame"), None)
    last_frame = next((item for item in plan.get("items") or [] if item.get("role") == "last_frame"), None)
    if first_frame and "begins from" not in body.casefold():
        body = f"{body.rstrip('. ')}. The shot begins from {picture_tag(int(first_frame['pictureIndex']))}."
    if last_frame and "ends on" not in body.casefold() and _is_i2v(plan):
        body = f"{body.rstrip('. ')}. The shot ends on {picture_tag(int(last_frame['pictureIndex']))}."
    return body.strip()


def _timeline_description(shots: list[dict[str, Any]], plan: dict[str, Any]) -> str:
    cursor = 0.0
    blocks: list[str] = []
    for index, shot in enumerate(shots):
        shot_duration = snap_h3_duration_sec(_get(shot, "durationSec", "duration_sec", default=5))
        body = _shot_visual_body(shot, plan)
        if index == 0:
            blocks.append(f"[Shot 1] {body}")
        else:
            blocks.append(f"[Shot {index + 1}] At {h3_timecode(cursor)}, the camera cuts to {body}")
        cursor += shot_duration
    return " ".join(blocks).strip()


def _retention_analysis(project: dict[str, Any], plan: dict[str, Any]) -> str:
    lines: list[str] = []
    for item in plan.get("items") or []:
        role = item.get("role")
        tag = picture_tag(int(item["pictureIndex"]))
        if role == "first_frame":
            lines.append(f"{tag} ([Shot 1] first frame): fully_preserved - the opening composition, subjects, and lighting remain the starting state of [Shot 1].")
        elif role == "last_frame":
            lines.append(f"{tag} (final frame): fully_preserved - the closing composition is reached by the end of the final shot.")
        elif role == "subject":
            slot_index = item.get("slotIndex") or item.get("pictureIndex")
            retention = "fully_preserved"
            slots = _get(project, "subjectSlots", "subject_slots", default=[]) or []
            slot = next((candidate for candidate in slots if str(_get(candidate, "id")) == str(item.get("slotId"))), None)
            if isinstance(slot, dict):
                retention = str(_get(slot, "retention", default="fully_preserved") or "fully_preserved")
                slot_index = _get(slot, "slotIndex", "slot_index", default=slot_index)
            marker = retention if retention in {"fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference"} else "fully_preserved"
            if retention == "strong":
                marker = "fully_preserved"
            elif retention == "weak":
                marker = "weak_reference"
            lines.append(f"<Subject {slot_index}> (appears in [Shot 1]): {marker} - identity, costume, and key visual features are retained.")
    return "\n".join(lines)


def _ref2va_summary(plan: dict[str, Any]) -> str:
    has_keyframe = any(item.get("role") in {"first_frame", "last_frame"} for item in plan.get("items") or [])
    has_subject = any(item.get("role") == "subject" for item in plan.get("items") or [])
    types: list[str] = []
    if has_keyframe:
        types.append("keyframe completion")
    if has_subject:
        types.append("reference generation")
    prefix = " + ".join(types) or "reference generation"
    return f"[{prefix}] The target video follows the referenced subjects and keyframes while playing the described actions, camera moves, and diegetic sound."


def assemble_h3_prompt(
    project: dict[str, Any],
    shots: list[dict[str, Any]],
    plan: dict[str, Any],
    duration_sec: float,
) -> str:
    description = _timeline_description(shots, plan)
    soundscape = _shot_soundscape(project, shots)
    music = _non_diegetic_music(project)
    if _is_r2v(plan):
        definitions = _subject_definitions(project, plan)
        retention = _retention_analysis(project, plan)
        sections = [
            definitions,
            f"summary:\n{_ref2va_summary(plan)}",
            f"retention_analysis:\n{retention}" if retention else "",
            f"detailed_description:\n{description}",
            f"overall_soundscape:\n{soundscape}",
            f"non_diegetic_music:\n{music}",
        ]
        return "\n\n".join(part for part in sections if part).strip()

    sections: list[str] = []
    alignment = _keyframe_alignment(plan, duration_sec) if _is_i2v(plan) else ""
    if alignment:
        sections.append(alignment)
    sections.extend([
        f"integrated_multimodal_description: {description}",
        f"overall_soundscape: {soundscape}",
        f"non_diegetic_music: {music}",
    ])
    return "\n\n".join(sections).strip()


def compile_shot_prompt(project: dict[str, Any], shot: dict[str, Any], plan: dict[str, Any] | None = None) -> str:
    plan = plan or build_reference_plan(project, shot)
    duration = snap_h3_duration_sec(_get(shot, "durationSec", "duration_sec", default=5))
    return assemble_h3_prompt(project, [shot], plan, duration)


def compile_clip_prompt(project: dict[str, Any]) -> dict[str, Any]:
    shots = list(_get(project, "shots", default=[]) or [])
    warnings: list[str] = []
    errors: list[str] = []
    duration, allowed = clip_duration_sec(shots)
    empty_plan = {"items": [], "route": "t2v", "workflowId": resolve_director_workflow(_project_workflow_family(project), "t2v"), "warnings": [], "errors": []}
    if not shots:
        errors.append("没有可编译的分镜")
        return {"allowed": False, "prompt": "", "durationSec": H3_MIN_DURATION_SEC, "plan": empty_plan, "warnings": warnings, "errors": errors}
    if not allowed:
        errors.append(
            f"选中分镜合计 {duration}s，整段提交必须在 {H3_MIN_DURATION_SEC}–{H3_MAX_DURATION_SEC} 秒；请改为逐镜接龙"
        )
        return {"allowed": False, "prompt": "", "durationSec": duration, "plan": empty_plan, "warnings": warnings, "errors": errors}

    plan = build_clip_reference_plan(project)
    errors.extend(plan.get("errors") or [])
    warnings.extend(plan.get("warnings") or [])
    prompt = assemble_h3_prompt(project, shots, plan, duration)
    word_count = count_words(prompt)
    if word_count > H3_WORD_COUNT_WARN:
        warnings.append(f"提示词总词数 ({word_count} words) 超过官方推荐的 {H3_WORD_COUNT_WARN} 词上限，建议精简分镜描述。")
    return {
        "allowed": not errors,
        "prompt": prompt,
        "durationSec": duration,
        "plan": plan,
        "warnings": warnings,
        "errors": errors,
        "wordCount": word_count,
    }


def _override_text(project: dict[str, Any]) -> str:
    if not _get(project, "manualPromptOverrideEnabled", "manual_prompt_override_enabled"):
        return ""
    return str(_get(project, "manualPromptOverrideText", "manual_prompt_override_text", default="") or "").strip()


def resolve_shot_submission(project: dict[str, Any], shot: dict[str, Any], render_pass: str = "final") -> dict[str, Any]:
    plan = build_reference_plan(project, shot)
    duration = snap_h3_duration_sec(_get(shot, "durationSec", "duration_sec", default=5))
    override = _override_text(project)
    prompt = override or compile_shot_prompt(project, shot, plan)
    _, clip_allowed = clip_duration_sec(_get(project, "shots", default=[]))
    job = director_job_options(render_pass, _get(project, "canvasTier", "canvas_tier"), project)
    return {
        "workflowId": plan["workflowId"],
        "prompt": prompt,
        "durationSec": duration,
        "aspectRatio": _get(project, "aspectRatio", "aspect_ratio", default="16:9"),
        "quality": job["quality"],
        "speed": job["speed"],
        "renderPass": job["renderPass"],
        "plan": plan,
        "isOverride": bool(override),
        "isClip": False,
        "clipAllowed": clip_allowed,
        "totalFrames": h3_aligned_frames(duration),
        "errors": list(plan.get("errors") or []),
        "warnings": list(plan.get("warnings") or []),
    }


def resolve_clip_submission(project: dict[str, Any], render_pass: str = "final") -> dict[str, Any]:
    compiled = compile_clip_prompt(project)
    override = _override_text(project)
    prompt = override if compiled["allowed"] and override else compiled["prompt"]
    job = director_job_options(render_pass, _get(project, "canvasTier", "canvas_tier"), project)
    return {
        "workflowId": compiled["plan"]["workflowId"],
        "prompt": prompt,
        "durationSec": compiled["durationSec"],
        "aspectRatio": _get(project, "aspectRatio", "aspect_ratio", default="16:9"),
        "quality": job["quality"],
        "speed": job["speed"],
        "renderPass": job["renderPass"],
        "plan": compiled["plan"],
        "isOverride": bool(compiled["allowed"] and override),
        "isClip": True,
        "clipAllowed": compiled["allowed"],
        "totalFrames": h3_aligned_frames(compiled["durationSec"]),
        "errors": list(compiled.get("errors") or []),
        "warnings": list(compiled.get("warnings") or []),
    }


def iter_recipe_shots(recipe: dict[str, Any] | None):
    raw = recipe if isinstance(recipe, dict) else {}
    for scene in raw.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        nested = scene.get("shots")
        if isinstance(nested, list) and nested:
            for shot in nested:
                if isinstance(shot, dict):
                    yield scene, shot
        else:
            yield scene, scene


def recipe_style_prefix(recipe: dict[str, Any] | None) -> str:
    art = _get(recipe, "artStyle", "art_style", default={}) if recipe else {}
    if not isinstance(art, dict):
        return ""
    return str(art.get("promptPrefix") or art.get("prompt_prefix") or "").strip()


def _asset_has_plate(asset: dict[str, Any] | None) -> bool:
    if not isinstance(asset, dict):
        return False
    return bool(
        _get(asset, "imageUrl", "image_url")
        or _get(asset, "imageJobId", "image_job_id")
        or _get(asset, "previewUrl", "preview_url")
        or _get(asset, "file", "hasImage")
    )


def recipe_assets_as_slots(recipe: dict[str, Any], shot: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Pack character/location plates used by a shot into ≤9 H3 subject slots."""
    recipe = recipe if isinstance(recipe, dict) else {}
    shot = shot if isinstance(shot, dict) else {}
    characters = [item for item in (recipe.get("characters") or []) if isinstance(item, dict)]
    locations = [item for item in (recipe.get("locations") or []) if isinstance(item, dict)]
    named = {str(name).strip() for name in (shot.get("characterNames") or shot.get("character_names") or []) if str(name).strip()}
    location_name = str(_get(shot, "locationName", "location_name", default="") or "").strip()

    selected_chars = [item for item in characters if _asset_has_plate(item)]
    if named:
        selected_chars = [
            item for item in selected_chars
            if str(item.get("name") or "").strip() in named
        ]
        if not selected_chars:
            selected_chars = [item for item in characters if str(item.get("name") or "").strip() in named and _asset_has_plate(item)]

    selected_locs: list[dict[str, Any]] = []
    if location_name:
        selected_locs = [
            item for item in locations
            if str(item.get("name") or "").strip() == location_name and _asset_has_plate(item)
        ]
    if not selected_locs:
        selected_locs = [item for item in locations if _asset_has_plate(item)]

    combined = selected_chars + selected_locs
    if not combined:
        combined = [item for item in characters + locations if _asset_has_plate(item)]

    slots: list[dict[str, Any]] = []
    for index, asset in enumerate(combined[:H3_MAX_REFERENCE_IMAGES]):
        is_location = asset in locations or str(asset.get("type") or "") in {"location", "scene"}
        slots.append({
            "id": f"@ref{index + 1}",
            "slotIndex": index + 1,
            "name": str(asset.get("name") or f"主体 {index + 1}"),
            "kind": "scene" if is_location else ("prop" if str(asset.get("type") or "") == "object" else "character"),
            "retention": "fully_preserved",
            "description": str(asset.get("promptText") or asset.get("prompt_text") or asset.get("description") or "").strip(),
            "previewUrl": _get(asset, "imageUrl", "image_url", "previewUrl"),
            "imageJobId": _get(asset, "imageJobId", "image_job_id"),
            "hasImage": True,
            "file": True,
        })
    return slots


def recipe_shot_as_timeline_shot(recipe: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    prefix = recipe_style_prefix(recipe)
    h3_body = ""
    for key in ("promptText", "prompt_text", "prompt", "description"):
        h3_body = str(_get(shot, key, default="") or "").strip()
        if h3_body:
            break
    visual = f"{prefix}. {h3_body}".strip(". ").strip() if prefix else h3_body
    timeline_shot = {
        "id": shot.get("id"),
        "title": shot.get("title"),
        "prompt": visual or h3_body,
        "dialogue": _get(shot, "dialogue", default="") or "",
        "durationSec": snap_h3_duration_sec(_get(shot, "durationSec", "duration_sec", default=5)),
        "soundscape": _get(shot, "soundscape", default="") or _get(recipe, "globalSoundscape", "global_soundscape", default=""),
        "camera": _get(shot, "camera", default={}) or {},
        "characterNames": list(shot.get("characterNames") or shot.get("character_names") or []),
    }
    return timeline_shot


def recipe_as_timeline_project(recipe: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    slots = recipe_assets_as_slots(recipe, shot)
    timeline_shot = recipe_shot_as_timeline_shot(recipe, shot)
    return {
        "aspectRatio": _get(recipe, "aspectRatio", "aspect_ratio", default="16:9") or "16:9",
        "canvasTier": _get(recipe, "canvasTier", "canvas_tier", default="native"),
        "previewQuality": _get(recipe, "previewQuality", "preview_quality"),
        "previewSpeed": _get(recipe, "previewSpeed", "preview_speed"),
        "finalQuality": _get(recipe, "finalQuality", "final_quality"),
        "finalSpeed": _get(recipe, "finalSpeed", "final_speed"),
        "refsMode": "refs_on" if slots else "refs_off",
        "subjectSlots": slots,
        "shots": [timeline_shot],
        "globalSoundscape": _get(recipe, "globalSoundscape", "global_soundscape", default=""),
        "globalMusic": _get(recipe, "globalMusic", "global_music", default=""),
        "manualPromptOverrideEnabled": _get(recipe, "manualPromptOverrideEnabled", "manual_prompt_override_enabled"),
        "manualPromptOverrideText": _get(recipe, "manualPromptOverrideText", "manual_prompt_override_text", default=""),
        "videoWorkflowFamily": _get(recipe, "videoWorkflowFamily", "video_workflow_family", default=DEFAULT_DIRECTOR_WORKFLOW_FAMILY),
    }


def resolve_recipe_shot_submission(
    recipe: dict[str, Any],
    shot: dict[str, Any],
    render_pass: str = "final",
) -> dict[str, Any]:
    project = recipe_as_timeline_project(recipe, shot)
    return resolve_shot_submission(project, project["shots"][0], render_pass)


def compile_recipe_media(recipe: dict[str, Any]) -> dict[str, Any]:
    """Write compiled H3 prompts onto each shot. Used by the media agent."""
    for _scene, shot in iter_recipe_shots(recipe):
        submission = resolve_recipe_shot_submission(recipe, shot)
        shot["compiledPrompt"] = submission.get("prompt") or ""
    return recipe
