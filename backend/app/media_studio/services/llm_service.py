from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse
import requests

from ..provider_bridge import credential_manager, llm_row, vlm_row
from ...llm_client import LlmError, OpenAICompatibleClient
from ...llm_provider import model_supports_vision
from ...vlm_provider import VLM_UNAVAILABLE_MESSAGE, VLM_NOT_VISION_MESSAGE
from ...llm_minimax_skills import (
    build_workshop_h3_timing_rules,
    load_h3_prompt_writing_guide,
    load_h3_prompt_writing_skill,
)
from .asset_prompt_inference import infer_system_prompt, infer_user_text, parse_infer_payload
from .h3_prompt_builder import H3PromptBuilder, H3_SPEECH_UNIQUENESS_RULES

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
        row = vlm_row()
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
        base_url, model, api_key = cls._vlm_runtime_config()
        content: list[dict[str, Any]] = [
            {"type": "text", "text": infer_user_text(kind, name, role)},
            *[{"type": "image_url", "image_url": {"url": url}} for url in images],
        ]
        client = OpenAICompatibleClient(base_url=base_url, api_key=api_key)
        try:
            raw = client.chat_completion(
                [
                    {"role": "system", "content": infer_system_prompt(kind)},
                    {"role": "user", "content": content},
                ],
                model=model,
                temperature=0.2,
                max_tokens=1024,
                timeout=90.0,
            )
        except LlmError as err:
            raise RuntimeError(str(err)) from err
        parsed = parse_infer_payload(raw)
        parsed["model"] = model
        return parsed

    @classmethod
    def chat_text(
        cls,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 6000,
        temperature: float = 0.4,
    ) -> str:
        base_url, model, api_key = cls._runtime_config()
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=240,
        )
        if not response.ok:
            raise RuntimeError(f"大模型请求失败，HTTP {response.status_code}: {response.text[:500]}")
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        text = str(content or "").strip()
        if not text:
            raise ValueError("大模型未返回提示词内容")
        return text

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
        skill = load_h3_prompt_writing_skill()
        base = load_h3_prompt_writing_guide(mode="base")
        if mode == "Ref2VA":
            ref = load_h3_prompt_writing_guide(mode="ref")
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
        return (
            f"{build_workshop_h3_timing_rules(duration_seconds)}\n\n"
            f"{skill}\n\n{selected}"
        )

    @classmethod
    def _h3_system_prompt(cls, mode: str, duration_seconds: str) -> str:
        if mode == "Ref2VA":
            headings = "\n".join(f"{name}:" for name in H3_REF_SECTIONS)
            structure = (
                "Return only the finished prompt. It must contain exactly these six section headings, "
                f"spelled exactly and in this order, with each heading on its own line:\n{headings}\n\n"
                "Write all six sections in English. Preserve the original language only for dialogue, lyrics, "
                "and visible scene text. A speaker name is metadata, never dialogue."
            )
        else:
            headings = "\n".join(f"{name}:" for name in H3_BASE_SECTIONS)
            if mode == "T2VA":
                instruction = "Begin directly with integrated_multimodal_description."
            elif mode == "I2VA":
                instruction = "The first line must be exactly: For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
            elif mode == "FL2VA":
                instruction = f"Use the FL2VA first-and-last-frame alignment instruction, with {duration_seconds}.00 as the last-frame timestamp."
            else:
                instruction = f"Use the L2VA last-frame alignment instruction, aligning <Picture 1> with the {duration_seconds}.00-second mark."
            structure = (
                f"Return only the finished {mode} prompt.\n{instruction}\n"
                f"Follow it with exactly these core fields, each heading on its own line:\n{headings}"
            )
        picture_body = (
            "detailed_description" if mode == "Ref2VA" else "integrated_multimodal_description"
        )
        return (
            f"You are a MiniMax H3 prompt writer. Follow the skill and selected guide exactly for mode {mode}. "
            f"Fit all described action and complete speech naturally within {duration_seconds} seconds.\n\n"
            f"{structure}\n\n"
            "Assign actual speakers stable global IDs (S1), (S2). Put spoken content only inside "
            "<d>[Language] ...</d>. Never put the speaker name or quotation wrappers inside <d>. "
            "Do not invent dialogue. Use at most one camera move with small amplitude at slow speed, or a static hold. "
            f"{H3_SPEECH_UNIQUENESS_RULES} "
            "Expand the beat's Chinese action, English visual_prompt, and audio fully into "
            f"{picture_body} and overall_soundscape. Do not copy a one-sentence summary. "
            "Write at least 320 English words. The picture body must cover composition, blocking and "
            "referenced appearance, environment, lighting, props, "
            f"chronological {duration_seconds}-second performance, "
            "camera type/amplitude/speed, synchronized physical sounds, closed lips or lip-sync, and a final held frame. "
            "Use exactly one [Shot 1]; no internal cuts and no timecodes.\n\n"
            f"--- skill rules ---\n{cls._h3_rule_text(mode, duration_seconds)}"
        )

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
                user_lines.append(f"{idx}. {prop.get('name')}（{prop.get('desc') or '特征完好'}）")
        cleaned_dialogue = cls._clean_h3_dialogue(beat_info.get("dialogue"), beat_info.get("speaker"))
        visual_prompt = str(beat_info.get("visual_prompt") or "").strip()
        audio = str(beat_info.get("audio") or beat_info.get("soundscape") or "").strip()
        video_prompt_zh = str(beat_info.get("video_prompt_zh") or "").strip()
        shot_for_speech = {
            "dialogue": beat_info.get("dialogue"),
            "speaker": beat_info.get("speaker"),
            "dialogue_turns": beat_info.get("dialogue_turns"),
            "narration": beat_info.get("narration"),
            "characters": [item.get("name") for item in characters if isinstance(item, dict)],
        }
        spoken_turns = list(beat_info.get("dialogue_turns") or []) or H3PromptBuilder._dialogue_turns(shot_for_speech)
        if spoken_turns:
            spoken_turns = [
                {
                    **turn,
                    "text": cls._clean_h3_dialogue(turn.get("text"), turn.get("speaker")),
                }
                for turn in spoken_turns
                if isinstance(turn, dict) and not H3PromptBuilder._is_inner_speaker(
                    str(turn.get("speaker") or ""),
                    str(turn.get("delivery") or ""),
                )
            ]
        inner_turns = H3PromptBuilder._inner_turns(shot_for_speech)
        echo_lines = [
            str(turn.get("text") or "").strip()
            for turn in [*spoken_turns, *inner_turns]
            if str(turn.get("text") or "").strip()
        ]
        action = H3PromptBuilder.strip_script_echo(str(beat_info.get("action") or ""), echo_lines)
        visual_prompt = H3PromptBuilder.strip_script_echo(visual_prompt, echo_lines)
        video_prompt_zh = H3PromptBuilder.strip_script_echo(video_prompt_zh, echo_lines)
        user_lines.extend([
            f"画面动作与细节要求（中文动作，必须展开进画面正文，禁止只抄一句；不要复述台词原文）：{action or '画面进行中'}",
            f"英文 visual_prompt（必须展开进画面正文，不要再贴中文台词原文）：{visual_prompt or '无'}",
            f"音效 / audio（必须写入 overall_soundscape 与同期声）：{audio or '无'}",
        ])
        if video_prompt_zh and action and action in video_prompt_zh:
            pass
        elif video_prompt_zh:
            user_lines.append(f"中文视频提示拼接 video_prompt_zh：{video_prompt_zh}")
        spoken_blob = " ".join(
            str(turn.get("text") or "").strip()
            for turn in spoken_turns
            if str(turn.get("text") or "").strip()
        )
        if not spoken_turns and not inner_turns:
            spoken_blob = cleaned_dialogue
        user_lines.extend([
            "镜头与机位：" + (str(beat_info.get("camera") or "").strip() or "固定机位，或一次缓慢小幅运镜"),
            f"时间与环境氛围：{beat_info.get('time_of_day') or '日间'}",
            f"视频时长：{duration_seconds} 秒",
            f"说话人（仅作元数据，不得写入 <d> 台词正文）：{beat_info.get('speaker') or '无'}",
            f"对白原文（仅开口台词，每句只出现一次，必须逐字放入 <d>，不得包含说话人姓名和外围引号）：{spoken_blob or '无对白'}",
        ])
        if spoken_turns:
            user_lines.append("多轮开口对白（按顺序保留原文，每轮使用稳定说话人 ID，禁止口型同步内心）：")
            for turn in spoken_turns:
                speaker = str(turn.get("speaker") or "").strip()
                text = cls._clean_h3_dialogue(turn.get("text"), speaker)
                if text:
                    user_lines.append(f"- {speaker or '未命名说话人'}：{text}")
        visible_text = str(beat_info.get("visible_text") or "").strip()
        if visible_text:
            user_lines.append(f"画面可见文字（原样保留，不得朗读）：{visible_text}")
        if inner_turns:
            user_lines.append("旁白/内心（画外音，可见人物嘴唇保持闭合，禁止口型同步，成品里中文只出现一次）：")
            for turn in inner_turns:
                speaker = str(turn.get("speaker") or "").strip()
                text = cls._clean_h3_dialogue(turn.get("text"), speaker)
                if text:
                    user_lines.append(f"- {speaker or '旁白'}：{text}")
        user_lines.append("reference_map（标签含义必须严格一一对应，禁止增删改编号）：")
        ref_images = beat_info.get("ref_images") or []
        if mode == "T2VA":
            user_lines.append("- 无参考图。使用 T2VA，不要编造 <Picture N> 或 <Subject N>。")
        elif ref_images:
            for item in ref_images:
                cat = item.get("category")
                cat_name = "场景" if cat == "scene" else ("道具" if cat == "prop" else "角色")
                user_lines.append(f"- <Picture {item.get('index')}>: {item.get('name')}（{cat_name}参考图）")
        else:
            user_lines.append("- 未提供可用参考素材。不要编造引用标签。")
        user_lines.extend([
            "",
            "英文成品至少 320 词。detailed_description / integrated_multimodal_description 必须覆盖构图、"
            f"站位与参考外形、环境、光影、道具、{duration_seconds} 秒时序、机位类型/幅度/速度、同期声、闭嘴或口型、结尾定格。"
            f"单镜 [Shot 1] 必须在 {duration_seconds} 秒内演完对白与调度，禁止写成更长的戏再压进短片。无内切、无时间码。"
            "同一句中文在成品里只能出现一次；开口台词口型同步，内心/旁白闭嘴画外音。",
        ])
        return "\n".join(user_lines)

    @classmethod
    def _validate_h3_prompt(cls, prompt: str, mode: str, beat_info: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        text = str(prompt or "").strip()
        sections = H3_REF_SECTIONS if mode == "Ref2VA" else H3_BASE_SECTIONS
        positions = [re.search(rf"(?m)^{re.escape(name)}:\s*$", text) for name in sections]
        starts = [match.start() if match else -1 for match in positions]
        if any(pos < 0 for pos in starts) or starts != sorted(starts):
            errors.append("required section headings are missing or out of order")
        expected: list[str] = []
        shot_for_speech = {
            "dialogue": beat_info.get("dialogue"),
            "speaker": beat_info.get("speaker"),
            "dialogue_turns": beat_info.get("dialogue_turns"),
            "narration": beat_info.get("narration"),
        }
        spoken = list(beat_info.get("dialogue_turns") or []) or H3PromptBuilder._dialogue_turns(shot_for_speech)
        if isinstance(spoken, list):
            for turn in spoken:
                if not isinstance(turn, dict):
                    continue
                if H3PromptBuilder._is_inner_speaker(str(turn.get("speaker") or ""), str(turn.get("delivery") or "")):
                    continue
                cleaned = cls._clean_h3_dialogue(turn.get("text"), turn.get("speaker"))
                if cleaned:
                    expected.append(cleaned)
        for turn in H3PromptBuilder._inner_turns(shot_for_speech):
            cleaned = cls._clean_h3_dialogue(turn.get("text"), turn.get("speaker"))
            if cleaned and cleaned not in expected:
                expected.append(cleaned)
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
        errors.extend(H3PromptBuilder.thickness_errors(text))
        errors.extend(H3PromptBuilder.speech_uniqueness_errors(text, shot_for_speech))
        return errors

    @classmethod
    def generate_h3_prompt(cls, beat_info: dict[str, Any]) -> str:
        mode = cls.resolve_h3_prompt_mode(beat_info)
        duration_seconds = str(beat_info.get("duration_seconds") or "8").strip() or "8"
        system_prompt = cls._h3_system_prompt(mode, duration_seconds)
        user_prompt = cls._h3_user_prompt(beat_info, mode, duration_seconds)
        shot = H3PromptBuilder.shot_from_beat_info(beat_info)
        prompt = cls._request_h3_prompt(system_prompt, user_prompt, beat_info)
        prompt = H3PromptBuilder.prepare_generated_prompt(prompt, shot)
        errors = cls._validate_h3_prompt(prompt, mode, beat_info)
        if errors:
            retry_user = (
                f"{user_prompt}\n\nThe previous output failed validation. Rewrite the complete prompt.\n"
                + "\n".join(f"- {item}" for item in errors)
                + f"\nPrevious output:\n{prompt}"
            )
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
