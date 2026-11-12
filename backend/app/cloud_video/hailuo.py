"""MiniMax 海螺 Hailuo 适配器。

- 鉴权：``Authorization: Bearer <Group API Key>``。
- 提交：POST /v1/video_generation（model / prompt / first_frame_image）；first_frame_image 接受裸 base64，
  海螺图生视频只支持首帧，不支持尾帧（注册表不登记尾帧槽位）。
- 轮询：GET /v1/query/video_generation?task_id=...，status ∈ Queueing/Processing/Success/Fail；
  Success 后需再 GET /v1/files/retrieve?file_id=...&purpose=video_download 取 download_url。
- 响应统一带 ``base_resp.status_code``（0 = 成功；1004 = 鉴权失败）。
- 测试连接：用不存在的任务 ID 探测——Key 无效返回鉴权错误码，Key 有效返回任务不存在类错误。
"""

from __future__ import annotations

import base64
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

PROVIDER_LABEL = "海螺视频服务"
BALANCE_PROBE_TIMEOUT = (12.0, 30.0)
HAILUO_AUTH_ERROR_CODES = {1004, 1008, 1013, 1015}


class HailuoClient:
    def __init__(self, base_url: str, api_key: str, *, session: requests.Session | None = None) -> None:
        self.http = CloudVideoHttpClient(base_url, session=session, provider_label=PROVIDER_LABEL)
        self.api_key = api_key

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _unwrap(self, payload: dict[str, Any], action: str) -> dict[str, Any]:
        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict):
            status_code = base_resp.get("status_code")
            if status_code not in (None, 0, "0"):
                message = str(base_resp.get("status_msg") or f"错误码 {status_code}")
                if int(status_code) in HAILUO_AUTH_ERROR_CODES:
                    message = f"API Key 无效或无权限：{message}"
                raise CloudVideoError(f"{self.http.label(action)}失败：{message}")
        return payload

    # ------------------------------------------------------------------
    # 提交
    # ------------------------------------------------------------------

    def submit(self, request: CloudVideoSubmitRequest) -> str:
        options = request.options or {}
        model = str(options.get("model") or request.model)
        body: dict[str, Any] = {"model": model, "prompt": request.prompt}
        if request.first_frame is not None:
            body["first_frame_image"] = _image_base64(request.first_frame)
        prompt_optimizer = options.get("prompt_optimizer")
        if prompt_optimizer is not None:
            body["prompt_optimizer"] = bool(prompt_optimizer)
        response = self.http.request(
            "post", f"{self.http.base_url}/v1/video_generation", action="提交", timeout=SUBMIT_TIMEOUT,
            uncertain_on_read=True, headers=self.headers, json=body,
        )
        payload = self.http.parse_json(response, "提交")
        payload = self._unwrap(payload, "提交")
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            raise CloudVideoError(f"{self.http.label('提交')}成功但未返回远端任务 ID")
        return task_id

    # ------------------------------------------------------------------
    # 轮询
    # ------------------------------------------------------------------

    def poll(self, remote_task_id: str) -> CloudTaskSnapshot:
        response = self.http.request(
            "get", f"{self.http.base_url}/v1/query/video_generation", action="查询", timeout=POLL_TIMEOUT,
            headers=self.headers, params={"task_id": remote_task_id},
        )
        payload = self.http.parse_json(response, "查询")
        payload = self._unwrap(payload, "查询")
        status = normalize_cloud_task_status(payload.get("status"))
        videos: list[str] = []
        if status == "completed":
            file_ref = payload.get("file")
            if isinstance(file_ref, dict) and file_ref.get("download_url"):
                videos.append(str(file_ref["download_url"]))
            else:
                file_id = str(payload.get("file_id") or "").strip()
                if file_id:
                    videos.append(self._retrieve_video_url(file_id))
        return CloudTaskSnapshot(
            status=status, video_urls=normalize_video_urls(videos),
            message=None, remote_status=str(payload.get("status") or ""),
        )

    def _retrieve_video_url(self, file_id: str) -> str:
        response = self.http.request(
            "get", f"{self.http.base_url}/v1/files/retrieve", action="获取成片地址", timeout=POLL_TIMEOUT,
            headers=self.headers, params={"file_id": file_id, "purpose": "video_download"},
        )
        payload = self.http.parse_json(response, "获取成片地址")
        payload = self._unwrap(payload, "获取成片地址")
        file_ref = payload.get("file")
        url = file_ref.get("download_url") if isinstance(file_ref, dict) else None
        if not url:
            raise CloudVideoError(f"{self.http.label('获取成片地址')}成功但未返回下载地址")
        return str(url)

    # ------------------------------------------------------------------
    # 测试连接（海螺无免费探活端点，用不存在任务 ID 区分鉴权结果）
    # ------------------------------------------------------------------

    def test_connection(self) -> str:
        response = self.http.request(
            "get", f"{self.http.base_url}/v1/query/video_generation", action="测试连接", timeout=BALANCE_PROBE_TIMEOUT,
            headers=self.headers, params={"task_id": "zly-probe-nonexistent-task"},
        )
        payload = self.http.parse_json(response, "测试连接", allow_client_error=True)
        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict):
            status_code = base_resp.get("status_code")
            if int(status_code or 0) in HAILUO_AUTH_ERROR_CODES:
                raise CloudVideoError(
                    f"API Key 无效或无权限：{base_resp.get('status_msg') or '鉴权失败'}",
                )
        return "连接成功，API Key 鉴权通过"

    def balance(self) -> float | None:
        # 海螺开放平台未提供稳定的余额查询端点，暂不展示余额。
        return None


def _image_base64(path: Path) -> str:
    """海螺 first_frame_image：裸 base64（去掉 data: 前缀）。"""
    content = Path(path).read_bytes()
    return base64.b64encode(content).decode("ascii")
