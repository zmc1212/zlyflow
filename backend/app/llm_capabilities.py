"""Optional LLM capabilities by provider and model family.

Detection is deliberately optimistic for models whose vendor documents the
feature, and conservative for aggregated gateways where pass-through differs
per model.  Every optional field is sent with a runtime fallback: if the
upstream rejects it, the provider retries without that capability and records
the downgrade for the rest of the process.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .llm_client import catalog_provider_key

STRUCTURED_NONE = None
STRUCTURED_OBJECT = "json_object"
STRUCTURED_SCHEMA = "json_schema"
CACHE_EXPLICIT = "explicit"
CACHE_IMPLICIT = "implicit"


@dataclass(frozen=True)
class LlmCapabilities:
    provider: str
    native_tools: bool
    structured_output: str | None
    prompt_cache: str | None
    web_search: bool
    usage_reporting: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_QWEN_VERSION = re.compile(r"qwen[-_]?(\d+(?:\.\d+)?)", re.I)
_NON_TEXT_MARKERS = (
    "vl", "vision", "audio", "asr", "tts", "ocr", "image", "embed", "rerank",
    "whisper", "sensevoice", "video", "sd-", "flux",
)
_TOOL_FAMILY = re.compile(
    r"qwen|deepseek|glm|gpt-|gpt-4|gpt-5|^o[134]|claude|gemini|llama-3\.[3-9]|llama-4|mistral-large",
    re.I,
)


def _is_text_model(model: str) -> bool:
    return not any(marker in model for marker in _NON_TEXT_MARKERS)


def _qwen_version(model: str) -> float | None:
    match = _QWEN_VERSION.search(model)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _has_explicit_cache(model: str, qwen_version: float | None) -> bool:
    if "qwen-plus" in model or "qwen-max" in model or "qwen3-max" in model:
        return True
    return qwen_version is not None and qwen_version >= 3.5


def _has_schema_output(model: str, qwen_version: float | None) -> bool:
    if "qwen3" in model:
        return True
    return qwen_version is not None and qwen_version >= 3.5


def detect_capabilities(base_url: str, model: str) -> LlmCapabilities:
    provider = catalog_provider_key(base_url)
    lowered = (model or "").strip().lower()
    text_model = _is_text_model(lowered)
    qwen = _qwen_version(lowered)
    tool_family = bool(_TOOL_FAMILY.search(lowered)) and text_model

    if provider == "dashscope":
        # Bailian exposes one OpenAI-compatible surface for every chat model;
        # model-level gaps (tools, search, schema, cache) are handled by the
        # runtime rejection fallback, so only multimodal/embedding models opt out.
        return LlmCapabilities(
            provider=provider,
            native_tools=text_model,
            structured_output=(
                STRUCTURED_SCHEMA if _has_schema_output(lowered, qwen) else STRUCTURED_OBJECT
            ) if text_model else STRUCTURED_NONE,
            prompt_cache=(
                CACHE_EXPLICIT if _has_explicit_cache(lowered, qwen) else CACHE_IMPLICIT
            ) if text_model else None,
            web_search=text_model,
        )

    if provider == "deepseek":
        return LlmCapabilities(
            provider=provider,
            native_tools=tool_family,
            structured_output=STRUCTURED_OBJECT if text_model else STRUCTURED_NONE,
            prompt_cache=CACHE_IMPLICIT if text_model else None,
            web_search=False,
        )

    if provider == "modelscope":
        # Aggregated inference gateway: tool pass-through varies per model, so
        # keep the validated JSON protocol and only opt into JSON mode.
        return LlmCapabilities(
            provider=provider,
            native_tools=False,
            structured_output=STRUCTURED_OBJECT if tool_family else STRUCTURED_NONE,
            prompt_cache=None,
            web_search=False,
        )

    if provider == "internai":
        # 端砚 discovery 网关同样是聚合推理入口：书生-S2 / Agents-A1 官方声明支持
        # 工具调用，但网关对第三方模型的透传口径未经验证，按 modelscope 的保守
        # 处理——不发送原生 tools，仅对工具家族模型启用 JSON 模式；显式缓存字段
        # 一律不发送（平台侧缓存计费自动生效）。
        return LlmCapabilities(
            provider=provider,
            native_tools=False,
            structured_output=STRUCTURED_OBJECT if tool_family else STRUCTURED_NONE,
            prompt_cache=None,
            web_search=False,
        )

    if provider == "siliconflow":
        return LlmCapabilities(
            provider=provider,
            native_tools=tool_family,
            structured_output=STRUCTURED_OBJECT if text_model else STRUCTURED_NONE,
            prompt_cache=CACHE_IMPLICIT if tool_family else None,
            web_search=False,
        )

    if provider == "zhipu":
        glm = "glm" in lowered and text_model
        return LlmCapabilities(
            provider=provider,
            native_tools=glm,
            structured_output=STRUCTURED_OBJECT if glm else STRUCTURED_NONE,
            prompt_cache=None,
            web_search=False,
        )

    if provider == "qiniu":
        # 官方聚合推理网关：conatus 免费模型声明支持工具调用、结构化输出与图像
        # 理解；其余模型按聚合网关的保守口径处理，运行期拒绝仍有一键降级兜底。
        conatus = lowered == "qiniu/conatus-free"
        return LlmCapabilities(
            provider=provider,
            native_tools=tool_family or conatus,
            structured_output=STRUCTURED_OBJECT if (tool_family or conatus) and text_model else STRUCTURED_NONE,
            prompt_cache=None,
            web_search=False,
        )

    if provider == "ollama":
        return LlmCapabilities(
            provider=provider,
            native_tools=text_model,
            structured_output=STRUCTURED_SCHEMA if text_model else STRUCTURED_NONE,
            prompt_cache=None,
            web_search=False,
        )

    modern_gpt = any(marker in lowered for marker in ("gpt-5", "gpt-4.1", "gpt-4o", "o3", "o4"))
    return LlmCapabilities(
        provider=provider,
        native_tools=tool_family,
        structured_output=(
            STRUCTURED_SCHEMA if modern_gpt
            else (STRUCTURED_OBJECT if tool_family else STRUCTURED_NONE)
        ),
        prompt_cache=None,
        web_search=False,
    )
