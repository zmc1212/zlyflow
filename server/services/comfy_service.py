from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
import requests

from ..db import execute_sql, now_str, query_one
from ..models import ComfyConfigResponse


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
    DEFAULT_URL = "http://127.0.0.1:8188"

    @classmethod
    def get_config(cls) -> ComfyConfigResponse:
        row = query_one("SELECT * FROM ai_comfy_provider_settings WHERE id = 1")
        if not row:
            return ComfyConfigResponse(
                base_url=cls.DEFAULT_URL,
                env_default=cls.DEFAULT_URL,
            )
        return ComfyConfigResponse(
            base_url=row["base_url"] or cls.DEFAULT_URL,
            env_default=cls.DEFAULT_URL,
            last_test_status=row.get("last_test_status"),
            last_test_message=row.get("last_test_message"),
            last_test_at=row.get("last_test_at"),
        )

    @classmethod
    def update_config(cls, base_url: str) -> ComfyConfigResponse:
        valid_url = validate_comfy_base_url(base_url)
        timestamp = now_str()
        execute_sql(
            """
            INSERT INTO ai_comfy_provider_settings (id, base_url, updated_at)
            VALUES (1, %s, %s)
            ON DUPLICATE KEY UPDATE base_url = VALUES(base_url), updated_at = VALUES(updated_at)
            """,
            (valid_url, timestamp),
        )
        return cls.get_config()

    @classmethod
    def test_connection(cls, base_url: str | None = None) -> ComfyConfigResponse:
        current = cls.get_config()
        test_url = validate_comfy_base_url(base_url or current.base_url)
        timestamp = now_str()
        try:
            resp = requests.get(f"{test_url}/system_stats", timeout=5)
            if not resp.ok:
                raise RuntimeError(f"ComfyUI 返回 HTTP {resp.status_code}")
            status = "success"
            msg = "已连通 /system_stats"
        except Exception as err:
            status = "failed"
            msg = str(err)

        execute_sql(
            """
            UPDATE ai_comfy_provider_settings
            SET last_test_status = %s, last_test_message = %s, last_test_at = %s, updated_at = %s
            WHERE id = 1
            """,
            (status, msg, timestamp, timestamp),
        )
        if status == "failed":
            raise RuntimeError(f"无法连接 ComfyUI: {msg}")

        return cls.get_config()
