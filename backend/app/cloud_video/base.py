"""云端视频模型供应商适配层。

统一可灵 Kling、火山方舟（即梦/Seedance）、MiniMax 海螺、超算互联网（SCNet）四家官方 API 的差异：
- 各厂商 adapter（kling.py / jimeng.py / hailuo.py / scnet.py）实现统一的 ``CloudVideoAdapter`` 协议；
- 异常分级对齐 ``grs_client``：连接未发出（可安全重试）/ 提交结果不确定（禁止自动重试，
  必须带扣费警示文案）/ 临时错误（轮询时退避重试）；
- 远端任务状态统一归一为 ``active`` / ``completed`` / ``failed``；
- 参考图片统一以 data URI（base64）随请求提交（与 GRS 图片服务一致）。

连接配置（enabled/base_url/密钥）存 ``cloud_video_provider_settings`` 多行表，
每厂商一行；具体模型条目由 ``workflow_registry`` 静态登记（cloud_provider + cloud_model）。
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..grs_client import GrsClient, GrsError

CLOUD_VIDEO_BILLING_CAUTION = "云端视频模型按次计费，为避免重复扣费，请确认远端任务状态后显式重试。"

# 各厂商上传参考图/下载成片的最大字节数
CLOUD_VIDEO_MAX_IMAGE_BYTES = 50 * 1024 * 1024
CLOUD_VIDEO_MAX_VIDEO_BYTES = 1024 * 1024 * 1024


class CloudVideoError(RuntimeError):
    """云端视频服务错误（终态，直接把任务置失败）。"""


class CloudVideoTemporaryError(CloudVideoError):
    """临时性错误（429/5xx 等），轮询时可退避重试。"""


class CloudVideoConnectionError(CloudVideoTemporaryError):
    """TCP/TLS 未完成，请求肯定没有发出，可以安全重试提交。"""


class CloudVideoUncertainSubmitError(CloudVideoError):
    """提交请求可能已到达厂商（读超时等），禁止自动重试；调用方必须提示扣费风险。"""


def with_cloud_video_billing_caution(message: str) -> str:
    text = (message or "").strip() or "云端视频服务提交失败"
    if CLOUD_VIDEO_BILLING_CAUTION in text:
        return text
    return f"{text}；{CLOUD_VIDEO_BILLING_CAUTION}"


# --------------------------------------------------------------------------
# 远端任务状态归一
# --------------------------------------------------------------------------

_ACTIVE_STATUSES = {
    "active", "submitted", "queued", "queue", "queuing", "pending", "processing",
    "running", "generating", "in_progress", "inprogress", "working", "not_start",
    "not_started", "converting", "checking", "unknown",
}
_COMPLETED_STATUSES = {"completed", "complete", "succeed", "succeeded", "success", "done", "finished", "ok"}
_FAILED_STATUSES = {
    "failed", "failure", "error", "violation", "cancelled", "canceled", "timeout",
    "expired", "rejected", "not_found",
}


def normalize_cloud_task_status(raw: Any) -> str:
    """把各厂商的任务状态字符串归一为 active / completed / failed。

    未知状态按 active 处理（继续轮询，由超时兜底），与 GRS result 缺省 processing 的策略一致。
    """
    text = str(raw or "").strip().lower()
    if not text:
        return "active"
    if text in _COMPLETED_STATUSES:
        return "completed"
    if text in _FAILED_STATUSES:
        return "failed"
    return "active"


@dataclass
class CloudTaskSnapshot:
    """一次轮询得到的远端任务状态快照。"""

    status: str  # active / completed / failed
    progress: int = 0  # 0-100，厂商不提供时为 0
    video_urls: list[str] = field(default_factory=list)
    message: str | None = None
    remote_status: str = ""  # 厂商原始状态串，落 remote_status 列便于排障


# --------------------------------------------------------------------------
# 供应商注册表（连接信息与能力声明；模型条目在 workflow_registry 登记）
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CloudVideoProviderSpec:
    key: str
    label: str
    default_base_url: str
    requires_secret: bool = False  # True = AccessKey + SecretKey 双密钥；False = 单 API Key
    api_key_label: str = "API Key"
    api_secret_label: str = "Secret Key"
    base_url_hint: str = ""
    supports_balance: bool = False  # 是否有账户余额查询接口


CLOUD_VIDEO_PROVIDERS: dict[str, CloudVideoProviderSpec] = {
    spec.key: spec
    for spec in (
        CloudVideoProviderSpec(
            key="kling",
            label="可灵 Kling",
            default_base_url="https://api.klingai.com",
            requires_secret=True,
            api_key_label="AccessKey（AK）",
            api_secret_label="SecretKey（SK）",
            base_url_hint="国内站 https://api.klingai.com，国际站 https://api-singapore.klingai.com",
            supports_balance=True,
        ),
        CloudVideoProviderSpec(
            key="jimeng",
            label="即梦 / Seedance（火山方舟）",
            default_base_url="https://ark.cn-beijing.volces.com",
            requires_secret=False,
            api_key_label="Ark API Key",
            base_url_hint="默认华北2（北京）；其他区域请改为对应 ark.<region>.volces.com 地址",
        ),
        CloudVideoProviderSpec(
            key="hailuo",
            label="海螺 Hailuo（MiniMax）",
            default_base_url="https://api.minimaxi.com",
            requires_secret=False,
            api_key_label="Group API Key",
            base_url_hint="国内平台 https://api.minimaxi.com，国际平台 https://api.minimax.io",
            supports_balance=True,
        ),
        CloudVideoProviderSpec(
            key="scnet",
            label="超算互联网（SCNet）",
            default_base_url="https://api.scnet.cn/api/llm",
            requires_secret=False,
            api_key_label="SCNet API Key",
            base_url_hint=(
                "默认 api.scnet.cn 模型服务网关；API Key 在超算互联网控制台「模型服务 → API Key 管理」创建，"
                "需账号已开通 MiniMax-H3 / Seedance / HappyHorse 视频模型"
            ),
        ),
    )
}

CLOUD_VIDEO_PROVIDER_ORDER: tuple[str, ...] = ("kling", "jimeng", "hailuo", "scnet")


def cloud_video_provider_keys() -> tuple[str, ...]:
    return CLOUD_VIDEO_PROVIDER_ORDER


def cloud_video_provider_spec(provider_key: str) -> CloudVideoProviderSpec:
    spec = CLOUD_VIDEO_PROVIDERS.get(str(provider_key or "").strip())
    if spec is None:
        raise CloudVideoError(f"未知的云端视频供应商: {provider_key}")
    return spec


def cloud_video_provider_defaults(provider_key: str) -> dict[str, Any]:
    """storage.get_cloud_video_settings 的默认行（行缺失时补齐用）。"""
    spec = cloud_video_provider_spec(provider_key)
    return {
        "provider_key": spec.key,
        "enabled": 0,
        "base_url": None,  # None = 使用 spec.default_base_url
        "api_key_encrypted": None,
        "api_secret_encrypted": None,
        "extra_config_json": None,
        "last_test_status": None,
        "last_test_message": None,
        "last_test_at": None,
        "updated_at": "",
    }


# --------------------------------------------------------------------------
# 参考素材与统一协议
# --------------------------------------------------------------------------


def image_data_uri(path: Path) -> str:
    """本地参考图片 → data URI（复用 GRS 的色彩归一化与 50MB 防护）。"""
    try:
        return GrsClient.data_uri(Path(path))
    except GrsError as error:
        raise CloudVideoError(str(error)) from error


def normalize_video_urls(raw_urls: list[str]) -> list[str]:
    return [str(url) for url in dict.fromkeys(url for url in raw_urls if url)]


class CloudVideoSubmitRequest:
    """一次云端视频生成提交所需的全部输入（由调用方按注册表参数解析好）。"""

    def __init__(
        self,
        *,
        model: str,
        prompt: str,
        negative_prompt: str | None = None,
        first_frame: Path | None = None,
        last_frame: Path | None = None,
        references: list[Path] | None = None,
        options: dict[str, Any] | None = None,
        client_ref: str | None = None,
    ) -> None:
        self.model = model
        self.prompt = prompt
        self.negative_prompt = negative_prompt
        self.first_frame = first_frame
        self.last_frame = last_frame
        self.references = list(references or [])
        self.options = dict(options or {})
        self.client_ref = client_ref


class CloudVideoAdapter(Protocol):
    """厂商适配器协议（kling/jimeng/hailuo 各自实现）。"""

    def submit(self, request: CloudVideoSubmitRequest) -> str:
        """提交生成任务，返回远端任务 ID；读超时抛 CloudVideoUncertainSubmitError。"""
        ...

    def poll(self, remote_task_id: str) -> CloudTaskSnapshot:
        """查询远端任务状态（不重试终态之外的网络抖动由调用方退避处理）。"""
        ...

    def test_connection(self) -> str:
        """连通性与鉴权自检，返回描述性消息；失败抛 CloudVideoError。"""
        ...

    def balance(self) -> float | None:
        """账户余额（厂商无该接口时返回 None）。"""
        ...


def monotonic_deadline(timeout_seconds: float) -> float:
    return time.monotonic() + timeout_seconds


__all__ = [
    "CLOUD_VIDEO_BILLING_CAUTION",
    "CLOUD_VIDEO_MAX_IMAGE_BYTES",
    "CLOUD_VIDEO_MAX_VIDEO_BYTES",
    "CLOUD_VIDEO_PROVIDER_ORDER",
    "CLOUD_VIDEO_PROVIDERS",
    "CloudTaskSnapshot",
    "CloudVideoAdapter",
    "CloudVideoConnectionError",
    "CloudVideoError",
    "CloudVideoProviderSpec",
    "CloudVideoSubmitRequest",
    "CloudVideoTemporaryError",
    "CloudVideoUncertainSubmitError",
    "cloud_video_provider_defaults",
    "cloud_video_provider_keys",
    "cloud_video_provider_spec",
    "image_data_uri",
    "monotonic_deadline",
    "normalize_cloud_task_status",
    "normalize_video_urls",
    "with_cloud_video_billing_caution",
]
