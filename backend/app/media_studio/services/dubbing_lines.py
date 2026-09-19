from __future__ import annotations

import hashlib
import json
import re
import struct
import wave
from io import BytesIO
from typing import Any

from ...tts_provider import clamp_duration_factor, clamp_emo_alpha
from .h3_prompt_builder import H3PromptBuilder
from .voice_profile import DEFAULT_EMOTION, normalize_emotion, voice_of

LINE_KINDS = ("spoken", "inner", "narration")
LINE_STATUSES = ("idle", "queued", "running", "ready", "failed")
MIX_MODES = ("overlay", "replace")
_NARRATION_SPEAKER_RE = re.compile(r"^(旁白|画外音|解说)$")
_KEEP_LINE_FIELDS = (
    "emotion",
    "emo_alpha",
    "duration_factor",
    "mix",
    "status",
    "audio_url",
    "duration_sec",
    "job_id",
    "error",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def line_fingerprint(beat_id: str, kind: str, speaker: str, text: str) -> str:
    raw = "|".join((beat_id, kind, speaker, text))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def line_id(beat_id: str, kind: str, speaker: str, text: str) -> str:
    return f"line-{line_fingerprint(beat_id, kind, speaker, text)}"


def default_mix(kind: str) -> str:
    return "overlay"


def classify_event_kind(event: dict[str, Any], beat: dict[str, Any]) -> str:
    kind = _text(event.get("kind")) or "spoken"
    speaker = _text(event.get("speaker"))
    text = _text(event.get("text"))
    if kind != "inner":
        return "spoken"
    narration = _text(beat.get("narration"))
    if narration and (text == narration or narration in text or text in narration):
        return "narration"
    if _NARRATION_SPEAKER_RE.match(speaker):
        return "narration"
    for item in H3PromptBuilder._inner_turns(beat):
        if not isinstance(item, dict):
            continue
        if _text(item.get("text")) == text and _text(item.get("delivery")) == "narration":
            return "narration"
    return "inner"


def _aliases(asset: dict[str, Any]) -> set[str]:
    names = {_text(asset.get("name"))}
    extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
    raw = extra.get("aliases") or ""
    if isinstance(raw, str):
        for part in re.split(r"[,，/、|]", raw):
            names.add(part.strip())
    names.add(_text(extra.get("role_position")))
    return {item for item in names if item}


def match_character_id(
    speaker: str,
    *,
    assets: list[dict[str, Any]],
    beat: dict[str, Any],
    kind: str,
) -> str:
    name = _text(speaker)
    characters = [item for item in assets if isinstance(item, dict) and item.get("kind") == "character"]
    if kind == "narration" and not name:
        for asset in characters:
            extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
            role = _text(extra.get("role_position") or asset.get("role"))
            if role in {"旁白", "解说"} or "旁白" in _text(asset.get("name")):
                return _text(asset.get("id"))
    if not name:
        ids = [str(item) for item in (beat.get("character_ids") or []) if str(item or "").strip()]
        return ids[0] if len(ids) == 1 else ""
    for asset in characters:
        if name in _aliases(asset):
            return _text(asset.get("id"))
    beat_ids = {str(item) for item in (beat.get("character_ids") or []) if str(item or "").strip()}
    for asset in characters:
        if _text(asset.get("id")) in beat_ids and name in _aliases(asset):
            return _text(asset.get("id"))
    return ""


def empty_line(
    *,
    beat_id: str,
    kind: str,
    speaker: str,
    text: str,
    character_id: str = "",
    seq: str = "",
) -> dict[str, Any]:
    return {
        "id": line_id(beat_id, kind, speaker, text),
        "beat_id": beat_id,
        "seq": seq,
        "character_id": character_id,
        "speaker": speaker,
        "text": text,
        "kind": kind if kind in LINE_KINDS else "spoken",
        "emotion": DEFAULT_EMOTION,
        "emo_alpha": 0.8,
        "duration_factor": 1.0,
        "mix": default_mix(kind),
        "status": "idle",
        "audio_url": "",
        "duration_sec": 0.0,
        "job_id": "",
        "error": "",
    }


def normalize_line(raw: Any, *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    source = dict(fallback or {})
    if isinstance(raw, dict):
        source.update(raw)
    beat_id = _text(source.get("beat_id"))
    kind = _text(source.get("kind")) or "spoken"
    if kind not in LINE_KINDS:
        kind = "spoken"
    speaker = _text(source.get("speaker"))
    text = _text(source.get("text"))
    line = empty_line(
        beat_id=beat_id,
        kind=kind,
        speaker=speaker,
        text=text,
        character_id=_text(source.get("character_id")),
        seq=_text(source.get("seq")),
    )
    stored_id = _text(source.get("id"))
    if stored_id:
        line["id"] = stored_id
    line["emotion"] = normalize_emotion(source.get("emotion"), DEFAULT_EMOTION)
    line["emo_alpha"] = clamp_emo_alpha(source.get("emo_alpha"))
    line["duration_factor"] = clamp_duration_factor(source.get("duration_factor"))
    mix = _text(source.get("mix"))
    line["mix"] = mix if mix in MIX_MODES else default_mix(kind)
    status = _text(source.get("status")) or "idle"
    line["status"] = status if status in LINE_STATUSES else "idle"
    line["audio_url"] = _text(source.get("audio_url"))
    try:
        line["duration_sec"] = max(0.0, float(source.get("duration_sec") or 0))
    except (TypeError, ValueError):
        line["duration_sec"] = 0.0
    line["job_id"] = _text(source.get("job_id"))
    line["error"] = _text(source.get("error"))
    if line["audio_url"] and line["status"] == "idle":
        line["status"] = "ready"
    return line


def expand_beat_lines(beat: dict[str, Any], assets: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if not isinstance(beat, dict):
        return []
    beat_id = _text(beat.get("id"))
    events = H3PromptBuilder.ordered_speech_events(beat)
    existing = {
        _text(item.get("id")): item
        for item in (beat.get("dubbing_lines") or [])
        if isinstance(item, dict) and _text(item.get("id"))
    }
    by_fp: dict[str, dict[str, Any]] = {}
    for item in existing.values():
        fp = line_fingerprint(
            _text(item.get("beat_id")) or beat_id,
            _text(item.get("kind")) or "spoken",
            _text(item.get("speaker")),
            _text(item.get("text")),
        )
        by_fp[fp] = item
    lines: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        text = _text(event.get("text"))
        if not text:
            continue
        kind = classify_event_kind(event, beat)
        speaker = _text(event.get("speaker"))
        if kind == "narration" and not speaker:
            speaker = "旁白"
        character_id = match_character_id(speaker, assets=assets or [], beat=beat, kind=kind)
        generated = empty_line(
            beat_id=beat_id,
            kind=kind,
            speaker=speaker,
            text=text,
            character_id=character_id,
        )
        previous = existing.get(generated["id"]) or by_fp.get(line_fingerprint(beat_id, kind, speaker, text))
        if previous:
            merged = normalize_line(previous, fallback=generated)
            merged["id"] = generated["id"]
            merged["beat_id"] = beat_id
            merged["kind"] = kind
            merged["speaker"] = speaker
            merged["text"] = text
            if not merged.get("character_id"):
                merged["character_id"] = character_id
            if merged.get("status") == "ready" and not merged.get("audio_url"):
                merged["status"] = "idle"
            lines.append(merged)
        else:
            if character_id:
                generated.update(_voice_defaults(assets or [], character_id))
            lines.append(generated)
    return lines


def _voice_defaults(assets: list[dict[str, Any]], character_id: str) -> dict[str, Any]:
    asset = next((item for item in assets if _text(item.get("id")) == character_id), None)
    if not asset:
        return {}
    extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
    voice = voice_of(extra)
    return {
        "emotion": voice.get("default_emotion") or DEFAULT_EMOTION,
        "emo_alpha": voice.get("emo_alpha") or 0.8,
        "duration_factor": voice.get("duration_factor") or 1.0,
    }


def assign_sequences(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    numbered: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        item = dict(line)
        item["seq"] = f"B{index}"
        numbered.append(item)
    return numbered


def expand_episode_lines(
    beats: list[dict[str, Any]],
    assets: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    ordered = sorted(
        [beat for beat in beats if isinstance(beat, dict)],
        key=lambda item: int(item.get("sequence") or 0),
    )
    collected: list[dict[str, Any]] = []
    for beat in ordered:
        collected.extend(expand_beat_lines(beat, assets))
    return assign_sequences(collected)


def lines_by_beat(lines: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        beat_id = _text(line.get("beat_id"))
        grouped.setdefault(beat_id, []).append(line)
    return grouped


def apply_line_patch(line: dict[str, Any], patch: dict[str, Any] | None) -> dict[str, Any]:
    allowed = {
        "text", "emotion", "emo_alpha", "duration_factor", "mix",
        "character_id", "speaker", "status", "audio_url", "duration_sec", "job_id", "error",
    }
    updates = {key: value for key, value in (patch or {}).items() if key in allowed}
    if "text" in updates and _text(updates["text"]) != _text(line.get("text")):
        updates.setdefault("status", "idle")
        updates.setdefault("audio_url", "")
        updates.setdefault("duration_sec", 0)
        updates.setdefault("job_id", "")
        updates.setdefault("error", "")
    return normalize_line({**line, **updates}, fallback=line)


def wav_duration_sec(content: bytes) -> float:
    if not content or not content.startswith(b"RIFF"):
        return 0.0
    try:
        with wave.open(BytesIO(content), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or 1
            return round(max(0.0, frames / float(rate)), 3)
    except (wave.Error, struct.error, EOFError):
        return 0.0


def estimate_duration_sec(content: bytes, text: str = "") -> float:
    duration = wav_duration_sec(content)
    if duration:
        return duration
    chars = max(1, len(_text(text)))
    return round(max(0.6, chars / 4.5), 3)


def line_voice_asset(line: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    character_id = _text(line.get("character_id"))
    if character_id:
        found = next((item for item in assets if _text(item.get("id")) == character_id), None)
        if found:
            return found
    speaker = _text(line.get("speaker"))
    for asset in assets:
        if asset.get("kind") == "character" and speaker in _aliases(asset):
            return asset
    return None
