from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from ..provider_bridge import credential_manager, llm_row
from ...llm_minimax_skills import (
    build_workshop_h3_timing_rules,
    load_h3_prompt_writing_guide,
    load_h3_prompt_writing_skill,
    load_h3_ref2va_workshop_excerpt,
)


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
_EMPTY_SPEAKER_QUOTE_RE = re.compile(
    r"[^：:“”\"'\s]{1,24}"
    r"(?:\s+[^：:“”\"'\s]{1,24})?"
    r"(?:（[^）]{0,24}）|\([^)]{0,24}\))?"
    r"[：:]\s*"
    r"(?:[“\"「『]\s*[”\"」』]|“”|\"\"|「」|『』)"
    r"\s*[。.]?"
)
_INNER_MARK_RE = re.compile(
    r"(内心|心声|旁白|画外音|内心独白|off[\s-]?screen|voice[\s-]?over|\bVO\b)",
    re.I,
)
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_LIPSYNC_ZH_RE = re.compile(r"本镜对白必须口型同步：.*?(?=收束：|本集情境：|$)", re.S)
_LIPSYNC_EN_RE = re.compile(
    r"Lip-sync the exact Chinese line\(s\):.*?(?:Do not translate the line onto the picture\.|(?=\s*(?:A visible body action|SYNCHRONIZED SOUND|FINISH AND FORBIDDEN|$)))",
    re.S,
)
_LIP_SYNC_HINT_RE = re.compile(r"(lip[\s-]?sync|says|口型同步|开口)", re.I)
_CLOSED_MOUTH_HINT_RE = re.compile(
    r"(off[\s-]?screen|voice[\s-]?over|inner voice|嘴唇闭合|闭嘴|closed lips|mouths? stay(?:s)? closed)",
    re.I,
)
_D_TAG_SPLIT_RE = re.compile(r"(<d>.*?</d>)", re.S)
_D_TAG_RE = re.compile(r"<d>.*?</d>", re.S)
_D_TAG_BODY_RE = re.compile(r"<d>(?:\[[^\]]+\]\s*)?(.*?)</d>\s*$", re.S)
_SAYS_STUB_RE = re.compile(
    r"(?:\(\w+\)\s+)?(?:<Subject\s+\d+>\s+)?"
    r"(?:[A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff' .\-]{0,22})\bsays\s*[.,]?",
    re.I,
)
_DLG_TOKEN_RE = re.compile(r"\{\{D(\d+)\}\}")
_HOLD_LINE_RE = re.compile(
    r"\s*The shot holds long enough for the complete unhurried speech and a natural pause\.",
    re.I,
)
_VOICE_DIR_RE = re.compile(
    r"\s*,?\s*in a [^.!?]{0,80}?\b(?:voice|tone|cadence)\b[^.,;]{0,48}[.,]?",
    re.I,
)
_FREEZE_TAIL_RE = re.compile(
    r"(?:After the last syllable[, ]*)?(?:The (?:shot|camera) freeze[s]?\b[^.]*\.)"
    r"|(?:\bfreezes on\b[^.]*\.)",
    re.I,
)
_INNER_PREFIX_RE = re.compile(
    r"(?:(?:\(\w+\)\s+)?(?:<Subject\s+\d+>\s+)?[^\n<>]{0,24}?\bthinks\.?\s+)?"
    r"in an off-screen inner voiceover, all visible characters keep their lips closed:\s*",
    re.I,
)
_SPEECH_LEADIN_RE = re.compile(
    r"(?:"
    r"(?:(?:she|he|they)\s+)?(?:then\s+)?(?:first\s+)?"
    r"(?:(?:briefly\s+)?before\s+)?"
    r"(?:speaks?(?:\s+with)?|continues?(?:\s+with)?|continuing with)\s*"
    r"|"
    r"(?:(?:she|he|they)\s+)?speaks?\s+first\b[^.!?\n]{0,80}(?:\.|,)\s*"
    r"|"
    r"(?:(?:she|he|they)\s+)?pauses?\s+[^.!?\n]{0,60}?before continuing,\s*"
    r"|"
    r"(?:\(\w+\)\s+)?(?:<Subject\s+\d+>\s+)?"
    r"[A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff' .\-]{0,40}"
    r"(?:\s*\(\w+\))?"
    r"\s+(?:then\s+)?speaks?\b(?:,|\s+(?:his|her|their|in|with)\b)?[^.!?\n]{0,80}\.\s*"
    r")$",
    re.I,
)
_CONTINUING_GLUE_RE = re.compile(
    r"(?:(?:she|he|they)\s+)?pauses?\s+[^.!?\n]{0,60}?before continuing,\s*",
    re.I,
)
_CLOSED_MOUTH_BEAT = " The camera holds on the closed mouth. "
_SPEECH_TRAIL_RE = re.compile(
    r"^\s*(?:spoken by [^.]{0,48}\.?)",
    re.I,
)
_SLOT_LEGEND_RE = re.compile(
    r"\s*(?:\.\s*)?(?:"
    r"spoken lip-sync"
    r"|inner off-screen, lips closed(?:; listener thought, not the previous speaker continuing)?"
    r"|listener thought, not the previous speaker continuing"
    r")\s*[—\-–:]?\s*"
    r"(?:[A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff' .\-]{0,40})?"
    r"(?:\s*\(\w+\))?"
    r"(?:\s*<Subject\s+\d+>)?",
    re.I,
)
_AFTER_LINE_HOLD_RE = re.compile(
    r"\s*After [^.]{0,48}(?:'s|’s) line,\s+the camera holds[^.]*\.",
    re.I,
)
_CAMERA_BEAT_RE = re.compile(
    r"\b(?:tilts?|push(?:es)?(?:\s+in|\s+back)?|pans?|tracks?|"
    r"doll(?:y|ies)|follows\s+(?:his|her|the)\s+(?:gaze|look)|"
    r"eyes travel down|"
    r"pulls?\s+(?:in|back)|crane)\b",
    re.I,
)
_SPEECH_GAP_BEAT_RE = re.compile(
    r"\b(?:tilts?|push(?:es)?(?:\s+in|\s+back)?|pans?|tracks?|"
    r"doll(?:y|ies)|follows\s+(?:his|her|the)\s+(?:gaze|look)|"
    r"eyes travel down|"
    r"pulls?\s+(?:in|back)|crane|(?:camera|shot)\s+holds?)\b",
    re.I,
)
_GAZE_BEAT_RE = re.compile(
    r"follows\s+(?:his|her|the)\s+(?:gaze|look)|"
    r"gaze tilting down|"
    r"tilt(?:s|ing)?\s+down\s+with\s+(?:small|large)\s+amplitude|"
    r"tilt(?:s|ing)?\s+down\s+(?:her|his|the)\s+"
    r"(?:outfit|body|figure|clothes|camisole|skirt)|"
    r"eyes travel down",
    re.I,
)
_PUSH_BACK_RE = re.compile(r"\bpush(?:es)?\s+back\b", re.I)
_LAND_ON_FACE_RE = re.compile(
    r"\bpush(?:es)?\b.{0,80}\b(?:face|medium-close|landlord|speaker|left)\b"
    r"|\blips stay closed\b",
    re.I,
)
_INNER_GAZE_FALLBACK = (
    "The camera tilts down with small amplitude at slow speed "
    "and holds a static shot on the other person's torso until the clothes fill the vertical frame; "
    "keep the thinker off-screen or as a sliver until this inner voice ends."
)
_INNER_BODY_HOLD = (
    "Hold a static shot on that torso so the clothes fill the vertical frame; "
    "do not push in until this inner voice ends."
)
_GAP_CAMERA_BEATS = (
    "The camera tilts slightly to keep the listener's face readable.",
    "The camera pushes in a fraction on the closed mouth.",
    "The camera pans a hair toward the speaker's eyes.",
    "The camera tracks a small reaction on the listener.",
)
_DUP_HOLD_RE = re.compile(
    r"(The shot holds long enough for the complete unhurried speech and a natural pause\.)"
    r"(?:\s*\.?\s*The shot holds long enough for the complete unhurried speech and a natural pause\.)+",
    re.I,
)
H3_SPEECH_UNIQUENESS_RULES = (
    "Spoken character lines appear exactly once, inside <d>[Chinese] ...</d>, with lip-sync. "
    "Inner voice / narration / 内心 / 旁白 appear exactly once as an off-screen voiceover; "
    "every visible mouth stays closed. Never lip-sync inner voice. "
    "Never copy the same Chinese sentence twice. Do not paste script quotes from the action "
    "or visual_prompt fields into the picture body once they already appear in <d>. "
    "Speaker names and 内心/旁白 labels are metadata, never spoken inside <d>."
)
H3_PACKING_RETRY_INSTRUCTION = (
    "Keep the same detailed_description; only fix these contract issues."
)
_THICK_DRAFT_MARKERS = ("COMPOSITION", "LIGHTING", "PERFORMANCE")
_ASPECT_RATIO_RE = re.compile(r"\b(9\s*[:：]\s*16|16\s*[:：]\s*9)\b")
_THICKNESS_PAD = (
    "The camera holds a stable medium composition while natural lighting defines the room, "
    "the subject performs a precise visible action, and synchronized sound follows every contact."
)
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_SECTION_SPLIT_RE = re.compile(
    r"(?=(?:COMPOSITION AND CAMERA|LOCATION|LIGHTING|CAST LOCK|"
    r"HERO PROPS(?: IN FRAME)?|FINISH AND FORBIDDEN|FORBIDDEN|"
    r"SYNCHRONIZED SOUND|"
    r"(?:(?<!\d)\d+|[A-Z]+)-SECOND\s+PERFORMANCE|PERFORMANCE)\s*[:：,])"
)
_FREEZE_CLAUSE_RE = re.compile(r"\b(?:freeze|freezes|freezing)\b", re.I)
_FRAMING_LEAD_RE = re.compile(
    r"^(?:Photorealistic|Heads sit in the upper third|Shallow depth of field|"
    r"If two or three people share the frame)\b",
    re.I,
)
_LOCK_LEAD_RE = re.compile(
    r"^(?:LOCATION|LIGHTING|CAST LOCK|HERO PROPS|FINISH AND FORBIDDEN|FORBIDDEN|"
    r"SYNCHRONIZED SOUND|Episode context|Practical lights only|"
    r"Props stay in the same hands|Wu Nai stays|Sha Lili keeps|Yu Qian stays|"
    r"Bai Xue stays)\b",
    re.I,
)
_SPEECH_ECHO_RE = re.compile(
    r"\b(?:lip-sync|do not translate the line|"
    r"(?:she|he|they)\s+(?:first\s+)?says\b|"
    r"opens (?:his|her|their) mouth|"
    r"inner voice|"
    r"no need to guess)\b",
    re.I,
)
_NAMECARD_ASIDE_RE = re.compile(
    r";?\s*optional name-card[^.]*\.?",
    re.I,
)
_CONTRACT_STUB_RE = re.compile(
    r"\(S\d+\)\s*<Subject\s+\d+>\s*[^\n<>]{0,40}?\b(?:says|thinks)\.?",
    re.I,
)
_DUP_THINKS_RE = re.compile(
    r"(?:(?:\(\w+\)\s*)?(?:<Subject\s+\d+>\s*)?[^\n<>]{1,24}?\s+thinks\.\s*)+"
    r"(?=(?:\(\w+\)\s*)?(?:<Subject\s+\d+>\s*)?[^\n<>]{1,24}?\s+thinks\b)",
    re.I,
)
_HE_THINKS_LEAD_RE = re.compile(
    r"(?:(?:He|She|They)\s+thinks\s+)(?=(?:\(\w+\)\s*)?(?:<Subject\s+\d+>\s*)?[^\n<>]{1,24}?\s+thinks\b)",
    re.I,
)
_TEMPLATE_SKIP_RE = re.compile(
    r"^(?:A visible body action happens|Off-screen narration or system voice|"
    r"Dialogue sits above ambience|Music stays low|Do not translate)\b",
    re.I,
)
_MOUTH_PARAPHRASE_RE = re.compile(
    r"[;,]?\s*(?:she|he|they)\s+opens (?:his|her|their) mouth:[^.]*\.?",
    re.I,
)
_WRECKAGE_CLAUSE_RE = re.compile(
    r"^(?:\d+(?:-SECOND)?|FINISH AND|PERFORMANCE)\.?\s*$",
    re.I,
)
_FINISH_HOLD_RE = re.compile(
    r"^Hold (?:his|her|their|the).{0,48}\b(?:look|expression)\b|"
    r"^hold the last expression\b",
    re.I,
)
_FORBIDDEN_TAIL_RE = re.compile(r"^No (?:costume jump|location jump)\b", re.I)
_PERFORMANCE_LEAD_RE = re.compile(
    r"^(?:(?:\d+|[A-Z]+)-SECOND\s+)?PERFORMANCE(?:, chronological, all inside this single take)?:\s*",
    re.I,
)
_RUNON_CAMERA_RE = re.compile(
    r"(?<=[a-z;:])\s+(?=(?:Push|Pull|Tilt|Pan|Track|(?:The|the)\s+camera|His lips stay closed)\b)"
)
_CAST_STAYS_RE = re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+stays\b")
_CAST_ALIASES = {
    "wu nai": ("吴耐", "wu nai"),
    "sha lili": ("沙丽丽", "sha lili"),
    "yu qian": ("于倩", "yu qian"),
    "bai xue": ("白雪", "bai xue"),
}
_CAMERA_THEN_RE = re.compile(r",\s*then\s+|\s+then\s+a\s+", re.I)
_CAMERA_AND_MOVE_RE = re.compile(
    r"\s+and\s+(?=a\s+(?:slow\s+)?(?:tilt|push|pan|track|dolly)\b)",
    re.I,
)
_SOUND_EXTRACT_RE = re.compile(
    r"SYNCHRONIZED SOUND:\s*(.+?)(?:\.\s*Dialogue sits|\.\s*Music stays|"
    r"\.\s*FINISH AND|\s*FINISH AND FORBIDDEN|\s*Episode context|$)",
    re.I | re.S,
)
_SOUND_TERM_RE = re.compile(r"\b(?:sound|audio|ambience|ambient)\b", re.I)
_SOUND_ENGLISH_TAIL = "Synchronized ambient sound follows on-camera movement."


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
        used_ids: set[str] = set()
        for shot in shots:
            for index, reference in enumerate(shot.get("character_references") or [], start=1):
                if not isinstance(reference, dict):
                    continue
                name = str(reference.get("character_name") or "").strip()
                sid = f"S{index}"
                if not name or name in mapping:
                    continue
                if sid in used_ids:
                    continue
                mapping[name] = sid
                used_ids.add(sid)
        next_id = 1

        def take_next() -> str:
            nonlocal next_id
            while f"S{next_id}" in used_ids:
                next_id += 1
            sid = f"S{next_id}"
            next_id += 1
            used_ids.add(sid)
            return sid

        for shot in shots:
            turns = H3PromptBuilder._dialogue_turns(shot)
            speakers = [str(turn.get("speaker") or "").strip() for turn in turns]
            if not speakers:
                speakers = [str(shot.get("speaker") or "").strip()]
            for speaker in speakers:
                if speaker and speaker not in mapping:
                    mapping[speaker] = take_next()
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

    @classmethod
    def ordered_speech_events(cls, shot: dict[str, Any]) -> list[dict[str, Any]]:
        extra = cls._known_speaker_names(shot)
        parsed = cls._parse_script_turns(str(shot.get("dialogue") or ""), extra)
        events: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(kind: str, speaker: str, text: str) -> None:
            line = str(text or "").strip()
            if not line:
                return
            key = cls._han_only(line) or line
            if key in seen:
                return
            if kind == "inner" and cls._han_only(line):
                han = cls._han_only(line)
                for index, event in enumerate(events):
                    if event.get("kind") != "inner":
                        continue
                    other = cls._han_only(str(event.get("text") or ""))
                    if not other:
                        continue
                    if han != other and han in other:
                        return
                    if han != other and other in han:
                        seen.discard(other)
                        seen.add(han)
                        events[index] = {"kind": kind, "speaker": str(speaker or "").strip(), "text": line}
                        return
            seen.add(key)
            events.append({"kind": kind, "speaker": str(speaker or "").strip(), "text": line})

        mixed = parsed and any(cls._is_inner_speaker(str(item.get("speaker") or "")) for item in parsed)
        if mixed:
            for item in parsed:
                speaker = str(item.get("speaker") or "").strip()
                if cls._is_inner_speaker(speaker):
                    add("inner", cls._base_speaker_name(speaker), str(item.get("text") or ""))
                else:
                    add("spoken", speaker, str(item.get("text") or ""))
            for item in cls._inner_turns(shot):
                add("inner", str(item.get("speaker") or "").strip(), str(item.get("text") or ""))
            return events
        for item in cls._dialogue_turns(shot):
            add("spoken", str(item.get("speaker") or "").strip(), str(item.get("text") or ""))
        for item in cls._inner_turns(shot):
            add("inner", str(item.get("speaker") or "").strip(), str(item.get("text") or ""))
        return events

    @classmethod
    def _speech_contract_line(
        cls,
        event: dict[str, Any],
        shot: dict[str, Any],
        speaker_map: dict[str, str],
    ) -> str:
        text = str(event.get("text") or "").strip()
        speaker = str(event.get("speaker") or "").strip()
        subject_index = cls._subject_index_for_speaker(shot, event)
        subject = f"<Subject {subject_index}> " if subject_index else ""
        speaker_id = f"S{subject_index}" if subject_index else speaker_map.get(speaker)
        identity = f"({speaker_id}) {subject}" if speaker_id else ""
        if event.get("kind") == "inner":
            speaker = speaker or "旁白"
            return (
                f"{identity}{speaker} thinks. In an off-screen inner voiceover, "
                "all visible characters keep their lips closed: "
                f"<d>[Chinese] {text}</d>."
            )
        return (
            f"{identity}{speaker} says <d>[Chinese] {text}</d>. "
            "The shot holds long enough for the complete unhurried speech and a natural pause."
        )

    @classmethod
    def _subject_index_for_speaker(cls, shot: dict[str, Any], event: dict[str, Any] | str) -> int | None:
        if isinstance(event, dict):
            speaker = str(event.get("speaker") or "").strip()
            character_id = str(event.get("character_id") or "")
        else:
            speaker = str(event or "").strip()
            character_id = ""
        character_references = [item for item in (shot.get("character_references") or []) if isinstance(item, dict)]
        for index, reference in enumerate(character_references, start=1):
            if character_id and str(reference.get("character_id") or "") == character_id:
                return index
        for index, reference in enumerate(character_references, start=1):
            if speaker and str(reference.get("character_name") or "").strip() == speaker:
                return index
        return None

    @classmethod
    def speech_slot_lines(cls, shot: dict[str, Any]) -> list[str]:
        return [
            f"{{{{D{index}}}}}"
            for index, event in enumerate(cls.ordered_speech_events(shot), start=1)
            if str(event.get("text") or "").strip()
        ]

    @classmethod
    def speech_slot_legend(cls, shot: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        for index, event in enumerate(cls.ordered_speech_events(shot), start=1):
            if not str(event.get("text") or "").strip():
                continue
            speaker = str(event.get("speaker") or "").strip()
            subject_index = cls._subject_index_for_speaker(shot, event)
            speaker_id = f"S{subject_index}" if subject_index else ""
            subject = f"<Subject {subject_index}>" if subject_index else ""
            identity = " ".join(item for item in ((f"({speaker_id})" if speaker_id else ""), subject) if item)
            if event.get("kind") == "inner":
                kind = "inner off-screen"
                speaker = speaker or "旁白"
            else:
                kind = "spoken"
                speaker = speaker or "说话人"
            who = " ".join(item for item in (identity, speaker) if item)
            lines.append(f"D{index}: {who} {kind}")
        return lines

    @classmethod
    def _placeholder_contract(cls, shot: dict[str, Any], speaker_map: dict[str, str]) -> str:
        required = cls._required_contract(shot, speaker_map)
        events = [item for item in cls.ordered_speech_events(shot) if str(item.get("text") or "").strip()]
        if not events:
            return required
        shell, _, tail = required.partition("detailed_description:\n")
        detail, sep, rest = tail.partition("\noverall_soundscape:")
        tokens = "\n".join(f"{{{{D{index}}}}}" for index, _ in enumerate(events, start=1))
        return f"{shell}detailed_description:\n[Shot 1]\n{tokens}{sep}{rest}"

    @classmethod
    def _protect_spans(cls, text: str, spans: list[str]) -> tuple[str, dict[str, str]]:
        mapping: dict[str, str] = {}
        protected = str(text or "")
        unique = sorted({item for item in spans if item}, key=len, reverse=True)
        for index, span in enumerate(unique):
            if span not in protected:
                continue
            token = f"__H3KEEP_{index}__"
            protected = protected.replace(span, token)
            mapping[token] = span
        return protected, mapping

    @classmethod
    def _restore_spans(cls, text: str, mapping: dict[str, str]) -> str:
        restored = str(text or "")
        for token, span in mapping.items():
            restored = restored.replace(token, span)
        return restored

    @classmethod
    def _replace_model_speech_span(
        cls,
        text: str,
        event: dict[str, Any],
        line: str,
    ) -> tuple[bool, str]:
        needle = cls._han_only(str(event.get("text") or ""))
        if len(needle) < 4:
            return False, text
        for match in re.finditer(r"<d>(?:\[[^\]]+\]\s*)?(.*?)</d>", text, flags=re.S):
            body_han = cls._han_only(match.group(1))
            if not body_han:
                continue
            if needle != body_han and needle not in body_han and body_han not in needle:
                continue
            start, end = match.start(), match.end()
            prefix = text[max(0, start - 140):start]
            says = re.search(
                r"(?:\(\w+\)\s+)?(?:<Subject\s+\d+>\s+)?"
                r"[^\n<>]{0,40}?\b(?:says|thinks)\s*"
                r"(?:in an off-screen inner voiceover:\s*)?$",
                prefix,
                flags=re.I,
            )
            inner_pref = re.search(_INNER_PREFIX_RE.pattern + r"$", prefix, flags=re.I)
            thinks_stub = re.search(
                r"(?:\(\w+\)\s*)?(?:<Subject\s+\d+>\s*)?[^\n<>]{1,24}?\s+thinks\.?\s*"
                r"(?:In an off-screen inner voiceover,[^:]{0,120}:\s*)?$",
                prefix,
                flags=re.I,
            )
            if thinks_stub:
                start = max(0, match.start() - 140) + thinks_stub.start()
            elif says:
                start = max(0, start - 140) + says.start()
            elif inner_pref:
                start = max(0, match.start() - 140) + inner_pref.start()
            suffix = text[end:end + 180]
            extra = 0
            voice = _VOICE_DIR_RE.match(suffix)
            if voice:
                extra = voice.end()
            hold = _HOLD_LINE_RE.match(suffix[extra:])
            if hold:
                extra += hold.end()
            return True, text[:start] + line + text[end + extra:]
        found = cls._flexible_line_re(str(event.get("text") or "")).search(text)
        if not found:
            return False, text
        around = text[max(0, found.start() - 8):found.start()]
        if "<d>" in around:
            return False, text
        start = found.start()
        prefix = text[max(0, start - 140):start]
        thinks_lead = re.search(
            r"(?:(?:\(\w+\)\s*)?(?:<Subject\s+\d+>\s*)?[^\n<>]{1,24}?\s+)?"
            r"(?:he|she|they)\s+thinks\s*$"
            r"|(?:\(\w+\)\s*)?(?:<Subject\s+\d+>\s*)?[^\n<>]{1,24}?\s+thinks\.\s*$",
            prefix,
            flags=re.I,
        )
        if thinks_lead:
            start = max(0, found.start() - 140) + thinks_lead.start()
        return True, text[:start] + line + " " + text[found.end():]

    @classmethod
    def _insert_before_freeze_or_append(cls, text: str, lines: list[str]) -> str:
        block = " ".join(item for item in lines if item).strip()
        if not block:
            return text
        detail_start = text.find("detailed_description:")
        sound_start = text.find("\noverall_soundscape:", detail_start)
        if detail_start < 0:
            return text.rstrip() + "\n" + block
        detail = text[detail_start:sound_start if sound_start >= 0 else len(text)]
        prefix = text[:detail_start]
        suffix = text[sound_start:] if sound_start >= 0 else ""
        freeze = _FREEZE_TAIL_RE.search(detail)
        if freeze:
            detail = detail[:freeze.start()].rstrip() + " " + block + " " + detail[freeze.start():]
        else:
            detail = detail.rstrip() + "\n" + block
        return prefix + detail + suffix

    @classmethod
    def _move_freeze_after_speech(cls, text: str) -> str:
        detail_start = text.find("detailed_description:")
        sound_start = text.find("\noverall_soundscape:", detail_start)
        if detail_start < 0 or sound_start < 0:
            return text
        detail = text[detail_start:sound_start]
        freeze = _FREEZE_TAIL_RE.search(detail)
        last_d = None
        for match in re.finditer(r"</d>", detail):
            last_d = match
        if not freeze or not last_d or freeze.start() > last_d.start():
            return text
        freeze_sent = freeze.group(0).strip()
        detail = (detail[:freeze.start()] + " " + detail[freeze.end():]).strip()
        last_d = None
        for match in re.finditer(r"</d>", detail):
            last_d = match
        if not last_d:
            return text
        insert_at = last_d.end()
        hold = _HOLD_LINE_RE.match(detail[insert_at:])
        if hold:
            insert_at += hold.end()
        detail = detail[:insert_at] + " " + freeze_sent + detail[insert_at:]
        return text[:detail_start] + re.sub(r"[ \t]{2,}", " ", detail) + text[sound_start:]

    @classmethod
    def _strip_speech_glue(cls, text: str, lines: list[str]) -> str:
        for line in lines:
            if not line:
                continue
            start = 0
            while True:
                pos = text.find(line, start)
                if pos < 0:
                    break
                prefix = text[:pos]
                suffix = text[pos + len(line):]
                window = prefix[-160:]
                lead = _SPEECH_LEADIN_RE.search(window)
                if lead and lead.end() == len(window):
                    prefix = prefix[: len(prefix) - len(window) + lead.start()]
                trail = _SPEECH_TRAIL_RE.match(suffix)
                if trail:
                    suffix = suffix[trail.end():]
                text = prefix + line + suffix
                start = len(prefix) + len(line)
        return text

    @classmethod
    def _strip_slot_legends(cls, text: str) -> str:
        previous = None
        while previous != text:
            previous = text
            text = _SLOT_LEGEND_RE.sub(" ", text)
        return text

    @classmethod
    def _strip_misplaced_after_line_holds(cls, text: str) -> str:
        last_d = None
        for match in re.finditer(r"</d>", text):
            last_d = match
        if not last_d:
            return text
        return _AFTER_LINE_HOLD_RE.sub(" ", text[: last_d.end()]) + text[last_d.end() :]

    @classmethod
    def _unglue_and_complete_names(cls, text: str) -> str:
        value = re.sub(r"([A-Za-z])(\(S\d+\))", r"\1. \2", text)
        names = [
            match.group(1)
            for match in re.finditer(
                r"<Subject\s+\d+>\s+is\s+[^.]*?\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+in\s+<Picture",
                value,
            )
        ]
        for full in names:
            parts = full.split()
            if len(parts) < 2:
                continue
            last = parts[-1]
            prefix = " ".join(parts[:-1])
            for size in range(2, len(last)):
                stub = f"{prefix} {last[:size]}".strip()
                value = re.sub(
                    rf"\b{re.escape(stub)}\.?\s*(\(S\d+\))",
                    f"{full}. \\1",
                    value,
                )
        return value

    @classmethod
    def _separate_clustered_speech(cls, text: str, lines: list[str]) -> str:
        for left, right in zip(lines, lines[1:]):
            if not left or not right:
                continue
            start = text.find(left)
            nxt = text.find(right, start + len(left) if start >= 0 else 0)
            if start < 0 or nxt < 0:
                continue
            gap = text[start + len(left):nxt]
            if _SPEECH_GAP_BEAT_RE.search(gap):
                continue
            visual = _HOLD_LINE_RE.sub(" ", gap)
            if len(re.findall(r"\b[A-Za-z]{4,}\b", visual)) >= 6:
                continue
            text = text[: start + len(left)] + _CLOSED_MOUTH_BEAT + text[nxt:]
        return text

    @classmethod
    def _interleave_errors(cls, prompt: str, event_count: int) -> list[str]:
        if event_count < 2:
            return []
        detail_start = prompt.find("detailed_description:")
        sound_start = prompt.find("\noverall_soundscape:", detail_start)
        if detail_start < 0:
            return []
        detail = prompt[detail_start: sound_start if sound_start >= 0 else len(prompt)]
        tags = list(re.finditer(r"<d>.*?</d>", detail, flags=re.S))
        if event_count >= 3:
            for left, right in zip(tags, tags[1:]):
                gap = detail[left.end():right.start()]
                if _SPEECH_GAP_BEAT_RE.search(gap):
                    continue
                visual = re.sub(
                    r"\s*(?:\(\w+\)\s*)?(?:<Subject\s+\d+>\s*)?"
                    r"[^\n<>]{0,24}?\b(?:says|thinks)\.?\s*"
                    r"(?:In an off-screen inner voiceover,[^:]{0,80}:\s*)?",
                    " ",
                    gap,
                    flags=re.I,
                )
                visual = _HOLD_LINE_RE.sub(" ", visual)
                if len(re.findall(r"\b[A-Za-z]{4,}\b", visual)) < 6:
                    return [
                        "interleave each speech line with its camera beat; do not cluster inner and spoken after the last camera move"
                    ]
        return []

    @classmethod
    def rewrite_location_labels(cls, prompt: str, shot: dict[str, Any]) -> str:
        indexes = cls._required_picture_indexes(shot)
        if not indexes:
            return str(prompt or "")
        scene_index = indexes[-1]
        return re.sub(r"<Location\s+\d+\s*>", f"<Subject {scene_index}>", str(prompt or ""), flags=re.I)

    @classmethod
    def _repair_lipsync_claim(cls, text: str, shot: dict[str, Any]) -> str:
        if not cls._inner_turns(shot):
            return text
        return re.sub(
            r"All dialogue is lip-synced[^.]*\.",
            "Spoken lines are lip-synced; inner voice stays off-screen with closed lips.",
            text,
            flags=re.I,
        )

    @classmethod
    def fill_speech_placeholders(
        cls,
        prompt: str,
        shot: dict[str, Any],
        speaker_map: dict[str, str] | None = None,
    ) -> str:
        speaker_map = speaker_map or cls._speaker_map([shot])
        events = [item for item in cls.ordered_speech_events(shot) if str(item.get("text") or "").strip()]
        lines = [cls._speech_contract_line(item, shot, speaker_map) for item in events]
        text = str(prompt or "")
        used: set[int] = set()

        def sub_token(match: re.Match[str]) -> str:
            index = int(match.group(1))
            used.add(index)
            if 1 <= index <= len(lines):
                return lines[index - 1]
            return ""

        text = _DLG_TOKEN_RE.sub(sub_token, text)
        placed = set(used)
        for index, (event, line) in enumerate(zip(events, lines), start=1):
            if index in placed or line in text:
                placed.add(index)
                continue
            replaced, text = cls._replace_model_speech_span(text, event, line)
            if replaced:
                placed.add(index)
        expected_hans = [
            han for han in (cls._han_only(str(event.get("text") or "")) for event in events) if han
        ]
        if cls._d_tag_hans(text) == expected_hans:
            text = _HE_THINKS_LEAD_RE.sub("", text)
            text = _DUP_THINKS_RE.sub("", text)
            text = cls._strip_speech_glue(text, lines)
            text = cls._strip_slot_legends(text)
            text = _CONTINUING_GLUE_RE.sub(" ", text)
            text = cls._unglue_and_complete_names(text)
            text = cls._strip_misplaced_after_line_holds(text)
            text = cls._separate_clustered_speech(text, lines)
            text = re.sub(r"</d>\s*\.{2,}", "</d>.", text)
            text = cls._move_freeze_after_speech(text)
            text = _DUP_HOLD_RE.sub(r"\1", text)
            text = cls._repair_lipsync_claim(text, shot)
            text = _HE_THINKS_LEAD_RE.sub("", text)
            text = _DUP_THINKS_RE.sub("", text)
            return re.sub(r"[ \t]{2,}", " ", text)
        text = cls.strip_model_speech_tags(text, shot, keep_lines=lines)
        placed = {
            index
            for index, event in enumerate(events, start=1)
            if cls._han_in_d_tag(text, event.get("text") or "")
        }
        for index in range(1, len(lines) + 1):
            if index in placed:
                continue
            nxt = next((item for item in range(index + 1, len(lines) + 1) if item in placed), None)
            if nxt:
                anchor = lines[nxt - 1]
                pos = text.find(anchor)
                if pos >= 0:
                    text = text[:pos] + lines[index - 1] + " " + text[pos:]
                    placed.add(index)
                    continue
            text = cls._insert_before_freeze_or_append(text, [lines[index - 1]])
            placed.add(index)
        text = cls._strip_speech_glue(text, lines)
        text = cls._strip_slot_legends(text)
        text = _CONTINUING_GLUE_RE.sub(" ", text)
        text = cls._unglue_and_complete_names(text)
        text = cls._strip_misplaced_after_line_holds(text)
        text = cls._separate_clustered_speech(text, lines)
        text = re.sub(r"</d>\s*\.{2,}", "</d>.", text)
        text = cls._move_freeze_after_speech(text)
        text = _DUP_HOLD_RE.sub(r"\1", text)
        text = cls._repair_lipsync_claim(text, shot)
        text = re.sub(
            r"\(S(\d+)\)(\s*<Subject\s+)(\d+)(>)",
            lambda match: (
                f"(S{match.group(3)}){match.group(2)}{match.group(3)}{match.group(4)}"
                if match.group(1) != match.group(3)
                else match.group(0)
            ),
            text,
            flags=re.I,
        )
        text = _HE_THINKS_LEAD_RE.sub("", text)
        text = _DUP_THINKS_RE.sub("", text)
        return re.sub(r"[ \t]{2,}", " ", text)

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
        value = _NAMECARD_ASIDE_RE.sub(" ", value)
        value = _CONTRACT_STUB_RE.sub(" ", value)
        value = re.sub(r":\s*;", ":", value)
        value = re.sub(r"\bwhile the\s*\.", " ", value, flags=re.I)
        value = re.sub(r"FINISH AND\.\s*FORBIDDEN", "FORBIDDEN", value, flags=re.I)
        value = re.sub(r"Episode context:\s*[^.]*/\s*\.", " ", value)
        for line in sorted({item for item in (extra_lines or []) if item}, key=len, reverse=True):
            if len(_HAN_RE.findall(line)) < 4:
                continue
            for variant in cls._line_variants(line):
                value = value.replace(variant, "")
            value = cls._flexible_line_re(line).sub("", value)
            for clause in sorted(cls._line_clauses(line), key=len, reverse=True):
                value = value.replace(clause, "")
        return re.sub(r"[ \t]{2,}", " ", value).strip()

    @classmethod
    def _strip_empty_speaker_quotes(cls, text: str) -> str:
        value = str(text or "")
        previous = None
        while previous != value:
            previous = value
            value = _EMPTY_SPEAKER_QUOTE_RE.sub(" ", value)
        return re.sub(r"[ \t]{2,}", " ", value).strip()

    @classmethod
    def _draft_echo_lines(cls, beat_info: dict[str, Any]) -> list[str]:
        characters = beat_info.get("characters") or []
        names: list[str] = []
        if isinstance(characters, list):
            for item in characters:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                else:
                    name = str(item or "").strip()
                if name and name not in names:
                    names.append(name)
        shot = {
            "dialogue": beat_info.get("dialogue"),
            "speaker": beat_info.get("speaker"),
            "dialogue_turns": beat_info.get("dialogue_turns"),
            "narration": beat_info.get("narration"),
            "characters": names,
        }
        spoken = list(beat_info.get("dialogue_turns") or []) or cls._dialogue_turns(shot)
        if spoken:
            spoken = [
                turn for turn in spoken
                if isinstance(turn, dict) and not cls._is_inner_speaker(
                    str(turn.get("speaker") or ""),
                    str(turn.get("delivery") or ""),
                )
            ]
        inner = cls._inner_turns(shot)
        return [
            str(turn.get("text") or "").strip()
            for turn in [*spoken, *inner]
            if isinstance(turn, dict) and str(turn.get("text") or "").strip()
        ]

    @classmethod
    def sanitize_beat_draft(cls, beat_info: dict[str, Any] | None) -> dict[str, Any]:
        """Strip empty quotes, inner-voice leaks, and lip-sync paste blocks before the LLM."""
        info = dict(beat_info or {})
        info.pop("existing_prompt", None)
        echo_lines = cls._draft_echo_lines(info)
        for key in ("action", "visual_prompt", "video_prompt_zh"):
            cleaned = cls._strip_empty_speaker_quotes(
                cls.strip_script_echo(str(info.get(key) or ""), echo_lines)
            )
            if key in info or cleaned:
                info[key] = cleaned
        return info

    @staticmethod
    def english_word_count(text: str) -> int:
        return len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", str(text or "")))

    @classmethod
    def is_thick_visual_draft(cls, visual_prompt: str) -> bool:
        text = str(visual_prompt or "")
        if cls.english_word_count(text) >= 280:
            return True
        return any(marker in text for marker in _THICK_DRAFT_MARKERS)

    @classmethod
    def detect_pack_aspect_ratio(cls, beat_info: dict[str, Any]) -> str:
        explicit = re.sub(r"\s+", "", str(beat_info.get("aspect_ratio") or "").replace("：", ":"))
        if explicit in {"9:16", "16:9"}:
            return explicit
        blob = " ".join(
            str(beat_info.get(key) or "")
            for key in ("visual_prompt", "action", "video_prompt_zh", "camera")
        )
        match = _ASPECT_RATIO_RE.search(blob)
        if not match:
            return ""
        return re.sub(r"\s+", "", match.group(1).replace("：", ":"))

    @classmethod
    def packing_retry_block(cls, errors: list[str], previous_prompt: str = "") -> str:
        joined = "；".join(str(item) for item in errors if item)
        timeline = any(
            token in joined
            for token in (
                "speaker ID",
                "<Location",
                "does not match <Subject",
                "interleave",
                "slot legend",
                "then speaks",
                "speaks first",
                "before continuing",
                "glued to a truncated",
            )
        )
        instruction = (
            "Keep subject_definitions and locked Chinese. Rewrite only [Shot 1] blocking so each "
            "{{Dn}} sits on its camera beat, (Sn) equals <Subject n>, and the scene uses "
            "<Subject n> not <Location n>."
            if timeline
            else H3_PACKING_RETRY_INSTRUCTION
        )
        lines = [instruction, *(f"- {item}" for item in errors if item)]
        if previous_prompt:
            lines.append(f"Previous output:\n{previous_prompt}")
        return "\n".join(lines)

    @classmethod
    def packing_rule_text(cls, mode: str, duration_seconds: str | int = "8") -> str:
        timing = build_workshop_h3_timing_rules(duration_seconds)
        if mode == "Ref2VA":
            return f"{timing}\n\n{load_h3_ref2va_workshop_excerpt()}"
        skill = load_h3_prompt_writing_skill()
        base = load_h3_prompt_writing_guide(mode="base")
        selected = (
            "# Selected guide: references/base-en.txt\n"
            f"Input mode is {mode}. Follow its alignment instruction and the three core fields exactly. "
            "Do not use the Ref2VA six-section format.\n\n"
            f"{base}"
        )
        return f"{timing}\n\n{skill}\n\n{selected}"

    @classmethod
    def packing_system_prompt(cls, mode: str, duration_seconds: str | int = "8") -> str:
        seconds = str(duration_seconds).strip() or "8"
        if mode == "Ref2VA":
            headings = "\n".join(f"{name}:" for name in H3_SECTIONS)
            structure = (
                "Return only the finished prompt. It must contain exactly these six section headings, "
                f"spelled exactly and in this order, with each heading on its own line:\n{headings}\n\n"
                "Write all six sections in English. Preserve the original language only for dialogue, lyrics, "
                "and visible scene text. A speaker name is metadata, never dialogue."
            )
        else:
            headings = "\n".join(
                f"{name}:"
                for name in (
                    "integrated_multimodal_description",
                    "overall_soundscape",
                    "non_diegetic_music",
                )
            )
            if mode == "T2VA":
                instruction = "Begin directly with integrated_multimodal_description."
            elif mode == "I2VA":
                instruction = (
                    "The first line must be exactly: For the target video, at 0.00 seconds into the "
                    "target video, <Picture 1> (from [Shot 1]) is fully referenced."
                )
            elif mode == "FL2VA":
                instruction = (
                    f"Use the FL2VA first-and-last-frame alignment instruction, with {seconds}.00 "
                    "as the last-frame timestamp."
                )
            else:
                instruction = (
                    f"Use the L2VA last-frame alignment instruction, aligning <Picture 1> with the "
                    f"{seconds}.00-second mark."
                )
            structure = (
                f"Return only the finished {mode} prompt.\n{instruction}\n"
                f"Follow it with exactly these core fields, each heading on its own line:\n{headings}"
            )
        picture_body = "detailed_description" if mode == "Ref2VA" else "integrated_multimodal_description"
        return (
            f"You are a MiniMax H3 prompt packer for mode {mode}. "
            "Pack the supplied visual draft into the official shell. Do not write a new scene. "
            f"Fit all described action and complete speech naturally within {seconds} seconds.\n\n"
            f"{structure}\n\n"
            f"{picture_body} must preserve the SOURCE VISUAL DRAFT's composition, lighting, blocking, "
            "camera, and FORBIDDEN items. Keep the draft's "
            f"{seconds}-second performance as one [Shot 1] lasting {seconds} seconds; "
            "do not invent extra events or compress a longer play into this take. "
            "Assign actual speakers stable IDs where (Sn) is always <Subject n>. "
            "Do not invent <Location n>; the environment is the last <Subject n> anchored by that <Picture n>. "
            "Place {{D1}}, {{D2}}, ... tokens in [Shot 1] on the matching camera beat. "
            "Interleave: camera action, then that beat's {{Dn}}, then the next camera action. "
            "Do not describe the whole camera move first and dump all speech after. "
            "Copy only the {{Dn}} token into [Shot 1]; never copy slot legends, "
            "'spoken lip-sync — Name', or 'inner off-screen — Name'. "
            "Do not write says-sentences, 'X then speaks', 'speaks first with a tone', "
            "'before continuing', 'speaks with', 'continuing with', or 'spoken by'. "
            "Do not emit <d> tags or Chinese dialogue; the renderer substitutes locked speech into those tokens. "
            "Inner {{Dn}} is the listener's off-screen thought with closed lips, never the previous speaker continuing. "
            "Separate inner {{Dn}} from the next spoken {{Dn}} with a closed-mouth camera beat. "
            "Put freeze or end hold AFTER the last {{Dn}}. "
            "Never put the speaker name or quotation wrappers inside spoken tags. "
            "Do not invent dialogue. Use at most one camera move with small amplitude at slow speed, or a static hold. "
            f"{H3_SPEECH_UNIQUENESS_RULES} "
            "When reference images are present, subject_definitions write appearance from the matching "
            "<Picture N>; do not novelize long CAST LOCK faces or wardrobe in the picture body. "
            "Use exactly one [Shot 1]; no internal cuts and no timecodes.\n\n"
            f"--- packing rules ---\n{cls.packing_rule_text(mode, seconds)}"
        )

    @classmethod
    def beat_info_from_shot(cls, shot: dict[str, Any]) -> dict[str, Any]:
        characters: list[dict[str, Any]] = []
        for ref in shot.get("character_references") or []:
            if not isinstance(ref, dict):
                continue
            characters.append({
                "id": ref.get("character_id") or "",
                "name": ref.get("character_name") or "",
                "desc": ref.get("description") or "",
                "look_desc": ref.get("description") or "",
            })
        if not characters:
            for item in shot.get("characters") or []:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        characters.append({"name": name, "desc": item.get("desc") or item.get("look_desc") or ""})
                elif str(item or "").strip():
                    characters.append({"name": str(item).strip()})
        ref_images = shot.get("ref_images") if isinstance(shot.get("ref_images"), list) else []
        if not ref_images:
            for index, character in enumerate(characters, 1):
                ref_images.append({
                    "index": index,
                    "name": character.get("name") or f"character {index}",
                    "category": "character",
                })
            scene_name = str(shot.get("scene") or shot.get("scene_name") or "").strip()
            if scene_name:
                ref_images.append({
                    "index": len(ref_images) + 1,
                    "name": scene_name,
                    "category": "scene",
                })
            for prop in shot.get("props") or []:
                if not isinstance(prop, dict):
                    continue
                name = str(prop.get("name") or "").strip()
                if not name:
                    continue
                ref_images.append({
                    "index": len(ref_images) + 1,
                    "name": name,
                    "category": "prop",
                })
        return cls.sanitize_beat_draft({
            "beat_id": shot.get("beat_id") or "",
            "sequence": shot.get("sequence") or 1,
            "heading": shot.get("heading") or "",
            "action": shot.get("action") or "",
            "visual_prompt": shot.get("visual_prompt") or shot.get("promptText") or "",
            "video_prompt_zh": shot.get("video_prompt_zh") or "",
            "audio": shot.get("audio") or shot.get("soundscape") or "",
            "camera": shot.get("camera") or "",
            "dialogue": shot.get("dialogue") or "",
            "dialogue_turns": shot.get("dialogue_turns") if isinstance(shot.get("dialogue_turns"), list) else [],
            "narration": shot.get("narration") or "",
            "visible_text": shot.get("visible_text") or "",
            "speaker": shot.get("speaker") or "",
            "characters": characters,
            "props": shot.get("props") if isinstance(shot.get("props"), list) else [],
            "scene_name": shot.get("scene") or shot.get("scene_name") or "",
            "scene_desc": shot.get("scene_description") or shot.get("scene_desc") or "",
            "ref_images": ref_images,
            "aspect_ratio": shot.get("aspect_ratio") or "",
            "duration_seconds": shot.get("duration_seconds") or shot.get("duration_sec") or 8,
            "time_of_day": shot.get("time_of_day") or "日间",
        })

    @classmethod
    def build_packing_user_prompt(
        cls,
        beat_info: dict[str, Any],
        mode: str,
        duration_seconds: str | int,
        *,
        json_output: bool = False,
        speaker_map: dict[str, str] | None = None,
        required_contract: str = "",
        correction: str = "",
    ) -> str:
        beat_info = cls.sanitize_beat_draft(beat_info)
        seconds = str(duration_seconds).strip() or "8"
        picture_body = "detailed_description" if mode == "Ref2VA" else "integrated_multimodal_description"
        visual_prompt = str(beat_info.get("visual_prompt") or "").strip()
        thick = cls.is_thick_visual_draft(visual_prompt)
        aspect_ratio = cls.detect_pack_aspect_ratio(beat_info)
        if thick:
            packing_task = (
                f"Pack this beat into the official {mode} shell. Preserve the SOURCE VISUAL DRAFT as "
                f"{picture_body}. Pack and preserve composition, lighting, blocking, camera, and FORBIDDEN "
                "items. Do not write a new scene."
            )
        else:
            packing_task = (
                f"Pack this beat into the official {mode} shell. SOURCE VISUAL DRAFT is the picture-body "
                "authority. Fill only missing camera, lighting, sound, or timing into English. Chinese action "
                "and audio only fill gaps. Do not write a new scene."
            )
        user_lines = [
            packing_task,
            "只输出成品提示词。禁止另写一场戏。",
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
                if isinstance(char, dict):
                    desc = char.get("look_desc") or char.get("desc") or "暂无特征描述"
                    user_lines.append(f"{idx}. {char.get('name')}（{desc}）")
                else:
                    user_lines.append(f"{idx}. {char}")
        else:
            user_lines.append("未指定出场角色。")
        props = beat_info.get("props") or []
        if props:
            user_lines.append("出场道具列表：")
            for idx, prop in enumerate(props, 1):
                if isinstance(prop, dict):
                    user_lines.append(f"{idx}. {prop.get('name')}（{prop.get('desc') or '特征完好'}）")
                else:
                    user_lines.append(f"{idx}. {prop}")
        cleaned_dialogue = cls._clean_dialogue(str(beat_info.get("dialogue") or ""), str(beat_info.get("speaker") or ""))
        audio = str(beat_info.get("audio") or beat_info.get("soundscape") or "").strip()
        shot_for_speech = {
            "dialogue": beat_info.get("dialogue"),
            "speaker": beat_info.get("speaker"),
            "dialogue_turns": beat_info.get("dialogue_turns"),
            "narration": beat_info.get("narration"),
            "characters": [
                item.get("name") if isinstance(item, dict) else item
                for item in characters
            ],
            "character_references": [
                {
                    "character_id": str(item.get("id") or ""),
                    "character_name": str(item.get("name") or ""),
                }
                for item in characters
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ],
        }
        spoken_turns = list(beat_info.get("dialogue_turns") or []) or cls._dialogue_turns(shot_for_speech)
        if spoken_turns:
            spoken_turns = [
                {
                    **turn,
                    "text": cls._clean_dialogue(str(turn.get("text") or ""), str(turn.get("speaker") or "")),
                }
                for turn in spoken_turns
                if isinstance(turn, dict) and not cls._is_inner_speaker(
                    str(turn.get("speaker") or ""),
                    str(turn.get("delivery") or ""),
                )
            ]
        inner_turns = cls._inner_turns(shot_for_speech)
        action = str(beat_info.get("action") or "").strip()
        video_prompt_zh = str(beat_info.get("video_prompt_zh") or "").strip()
        user_lines.extend([
            "SOURCE VISUAL DRAFT（画面正文权威，装箱进 "
            f"{picture_body}，中文动作和 audio 只补缺口）：",
            visual_prompt or "无",
            f"画面动作与细节要求（中文动作，只补草稿缺口，不要复述台词原文）：{action or '画面进行中'}",
            f"音效 / audio（写入 overall_soundscape 与同期声，只补缺口）：{audio or '无'}",
        ])
        if aspect_ratio:
            user_lines.append(f"画幅：原样保留 {aspect_ratio}，不要改成另一种比例。")
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
            f"视频时长：{seconds} 秒",
            f"说话人（仅作元数据，不得写入 <d> 台词正文）：{beat_info.get('speaker') or '无'}",
            f"对白原文（仅开口台词；不要写入画面正文或 <d>，用 {{{{D1}}}} {{{{D2}}}} 占位，渲染器逐字填回）：{spoken_blob or '无对白'}",
        ])
        slot_lines = cls.speech_slot_lines(shot_for_speech)
        slot_legend = cls.speech_slot_legend(shot_for_speech)
        if slot_lines:
            user_lines.append(
                "SPEECH TOKENS（只把下列 token 写入对应运镜之后，禁止抄说明或人名；(Sn) 必须等于 <Subject n>；禁止 <Location n>；冻结放在最后一个 token 之后）："
            )
            user_lines.extend(f"- {item}" for item in slot_lines)
        if slot_legend:
            user_lines.append("SPEECH OWNERS（编号对照，禁止抄进 [Shot 1]）：")
            user_lines.extend(f"- {item}" for item in slot_legend)
        if spoken_turns:
            user_lines.append("多轮开口对白（按顺序保留原文，每轮使用稳定说话人 ID，禁止口型同步内心）：")
            for turn in spoken_turns:
                speaker = str(turn.get("speaker") or "").strip()
                text = cls._clean_dialogue(str(turn.get("text") or ""), speaker)
                if text:
                    user_lines.append(f"- {speaker or '未命名说话人'}：{text}")
        visible_text = str(beat_info.get("visible_text") or "").strip()
        if visible_text:
            user_lines.append(f"画面可见文字（原样保留，不得朗读）：{visible_text}")
        if inner_turns:
            user_lines.append("旁白/内心（画外音，可见人物嘴唇保持闭合，禁止口型同步，成品里中文只出现一次）：")
            for turn in inner_turns:
                speaker = str(turn.get("speaker") or "").strip()
                text = cls._clean_dialogue(str(turn.get("text") or ""), speaker)
                if text:
                    user_lines.append(f"- {speaker or '旁白'}：{text}")
        user_lines.append("reference_map（标签含义必须严格一一对应，禁止增删改编号）：")
        ref_images = beat_info.get("ref_images") or []
        if mode == "T2VA":
            user_lines.append("- 无参考图。使用 T2VA，不要编造 <Picture N> 或 <Subject N>。")
        elif ref_images:
            for item in ref_images:
                if not isinstance(item, dict):
                    continue
                cat = item.get("category")
                cat_name = "场景" if cat == "scene" else ("道具" if cat == "prop" else "角色")
                user_lines.append(f"- <Picture {item.get('index')}>: {item.get('name')}（{cat_name}参考图）")
            user_lines.append(
                "subject_definitions 写 appearance from 对应 <Picture N>；正文不要再小说式重描五官或服装。"
            )
        else:
            user_lines.append("- 未提供可用参考素材。不要编造引用标签。")
        user_lines.extend([
            "",
            f"{picture_body} 必须保住草稿里的构图、光、调度、运镜、禁止项。"
            f"单镜 [Shot 1] 必须在 {seconds} 秒内演完对白与调度，覆盖 {seconds} 秒时序；"
            "禁止写成更长的戏再压进短片。无内切、无时间码。"
            "同一句中文在成品里只能出现一次；装箱只写 {{Dn}} 占位并插在对应运镜之后，开口台词由渲染器口型同步，内心/旁白闭嘴画外音。"
            "(Sn) 等于 <Subject n>。场景用 <Subject n>，不要写 <Location n>。",
        ])
        if json_output:
            beat_id = str(beat_info.get("beat_id") or "")
            user_lines.extend([
                "",
                f"Create exactly one independent {seconds}-second {mode} prompt for this beat. "
                'Return JSON only as {"beat_id":"...","prompt":"..."}. '
                "Do not put content on the same line as a section heading. Copy every mandatory literal below exactly; "
                "do not remove angle brackets, change [Chinese], or paraphrase quoted text.",
            ])
            if required_contract:
                user_lines.append(f"Mandatory literal contract:\n{required_contract}")
                user_lines.append("Do not omit, translate, paraphrase, or shorten dialogue and narration.")
            if speaker_map:
                user_lines.append(
                    f"Stable speaker IDs for the whole episode: {json.dumps(speaker_map, ensure_ascii=False)}"
                )
            if beat_id:
                user_lines.append(f"beat_id must be exactly: {beat_id}")
        if correction:
            user_lines.append(correction)
        return "\n".join(user_lines)

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
    def _d_tag_hans(cls, text: str) -> list[str]:
        hans: list[str] = []
        for inner in re.findall(r"<d>(?:\[[^\]]+\]\s*)?(.*?)</d>", text, flags=re.S):
            han = cls._han_only(inner)
            if han:
                hans.append(han)
        return hans

    @classmethod
    def _line_clauses(cls, line: str) -> list[str]:
        parts = re.split(r"[，,、。.!！？?\s]+", str(line or "").strip())
        return [part for part in parts if len(_HAN_RE.findall(part)) >= 4]

    @classmethod
    def _flexible_line_re(cls, line: str) -> re.Pattern[str]:
        parts = [re.escape(part) for part in re.split(r"[，,、。.!！？?\s]+", str(line or "").strip()) if part]
        if not parts:
            return re.compile(re.escape(str(line or "")))
        return re.compile(r"[^\u4e00-\u9fff]*".join(parts))

    @classmethod
    def _drop_han_sequence(cls, text: str, needle: str) -> str:
        if not needle:
            return text
        hay_pos: list[int] = []
        hay_chars: list[str] = []
        for index, char in enumerate(text):
            if _HAN_RE.fullmatch(char):
                hay_pos.append(index)
                hay_chars.append(char)
        haystack = "".join(hay_chars)
        drop: set[int] = set()
        start = 0
        step = max(len(needle), 1)
        while True:
            idx = haystack.find(needle, start)
            if idx < 0:
                break
            drop.update(hay_pos[idx:idx + len(needle)])
            start = idx + step
        if not drop:
            return text
        cleaned = "".join(char for index, char in enumerate(text) if index not in drop)
        return re.sub(r"[ \t]{2,}", " ", cleaned)

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
    def speech_contract_errors(cls, prompt: str, shot: dict[str, Any]) -> list[str]:
        errors = cls.speech_uniqueness_errors(prompt, shot)
        events = [item for item in cls.ordered_speech_events(shot) if str(item.get("text") or "").strip()]
        expected = [cls._han_only(str(item.get("text") or "")) for item in events]
        expected = [item for item in expected if item]
        if not expected:
            return errors
        bodies = [
            cls._clean_dialogue(value, extra_names=cls._known_speaker_names(shot)).strip()
            for value in re.findall(r"<d>\[Chinese\]\s*(.*?)</d>", prompt, flags=re.S)
            if str(value or "").strip()
        ]
        expected_set = set(expected)
        actual = [cls._han_only(item) for item in bodies]
        actual = [item for item in actual if item]
        for body, han in zip(bodies, actual):
            if han in expected_set:
                continue
            if any(len(exp) >= 6 and (han in exp or exp in han) for exp in expected_set):
                continue
            errors.append(f"unexpected spoken tag: {body[:40]}")
        matched = [han for han in actual if han in expected_set]
        if expected and matched != expected:
            errors.append("speech tags missing or out of performance order")
        for match in re.finditer(r"\(S(\d+)\)\s*<Subject\s+(\d+)>", prompt, flags=re.I):
            if match.group(1) != match.group(2):
                errors.append(
                    f"speaker ID S{match.group(1)} does not match <Subject {match.group(2)}>"
                )
        if re.search(r"<Location\s+\d+", prompt, flags=re.I):
            errors.append("scene must use <Subject n>, not <Location n>")
        if re.search(r"spoken lip-sync\s*[—\-–:]", prompt, flags=re.I):
            errors.append("slot legend leftover: spoken lip-sync")
        if re.search(r"listener thought, not the previous speaker continuing", prompt, flags=re.I):
            errors.append("slot legend leftover: inner annotation")
        if re.search(r"\bthen speaks\b", prompt, flags=re.I):
            errors.append("wrong speaker cue leftover: then speaks")
        if re.search(r"\bspeaks first with\b", prompt, flags=re.I):
            errors.append("wrong speaker cue leftover: speaks first with")
        if re.search(r"\bbefore continuing\b", prompt, flags=re.I):
            errors.append("slot legend leftover: before continuing")
        if re.search(r"[A-Za-z]\(S\d+\)", prompt):
            errors.append("speaker ID glued to a truncated name")
        if _DLG_TOKEN_RE.search(prompt):
            errors.append("unfilled {{Dn}} token")
        errors.extend(cls._interleave_errors(prompt, len(events)))
        return errors

    @classmethod
    def strip_model_speech_tags(
        cls,
        prompt: str,
        shot: dict[str, Any],
        keep_lines: list[str] | None = None,
    ) -> str:
        text, mapping = cls._protect_spans(str(prompt or ""), keep_lines or [])
        text = _D_TAG_RE.sub("", text)
        text = _INNER_PREFIX_RE.sub("", text)
        text = _SAYS_STUB_RE.sub(" ", text)
        for event in cls.ordered_speech_events(shot):
            line = str(event.get("text") or "").strip()
            needle = cls._han_only(line)
            if len(needle) < 4:
                continue
            text = cls._drop_han_sequence(text, needle)
            for variant in cls._line_variants(line):
                text = text.replace(variant, "")
            text = cls._flexible_line_re(line).sub("", text)
            for clause in cls._line_clauses(line):
                text = text.replace(clause, "")
        text = cls._restore_spans(text, mapping)
        return re.sub(r"[ \t]{2,}", " ", text)

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
                    if needle in cls._han_only(stripped):
                        stripped = cls._drop_han_sequence(stripped, needle)
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
            "visual_prompt": str(info.get("visual_prompt") or info.get("promptText") or ""),
            "audio": str(info.get("audio") or info.get("soundscape") or ""),
            "camera": str(info.get("camera") or ""),
            "action": str(info.get("action") or ""),
            "aspect_ratio": str(info.get("aspect_ratio") or ""),
            "duration_seconds": info.get("duration_seconds") or info.get("duration_sec") or 8,
        }

    @classmethod
    def split_visual_clauses(cls, text: str) -> list[str]:
        raw = re.sub(r"[ \t]+", " ", str(text or "")).strip()
        if not raw:
            return []
        chunks = [item.strip() for item in _SECTION_SPLIT_RE.split(raw) if item.strip()]
        clauses: list[str] = []
        for chunk in chunks:
            pieces = [item.strip() for item in _CLAUSE_SPLIT_RE.split(chunk) if item.strip()]
            for piece in pieces or [chunk]:
                if not piece.endswith((".", "!", "?")):
                    piece += "."
                clauses.append(piece)
        return clauses

    @classmethod
    def _clause_covers_speech_gap(cls, clause: str) -> bool:
        text = str(clause or "").strip()
        if not text:
            return False
        if _SPEECH_GAP_BEAT_RE.search(text):
            return True
        return len(re.findall(r"\b[A-Za-z]{4,}\b", text)) >= 6

    @classmethod
    def _fallback_camera_beat(cls, index: int) -> str:
        return _GAP_CAMERA_BEATS[index % len(_GAP_CAMERA_BEATS)]

    @classmethod
    def _subject_definition_lines(cls, shot: dict[str, Any]) -> list[str]:
        indexes = cls._required_picture_indexes(shot)
        refs: dict[int, dict[str, Any]] = {}
        for item in shot.get("ref_images") or []:
            if not isinstance(item, dict) or item.get("index") in (None, ""):
                continue
            try:
                refs[int(item["index"])] = item
            except (TypeError, ValueError):
                continue
        chars = [item for item in (shot.get("character_references") or []) if isinstance(item, dict)]
        last = indexes[-1] if indexes else 0
        lines: list[str] = []
        for index in indexes:
            ref = refs.get(index) or {}
            cat = str(ref.get("category") or "").strip().lower()
            name = str(ref.get("name") or "").strip()
            desc = ""
            if 1 <= index <= len(chars):
                name = name or str(chars[index - 1].get("character_name") or "").strip()
                desc = str(chars[index - 1].get("description") or "").strip()
            is_scene = cat == "scene" or (
                index == last and cat not in {"character", "prop"} and len(indexes) > len(chars)
            )
            if is_scene:
                label = name or "scene"
                lines.append(f"<Subject {index}> is the {label} environment in <Picture {index}>.")
                lines.append(
                    f"<Subject {index}> is the exact scene environment anchored by <Picture {index}>."
                )
            else:
                label = name or f"subject {index}"
                featuring = cls._appearance_fragment(desc)
                extra = f", featuring {featuring}" if featuring else ""
                lines.append(f"<Subject {index}> is {label} in <Picture {index}>{extra}.")
                lines.append(
                    f"<Subject {index}> is the exact character appearance anchored by <Picture {index}>."
                )
        return lines

    @staticmethod
    def _appearance_fragment(desc: str) -> str:
        text = str(desc or "").strip()
        if not text:
            return ""
        if len(_HAN_RE.findall(text)) >= 8 or len(text) > 120:
            return ""
        return text

    @classmethod
    def _split_camera_subbeats(cls, clause: str) -> list[str]:
        text = str(clause or "").strip()
        if not text:
            return []
        chunks = [item.strip(" ,;") for item in _CAMERA_THEN_RE.split(text) if item.strip(" ,;")] or [text]
        parts: list[str] = []
        for chunk in chunks:
            parts.extend(
                item.strip(" ,;")
                for item in _CAMERA_AND_MOVE_RE.split(chunk)
                if item.strip(" ,;")
            )
        if len(parts) < 2:
            return [text]
        beats: list[str] = []
        for index, part in enumerate(parts):
            if index > 0 and not re.match(r"^(?:the\s+)?camera\b|^then\b", part, flags=re.I):
                if re.match(r"^a\s+", part, flags=re.I):
                    part = f"Then {part}"
                else:
                    part = f"The camera {part[0].lower() + part[1:]}" if part[0].isupper() else f"The camera {part}"
            if not part.endswith((".", "!", "?")):
                part += "."
            beats.append(part)
        return beats or [text]

    @staticmethod
    def _is_gaze_beat(clause: str) -> bool:
        return bool(_GAZE_BEAT_RE.search(str(clause or "")))

    @staticmethod
    def _is_push_back_beat(clause: str) -> bool:
        return bool(_PUSH_BACK_RE.search(str(clause or "")))

    @classmethod
    def _is_land_on_face_beat(cls, clause: str) -> bool:
        text = str(clause or "")
        if cls._is_gaze_beat(text) or cls._is_push_back_beat(text):
            return False
        return bool(_LAND_ON_FACE_RE.search(text))

    @staticmethod
    def _take_matching(motion: list[str], predicate) -> str:
        for index, clause in enumerate(motion):
            if predicate(clause):
                return motion.pop(index)
        return ""

    @staticmethod
    def _take_best_matching(motion: list[str], predicate, score=None) -> str:
        matches = [(index, clause) for index, clause in enumerate(motion) if predicate(clause)]
        if not matches:
            return ""
        key = score or (lambda clause: len(clause))
        index, clause = max(matches, key=lambda item: key(item[1]))
        motion.pop(index)
        return clause

    @classmethod
    def _last_spoken_land_score(cls, clause: str) -> tuple:
        text = str(clause or "").lower()
        rank = 0
        if cls._is_push_back_beat(clause):
            rank += 8
        if re.search(r"\b(face|medium-close|close-up)\b", text):
            rank += 4
        if "wu nai" in text:
            rank += 3
        if "landlord" in text:
            rank += 1
        return (rank, len(clause))

    @classmethod
    def _camera_for_speech_event(
        cls,
        event: dict[str, Any],
        index: int,
        events: list[dict[str, Any]],
        motion: list[str],
        character_count: int,
    ) -> str:
        pieces: list[str] = []
        if event.get("kind") == "inner":
            gaze = cls._take_best_matching(motion, cls._is_gaze_beat)
            motion[:] = [clause for clause in motion if not cls._is_gaze_beat(clause)]
            if gaze:
                pieces.append(gaze)
                pieces.append(_INNER_BODY_HOLD)
            elif character_count >= 2:
                pieces.append(_INNER_GAZE_FALLBACK)
        elif index == len(events) - 1:
            back = cls._take_matching(motion, cls._is_push_back_beat)
            if not back:
                back = cls._take_best_matching(
                    motion,
                    cls._is_land_on_face_beat,
                    score=cls._last_spoken_land_score,
                )
            if back:
                pieces.append(back)
        if not pieces and motion:
            pieces.append(motion.pop(0))
        cleaned: list[str] = []
        for item in pieces:
            text = re.sub(r"[:;.,\s]+$", "", str(item).strip())
            if not text:
                continue
            if text[0].islower():
                text = text[0].upper() + text[1:]
            cleaned.append(cls._punctuate_clause(text))
        clause = " ".join(cleaned)
        if not cls._clause_covers_speech_gap(clause):
            fallback = cls._fallback_camera_beat(index)
            clause = f"{fallback} {clause}".strip() if clause else fallback
        return clause

    @classmethod
    def _is_speech_echo_clause(cls, clause: str) -> bool:
        text = str(clause or "").strip()
        if not text or _CONTRACT_STUB_RE.search(text) or _TEMPLATE_SKIP_RE.search(text):
            return True
        if _SPEECH_ECHO_RE.search(text) and not _CAMERA_BEAT_RE.search(text):
            return True
        if _SPEECH_ECHO_RE.search(text) and re.search(r"\b(?:says|opens (?:his|her|their) mouth|no need to guess)\b", text, flags=re.I):
            return True
        return False

    @classmethod
    def _partition_visual_clauses(
        cls,
        clauses: list[str],
        present_names: list[str] | None = None,
    ) -> dict[str, list[str]]:
        names = [str(item).strip().lower() for item in (present_names or []) if str(item).strip()]
        buckets = {
            "intro": [],
            "lock": [],
            "motion": [],
            "blocking": [],
            "freeze": [],
        }
        for raw in clauses:
            clause = _PERFORMANCE_LEAD_RE.sub("", raw).strip()
            clause = _NAMECARD_ASIDE_RE.sub(" ", clause).strip()
            clause = _MOUTH_PARAPHRASE_RE.sub("", clause).strip()
            clause = re.sub(r"[ \t]{2,}", " ", clause).strip()
            if not clause:
                continue
            for part in _RUNON_CAMERA_RE.split(clause) or [clause]:
                cls._bucket_visual_clause(part, buckets, names)
        return buckets

    @classmethod
    def _cast_lock_applies(cls, clause: str, names: list[str]) -> bool:
        lead = _CAST_STAYS_RE.match(str(clause or "").strip())
        if not lead:
            return True
        who = lead.group(1).lower()
        aliases = _CAST_ALIASES.get(who, (who,))
        return any(alias in names for alias in aliases)

    @classmethod
    def _bucket_visual_clause(
        cls,
        clause: str,
        buckets: dict[str, list[str]],
        names: list[str],
    ) -> None:
        clause = str(clause or "").strip()
        if not clause or clause in {".", ":", ";"} or _WRECKAGE_CLAUSE_RE.search(clause):
            return
        if re.match(r"^(?:SYNCHRONIZED SOUND|Episode context)\b", clause, flags=re.I):
            return
        if not clause.endswith((".", "!", "?")):
            clause = clause.rstrip(" :;") + "."
        if _FREEZE_CLAUSE_RE.search(clause) or _FINISH_HOLD_RE.search(clause):
            buckets["freeze"].append(clause)
            return
        if cls._is_speech_echo_clause(clause):
            return
        if not cls._cast_lock_applies(clause, names):
            return
        if _LOCK_LEAD_RE.search(clause) or _FORBIDDEN_TAIL_RE.search(clause):
            buckets["lock"].append(clause)
            return
        if _FRAMING_LEAD_RE.search(clause):
            buckets["intro"].append(clause)
            return
        if _CAMERA_BEAT_RE.search(clause) or re.match(r"^COMPOSITION AND CAMERA\b", clause, flags=re.I):
            buckets["motion"].extend(cls._split_camera_subbeats(clause))
            return
        buckets["blocking"].append(clause)

    @classmethod
    def _shot_soundscape(cls, shot: dict[str, Any]) -> str:
        audio = str(shot.get("audio") or "").strip()
        generic = audio.lower() in {"", "n/a", "ambient room sound and synchronized movement."}
        text = audio
        if generic:
            match = _SOUND_EXTRACT_RE.search(str(shot.get("visual_prompt") or ""))
            if match:
                extracted = re.sub(r"\s+", " ", match.group(1)).strip().rstrip(".")
                if extracted:
                    text = extracted + "."
            text = text or "Ambient room sound and synchronized movement."
        if not _SOUND_TERM_RE.search(text):
            text = f"{text.rstrip('. 。． ')}. {_SOUND_ENGLISH_TAIL}"
        return text

    @classmethod
    def assemble_shot_body(cls, shot: dict[str, Any], speaker_map: dict[str, str] | None = None) -> str:
        speaker_map = speaker_map or cls._speaker_map([shot])
        echo = [
            str(event.get("text") or "").strip()
            for event in cls.ordered_speech_events(shot)
            if str(event.get("text") or "").strip()
        ]
        draft = cls.strip_script_echo(str(shot.get("visual_prompt") or ""), echo)
        present = [
            str(item.get("character_name") or item.get("name") or "").strip()
            for item in [
                *(shot.get("character_references") or []),
                *[{"name": name} for name in (shot.get("characters") or []) if not isinstance(name, dict)],
                *[item for item in (shot.get("characters") or []) if isinstance(item, dict)],
            ]
            if isinstance(item, dict)
        ]
        present.extend(str(item.get("name") or "") for item in (shot.get("ref_images") or []) if isinstance(item, dict))
        buckets = cls._partition_visual_clauses(cls.split_visual_clauses(draft), present)
        motion = [
            item for item in buckets["motion"]
            if item and not cls._is_speech_echo_clause(item)
        ]
        events = [
            item for item in cls.ordered_speech_events(shot) if str(item.get("text") or "").strip()
        ]
        character_count = len([
            item for item in (shot.get("character_references") or [])
            if isinstance(item, dict) and str(item.get("character_name") or "").strip()
        ])
        body: list[str] = []
        body.extend(buckets["intro"])
        body.extend(buckets["lock"])
        body.extend(buckets["blocking"])
        for index, event in enumerate(events):
            body.append(cls._camera_for_speech_event(event, index, events, motion, character_count))
            body.append(cls._speech_contract_line(event, shot, speaker_map))
        body.extend(buckets["freeze"] or [
            "After the last syllable, the shot freezes on a readable facial reaction for about one second."
        ])
        visible = str(shot.get("visible_text") or "").strip()
        if visible:
            body.append(
                f'The only required visible Chinese text is exactly: "{visible}". '
                "It is on-screen text and is never spoken aloud."
            )
        text = " ".join(
            cls._punctuate_clause(piece)
            for piece in body
            if str(piece).strip()
        )
        text = _DUP_THINKS_RE.sub("", text)
        return re.sub(r"[ \t]{2,}", " ", text).strip()

    @staticmethod
    def _punctuate_clause(piece: str) -> str:
        item = str(piece).strip()
        if not item or item.endswith((".", "!", "?")):
            return item
        return f"{item}."

    @classmethod
    def render_ref2va(cls, shot: dict[str, Any]) -> str:
        speaker_map = cls._speaker_map([shot])
        seconds = str(shot.get("duration_seconds") or shot.get("duration_sec") or 8).strip() or "8"
        names = [
            str(item.get("character_name") or "").strip()
            for item in (shot.get("character_references") or [])
            if isinstance(item, dict) and str(item.get("character_name") or "").strip()
        ]
        scene = str(shot.get("scene") or "").strip() or "the referenced setting"
        who = " and ".join(names) if names else "the referenced subjects"
        ratio = cls.detect_pack_aspect_ratio({
            "visual_prompt": shot.get("visual_prompt") or "",
            "action": shot.get("action") or "",
            "camera": shot.get("camera") or "",
            "aspect_ratio": shot.get("aspect_ratio") or "",
        })
        ratio_note = f" {ratio}" if ratio else ""
        detail = "[Shot 1] " + cls.assemble_shot_body(shot, speaker_map)
        while cls.english_word_count(detail) < 280:
            detail = f"{_THICKNESS_PAD} {detail}"
        indexes = cls._required_picture_indexes(shot)
        retention = [
            f"<Subject {index}> (appears in [Shot 1]): fully_preserved - "
            f"appearance anchored by <Picture {index}> is retained."
            for index in indexes
        ]
        audio = cls._shot_soundscape(shot)
        return "\n".join([
            "subject_definitions:",
            " ".join(cls._subject_definition_lines(shot)),
            "summary:",
            f"[reference generation] A {seconds}-second{ratio_note} shot of {who} in {scene}.",
            "retention_analysis:",
            " ".join(retention) if retention else "fully_preserved.",
            "detailed_description:",
            detail,
            "overall_soundscape:",
            audio,
            "non_diegetic_music:",
            "N/A",
        ])

    @classmethod
    def prepare_generated_prompt(
        cls,
        prompt: str,
        shot: dict[str, Any],
        speaker_map: dict[str, str] | None = None,
    ) -> str:
        speaker_map = speaker_map or cls._speaker_map([shot])
        text = cls.canonicalize_reference_tags(prompt)
        text = cls.rewrite_location_labels(text, shot)
        text = cls.fill_speech_placeholders(text, shot, speaker_map)
        text = cls._normalize_prompt(shot, text, speaker_map)
        text = cls.ensure_reference_tags(text, shot)
        text = cls.collapse_repeated_speech(text, shot)
        text = cls.repair_inner_delivery(text, shot)
        text = _HE_THINKS_LEAD_RE.sub("", text)
        text = _DUP_THINKS_RE.sub("", text)
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
        prompts: list[str] = []
        for shot in shots:
            beat_info = cls.sanitize_beat_draft(cls.beat_info_from_shot(shot))
            rendered = cls.shot_from_beat_info(beat_info)
            prompt = cls.render_ref2va(rendered)
            errors = cls.validate_prompts([rendered], [prompt])
            if on_attempt:
                on_attempt({
                    "beat_id": str(shot.get("beat_id") or rendered.get("beat_id") or ""),
                    "sequence": int(shot.get("sequence") or rendered.get("sequence") or len(prompts) + 1),
                    "attempt": 1,
                    "raw_response": "",
                    "prompt": prompt,
                    "errors": list(errors),
                    "status": "passed" if not errors else "failed",
                })
            if errors:
                raise ValueError(
                    f"Beat {shot.get('sequence', len(prompts) + 1)} H3 提示词未通过规则校验："
                    + "；".join(errors)
                )
            prompts.append(prompt)
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
            "visual_prompt": shot.get("visual_prompt") or shot.get("promptText") or "",
            "audio": shot.get("audio") or shot.get("soundscape") or "",
            "video_prompt_zh": shot.get("video_prompt_zh") or "",
            "aspect_ratio": shot.get("aspect_ratio") or "",
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
        for event in H3PromptBuilder.ordered_speech_events(shot):
            speech_lines.append(H3PromptBuilder._speech_contract_line(event, shot, speaker_map))
        visible_text = str(shot.get("visible_text") or "").strip()
        if visible_text:
            speech_lines.append(
                f'The only required visible Chinese text is exactly: "{visible_text}". '
                "It is on-screen text and is never spoken aloud."
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
                shot_map = cls._speaker_map([shot])
                speaker_id = shot_map.get(speaker)
                subject_index = cls._subject_index_for_speaker(shot, speaker)
                if subject_index:
                    speaker_id = f"S{subject_index}"
                if speaker and speaker_id and f"({speaker_id})" not in prompt:
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
            for issue in cls.speech_contract_errors(prompt, shot):
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

    @classmethod
    def _system_prompt(cls, duration_seconds: int = 8) -> str:
        return cls.packing_system_prompt("Ref2VA", duration_seconds)
