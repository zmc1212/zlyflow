from __future__ import annotations

import json
import re
from typing import Any


EMOTION_KEYS = (
    "happy",
    "angry",
    "sad",
    "afraid",
    "disgusted",
    "melancholic",
    "surprised",
    "calm",
)

EMOTION_LABELS = {
    "happy": "开心",
    "angry": "愤怒",
    "sad": "悲伤",
    "afraid": "害怕",
    "disgusted": "厌恶",
    "melancholic": "忧郁",
    "surprised": "惊讶",
    "calm": "平静",
}

_LANG_ALIASES = {
    "zh": "ZH",
    "cn": "ZH",
    "chinese": "ZH",
    "中文": "ZH",
    "en": "EN",
    "english": "EN",
    "ja": "JA",
    "jp": "JA",
    "japanese": "JA",
    "es": "ES",
    "spanish": "ES",
    "ar": "AR",
    "arabic": "AR",
}

_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")


def clamp_emo_alpha(value: Any, default: float = 0.8) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def clamp_duration_factor(value: Any, default: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.5, min(2.0, number))


def normalize_emotion(value: Any, default: str = "calm") -> str:
    text = str(value or "").strip().lower()
    if text in EMOTION_KEYS:
        return text
    for key, label in EMOTION_LABELS.items():
        if text == label:
            return key
    return default if default in EMOTION_KEYS else "calm"


def emotion_vector(emotion: str | None = None, values: Any = None, *, intensity: float = 1.0) -> list[float]:
    vector = [0.0] * len(EMOTION_KEYS)
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except json.JSONDecodeError:
            values = None
    if isinstance(values, (list, tuple)) and len(values) == len(EMOTION_KEYS):
        parsed: list[float] = []
        for item in values:
            try:
                parsed.append(max(0.0, min(1.0, float(item))))
            except (TypeError, ValueError):
                parsed.append(0.0)
        return parsed
    key = normalize_emotion(emotion)
    vector[EMOTION_KEYS.index(key)] = max(0.0, min(1.0, float(intensity or 1.0)))
    return vector


def detect_lang(text: str, explicit: str | None = None) -> str:
    named = _LANG_ALIASES.get(str(explicit or "").strip().lower())
    if named:
        return named
    sample = str(text or "")
    if _ARABIC_RE.search(sample):
        return "AR"
    if _KANA_RE.search(sample):
        return "JA"
    if _HAN_RE.search(sample):
        return "ZH"
    return "EN"
