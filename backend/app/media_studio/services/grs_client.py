"""
GRS 极速生图客户端
参考 source1/app/grs_client.py 实现
支持：提交任务 → 轮询结果（同步阻塞）
"""
from __future__ import annotations

import base64
import mimetypes
import time
from typing import Any
from urllib.parse import urlparse

import requests

GRS_SUBMIT_TIMEOUT = (12.0, 60.0)
GRS_RESULT_TIMEOUT = (12.0, 60.0)
GRS_DOWNLOAD_TIMEOUT = (10.0, 120.0)
GRS_POLL_INTERVAL = 2.0      # 轮询间隔（秒）
GRS_POLL_MAX_WAIT = 120.0    # 最大等待时长（秒）
MAX_IMAGE_BYTES = 50 * 1024 * 1024

SUCCESS_STATUSES = {"success", "succeeded", "completed", "done"}
FAILED_STATUSES  = {"failed", "failure", "error", "violation", "cancelled", "canceled"}

IMAGE_URL_KEYS = {
    "url", "image", "image_url", "imageurl", "output", "result", "results",
    "urls", "images", "file", "src", "href",
}


class GrsError(RuntimeError):
    pass


class GrsClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._session = requests.Session()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #
    # 提交生图任务
    # ------------------------------------------------------------------ #
    def submit(
        self,
        *,
        model: str,
        prompt: str,
        aspect_ratio: str,
        images: list[str] | None = None,
        image_size: str | None = None,
    ) -> str:
        """提交异步生图任务，返回远端 task_id。"""
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "images": images or [],
            "aspectRatio": aspect_ratio,
            "replyType": "async",
        }
        if image_size:
            body["imageSize"] = image_size
        try:
            resp = self._session.post(
                f"{self.base_url}/v1/api/generate",
                headers=self._headers,
                json=body,
                timeout=GRS_SUBMIT_TIMEOUT,
            )
        except requests.RequestException as e:
            raise GrsError(f"GRS 提交失败: {e}") from e

        if resp.status_code >= 500:
            raise GrsError(f"GRS 服务暂时不可用 (HTTP {resp.status_code})")
        try:
            data = resp.json()
        except ValueError as e:
            raise GrsError("GRS 提交返回了无效 JSON") from e

        remote_id = (
            self._first(data, "id", "task_id", "taskId")
            or self._first(data.get("data") or {}, "id", "task_id", "taskId")
        )
        if not remote_id:
            raise GrsError(f"GRS 提交成功但未返回任务 ID，响应：{data}")
        return str(remote_id)

    # ------------------------------------------------------------------ #
    # 查询任务结果
    # ------------------------------------------------------------------ #
    def result(self, task_id: str) -> tuple[str, list[str], str | None]:
        """查询任务状态，返回 (status, image_urls, error_message)。"""
        try:
            resp = self._session.get(
                f"{self.base_url}/v1/api/result",
                headers=self._headers,
                params={"id": task_id},
                timeout=GRS_RESULT_TIMEOUT,
            )
        except requests.RequestException as e:
            raise GrsError(f"GRS 结果查询失败: {e}") from e

        try:
            payload = resp.json()
        except ValueError as e:
            raise GrsError("GRS 结果返回了无效 JSON") from e

        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        default_status = "failed" if resp.status_code >= 400 else "processing"
        status = str(
            self._first(data, "status", "state")
            or self._first(payload, "status", "state")
            or default_status
        ).lower()
        urls = self._image_urls(data) or self._image_urls(payload)
        message = (
            self._first(data, "error", "message", "msg")
            or self._first(payload, "error", "message", "msg")
        )
        return status, urls, str(message) if message else None

    # ------------------------------------------------------------------ #
    # 同步等待：提交 + 轮询直到完成
    # ------------------------------------------------------------------ #
    def generate_sync(
        self,
        *,
        model: str,
        prompt: str,
        aspect_ratio: str,
        images: list[str] | None = None,
        image_size: str | None = None,
    ) -> str:
        """
        提交任务并同步轮询直到完成，返回第一张图片的 URL。
        超时或失败时抛出 GrsError。
        """
        task_id = self.submit(
            model=model,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            images=images,
            image_size=image_size,
        )

        return self.wait_for_result(task_id)

    def wait_for_result(self, task_id: str) -> str:
        """Poll an already-submitted task until its first image is ready."""
        deadline = time.time() + GRS_POLL_MAX_WAIT
        while time.time() < deadline:
            time.sleep(GRS_POLL_INTERVAL)
            status, urls, error_msg = self.result(task_id)

            if status in SUCCESS_STATUSES:
                if not urls:
                    raise GrsError("GRS 任务完成但未返回图片 URL")
                return urls[0]

            if status in FAILED_STATUSES:
                detail = (error_msg or "").strip()
                if status == "violation":
                    raise GrsError(f"GRS 内容审核未通过：{detail}")
                raise GrsError(f"GRS 生图失败 [{status}]：{detail or '未知原因'}")

            # 还在处理中，继续轮询
            continue

        raise GrsError(f"GRS 生图超时（超过 {GRS_POLL_MAX_WAIT}s）")

    # ------------------------------------------------------------------ #
    # 工具方法
    # ------------------------------------------------------------------ #
    @staticmethod
    def _first(payload: dict[str, Any], *names: str) -> Any:
        return next(
            (payload.get(n) for n in names if payload.get(n) is not None),
            None,
        )

    @classmethod
    def _image_urls(cls, payload: Any) -> list[str]:
        found: list[str] = []

        def visit(value: Any, key: str = "") -> None:
            if isinstance(value, str) and value.startswith(("https://", "http://")):
                if key.lower() in IMAGE_URL_KEYS or not key:
                    found.append(value)
            elif isinstance(value, list):
                for item in value:
                    visit(item, key)
            elif isinstance(value, dict):
                for k, v in value.items():
                    visit(v, k)

        visit(payload)
        return list(dict.fromkeys(found))

    @staticmethod
    def data_uri_from_bytes(content: bytes, filename: str = "ref.png") -> str:
        mime = mimetypes.guess_type(filename)[0] or "image/png"
        if not mime.startswith("image/"):
            mime = "image/png"
        if len(content) > MAX_IMAGE_BYTES:
            raise GrsError("参考图片超过 50 MB")
        return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"

    def download_image(self, url: str) -> tuple[str, bytes]:
        """下载 GRS 临时结果图，返回 (filename, bytes)。仅允许 HTTPS。"""
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise GrsError("GRS 结果必须使用无凭证的 HTTPS 公共地址")
        try:
            resp = self._session.get(url, timeout=GRS_DOWNLOAD_TIMEOUT, stream=True)
        except requests.RequestException as e:
            raise GrsError(f"GRS 图片下载失败: {e}") from e
        if resp.status_code >= 400:
            resp.close()
            raise GrsError(f"GRS 图片下载失败（HTTP {resp.status_code}）")
        content_type = (resp.headers.get("Content-Type") or "").split(";", 1)[0].lower()
        declared = resp.headers.get("Content-Length")
        if declared:
            try:
                if int(declared) > MAX_IMAGE_BYTES:
                    resp.close()
                    raise GrsError("GRS 图片超过 50 MB")
            except ValueError:
                pass
        content = bytearray()
        try:
            for chunk in resp.iter_content(1024 * 1024):
                content.extend(chunk)
                if len(content) > MAX_IMAGE_BYTES:
                    raise GrsError("GRS 图片超过 50 MB")
        finally:
            resp.close()
        data = bytes(content)
        if not (
            data.startswith(b"\xff\xd8\xff")
            or data.startswith(b"\x89PNG\r\n\x1a\n")
            or data.startswith((b"GIF87a", b"GIF89a"))
            or (len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
        ):
            raise GrsError("GRS 结果不是有效图片")
        suffix = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }.get(content_type, ".png")
        if data.startswith(b"\xff\xd8\xff"):
            suffix = ".jpg"
        elif data.startswith(b"\x89PNG"):
            suffix = ".png"
        elif data.startswith(b"RIFF"):
            suffix = ".webp"
        return f"grs-result{suffix}", data
