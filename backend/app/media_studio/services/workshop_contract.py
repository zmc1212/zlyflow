"""The v7 workshop contract: confirmed shots, groups and one prompt per shot.

No model calls or persistence here. Execution segments are derived, never edited.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
import uuid

from ...workflow_registry import workflow_for, H3_STANDARD_OPTION_SCHEMA

VERSION = 7
SHOT_FIELDS = ("heading", "scene", "scene_id", "scene_time", "action", "camera", "dialogue",
               "speaker", "audio", "video_duration", "character_ids", "character_look_ids", "prop_ids",
               "opening_state", "closing_state", "transition_note")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def plan_of(detail):
    return (detail.get("prompt_authoring") or (detail.get("data") or {}).get("prompt_authoring") or {}).get("director_plan") or {}


def unified(detail):
    return plan_of(detail).get("schema_version") == VERSION


def shot_fingerprint(beat):
    return digest({k: beat.get(k) for k in SHOT_FIELDS})


def scene_key(beat):
    return str(beat.get("scene_id") or beat.get("scene") or "").strip() + "|" + str(beat.get("scene_time") or "")


def duration(beat):
    value = float(beat.get("video_duration") or beat.get("duration_seconds") or 0)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("镜头时长必须是有效正数")
    return value


def group_timecode_mode(group):
    return "cumulative" if str(group.get("timecode_mode") or "per_shot") == "cumulative" else "per_shot"


def fmt_timecode(seconds):
    total = max(0.0, float(seconds))
    minutes = int(total // 60)
    return f"{minutes:02}:{total - minutes * 60:05.2f}"


def shot_header(beat, group, ordered_beats=None):
    beat_ids = list(group.get("beat_ids") or [])
    bid = beat.get("id")
    index = beat_ids.index(bid) if bid in beat_ids else 0
    seconds = duration(beat)
    if group_timecode_mode(group) == "cumulative":
        by_id = {b.get("id"): b for b in (ordered_beats or [])}
        start = 0.0
        for previous_id in beat_ids[:index]:
            previous = by_id.get(previous_id)
            if previous:
                start += duration(previous)
        return index + 1, start, start + seconds
    return 1, 0.0, seconds


def validate_groups(beats, groups, workflow_id, maximum):
    definition = workflow_for(workflow_id)
    limit = definition.max_segments or 1
    if type(maximum) is not int or not 1 <= maximum <= limit:
        raise ValueError(f"每组最多镜头数必须在 1～{limit} 之间")
    ids = [b["id"] for b in beats]
    if len(set(ids)) != len(ids) or not ids:
        raise ValueError("镜头清单为空或 ID 重复")
    if not groups or [bid for g in groups for bid in g.get("beat_ids", [])] != ids:
        raise ValueError("分组必须按顺序完整覆盖每个镜头一次")
    if len({g.get("id") for g in groups}) != len(groups) or any(not g.get("id") for g in groups):
        raise ValueError("镜头组 ID 缺失或重复")
    by_id = {b["id"]: b for b in beats}
    duration_rule = ((definition.option_schema or H3_STANDARD_OPTION_SCHEMA).get("properties") or {}).get("duration") or H3_STANDARD_OPTION_SCHEMA["properties"]["duration"]
    for beat in beats:
        seconds = duration(beat)
        if seconds < duration_rule.get("minimum", 0) or seconds > duration_rule.get("maximum", float("inf")):
            raise ValueError(f"镜头时长超出工作流支持范围：{duration_rule.get('minimum')}～{duration_rule.get('maximum')} 秒，请调整规划")
    for group in groups:
        local = [by_id[bid] for bid in group["beat_ids"]]
        if not local or len(local) > maximum or len({scene_key(b) for b in local}) != 1:
            raise ValueError("只能合并同场景、同时间且不超过镜头数上限的相邻镜头")
        if definition.max_total_frames and sum(round(duration(b) * 24) for b in local) > definition.max_total_frames:
            raise ValueError("本组超过工作流时长容量，请在规划中拆组")
        slots = group.get("reference_slots") or []
        if len(slots) > definition.max_references:
            raise ValueError(f"本组最多允许 {definition.max_references} 张最终视频参考图")
        for i, slot in enumerate(slots, 1):
            if not slot.get("image_url") or slot.get("token") != f"<Picture {i}>":
                raise ValueError("参考图片必须有有效地址，并按 Picture 1 起连续编号")


def group_shots(beats, workflow_id, maximum=3):
    definition = workflow_for(workflow_id)
    maximum = min(maximum, definition.max_segments or 1)
    groups = []
    by_id = {b["id"]: b for b in beats}
    for beat in beats:
        frames = round(duration(beat) * 24)
        previous = groups[-1] if groups else None
        if (not previous or len(previous["beat_ids"]) >= maximum
                or scene_key(by_id[previous["beat_ids"][-1]]) != scene_key(beat)
                or definition.max_total_frames and previous["frame_count"] + frames > definition.max_total_frames):
            groups.append({"id": "group-" + uuid.uuid4().hex[:12], "beat_ids": [], "frame_count": 0,
                           "common_prompt": f"保持{beat.get('scene') or '当前场景'}的空间与光线一致，人物沿用剧本中的身份和已选造型。", "reference_slots": [], "reference_policy": "auto", "timecode_mode": "per_shot"})
        groups[-1]["beat_ids"].append(beat["id"])
        groups[-1]["frame_count"] += frames
    for group in groups:
        names = []
        for bid in group["beat_ids"]:
            shot = by_id[bid]
            for name in [*(shot.get("characters") or []), shot.get("speaker")]:
                if isinstance(name, str) and name.strip() and name.strip() not in names:
                    names.append(name.strip())
        group["common_prompt"] += "\n" + "\n".join(
            f"<Subject {index}>：{name}，沿用已采纳剧本与已选造型，组内身份、服饰与声音保持一致。"
            for index, name in enumerate(names, 1)
        )
    if definition.prompt_profile == "director_segments":
        from .workshop_h3_skill import ensure_sound_settings
        ensure_sound_settings(groups, beats)
    validate_groups(beats, groups, workflow_id, maximum)
    return groups


def new_plan(beats, workflow_id, source, previous=None, maximum=3):
    previous = previous or {}
    maximum = min(maximum, workflow_for(workflow_id).max_segments or 1)
    return {"schema_version": VERSION, "id": previous.get("id") if previous.get("schema_version") == VERSION else "plan-" + uuid.uuid4().hex[:12],
            "revision": int(previous.get("revision") or 0) + 1, "planning_revision": int(previous.get("planning_revision") or 0) + 1,
            "source_revision": source["revision"], "source_fingerprint": source["fingerprint"],
            "workflow_id": workflow_id, "aspect_ratio": previous.get("aspect_ratio") or "16:9",
            "max_shots_per_group": maximum, "status": "current", "groups": group_shots(beats, workflow_id, maximum),
            "shot_prompts": {}, "shot_fingerprints": {b["id"]: shot_fingerprint(b) for b in beats}}


def prompt_fingerprint(beat, group, plan):
    return digest([shot_fingerprint(beat), group.get("common_prompt"), group.get("reference_slots"),
                   plan.get("aspect_ratio"), plan.get("workflow_id"), group.get("timecode_mode"),
                   beat.get("workshop_writing_refs") or []])


def content_matches(record, group, plan):
    """Versioned integrity check; old records are not silently migrated."""
    return not record.get("content_digest") or record["content_digest"] == digest([
        record.get("h3_prompt"), group.get("common_prompt"), plan.get("source_fingerprint"), record.get("contract_version")])


def prompt_checks(body, beat, group, *, h3=False, ordered_beats=None):
    errors = []
    if not str(body).strip():
        return ["尚未保存 H3 提示词"]
    if any(int(n) > len(group.get("reference_slots") or []) or int(n) < 1 for n in re.findall(r"<Picture\s+(\d+)>", body, re.I)):
        errors.append("提示词引用了不存在的参考图编号")
    subjects = set(re.findall(r"<Subject\s+(\d+)>", str(group.get("common_prompt") or ""), re.I))
    if set(re.findall(r"<Subject\s+(\d+)>", body, re.I)) - subjects:
        errors.append("提示词引用了组公共设定中未定义的主体编号，请补齐组设定或直接使用人物姓名")
    compact = lambda text: re.sub(r"[\W_]+", "", str(text), flags=re.UNICODE)
    dialogue = str(beat.get("dialogue") or "").strip()
    lines = re.findall(r'[“"]([^”"\n]+)[”"]', dialogue)
    if not lines and dialogue not in {"", "无", "无对白", "（无）", "—"}:
        lines = [re.sub(r"^[^：:\n]{1,24}[：:]", "", line).strip() for line in dialogue.splitlines()]
    for line in lines:
        if compact(line) and compact(line) not in compact(body):
            errors.append("提示词遗漏对白：" + line)
    numbers = re.findall(r"\[Shot\s+(\d+)", body, re.I)
    if not numbers:
        errors.append("本镜正文需要镜头编号，如 [Shot 1]；需要拆镜请返回镜头规划")
    mode = group_timecode_mode(group)
    shot_num, start_sec, end_sec = shot_header(beat, group, ordered_beats)
    if numbers and any(int(n) != shot_num for n in numbers):
        errors.append(f"本镜正文只能包含 [Shot {shot_num}]；需要拆镜请返回镜头规划")
    timeline = re.search(rf"\[Shot\s+{shot_num}\][\s*：（(\[]*(\d{{1,2}}):(\d{{2}}(?:\.\d+)?)\s*[–—−-]\s*(\d{{1,2}}):(\d{{2}}(?:\.\d+)?)", body, re.I)
    if not timeline:
        errors.append(f"镜头正文需要本镜时间范围，如 [Shot {shot_num}] {fmt_timecode(start_sec)}–{fmt_timecode(end_sec)}")
    else:
        actual_start = int(timeline[1]) * 60 + float(timeline[2])
        actual_end = int(timeline[3]) * 60 + float(timeline[4])
        if abs(actual_start - start_sec) > 0.05 or abs(actual_end - end_sec) > 0.05:
            errors.append(f"镜头时间需为 {fmt_timecode(start_sec)}–{fmt_timecode(end_sec)}，并与确认时长一致")
    if h3:
        from .workshop_h3_skill import performance_checks
        errors.extend(performance_checks(body, beat, group, offset_sec=start_sec))
    return list(dict.fromkeys(errors))


def project_prompts(beats, plan):
    result = deepcopy(beats)
    for beat in result:
        group = next((g for g in plan["groups"] if beat["id"] in g["beat_ids"]), {})
        record = plan.get("shot_prompts", {}).get(beat["id"], {})
        beat["h3_prompt"] = record.get("h3_prompt", "")
        beat["h3_prompt_source"] = "workshop_v7"
        ordered = [b for b in beats if b["id"] in group.get("beat_ids", [])]
        valid = content_matches(record, group, plan) and not prompt_checks(beat["h3_prompt"], beat, group, h3=workflow_for(plan["workflow_id"]).prompt_profile == "director_segments", ordered_beats=ordered) if record else False
        beat["h3_prompt_reference_state"] = "current" if valid and not group.get("reference_issues") and record.get("fingerprint") == prompt_fingerprint(beat, group, plan) else "stale" if record else "missing"
    return result


def legacy_candidates(beats, old):
    result = {}
    for beat in beats:
        entries = []
        if beat.get("h3_prompt"):
            entries.append({"source": "原素材组手工稿", "h3_prompt": beat["h3_prompt"]})
        for part in old.get("parts") or []:
            for segment in part.get("segments") or []:
                if beat["id"] in segment.get("source_beat_ids", []):
                    entries.append({"source": f"历史 {part.get('id')} / {segment.get('id')}",
                                    "h3_prompt": segment.get("h3_prompt") or segment.get("prompt_text") or "",
                                    "source_beat_ids": segment.get("source_beat_ids"),
                                    "common_prompt": (old.get("common_setting") or {}).get("subject_definitions", "")})
        if entries:
            result[beat["id"]] = entries
    return result


def execution_plan(detail, selected_ids=None):
    """One confirmed shot becomes exactly one segment; group packing is already final."""
    plan = plan_of(detail)
    if plan.get("schema_version") != VERSION:
        raise ValueError("请先确认镜头规划")
    beats = detail.get("beats") or []
    validate_groups(beats, plan["groups"], plan["workflow_id"], plan["max_shots_per_group"])
    wanted = set(selected_ids or [b["id"] for b in beats])
    if not wanted or wanted - {b["id"] for b in beats}:
        raise ValueError("请选择有效镜头")
    by_id = {b["id"]: b for b in beats}
    parts = []
    for group in plan["groups"]:
        ids = [bid for bid in group["beat_ids"] if bid in wanted]
        if not ids:
            continue
        if group.get("reference_issues"):
            raise ValueError("；".join(group["reference_issues"]))
        if ids != group["beat_ids"] and len(ids) != 1:
            raise ValueError("请选择完整镜头组或单个镜头")
        slots = group.get("reference_slots") or []
        definition = workflow_for(plan["workflow_id"])
        if len(slots) < definition.min_references:
            raise ValueError(f"至少需要 {definition.min_references} 张最终视频参考图，请在工坊「组设置」选择人物／道具设定图，再生成并采纳提示词")
        segments = []
        for index, bid in enumerate(ids):
            beat = by_id[bid]
            record = plan.get("shot_prompts", {}).get(bid, {})
            if record.get("fingerprint") != prompt_fingerprint(beat, group, plan):
                raise ValueError(f"镜头 {beat.get('sequence', bid)} 提示词缺失或待更新")
            if not content_matches(record, group, plan):
                raise ValueError(f"镜头 {beat.get('sequence', bid)} 正文与采纳证据不一致，请检查后重新保存")
            ordered = [by_id[x] for x in group["beat_ids"] if x in by_id]
            errors = prompt_checks(record.get("h3_prompt", ""), beat, group, h3=definition.prompt_profile == "director_segments", ordered_beats=ordered)
            if errors:
                raise ValueError("；".join(errors))
            segments.append({"id": bid, "index": index + 1, "title": beat.get("heading") or bid,
                             "duration_seconds": duration(beat), "frame_count": round(duration(beat) * 24),
                             "source_beat_ids": [bid], "h3_prompt": record["h3_prompt"], "prompt_text": record["h3_prompt"],
                             "continuity_from_prev": index > 0})
        parts.append({"id": group["id"], "source_group_id": group["id"], "segments": segments,
                      "common_prompt": group.get("common_prompt", ""), "reference_slots": slots,
                      "workflow_id": plan["workflow_id"], "render_mode": "director" if len(ids) > 1 and definition.supports_multi_segment else "shot",
                      "frame_count": sum(s["frame_count"] for s in segments)})
    from .director_reliable import assign_routes
    if workflow_for(plan["workflow_id"]).supports_multi_segment:
        assign_routes(parts, plan)
    for part in parts:
        if part.get("render_blocker"):
            raise ValueError(part["render_blocker"])
    return {**deepcopy(plan), "parts": parts}


def execution_shots(detail, selected_ids=None):
    plan = execution_plan(detail, selected_ids)
    result = []
    for part in plan["parts"]:
        for index, segment in enumerate(part["segments"]):
            common = part.get("common_prompt") or ""
            body = segment["h3_prompt"]
            prompt = f"主体定义：{common}\n\n{body}" if part["render_mode"] == "shot" and common else body
            result.append({"beat_id": segment["id"], "sequence": len(result) + 1, "heading": segment["title"],
                "prompt": prompt, "h3_prompt": prompt, "h3_prompt_source": "workshop_v7", "global_prompt": common,
                "duration_sec": segment["duration_seconds"], "duration_seconds": segment["duration_seconds"],
                "frame_count": segment["frame_count"], "planned_frame_count": segment["frame_count"],
                "reference_urls": [s["image_url"] for s in part["reference_slots"]],
                "group_render_mode": part["render_mode"], "group_workflow_id": part["workflow_id"],
                "group_options": part.get("execution_options") or {}, "part_boundary": index == 0,
                "director_part_id": part["id"], "continuity": {"partId": part["id"], "segmentId": segment["id"]},
                "source_beat_ids": [segment["id"]], "continuity_from_prev": index > 0})
    return result, plan
