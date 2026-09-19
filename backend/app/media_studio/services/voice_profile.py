from __future__ import annotations

from typing import Any

from ...tts_provider import (
    INDEXTTS_EMOTION_KEYS,
    INDEXTTS_VOICE,
    clamp_duration_factor,
    clamp_emo_alpha,
)

MAX_VOICE_AUDIO_BYTES = 20 * 1024 * 1024
VOICE_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
DEFAULT_EMOTION = "calm"

_AUDIO_MAGIC = (
    (b"RIFF", ".wav"),
    (b"ID3", ".mp3"),
    (b"OggS", ".ogg"),
    (b"fLaC", ".flac"),
)


def normalize_emotion(value: Any, default: str = DEFAULT_EMOTION) -> str:
    text = str(value or "").strip().lower()
    labels = {
        "开心": "happy",
        "愤怒": "angry",
        "悲伤": "sad",
        "害怕": "afraid",
        "厌恶": "disgusted",
        "忧郁": "melancholic",
        "惊讶": "surprised",
        "平静": "calm",
    }
    if text in INDEXTTS_EMOTION_KEYS:
        return text
    if text in labels:
        return labels[text]
    return default if default in INDEXTTS_EMOTION_KEYS else DEFAULT_EMOTION


def sniff_audio_suffix(content: bytes, filename: str = "", content_type: str = "") -> str:
    from pathlib import Path

    suffix = Path(filename or "").suffix.lower()
    if suffix in VOICE_AUDIO_SUFFIXES:
        return suffix
    lowered = (content_type or "").lower()
    if "wav" in lowered:
        return ".wav"
    if "mpeg" in lowered or "mp3" in lowered:
        return ".mp3"
    if "ogg" in lowered:
        return ".ogg"
    if "flac" in lowered:
        return ".flac"
    if "aac" in lowered or "mp4" in lowered or "m4a" in lowered:
        return ".m4a"
    head = content[:12] if content else b""
    for magic, mapped in _AUDIO_MAGIC:
        if head.startswith(magic):
            return mapped
    if head[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return ".mp3"
    raise ValueError("请上传 wav / mp3 / m4a / flac / ogg 参考音")


def empty_voice_profile() -> dict[str, Any]:
    return {
        "preset_id": "",
        "ref_audio_url": "",
        "preview_url": "",
        "default_emotion": DEFAULT_EMOTION,
        "emo_alpha": 0.8,
        "duration_factor": 1.0,
        "source": None,
    }


def normalize_voice_source(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()
    episode_id = str(raw.get("episode_id") or "").strip()
    beat_id = str(raw.get("beat_id") or "").strip()
    if kind != "shot" or not episode_id or not beat_id:
        return None
    try:
        start_sec = float(raw.get("start_sec"))
        end_sec = float(raw.get("end_sec"))
    except (TypeError, ValueError):
        return None
    return {
        "kind": "shot",
        "episode_id": episode_id,
        "beat_id": beat_id,
        "start_sec": start_sec,
        "end_sec": end_sec,
    }


def normalize_voice_profile(raw: Any) -> dict[str, Any]:
    base = empty_voice_profile()
    if not isinstance(raw, dict):
        return base
    base["preset_id"] = str(raw.get("preset_id") or "").strip()
    base["ref_audio_url"] = str(raw.get("ref_audio_url") or "").strip()
    base["preview_url"] = str(raw.get("preview_url") or "").strip()
    base["default_emotion"] = normalize_emotion(raw.get("default_emotion"))
    base["emo_alpha"] = clamp_emo_alpha(raw.get("emo_alpha"))
    base["duration_factor"] = clamp_duration_factor(raw.get("duration_factor"))
    base["source"] = normalize_voice_source(raw.get("source"))
    return base


def voice_of(extra: dict[str, Any] | None) -> dict[str, Any]:
    payload = extra if isinstance(extra, dict) else {}
    return normalize_voice_profile(payload.get("voice"))


def has_ref_audio(extra: dict[str, Any] | None) -> bool:
    voice = voice_of(extra)
    return bool(voice.get("ref_audio_url") or voice.get("preset_id"))


def merge_voice(extra: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(extra or {})
    voice = normalize_voice_profile({**voice_of(current), **(patch or {})})
    current["voice"] = voice
    return current


def clone_voice_id(current: str | None) -> str:
    value = str(current or "").strip()
    return value or INDEXTTS_VOICE
