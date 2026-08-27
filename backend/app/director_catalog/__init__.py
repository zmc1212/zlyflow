from __future__ import annotations

import json
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any


CATALOG_PATH = Path(__file__).with_name("art_styles.json")
PREVIEW_DIR = Path(__file__).resolve().parent / "previews"
EXPECTED_CATEGORY_COUNT = 9
EXPECTED_STYLE_COUNT = 34
JPEG_MAGIC = b"\xff\xd8"
_PREVIEW_LOCK = Lock()

REQUIRED_STYLE_FIELDS = ("id", "name_zh", "name_en", "category", "description", "promptPrefix", "keywords", "imageUrl")
REQUIRED_CATEGORY_FIELDS = ("id", "name_zh", "name_en")


class ArtStyleCatalogError(ValueError):
    """Raised when the on-disk art-style seed is invalid."""


def _require_text(value: Any, field: str, *, loc: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ArtStyleCatalogError(f"{loc} 缺少 {field}")
    return text


def _validate_catalog(data: dict[str, Any]) -> None:
    """OpenDirector seed uses category id `3d` and art_style_id `as_1001`…`as_1034`."""
    categories = data.get("categories")
    styles = data.get("styles")
    if not isinstance(categories, list) or not isinstance(styles, list):
        raise ArtStyleCatalogError("画风目录必须包含 categories 与 styles 数组")
    if len(categories) != EXPECTED_CATEGORY_COUNT:
        raise ArtStyleCatalogError(f"画风目录应有 {EXPECTED_CATEGORY_COUNT} 个分类，实际 {len(categories)}")
    if len(styles) != EXPECTED_STYLE_COUNT:
        raise ArtStyleCatalogError(f"画风目录应有 {EXPECTED_STYLE_COUNT} 条，实际 {len(styles)}")

    category_ids: set[str] = set()
    for index, category in enumerate(categories):
        loc = f"categories[{index}]"
        if not isinstance(category, dict):
            raise ArtStyleCatalogError(f"{loc} 必须是对象")
        for field in REQUIRED_CATEGORY_FIELDS:
            _require_text(category.get(field), field, loc=loc)
        category_id = str(category["id"]).strip()
        if category_id in category_ids:
            raise ArtStyleCatalogError(f"分类 id 重复：{category_id}")
        category_ids.add(category_id)

    style_ids: set[str] = set()
    for index, style in enumerate(styles):
        loc = f"styles[{index}]"
        if not isinstance(style, dict):
            raise ArtStyleCatalogError(f"{loc} 必须是对象")
        for field in REQUIRED_STYLE_FIELDS:
            if field == "keywords":
                keywords = style.get("keywords")
                if not isinstance(keywords, list) or not keywords:
                    raise ArtStyleCatalogError(f"{loc} 缺少 keywords")
                continue
            _require_text(style.get(field), field, loc=loc)
        style_id = str(style["id"]).strip()
        if style_id in style_ids:
            raise ArtStyleCatalogError(f"画风 id 重复：{style_id}")
        style_ids.add(style_id)
        category = str(style["category"]).strip()
        if category not in category_ids:
            raise ArtStyleCatalogError(f"{loc} 的 category={category} 不在分类目录中")


@lru_cache(maxsize=1)
def load_art_style_catalog() -> dict[str, Any]:
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ArtStyleCatalogError("画风目录 JSON 根节点必须是对象")
    _validate_catalog(raw)
    return raw


def list_art_style_categories() -> list[dict[str, str]]:
    catalog = load_art_style_catalog()
    return [
        {
            "id": str(item["id"]).strip(),
            "name_zh": str(item["name_zh"]).strip(),
            "name_en": str(item["name_en"]).strip(),
        }
        for item in catalog["categories"]
        if isinstance(item, dict)
    ]


def _category_map() -> dict[str, dict[str, str]]:
    return {item["id"]: item for item in list_art_style_categories()}


def _public_style(style: dict[str, Any], categories: dict[str, dict[str, str]]) -> dict[str, Any]:
    category = categories.get(str(style["category"]).strip(), {})
    keywords = [
        str(item).strip()
        for item in (style.get("keywords") or [])
        if str(item).strip()
    ]
    return {
        "id": str(style["id"]).strip(),
        "name_zh": str(style["name_zh"]).strip(),
        "name_en": str(style["name_en"]).strip(),
        "category": str(style["category"]).strip(),
        "category_name_zh": category.get("name_zh", ""),
        "category_name_en": category.get("name_en", ""),
        "description": str(style.get("description") or "").strip(),
        "promptPrefix": str(style["promptPrefix"]).strip(),
        "imageUrl": public_preview_url(str(style["id"]).strip()),
        "keywords": keywords,
    }


def public_preview_url(style_id: str) -> str:
    return f"/api/director/art-styles/{style_id}/preview"


def source_preview_url(style_id: str) -> str | None:
    needle = (style_id or "").strip()
    if not needle:
        return None
    catalog = load_art_style_catalog()
    for style in catalog["styles"]:
        if isinstance(style, dict) and str(style.get("id") or "").strip() == needle:
            url = str(style.get("imageUrl") or "").strip()
            return url or None
    return None


def preview_file_path(style_id: str) -> Path:
    return PREVIEW_DIR / f"{style_id}.jpg"


def ensure_art_style_preview(style_id: str) -> Path:
    found = get_art_style(style_id)
    if found is None:
        raise KeyError(style_id)
    dest = preview_file_path(found["id"])
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    source = source_preview_url(found["id"])
    if not source:
        raise ArtStyleCatalogError(f"{found['id']} 没有预览图源")
    with _PREVIEW_LOCK:
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            source,
            headers={"User-Agent": "ZLY-AI-Video-Studio/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read()
        except (OSError, urllib.error.URLError) as error:
            raise ArtStyleCatalogError(f"无法下载画风预览：{error}") from error
        if not data.startswith(JPEG_MAGIC):
            raise ArtStyleCatalogError("画风预览不是 JPEG")
        tmp = dest.with_suffix(".jpg.part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return dest


def list_art_styles() -> list[dict[str, Any]]:
    catalog = load_art_style_catalog()
    categories = _category_map()
    return [
        _public_style(style, categories)
        for style in catalog["styles"]
        if isinstance(style, dict)
    ]


def get_art_style(style_id: str) -> dict[str, Any] | None:
    needle = (style_id or "").strip()
    if not needle:
        return None
    for style in list_art_styles():
        if style["id"] == needle:
            return style
    return None


def find_art_style(ref: Any) -> dict[str, Any] | None:
    """Resolve a catalog style by id, Chinese name, or English name. Empty ref → None."""
    if ref is None:
        return None
    if isinstance(ref, str):
        needle = ref.strip()
        if not needle:
            return None
        by_id = get_art_style(needle)
        if by_id is not None:
            return by_id
        lowered = needle.casefold()
        for style in list_art_styles():
            if style["name_zh"] == needle or style["name_en"].casefold() == lowered:
                return style
        return None
    if not isinstance(ref, dict):
        return None
    style_id = str(ref.get("id") or "").strip()
    if style_id:
        found = get_art_style(style_id)
        if found is not None:
            return found
        return None
    name = str(ref.get("name") or ref.get("name_zh") or ref.get("name_en") or "").strip()
    if not name:
        return None
    return find_art_style(name)


def art_style_catalog_payload() -> dict[str, Any]:
    styles = list_art_styles()
    return {
        "categories": list_art_style_categories(),
        "styles": styles,
        "count": len(styles),
    }


def art_style_ref_for_recipe(style: dict[str, Any]) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "id": style["id"],
        "name": style["name_zh"],
        "name_en": style["name_en"],
        "promptPrefix": style["promptPrefix"],
    }
    image_url = str(style.get("imageUrl") or "").strip()
    if image_url:
        ref["imageUrl"] = image_url
    return ref
