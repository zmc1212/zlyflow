"""Version 5 Director contracts. Structure belongs to the program, prose to the model."""
from __future__ import annotations

from copy import deepcopy
import math
import os

from ...dialogue_timing import estimate_dialogue_duration_sec
from ...workflow_registry import WORKFLOWS, workflow_for, normalize_options
from .director_plan_quality import beat_duration
from .prompt_templates import PromptTemplateError


def enabled() -> bool:
    return os.environ.get("ZLY_DIRECTOR_RELIABLE", "1").lower() not in {"0", "false", "off"}


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
        scene = str(beat.get("scene_id") or beat.get("scene") or beat.get("heading") or "").strip()
        for unit, count in zip(rows, frames):
            unit["duration_seconds"] = count / fps
            if scene:
                unit["scene_key"] = scene
            if not unit.get("dialogue_ids"):
                unit["dialogue_timing"] = "无对白"
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
        route, error = (shot_route(request["workflow_id"], len(request.get("reference_slots") or []),
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
        count = len(plan.get("reference_slots") or [])
        if not definition.min_references <= count <= definition.max_references:
            raise ValueError(f"生成组 {part['id']} 参考图数量不兼容")
        if part.get("render_mode") == "shot":
            if definition.prompt_profile != "full_reference" or definition.supports_timeline:
                raise ValueError("逐镜组必须使用已注册逐镜工作流")
            options = normalize_options(definition.id, {**part.get("execution_options", {}), "duration": part["frame_count"] / 24})
            if float(options.get("duration", 0)) != part["frame_count"] / 24:
                raise ValueError("逐镜工作流不能保持该段时长")
        elif part.get("render_mode") != "director" or definition.prompt_profile != "director_segments":
            raise ValueError("连续生成组工作流无效")
