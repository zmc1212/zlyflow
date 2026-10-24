"""Signed references to media files that stay in their original local folder.

Local assets are never copied or uploaded. A document stores only an opaque
token that binds the absolute path to the workbench credential key, so a saved
timeline keeps working after a restart without exposing a writable path API.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from pathlib import Path
from urllib.parse import unquote

LOCAL_MEDIA_PREFIX = "/api/local-media/"
_TOKEN = re.compile(r"([A-Za-z0-9_-]{4,2048})\.([0-9a-f]{32})")
LOCAL_MEDIA_EXTENSIONS = {
    ".mp4": "video", ".mov": "video", ".webm": "video", ".mkv": "video",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".ogg": "audio", ".flac": "audio",
}


class LocalMediaError(ValueError):
    pass


def _secret() -> bytes:
    from .config import settings
    key = settings.credential_key
    if not key:
        raise LocalMediaError("本机素材签名密钥不可用，请通过启动脚本运行工作台")
    return key.encode("utf-8")


def _sign(payload: str) -> str:
    return hmac.new(_secret(), f"local-media:{payload}".encode("ascii"), hashlib.sha256).hexdigest()[:32]


def encode_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    if not resolved.is_absolute():
        raise LocalMediaError("本机素材必须是绝对路径")
    payload = base64.urlsafe_b64encode(str(resolved).encode("utf-8")).decode("ascii").rstrip("=")
    return f"{payload}.{_sign(payload)}"


def url_for_path(path: Path) -> str:
    return LOCAL_MEDIA_PREFIX + encode_path(path)


def is_valid_token(token: str) -> bool:
    return bool(_TOKEN.fullmatch(token))


def path_for_token(token: str) -> Path:
    match = _TOKEN.fullmatch(unquote(token))
    if not match:
        raise LocalMediaError("本机素材地址无效")
    payload, signature = match.groups()
    if not hmac.compare_digest(signature, _sign(payload)):
        raise LocalMediaError("本机素材签名校验失败，请重新导入")
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise LocalMediaError("本机素材地址无效") from error
    path = Path(raw)
    if not path.is_absolute():
        raise LocalMediaError("本机素材地址无效")
    if not path.is_file():
        raise LocalMediaError(f"本机素材不存在或已移动：{path}")
    return path


def path_for_url(url: str) -> Path:
    if not url.startswith(LOCAL_MEDIA_PREFIX):
        raise LocalMediaError("不是本机素材地址")
    return path_for_token(url[len(LOCAL_MEDIA_PREFIX):])


def is_local_url(url: str) -> bool:
    return str(url or "").startswith(LOCAL_MEDIA_PREFIX)


def import_roots() -> list[Path]:
    from .config import settings
    roots = []
    for raw in settings.local_media_roots:
        try:
            roots.append(Path(raw).expanduser().resolve())
        except OSError:
            continue
    return roots


def ensure_import_allowed(path: Path, user: dict) -> Path:
    """Admins may reference any readable local file; employees only approved roots."""
    resolved = path.expanduser().resolve()
    if user.get("role") in {"super_admin", "admin"}:
        return resolved
    roots = import_roots()
    if not roots or not any(resolved == root or root in resolved.parents for root in roots):
        raise PermissionError("本机路径导入仅限管理员，或由管理员配置允许目录")
    return resolved


def ensure_export_allowed(path: Path, user: dict) -> Path:
    """Admins may write anywhere writable; employees only approved roots."""
    resolved = path.expanduser().resolve()
    if resolved.exists() and not resolved.is_dir():
        raise ValueError("导出位置必须是文件夹路径")
    if user.get("role") not in {"super_admin", "admin"}:
        roots = import_roots()
        if not roots or not any(resolved == root or root in resolved.parents for root in roots):
            raise PermissionError("导出到自定义目录仅限管理员，或由管理员配置允许目录")
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ValueError(f"无法创建导出目录：{error}") from error
    if not os.access(resolved, os.W_OK):
        raise ValueError("导出目录不可写")
    return resolved
