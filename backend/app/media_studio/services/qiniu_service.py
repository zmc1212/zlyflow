from __future__ import annotations

import io
import mimetypes
import secrets
import time
from pathlib import Path
from typing import Any
import qiniu

from ..models import QiniuConfigResponse
from ..provider_bridge import credential_manager, qiniu_row

QINIU_REGIONS = ("z0", "cn-east-2", "z1", "z2", "na0", "as0")
QINIU_UPLOAD_HOSTS = {
    "z0": "up-z0.qiniup.com",
    "cn-east-2": "up-cn-east-2.qiniup.com",
    "z1": "up-z1.qiniup.com",
    "z2": "up-z2.qiniup.com",
    "na0": "up-na0.qiniup.com",
    "as0": "up-as0.qiniup.com",
}


class QiniuService:
    @classmethod
    def get_config(cls) -> QiniuConfigResponse:
        cred = credential_manager()
        row = qiniu_row()
        if not row:
            return QiniuConfigResponse(
                enabled=False,
                bucket="",
                region="z0",
                domain="",
                object_prefix="zly-ai-video-studio/",
                has_access_key=False,
                has_secret_key=False,
                credential_ready=cred.ready,
                available=False,
            )

        has_ak = bool(row.get("access_key_encrypted"))
        has_sk = bool(row.get("secret_key_encrypted"))
        ak = cred.decrypt(row.get("access_key_encrypted")) if has_ak else None
        sk = cred.decrypt(row.get("secret_key_encrypted")) if has_sk else None

        available = bool(row.get("enabled") and cred.ready and ak and sk and row.get("bucket") and row.get("domain"))

        return QiniuConfigResponse(
            enabled=bool(row.get("enabled")),
            bucket=row.get("bucket") or "",
            region=row.get("region") or "z0",
            domain=row.get("domain") or "",
            object_prefix=row.get("object_prefix") or "zly-ai-video-studio/",
            has_access_key=has_ak,
            has_secret_key=has_sk,
            credential_ready=cred.ready,
            available=available,
            last_test_status=row.get("last_test_status"),
            last_test_message=row.get("last_test_message"),
            last_test_at=row.get("last_test_at"),
        )

    @classmethod
    def _runtime_config(cls) -> dict[str, str]:
        cred = credential_manager()
        row = qiniu_row()
        if not row or not row.get("enabled"):
            raise RuntimeError("请先在管理后台启用七牛云")
        ak = cred.decrypt(row.get("access_key_encrypted")) if row.get("access_key_encrypted") else None
        sk = cred.decrypt(row.get("secret_key_encrypted")) if row.get("secret_key_encrypted") else None
        bucket = (row.get("bucket") or "").strip()
        domain = (row.get("domain") or "").strip().rstrip("/")
        if not ak or not sk or not bucket or not domain:
            raise RuntimeError("请先在管理后台启用七牛云并填写 AK/SK、Bucket 与访问域名")
        prefix = (row.get("object_prefix") or "zly-ai-video-studio/").strip()
        if prefix and not prefix.endswith("/"):
            prefix = f"{prefix}/"
        region = (row.get("region") or "z0").strip() or "z0"
        return {
            "access_key": ak or "",
            "secret_key": sk or "",
            "bucket": bucket,
            "domain": domain,
            "object_prefix": prefix,
            "region": region,
        }

    @classmethod
    def object_url(cls, key: str, domain: str | None = None) -> str:
        host = (domain or "").rstrip("/")
        if not host:
            host = cls._runtime_config()["domain"]
        object_key = str(key or "").lstrip("/")
        if not host or not object_key:
            raise RuntimeError("七牛云对象地址无效")
        return f"{host}/{object_key}"

    @classmethod
    def store_bytes(cls, prefix: str, source_filename: str, content: bytes) -> tuple[str, str]:
        """上传二进制到七牛，返回 (object_key, cdn_url)。对齐 source1 QiniuStorage.store_bytes。"""
        cfg = cls._runtime_config()
        suffix = Path(source_filename).suffix or ".bin"
        timestamp = time.strftime("%Y%m%d/%H%M%S")
        key = f"{cfg['object_prefix']}{prefix}/{timestamp}_{secrets.token_hex(8)}{suffix}"
        mime_type = mimetypes.guess_type(source_filename)[0] or "application/octet-stream"
        auth = qiniu.Auth(cfg["access_key"], cfg["secret_key"])
        token = auth.upload_token(cfg["bucket"], key, 3600)
        region = cfg["region"] if cfg["region"] in QINIU_UPLOAD_HOSTS else "z0"
        regions = [qiniu.Region(up_host=QINIU_UPLOAD_HOSTS[region], scheme="https")]
        result, info = qiniu.put_data(
            token, key, content, mime_type=mime_type, check_crc=True, regions=regions,
        )
        if not getattr(info, "ok", lambda: False)() or not result or result.get("key") != key:
            raise RuntimeError(f"七牛云上传失败: {getattr(info, 'error', None) or info}")
        return key, cls.object_url(key, cfg["domain"])
