from __future__ import annotations

import json
import re
from typing import Any, Callable

import requests

from ..crypto import CredentialManager
from ..config import settings
from ..db import query_one
from .llm_service import is_local_base_url


H3_SECTIONS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)


class H3PromptBuilder:
    """Generate and validate MiniMax H3 Ref2VA prompts for episode beats."""

    @staticmethod
    def _runtime_config() -> tuple[str, str, str]:
        row = query_one("SELECT * FROM ai_llm_provider_settings WHERE id = 1") or {}
        if not row.get("enabled"):
            raise ValueError("大模型供应商未启用，请先前往系统设置启用大模型服务。")
        base_url = str(row.get("base_url") or "").strip().rstrip("/")
        model = str(row.get("model") or "").strip()
        encrypted_key = row.get("api_key_encrypted")
        api_key = CredentialManager(settings.credential_key).decrypt(encrypted_key) if encrypted_key else None
        if not api_key and is_local_base_url(base_url):
            api_key = "ollama"
        if not base_url or not model or not api_key:
            raise ValueError("大模型供应商配置不完整，请检查地址、模型和 API Key。")
        return base_url, model, api_key

    @classmethod
    def ensure_available(cls) -> dict[str, str]:
        base_url, model, _ = cls._runtime_config()
        return {"base_url": base_url, "model": model}

    @staticmethod
    def _speaker_map(shots: list[dict[str, Any]]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for shot in shots:
            speaker = str(shot.get("speaker") or "").strip()
            if speaker and speaker not in mapping:
                mapping[speaker] = f"S{len(mapping) + 1}"
        return mapping

    @classmethod
    def build_prompts(
        cls,
        shots: list[dict[str, Any]],
        on_attempt: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[str]:
        base_url, model, api_key = cls._runtime_config()
        speaker_map = cls._speaker_map(shots)
        prompts: list[str] = []
        for shot in shots:
            source = cls._shot_source(shot, speaker_map)
            required_contract = cls._required_contract(shot, speaker_map)
            errors: list[str] = []
            for attempt in range(1, 3):
                correction = ""
                if errors:
                    correction = (
                        "\nThe previous answer failed validation. Correct every issue: "
                        + "; ".join(errors)
                    )
                raw_response = ""
                prompt = ""
                try:
                    response = requests.post(
                        f"{base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": cls._system_prompt()},
                                {"role": "user", "content": (
                                    "Create exactly one independent eight-second Ref2VA prompt for this beat. "
                                    "Return JSON only as {\"beat_id\":\"...\",\"prompt\":\"...\"}. "
                                    "Write at least 320 English words in the prompt. Do not put content on the "
                                    "same line as a section heading. Copy every mandatory literal below exactly; "
                                    "do not remove angle brackets, change [Chinese], or paraphrase quoted text.\n"
                                    f"Mandatory literal contract:\n{required_contract}\n"
                                    "Do not omit, translate, paraphrase, or shorten dialogue and narration.\n"
                                    f"Stable speaker IDs for the whole episode: {json.dumps(speaker_map, ensure_ascii=False)}\n"
                                    f"Input beat: {json.dumps(source, ensure_ascii=False)}{correction}"
                                )},
                            ],
                            "temperature": 0.35,
                            "max_tokens": 5000,
                            "response_format": {"type": "json_object"},
                        },
                        timeout=240,
                    )
                    raw_response = response.text
                    if not response.ok:
                        errors = [f"HTTP {response.status_code}: {response.text[:500]}"]
                    else:
                        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                        raw_response = str(content or "")
                        parsed = cls._parse_json(raw_response)
                        prompt = cls._prompt_from_response(parsed, str(shot["beat_id"]))
                        prompt = cls._normalize_prompt(shot, prompt, speaker_map)
                        errors = cls.validate_prompts([shot], [prompt], speaker_map)
                except Exception as err:
                    errors = [str(err)]

                passed = not errors
                if on_attempt:
                    on_attempt({
                        "beat_id": str(shot["beat_id"]),
                        "sequence": int(shot.get("sequence") or len(prompts) + 1),
                        "attempt": attempt,
                        "raw_response": raw_response,
                        "prompt": prompt,
                        "errors": list(errors),
                        "status": "passed" if passed else "failed",
                    })
                if passed:
                    prompts.append(prompt)
                    break
            else:
                raise ValueError(
                    f"Beat {shot.get('sequence', len(prompts) + 1)} H3 提示词连续两次未通过规则校验："
                    + "；".join(errors)
                )
        return prompts

    @staticmethod
    def _shot_source(shot: dict[str, Any], speaker_map: dict[str, str]) -> dict[str, Any]:
        character_references = shot.get("character_references") or [{
            "character_name": shot.get("character_name") or "protagonist",
            "description": shot.get("character_description") or "",
        }]
        reference_map = [
            {
                "picture": f"<Picture {index}>",
                "subject": f"<Subject {index}>",
                "type": "character",
                "character_name": reference.get("character_name") or "",
                "appearance": reference.get("description") or "",
            }
            for index, reference in enumerate(character_references, start=1)
        ]
        scene_picture_index = len(reference_map) + 1
        reference_map.append({
            "picture": f"<Picture {scene_picture_index}>",
            "subject": f"<Subject {scene_picture_index}>",
            "type": "scene",
            "scene": shot.get("scene") or "",
            "description": shot.get("scene_description") or "",
        })
        return {
            "beat_id": shot["beat_id"],
            "sequence": shot["sequence"],
            "heading": shot.get("heading") or "",
            "action": shot.get("action") or "",
            "camera": shot.get("camera") or "",
            "dialogue": shot.get("dialogue") or "",
            "narration": shot.get("narration") or "",
            "speaker": shot.get("speaker") or "",
            "speaker_id": speaker_map.get(str(shot.get("speaker") or "").strip()),
            "characters": shot.get("characters") or [],
            "props": shot.get("props") or [],
            "scene": shot.get("scene") or "",
            "character_reference_description": shot.get("character_description") or "",
            "scene_reference_description": shot.get("scene_description") or "",
            "reference_map": reference_map,
            "duration_seconds": 8,
        }

    @staticmethod
    def _prompt_from_response(parsed: dict[str, Any], beat_id: str) -> str:
        if "prompt" in parsed:
            returned_id = str(parsed.get("beat_id") or beat_id)
            return str(parsed.get("prompt") or "").strip() if returned_id == beat_id else ""
        items = parsed.get("prompts")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and str(item.get("beat_id")) == beat_id:
                    return str(item.get("prompt") or "").strip()
        return ""

    @staticmethod
    def _required_contract(shot: dict[str, Any], speaker_map: dict[str, str]) -> str:
        character_references = shot.get("character_references") or [{}]
        definitions = [
            f"<Subject {index}> is the exact character appearance anchored by <Picture {index}>."
            for index in range(1, len(character_references) + 1)
        ]
        scene_index = len(character_references) + 1
        definitions.append(
            f"<Subject {scene_index}> is the exact scene environment anchored by <Picture {scene_index}>."
        )
        speech_lines: list[str] = []
        dialogue = str(shot.get("dialogue") or "").strip()
        speaker = str(shot.get("speaker") or "").strip()
        if dialogue:
            speech_lines.append(
                f"({speaker_map.get(speaker)}) {speaker} says <d>[Chinese] {dialogue}</d>. "
                "The shot holds long enough for the complete unhurried speech and a natural pause."
            )
        narration = str(shot.get("narration") or "").strip()
        if narration:
            speech_lines.append(
                f"In an off-screen voiceover: <d>[Chinese] {narration}</d>. "
                "All visible characters keep their lips closed."
            )
        return "\n".join([
            "subject_definitions:",
            *definitions,
            "summary:",
            "[reference generation + audio reference]",
            "retention_analysis:",
            "fully_preserved",
            "detailed_description:",
            "[Shot 1]",
            *speech_lines,
            "overall_soundscape:",
            "non_diegetic_music:",
        ])

    @classmethod
    def _normalize_prompt(
        cls,
        shot: dict[str, Any],
        prompt: str,
        speaker_map: dict[str, str],
    ) -> str:
        text = str(prompt or "").strip()
        matches = [re.search(rf"(?i){re.escape(section)}:\s*", text) for section in H3_SECTIONS]
        if all(matches) and [match.start() for match in matches] == sorted(match.start() for match in matches):
            rebuilt: list[str] = []
            for index, (section, match) in enumerate(zip(H3_SECTIONS, matches)):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                rebuilt.extend((f"{section}:", text[match.end():end].strip()))
            text = "\n".join(rebuilt)
        else:
            for section in H3_SECTIONS:
                text = re.sub(rf"(?m)(?<![A-Za-z_]){re.escape(section)}:\s*", f"{section}:\n", text)

        definitions = cls._required_contract(shot, speaker_map).split("summary:", 1)[0].strip()
        subject_end = text.find("\nsummary:")
        if subject_end >= 0:
            existing_subject = text[:subject_end]
            for line in definitions.splitlines()[1:]:
                if line not in existing_subject:
                    existing_subject += "\n" + line
            text = existing_subject + text[subject_end:]

        detail_start = text.find("detailed_description:\n")
        sound_start = text.find("\noverall_soundscape:", detail_start)
        if detail_start >= 0 and sound_start >= 0:
            detail = text[detail_start:sound_start]
            mandatory_lines = cls._required_contract(shot, speaker_map).split("detailed_description:\n", 1)[1]
            mandatory_lines = mandatory_lines.split("\noverall_soundscape:", 1)[0].splitlines()
            for line in mandatory_lines:
                if line and line not in detail:
                    detail += "\n" + line
            text = text[:detail_start] + detail + text[sound_start:]
        return text.strip()

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        text = str(content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            value = json.loads(text)
        except json.JSONDecodeError as err:
            raise ValueError(f"大模型未返回有效 JSON: {err}") from err
        if not isinstance(value, dict):
            raise ValueError("大模型提示词响应必须是 JSON 对象")
        return value

    @classmethod
    def validate_prompts(
        cls,
        shots: list[dict[str, Any]],
        prompts: list[str],
        speaker_map: dict[str, str] | None = None,
    ) -> list[str]:
        errors: list[str] = []
        if len(prompts) != len(shots):
            return [f"提示词数量应为 {len(shots)}，实际为 {len(prompts)}"]
        speaker_map = speaker_map or cls._speaker_map(shots)
        for index, (shot, prompt) in enumerate(zip(shots, prompts), start=1):
            label = f"Beat {shot.get('sequence', index)}"
            if not prompt:
                errors.append(f"{label} 提示词为空")
                continue
            positions = []
            for name in H3_SECTIONS:
                match = re.search(rf"(?m)^{re.escape(name)}:\s*$", prompt)
                positions.append(match.start() if match else -1)
            if any(pos < 0 for pos in positions) or positions != sorted(positions):
                errors.append(f"{label} 六段标题缺失或顺序错误")
            character_references = shot.get("character_references") or [{}]
            picture_count = len(character_references) + 1
            required_tokens = ["[Shot 1]"]
            for picture_index in range(1, picture_count + 1):
                required_tokens.extend((f"<Picture {picture_index}>", f"<Subject {picture_index}>"))
            for token in required_tokens:
                if token not in prompt:
                    errors.append(f"{label} 缺少 {token}")
            dialogue = str(shot.get("dialogue") or "").strip()
            narration = str(shot.get("narration") or "").strip()
            for kind, source_text in (("对白", dialogue), ("旁白", narration)):
                if source_text and source_text not in prompt:
                    errors.append(f"{label} 未逐字保留{kind}")
            speaker = str(shot.get("speaker") or "").strip()
            if dialogue and speaker and f"({speaker_map.get(speaker)})" not in prompt:
                errors.append(f"{label} 缺少稳定说话人 ID")
            if dialogue and ("<d>[Chinese]" not in prompt or "hold" not in prompt.lower()):
                errors.append(f"{label} 缺少中文对白标签或完整说完要求")
            lower = prompt.lower()
            if len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", prompt)) < 280:
                errors.append(f"{label} 英文描述过短，未达到丰富提示词要求")
            required_terms = {
                "camera": r"\bcamera\b",
                "lighting": r"\b(?:lighting|light|lit|illumination|illuminated)\b",
                "sound": r"\b(?:sound|audio|ambience|ambient)\b",
            }
            for required, pattern in required_terms.items():
                if not re.search(pattern, lower):
                    errors.append(f"{label} 缺少 {required} 描述")
        return errors

    @staticmethod
    def _system_prompt() -> str:
        return """You are a MiniMax H3 Ref2VA prompt writer. Follow this contract exactly.

Each prompt has exactly six sections in this order:
subject_definitions:
summary:
retention_analysis:
detailed_description:
overall_soundscape:
non_diegetic_music:

Write the six sections in English. Preserve Chinese dialogue, narration, lyrics, and visible text in their original language. Every input beat contains a reference_map that is the only authority for reference meanings. Character pictures appear first in the supplied order and the final picture always supplies the environment, props, lighting, and spatial layout. Define one matching <Subject N> for every <Picture N>, preserve every referenced character's distinct identity and selected costume, and never swap, merge, omit, or invent reference labels.

The summary begins with [reference generation + audio reference]. retention_analysis uses fully_preserved. detailed_description must be concrete and rich: composition, subject positions and referenced appearance, environment, lighting, props, chronological actions and state changes, camera type/amplitude/speed, synchronized physical sounds, ambience, lip closure, and an explicit final held reaction. Describe one [Shot 1] lasting eight seconds; do not add internal cuts or timestamps. Begin speech early enough to finish naturally. Preserve every supplied spoken character exactly inside <d>[Chinese] ...</d>, use the supplied global (Sx), and state that the shot holds long enough for complete unhurried speech and a natural pause. Off-screen narration must say 'in an off-screen voiceover' and all visible characters keep their lips closed. Do not invent dialogue or narration.

overall_soundscape summarizes ambience and synchronized physical sounds. non_diegetic_music states instruments, tempo, rhythm, and dynamics, or N/A. Do not use abstract plot summaries. Keep reference meanings consistent. Aim for detailed generation-quality prose while ensuring the described action fits eight seconds."""
