"""导入分镜的开场/落幅衔接：给 shot_plan、工坊 beat、H3 与三联共用。"""
from __future__ import annotations

import re
from typing import Any

MATCH_CUT_NOTES = ("动作匹配切", "视线匹配切", "方向匹配切", "声音桥")
HARD_CUT_NOTES = ("硬切换场", "硬切")
_ACTION_SUMMARY_LIMIT = 48

def shot_sequence_number(item: dict[str, Any] | None) -> int:
    raw = item if isinstance(item, dict) else {}
    for key in ("sequence", "shot_num", "story_shot"):
        value = raw.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def find_previous_shot(
    shots: list[dict[str, Any]] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(current, dict):
        return None
    current_seq = shot_sequence_number(current)
    previous: dict[str, Any] | None = None
    previous_seq = -1
    for item in shots or []:
        if not isinstance(item, dict) or item is current:
            continue
        seq = shot_sequence_number(item)
        if seq <= 0 or seq >= current_seq:
            continue
        if seq > previous_seq:
            previous = item
            previous_seq = seq
    return previous


def is_hard_cut(note: Any) -> bool:
    text = str(note or "").strip()
    return any(token in text for token in HARD_CUT_NOTES)


def is_named_match_cut(note: Any) -> bool:
    text = str(note or "").strip()
    if is_hard_cut(text):
        return False
    return any(token in text for token in MATCH_CUT_NOTES)


def same_scene(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    first = _scene_key(left)
    second = _scene_key(right)
    return bool(first and second and first == second)


def should_inherit_opening_pose(
    current: dict[str, Any] | None,
    previous: dict[str, Any] | None,
) -> bool:
    if not isinstance(current, dict) or not isinstance(previous, dict):
        return False
    note = str(
        current.get("transition_note")
        or previous.get("transition_note")
        or ""
    ).strip()
    if is_hard_cut(note):
        return False
    if is_named_match_cut(note):
        return True
    return same_scene(current, previous)


def format_previous_shot_handoff(
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None = None,
) -> str:
    if not isinstance(previous, dict):
        return ""
    closing = _closing_state(previous)
    note = str(
        (current or {}).get("transition_note")
        or previous.get("transition_note")
        or ""
    ).strip()
    summary = _action_summary(previous.get("action"))
    parts: list[str] = []
    if closing:
        parts.append(f"落幅姿势：{closing}")
    if note:
        parts.append(f"切型：{note}")
    if summary:
        parts.append(f"上一镜动作：{summary}")
    return "；".join(parts)


def left_panel_inherit_instruction(
    beat: dict[str, Any] | None,
    previous: dict[str, Any] | None,
) -> str:
    if not should_inherit_opening_pose(beat, previous):
        return ""
    landing = _closing_state(previous or {})
    opening = str((beat or {}).get("opening_state") or "").strip()
    closing = str((beat or {}).get("closing_state") or "").strip()
    pose = opening or landing
    if not pose:
        return ""
    lines = [
        "LEFT panel MUST inherit the previous shot's RIGHT/end pose: "
        f"{landing or pose}. Same sit/stand, same held props, same eyeline and screen direction. "
        "Do NOT change body state (for example do not stand if the previous landing was seated).",
        f"CENTER = this shot's new action starting from that inherited pose: {pose}.",
    ]
    if closing:
        lines.append(f"RIGHT = this shot's landing / result pose: {closing}.")
    return " ".join(lines)


def _scene_key(item: dict[str, Any] | None) -> str:
    raw = item if isinstance(item, dict) else {}
    scene_id = str(raw.get("scene_id") or "").strip()
    if scene_id:
        return f"id:{scene_id}"
    return str(raw.get("scene") or raw.get("scene_name") or "").strip()


def _closing_state(shot: dict[str, Any]) -> str:
    closing = str(shot.get("closing_state") or "").strip()
    if closing:
        return closing
    action = str(shot.get("action") or "")
    match = re.search(r"收束[:：]\s*([^。\n]+)", action)
    if match:
        return match.group(1).strip()
    return ""


def _action_summary(action: Any) -> str:
    text = str(action or "").strip()
    if not text:
        return ""
    text = re.sub(r"开场[:：]\s*", "", text)
    text = re.sub(r"收束[:：]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= _ACTION_SUMMARY_LIMIT:
        return text
    return text[:_ACTION_SUMMARY_LIMIT].rstrip() + "…"
