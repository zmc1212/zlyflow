"""Bounded, credential-free image delivery for Aliyun OpenAI-compatible APIs.

Only the wire payload changes. Persisted URLs, picture order and model selection
stay intact; a missing image fails the call instead of becoming text-only.
"""
from __future__ import annotations

import base64
import binascii
import io
import ipaddress
import socket
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_ENCODED_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_EDGE = 2048
DOWNLOAD_SECONDS = 30.0
PREPARATION_SECONDS = 90.0
MIME_BY_FORMAT = {"PNG": "image/png", "JPEG": "image/jpeg",
                  "WEBP": "image/webp", "GIF": "image/gif"}
# Same fake-IP ranges used by the workstation's proxy and existing GRS downloader.
# They are NOT generally public: the exception below is for the admin-owned CDN only.
PROXY_NETWORKS = (ipaddress.ip_network("198.18.0.0/15"),
                  ipaddress.ip_network("fdfe:dcba:9876::/48"))


class ImageTransportError(ValueError):
    """Safe-to-display error; never includes a signed URL or image content."""


def uses_inline_images(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or "").lower().rstrip(".")
    return host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com",
                    "dashscope-us.aliyuncs.com"} or host.endswith(".maas.aliyuncs.com")


def _configured_media_hostname() -> str:
    # Read only the public domain, never the storage credentials. Lazy lookup
    # keeps normal public downloads/probes independent of the database.
    from .media_studio.db import query_one
    row = query_one("SELECT domain FROM qiniu_provider_settings WHERE id=1") or {}
    parsed = urlsplit(str(row.get("domain") or ""))
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return ""
    return (parsed.hostname or "").lower().rstrip(".")


def _validate_public_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ImageTransportError("图片地址必须是无凭证的 HTTP/HTTPS 公网地址")
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
        resolved = [ipaddress.ip_address(item[4][0]) for item in addresses]
        non_public = [ip for ip in resolved if not ip.is_global]
        proxy_allowed = False
        if non_public and all(any(ip in net for net in PROXY_NETWORKS) for ip in non_public):
            try:
                proxy_allowed = (parsed.scheme == "https" and parsed.port in {None, 443}
                                 and parsed.hostname.lower().rstrip(".") == _configured_media_hostname())
            except Exception:
                proxy_allowed = False  # unavailable settings must never broaden access
        if not resolved or (non_public and not proxy_allowed):
            raise ImageTransportError("图片地址指向非公网网络，已拒绝下载")
    except (OSError, ValueError) as exc:
        if isinstance(exc, ImageTransportError):
            raise
        raise ImageTransportError("图片地址无效或无法解析") from exc


def download_image(url: str) -> bytes:
    """Use a separate session: never send the model API key to a media host."""
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    current = url
    with requests.Session() as session:
        # Do not inherit .netrc credentials or a model client's auth/cookies.
        session.trust_env = False
        for _ in range(4):
            _validate_public_url(current)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ImageTransportError("图片下载超时")
            try:
                with session.get(current, timeout=(min(5.0, remaining), min(15.0, remaining)),
                                 stream=True, allow_redirects=False) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        target = response.headers.get("Location")
                        if not target:
                            raise ImageTransportError("图片重定向缺少目标地址")
                        current = urljoin(current, target)
                        continue
                    if response.status_code != 200:
                        raise ImageTransportError(f"图片下载失败（HTTP {response.status_code}）")
                    mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                    if mime not in {*MIME_BY_FORMAT.values(), "application/octet-stream"}:
                        raise ImageTransportError("图片地址未返回受支持的图片文件")
                    length = response.headers.get("Content-Length", "")
                    if length.isdigit() and int(length) > MAX_SOURCE_BYTES:
                        raise ImageTransportError("参考原图超过 20 MB，请缩小后重试")
                    content = bytearray()
                    for chunk in response.iter_content(64 * 1024):
                        if time.monotonic() > deadline:
                            raise ImageTransportError("图片下载超时")
                        content.extend(chunk)
                        if len(content) > MAX_SOURCE_BYTES:
                            raise ImageTransportError("参考原图超过 20 MB，请缩小后重试")
                    return bytes(content)
            except requests.Timeout as exc:
                raise ImageTransportError("图片下载超时") from exc
            except requests.RequestException as exc:
                raise ImageTransportError("无法下载参考图片，请检查图片存储连接") from exc
    raise ImageTransportError("图片重定向次数过多")


def _read_data_url(url: str) -> bytes:
    header, sep, encoded = url.partition(",")
    if not sep or not header.startswith("data:image/") or not header.endswith(";base64"):
        raise ImageTransportError("内嵌参考图片必须使用 Base64 图片格式")
    if len(encoded) > (MAX_SOURCE_BYTES + 2) // 3 * 4:
        raise ImageTransportError("参考原图超过 20 MB，请缩小后重试")
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ImageTransportError("内嵌参考图片的 Base64 无效") from exc


def _encode_image(content: bytes, budget: int) -> str:
    if not content or len(content) > MAX_SOURCE_BYTES:
        raise ImageTransportError("参考图片为空或超过 20 MB")
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ImageTransportError("参考图片像素过大，请缩小后重试")
            if getattr(source, "n_frames", 1) != 1:
                raise ImageTransportError("请使用静态参考图片，不支持动态图")
            mime = MIME_BY_FORMAT.get(source.format)
            if not mime:
                raise ImageTransportError("参考图片格式不受支持")
            source.load()
            # Preserve original bytes whenever they fit, including the vision probe.
            if len(content) <= budget and max(source.size) <= MAX_IMAGE_EDGE:
                return f"data:{mime};base64," + base64.b64encode(content).decode("ascii")
            image = ImageOps.exif_transpose(source)
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
            for attempt in range(6):
                output = io.BytesIO()
                if has_alpha:
                    image.save(output, format="PNG", optimize=True)
                    mime = "image/png"
                else:
                    image.save(output, format="JPEG", quality=max(80, 95 - attempt * 3), optimize=True)
                    mime = "image/jpeg"
                raw = output.getvalue()
                if len(raw) <= budget:
                    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
                image.thumbnail((max(1, int(image.width * 0.8)), max(1, int(image.height * 0.8))),
                                Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        if isinstance(exc, ImageTransportError):
            raise
        raise ImageTransportError("参考图片损坏或无法解码") from exc
    raise ImageTransportError("参考图片压缩后仍过大，请减少参考图或缩小图片")


def prepare_chat_images(messages: list[dict[str, Any]], base_url: str,
                        *, meta_out: dict[str, Any]) -> list[dict[str, Any]]:
    if not uses_inline_images(base_url):
        return messages
    count = sum(1 for message in messages if isinstance(message.get("content"), list)
                for part in message["content"] if isinstance(part, dict) and part.get("type") == "image_url")
    if not count:
        return messages
    meta_out.update(image_transport="inline_base64", image_count=count, inlined_image_count=0, image_payload_bytes=0)
    # Reserve the data-URL headers inside the 8 MiB aggregate image budget.
    budget = min(MAX_IMAGE_BYTES, ((MAX_ENCODED_BYTES - count * 64) // count // 4) * 3)
    if budget < 16 * 1024:
        raise ImageTransportError("参考图片数量过多，请减少后重试")
    deadline = time.monotonic() + PREPARATION_SECONDS
    cache: dict[str, str] = {}
    result = []
    position = 0
    for message in messages:
        if not isinstance(message.get("content"), list):
            result.append(message)
            continue
        parts = []
        for part in message["content"]:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                parts.append(part)
                continue
            position += 1
            info = part.get("image_url")
            url = info.get("url") if isinstance(info, dict) else info
            try:
                if not isinstance(url, str) or not url.strip():
                    raise ImageTransportError("参考图片地址为空")
                if time.monotonic() > deadline:
                    raise ImageTransportError("参考图片准备超时")
                if url not in cache:
                    content = _read_data_url(url) if url.startswith("data:") else download_image(url)
                    cache[url] = _encode_image(content, budget)
                inline = cache[url]
            except ImageTransportError as exc:
                raise ImageTransportError(f"第 {position} 张参考图准备失败：{exc}") from exc
            parts.append({**part, "image_url": {**(info if isinstance(info, dict) else {}), "url": inline}})
            meta_out["inlined_image_count"] += 1
            meta_out["image_payload_bytes"] += len(inline)
        result.append({**message, "content": parts})
    return result
