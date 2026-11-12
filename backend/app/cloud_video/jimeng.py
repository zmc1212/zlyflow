"""火山方舟（即梦 / Seedance）适配器。

- 鉴权：``Authorization: Bearer <Ark API Key>``（方舟 /api/v3 端点的主推鉴权方式，无需 AKSK V4 签名）。
- 提交：POST /api/v3/contents/generations/tasks；Seedance 的生成参数以命令后缀拼在 text 内容里
  （``--ratio`` / ``--duration`` / ``--resolution`` / ``--watermark``）。
- 首尾帧：content 数组中 ``{"type":"image_url","image_url":{"url":"data:..."},"role":"first_frame"/"last_frame"}``。
- 轮询：GET /api/v3/contents/generations/tasks/{id}，status ∈ queued/running/succeeded/failed/cancelled。
- 测试连接：用不存在的任务 ID 探测——鉴权失败返回 401，鉴权通过返回 404。
"""

from __future__ import annotations

from typing import Any

import requests

from .base import (
    CloudTaskSnapshot,
    CloudVideoError,
    CloudVideoSubmitRequest,
    image_data_uri,
    normalize_cloud_task_status,
    normalize_video_urls,
)
from .http import CloudVideoHttpClient, POLL_TIMEOUT, SUBMIT_TIMEOUT

PROVIDER_LABEL = "方舟视频服务"
SEEDANCE_RESOLUTIONS = {"480p", "720p", "1080p"}


class JimengClient:
    def __init__(self, base_url: str, api_key: str, *, session: requests.Session | None = None) -> None:
        self.http = CloudVideoHttpClient(base_url, session=session, provider_label=PROVIDER_LABEL)
        self.api_key = api_key

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # ------------------------------------------------------------------
    # 提交
    # ------------------------------------------------------------------

    @staticmethod
    def _seedance_command_suffix(options: dict[str, Any]) -> str:
        flags: list[str] = []
        ratio = str(options.get("aspect_ratio") or "").strip()
        if ratio:
            flags.append(f"--ratio {ratio}")
        duration = str(options.get("duration") or "").strip()
        if duration:
            flags.append(f"--duration {duration}")
        resolution = str(options.get("resolution") or "").strip().lower()
        if resolution in SEEDANCE_RESOLUTIONS:
            flags.append(f"--resolution {resolution}")
        watermark = options.get("watermark")
        if watermark is not None:
            flags.append(f"--watermark {'true' if watermark else 'false'}")
        return (" " + " ".join(flags)) if flags else ""

    def submit(self, request: CloudVideoSubmitRequest) -> str:
        options = request.options or {}
        model = str(options.get("model") or request.model)
        text = f"{request.prompt}{self._seedance_command_suffix(options)}"
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        if request.first_frame is not None:
            content.append(
                {"type": "image_url", "image_url": {"url": image_data_uri(request.first_frame)}, "role": "first_frame"},
            )
        if request.last_frame is not None:
            content.append(
                {"type": "image_url", "image_url": {"url": image_data_uri(request.last_frame)}, "role": "last_frame"},
            )
        body: dict[str, Any] = {"model": model, "content": content}
        response = self.http.request(
            "post", f"{self.http.base_url}/api/v3/contents/generations/tasks", action="提交",
            timeout=SUBMIT_TIMEOUT, uncertain_on_read=True, headers=self.headers, json=body,
        )
        payload = self.http.parse_json(response, "提交")
        task_id = str(payload.get("id") or "").strip()
        if not task_id:
            raise CloudVideoError(f"{self.http.label('提交')}成功但未返回远端任务 ID")
        return task_id

    # ------------------------------------------------------------------
    # 轮询
    # ------------------------------------------------------------------

    def poll(self, remote_task_id: str) -> CloudTaskSnapshot:
        response = self.http.request(
            "get", f"{self.http.base_url}/api/v3/contents/generations/tasks/{remote_task_id}",
            action="查询", timeout=POLL_TIMEOUT, headers=self.headers,
        )
        payload = self.http.parse_json(response, "查询")
        status = normalize_cloud_task_status(payload.get("status"))
        message = None
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip() or None
        videos: list[str] = []
        if status == "completed":
            content = payload.get("content")
            if isinstance(content, dict) and content.get("video_url"):
                videos.append(str(content["video_url"]))
        return CloudTaskSnapshot(
            status=status, video_urls=normalize_video_urls(videos), message=message,
            remote_status=str(payload.get("status") or ""),
        )

    # ------------------------------------------------------------------
    # 测试连接（方舟无免费探活端点，用不存在任务 ID 区分鉴权与不存在）
    # ------------------------------------------------------------------

    def test_connection(self) -> str:
        probe_id = "zly-probe-nonexistent-task"
        response = self.http.request(
            "get", f"{self.http.base_url}/api/v3/contents/generations/tasks/{probe_id}",
            action="测试连接", timeout=POLL_TIMEOUT, headers=self.headers,
        )
        if response.status_code in (401, 403):
            raise CloudVideoError(f"{self.http.label('测试连接')}失败：API Key 无效或无权限（HTTP {response.status_code}）")
        if response.status_code == 404:
            return "连接成功，API Key 鉴权通过"
        payload = self.http.parse_json(response, "测试连接", allow_client_error=True)
        error = payload.get("error")
        if isinstance(error, dict) and str(error.get("code") or "").lower() in {"authenticationerror", "unauthorized"}:
            raise CloudVideoError(f"{self.http.label('测试连接')}失败：{error.get('message') or 'API Key 无效'}")
        return "连接成功，API Key 鉴权通过"
