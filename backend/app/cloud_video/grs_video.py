"""GRS 视频服务适配器（MiniMax-H3 / Agnes Video 2.5 / Wan 3.0）。

- 鉴权：``Authorization: Bearer <API Key>``；余额查询走同族接口 ``POST /client/openapi/getAPIKeyCredits``（apiKey 放 JSON body）。
- 提交：POST /v1/api/generate，按 model 分三套参数：
  * minimax-h3：``aspectRatio(landscape/portrait)``、resolution 480p/768p/1080p、duration 1-15（1080p ≤10），
    参考图 ``images[]`` ≤9，首尾帧 ``firstFrame``/``lastFrame`` 必须成对且与 images 互斥，``promptSkill`` 默认 False。
  * agnes-video-2.5：``aspectRatio(16:9/9:16/21:9/4:3/1:1/3:4)``、resolution 720p/1080p/2k、duration 4-12，
    参考图 ``images[]`` ≤5，首帧可单独使用，首尾帧与 images 互斥（上游 audios/videos 参考未开放）。
  * wan-3.0：``aspectRatio(16:9/9:16/21:9/4:3/1:1/3:4)``、resolution 480p/720p/1080p、duration 2-30，
    参考图 ``images[]`` ≤10、参考音频 ``audios[]`` ≤5（每段 ≤15 秒）、参考视频 ``videos[]`` ≤5（MP4，合计 ≤15 秒）；
    首帧/尾帧可单独或成对使用，但与 images/audios 互斥（videos 可与首尾帧同时使用）。
- 轮询：GET /v1/api/result?id=<task_id>，status ∈ running / violation / succeeded / failed；
  成片地址在 ``results[].url``；查询有效期 2 小时。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from .base import (
    CloudTaskSnapshot,
    CloudVideoError,
    CloudVideoSubmitRequest,
    image_data_uri,
    reference_media_data_uri,
)
from .http import CloudVideoHttpClient, POLL_TIMEOUT, SUBMIT_TIMEOUT

PROVIDER_LABEL = "GRS视频服务"
BALANCE_PROBE_TIMEOUT = (12.0, 30.0)
GRS_H3_RESOLUTIONS = ("480p", "768p", "1080p")
GRS_H3_MAX_DURATION = 15
GRS_H3_1080P_MAX_DURATION = 10
GRS_H3_MAX_REFERENCES = 9
GRS_H3_ASPECTS = ("landscape", "portrait")
GRS_AGNES_PREFIX = "agnes"
GRS_AGNES_RESOLUTIONS = ("720p", "1080p", "2k")
GRS_AGNES_ASPECTS = ("16:9", "9:16", "21:9", "4:3", "1:1", "3:4")
GRS_AGNES_MAX_REFERENCES = 5
GRS_AGNES_MIN_DURATION = 4
GRS_AGNES_MAX_DURATION = 12
GRS_WAN_PREFIX = "wan"
GRS_WAN_RESOLUTIONS = ("480p", "720p", "1080p")
GRS_WAN_ASPECTS = ("16:9", "9:16", "21:9", "4:3", "1:1", "3:4")
GRS_WAN_MIN_DURATION = 2
GRS_WAN_MAX_DURATION = 30
GRS_WAN_MAX_REFERENCES = 10
GRS_WAN_MAX_AUDIO_REFERENCES = 5
GRS_WAN_MAX_VIDEO_REFERENCES = 5


class GrsVideoClient:
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
        model = str(options.get("model") or request.model or "").strip()
        if model.lower().startswith(GRS_AGNES_PREFIX):
            return self._submit_agnes(request, model)
        if model.lower().startswith(GRS_WAN_PREFIX):
            return self._submit_wan(request, model)
        resolution = str(options.get("resolution") or "").strip().lower()
        if resolution not in GRS_H3_RESOLUTIONS:
            raise CloudVideoError(f"GRS 视频分辨率必须是 {'/'.join(GRS_H3_RESOLUTIONS)} 之一")
        duration = _as_int(options.get("duration"))
        if duration is None or not 1 <= duration <= GRS_H3_MAX_DURATION:
            raise CloudVideoError(f"GRS 视频时长必须是 1-{GRS_H3_MAX_DURATION} 秒")
        if resolution == "1080p" and duration > GRS_H3_1080P_MAX_DURATION:
            raise CloudVideoError(f"1080p 分辨率最长支持 {GRS_H3_1080P_MAX_DURATION} 秒")
        aspect = str(options.get("aspect_ratio") or "landscape").strip().lower()
        if aspect not in GRS_H3_ASPECTS:
            raise CloudVideoError(f"GRS 视频画幅只支持 {'/'.join(GRS_H3_ASPECTS)}")

        if request.first_frame is not None and request.last_frame is None:
            raise CloudVideoError("GRS 首尾帧必须成对提供：只给了首帧")
        if request.first_frame is None and request.last_frame is not None:
            raise CloudVideoError("GRS 首尾帧必须成对提供：只给了尾帧")
        if request.first_frame is not None and request.references:
            raise CloudVideoError("GRS 首尾帧与参考图互斥，不能同时提供")

        body: dict[str, Any] = {
            "model": str(options.get("model") or request.model),
            "prompt": request.prompt,
            "aspectRatio": aspect,
            "resolution": resolution,
            "duration": duration,
            "replyType": "async",
            "promptSkill": bool(options.get("prompt_skill") or False),
        }
        seed = _as_int(options.get("seed"))
        if seed:  # schema 约定 0 = 随机，不下发 seed
            body["seed"] = seed
        if request.first_frame is not None:
            body["firstFrame"] = image_data_uri(request.first_frame)
            body["lastFrame"] = image_data_uri(request.last_frame)  # 成对性已在上方校验
        elif request.references:
            if len(request.references) > GRS_H3_MAX_REFERENCES:
                raise CloudVideoError(f"GRS 参考图最多 {GRS_H3_MAX_REFERENCES} 张")
            body["images"] = [image_data_uri(Path(path)) for path in request.references]

        return self._post_generate(body)

    def _submit_agnes(self, request: CloudVideoSubmitRequest, model: str) -> str:
        """Agnes Video 2.5：固定六种画幅、720p/1080p/2k、4-12 秒，首帧可单独使用。"""
        options = request.options or {}
        resolution = str(options.get("resolution") or "").strip().lower()
        if resolution not in GRS_AGNES_RESOLUTIONS:
            raise CloudVideoError(f"GRS Agnes 分辨率必须是 {'/'.join(GRS_AGNES_RESOLUTIONS)} 之一")
        duration = _as_int(options.get("duration"))
        if duration is None or not GRS_AGNES_MIN_DURATION <= duration <= GRS_AGNES_MAX_DURATION:
            raise CloudVideoError(
                f"GRS Agnes 视频时长必须是 {GRS_AGNES_MIN_DURATION}-{GRS_AGNES_MAX_DURATION} 秒",
            )
        aspect = str(options.get("aspect_ratio") or "16:9").strip()
        if aspect not in GRS_AGNES_ASPECTS:
            raise CloudVideoError(f"GRS Agnes 画幅只支持 {'/'.join(GRS_AGNES_ASPECTS)}")
        if request.first_frame is None and request.last_frame is not None:
            raise CloudVideoError("GRS Agnes 尾帧必须与首帧同时提供")
        if (request.first_frame is not None or request.last_frame is not None) and request.references:
            raise CloudVideoError("GRS Agnes 首尾帧与参考图互斥，不能同时提供")

        body: dict[str, Any] = {
            "model": model,
            "prompt": request.prompt,
            "aspectRatio": aspect,
            "resolution": resolution,
            "duration": duration,
            "replyType": "async",
        }
        seed = _as_int(options.get("seed"))
        if seed:  # 0 = 随机，不下发 seed
            body["seed"] = seed
        if request.first_frame is not None:
            body["firstFrame"] = image_data_uri(request.first_frame)
            if request.last_frame is not None:
                body["lastFrame"] = image_data_uri(request.last_frame)
        elif request.references:
            if len(request.references) > GRS_AGNES_MAX_REFERENCES:
                raise CloudVideoError(f"GRS Agnes 参考图最多 {GRS_AGNES_MAX_REFERENCES} 张")
            body["images"] = [image_data_uri(Path(path)) for path in request.references]

        return self._post_generate(body)

    def _submit_wan(self, request: CloudVideoSubmitRequest, model: str) -> str:
        """Wan 3.0：六种画幅、480p/720p/1080p、2-30 秒，参考图 ≤10，首帧/尾帧可单独或成对使用。"""
        options = request.options or {}
        resolution = str(options.get("resolution") or "").strip().lower()
        if resolution not in GRS_WAN_RESOLUTIONS:
            raise CloudVideoError(f"GRS Wan 分辨率必须是 {'/'.join(GRS_WAN_RESOLUTIONS)} 之一")
        duration = _as_int(options.get("duration"))
        if duration is None or not GRS_WAN_MIN_DURATION <= duration <= GRS_WAN_MAX_DURATION:
            raise CloudVideoError(
                f"GRS Wan 视频时长必须是 {GRS_WAN_MIN_DURATION}-{GRS_WAN_MAX_DURATION} 秒",
            )
        aspect = str(options.get("aspect_ratio") or GRS_WAN_ASPECTS[0]).strip()
        if aspect not in GRS_WAN_ASPECTS:
            raise CloudVideoError(f"GRS Wan 画幅只支持 {'/'.join(GRS_WAN_ASPECTS)}")
        uses_frames = request.first_frame is not None or request.last_frame is not None
        if uses_frames and (request.references or request.audio_references):
            raise CloudVideoError("GRS Wan 首尾帧与参考图/参考音频互斥，不能同时提供")

        body: dict[str, Any] = {
            "model": model,
            "prompt": request.prompt,
            "aspectRatio": aspect,
            "resolution": resolution,
            "duration": duration,
            "replyType": "async",
        }
        seed = _as_int(options.get("seed"))
        if seed:  # 0 = 随机，不下发 seed
            body["seed"] = seed
        if request.first_frame is not None:
            body["firstFrame"] = image_data_uri(request.first_frame)
        if request.last_frame is not None:
            body["lastFrame"] = image_data_uri(request.last_frame)
        if request.references:
            if len(request.references) > GRS_WAN_MAX_REFERENCES:
                raise CloudVideoError(f"GRS Wan 参考图最多 {GRS_WAN_MAX_REFERENCES} 张")
            body["images"] = [image_data_uri(Path(path)) for path in request.references]
        if request.audio_references:
            if len(request.audio_references) > GRS_WAN_MAX_AUDIO_REFERENCES:
                raise CloudVideoError(f"GRS Wan 参考音频最多 {GRS_WAN_MAX_AUDIO_REFERENCES} 段")
            body["audios"] = [reference_media_data_uri(Path(path), "audio") for path in request.audio_references]
        if request.video_references:
            if len(request.video_references) > GRS_WAN_MAX_VIDEO_REFERENCES:
                raise CloudVideoError(f"GRS Wan 参考视频最多 {GRS_WAN_MAX_VIDEO_REFERENCES} 段")
            body["videos"] = [
                {"url": reference_media_data_uri(Path(path), "video")} for path in request.video_references
            ]
        return self._post_generate(body)

    def _post_generate(self, body: dict[str, Any]) -> str:
        """提交 /v1/api/generate 并解析远端任务 ID（GRS 对违规/参数拒绝会返回 HTTP 400 + error）。"""
        response = self.http.request(
            "post", f"{self.http.base_url}/v1/api/generate", action="提交", timeout=SUBMIT_TIMEOUT,
            uncertain_on_read=True, headers=self.headers, json=body,
        )
        payload = self.http.parse_json(response, "提交", allow_client_error=True)
        message = str(payload.get("error") or "").strip()
        task_id = str(payload.get("id") or "").strip()
        if not task_id:
            if message:
                raise CloudVideoError(f"{self.http.label('提交')}被拒绝：{message}")
            raise CloudVideoError(f"{self.http.label('提交')}成功但未返回远端任务 ID")
        return task_id

    # ------------------------------------------------------------------
    # 轮询
    # ------------------------------------------------------------------

    def poll(self, remote_task_id: str) -> CloudTaskSnapshot:
        response = self.http.request(
            "get", f"{self.http.base_url}/v1/api/result", action="查询", timeout=POLL_TIMEOUT,
            headers=self.headers, params={"id": remote_task_id},
        )
        payload = self.http.parse_json(response, "查询", allow_client_error=True)
        status_raw = str(payload.get("status") or "").strip().lower()
        message = str(payload.get("error") or "").strip() or None
        if status_raw == "succeeded":
            status = "completed"
        elif status_raw in {"failed", "violation"}:
            status = "failed"
            if status_raw == "violation":
                message = f"内容违规，上游已返还积分：{message}" if message else "内容违规，上游已返还积分"
        else:
            # running 与未知状态一律视为进行中，由调用方继续轮询。
            status = "active"
        videos: list[str] = []
        if status == "completed":
            results = payload.get("results")
            if isinstance(results, list):
                videos = [
                    str(item.get("url") or "").strip()
                    for item in results
                    if isinstance(item, dict) and item.get("url")
                ]
            if not videos:
                raise CloudVideoError(f"{self.http.label('查询')}完成但未返回成片地址")
        progress = _as_int(payload.get("progress"))
        if progress is None or not 0 <= progress <= 100:
            progress = 12 if status == "active" else (100 if status == "completed" else 0)
        return CloudTaskSnapshot(
            status=status,
            progress=progress,
            video_urls=videos,
            message=message,
            remote_status=status_raw,
        )

    # ------------------------------------------------------------------
    # 测试连接与余额（与生图共用同族接口）
    # ------------------------------------------------------------------

    def test_connection(self) -> str:
        credits = self.balance()
        if credits is None:
            return "连接成功，API Key 鉴权通过"
        return f"连接成功，API Key 鉴权通过，剩余积分 {credits:g}"

    def balance(self) -> float | None:
        response = self.http.request(
            "post", f"{self.http.base_url}/client/openapi/getAPIKeyCredits", action="余额查询",
            timeout=BALANCE_PROBE_TIMEOUT,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"apiKey": self.api_key},
        )
        payload = self.http.parse_json(response, "余额查询")
        if payload.get("code") not in {None, 0, "0"}:
            raise CloudVideoError(str(payload.get("msg") or payload.get("message") or "GRS视频服务余额查询失败"))
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        try:
            return float(data["credits"])
        except (KeyError, TypeError, ValueError) as error:
            raise CloudVideoError("GRS视频服务余额响应缺少 credits") from error


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
