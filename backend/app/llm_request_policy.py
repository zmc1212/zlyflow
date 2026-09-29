"""按官方协议构造最小 Chat 请求，不从报错猜测参数、不静默切模型。

能力表只管理请求参数，与视觉能力无关；看图必须继续使用真实图片探测。
未知模型使用上游采样/思考默认值，保留创作 token 上限。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

OPENAI_CHAT_DOC = "https://platform.openai.com/docs/api-reference/chat/create"
BAILIAN_GLM_DOC = "https://help.aliyun.com/zh/model-studio/glm"
BAILIAN_KIMI_DOC = "https://help.aliyun.com/zh/model-studio/kimi-api"
DEEPSEEK_THINKING_DOC = "https://api-docs.deepseek.com/guides/thinking_mode"
BAILIAN_QWEN_DOC = "https://help.aliyun.com/zh/model-studio/deep-thinking"


@dataclass(frozen=True)
class ChatParameterPolicy:
    name: str
    source: str
    token_parameter: str = "max_tokens"
    temperature_supported: bool = False
    reasoning_effort_supported: bool = False
    thinking_required: bool = False
    thinking_control: str | None = None


def model_name(model: str) -> str:
    return (model or "").strip().lower().rsplit("/", 1)[-1]


def is_openai_reasoning_chat_model(model: str) -> bool:
    name = model_name(model)
    return name.startswith("gpt-5") or name.startswith(("o1", "o3", "o4"))


def requires_glm_thinking(model: str) -> bool:
    return bool(re.fullmatch(r"glm-5\.3(?:[-:].+)?", model_name(model)))


def chat_policy(model: str, base_url: str) -> ChatParameterPolicy:
    name = model_name(model)
    host = (urlparse(base_url).hostname or "").lower()
    dashscope = host.endswith(".aliyuncs.com")
    if is_openai_reasoning_chat_model(model):
        return ChatParameterPolicy("openai-reasoning", OPENAI_CHAT_DOC,
                                   token_parameter="max_completion_tokens", reasoning_effort_supported=True)
    if requires_glm_thinking(model):
        return ChatParameterPolicy("glm-5.3", BAILIAN_GLM_DOC,
                                   thinking_required=True, thinking_control="enable")
    if re.fullmatch(r"kimi-k(?:3|2\.7-code|2-thinking)(?:[-:].+)?", name):
        return ChatParameterPolicy("kimi-thinking", BAILIAN_KIMI_DOC,
                                   thinking_required=True, thinking_control="enable" if dashscope else None)
    if re.fullmatch(r"kimi-k2\.[56](?:[-:].+)?", name):
        return ChatParameterPolicy("kimi-hybrid", BAILIAN_KIMI_DOC)
    if "deepseek" in name and ("v4" in name or "flash" in name or name in {"deepseek-chat", "deepseek-reasoner"}):
        return ChatParameterPolicy("deepseek-v4", DEEPSEEK_THINKING_DOC,
                                   temperature_supported=True, thinking_control="deepseek-disable")
    if name.startswith("qwen"):
        # 思考专用或未经声明的新型号使用官方默认模式。
        only_thinking = "thinking" in name or name in {
            "qwen3.8-2.4t-a95b", "qwen3.7-max-preview", "qwen3.7-max-2026-05-17",
        }
        known_hybrid = bool(re.fullmatch(r"qwen(?:2\.5.*|3-(?:235b-a22b|32b|30b-a3b|14b|8b)|3\.[568]-(?:max|plus|flash)(?:-.+)?)", name))
        return ChatParameterPolicy("qwen", BAILIAN_QWEN_DOC, temperature_supported=True,
                                   thinking_required=only_thinking,
                                   thinking_control="disable" if known_hybrid and not only_thinking else None)
    if name.startswith(("deepseek-r1", "qwq-", "minimax-m2")):
        return ChatParameterPolicy("thinking-defaults", BAILIAN_QWEN_DOC, thinking_required=True)
    if re.fullmatch(r"glm-(?:4\.[67]|5(?:\.[12])?)(?:[-:].+)?", name):
        return ChatParameterPolicy("glm-hybrid", BAILIAN_GLM_DOC,
                                   temperature_supported=True, thinking_control="disable")
    return ChatParameterPolicy("upstream-defaults", OPENAI_CHAT_DOC)


def thinking_control_fields(policy: ChatParameterPolicy) -> dict[str, Any]:
    if policy.thinking_control == "enable":
        return {"enable_thinking": True}
    if policy.thinking_control == "disable":
        return {"enable_thinking": False}
    if policy.thinking_control == "deepseek-disable":
        return {"enable_thinking": False, "thinking": {"type": "disabled"}}
    return {}


def chat_parameters(policy: ChatParameterPolicy, *, temperature: float,
                    max_tokens: int, reasoning_effort: str | None) -> dict[str, Any]:
    fields: dict[str, Any] = {policy.token_parameter: max_tokens}
    if policy.temperature_supported:
        fields["temperature"] = temperature
    if policy.reasoning_effort_supported and reasoning_effort:
        fields["reasoning_effort"] = reasoning_effort
    fields.update(thinking_control_fields(policy))
    return fields


def probe_token_budget(model: str, base_url: str, default: int) -> int:
    # 仅用于短探测；正式创作预算保持调用者指定值。
    return max(default, 4096) if chat_policy(model, base_url).thinking_required else default
