from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse
import requests

from ..config import settings
from ..crypto import CredentialManager
from ..db import execute_sql, now_str, query_one
from ..models import (
    LlmCatalogModelItem,
    LlmCatalogResponse,
    LlmConfigResponse,
    LlmTestRequest,
    LlmUpdateRequest,
)


def get_credential_manager() -> CredentialManager:
    return CredentialManager(settings.credential_key)


def is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


class LlmService:
    DEFAULT_URL = "https://api-inference.modelscope.cn/v1"
    DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"

    @classmethod
    def _runtime_config(cls) -> tuple[str, str, str]:
        row = query_one("SELECT * FROM ai_llm_provider_settings WHERE id = 1") or {}
        if not row.get("enabled"):
            raise ValueError("大模型服务尚未启用，请先前往系统设置启用。")
        base_url = str(row.get("base_url") or cls.DEFAULT_URL).strip().rstrip("/")
        model = str(row.get("model") or cls.DEFAULT_MODEL).strip()
        encrypted_key = row.get("api_key_encrypted")
        api_key = get_credential_manager().decrypt(encrypted_key) if encrypted_key else None
        if not api_key and is_local_base_url(base_url):
            api_key = "ollama"
        if not base_url or not model or not api_key:
            raise ValueError("大模型配置不完整，请检查服务地址、模型和 API Key。")
        return base_url, model, api_key

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        text = str(content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            value = json.loads(text)
        except json.JSONDecodeError as err:
            raise ValueError(f"大模型未返回有效 JSON：{err}") from err
        if not isinstance(value, dict):
            raise ValueError("大模型返回内容必须是 JSON 对象。")
        return value

    @classmethod
    def generate_character_content(
        cls,
        requirement: str,
        *,
        name: str = "",
        role: str = "",
    ) -> dict[str, str]:
        brief = str(requirement or "").strip()
        if not brief:
            raise ValueError("请输入角色简洁需求。")
        if len(brief) > 1000:
            raise ValueError("角色需求不能超过 1000 个字符。")
        base_url, model, api_key = cls._runtime_config()
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是影视角色视觉设定师。根据用户的简洁需求生成可直接用于角色资产库的中文内容。"
                            "description 必须清楚描述性别、年龄感、脸型五官、肤色、发型、身形、气质，以及服装款式、"
                            "内外层次、颜色、面料、鞋履、配饰和时代特征；不得混入互相冲突的时代、年龄或服装。"
                            "visual_prompt 必须是单人全身角色设定图提示词，完整复述关键容貌与服装，要求从头到脚、"
                            "自然站姿、中性纯色背景、五官清晰、服装细节清晰、无文字、无拼图、无其他人物。"
                            "只返回 JSON 对象，格式严格为："
                            '{"description":"...","visual_prompt":"..."}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"角色名称：{str(name or '').strip() or '未命名'}\n"
                            f"角色定位：{str(role or '').strip() or '未指定'}\n"
                            f"简洁需求：{brief}"
                        ),
                    },
                ],
                "temperature": 0.4,
                "max_tokens": 1200,
                "response_format": {"type": "json_object"},
            },
            timeout=120,
        )
        if not response.ok:
            raise RuntimeError(f"AI 生成角色内容失败，HTTP {response.status_code}: {response.text[:300]}")
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = cls._parse_json_object(content)
        description = str(parsed.get("description") or "").strip()
        visual_prompt = str(parsed.get("visual_prompt") or "").strip()
        if not description or not visual_prompt:
            raise ValueError("大模型返回缺少容貌服装描述或生图提示词，请重试。")
        return {
            "description": description,
            "visual_prompt": visual_prompt,
            "model": model,
        }

    @classmethod
    def get_config(cls) -> LlmConfigResponse:
        cred = get_credential_manager()
        row = query_one("SELECT * FROM ai_llm_provider_settings WHERE id = 1")
        if not row:
            return LlmConfigResponse(
                enabled=False,
                base_url=cls.DEFAULT_URL,
                model=cls.DEFAULT_MODEL,
                has_api_key=False,
                credential_ready=cred.ready,
            )

        encrypted_key = row.get("api_key_encrypted")
        decrypted_key = cred.decrypt(encrypted_key) if encrypted_key else None
        if not decrypted_key and is_local_base_url(row.get("base_url") or ""):
            decrypted_key = "ollama"

        available = bool(row["enabled"] and (cred.ready or is_local_base_url(row.get("base_url") or "")) and decrypted_key and row.get("model"))
        reason = None
        if not row["enabled"]:
            reason = "大模型服务尚未启用。"
        elif not decrypted_key:
            reason = "大模型 API Key / Token 未配置。"
        elif not row.get("model"):
            reason = "未配置模型名称。"

        return LlmConfigResponse(
            enabled=bool(row["enabled"]),
            base_url=row["base_url"] or cls.DEFAULT_URL,
            model=row["model"] or cls.DEFAULT_MODEL,
            api_key_masked=cred.mask(decrypted_key) if decrypted_key != "ollama" else "ollama (本地免密)",
            has_api_key=bool(encrypted_key or is_local_base_url(row.get("base_url") or "")),
            credential_ready=cred.ready,
            available=available,
            unavailable_reason=reason,
            last_test_status=row.get("last_test_status"),
            last_test_message=row.get("last_test_message"),
            last_test_at=row.get("last_test_at"),
        )

    @classmethod
    def update_config(cls, payload: LlmUpdateRequest) -> LlmConfigResponse:
        cred = get_credential_manager()
        timestamp = now_str()
        current = query_one("SELECT * FROM ai_llm_provider_settings WHERE id = 1") or {}

        encrypted_key = current.get("api_key_encrypted")
        if payload.api_key and payload.api_key.strip():
            encrypted_key = cred.encrypt(payload.api_key.strip())

        execute_sql(
            """
            INSERT INTO ai_llm_provider_settings (id, enabled, base_url, model, api_key_encrypted, updated_at)
            VALUES (1, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                enabled = VALUES(enabled),
                base_url = VALUES(base_url),
                model = VALUES(model),
                api_key_encrypted = VALUES(api_key_encrypted),
                updated_at = VALUES(updated_at)
            """,
            (
                1 if payload.enabled else 0,
                payload.base_url.rstrip("/"),
                payload.model.strip(),
                encrypted_key,
                timestamp,
            ),
        )
        return cls.get_config()

    @classmethod
    def test_connection(cls, payload: LlmTestRequest | None = None) -> LlmConfigResponse:
        cred = get_credential_manager()
        current = query_one("SELECT * FROM ai_llm_provider_settings WHERE id = 1") or {}

        base_url = (payload.base_url if payload and payload.base_url else current.get("base_url") or cls.DEFAULT_URL).rstrip("/")
        model = (payload.model if payload and payload.model else current.get("model") or cls.DEFAULT_MODEL).strip()

        api_key = payload.api_key.strip() if payload and payload.api_key and payload.api_key.strip() else None
        if not api_key and current.get("api_key_encrypted"):
            api_key = cred.decrypt(current["api_key_encrypted"])
        if not api_key and is_local_base_url(base_url):
            api_key = "ollama"

        if not api_key:
            raise RuntimeError("测试连接需要提供有效的 API Key / Token")

        timestamp = now_str()
        timeout = 90.0 if is_local_base_url(base_url) else 20.0
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "请只回复两个字：收到"}],
                    "max_tokens": 16,
                },
                timeout=timeout,
            )
            if not resp.ok:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip() or "成功响应"
            status = "成功"
            msg = f"连接成功，模型响应: {reply}"
        except Exception as err:
            status = "失败"
            msg = str(err)

        execute_sql(
            """
            UPDATE ai_llm_provider_settings
            SET last_test_status = %s, last_test_message = %s, last_test_at = %s, updated_at = %s
            WHERE id = 1
            """,
            (status, msg, timestamp, timestamp),
        )

        if status == "失败":
            raise RuntimeError(f"大模型测试连接失败: {msg}")

        return cls.get_config()

    @classmethod
    def list_models_catalog(cls, payload: LlmTestRequest | None = None) -> LlmCatalogResponse:
        cred = get_credential_manager()
        current = query_one("SELECT * FROM ai_llm_provider_settings WHERE id = 1") or {}

        base_url = (payload.base_url if payload and payload.base_url else current.get("base_url") or cls.DEFAULT_URL).rstrip("/")
        api_key = payload.api_key.strip() if payload and payload.api_key and payload.api_key.strip() else None
        if not api_key and current.get("api_key_encrypted"):
            api_key = cred.decrypt(current["api_key_encrypted"])
        if not api_key and is_local_base_url(base_url):
            api_key = "ollama"

        if not api_key:
            raise RuntimeError("拉取可用模型目录需要提供有效 API Key")

        try:
            resp = requests.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15,
            )
            if not resp.ok:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            raw_models = data.get("data") if isinstance(data.get("data"), list) else data.get("models", [])
            items = []
            for item in raw_models:
                m_id = item.get("id") or item.get("name")
                if m_id:
                    items.append(
                        LlmCatalogModelItem(
                            id=m_id,
                            label=m_id,
                            owned_by=item.get("owned_by"),
                        )
                    )
            return LlmCatalogResponse(models=items, provider="upstream", message=f"成功获取 {len(items)} 个模型")
        except Exception as err:
            return LlmCatalogResponse(models=[], provider="upstream", message=f"拉取模型列表失败: {err}")
