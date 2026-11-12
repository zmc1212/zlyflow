from __future__ import annotations

import json
import os
import threading
from typing import Any, Callable
from urllib.parse import urlparse

from .grs_provider import CredentialManager
from .llm_capabilities import STRUCTURED_OBJECT, STRUCTURED_SCHEMA, detect_capabilities
from .llm_client import (
    LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
    LLM_OPTIMIZE_TIMEOUT_SECONDS,
    LLM_TEST_TIMEOUT_SECONDS,
    ChatResult,
    OpenAICompatibleClient,
    LlmCapabilityError,
    LlmError,
    LlmTemporaryError,
    normalize_api_key,
    summarize_llm_test_reply,
)
from .storage import JobStore, now



DEFAULT_MODELSCOPE_BASE_URL = "https://api-inference.modelscope.cn/v1"
DEFAULT_MODELSCOPE_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"
# Verified in the A5.0 route check (docs/智能剪辑助手开发计划.md 4.2): this is the
# only catalog model that returns per-segment timestamps with acceptable Chinese
# accuracy. Whisper/SenseVoice variants on this provider expose no timestamps.
DEFAULT_ASR_MODEL = "XingChenAGI/XingChenASR-V3.2-Ultra"
ASR_MODEL_ENV = "ZLY_AI_VIDEO_STUDIO_ASR_MODEL"
ASR_TIMEOUT_SECONDS = 300.0

# A rejected optional field is remembered per endpoint+model so the next turn
# does not repeat the same failed request.
_CAPABILITY_DEGRADED: dict[str, set[str]] = {}
_CAPABILITY_LOCK = threading.Lock()


def _capability_key(base_url: str, model: str) -> str:
    return f"{str(base_url or '').rstrip('/')}|{model}"


def _remember_degraded(key: str, field: str) -> None:
    with _CAPABILITY_LOCK:
        _CAPABILITY_DEGRADED.setdefault(key, set()).add(field)


def _degraded_capabilities(key: str) -> set[str]:
    with _CAPABILITY_LOCK:
        return set(_CAPABILITY_DEGRADED.get(key, set()))


VISION_MODEL_MARKERS = (
    "vl", "vision", "gpt-4o", "gpt-4.1", "gpt-4.5", "gpt-5", "o4-mini",
    "gemini", "claude-3", "claude-4", "claude-sonnet", "claude-opus", "claude-haiku",
    "llava", "pixtral", "minimax-vl", "glm-4v", "glm-4.1v", "glm-4.5v", "glm-4.6v",
    "glm-5v", "internvl",
    "phi-4-multimodal", "phi-3.5-vision", "gemma-3", "gemma-4", "minicpm-v", "step-1v",
    "qwen2-vl", "qwen2.5-vl", "qwen3-vl", "qwen-vl",
    # 七牛 conatus 免费模型名称不含 VL/Vision，但官方声明支持图像理解。
    "conatus",
)


def model_supports_vision(model: str | None) -> bool:
    lowered = (model or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in VISION_MODEL_MARKERS)


def is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


class LlmProviderService:
    def __init__(self, store: JobStore, credential_key: str | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)

    def api_key(self) -> str | None:
        decrypted = self.credentials.decrypt(self.store.get_llm_settings().get("api_key_encrypted"))
        if not decrypted:
            config = self.store.get_llm_settings()
            if is_local_base_url(config.get("base_url", "")):
                return "ollama"  # 本地服务默认虚拟 key
        return decrypted

    def reveal_secret(self, field: str) -> str | None:
        """管理页「复制 Key」取回的明文；本地虚拟 Key 不返回。"""
        if field != "api_key":
            raise ValueError("LLM 大模型只支持复制 API Key")
        return self.credentials.decrypt(self.store.get_llm_settings().get("api_key_encrypted"))

    def availability(self) -> tuple[bool, str | None]:
        config = self.store.get_llm_settings()
        if not config["enabled"]:
            return False, "大模型服务尚未启用，请联系超级管理员配置。"
        if not is_local_base_url(config.get("base_url", "")) and not self.credentials.ready:
            return False, self.credentials.error or "凭证主密钥不可用"
        if not self.api_key():
            return False, "大模型 API Key / Token 未配置或无法解密。"
        if not config.get("model"):
            return False, "未配置大模型名称 (Model Name)。"
        return True, None

    def _stored_api_key(self, base_url: str) -> str | None:
        """Decrypted key saved in the endpoint credential vault for this base URL."""
        record = self.store.get_llm_endpoint_credential(base_url)
        if not record:
            return None
        return self.credentials.decrypt(record.get("api_key_encrypted"))

    def _resolve_request_key(self, base_url: str, submitted_key: str | None) -> str | None:
        """Key for a test/catalog call: submitted > active config > endpoint vault > local fallback."""
        same_endpoint = str(base_url or "").rstrip("/") == str(self.store.get_llm_settings()["base_url"]).rstrip("/")
        api_key = submitted_key or (self.api_key() if same_endpoint else None)
        if not api_key and not same_endpoint:
            api_key = self._stored_api_key(base_url)
        if not api_key and is_local_base_url(base_url or ""):
            api_key = "ollama"
        return api_key

    def _missing_key_message(self, base_url: str, action: str) -> str:
        """无 Key 可沿用时区分场景：切到从未保存过凭据的服务要提示先粘贴一次。"""
        same_endpoint = str(base_url or "").rstrip("/") == str(self.store.get_llm_settings()["base_url"]).rstrip("/")
        if not same_endpoint and not is_local_base_url(base_url or "") and not self._stored_api_key(base_url):
            return (
                f"{action}前请先粘贴一次该服务的 API Key：该服务还没有保存过凭据，"
                "保存后会自动记住，之后切换供应商会自动带出。"
            )
        return f"{action}需要提供有效的 API Key / Token"


    @staticmethod
    def _mask_key(api_key: str | None) -> str | None:
        if not api_key:
            return None
        if len(api_key) > 5:
            return f"{api_key[:3]}{'*' * max(5, min(16, len(api_key) - 5))}{api_key[-2:]}"
        return "*****"

    def _endpoint_credential_summaries(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for record in self.store.list_llm_endpoint_credentials():
            summaries.append({
                "base_url": record.get("base_url"),
                "model": str(record.get("model") or ""),
                "api_key_masked": self._mask_key(self.credentials.decrypt(record.get("api_key_encrypted"))),
                "updated_at": record.get("updated_at"),
            })
        return summaries

    def public_config(self) -> dict[str, Any]:
        config = self.store.get_llm_settings()
        api_key = self.api_key()
        available, reason = self.availability()
        return {
            "enabled": config["enabled"],
            "base_url": config["base_url"],
            "model": config["model"],
            "api_key_masked": self._mask_key(api_key),
            "has_api_key": bool(config.get("api_key_encrypted")),
            "credential_ready": self.credentials.ready,
            "last_test_status": config.get("last_test_status"),
            "last_test_message": config.get("last_test_message"),
            "last_test_at": config.get("last_test_at"),
            "available": available,
            "unavailable_reason": reason,
            "supports_vision": model_supports_vision(config.get("model")),
            "assistant_models": self.assistant_models(),
            "saved_provider_credentials": self._endpoint_credential_summaries(),
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        values = {key: value for key, value in payload.items() if key not in {"api_key", "assistant_models"}}
        if payload.get("assistant_models") is not None:
            models = list(dict.fromkeys(str(item).strip() for item in payload["assistant_models"] if str(item).strip()))
            if len(models) > 32 or any(len(item) > 255 for item in models):
                raise ValueError("助手可选模型最多32项，模型 ID 最多255字符")
            import json
            values["assistant_models_json"] = json.dumps(models, ensure_ascii=False)
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

        api_key = normalize_api_key(payload.get("api_key"))
        previous = self.store.get_llm_settings()
        previous_base_url = str(previous.get("base_url") or "").rstrip("/")
        changed_endpoint = values["base_url"] != previous_base_url
        if changed_endpoint or values["model"] != previous.get("model") or (api_key and api_key != self.api_key()):
            values.update(last_test_status=None, last_test_message=None, last_test_at=None)
        # 换端点即将覆盖主配置里的密文：先把旧端点凭据补进档案表，避免下次切回旧端点还要重新粘贴 Key。
        # 同端点保存与空端点（首次配置）不触发；本机地址本就无需 Key，跳过补档。
        if changed_endpoint and previous.get("api_key_encrypted") and previous_base_url \
                and not is_local_base_url(previous_base_url) \
                and not self.store.get_llm_endpoint_credential(previous_base_url):
            self.store.upsert_llm_endpoint_credential(
                previous_base_url, previous["api_key_encrypted"], str(previous.get("model") or "")
            )
        if api_key:
            if not self.credentials.ready:
                raise ValueError(self.credentials.error or "凭证主密钥不可用")
            values["api_key_encrypted"] = self.credentials.encrypt(api_key)
            self.store.upsert_llm_endpoint_credential(values["base_url"], values["api_key_encrypted"], values["model"])
        elif changed_endpoint:
            # 切换服务地址：优先带出该端点已保存的凭据档案，避免每次切换重新粘贴 Key。
            stored = self.store.get_llm_endpoint_credential(values["base_url"])
            if stored and stored.get("api_key_encrypted"):
                values["api_key_encrypted"] = stored["api_key_encrypted"]
            elif previous.get("api_key_encrypted") and not is_local_base_url(values["base_url"]):
                raise ValueError("切换服务地址后请填写对应的 API Key；该服务还没有保存过凭据，输入一次后会自动记住。")
            else:
                values["api_key_encrypted"] = None
        elif previous.get("api_key_encrypted"):
            # 同端点保存：把既有凭据回填为该端点的档案，历史配置升级后立即具备切换能力。
            self.store.upsert_llm_endpoint_credential(values["base_url"], previous["api_key_encrypted"], values["model"])

        self.store.update_llm_settings(**values)
        return self.public_config()

    def assistant_models(self) -> list[str]:
        import json
        config = self.store.get_llm_settings()
        try:
            values = json.loads(config.get("assistant_models_json") or "[]")
        except (ValueError, TypeError):
            values = []
        if not isinstance(values, list):
            values = []
        return list(dict.fromkeys(str(v) for v in values if isinstance(v, str) and v.strip())) or [config["model"]]

    def assistant_capabilities(self, model_id: str) -> dict[str, Any]:
        config = self.store.get_llm_settings()
        base_url = str(config.get("base_url") or "")
        caps = detect_capabilities(base_url, model_id).as_dict()
        degraded = _degraded_capabilities(_capability_key(base_url, model_id))
        if "native_tools" in degraded:
            caps["native_tools"] = False
        if "response_format" in degraded:
            caps["structured_output"] = None
        elif "json_schema" in degraded and caps["structured_output"] == STRUCTURED_SCHEMA:
            caps["structured_output"] = STRUCTURED_OBJECT
        if "prompt_cache" in degraded:
            caps["prompt_cache"] = None
        if "web_search" in degraded:
            caps["web_search"] = False
        if "stream_options" in degraded:
            caps["usage_reporting"] = False
        caps["degraded"] = sorted(degraded)
        return caps

    def assistant_model_catalog(self) -> list[dict[str, Any]]:
        return [
            {"id": model, "label": model, "capabilities": self.assistant_capabilities(model)}
            for model in self.assistant_models()
        ]

    def assistant_chat(self, messages: list[dict], model_id: str, on_chunk: Any = None) -> str:
        if model_id not in self.assistant_models():
            raise ValueError("该模型未向助手开放，请重新选择模型")
        client, _ = self._chat_client()
        try:
            return client.chat_completion(
                messages,
                model=model_id,
                stream=True,
                on_chunk=on_chunk,
                max_tokens=16000,
                temperature=0.5,
                timeout=(15, 240),
                stream_idle_timeout=90,
                stream_total_timeout=900,
            )
        except LlmTemporaryError:
            # Free providers often keep the SSE socket open after the answer.
            # Retry once without streaming so the run still finishes.
            return client.chat_completion(
                messages,
                model=model_id,
                stream=False,
                max_tokens=16000,
                temperature=0.5,
                timeout=(15, 300),
            )

    def chat_json(self, system_prompt: str, user_content: str, *, temperature: float = 0.7, max_tokens: int = 4096) -> dict[str, Any]:
        """One-shot JSON chat with the default chat model, for domain flows that need structured output."""
        return self.chat_json_messages(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _json_chat_call(
        self,
        client: OpenAICompatibleClient,
        messages: list[dict],
        model: str,
        *,
        temperature: float,
        max_tokens: int,
        stream: bool,
        on_delta: Any = None,
    ) -> str:
        """chat_json_* 专用调用：优先开 JSON 模式（response_format=json_object）。

        弱模型遇到“只改音色”这类小修改时会无视“只输出 JSON”的提示词、直接回散文
        （实测 deepseek-v4-flash 连续复现），导致“大模型未返回有效的 JSON”；
        JSON 模式由服务端强制约束输出格式，是唯一可靠的解法。
        上游拒绝该字段时按能力降级记忆退回普通调用，与 assistant_chat_with_meta 同一惯用法。"""
        key = _capability_key(self.store.get_llm_settings()["base_url"], model)
        use_json_mode = "response_format" not in _degraded_capabilities(key)
        while True:
            try:
                result = client.chat_completion_result(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=(15, 300),
                    stream=stream,
                    on_delta=on_delta,
                    response_format={"type": STRUCTURED_OBJECT} if use_json_mode else None,
                )
                return result.content
            except LlmCapabilityError as error:
                if error.field != "response_format" or not use_json_mode:
                    raise
                _remember_degraded(key, "response_format")
                use_json_mode = False

    def chat_json_messages(self, messages: list[dict], *, temperature: float = 0.7, max_tokens: int = 4096) -> dict[str, Any]:
        """Multi-turn JSON chat with the default chat model; same parsing contract as chat_json."""
        from .director_agents import parse_json_object
        from .llm_client import LlmError

        client, model = self._chat_client()
        raw = self._json_chat_call(
            client, messages, model,
            temperature=temperature, max_tokens=max_tokens, stream=False,
        )
        parsed = parse_json_object(raw)
        if not isinstance(parsed, dict):
            raise LlmError("大模型未返回有效的 JSON，请重试")
        return parsed

    def chat_json_messages_stream(
        self, messages: list[dict], on_chunk: Any = None, *, temperature: float = 0.7, max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Streaming variant of chat_json_messages: on_chunk receives the accumulated raw
        text so far (for partial-JSON previews); the parsed dict is returned on completion.

        预览走 on_delta 钩子逐 token 累积（on_chunk 的 1.5s/400 字符节流会把短回复合并成一段）。"""
        from .director_agents import parse_json_object
        from .llm_client import LlmError, LlmTemporaryError

        client, model = self._chat_client()
        pieces: list[str] = []

        def on_delta(kind: str, piece: str) -> None:
            if kind == "content" and piece and on_chunk:
                pieces.append(piece)
                on_chunk("".join(pieces))

        try:
            raw = self._json_chat_call(
                client, messages, model,
                temperature=temperature, max_tokens=max_tokens, stream=True, on_delta=on_delta,
            )
        except LlmTemporaryError:
            # 免费通道常在 SSE 结束后不关流；降级一次非流式重试
            raw = self._json_chat_call(
                client, messages, model,
                temperature=temperature, max_tokens=max_tokens, stream=False,
            )
        try:
            parsed = parse_json_object(raw)
        except Exception:
            # 流式通道偶发吐垃圾/限流文案；换非流式整段重试一次
            raw = self._json_chat_call(
                client, messages, model,
                temperature=temperature, max_tokens=max_tokens, stream=False,
            )
            parsed = parse_json_object(raw)
        if not isinstance(parsed, dict):
            raise LlmError("大模型未返回有效的 JSON，请重试")
        return parsed

    def assistant_chat_with_meta(
        self,
        messages: list[dict],
        model_id: str,
        on_chunk: Any = None,
        *,
        response_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        enable_search: bool = False,
    ) -> ChatResult:
        """Assistant chat with native tools, JSON schema, cache and web search.

        Each optional capability has a one-shot runtime fallback: when the
        upstream rejects a field the call is retried without it and the
        downgrade is remembered for this endpoint+model.
        """
        if model_id not in self.assistant_models():
            raise ValueError("该模型未向助手开放，请重新选择模型")
        client, _ = self._chat_client()
        config = self.store.get_llm_settings()
        base_url = str(config.get("base_url") or "")
        key = _capability_key(base_url, model_id)
        caps = detect_capabilities(base_url, model_id)
        degraded = _degraded_capabilities(key)
        options: dict[str, Any] = {
            "response_format": self._assistant_response_format(caps, degraded, response_schema),
            "tools": tools if tools and caps.native_tools and "native_tools" not in degraded else None,
            "enable_search": bool(enable_search and caps.web_search and "web_search" not in degraded),
            "cache_control": bool(caps.prompt_cache == "explicit" and "prompt_cache" not in degraded),
            "include_usage": "stream_options" not in degraded,
        }
        fallbacks: list[str] = []
        for _ in range(7):
            try:
                result = self._assistant_request(client, messages, model_id, on_chunk, options)
            except LlmCapabilityError as error:
                field_name = error.field
                if (
                    field_name == "response_format"
                    and options["response_format"]
                    and options["response_format"].get("type") == STRUCTURED_SCHEMA
                ):
                    _remember_degraded(key, "json_schema")
                    options["response_format"] = {"type": STRUCTURED_OBJECT} if response_schema else None
                    fallbacks.append("json_schema→json_object")
                    continue
                if field_name == "response_format":
                    _remember_degraded(key, "response_format")
                    options["response_format"] = None
                    fallbacks.append("response_format")
                    continue
                if field_name == "tools":
                    _remember_degraded(key, "native_tools")
                    options["tools"] = None
                    fallbacks.append("native_tools")
                    continue
                if field_name == "enable_search":
                    _remember_degraded(key, "web_search")
                    options["enable_search"] = False
                    fallbacks.append("web_search")
                    continue
                if field_name == "cache_control":
                    _remember_degraded(key, "prompt_cache")
                    options["cache_control"] = False
                    fallbacks.append("prompt_cache")
                    continue
                if field_name == "stream_options":
                    _remember_degraded(key, "stream_options")
                    options["include_usage"] = False
                    fallbacks.append("stream_options")
                    continue
                raise
            result.extra.setdefault("provider", caps.provider)
            result.extra["degraded"] = fallbacks
            result.extra.setdefault("web_search_requested", bool(options["enable_search"]))
            return result
        raise LlmError("大模型拒绝了本轮请求的附加能力，请更换模型后重试")

    @staticmethod
    def _assistant_response_format(caps: Any, degraded: set[str], schema: dict[str, Any] | None) -> dict[str, Any] | None:
        if not schema or "response_format" in degraded:
            return None
        if caps.structured_output == STRUCTURED_SCHEMA and "json_schema" not in degraded:
            return {"type": STRUCTURED_SCHEMA, "json_schema": schema}
        if caps.structured_output in {STRUCTURED_SCHEMA, STRUCTURED_OBJECT}:
            return {"type": STRUCTURED_OBJECT}
        return None

    @staticmethod
    def _assistant_request(
        client: OpenAICompatibleClient,
        messages: list[dict],
        model_id: str,
        on_chunk: Any,
        options: dict[str, Any],
    ) -> ChatResult:
        try:
            return client.chat_completion_result(
                messages,
                model=model_id,
                stream=True,
                on_chunk=on_chunk,
                max_tokens=16000,
                temperature=0.5,
                timeout=(15, 240),
                stream_idle_timeout=90,
                stream_total_timeout=900,
                response_format=options["response_format"],
                tools=options["tools"],
                enable_search=options["enable_search"],
                cache_control=options["cache_control"],
                include_usage=options["include_usage"],
            )
        except LlmTemporaryError:
            # Free providers often keep the SSE socket open after the answer.
            # Retry once without streaming so the run still finishes.
            return client.chat_completion_result(
                messages,
                model=model_id,
                stream=False,
                max_tokens=16000,
                temperature=0.5,
                timeout=(15, 300),
                response_format=options["response_format"],
                tools=options["tools"],
                enable_search=options["enable_search"],
                cache_control=options["cache_control"],
            )


    def test(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        config = self.store.get_llm_settings()
        base_url = (payload.get("base_url") if payload else None) or config["base_url"]
        model = (payload.get("model") if payload else None) or config["model"]
        submitted_key = normalize_api_key(payload.get("api_key")) if payload else None
        api_key = self._resolve_request_key(base_url, submitted_key)

        if not api_key:
            raise ValueError(self._missing_key_message(base_url, "测试连接"))
        if not base_url:
            raise ValueError("Base URL 不能为空")
        if not model:
            raise ValueError("Model 名称不能为空")

        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        test_time = now()
        try:
            reply = client.test_connection(model=model, timeout=LLM_TEST_TIMEOUT_SECONDS)
            test_status = "成功"
            test_message = summarize_llm_test_reply(reply)
        except Exception as exc:
            test_status = "失败"
            test_message = str(exc)

        current = self.store.get_llm_settings()
        if base_url.rstrip("/") == str(current["base_url"]).rstrip("/") and model == current["model"] and api_key == self.api_key():
            self.store.update_llm_settings(
                last_test_status=test_status,
                last_test_message=test_message,
                last_test_at=test_time,
            )
        if test_status != "成功":

            raise LlmError(f"大模型连接测试失败：{test_message}")
        return {**self.public_config(), "last_test_status": test_status, "last_test_message": test_message, "last_test_at": test_time}

    def list_catalog(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        config = self.store.get_llm_settings()
        base_url = (payload.get("base_url") if payload else None) or config["base_url"]
        submitted_key = normalize_api_key(payload.get("api_key")) if payload else None
        api_key = self._resolve_request_key(base_url, submitted_key)
        if not api_key:
            raise LlmError(self._missing_key_message(base_url, "拉取模型目录"))
        if not base_url:
            raise LlmError("Base URL 不能为空")
        free_only = True if payload is None else bool(payload.get("free_only", True))
        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        return client.list_model_catalog(free_only=free_only)

    def optimize_prompt(
        self,
        prompt: str,
        *,
        media_type: str = "video",
        workflow_name: str | None = None,
        skill_id: str | None = None,
        skill_pack_id: str | None = None,
        reference_count: int = 0,
        workflow_id: str | None = None,
        image_urls: list[str] | None = None,
        reference_mode: str | None = None,
        duration_seconds: float | None = None,
    ) -> dict[str, str]:
        available, reason = self.availability()
        if not available:
            raise LlmError(reason or "大模型服务不可用")

        config = self.store.get_llm_settings()
        api_key = self.api_key()
        if not api_key:
            raise LlmError("大模型凭据未配置")

        from .llm_minimax_skills import build_h3_system_prompt, resolve_h3_prompt_mode
        from .vision_runtime import complete_authoring, normalize_image_urls

        urls = normalize_image_urls(image_urls)
        resolved_reference_mode = reference_mode
        if not resolved_reference_mode and media_type == "video" and workflow_id:
            from .workflow_registry import workflow_for

            try:
                resolved_reference_mode = workflow_for(workflow_id).reference_mode
            except KeyError:
                resolved_reference_mode = None
        effective_reference_count = max(reference_count, len(urls)) if media_type == "video" else reference_count
        prompt_mode = resolve_h3_prompt_mode(resolved_reference_mode, effective_reference_count)
        max_tokens = 2600 if prompt_mode == "REF2VA" else 1800

        if urls:
            system_instruction = build_h3_system_prompt(
                skill_id=skill_id,
                reference_count=effective_reference_count,
                media_type=media_type,
                workflow_name=workflow_name,
                skill_pack_id=skill_pack_id,
                reference_mode=resolved_reference_mode,
                duration_seconds=duration_seconds,
            )
            user_content = f"原始创意需求：{prompt.strip()}"
            if workflow_name:
                user_content += f"\n当前工作流名称：{workflow_name}"
            if workflow_id:
                user_content += f"\n当前工作流 ID：{workflow_id}"
            user_content += f"\n已上传参考图数量：{len(urls)} 张"
            text, _meta = complete_authoring(
                config,
                self.store.get_vlm_settings(),
                self.credentials.decrypt,
                system_instruction,
                user_content,
                urls,
                max_tokens=max_tokens,
                temperature=0.7,
                timeout=LLM_OPTIMIZE_TIMEOUT_SECONDS,
            )
            optimized = str(text or "").strip()
            if optimized.startswith("```") and optimized.endswith("```"):
                lines = optimized.splitlines()
                if len(lines) >= 3:
                    optimized = "\n".join(lines[1:-1]).strip()
            if not optimized:
                raise LlmError("大模型未返回优化后的提示词")
            optimized = self._finalize_optimized_prompt(optimized, media_type)
            display = self._translate_prompt_for_display(optimized, config, api_key) if media_type == "video" else ""
            return {"optimized_prompt": optimized, "optimized_prompt_zh": display}

        client = OpenAICompatibleClient(base_url=config["base_url"], api_key=api_key)
        optimized = client.optimize_prompt(
            prompt,
            media_type=media_type,
            workflow_name=workflow_name,
            skill_id=skill_id,
            skill_pack_id=skill_pack_id,
            reference_count=effective_reference_count,
            workflow_id=workflow_id,
            model=config["model"],
            reference_mode=resolved_reference_mode,
            duration_seconds=duration_seconds,
            max_tokens=max_tokens,
        )
        optimized = self._finalize_optimized_prompt(optimized, media_type)
        display = self._translate_prompt_for_display(optimized, config, api_key) if media_type == "video" else ""
        return {"optimized_prompt": optimized, "optimized_prompt_zh": display}

    @staticmethod
    def _finalize_optimized_prompt(optimized: str, media_type: str) -> str:
        text = (optimized or "").strip()
        if media_type != "video":
            return text
        from .llm_minimax_skills import extract_h3_prompt_from_model_output

        extracted = extract_h3_prompt_from_model_output(text)
        if not extracted:
            raise LlmError("大模型返回了分析过程，但没有可用的 H3 提示词。请重试或更换模型。")
        return extracted

    def _translate_prompt_for_display(self, prompt: str, config: dict[str, Any], api_key: str) -> str:
        """Best-effort Chinese display copy; generation still uses the English H3 prompt."""
        from .llm_minimax_skills import missing_h3_translation_fields

        try:
            client = OpenAICompatibleClient(base_url=config["base_url"], api_key=api_key)
            display = client.translate_h3_prompt_to_chinese(prompt, model=config["model"]).strip()
            missing = missing_h3_translation_fields(prompt, display)
            if missing:
                display = client.translate_h3_prompt_to_chinese(
                    prompt, model=config["model"], field_reminder=missing,
                ).strip()
                if missing_h3_translation_fields(prompt, display):
                    return ""
            return display
        except Exception:
            return ""

    def split_script(
        self,
        script: str,
        *,
        shot_count: int = 4,
        style_vibe: str | None = None,
        cast_names: list[str] | None = None,
        script_mode: str = "literal",
    ) -> dict[str, Any]:
        available, reason = self.availability()
        if not available:
            raise LlmError(reason or "大模型服务不可用")

        config = self.store.get_llm_settings()
        api_key = self.api_key()
        if not api_key:
            raise LlmError("大模型凭据未配置")

        client = OpenAICompatibleClient(base_url=config["base_url"], api_key=api_key)
        return client.split_script(
            script,
            shot_count=shot_count,
            style_vibe=style_vibe,
            cast_names=cast_names,
            script_mode=script_mode,
            model=config["model"],
        )

    def repair_director_continuity(
        self,
        recipe: dict[str, Any],
        *,
        from_shot: int,
        to_shot: int,
    ) -> dict[str, Any]:
        from .director_agents import (
            _apply_continuity_repair,
            _chat_json,
            _continuity_repair_payload,
            default_chat_fn,
            validate_continuity_pairs,
        )
        from .director_recipe import normalize_recipe_payload
        from .llm_minimax_skills import build_storyboard_continuity_repair_prompt

        normalized = normalize_recipe_payload(recipe)
        qa = validate_continuity_pairs(normalized)
        selected = next((
            pair for pair in qa.get("pairs", [])
            if pair.get("fromShot") == from_shot and pair.get("toShot") == to_shot
        ), None)
        if selected is None:
            raise LlmError("指定的相邻镜头不存在")
        if selected.get("status") != "warning":
            return {"recipe": normalized, "applied": 0, "pair": selected, "alreadyPassed": True}

        request_payload, requested_pairs = _continuity_repair_payload(normalized, [selected], limit=1)
        if requested_pairs != [(from_shot, to_shot)]:
            raise LlmError("无法构造指定镜头对的连续性修复请求")

        client, model = self._chat_client()
        parsed = _chat_json(default_chat_fn(client, model), [
            {"role": "system", "content": build_storyboard_continuity_repair_prompt()},
            {"role": "user", "content": json.dumps(request_payload, ensure_ascii=False)},
        ], retries=1)
        if not isinstance(parsed, dict):
            raise LlmError("连续性修复未返回合法 JSON")

        applied, errors, resplit_required = _apply_continuity_repair(
            normalized,
            parsed,
            requested_pairs=requested_pairs,
        )
        if errors:
            raise LlmError("；".join(errors))
        normalized["continuityQa"] = validate_continuity_pairs(normalized)
        pair = next((
            item for item in normalized["continuityQa"].get("pairs", [])
            if item.get("fromShot") == from_shot and item.get("toShot") == to_shot
        ), {"fromShot": from_shot, "toShot": to_shot, "status": "warning"})
        return {
            "recipe": normalized,
            "applied": applied,
            "pair": pair,
            "resplitRequired": resplit_required,
            "alreadyPassed": False,
        }

    def _chat_client(self) -> tuple[Any, str]:
        available, reason = self.availability()
        if not available:
            raise LlmError(reason or "大模型服务不可用")
        config = self.store.get_llm_settings()
        api_key = self.api_key()
        if not api_key:
            raise LlmError("大模型凭据未配置")
        return OpenAICompatibleClient(base_url=config["base_url"], api_key=api_key), config["model"]

    def transcription_model(self) -> str | None:
        return (os.getenv(ASR_MODEL_ENV) or "").strip() or DEFAULT_ASR_MODEL

    def transcription_availability(self) -> tuple[bool, str | None]:
        """Audio transcription reuses the LLM endpoint and credential; no separate provider table."""
        config = self.store.get_llm_settings()
        if not config["enabled"]:
            return False, "大模型服务尚未启用，请联系超级管理员配置。"
        if not is_local_base_url(config.get("base_url", "")) and not self.credentials.ready:
            return False, self.credentials.error or "凭证主密钥不可用"
        if not self.api_key():
            return False, "大模型 API Key / Token 未配置或无法解密。"
        if not self.transcription_model():
            return False, "未配置语音转写模型。"
        return True, None

    def transcribe_audio(self, audio_path: Any, *, timeout: float = ASR_TIMEOUT_SECONDS) -> dict[str, Any]:
        available, reason = self.transcription_availability()
        if not available:
            raise LlmError(reason or "语音转写服务不可用")
        config = self.store.get_llm_settings()
        client = OpenAICompatibleClient(base_url=config["base_url"], api_key=self.api_key())
        return client.transcribe(audio_path=audio_path, model=self.transcription_model(), timeout=timeout)

    def run_director_recipe(
        self,
        recipe: dict[str, Any] | None,
        *,
        goal: str,
        art_style_id: str | None = None,
        agents: list[str] | None = None,
        skip_research: bool | None = None,
        on_progress: Any = None,
        on_stream: Any = None,
        clarifications: Any = None,
        resume: bool | None = None,
    ) -> dict[str, Any]:
        from .director_agents import default_chat_fn, run_recipe_pipeline

        client, model = self._chat_client()
        return run_recipe_pipeline(
            recipe,
            goal=goal,
            chat_fn=default_chat_fn(client, model),
            art_style_id=art_style_id,
            agents=agents,
            skip_research=skip_research,
            on_progress=on_progress,
            on_stream=on_stream,
            clarifications=clarifications,
            resume=resume,
        )

    @staticmethod
    def _art_style_category_names() -> str:
        try:
            from .director_catalog import list_art_style_categories

            categories = list_art_style_categories()
        except Exception:
            return ""
        return "、".join(str(item.get("name_zh") or "").strip() for item in categories if str(item.get("name_zh") or "").strip())

    def run_director_clarify(
        self,
        goal: str,
        *,
        recipe: Any = None,
        agent: str | None = None,
        feedback: str | None = None,
        on_stream: Any = None,
        include_beat_count: bool = True,
        include_shots_per_episode: bool = False,
    ) -> list[dict[str, Any]]:
        """Ask confirm questions and stream them via on_stream.

        agent=None asks plot-direction questions before the script agent; otherwise
        agent is a STAGE_CLARIFY_AGENT_IDS step and the questions cover that step only.
        feedback is the user's free-text revision request for the current step; it is
        injected as 「本轮调整诉求」 so the questions target that request.
        """
        from .director_stream import AGENT_STREAM_SPECS, AgentStreamTracker
        from .llm_minimax_skills import (
            OPENING_SCALE_QUESTION_IDS,
            STAGE_CLARIFY_AGENT_IDS,
            build_clarify_questions_prompt,
            build_stage_clarify_context,
            build_stage_clarify_prompt,
            normalize_clarify_questions,
            normalize_stage_clarify_questions,
        )

        brief = str(goal or "").strip()
        if not brief:
            raise LlmError("请先填写创意简报")
        agent_id = str(agent or "").strip() or None
        feedback_text = str(feedback or "").strip()
        if agent_id:
            if agent_id not in STAGE_CLARIFY_AGENT_IDS:
                raise LlmError(f"该环节不支持创作确认：{agent_id}")
            system_prompt = build_stage_clarify_prompt(agent_id, style_categories=self._art_style_category_names())
            user_content = build_stage_clarify_context(recipe, brief)
            if not user_content:
                raise LlmError("还没有可以确认的创作内容，请先生成剧本")
        else:
            system_prompt = build_clarify_questions_prompt(
                include_beat_count=include_beat_count,
                include_shots_per_episode=include_shots_per_episode,
            )
            user_content = brief
        if feedback_text:
            system_prompt += (
                "\n\n用户对本环节当前产出不满意，下面的「本轮调整诉求」是本轮必须围绕的调整方向。"
                "问题必须针对这些诉求展开，禁止无视反馈另起一套空泛问题。"
            )
            user_content = f"{user_content}\n\n本轮调整诉求：{feedback_text}"
        client, model = self._chat_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        tracker = AgentStreamTracker(AGENT_STREAM_SPECS["clarify"], on_stream) if on_stream is not None else None
        raw = client.chat_completion(
            messages,
            model=model,
            temperature=0.6,
            max_tokens=2048,
            timeout=LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
            stream=True,
            on_chunk=tracker.feed if tracker is not None else None,
        )
        from .director_agents import parse_json_object

        parsed = parse_json_object(raw)
        raw_questions = parsed.get("questions") if isinstance(parsed, dict) else None
        if agent_id:
            questions = normalize_stage_clarify_questions(raw_questions)
            if not questions:
                raise LlmError("大模型未返回有效的确认问题，请重试")
            if agent_id == "storyboard" and bool((recipe or {}).get("scenes")):
                questions.insert(0, {
                    "id": "keep_original_storyboard",
                    "question": "检测到已导入原分镜，是否直接使用？",
                    "why": "你可以选择保留已导入的分镜，或者让大模型根据剧本重新自动拆分。",
                    "options": [
                        {"label": "不改变原分镜", "value": "保留并跳过 AI 生成", "recommended": True},
                        {"label": "调用大模型自动拆分", "value": "重新生成"},
                    ],
                    "allowCustom": False,
                })
        else:
            has_direction_question = any(
                isinstance(item, dict)
                and str(item.get("question") or "").strip()
                and str(item.get("id") or "").strip() not in OPENING_SCALE_QUESTION_IDS
                for item in (raw_questions or [])
            )
            if not has_direction_question:
                raise LlmError("大模型未返回有效的创作方向问题，请重试")
            questions = normalize_clarify_questions(
                raw_questions,
                include_beat_count=include_beat_count,
                include_shots_per_episode=include_shots_per_episode,
            )
            if bool(str(((recipe or {}).get("script") or {}).get("fullStory") or "").strip()):
                questions.insert(0, {
                    "id": "keep_original_script",
                    "question": "检测到已导入原剧本，是否直接使用？",
                    "why": "你可以选择保留已导入的文本，或者在后续步骤让大模型根据你的想法重新生成。",
                    "options": [
                        {"label": "不改变原剧本", "value": "保留并跳过 AI 生成", "recommended": True},
                        {"label": "让大模型按新想法重新生成", "value": "重新生成"},
                    ],
                    "allowCustom": False,
                })
        if tracker is not None:
            tracker.finish({"questions": questions})
        return questions

    def run_director_agent_step(
        self,
        recipe: dict[str, Any] | None,
        *,
        goal: str,
        agent_id: str,
        art_style_id: str | None = None,
        skip_research: bool | None = None,
        on_progress: Any = None,
    ) -> dict[str, Any]:
        from .director_agents import default_chat_fn, run_agent

        client, model = self._chat_client()
        return run_agent(
            agent_id,
            recipe or {},
            goal=goal,
            chat_fn=default_chat_fn(client, model),
            art_style_id=art_style_id,
            skip_research=skip_research,
            on_progress=on_progress,
        )

    def polish_director_h3_prompt(
        self,
        draft_prompt: str,
        mode: str,
        on_chunk: Callable[[str], None] | None = None,
        image_urls: list[str] | None = None,
    ) -> str:
        """Use the configured LLM after the final H3 input mode and reference order are known."""
        from .llm_minimax_skills import build_h3_final_prompt_polish_prompt
        from .vision_runtime import complete_authoring, normalize_image_urls

        draft = str(draft_prompt or "").strip()
        if not draft:
            raise LlmError("没有可润色的 H3 提示词")
        urls = normalize_image_urls(image_urls)
        if urls:
            text, _meta = complete_authoring(
                self.store.get_llm_settings(),
                self.store.get_vlm_settings(),
                self.credentials.decrypt,
                build_h3_final_prompt_polish_prompt(mode),
                f"Requested final prompt:\n\n{draft}",
                urls,
                max_tokens=8192,
                temperature=0.35,
                timeout=LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
            )
            return text.strip()
        client, model = self._chat_client()
        return client.chat_completion(
            [
                {"role": "system", "content": build_h3_final_prompt_polish_prompt(mode)},
                {"role": "user", "content": f"Requested final prompt:\n\n{draft}"},
            ],
            model=model,
            temperature=0.35,
            max_tokens=8192,
            timeout=LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
            stream=True,
            on_chunk=on_chunk,
        ).strip()

    def translate_director_shot_prompt(self, text: str) -> str:
        """Translate a Chinese shot body into an official-format English H3 shot body."""
        from .llm_minimax_skills import build_h3_prompt_translate_prompt

        source = str(text or "").strip()
        if not source:
            raise LlmError("没有可翻译的镜头正文")
        client, model = self._chat_client()
        return client.chat_completion(
            [
                {"role": "system", "content": build_h3_prompt_translate_prompt()},
                {"role": "user", "content": f"Translate this shot body to English:\n\n{source}"},
            ],
            model=model,
            temperature=0.2,
            max_tokens=4096,
            timeout=LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
            stream=False,
        ).strip()

    def fission_batch_scripts(
        self,
        *,
        theme: str,
        count: int,
        duration_sec: int,
        aspect_ratio: str,
        art_style: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        from .director_agents import default_chat_fn, fission_batch_scripts

        client, model = self._chat_client()
        return fission_batch_scripts(
            theme=theme,
            count=count,
            duration_sec=duration_sec,
            aspect_ratio=aspect_ratio,
            art_style=art_style,
            chat_fn=default_chat_fn(client, model),
        )
