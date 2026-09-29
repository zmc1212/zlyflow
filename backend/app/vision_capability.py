"""Endpoint-scoped vision evidence; model-name guesses are migration hints only."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
import threading
import time
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .llm_client import LlmTemporaryError, OpenAICompatibleClient
from .llm_request_policy import chat_policy, probe_token_budget

VISION_CAP_UNKNOWN = "unknown"
VISION_CAP_SUPPORTED = "supported"
VISION_CAP_UNSUPPORTED = "unsupported"
VISION_SOURCE_PROBE = "probe"
VISION_SOURCE_CATALOG = "catalog"
VISION_SOURCE_LEGACY_NAME_GUESS = "legacy_name_guess"
VISION_SOURCE_MANUAL = "manual"
VISION_PROBE_TIMEOUT = 20.0
VISION_PROBE_MAX_TOKENS = 32
VISION_CACHE_SECONDS = 24 * 60 * 60
_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_CACHE_LOCK = threading.RLock()


def _color_png(rgb: bytes) -> str:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
    raw = b"\x89PNG\r\n\x1a\n"
    raw += chunk(b"IHDR", struct.pack("!2I5B", 32, 32, 8, 2, 0, 0, 0))
    raw += chunk(b"IDAT", zlib.compress((b"\0" + rgb * 32) * 32))
    raw += chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


RED_PROBE_DATA_URL = _color_png(b"\xff\0\0")
BLUE_PROBE_DATA_URL = _color_png(b"\0\0\xff")
VISION_PROBE_SYSTEM_PROMPT = "Name the solid color of the attached image. Reply with one color word only."
VISION_PROBE_USER_PROMPT = "What color is this image?"


@dataclass(frozen=True)
class VisionProbeResult:
    capability: str
    message: str
    reply: str = ""


def credentials_fingerprint(base_url: str | None, api_key_encrypted: str | None,
                            model: str | None = None, profile_id: str | None = None) -> str:
    identity = [str(profile_id or ""), str(base_url or "").strip().rstrip("/"),
                str(model or "").strip(), str(api_key_encrypted or "")]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=True).encode()).hexdigest()


def row_fingerprint(row: dict[str, Any]) -> str:
    return credentials_fingerprint(row.get("base_url"), row.get("api_key_encrypted") or row.get("api_key"),
                                   row.get("model"), row.get("profile_id"))


def sanitize_probe_error(exc: Any, api_key: str = "") -> str:
    text = str(exc).replace("\n", " ").replace("\r", " ")
    if api_key:
        text = text.replace(api_key, "[redacted]")
    text = re.sub(r"(?i)(bearer\s+|(?:api[_-]?key|authorization|token)\s*[:=]\s*)[^\s,;]+",
                  r"\1[redacted]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", text)
    return text[:240].strip() or "上游未提供错误摘要"


_COLOR_ZH = {"red": ("红",), "blue": ("蓝",)}


def _color_matches(color: str, expected: str) -> bool:
    """宽松颜色校验：精确 / 单词边界 / 中文颜色词三层匹配。"""
    if color == expected:
        return True
    if re.search(r"\b" + re.escape(expected) + r"\b", color):
        return True
    for zh in _COLOR_ZH.get(expected, ()):
        if zh in color:
            return True
    return False


_COLOR_ZH = {"red": ("红",), "blue": ("蓝",)}


def _color_matches(color: str, expected: str) -> bool:
    # wide color check: exact / word-boundary / Chinese color word
    if color == expected:
        return True
    if re.search(r"\\b" + re.escape(expected) + r"\\b", color):
        return True
    for zh in _COLOR_ZH.get(expected, ()):
        if zh in color:
            return True
    return False


def probe_vision_capability(*, base_url: str, api_key: str, model: str,
                           timeout: float | None = None, semantic_check: bool = True) -> VisionProbeResult:
    if timeout is None:
        timeout = 90.0 if chat_policy(model, base_url).thinking_required else VISION_PROBE_TIMEOUT
    deadline = time.monotonic() + timeout
    replies = []
    try:
        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        samples = [("red", RED_PROBE_DATA_URL), ("blue", BLUE_PROBE_DATA_URL)] if semantic_check else [("red", RED_PROBE_DATA_URL)]
        for expected, image in samples:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("视觉探测超时")
            probe_text = VISION_PROBE_SYSTEM_PROMPT + "\n" + VISION_PROBE_USER_PROMPT
            reply = client.chat_completion(
                [{"role": "user", "content": [
                    {"type": "text", "text": probe_text},
                    {"type": "image_url", "image_url": {"url": image}},
                ]}],
                model=model, temperature=0,
                max_tokens=probe_token_budget(model, base_url, VISION_PROBE_MAX_TOKENS),
                timeout=remaining, stream=False, reasoning_effort="none",
            )
            color = str(reply or "").strip().lower().strip(" .\u3002!")
            if not color or (semantic_check and not _color_matches(color, expected)):
                snippet = str(reply or "").strip()[:60]
                msg = (
                    "视觉语义校验未通过；"
                    "请检查模型是否真正接收图片。"
                    "模型实际回复：" + repr(snippet)
                )
                return VisionProbeResult(VISION_CAP_UNSUPPORTED, msg)
            replies.append(color)
    except (LlmTemporaryError, TimeoutError) as exc:
        return VisionProbeResult(VISION_CAP_UNKNOWN,
                                 "视觉探测暂未完成：" + sanitize_probe_error(exc, api_key))
    except Exception as exc:
        return VisionProbeResult(VISION_CAP_UNSUPPORTED,
                                 "视觉探测失败：" + sanitize_probe_error(exc, api_key))
    return VisionProbeResult(VISION_CAP_SUPPORTED,
                             "双色图视觉验证通过" if semantic_check else "图片请求通过（未做语义校验）",
                             " / ".join(replies))

def unknown_vision_fields() -> dict[str, Any]:
    return {"vision_capability": VISION_CAP_UNKNOWN, "vision_capability_source": None,
            "vision_capability_checked_at": None, "vision_capability_message": None,
            "vision_capability_fingerprint": None}


def invalidate_changed_capability(previous: dict[str, Any], updates: dict[str, Any]) -> None:
    if "vision_capability" not in updates and any(
        key in updates and updates[key] != previous.get(key)
        for key in ("profile_id", "base_url", "model", "api_key_encrypted", "use_llm_credentials")
    ):
        updates.update(unknown_vision_fields())


def probe_fields(row: dict[str, Any], result: VisionProbeResult) -> dict[str, Any]:
    fields = {"vision_capability": result.capability, "vision_capability_source": VISION_SOURCE_PROBE,
              "vision_capability_checked_at": datetime.now(timezone.utc).isoformat(),
              "vision_capability_message": result.message, "vision_capability_fingerprint": row_fingerprint(row)}
    with _CACHE_LOCK:
        _CACHE[row_fingerprint(row)] = dict(fields)
        _CACHE.move_to_end(row_fingerprint(row))
        while len(_CACHE) > 128:
            _CACHE.popitem(last=False)
    return fields


def evidence_for_saved_connection(candidate: dict[str, Any], api_key: str | None,
                                  previous: dict[str, Any], previous_key: str | None) -> dict[str, Any]:
    """保存时将同一实际连接的服务端探测证据绑定到持久化指纹。

    临时表单使用明文密钥身份，保存使用随机加密密文身份；仅迁移服务端缓存中
    的新鲜探测证据，保留原时间，不接受客户端能力声明或跨连接证据。
    """
    if not api_key:
        return {}
    preview = {**candidate, "api_key_encrypted": None, "api_key": api_key}
    fields = capability_fields(preview)
    same_connection = api_key == previous_key and all(
        candidate.get(name) == previous.get(name) for name in ("profile_id", "base_url", "model")
    )
    if fields.get("vision_capability_source") != VISION_SOURCE_PROBE and same_connection:
        fields = capability_fields(previous)
    if (fields.get("vision_capability_source") != VISION_SOURCE_PROBE
            or fields.get("vision_capability") not in {VISION_CAP_SUPPORTED, VISION_CAP_UNSUPPORTED}):
        return {}
    return {**fields, "vision_capability_fingerprint": row_fingerprint(candidate)}


def _fresh(fields: dict[str, Any], row: dict[str, Any]) -> bool:
    if fields.get("vision_capability_fingerprint") != row_fingerprint(row):
        return False
    try:
        checked = datetime.fromisoformat(str(fields["vision_capability_checked_at"]).replace("Z", "+00:00"))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        return 0 <= (datetime.now(timezone.utc) - checked).total_seconds() < VISION_CACHE_SECONDS
    except (ValueError, TypeError, KeyError):
        return False


def capability_fields(row: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(row or {})
    fields = {key: data.get(key) for key in unknown_vision_fields()}
    if data.get("vision_capability_source") != VISION_SOURCE_LEGACY_NAME_GUESS and _fresh(data, data):
        return fields
    with _CACHE_LOCK:
        cached = _CACHE.get(row_fingerprint(data))
        if cached and _fresh(cached, data):
            return dict(cached)
    if data.get("vision_capability_source") == VISION_SOURCE_LEGACY_NAME_GUESS:
        return {**fields, "vision_capability": VISION_CAP_UNKNOWN}
    return unknown_vision_fields()


def row_vision_capability(row: dict[str, Any] | None) -> str:
    cap = capability_fields(row)["vision_capability"]
    return cap if cap in {VISION_CAP_SUPPORTED, VISION_CAP_UNSUPPORTED} else VISION_CAP_UNKNOWN


def row_supports_vision(row: dict[str, Any] | None) -> bool:
    return row_vision_capability(row) == VISION_CAP_SUPPORTED


def ensure_vision_capability(row: dict[str, Any], api_key: str) -> dict[str, Any]:
    with _CACHE_LOCK:
        current = capability_fields(row)
        if current["vision_capability"] != VISION_CAP_UNKNOWN:
            return {**row, **current}
        result = probe_vision_capability(base_url=str(row.get("base_url") or ""),
                                        model=str(row.get("model") or ""), api_key=api_key)
        return {**row, **probe_fields(row, result)}


def vision_capability_fields_for_backfill(model: str | None) -> dict[str, Any]:
    from .llm_provider import model_supports_vision
    return {"vision_capability": VISION_CAP_SUPPORTED if model_supports_vision(model) else VISION_CAP_UNKNOWN,
            "vision_capability_source": VISION_SOURCE_LEGACY_NAME_GUESS,
            "vision_capability_message": "历史名称推断，仅供参考；请重新探测视觉能力。"}
