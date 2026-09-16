from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from ..provider_bridge import credential_manager, llm_row
from ...llm_minimax_skills import build_workshop_h3_timing_rules


H3_SECTIONS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)

_SCRIPT_TURN_RE = re.compile(
    r"([^：:“”\"'\s]{1,20})[：:]\s*[“\"「]([^”\"」]+)[”\"」]"
)
_QUOTE_PAIRS = (("“", "”"), ("‘", "’"), ('"', '"'), ("'", "'"), ("「", "」"), ("『", "』"))
_INNER_MARK_RE = re.compile(
    r"(内心|心声|旁白|画外音|内心独白|off[\s-]?screen|voice[\s-]?over|\bVO\b)",
    re.I,
)
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_LIPSYNC_ZH_RE = re.compile(r"本镜对白必须口型同步：.*?(?=收束：|本集情境：|$)", re.S)
_LIPSYNC_EN_RE = re.compile(
    r"Lip-sync the exact Chinese line\(s\):.*?(?:Do not translate the line onto the picture\.)?",
    re.S,
)
_LIP_SYNC_HINT_RE = re.compile(r"(lip[\s-]?sync|says|口型同步|开口)", re.I)
_CLOSED_MOUTH_HINT_RE = re.compile(
    r"(off[\s-]?screen|voice[\s-]?over|inner voice|嘴唇闭合|闭嘴|closed lips|mouths? stay(?:s)? closed)",
    re.I,
)
_D_TAG_SPLIT_RE = re.compile(r"(<d>.*?</d>)", re.S)
_D_TAG_BODY_RE = re.compile(r"<d>(?:\[[^\]]+\]\s*)?(.*?)</d>\s*$", re.S)
H3_SPEECH_UNIQUENESS_RULES = (
    "Spoken character lines appear exactly once, inside <d>[Chinese] ...</d>, with lip-sync. "
    "Inner voice / narration / 内心 / 旁白 appear exactly once as an off-screen voiceover; "
    "every visible mouth stays closed. Never lip-sync inner voice. "
    "Never copy the same Chinese sentence twice. Do not paste script quotes from the action "
    "or visual_prompt fields into the picture body once they already appear in <d>. "
    "Speaker names and 内心/旁白 labels are metadata, never spoken inside <d>."
)


class H3PromptBuilder:
    """Generate and validate MiniMax H3 Ref2VA prompts for episode beats."""

    @staticmethod
    def _runtime_config() -> tuple[str, str, str]:
        row = llm_row()
        if not row.get("enabled"):
            raise ValueError("大模型供应商未启用，请先在管理后台启用大模型服务。")
        base_url = str(row.get("base_url") or "").strip().rstrip("/")
        model = str(row.get("model") or "").strip()
        encrypted_key = row.get("api_key_encrypted")
        api_key = credential_manager().decrypt(encrypted_key) if encrypted_key else None
        hostname = (urlparse(base_url).hostname or "").lower()
        if not api_key and hostname in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
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
            turns = H3PromptBuilder._dialogue_turns(shot)
            speakers = [str(turn.get("speaker") or "").strip() for turn in turns]
            if not speakers:
                speakers = [str(shot.get("speaker") or "").strip()]
            for speaker in speakers:
                if speaker and speaker not in mapping:
                    mapping[speaker] = f"S{len(mapping) + 1}"
        return mapping

    @staticmethod
    def _known_speaker_names(shot: dict[str, Any]) -> list[str]:
        names: list[str] = []
        for item in shot.get("character_references") or []:
            if isinstance(item, dict):
                name = str(item.get("character_name") or "").strip()
                if name and name not in names:
                    names.append(name)
        for item in shot.get("characters") or []:
            name = str(item or "").strip()
            if name and name not in names:
                names.append(name)
        speaker = str(shot.get("speaker") or "").strip()
        if speaker and speaker not in names:
            names.append(speaker)
        return names

    @staticmethod
    def _strip_wrapping_quotes(text: str) -> str:
        value = str(text or "").strip()
        while len(value) >= 2 and any(value.startswith(left) and value.endswith(right) for left, right in _QUOTE_PAIRS):
            value = value[1:-1].strip()
        return value

    @classmethod
    def _clean_dialogue(cls, text: str, speaker: str = "", extra_names: list[str] | None = None) -> str:
        value = str(text or "").strip()
        names = [str(item).strip() for item in [speaker, *(extra_names or [])] if str(item).strip()]
        for name in sorted(set(names), key=len, reverse=True):
            value = re.sub(
                rf"^[\s\"'“‘]*{re.escape(name)}\s*(?:（[^）]*）|\([^)]*\))?\s*[：:]\s*",
                "",
                value,
            ).strip()
        value = cls._strip_wrapping_quotes(value)
        return value

    @classmethod
    def _parse_script_turns(cls, dialogue: str, extra_names: list[str] | None = None) -> list[dict[str, str]]:
        turns: list[dict[str, str]] = []
        for speaker, spoken in _SCRIPT_TURN_RE.findall(str(dialogue or "")):
            name = str(speaker or "").strip()
            text = cls._clean_dialogue(spoken, name, extra_names)
            if text:
                turns.append({"speaker": name, "text": text})
        return turns

    @staticmethod
    def _is_inner_speaker(speaker: str, delivery: str = "") -> bool:
        return bool(_INNER_MARK_RE.search(f"{speaker} {delivery}"))

    @staticmethod
    def _base_speaker_name(speaker: str) -> str:
        name = str(speaker or "").strip()
        name = re.sub(
            r"[（(][^）)]*(内心|心声|旁白|画外音|内心独白)[^）)]*[）)]",
            "",
            name,
        ).strip()
        name = re.sub(r"(内心|心声|旁白|画外音|内心独白)$", "", name).strip()
        return name or str(speaker or "").strip()

    @classmethod
    def _raw_script_turns(cls, shot: dict[str, Any]) -> list[dict[str, Any]]:
        extra_names = cls._known_speaker_names(shot)
        stored = shot.get("dialogue_turns")
        if isinstance(stored, list) and stored:
            result: list[dict[str, Any]] = []
            for turn in stored:
                if not isinstance(turn, dict):
                    continue
                speaker = str(turn.get("speaker") or "").strip()
                cleaned = cls._clean_dialogue(turn.get("text"), speaker, extra_names)
                if cleaned:
                    result.append({**turn, "speaker": speaker, "text": cleaned})
            if result:
                return result
        dialogue = str(shot.get("dialogue") or "").strip()
        parsed = cls._parse_script_turns(dialogue, extra_names)
        if parsed:
            return parsed
        speaker = str(shot.get("speaker") or "").strip()
        if dialogue:
            cleaned = cls._clean_dialogue(dialogue, speaker, extra_names)
            if cleaned:
                return [{"speaker": speaker, "text": cleaned}]
        return []

    @classmethod
    def split_spoken_and_inner(cls, shot: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        spoken: list[dict[str, Any]] = []
        inner: list[dict[str, Any]] = []
        for turn in cls._raw_script_turns(shot):
            speaker = str(turn.get("speaker") or "").strip()
            delivery = str(turn.get("delivery") or turn.get("mode") or "").strip()
            if cls._is_inner_speaker(speaker, delivery):
                inner.append({**turn, "speaker": cls._base_speaker_name(speaker)})
            else:
                spoken.append(turn)
        return spoken, inner

    @classmethod
    def _dialogue_turns(cls, shot: dict[str, Any]) -> list[dict[str, Any]]:
        spoken, _inner = cls.split_spoken_and_inner(shot)
        return spoken

    @classmethod
    def _inner_turns(cls, shot: dict[str, Any]) -> list[dict[str, Any]]:
        _spoken, inner = cls.split_spoken_and_inner(shot)
        narration = str(shot.get("narration") or "").strip()
        if narration:
            existing = {str(item.get("text") or "").strip() for item in inner}
            if narration not in existing and not any(
                narration in text or text in narration for text in existing if text
            ):
                inner.append({"speaker": "", "text": narration, "delivery": "narration"})
        return inner

    @staticmethod
    def _line_variants(line: str) -> list[str]:
        base = str(line or "").strip()
        if not base:
            return []
        stripped = base.rstrip("。.!！？?，,、 ")
        variants = {base, stripped, base.replace("，", "、"), base.replace("、", "，")}
        quoted: set[str] = set()
        for item in list(variants):
            quoted.add(f"“{item}”")
            quoted.add(f'"{item}"')
        return [item for item in (*variants, *quoted) if item]

    @classmethod
    def strip_script_echo(cls, text: str, extra_lines: list[str] | None = None) -> str:
        value = str(text or "")
        value = _LIPSYNC_ZH_RE.sub("", value)
        value = _LIPSYNC_EN_RE.sub("", value)
        value = re.sub(r"内心(?:独白|说|继续)[^。；;]*", "", value)
        value = re.sub(r"inner voice (?:heavy|continues)[^.；;]*", "", value, flags=re.I)
        for line in sorted({item for item in (extra_lines or []) if item}, key=len, reverse=True):
            if len(_HAN_RE.findall(line)) < 4:
                continue
            for variant in cls._line_variants(line):
                value = value.replace(variant, "")
        return re.sub(r"[ \t]{2,}", " ", value).strip()

    @staticmethod
    def _han_only(text: str) -> str:
        return "".join(_HAN_RE.findall(text or ""))

    @classmethod
    def prompt_contains_line(cls, prompt: str, line: str) -> bool:
        needle = cls._han_only(line)
        if not needle:
            value = str(line or "").strip()
            return bool(value) and value in str(prompt or "")
        return needle in cls._han_only(prompt)

    @classmethod
    def count_han_line(cls, prompt: str, line: str) -> int:
        needle = cls._han_only(line)
        if not needle:
            return 0
        haystack = cls._han_only(prompt)
        count = 0
        start = 0
        step = max(len(needle), 1)
        while True:
            idx = haystack.find(needle, start)
            if idx < 0:
                break
            count += 1
            start = idx + step
        return count

    @classmethod
    def _han_in_d_tag(cls, text: str, line: str) -> bool:
        needle = cls._han_only(line)
        if not needle:
            return False
        for inner in re.findall(r"<d>(?:\[[^\]]+\]\s*)?(.*?)</d>", text, flags=re.S):
            body = cls._han_only(inner)
            if needle == body or needle in body:
                return True
        return False

    @classmethod
    def _flexible_line_re(cls, line: str) -> re.Pattern[str]:
        parts = [re.escape(part) for part in re.split(r"[，,、。.!！？?\s]+", str(line or "").strip()) if part]
        if not parts:
            return re.compile(re.escape(str(line or "")))
        return re.compile(r"[，,、。.!！？?\s“”\"']*".join(parts))

    @classmethod
    def count_verbatim_line(cls, prompt: str, line: str) -> int:
        return cls.count_han_line(prompt, line)

    @classmethod
    def speech_uniqueness_errors(cls, prompt: str, shot: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        spoken = cls._dialogue_turns(shot)
        inner = cls._inner_turns(shot)
        for turn in spoken:
            line = str(turn.get("text") or "").strip()
            if len(_HAN_RE.findall(line)) < 6:
                continue
            if cls.count_han_line(prompt, line) > 1:
                errors.append(f"spoken line duplicated: {line[:40]}")
        for turn in inner:
            line = str(turn.get("text") or "").strip()
            if not line:
                continue
            if len(_HAN_RE.findall(line)) >= 6 and cls.count_han_line(prompt, line) > 1:
                errors.append(f"inner/narration line duplicated: {line[:40]}")
            locations: list[tuple[int, int]] = []
            for match in re.finditer(r"<d>(?:\[[^\]]+\]\s*)?(.*?)</d>", prompt, flags=re.S):
                if cls._han_only(line) and cls._han_only(line) in cls._han_only(match.group(1)):
                    locations.append((match.start(), match.end()))
            if not locations:
                locations = [(match.start(), match.end()) for match in cls._flexible_line_re(line).finditer(prompt)]
            if not locations:
                continue
            closed = False
            lip_synced = False
            for start, end in locations:
                prefix = prompt[max(0, start - 100):start]
                around = prompt[max(0, start - 160):end + 40]
                if _CLOSED_MOUTH_HINT_RE.search(around):
                    closed = True
                if re.search(r"(lip[\s-]?sync|says|口型同步)\s*$", prefix.strip(), re.I):
                    if not _CLOSED_MOUTH_HINT_RE.search(prefix):
                        lip_synced = True
            if lip_synced:
                errors.append(f"inner voice must not be lip-synced: {line[:40]}")
            elif not closed:
                errors.append(f"inner voice missing closed-mouth/off-screen delivery: {line[:40]}")
        return errors

    @classmethod
    def _should_append_contract_line(cls, detail: str, line: str) -> bool:
        text = str(line or "").strip()
        if not text or text in detail:
            return False
        tagged = re.findall(r"<d>\[Chinese\]\s*(.*?)</d>", text)
        if tagged and all(cls._han_in_d_tag(detail, item) for item in tagged):
            return False
        return True

    @staticmethod
    def canonicalize_reference_tags(prompt: str) -> str:
        text = str(prompt or "")
        text = re.sub(r"<picture\s*(\d+)\s*>", r"<Picture \1>", text, flags=re.I)
        text = re.sub(r"<subject\s*(\d+)\s*>", r"<Subject \1>", text, flags=re.I)
        return text

    @staticmethod
    def _required_picture_indexes(shot: dict[str, Any]) -> list[int]:
        indexes: list[int] = []
        for item in shot.get("ref_images") or []:
            if not isinstance(item, dict) or item.get("index") in (None, ""):
                continue
            try:
                indexes.append(int(item["index"]))
            except (TypeError, ValueError):
                continue
        if indexes:
            return sorted(set(indexes))
        n_chars = max(len(shot.get("character_references") or [{}]), 1)
        return list(range(1, n_chars + 2))

    @classmethod
    def ensure_reference_tags(cls, prompt: str, shot: dict[str, Any]) -> str:
        text = cls.canonicalize_reference_tags(prompt)
        missing: list[str] = []
        for index in cls._required_picture_indexes(shot):
            if f"<Picture {index}>" not in text or f"<Subject {index}>" not in text:
                missing.append(
                    f"<Subject {index}> is the exact appearance anchored by <Picture {index}>."
                )
        if not missing:
            return text
        marker = "\nsummary:"
        idx = text.find(marker)
        block = "\n".join(missing)
        if idx >= 0:
            return text[:idx].rstrip() + "\n" + block + text[idx:]
        return text.rstrip() + "\n" + block

    @classmethod
    def collapse_repeated_speech(cls, prompt: str, shot: dict[str, Any]) -> str:
        text = str(prompt or "")
        jobs = [
            (str(turn.get("text") or "").strip(), False)
            for turn in cls._dialogue_turns(shot)
        ]
        jobs.extend(
            (str(turn.get("text") or "").strip(), True)
            for turn in cls._inner_turns(shot)
        )
        jobs.sort(key=lambda item: len(cls._han_only(item[0])), reverse=True)
        for line, _inner in jobs:
            needle = cls._han_only(line)
            if len(needle) < 4:
                continue
            rebuilt: list[str] = []
            kept = False
            for part in _D_TAG_SPLIT_RE.split(text):
                d_match = _D_TAG_BODY_RE.match(part)
                if d_match:
                    body_han = cls._han_only(d_match.group(1))
                    if needle == body_han or (len(needle) >= 6 and needle in body_han):
                        if not kept:
                            rebuilt.append(f"<d>[Chinese] {line}</d>")
                            kept = True
                        continue
                    rebuilt.append(part)
                    continue
                if needle in cls._han_only(part):
                    stripped = part
                    for variant in cls._line_variants(line):
                        stripped = stripped.replace(variant, "")
                    stripped = cls._flexible_line_re(line).sub("", stripped)
                    rebuilt.append(stripped)
                else:
                    rebuilt.append(part)
            text = "".join(rebuilt)
        return text

    @classmethod
    def repair_inner_delivery(cls, prompt: str, shot: dict[str, Any]) -> str:
        text = str(prompt or "")
        offscreen = "In an off-screen inner voiceover, all visible characters keep their lips closed: "
        for turn in cls._inner_turns(shot):
            line = str(turn.get("text") or "").strip()
            if not line:
                continue
            tag = f"<d>[Chinese] {line}</d>"
            idx = text.find(tag)
            if idx < 0:
                for match in re.finditer(r"<d>(?:\[[^\]]+\]\s*)?(.*?)</d>", text, flags=re.S):
                    if cls._han_only(line) and cls._han_only(line) in cls._han_only(match.group(1)):
                        idx = match.start()
                        tag = match.group(0)
                        break
            if idx < 0:
                continue
            prefix = text[max(0, idx - 120):idx]
            around = text[max(0, idx - 160):idx + len(tag) + 40]
            says_match = re.search(
                r"(?:\(\w+\)\s+)?(?:<Subject\s+\d+>\s+)?[^\n<>]{0,48}?\bsays\s+$",
                prefix,
                flags=re.I,
            )
            if says_match and not _CLOSED_MOUTH_HINT_RE.search(prefix):
                start = idx - len(says_match.group(0))
                text = text[:start] + offscreen + text[idx:]
                continue
            if not _CLOSED_MOUTH_HINT_RE.search(around):
                text = text[:idx] + offscreen + text[idx:]
        return text

    @classmethod
    def shot_from_beat_info(
        cls,
        beat_info: dict[str, Any] | None,
        *,
        beat_id: str = "beat",
        sequence: int | None = None,
    ) -> dict[str, Any]:
        info = beat_info if isinstance(beat_info, dict) else {}
        characters = [item for item in (info.get("characters") or []) if isinstance(item, dict)]
        char_refs = [
            {
                "character_id": str(item.get("id") or ""),
                "character_name": str(item.get("name") or ""),
                "description": str(item.get("look_desc") or item.get("desc") or ""),
            }
            for item in characters
        ]
        if not char_refs:
            for item in info.get("ref_images") or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("category") or "character") != "character":
                    continue
                char_refs.append({
                    "character_name": str(item.get("name") or ""),
                    "description": "",
                })
        names: list[str] = [str(item.get("name") or "") for item in characters]
        if not names:
            raw_chars = info.get("characters") or []
            names = [str(item) for item in raw_chars if isinstance(item, str) and str(item).strip()]
        return {
            "beat_id": str(info.get("beat_id") or beat_id),
            "sequence": int(sequence or info.get("sequence") or 1),
            "speaker": str(info.get("speaker") or ""),
            "dialogue": str(info.get("dialogue") or ""),
            "dialogue_turns": info.get("dialogue_turns") if isinstance(info.get("dialogue_turns"), list) else [],
            "narration": str(info.get("narration") or ""),
            "visible_text": str(info.get("visible_text") or ""),
            "characters": names,
            "character_references": char_refs,
            "scene": str(info.get("scene_name") or info.get("scene") or ""),
            "scene_description": str(info.get("scene_desc") or info.get("scene_description") or ""),
            "ref_images": info.get("ref_images") if isinstance(info.get("ref_images"), list) else [],
            "props": info.get("props") if isinstance(info.get("props"), list) else [],
        }

    @classmethod
    def prepare_generated_prompt(
        cls,
        prompt: str,
        shot: dict[str, Any],
        speaker_map: dict[str, str] | None = None,
    ) -> str:
        speaker_map = speaker_map or cls._speaker_map([shot])
        text = cls.canonicalize_reference_tags(prompt)
        text = cls._normalize_prompt(shot, text, speaker_map)
        text = cls.ensure_reference_tags(text, shot)
        text = cls.collapse_repeated_speech(text, shot)
        text = cls.repair_inner_delivery(text, shot)
        return text.strip()

    @classmethod
    def _clean_prompt_dialogue(cls, prompt: str, shot: dict[str, Any]) -> str:
        if not prompt:
            return prompt
        extra_names = cls._known_speaker_names(shot)
        extra_names.extend(str(turn.get("speaker") or "").strip() for turn in cls._dialogue_turns(shot))

        def clean_tag(match: re.Match[str]) -> str:
            language = match.group(1)
            spoken = cls._clean_dialogue(match.group(2), extra_names=extra_names)
            return f"<d>{language}{spoken}</d>"

        return re.sub(r"<d>(\[[^\]]+\]\s*)(.*?)</d>", clean_tag, prompt, flags=re.DOTALL)

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
            duration_seconds = int(source.get("duration_seconds") or 8)
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
                                {"role": "system", "content": cls._system_prompt(duration_seconds)},
                                {"role": "user", "content": (
                                    f"Create exactly one independent {duration_seconds}-second Ref2VA prompt for this beat. "
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
                        prompt = cls.prepare_generated_prompt(prompt, shot, speaker_map)
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

    @classmethod
    def _shot_source(cls, shot: dict[str, Any], speaker_map: dict[str, str]) -> dict[str, Any]:
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
            "dialogue": "" if shot.get("dialogue_turns") else (shot.get("dialogue") or ""),
            "dialogue_turns": [
                {
                    **turn,
                    "speaker_id": speaker_map.get(str(turn.get("speaker") or "").strip()),
                }
                for turn in cls._dialogue_turns(shot)
            ],
            "visible_text": shot.get("visible_text") or "",
            "narration": shot.get("narration") or "",
            "speaker": shot.get("speaker") or "",
            "speaker_id": speaker_map.get(str(shot.get("speaker") or "").strip()),
            "characters": shot.get("characters") or [],
            "props": shot.get("props") or [],
            "scene": shot.get("scene") or "",
            "character_reference_description": shot.get("character_description") or "",
            "scene_reference_description": shot.get("scene_description") or "",
            "reference_map": reference_map,
            "duration_seconds": int(
                shot.get("duration_seconds")
                or shot.get("duration_sec")
                or shot.get("video_duration")
                or 8
            ),
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
        reference_index = {
            str(reference.get("character_id") or ""): index
            for index, reference in enumerate(character_references, start=1)
            if isinstance(reference, dict)
        }
        name_index = {
            str(reference.get("character_name") or "").strip(): index
            for index, reference in enumerate(character_references, start=1)
            if isinstance(reference, dict) and str(reference.get("character_name") or "").strip()
        }
        for turn in H3PromptBuilder._dialogue_turns(shot):
            speaker = str(turn.get("speaker") or "").strip()
            dialogue = str(turn.get("text") or "").strip()
            subject_index = reference_index.get(str(turn.get("character_id") or "")) or name_index.get(speaker)
            subject = f"<Subject {subject_index}> " if subject_index else ""
            speech_lines.append(
                f"({speaker_map.get(speaker)}) {subject}{speaker} says <d>[Chinese] {dialogue}</d>. "
                "The shot holds long enough for the complete unhurried speech and a natural pause."
            )
        visible_text = str(shot.get("visible_text") or "").strip()
        if visible_text:
            speech_lines.append(
                f'The only required visible Chinese text is exactly: "{visible_text}". '
                "It is on-screen text and is never spoken aloud."
            )
        for turn in H3PromptBuilder._inner_turns(shot):
            inner_text = str(turn.get("text") or "").strip()
            if not inner_text:
                continue
            speech_lines.append(
                "In an off-screen inner voiceover, all visible characters keep their lips closed: "
                f"<d>[Chinese] {inner_text}</d>."
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
        text = cls._clean_prompt_dialogue(cls.canonicalize_reference_tags(str(prompt or "").strip()), shot)
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
                if cls._should_append_contract_line(detail, line):
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
                if token.startswith("<"):
                    name, _, rest = token[1:].partition(" ")
                    idx = rest[:-1] if rest.endswith(">") else rest
                    if not re.search(rf"<{re.escape(name)}\s*{re.escape(idx)}\s*>", prompt, flags=re.I):
                        errors.append(f"{label} 缺少 {token}")
                elif token not in prompt:
                    errors.append(f"{label} 缺少 {token}")
            turns = cls._dialogue_turns(shot)
            inner = cls._inner_turns(shot)
            for turn in turns:
                source_text = str(turn.get("text") or "").strip()
                if source_text and not cls.prompt_contains_line(prompt, source_text):
                    errors.append(f"{label} 未逐字保留「{turn.get('speaker') or '对白'}」台词")
                speaker = str(turn.get("speaker") or "").strip()
                if speaker and f"({speaker_map.get(speaker)})" not in prompt:
                    errors.append(f"{label} 缺少「{speaker}」稳定说话人 ID")
            for turn in inner:
                inner_text = str(turn.get("text") or "").strip()
                if inner_text and not cls.prompt_contains_line(prompt, inner_text):
                    errors.append(f"{label} 未逐字保留旁白")
            if turns and ("<d>[Chinese]" not in prompt or "hold" not in prompt.lower()):
                errors.append(f"{label} 缺少中文对白标签或完整说完要求")
            expected_dialogue = {
                str(turn.get("text") or "").strip()
                for turn in [*turns, *inner]
                if str(turn.get("text") or "").strip()
            }
            expected_han = {cls._han_only(item) for item in expected_dialogue if cls._han_only(item)}
            actual_dialogue = {
                cls._clean_dialogue(value, extra_names=cls._known_speaker_names(shot)).strip()
                for value in re.findall(r"<d>\[Chinese\]\s*(.*?)</d>", prompt, flags=re.S)
                if str(value or "").strip()
            }
            unexpected = []
            if expected_dialogue:
                for item in sorted(actual_dialogue):
                    if not item:
                        continue
                    han = cls._han_only(item)
                    if han and han in expected_han:
                        continue
                    if item in expected_dialogue:
                        continue
                    unexpected.append(item)
            if unexpected:
                errors.append(f"{label} 含有原文不存在的新增对白：{' / '.join(unexpected)}")
            visible_text = str(shot.get("visible_text") or "").strip()
            if visible_text and visible_text not in prompt:
                errors.append(f"{label} 未逐字保留画面文字")
            for issue in cls.speech_uniqueness_errors(prompt, shot):
                errors.append(f"{label} {issue}")
            for issue in cls.thickness_errors(prompt):
                errors.append(f"{label} {issue}")
        return errors

    @staticmethod
    def thickness_errors(prompt: str) -> list[str]:
        text = str(prompt or "")
        errors: list[str] = []
        if len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", text)) < 280:
            errors.append("英文描述过短，未达到丰富提示词要求")
        lower = text.lower()
        required_terms = {
            "camera": r"\bcamera\b",
            "lighting": r"\b(?:lighting|light|lit|illumination|illuminated)\b",
            "sound": r"\b(?:sound|audio|ambience|ambient)\b",
        }
        for required, pattern in required_terms.items():
            if not re.search(pattern, lower):
                errors.append(f"缺少 {required} 描述")
        return errors

    @staticmethod
    def _system_prompt(duration_seconds: int = 8) -> str:
        timing = build_workshop_h3_timing_rules(duration_seconds)
        return f"""You are a MiniMax H3 Ref2VA prompt writer. Follow this contract exactly.

{timing}

{H3_SPEECH_UNIQUENESS_RULES}

Each prompt has exactly six sections in this order:
subject_definitions:
summary:
retention_analysis:
detailed_description:
overall_soundscape:
non_diegetic_music:

Write the six sections in English. Preserve Chinese dialogue, narration, lyrics, and visible text in their original language. Every input beat contains a reference_map that is the only authority for reference meanings. Character pictures appear first in the supplied order and the final picture always supplies the environment, props, lighting, and spatial layout. Define one matching <Subject N> for every <Picture N>, preserve every referenced character's distinct identity and selected costume, and never swap, merge, omit, or invent reference labels.

The summary begins with [reference generation + audio reference]. retention_analysis uses fully_preserved. detailed_description must be concrete and rich: composition, subject positions and referenced appearance, environment, lighting, props, chronological actions and state changes, camera type/amplitude/speed, synchronized physical sounds, ambience, lip closure, and an explicit final held reaction. Describe one [Shot 1] lasting {duration_seconds} seconds; do not add internal cuts or timestamps. Begin speech early enough to finish naturally. Preserve every supplied spoken character line exactly once inside <d>[Chinese] ...</d>, use the supplied global (Sx), and state that the shot holds long enough for complete unhurried speech and a natural pause. A speaker name is metadata and must never appear inside <d>. Inner voice and off-screen narration must say 'in an off-screen voiceover' and all visible characters keep their lips closed; they are never lip-synced. Do not invent dialogue or narration.

overall_soundscape summarizes ambience and synchronized physical sounds. non_diegetic_music states instruments, tempo, rhythm, and dynamics, or N/A. Do not use abstract plot summaries. Keep reference meanings consistent. Aim for detailed generation-quality prose while ensuring the described action fits {duration_seconds} seconds."""
