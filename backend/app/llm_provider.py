from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .grs_provider import CredentialManager
from .llm_client import LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS, OpenAICompatibleClient, LlmError
from .storage import JobStore, now



DEFAULT_MODELSCOPE_BASE_URL = "https://api-inference.modelscope.cn/v1"
DEFAULT_MODELSCOPE_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"

VISION_MODEL_MARKERS = (
    "vl", "vision", "gpt-4o", "gpt-4.1", "gpt-4.5", "gpt-5", "o4-mini",
    "gemini", "claude-3", "claude-4", "claude-sonnet", "claude-opus", "claude-haiku",
    "llava", "pixtral", "minimax-vl", "glm-4v", "glm-4.1v", "internvl",
    "phi-4-multimodal", "phi-3.5-vision", "gemma-3", "minicpm-v", "step-1v",
    "qwen2-vl", "qwen2.5-vl", "qwen3-vl", "qwen-vl",
)


def model_supports_vision(model: str | None) -> bool:
    lowered = (model or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in VISION_MODEL_MARKERS)


def is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


class LlmProviderService:
    def __init__(self, store: JobStore, credential_key: str | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)

    def api_key(self) -> str | None:
        decrypted = self.credentials.decrypt(self.store.get_llm_settings().get("api_key_encrypted"))
        if not decrypted:
            config = self.store.get_llm_settings()
            if is_local_base_url(config.get("base_url", "")):
                return "ollama"  # 本地服务默认虚拟 key
        return decrypted

    def availability(self) -> tuple[bool, str | None]:
        config = self.store.get_llm_settings()
        if not config["enabled"]:
            return False, "大模型服务尚未启用，请联系超级管理员配置。"
        if not is_local_base_url(config.get("base_url", "")) and not self.credentials.ready:
            return False, self.credentials.error or "凭证主密钥不可用"
        if not self.api_key():
            return False, "大模型 API Key / Token 未配置或无法解密。"
        if not config.get("model"):
            return False, "未配置大模型名称 (Model Name)。"
        return True, None


    def public_config(self) -> dict[str, Any]:
        config = self.store.get_llm_settings()
        api_key = self.api_key()
        available, reason = self.availability()
        masked = None
        if api_key:
            masked = (
                f"{api_key[:3]}{'*' * max(5, min(16, len(api_key) - 5))}{api_key[-2:]}"
                if len(api_key) > 5
                else "*****"
            )
        return {
            "enabled": config["enabled"],
            "base_url": config["base_url"],
            "model": config["model"],
            "api_key_masked": masked,
            "has_api_key": bool(config.get("api_key_encrypted")),
            "credential_ready": self.credentials.ready,
            "last_test_status": config.get("last_test_status"),
            "last_test_message": config.get("last_test_message"),
            "last_test_at": config.get("last_test_at"),
            "available": available,
            "unavailable_reason": reason,
            "supports_vision": model_supports_vision(config.get("model")),
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        values = {key: value for key, value in payload.items() if key != "api_key"}
        base_url_str = str(values.get("base_url", "")).strip()
        if not base_url_str:
            base_url_str = DEFAULT_MODELSCOPE_BASE_URL
        parsed = urlparse(base_url_str)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Base URL 必须是有效的 HTTP 或 HTTPS 地址")
        values["base_url"] = base_url_str.rstrip("/")

        model_name = str(values.get("model", "")).strip()
        if not model_name:
            model_name = DEFAULT_MODELSCOPE_MODEL
        values["model"] = model_name

        api_key = payload.get("api_key")
        if api_key is not None and str(api_key).strip():
            if not self.credentials.ready:
                raise ValueError(self.credentials.error or "凭证主密钥不可用")
            values["api_key_encrypted"] = self.credentials.encrypt(str(api_key).strip())

        self.store.update_llm_settings(**values)
        return self.public_config()


    def test(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        config = self.store.get_llm_settings()
        base_url = (payload.get("base_url") if payload else None) or config["base_url"]
        model = (payload.get("model") if payload else None) or config["model"]
        api_key = payload.get("api_key") if payload and payload.get("api_key") is not None else self.api_key()
        if not api_key and is_local_base_url(base_url or ""):
            api_key = "ollama"

        if not api_key:
            raise ValueError("测试连接需要提供有效的 API Key / Token")
        if not base_url:
            raise ValueError("Base URL 不能为空")
        if not model:
            raise ValueError("Model 名称不能为空")

        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        test_time = now()
        test_timeout = 90.0 if is_local_base_url(base_url or "") else 15.0
        try:
            reply = client.test_connection(model=model, timeout=test_timeout)
            test_status = "成功"
            test_message = f"连接成功，模型响应：{reply}"
        except Exception as exc:
            test_status = "失败"
            test_message = str(exc)

        self.store.update_llm_settings(
            last_test_status=test_status,
            last_test_message=test_message,
            last_test_at=test_time,
        )
        if test_status != "成功":

            raise LlmError(f"大模型连接测试失败：{test_message}")
        return self.public_config()

    def list_catalog(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        config = self.store.get_llm_settings()
        base_url = (payload.get("base_url") if payload else None) or config["base_url"]
        submitted_key = payload.get("api_key") if payload else None
        api_key = submitted_key.strip() if isinstance(submitted_key, str) and submitted_key.strip() else self.api_key()
        if not api_key and is_local_base_url(base_url or ""):
            api_key = "ollama"
        if not api_key:
            raise LlmError("拉取模型目录需要提供有效的 API Key / Token")
        if not base_url:
            raise LlmError("Base URL 不能为空")
        free_only = True if payload is None else bool(payload.get("free_only", True))
        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        return client.list_model_catalog(free_only=free_only)

    def optimize_prompt(
        self,
        prompt: str,
        *,
        media_type: str = "video",
        workflow_name: str | None = None,
        skill_id: str | None = None,
        reference_count: int = 0,
        workflow_id: str | None = None,
    ) -> str:
        available, reason = self.availability()
        if not available:
            raise LlmError(reason or "大模型服务不可用")

        config = self.store.get_llm_settings()
        api_key = self.api_key()
        if not api_key:
            raise LlmError("大模型凭据未配置")

        client = OpenAICompatibleClient(base_url=config["base_url"], api_key=api_key)
        return client.optimize_prompt(
            prompt,
            media_type=media_type,
            workflow_name=workflow_name,
            skill_id=skill_id,
            reference_count=reference_count,
            workflow_id=workflow_id,
            model=config["model"],
        )

    def analyze_subject(
        self,
        *,
        image_data_url: str,
        kind: str,
        name: str,
    ) -> str:
        available, reason = self.availability()
        if not available:
            raise LlmError(reason or "大模型服务不可用")
        config = self.store.get_llm_settings()
        if not model_supports_vision(config.get("model")):
            raise LlmError("当前大模型不支持视觉输入，无法根据参考图提取外貌。请在管理设置中改用带 VL/Vision 的模型。")
        api_key = self.api_key()
        if not api_key:
            raise LlmError("大模型凭据未配置")
        client = OpenAICompatibleClient(base_url=config["base_url"], api_key=api_key)
        return client.analyze_subject(
            image_data_url=image_data_url,
            kind=kind,
            name=name,
            model=config["model"],
        )

    def split_script(
        self,
        script: str,
        *,
        shot_count: int = 4,
        style_vibe: str | None = None,
        cast_names: list[str] | None = None,
    ) -> dict[str, Any]:
        available, reason = self.availability()
        if not available:
            raise LlmError(reason or "大模型服务不可用")

        config = self.store.get_llm_settings()
        api_key = self.api_key()
        if not api_key:
            raise LlmError("大模型凭据未配置")

        client = OpenAICompatibleClient(base_url=config["base_url"], api_key=api_key)
        return client.split_script(
            script,
            shot_count=shot_count,
            style_vibe=style_vibe,
            cast_names=cast_names,
            model=config["model"],
        )

    def _chat_client(self) -> tuple[Any, str]:
        available, reason = self.availability()
        if not available:
            raise LlmError(reason or "大模型服务不可用")
        config = self.store.get_llm_settings()
        api_key = self.api_key()
        if not api_key:
            raise LlmError("大模型凭据未配置")
        return OpenAICompatibleClient(base_url=config["base_url"], api_key=api_key), config["model"]

    def run_director_recipe(
        self,
        recipe: dict[str, Any] | None,
        *,
        goal: str,
        art_style_id: str | None = None,
        agents: list[str] | None = None,
        skip_research: bool | None = None,
        on_progress: Any = None,
    ) -> dict[str, Any]:
        from .director_agents import default_chat_fn, run_recipe_pipeline

        client, model = self._chat_client()
        return run_recipe_pipeline(
            recipe,
            goal=goal,
            chat_fn=default_chat_fn(client, model),
            art_style_id=art_style_id,
            agents=agents,
            skip_research=skip_research,
            on_progress=on_progress,
        )

    def run_director_agent_step(
        self,
        recipe: dict[str, Any] | None,
        *,
        goal: str,
        agent_id: str,
        art_style_id: str | None = None,
        skip_research: bool | None = None,
        on_progress: Any = None,
    ) -> dict[str, Any]:
        from .director_agents import default_chat_fn, run_agent

        client, model = self._chat_client()
        return run_agent(
            agent_id,
            recipe or {},
            goal=goal,
            chat_fn=default_chat_fn(client, model),
            art_style_id=art_style_id,
            skip_research=skip_research,
            on_progress=on_progress,
        )

    def polish_director_h3_prompt(self, draft_prompt: str, mode: str) -> str:
        """Use the configured LLM after the final H3 input mode and reference order are known."""
        from .llm_minimax_skills import build_h3_final_prompt_polish_prompt

        draft = str(draft_prompt or "").strip()
        if not draft:
            raise LlmError("没有可润色的 H3 提示词")
        client, model = self._chat_client()
        return client.chat_completion(
            [
                {"role": "system", "content": build_h3_final_prompt_polish_prompt(mode)},
                {"role": "user", "content": f"Requested final prompt:\n\n{draft}"},
            ],
            model=model,
            temperature=0.35,
            max_tokens=8192,
            timeout=LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
            stream=True,
        ).strip()

    def polish_director_ref2va_prompt(self, draft_prompt: str) -> str:
        """Backward-compatible entry point for callers that explicitly request Ref2VA."""
        return self.polish_director_h3_prompt(draft_prompt, "REF2VA")

    def fission_batch_scripts(
        self,
        *,
        theme: str,
        count: int,
        duration_sec: int,
        aspect_ratio: str,
        art_style: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        from .director_agents import default_chat_fn, fission_batch_scripts

        client, model = self._chat_client()
        return fission_batch_scripts(
            theme=theme,
            count=count,
            duration_sec=duration_sec,
            aspect_ratio=aspect_ratio,
            art_style=art_style,
            chat_fn=default_chat_fn(client, model),
        )

    def analyze_xiaji_ingest(
        self,
        text: str,
        *,
        spine_template: str = "drama",
        visual_style: str = "",
        narration_style: str = "",
        ethnicity: str = "",
    ) -> dict[str, Any]:
        from .xiaji_analyze import analyze_ingest_text

        client, model = self._chat_client()
        return analyze_ingest_text(
            client,
            model,
            text,
            spine_template=spine_template,
            visual_style=visual_style,
            narration_style=narration_style,
            ethnicity=ethnicity,
        )

    def define_xiaji_voice(self, payload: dict[str, Any]) -> dict[str, Any]:
        from .xiaji_analyze import define_voice_profile

        client, model = self._chat_client()
        return define_voice_profile(client, model, payload)

    def generate_xiaji_script(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        from .xiaji_episode_prompts import generate_script_beats

        client, model = self._chat_client()
        return generate_script_beats(
            client,
            model,
            original_lines=list(payload.get("original_lines") or []),
            characters=list(payload.get("characters") or []),
            scenes=list(payload.get("scenes") or []),
            props=list(payload.get("props") or []),
            visual_style=str(payload.get("visual_style") or ""),
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            name_to_asset=payload.get("name_to_asset") or {},
        )
