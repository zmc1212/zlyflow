"""按集规划可出片镜头：prompt、JSON 归一化、单镜时长夹取到 5–15 秒。"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

SHOT_DURATION_MIN_SEC = 5
SHOT_DURATION_MAX_SEC = 15
DEFAULT_SHOT_DURATION_SEC = 8
SHOTS_SOURCE_LLM = "llm"
AI_PIPELINE_INPUT_MODE = "ai_pipeline"

SHOT_TEXT_FIELDS = (
    "title",
    "scene",
    "action",
    "camera",
    "dialogue",
    "visual_prompt",
    "audio",
    "subtitle",
    "raw_content",
)
SHOT_LIST_FIELDS = ("characters", "props")
_DURATION_KEYS = ("duration_sec", "duration", "video_duration", "durationSec", "duration_seconds")
_FORBIDDEN_TEMPLATE_TERMS = ("口型", "内心覆盖", "近景定性")


def clamp_shot_duration_sec(
    value: Any,
    *,
    default: int = DEFAULT_SHOT_DURATION_SEC,
) -> int:
    numeric = _parse_duration_number(value)
    if numeric is None:
        numeric = float(default)
    rounded = int(round(numeric))
    return max(SHOT_DURATION_MIN_SEC, min(SHOT_DURATION_MAX_SEC, rounded))


def build_shot_plan_system_prompt() -> str:
    min_sec = SHOT_DURATION_MIN_SEC
    max_sec = SHOT_DURATION_MAX_SEC
    return (
        "你是短剧分镜导演，只根据【这一集】已经写好的动作和对白，规划 MiniMax H3 可出片镜头列表。"
        "集数已由程序按「# 第N集」切好，禁止增删、合并或改集号。"
        f"每条镜头必须是 {min_sec}–{max_sec} 的整数秒；一条片子演不完动作或对白就拆成下一条，"
        f"短于 {min_sec} 秒的相邻节拍必须合并，不要留下不够起片的碎镜。"
        "剧本里已有的「### 镜头」只是素材（动作、对白、场景、人物），不是必须遵守的镜数。"
        f"能一镜拍完就只出一条；只有 {max_sec} 秒拍不下，或同一时间里调度互斥（例如必须换机位才能看清下一拍）时才加镜。"
        f"禁止用「{' / '.join(_FORBIDDEN_TEMPLATE_TERMS)}」这类关键词模板去拆镜；不要因为有开口、内心或推近就固定拆成三条。"
        "不发明剧情、人名、道具或台词。台词可以拆到不同镜，但必须从原文逐字截取，不得改写、概括或补词。"
        "只返回 JSON 对象，不要 markdown，不要解释。格式严格为："
        '{"shots":[{"title":"...","characters":["..."],"scene":"...","props":["..."],'
        '"action":"...","camera":"...","dialogue":"...","audio":"...","subtitle":"...",'
        '"visual_prompt":"...","duration_sec":8}]}'
        "shot_num 由程序重排，不要返回 episode_num。duration_sec 必须是整数。"
    )


def build_shot_plan_user_prompt(episode: dict[str, Any]) -> str:
    episode_num = episode.get("episode_num")
    title = str(episode.get("title") or "").strip() or "未命名"
    summary = str(episode.get("summary") or "").strip() or "（无）"
    source = episode_source_text(episode)
    parsed_shots = [
        _compact_source_shot(item)
        for item in (episode.get("shots") or [])
        if isinstance(item, dict)
    ]
    parsed_json = json.dumps(parsed_shots, ensure_ascii=False, indent=2)
    return (
        f"本集集号：{episode_num if episode_num is not None else '（未知）'}\n"
        f"本集标题：{title}\n"
        f"剧情摘要：{summary}\n\n"
        "本集原文（只读，按这里的动作和对白规划出片镜）：\n"
        f"{source or '（无正文）'}\n\n"
        "解析器已抽出的镜头字段（仅作素材，不是必须遵守的镜数）：\n"
        f"{parsed_json}\n\n"
        f"请输出本集可出片 shots。单镜 {SHOT_DURATION_MIN_SEC}–{SHOT_DURATION_MAX_SEC} 整数秒。"
        "不要改集号，不要发明台词。"
    )


def episode_source_text(episode: dict[str, Any]) -> str:
    body = str(episode.get("body") or "").strip()
    if body:
        return body
    return render_episode_source_markdown(episode)


def render_episode_source_markdown(episode: dict[str, Any]) -> str:
    lines: list[str] = []
    number = episode.get("episode_num") or 1
    title = str(episode.get("title") or "").strip()
    header = f"# 第{number}集 {title}".rstrip()
    lines.append(header)
    summary = str(episode.get("summary") or "").strip()
    if summary:
        lines.append(f"剧情：{summary}")
    for index, shot in enumerate(episode.get("shots") or [], start=1):
        if not isinstance(shot, dict):
            continue
        shot_num = shot.get("shot_num") or index
        shot_title = str(shot.get("title") or f"镜头 {shot_num}").strip()
        lines.append("")
        lines.append(f"### 镜头 {shot_num}｜{shot_title}")
        characters = _as_name_list(shot.get("characters"))
        if characters:
            lines.append(f"- 人物：{'、'.join(characters)}")
        scene = str(shot.get("scene") or "").strip()
        if scene:
            lines.append(f"- 场景：{scene}")
        props = _as_name_list(shot.get("props"))
        if props:
            lines.append(f"- 道具：{'、'.join(props)}")
        duration = shot.get("duration_sec")
        if duration not in (None, ""):
            lines.append(f"- 时长：{duration}秒")
        for label, key in (
            ("动作", "action"),
            ("运镜", "camera"),
            ("台词", "dialogue"),
            ("音效", "audio"),
            ("字幕", "subtitle"),
            ("提示词", "visual_prompt"),
        ):
            value = str(shot.get(key) or "").strip()
            if value:
                lines.append(f"- {label}：{value}")
    return "\n".join(lines).strip()


def parse_shot_plan_response(raw: str) -> list[dict[str, Any]]:
    payload = _loads_json(raw)
    return _shots_from_payload(payload)


def normalize_planned_shots(planned: Any) -> list[dict[str, Any]]:
    items = [_blank_shot(item) for item in _shots_from_payload(planned)]
    items = [item for item in items if _shot_has_content(item)]
    items = merge_short_adjacent_shots(items)
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        shot = _blank_shot(item)
        shot["shot_num"] = index
        if not str(shot.get("title") or "").strip():
            shot["title"] = f"镜头 {index}"
        shot["duration_sec"] = clamp_shot_duration_sec(shot.get("duration_sec"))
        shot.pop("episode_num", None)
        normalized.append(shot)
    return normalized


def merge_short_adjacent_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not shots:
        return []
    merged: list[dict[str, Any]] = [dict(shots[0])]
    for item in shots[1:]:
        current = dict(item)
        previous = merged[-1]
        prev_duration = _parse_duration_number(previous.get("duration_sec"))
        current_duration = _parse_duration_number(current.get("duration_sec"))
        if (
            prev_duration is not None
            and current_duration is not None
            and prev_duration < SHOT_DURATION_MIN_SEC
            and current_duration < SHOT_DURATION_MIN_SEC
            and (prev_duration + current_duration) <= SHOT_DURATION_MAX_SEC
        ):
            merged[-1] = _combine_shots(previous, current)
            continue
        merged.append(current)
    if len(merged) >= 2:
        last_duration = _parse_duration_number(merged[-1].get("duration_sec"))
        prev_duration = _parse_duration_number(merged[-2].get("duration_sec"))
        if (
            last_duration is not None
            and last_duration < SHOT_DURATION_MIN_SEC
            and prev_duration is not None
            and (prev_duration + last_duration) <= SHOT_DURATION_MAX_SEC
        ):
            merged[-2] = _combine_shots(merged[-2], merged[-1])
            merged.pop()
    return merged


def is_ai_pipeline_document(input_mode: Any) -> bool:
    return str(input_mode or "").strip().lower() == AI_PIPELINE_INPUT_MODE


def needs_episode_shot_plan(episode: Any, *, input_mode: Any = "") -> bool:
    if is_ai_pipeline_document(input_mode):
        return False
    if not isinstance(episode, dict):
        return False
    return str(episode.get("shots_source") or "").strip().lower() != SHOTS_SOURCE_LLM


def shot_plan_episode_indexes(analysis: Any, *, input_mode: Any = "") -> list[int]:
    if is_ai_pipeline_document(input_mode) or not isinstance(analysis, dict):
        return []
    indexes: list[int] = []
    for index, episode in enumerate(analysis.get("episodes") or []):
        if needs_episode_shot_plan(episode, input_mode=input_mode):
            indexes.append(index)
    return indexes


def document_needs_shot_plan(analysis: Any, *, input_mode: Any = "") -> bool:
    return bool(shot_plan_episode_indexes(analysis, input_mode=input_mode))


def apply_episode_shot_plan(episode: dict[str, Any], planned: Any) -> dict[str, Any]:
    """用规划结果覆盖本集 shots；空结果回退解析器镜头，且不改 episode_num。"""
    result = copy.deepcopy(episode) if isinstance(episode, dict) else {}
    episode_num = episode.get("episode_num") if isinstance(episode, dict) else None
    shots = normalize_planned_shots(planned)
    if not shots:
        result["episode_num"] = episode_num
        return result
    result["shots"] = shots
    result["shots_count"] = len(shots)
    result["shots_source"] = SHOTS_SOURCE_LLM
    result["episode_num"] = episode_num
    return result


def _blank_shot(item: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = item if isinstance(item, dict) else {}
    shot: dict[str, Any] = {
        "shot_num": raw.get("shot_num") or 0,
        "title": str(raw.get("title") or "").strip(),
        "characters": _as_name_list(raw.get("characters")),
        "scene": str(raw.get("scene") or "").strip(),
        "props": _as_name_list(raw.get("props")),
        "action": str(raw.get("action") or "").strip(),
        "camera": str(raw.get("camera") or "").strip(),
        "dialogue": str(raw.get("dialogue") or "").strip(),
        "visual_prompt": str(raw.get("visual_prompt") or "").strip(),
        "audio": str(raw.get("audio") or "").strip(),
        "subtitle": str(raw.get("subtitle") or "").strip(),
        "duration_sec": _first_duration_value(raw),
        "raw_content": str(raw.get("raw_content") or "").strip(),
    }
    return shot


def _shot_has_content(shot: dict[str, Any]) -> bool:
    if any(str(shot.get(key) or "").strip() for key in SHOT_TEXT_FIELDS):
        return True
    return any(shot.get(key) for key in SHOT_LIST_FIELDS)


def _combine_shots(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    combined = _blank_shot(left)
    right_shot = _blank_shot(right)
    if not combined["title"]:
        combined["title"] = right_shot["title"]
    combined["characters"] = _unique_join(combined["characters"], right_shot["characters"])
    if not combined["scene"]:
        combined["scene"] = right_shot["scene"]
    combined["props"] = _unique_join(combined["props"], right_shot["props"])
    for key in ("action", "camera", "dialogue", "visual_prompt", "audio", "subtitle", "raw_content"):
        combined[key] = _join_text(combined.get(key), right_shot.get(key))
    left_duration = _parse_duration_number(left.get("duration_sec")) or 0.0
    right_duration = _parse_duration_number(right.get("duration_sec")) or 0.0
    combined["duration_sec"] = left_duration + right_duration
    return combined


def _join_text(left: Any, right: Any) -> str:
    first = str(left or "").strip()
    second = str(right or "").strip()
    if not first:
        return second
    if not second:
        return first
    if second in first:
        return first
    if first in second:
        return second
    return f"{first} {second}".strip()


def _unique_join(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        for item in group:
            token = str(item or "").strip()
            if not token or token in seen:
                continue
            seen.add(token)
            result.append(token)
    return result


def _as_name_list(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[、,，/|]+", value)
        return [part.strip() for part in parts if part.strip()]
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            token = str(item or "").strip()
            if token:
                result.append(token)
        return result
    return []


def _first_duration_value(item: dict[str, Any]) -> Any:
    for key in _DURATION_KEYS:
        if key in item and item.get(key) not in (None, ""):
            return item.get(key)
    return None


def _parse_duration_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric != numeric or numeric in {float("inf"), float("-inf")}:
            return None
        return numeric
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    if not match:
        return None
    return float(match.group(1))


def _compact_source_shot(shot: dict[str, Any]) -> dict[str, Any]:
    compact = _blank_shot(shot)
    if compact["duration_sec"] is None:
        compact.pop("duration_sec", None)
    if not compact["raw_content"]:
        compact.pop("raw_content", None)
    return compact


def _shots_from_payload(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("shots", "takes", "items"):
        items = value.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    nested = value.get("data")
    if nested is not None and nested is not value:
        return _shots_from_payload(nested)
    if _shot_has_content(_blank_shot(value)) or _first_duration_value(value) is not None:
        return [value]
    return []


def _loads_json(raw: str) -> Any | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```.*$", "", text, flags=re.S)
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
    return None
