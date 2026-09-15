from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse
import requests

from ..provider_bridge import credential_manager, llm_row


def is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


class LlmService:
    DEFAULT_URL = "https://api-inference.modelscope.cn/v1"
    DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"

    @classmethod
    def _runtime_config(cls) -> tuple[str, str, str]:
        row = llm_row()
        if not row.get("enabled"):
            raise ValueError("大模型服务尚未启用，请先在管理后台启用大模型服务。")
        base_url = str(row.get("base_url") or cls.DEFAULT_URL).strip().rstrip("/")
        model = str(row.get("model") or cls.DEFAULT_MODEL).strip()
        encrypted_key = row.get("api_key_encrypted")
        api_key = credential_manager().decrypt(encrypted_key) if encrypted_key else None
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
