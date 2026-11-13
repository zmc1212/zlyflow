"""云端视频模型供应商适配层（可灵 Kling / 火山方舟 Seedance / MiniMax 海螺 / 超算互联网 SCNet）。

对外入口：``build_adapter`` 按厂商构造已配置的客户端实例；
连接配置读取与凭据解密在 ``cloud_video_service.CloudVideoService`` 完成。
"""

from __future__ import annotations

import requests

from .base import (
    CLOUD_VIDEO_BILLING_CAUTION,
    CLOUD_VIDEO_PROVIDER_ORDER,
    CLOUD_VIDEO_PROVIDERS,
    CloudTaskSnapshot,
    CloudVideoAdapter,
    CloudVideoConnectionError,
    CloudVideoError,
    CloudVideoProviderSpec,
    CloudVideoSubmitRequest,
    CloudVideoTemporaryError,
    CloudVideoUncertainSubmitError,
    cloud_video_provider_defaults,
    cloud_video_provider_keys,
    cloud_video_provider_spec,
    image_data_uri,
    normalize_cloud_task_status,
    normalize_video_urls,
    with_cloud_video_billing_caution,
)
from .hailuo import HailuoClient
from .http import CloudVideoHttpClient
from .jimeng import JimengClient
from .kling import KlingClient
from .scnet import ScnetClient


def build_adapter(
    provider_key: str,
    *,
    base_url: str | None,
    api_key: str,
    api_secret: str | None = None,
    session: requests.Session | None = None,
):
    """按厂商构造适配器实例；base_url 留空时使用厂商官方默认地址。"""
    spec = cloud_video_provider_spec(provider_key)
    effective_base = str(base_url or "").strip() or spec.default_base_url
    if spec.key == "kling":
        return KlingClient(effective_base, api_key, api_secret or "", session=session)
    if spec.key == "jimeng":
        return JimengClient(effective_base, api_key, session=session)
    if spec.key == "hailuo":
        return HailuoClient(effective_base, api_key, session=session)
    if spec.key == "scnet":
        return ScnetClient(effective_base, api_key, session=session)
    raise CloudVideoError(f"未知的云端视频供应商: {provider_key}")  # pragma: no cover


__all__ = [
    "CLOUD_VIDEO_BILLING_CAUTION",
    "CLOUD_VIDEO_PROVIDER_ORDER",
    "CLOUD_VIDEO_PROVIDERS",
    "CloudTaskSnapshot",
    "CloudVideoAdapter",
    "CloudVideoConnectionError",
    "CloudVideoError",
    "CloudVideoHttpClient",
    "CloudVideoProviderSpec",
    "CloudVideoSubmitRequest",
    "CloudVideoTemporaryError",
    "CloudVideoUncertainSubmitError",
    "HailuoClient",
    "JimengClient",
    "KlingClient",
    "ScnetClient",
    "build_adapter",
    "cloud_video_provider_defaults",
    "cloud_video_provider_keys",
    "cloud_video_provider_spec",
    "image_data_uri",
    "normalize_cloud_task_status",
    "normalize_video_urls",
    "with_cloud_video_billing_caution",
]
