from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .grs_provider import CredentialManager
from .llm_client import (
    LLM_TEST_TIMEOUT_SECONDS,
    OpenAICompatibleClient,
    LlmError,
    catalog_provider_key,
    normalize_api_key,
    summarize_llm_test_reply,
)
from .llm_provider import is_local_base_url, model_supports_vision
from .storage import JobStore, now
from .vision_runtime import overlay_vlm_credentials, resolve_analysis_endpoint


DEFAULT_VLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_VLM_MODEL = "glm-4.6v-flash"

ZHIPU_VISION_CATALOG = [
    {"id": "glm-4.6v-flash", "label": "GLM-4.6V-Flash（免费）", "free": True},
    {"id": "glm-4v-flash", "label": "GLM-4V-Flash（免费）", "free": True},
    {"id": "glm-4.1v-thinking-flash", "label": "GLM-4.1V-Thinking-Flash（免费）", "free": True},
    {"id": "glm-4v", "label": "GLM-4V", "free": False},
    {"id": "glm-4v-plus", "label": "GLM-4V-Plus", "free": False},
]
VLM_UNAVAILABLE_MESSAGE = "视觉模型尚未启用。请在管理设置 → VLM 视觉模型 中配置后再使用看图功能。"
VLM_NOT_VISION_MESSAGE = "当前视觉模型名称无法识别为看图模型。请在管理设置 → VLM 视觉模型 中改用名称含 VL/Vision 的模型，例如 glm-4.6v-flash。"
ANALYSIS_UNAVAILABLE_MESSAGE = (
    "视觉分析不可用。请在管理设置 → VLM 视觉模型 配置看图模型；"
    "或在 LLM 页使用名称可看图的多模态模型。"
)


def _mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 5:
        return "*****"
    return f"{api_key[:3]}{'*' * max(5, min(16, len(api_key) - 5))}{api_key[-2:]}"


class VlmProviderService:
    def __init__(self, store: JobStore, credential_key: str | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)

    def _effective_config(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = dict(config or self.store.get_vlm_settings())
        if settings.get("use_llm_credentials"):
            return overlay_vlm_credentials(settings, self.store.get_llm_settings())
        return settings

    def api_key(self, config: dict[str, Any] | None = None) -> str | None:
        settings = self._effective_config(config)
        decrypted = self.credentials.decrypt(settings.get("api_key_encrypted"))
        if decrypted:
            return decrypted
        if is_local_base_url(self.base_url(config)):
            return "ollama"
        return None

    def base_url(self, config: dict[str, Any] | None = None) -> str:
        settings = self._effective_config(config)
        return str(settings.get("base_url") or "").rstrip("/")

    def availability(self) -> tuple[bool, str | None]:
        config = self.store.get_vlm_settings()
        if not config["enabled"]:
            return False, VLM_UNAVAILABLE_MESSAGE
        if not is_local_base_url(self.base_url(config)) and not self.credentials.ready:
            return False, self.credentials.error or "凭证主密钥不可用"
        if not self.api_key(config):
            return False, "视觉模型 API Key / Token 未配置或无法解密。可勾选复用大模型凭据。"
        if not config.get("model"):
            return False, "未配置视觉模型名称 (Model Name)。"
        if not model_supports_vision(config.get("model")):
            return False, VLM_NOT_VISION_MESSAGE
        return True, None

    def public_config(self) -> dict[str, Any]:
        config = self.store.get_vlm_settings()
        api_key = self.api_key(config)
        available, reason = self.availability()
        return {
            "enabled": config["enabled"],
            "use_llm_credentials": bool(config.get("use_llm_credentials")),
            "base_url": self.base_url(config),
            "model": config["model"],
            "api_key_masked": _mask_api_key(api_key),
            "has_api_key": bool(api_key),
            "credential_ready": self.credentials.ready,
            "last_test_status": config.get("last_test_status"),
            "last_test_message": config.get("last_test_message"),
            "last_test_at": config.get("last_test_at"),
            "available": available,
            "unavailable_reason": reason,
            "supports_vision": model_supports_vision(config.get("model")),
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        values = {key: value for key, value in payload.items() if key != "api_key"}
        base_url_str = str(values.get("base_url", "")).strip()
        if not base_url_str:
            base_url_str = DEFAULT_VLM_BASE_URL
        parsed = urlparse(base_url_str)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Base URL 必须是有效的 HTTP 或 HTTPS 地址")
        values["base_url"] = base_url_str.rstrip("/")

        model_name = str(values.get("model", "")).strip()
        if not model_name:
            model_name = DEFAULT_VLM_MODEL
        if not model_supports_vision(model_name):
            raise ValueError(VLM_NOT_VISION_MESSAGE)
        values["model"] = model_name

        api_key = normalize_api_key(payload.get("api_key"))
        if api_key:
            if not self.credentials.ready:
                raise ValueError(self.credentials.error or "凭证主密钥不可用")
            values["api_key_encrypted"] = self.credentials.encrypt(api_key)
        if "use_llm_credentials" in payload:
            values["use_llm_credentials"] = bool(payload.get("use_llm_credentials"))

        self.store.update_vlm_settings(**values)
        return self.public_config()

    def test(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        config = self.store.get_vlm_settings()
        reuse = bool((payload or {}).get("use_llm_credentials", config.get("use_llm_credentials")))
        base_url = (payload.get("base_url") if payload else None) or self.base_url({**config, "use_llm_credentials": reuse})
        if reuse:
            base_url = self.base_url({**config, "use_llm_credentials": True})
        model = (payload.get("model") if payload else None) or config["model"]
        submitted_key = normalize_api_key(payload.get("api_key")) if payload else None
        api_key = submitted_key or self.api_key({**config, "use_llm_credentials": reuse})
        if not api_key and is_local_base_url(base_url or ""):
            api_key = "ollama"

        if not api_key:
            if config.get("api_key_encrypted") and not submitted_key and not reuse:
                raise ValueError("已保存的视觉模型 Key 无法解密，请重新填写 API Key 后保存再测试。")
            raise ValueError("测试连接需要提供有效的 API Key / Token")
        if not base_url:
            raise ValueError("Base URL 不能为空")
        if not model:
            raise ValueError("Model 名称不能为空")
        if not model_supports_vision(model):
            raise ValueError(VLM_NOT_VISION_MESSAGE)

        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        test_time = now()
        try:
            reply = client.test_connection(model=model, timeout=LLM_TEST_TIMEOUT_SECONDS)
            test_status = "成功"
            test_message = summarize_llm_test_reply(reply)
        except Exception as exc:
            test_status = "失败"
            test_message = str(exc)

        self.store.update_vlm_settings(
            last_test_status=test_status,
            last_test_message=test_message,
            last_test_at=test_time,
        )
        if test_status != "成功":
            raise LlmError(f"视觉模型连接测试失败：{test_message}")
        return self.public_config()

    def list_catalog(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        config = self.store.get_vlm_settings()
        reuse = bool((payload or {}).get("use_llm_credentials", config.get("use_llm_credentials")))
        base_url = (payload.get("base_url") if payload else None) or self.base_url({**config, "use_llm_credentials": reuse})
        if reuse:
            base_url = self.base_url({**config, "use_llm_credentials": True})
        submitted_key = normalize_api_key(payload.get("api_key")) if payload else None
        api_key = submitted_key or self.api_key({**config, "use_llm_credentials": reuse})
        if not api_key and is_local_base_url(base_url or ""):
            api_key = "ollama"
        if not api_key:
            raise LlmError("拉取模型目录需要提供有效的 API Key / Token")
        if not base_url:
            raise LlmError("Base URL 不能为空")
        free_only = False if payload is None else bool(payload.get("free_only", False))
        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        catalog = client.list_model_catalog(free_only=free_only)
        vision_models = [
            row for row in (catalog.get("models") or [])
            if isinstance(row, dict) and model_supports_vision(str(row.get("id") or ""))
        ]
        if catalog_provider_key(base_url or "") == "zhipu":
            seen = {str(row.get("id") or "") for row in vision_models}
            for row in ZHIPU_VISION_CATALOG:
                if row["id"] not in seen:
                    vision_models.insert(0, dict(row))
                    seen.add(row["id"])
        message = catalog.get("message")
        if not vision_models:
            message = "上游目录中没有名称含 VL/Vision 的视觉模型。可手填 glm-4.6v-flash、qwen3-vl-flash 或 Qwen/Qwen3-VL-8B-Instruct。"
        return {
            "models": vision_models,
            "provider": catalog.get("provider") or "custom",
            "free_only": free_only,
            "message": message,
        }

    def _analysis_endpoint(self):
        return resolve_analysis_endpoint(
            self.store.get_llm_settings(),
            self.store.get_vlm_settings(),
            self.credentials.decrypt,
        )

    def analyze_subject(
        self,
        *,
        image_data_url: str,
        kind: str,
        name: str,
    ) -> str:
        endpoint = self._analysis_endpoint()
        if endpoint is None:
            raise LlmError(ANALYSIS_UNAVAILABLE_MESSAGE)
        client = OpenAICompatibleClient(base_url=endpoint.base_url, api_key=endpoint.api_key)
        return client.analyze_subject(
            image_data_url=image_data_url,
            kind=kind,
            name=name,
            model=endpoint.model,
        )

    def analyze_video_shot(
        self,
        *,
        frames: list[str],
        shot_number: int,
        duration_sec: float,
        art_style: str = "",
    ) -> dict[str, Any]:
        endpoint = self._analysis_endpoint()
        if endpoint is None:
            raise LlmError(ANALYSIS_UNAVAILABLE_MESSAGE)
        client = OpenAICompatibleClient(base_url=endpoint.base_url, api_key=endpoint.api_key)
        return client.analyze_video_shot(
            frames=frames,
            shot_number=shot_number,
            duration_sec=duration_sec,
            art_style=art_style,
            model=endpoint.model,
        )

    def vision_model_name(self) -> str | None:
        endpoint = self._analysis_endpoint()
        return endpoint.model if endpoint is not None else None
