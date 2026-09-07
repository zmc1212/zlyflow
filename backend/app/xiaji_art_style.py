from __future__ import annotations

from typing import Any

from .director_catalog import art_style_ref_for_recipe, find_art_style


def normalize_art_style_id(value: Any) -> str:
    if isinstance(value, dict):
        found = find_art_style(value)
        return str(found["id"]) if found else ""
    text = str(value or "").strip()
    if not text:
        return ""
    found = find_art_style(text)
    return str(found["id"]) if found else ""


def first_art_style_id(*candidates: Any) -> str:
    for item in candidates:
        style_id = normalize_art_style_id(item)
        if style_id:
            return style_id
    return ""


def settings_art_style_id(settings: Any) -> str:
    payload = settings if isinstance(settings, dict) else {}
    return first_art_style_id(payload.get("art_style_id"), payload.get("art_style"), payload.get("visual_style"))


def definition_art_style_id(definition: Any) -> str:
    payload = definition if isinstance(definition, dict) else {}
    return first_art_style_id(payload.get("art_style_id"), payload.get("art_style"), payload.get("visual_style"))


def art_style_prefix(style_id: str) -> str:
    found = find_art_style(style_id)
    if not found:
        return ""
    return str(found.get("promptPrefix") or "").strip()


def art_style_label(style_id: str) -> str:
    found = find_art_style(style_id)
    if not found:
        return ""
    return str(found.get("name_zh") or found.get("name_en") or "").strip()


def art_style_hint(style_id: str) -> str:
    found = find_art_style(style_id)
    if not found:
        return ""
    name = art_style_label(style_id)
    prefix = str(found.get("promptPrefix") or "").strip()
    if name and prefix:
        return f"{name}。{prefix}"
    return name or prefix


def _art_style_blob(found: dict[str, Any]) -> str:
    return " ".join(
        [
            str(found.get("name_en") or ""),
            str(found.get("name_zh") or ""),
            " ".join(str(item) for item in (found.get("keywords") or [])),
            str(found.get("promptPrefix") or ""),
        ]
    ).casefold()


def is_animation_art_style(style_id: str) -> bool:
    found = find_art_style(style_id)
    if not found:
        return False
    category = str(found.get("category") or "").strip().lower()
    if category == "anime":
        return True
    blob = _art_style_blob(found)
    return "anime" in blob or "manga" in blob or "动漫" in blob


def is_non_live_art_style(style_id: str) -> bool:
    text = (style_id or "").strip()
    if text in {"anime", "guoman_fantasy"}:
        return True
    if is_animation_art_style(text):
        return True
    found = find_art_style(text)
    if not found:
        folded = text.casefold()
        return any(token in folded for token in ("anime", "3d", "animation", "illustration", "动漫", "动画", "插画"))
    category = str(found.get("category") or "").strip().lower()
    if category in {"anime", "3d", "illustration"}:
        return True
    blob = _art_style_blob(found)
    return any(token in blob for token in ("3d", "animation", "illustrated", "插画", "动画"))


def resolve_beat_art_style(visual_style: str, characters: list[dict[str, Any]] | None = None) -> str:
    resolved = first_art_style_id(visual_style)
    if resolved:
        return resolved
    ordered: list[dict[str, Any]] = []
    for item in characters or []:
        if not isinstance(item, dict):
            continue
        definition = item.get("definition") if isinstance(item.get("definition"), dict) else {}
        if definition.get("is_main"):
            ordered.insert(0, item)
        else:
            ordered.append(item)
    for item in ordered:
        definition = item.get("definition") if isinstance(item.get("definition"), dict) else {}
        style_id = definition_art_style_id(definition)
        if style_id:
            return style_id
    return (visual_style or "").strip()


def art_style_public_ref(style_id: str) -> dict[str, Any] | None:
    found = find_art_style(style_id)
    if not found:
        return None
    return art_style_ref_for_recipe(found)
