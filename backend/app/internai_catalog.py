"""Official InternLM Discovery (书生·端砚) preset and campaign pricing metadata.

上海人工智能实验室「书生·端砚」科研模型平台（discovery.intern-ai.org.cn）在测试期
每月向账号发放墨点额度，其中三款模型「限时 0 墨点」可免额度调用，其余模型按墨点
计费（官方计费表以 DeepSeek-V4-Flash 为例：缓存命中输入 0.02 墨点/百万 Token、
未命中输入 1、输出 4）。平台仅注明「测试期间」，未公布免费口径截止日，因此免费
标记不带时间窗口，以 ``pricing_verified_at`` 记录核对日期；上游 ``/v1/models``
返回的显式价格元数据仍然优先于本表。

API 采用标准 OpenAI 兼容协议：Base URL 为 ``https://discovery-api.intern-ai.org.cn/v1``
（结尾带 ``/v1``），``/v1/models`` 与对话接口均需 Bearer API Key（在端砚平台
「科研模型」页创建）。平台速率限制 RPM 50 / TPM 200 万，墨点与限额均为账户级
共享。测试期补贴随时可能调整，不宜作为生产关键链路的唯一供应商。

Reference: https://mp.weixin.qq.com/s/eT3vNsVv6Fvo42wStVPuhA（2026-11-01 核对，
计费口径引自上海AI实验室 2026-09-13 官方新闻与端砚 Token Plan 官方文档；
``deepseek-v4-flash-0731`` 的 ID 已由第三方实测确认，其余以平台「科研模型」页
与「拉取模型目录」结果为准）。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

INTERNAI_BASE_URL = "https://discovery-api.intern-ai.org.cn/v1"
INTERNAI_PORTAL_URL = "https://discovery.intern-ai.org.cn"
INTERNAI_PRICING_URL = "https://discovery.intern-ai.org.cn"
INTERNAI_PRICING_VERIFIED_AT = "2026-11-01"

# 限时 0 墨点（测试期，官方未公布截止日）：书生-S2、Atria-Dawn-Preview、Agents-A1。
INTERNAI_FREE_MODELS = ("intern-s2", "atria-dawn-preview", "agents-a1")
# 按墨点计费的模型：DeepSeek 三款（含唯一可看图的 Flash-Vision）+ GLM/Kimi/MiniMax/Qwen。
INTERNAI_METERED_MODELS = (
    "deepseek-v4-flash-0731",
    "deepseek-v4-pro-0813",
    "deepseek-v4-flash-vision",
    "glm-5.3",
    "kimi-k2.6",
    "minimax-m3",
    "qwen3.8-27b",
)

INTERNAI_CHAT_CATALOG = [
    {"id": "intern-s2", "label": "书生-S2（限时 0 墨点）", "free": True},
    {"id": "atria-dawn-preview", "label": "Atria-Dawn-Preview（限时 0 墨点，纯文本）", "free": True},
    {"id": "agents-a1", "label": "Agents-A1（限时 0 墨点）", "free": True},
    {"id": "deepseek-v4-flash-0731", "label": "DeepSeek-V4-Flash-0731（按墨点）", "free": False},
    {"id": "deepseek-v4-pro-0813", "label": "DeepSeek-V4-Pro-0813（按墨点）", "free": False},
    {"id": "deepseek-v4-flash-vision", "label": "DeepSeek-V4-Flash-Vision（按墨点，可看图）", "free": False},
    {"id": "glm-5.3", "label": "GLM-5.3（按墨点，消耗高）", "free": False},
    {"id": "kimi-k2.6", "label": "Kimi-K2.6（按墨点，消耗高）", "free": False},
    {"id": "minimax-m3", "label": "MiniMax-M3（按墨点）", "free": False},
    {"id": "qwen3.8-27b", "label": "Qwen3.8-27B（按墨点）", "free": False},
]
# 平台官方口径中唯一声明支持图像理解的模型，作为 VLM 设置页推荐项。
INTERNAI_VISION_CATALOG = [
    {"id": "deepseek-v4-flash-vision", "label": "DeepSeek-V4-Flash-Vision（按墨点，可看图）", "free": False},
]


def is_internai_official_base_url(base_url: str) -> bool:
    try:
        parsed = urlparse(str(base_url or "").strip())
        return (
            parsed.scheme == "https"
            and parsed.hostname == "discovery-api.intern-ai.org.cn"
            and parsed.port in (None, 443)
            and parsed.path.rstrip("/") in ("", "/v1")
            and not parsed.query and not parsed.fragment and not parsed.username
        )
    except (ValueError, AttributeError):
        return False


def internai_model_free(base_url: str, model: str) -> bool | None:
    """Campaign tariff hint for the official endpoint; upstream metadata still wins."""
    if not is_internai_official_base_url(base_url):
        return None
    lowered = str(model or "").strip().lower()
    if lowered in INTERNAI_FREE_MODELS:
        return True
    if lowered in INTERNAI_METERED_MODELS:
        return False
    return None


def internai_provider_preset() -> dict[str, Any]:
    return {
        "key": "internai",
        "label": "书生·端砚（上海AI实验室）",
        "base_url": INTERNAI_BASE_URL,
        "api_key_url": INTERNAI_PORTAL_URL,
        "pricing_url": INTERNAI_PRICING_URL,
        "pricing_verified_at": INTERNAI_PRICING_VERIFIED_AT,
        "chat_models": deepcopy(INTERNAI_CHAT_CATALOG),
        "vision_models": deepcopy(INTERNAI_VISION_CATALOG),
    }
