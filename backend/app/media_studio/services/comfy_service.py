from __future__ import annotations

from urllib.parse import urlparse

from ..models import ComfyConfigResponse
from ..provider_bridge import COMFY_DEFAULT_URL, comfy_row


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


class ComfyService:
    DEFAULT_URL = COMFY_DEFAULT_URL

    @classmethod
    def get_config(cls) -> ComfyConfigResponse:
        row = comfy_row()
        if not row:
            return ComfyConfigResponse(
                base_url=cls.DEFAULT_URL,
                env_default=cls.DEFAULT_URL,
            )
        return ComfyConfigResponse(
            base_url=row.get("base_url") or cls.DEFAULT_URL,
            env_default=cls.DEFAULT_URL,
            last_test_status=row.get("last_test_status"),
            last_test_message=row.get("last_test_message"),
            last_test_at=row.get("last_test_at"),
        )
