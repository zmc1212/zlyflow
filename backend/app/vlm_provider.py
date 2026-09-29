from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .grs_provider import CredentialManager
from .llm_client import (
    LLM_TEST_TIMEOUT_SECONDS,
    OpenAICompatibleClient,
    LlmError,
    catalog_provider_key,
    normalize_api_key,
    summarize_llm_test_reply,
)
from .llm_provider import LlmProviderService, is_local_base_url
from .storage import JobStore, now, provider_profile_id
from .vision_capability import (
    capability_fields, row_fingerprint, probe_fields, unknown_vision_fields, sanitize_probe_error, ensure_vision_capability,
    probe_vision_capability,
    row_supports_vision,
)
from .vision_runtime import overlay_vlm_credentials, resolve_analysis_endpoint


DEFAULT_VLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_VLM_MODEL = "glm-4v-flash"
VLM_PROFILE_IDS = {"modelink", "zhipu", "dashscope", "modelscope", "siliconflow", "ollama", "custom"}

ZHIPU_VISION_CATALOG = [
    {"id": "glm-4.6v-flash", "label": "GLM-4.6V-Flash（免费）", "free": True},
    {"id": "glm-4v-flash", "label": "GLM-4V-Flash（免费）", "free": True},
    {"id": "glm-4.1v-thinking-flash", "label": "GLM-4.1V-Thinking-Flash（免费）", "free": True},
    {"id": "glm-4v", "label": "GLM-4V", "free": False},
    {"id": "glm-4v-plus", "label": "GLM-4V-Plus", "free": False},
]
VLM_UNAVAILABLE_MESSAGE = "视觉模型尚未启用。请在管理设置 → VLM 视觉模型 中配置后再使用看图功能。"
VLM_NOT_VISION_MESSAGE = "当前连接尚未验证支持看图。请在管理设置 → VLM 视觉模型 中重新探测视觉能力。"
ANALYSIS_UNAVAILABLE_MESSAGE = (
    "视觉分析不可用。请在管理设置 → VLM 视觉模型 配置看图模型；"
    "或在 LLM 页验证多模态模型的视觉能力。"
)


def _mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 5:
        return "*****"
    return f"{api_key[:3]}{'*' * max(5, min(16, len(api_key) - 5))}{api_key[-2:]}"


class VlmProviderService:
    def __init__(self, store: JobStore, credential_key: str | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)
        self.llm_connection = LlmProviderService(store, credential_key)

    def _effective_config(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = dict(config or self.store.get_vlm_settings())
        if settings.get("use_llm_credentials"):
            return overlay_vlm_credentials(settings, self.store.get_llm_settings())
        return settings

    def _reuse_model_guard(self, config: dict[str, Any] | None = None) -> None:
        settings = dict(config or self.store.get_vlm_settings())
        if settings.get("use_llm_credentials") and not row_supports_vision(self._effective_config(settings)):
            raise ValueError("复用连接的模型与地址尚未通过视觉验证，请测试当前组合。")

    def _profile_for_payload(self, payload: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
        current = self.store.get_vlm_settings()
        requested = str((payload or {}).get("profile_id") or "").strip()
        profile_id = requested or str(current.get("profile_id") or provider_profile_id(current.get("base_url"), vision=True))
        profile = self.store.get_vlm_profile(profile_id) if requested else None
        return profile_id, (profile or {}) if requested else current

    def api_key(self, config: dict[str, Any] | None = None) -> str | None:
        settings = self._effective_config(config)
        decrypted = self.credentials.decrypt(settings.get("api_key_encrypted"))
        if decrypted:
            return decrypted
        if is_local_base_url(self.base_url(config)):
            return "ollama"
        return None

    def base_url(self, config: dict[str, Any] | None = None) -> str:
        settings = self._effective_config(config)
        return str(settings.get("base_url") or "").rstrip("/")

    def availability(self) -> tuple[bool, str | None]:
        config = self.store.get_vlm_settings()
        if not config["enabled"]:
            return False, VLM_UNAVAILABLE_MESSAGE
        if not is_local_base_url(self.base_url(config)) and not self.credentials.ready:
            return False, self.credentials.error or "凭证主密钥不可用"
        if not self.api_key(config):
            return False, "视觉模型 API Key / Token 未配置或无法解密。可勾选复用大模型凭据。"
        if not self._effective_config(config).get("model"):
            return False, "未配置视觉模型名称 (Model Name)。"
        # Reuse follows the entire LLM connection, including its model/evidence.
        try:
            self._reuse_model_guard(config)
        except ValueError as exc:
            return False, str(exc)
        # 可用性以持久化三态为准；名字猜测仅在未探测时给出“待验证”提示，不再一票否决。
        effective = self._effective_config(config)
        if not row_supports_vision(effective):
            return False, VLM_NOT_VISION_MESSAGE
        return True, None

    def public_config(self) -> dict[str, Any]:
        config = self.store.get_vlm_settings()
        api_key = self.api_key(config)
        available, reason = self.availability()
        effective = self._effective_config(config)
        return {
            "profile_id": str(config.get("profile_id") or provider_profile_id(config.get("base_url"), vision=True)),
            "enabled": config["enabled"],
            "use_llm_credentials": bool(config.get("use_llm_credentials")),
            "base_url": self.base_url(config),
            "model": effective.get("model") or "",
            "independent_base_url": config.get("base_url"),
            "independent_model": config.get("model"),
            "connection_source": "llm" if config.get("use_llm_credentials") else "vlm",
            "api_key_masked": _mask_api_key(api_key),
            "has_api_key": bool(api_key),
            "credential_ready": self.credentials.ready,
            "last_test_status": effective.get("last_test_status"),
            "last_test_message": effective.get("last_test_message"),
            "last_test_at": effective.get("last_test_at"),
            "available": available,
            "unavailable_reason": reason,
            "vision_capability": config.get("vision_capability") or "unknown",
            "vision_capability_source": config.get("vision_capability_source"),
            "vision_capability_checked_at": config.get("vision_capability_checked_at"),
            "vision_capability_message": config.get("vision_capability_message"),
            **{k: v for k, v in capability_fields(effective).items() if k != "vision_capability_fingerprint"},
            "supports_vision": row_supports_vision(effective),
        }

    def profiles_config(self) -> dict[str, Any]:
        current = self.store.get_vlm_settings()
        rows = []
        for profile in self.store.list_vlm_profiles():
            stored_key = self.credentials.decrypt(profile.get("api_key_encrypted"))
            rows.append({
                "profile_id": profile["profile_id"],
                "configured": True,
                "base_url": profile["base_url"],
                "model": profile["model"],
                "use_llm_credentials": bool(profile.get("use_llm_credentials")),
                "api_key_masked": _mask_api_key(stored_key),
                "has_api_key": bool(profile.get("api_key_encrypted")),
                "last_test_status": profile.get("last_test_status"),
                "last_test_message": profile.get("last_test_message"),
                "last_test_at": profile.get("last_test_at"),
            })
        return {
            "active_profile_id": str(current.get("profile_id") or provider_profile_id(current.get("base_url"), vision=True)),
            "profiles": rows,
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("use_llm_credentials"):
            # Keep the independent VLM profile intact so turning reuse off is reversible.
            current = self.store.get_vlm_settings()
            candidate = {**current, "use_llm_credentials": True}
            effective = self._effective_config(candidate)
            key = self.api_key(candidate)
            if not key or not effective.get("base_url") or not effective.get("model"):
                raise ValueError("复用连接缺少大模型地址、模型或密钥，请先配置 LLM 大模型。")
            verified = ensure_vision_capability(effective, key)
            # Evidence belongs to the actual LLM endpoint, not the retained VLM profile.
            latest_llm = self.store.get_llm_settings()
            if row_fingerprint(latest_llm) != row_fingerprint(effective):
                raise ValueError("大模型连接已在验证期间变更，请刷新后重试。")
            evidence = {name: verified.get(name) for name in unknown_vision_fields()}
            if any(latest_llm.get(name) != value for name, value in evidence.items()):
                self.store.update_llm_profile(str(latest_llm["profile_id"]), evidence, activate=True)
            if not row_supports_vision(verified):
                raise ValueError("复用大模型连接尚未通过视觉验证：" + str(verified.get("vision_capability_message") or "请到 LLM 页重新探测"))
            profile_id = str(current.get("profile_id") or provider_profile_id(current.get("base_url"), vision=True))
            self.store.update_vlm_profile(profile_id, {"use_llm_credentials": True, "enabled": payload.get("enabled", current.get("enabled", False))}, activate=True)
            return self.public_config()
        values = {key: value for key, value in payload.items() if key not in {"api_key", "profile_id"}}
        base_url_str = str(values.get("base_url", "")).strip()
        if not base_url_str:
            base_url_str = DEFAULT_VLM_BASE_URL
        parsed = urlparse(base_url_str)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Base URL 必须是有效的 HTTP 或 HTTPS 地址")
        values["base_url"] = base_url_str.rstrip("/")

        model_name = str(values.get("model", "")).strip()
        if not model_name:
            model_name = DEFAULT_VLM_MODEL
        values["model"] = model_name

        profile_id = str(payload.get("profile_id") or provider_profile_id(values["base_url"], vision=True)).strip()
        if profile_id not in VLM_PROFILE_IDS:
            raise ValueError("未知的 VLM 服务预设")

        api_key = normalize_api_key(payload.get("api_key"))
        if api_key:
            if not self.credentials.ready:
                raise ValueError(self.credentials.error or "凭证主密钥不可用")
            values["api_key_encrypted"] = self.credentials.encrypt(api_key)
        values["use_llm_credentials"] = False
        from .vision_capability import evidence_for_saved_connection
        previous = self.store.get_vlm_profile(profile_id) or {}
        candidate = {**previous, **values, "profile_id": profile_id}
        values.update(evidence_for_saved_connection(candidate, self.api_key(candidate),
                                                    previous, self.api_key(previous) if previous else None))
        self.store.update_vlm_profile(profile_id, values, activate=True)
        return self.public_config()

    def test(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        profile_id, config = self._profile_for_payload(payload)
        reuse = (payload or {}).get("use_llm_credentials")
        if reuse is None:
            reuse = config.get("use_llm_credentials")
        if reuse:
            result = self.llm_connection.test()
            if not result.get("supports_vision"):
                raise ValueError("复用大模型连接尚未通过视觉验证：" + str(result.get("vision_capability_message") or "请到 LLM 页重新探测"))
            shared = {key: result.get(key) for key in ("base_url", "model", "supports_vision", "last_test_status", "last_test_message", "last_test_at", *unknown_vision_fields()) if key != "vision_capability_fingerprint"}
            return {**self.public_config(), **shared, "use_llm_credentials": True, "connection_source": "llm"}
        config = {**config, "profile_id": profile_id}
        submitted = payload or {}
        candidate = {**config, **{k: v for k, v in submitted.items() if k in {"base_url", "model", "use_llm_credentials"} and v is not None}}
        candidate["base_url"] = str(candidate.get("base_url") or "").strip().rstrip("/")
        candidate["model"] = str(candidate.get("model") or "").strip()
        effective = self._effective_config(candidate)
        submitted_key = str(submitted.get("api_key") or "").strip()
        saved_key = self.api_key(candidate)
        api_key = saved_key if candidate.get("use_llm_credentials") else submitted_key or saved_key
        if not api_key and is_local_base_url(effective.get("base_url") or ""):
            api_key = "ollama"
        if not api_key or not effective.get("base_url") or not effective.get("model"):
            raise ValueError("测试连接需要完整的地址、模型和 API Key / Token")
        # Unsaved form inputs must not certify a different saved endpoint/key.
        persisted = self._effective_config(config)
        matches = row_fingerprint(effective) == row_fingerprint(persisted) and api_key == self.api_key(config)
        probe_row = dict(effective)
        if not matches:
            probe_row["api_key_encrypted"] = None
            probe_row["api_key"] = api_key
        client = OpenAICompatibleClient(base_url=effective["base_url"], api_key=api_key)
        test_time = now()
        fields = unknown_vision_fields()
        try:
            reply = client.test_connection(model=effective["model"], timeout=LLM_TEST_TIMEOUT_SECONDS)
            status, message = "成功", sanitize_probe_error(summarize_llm_test_reply(reply), api_key)
        except Exception as exc:
            status, message = "失败", sanitize_probe_error(exc, api_key)
        if status == "成功":
            result = probe_vision_capability(base_url=effective["base_url"], api_key=api_key, model=effective["model"])
            fields = probe_fields(probe_row, result)
        test_fields = {"last_test_status": status, "last_test_message": message, "last_test_at": test_time}
        if matches:
            # Recheck after network I/O; a concurrent config edit must win.
            latest = self.store.get_vlm_profile(profile_id) or {}
            latest_effective = self._effective_config(latest)
            if row_fingerprint(latest_effective) == row_fingerprint(effective):
                active_id = str(self.store.get_vlm_settings().get("profile_id") or "")
                self.store.update_vlm_profile(profile_id, {**test_fields, **fields}, activate=profile_id == active_id)
        if status != "成功":
            raise LlmError(f"连接测试失败：{message}")
        if not matches:
            fields["vision_capability_message"] = str(fields.get("vision_capability_message") or "") + "（当前输入未保存，结果不用于已保存配置）"
        return {**self.public_config(), "profile_id": profile_id, "base_url": effective["base_url"],
                "model": effective["model"], **test_fields,
                **{k: v for k, v in fields.items() if k != "vision_capability_fingerprint"},
                "supports_vision": fields["vision_capability"] == "supported"}

    def list_catalog(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        _profile_id, config = self._profile_for_payload(payload)
        requested_reuse = (payload or {}).get("use_llm_credentials")
        reuse = bool(config.get("use_llm_credentials") if requested_reuse is None else requested_reuse)
        base_url = (payload.get("base_url") if payload else None) or self.base_url({**config, "use_llm_credentials": reuse})
        if reuse:
            base_url = self.base_url({**config, "use_llm_credentials": True})
        submitted_key = normalize_api_key(payload.get("api_key")) if payload else None
        api_key = self.api_key({**config, "use_llm_credentials": True}) if reuse else submitted_key or self.api_key({**config, "use_llm_credentials": False})
        if not api_key and is_local_base_url(base_url or ""):
            api_key = "ollama"
        if not api_key:
            raise LlmError("拉取模型目录需要提供有效的 API Key / Token")
        if not base_url:
            raise LlmError("Base URL 不能为空")
        free_only = False if payload is None else bool(payload.get("free_only", False))
        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        catalog = client.list_model_catalog(free_only=free_only)
        vision_models = [
            row for row in (catalog.get("models") or [])
            if isinstance(row, dict)
        ]
        if catalog_provider_key(base_url or "") == "zhipu":
            seen = {str(row.get("id") or "") for row in vision_models}
            for row in ZHIPU_VISION_CATALOG:
                if row["id"] not in seen:
                    vision_models.insert(0, dict(row))
                    seen.add(row["id"])
        message = catalog.get("message")
        if not vision_models:
            message = "上游未返回模型目录，可手填模型 ID 并探测视觉能力；模型名称不能证明是否支持图片。"
        return {
            "models": vision_models,
            "provider": catalog.get("provider") or "custom",
            "free_only": free_only,
            "message": message,
        }

    def _analysis_endpoint(self):
        return resolve_analysis_endpoint(
            self.store.get_llm_settings(),
            self.store.get_vlm_settings(),
            self.credentials.decrypt,
            probe_unknown=True,
        )

    def analyze_subject(
        self,
        *,
        image_data_url: str,
        kind: str,
        name: str,
    ) -> str:
        endpoint = self._analysis_endpoint()
        if endpoint is None:
            raise LlmError(ANALYSIS_UNAVAILABLE_MESSAGE)
        client = OpenAICompatibleClient(base_url=endpoint.base_url, api_key=endpoint.api_key)
        return client.analyze_subject(
            image_data_url=image_data_url,
            kind=kind,
            name=name,
            model=endpoint.model,
        )

    def analyze_video_shot(
        self,
        *,
        frames: list[str],
        shot_number: int,
        duration_sec: float,
        art_style: str = "",
    ) -> dict[str, Any]:
        endpoint = self._analysis_endpoint()
        if endpoint is None:
            raise LlmError(ANALYSIS_UNAVAILABLE_MESSAGE)
        client = OpenAICompatibleClient(base_url=endpoint.base_url, api_key=endpoint.api_key)
        return client.analyze_video_shot(
            frames=frames,
            shot_number=shot_number,
            duration_sec=duration_sec,
            art_style=art_style,
            model=endpoint.model,
        )

    def vision_model_name(self) -> str | None:
        endpoint = self._analysis_endpoint()
        return endpoint.model if endpoint is not None else None
