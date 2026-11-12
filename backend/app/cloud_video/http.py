"""云端视频适配器共享的 HTTP 基础设施。

错误分级语义与 ``grs_client.GrsClient`` 对齐（连接未发出 / 提交结果不确定 / 临时错误），
统一抛 ``CloudVideoError`` 族异常，三个厂商适配器只关注各自的鉴权与请求体差异。
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import requests
from requests import exceptions as request_exceptions

from .base import (
    CloudVideoConnectionError,
    CloudVideoError,
    CloudVideoTemporaryError,
    CloudVideoUncertainSubmitError,
    with_cloud_video_billing_caution,
)

CONNECT_TIMEOUT_SECONDS = 12.0
READ_TIMEOUT_SECONDS = 60.0
SUBMIT_TIMEOUT = (CONNECT_TIMEOUT_SECONDS, 120.0)
POLL_TIMEOUT = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)
DOWNLOAD_TIMEOUT = (15.0, 300.0)
CONNECT_RETRIES = 1
CONNECT_RETRY_DELAY_SECONDS = 0.5


class CloudVideoHttpClient:
    """requests 会话封装：连接错误分级 + 临时错误识别 + JSON 解析。"""

    def __init__(
        self, base_url: str, *, session: requests.Session | None = None,
        provider_label: str = "云端视频服务",
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.session = session or requests.Session()
        self.provider_label = provider_label

    def label(self, action: str) -> str:
        return f"{self.provider_label}{action}"

    def _connect_error(self, url: str, reason: str) -> CloudVideoConnectionError:
        host = urlparse(url).hostname or self.base_url
        return CloudVideoConnectionError(
            f"无法连接{self.provider_label}（{host}）：{reason}。请求尚未发出，不会扣费。",
        )

    def request(
        self, method: str, url: str, *, action: str, timeout: float | tuple[float, float],
        uncertain_on_read: bool = False, **kwargs: Any,
    ) -> requests.Response:
        last_connect: BaseException | None = None
        for attempt in range(CONNECT_RETRIES + 1):
            try:
                return getattr(self.session, method)(url, timeout=timeout, **kwargs)
            except request_exceptions.ReadTimeout as error:
                if uncertain_on_read:
                    raise CloudVideoUncertainSubmitError(
                        with_cloud_video_billing_caution(f"{self.label(action)}已发出但等待响应超时"),
                    ) from error
                raise CloudVideoTemporaryError(f"{self.label(action)}读取超时") from error
            except (
                request_exceptions.ConnectTimeout,
                request_exceptions.SSLError,
                request_exceptions.ProxyError,
                request_exceptions.ConnectionError,
            ) as error:
                last_connect = error
                if attempt + 1 < CONNECT_RETRIES + 1:
                    time.sleep(CONNECT_RETRY_DELAY_SECONDS)
                    continue
                if isinstance(error, request_exceptions.SSLError):
                    reason = "TLS 握手失败"
                elif isinstance(error, request_exceptions.ConnectTimeout):
                    reason = "连接超时"
                else:
                    reason = "网络连接失败"
                raise self._connect_error(url, reason) from error
            except request_exceptions.RequestException as error:
                raise CloudVideoError(f"{self.label(action)}网络请求失败") from error
        raise self._connect_error(url, "网络连接失败") from last_connect  # pragma: no cover

    def parse_json(
        self, response: requests.Response, action: str, *, allow_client_error: bool = False,
    ) -> dict[str, Any]:
        if response.status_code >= 500 or response.status_code in {408, 425, 429}:
            raise CloudVideoTemporaryError(f"{self.label(action)}暂时不可用（HTTP {response.status_code}）")
        try:
            payload = response.json()
        except ValueError as error:
            if response.status_code >= 400:
                raise CloudVideoError(f"{self.label(action)}失败（HTTP {response.status_code}）") from error
            raise CloudVideoError(f"{self.label(action)}返回了无效 JSON") from error
        if not isinstance(payload, dict):
            raise CloudVideoError(f"{self.label(action)}返回格式无效")
        if response.status_code >= 400 and not allow_client_error:
            raise CloudVideoError(f"{self.label(action)}失败（HTTP {response.status_code}）")
        return payload
