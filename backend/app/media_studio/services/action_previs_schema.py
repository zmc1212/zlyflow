"""Versioned, bounded contract between the choreography agent and Blender."""

from __future__ import annotations

import math
from typing import Any

FPS = 24
MIN_SECONDS = 2
MAX_SECONDS = 15
ACTION_TYPES = frozenset({
    "idle", "walk", "run", "step", "turn", "reach", "point", "wave",
    "push", "pull", "grab", "release", "crouch", "jump", "guard",
    "jab", "cross", "hook", "block", "dodge", "knee", "low_kick",
    "side_kick", "recoil", "recover",
})
SHOT_SIZES = frozenset({"wide", "medium", "close", "detail"})
SHOT_ANGLES = frozenset({"front", "side", "three_quarter", "over_shoulder", "low", "high"})
SHOT_MOVES = frozenset({"static", "dolly_in", "dolly_out", "truck_left", "truck_right", "orbit_left", "orbit_right", "follow"})
CONTACT_BONES = frozenset({"hand.L", "hand.R", "foot.L", "foot.R", "forearm.L", "forearm.R", "chest", "shoulder.L", "shoulder.R"})


def _number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是数字") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label}必须是有限数字")
    return number


def _frame(value: Any, label: str, limit: int) -> int:
    number = _number(value, label)
    if int(number) != number or not 0 <= number <= limit:
        raise ValueError(f"{label}超出帧范围")
    return int(number)


def _text(value: Any, label: str, limit: int = 160) -> str:
    result = str(value or "").strip()
    if not result or len(result) > limit:
        raise ValueError(f"{label}不能为空或超过{limit}字")
    return result


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label}必须是三个坐标")
    result = [_number(item, label) for item in value]
    if any(abs(item) > 20 for item in result):
        raise ValueError(f"{label}超出场景范围")
    return result


def validate_plan(raw: Any, *, expected_frames: int | None = None) -> dict[str, Any]:
    """Normalize model/user JSON without accepting executable instructions."""
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("动作方案版本无效")
    frame_count = _frame(raw.get("frame_count"), "总帧数", FPS * MAX_SECONDS)
    if frame_count < FPS * MIN_SECONDS or (expected_frames is not None and frame_count != expected_frames):
        raise ValueError("动作方案时长与当前镜头不一致")
    actors_raw = raw.get("actors")
    if not isinstance(actors_raw, list) or not 1 <= len(actors_raw) <= 2:
        raise ValueError("首版仅支持一到两名人形角色")
    actors: list[dict[str, Any]] = []
    for index, item in enumerate(actors_raw):
        if not isinstance(item, dict) or item.get("id") != ("A" if index == 0 else "B"):
            raise ValueError("角色 ID 必须按 A、B 排列")
        actors.append({
            "id": item["id"],
            "label": _text(item.get("label"), "角色名称", 40),
            "start": _vector(item.get("start"), "角色起始位置"),
            "facing_deg": _number(item.get("facing_deg", 0), "角色朝向"),
        })
    actor_ids = {item["id"] for item in actors}

    beats_raw = raw.get("beats")
    if not isinstance(beats_raw, list) or not 1 <= len(beats_raw) <= 12:
        raise ValueError("动作节拍数量必须为 1–12")
    beats: list[dict[str, Any]] = []
    cursor = 0
    for index, item in enumerate(beats_raw):
        if not isinstance(item, dict):
            raise ValueError("动作节拍格式无效")
        start = _frame(item.get("start"), "动作开始帧", frame_count)
        end = _frame(item.get("end"), "动作结束帧", frame_count)
        if start != cursor or end <= start:
            raise ValueError("动作节拍必须连续、无重叠地覆盖镜头")
        cursor = end
        actions_raw = item.get("actions")
        if not isinstance(actions_raw, list) or not 1 <= len(actions_raw) <= len(actors):
            raise ValueError("每拍须包含一至两名角色的动作")
        actions: list[dict[str, str]] = []
        used: set[str] = set()
        for action in actions_raw:
            if not isinstance(action, dict):
                raise ValueError("角色动作格式无效")
            actor = str(action.get("actor") or "")
            kind = str(action.get("type") or "")
            if actor not in actor_ids or actor in used or kind not in ACTION_TYPES:
                raise ValueError("角色或动作类型无效；不支持的动作须先修改节拍表")
            used.add(actor)
            actions.append({"actor": actor, "type": kind})
        contact = None
        if item.get("contact") is not None:
            source = item["contact"]
            if not isinstance(source, dict) or len(actors) != 2:
                raise ValueError("接触事件仅适用于双人镜头")
            contact_frame = _frame(source.get("frame"), "接触帧", frame_count)
            if not start <= contact_frame < end:
                raise ValueError("接触帧须在当前动作节拍内")
            actor = str(source.get("actor") or "")
            target_actor = str(source.get("target_actor") or "")
            bone = str(source.get("bone") or "")
            target_bone = str(source.get("target_bone") or "")
            if actor not in actor_ids or target_actor not in actor_ids or actor == target_actor or bone not in CONTACT_BONES or target_bone not in CONTACT_BONES:
                raise ValueError("接触角色或骨骼无效")
            contact = {"frame": contact_frame, "actor": actor, "target_actor": target_actor,
                       "bone": bone, "target_bone": target_bone}
        beats.append({"id": f"b{index + 1}", "start": start, "end": end,
                      "description": _text(item.get("description"), "动作说明", 240),
                      "actions": actions, "contact": contact})
    if cursor != frame_count:
        raise ValueError("动作节拍没有覆盖镜头末帧")

    shots_raw = raw.get("shots")
    if not isinstance(shots_raw, list) or not 1 <= len(shots_raw) <= 8:
        raise ValueError("镜头表数量必须为 1–8")
    shots: list[dict[str, Any]] = []
    cursor = 0
    for index, item in enumerate(shots_raw):
        if not isinstance(item, dict):
            raise ValueError("镜头格式无效")
        start = _frame(item.get("start"), "镜头开始帧", frame_count)
        end = _frame(item.get("end"), "镜头结束帧", frame_count)
        if start != cursor or end <= start:
            raise ValueError("机位必须连续、无重叠地覆盖镜头")
        cursor = end
        size, angle, move = (str(item.get(key) or "") for key in ("size", "angle", "move"))
        subject = str(item.get("subject") or "")
        lens = _number(item.get("lens_mm"), "焦距")
        if size not in SHOT_SIZES or angle not in SHOT_ANGLES or move not in SHOT_MOVES:
            raise ValueError("景别、机位或运镜类型无效")
        if subject not in actor_ids | {"both"} or not 18 <= lens <= 100:
            raise ValueError("镜头主体或焦距无效")
        shots.append({"id": f"s{index + 1}", "start": start, "end": end, "size": size,
                      "angle": angle, "move": move, "subject": subject, "lens_mm": lens})
    if cursor != frame_count:
        raise ValueError("镜头表没有覆盖镜头末帧")
    return {"version": 1, "fps": FPS, "frame_count": frame_count,
            "actors": actors, "beats": beats, "shots": shots}
