"""资产库原片参考图：规范化 extra.source_references，并在生图时并入 GRS images。"""
from __future__ import annotations

import uuid
from typing import Any, Iterable

MAX_SOURCE_REFERENCES = 9
MAX_SOURCE_REFERENCE_BYTES = 10 * 1024 * 1024
PRIMARY_GENERATION_TARGETS = {
    "avatar",
    "identity",
    "scene_master",
    "prop_reference",
    "asset",
}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _as_item(raw: Any) -> dict[str, str] | None:
    if isinstance(raw, str):
        url = raw.strip()
        if not url:
            return None
        return {"id": f"ref-{uuid.uuid4().hex[:10]}", "url": url, "filename": ""}
    if not isinstance(raw, dict):
        return None
    url = str(raw.get("url") or "").strip()
    if not url:
        return None
    ref_id = str(raw.get("id") or "").strip() or f"ref-{uuid.uuid4().hex[:10]}"
    filename = str(raw.get("filename") or "").strip()
    return {"id": ref_id, "url": url, "filename": filename}


def normalize_source_references(extra: dict[str, Any] | None) -> list[dict[str, str]]:
    extra = extra if isinstance(extra, dict) else {}
    raw = extra.get("source_references")
    if not isinstance(raw, list):
        raw = extra.get("source_reference_urls") or []
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        item = _as_item(entry)
        if not item or item["url"] in seen:
            continue
        seen.add(item["url"])
        items.append(item)
        if len(items) >= MAX_SOURCE_REFERENCES:
            break
    return items


def source_reference_urls(extra: dict[str, Any] | None) -> list[str]:
    return [item["url"] for item in normalize_source_references(extra)]


def merge_reference_urls(*groups: Iterable[str] | None, limit: int = MAX_SOURCE_REFERENCES) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not group:
            continue
        for raw in group:
            url = str(raw or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(url)
            if len(out) >= limit:
                return out
    return out


def source_reference_prompt_note(kind: str) -> str:
    if kind == "character":
        return (
            "SOURCE PHOTO REFERENCES (HIGHEST PRIORITY): The attached images are original-footage "
            "screenshots of this character. Copy that person exactly: face, age, hair, body, and "
            "EVERY visible garment and layer. Do not add a coat, jacket, shirt, sweater, tie, or "
            "any extra clothing that is not in the photos. If any later text names different "
            "clothes, age, or hairstyle, IGNORE that text. Keep a clean production-reference look."
        )
    if kind == "scene":
        subject = "location: architecture, layout, lighting, and spatial atmosphere"
    else:
        subject = "prop: shape, material, color, and wear"
    return (
        "SOURCE PHOTO REFERENCES (HIGHEST PRIORITY): The attached images are screenshots or photos "
        f"from the original footage of this {subject}. Match that identity exactly. "
        "Do not invent objects, furniture, or materials that are not in the photos. "
        "If any later text conflicts with the photos, IGNORE that text. "
        "Keep a clean production-reference presentation unless the target is an establishing scene."
    )


def sniff_image_suffix(content: bytes, filename: str = "", content_type: str = "") -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8"):
        return ".jpg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    if content.startswith(b"GIF8"):
        return ".gif"
    suffix = ""
    name = (filename or "").lower()
    for candidate in _IMAGE_SUFFIXES:
        if name.endswith(candidate):
            suffix = candidate
            break
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime in {"image/jpeg", "image/jpg"}:
        suffix = suffix or ".jpg"
    elif mime == "image/png":
        suffix = suffix or ".png"
    elif mime == "image/webp":
        suffix = suffix or ".webp"
    elif mime == "image/gif":
        suffix = suffix or ".gif"
    if suffix in _IMAGE_SUFFIXES:
        return suffix
    raise ValueError("必须为 JPG / PNG / WebP / GIF 图片")


def append_source_reference(
    extra: dict[str, Any] | None,
    *,
    url: str,
    filename: str = "",
) -> list[dict[str, str]]:
    items = normalize_source_references(extra)
    if len(items) >= MAX_SOURCE_REFERENCES:
        raise ValueError(f"每条资产最多上传 {MAX_SOURCE_REFERENCES} 张原片参考图")
    item = _as_item({"url": url, "filename": filename})
    if item is None:
        raise ValueError("参考图地址无效")
    if any(existing["url"] == item["url"] for existing in items):
        return items
    items.append(item)
    return items


def remove_source_reference(extra: dict[str, Any] | None, ref_id: str) -> list[dict[str, str]]:
    wanted = str(ref_id or "").strip()
    return [item for item in normalize_source_references(extra) if item["id"] != wanted]


def payload_image_urls(payload: dict[str, Any] | None) -> list[str]:
    raw = (payload or {}).get("images")
    if not isinstance(raw, list):
        return []
    return [str(url).strip() for url in raw if str(url or "").strip()]


def apply_source_references_to_generation(
    *,
    kind: str,
    extra: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    target_type: str,
    reference_urls: list[str] | None,
    clean_prompt: str,
) -> tuple[list[str], str]:
    """原片参考图排在最前；头像/主视角/道具主图等衍生链保持其后。"""
    source_urls = source_reference_urls(extra)
    prompt = clean_prompt or ""
    if target_type in PRIMARY_GENERATION_TARGETS:
        if source_urls:
            note = source_reference_prompt_note(kind)
            if note not in prompt:
                prompt = f"{note}\n\n{prompt}"
        merged = merge_reference_urls(source_urls, payload_image_urls(payload), reference_urls)
    else:
        merged = merge_reference_urls(payload_image_urls(payload), reference_urls)
    return merged, prompt
