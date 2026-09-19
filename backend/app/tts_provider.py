from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import requests

from .grs_provider import CredentialManager
from .llm_client import LlmError, OpenAICompatibleClient
from .llm_provider import DEFAULT_MODELSCOPE_BASE_URL, is_local_base_url
from .storage import JobStore, now


DEFAULT_TTS_MODEL = "tts-1"
DEFAULT_TTS_VOICE = "alloy"
COSYVOICE2_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
MOSS_TTSD_MODEL = "fnlp/MOSS-TTSD-v0.5"
INDEXTTS_MODEL = "indextts-2.5"
INDEXTTS_VOICE = "clone"
INDEXTTS_DEFAULT_ORIGIN = "http://127.0.0.1:7866"
INDEXTTS_DEFAULT_BASE_URL = f"{INDEXTTS_DEFAULT_ORIGIN}/v1"
INDEXTTS_EMOTION_KEYS = (
    "happy",
    "angry",
    "sad",
    "afraid",
    "disgusted",
    "melancholic",
    "surprised",
    "calm",
)

OPENAI_VOICE_IDS = frozenset({"alloy", "echo", "fable", "onyx", "nova", "shimmer"})

OPENAI_TTS_VOICES: tuple[dict[str, str], ...] = (
    {"id": "alloy", "label": "Alloy（中性）", "gender": "unspecified"},
    {"id": "echo", "label": "Echo（男声）", "gender": "male"},
    {"id": "fable", "label": "Fable（叙事）", "gender": "unspecified"},
    {"id": "onyx", "label": "Onyx（低沉男声）", "gender": "male"},
    {"id": "nova", "label": "Nova（女声）", "gender": "female"},
    {"id": "shimmer", "label": "Shimmer（柔和女声）", "gender": "female"},
)

SILICONFLOW_COSYVOICE_VOICES: tuple[dict[str, str], ...] = (
    {"id": f"{COSYVOICE2_MODEL}:alex", "label": "Alex（沉稳男声）", "gender": "male"},
    {"id": f"{COSYVOICE2_MODEL}:benjamin", "label": "Benjamin（低沉男声）", "gender": "male"},
    {"id": f"{COSYVOICE2_MODEL}:charles", "label": "Charles（磁性男声）", "gender": "male"},
    {"id": f"{COSYVOICE2_MODEL}:david", "label": "David（活泼男声）", "gender": "male"},
    {"id": f"{COSYVOICE2_MODEL}:anna", "label": "Anna（沉稳女声）", "gender": "female"},
    {"id": f"{COSYVOICE2_MODEL}:bella", "label": "Bella（激情女声）", "gender": "female"},
    {"id": f"{COSYVOICE2_MODEL}:claire", "label": "Claire（温柔女声）", "gender": "female"},
    {"id": f"{COSYVOICE2_MODEL}:diana", "label": "Diana（活泼女声）", "gender": "female"},
)

INDEXTTS_VOICES: tuple[dict[str, str], ...] = (
    {"id": INDEXTTS_VOICE, "label": "角色参考音克隆", "gender": "unspecified"},
)

# 兼容旧常量名
TTS_VOICES = OPENAI_TTS_VOICES


def sidecar_origin(base_url: str = "") -> str:
    parsed = urlparse((base_url or "").strip() or INDEXTTS_DEFAULT_BASE_URL)
    if not parsed.scheme or not parsed.hostname:
        return INDEXTTS_DEFAULT_ORIGIN
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def detect_tts_provider(*, base_url: str = "", model: str = "") -> str:
    lowered_url = (base_url or "").strip().lower()
    lowered_model = (model or "").strip().lower()
    parsed = urlparse(base_url or "")
    if parsed.port == 7866 or "7866" in lowered_url or "indextts" in lowered_url or "indextts" in lowered_model:
        return "indextts"
    if "siliconflow" in lowered_url:
        return "siliconflow"
    if "cosyvoice" in lowered_model or "moss-ttsd" in lowered_model or lowered_model.startswith("funaudiollm/"):
        return "siliconflow"
    if "openai.com" in lowered_url or lowered_model in {"tts-1", "tts-1-hd"}:
        return "openai"
    return "custom"


def voices_for_provider(provider: str) -> list[dict[str, str]]:
    if provider == "indextts":
        return [dict(item) for item in INDEXTTS_VOICES]
    if provider == "siliconflow":
        return [dict(item) for item in SILICONFLOW_COSYVOICE_VOICES]
    if provider == "openai":
        return [dict(item) for item in OPENAI_TTS_VOICES]
    return [dict(item) for item in OPENAI_TTS_VOICES]


def emotion_vector(emotion: str | None = None, values: Any = None, *, intensity: float = 1.0) -> list[float]:
    vector = [0.0] * len(INDEXTTS_EMOTION_KEYS)
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except json.JSONDecodeError:
            values = None
    if isinstance(values, (list, tuple)) and len(values) == len(INDEXTTS_EMOTION_KEYS):
        parsed: list[float] = []
        for item in values:
            try:
                parsed.append(max(0.0, min(1.0, float(item))))
            except (TypeError, ValueError):
                parsed.append(0.0)
        return parsed
    key = str(emotion or "calm").strip().lower()
    if key not in INDEXTTS_EMOTION_KEYS:
        key = "calm"
    try:
        strength = max(0.0, min(1.0, float(intensity)))
    except (TypeError, ValueError):
        strength = 1.0
    vector[INDEXTTS_EMOTION_KEYS.index(key)] = strength
    return vector


def clamp_emo_alpha(value: Any, default: float = 0.8) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def clamp_duration_factor(value: Any, default: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.5, min(2.0, number))


def free_indextts_sidecar(base_url: str = "") -> bool:
    origin = sidecar_origin(base_url or INDEXTTS_DEFAULT_BASE_URL)
    try:
        response = requests.post(f"{origin}/free", timeout=8)
        return bool(response.ok)
    except requests.RequestException:
        return False


def indextts_health(base_url: str = "") -> dict[str, Any]:
    origin = sidecar_origin(base_url or INDEXTTS_DEFAULT_BASE_URL)
    try:
        response = requests.get(f"{origin}/health", timeout=5)
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict):
            payload = {}
        payload["http_status"] = response.status_code
        payload["ok"] = bool(response.ok and payload.get("ready", payload.get("status") == "ok"))
        return payload
    except requests.RequestException as exc:
        return {"ok": False, "status": "unreachable", "detail": str(exc), "origin": origin}


def voice_for_gender(gender: str | None, *, base_url: str = "", model: str = "") -> str:
    provider = detect_tts_provider(base_url=base_url, model=model)
    value = (gender or "").strip().lower()
    if provider == "indextts":
        return INDEXTTS_VOICE
    if provider == "siliconflow":
        if value in {"male", "男"}:
            return f"{COSYVOICE2_MODEL}:benjamin"
        if value in {"female", "女"}:
            return f"{COSYVOICE2_MODEL}:bella"
        return f"{COSYVOICE2_MODEL}:alex"
    if value in {"male", "男"}:
        return "onyx"
    if value in {"female", "女"}:
        return "nova"
    return DEFAULT_TTS_VOICE


def resolve_tts_voice(
    voice: str | None,
    *,
    gender: str = "",
    base_url: str = "",
    model: str = "",
) -> str:
    selected = str(voice or "").strip()
    provider = detect_tts_provider(base_url=base_url, model=model)
    if provider == "indextts":
        return selected or INDEXTTS_VOICE
    if provider == "siliconflow" and selected in OPENAI_VOICE_IDS:
        return voice_for_gender(gender, base_url=base_url, model=model)
    if selected:
        return selected
    return voice_for_gender(gender, base_url=base_url, model=model)


class TtsProviderService:
    def __init__(self, store: JobStore, credential_key: str | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)

    def _effective_config(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = dict(config or self.store.get_tts_settings())
        stored_provider = detect_tts_provider(
            base_url=str(settings.get("base_url") or ""),
            model=str(settings.get("model") or ""),
        )
        if stored_provider == "indextts":
            settings["use_llm_credentials"] = False
            if not str(settings.get("base_url") or "").strip():
                settings["base_url"] = INDEXTTS_DEFAULT_BASE_URL
            return settings
        if settings.get("use_llm_credentials"):
            llm = self.store.get_llm_settings()
            settings["base_url"] = str(llm.get("base_url") or settings.get("base_url") or "")
        return settings

    def provider_name(self, config: dict[str, Any] | None = None) -> str:
        effective = self._effective_config(config)
        return detect_tts_provider(base_url=self.base_url(effective), model=self.model(effective))

    def supports_clone(self, config: dict[str, Any] | None = None) -> bool:
        return self.provider_name(config) == "indextts"

    def api_key(self, config: dict[str, Any] | None = None) -> str | None:
        settings = self._effective_config(config)
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
        settings = self._effective_config(config)
        if settings.get("use_llm_credentials"):
            return str(self.store.get_llm_settings().get("base_url") or "").rstrip("/")
        return str(settings.get("base_url") or "").rstrip("/")

    def model(self, config: dict[str, Any] | None = None) -> str:
        settings = config or self.store.get_tts_settings()
        return str(settings.get("model") or DEFAULT_TTS_MODEL).strip() or DEFAULT_TTS_MODEL

    def voice(self, config: dict[str, Any] | None = None) -> str:
        settings = config or self.store.get_tts_settings()
        stored = str(settings.get("voice") or DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE
        effective = self._effective_config(settings)
        return resolve_tts_voice(
            stored,
            base_url=self.base_url(settings),
            model=self.model(settings),
        )

    def voice_catalog(self, config: dict[str, Any] | None = None) -> list[dict[str, str]]:
        effective = self._effective_config(config)
        provider = detect_tts_provider(
            base_url=self.base_url(effective),
            model=self.model(effective),
        )
        return voices_for_provider(provider)

    def resolve_voice(self, voice: str | None, *, gender: str = "") -> str:
        effective = self._effective_config()
        return resolve_tts_voice(
            voice,
            gender=gender,
            base_url=self.base_url(effective),
            model=self.model(effective),
        )

    def availability(self) -> tuple[bool, str | None]:
        config = self.store.get_tts_settings()
        if not config["enabled"]:
            return False, "语音合成尚未启用，请联系超级管理员在「管理设置 → TTS」配置语音合成。"
        if not self.base_url(config):
            return False, "TTS Base URL 未配置。可勾选复用大模型凭据，或填写独立 OpenAI 兼容地址。"
        provider = self.provider_name(config)
        if provider != "indextts" and not is_local_base_url(self.base_url(config)) and not self.credentials.ready:
            return False, self.credentials.error or "凭证主密钥不可用"
        if provider != "indextts" and not self.api_key(config):
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
            "voices": self.voice_catalog(config),
            "provider": detect_tts_provider(base_url=self.base_url(config), model=self.model(config)),
            "supports_clone": self.supports_clone(config),
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
        provider = detect_tts_provider(
            base_url=str(values.get("base_url") or self.base_url(self.store.get_tts_settings())),
            model=model_name,
        )
        if provider == "indextts":
            values["use_llm_credentials"] = False
            values["model"] = model_name or INDEXTTS_MODEL
            values["voice"] = str(values.get("voice") or INDEXTTS_VOICE).strip() or INDEXTTS_VOICE
            if not str(values.get("base_url") or "").strip():
                values["base_url"] = INDEXTTS_DEFAULT_BASE_URL
        else:
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
        voice = resolve_tts_voice(
            str(merged.get("voice") or self.voice(config)),
            base_url=base_url,
            model=model,
        )
        submitted_key = payload.get("api_key") if payload else None
        api_key = (
            submitted_key.strip()
            if isinstance(submitted_key, str) and submitted_key.strip()
            else self.api_key({**config, **(payload or {}), "use_llm_credentials": merged.get("use_llm_credentials", config.get("use_llm_credentials"))})
        )
        if not api_key and is_local_base_url(base_url or ""):
            api_key = "ollama"
        provider = detect_tts_provider(base_url=base_url, model=model)
        if provider != "indextts" and not api_key:
            raise ValueError("测试语音合成需要提供有效的 API Key / Token")
        if not base_url:
            raise ValueError("TTS Base URL 不能为空")
        test_time = now()
        try:
            if provider == "indextts":
                health = indextts_health(base_url)
                if not health.get("ok"):
                    raise LlmError(health.get("detail") or health.get("status") or "IndexTTS 旁路未就绪")
                test_status = "成功"
                test_message = (
                    f"旁路已连接（{sidecar_origin(base_url)}），"
                    f"权重{'就绪' if health.get('ready') else '未找到'}，"
                    f"模型{'已加载' if health.get('loaded') else '未占用显存'}"
                )
            else:
                client = OpenAICompatibleClient(base_url=base_url, api_key=api_key or "ollama")
                audio = client.speech(text="试听。", model=model, voice=voice, timeout=30.0)
                if not audio:
                    raise LlmError("上游返回了空音频")
                test_status = "成功"
                test_message = f"连接成功，收到 {len(audio)} 字节音频"
        except Exception as extra:
            test_status = "失败"
            test_message = str(extra)
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
        api_key = self.api_key() or ("ollama" if is_local_base_url(self.base_url()) else None)
        if not api_key:
            raise LlmError("TTS 凭据未配置")
        return (
            OpenAICompatibleClient(base_url=self.base_url(), api_key=api_key),
            self.model(),
            self.voice(),
        )

    def free_sidecar(self) -> bool:
        if not self.supports_clone():
            return False
        return free_indextts_sidecar(self.base_url())

    def clone(
        self,
        text: str,
        *,
        spk_audio: bytes,
        spk_filename: str = "prompt.wav",
        lang: str | None = None,
        emotion: str | None = None,
        emo_vector: list[float] | None = None,
        emo_alpha: float | None = None,
        duration_factor: float | None = None,
        timeout: float = 180.0,
    ) -> bytes:
        line = str(text or "").strip()
        if not line:
            raise LlmError("配音文本不能为空")
        if not spk_audio:
            raise LlmError("请先上传角色参考音")
        if not self.supports_clone():
            return self.synthesize(line)
        origin = sidecar_origin(self.base_url())
        files = {"spk_audio": (spk_filename or "prompt.wav", spk_audio, "application/octet-stream")}
        data = {
            "text": line,
            "lang": lang or "",
            "emotion": emotion or "calm",
            "emo_vector": json.dumps(emotion_vector(emotion, emo_vector), ensure_ascii=False),
            "emo_alpha": str(clamp_emo_alpha(emo_alpha)),
            "duration_factor": str(clamp_duration_factor(duration_factor)),
        }
        try:
            response = requests.post(
                f"{origin}/v1/tts/clone",
                files=files,
                data=data,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise LlmError(f"IndexTTS 克隆超时（等待 {timeout:.0f} 秒）：{exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise LlmError(f"无法连接 IndexTTS 旁路 {origin}：{exc}") from exc
        if response.status_code >= 400:
            detail = (response.text or "").strip()[:400] or f"HTTP {response.status_code}"
            try:
                parsed = response.json()
                if isinstance(parsed, dict) and parsed.get("detail"):
                    detail = str(parsed.get("detail"))
            except Exception:
                pass
            raise LlmError(f"IndexTTS 克隆失败：{detail}")
        body = response.content or b""
        if not body:
            raise LlmError("IndexTTS 返回了空音频")
        return body

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        spk_audio: bytes | None = None,
        spk_filename: str = "prompt.wav",
        lang: str | None = None,
        emotion: str | None = None,
        emo_vector: list[float] | None = None,
        emo_alpha: float | None = None,
        duration_factor: float | None = None,
    ) -> bytes:
        if spk_audio and self.supports_clone():
            return self.clone(
                text,
                spk_audio=spk_audio,
                spk_filename=spk_filename,
                lang=lang,
                emotion=emotion,
                emo_vector=emo_vector,
                emo_alpha=emo_alpha,
                duration_factor=duration_factor,
            )
        client, model, default_voice = self.client()
        resolved = resolve_tts_voice(
            voice or default_voice,
            base_url=self.base_url(),
            model=model,
        )
        return client.speech(
            text=text,
            model=model,
            voice=resolved.strip() or default_voice,
        )
