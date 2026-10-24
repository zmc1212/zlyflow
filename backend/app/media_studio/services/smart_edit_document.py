"""Versioned, frame-aligned editing document shared by preview and export.

All times are seconds on the output timeline. duration is AFTER speed changes;
in_point is in source seconds. One lane each for picture, soundtrack and text.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any
from urllib.parse import urlsplit

from ...local_media import LOCAL_MEDIA_PREFIX, is_valid_token

EFFECTS = {"none", "mono", "sepia", "warm", "cool", "vivid", "soft", "fade"}
RATIOS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:3": (1440, 1080), "3:4": (1080, 1440)}
MAX_DURATION = 1800


def wrap_text(text: str, font_size: float) -> str:
    """The same conservative character widths as the browser model.

    Both sides render these explicit breaks; neither renderer wraps implicitly.
    Font size is expressed on a logical 1920px-wide canvas for all aspect ratios.
    """
    limit = 1920 * .86 / font_size
    output, line, used = [], "", 0.0
    for char in text.replace("\r\n", "\n").replace("\r", "\n"):
        if char == "\n":
            output.append(line)
            line, used = "", 0.0
            continue
        weight = 1.0 if ord(char) > 127 else .35 if char in " il.,'`:;!|" else .95 if char in "MWmw@#%&" else .65
        if line and used + weight > limit:
            output.append(line)
            line, used = "", 0.0
        line += char
        used += weight
    output.append(line)
    return "\n".join(output)


def empty_document(name: str = "未命名剪辑") -> dict[str, Any]:
    return {"version": 1, "name": name, "settings": {"ratio": "16:9", "fps": 24, "background": "#000000"}, "assets": [], "clips": []}


def number(value: Any, minimum: float, maximum: float, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label}必须是数字")
    try:
        result = float(value)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{label}必须是数字") from error
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{label}需在 {minimum:g}–{maximum:g} 之间")
    return result


def media_url(value: Any) -> str:
    url = str(value or "")
    if len(url) > 4096:
        raise ValueError("素材地址过长，请重新导入素材")
    if url.startswith(LOCAL_MEDIA_PREFIX):
        if not is_valid_token(url[len(LOCAL_MEDIA_PREFIX):]):
            raise ValueError("本机素材地址无效，请重新导入素材")
        return url
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("素材需要有效的 HTTP(S) 或本机引用地址，请重新导入素材")
    return url


def validate_document(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("不支持的剪辑工程版本")
    doc = copy.deepcopy(raw)
    doc["name"] = str(doc.get("name") or "未命名剪辑").strip()[:120]
    settings = doc.get("settings")
    if not isinstance(settings, dict) or settings.get("ratio") not in RATIOS or settings.get("fps") not in (24, 25, 30, 60):
        raise ValueError("请选择有效的画面比例和帧率")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(settings.get("background"))):
        raise ValueError("背景颜色无效")
    assets, clips = doc.get("assets"), doc.get("clips")
    if not isinstance(assets, list) or len(assets) > 300 or not isinstance(clips, list) or len(clips) > 200:
        raise ValueError("单个工程最多 300 个素材、200 个片段")
    ids: set[str] = set()
    by_asset = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("id"), str) or not asset["id"] or len(asset["id"]) > 160 or asset["id"] in ids:
            raise ValueError("素材 ID 无效或重复")
        ids.add(asset["id"])
        if asset.get("kind") not in {"video", "image", "audio"}:
            raise ValueError("不支持的素材类型")
        asset["url"] = media_url(asset.get("url"))
        if asset.get("thumbnail"):
            asset["thumbnail"] = media_url(asset["thumbnail"])
        asset["name"] = str(asset.get("name") or "素材")[:200]
        asset["duration"] = number(asset.get("duration", 5), .04, 86400, "素材时长")
        by_asset[asset["id"]] = asset
    ids.clear()
    lanes: dict[str, list] = {"video": [], "audio": [], "text": []}
    fps = settings["fps"]
    for clip in clips:
        if not isinstance(clip, dict) or not isinstance(clip.get("id"), str) or not clip["id"] or len(clip["id"]) > 160 or clip["id"] in ids:
            raise ValueError("片段 ID 无效或重复")
        ids.add(clip["id"])
        track = clip.get("track")
        if track not in lanes:
            raise ValueError("无效的时间线轨道")
        for key, default, low, high in (("start", 0, 0, MAX_DURATION), ("duration", 5, 1 / fps, MAX_DURATION), ("in_point", 0, 0, 86400), ("speed", 1, .25, 4), ("volume", 1, 0, 2), ("opacity", 1, 0, 1), ("scale", 1, .25, 3), ("x", 0, -100, 100), ("y", 0, -100, 100), ("rotation", 0, -180, 180), ("fade_in", 0, 0, 10), ("fade_out", 0, 0, 10), ("font_size", 64, 16, 200)):
            clip[key] = number(clip.get(key, default), low, high, key)
        for key in ("start", "duration"):
            if abs(clip[key] * fps - round(clip[key] * fps)) > .001:
                raise ValueError("片段时间必须对齐工程帧率")
        if clip["start"] + clip["duration"] > MAX_DURATION + .001:
            raise ValueError("时间线最长为 30 分钟")
        clip["muted"] = bool(clip.get("muted", False))
        if clip.get("effect", "none") not in EFFECTS:
            raise ValueError("不支持的画面特效")
        clip["effect"] = clip.get("effect", "none")
        if clip["fade_in"] + clip["fade_out"] > clip["duration"] + .001:
            raise ValueError("淡入淡出时长不能超过片段时长")
        if track == "text":
            clip["text"] = str(clip.get("text") or "")[:1000]
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(clip.get("color", "#ffffff"))):
                raise ValueError("文字颜色无效")
            clip["color"] = clip.get("color", "#ffffff")
        else:
            asset = by_asset.get(clip.get("asset_id"))
            if not asset or (track == "audio" and asset["kind"] != "audio") or (track == "video" and asset["kind"] == "audio"):
                raise ValueError("片段引用了缺失或类型不匹配的素材")
            if asset["kind"] != "image" and clip["in_point"] + clip["duration"] * clip["speed"] > asset["duration"] + .1:
                raise ValueError("片段超出原始素材时长")
        lanes[track].append(clip)
    for lane in lanes.values():
        lane.sort(key=lambda c: c["start"])
        for previous, current in zip(lane, lane[1:]):
            if current["start"] < previous["start"] + previous["duration"] - .001:
                raise ValueError("同一轨道内的片段不能重叠，请移动到空白位置")
    return doc


def timeline_duration(doc: dict) -> float:
    return max((c["start"] + c["duration"] for c in doc["clips"]), default=0)
