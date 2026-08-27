from __future__ import annotations

from typing import Any

from .workflow_registry import H3_DURATION_MAX_SEC, H3_DURATION_MIN_SEC, H3_FPS, h3_length

H3_MIN_DURATION_SEC = H3_DURATION_MIN_SEC
H3_MAX_DURATION_SEC = H3_DURATION_MAX_SEC
H3_MAX_REFERENCE_IMAGES = 9
H3_WORD_COUNT_WARN = 500

WORKFLOW_T2V = "minimax-h3-t2v"
WORKFLOW_I2V = "minimax-h3-i2v"
WORKFLOW_R2V = "minimax-h3-r2v"

CAMERA_SCALE_LABELS = {"ELS": "大远景", "WS": "全景", "MS": "中景", "CU": "特写", "ECU": "大特写"}
CAMERA_MOVEMENT_LABELS = {
    "zoom_in": "前推", "zoom_out": "后拉", "pan_left": "左移", "pan_right": "右移",
    "tilt_up": "仰拍运镜", "tilt_down": "俯拍运镜", "orbit": "环绕旋转", "tracking": "跟拍跟随", "static": "定焦静止",
}
CAMERA_ANGLE_LABELS = {
    "eye_level": "平视视平线", "low_angle": "低机位仰角", "high_angle": "高机位俯视",
    "dutch": "倾斜荷兰角", "pov": "第一人称主观",
}
CAMERA_SPEED_LABELS = {"smooth": "平稳电影感", "dynamic": "激烈快动态", "slow": "柔和微动"}
CAMERA_LIGHTING_LABELS = {
    "cinematic_soft": "电影级柔光", "cyberpunk": "赛博霓虹", "golden_hour": "黄金时段逆光",
    "dramatic_low_key": "低调戏剧性", "studio": "纯净影棚布光",
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


def _route_workflow(subject_count: int, has_first: bool, has_last: bool) -> str:
    if subject_count > 0:
        return WORKFLOW_R2V
    if has_first or has_last:
        return WORKFLOW_I2V
    return WORKFLOW_T2V


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

    return {
        "items": items,
        "workflowId": _route_workflow(len(subjects), _shot_has_first_frame(shot), _shot_has_last_frame(shot)),
        "warnings": warnings,
        "errors": errors,
    }


def build_clip_reference_plan(project: dict[str, Any]) -> dict[str, Any]:
    shots = list(_get(project, "shots", default=[]) or [])
    if not shots:
        return {"items": [], "workflowId": WORKFLOW_T2V, "warnings": [], "errors": []}
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


def build_formatted_shot_prompt(shot: dict[str, Any]) -> str:
    camera = _get(shot, "camera", default={}) or {}
    scale = CAMERA_SCALE_LABELS.get(str(_get(camera, "scale", default="MS")), "中景")
    movement = CAMERA_MOVEMENT_LABELS.get(str(_get(camera, "movement", default="zoom_in")), "前推")
    angle = CAMERA_ANGLE_LABELS.get(str(_get(camera, "angle", default="eye_level")), "平视视平线")
    lighting = CAMERA_LIGHTING_LABELS.get(str(_get(camera, "lighting", default="cinematic_soft")), "电影级柔光")
    speed = CAMERA_SPEED_LABELS.get(str(_get(camera, "speed", default="smooth")), "平稳电影感")
    prefix = f"【{scale}，{angle}，镜头{movement}，{speed}，{lighting}】"
    result = str(_get(shot, "prompt", default="") or "").strip()
    if not result.startswith("【"):
        result = f"{prefix} {result}".strip()
    dialogue = str(_get(shot, "dialogue", default="") or "").strip()
    if dialogue:
        result += f"\n[台词对白: {dialogue}]"
    soundscape = str(_get(shot, "soundscape", default="") or "").strip()
    sfx = str(_get(camera, "sfx", default="") or "").strip()
    if soundscape:
        result += f"\n[音效: {soundscape}]"
    elif sfx:
        result += f"\n[环境音效: {sfx}]"
    return result


def _subject_definitions(project: dict[str, Any], plan: dict[str, Any]) -> str:
    slots = {str(_get(slot, "id")): slot for slot in (_get(project, "subjectSlots", "subject_slots", default=[]) or []) if isinstance(slot, dict)}
    lines: list[str] = []
    for item in plan.get("items") or []:
        if item.get("role") != "subject" or not item.get("slotId"):
            continue
        slot = slots.get(str(item["slotId"]))
        if not slot:
            continue
        description = str(_get(slot, "description", default="") or "").strip()
        desc_part = f" {description}" if description else ""
        kind = _get(slot, "kind", default="character")
        retention = _get(slot, "retention", default="fully_preserved")
        slot_index = _get(slot, "slotIndex", "slot_index", default=item.get("slotIndex"))
        lines.append(
            f"<Subject {slot_index}> ({item['slotId']}) is the {kind}{desc_part} shown in {picture_tag(int(item['pictureIndex']))} [retention: {retention}]."
        )
    if not lines:
        return ""
    return "[Subject definitions]:\n" + "\n".join(lines)


def compile_shot_prompt(project: dict[str, Any], shot: dict[str, Any], plan: dict[str, Any] | None = None) -> str:
    plan = plan or build_reference_plan(project, shot)
    sections: list[str] = []
    if plan.get("workflowId") == WORKFLOW_R2V:
        definitions = _subject_definitions(project, plan)
        if definitions:
            sections.append(definitions)
    body = replace_ref_tags(build_formatted_shot_prompt(shot), plan)
    first_frame = next((item for item in plan.get("items") or [] if item.get("role") == "first_frame"), None)
    if first_frame and plan.get("workflowId") == WORKFLOW_R2V:
        body += f"\n(begins from {picture_tag(int(first_frame['pictureIndex']))})"
    sections.append(body)
    return "\n\n".join(sections).strip()


def _task_type_label(workflow_id: str) -> str:
    if workflow_id == WORKFLOW_R2V:
        return "Reference-to-Video (Ref2VA)"
    if workflow_id == WORKFLOW_I2V:
        return "Image-to-Video (I2VA)"
    return "Text-to-Video (T2VA)"


def compile_clip_prompt(project: dict[str, Any]) -> dict[str, Any]:
    shots = list(_get(project, "shots", default=[]) or [])
    warnings: list[str] = []
    errors: list[str] = []
    duration, allowed = clip_duration_sec(shots)
    empty_plan = {"items": [], "workflowId": WORKFLOW_T2V, "warnings": [], "errors": []}
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

    sections: list[str] = [f"[task type]: {_task_type_label(plan['workflowId'])}"]
    soundscape = str(_get(project, "globalSoundscape", "global_soundscape", default="") or "").strip()
    music = str(_get(project, "globalMusic", "global_music", default="") or "").strip()
    if soundscape:
        sections.append(f"[overall_soundscape]: {soundscape}")
    if music:
        sections.append(f"[non_diegetic_music]: {music}")
    definitions = _subject_definitions(project, plan)
    if definitions:
        sections.append(definitions)

    cursor = 0.0
    shot_blocks: list[str] = []
    first_frame = next((item for item in plan.get("items") or [] if item.get("role") == "first_frame"), None)
    for index, shot in enumerate(shots):
        shot_duration = snap_h3_duration_sec(_get(shot, "durationSec", "duration_sec", default=5))
        start, end = cursor, cursor + shot_duration
        cursor = end
        shot_plan = plan
        header = f"[Shot {index + 1}] ({start:.1f}s - {end:.1f}s"
        if index == 0 and first_frame:
            header += f", begins from {picture_tag(int(first_frame['pictureIndex']))}"
        elif _get(shot, "usePreviousEndFrame", "use_previous_end_frame"):
            header += ", corresponds to previous keyframe"
        header += "):"
        body = replace_ref_tags(build_formatted_shot_prompt(shot), shot_plan)
        shot_blocks.append(f"{header} {body}")
    sections.append("[Timeline sequence]:\n" + "\n\n".join(shot_blocks))

    prompt = "\n\n".join(sections).strip()
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
