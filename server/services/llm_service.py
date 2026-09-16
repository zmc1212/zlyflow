from __future__ import annotations

import json
import re
from pathlib import Path
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


H3_SKILL_DIR = Path(__file__).resolve().parents[2] / ".agents" / "skills" / "h3-prompt-writing"
H3_REF_SECTIONS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)
H3_BASE_SECTIONS = (
    "integrated_multimodal_description",
    "overall_soundscape",
    "non_diegetic_music",
)


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
    def _chat_json(cls, system: str, user: str, *, max_tokens: int = 1600, temperature: float = 0.2) -> dict[str, Any]:
        base_url, model, api_key = cls._runtime_config()
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=180,
        )
        if not response.ok:
            raise RuntimeError(f"大模型调用失败，HTTP {response.status_code}: {response.text[:300]}")
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = cls._parse_json_object(content)
        parsed["_model"] = model
        return parsed

    @classmethod
    def enrich_one_character(cls, character: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = context or {}
        compact = {
            "name": character.get("name") or "",
            "aliases": character.get("aliases") or "",
            "role": character.get("role") or "",
            "role_position": character.get("role_position") or "",
            "gender": character.get("gender") or "",
            "age": character.get("age") or "",
            "age_group": character.get("age_group") or "",
            "description": (character.get("description") or "")[:800],
            "face_prompt": character.get("face_prompt") or "",
            "body_type": character.get("body_type") or "",
            "art_style_id": character.get("art_style_id") or "",
            "visual_style": character.get("visual_style") or "",
            "ethnicity": character.get("ethnicity") or "",
            "visual_prompt": (character.get("visual_prompt") or "")[:500],
            "looks": character.get("looks") or [],
        }
        parsed = cls._chat_json(
            (
                "你是影视角色设定补全助手。只分析这一个角色，补全缺失字段；已有非空字段尽量保留，不得改名。"
                "aliases 用英文逗号分隔，不要重复姓名本身。"
                "role_position 只能是：主角、反派/观察、配角、龙套、旁白。"
                "age_group 只能是：幼年、少年、青年、中年、老年。"
                "gender 只能是：男、女、未指定。"
                "body_type 只能是：纤细、苗条、标准、精悍、健壮、魁梧。"
                "art_style_id 只能是：chinese_period_drama、chinese_modern_drama、guoman_fantasy、anime、western_realistic、western_cartoon。"
                "visual_style 只能是：realistic、ancient、modern、fantasy、cyberpunk。"
                "ethnicity 默认 Chinese。"
                "face_prompt 必须是头像生图用的中文面部描述，含性别、年龄段、发型、眉眼、肤色、脸型，不要写服装。"
                "description 为完整人物小传。"
                "visual_prompt 为单人全身设定图提示词。"
                "avatar_prompt 为面部特写提示词。"
                "looks 若有多造型，保留 name，补全 description 与 visual_prompt。"
                "只返回一个 JSON 对象，不要包数组。"
            ),
            (
                f"剧目：{ctx.get('title') or '未命名'}\n"
                f"类型：{ctx.get('genre') or ''}\n"
                f"项目画风：{ctx.get('project_style') or ''}\n"
                f"视觉风格：{ctx.get('visual_style') or ''}\n"
                f"角色草稿：{json.dumps(compact, ensure_ascii=False)}"
            ),
            max_tokens=1800,
        )
        parsed.pop("_model", None)
        return parsed

    @classmethod
    def enrich_one_scene(cls, scene: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = context or {}
        compact = {
            "name": scene.get("name") or "",
            "type": scene.get("type") or "",
            "description": (scene.get("description") or "")[:600],
            "elements": scene.get("elements") or [],
        }
        parsed = cls._chat_json(
            (
                "你是影视场景设定补全助手。只分析这一个场景。"
                "scene_type 只能是 interior 或 exterior。"
                "description 写清空间、材质、光线、时代。"
                "environment_prompt 为可直接生图的空镜提示词，无人物、无文字。"
                "visual_style 只能是：realistic、ancient、modern、fantasy、cyberpunk。"
                "不得改名。只返回一个 JSON 对象。"
            ),
            (
                f"剧目：{ctx.get('title') or '未命名'}\n"
                f"项目画风：{ctx.get('project_style') or ''}\n"
                f"场景草稿：{json.dumps(compact, ensure_ascii=False)}"
            ),
            max_tokens=1200,
        )
        parsed.pop("_model", None)
        return parsed

    @classmethod
    def enrich_one_prop(cls, prop: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = context or {}
        compact = {
            "name": prop.get("name") or "",
            "kind": prop.get("kind") or "",
            "related_character": prop.get("related_character") or "",
            "description": (prop.get("description") or "")[:400],
        }
        parsed = cls._chat_json(
            (
                "你是影视道具设定补全助手。只分析这一个道具。"
                "prop_type 只能是：weapon、accessory、artifact、document、furniture、object。"
                "owner 填写所属角色名，没有则空字符串。"
                "description 写材质、年代、用途。"
                "visual_prompt 为静物道具设定图提示词，无人物、无文字。"
                "不得改名。只返回一个 JSON 对象。"
            ),
            (
                f"剧目：{ctx.get('title') or '未命名'}\n"
                f"道具草稿：{json.dumps(compact, ensure_ascii=False)}"
            ),
            max_tokens=900,
        )
        parsed.pop("_model", None)
        return parsed

    @classmethod
    def enrich_one_shot(cls, shot: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = context or {}
        compact = {
            "shot_num": shot.get("shot_num") or shot.get("sequence"),
            "title": shot.get("title") or shot.get("heading") or "",
            "characters": shot.get("characters") or [],
            "speaker": shot.get("speaker") or "",
            "scene": shot.get("scene") or "",
            "props": shot.get("props") or [],
            "action": (shot.get("action") or "")[:400],
            "camera": shot.get("camera") or "",
            "dialogue": (shot.get("dialogue") or "")[:400],
            "visual_prompt": (shot.get("visual_prompt") or "")[:400],
            "raw_content": (shot.get("raw_content") or "")[:600],
        }
        roster = ctx.get("characters") or []
        parsed = cls._chat_json(
            (
                "你是分镜补全助手。只分析这一个镜头，把字段补全。"
                "speaker 必须是角色名单中的姓名，不能写年龄或现代/古代前缀。"
                "characters 只能使用角色名单中的姓名。"
                "character_looks 为 {角色名: 造型名}，造型名必须来自该角色的 looks。"
                "camera 只能是：特写、中景、全景、俯视全景、仰拍微距。"
                "time_of_day 只能是：日、夜、清晨、黄昏、室内、室外。"
                "video_duration 用数字字符串，默认 10。"
                "visual_prompt 为该镜头生图提示词，写实电影感，无字幕文字。"
                "video_prompt_zh 为该镜头视频动作提示。"
                "heading 格式：标题 · 场景 · 景别。"
                "只返回一个 JSON 对象。"
            ),
            (
                f"剧目：{ctx.get('title') or '未命名'}\n"
                f"第{ctx.get('episode_num') or ''}集 {ctx.get('episode_title') or ''}\n"
                f"角色名单：{json.dumps(roster, ensure_ascii=False)}\n"
                f"镜头草稿：{json.dumps(compact, ensure_ascii=False)}"
            ),
            max_tokens=1400,
        )
        parsed.pop("_model", None)
        return parsed

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
    def enrich_imported_characters(
        cls,
        characters: list[dict[str, Any]],
        *,
        title: str = "",
        genre: str = "",
        visual_style: str = "",
        project_style: str = "",
    ) -> list[dict[str, Any]]:
        if not characters:
            return []
        base_url, model, api_key = cls._runtime_config()
        compact = []
        for item in characters:
            compact.append({
                "name": item.get("name") or "",
                "aliases": item.get("aliases") or "",
                "role": item.get("role") or "",
                "role_position": item.get("role_position") or "",
                "gender": item.get("gender") or "",
                "age": item.get("age") or "",
                "age_group": item.get("age_group") or "",
                "description": (item.get("description") or "")[:800],
                "face_prompt": item.get("face_prompt") or "",
                "body_type": item.get("body_type") or "",
                "art_style_id": item.get("art_style_id") or "",
                "visual_style": item.get("visual_style") or "",
                "ethnicity": item.get("ethnicity") or "",
                "visual_prompt": (item.get("visual_prompt") or "")[:400],
            })
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是影视角色设定补全助手。根据已解析的剧本人物草稿，补全缺失字段，"
                            "已有非空字段必须原样保留，不得改名。"
                            "aliases 用英文逗号分隔，不要重复姓名本身。"
                            "role_position 只能是：主角、反派/观察、配角、龙套、旁白。"
                            "age_group 只能是：幼年、少年、青年、中年、老年。"
                            "gender 只能是：男、女、未指定。"
                            "body_type 只能是：纤细、苗条、标准、精悍、健壮、魁梧。"
                            "art_style_id 只能是：chinese_period_drama、chinese_modern_drama、"
                            "guoman_fantasy、anime、western_realistic、western_cartoon。"
                            "visual_style 只能是：realistic、ancient、modern、fantasy、cyberpunk。"
                            "ethnicity 默认 Chinese。"
                            "face_prompt 必须是可直接用于头像生图的中文面部描述，包含性别、年龄段、发型、眉眼、肤色、脸型，不要写服装。"
                            "description 补全为完整人物小传，含外貌、气质、身份。"
                            "visual_prompt 为单人全身设定图提示词。"
                            "avatar_prompt 为面部特写提示词。"
                            "只返回 JSON：{\"characters\":[{...}]}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"剧目：{title or '未命名'}\n"
                            f"类型：{genre or '未指定'}\n"
                            f"项目画风：{project_style or '未指定'}\n"
                            f"视觉风格描述：{visual_style or '无'}\n"
                            f"待补全角色：{json.dumps(compact, ensure_ascii=False)}"
                        ),
                    },
                ],
                "temperature": 0.2,
                "max_tokens": 4000,
                "response_format": {"type": "json_object"},
            },
            timeout=180,
        )
        if not response.ok:
            raise RuntimeError(f"AI 补全角色档案失败，HTTP {response.status_code}: {response.text[:300]}")
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = cls._parse_json_object(content)
        rows = parsed.get("characters")
        if not isinstance(rows, list):
            raise ValueError("大模型未返回 characters 数组。")
        return [item for item in rows if isinstance(item, dict)]


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

    @classmethod
    def chat_text(cls, system: str, user: str, *, max_tokens: int = 2500, temperature: float = 0.6) -> str:
        """调用大模型输出纯文本对话内容，自动清洗 think 标签与 markdown 标记"""
        base_url, model, api_key = cls._runtime_config()
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=180,
        )
        if not response.ok:
            raise RuntimeError(f"大模型调用失败，HTTP {response.status_code}: {response.text[:300]}")
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        # 如果模型输出带有思考链 <think>...</think>，自动剔除
        if "<think>" in content:
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:markdown|text)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        # 清除标题前的 markdown ## 号，使其严格符合 H3 规范
        content = re.sub(r"^##\s*", "", content, flags=re.MULTILINE)
        # 清除尾部可能附带的模型说明或多余反引号
        content = re.sub(r"\n*```+\s*$", "", content)
        content = re.sub(r"\n*[（\(](?:提示词|以上|本提示词|注意)[^）\)]*?[）\)]\s*$", "", content, flags=re.DOTALL)
        return content.strip()

    @classmethod
    def resolve_h3_prompt_mode(cls, beat_info: dict[str, Any]) -> str:
        """按技能规则选择 T2VA / I2VA / FL2VA / L2VA / Ref2VA。有角色、场景、道具参考图时走全参考。"""
        aliases = {
            "t2va": "T2VA",
            "t2v": "T2VA",
            "i2va": "I2VA",
            "i2v": "I2VA",
            "fl2va": "FL2VA",
            "fl2v": "FL2VA",
            "l2va": "L2VA",
            "l2v": "L2VA",
            "ref2va": "Ref2VA",
            "r2v": "Ref2VA",
            "fullreference": "Ref2VA",
        }
        explicit = re.sub(r"[\s_-]+", "", str(beat_info.get("prompt_mode") or "").strip().lower())
        if explicit in aliases:
            return aliases[explicit]

        pictures = [item for item in (beat_info.get("ref_images") or []) if isinstance(item, dict)]
        videos = [item for item in (beat_info.get("ref_videos") or []) if isinstance(item, dict)]
        audios = [item for item in (beat_info.get("ref_audios") or []) if isinstance(item, dict)]
        roles = {
            str(item.get("role") or item.get("frame_role") or "").strip().lower()
            for item in pictures
        }
        categories = {str(item.get("category") or "").strip().lower() for item in pictures}
        keyframe_roles = roles & {"first", "first_frame", "last", "last_frame"}
        reference_categories = categories & {"character", "scene", "prop", "subject", "style"}
        if videos or audios or reference_categories or (pictures and not keyframe_roles):
            return "Ref2VA"
        if {"first", "first_frame"} & roles and {"last", "last_frame"} & roles:
            return "FL2VA"
        if {"last", "last_frame"} & roles:
            return "L2VA"
        if {"first", "first_frame"} & roles:
            return "I2VA"
        return "T2VA"

    @classmethod
    def _h3_rule_text(cls, mode: str) -> str:
        root = H3_SKILL_DIR
        skill_path = root / "SKILL.md"
        base_path = root / "references" / "base-en.txt"
        ref_path = root / "references" / "ref-en.txt"
        missing = [str(path) for path in (skill_path, base_path, ref_path) if not path.is_file()]
        if missing:
            raise ValueError("H3 提示词规则文件缺失: " + ", ".join(missing))
        skill = skill_path.read_text(encoding="utf-8").strip()
        base = base_path.read_text(encoding="utf-8").strip()
        if mode == "Ref2VA":
            ref = ref_path.read_text(encoding="utf-8").strip()
            selected = (
                "# Selected guide: references/ref-en.txt\n"
                "Use the six-section Ref2VA format. Camera, speaker, dialogue, cut, and sound rules "
                "shared with base modes are in references/base-en.txt and apply inside detailed_description.\n\n"
                f"{ref}\n\n"
                "# Shared audiovisual rules: references/base-en.txt\n\n"
                f"{base}"
            )
        else:
            selected = (
                "# Selected guide: references/base-en.txt\n"
                f"Input mode is {mode}. Follow its alignment instruction and the three core fields exactly. "
                "Do not use the Ref2VA six-section format.\n\n"
                f"{base}"
            )
        return f"{skill}\n\n{selected}"

    @classmethod
    def _h3_system_prompt(cls, mode: str, duration_seconds: str) -> str:
        if mode == "Ref2VA":
            headings = "\n".join(f"{name}:" for name in H3_REF_SECTIONS)
            structure = f"""Return only the finished prompt. It must contain exactly these six section headings, spelled exactly and in this order, with each heading on its own line:
{headings}

Write all six sections in English. Preserve the original language only for dialogue, lyrics, and visible scene text. Do not add Chinese section headings, markdown fences, commentary, or an advertising-copy section. Keep every supplied <Picture N>, <Video N>, <Audio N>, and <Subject N> index stable; never swap, merge, omit, or invent labels. A picture used only as a subject source is cited inside that subject definition, not defined again as a standalone picture."""
        else:
            headings = "\n".join(f"{name}:" for name in H3_BASE_SECTIONS)
            if mode == "T2VA":
                instruction = "Begin directly with integrated_multimodal_description. Do not add a picture-alignment instruction or any reference label."
            elif mode == "I2VA":
                instruction = "The first line must be exactly: For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
            elif mode == "FL2VA":
                instruction = (
                    "The first line must be the FL2VA picture-alignment instruction from the guide, "
                    f"using {duration_seconds}.00 as the last-frame timestamp when the beat does not specify another cut time."
                )
            else:
                instruction = (
                    "The first line must be the L2VA picture-alignment instruction from the guide, "
                    f"aligning <Picture 1> with the {duration_seconds}.00-second mark."
                )
            structure = f"""Return only the finished {mode} prompt.
{instruction}
Follow it with exactly these core fields, spelled exactly and in this order, each heading on its own line:
{headings}

Write the fields in English. Preserve the original language only for dialogue, lyrics, and visible scene text. Do not add Chinese section headings, markdown fences, commentary, subject_definitions, summary, retention_analysis, or an advertising-copy section."""
        return f"""You are a MiniMax H3 prompt writer. The skill and the selected reference guide below are the only format authority. Follow them exactly for mode {mode}. Fit all described action and complete speech naturally within {duration_seconds} seconds.

{structure}

Assign actual speakers stable global IDs (S1), (S2), and so on. A speaker name is metadata, never dialogue. Put spoken content only inside <d>[Language] ...</d>, preserving the supplied words and original language exactly. Never put the speaker name or quotation wrappers inside <d>. Do not invent, paraphrase, repeat, or reassign dialogue. Complete spoken statements end with suitable basic punctuation before </d>. When a visible character is not speaking, keep their lips naturally closed; never instruct the active speaker to keep their lips closed during speech. overall_soundscape summarizes ambience and physical sounds and must not repeat complete dialogue. non_diegetic_music describes audience-only music with instrumentation, tempo, rhythm, and dynamic development, or N/A.

Camera budget, which overrides fast, epic, multi-angle, orbit, or 推升 wording in the source camera note, and also overrides the skill's optional `at fast speed` / `with large amplitude` expressions:
- Use exactly one continuous [Shot 1]. Do not add [Shot 2] or later cuts, hidden cuts, or timestamps unless the beat explicitly lists multiple shots.
- Use at most one camera move in the whole clip. A static hold is preferred for dialogue. Do not chain push, tilt, pan, zoom, orbit, or a reveal into one another.
- If there is a move, write it once as natural English with both `with small amplitude` and `at slow speed`. Example: `The camera pushes in with small amplitude at slow speed`.
- Never use fast speed, rapid, quick, whip, crash zoom, 180-degree, 360-degree, orbit, arc-around, crane soar, or a focal-length jump.
- If the source says 快速, 急推, 环绕, 多角度, or 推升至俯拍, keep only the opening composition and at most a slow hint of that direction. Do not execute the fast or multi-shot version.
- Hold the ending long enough to read faces, costumes, and props. Do not add follow-up reframes.

--- skill rules ---
{cls._h3_rule_text(mode)}"""

    @classmethod
    def _h3_user_prompt(cls, beat_info: dict[str, Any], mode: str, duration_seconds: str) -> str:
        user_lines = [
            "请严格按上方技能规则，为以下分镜生成高品质 H3 视频提示词。只输出成品提示词。",
            f"Target mode: {mode}",
            f"分镜序号：第 {beat_info.get('sequence', 1)} 镜头",
            f"分镜标题：{beat_info.get('heading') or '未命名镜头'}",
            f"场景设定：{beat_info.get('scene_name') or '默认场景'}"
            + (f"（{beat_info.get('scene_desc')}）" if beat_info.get("scene_desc") else ""),
            "出场角色列表：",
        ]
        characters = beat_info.get("characters") or []
        if characters:
            for idx, char in enumerate(characters, 1):
                desc = char.get("look_desc") or char.get("desc") or "暂无特征描述"
                user_lines.append(f"{idx}. {char.get('name')}（{desc}）")
        else:
            user_lines.append("未指定出场角色。")

        props = beat_info.get("props") or []
        if props:
            user_lines.append("出场道具列表：")
            for idx, prop in enumerate(props, 1):
                desc = prop.get("desc") or "特征完好，质感细腻"
                user_lines.append(f"{idx}. {prop.get('name')}（{desc}）")

        user_lines.extend([
            f"画面动作与细节要求：{beat_info.get('action') or '画面进行中'}",
            "镜头与机位（只采用起始构图；不要执行其中的快速、环绕、多机位或大幅度推升）："
            + (str(beat_info.get("camera") or "").strip() or "固定机位，或一次缓慢小幅运镜"),
            "运镜预算：整段只有 [Shot 1]；最多一种运镜；若运镜必须同时写 with small amplitude 和 at slow speed；禁止快推、180/360 环绕、焦段大跳和连续切换机位。",
            f"时间与环境氛围：{beat_info.get('time_of_day') or '日间'}",
            f"视频时长：{duration_seconds} 秒",
            f"说话人（仅作元数据，不得写入 <d> 台词正文）：{beat_info.get('speaker') or '无'}",
            f"对白原文（必须逐字放入 <d>，不得包含说话人姓名和外围引号）：{cls._clean_h3_dialogue(beat_info.get('dialogue'), beat_info.get('speaker')) or '无对白'}",
        ])
        turns = beat_info.get("dialogue_turns") or []
        if isinstance(turns, list) and turns:
            user_lines.append("多轮对白（按顺序保留原文，每轮使用稳定说话人 ID）：")
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                speaker = str(turn.get("speaker") or "").strip()
                text = cls._clean_h3_dialogue(turn.get("text"), speaker)
                if text:
                    user_lines.append(f"- {speaker or '未命名说话人'}：{text}")
        visible_text = str(beat_info.get("visible_text") or "").strip()
        if visible_text:
            user_lines.append(f"画面可见文字（原样保留，不得朗读）：{visible_text}")
        narration = cls._clean_h3_dialogue(beat_info.get("narration"))
        if narration:
            user_lines.append(f"旁白（画外音，可见人物嘴唇保持闭合）：{narration}")

        user_lines.append("reference_map（标签含义必须严格一一对应，禁止增删改编号）：")
        ref_images = beat_info.get("ref_images") or []
        ref_videos = beat_info.get("ref_videos") or []
        ref_audios = beat_info.get("ref_audios") or []
        if mode == "T2VA":
            user_lines.append("- 无参考图、参考视频或参考音频。使用 T2VA，不要编造 <Picture N>、<Subject N>、<Video N> 或 <Audio N>。")
        else:
            if ref_images:
                for item in ref_images:
                    cat = item.get("category")
                    role = item.get("role") or item.get("frame_role") or ""
                    cat_name = "场景" if cat == "scene" else ("道具" if cat == "prop" else "角色")
                    role_text = f"，用途={role}" if role else ""
                    user_lines.append(
                        f"- <Picture {item.get('index')}>: {item.get('name')}（{cat_name}参考图{role_text}）"
                    )
            if ref_videos:
                for item in ref_videos:
                    user_lines.append(f"- <Video {item.get('index')}>: {item.get('name') or '参考视频'}")
            if ref_audios:
                for item in ref_audios:
                    user_lines.append(f"- <Audio {item.get('index')}>: {item.get('name') or '参考音频'}")
            if not ref_images and not ref_videos and not ref_audios:
                user_lines.append("- 未提供可用参考素材。不要编造引用标签。")

        if beat_info.get("existing_prompt"):
            user_lines.extend([
                "",
                "现有文本仅作内容参考。若它使用中文段落名、画面广告文案或不合当前模式的结构，必须整段重写，不得沿用错误格式：",
                str(beat_info.get("existing_prompt")),
            ])
        return "\n".join(user_lines)

    @classmethod
    def _validate_h3_prompt(cls, prompt: str, mode: str, beat_info: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        text = str(prompt or "").strip()
        sections = H3_REF_SECTIONS if mode == "Ref2VA" else H3_BASE_SECTIONS
        positions = []
        for name in sections:
            match = re.search(rf"(?m)^{re.escape(name)}:\s*$", text)
            positions.append(match.start() if match else -1)
        if any(pos < 0 for pos in positions) or positions != sorted(positions):
            errors.append("required section headings are missing or out of order")
        for item in ("主体定义:", "摘要:", "保留分析:", "详细描述:", "整体声景:", "非叙事配乐:", "画面广告文案:"):
            if item in text:
                errors.append(f"illegal section heading: {item}")
        expected: list[str] = []
        turns = beat_info.get("dialogue_turns") or []
        if isinstance(turns, list):
            for turn in turns:
                if isinstance(turn, dict):
                    cleaned = cls._clean_h3_dialogue(turn.get("text"), turn.get("speaker"))
                    if cleaned:
                        expected.append(cleaned)
        dialogue = cls._clean_h3_dialogue(beat_info.get("dialogue"), beat_info.get("speaker"))
        if dialogue and dialogue not in expected:
            expected.append(dialogue)
        for line in expected:
            if line not in text:
                errors.append(f"dialogue not preserved verbatim: {line[:80]}")
        visible_text = str(beat_info.get("visible_text") or "").strip()
        if visible_text and visible_text not in text:
            errors.append("visible text not preserved verbatim")
        if mode == "Ref2VA":
            for item in beat_info.get("ref_images") or []:
                if isinstance(item, dict) and item.get("index"):
                    token = f"<Picture {item.get('index')}>"
                    if token not in text:
                        errors.append(f"missing {token}")
        if mode == "I2VA" and not text.startswith("For the target video, at 0.00 seconds"):
            errors.append("I2VA alignment instruction missing")
        if mode == "T2VA" and re.search(r"<(?:Picture|Subject|Video|Audio) \d+>", text):
            errors.append("T2VA prompt must not invent reference labels")
        errors.extend(cls._camera_budget_errors(text, mode, beat_info))
        return errors

    @classmethod
    def _camera_budget_errors(cls, prompt: str, mode: str, beat_info: dict[str, Any]) -> list[str]:
        body = cls._h3_description_body(prompt, mode)
        errors: list[str] = []
        source = " ".join(
            str(beat_info.get(key) or "")
            for key in ("camera", "action", "heading")
        )
        allows_cuts = bool(re.search(r"多镜头|镜头切换|切到|\[Shot\s*2\]", source, flags=re.I))
        if not allows_cuts and re.search(r"\[Shot\s*[2-9]\d*\]", body):
            errors.append("too many shots; keep one continuous [Shot 1]")
        if re.search(r"at fast speed|fast speed|\brapid(?:ly)?\b|\bquick(?:ly)?\b|\bwhip\b|crash zoom|360|180(?:\s*|-)?degree|\borbit", body, flags=re.I):
            errors.append("camera is too fast or too dizzy; remove fast, 180/360, whip, and orbit moves")
        if re.search(r"focal length|\b\d+\s*mm\b.+\b\d+\s*mm\b", body, flags=re.I):
            errors.append("do not jump focal length")
        move_count = cls._camera_move_count(body)
        if move_count > 1:
            errors.append("too many camera moves; use one slow small-amplitude move or a static hold")
        elif move_count == 1 and (
            "with small amplitude" not in body.lower() or "at slow speed" not in body.lower()
        ):
            errors.append("the single camera move must say with small amplitude and at slow speed")
        return errors

    @staticmethod
    def _h3_description_body(prompt: str, mode: str) -> str:
        text = str(prompt or "")
        start_key = "detailed_description:" if mode == "Ref2VA" else "integrated_multimodal_description:"
        start = text.find(start_key)
        end = text.find("\noverall_soundscape:")
        if start < 0:
            return text
        return text[start:end if end > start else None]

    @staticmethod
    def _camera_move_count(body: str) -> int:
        """只统计紧跟 camera 的运镜动词，避免把人物仰头、拂袖算成运镜。"""
        verb = (
            r"push(?:es|ing)? in|pull(?:s|ing)? out|pans?|panning|tilts?|tilting|"
            r"trucks?|pedestal|arc shot|zooms?(?:\s|-)?(?:in|out)|rises?|rising|"
            r"ascends?|descends?|rotates?|rotating|doll(?:y|ies)|tracking shot"
        )
        return len(re.findall(rf"\bcameras?\b(?:\s+\w+){{0,2}}\s+(?:{verb})\b", body or "", flags=re.I))

    @classmethod
    def _restrain_h3_camera(cls, prompt: str, mode: str, beat_info: dict[str, Any]) -> str:
        """运镜超标时不让任务失败，收成一次缓慢小幅运镜后保存。"""
        text = str(prompt or "")
        start_key = "detailed_description:" if mode == "Ref2VA" else "integrated_multimodal_description:"
        start = text.find(start_key)
        if start < 0:
            return text
        end = text.find("\noverall_soundscape:")
        body_start = start + len(start_key)
        body = text[body_start:end if end > body_start else None]
        restrained = cls._restrain_description_camera(body, beat_info)
        suffix = text[end:] if end > body_start else ""
        return text[:body_start] + restrained + suffix

    @classmethod
    def _restrain_description_camera(cls, body: str, beat_info: dict[str, Any]) -> str:
        text = re.sub(r"\[Shot\s*[2-9]\d*\]\s*(?:At\s+\d{2}:\d{2}\.\d{3},?\s*)?", "", body or "", flags=re.I)
        text = re.sub(
            r"\b(?:the camera cuts to|the shot cuts to|the shot transitions to|the shot changes to|the shot switches to)\b\s*",
            "",
            text,
            flags=re.I,
        )
        source = " ".join(str(beat_info.get(key) or "") for key in ("camera", "action", "heading"))
        if re.search(r"仰拍|推升|俯拍|升起|升至", source):
            move = "The camera rises with small amplitude at slow speed from the opening composition and then holds."
        else:
            move = "The camera pushes in with small amplitude at slow speed and then holds."
        verb = (
            r"push(?:es|ing)? in|pull(?:s|ing)? out|pans?|panning|tilts?|tilting|"
            r"trucks?|zooms?(?:\s|-)?(?:in|out)|rises?|rising|ascends?|descends?|"
            r"rotates?|rotating|doll(?:y|ies)|tracking shot|arc shot|holds?|holding|static shot"
        )
        camera_sentence = re.compile(
            rf"(?i)(?:^|\s)\[Shot 1\]\s+The camera\b(?:\s+\w+){{0,2}}\s+(?:{verb})\b[^.?!]*[.?!]?|"
            rf"\b[Tt]he camera\b(?:\s+\w+){{0,2}}\s+(?:{verb})\b[^.?!]*[.?!]|"
            rf"\bCamera\b(?:\s+\w+){{0,2}}\s+(?:{verb})\b[^.?!]*[.?!]"
        )
        text = camera_sentence.sub(" ", text)
        text = re.sub(r"\bat fast speed\b|\bfast speed\b|\brapid(?:ly)?\b|\bquick(?:ly)?\b|360(?:\s*|-)?degree|180(?:\s*|-)?degree|\borbit(?:s|ing)?\b", "", text, flags=re.I)
        text = re.sub(r"focal length[^.]{0,80}\d+\s*mm", "", text, flags=re.I)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if "[Shot 1]" in text:
            text = text.replace("[Shot 1]", f"[Shot 1] {move}", 1)
        else:
            text = f"[Shot 1] {move} {text}".strip()
        return "\n" + text + "\n"

    @staticmethod
    def _is_camera_budget_error(error: str) -> bool:
        return error.startswith((
            "too many shots",
            "camera is too fast",
            "do not jump focal length",
            "too many camera moves",
            "the single camera move must",
        ))

    @classmethod
    def generate_h3_prompt(cls, beat_info: dict[str, Any]) -> str:
        """按 h3-prompt-writing 技能规则选择模式，并把规则原文交给大模型生成提示词。"""
        mode = cls.resolve_h3_prompt_mode(beat_info)
        duration_seconds = str(beat_info.get("duration_seconds") or "10").strip() or "10"
        system_prompt = cls._h3_system_prompt(mode, duration_seconds)
        user_prompt = cls._h3_user_prompt(beat_info, mode, duration_seconds)
        prompt = cls._request_h3_prompt(system_prompt, user_prompt, beat_info)
        errors = cls._validate_h3_prompt(prompt, mode, beat_info)
        if any(not cls._is_camera_budget_error(item) for item in errors):
            retry_user = (
                f"{user_prompt}\n\n"
                "The previous output failed validation. Rewrite the complete prompt and return only the finished prompt.\n"
                + "\n".join(f"- {item}" for item in errors)
                + f"\nPrevious output:\n{prompt}"
            )
            prompt = cls._request_h3_prompt(system_prompt, retry_user, beat_info)
            errors = cls._validate_h3_prompt(prompt, mode, beat_info)
        if any(cls._is_camera_budget_error(item) for item in errors):
            prompt = cls._restrain_h3_camera(prompt, mode, beat_info)
            errors = [
                item for item in cls._validate_h3_prompt(prompt, mode, beat_info)
                if not cls._is_camera_budget_error(item)
            ]
        if errors:
            raise ValueError("H3 提示词未通过规则校验：" + "；".join(errors))
        return prompt

    @classmethod
    def _request_h3_prompt(cls, system_prompt: str, user_prompt: str, beat_info: dict[str, Any]) -> str:
        prompt = cls.chat_text(system_prompt, user_prompt, max_tokens=6000, temperature=0.4)
        return cls._clean_h3_prompt_dialogue(prompt, beat_info.get("speaker"))

    @staticmethod
    def _clean_h3_dialogue(dialogue: Any, speaker: Any = "") -> str:
        text = str(dialogue or "").strip()
        speaker_name = str(speaker or "").strip()
        if speaker_name:
            text = re.sub(
                rf"^[\s\"'“‘]*{re.escape(speaker_name)}\s*[：:]\s*",
                "",
                text,
            ).strip()
        quote_pairs = (("“", "”"), ("‘", "’"), ('"', '"'), ("'", "'"), ("「", "」"), ("『", "』"))
        while len(text) >= 2 and any(text.startswith(left) and text.endswith(right) for left, right in quote_pairs):
            text = text[1:-1].strip()
        return text

    @classmethod
    def _clean_h3_prompt_dialogue(cls, prompt: str, speaker: Any = "") -> str:
        if not prompt or not str(speaker or "").strip():
            return prompt

        def clean_tag(match: re.Match[str]) -> str:
            language = match.group(1)
            dialogue = cls._clean_h3_dialogue(match.group(2), speaker)
            return f"<d>{language}{dialogue}</d>"

        return re.sub(r"<d>(\[[^\]]+\]\s*)(.*?)</d>", clean_tag, prompt, flags=re.DOTALL)
