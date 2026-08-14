from __future__ import annotations

from typing import Any

from .grs_provider import CredentialManager
from .qiniu_storage import QiniuStorage, validate_qiniu_config
from .storage import JobStore, now


class QiniuProviderService:
    def __init__(self, store: JobStore, credential_key: str | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)

    def _secrets(self) -> tuple[str | None, str | None]:
        config = self.store.get_qiniu_settings()
        return (
            self.credentials.decrypt(config.get("access_key_encrypted")),
            self.credentials.decrypt(config.get("secret_key_encrypted")),
        )

    def storage(self) -> QiniuStorage:
        config = self.store.get_qiniu_settings()
        access_key, secret_key = self._secrets()
        return QiniuStorage({**config, "access_key": access_key or "", "secret_key": secret_key or ""})

    def enabled_storage(self) -> QiniuStorage | None:
        config = self.store.get_qiniu_settings()
        return self.storage() if config["enabled"] else None

    def public_config(self) -> dict[str, Any]:
        config = self.store.get_qiniu_settings()
        access_key, secret_key = self._secrets()
        available = bool(config["enabled"] and self.credentials.ready and access_key and secret_key and config["bucket"] and config["domain"])
        return {
            "enabled": config["enabled"], "bucket": config["bucket"], "region": config["region"],
            "domain": config["domain"], "object_prefix": config["object_prefix"],
            "has_access_key": bool(config.get("access_key_encrypted")),
            "has_secret_key": bool(config.get("secret_key_encrypted")),
            "credential_ready": self.credentials.ready, "available": available,
            "last_test_status": config.get("last_test_status"), "last_test_message": config.get("last_test_message"),
            "last_test_at": config.get("last_test_at"),
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.store.get_qiniu_settings()
        values = validate_qiniu_config({**current, **payload})
        access_key = str(payload.get("access_key") or "").strip()
        secret_key = str(payload.get("secret_key") or "").strip()
        if values["enabled"] and not self.credentials.ready:
            raise ValueError(self.credentials.error or "凭证主密钥不可用")
        if values["enabled"] and (not access_key and not current.get("access_key_encrypted")):
            raise ValueError("启用七牛云前必须填写 Access Key")
        if values["enabled"] and (not secret_key and not current.get("secret_key_encrypted")):
            raise ValueError("启用七牛云前必须填写 Secret Key")
        if values["enabled"] and (not values["bucket"] or not values["domain"]):
            raise ValueError("启用七牛云前必须填写 Bucket 和访问域名")
        updates: dict[str, Any] = {key: value for key, value in values.items() if key not in {"access_key", "secret_key"}}
        if access_key:
            updates["access_key_encrypted"] = self.credentials.encrypt(access_key)
        if secret_key:
            updates["secret_key_encrypted"] = self.credentials.encrypt(secret_key)
        self.store.update_qiniu_settings(**updates)
        return self.public_config()

    def test_connection(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        timestamp = now()
        try:
            if payload:
                current = self.store.get_qiniu_settings()
                access_key, secret_key = self._secrets()
                values = validate_qiniu_config({**current, **payload, "access_key": payload.get("access_key") or access_key or "", "secret_key": payload.get("secret_key") or secret_key or ""})
                QiniuStorage(values).test_connection()
            else:
                self.storage().test_connection()
            self.store.update_qiniu_settings(last_test_status="success", last_test_message="上传和删除验证成功", last_test_at=timestamp)
        except Exception as error:
            self.store.update_qiniu_settings(last_test_status="failed", last_test_message=str(error), last_test_at=timestamp)
            raise
        return self.public_config()
