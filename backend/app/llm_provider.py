from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .grs_provider import CredentialManager
from .llm_client import OpenAICompatibleClient, LlmError
from .storage import JobStore, now



DEFAULT_MODELSCOPE_BASE_URL = "https://api-inference.modelscope.cn/v1"
DEFAULT_MODELSCOPE_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"






class LlmProviderService:
    def __init__(self, store: JobStore, credential_key: str | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)

    def api_key(self) -> str | None:
        return self.credentials.decrypt(self.store.get_llm_settings().get("api_key_encrypted"))

    def availability(self) -> tuple[bool, str | None]:
        config = self.store.get_llm_settings()
        if not config["enabled"]:
            return False, "大模型服务尚未启用，请联系超级管理员配置。"
        if not self.credentials.ready:
            return False, self.credentials.error or "凭证主密钥不可用"
        if not self.api_key():
            return False, "大模型 API Key / Token 未配置或无法解密。"
        if not config.get("model"):
            return False, "未配置大模型名称 (Model Name)。"
        return True, None

    def public_config(self) -> dict[str, Any]:
        config = self.store.get_llm_settings()
        api_key = self.api_key()
        available, reason = self.availability()
        masked = None
        if api_key:
            masked = (
                f"{api_key[:3]}{'*' * max(5, min(16, len(api_key) - 5))}{api_key[-2:]}"
                if len(api_key) > 5
                else "*****"
            )
        return {
            "enabled": config["enabled"],
            "base_url": config["base_url"],
            "model": config["model"],
            "api_key_masked": masked,
            "has_api_key": bool(config.get("api_key_encrypted")),
            "credential_ready": self.credentials.ready,
            "last_test_status": config.get("last_test_status"),
            "last_test_message": config.get("last_test_message"),
            "last_test_at": config.get("last_test_at"),
            "available": available,
            "unavailable_reason": reason,
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        values = {key: value for key, value in payload.items() if key != "api_key"}
        base_url_str = str(values.get("base_url", "")).strip()
        if not base_url_str:
            base_url_str = DEFAULT_MODELSCOPE_BASE_URL
        parsed = urlparse(base_url_str)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Base URL 必须是有效的 HTTP 或 HTTPS 地址")
        values["base_url"] = base_url_str.rstrip("/")

        model_name = str(values.get("model", "")).strip()
        if not model_name:
            model_name = DEFAULT_MODELSCOPE_MODEL
        values["model"] = model_name

        api_key = payload.get("api_key")
        if api_key is not None and str(api_key).strip():
            if not self.credentials.ready:
                raise ValueError(self.credentials.error or "凭证主密钥不可用")
            values["api_key_encrypted"] = self.credentials.encrypt(str(api_key).strip())

        self.store.update_llm_settings(**values)
        return self.public_config()


    def test(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        config = self.store.get_llm_settings()
        base_url = (payload.get("base_url") if payload else None) or config["base_url"]
        model = (payload.get("model") if payload else None) or config["model"]
        api_key = payload.get("api_key") if payload and payload.get("api_key") is not None else self.api_key()

        if not api_key:
            raise ValueError("测试连接需要提供有效的 API Key / Token")
        if not base_url:
            raise ValueError("Base URL 不能为空")
        if not model:
            raise ValueError("Model 名称不能为空")

        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        test_time = now()
        try:
            reply = client.test_connection(model=model)
            test_status = "成功"
            test_message = f"连接成功，模型响应：{reply}"
        except Exception as exc:
            test_status = "失败"
            test_message = str(exc)

        self.store.update_llm_settings(
            last_test_status=test_status,
            last_test_message=test_message,
            last_test_at=test_time,
        )
        if test_status != "成功":

            raise LlmError(f"大模型连接测试失败：{test_message}")
        return self.public_config()

    def optimize_prompt(
        self,
        prompt: str,
        *,
        media_type: str = "video",
        workflow_name: str | None = None,
        skill_id: str | None = None,
        reference_count: int = 0,
        workflow_id: str | None = None,
    ) -> str:
        available, reason = self.availability()
        if not available:
            raise LlmError(reason or "大模型服务不可用")

        config = self.store.get_llm_settings()
        api_key = self.api_key()
        if not api_key:
            raise LlmError("大模型凭据未配置")

        client = OpenAICompatibleClient(base_url=config["base_url"], api_key=api_key)
        return client.optimize_prompt(
            prompt,
            media_type=media_type,
            workflow_name=workflow_name,
            skill_id=skill_id,
            reference_count=reference_count,
            workflow_id=workflow_id,
            model=config["model"],
        )

