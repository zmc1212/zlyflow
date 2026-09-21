"""成片画幅：请求 > 项目 extra.workshop_aspect_ratio > 配方 confirm_format > 9:16。"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

WORKSHOP_ASPECT_KEY = "workshop_aspect_ratio"
DEFAULT_ASPECT = "9:16"
SCAN_ASPECTS = ("9:16", "16:9", "1:1", "3:4", "4:3", "21:9")
_WORD_MAP = (
    ("正方形", "1:1"),
    ("方形", "1:1"),
    ("竖屏", "9:16"),
    ("横屏", "16:9"),
)
_ASPECT_TOKEN_RE = re.compile(
    r"(?<!\d)(21|16|9|4|3|1)\s*[:：/x×]\s*(9|16|3|4|1)(?!\d)"
)
_GENERIC_ASPECT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[:：/x×]\s*(\d+(?:\.\d+)?)"
)

Orientation = str  # portrait | landscape | square


def normalize_aspect_ratio(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = _GENERIC_ASPECT_RE.search(text.replace("：", ":"))
    if not match:
        return None
    width = _canon_number(match.group(1))
    height = _canon_number(match.group(2))
    if not width or not height:
        return None
    return f"{width}:{height}"


def aspect_parts(value: Any) -> tuple[float, float] | None:
    normalized = normalize_aspect_ratio(value)
    if not normalized:
        return None
    width_text, height_text = normalized.split(":", 1)
    try:
        width = float(width_text)
        height = float(height_text)
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def aspect_orientation(value: Any) -> Orientation:
    parts = aspect_parts(value)
    if not parts:
        return "portrait"
    width, height = parts
    if height > width:
        return "portrait"
    if width > height:
        return "landscape"
    return "square"


def aspect_orientation_zh(value: Any) -> str:
    kind = aspect_orientation(value)
    if kind == "landscape":
        return "横屏"
    if kind == "square":
        return "方形"
    return "竖屏"


def aspect_orientation_en(value: Any) -> str:
    kind = aspect_orientation(value)
    if kind == "landscape":
        return "horizontal"
    if kind == "square":
        return "square"
    return "vertical"


def workshop_aspect_of(*sources: Any) -> str | None:
    for source in sources:
        extra = _extra_map(source)
        if extra:
            found = normalize_aspect_ratio(extra.get(WORKSHOP_ASPECT_KEY))
            if found:
                return found
        if isinstance(source, dict):
            found = normalize_aspect_ratio(source.get(WORKSHOP_ASPECT_KEY))
            if found:
                return found
    return None


def resolve_workshop_aspect_ratio(
    *,
    request: Any = None,
    project: Any = None,
    extra: Any = None,
    recipe: Any = None,
    project_id: str | None = None,
    default: str = DEFAULT_ASPECT,
) -> str:
    found = _aspect_from_request(request)
    if found:
        return found
    project_obj = project
    if project_obj is None and project_id:
        project_obj = _load_project(project_id)
    found = workshop_aspect_of(extra, project_obj)
    if found:
        return found
    found = _recipe_aspect(recipe) or _recipe_aspect(_recipe_from_project(project_obj, extra))
    if found:
        return found
    return normalize_aspect_ratio(default) or DEFAULT_ASPECT


def scan_script_aspect_hints(text: str, *, default: str = DEFAULT_ASPECT) -> dict[str, Any]:
    source = str(text or "")
    hits: list[dict[str, str]] = []
    for match in _ASPECT_TOKEN_RE.finditer(source):
        token = str(match.group(0) or "")
        aspect = normalize_aspect_ratio(token)
        if aspect in SCAN_ASPECTS:
            hits.append({"token": re.sub(r"\s+", "", token).replace("：", ":"), "aspect": aspect, "kind": "explicit"})
    occupied = [False] * len(source)
    for word, aspect in sorted(_WORD_MAP, key=lambda item: len(item[0]), reverse=True):
        start = 0
        while True:
            index = source.find(word, start)
            if index < 0:
                break
            end = index + len(word)
            if any(occupied[index:end]):
                start = index + 1
                continue
            hits.append({"token": word, "aspect": aspect, "kind": "word"})
            occupied[index:end] = [True] * (end - index)
            start = end
    explicit = [item["aspect"] for item in hits if item["kind"] == "explicit"]
    words = [item["aspect"] for item in hits if item["kind"] == "word"]
    fallback = normalize_aspect_ratio(default) or DEFAULT_ASPECT
    suggested = _majority(explicit) or _majority(words) or fallback
    unique: list[str] = []
    for item in hits:
        if item["aspect"] not in unique:
            unique.append(item["aspect"])
    return {
        "suggested": suggested,
        "hits": [item["token"] for item in hits],
        "explicit": explicit,
        "conflicts": unique if len(unique) >= 2 else [],
    }


def document_aspect_hint(
    raw_text: str,
    *,
    project: Any = None,
    extra: Any = None,
    recipe: Any = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    project_obj = project
    if project_obj is None and project_id:
        project_obj = _load_project(project_id)
    fallback = resolve_workshop_aspect_ratio(
        project=project_obj,
        extra=extra,
        recipe=recipe,
        default=DEFAULT_ASPECT,
    )
    hint = scan_script_aspect_hints(raw_text, default=fallback)
    stored = workshop_aspect_of(extra, project_obj)
    if stored:
        hint["suggested"] = stored
        hint["source"] = "project"
    elif hint["hits"]:
        hint["source"] = "script"
    else:
        hint["source"] = "recipe"
    return hint


def persist_workshop_aspect_ratio(project_id: str, aspect: Any) -> str:
    resolved = normalize_aspect_ratio(aspect) or DEFAULT_ASPECT
    from ..media_studio.models import ProjectUpdateRequest
    from ..media_studio.services.project_service import ProjectService

    ProjectService.update_project(
        project_id,
        ProjectUpdateRequest(extra={WORKSHOP_ASPECT_KEY: resolved}),
    )
    return resolved


def triptych_panel_geometry_en(aspect: Any) -> str:
    confirmed = normalize_aspect_ratio(aspect) or DEFAULT_ASPECT
    kind = aspect_orientation(confirmed)
    if kind == "landscape":
        return f"horizontal {confirmed} composition"
    if kind == "square":
        return f"square {confirmed} composition"
    return f"vertical {confirmed}"


def format_aspect_template(text: Any, aspect: Any) -> str:
    raw = str(text or "")
    if not raw or "{" not in raw:
        return raw
    confirmed = normalize_aspect_ratio(aspect) or DEFAULT_ASPECT
    values = {
        "aspect": confirmed,
        "orientation": aspect_orientation_zh(confirmed),
        "orientation_en": aspect_orientation_en(confirmed),
        "panel_geometry": triptych_panel_geometry_en(confirmed),
        "fill": f"铺满{aspect_orientation_zh(confirmed)}",
    }

    class _Safe(dict[str, str]):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    try:
        return raw.format_map(_Safe(values))
    except Exception:
        return raw


def rewrite_aspect_copy(text: Any, aspect: Any) -> str:
    raw = str(text or "")
    if not raw:
        return ""
    confirmed = normalize_aspect_ratio(aspect) or DEFAULT_ASPECT
    orientation = aspect_orientation_zh(confirmed)
    updated = raw
    for token in sorted(SCAN_ASPECTS, key=len, reverse=True):
        width, height = token.split(":")
        pattern = re.compile(
            rf"(?<!\d){re.escape(width)}\s*[:：/x×]\s*{re.escape(height)}(?!\d)"
        )
        updated = pattern.sub(confirmed, updated)
    for word, _mapped in _WORD_MAP:
        if word != orientation:
            updated = updated.replace(word, orientation)
    return updated


def apply_confirmed_aspect_to_shot(shot: dict[str, Any], aspect: Any) -> dict[str, Any]:
    confirmed = normalize_aspect_ratio(aspect) or DEFAULT_ASPECT
    orientation = aspect_orientation_zh(confirmed)
    updated = dict(shot)
    for key in ("title", "camera", "action", "visual_prompt", "heading"):
        if key not in updated:
            continue
        value = str(updated.get(key) or "").strip()
        if value:
            updated[key] = rewrite_aspect_copy(value, confirmed)
    camera = str(updated.get("camera") or "").strip()
    stamp = f"成片 {confirmed}（{orientation}）"
    if confirmed not in camera:
        updated["camera"] = f"{camera} {stamp}".strip() if camera else stamp
    return updated


def _canon_number(raw: str) -> str:
    try:
        number = float(raw)
    except ValueError:
        return ""
    if number <= 0:
        return ""
    if number.is_integer():
        return str(int(number))
    return str(raw)


def _aspect_from_request(request: Any) -> str | None:
    if request is None or request is False:
        return None
    if isinstance(request, dict):
        for key in ("aspect_ratio", WORKSHOP_ASPECT_KEY):
            found = normalize_aspect_ratio(request.get(key))
            if found:
                return found
        nested = request.get("options")
        if isinstance(nested, dict):
            found = normalize_aspect_ratio(nested.get("aspect_ratio"))
            if found:
                return found
        return None
    return normalize_aspect_ratio(request)


def _recipe_aspect(recipe: Any) -> str | None:
    if recipe is None:
        return None
    fmt = getattr(recipe, "confirm_format", None)
    if fmt is None and isinstance(recipe, dict):
        fmt = recipe.get("confirm_format")
    if not isinstance(fmt, dict):
        return None
    return normalize_aspect_ratio(fmt.get("aspect_ratio"))


def _recipe_from_project(project: Any, extra: Any) -> Any:
    from .binding import skill_pack_id_of
    from .recipe import get_pack

    pack_id = skill_pack_id_of(project) or skill_pack_id_of(extra)
    try:
        return get_pack(pack_id)
    except Exception:
        return None


def _extra_map(source: Any) -> dict[str, Any]:
    if source is None:
        return {}
    from .binding import extra_mapping

    try:
        return extra_mapping(source)
    except Exception:
        return {}


def _load_project(project_id: str) -> dict[str, Any] | None:
    try:
        from .binding import load_project

        return load_project(project_id)
    except Exception:
        return None


def _majority(items: list[str]) -> str | None:
    if not items:
        return None
    ranked = Counter(items).most_common()
    if len(ranked) >= 2 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]
