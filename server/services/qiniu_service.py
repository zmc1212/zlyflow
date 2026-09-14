from __future__ import annotations

import io
import mimetypes
import secrets
import time
from pathlib import Path
import qiniu

from ..config import settings
from ..crypto import CredentialManager
from ..db import execute_sql, now_str, query_one
from ..models import QiniuConfigResponse, QiniuTestRequest, QiniuUpdateRequest

QINIU_REGIONS = ("z0", "cn-east-2", "z1", "z2", "na0", "as0")
QINIU_UPLOAD_HOSTS = {
    "z0": "up-z0.qiniup.com",
    "cn-east-2": "up-cn-east-2.qiniup.com",
    "z1": "up-z1.qiniup.com",
    "z2": "up-z2.qiniup.com",
    "na0": "up-na0.qiniup.com",
    "as0": "up-as0.qiniup.com",
}


def get_credential_manager() -> CredentialManager:
    return CredentialManager(settings.credential_key)


class QiniuService:
    @classmethod
    def get_config(cls) -> QiniuConfigResponse:
        cred = get_credential_manager()
        row = query_one("SELECT * FROM ai_qiniu_provider_settings WHERE id = 1")
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

        available = bool(row["enabled"] and cred.ready and ak and sk and row.get("bucket") and row.get("domain"))

        return QiniuConfigResponse(
            enabled=bool(row["enabled"]),
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
    def update_config(cls, payload: QiniuUpdateRequest) -> QiniuConfigResponse:
        cred = get_credential_manager()
        timestamp = now_str()
        current = query_one("SELECT * FROM ai_qiniu_provider_settings WHERE id = 1") or {}

        ak_enc = current.get("access_key_encrypted")
        sk_enc = current.get("secret_key_encrypted")

        if payload.access_key and payload.access_key.strip():
            ak_enc = cred.encrypt(payload.access_key.strip())
        if payload.secret_key and payload.secret_key.strip():
            sk_enc = cred.encrypt(payload.secret_key.strip())

        prefix = payload.object_prefix.strip().strip("/")
        normalized_prefix = f"{prefix}/" if prefix else ""

        execute_sql(
            """
            INSERT INTO ai_qiniu_provider_settings
            (id, enabled, access_key_encrypted, secret_key_encrypted, bucket, region, domain, object_prefix, updated_at)
            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                enabled = VALUES(enabled),
                access_key_encrypted = VALUES(access_key_encrypted),
                secret_key_encrypted = VALUES(secret_key_encrypted),
                bucket = VALUES(bucket),
                region = VALUES(region),
                domain = VALUES(domain),
                object_prefix = VALUES(object_prefix),
                updated_at = VALUES(updated_at)
            """,
            (
                1 if payload.enabled else 0,
                ak_enc,
                sk_enc,
                payload.bucket.strip(),
                payload.region.strip(),
                payload.domain.strip().rstrip("/"),
                normalized_prefix,
                timestamp,
            ),
        )
        return cls.get_config()

    @classmethod
    def test_connection(cls, payload: QiniuTestRequest | None = None) -> QiniuConfigResponse:
        cred = get_credential_manager()
        current = query_one("SELECT * FROM ai_qiniu_provider_settings WHERE id = 1") or {}

        ak = payload.access_key.strip() if payload and payload.access_key and payload.access_key.strip() else None
        if not ak and current.get("access_key_encrypted"):
            ak = cred.decrypt(current["access_key_encrypted"])

        sk = payload.secret_key.strip() if payload and payload.secret_key and payload.secret_key.strip() else None
        if not sk and current.get("secret_key_encrypted"):
            sk = cred.decrypt(current["secret_key_encrypted"])

        bucket = (payload.bucket if payload and payload.bucket else current.get("bucket") or "").strip()
        region = (payload.region if payload and payload.region else current.get("region") or "z0").strip()

        if not ak or not sk:
            raise RuntimeError("七牛云 AK 与 SK 不能为空")
        if not bucket:
            raise RuntimeError("七牛云 Bucket 名称不能为空")

        timestamp = now_str()
        try:
            auth = qiniu.Auth(ak, sk)
            bucket_mgr = qiniu.BucketManager(auth)
            probe_key = f"_probe/probe_{int(time.time())}.txt"
            token = auth.upload_token(bucket, probe_key, 300)
            data = b"qiniu-probe-test"
            ret, info = qiniu.put_data(token, probe_key, io.BytesIO(data))
            if not info.ok():
                raise RuntimeError(f"测试上传失败: {info.error or info.text_body}")

            # Delete probe file
            bucket_mgr.delete(bucket, probe_key)
            status = "success"
            msg = "上传和删除探针文件验证成功，AK/SK 及 Bucket 权限正常"
        except Exception as err:
            status = "failed"
            msg = str(err)

        execute_sql(
            """
            UPDATE ai_qiniu_provider_settings
            SET last_test_status = %s, last_test_message = %s, last_test_at = %s, updated_at = %s
            WHERE id = 1
            """,
            (status, msg, timestamp, timestamp),
        )

        if status == "failed":
            raise RuntimeError(f"七牛云存储测试连接失败: {msg}")

        return cls.get_config()

    @classmethod
    def _runtime_config(cls) -> dict[str, str]:
        cred = get_credential_manager()
        row = query_one("SELECT * FROM ai_qiniu_provider_settings WHERE id = 1")
        if not row or not row.get("enabled"):
            raise RuntimeError("请先在系统设置启用七牛云")
        ak = cred.decrypt(row.get("access_key_encrypted")) if row.get("access_key_encrypted") else None
        sk = cred.decrypt(row.get("secret_key_encrypted")) if row.get("secret_key_encrypted") else None
        bucket = (row.get("bucket") or "").strip()
        domain = (row.get("domain") or "").strip().rstrip("/")
        if not ak or not sk or not bucket or not domain:
            raise RuntimeError("请先在系统设置启用七牛云并填写 AK/SK、Bucket 与访问域名")
        prefix = (row.get("object_prefix") or "zly-ai-video-studio/").strip()
        if prefix and not prefix.endswith("/"):
            prefix = f"{prefix}/"
        region = (row.get("region") or "z0").strip() or "z0"
        return {
            "access_key": ak,
            "secret_key": sk,
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
