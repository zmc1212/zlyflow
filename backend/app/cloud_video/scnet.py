"""超算互联网（SCNet）模型服务视频适配器。

- 网关：``https://api.scnet.cn/api/llm``，``Authorization: Bearer <API Key>``；视频任务是异步任务，
  提交时必须带 ``X-MultiModal-Async: true``。
- 提交：POST /v1/videos/generations，body 为 ``{model, input{prompt, media[]}, parameters{}}``；
  MiniMax-H3 / Seedance 通过 ``media[].type`` 区分 ``first_frame`` / ``last_frame`` / ``reference_image``。
  本地图片当前按 Base64 data URI 内联，先不改造参考图存储链路。
- 轮询：GET /v1/tasks/{task_id}；状态 pending / running / succeeded / failed / cancelled，
  成片地址在 ``output.results``（字符串数组）。
- 测试连接：GET /v1/models（模型列表），同时回报账号可用列表里是否包含三个视频模型。

三个模型共用同一套提交/查询端点，差异只在 model 名与 parameters 字段：
- ``MiniMax-H3``：resolution 768P/2K，duration 4-15，文生视频 ratio 必填；
- ``Seedance2.5`` / ``Seedance2.0``：resolution 480p/720p/1080p，duration 4-15，可选 generate_audio / seed；
  官方示例还会带 ``output_format: mp4``，本次一并固定下发。
- ``HappyHorse-1.0-T2V``：仅文生视频，resolution 720p/1080p，duration 3-15，可选 seed。
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

PROVIDER_LABEL = "超算互联网视频服务"
VIDEO_MODEL_IDS = ("MiniMax-H3", "Seedance2.5", "Seedance2.0", "HappyHorse-1.0-T2V")


def _as_int(value: Any) -> int | None:
    """把注册表 options 里的数字/数字字符串（含 '5.0'）转成 int；空值与非法值返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


class ScnetClient:
    def __init__(self, base_url: str, api_key: str, *, session: requests.Session | None = None) -> None:
        self.http = CloudVideoHttpClient(base_url, session=session, provider_label=PROVIDER_LABEL)
        self.api_key = api_key

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # 视频生成是异步任务，平台要求必须显式声明，否则不会返回 task_id。
            "X-MultiModal-Async": "true",
        }

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    # ------------------------------------------------------------------
    # 请求体
    # ------------------------------------------------------------------

    def _input_payload(self, request: CloudVideoSubmitRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {"prompt": request.prompt}
        media: list[dict[str, str]] = []
        if request.first_frame is not None:
            media.append({"type": "first_frame", "url": image_data_uri(request.first_frame)})
        if request.last_frame is not None:
            media.append({"type": "last_frame", "url": image_data_uri(request.last_frame)})
        for reference in request.references or []:
            media.append({"type": "reference_image", "url": image_data_uri(reference)})
        if media:
            payload["media"] = media
        return payload

    @staticmethod
    def _parameters_payload(options: dict[str, Any], model: str = "") -> dict[str, Any]:
        parameters: dict[str, Any] = {}
        ratio = str(options.get("aspect_ratio") or "").strip()
        if ratio:
            parameters["ratio"] = ratio
        duration = _as_int(options.get("duration"))
        if duration is not None:
            parameters["duration"] = duration
        resolution = str(options.get("resolution") or "").strip()
        if resolution:
            parameters["resolution"] = resolution
        if "generate_audio" in options:
            parameters["generate_audio"] = bool(options.get("generate_audio"))
        seed = _as_int(options.get("seed"))
        if seed is not None:
            parameters["seed"] = seed
        # 官方 Seedance2.5 示例带 output_format=mp4；只对 Seedance 下发，避免影响 H3/HappyHorse。
        if str(model or options.get("model") or "").strip().lower().startswith("seedance"):
            parameters["output_format"] = "mp4"
        # 三个模型都支持 watermark；统一不加 AIGC 水印（HappyHorse 默认 true，必须显式关闭）。
        parameters["watermark"] = bool(options.get("watermark", False))
        return parameters

    @staticmethod
    def _error_message(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("msg")
            if message:
                return str(message).strip() or None
        elif isinstance(error, str) and error.strip():
            return error.strip()
        for key in ("error_message", "message", "msg"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        output = payload.get("output")
        if isinstance(output, dict):
            value = output.get("error_message")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    # ------------------------------------------------------------------
    # 提交 / 轮询
    # ------------------------------------------------------------------

    def submit(self, request: CloudVideoSubmitRequest) -> str:
        options = dict(request.options or {})
        model = str(options.get("model") or request.model or "").strip()
        if not model:
            raise CloudVideoError(f"{self.http.label('提交')}失败：未配置模型名")
        body = {
            "model": model,
            "input": self._input_payload(request),
            "parameters": self._parameters_payload(options, model),
        }
        response = self.http.request(
            "post", f"{self.http.base_url}/v1/videos/generations", action="提交",
            timeout=SUBMIT_TIMEOUT, uncertain_on_read=True, headers=self.headers, json=body,
        )
        payload = self.http.parse_json(response, "提交", allow_client_error=True)
        if response.status_code >= 400:
            detail = self._error_message(payload) or "请检查模型名、参数与账户额度"
            raise CloudVideoError(f"{self.http.label('提交')}失败（HTTP {response.status_code}）：{detail}")
        output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
        task_id = str(output.get("task_id") or payload.get("task_id") or "").strip()
        if not task_id:
            raise CloudVideoError(
                self._error_message(payload) or f"{self.http.label('提交')}成功但未返回远端任务 ID",
            )
        return task_id

    def poll(self, remote_task_id: str) -> CloudTaskSnapshot:
        response = self.http.request(
            "get", f"{self.http.base_url}/v1/tasks/{remote_task_id}",
            action="查询", timeout=POLL_TIMEOUT, headers=self.headers,
        )
        payload = self.http.parse_json(response, "查询")
        output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
        raw_status = str(output.get("task_status") or payload.get("task_status") or "")
        status = normalize_cloud_task_status(raw_status)
        videos: list[str] = []
        if status == "completed":
            results = output.get("results")
            for item in results if isinstance(results, list) else []:
                if isinstance(item, str) and item.strip():
                    videos.append(item.strip())
                elif isinstance(item, dict):
                    url = str(item.get("url") or item.get("video_url") or "").strip()
                    if url:
                        videos.append(url)
        message = str(output.get("error_message") or "").strip() or self._error_message(payload) or None
        return CloudTaskSnapshot(
            status=status,
            video_urls=normalize_video_urls(videos),
            message=message,
            remote_status=raw_status,
        )

    # ------------------------------------------------------------------
    # 测试连接（模型列表是免费只读端点，可直接验证 Key 与模型开通情况）
    # ------------------------------------------------------------------

    def test_connection(self) -> str:
        response = self.http.request(
            "get", f"{self.http.base_url}/v1/models", action="测试连接",
            timeout=POLL_TIMEOUT, headers=self.auth_headers,
        )
        if response.status_code in (401, 403):
            raise CloudVideoError(
                f"{self.http.label('测试连接')}失败：API Key 无效或无权限（HTTP {response.status_code}）",
            )
        payload = self.http.parse_json(response, "测试连接", allow_client_error=True)
        if response.status_code >= 400:
            detail = self._error_message(payload) or "请检查 API Key 与服务地址"
            raise CloudVideoError(f"{self.http.label('测试连接')}失败（HTTP {response.status_code}）：{detail}")
        data = payload.get("data")
        if not isinstance(data, list):
            raise CloudVideoError(f"{self.http.label('测试连接')}返回格式无效：缺少模型列表")
        available = {
            str(item.get("id") or "").strip()
            for item in data
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        lowered = {item.lower() for item in available}
        seedance_versions = sorted(item for item in available if item.lower().startswith("seedance"))
        families = {
            "MiniMax-H3": any(item.startswith("minimax-h3") for item in lowered),
            "Seedance": bool(seedance_versions),
            "HappyHorse": any(item.startswith("happyhorse") for item in lowered),
        }
        missing = [name for name, present in families.items() if not present]
        available_parts: list[str] = []
        if families["MiniMax-H3"]:
            available_parts.append("MiniMax-H3")
        if seedance_versions:
            available_parts.append(f"Seedance（{'/'.join(seedance_versions)}）")
        if families["HappyHorse"]:
            available_parts.append("HappyHorse")
        summary = "、".join(available_parts) or "无"
        if missing:
            return (
                "连接成功，API Key 鉴权通过；当前 Key 未见："
                f"{'、'.join(missing)}（请确认账号已开通）。可用视频模型：{summary}"
            )
        return f"连接成功，API Key 鉴权通过；可用视频模型：{summary}"

    def balance(self) -> float | None:
        return None


__all__ = ["PROVIDER_LABEL", "VIDEO_MODEL_IDS", "ScnetClient"]
