"""云端视频模型共享执行服务。

职责（供 worker 云端视频执行器与剧集工坊共用）：
- 连接配置：读取 ``cloud_video_provider_settings`` 多行表，凭据经 ``CredentialManager``（Fernet）加解密；
- 管理设置：public_config / update / test（回写 last_test_*，响应必含 available/unavailable_reason）；
- 执行：submit（提交→立即返回 remote_task_id）、wait_for_task（轮询 + 临时错误退避 + 超时）、
  download_and_store（下载成片 → 资源存储（七牛）→ 产出 outputs payload）。

线程模型：所有方法为阻塞实现，调用方用 ``asyncio.to_thread`` 包装（与 GrsClient/MusicJobService 一致）。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from .cloud_video.base import (
    CLOUD_VIDEO_MAX_VIDEO_BYTES,
    CloudTaskSnapshot,
    CloudVideoAdapter,
    CloudVideoError,
    CloudVideoSubmitRequest,
    CloudVideoTemporaryError,
    CloudVideoUncertainSubmitError,
    cloud_video_provider_keys,
    cloud_video_provider_spec,
    normalize_cloud_task_status,
    with_cloud_video_billing_caution,
)
from .cloud_video import build_adapter
from .grs_provider import CredentialManager
from .resource_storage import ResourceStorage, resource_object_url

POLL_INTERVAL_SECONDS = 6.0
POLL_MAX_INTERVAL_SECONDS = 30.0
TASK_TIMEOUT_SECONDS = 45 * 60.0
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


class CloudVideoService:
    _instance: "CloudVideoService | None" = None
    _CONFIGURE_LOCK = threading.Lock()

    def __init__(self, store, credential_key: str | None, resource_storage: ResourceStorage | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)
        self.resource_storage = resource_storage

    # ------------------------------------------------------------------
    # 类级单例（MusicJobService 模式）
    # ------------------------------------------------------------------

    @classmethod
    def configure(cls, store, credential_key: str | None, resource_storage: ResourceStorage | None) -> "CloudVideoService":
        with cls._CONFIGURE_LOCK:
            cls._instance = cls(store, credential_key, resource_storage)
        return cls._instance

    @classmethod
    def instance(cls) -> "CloudVideoService":
        if cls._instance is None:
            raise CloudVideoError("云端视频服务尚未初始化")
        return cls._instance

    # ------------------------------------------------------------------
    # 凭据与客户端
    # ------------------------------------------------------------------

    @property
    def credential_ready(self) -> bool:
        return self.credentials.error is None and self.credentials._fernet is not None

    def _decrypt(self, value: str | None) -> str:
        if not value:
            return ""
        decrypted = self.credentials.decrypt(value)
        return decrypted or ""

    def provider_settings(self, provider_key: str) -> dict[str, Any]:
        return self.store.get_cloud_video_settings(provider_key)

    def effective_base_url(self, settings_row: dict[str, Any]) -> str:
        return str(settings_row.get("base_url") or "").strip() or cloud_video_provider_spec(
            settings_row["provider_key"],
        ).default_base_url

    def client(
        self, provider_key: str, *, base_url: str | None = None, api_key: str | None = None,
        api_secret: str | None = None,
    ) -> CloudVideoAdapter:
        """构造厂商客户端；显式参数优先（测试连接时用未保存的输入），否则读已保存配置并解密。"""
        spec = cloud_video_provider_spec(provider_key)
        settings_row = self.provider_settings(provider_key)
        effective_base = str(base_url or "").strip() or self.effective_base_url(settings_row)
        effective_key = api_key if api_key is not None else self._decrypt(settings_row.get("api_key_encrypted"))
        effective_secret = None
        if spec.requires_secret:
            effective_secret = api_secret if api_secret is not None else self._decrypt(
                settings_row.get("api_secret_encrypted"),
            )
        return build_adapter(
            provider_key, base_url=effective_base, api_key=effective_key or "", api_secret=effective_secret,
        )

    # ------------------------------------------------------------------
    # 可用性
    # ------------------------------------------------------------------

    def availability(self, provider_key: str) -> tuple[bool, str | None]:
        spec = cloud_video_provider_spec(provider_key)
        settings_row = self.provider_settings(provider_key)
        if not settings_row.get("enabled"):
            return False, f"「{spec.label}」尚未在管理设置中启用。"
        if not self.credential_ready:
            return False, "服务器未配置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY，无法解密云端视频凭据。"
        if not self._decrypt(settings_row.get("api_key_encrypted")):
            return False, f"「{spec.label}」尚未保存 {spec.api_key_label}。"
        if spec.requires_secret and not self._decrypt(settings_row.get("api_secret_encrypted")):
            return False, f"「{spec.label}」尚未保存 {spec.api_secret_label}。"
        return True, None

    # ------------------------------------------------------------------
    # 管理设置：public_config / update / test
    # ------------------------------------------------------------------

    def public_config(self, provider_key: str) -> dict[str, Any]:
        spec = cloud_video_provider_spec(provider_key)
        settings_row = self.provider_settings(provider_key)
        available, reason = self.availability(provider_key)
        key_masked = ""
        has_key = bool(self._decrypt(settings_row.get("api_key_encrypted")))
        if has_key:
            key = self._decrypt(settings_row.get("api_key_encrypted"))
            key_masked = f"{key[:3]}{'*' * max(len(key) - 5, 3)}{key[-2:]}"
        return {
            "provider_key": spec.key,
            "label": spec.label,
            "requires_secret": spec.requires_secret,
            "api_key_label": spec.api_key_label,
            "api_secret_label": spec.api_secret_label,
            "base_url_hint": spec.base_url_hint,
            "default_base_url": spec.default_base_url,
            "enabled": bool(settings_row.get("enabled")),
            "base_url": str(settings_row.get("base_url") or ""),
            "effective_base_url": self.effective_base_url(settings_row),
            "has_api_key": has_key,
            "api_key_masked": key_masked,
            "has_api_secret": bool(self._decrypt(settings_row.get("api_secret_encrypted"))),
            "credential_ready": self.credential_ready,
            "last_test_status": settings_row.get("last_test_status"),
            "last_test_message": settings_row.get("last_test_message"),
            "last_test_at": settings_row.get("last_test_at"),
            "available": available,
            "unavailable_reason": reason,
        }

    def public_configs(self) -> list[dict[str, Any]]:
        return [self.public_config(key) for key in cloud_video_provider_keys()]

    def update_provider(self, provider_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        spec = cloud_video_provider_spec(provider_key)
        updates: dict[str, Any] = {}
        if payload.get("enabled") is not None:
            updates["enabled"] = 1 if payload.get("enabled") else 0
        if "base_url" in payload:
            base_url = str(payload.get("base_url") or "").strip()
            if base_url:
                self._validate_base_url(base_url)
            updates["base_url"] = base_url or None
        if "api_key" in payload:
            api_key = str(payload.get("api_key") or "").strip()
            if api_key:
                updates["api_key_encrypted"] = self.credentials.encrypt(api_key)
        if "api_secret" in payload and spec.requires_secret:
            api_secret = str(payload.get("api_secret") or "").strip()
            if api_secret:
                updates["api_secret_encrypted"] = self.credentials.encrypt(api_secret)
        if updates:
            self.store.update_cloud_video_settings(provider_key, **updates)
        return self.public_config(provider_key)

    @staticmethod
    def _validate_base_url(base_url: str) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Base URL 必须是无内嵌凭证的 HTTPS 地址")
        if parsed.username or parsed.password:
            raise ValueError("Base URL 不能内嵌账号密码")

    def test_provider(
        self, provider_key: str, *, base_url: str | None = None, api_key: str | None = None,
        api_secret: str | None = None,
    ) -> dict[str, Any]:
        """测试连接：显式参数优先（未保存的输入），结果回写 last_test_*。"""
        try:
            client = self.client(
                provider_key, base_url=base_url, api_key=api_key, api_secret=api_secret,
            )
            message = client.test_connection()
            status = "success"
        except Exception as error:
            status = "failed"
            message = str(error)
            self.store.update_cloud_video_settings(
                provider_key,
                last_test_status=status, last_test_message=message[:500], last_test_at=_now_text(),
            )
            raise
        self.store.update_cloud_video_settings(
            provider_key, last_test_status=status, last_test_message=message[:500], last_test_at=_now_text(),
        )
        result = self.public_config(provider_key)
        result["available"], result["unavailable_reason"] = self.availability(provider_key)
        return result

    def balance(self, provider_key: str) -> float | None:
        """账户余额（厂商无接口时返回 None），供管理设置展示。"""
        client = self.client(provider_key)
        try:
            return client.balance()
        except CloudVideoError:
            raise
        except Exception as error:  # pragma: no cover
            raise CloudVideoError(str(error)) from error

    # ------------------------------------------------------------------
    # 执行：提交 / 轮询 / 下载落盘
    # ------------------------------------------------------------------

    def submit_generation(
        self, provider_key: str, *, model: str, prompt: str, negative_prompt: str | None = None,
        first_frame: Path | None = None, last_frame: Path | None = None,
        references: list[Path] | None = None, options: dict[str, Any] | None = None,
        client_ref: str | None = None,
    ) -> str:
        request = CloudVideoSubmitRequest(
            model=model, prompt=prompt, negative_prompt=negative_prompt, first_frame=first_frame,
            last_frame=last_frame, references=references, options=options, client_ref=client_ref,
        )
        return self.client(provider_key).submit(request)

    def wait_for_task(
        self, provider_key: str, remote_task_id: str, *, poll_interval: float = POLL_INTERVAL_SECONDS,
        timeout: float = TASK_TIMEOUT_SECONDS, on_progress: Callable[[CloudTaskSnapshot], None] | None = None,
    ) -> CloudTaskSnapshot:
        """轮询远端任务直到 completed / failed / 超时；临时错误退避重试。"""
        client = self.client(provider_key)
        deadline = time.monotonic() + timeout
        interval = poll_interval
        while True:
            time.sleep(interval)
            try:
                snapshot = client.poll(remote_task_id)
            except CloudVideoTemporaryError:
                if time.monotonic() >= deadline:
                    raise CloudVideoError(
                        f"云端视频任务查询超时（超过 {int(timeout)}s），远端任务 ID {remote_task_id}",
                    )
                interval = min(interval * 1.5, POLL_MAX_INTERVAL_SECONDS)
                continue
            if callable(on_progress):
                try:
                    on_progress(snapshot)
                except Exception:  # noqa: BLE001 — 进度回调失败不影响主流程
                    pass
            if snapshot.status == "completed":
                return snapshot
            if snapshot.status == "failed":
                raise CloudVideoError(f"云端视频生成失败：{snapshot.message or snapshot.remote_status or '未知原因'}")
            if time.monotonic() >= deadline:
                raise CloudVideoError(
                    f"云端视频生成超时（超过 {int(timeout / 60)} 分钟），远端任务 ID {remote_task_id}",
                )
            interval = poll_interval

    def resume_snapshot(self, provider_key: str, remote_task_id: str) -> CloudTaskSnapshot:
        """续传探测：直接查询一次远端状态（供重试时判断远端是否已完成）。"""
        return self.client(provider_key).poll(remote_task_id)

    def download_and_store(
        self, video_urls: list[str], *, prefix: str, filename: str, label: str = "生成视频",
    ) -> dict[str, Any]:
        """下载成片并写入资源存储（七牛），返回与 ComfyService.output_payload 同形状的输出条目。"""
        if self.resource_storage is None:
            raise CloudVideoError("服务器未初始化资源存储。")
        content = self._download_video(video_urls)
        stored = self.resource_storage.store_bytes(prefix, filename, content)
        output: dict[str, Any] = {
            "kind": "video", "path": stored.key, "label": label,
            "delivery_status": "cloud" if self.resource_storage.persistent_outputs else "pending",
            "delivered_at": None,
        }
        cloud_url = resource_object_url(self.resource_storage, stored.key)
        if cloud_url:
            output["cloud_url"] = cloud_url
        return output

    @staticmethod
    def _download_video(video_urls: list[str]) -> bytes:
        last_error: Exception | None = None
        for url in video_urls:
            try:
                response = requests.get(url, stream=True, timeout=(15.0, 300.0))
                response.raise_for_status()
            except Exception as error:  # noqa: BLE001
                last_error = error
                continue
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                total += len(chunk)
                if total > CLOUD_VIDEO_MAX_VIDEO_BYTES:
                    raise CloudVideoError("云端视频成片超过 1GB 上限，拒绝下载")
                chunks.append(chunk)
            content = b"".join(chunks)
            _validate_video_magic(content)
            return content
        raise CloudVideoError(f"云端视频成片下载失败：{last_error or '未返回可下载地址'}")


def _validate_video_magic(content: bytes) -> None:
    head = content[:16]
    is_mp4 = len(head) >= 8 and head[4:8] == b"ftyp"
    is_matroska = head.startswith(b"\x1aE\xdf\xa3")
    if not (is_mp4 or is_matroska):
        raise CloudVideoError("云端视频成片不是有效的 MP4/MKV 文件，已拒绝保存")


def _now_text() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "POLL_INTERVAL_SECONDS",
    "TASK_TIMEOUT_SECONDS",
    "CloudVideoService",
    "normalize_cloud_task_status",
    "with_cloud_video_billing_caution",
    "CloudVideoUncertainSubmitError",
]
