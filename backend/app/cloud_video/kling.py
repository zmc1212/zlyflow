"""可灵 Kling 开放平台适配器。

- 鉴权：AccessKey/SecretKey 手写 HS256 JWT（与官方 Python SDK 的 jwt 构造一致，避免引入 pyjwt 依赖）。
- 文生视频：POST /v1/videos/text2video；图生视频：POST /v1/videos/image2video（image + 可选 image_tail 尾帧）。
- 轮询：GET /v1/videos/{text2video|image2video}/{task_id}。可灵查询端点按任务类型分路由，
  因此 submit 返回的远端 ID 带 ``t2v:`` / ``i2v:`` 前缀，poll 内解析后还原查询路径。
- 参考图：image 字段接受不带 ``data:`` 前缀的裸 base64。
- 余额/测试连接：GET /v1/users/get_balance。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

import requests

from .base import (
    CloudTaskSnapshot,
    CloudVideoError,
    CloudVideoSubmitRequest,
    normalize_cloud_task_status,
    normalize_video_urls,
)
from .http import CloudVideoHttpClient, POLL_TIMEOUT, SUBMIT_TIMEOUT

PROVIDER_LABEL = "可灵视频服务"
JWT_EXPIRE_SECONDS = 1800
BALANCE_TIMEOUT = (12.0, 30.0)

# 提交体允许的取值（超范围由注册表 option_schema 先行约束）
KLING_MODES = {"std", "pro"}
KLING_DURATIONS = {"5", "10"}


def _b64url(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def kling_jwt(access_key: str, secret_key: str) -> str:
    """可灵开放平台鉴权 JWT：headers={"alg":"HS256","typ":"JWT"}, payload={"iss":AK,"exp","nbf"}。"""
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = _b64url(
        json.dumps({"iss": access_key, "exp": now + JWT_EXPIRE_SECONDS, "nbf": now - 5}, separators=(",", ":")).encode(
            "utf-8",
        ),
    )
    signing_input = header + b"." + payload
    signature = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return (signing_input + b"." + _b64url(signature)).decode("ascii")


def _image_base64(path: Path) -> str:
    """可灵 image 字段：裸 base64（去掉 data: 前缀）。"""
    content = Path(path).read_bytes()
    return base64.b64encode(content).decode("ascii")


class KlingClient:
    def __init__(
        self, base_url: str, access_key: str, secret_key: str, *, session: requests.Session | None = None,
    ) -> None:
        self.http = CloudVideoHttpClient(base_url, session=session, provider_label=PROVIDER_LABEL)
        self.access_key = access_key
        self.secret_key = secret_key

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {kling_jwt(self.access_key, self.secret_key)}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # 响应解包：可灵统一 code/message 信封
    # ------------------------------------------------------------------

    def _unwrap(self, payload: dict[str, Any], action: str) -> dict[str, Any]:
        code = payload.get("code")
        if code not in (None, 0, "0"):
            message = str(payload.get("message") or payload.get("msg") or f"HTTP 错误 {code}")
            raise CloudVideoError(f"{self.http.label(action)}失败：{message}")
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # 提交
    # ------------------------------------------------------------------

    def submit(self, request: CloudVideoSubmitRequest) -> str:
        options = request.options or {}
        model = str(options.get("model") or request.model)
        mode = str(options.get("kling_mode") or "std")
        duration = str(options.get("duration") or "5")
        task_type = "i2v" if request.first_frame is not None else "t2v"
        body: dict[str, Any] = {
            "model_name": model,
            "prompt": request.prompt,
            "mode": mode if mode in KLING_MODES else "std",
            "duration": duration if duration in KLING_DURATIONS else "5",
        }
        negative = str(request.negative_prompt or "").strip()
        if negative:
            body["negative_prompt"] = negative
        aspect_ratio = str(options.get("aspect_ratio") or "").strip()
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        cfg_scale = options.get("cfg_scale")
        if cfg_scale is not None:
            try:
                body["cfg_scale"] = float(cfg_scale)
            except (TypeError, ValueError):
                pass
        if task_type == "i2v":
            body["image"] = _image_base64(request.first_frame)
            if request.last_frame is not None:
                body["image_tail"] = _image_base64(request.last_frame)
        endpoint = "image2video" if task_type == "i2v" else "text2video"
        response = self.http.request(
            "post", f"{self.http.base_url}/v1/videos/{endpoint}", action="提交", timeout=SUBMIT_TIMEOUT,
            uncertain_on_read=True, headers=self.headers, json=body,
        )
        payload = self.http.parse_json(response, "提交")
        data = self._unwrap(payload, "提交")
        task_id = str(data.get("task_id") or "").strip()
        if not task_id:
            raise CloudVideoError(f"{self.http.label('提交')}成功但未返回远端任务 ID")
        return f"{task_type}:{task_id}"

    # ------------------------------------------------------------------
    # 轮询
    # ------------------------------------------------------------------

    def poll(self, remote_task_id: str) -> CloudTaskSnapshot:
        task_type, _, task_id = str(remote_task_id).partition(":")
        if task_id and task_type not in ("t2v", "i2v"):
            task_id, task_type = str(remote_task_id), ""
        endpoint = "image2video" if task_type == "i2v" else "text2video"
        response = self.http.request(
            "get", f"{self.http.base_url}/v1/videos/{endpoint}/{task_id}", action="查询", timeout=POLL_TIMEOUT,
            headers=self.headers,
        )
        payload = self.http.parse_json(response, "查询")
        data = self._unwrap(payload, "查询")
        status = normalize_cloud_task_status(data.get("task_status"))
        message = str(data.get("task_status_msg") or "").strip() or None
        videos: list[str] = []
        if status == "completed":
            result = data.get("task_result")
            if isinstance(result, dict):
                for video in result.get("videos") or []:
                    if isinstance(video, dict) and video.get("url"):
                        videos.append(str(video["url"]))
        return CloudTaskSnapshot(
            status=status, video_urls=normalize_video_urls(videos), message=message,
            remote_status=str(data.get("task_status") or ""),
        )

    # ------------------------------------------------------------------
    # 余额与测试连接
    # ------------------------------------------------------------------

    def balance(self) -> float:
        response = self.http.request(
            "get", f"{self.http.base_url}/v1/users/get_balance", action="余额查询", timeout=BALANCE_TIMEOUT,
            headers=self.headers,
        )
        payload = self.http.parse_json(response, "余额查询")
        data = self._unwrap(payload, "余额查询")
        try:
            return float(data.get("balance"))
        except (TypeError, ValueError) as error:
            raise CloudVideoError(f"{self.http.label('余额查询')}返回了无效余额") from error

    def test_connection(self) -> str:
        balance = self.balance()
        return f"连接成功，账户余额 {balance:.2f}"
