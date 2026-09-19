from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse
import requests

from ..provider_bridge import credential_manager, llm_row, vlm_row
from ...llm_client import (
    LlmError,
    LlmTemporaryError,
    OpenAICompatibleClient,
    emit_llm_stream_status,
    is_llm_timeout_error,
    is_openai_reasoning_chat_model,
)
from ...llm_provider import model_supports_vision
from ...vlm_provider import ANALYSIS_UNAVAILABLE_MESSAGE, VLM_UNAVAILABLE_MESSAGE, VLM_NOT_VISION_MESSAGE
from ...vision_runtime import (
    VISION_STATUS_UNAVAILABLE,
    VisionCallMeta,
    chat_on_endpoint,
    complete_authoring,
    overlay_vlm_credentials,
    resolve_analysis_endpoint,
)
from .asset_prompt_inference import infer_system_prompt, infer_user_text, parse_infer_payload
from .episode_shot_planner import (
    build_shot_plan_system_prompt,
    build_shot_plan_user_prompt,
    normalize_planned_shots,
    parse_shot_plan_response,
)
from .h3_prompt_builder import H3PromptBuilder

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


def is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


@dataclass
class DualShotAuthorResult:
    zh_prompt: str
    en_prompt: str = ""
    en_valid: bool = False
    vision: VisionCallMeta = field(default_factory=lambda: VisionCallMeta(status=VISION_STATUS_UNAVAILABLE))


AUTHOR_DRAFT_LIMIT = 4000


class DualShotAuthorError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        errors: list[str] | None = None,
        zh_prompt: str = "",
        en_prompt: str = "",
        raw_prompt: str = "",
        vision: VisionCallMeta | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = [str(item).strip() for item in (errors or []) if str(item).strip()]
        self.zh_prompt = str(zh_prompt or "")
        self.en_prompt = str(en_prompt or "")
        self.raw_prompt = str(raw_prompt or "")
        self.vision = vision or VisionCallMeta(status=VISION_STATUS_UNAVAILABLE)

    def payload_fields(self, *, limit: int = AUTHOR_DRAFT_LIMIT) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "author_errors": list(self.errors),
            "author_zh_draft": self.zh_prompt[:limit],
            "author_en_draft": self.en_prompt[:limit],
        }
        if self.raw_prompt:
            fields["author_raw_draft"] = self.raw_prompt[:limit]
        vision = self.vision.as_dict()
        has_vision = (
            vision.get("vision_status") not in (None, "", VISION_STATUS_UNAVAILABLE)
            or bool(vision.get("vision_model"))
            or int(vision.get("vision_image_count") or 0) > 0
        )
        if has_vision:
            fields.update(vision)
        return fields


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

    @classmethod
    def _vlm_runtime_config(cls) -> tuple[str, str, str]:
        row = overlay_vlm_credentials(vlm_row(), llm_row())
        if not row.get("enabled"):
            raise ValueError(VLM_UNAVAILABLE_MESSAGE)
        base_url = str(row.get("base_url") or "").strip().rstrip("/")
        model = str(row.get("model") or "").strip()
        encrypted_key = row.get("api_key_encrypted")
        api_key = credential_manager().decrypt(encrypted_key) if encrypted_key else None
        if not api_key and is_local_base_url(base_url):
            api_key = "ollama"
        if not base_url or not model or not api_key:
            raise ValueError("视觉模型配置不完整，请检查服务地址、模型和 API Key。")
        if not model_supports_vision(model):
            raise ValueError(VLM_NOT_VISION_MESSAGE)
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
    def infer_asset_prompts_from_images(
        cls,
        *,
        kind: str,
        name: str,
        role: str = "",
        images: list[str],
    ) -> dict[str, Any]:
        if not images:
            raise ValueError("请先上传至少一张原片参考图")
        decrypt = credential_manager().decrypt
        endpoint = resolve_analysis_endpoint(llm_row(), overlay_vlm_credentials(vlm_row(), llm_row()), decrypt)
        if endpoint is None:
            raise ValueError(ANALYSIS_UNAVAILABLE_MESSAGE)
        raw = chat_on_endpoint(
            endpoint,
            infer_system_prompt(kind),
            infer_user_text(kind, name, role),
            images,
            max_tokens=1024,
            temperature=0.2,
            timeout=90.0,
        )
        parsed = parse_infer_payload(raw)
        parsed["model"] = endpoint.model
        return parsed

    @classmethod
    def chat_text(
        cls,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 6000,
        temperature: float = 0.4,
        timeout: float = 240.0,
    ) -> str:
        base_url, model, api_key = cls._runtime_config()
        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        extra: dict[str, Any] = {}
        if is_openai_reasoning_chat_model(model):
            extra["reasoning_effort"] = "low"
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                text = client.chat_completion(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    stream=True,
                    **extra,
                ).strip()
            except LlmTemporaryError as err:
                last_error = err
                if attempt == 0 and (is_llm_timeout_error(err) or "网关超时" in str(err)):
                    continue
                raise RuntimeError(str(err)) from err
            except LlmError as err:
                raise RuntimeError(str(err)) from err
            if not text:
                raise ValueError("大模型未返回提示词内容")
            return text
        raise RuntimeError(str(last_error or "大模型请求失败"))

    @classmethod
    def plan_episode_shots(cls, episode: dict[str, Any]) -> list[dict[str, Any]]:
        """按本集动作与对白规划出片镜头，单镜 5–15 秒。只处理这一集。"""
        if not isinstance(episode, dict):
            raise ValueError("本集数据无效，无法规划镜头。")
        has_body = bool(str(episode.get("body") or "").strip())
        has_shots = any(isinstance(item, dict) for item in (episode.get("shots") or []))
        if not has_body and not has_shots:
            raise ValueError("本集没有可供规划的动作或对白。")
        raw = cls.chat_text(
            build_shot_plan_system_prompt(),
            build_shot_plan_user_prompt(episode),
            max_tokens=4000,
            temperature=0.2,
        )
        shots = normalize_planned_shots(parse_shot_plan_response(raw))
        if not shots:
            raise ValueError("大模型未返回可出片镜头。")
        return shots

    @classmethod
    def chat_vision(
        cls,
        system_prompt: str,
        user_prompt: str,
        image_urls: list[str],
        *,
        max_tokens: int = 4000,
        temperature: float = 0.3,
    ) -> str:
        text, _meta = cls._complete_zh_author(system_prompt, user_prompt, image_urls, max_tokens=max_tokens, temperature=temperature)
        return text

    @classmethod
    def author_timestamped_zh_prompt(
        cls,
        recipe: Any,
        beat: dict[str, Any],
        assets: list[dict[str, Any]] | None = None,
        template: str = "",
        *,
        beat_info: dict[str, Any] | None = None,
    ) -> DualShotAuthorResult:
        from ...skill_packs.handlers import (
            ZH_BLOCK_MARK,
            build_dual_author_system,
            build_timestamped_zh_author_user,
            collect_zh_author_image_urls,
            extract_ref2va_prompt,
            extract_timestamped_zh_prompt,
            is_stub_en_prompt,
            parse_dual_author_output,
            validate_timestamped_zh_prompt,
        )

        assets = list(assets or [])
        info = dict(beat_info or {})
        template = str(template or "").strip() or str(recipe.reference_text("h3-video-prompt-template.md") or "")
        seconds = str(info.get("duration_seconds") or beat.get("duration_seconds") or beat.get("video_duration") or "8")
        system_prompt = build_dual_author_system(recipe, template, duration_seconds=seconds)
        user_prompt = build_timestamped_zh_author_user(recipe, beat, assets, beat_info=info)
        image_urls = collect_zh_author_image_urls(recipe, beat, assets)
        last_errors: list[str] = []
        last_zh = ""
        last_en = ""
        last_raw = ""
        vision = VisionCallMeta(status=VISION_STATUS_UNAVAILABLE)
        packed_info = cls._dual_pack_info(recipe, beat, assets, info)
        skip_pack = bool(getattr(getattr(recipe, "packing_overrides", None), "skip_program_pack", False))
        for _attempt in range(2):
            prompt = user_prompt
            if last_errors:
                prompt = (
                    f"{user_prompt}\n\n上次校验失败，请整篇重写 <<<ZH>>> 与 <<<EN>>> 两块，"
                    "不要只补一句，不要写「官方八块中文分秒稿与英文六段稿」这种说明。\n"
                    + "\n".join(f"- {item}" for item in last_errors)
                )
            try:
                raw, vision = cls._complete_zh_author(
                    system_prompt,
                    prompt,
                    image_urls,
                    max_tokens=16000,
                    temperature=0.3,
                )
            except Exception as err:
                last_errors = [str(err)]
                continue
            last_raw = raw
            last_zh, last_en = parse_dual_author_output(raw)
            last_zh = extract_timestamped_zh_prompt(last_zh)
            last_en = extract_ref2va_prompt(last_en)
            if last_zh:
                zh_errors = validate_timestamped_zh_prompt(last_zh, recipe, beat, assets)
            elif ZH_BLOCK_MARK not in last_raw:
                zh_errors = ["缺 <<<ZH>>> 中文分秒稿"]
            else:
                zh_errors = validate_timestamped_zh_prompt(last_zh, recipe, beat, assets)
            en_errors: list[str] = []
            if last_en:
                packed_info["timestamped_zh_prompt"] = last_zh
                if skip_pack:
                    last_en = H3PromptBuilder.canonicalize_authored_ref2va(
                        last_en,
                        H3PromptBuilder.shot_from_beat_info(packed_info),
                    )
                    if is_stub_en_prompt(last_en):
                        en_errors = [
                            "上轮英文块只写了说明句，必须从 subject_definitions: 写到 non_diegetic_music:，并保留 [Shot 1] 与 <Picture n>"
                        ]
                    else:
                        en_errors = cls._validate_h3_prompt(last_en, "Ref2VA", packed_info)
                else:
                    shot = H3PromptBuilder.shot_from_beat_info(packed_info)
                    prepared = H3PromptBuilder.prepare_generated_prompt(last_en, shot)
                    last_en = prepared
                    en_errors = cls._validate_h3_prompt(prepared, "Ref2VA", packed_info)
            elif last_zh:
                en_errors = ["缺少 <<<EN>>> 六段英文稿"]
            last_errors = [*zh_errors, *en_errors]
            if not last_errors:
                result = DualShotAuthorResult(
                    zh_prompt=last_zh,
                    en_prompt=last_en,
                    en_valid=True,
                    vision=vision,
                )
                cls._apply_author_result(info, result)
                if isinstance(beat_info, dict):
                    cls._apply_author_result(beat_info, result)
                return result
        zh_errors = validate_timestamped_zh_prompt(last_zh, recipe, beat, assets) if last_zh else ["中文分秒稿为空"]
        if skip_pack or zh_errors:
            raise DualShotAuthorError(
                "写稿未通过校验：" + "；".join(last_errors or zh_errors or ["空结果"]),
                errors=last_errors or zh_errors,
                zh_prompt=last_zh,
                en_prompt=last_en,
                raw_prompt=last_raw,
                vision=vision,
            )
        result = DualShotAuthorResult(
            zh_prompt=last_zh,
            en_prompt=last_en,
            en_valid=False,
            vision=vision,
        )
        cls._apply_author_result(info, result)
        if isinstance(beat_info, dict):
            cls._apply_author_result(beat_info, result)
        return result

    @classmethod
    def _dual_pack_info(
        cls,
        recipe: Any,
        beat: dict[str, Any],
        assets: list[dict[str, Any]],
        beat_info: dict[str, Any],
    ) -> dict[str, Any]:
        packed = {**beat, **beat_info}
        if getattr(recipe, "id", None):
            packed["skill_pack_id"] = recipe.id
        if getattr(getattr(recipe, "packing_overrides", None), "faithful_zh_pack", False):
            packed["faithful_zh_pack"] = True
        if not packed.get("ref_images"):
            from ...skill_packs.handlers import bind_r2v_slot_images

            slots = bind_r2v_slot_images(recipe, packed, assets)
            if slots:
                packed["ref_images"] = slots
        return packed

    @staticmethod
    def _apply_author_result(target: dict[str, Any], result: DualShotAuthorResult) -> None:
        target["timestamped_zh_prompt"] = result.zh_prompt
        target["authored_en_prompt"] = result.en_prompt
        target["authored_en_valid"] = result.en_valid
        target["authored_en_attempted"] = True
        target.update(result.vision.as_dict())

    @classmethod
    def _complete_zh_author(
        cls,
        system_prompt: str,
        user_prompt: str,
        image_urls: list[str],
        *,
        max_tokens: int = 16000,
        temperature: float = 0.3,
    ) -> tuple[str, VisionCallMeta]:
        decrypt = credential_manager().decrypt
        return complete_authoring(
            llm_row(),
            vlm_row(),
            decrypt,
            system_prompt,
            user_prompt,
            image_urls,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    @classmethod
    def resolve_h3_prompt_mode(cls, beat_info: dict[str, Any]) -> str:
        aliases = {
            "t2va": "T2VA", "t2v": "T2VA", "i2va": "I2VA", "i2v": "I2VA",
            "fl2va": "FL2VA", "fl2v": "FL2VA", "l2va": "L2VA", "l2v": "L2VA",
            "ref2va": "Ref2VA", "r2v": "Ref2VA", "fullreference": "Ref2VA",
        }
        explicit = re.sub(r"[\s_-]+", "", str(beat_info.get("prompt_mode") or "").strip().lower())
        if explicit in aliases:
            return aliases[explicit]
        pictures = [item for item in (beat_info.get("ref_images") or []) if isinstance(item, dict)]
        videos = [item for item in (beat_info.get("ref_videos") or []) if isinstance(item, dict)]
        audios = [item for item in (beat_info.get("ref_audios") or []) if isinstance(item, dict)]
        roles = {str(item.get("role") or item.get("frame_role") or "").strip().lower() for item in pictures}
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
    def _h3_rule_text(cls, mode: str, duration_seconds: str = "8") -> str:
        return H3PromptBuilder.packing_rule_text(mode, duration_seconds)

    @classmethod
    def _h3_system_prompt(
        cls,
        mode: str,
        duration_seconds: str,
        packing_overrides: dict[str, Any] | None = None,
        skill_pack_id: str | None = None,
    ) -> str:
        overrides = packing_overrides
        if overrides is None and skill_pack_id:
            from ...skill_packs import packing_overrides_of

            overrides = packing_overrides_of(skill_pack_id)
        prompt = H3PromptBuilder.packing_system_prompt(mode, duration_seconds, packing_overrides=overrides)
        if skill_pack_id:
            from ...director_craft.coverage import COVERAGE_CONTRACT_EXCERPT
            from ...skill_packs import craft_overlay_for_stage

            overlay = craft_overlay_for_stage("optimize", skill_pack_id)
            extras = [item for item in (overlay, COVERAGE_CONTRACT_EXCERPT) if str(item or "").strip()]
            if extras:
                prompt = prompt + "\n\n" + "\n\n".join(extras)
        return prompt

    @classmethod
    def _h3_user_prompt(cls, beat_info: dict[str, Any], mode: str, duration_seconds: str) -> str:
        return H3PromptBuilder.build_packing_user_prompt(beat_info, mode, duration_seconds)

    @classmethod
    def _skip_program_pack(cls, beat_info: dict[str, Any] | None = None) -> bool:
        from ...skill_packs import resolve_skill_pack_id, skip_program_pack_enabled

        info = beat_info if isinstance(beat_info, dict) else {}
        pack_id = str(info.get("skill_pack_id") or "").strip()
        if not pack_id:
            pack_id = resolve_skill_pack_id(payload=info, project_id=info.get("project_id")) or ""
        return skip_program_pack_enabled(pack_id)

    @classmethod
    def _validate_h3_prompt(cls, prompt: str, mode: str, beat_info: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        text = str(prompt or "").strip()
        sections = H3_REF_SECTIONS if mode == "Ref2VA" else H3_BASE_SECTIONS
        positions = [re.search(rf"(?m)^{re.escape(name)}:\s*", text) for name in sections]
        starts = [match.start() if match else -1 for match in positions]
        if any(pos < 0 for pos in starts) or starts != sorted(starts):
            errors.append("required section headings are missing or out of order")
        expected: list[str] = []
        seen_lines: set[str] = set()
        shot_for_speech = H3PromptBuilder.shot_from_beat_info(beat_info)

        def add_expected(raw: Any, speaker: Any = "") -> None:
            cleaned = cls._clean_h3_dialogue(raw, speaker)
            if not cleaned:
                return
            for atom in H3PromptBuilder.split_speech_atoms(cleaned):
                key = H3PromptBuilder._han_only(atom) or atom
                if not key or key in seen_lines:
                    continue
                seen_lines.add(key)
                expected.append(atom)

        spoken = list(beat_info.get("dialogue_turns") or []) or H3PromptBuilder._dialogue_turns(shot_for_speech)
        if isinstance(spoken, list):
            for turn in spoken:
                if not isinstance(turn, dict):
                    continue
                if H3PromptBuilder._is_inner_speaker(str(turn.get("speaker") or ""), str(turn.get("delivery") or "")):
                    continue
                add_expected(turn.get("text"), turn.get("speaker"))
        for turn in H3PromptBuilder._inner_turns(shot_for_speech):
            add_expected(turn.get("text"), turn.get("speaker"))
        for line in expected:
            if not H3PromptBuilder.prompt_contains_line(text, line):
                errors.append(f"dialogue not preserved verbatim: {line[:80]}")
        visible_text = str(beat_info.get("visible_text") or "").strip()
        if visible_text and not H3PromptBuilder.prompt_contains_line(text, visible_text):
            errors.append("visible text not preserved verbatim")
        if mode == "Ref2VA":
            for item in beat_info.get("ref_images") or []:
                if not isinstance(item, dict) or not item.get("index"):
                    continue
                if not re.search(rf"<Picture\s+{re.escape(str(item.get('index')))}\s*>", text, flags=re.I):
                    errors.append(f"missing <Picture {item.get('index')}>")
        if mode == "T2VA" and re.search(r"<(?:Picture|Subject|Video|Audio) \d+>", text):
            errors.append("T2VA prompt must not invent reference labels")
        if "[Shot 1]" not in text:
            errors.append("missing [Shot 1]")
        skip_pack = cls._skip_program_pack(beat_info)
        if skip_pack:
            errors.extend(H3PromptBuilder.inner_delivery_errors(text, shot_for_speech))
        else:
            errors.extend(H3PromptBuilder.thickness_errors(text))
            errors.extend(H3PromptBuilder.speech_contract_errors(text, shot_for_speech))
            errors.extend(H3PromptBuilder.craft_prompt_errors(text, shot_for_speech))
        return errors

    @classmethod
    def generate_h3_prompt(cls, beat_info: dict[str, Any]) -> str:
        from ...skill_packs import resolve_skill_pack_id

        source = beat_info if isinstance(beat_info, dict) else {}
        beat_info = H3PromptBuilder.sanitize_beat_draft(source)
        pack_id = resolve_skill_pack_id(payload=beat_info, project_id=source.get("project_id") or beat_info.get("project_id"))
        if pack_id:
            beat_info = {**beat_info, "skill_pack_id": pack_id}

        def _sync_workshop_fields() -> None:
            for key in (
                "timestamped_zh_prompt",
                "video_prompt_zh",
                "ref_images",
                "authored_en_prompt",
                "authored_en_valid",
                "authored_en_attempted",
                "vision_status",
                "vision_model",
                "vision_image_count",
                "vision_source",
            ):
                if key in beat_info and beat_info.get(key) not in (None, ""):
                    source[key] = beat_info[key]

        mode = cls.resolve_h3_prompt_mode(beat_info)
        shot = H3PromptBuilder.shot_from_beat_info(beat_info)
        duration_seconds = str(beat_info.get("duration_seconds") or "8").strip() or "8"
        if mode == "Ref2VA":
            from ...skill_packs import run_workshop_prompt

            emit_llm_stream_status("author", "正在看图写稿", reset=True)
            prompt = run_workshop_prompt(beat_info)
            _sync_workshop_fields()
            skip_pack = False
            if pack_id:
                from ...skill_packs import packing_overrides_of

                overrides = packing_overrides_of(pack_id)
                if overrides.get("faithful_zh_pack"):
                    beat_info["faithful_zh_pack"] = True
                skip_pack = bool(overrides.get("skip_program_pack"))
            shot = H3PromptBuilder.shot_from_beat_info(beat_info)
            if skip_pack:
                authored_en = str(beat_info.get("authored_en_prompt") or "").strip()
                if not H3PromptBuilder.has_ref2va_headings(authored_en):
                    raise DualShotAuthorError(
                        "写稿未通过校验：英文六段缺失或标题不齐",
                        errors=["英文六段缺失或标题不齐"],
                        zh_prompt=str(beat_info.get("timestamped_zh_prompt") or ""),
                        en_prompt=authored_en,
                    )
                prompt = H3PromptBuilder.canonicalize_authored_ref2va(authored_en, shot)
                errors = cls._validate_h3_prompt(prompt, mode, beat_info)
                if errors:
                    raise DualShotAuthorError(
                        "写稿未通过校验：" + "；".join(errors),
                        errors=errors,
                        zh_prompt=str(beat_info.get("timestamped_zh_prompt") or ""),
                        en_prompt=prompt,
                    )
                _sync_workshop_fields()
                return prompt
            prompt = H3PromptBuilder.prepare_generated_prompt(prompt, shot)
            errors = cls._validate_h3_prompt(prompt, mode, beat_info)
            if not pack_id:
                if errors:
                    raise ValueError("H3 提示词未通过规则校验：" + "；".join(errors))
                _sync_workshop_fields()
                return prompt
            workshop_prompt = prompt
            workshop_errors = list(errors)
            packed_info = dict(beat_info)
            zh_prompt = str(
                packed_info.get("timestamped_zh_prompt") or packed_info.get("video_prompt_zh") or ""
            ).strip()
            if zh_prompt:
                existing = str(packed_info.get("visual_prompt") or "").strip()
                packed_info["visual_prompt"] = f"{existing}\n\n{zh_prompt}".strip() if existing else zh_prompt
                packed_info["timestamped_zh_prompt"] = zh_prompt
            authored_en = str(packed_info.get("authored_en_prompt") or "").strip()
            authored_valid = bool(packed_info.get("authored_en_valid"))
            authored_attempted = bool(packed_info.get("authored_en_attempted")) or bool(authored_en)
            if authored_valid and authored_en:
                packed = H3PromptBuilder.prepare_generated_prompt(authored_en, shot)
                packed_errors = cls._validate_h3_prompt(packed, mode, beat_info)
                if not packed_errors:
                    _sync_workshop_fields()
                    return packed
                authored_valid = False
            if authored_attempted:
                merged = H3PromptBuilder.prepare_generated_prompt(
                    H3PromptBuilder.overlay_packed_detail(workshop_prompt, authored_en or workshop_prompt),
                    shot,
                )
                merged_errors = cls._validate_h3_prompt(merged, mode, beat_info)
                if not merged_errors:
                    _sync_workshop_fields()
                    return merged
                if not workshop_errors:
                    _sync_workshop_fields()
                    return workshop_prompt
                heading_only = list(merged_errors or workshop_errors) == [
                    "required section headings are missing or out of order"
                ]
                workshop_heading_ok = all("section headings" not in item for item in workshop_errors)
                if heading_only and workshop_heading_ok:
                    _sync_workshop_fields()
                    return workshop_prompt
                raise ValueError("H3 提示词未通过规则校验：" + "；".join(merged_errors or workshop_errors))
            system_prompt = cls._h3_system_prompt(mode, duration_seconds, skill_pack_id=pack_id)
            user_prompt = cls._h3_user_prompt(packed_info, mode, duration_seconds)
            if workshop_errors:
                user_prompt = f"{user_prompt}\n\n{H3PromptBuilder.packing_retry_block(workshop_errors, workshop_prompt, beat_info=packed_info)}"
            emit_llm_stream_status("pack", "正在装箱六段英文", reset=True)
            prompt = cls._request_h3_prompt(system_prompt, user_prompt, beat_info)
            prompt = H3PromptBuilder.prepare_generated_prompt(prompt, shot)
            errors = cls._validate_h3_prompt(prompt, mode, beat_info)
            if errors:
                retry_user = f"{user_prompt}\n\n{H3PromptBuilder.packing_retry_block(errors, prompt, beat_info=packed_info)}"
                emit_llm_stream_status("pack", "正在按规则重写六段", reset=True)
                prompt = cls._request_h3_prompt(system_prompt, retry_user, beat_info)
                prompt = H3PromptBuilder.prepare_generated_prompt(prompt, shot)
                errors = cls._validate_h3_prompt(prompt, mode, beat_info)
            if errors:
                merged = H3PromptBuilder.prepare_generated_prompt(
                    H3PromptBuilder.overlay_packed_detail(workshop_prompt, prompt),
                    shot,
                )
                merged_errors = cls._validate_h3_prompt(merged, mode, beat_info)
                if not merged_errors:
                    prompt = merged
                elif not workshop_errors:
                    prompt = workshop_prompt
                else:
                    heading_only = errors == ["required section headings are missing or out of order"]
                    workshop_heading_ok = all("section headings" not in item for item in workshop_errors)
                    if heading_only and workshop_heading_ok:
                        prompt = workshop_prompt
                    else:
                        raise ValueError("H3 提示词未通过规则校验：" + "；".join(errors))
            _sync_workshop_fields()
            return prompt
        system_prompt = cls._h3_system_prompt(mode, duration_seconds, skill_pack_id=pack_id or None)
        user_prompt = cls._h3_user_prompt(beat_info, mode, duration_seconds)
        emit_llm_stream_status("write", "正在生成提示词", reset=True)
        prompt = cls._request_h3_prompt(system_prompt, user_prompt, beat_info)
        prompt = H3PromptBuilder.prepare_generated_prompt(prompt, shot)
        errors = cls._validate_h3_prompt(prompt, mode, beat_info)
        if errors:
            retry_user = f"{user_prompt}\n\n{H3PromptBuilder.packing_retry_block(errors, prompt)}"
            prompt = cls._request_h3_prompt(system_prompt, retry_user, beat_info)
            prompt = H3PromptBuilder.prepare_generated_prompt(prompt, shot)
            errors = cls._validate_h3_prompt(prompt, mode, beat_info)
        if errors:
            raise ValueError("H3 提示词未通过规则校验：" + "；".join(errors))
        return prompt

    @classmethod
    def _request_h3_prompt(cls, system_prompt: str, user_prompt: str, beat_info: dict[str, Any]) -> str:
        prompt = cls.chat_text(system_prompt, user_prompt, max_tokens=6000, temperature=0.4)
        speakers = [str(beat_info.get("speaker") or "").strip()]
        for turn in beat_info.get("dialogue_turns") or []:
            if isinstance(turn, dict):
                speakers.append(str(turn.get("speaker") or "").strip())
        parsed = H3PromptBuilder._parse_script_turns(str(beat_info.get("dialogue") or ""))
        speakers.extend(item["speaker"] for item in parsed)
        return cls._clean_h3_prompt_dialogue(prompt, speakers)

    @staticmethod
    def _clean_h3_dialogue(dialogue: Any, speaker: Any = "") -> str:
        return H3PromptBuilder._clean_dialogue(str(dialogue or ""), str(speaker or ""))

    @classmethod
    def _clean_h3_prompt_dialogue(cls, prompt: str, speakers: Any = "") -> str:
        if not prompt:
            return prompt
        names = speakers if isinstance(speakers, list) else [str(speakers or "").strip()]
        names = [str(item).strip() for item in names if str(item).strip()]

        def clean_tag(match: re.Match[str]) -> str:
            language = match.group(1)
            dialogue = H3PromptBuilder._clean_dialogue(match.group(2), extra_names=names)
            return f"<d>{language}{dialogue}</d>"

        return re.sub(r"<d>(\[[^\]]+\]\s*)(.*?)</d>", clean_tag, prompt, flags=re.DOTALL)
