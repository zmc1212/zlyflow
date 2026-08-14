from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from .grs_client import GrsClient, GrsError
from .models import JobMode
from .storage import JobStore, now


class CredentialManager:
    def __init__(self, key: str | None) -> None:
        self._fernet: Fernet | None = None
        self.error: str | None = None
        if not key:
            self.error = "未配置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY"
            return
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (TypeError, ValueError):
            self.error = "ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY 不是有效的 Fernet 密钥"

    @property
    def ready(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise ValueError(self.error or "凭证主密钥不可用")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if not value or self._fernet is None:
            return None
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None


class GrsProviderService:
    def __init__(self, store: JobStore, credential_key: str | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)

    def api_key(self) -> str | None:
        return self.credentials.decrypt(self.store.get_grs_settings().get("api_key_encrypted"))

    def availability(self, mode: JobMode | None = None) -> tuple[bool, str | None]:
        config = self.store.get_grs_settings()
        if not config["enabled"]:
            return False, "GRS 图片供应商尚未启用，请联系超级管理员。"
        if not self.credentials.ready:
            return False, self.credentials.error
        if not self.api_key():
            return False, "GRS API Key 未配置或无法使用当前主密钥解密。"
        if mode is JobMode.GRS_GPT_IMAGE_2 and not config["gpt_image_2_enabled"]:
            return False, "GPT Image 2 已被管理员停用。"
        if mode is JobMode.GRS_GPT_IMAGE_2_VIP and not config["gpt_image_2_vip_enabled"]:
            return False, "GPT Image 2 VIP 已被管理员停用。"
        return True, None

    def public_config(self) -> dict[str, Any]:
        config = self.store.get_grs_settings()
        api_key = self.api_key()
        available, reason = self.availability()
        masked = None
        if api_key:
            masked = f"{api_key[:3]}{'*' * max(5, min(16, len(api_key) - 5))}{api_key[-2:]}" if len(api_key) > 5 else "*****"
        return {
            "enabled": config["enabled"],
            "base_url": config["base_url"],
            "api_key_masked": masked,
            "has_api_key": bool(config.get("api_key_encrypted")),
            "credential_ready": self.credentials.ready,
            "gpt_image_2_enabled": config["gpt_image_2_enabled"],
            "gpt_image_2_vip_enabled": config["gpt_image_2_vip_enabled"],
            "last_test_status": config.get("last_test_status"),
            "last_test_message": config.get("last_test_message"),
            "last_test_at": config.get("last_test_at"),
            "last_balance": config.get("last_balance"),
            "last_balance_at": config.get("last_balance_at"),
            "available": available,
            "unavailable_reason": reason,
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        values = {key: value for key, value in payload.items() if key != "api_key"}
        parsed = urlparse(str(values.get("base_url", "")))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("GRS Base URL 必须是无内嵌凭证的 HTTPS 地址")
        values["base_url"] = str(values["base_url"]).rstrip("/")
        api_key = payload.get("api_key")
        if api_key is not None and api_key.strip():
            values["api_key_encrypted"] = self.credentials.encrypt(api_key.strip())
        self.store.update_grs_settings(**values)
        return self.public_config()

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("GRS Base URL 必须是无内嵌凭证的 HTTPS 地址")
        return base_url.rstrip("/")

    def client(self, *, base_url: str | None = None, api_key: str | None = None) -> GrsClient:
        config = self.store.get_grs_settings()
        effective_key = api_key.strip() if api_key and api_key.strip() else self.api_key()
        if not effective_key:
            if not self.credentials.ready:
                raise GrsError(self.credentials.error or "凭证主密钥不可用")
            raise GrsError("尚未保存 GRS API Key，请输入 API Key 后测试或保存配置")
        effective_url = self._validate_base_url((base_url or config["base_url"]).strip())
        return GrsClient(effective_url, effective_key)

    def test_connection(self, *, base_url: str | None = None, api_key: str | None = None) -> dict[str, Any]:
        timestamp = now()
        try:
            credits = self.client(base_url=base_url, api_key=api_key).balance()
            self.store.update_grs_settings(
                last_test_status="success", last_test_message="连接成功", last_test_at=timestamp,
                last_balance=credits, last_balance_at=timestamp,
            )
        except Exception as error:
            self.store.update_grs_settings(
                last_test_status="failed", last_test_message=str(error), last_test_at=timestamp,
            )
            raise
        return self.public_config()

    def balance(self) -> tuple[float, str]:
        credits = self.client().balance()
        timestamp = now()
        self.store.update_grs_settings(last_balance=credits, last_balance_at=timestamp)
        return credits, timestamp

    def balance_snapshot(self) -> dict[str, float | str | None]:
        config = self.store.get_grs_settings()
        return {
            "credits": config.get("last_balance"),
            "queried_at": config.get("last_balance_at"),
        }
