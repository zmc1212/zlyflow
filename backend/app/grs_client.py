from __future__ import annotations

import base64
import ipaddress
import mimetypes
import socket
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import requests


MAX_IMAGE_BYTES = 50 * 1024 * 1024
SUCCESS_STATUSES = {"success", "succeeded", "completed", "done"}
FAILED_STATUSES = {"failed", "failure", "error", "violation", "cancelled", "canceled"}
IMAGE_URL_KEYS = {
    "url", "image", "image_url", "imageurl", "output", "result", "results",
    "urls", "images", "file", "src", "href",
}
# GRS currently serves generated files through this CDN name, which resolves to
# RFC 2544's benchmark range. Keep this exception narrowly scoped so result
# URLs from other hosts cannot be used to reach non-public addresses.
GRS_BENCHMARK_RESULT_HOSTS = {"file1.aitohumanize.com"}
RFC2544_BENCHMARK_NETWORK = ipaddress.ip_network("198.18.0.0/15")


class GrsError(RuntimeError):
    pass


class GrsTemporaryError(GrsError):
    pass


class GrsClient:
    def __init__(
        self, base_url: str, api_key: str, *, session: requests.Session | None = None,
        resolver: Callable[[str], list[str]] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.resolver = resolver or self._resolve_host

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _resolve_host(host: str) -> list[str]:
        return list({item[4][0] for item in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})

    def _json(
        self, response: requests.Response, action: str, *, allow_client_error: bool = False,
    ) -> dict[str, Any]:
        if response.status_code >= 500 or response.status_code in {408, 425, 429}:
            raise GrsTemporaryError(f"GRS {action} 暂时不可用（HTTP {response.status_code}）")
        try:
            payload = response.json()
        except ValueError as error:
            if response.status_code >= 400:
                raise GrsError(f"GRS {action} 失败（HTTP {response.status_code}）") from error
            raise GrsError(f"GRS {action} 返回了无效 JSON") from error
        if not isinstance(payload, dict):
            raise GrsError(f"GRS {action} 返回格式无效")
        if response.status_code >= 400 and not allow_client_error:
            raise GrsError(f"GRS {action} 失败（HTTP {response.status_code}）")
        return payload

    def submit(
        self, *, model: str, prompt: str, images: list[str], aspect_ratio: str,
        image_size: str | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "images": images,
            "aspectRatio": aspect_ratio,
            "replyType": "async",
        }
        if image_size:
            body["imageSize"] = image_size
        response = self.session.post(f"{self.base_url}/v1/api/generate", headers=self.headers, json=body, timeout=60)
        payload = self._json(response, "提交")
        remote_id = self._first(payload, "id", "task_id", "taskId")
        if remote_id is None and isinstance(payload.get("data"), dict):
            remote_id = self._first(payload["data"], "id", "task_id", "taskId")
        if not remote_id:
            raise GrsError("GRS 提交成功但未返回远端任务 ID")
        return str(remote_id)

    def result(self, remote_task_id: str) -> tuple[str, list[str], str | None]:
        response = self.session.get(
            f"{self.base_url}/v1/api/result", headers=self.headers,
            params={"id": remote_task_id}, timeout=60,
        )
        payload = self._json(response, "查询", allow_client_error=True)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        default_status = "failed" if response.status_code >= 400 else "processing"
        status = str(
            self._first(data, "status", "state") or self._first(payload, "status", "state") or default_status
        ).lower()
        urls = self._image_urls(data) or self._image_urls(payload)
        message = self._first(data, "error", "message", "msg") or self._first(payload, "error", "message", "msg")
        return status, urls, str(message) if message else None

    @staticmethod
    def format_failure(status: str, message: str | None = None) -> str:
        detail = (message or "").strip()
        if status == "violation":
            base = "内容未通过审核（可能含真人等受限内容）"
            return f"{base}：{detail}" if detail else base
        return detail or f"GRS 任务失败：{status}"

    def balance(self) -> float:
        response = self.session.post(
            f"{self.base_url}/client/openapi/getAPIKeyCredits",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"apiKey": self.api_key}, timeout=30,
        )
        payload = self._json(response, "余额查询")
        if payload.get("code") not in {None, 0, "0"}:
            raise GrsError(str(payload.get("msg") or payload.get("message") or "GRS 余额查询失败"))
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        try:
            return float(data["credits"])
        except (KeyError, TypeError, ValueError) as error:
            raise GrsError("GRS 余额响应缺少 credits") from error

    @staticmethod
    def _first(payload: dict[str, Any], *names: str) -> Any:
        return next((payload.get(name) for name in names if payload.get(name) is not None), None)

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
                for child_key, child in value.items():
                    visit(child, child_key)

        visit(payload)
        return list(dict.fromkeys(found))

    @staticmethod
    def data_uri(path: Path) -> str:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if not mime.startswith("image/"):
            raise GrsError(f"参考文件不是图片: {path.name}")
        content = path.read_bytes()
        if len(content) > MAX_IMAGE_BYTES:
            raise GrsError(f"参考图片超过 50 MB: {path.name}")
        return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"

    def _validate_public_https(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise GrsError("GRS 结果必须使用无凭证的 HTTPS 公共地址")
        hostname = parsed.hostname.lower().rstrip(".")
        try:
            addresses = self.resolver(hostname)
        except OSError as error:
            raise GrsTemporaryError("无法解析 GRS 图片地址") from error
        if not addresses:
            raise GrsError("GRS 图片地址没有可用 IP")
        for address in addresses:
            resolved = ipaddress.ip_address(address)
            if not resolved.is_global and not (
                hostname in GRS_BENCHMARK_RESULT_HOSTS and resolved in RFC2544_BENCHMARK_NETWORK
            ):
                raise GrsError("GRS 图片地址指向非公共网络，已拒绝下载")

    def download_image(self, url: str) -> tuple[str, bytes]:
        current = url
        for _ in range(6):
            self._validate_public_https(current)
            response = self.session.get(current, timeout=(10, 120), stream=True, allow_redirects=False)
            if response.status_code in {301, 302, 303, 307, 308}:
                target = response.headers.get("Location")
                response.close()
                if not target:
                    raise GrsError("GRS 图片重定向缺少目标地址")
                current = urljoin(current, target)
                continue
            if response.status_code >= 500 or response.status_code in {408, 425, 429}:
                response.close()
                raise GrsTemporaryError(f"GRS 图片下载暂时失败（HTTP {response.status_code}）")
            if response.status_code >= 400:
                response.close()
                raise GrsError(f"GRS 图片下载失败（HTTP {response.status_code}）")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if not content_type.startswith("image/"):
                response.close()
                raise GrsError("GRS 结果 MIME 不是图片")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_IMAGE_BYTES:
                response.close()
                raise GrsError("GRS 图片超过 50 MB")
            content = bytearray()
            for chunk in response.iter_content(1024 * 1024):
                content.extend(chunk)
                if len(content) > MAX_IMAGE_BYTES:
                    response.close()
                    raise GrsError("GRS 图片超过 50 MB")
            response.close()
            self._validate_signature(bytes(content))
            suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(content_type, ".img")
            return f"grs-result{suffix}", bytes(content)
        raise GrsError("GRS 图片重定向次数过多")

    @staticmethod
    def _validate_signature(content: bytes) -> None:
        signatures = (
            content.startswith(b"\xff\xd8\xff"),
            content.startswith(b"\x89PNG\r\n\x1a\n"),
            content.startswith((b"GIF87a", b"GIF89a")),
            len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP",
        )
        if not any(signatures):
            raise GrsError("GRS 图片文件签名无效")
