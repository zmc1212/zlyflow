from __future__ import annotations

import math
import re
from typing import Any

from .director_compiler import snap_h3_duration_sec
from .director_recipe import normalize_dialogue


_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_SCRIPT_FIELD_PREFIXES = frozenset({
    "地点", "人物", "动作", "对白", "场次", "场景", "时间", "镜头", "旁白", "画外音",
})
_SCRIPT_SECTION_RE = re.compile(r"^(地点|人物|动作|场次|场景|时间|镜头)[：:]")
_ENTRY_LINE_RE = re.compile(
    r"^\s*([^：:\n]{1,24}?)[：:]\s*(?:(?:（([^）]*)）|\(([^)]*)\))\s*)?(.+?)\s*$"
)
_D_TAG_RE = re.compile(r"<d>(?:\[[^\]]+\])?\s*(.*?)</d>", re.IGNORECASE | re.DOTALL)
_TRUNCATED_SUFFIX_RE = re.compile(r"[.。…]{2,}$")


def count_han_characters(text: str) -> int:
    return len(_HAN_RE.findall(text or ""))


def count_latin_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text or ""))


def estimate_dialogue_duration_sec(dialogue: str, *, emotional: bool = False) -> float:
    text = (dialogue or "").strip()
    if not text:
        return 0.0
    han = count_han_characters(text)
    words = count_latin_words(text)
    if han and not words:
        rate = 3.0 if emotional else 4.0
        return han / rate
    if words and not han:
        return words / 2.5
    if han and words:
        return max(han / (3.0 if emotional else 4.0), words / 2.5)
    return max(1.0, len(text) / 6.0)


def estimate_shot_duration_sec(
    dialogue: str,
    *,
    action_beats: int = 1,
    emotional: bool = False,
) -> int:
    speech = estimate_dialogue_duration_sec(dialogue, emotional=emotional)
    beats = max(1, int(action_beats))
    action = 2.0 + max(0, beats - 1) * 2.5
    if speech:
        action += 1.0
    return max(2, min(15, int(math.ceil(max(speech, action)))))


def extract_script_dialogue_entries(text: str) -> list[dict[str, str]]:
    """Extract speaker + dialogue from Chinese screenplay-style script text."""
    if not (text or "").strip():
        return []
    entries: list[dict[str, str]] = []
    in_dialogue_section = False
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^对白[：:]", line):
            in_dialogue_section = True
            continue
        if _SCRIPT_SECTION_RE.match(line):
            in_dialogue_section = False
            continue
        match = _ENTRY_LINE_RE.match(line)
        if not match:
            if in_dialogue_section and line and not line.startswith("【"):
                entries.append({"speaker": "", "delivery": "", "dialogue": line})
            continue
        speaker = match.group(1).strip()
        if speaker in _SCRIPT_FIELD_PREFIXES:
            continue
        delivery = (match.group(2) or match.group(3) or "").strip()
        dialogue = (match.group(4) or "").strip()
        if dialogue:
            entries.append({"speaker": speaker, "delivery": delivery, "dialogue": dialogue})
    return entries


def extract_script_dialogue_lines(text: str) -> list[str]:
    """Extract speakable lines from Chinese screenplay-style script text."""
    return [entry["dialogue"] for entry in extract_script_dialogue_entries(text)]


def count_script_dialogue_lines(text: str) -> int:
    return len(extract_script_dialogue_lines(text))


def script_dialogue_coverage_low(script_text: str, assigned_dialogue_shots: int) -> bool:
    expected = count_script_dialogue_lines(script_text)
    if expected < 1:
        return False
    return assigned_dialogue_shots < expected


def _shot_text_blob(shot: dict[str, Any]) -> str:
    return " ".join(
        str(shot.get(key) or "")
        for key in ("title", "description", "promptText", "soundscape")
    )


def _speaker_matches_shot(shot: dict[str, Any], speaker: str) -> bool:
    speaker = (speaker or "").strip()
    if not speaker:
        return False
    for name in shot.get("characterNames") or []:
        name_text = str(name).strip()
        if not name_text:
            continue
        if speaker in name_text or name_text in speaker:
            return True
    blob = _shot_text_blob(shot)
    return speaker in blob


def _score_shot_for_dialogue_entry(shot: dict[str, Any], entry: dict[str, str]) -> int:
    speaker = entry.get("speaker") or ""
    dialogue = entry.get("dialogue") or ""
    delivery = entry.get("delivery") or ""
    score = 0
    if _speaker_matches_shot(shot, speaker):
        score += 12
    if delivery and delivery in _shot_text_blob(shot):
        score += 6
    if speaker and speaker in _shot_text_blob(shot):
        score += 8
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", dialogue):
        if chunk in _shot_text_blob(shot):
            score += 3
    if "同门" in speaker and "同门" in _shot_text_blob(shot):
        score += 8
    if "灵石" in dialogue and "灵石" in _shot_text_blob(shot):
        score += 4
    return score


def missing_script_dialogue_entries(script_text: str, recipe: dict[str, Any]) -> list[dict[str, str]]:
    entries = extract_script_dialogue_entries(script_text)
    if not entries:
        return []
    existing = {
        normalize_dialogue(shot.get("dialogue")).strip()
        for scene in recipe.get("scenes") or []
        if isinstance(scene, dict)
        for shot in scene.get("shots") or []
        if isinstance(shot, dict)
    }
    existing.discard("")
    return [entry for entry in entries if entry["dialogue"] not in existing]


def assign_missing_script_dialogue(recipe: dict[str, Any], script_text: str) -> int:
    """Assign parsed script dialogue onto silent shots without a full LLM re-storyboard."""
    missing = missing_script_dialogue_entries(script_text, recipe)
    if not missing:
        return 0
    silent_shots: list[dict[str, Any]] = []
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if isinstance(shot, dict) and not normalize_dialogue(shot.get("dialogue")).strip():
                silent_shots.append(shot)
    if not silent_shots:
        return 0
    assigned = 0
    pending = list(missing)
    while pending and silent_shots:
        best_shot_idx = 0
        best_entry_idx = 0
        best_score = -1
        for shot_idx, shot in enumerate(silent_shots):
            for entry_idx, entry in enumerate(pending):
                score = _score_shot_for_dialogue_entry(shot, entry)
                if score > best_score:
                    best_score = score
                    best_shot_idx = shot_idx
                    best_entry_idx = entry_idx
        shot = silent_shots.pop(best_shot_idx)
        entry = pending.pop(best_entry_idx)
        shot["dialogue"] = entry["dialogue"]
        speaker = (entry.get("speaker") or "").strip()
        if speaker and not (shot.get("speakerName") or "").strip():
            shot["speakerName"] = speaker
        note = (shot.get("timingNote") or "").strip()
        suffix = "对白已从剧本补全"
        shot["timingNote"] = f"{note}；{suffix}" if note else suffix
        if shot.get("durationSec") in (None, 0, 5):
            shot["durationSec"] = estimate_shot_duration_sec(entry["dialogue"])
        enforce_shot_dialogue_timing(shot)
        assigned += 1
    return assigned


def looks_truncated_dialogue(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if cleaned.endswith("...") or cleaned.endswith("…"):
        return True
    return bool(_TRUNCATED_SUFFIX_RE.search(cleaned))


def is_dialogue_truncated(candidate: str, baseline: str) -> bool:
    cand = normalize_dialogue(candidate).strip()
    base = normalize_dialogue(baseline).strip()
    if not base:
        return False
    if not cand:
        return True
    if looks_truncated_dialogue(cand):
        return True
    if len(cand) < len(base):
        stripped = re.sub(r"[.。…]+$", "", cand).strip()
        if stripped and base.startswith(stripped) and stripped != base:
            return True
    return False


def dialogue_language_tag(text: str) -> str:
    han = count_han_characters(text)
    words = count_latin_words(text)
    if han and not words:
        return "Chinese"
    if words and not han:
        return "English"
    return "Chinese" if han >= words else "English"


def format_dialogue_tag(dialogue: str) -> str:
    line = (dialogue or "").strip()
    return f"<d>[{dialogue_language_tag(line)}] {line}</d>"


def extract_dialogue_from_prompt(prompt_text: str) -> str:
    match = _D_TAG_RE.search(prompt_text or "")
    if not match:
        return ""
    return normalize_dialogue(match.group(1)).strip()


def count_prompt_action_beats(prompt_text: str) -> int:
    return max(1, len(re.findall(r"At\s+00:", prompt_text or "", re.I)))


def replace_dialogue_in_prompt(prompt_text: str, dialogue: str) -> str:
    line = (dialogue or "").strip()
    if not line:
        return prompt_text or ""
    text = prompt_text or ""
    tag_block = format_dialogue_tag(line)
    if re.search(r"<d>", text, re.I):
        return re.sub(
            r"<d>(?:\[[^\]]+\])?\s*.*?</d>",
            tag_block,
            text,
            count=1,
            flags=re.I | re.DOTALL,
        )
    if re.search(r"says\s*:", text, re.I):
        return re.sub(
            r"(says\s*:\s*)(?:<d>.*?</d>|.+?)(?=\s+At\s+00:|$)",
            rf"\1{tag_block}",
            text,
            count=1,
            flags=re.I | re.DOTALL,
        )
    return f"{text.rstrip()} {tag_block}"


def enforce_shot_dialogue_timing(shot: dict[str, Any], *, baseline_dialogue: str | None = None) -> bool:
    """Keep dialogue complete, extend durationSec, and sync promptText <d> tags."""
    baseline = normalize_dialogue(baseline_dialogue or shot.get("dialogue")).strip()
    current = normalize_dialogue(shot.get("dialogue")).strip()
    prompt_line = extract_dialogue_from_prompt(str(shot.get("promptText") or ""))

    full = baseline
    for candidate in (current, prompt_line):
        if not candidate:
            continue
        if baseline and is_dialogue_truncated(candidate, baseline):
            continue
        if len(candidate) > len(full):
            full = candidate
    if baseline and (not full or is_dialogue_truncated(full, baseline)):
        full = baseline

    if not full:
        return False

    changed = False
    if current != full:
        shot["dialogue"] = full
        changed = True

    action_beats = count_prompt_action_beats(str(shot.get("promptText") or ""))
    recommended = estimate_shot_duration_sec(full, action_beats=action_beats)
    duration = snap_h3_duration_sec(shot.get("durationSec") or 5)
    if duration < recommended:
        shot["durationSec"] = recommended
        note = f"对白需完整说完，时长 {duration}s→{recommended}s"
        existing = str(shot.get("timingNote") or "").strip()
        shot["timingNote"] = f"{existing}；{note}" if existing else note
        changed = True

    prompt = str(shot.get("promptText") or "")
    new_prompt = replace_dialogue_in_prompt(prompt, full)
    if new_prompt != prompt:
        shot["promptText"] = new_prompt
        changed = True
    return changed


def enforce_recipe_shot_dialogue_timing(recipe: dict[str, Any]) -> int:
    fixed = 0
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if isinstance(shot, dict) and enforce_shot_dialogue_timing(shot):
                fixed += 1
    return fixed


def dialogue_timing_warning(dialogue: str, duration_sec: Any, *, action_beats: int = 1) -> str | None:
    try:
        duration = max(2, min(15, int(round(float(duration_sec)))))
    except (TypeError, ValueError):
        duration = 5
    text = (dialogue or "").strip()
    if not text:
        return None
    recommended = estimate_shot_duration_sec(text, action_beats=action_beats)
    if recommended <= duration:
        return None
    han = count_han_characters(text)
    if han:
        return f"对白约 {han} 字，建议时长 ≥ {recommended}s（当前 {duration}s）"
    return f"对白偏长，建议时长 ≥ {recommended}s（当前 {duration}s）"
