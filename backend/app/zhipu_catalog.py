"""Official Zhipu presets and conservative pricing metadata shared by both settings pages."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ZHIPU_PRICING_URL = "https://docs.bigmodel.cn/cn/guide/start/pricing"
ZHIPU_PRICING_VERIFIED_AT = "2026-10-20"

ZHIPU_CHAT_CATALOG = [
    {"id": "glm-4.7-flash", "label": "GLM-4.7-Flash", "free": True},
    {"id": "glm-4.7", "label": "GLM-4.7", "free": False},
    {"id": "glm-5.3", "label": "GLM-5.3", "free": False},
]
ZHIPU_VISION_CATALOG = [
    {"id": "glm-4.6v-flash", "label": "GLM-4.6V-Flash", "free": True},
    {"id": "glm-4.6v", "label": "GLM-4.6V", "free": False},
    {"id": "glm-4.6v-flashx", "label": "GLM-4.6V-FlashX", "free": False},
    {"id": "glm-4v-flash", "label": "GLM-4V-Flash", "free": True},
    {"id": "glm-4.1v-thinking-flash", "label": "GLM-4.1V-Thinking-Flash", "free": True},
]

# Exact IDs only: FlashX, dated variants, relays and unknown models must never
# inherit a Flash model's free status. Upstream explicit pricing takes priority.
_MODEL_PRICING = {row["id"]: row["free"] for row in ZHIPU_CHAT_CATALOG + ZHIPU_VISION_CATALOG}


def is_zhipu_official_base_url(base_url: str) -> bool:
    try:
        parsed = urlparse(base_url.strip())
        return (
            parsed.scheme == "https"
            and parsed.hostname == "open.bigmodel.cn"
            and parsed.port in (None, 443)
            and parsed.path.rstrip("/") == "/api/paas/v4"
            and not parsed.query and not parsed.fragment and not parsed.username
        )
    except (ValueError, AttributeError):
        return False


def zhipu_model_free(base_url: str, model: str) -> bool | None:
    if not is_zhipu_official_base_url(base_url):
        return None
    return _MODEL_PRICING.get(model.strip().lower())


def model_provider_presets() -> dict[str, Any]:
    # 历史入口：官方预设聚合函数最初只服务智谱，现按官方活动扩展七牛 AI 推理与书生·端砚。
    from .internai_catalog import internai_provider_preset
    from .qiniu_catalog import qiniu_provider_preset

    return {"presets": [{
        "key": "zhipu",
        "label": "智谱官方",
        "base_url": ZHIPU_BASE_URL,
        "api_key_url": "https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys",
        "pricing_url": ZHIPU_PRICING_URL,
        "pricing_verified_at": ZHIPU_PRICING_VERIFIED_AT,
        "chat_models": deepcopy(ZHIPU_CHAT_CATALOG),
        "vision_models": deepcopy(ZHIPU_VISION_CATALOG),
    }, qiniu_provider_preset(), internai_provider_preset()]}


def zhipu_can_disable_thinking(model: str) -> bool:
    # Fixed Thinking versions and GLM-5.3 cannot accept thinking.type=disabled.
    return model.strip().lower() in {
        "glm-4.7-flash", "glm-4.7", "glm-4.6v", "glm-4.6v-flash", "glm-4.6v-flashx",
    }


def zhipu_requires_thinking(model: str) -> bool:
    return model.strip().lower() in {
        "glm-5.3", "glm-5.3-flash", "glm-5.3-flashx", "glm-4.1v-thinking-flash",
    }
