"""MiniMax 官方平台视频适配器（platform.minimax.cn / api.minimax.cn，H3 系列）。

- 鉴权：``Authorization: Bearer <API Key>``（控制台 platform.minimax.cn「接口密钥」签发）。
- 提交：POST /v2/video_generation，body 为多模态 ``content[]``：必填 ``{"type":"text","text":prompt}``，
  图片走 ``{"type":"image_url","image_url":{"url":dataURI},"role":...}``；首帧单独提供即图生视频，
  尾帧必须与首帧成对，首尾帧与参考图（≤9 张）角色互斥；``resolution`` ∈ 480P/768P/2K（2K 仅 MiniMax-H3）、
  ``duration`` 4-15 秒（H3-Max 起步 5 秒）；文生视频 ``ratio`` 必填且非 adaptive，图生视频宽高比恒随输入（adaptive）
  不下发，多模态参考生成必须显式下发具体 ``ratio``（官方 Lite/Highspeed/Max 档不支持 adaptive）；
  ``generate_audio`` 默认 True（工作台默认带声音，可在「更多设置」关闭），``aigc_watermark`` 固定 False。
- 轮询：GET /v2/query/video_generation/{task_id}，task.status ∈ queued/running/succeeded/failed/cancelled；
  成功直接返回 ``task.content.url`` 限时直链（无需 file_id 二次换取），失败取 ``task.error`` 文案。
- 错误响应为 OpenAI 风格 ``{error:{type,message,http_code},request_id}``。
- 测试连接：用不存在的任务 ID 探活——Key 无效返回 401 类鉴权错误，Key 有效返回任务不存在类错误。
- 官方无余额查询端点，``balance`` 返回 None。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

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

PROVIDER_LABEL = "MiniMax官方视频"
PROBE_TIMEOUT = (12.0, 30.0)
MINIMAX_H3_MODELS = ("MiniMax-H3-Lite", "MiniMax-H3-Highspeed", "MiniMax-H3", "MiniMax-H3-Max")
MINIMAX_H3_MODEL_DEFAULT = "MiniMax-H3-Lite"
MINIMAX_H3_RESOLUTIONS = ("480P", "768P", "2K")
MINIMAX_H3_MIN_DURATION = 4
MINIMAX_H3_MAX_DURATION = 15
MINIMAX_H3_MAX_REFERENCES = 9
MINIMAX_H3_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
MINIMAX_AUTH_ERROR_CODES = {401, 403}


class MiniMaxClient:
    def __init__(self, base_url: str, api_key: str, *, session: requests.Session | None = None) -> None:
        self.http = CloudVideoHttpClient(base_url, session=session, provider_label=PROVIDER_LABEL)
        self.api_key = api_key

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # ------------------------------------------------------------------
    # 提交
    # ------------------------------------------------------------------

    def submit(self, request: CloudVideoSubmitRequest) -> str:
        options = request.options or {}
        model = str(options.get("model") or request.model or MINIMAX_H3_MODEL_DEFAULT).strip()
        if model not in MINIMAX_H3_MODELS:
            raise CloudVideoError(f"MiniMax 官方视频模型必须是 {'/'.join(MINIMAX_H3_MODELS)} 之一")
        resolution = str(options.get("resolution") or "").strip().upper()
        if resolution not in MINIMAX_H3_RESOLUTIONS:
            raise CloudVideoError(f"MiniMax 官方视频分辨率必须是 {'/'.join(MINIMAX_H3_RESOLUTIONS)} 之一")
        if resolution == "2K" and model != "MiniMax-H3":
            raise CloudVideoError("2K 分辨率仅 MiniMax-H3 旗舰档支持，请改用 480P/768P")
        if resolution == "480P" and model == "MiniMax-H3":
            # 官方价目表 H3 旗舰档只有 768P / 2K，480P 仅 Lite / Highspeed / H3-Max。
            raise CloudVideoError("480P 仅 MiniMax-H3-Lite / Highspeed / H3-Max 支持，H3 旗舰档请改用 768P 或 2K")
        minimum_duration = 5 if model == "MiniMax-H3-Max" else MINIMAX_H3_MIN_DURATION
        duration = _as_int(options.get("duration"))
        if duration is None or not minimum_duration <= duration <= MINIMAX_H3_MAX_DURATION:
            raise CloudVideoError(f"MiniMax 官方视频时长必须是 {minimum_duration}-{MINIMAX_H3_MAX_DURATION} 秒")

        prompt = str(request.prompt or "").strip()
        if not prompt:
            raise CloudVideoError("提示词不能为空：官方平台要求每次请求必含非空 text")
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

        if request.last_frame is not None and request.first_frame is None:
            raise CloudVideoError("首尾帧必须成对提供：官方平台要求尾帧与首帧成对")
        if request.first_frame is not None and request.references:
            raise CloudVideoError("首尾帧与参考图互斥，不能同时提供")
        if request.first_frame is not None:
            content.append(_image_item(request.first_frame, "first_frame"))
            if request.last_frame is not None:
                content.append(_image_item(request.last_frame, "last_frame"))
        elif request.references:
            if len(request.references) > MINIMAX_H3_MAX_REFERENCES:
                raise CloudVideoError(f"MiniMax 参考图最多 {MINIMAX_H3_MAX_REFERENCES} 张")
            for path in request.references:
                content.append(_image_item(path, "reference_image"))

        body: dict[str, Any] = {
            "model": model,
            "content": content,
            "resolution": resolution,
            "duration": duration,
            "generate_audio": bool(options.get("generate_audio", True)),
            "aigc_watermark": False,
        }
        ratio = str(options.get("aspect_ratio") or "").strip()
        uses_references = bool(request.references) and request.first_frame is None
        if ratio:
            if ratio not in MINIMAX_H3_RATIOS:
                raise CloudVideoError(f"MiniMax 官方视频画幅只支持 {'/'.join(MINIMAX_H3_RATIOS)}")
            body["ratio"] = ratio
        elif uses_references:
            # 官方 reference v2 文档：r2va 的 ratio 名义上默认 adaptive，但 Lite/Highspeed/Max 档不支持
            # adaptive，必须显式下发具体比例，否则上游返回 2013「参考生场景必须显式指定 ratio」。
            raise CloudVideoError("MiniMax 官方参考图生视频必须显式指定画幅：官方非旗舰档不支持 adaptive 画幅")

        response = self.http.request(
            "post", f"{self.http.base_url}/v2/video_generation", action="提交", timeout=SUBMIT_TIMEOUT,
            uncertain_on_read=True, headers=self.headers, json=body,
        )
        # 官方对鉴权/余额/参数拒绝以 4xx 返回 OpenAI 风格 {error:{...}}，需读取错误详情而非统一报错。
        payload = self.http.parse_json(response, "提交", allow_client_error=True)
        self._raise_for_error(payload, "提交")
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            raise CloudVideoError(f"{self.http.label('提交')}成功但未返回远端任务 ID")
        return task_id

    # ------------------------------------------------------------------
    # 轮询
    # ------------------------------------------------------------------

    def poll(self, remote_task_id: str) -> CloudTaskSnapshot:
        response = self.http.request(
            "get", f"{self.http.base_url}/v2/query/video_generation/{quote(remote_task_id, safe='')}",
            action="查询", timeout=POLL_TIMEOUT, headers=self.headers,
        )
        payload = self.http.parse_json(response, "查询", allow_client_error=True)
        self._raise_for_error(payload, "查询")
        task = payload.get("task") if isinstance(payload.get("task"), dict) else payload
        status = normalize_cloud_task_status(task.get("status"))
        message: str | None = None
        if status == "failed":
            error = task.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "").strip() or f"官方任务错误码 {error.get('code') or '未知'}"
            else:
                message = "官方任务失败"
        videos: list[str] = []
        if status == "completed":
            content_ref = task.get("content")
            url = content_ref.get("url") if isinstance(content_ref, dict) else None
            if not url:
                raise CloudVideoError(f"{self.http.label('查询')}完成但未返回成片地址")
            videos.append(str(url))
        return CloudTaskSnapshot(
            status=status,
            progress=12 if status == "active" else (100 if status == "completed" else 0),
            video_urls=normalize_video_urls(videos),
            message=message,
            remote_status=str(task.get("status") or ""),
        )

    # ------------------------------------------------------------------
    # 测试连接与余额
    # ------------------------------------------------------------------

    def test_connection(self) -> str:
        response = self.http.request(
            "get", f"{self.http.base_url}/v2/query/video_generation/zly-probe-nonexistent-task",
            action="测试连接", timeout=PROBE_TIMEOUT, headers=self.headers,
        )
        payload = self.http.parse_json(response, "测试连接", allow_client_error=True)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            try:
                http_code = int(error.get("http_code"))
            except (TypeError, ValueError):
                http_code = None
            if http_code in MINIMAX_AUTH_ERROR_CODES:
                raise CloudVideoError(
                    f"API Key 无效或无权限：{error.get('message') or '鉴权失败'}",
                )
            if http_code == 402:
                raise CloudVideoError(f"官方平台余额不足：{error.get('message') or '请充值后重试'}")
        return "连接成功，API Key 鉴权通过"

    def balance(self) -> float | None:
        # 官方平台未提供余额查询端点，暂不展示余额。
        return None

    def _raise_for_error(self, payload: dict[str, Any], action: str) -> None:
        error = payload.get("error")
        if not isinstance(error, dict):
            return
        message = str(error.get("message") or "").strip() or f"错误类型 {error.get('type') or '未知'}"
        try:
            http_code = int(error.get("http_code"))
        except (TypeError, ValueError):
            http_code = None
        if http_code in MINIMAX_AUTH_ERROR_CODES:
            message = f"API Key 无效或无权限：{message}"
        elif http_code == 402:
            message = f"官方平台余额不足：{message}"
        raise CloudVideoError(f"{self.http.label(action)}失败：{message}")


def _image_item(path: Path, role: str) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": image_data_uri(Path(path))}, "role": role}


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
