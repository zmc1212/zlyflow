from __future__ import annotations

import io
from typing import Any
from urllib.parse import urlparse

from PIL import Image


PANEL_KEYS = ("start", "mid", "end")


def split_triptych_image(image: Image.Image) -> dict[str, Image.Image]:
    width, height = image.size
    if width < 3 or height < 1:
        raise ValueError("三联图尺寸无效")
    panel_width = max(1, width // 3)
    boxes = {
        "start": (0, 0, panel_width, height),
        "mid": (panel_width, 0, panel_width * 2, height),
        "end": (panel_width * 2, 0, width, height),
    }
    return {key: image.crop(box) for key, box in boxes.items()}


def split_triptych_bytes(data: bytes) -> dict[str, bytes]:
    with Image.open(io.BytesIO(data)) as image:
        rgb = image.convert("RGB")
        panels = split_triptych_image(rgb)
        out: dict[str, bytes] = {}
        for key, panel in panels.items():
            buffer = io.BytesIO()
            panel.save(buffer, format="JPEG", quality=92)
            out[key] = buffer.getvalue()
        return out


def split_triptych_path(path: str) -> dict[str, bytes]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        panels = split_triptych_image(rgb)
        out: dict[str, bytes] = {}
        for key, panel in panels.items():
            buffer = io.BytesIO()
            panel.save(buffer, format="JPEG", quality=92)
            out[key] = buffer.getvalue()
        return out


def split_triptych_url(url: str) -> dict[str, bytes]:
    import requests

    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("三联图地址无效")
    response = requests.get(str(url).strip(), timeout=60)
    response.raise_for_status()
    return split_triptych_bytes(response.content)


def persist_panel_bytes(panels: dict[str, bytes]) -> dict[str, str]:
    stored = empty_panels()
    try:
        from ..media_studio.services.qiniu_service import QiniuService
    except Exception:
        QiniuService = None  # type: ignore[assignment]
    for key, data in panels.items():
        url = ""
        if QiniuService is not None:
            try:
                _key, url = QiniuService.store_bytes("image", f"triptych-{key}.jpg", data)
            except Exception:
                url = ""
        stored[key] = str(url or "").strip() or f"memory:{key}:{len(data)}"
    return stored


def empty_panels() -> dict[str, str]:
    return {key: "" for key in PANEL_KEYS}


def normalize_panels(raw: Any) -> dict[str, str]:
    data = raw if isinstance(raw, dict) else {}
    return {key: str(data.get(key) or "").strip() for key in PANEL_KEYS}


def public_panel_url(value: Any) -> str:
    url = str(value or "").strip()
    if url.startswith(("http://", "https://")):
        return url
    return ""


def build_triptych_generation_prompt(
    beat: dict[str, Any],
    *,
    template: str = "",
    aspect_ratio: Any = None,
    previous_beat: dict[str, Any] | None = None,
) -> str:
    from .aspect import format_aspect_template, resolve_workshop_aspect_ratio, triptych_panel_geometry_en

    action = str(beat.get("action") or "").strip()
    camera = str(beat.get("camera") or "").strip()
    heading = str(beat.get("heading") or beat.get("scene") or "").strip()
    dialogue = str(beat.get("dialogue") or "").strip()
    narration = str(beat.get("narration") or "").strip()
    aspect = resolve_workshop_aspect_ratio(request=aspect_ratio or beat.get("aspect_ratio"))
    fallback = (
        "OUTPUT CANVAS: one 16:9 master containing three equal {panel_geometry} panels left/center/right. "
        "All three panels are finished-shot {aspect} compositions."
    )
    source = template.strip() if str(template or "").strip() else fallback
    parts = [format_aspect_template(source, aspect)]
    if heading:
        parts.append(f"SCENE: {heading}")
    from ..media_studio.services.shot_handoff import left_panel_inherit_instruction

    inherit = left_panel_inherit_instruction(beat, previous_beat if isinstance(previous_beat, dict) else None)
    if inherit:
        parts.append(inherit)
        if action:
            parts.append(f"ACTION: {action}")
    elif action:
        parts.append(f"LEFT=start blocking, CENTER=main action, RIGHT=result. ACTION: {action}")
    if camera:
        parts.append(f"CAMERA LANGUAGE: {camera}")
    spoken = " ".join(part for part in (dialogue, narration) if part)
    if spoken:
        parts.append(f"Spoken/narration context (do not render as readable text): {spoken}")
    geometry = triptych_panel_geometry_en(aspect)
    if geometry not in parts[0]:
        parts.append(f"PANEL GEOMETRY: three equal {geometry} landmarks; crop still trisects the 16:9 master.")
    return "\n\n".join(part for part in parts if part)
