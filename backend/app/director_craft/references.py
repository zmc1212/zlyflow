from __future__ import annotations

import re
from typing import Any


_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_CAST_LOCK_HEAD_RE = re.compile(r"^CAST LOCK\b", re.I)
_CAST_STAYS_RE = re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+stays\b")
_CAST_KEEPS_RE = re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+keeps\b")
_CAST_BEAUTIFY_RE = re.compile(r"do not beautify or swap faces", re.I)
_SECTION_RE = re.compile(
    r"(?m)^(subject_definitions|summary|retention_analysis|detailed_description|"
    r"overall_soundscape|non_diegetic_music):\s*$"
)


def character_subject_line(index: int, name: str) -> str:
    label = str(name or "").strip() or f"subject {index}"
    return (
        f"<Subject {index}> is {label} in <Picture {index}>. "
        f"<Picture {index}> is a single-person multi-view design sheet; "
        f"<Picture {index}> controls {label} identity only: lock face, hair, and wardrobe. "
        "Do not copy the panel grid, white background, or repeated mini figures into the shot; "
        "do not transfer pose."
    )


def scene_subject_line(index: int, name: str) -> str:
    label = str(name or "").strip() or "scene"
    return (
        f"<Subject {index}> is the {label} environment in <Picture {index}>. "
        f"<Picture {index}> supplies the setting only; "
        "do not lock blocking or standing positions."
    )


def prop_subject_line(index: int, name: str) -> str:
    label = str(name or "").strip() or f"prop {index}"
    return (
        f"<Subject {index}> is {label} in <Picture {index}>. "
        f"<Picture {index}> controls {label} identity only; do not transfer pose."
    )


def composition_subject_line(index: int, name: str, role: str = "start") -> str:
    key = str(role or "start").strip().lower()
    if key in {"mid", "middle"}:
        return (
            f"<Subject {index}> is the same-shot main-action composition landmark in <Picture {index}>, "
            "not a new character. "
            f"<Picture {index}> locks blocking during the main-action window; "
            "do not interpolate a full 16:9 triptych; do not show all three panels at once; "
            "the finished clip stays a single 9:16 frame."
        )
    if key in {"end", "result"}:
        return (
            f"<Subject {index}> is the same-shot closing composition landmark in <Picture {index}>, "
            "not a new character. "
            f"<Picture {index}> locks the result/hold framing; "
            "do not interpolate a full 16:9 triptych; do not show all three panels at once; "
            "the finished clip stays a single 9:16 frame."
        )
    label = str(name or "").strip() or "start-frame composition"
    return (
        f"<Subject {index}> is the {label} still in <Picture {index}>, "
        "a 00:00 composition landmark of this same shot, not a new character. "
        f"<Picture {index}> anchors opening blocking only; do not interpolate a full 16:9 triptych; "
        "do not show all three panels at once; the finished clip stays a single 9:16 frame."
    )


def is_identity_portrait_clause(clause: str) -> bool:
    text = str(clause or "").strip()
    if not text:
        return False
    if _CAST_LOCK_HEAD_RE.match(text) or _CAST_BEAUTIFY_RE.search(text):
        return True
    if _CAST_STAYS_RE.match(text) or _CAST_KEEPS_RE.match(text):
        return True
    return False


def reference_authority_errors(prompt: str, shot: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    subjects = _section_body(prompt, "subject_definitions")
    detail = _section_body(prompt, "detailed_description")
    six = f"{subjects}\n{detail}"
    if _CAST_LOCK_HEAD_RE.search(detail) or re.search(r"\bCAST LOCK\b", detail, flags=re.I):
        errors.append("long CAST LOCK portrait leaked into detailed_description")
    if _CAST_BEAUTIFY_RE.search(detail):
        errors.append("CAST LOCK wardrobe portrait leaked into detailed_description")
    shot = shot if isinstance(shot, dict) else {}
    for bio in _shot_bios(shot):
        han = "".join(_HAN_RE.findall(bio))
        if len(han) >= 8 and han in "".join(_HAN_RE.findall(six)):
            errors.append("character bio leaked into six-section prompt")
            break
        if len(bio) > 40 and bio in six:
            errors.append("character bio leaked into six-section prompt")
            break
    return errors


def _section_body(prompt: str, name: str) -> str:
    matches = list(_SECTION_RE.finditer(str(prompt or "")))
    for index, match in enumerate(matches):
        if match.group(1) != name:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(prompt)
        return str(prompt or "")[match.end():end]
    return ""


def _shot_bios(shot: dict[str, Any]) -> list[str]:
    bios: list[str] = []
    for item in shot.get("character_references") or []:
        if isinstance(item, dict):
            text = str(item.get("description") or item.get("look_desc") or "").strip()
            if text:
                bios.append(text)
    for item in shot.get("characters") or []:
        if isinstance(item, dict):
            text = str(item.get("look_desc") or item.get("desc") or "").strip()
            if text:
                bios.append(text)
    return bios
