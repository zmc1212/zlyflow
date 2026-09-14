from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse
import requests

from ..config import settings
from ..crypto import CredentialManager
from ..db import execute_sql, now_str, query_all, query_one
from ..models import (
    CatalogModel,
    CatalogModelCreateRequest,
    CatalogPayload,
    GrsBalanceResponse,
    GrsConfigResponse,
    GrsUpdateRequest,
)

PROFILE_LABELS = {
    "nano_banana": "NanoBanana 极速 (1024x1024 / 1536 / 等)",
    "flux": "FLUX 高清真实质感",
    "midjourney": "Midjourney 风格化艺术",
    "sdxl": "SDXL 通用写实",
}


def get_credential_manager() -> CredentialManager:
    return CredentialManager(settings.credential_key)


class GrsService:
    DEFAULT_URL = "https://grsai.dakka.com.cn"

    @classmethod
    def get_config(cls) -> GrsConfigResponse:
        cred = get_credential_manager()
        row = query_one("SELECT * FROM ai_grs_provider_settings WHERE id = 1")
        if not row:
            return GrsConfigResponse(
                enabled=False,
                base_url=cls.DEFAULT_URL,
                has_api_key=False,
                credential_ready=cred.ready,
                max_storyboard_concurrency=5,
            )

        encrypted_key = row.get("api_key_encrypted")
        decrypted_key = cred.decrypt(encrypted_key) if encrypted_key else None
        available = bool(row["enabled"] and cred.ready and decrypted_key)
        reason = None
        if not row["enabled"]:
            reason = "GRS 图片供应商尚未启用。"
        elif not cred.ready:
            reason = cred.error or "凭证主密钥不可用"
        elif not decrypted_key:
            reason = "GRS API Key 未配置或无法解密。"

        return GrsConfigResponse(
            enabled=bool(row["enabled"]),
            base_url=row["base_url"] or cls.DEFAULT_URL,
            api_key_masked=cred.mask(decrypted_key),
            has_api_key=bool(encrypted_key),
            credential_ready=cred.ready,
            gpt_image_2_enabled=bool(row.get("gpt_image_2_enabled", 1)),
            gpt_image_2_vip_enabled=bool(row.get("gpt_image_2_vip_enabled", 1)),
            models=row.get("models") or "gpt-image-2",
            vip_models=row.get("vip_models") or "gpt-image-2-vip",
            last_test_status=row.get("last_test_status"),
            last_test_message=row.get("last_test_message"),
            last_test_at=row.get("last_test_at"),
            last_balance=row.get("last_balance"),
            last_balance_at=row.get("last_balance_at"),
            available=available,
            unavailable_reason=reason,
            max_storyboard_concurrency=max(1, min(20, int(row.get("max_storyboard_concurrency") or 5))),
        )

    @classmethod
    def update_config(cls, payload: GrsUpdateRequest) -> GrsConfigResponse:
        cred = get_credential_manager()
        timestamp = now_str()
        current = query_one("SELECT * FROM ai_grs_provider_settings WHERE id = 1") or {}

        encrypted_key = current.get("api_key_encrypted")
        if payload.api_key and payload.api_key.strip():
            encrypted_key = cred.encrypt(payload.api_key.strip())

        concurrency = max(1, min(20, int(payload.max_storyboard_concurrency or 5)))
        execute_sql(
            """
            INSERT INTO ai_grs_provider_settings
              (id, enabled, base_url, api_key_encrypted, max_storyboard_concurrency, updated_at)
            VALUES (1, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                enabled = VALUES(enabled),
                base_url = VALUES(base_url),
                api_key_encrypted = VALUES(api_key_encrypted),
                max_storyboard_concurrency = VALUES(max_storyboard_concurrency),
                updated_at = VALUES(updated_at)
            """,
            (1 if payload.enabled else 0, payload.base_url.rstrip("/"), encrypted_key, concurrency, timestamp),
        )
        from .storyboard_image_service import StoryboardImageService
        StoryboardImageService.kick()
        return cls.get_config()

    @classmethod
    def query_balance_remote(cls, base_url: str, api_key: str) -> float:
        resp = requests.post(
            f"{base_url.rstrip('/')}/client/openapi/getAPIKeyCredits",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"apiKey": api_key},
            timeout=(10, 30),
        )
        if not resp.ok:
            raise RuntimeError(f"GRS 响应异常: HTTP {resp.status_code}")
        data = resp.json()
        if data.get("code") not in {None, 0, "0"}:
            raise RuntimeError(str(data.get("msg") or data.get("message") or "查询余额失败"))
        inner_data = data.get("data") if isinstance(data.get("data"), dict) else {}
        if "credits" not in inner_data:
            raise RuntimeError("GRS 响应缺少 credits 字段")
        return float(inner_data["credits"])

    @classmethod
    def test_connection(cls, base_url: str | None = None, api_key: str | None = None) -> GrsConfigResponse:
        cred = get_credential_manager()
        current_row = query_one("SELECT * FROM ai_grs_provider_settings WHERE id = 1") or {}
        effective_url = (base_url or current_row.get("base_url") or cls.DEFAULT_URL).rstrip("/")

        effective_key = api_key.strip() if api_key and api_key.strip() else None
        if not effective_key and current_row.get("api_key_encrypted"):
            effective_key = cred.decrypt(current_row["api_key_encrypted"])

        if not effective_key:
            raise RuntimeError("尚未配置或输入 GRS API Key")

        timestamp = now_str()
        try:
            credits = cls.query_balance_remote(effective_url, effective_key)
            status = "success"
            msg = f"连接成功，当前剩余点数: {credits}"
            execute_sql(
                """
                UPDATE ai_grs_provider_settings
                SET last_test_status = %s, last_test_message = %s, last_test_at = %s,
                    last_balance = %s, last_balance_at = %s, updated_at = %s
                WHERE id = 1
                """,
                (status, msg, timestamp, credits, timestamp, timestamp),
            )
        except Exception as err:
            status = "failed"
            msg = str(err)
            execute_sql(
                """
                UPDATE ai_grs_provider_settings
                SET last_test_status = %s, last_test_message = %s, last_test_at = %s, updated_at = %s
                WHERE id = 1
                """,
                (status, msg, timestamp, timestamp),
            )
            raise RuntimeError(f"GRS 连接失败: {msg}")

        return cls.get_config()

    @classmethod
    def get_balance(cls) -> GrsBalanceResponse:
        cred = get_credential_manager()
        row = query_one("SELECT * FROM ai_grs_provider_settings WHERE id = 1")
        if not row:
            return GrsBalanceResponse(error="未配置 GRS 供应商")
        encrypted_key = row.get("api_key_encrypted")
        api_key = cred.decrypt(encrypted_key) if encrypted_key else None
        if not api_key:
            return GrsBalanceResponse(error="未配置 API Key")

        try:
            credits = cls.query_balance_remote(row["base_url"], api_key)
            ts = now_str()
            execute_sql(
                "UPDATE ai_grs_provider_settings SET last_balance = %s, last_balance_at = %s WHERE id = 1",
                (credits, ts),
            )
            return GrsBalanceResponse(credits=credits, queried_at=ts)
        except Exception as err:
            return GrsBalanceResponse(
                credits=row.get("last_balance"),
                queried_at=row.get("last_balance_at"),
                error=str(err),
            )

    @classmethod
    def get_models_catalog(cls) -> CatalogPayload:
        rows = query_all("SELECT * FROM ai_grs_image_models ORDER BY is_default DESC, sort_order ASC")
        models = []
        for r in rows:
            res = None
            if r.get("resolutions_json"):
                try:
                    res = json.loads(r["resolutions_json"])
                except Exception:
                    pass
            models.append(
                CatalogModel(
                    workflow_id=r["workflow_id"],
                    provider_model=r["provider_model"],
                    display_name=r["display_name"],
                    description=r.get("description") or "",
                    profile=r["profile"],
                    resolutions=res,
                    enabled=bool(r["enabled"]),
                    sort_order=r.get("sort_order", 100),
                    is_default=bool(r.get("is_default", 0)),
                    builtin=bool(r.get("builtin", 0)),
                )
            )
        profiles = [{"value": k, "label": v} for k, v in PROFILE_LABELS.items()]
        return CatalogPayload(models=models, profiles=profiles)

    @classmethod
    def batch_update_models(cls, items: list[dict[str, Any]]) -> CatalogPayload:
        ts = now_str()
        for item in items:
            wid = item.get("workflow_id")
            if not wid:
                continue
            execute_sql(
                """
                UPDATE ai_grs_image_models
                SET display_name = %s, enabled = %s, sort_order = %s, is_default = %s, updated_at = %s
                WHERE workflow_id = %s
                """,
                (
                    item.get("display_name"),
                    1 if item.get("enabled") else 0,
                    item.get("sort_order", 100),
                    1 if item.get("is_default") else 0,
                    ts,
                    wid,
                ),
            )
        return cls.get_models_catalog()

    @classmethod
    def create_model(cls, payload: CatalogModelCreateRequest) -> CatalogPayload:
        wid = f"grs-{payload.provider_model.lower().replace(' ', '-').replace('/', '-')}"
        ts = now_str()
        res_json = json.dumps(payload.resolutions or ["1024x1024", "1024x1536", "1536x1024"])
        execute_sql(
            """
            INSERT INTO ai_grs_image_models
            (workflow_id, provider_model, display_name, description, profile, resolutions_json, enabled, sort_order, is_default, builtin, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, 1, 100, %s, 0, %s, %s)
            ON DUPLICATE KEY UPDATE
                display_name = VALUES(display_name),
                description = VALUES(description),
                profile = VALUES(profile),
                resolutions_json = VALUES(resolutions_json),
                updated_at = VALUES(updated_at)
            """,
            (
                wid,
                payload.provider_model.strip(),
                payload.display_name.strip(),
                payload.description or "",
                payload.profile,
                res_json,
                1 if payload.is_default else 0,
                ts,
                ts,
            ),
        )
        return cls.get_models_catalog()
