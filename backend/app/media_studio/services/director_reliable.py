"""Version 5 Director contracts. Structure belongs to the program, prose to the model."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
import re

from ...dialogue_timing import estimate_dialogue_duration_sec
from ...workflow_registry import WORKFLOWS, workflow_for, normalize_options
from .director_plan_quality import beat_duration
from .prompt_templates import PromptTemplateError


def source_groups(beats: list[dict], definition, max_shots_per_group: int, fps: int = 24,
                  *, source_facts: dict | None = None, max_input_chars: int = 24000) -> list[dict]:
    """Bound Director input by source shots, scene and registered frame capacity."""
    limit = int(definition.max_segments)
    if not 2 <= max_shots_per_group <= limit:
        raise ValueError(f"每组最多镜头数必须在 2～{limit} 之间")
    groups: list[dict] = []
    for beat in beats:
        scene = str(beat.get("scene_id") or beat.get("scene") or "").strip()
        time_of_day = str(beat.get("time_of_day") or beat.get("scene_time") or "").strip()
        scene_key = f"{scene}·{time_of_day}" if time_of_day else scene
        frames = round(beat_duration(beat) * fps)
        input_chars = len(json.dumps({"beat": beat, "facts": (source_facts or {}).get(str(beat.get("id")))}, ensure_ascii=False))
        if frames <= 0:
            raise ValueError(f"镜头 {beat.get('id')} 时长无效")
        if input_chars > max_input_chars:
            raise ValueError(f"镜头 {beat.get('id')} 来源过长，超过当前模型分组输入预算；请先按动作和对白边界拆分该镜头")
        if (not groups or groups[-1]["scene_key"] != scene_key
                or len(groups[-1]["beat_ids"]) >= max_shots_per_group
                or groups[-1]["frame_count"] + frames > int(definition.max_total_frames)
                or groups[-1]["input_chars_estimate"] + input_chars > max_input_chars):
            groups.append({"id": f"source-group-{len(groups) + 1}", "scene_key": scene_key,
                           "beat_ids": [], "frame_count": 0, "input_chars_estimate": 0})
        groups[-1]["beat_ids"].append(str(beat["id"]))
        groups[-1]["frame_count"] += frames
        groups[-1]["input_chars_estimate"] += input_chars
    return groups


def group_reference_slots(slots: list[dict], beats: list[dict], minimum: int = 0) -> list[dict]:
    """Keep ordered references related to this source group, with a route minimum."""
    linked = {str(value) for beat in beats for value in
              [beat.get("scene_id"), *(beat.get("character_ids") or []), *(beat.get("prop_ids") or [])]
              if value}
    source_text = "\n".join(str(beat.get(key) or "") for beat in beats
                            for key in ("heading", "scene", "action", "dialogue", "visual_prompt"))
    chosen = [slot for slot in slots if str(slot.get("asset_id") or "") in linked
              or (str(slot.get("name") or "").strip() and str(slot["name"]).split(" · ")[0] in source_text)]
    for slot in slots:
        if len(chosen) >= minimum:
            break
        if slot not in chosen:
            chosen.append(slot)
    return [{**slot, "index": index, "token": f"<Picture {index}>"}
            for index, slot in enumerate(chosen, 1)]


def enabled() -> bool:
    return os.environ.get("ZLY_DIRECTOR_RELIABLE", "1").lower() not in {"0", "false", "off"}


def failure_location(message: str, parts: list[dict]) -> tuple[str, list[str]]:
    segments = [s for p in parts for s in p["segments"]]
    ids = {s["id"] for s in segments if re.search(r"(?<![\w-])" + re.escape(s["id"]) + r"(?![\w-])", message)}
    for match in re.finditer(r"第\s*(\d+)\s*段", message):
        index = int(match[1]) - 1
        if 0 <= index < len(segments):
            ids.add(segments[index]["id"])
    for segment in segments:
        if any(re.search(r"Beat\s+" + re.escape(bid) + r"(?![\w-])", message) for bid in segment.get("source_beat_ids", [])):
            ids.add(segment["id"])
    owners = [p["id"] for p in parts if any(s["id"] in ids for s in p["segments"])]
    return owners[0] if len(owners) == 1 else "", [s["id"] for s in segments if s["id"] in ids]


def normalize_design(design: dict, beats: list[dict], facts: dict, fps: int = 24) -> dict:
    """Allocate exact frames and inherit state without changing any immutable fact."""
    result = deepcopy(design)
    units = result.get("units")
    if not isinstance(units, list) or not units or any(not isinstance(u, dict) for u in units):
        raise PromptTemplateError("导演设计缺少 units 数组")
    by_beat = {str(b["id"]): b for b in beats}
    for unit in units:
        bid = unit.get("source_beat_id")
        if bid not in by_beat:
            raise PromptTemplateError(f"未知 source_beat_id：{bid}")
    for bid, beat in by_beat.items():
        rows = [u for u in units if u["source_beat_id"] == bid]
        if not rows:
            raise PromptTemplateError(f"镜头 {bid} 未分配动作单元")
        total = round(beat_duration(beat) * fps)
        dialogues = {x["id"]: x["text"] for x in facts[bid]["dialogues"]}
        minimum = [max(1, math.ceil(sum(estimate_dialogue_duration_sec(dialogues.get(i, ""))
                    for i in u.get("dialogue_ids", [])) * fps)) for u in rows]
        if sum(minimum) > total:
            raise PromptTemplateError(f"镜头 {bid} 的对白与动作单元无法在原时长内完成")
        weights = []
        for unit in rows:
            try:
                weight = float(unit.get("duration_seconds", 1))
            except (ValueError, TypeError):
                weight = 1
            weights.append(weight if math.isfinite(weight) and weight > 0 else 1)
        free = total - sum(minimum)
        fractions = [free * w / sum(weights) for w in weights]
        frames = [m + int(x) for m, x in zip(minimum, fractions)]
        for index in sorted(range(len(rows)), key=lambda i: (-(fractions[i] % 1), i))[:total - sum(frames)]:
            frames[index] += 1
        scene = str(beat.get("scene_id") or beat.get("scene") or "").strip()
        time_of_day = str(beat.get("time_of_day") or beat.get("scene_time") or "").strip()
        if scene and time_of_day:
            scene += "·" + time_of_day
        for unit, count in zip(rows, frames):
            unit["duration_seconds"] = count / fps
            if scene:
                unit["scene_key"] = scene
            if not unit.get("dialogue_ids"):
                unit["dialogue_timing"] = "无对白"
        if beat.get("opening_state"):
            rows[0]["start_state"] = str(beat["opening_state"])
        if beat.get("closing_state"):
            rows[-1]["handoff_state"] = str(beat["closing_state"])
    previous = None
    for i, unit in enumerate(units):
        unit["id"] = f"story-unit-{i + 1}"
        same_scene = previous and unit.get("scene_key") == previous.get("scene_key") and unit.get("transition_type") != "cut"
        if same_scene:
            unit["start_state"] = previous.get("handoff_state", "")
            unit["start_state_ref"] = previous["id"]
        unit["transition_type"] = "continuous" if same_scene else "cut"
        previous = unit
    return result


def shot_route(director_id: str, references: int, duration: float) -> tuple[str | None, str | None]:
    """Only select a registered H3 single-video route, never a different model."""
    director = workflow_for(director_id)
    if director.id in {"minimax-h3-director-refine-accel-r2v", "minimax-h3-director-confirm-accel-r2v"}:
        if 1 <= references <= 9:
            return director.id, None
        return None, "H3 Director 二采加速版需要 1–9 张参考图，不会切换到其他配方"
    candidates = [w for w in WORKFLOWS if w.prompt_profile == "full_reference"
                  and w.supports_h3_options and not w.supports_timeline
                  and w.min_references <= references <= w.max_references
                  and (w.reference_mode == "collection" if references else w.reference_mode == "none")]
    candidates.sort(key=lambda w: (w.catalog_group != director.catalog_group, w.id))
    for candidate in candidates:
        try:
            options = normalize_options(candidate.id, {"duration": duration})
            if float(options.get("duration", duration)) != duration:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        return candidate.id, None
    return None, f"没有支持 {references} 张参考图、{duration:g} 秒的已注册 H3 逐镜工作流"


def assign_routes(parts: list[dict], request: dict) -> None:
    for part in parts:
        mode = "shot" if len(part["segments"]) == 1 else "director"
        route, error = (shot_route(request["workflow_id"], len(part.get("reference_slots", request.get("reference_slots") or [])),
                       part["frame_count"] / 24) if mode == "shot" else (request["workflow_id"], None))
        part.update(render_mode=mode, workflow_id=route, render_blocker=error,
                    segment_ids=[s["id"] for s in part["segments"]],
                    execution_options={"aspect_ratio": request.get("aspect_ratio", "16:9")})


def assert_routes(plan: dict) -> None:
    for part in plan.get("parts", []):
        if part.get("render_blocker"):
            raise ValueError(f"生成组 {part['id']}：{part['render_blocker']}")
        if not part.get("workflow_id"):
            raise ValueError(f"生成组 {part['id']} 缺少工作流")
        definition = workflow_for(part["workflow_id"])
        slots = part.get("reference_slots", plan.get("reference_slots") or [])
        count = len(slots)
        if [int(slot.get("index") or 0) for slot in slots] != list(range(1, count + 1)):
            raise ValueError(f"生成组 {part['id']} 参考图顺序无效")
        if not definition.min_references <= count <= definition.max_references:
            raise ValueError(f"生成组 {part['id']} 参考图数量不兼容")
        if part.get("render_mode") == "shot":
            if len(part.get("segments", [])) != 1 or not definition.supports_h3_options or definition.prompt_profile != "full_reference" or definition.supports_timeline:
                raise ValueError("逐镜组必须使用已注册逐镜工作流")
            options = normalize_options(definition.id, {**part.get("execution_options", {}), "duration": part["frame_count"] / 24})
            if float(options.get("duration", 0)) != part["frame_count"] / 24:
                raise ValueError("逐镜工作流不能保持该段时长")
        elif part.get("render_mode") != "director" or definition.prompt_profile != "director_segments":
            raise ValueError("连续生成组工作流无效")
        elif not 2 <= len(part.get("segments", [])) <= definition.max_segments or part["frame_count"] > definition.max_total_frames:
            raise ValueError(f"生成组 {part['id']} 超出 Director 容量")
