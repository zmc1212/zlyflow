from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .grs_provider import CredentialManager
from .llm_client import LlmError, OpenAICompatibleClient
from .llm_provider import DEFAULT_MODELSCOPE_BASE_URL, is_local_base_url
from .storage import JobStore, now


DEFAULT_TTS_MODEL = "tts-1"
DEFAULT_TTS_VOICE = "alloy"

TTS_VOICES = (
    {"id": "alloy", "label": "Alloy（中性）", "gender": "unspecified"},
    {"id": "echo", "label": "Echo（男声）", "gender": "male"},
    {"id": "fable", "label": "Fable（叙事）", "gender": "unspecified"},
    {"id": "onyx", "label": "Onyx（低沉男声）", "gender": "male"},
    {"id": "nova", "label": "Nova（女声）", "gender": "female"},
    {"id": "shimmer", "label": "Shimmer（柔和女声）", "gender": "female"},
)


def voice_for_gender(gender: str | None) -> str:
    value = (gender or "").strip().lower()
    if value in {"male", "男"}:
        return "onyx"
    if value in {"female", "女"}:
        return "nova"
    return DEFAULT_TTS_VOICE


class TtsProviderService:
    def __init__(self, store: JobStore, credential_key: str | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)

    def api_key(self, config: dict[str, Any] | None = None) -> str | None:
        settings = config or self.store.get_tts_settings()
        if settings.get("use_llm_credentials"):
            decrypted = self.credentials.decrypt(self.store.get_llm_settings().get("api_key_encrypted"))
            if decrypted:
                return decrypted
            llm = self.store.get_llm_settings()
            if is_local_base_url(llm.get("base_url", "")):
                return "ollama"
            return None
        decrypted = self.credentials.decrypt(settings.get("api_key_encrypted"))
        if decrypted:
            return decrypted
        if is_local_base_url(self.base_url(settings)):
            return "ollama"
        return None

    def base_url(self, config: dict[str, Any] | None = None) -> str:
        settings = config or self.store.get_tts_settings()
        if settings.get("use_llm_credentials"):
            return str(self.store.get_llm_settings().get("base_url") or "").rstrip("/")
        return str(settings.get("base_url") or "").rstrip("/")

    def model(self, config: dict[str, Any] | None = None) -> str:
        settings = config or self.store.get_tts_settings()
        return str(settings.get("model") or DEFAULT_TTS_MODEL).strip() or DEFAULT_TTS_MODEL

    def voice(self, config: dict[str, Any] | None = None) -> str:
        settings = config or self.store.get_tts_settings()
        return str(settings.get("voice") or DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE

    def availability(self) -> tuple[bool, str | None]:
        config = self.store.get_tts_settings()
        if not config["enabled"]:
            return False, "语音合成尚未启用，请联系超级管理员在「管理设置 → LLM」配置独立 TTS。"
        if not self.base_url(config):
            return False, "TTS Base URL 未配置。可勾选复用大模型凭据，或填写独立 OpenAI 兼容地址。"
        if not is_local_base_url(self.base_url(config)) and not self.credentials.ready:
            return False, self.credentials.error or "凭证主密钥不可用"
        if not self.api_key(config):
            return False, "TTS API Key 未配置或无法解密。"
        if not self.model(config):
            return False, "未配置 TTS 模型名称。"
        return True, None

    def public_config(self) -> dict[str, Any]:
        config = self.store.get_tts_settings()
        api_key = self.api_key(config)
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
            "use_llm_credentials": bool(config.get("use_llm_credentials")),
            "base_url": self.base_url(config),
            "model": self.model(config),
            "voice": self.voice(config),
            "api_key_masked": masked,
            "has_api_key": bool(api_key),
            "credential_ready": self.credentials.ready,
            "last_test_status": config.get("last_test_status"),
            "last_test_message": config.get("last_test_message"),
            "last_test_at": config.get("last_test_at"),
            "available": available,
            "unavailable_reason": reason,
            "voices": list(TTS_VOICES),
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {
            key: value for key, value in payload.items()
            if key not in {"api_key"}
        }
        base_url_str = str(values.get("base_url") or "").strip()
        if base_url_str:
            parsed = urlparse(base_url_str)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("TTS Base URL 必须是有效的 HTTP 或 HTTPS 地址")
            values["base_url"] = base_url_str.rstrip("/")
        elif not values.get("use_llm_credentials", True):
            values["base_url"] = DEFAULT_MODELSCOPE_BASE_URL
        model_name = str(values.get("model") or "").strip()
        values["model"] = model_name or DEFAULT_TTS_MODEL
        voice = str(values.get("voice") or "").strip()
        values["voice"] = voice or DEFAULT_TTS_VOICE
        api_key = payload.get("api_key")
        if api_key is not None and str(api_key).strip():
            if not self.credentials.ready:
                raise ValueError(self.credentials.error or "凭证主密钥不可用")
            values["api_key_encrypted"] = self.credentials.encrypt(str(api_key).strip())
        self.store.update_tts_settings(**values)
        return self.public_config()

    def test(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        config = self.store.get_tts_settings()
        merged = dict(config)
        if payload:
            merged.update({key: value for key, value in payload.items() if value is not None})
        base_url = str(merged.get("base_url") or self.base_url(config)).rstrip("/")
        if merged.get("use_llm_credentials", config.get("use_llm_credentials")):
            base_url = self.base_url({**config, "use_llm_credentials": True})
        model = str(merged.get("model") or self.model(config))
        voice = str(merged.get("voice") or self.voice(config))
        submitted_key = payload.get("api_key") if payload else None
        api_key = (
            submitted_key.strip()
            if isinstance(submitted_key, str) and submitted_key.strip()
            else self.api_key({**config, **(payload or {}), "use_llm_credentials": merged.get("use_llm_credentials", config.get("use_llm_credentials"))})
        )
        if not api_key and is_local_base_url(base_url or ""):
            api_key = "ollama"
        if not api_key:
            raise ValueError("测试语音合成需要提供有效的 API Key / Token")
        if not base_url:
            raise ValueError("TTS Base URL 不能为空")
        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        test_time = now()
        try:
            audio = client.speech(text="试听。", model=model, voice=voice, timeout=30.0)
            if not audio:
                raise LlmError("上游返回了空音频")
            test_status = "成功"
            test_message = f"连接成功，收到 {len(audio)} 字节音频"
        except Exception as exc:
            test_status = "失败"
            test_message = str(exc)
        self.store.update_tts_settings(
            last_test_status=test_status,
            last_test_message=test_message,
            last_test_at=test_time,
        )
        if test_status != "成功":
            raise LlmError(f"语音合成连接测试失败：{test_message}")
        return self.public_config()

    def client(self) -> tuple[OpenAICompatibleClient, str, str]:
        available, reason = self.availability()
        if not available:
            raise LlmError(reason or "语音合成服务不可用")
        api_key = self.api_key()
        if not api_key:
            raise LlmError("TTS 凭据未配置")
        return (
            OpenAICompatibleClient(base_url=self.base_url(), api_key=api_key),
            self.model(),
            self.voice(),
        )

    def synthesize(self, text: str, *, voice: str | None = None) -> bytes:
        client, model, default_voice = self.client()
        return client.speech(
            text=text,
            model=model,
            voice=(voice or default_voice).strip() or default_voice,
        )
