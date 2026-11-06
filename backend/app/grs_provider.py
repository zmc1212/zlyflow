from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from .grs_catalog import (
    GRS_PROFILE_GPT_IMAGE_2, GRS_PROFILE_GPT_IMAGE_2_VIP, GRS_PROFILES, PROFILE_LABELS,
    effective_description, guess_profile, is_image_model_id, platform_entry, validate_provider_model,
)
from .grs_client import GrsClient, GrsError
from .grs_composite import DEFAULT_COMPOSITE_PROVIDER_MODEL
from .models import JobMode
from .storage import JobStore, now
from .workflow_registry import image_workflow_from_catalog, mode_key

# 平台标价积分变化很少，进程内 6 小时随余额顺带刷新一次即可。
GRS_COSTS_REFRESH_SECONDS = 6 * 60 * 60.0


class CredentialManager:
    def __init__(self, key: str | None) -> None:
        self._fernet: Fernet | None = None
        self.error: str | None = None
        if not key:
            self.error = "未配置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY"
            return
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (TypeError, ValueError):
            self.error = "ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY 不是有效的 Fernet 密钥"

    @property
    def ready(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise ValueError(self.error or "凭证主密钥不可用")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if not value or self._fernet is None:
            return None
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None


class GrsProviderService:
    def __init__(self, store: JobStore, credential_key: str | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)
        self._balance_refresh_lock = threading.Lock()
        self._balance_refresh_deadline = 0.0
        self._costs_refresh_lock = threading.Lock()
        self._costs_refresh_deadline = 0.0

    def api_key(self) -> str | None:
        return self.credentials.decrypt(self.store.get_grs_settings().get("api_key_encrypted"))

    def reveal_secret(self, field: str) -> str | None:
        """管理页「复制 Key」取回的明文。"""
        if field != "api_key":
            raise ValueError("GRS 图片供应商只支持复制 API Key")
        return self.api_key()

    def availability(self, mode: JobMode | str | None = None) -> tuple[bool, str | None]:
        config = self.store.get_grs_settings()
        if not config["enabled"]:
            return False, "GRS 图片供应商尚未启用，请联系超级管理员。"
        if not self.credentials.ready:
            return False, self.credentials.error
        if not self.api_key():
            return False, "GRS API Key 未配置或无法使用当前主密钥解密。"
        if mode is not None:
            entry = self.store.get_grs_image_model(mode_key(mode))
            if entry is None or not entry["enabled"]:
                return False, "该生图模型已被管理员停用或不存在。"
        return True, None

    def model_enabled(self, provider_model: str) -> bool:
        """目录中是否存在该生图模型且已启用（复合图片工作流按 provider_model 校验）。"""
        return any(
            item["provider_model"] == provider_model and item["enabled"]
            for item in self.store.list_grs_image_models()
        )

    def resolve_composite_model(self, requested: str | None) -> str:
        """复合图片工作流（局部重绘/消除笔/扩图）的实际生图模型。

        这些工作流本身不在 GRS 模型目录里，只有内部 provider_model 指向目录条目；
        请求模型被管理员停用或不存在时，回落到目录默认启用模型，
        避免注册表内置默认值与管理员配置漂移导致任务必然失败。
        """
        enabled = [item for item in self.store.list_grs_image_models() if item["enabled"]]
        if requested and any(item["provider_model"] == requested for item in enabled):
            return requested
        if not enabled:
            return requested or DEFAULT_COMPOSITE_PROVIDER_MODEL
        default = next((item for item in enabled if item["is_default"]), enabled[0])
        return str(default["provider_model"])

    def enabled_image_workflows(self):
        """创作页可见的生图工作流，顺序完全由管理员的目录排序决定。

        「默认模型」不再占据首位：它只表示创作页预选和导演台自动出图使用的模型，
        因此消费方必须读 is_default，不能拿列表位置当默认。
        """
        models = [item for item in self.store.list_grs_image_models() if item["enabled"]]
        models.sort(key=lambda item: (item["sort_order"], item["display_name"]))
        return [image_workflow_from_catalog(item) for item in models]

    def catalog_payload(self) -> dict[str, Any]:
        models = self.store.list_grs_image_models()
        # 与创作页同源：库里存的是历史长句时按当前档位文案回显，避免管理页和下拉描述不一致。
        for row in models:
            row["description"] = effective_description(row)
        return {
            "models": models,
            "profiles": [{"value": key, "label": label} for key, label in PROFILE_LABELS.items()],
        }

    def fetch_platform_models(
        self, *, base_url: str | None = None, api_key: str | None = None,
    ) -> dict[str, Any]:
        """动态拉取 GRS 平台在售模型，并与本地目录对齐。

        平台接口只给模型 ID，能力档（比例/分辨率/画质参数）仍来自内置映射或家族推断，
        因此新模型导入前必须由管理员确认。
        """
        client = self.client(base_url=base_url, api_key=api_key)
        remote = client.list_models()
        # 积分只是展示项：价格接口失败不阻塞模型清单，本轮按目录里已有的数值回显。
        try:
            costs = client.model_costs()
        except Exception:
            costs = {}
        if costs:
            self.store.set_grs_image_model_costs(costs)
            self._costs_refresh_deadline = time.monotonic() + GRS_COSTS_REFRESH_SECONDS
        catalog = {item["provider_model"]: item for item in self.store.list_grs_image_models()}
        models: list[dict[str, Any]] = []
        listed: set[str] = set()
        for provider_model in remote:
            if not is_image_model_id(provider_model) or provider_model in listed:
                continue
            listed.add(provider_model)
            entry = platform_entry(provider_model)
            row = catalog.get(provider_model)
            models.append({
                "provider_model": provider_model,
                "workflow_id": entry["workflow_id"],
                "display_name": (row or entry)["display_name"],
                "profile": (row or entry)["profile"],
                "resolutions": (row or entry)["resolutions"],
                "profile_source": entry["profile_source"],
                "in_catalog": row is not None,
                "enabled": bool(row["enabled"]) if row else False,
                "is_default": bool(row["is_default"]) if row else False,
                "credit_cost": costs.get(provider_model) or (row or {}).get("credit_cost"),
                "description": effective_description(row or entry),
            })
        models.sort(key=lambda item: (item["in_catalog"], item["provider_model"]))
        off_platform = [
            {
                "workflow_id": row["workflow_id"], "provider_model": row["provider_model"],
                "display_name": row["display_name"], "profile": row["profile"],
                "enabled": row["enabled"], "builtin": row["builtin"],
            }
            for row in catalog.values() if row["provider_model"] not in listed
        ]
        off_platform.sort(key=lambda item: item["provider_model"])
        message = None
        if not models:
            message = (
                f"平台 /v1/models 返回 {len(remote)} 个模型，但没有识别出生图模型。"
                "可能是上游新增了命名家族，请改用手动添加并反馈。"
            )
        return {
            "models": models, "off_platform": off_platform,
            "total": len(remote), "fetched_at": now(), "message": message,
        }

    def import_platform_models(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """把管理员勾选的平台模型写入目录；已在目录中的跳过，不覆盖既有配置。"""
        created: list[str] = []
        skipped: list[str] = []
        for item in items:
            provider_model = validate_provider_model(item["provider_model"])
            entry = platform_entry(provider_model)
            profile = item.get("profile") or entry["profile"]
            if profile not in GRS_PROFILES:
                raise ValueError(f"未知的生图能力档: {profile}")
            display_name = str(item.get("display_name") or entry["display_name"]).strip()[:80]
            if not display_name:
                raise ValueError(f"模型 {provider_model} 缺少显示名称")
            try:
                saved = self.store.add_grs_image_model({
                    "provider_model": provider_model,
                    "display_name": display_name,
                    "profile": profile,
                    "resolutions": item.get("resolutions") or entry["resolutions"],
                    "description": str(item.get("description") or "").strip() or entry["description"],
                    "credit_cost": item.get("credit_cost"),
                    "enabled": bool(item.get("enabled", True)),
                })
            except ValueError as error:
                if "已存在" in str(error):
                    skipped.append(provider_model)
                    continue
                raise ValueError(f"{provider_model}: {error}") from error
            created.append(saved["workflow_id"])
        if not created and not skipped:
            raise ValueError("没有可导入的模型")
        # 勾选的价格来自拉取那一刻的快照；新导入的行可能不在当时的目录里，补一次强制刷新。
        if created:
            self.refresh_model_costs(force=True)
        return {"created": created, "skipped": skipped, **self.catalog_payload()}

    def public_config(self) -> dict[str, Any]:
        config = self.store.get_grs_settings()
        api_key = self.api_key()
        available, reason = self.availability()
        masked = None
        if api_key:
            masked = f"{api_key[:3]}{'*' * max(5, min(16, len(api_key) - 5))}{api_key[-2:]}" if len(api_key) > 5 else "*****"
        models = self.store.list_grs_image_models()
        gpt = next((item for item in models if item["workflow_id"] == "grs-gpt-image-2"), None)
        vip = next((item for item in models if item["workflow_id"] == "grs-gpt-image-2-vip"), None)
        enabled_standard = [
            item["provider_model"] for item in models
            if item["enabled"] and item["profile"] == GRS_PROFILE_GPT_IMAGE_2
        ]
        enabled_vip = [
            item["provider_model"] for item in models
            if item["enabled"] and item["profile"] == GRS_PROFILE_GPT_IMAGE_2_VIP
        ]
        return {
            "enabled": config["enabled"],
            "base_url": config["base_url"],
            "api_key_masked": masked,
            "has_api_key": bool(config.get("api_key_encrypted")),
            "credential_ready": self.credentials.ready,
            "gpt_image_2_enabled": bool(gpt and gpt["enabled"]),
            "gpt_image_2_vip_enabled": bool(vip and vip["enabled"]),
            "models": ",".join(enabled_standard) or "gpt-image-2",
            "vip_models": ",".join(enabled_vip) or "gpt-image-2-vip",
            "last_test_status": config.get("last_test_status"),
            "last_test_message": config.get("last_test_message"),
            "last_test_at": config.get("last_test_at"),
            "last_balance": config.get("last_balance"),
            "last_balance_at": config.get("last_balance_at"),
            "available": available,
            "unavailable_reason": reason,
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        values = {
            key: value for key, value in payload.items()
            if key not in {"api_key"}
        }
        parsed = urlparse(str(values.get("base_url", "")))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("GRS Base URL 必须是无内嵌凭证的 HTTPS 地址")
        values["base_url"] = str(values["base_url"]).rstrip("/")
        api_key = payload.get("api_key")
        if api_key is not None and api_key.strip():
            values["api_key_encrypted"] = self.credentials.encrypt(api_key.strip())
        self.store.update_grs_settings(**values)
        return self.public_config()

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("GRS Base URL 必须是无内嵌凭证的 HTTPS 地址")
        return base_url.rstrip("/")

    def client(self, *, base_url: str | None = None, api_key: str | None = None) -> GrsClient:
        config = self.store.get_grs_settings()
        effective_key = api_key.strip() if api_key and api_key.strip() else self.api_key()
        if not effective_key:
            if not self.credentials.ready:
                raise GrsError(self.credentials.error or "凭证主密钥不可用")
            raise GrsError("尚未保存 GRS API Key，请输入 API Key 后测试或保存配置")
        effective_url = self._validate_base_url((base_url or config["base_url"]).strip())
        return GrsClient(effective_url, effective_key)

    def test_connection(self, *, base_url: str | None = None, api_key: str | None = None) -> dict[str, Any]:
        timestamp = now()
        try:
            credits = self.client(base_url=base_url, api_key=api_key).balance()
            self.store.update_grs_settings(
                last_test_status="success", last_test_message="连接成功", last_test_at=timestamp,
                last_balance=credits, last_balance_at=timestamp,
            )
        except Exception as error:
            self.store.update_grs_settings(
                last_test_status="failed", last_test_message=str(error), last_test_at=timestamp,
            )
            raise
        return self.public_config()

    def balance(self) -> tuple[float, str]:
        credits = self.client().balance()
        timestamp = now()
        self.store.update_grs_settings(last_balance=credits, last_balance_at=timestamp)
        return credits, timestamp

    def balance_snapshot(self) -> dict[str, float | str | None]:
        config = self.store.get_grs_settings()
        return {
            "credits": config.get("last_balance"),
            "queried_at": config.get("last_balance_at"),
        }

    def refresh_model_costs(self, *, force: bool = False) -> int:
        """把平台标价积分同步进目录，返回写入的行数。

        积分只用于创作页与管理页展示，不影响提交参数，因此上游价格接口失败时静默
        保留上一次数值；同一进程内按 `GRS_COSTS_REFRESH_SECONDS` 限频，管理员手动
        拉取/导入模型时用 force 立即刷新。
        """
        with self._costs_refresh_lock:
            if not force and time.monotonic() < self._costs_refresh_deadline:
                return 0
            self._costs_refresh_deadline = time.monotonic() + GRS_COSTS_REFRESH_SECONDS
        try:
            costs = self.client().model_costs()
        except Exception:
            return 0
        return self.store.set_grs_image_model_costs(costs)

    def refresh_balance_snapshot(self, min_interval_seconds: float = 10.0) -> dict[str, float | str | None]:
        with self._balance_refresh_lock:
            snapshot = self.balance_snapshot()
            if time.monotonic() < self._balance_refresh_deadline:
                return snapshot
            self._balance_refresh_deadline = time.monotonic() + max(1.0, min_interval_seconds)
            available, reason = self.availability()
            if not available:
                return {**snapshot, "refresh_error": reason or "GRS 余额暂不可用"}
            try:
                self.balance()
            except Exception:
                return {**snapshot, "refresh_error": "GRS 余额暂不可用"}
            # 创作页加载就会走到这里，顺带把平台标价积分带上（6 小时限频，通常直接跳过）
            self.refresh_model_costs()
            return self.balance_snapshot()
