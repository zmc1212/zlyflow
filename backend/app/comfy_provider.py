from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests

from .storage import JobStore, now


class ComfyProviderError(RuntimeError):
    """ComfyUI 地址无效或连接测试失败。"""


def validate_comfy_base_url(value: str) -> str:
    text = (value or "").strip().rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("ComfyUI 地址必须是有效的 HTTP 或 HTTPS URL，例如 http://127.0.0.1:8188")
    if parsed.username or parsed.password:
        raise ValueError("ComfyUI 地址不能包含用户名或密码")
    if parsed.query or parsed.fragment:
        raise ValueError("ComfyUI 地址不能包含查询参数或片段")
    return text


class ComfyProviderService:
    """Runtime ComfyUI base URL stored in SQLite, seeded from the env default."""

    def __init__(self, store: JobStore, default_url: str) -> None:
        self.store = store
        self.default_url = validate_comfy_base_url(default_url)

    def current_url(self) -> str:
        config = self.store.get_comfy_settings()
        url = str(config.get("base_url") or "").strip()
        return url.rstrip("/") if url else self.default_url

    def public_config(self) -> dict[str, Any]:
        config = self.store.get_comfy_settings()
        return {
            "base_url": self.current_url(),
            "env_default": self.default_url,
            "last_test_status": config.get("last_test_status"),
            "last_test_message": config.get("last_test_message"),
            "last_test_at": config.get("last_test_at"),
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = validate_comfy_base_url(str(payload.get("base_url") or ""))
        self.store.update_comfy_settings(base_url=url)
        return self.public_config()

    def test(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        submitted = str((payload or {}).get("base_url") or "").strip()
        url = validate_comfy_base_url(submitted or self.current_url())
        timestamp = now()
        try:
            response = requests.get(f"{url}/system_stats", timeout=5)
            if not response.ok:
                raise ComfyProviderError(f"ComfyUI 返回 HTTP {response.status_code}")
            self.store.update_comfy_settings(
                last_test_status="success",
                last_test_message="已连通 /system_stats",
                last_test_at=timestamp,
            )
        except Exception as error:
            message = str(error)
            self.store.update_comfy_settings(
                last_test_status="failed",
                last_test_message=message,
                last_test_at=timestamp,
            )
            if isinstance(error, (ValueError, ComfyProviderError)):
                raise
            raise ComfyProviderError(f"无法连接 ComfyUI：{message}") from error
        return self.public_config()
