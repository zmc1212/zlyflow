"""Official Qiniu AI Inference (七牛云 AI 大模型推理) preset and campaign pricing metadata.

The Conatus free model is a limited-time campaign (1024 程序员节): it only consumes
the account's daily free token quota and stops accepting calls entirely once the
campaign ends — it never converts to a paid model.  The public ``/v1/models``
catalog carries no pricing metadata, so the campaign window is the only source
for the 免费 badge shown in the provider settings pages.

Reference: https://www.qiniu.com/ai/free-models/conatus-2026 (checked 2026-11-01).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

QINIU_BASE_URL = "https://api.qnaigc.com/v1"
QINIU_CONATUS_MODEL = "qiniu/conatus-free"
QINIU_API_KEY_URL = "https://ai.qiniu.com/"
QINIU_PRICING_URL = "https://www.qiniu.com/ai/free-models/conatus-2026"
QINIU_PRICING_VERIFIED_AT = "2026-11-01"

# Beijing-time boundaries of the official free campaign (2026-10-24 00:00 through
# 2026-11-30 23:59). Outside the window the endpoint rejects the model, so the
# catalog must not keep advertising it as free.
_QINIU_TZ = timezone(timedelta(hours=8))
QINIU_CONATUS_FREE_START = datetime(2026, 10, 24, 0, 0, tzinfo=_QINIU_TZ)
QINIU_CONATUS_FREE_END = datetime(2026, 12, 1, 0, 0, tzinfo=_QINIU_TZ)

QINIU_CONATUS_CATALOG = [
    {"id": QINIU_CONATUS_MODEL, "label": "Conatus Free（限时免费）", "free": True},
]


def is_qiniu_official_base_url(base_url: str) -> bool:
    try:
        parsed = urlparse(str(base_url or "").strip())
        return (
            parsed.scheme == "https"
            and parsed.hostname == "api.qnaigc.com"
            and parsed.port in (None, 443)
            and parsed.path.rstrip("/") in ("", "/v1")
            and not parsed.query and not parsed.fragment and not parsed.username
        )
    except (ValueError, AttributeError):
        return False


def is_qiniu_conatus_model(base_url: str, model: str) -> bool:
    return is_qiniu_official_base_url(base_url) and str(model or "").strip().lower() == QINIU_CONATUS_MODEL


def qiniu_model_free(base_url: str, model: str, now: datetime | None = None) -> bool | None:
    """Campaign tariff hint, never proof of remaining quota; upstream metadata still wins."""
    if not is_qiniu_conatus_model(base_url, model):
        return None
    moment = now or datetime.now(_QINIU_TZ)
    if QINIU_CONATUS_FREE_START <= moment < QINIU_CONATUS_FREE_END:
        return True
    return None


def qiniu_provider_preset() -> dict[str, Any]:
    return {
        "key": "qiniu",
        "label": "七牛云 AI 推理",
        "base_url": QINIU_BASE_URL,
        "api_key_url": QINIU_API_KEY_URL,
        "pricing_url": QINIU_PRICING_URL,
        "pricing_verified_at": QINIU_PRICING_VERIFIED_AT,
        # Conatus 官方声明支持工具调用、深度思考、结构化输出与图像理解，
        # 因此同一个免费模型同时作为文本与视觉推荐项。
        "chat_models": deepcopy(QINIU_CONATUS_CATALOG),
        "vision_models": deepcopy(QINIU_CONATUS_CATALOG),
    }
