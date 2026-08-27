from __future__ import annotations

import io
import mimetypes
import secrets
import socket
import time
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .resource_storage import StoredResource


QINIU_REGIONS = ("z0", "cn-east-2", "z1", "z2", "na0", "as0")
QINIU_UPLOAD_HOSTS = {
    "z0": "up-z0.qiniup.com",
    "cn-east-2": "up-cn-east-2.qiniup.com",
    "z1": "up-z1.qiniup.com",
    "z2": "up-z2.qiniup.com",
    "na0": "up-na0.qiniup.com",
    "as0": "up-as0.qiniup.com",
}


def qiniu_upload_host(region: str) -> str:
    return QINIU_UPLOAD_HOSTS[region]


def validate_qiniu_config(values: dict[str, Any]) -> dict[str, str | bool]:
    region = str(values.get("region", "z0")).strip()
    if region not in QINIU_REGIONS:
        raise ValueError("不支持的七牛云区域")
    domain = str(values.get("domain", "")).strip().rstrip("/")
    parsed = urlparse(domain)
    if domain and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password):
        raise ValueError("七牛云访问域名必须是无内嵌凭证的 HTTPS 地址")
    prefix = str(values.get("object_prefix", "zly-ai-video-studio/")).strip().strip("/")
    return {
        "enabled": bool(values.get("enabled", False)),
        "access_key": str(values.get("access_key", "")).strip(),
        "secret_key": str(values.get("secret_key", "")).strip(),
        "bucket": str(values.get("bucket", "")).strip(),
        "region": region,
        "domain": domain,
        "object_prefix": f"{prefix}/" if prefix else "",
    }


class QiniuStorage:
    """Persistent Qiniu storage for completed images and videos."""

    provider_id = "qiniu"
    streams_outputs = False
    retains_comfy_outputs = False
    persistent_outputs = True

    def __init__(self, config: dict[str, str | bool]) -> None:
        self.config = validate_qiniu_config(config)
        if not self.config["access_key"] or not self.config["secret_key"] or not self.config["bucket"] or not self.config["domain"]:
            raise ValueError("七牛云 AK、SK、Bucket 和访问域名均为必填项")
        try:
            import qiniu  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError("未安装 qiniu SDK，请重新安装后端依赖") from error
        self._qiniu = qiniu
        self._auth = qiniu.Auth(str(self.config["access_key"]), str(self.config["secret_key"]))
        self._bucket_manager = qiniu.BucketManager(self._auth)
        self._upload_regions = [qiniu.Region(
            up_host=qiniu_upload_host(str(self.config["region"])), scheme="https",
        )]

    def _key(self, prefix: str, source_filename: str) -> str:
        suffix = Path(source_filename).suffix or ".bin"
        timestamp = time.strftime("%Y%m%d/%H%M%S")
        return f"{self.config['object_prefix']}{prefix}/{timestamp}_{secrets.token_hex(8)}{suffix}"

    @staticmethod
    def _retryable_upload(info: object) -> bool:
        """判断七牛 SDK 返回的失败是否属于可安全重试的传输错误。"""
        status = getattr(info, "status_code", None)
        if status in {-1, 0, 408, 429} or isinstance(status, int) and 500 <= status < 600:
            return True
        exception = getattr(info, "exception", None)
        if isinstance(exception, (ConnectionError, OSError, TimeoutError, RemoteDisconnected, socket.timeout)):
            return True
        # qiniu.ResponseInfo 在不同 SDK 小版本中可能只保留异常的字符串表示。
        detail = str(exception or info)
        return any(token in detail for token in (
            "RemoteDisconnected", "Connection aborted", "Connection reset", "ConnectionError", "Broken pipe", "timed out",
        ))

    def _upload(self, token: str, key: str, source_filename: str, content: bytes) -> tuple[dict | None, object]:
        mime_type = mimetypes.guess_type(source_filename)[0] or "application/octet-stream"
        # 七牛官方建议超过 8 MiB 使用分片上传；put_data 会把整个视频作为单次表单请求发送，
        # 在本地网络或代理短暂断开时很容易留下 RemoteDisconnected。
        if len(content) > 8 * 1024 * 1024:
            stream_uploader = getattr(self._qiniu, "put_stream_v2", None)
            if stream_uploader is not None:
                return stream_uploader(
                    token,
                    key,
                    io.BytesIO(content),
                    source_filename,
                    len(content),
                    mime_type=mime_type,
                    bucket_name=str(self.config["bucket"]),
                    part_size=4 * 1024 * 1024,
                    regions=self._upload_regions,
                )
            # qiniu==7.16.0 exposes the same v2 resumable uploader as
            # put_stream(..., version="v2"); newer SDKs expose put_stream_v2.
            stream_uploader = getattr(self._qiniu, "put_stream", None)
            if stream_uploader is not None:
                return stream_uploader(
                    token,
                    key,
                    io.BytesIO(content),
                    source_filename,
                    len(content),
                    mime_type=mime_type,
                    bucket_name=str(self.config["bucket"]),
                    part_size=4 * 1024 * 1024,
                    version="v2",
                    regions=self._upload_regions,
                )
        return self._qiniu.put_data(
            token, key, content, mime_type=mime_type, check_crc=True, regions=self._upload_regions,
        )

    def store_bytes(self, prefix: str, source_filename: str, content: bytes) -> StoredResource:
        key = self._key(prefix, source_filename)
        token = self._auth.upload_token(str(self.config["bucket"]), key, 3600)
        last_info: object | None = None
        for attempt in range(3):
            try:
                result, info = self._upload(token, key, source_filename, content)
            except Exception as error:
                last_info = error
                if attempt < 2 and self._retryable_upload(error):
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise RuntimeError(f"七牛云上传失败: {error}") from error
            last_info = info
            if getattr(info, "ok", lambda: False)() and result and result.get("key") == key:
                return StoredResource(key=key, local_path=None)
            if attempt < 2 and self._retryable_upload(info):
                time.sleep(0.5 * (2**attempt))
                continue
            break
        raise RuntimeError(f"七牛云上传失败: {last_info}")

    def create_reference(self, prefix: str, source_filename: str) -> StoredResource:
        raise RuntimeError("七牛云存储需要先上传完成的媒体文件")

    def resolve(self, key: str) -> Path | None:
        return None

    def delete(self, key: str) -> bool:
        result, info = self._bucket_manager.delete(str(self.config["bucket"]), key)
        status = getattr(info, "status_code", 0)
        if info.ok() or status == 612:
            return True
        raise RuntimeError(f"七牛云删除失败: {info}")

    def object_url(self, key: str) -> str | None:
        domain = str(self.config.get("domain") or "").rstrip("/")
        object_key = str(key or "").lstrip("/")
        if not domain or not object_key:
            return None
        return f"{domain}/{object_key}"

    def download_url(self, key: str, expires_in_seconds: int = 300) -> str:
        url = self.object_url(key)
        if not url:
            raise ValueError("七牛云对象地址无效")
        return self._auth.private_download_url(url, expires=max(1, expires_in_seconds))

    def test_connection(self) -> None:
        stored: StoredResource | None = None
        try:
            stored = self.store_bytes(".probe", "qiniu-probe.bin", b"zly-ai-video-studio-qiniu-probe")
        finally:
            if stored is not None:
                self.delete(stored.key)
