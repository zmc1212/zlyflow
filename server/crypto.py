from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CredentialManager:
    def __init__(self, key: str | None) -> None:
        self._fernet: Fernet | None = None
        self.error: str | None = None
        if not key:
            self.error = "未配置凭证密钥"
            return
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (TypeError, ValueError):
            self.error = "凭据密钥格式不合法 (非有效 Fernet 密钥)"

    @property
    def ready(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise ValueError(self.error or "凭证加密密钥不可用")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if not value or self._fernet is None:
            return None
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None

    @staticmethod
    def mask(value: str | None) -> str | None:
        if not value:
            return None
        length = len(value)
        if length <= 6:
            return "*****"
        return f"{value[:3]}{'*' * min(16, max(4, length - 5))}{value[-2:]}"
