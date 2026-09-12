from __future__ import annotations

import json
import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from .director_catalog import art_style_ref_for_recipe, find_art_style, list_art_styles
from .director_compiler import compile_recipe_media, snap_h3_duration_sec
from .director_recipe import (
    AGENT_IDS,
    PIPELINE_AGENT_ORDER,
    default_audio_mix,
    empty_recipe_payload,
    normalize_dialogue,
    normalize_recipe_payload,
    normalize_voice_id,
    set_agent_status,
    split_display_and_prompt,
    sync_dialogue_prompt,
)
from .director_stream import AGENT_STREAM_SPECS, AgentStreamTracker
from .llm_client import (
    LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
    LlmBillingError,
    LlmError,
    LlmTemporaryError,
    OpenAICompatibleClient,
    is_llm_timeout_error,
    is_upstream_llm_failure,
    looks_like_llm_billing,
    repair_utf8_mojibake,
)
from .dialogue_timing import (
    assign_missing_script_dialogue,
    enforce_recipe_shot_dialogue_timing,
    enforce_shot_dialogue_timing,
    is_dialogue_truncated,
    script_dialogue_coverage_low,
)
from .llm_minimax_skills import (
    build_h3_batch_fission_prompt,
    build_h3_storyboard_agent_prompt,
    build_script_agent_prompt,
    build_shot_timing_polish_prompt,
    build_storyboard_continuity_repair_prompt,
    build_storyboard_continuity_polish_prompt,
)


ChatFn = Callable[[list[dict[str, Any]]], str]


class DirectorChatFn:
    """Callable chat wrapper that can report streamed bytes without changing ChatFn tests."""

    def __init__(self, client: OpenAICompatibleClient, model: str) -> None:
        self._client = client
        self._model = model
        self.on_chunk: Callable[[str], None] | None = None

    def __call__(self, messages: list[dict[str, Any]]) -> str:
        return self._client.chat_completion(
            messages,
            model=self._model,
            temperature=0.6,
            max_tokens=8192,
            timeout=LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
            stream=True,
            on_chunk=self.on_chunk,
        )


RESEARCH_HINTS = (
    "品牌", "公司", "真实事件", "历史", "纪录片", "据实", "史实", "知名",
    "IP", "改编", "wikipedia", "Wikipedia", "事实", "传记",
)
CAMERA_SCALES = {"ELS", "WS", "MS", "CU", "ECU"}
CAMERA_MOVEMENTS = {
    "zoom_in", "zoom_out", "pan_left", "pan_right", "tilt_up", "tilt_down",
    "orbit", "tracking", "static",
}
CAMERA_ANGLES = {"eye_level", "low_angle", "high_angle", "dutch", "pov"}
CAMERA_SPEEDS = {"smooth", "dynamic", "slow"}
CAMERA_LIGHTING = {
    "cinematic_soft", "cyberpunk", "golden_hour", "dramatic_low_key", "studio",
}

AGENT_LABELS = {
    "research": "研究",
    "script": "脚本",
    "art_style": "美术风格",
    "storyboard": "分镜",
    "characters": "角色",
    "locations": "场景",
    "voice": "配音",
    "music": "配乐",
    "media": "媒体",
}


def _repair_truncated_json(snippet: str) -> str:
    in_string = False
    escape = False
    stack: list[str] = []
    for character in snippet:
        if in_string:
            if escape:
                escape = False
            elif character == "\\":
                escape = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
            continue
        if character == "{":
            stack.append("}")
        elif character == "[":
            stack.append("]")
        elif character in "}]":
            if stack and stack[-1] == character:
                stack.pop()
    repaired = snippet.rstrip()
    if in_string:
        repaired += '"'
    repaired = repaired.rstrip().rstrip(",")
    while stack:
        repaired += stack.pop()
    return repaired


def _strip_json_fences(raw: str) -> str:
    clean_text = (raw or "").strip()
    if "```json" in clean_text:
        clean_text = clean_text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in clean_text:
        clean_text = clean_text.split("```", 1)[1].split("```", 1)[0].strip()
    return clean_text


def _loads_json_fragment(snippet: str) -> Any | None:
    last_close = max(snippet.rfind("}"), snippet.rfind("]"))
    candidates = []
    if last_close > 0:
        candidates.append(snippet[: last_close + 1])
    candidates.append(_repair_truncated_json(snippet))
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def parse_json_payload(raw: str) -> dict[str, Any] | list[Any] | None:
    clean_text = _strip_json_fences(raw)
    if not clean_text:
        return None
    brace = clean_text.find("{")
    bracket = clean_text.find("[")
    starts = [index for index in (brace, bracket) if index >= 0]
    if not starts:
        return None
    parsed = _loads_json_fragment(clean_text[min(starts):])
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def parse_json_object(raw: str) -> dict[str, Any] | None:
    parsed = parse_json_payload(raw)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        coerced = coerce_storyboard_data(parsed)
        return coerced if coerced else None
    return None


def should_run_research(goal: str) -> bool:
    text = goal or ""
    return any(marker in text for marker in RESEARCH_HINTS)


def score_art_style(goal: str, style: dict[str, Any]) -> int:
    haystack = (goal or "").casefold()
    if not haystack:
        return 0
    score = 0
    for keyword in style.get("keywords") or []:
        token = str(keyword or "").strip()
        if token and token.casefold() in haystack:
            score += 2
    for token in (style.get("name_zh"), style.get("name_en"), style.get("category_name_zh")):
        text = str(token or "").strip()
        if text and text.casefold() in haystack:
            score += 3
    return score


def pick_art_style_from_catalog(goal: str, preferred: Any = None) -> dict[str, str]:
    found = find_art_style(preferred) if preferred not in (None, "", {}) else None
    if found is not None:
        return art_style_ref_for_recipe(found)
    styles = list_art_styles()
    ranked = sorted(styles, key=lambda item: score_art_style(goal, item), reverse=True)
    chosen = ranked[0] if ranked and score_art_style(goal, ranked[0]) > 0 else next(
        (item for item in styles if item["id"] == "as_1001"),
        styles[0],
    )
    return art_style_ref_for_recipe(chosen)


def default_chat_fn(client: OpenAICompatibleClient, model: str) -> ChatFn:
    return DirectorChatFn(client, model)


def _make_agent_tracker(agent_id: str, on_stream: Callable[[dict[str, Any]], None] | None) -> AgentStreamTracker | None:
    """Build the display stream tracker for an agent, or None when streaming is off."""
    spec = AGENT_STREAM_SPECS.get(agent_id)
    if spec is None or on_stream is None:
        return None
    return AgentStreamTracker(spec, on_stream)


def _attach_agent_tracker(tracker: AgentStreamTracker | None, chat_fn: ChatFn | None) -> None:
    if tracker is not None and chat_fn is not None and hasattr(chat_fn, "on_chunk"):
        chat_fn.on_chunk = tracker.feed


def _finish_agent_tracker(tracker: AgentStreamTracker | None, parsed: Any) -> None:
    if tracker is not None:
        tracker.finish(parsed if isinstance(parsed, dict) else None)


def _clarified_goal_text(goal: str, clarifications: Any) -> str:
    """Append user-confirmed creative directions to the script agent input."""
    rows: list[str] = []
    if isinstance(clarifications, list):
        for item in clarifications:
            if not isinstance(item, dict):
                continue
            question = _text(item.get("question"))
            answer = _text(item.get("answer") or item.get("value"))
            if question and answer:
                rows.append(f"- {question} → {answer}")
    if not rows:
        return goal
    return goal + "\n\n创作方向确认（用户已选定，剧本必须遵循这些决定）：\n" + "\n".join(rows)


def _clarified_beat_target(clarifications: Any) -> int | None:
    """User-confirmed shot/beat count from the clarify answers; None keeps the default script scale."""
    if not isinstance(clarifications, list):
        return None
    for item in clarifications:
        if not isinstance(item, dict):
            continue
        question = _text(item.get("question"))
        matched = _text(item.get("id")) == "beat_count" or (
            "镜头" in question and any(token in question.lower() for token in ("beat", "数量", "多少"))
        )
        if not matched:
            continue
        answer = _text(item.get("answer") or item.get("value"))
        range_match = re.search(r"(\d+)\s*[-~～—至到]\s*(\d+)", answer)
        if range_match:
            value = (int(range_match.group(1)) + int(range_match.group(2))) // 2
        else:
            number_match = re.search(r"\d+", answer)
            if not number_match:
                continue
            value = int(number_match.group())
        return min(120, max(3, value))
    return None


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = repair_utf8_mojibake(str(value).strip())
    return text or fallback


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _chat_text(chat_fn: ChatFn, messages: list[dict[str, Any]], *, retries: int = 1) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            raw = chat_fn(messages)
        except LlmTemporaryError as error:
            last_error = error
            if is_llm_timeout_error(error) or attempt >= retries:
                break
            continue
        except LlmError:
            raise
        if (raw or "").strip():
            return raw
        last_error = ValueError("大模型未返回内容")
    if isinstance(last_error, LlmError):
        raise last_error
    return ""


def _chat_json(chat_fn: ChatFn, messages: list[dict[str, Any]], *, retries: int = 1) -> dict[str, Any] | None:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            raw = chat_fn(messages)
        except LlmTemporaryError as error:
            last_error = error
            if is_llm_timeout_error(error) or attempt >= retries:
                break
            continue
        except LlmError:
            raise
        parsed = parse_json_payload(raw)
        if isinstance(parsed, list):
            parsed = coerce_storyboard_data(parsed)
        if isinstance(parsed, dict):
            return parsed
        last_error = ValueError("大模型未返回合法 JSON")
    if isinstance(last_error, LlmError):
        raise last_error
    return None


def _system(agent_id: str, body: str) -> str:
    return f"AGENT_ID: {agent_id}\n{body}\n必须且仅输出一个合法 JSON 对象，不要解释。"


def _camera(raw: Any) -> dict[str, str]:
    item = raw if isinstance(raw, dict) else {}
    scale = _text(item.get("scale"), "MS")
    movement = _text(item.get("movement"), "zoom_in")
    angle = _text(item.get("angle"), "eye_level")
    speed = _text(item.get("speed"), "smooth")
    lighting = _text(item.get("lighting"), "cinematic_soft")
    return {
        "scale": scale if scale in CAMERA_SCALES else "MS",
        "movement": movement if movement in CAMERA_MOVEMENTS else "zoom_in",
        "angle": angle if angle in CAMERA_ANGLES else "eye_level",
        "speed": speed if speed in CAMERA_SPEEDS else "smooth",
        "lighting": lighting if lighting in CAMERA_LIGHTING else "cinematic_soft",
        "sfx": _text(item.get("sfx")),
    }


STORYBOARD_MAX_SCENES = 16
STORYBOARD_MAX_SHOTS_PER_SCENE = 8
STORYBOARD_MAX_TOTAL_SHOTS = 32
STORYBOARD_RETRY_SYSTEM = (
    "只输出一个 JSON 对象或镜头数组。把用户故事一次性拆成可独立提交 MiniMax H3 的全部镜头。"
    "每镜 title/description/soundscape 用中文；soundscapeEn, promptText, continuityIn 与 continuityOut 必须用纯英文，只写一个从 00:00 开始的 [Shot 1] 片段。"
    "<d> 仅用于实际可听见的台词或歌词；屏幕/招牌/手机上的可见文字必须以英文叙述描述，禁止包进 <d>。"
    "剧本里每条对白（含自言自语、旁白）必须写入对应镜头的 dialogue，并与同时发生的动作放在同一镜，禁止无对白建立镜头。"
    "覆盖全部剧情，通常 8–24 镜。禁止只输出 1 个主镜头，禁止输出 integrated_multimodal_description 顶层格式。"
    '优先输出 {"scenes":[{"title":"","locationName":"","shots":[{"title":"","description":"","promptText":"","dialogue":"","characterNames":[],"locationName":"","durationSec":5,"camera":{},"soundscape":"","soundscapeEn":""}]}]}'
)


def _apply_script(recipe: dict[str, Any], data: dict[str, Any], goal: str) -> None:
    script = recipe.setdefault("script", {})
    script["title"] = _text(data.get("title"), script.get("title") or goal[:24] or "未命名短片")
    script["summary"] = _text(data.get("summary"), script.get("summary") or goal)
    script["fullStory"] = _text(data.get("fullStory") or data.get("full_story"), script.get("fullStory") or goal)


def _looks_like_shot(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return bool(
        item.get("title") or item.get("description") or item.get("promptText")
        or item.get("prompt_text") or item.get("prompt") or item.get("dialogue")
        or item.get("shots")
    )


def _collect_storyboard_scenes(data: dict[str, Any]) -> list[Any]:
    for key in ("scenes", "storyboard", "shot_list", "shotList", "clips", "shots", "items", "镜头", "分镜"):
        value = data.get(key)
        if not isinstance(value, list) or not value:
            continue
        dict_items = [item for item in value if isinstance(item, dict)]
        if not dict_items:
            continue
        if key == "scenes" or all(isinstance(item.get("shots"), list) for item in dict_items):
            return dict_items
        if any(_looks_like_shot(item) for item in dict_items):
            return [{"title": "第一场", "shots": dict_items}]
    return []


def coerce_storyboard_data(value: Any, *, depth: int = 0) -> dict[str, Any]:
    if depth > 5:
        return {}
    if isinstance(value, list) and value:
        dict_items = [item for item in value if isinstance(item, dict)]
        if dict_items and all(isinstance(item.get("shots"), list) for item in dict_items):
            return {"scenes": dict_items}
        if dict_items and any(_looks_like_shot(item) for item in dict_items):
            return {"shots": dict_items}
        return {}
    if not isinstance(value, dict):
        return {}
    if _collect_storyboard_scenes(value):
        return value
    for key in ("data", "result", "payload", "output", "recipe", "content", "json", "storyboard"):
        inner = value.get(key)
        if inner is None:
            continue
        coerced = coerce_storyboard_data(inner, depth=depth + 1)
        if _collect_storyboard_scenes(coerced):
            return coerced
    if _looks_like_shot(value) and not isinstance(value.get("shots"), list):
        return {"shots": [value]}
    return value


def _storyboard_shot_count(data: dict[str, Any] | None) -> int:
    if not isinstance(data, dict):
        return 0
    count = 0
    for scene in _collect_storyboard_scenes(data):
        scene_item = scene if isinstance(scene, dict) else {}
        shots_raw = scene_item.get("shots")
        if not isinstance(shots_raw, list) or not shots_raw:
            shots_raw = [scene_item] if scene_item else []
        count += sum(1 for item in shots_raw if isinstance(item, dict))
    return count


def _is_collapsed_storyboard(data: dict[str, Any] | None, goal: str) -> bool:
    if not isinstance(data, dict):
        return True
    data = coerce_storyboard_data(data)
    scenes = _collect_storyboard_scenes(data)
    shots: list[dict[str, Any]] = []
    for scene in scenes:
        scene_item = scene if isinstance(scene, dict) else {}
        shots_raw = scene_item.get("shots")
        if not isinstance(shots_raw, list) or not shots_raw:
            shots_raw = [scene_item] if scene_item else []
        shots.extend(item for item in shots_raw if isinstance(item, dict))
    if len(shots) >= 2:
        return False
    if not shots:
        return True
    shot = shots[0]
    title = _text(shot.get("title"))
    description = _text(shot.get("description") or shot.get("promptText") or shot.get("prompt"))
    goal_text = _text(goal)
    dummy_title = title in {"", "主镜头", "开场", "分镜 1", "分镜1"}
    dummy_body = (not description) or description == goal_text
    return dummy_title and dummy_body


def _shots_from_prose(raw: str, goal: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return []
    chunks = re.split(r"\[Shot\s*\d+\]", text, flags=re.IGNORECASE)
    bodies = [chunk.strip().strip("-•* ").strip() for chunk in chunks[1:] if chunk.strip()]
    if len(bodies) < 2:
        numbered = re.split(r"(?:^|\n)\s*(?:镜头|分镜)\s*\d+[:.、.]\s*", text)
        bodies = [chunk.strip() for chunk in numbered[1:] if chunk.strip()]
    if len(bodies) < 2:
        return []
    shots: list[dict[str, Any]] = []
    for index, body in enumerate(bodies[:STORYBOARD_MAX_TOTAL_SHOTS], start=1):
        excerpt = body.split("\n")[0][:80]
        description, prompt_text = split_display_and_prompt(
            title=f"分镜 {index}",
            description=excerpt if any("\u4e00" <= ch <= "\u9fff" for ch in excerpt) else "",
            prompt_text=body[:1800],
            fallback_zh=excerpt or f"分镜 {index}",
        )
        shots.append({
            "title": f"分镜 {index}",
            "description": description,
            "promptText": prompt_text,
            "dialogue": "",
            "characterNames": [],
            "locationName": "",
            "durationSec": 5,
        })
    return shots


def _parse_storyboard_reply(raw: str, goal: str) -> dict[str, Any]:
    parsed = parse_json_payload(raw)
    data = coerce_storyboard_data(parsed) if parsed is not None else {}
    if not _is_collapsed_storyboard(data, goal):
        return data
    prose_shots = _shots_from_prose(raw, goal)
    if len(prose_shots) >= 2:
        return {"shots": prose_shots}
    return data


def _recipe_shot_count(recipe: dict[str, Any]) -> int:
    count = 0
    for scene in recipe.get("scenes") or []:
        if isinstance(scene, dict):
            count += sum(1 for shot in scene.get("shots") or [] if isinstance(shot, dict))
    return count


def _flatten_recipe_shots(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    shots: list[dict[str, Any]] = []
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if isinstance(shot, dict):
                shots.append(shot)
    return shots


def _continuity_coverage_gaps(recipe: dict[str, Any]) -> list[str]:
    """Return human-readable gaps after the Seedance-inspired continuity pass."""
    shots = _flatten_recipe_shots(recipe)
    if len(shots) < 2:
        return []
    gaps: list[str] = []
    for index, shot in enumerate(shots):
        number = shot.get("shotNumber") or index + 1
        if index > 0 and not _text(shot.get("continuityIn") or shot.get("continuity_in")):
            gaps.append(f"第{number}镜缺少 continuityIn")
        if index < len(shots) - 1 and not _text(shot.get("continuityOut") or shot.get("continuity_out")):
            gaps.append(f"第{number}镜缺少 continuityOut")
        if index < len(shots) - 1 and not _text(shot.get("transitionNote") or shot.get("transition_note")):
            gaps.append(f"第{number}镜缺少 transitionNote")
    return gaps


CONTINUITY_PATCH_FIELDS = (
    "promptText",
    "continuityIn",
    "continuityOut",
    "transitionNote",
    "soundscape",
    "soundscapeEn",
)


def _overlapping_continuity_windows(
    shots: list[dict[str, Any]], *, size: int = 5, overlap: int = 1,
) -> list[dict[str, Any]]:
    """Build windows where every adjacent cut is visible in one LLM request.

    The first shot of subsequent windows is read-only context. With a window
    size of five and one-shot overlap, shots 5 and 6 are deliberately sent
    together instead of being split at the old chunk boundary.
    """
    if not shots:
        return []
    size = max(2, int(size))
    overlap = max(1, min(int(overlap), size - 1))
    windows: list[dict[str, Any]] = []
    start = 0
    while start < len(shots):
        end = min(len(shots), start + size)
        context_count = 0 if start == 0 else overlap
        context = shots[start:start + context_count]
        editable = shots[start + context_count:end]
        if not editable:
            break
        window_shots = context + editable
        windows.append({
            "shots": window_shots,
            "contextShotNumbers": [int(item.get("shotNumber") or 0) for item in context],
            "editableShotNumbers": [int(item.get("shotNumber") or 0) for item in editable],
            "windowShotNumbers": [int(item.get("shotNumber") or 0) for item in window_shots],
        })
        if end >= len(shots):
            break
        start = end - overlap
    return windows


def _storyboard_shot_items(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return items
    for scene in _collect_storyboard_scenes(coerce_storyboard_data(data)):
        scene_item = scene if isinstance(scene, dict) else {}
        shots_raw = scene_item.get("shots")
        if not isinstance(shots_raw, list) or not shots_raw:
            shots_raw = [scene_item] if scene_item else []
        items.extend(item for item in shots_raw if isinstance(item, dict))
    return items


def _apply_continuity_patch(
    recipe: dict[str, Any],
    data: dict[str, Any],
    *,
    editable_shot_numbers: list[int],
    window_shot_numbers: list[int],
) -> tuple[bool, str]:
    """Apply only continuity-owned fields after validating the model response."""
    items = _storyboard_shot_items(data)
    if not items:
        return False, "连续性响应没有返回镜头"
    allowed = set(window_shot_numbers)
    editable = set(editable_shot_numbers)
    seen: set[int] = set()
    updates: dict[int, dict[str, Any]] = {}
    errors: list[str] = []
    for item in items:
        raw_number = item.get("shotNumber") or item.get("shot_number")
        try:
            number = int(raw_number)
        except (TypeError, ValueError):
            errors.append("返回镜头缺少有效 shotNumber")
            continue
        if number in seen:
            errors.append(f"第{number}镜重复返回")
            continue
        seen.add(number)
        if number not in allowed:
            errors.append(f"返回了窗口外的第{number}镜")
            continue
        updates[number] = item
    missing = sorted(editable - seen)
    if missing:
        errors.append("缺少可编辑镜头：" + ", ".join(f"第{number}镜" for number in missing))
    if errors:
        return False, "；".join(errors)

    recipe_by_number = {
        int(shot.get("shotNumber") or 0): shot
        for shot in _flatten_recipe_shots(recipe)
        if isinstance(shot, dict)
    }
    for number in editable_shot_numbers:
        shot = recipe_by_number.get(number)
        patch = updates.get(number)
        if not shot or not patch:
            continue
        for field in CONTINUITY_PATCH_FIELDS:
            aliases = (field, re.sub(r"([A-Z])", lambda match: "_" + match.group(1).lower(), field))
            source_key = next((key for key in aliases if key in patch), None)
            if source_key is None:
                continue
            value = _text(patch.get(source_key))
            if field == "promptText":
                if value:
                    # promptText is editable for visual continuity, but its
                    # dialogue tag remains sourced from the locked dialogue
                    # field so this pass cannot invent or rewrite speech.
                    shot[field] = sync_dialogue_prompt(value, shot.get("dialogue"))
            elif value:
                shot[field] = value
            else:
                shot[field] = ""
    return True, ""


def _continuity_tokens(value: Any) -> set[str]:
    text = _text(value).casefold()
    tokens: set[str] = set(re.findall(r"[a-z][a-z0-9_-]{2,}", text))
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(segment) >= 2:
            tokens.add(segment)
            tokens.update(segment[index:index + 2] for index in range(len(segment) - 1))
    return tokens - {
        "the", "and", "with", "from", "into", "this", "that", "continues",
        "continue", "雨声", "雨夜", "声音", "光线", "场景",
    }


def _continuity_prompt_opening(prompt: Any) -> str:
    text = _text(prompt)
    text = re.sub(r"^\s*\[Shot\s+\d+\]\s*", "", text, flags=re.IGNORECASE)
    match = re.search(r"\bAt\s+00:00(?:\.\d{1,3})?\s*,?\s*", text, flags=re.IGNORECASE)
    if match:
        text = text[match.end():]
    first_cut = re.search(r"\bAt\s+00:\d{2}(?:\.\d{1,3})?\s*,?\s*", text, flags=re.IGNORECASE)
    if first_cut:
        text = text[:first_cut.start()]
    return text[:420]


def _shot_field_tokens(shot: dict[str, Any], fields: tuple[str, ...]) -> set[str]:
    tokens: set[str] = set()
    for field in fields:
        value = shot.get(field)
        values = value if isinstance(value, list) else [value]
        for item in values:
            tokens.update(_continuity_tokens(item))
    return tokens


def _state_keywords(value: Any, keywords: tuple[str, ...]) -> set[str]:
    text = _text(value).casefold()
    return {keyword for keyword in keywords if keyword.casefold() in text}


_CONTINUITY_STATE_KEYWORDS = {
    "天气": ("rain", "rainy", "snow", "snowy", "fog", "mist", "wind", "storm", "雨", "雪", "雾", "风", "雷"),
    "时间": ("dawn", "morning", "noon", "afternoon", "evening", "dusk", "night", "midnight", "黎明", "清晨", "白天", "午后", "傍晚", "黄昏", "夜", "深夜"),
    "光线": ("sunlight", "moonlight", "daylight", "backlight", "neon", "candlelight", "明亮", "昏暗", "阳光", "月光", "霓虹", "烛光"),
}


def validate_continuity_pairs(recipe: dict[str, Any]) -> dict[str, Any]:
    """Run a conservative, deterministic QA pass over adjacent shot handoffs."""
    shots = _flatten_recipe_shots(recipe)
    pairs: list[dict[str, Any]] = []
    issues: list[str] = []
    for index in range(max(0, len(shots) - 1)):
        current = shots[index]
        following = shots[index + 1]
        from_number = int(current.get("shotNumber") or index + 1)
        to_number = int(following.get("shotNumber") or index + 2)
        pair_issues: list[str] = []
        transition = _text(following.get("transitionNote") or current.get("transitionNote"))
        hard_cut = bool(re.search(r"硬切|hard\s*cut|time\s*jump|location\s*jump", transition, re.I))
        current_location = _text(current.get("locationName") or current.get("locationId"))
        next_location = _text(following.get("locationName") or following.get("locationId"))
        if not _text(current.get("continuityOut")):
            pair_issues.append(f"第{from_number}镜缺少 continuityOut")
        if not _text(following.get("continuityIn")):
            pair_issues.append(f"第{to_number}镜缺少 continuityIn")
        if not transition:
            pair_issues.append(f"第{to_number}镜缺少 transitionNote")
        if current_location and next_location and current_location != next_location and not hard_cut:
            pair_issues.append(f"第{from_number}镜到第{to_number}镜场景变化未标记硬切")
        if not hard_cut:
            current_characters = _shot_field_tokens(current, ("characterNames", "characterBindings"))
            next_characters = _shot_field_tokens(following, ("characterNames", "characterBindings"))
            if current_characters and next_characters and not current_characters.intersection(next_characters):
                pair_issues.append(f"第{from_number}镜到第{to_number}镜人物锚点明显跳变")
            current_props = _shot_field_tokens(current, ("propNames", "propIds"))
            next_props = _shot_field_tokens(following, ("propNames", "propIds"))
            if current_props and next_props and not current_props.intersection(next_props):
                pair_issues.append(f"第{from_number}镜到第{to_number}镜道具锚点明显跳变")
            outgoing_state = _text(current.get("continuityOut"))
            incoming_state = _text(following.get("continuityIn"))
            opening_prompt = _continuity_prompt_opening(following.get("promptText"))
            for state_name, keywords in _CONTINUITY_STATE_KEYWORDS.items():
                outgoing_keywords = _state_keywords(outgoing_state, keywords)
                incoming_keywords = _state_keywords(incoming_state or opening_prompt, keywords)
                if outgoing_keywords and incoming_keywords and not outgoing_keywords.intersection(incoming_keywords):
                    pair_issues.append(f"第{from_number}镜到第{to_number}镜{state_name}状态明显跳变")
            outgoing_tokens = _continuity_tokens(current.get("continuityOut"))
            incoming_tokens = _continuity_tokens(following.get("continuityIn"))
            if outgoing_tokens and incoming_tokens and len(outgoing_tokens & incoming_tokens) == 0:
                pair_issues.append(f"第{from_number}镜出镜状态与第{to_number}镜入镜状态没有共同锚点")
            opening_tokens = _continuity_tokens(opening_prompt)
            if incoming_tokens and opening_tokens and len(incoming_tokens & opening_tokens) == 0:
                pair_issues.append(f"第{to_number}镜开场动作未体现入镜状态")
            transition_lower = transition.casefold()
            if re.search(r"动作匹配|action\s*match", transition_lower):
                if outgoing_tokens and opening_tokens and not outgoing_tokens.intersection(opening_tokens):
                    pair_issues.append(f"第{to_number}镜 transitionNote 标记动作匹配但实际动作不相连")
            if re.search(r"声音桥接|sound\s*bridge", transition_lower):
                outgoing_sound = _continuity_tokens(
                    f"{_text(current.get('soundscape'))} {_text(current.get('soundscapeEn'))} {outgoing_state}"
                )
                incoming_sound = _continuity_tokens(
                    f"{_text(following.get('soundscape'))} {_text(following.get('soundscapeEn'))} {incoming_state}"
                )
                if outgoing_sound and incoming_sound and not outgoing_sound.intersection(incoming_sound):
                    pair_issues.append(f"第{to_number}镜标记声音桥接但前后声音状态不相连")
        pair_status = "warning" if pair_issues else "passed"
        reason = "；".join(pair_issues)
        same_scene = not (current_location and next_location and current_location != next_location)
        visual_anchor = "none" if hard_cut else ("recommended" if same_scene and not pair_issues else "review")
        visual_anchor_reason = ("明确硬切场景，不继承上一镜尾帧" if hard_cut else
                                "同场景且连续性通过，建议使用上一镜尾帧" if visual_anchor == "recommended" else
                                "存在衔接风险，确认修复后再决定是否使用上一镜尾帧")
        pairs.append({
            "fromShot": from_number,
            "toShot": to_number,
            "status": pair_status,
            "reason": reason,
            "issues": list(pair_issues),
            "visualAnchor": visual_anchor,
            "visualAnchorReason": visual_anchor_reason,
        })
        issues.extend(pair_issues)
    return {"status": "warning" if issues else "passed", "issues": issues, "pairs": pairs}


CONTINUITY_REPAIR_FIELDS = (
    "promptText",
    "continuityIn",
    "continuityOut",
    "transitionNote",
    "soundscape",
    "soundscapeEn",
)
CONTINUITY_REPAIR_FROM_FIELDS = (
    "continuityOut",
    "transitionNote",
    "soundscape",
    "soundscapeEn",
)


def _continuity_shot_brief(shot: dict[str, Any]) -> dict[str, Any]:
    """Keep the repair request focused on creative facts, not execution state."""
    return {
        "shotNumber": shot.get("shotNumber"),
        "title": _text(shot.get("title")),
        "description": _text(shot.get("description")),
        "promptText": _text(shot.get("promptText")),
        "dialogue": normalize_dialogue(shot.get("dialogue")),
        "characterNames": list(_list(shot.get("characterNames"))),
        "characterBindings": list(_list(shot.get("characterBindings"))),
        "locationName": _text(shot.get("locationName")),
        "locationId": _text(shot.get("locationId")) or None,
        "propIds": list(_list(shot.get("propIds"))),
        "propNames": list(_list(shot.get("propNames"))),
        "durationSec": shot.get("durationSec"),
        "camera": deepcopy(shot.get("camera") or {}),
        "soundscape": _text(shot.get("soundscape")),
        "soundscapeEn": _text(shot.get("soundscapeEn")),
        "continuityIn": _text(shot.get("continuityIn")),
        "continuityOut": _text(shot.get("continuityOut")),
        "transitionNote": _text(shot.get("transitionNote")),
    }


def _continuity_repair_payload(
    recipe: dict[str, Any],
    qa_pairs: list[dict[str, Any]],
    *,
    limit: int = 8,
) -> tuple[dict[str, Any], list[tuple[int, int]]]:
    """Build a bounded repair request from the latest deterministic QA result."""
    shots = _flatten_recipe_shots(recipe)
    by_number: dict[int, dict[str, Any]] = {}
    for index, shot in enumerate(shots):
        try:
            number = int(shot.get("shotNumber") or index + 1)
        except (TypeError, ValueError):
            number = index + 1
        by_number[number] = shot

    requested: list[tuple[int, int]] = []
    pairs: list[dict[str, Any]] = []
    for raw_pair in qa_pairs:
        if not isinstance(raw_pair, dict) or raw_pair.get("status") != "warning":
            continue
        try:
            from_number = int(raw_pair.get("fromShot"))
            to_number = int(raw_pair.get("toShot"))
        except (TypeError, ValueError):
            continue
        current = by_number.get(from_number)
        following = by_number.get(to_number)
        if current is None or following is None or (from_number, to_number) in requested:
            continue
        requested.append((from_number, to_number))
        raw_issues = raw_pair.get("issues")
        if isinstance(raw_issues, list):
            issues = [_text(item) for item in raw_issues if _text(item)]
        else:
            reason = _text(raw_pair.get("reason"))
            issues = [reason] if reason else []
        pairs.append({
            "fromShot": from_number,
            "toShot": to_number,
            "issues": issues,
            "fromShotData": _continuity_shot_brief(current),
            "toShotData": _continuity_shot_brief(following),
        })
        if len(pairs) >= max(1, int(limit)):
            break

    script = recipe.get("script") if isinstance(recipe.get("script"), dict) else {}
    payload = {
        "storyContext": _text(script.get("fullStory"))[:8000],
        "pairs": pairs,
    }
    return payload, requested


def _patch_value(patch: dict[str, Any], field: str) -> tuple[bool, str]:
    snake = re.sub(r"([A-Z])", lambda match: "_" + match.group(1).lower(), field)
    for key in (field, snake):
        if key in patch:
            return True, _text(patch.get(key))
    return False, ""


def _apply_continuity_repair(
    recipe: dict[str, Any],
    data: dict[str, Any],
    *,
    requested_pairs: list[tuple[int, int]],
) -> tuple[int, list[str], list[dict[str, int]]]:
    """Apply a causal repair response without allowing creative-field drift."""
    repairs = data.get("repairs") if isinstance(data, dict) else None
    if not isinstance(repairs, list):
        return 0, ["连续性修复响应缺少 repairs 数组"], []

    shots = _flatten_recipe_shots(recipe)
    by_number: dict[int, dict[str, Any]] = {}
    for index, shot in enumerate(shots):
        try:
            number = int(shot.get("shotNumber") or index + 1)
        except (TypeError, ValueError):
            number = index + 1
        by_number[number] = shot

    allowed_pairs = set(requested_pairs)
    seen_pairs: set[tuple[int, int]] = set()
    errors: list[str] = []
    applied = 0
    resplit_required: list[dict[str, int]] = []
    validated_repairs: list[tuple[dict[str, Any], int, int, str, dict[str, Any], dict[str, Any]]] = []

    def apply_patch(
        shot: dict[str, Any],
        patch: Any,
        *,
        fields: tuple[str, ...],
        shot_number: int,
    ) -> bool:
        if not isinstance(patch, dict):
            return False
        changed = False
        for field in fields:
            present, value = _patch_value(patch, field)
            if not present or not value:
                continue
            if field in {"continuityIn", "continuityOut", "soundscapeEn"} and re.search(r"[\u4e00-\u9fff]", value):
                errors.append(f"第{shot_number}镜修复字段 {field} 不是纯英文，已忽略")
                continue
            if field == "promptText":
                _display, normalized_prompt = split_display_and_prompt(
                    title=_text(shot.get("title")),
                    description="",
                    prompt_text=value,
                    fallback_zh=_text(shot.get("description"), _text(shot.get("title"))),
                )
                if normalized_prompt:
                    shot[field] = sync_dialogue_prompt(normalized_prompt, shot.get("dialogue"))
                    changed = True
            else:
                shot[field] = value
                changed = True
        if changed and "promptText" in fields:
            dialogue = normalize_dialogue(shot.get("dialogue"), speaker_names=[_text(name) for name in _list(shot.get("characterNames"))])
            shot["dialogue"] = dialogue
            shot["promptText"] = sync_dialogue_prompt(shot.get("promptText"), dialogue)
            enforce_shot_dialogue_timing(shot, baseline_dialogue=dialogue)
        return changed

    for raw_repair in repairs:
        if not isinstance(raw_repair, dict):
            errors.append("连续性修复包含非对象项")
            continue
        try:
            from_number = int(raw_repair.get("fromShot") or raw_repair.get("from_shot"))
            to_number = int(raw_repair.get("toShot") or raw_repair.get("to_shot"))
        except (TypeError, ValueError):
            errors.append("连续性修复缺少有效 fromShot/toShot")
            continue
        key = (from_number, to_number)
        if key not in allowed_pairs:
            errors.append(f"连续性修复返回了未请求的边界：第{from_number}镜→第{to_number}镜")
            continue
        if key in seen_pairs:
            errors.append(f"连续性修复重复返回边界：第{from_number}镜→第{to_number}镜")
            continue
        seen_pairs.add(key)
        current = by_number.get(from_number)
        following = by_number.get(to_number)
        if current is None or following is None:
            errors.append(f"连续性修复找不到边界镜头：第{from_number}镜→第{to_number}镜")
            continue

        status = _text(raw_repair.get("status"), "repaired").casefold()
        if status in {"needs_resplit", "resplit", "需要重拆"}:
            resplit_required.append({"fromShot": from_number, "toShot": to_number})
        validated_repairs.append((raw_repair, from_number, to_number, status, current, following))

    missing = [pair for pair in requested_pairs if pair not in seen_pairs]
    if missing:
        errors.append("连续性修复缺少边界：" + "、".join(f"第{a}镜→第{b}镜" for a, b in missing))
    # Structural errors reject the complete response before any patch is
    # applied, matching the atomic behavior of the continuity-window pass.
    if errors:
        return 0, errors, resplit_required

    for raw_repair, from_number, to_number, status, current, following in validated_repairs:
        current_patch = raw_repair.get("fromShotPatch") or raw_repair.get("from_shot_patch")
        target_patch = (
            raw_repair.get("toShotPatch")
            or raw_repair.get("to_shot_patch")
            or raw_repair.get("patch")
        )
        changed = apply_patch(
            current,
            current_patch,
            fields=CONTINUITY_REPAIR_FROM_FIELDS,
            shot_number=from_number,
        )
        changed = apply_patch(
            following,
            target_patch,
            fields=CONTINUITY_REPAIR_FIELDS,
            shot_number=to_number,
        ) or changed
        if changed:
            applied += 1
        elif status not in {"needs_resplit", "resplit", "需要重拆"}:
            errors.append(f"第{from_number}镜→第{to_number}镜没有可应用的修复字段")
    return applied, errors, resplit_required


def _recipe_assigned_dialogue_count(recipe: dict[str, Any]) -> int:
    count = 0
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if isinstance(shot, dict) and normalize_dialogue(shot.get("dialogue")).strip():
                count += 1
    return count


def _story_script_text(recipe: dict[str, Any], goal: str) -> str:
    script = recipe.get("script") if isinstance(recipe.get("script"), dict) else {}
    return _text(script.get("fullStory"), goal)


def _storyboard_dialogue_coverage_low(recipe: dict[str, Any], goal: str) -> bool:
    return script_dialogue_coverage_low(
        _story_script_text(recipe, goal),
        _recipe_assigned_dialogue_count(recipe),
    )


def _apply_script_dialogue_fallback(recipe: dict[str, Any], goal: str) -> int:
    return assign_missing_script_dialogue(recipe, _story_script_text(recipe, goal))


def _apply_storyboard(recipe: dict[str, Any], data: dict[str, Any], goal: str) -> None:
    data = coerce_storyboard_data(data)
    scenes_raw = _collect_storyboard_scenes(data)
    scenes: list[dict[str, Any]] = []
    shot_number = 1
    for scene_index, scene_raw in enumerate(scenes_raw[:STORYBOARD_MAX_SCENES]):
        if shot_number > STORYBOARD_MAX_TOTAL_SHOTS:
            break
        scene_item = scene_raw if isinstance(scene_raw, dict) else {}
        shots_raw = scene_item.get("shots")
        if not isinstance(shots_raw, list) or not shots_raw:
            shots_raw = [scene_item] if _text(scene_item.get("title") or scene_item.get("description") or scene_item.get("promptText")) else []
        shots: list[dict[str, Any]] = []
        for shot_raw in shots_raw[:STORYBOARD_MAX_SHOTS_PER_SCENE]:
            if shot_number > STORYBOARD_MAX_TOTAL_SHOTS:
                break
            item = shot_raw if isinstance(shot_raw, dict) else {}
            names = item.get("characterNames") or item.get("character_names") or []
            bindings = item.get("characterBindings") or item.get("character_bindings") or []
            prop_ids = item.get("propIds") or item.get("prop_ids") or []
            prop_names = item.get("propNames") or item.get("prop_names") or []
            title = _text(item.get("title"), f"分镜 {shot_number}")
            description, prompt_text = split_display_and_prompt(
                title=title,
                description=_text(item.get("description"), goal if not _text(item.get("promptText") or item.get("prompt")) else ""),
                prompt_text=_text(item.get("promptText") or item.get("prompt_text") or item.get("prompt")),
                fallback_zh=title,
            )
            shots.append({
                "title": title,
                "description": description,
                "promptText": prompt_text,
                "dialogue": normalize_dialogue(item.get("dialogue"), speaker_names=[_text(name) for name in _list(names)]),
                "characterNames": [_text(name) for name in _list(names) if _text(name)],
                "characterBindings": [binding for binding in _list(bindings) if isinstance(binding, dict)],
                "locationName": _text(item.get("locationName") or item.get("location_name") or scene_item.get("locationName")),
                "locationId": _text(item.get("locationId") or item.get("location_id")) or None,
                "propIds": [_text(prop_id) for prop_id in _list(prop_ids) if _text(prop_id)],
                "propNames": [_text(name) for name in _list(prop_names) if _text(name)],
                "durationSec": snap_h3_duration_sec(item.get("durationSec") or item.get("duration_sec") or 5),
                "camera": _camera(item.get("camera")),
                "soundscape": _text(item.get("soundscape") or item.get("sfx")),
                "soundscapeEn": _text(item.get("soundscapeEn") or item.get("soundscape_en")),
                "timingNote": _text(item.get("timingNote") or item.get("timing_note")),
                "continuityIn": _text(item.get("continuityIn") or item.get("continuity_in")),
                "continuityOut": _text(item.get("continuityOut") or item.get("continuity_out")),
                "transitionNote": _text(item.get("transitionNote") or item.get("transition_note")),
                "status": "idle",
                "shotNumber": shot_number,
            })
            shot_number += 1
        if not shots:
            continue
        scenes.append({
            "title": _text(scene_item.get("title"), f"场 {scene_index + 1}"),
            "description": _text(scene_item.get("description")),
            "locationName": _text(scene_item.get("locationName") or scene_item.get("location_name")),
            "shots": shots,
        })
    recipe["scenes"] = scenes


def _recipe_shots_timing_payload(recipe: dict[str, Any]) -> dict[str, Any]:
    scenes: list[dict[str, Any]] = []
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        shots: list[dict[str, Any]] = []
        for shot in scene.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            shots.append({
                "shotNumber": shot.get("shotNumber"),
                "title": _text(shot.get("title")),
                "description": _text(shot.get("description")),
                "promptText": _text(shot.get("promptText")),
                "dialogue": normalize_dialogue(
                    shot.get("dialogue"),
                    speaker_names=[
                        *[_text(name) for name in _list(shot.get("characterNames"))],
                        *([_text(shot.get("speakerName"))] if _text(shot.get("speakerName")) else []),
                    ],
                ),
                "characterNames": list(shot.get("characterNames") or []),
                "characterBindings": list(shot.get("characterBindings") or []),
                "locationName": _text(shot.get("locationName")),
                "locationId": _text(shot.get("locationId")) or None,
                "propIds": list(shot.get("propIds") or []),
                "propNames": list(shot.get("propNames") or []),
                "durationSec": snap_h3_duration_sec(shot.get("durationSec") or 5),
                "camera": shot.get("camera") if isinstance(shot.get("camera"), dict) else {},
                "soundscape": _text(shot.get("soundscape")),
                "soundscapeEn": _text(shot.get("soundscapeEn")),
                "timingNote": _text(shot.get("timingNote") or shot.get("timing_note")),
                "continuityIn": _text(shot.get("continuityIn") or shot.get("continuity_in")),
                "continuityOut": _text(shot.get("continuityOut") or shot.get("continuity_out")),
                "transitionNote": _text(shot.get("transitionNote") or shot.get("transition_note")),
            })
        if not shots:
            continue
        scenes.append({
            "title": _text(scene.get("title")),
            "description": _text(scene.get("description")),
            "locationName": _text(scene.get("locationName")),
            "shots": shots,
        })
    return {"scenes": scenes}


def _apply_shot_timing_polish(recipe: dict[str, Any], data: dict[str, Any]) -> None:
    data = coerce_storyboard_data(data)
    scenes_raw = _collect_storyboard_scenes(data)
    if not scenes_raw:
        return
    updates_by_number: dict[int, dict[str, Any]] = {}
    shot_number = 1
    for scene_raw in scenes_raw:
        if shot_number > STORYBOARD_MAX_TOTAL_SHOTS:
            break
        scene_item = scene_raw if isinstance(scene_raw, dict) else {}
        shots_raw = scene_item.get("shots")
        if not isinstance(shots_raw, list) or not shots_raw:
            shots_raw = [scene_item] if _text(scene_item.get("title") or scene_item.get("description") or scene_item.get("promptText")) else []
        for shot_raw in shots_raw:
            if shot_number > STORYBOARD_MAX_TOTAL_SHOTS:
                break
            if isinstance(shot_raw, dict):
                actual_num = shot_raw.get("shotNumber") or shot_raw.get("shot_number")
                try:
                    key = int(actual_num) if actual_num is not None else shot_number
                except (TypeError, ValueError):
                    key = shot_number
                updates_by_number[key] = shot_raw
            shot_number += 1
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            try:
                number = int(shot.get("shotNumber") or 0)
            except (TypeError, ValueError):
                continue
            patch = updates_by_number.get(number)
            if not patch:
                continue
            speaker_names = [_text(name) for name in _list(shot.get("characterNames"))]
            original_dialogue = normalize_dialogue(shot.get("dialogue"), speaker_names=speaker_names).strip()
            if patch.get("durationSec") is not None:
                shot["durationSec"] = snap_h3_duration_sec(patch.get("durationSec"))
            if patch.get("dialogue") is not None:
                patch_dialogue = normalize_dialogue(patch.get("dialogue"), speaker_names=speaker_names)
                if original_dialogue and is_dialogue_truncated(patch_dialogue, original_dialogue):
                    shot["dialogue"] = original_dialogue
                else:
                    shot["dialogue"] = patch_dialogue
            prompt_text = _text(patch.get("promptText") or patch.get("prompt_text"))
            description = _text(patch.get("description"))
            if prompt_text or description:
                display_text, normalized_prompt = split_display_and_prompt(
                    title=_text(shot.get("title")),
                    description=description,
                    prompt_text=prompt_text,
                    fallback_zh=_text(shot.get("description"), _text(shot.get("title"))),
                )
                if description:
                    shot["description"] = display_text
                if prompt_text or normalized_prompt:
                    shot["promptText"] = normalized_prompt
            soundscape = _text(patch.get("soundscape"))
            if soundscape:
                shot["soundscape"] = soundscape
            soundscape_en = _text(patch.get("soundscapeEn") or patch.get("soundscape_en"))
            if soundscape_en:
                shot["soundscapeEn"] = soundscape_en
            timing_note = _text(patch.get("timingNote") or patch.get("timing_note"))
            if timing_note:
                shot["timingNote"] = timing_note
            continuity_in = _text(patch.get("continuityIn") or patch.get("continuity_in"))
            if continuity_in:
                shot["continuityIn"] = continuity_in
            continuity_out = _text(patch.get("continuityOut") or patch.get("continuity_out"))
            if continuity_out:
                shot["continuityOut"] = continuity_out
            transition_note = _text(patch.get("transitionNote") or patch.get("transition_note"))
            if transition_note:
                shot["transitionNote"] = transition_note
            enforce_shot_dialogue_timing(shot, baseline_dialogue=original_dialogue or shot.get("dialogue"))


def _normalize_recipe_dialogue_fields(recipe: dict[str, Any]) -> None:
    """Normalize model-added speaker labels and keep H3 dialogue tags in sync."""
    for shot in _flatten_recipe_shots(recipe):
        speaker_names = [_text(name) for name in _list(shot.get("characterNames"))]
        speaker_name = _text(shot.get("speakerName") or shot.get("speaker_name"))
        if speaker_name:
            speaker_names.append(speaker_name)
        dialogue = normalize_dialogue(shot.get("dialogue"), speaker_names=speaker_names).strip()
        shot["dialogue"] = dialogue
        prompt_base = shot.get("promptText") or shot.get("description")
        shot["promptText"] = sync_dialogue_prompt(prompt_base, dialogue)
        enforce_shot_dialogue_timing(shot, baseline_dialogue=dialogue)


def _apply_characters(recipe: dict[str, Any], data: dict[str, Any]) -> None:
    names_from_board: list[str] = []
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if isinstance(shot, dict):
                for name in shot.get("characterNames") or []:
                    text = str(name).strip()
                    if text and text not in names_from_board:
                        names_from_board.append(text)
    incoming = data.get("characters")
    items = incoming if isinstance(incoming, list) else []
    existing_characters = {
        _text(item.get("name")).casefold(): deepcopy(item)
        for item in _list(recipe.get("characters"))
        if isinstance(item, dict) and _text(item.get("name"))
    }
    by_name: dict[str, dict[str, Any]] = {}
    props_from_characters: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        name = _text(raw.get("name"))
        if not name:
            continue
        char_type = _text(raw.get("type"), "character")
        if char_type not in {"character", "object"}:
            char_type = "object" if char_type in {"prop", "道具"} else "character"
        description, prompt_text = split_display_and_prompt(
            title=name,
            description=_text(raw.get("description")),
            prompt_text=_text(raw.get("promptText") or raw.get("prompt_text") or raw.get("description")),
            fallback_zh=name,
        )
        existing = existing_characters.get(name.casefold(), {})
        incoming_looks = raw.get("looks") if isinstance(raw.get("looks"), list) else [{
            "id": "look-default",
            "name": "基础造型",
            "appearanceDetails": _text(raw.get("appearanceDetails") or raw.get("appearance_details") or description),
            "promptText": prompt_text,
            "status": "draft",
        }]
        existing_looks = {
            _text(look.get("id") or look.get("name")).casefold(): look
            for look in _list(existing.get("looks"))
            if isinstance(look, dict) and _text(look.get("id") or look.get("name"))
        }
        merged_looks = []
        for look_index, look in enumerate(incoming_looks):
            if not isinstance(look, dict):
                continue
            look_key = _text(look.get("id") or look.get("name") or ("look-default" if look_index == 0 else "")).casefold()
            merged_looks.append({
                **deepcopy(existing_looks.get(look_key, {})),
                **look,
                "id": _text(look.get("id"), "look-default" if look_index == 0 else ""),
                "status": "draft",
            })
        raw_identity_spec = raw.get("identitySpec") or raw.get("identity_spec")
        identity_spec = raw_identity_spec if isinstance(raw_identity_spec, dict) and raw_identity_spec else existing.get("identitySpec") or {}
        raw_assumptions = raw.get("aiAssumptions") or raw.get("ai_assumptions")
        ai_assumptions = raw_assumptions if isinstance(raw_assumptions, list) else existing.get("aiAssumptions") or []
        target = {
            **existing,
            "name": name,
            "description": description,
            "promptText": prompt_text or _text(raw.get("promptText") or raw.get("prompt_text") or raw.get("description")),
            "role": _text(raw.get("role")),
            "gender": _text(raw.get("gender"), "unspecified") or "unspecified",
            "type": char_type,
            "identitySpec": identity_spec,
            "specStatus": "draft" if raw_identity_spec else existing.get("specStatus") or "draft",
            "aiAssumptions": ai_assumptions,
            "looks": merged_looks,
            "voiceId": normalize_voice_id(raw.get("voiceId") or raw.get("voice_id"), gender=_text(raw.get("gender"), "unspecified")),
        }
        if char_type == "object":
            props_from_characters.append(target)
            continue
        by_name[name] = target
    ordered_names = list(by_name.keys())
    for name in names_from_board:
        if name not in ordered_names:
            ordered_names.append(name)
    characters: list[dict[str, Any]] = []
    for name in ordered_names:
        if name in by_name:
            characters.append(by_name[name])
        else:
            preserved = existing_characters.get(name.casefold())
            characters.append(preserved or {
                "name": name,
                "description": name,
                "promptText": f"consistent character named {name}, identity portrait and production character sheet",
                "gender": "unspecified",
                "type": "character",
            })
    if characters or items:
        recipe["characters"] = characters

    existing_props = {
        _text(item.get("name")).casefold(): deepcopy(item)
        for item in _list(recipe.get("props"))
        if isinstance(item, dict) and _text(item.get("name"))
    }
    prop_items = [item for item in _list(data.get("props")) if isinstance(item, dict)] + props_from_characters
    props: list[dict[str, Any]] = []
    for raw in prop_items:
        name = _text(raw.get("name"))
        if not name:
            continue
        description, prompt_text = split_display_and_prompt(
            title=name,
            description=_text(raw.get("description")),
            prompt_text=_text(raw.get("promptText") or raw.get("prompt_text") or raw.get("description")),
            fallback_zh=name,
        )
        props.append({
            **existing_props.get(name.casefold(), {}),
            "name": name,
            "description": description,
            "promptText": prompt_text,
        })
    if prop_items:
        recipe["props"] = props


def _apply_locations(recipe: dict[str, Any], data: dict[str, Any]) -> None:
    names: list[str] = []
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        loc = _text(scene.get("locationName"))
        if loc and loc not in names:
            names.append(loc)
        for shot in scene.get("shots") or []:
            if isinstance(shot, dict):
                loc = _text(shot.get("locationName"))
                if loc and loc not in names:
                    names.append(loc)
    incoming = data.get("locations")
    items = incoming if isinstance(incoming, list) else []
    existing_locations = {
        _text(item.get("name")).casefold(): deepcopy(item)
        for item in _list(recipe.get("locations"))
        if isinstance(item, dict) and _text(item.get("name"))
    }
    by_name: dict[str, dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        name = _text(raw.get("name"))
        if not name:
            continue
        description, prompt_text = split_display_and_prompt(
            title=name,
            description=_text(raw.get("description")),
            prompt_text=_text(raw.get("promptText") or raw.get("prompt_text") or raw.get("description")),
            fallback_zh=name,
        )
        by_name[name] = {
            **existing_locations.get(name.casefold(), {}),
            "name": name,
            "description": description,
            "promptText": prompt_text or _text(raw.get("promptText") or raw.get("prompt_text") or raw.get("description")),
        }
    ordered = list(by_name.keys())
    for name in names:
        if name not in ordered:
            ordered.append(name)
    locations: list[dict[str, Any]] = []
    for name in ordered:
        if name in by_name:
            locations.append(by_name[name])
        else:
            locations.append({
                "name": name,
                "description": name,
                "promptText": f"empty establishing shot of {name}, no people, cinematic environment",
            })
    if locations or items:
        recipe["locations"] = locations


def _apply_voice(recipe: dict[str, Any], data: dict[str, Any]) -> None:
    char_voices: dict[str, str] = {}
    for item in _list(data.get("characters")):
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        voice = _text(item.get("voiceId") or item.get("voice_id"))
        if name and voice:
            char_voices[name] = voice
    for character in recipe.get("characters") or []:
        if not isinstance(character, dict):
            continue
        name = _text(character.get("name"))
        if name in char_voices:
            character["voiceId"] = char_voices[name]
        else:
            character["voiceId"] = normalize_voice_id(
                character.get("voiceId"), gender=_text(character.get("gender")),
            )

    mapping: dict[str, dict[str, str]] = {}
    for item in _list(data.get("shots")):
        if not isinstance(item, dict):
            continue
        meta = {
            "dialogue": _text(item.get("dialogue")),
            "speakerName": _text(item.get("speakerName") or item.get("speaker_name")),
        }
        key = _text(item.get("id") or item.get("title") or item.get("shotNumber") or item.get("shot_number"))
        if key:
            mapping[key] = meta
        number = item.get("shotNumber") or item.get("shot_number")
        if number is not None:
            mapping[str(number)] = meta
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            key_id = _text(shot.get("id"))
            key_title = _text(shot.get("title"))
            key_number = str(shot.get("shotNumber") or "")
            meta = mapping.get(key_id) or mapping.get(key_number) or mapping.get(key_title)
            if not meta:
                continue
            shot["dialogue"] = meta["dialogue"]
            if meta["speakerName"]:
                shot["speakerName"] = meta["speakerName"]
            speaker = _text(shot.get("speakerName"))
            if speaker and speaker in char_voices:
                shot["voiceId"] = char_voices[speaker]


def _apply_music(recipe: dict[str, Any], data: dict[str, Any]) -> None:
    recipe["globalMusic"] = _text(data.get("globalMusic") or data.get("global_music"), recipe.get("globalMusic") or "")
    soundscape = _text(data.get("globalSoundscape") or data.get("global_soundscape"))
    if soundscape:
        recipe["globalSoundscape"] = soundscape
    audio = recipe.get("audio") if isinstance(recipe.get("audio"), dict) else default_audio_mix()
    if data.get("bgmVolume") is not None or data.get("bgm_volume") is not None:
        try:
            audio["bgmVolume"] = max(0.0, min(1.0, float(data.get("bgmVolume", data.get("bgm_volume")))))
        except (TypeError, ValueError):
            pass
    if data.get("bgmFadeInSec") is not None or data.get("bgm_fade_in_sec") is not None:
        try:
            audio["bgmFadeInSec"] = max(0.0, min(15.0, float(data.get("bgmFadeInSec", data.get("bgm_fade_in_sec")))))
        except (TypeError, ValueError):
            pass
    if data.get("bgmFadeOutSec") is not None or data.get("bgm_fade_out_sec") is not None:
        try:
            audio["bgmFadeOutSec"] = max(0.0, min(15.0, float(data.get("bgmFadeOutSec", data.get("bgm_fade_out_sec")))))
        except (TypeError, ValueError):
            pass
    recipe["audio"] = audio
    sfx_map: dict[str, str] = {}
    for item in _list(data.get("shotSfx") or data.get("shot_sfx")):
        if not isinstance(item, dict):
            continue
        sfx = _text(item.get("sfx") or item.get("soundscape"))
        number = item.get("shotNumber") or item.get("shot_number")
        if number is not None and sfx:
            sfx_map[str(number)] = sfx
    if not sfx_map:
        return
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            sfx = sfx_map.get(str(shot.get("shotNumber") or ""))
            if sfx:
                shot["soundscape"] = sfx


def _story_context(recipe: dict[str, Any], goal: str) -> str:
    script = recipe.get("script") or {}
    art = recipe.get("artStyle") if isinstance(recipe.get("artStyle"), dict) else {}
    style_line = ""
    if art:
        style_line = (
            f"画风：{art.get('name') or art.get('name_zh') or ''}"
            f"（{art.get('nameEn') or art.get('name_en') or ''}）。"
            f"画面前缀：{art.get('promptPrefix') or art.get('prompt_prefix') or ''}\n"
        )
    notes = _text(recipe.get("researchNotes"))
    notes_line = f"研究备注：{notes}\n" if notes else ""
    return (
        f"用户一句话：{goal}\n"
        f"标题：{script.get('title') or ''}\n"
        f"梗概：{script.get('summary') or ''}\n"
        f"故事：{script.get('fullStory') or goal}\n"
        f"{style_line}{notes_line}"
    )


def _storyboard_asset_context(recipe: dict[str, Any]) -> str:
    characters: list[dict[str, Any]] = []
    for character in _list(recipe.get("characters")):
        if not isinstance(character, dict):
            continue
        looks = [
            {"id": _text(look.get("id")), "name": _text(look.get("name"))}
            for look in _list(character.get("looks"))
            if isinstance(look, dict) and _text(look.get("id"))
        ]
        characters.append({
            "id": _text(character.get("id")),
            "name": _text(character.get("name")),
            "looks": looks,
        })
    locations = [
        {"id": _text(item.get("id")), "name": _text(item.get("name"))}
        for item in _list(recipe.get("locations"))
        if isinstance(item, dict) and _text(item.get("id"))
    ]
    props = [
        {"id": _text(item.get("id")), "name": _text(item.get("name"))}
        for item in _list(recipe.get("props"))
        if isinstance(item, dict) and _text(item.get("id"))
    ]
    return json.dumps({"characters": characters, "locations": locations, "props": props}, ensure_ascii=False)


def _split_story_into_scene_texts(full_story: str) -> list[str]:
    import re
    parts = re.split(r"(?=【)", full_story)
    scenes = []
    current_scene = ""
    for part in parts:
        if part.strip().startswith("【"):
            if current_scene.strip():
                scenes.append(current_scene.strip())
            current_scene = part
        else:
            current_scene += part
    if current_scene.strip():
        scenes.append(current_scene.strip())
    return scenes if scenes else [full_story]



def run_agent(
    agent_id: str,
    recipe: dict[str, Any],
    *,
    goal: str,
    chat_fn: ChatFn | None = None,
    art_style_id: str | None = None,
    skip_research: bool | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    on_stream: Callable[[dict[str, Any]], None] | None = None,
    clarifications: Any = None,
) -> dict[str, Any]:
    if agent_id not in AGENT_IDS:
        raise ValueError(f"未知 Agent：{agent_id}")
    recipe = normalize_recipe_payload(deepcopy(recipe) if recipe else empty_recipe_payload())
    set_agent_status(recipe, agent_id, "running")
    if on_progress:
        on_progress(recipe)

    def emit() -> None:
        if on_progress:
            on_progress(recipe)

    try:
        if agent_id == "research":
            skip = should_run_research(goal) is False if skip_research is None else bool(skip_research)
            if skip or chat_fn is None:
                recipe["researchNotes"] = ""
                set_agent_status(recipe, agent_id, "completed", message="无事实核查需求，已跳过")
                return recipe
            tracker = _make_agent_tracker(agent_id, on_stream)
            _attach_agent_tracker(tracker, chat_fn)
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(agent_id, "根据常识摘要用户故事里需要核实的设定。不要编造网址。输出 {\"notes\":\"...\",\"skipped\":false}。无事实需求时 notes 为空、skipped 为 true。")},
                {"role": "user", "content": goal},
            ])
            recipe["researchNotes"] = _text((parsed or {}).get("notes"))
            _finish_agent_tracker(tracker, parsed)
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "script":
            tracker = _make_agent_tracker(agent_id, on_stream)
            _attach_agent_tracker(tracker, chat_fn)
            messages = [
                {"role": "system", "content": _system(agent_id, build_script_agent_prompt(target_beats=_clarified_beat_target(clarifications)))},
                {"role": "user", "content": _clarified_goal_text(goal, clarifications)},
            ]
            parsed = _chat_json(chat_fn, messages) if chat_fn else None
            _apply_script(recipe, parsed or {}, goal)
            _finish_agent_tracker(tracker, parsed)
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "art_style":
            if art_style_id or recipe.get("artStyle"):
                recipe["artStyle"] = pick_art_style_from_catalog(goal, art_style_id or recipe.get("artStyle"))
                set_agent_status(recipe, agent_id, "completed")
                return recipe
            catalog_brief = "\n".join(
                f"{item['id']}\t{item['name_zh']}\t{item['name_en']}\t{','.join(item.get('keywords') or [])}"
                for item in list_art_styles()
            )
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(agent_id, "只能从目录里选一条画风，禁止发明 id 或名称。输出 {\"id\":\"as_1001\"}。\n目录：\n" + catalog_brief)},
                {"role": "user", "content": _story_context(recipe, goal)},
            ]) if chat_fn else None
            preferred = (parsed or {}).get("id") or (parsed or {}).get("name")
            recipe["artStyle"] = pick_art_style_from_catalog(goal, preferred)
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "storyboard":
            script = recipe.get("script") or {}
            full_story = script.get("fullStory") or script.get("content") or goal
            scene_texts = _split_story_into_scene_texts(full_story)
            all_scenes = []
            tracker = _make_agent_tracker(agent_id, on_stream)

            if chat_fn:
                previous_chunk = getattr(chat_fn, "on_chunk", None)

                try:
                    for idx, scene_text in enumerate(scene_texts):
                        msg = f"正在读剧本并构思 ({idx+1}/{len(scene_texts)}) - 剧本较长，AI需阅读约1~2分钟..."
                        set_agent_status(recipe, agent_id, "running", message=msg)
                        try: emit()
                        except: pass
                        
                        original_full = script.get("fullStory")
                        script["fullStory"] = scene_text
                        
                        user_content = (
                            _story_context(recipe, goal)
                            + "\n已建立的资产目录：" + _storyboard_asset_context(recipe)
                            + "\n请根据上面的剧本片段，一次性输出本片段的全部镜头。"
                            + "每个镜头必须从目录选择 characterBindings:[{characterId,lookId}]、locationId 和 propIds；"
                            + "同时保留 characterNames/locationName/propNames 便于人阅读，禁止发明新 ID。"
                            + "剧本每条对白（含自言自语）必须写入对应镜头的 dialogue，与同时发生的动作放在同一镜。"
                            + "拆镜时按 scene ledger 草拟相邻镜的 continuityIn / continuityOut（英文）与 transitionNote（中文）；"
                            + "后续时长与衔接润色会再校准，但不要整表留空。"
                        )
                        
                        if original_full is not None:
                            script["fullStory"] = original_full
                        else:
                            script.pop("fullStory", None)
                            
                        def local_report(accumulated: str) -> None:
                            n = len(accumulated or "")
                            if n > 0:
                                set_agent_status(recipe, agent_id, "running", message=f"正在写分镜 ({idx+1}/{len(scene_texts)}) - 已收 {n} 字")
                                try: emit()
                                except: pass

                        if hasattr(chat_fn, "on_chunk"):
                            if tracker is not None:
                                tracker.begin_call()

                                def combined_report(accumulated: str) -> None:
                                    local_report(accumulated)
                                    tracker.feed(accumulated)

                                chat_fn.on_chunk = combined_report
                            else:
                                chat_fn.on_chunk = local_report

                        raw = _chat_text(chat_fn, [
                            {"role": "system", "content": _system(agent_id, build_h3_storyboard_agent_prompt())},
                            {"role": "user", "content": user_content},
                        ], retries=1)
                        
                        set_agent_status(recipe, agent_id, "running", message=f"正在整理镜头 ({idx+1}/{len(scene_texts)})")
                        try: emit()
                        except: pass
                        parsed = _parse_storyboard_reply(raw, goal)
                        
                        if _is_collapsed_storyboard(parsed, goal):
                            set_agent_status(recipe, agent_id, "running", message=f"镜头不完整，正在重拆 ({idx+1}/{len(scene_texts)})")
                            try: emit()
                            except: pass
                            if tracker is not None and hasattr(chat_fn, "on_chunk"):
                                tracker.begin_call()
                            raw = _chat_text(chat_fn, [
                                {"role": "system", "content": _system(agent_id, STORYBOARD_RETRY_SYSTEM)},
                                {"role": "user", "content": user_content},
                            ], retries=1)
                            parsed = _parse_storyboard_reply(raw, goal)
                            
                        parsed_scenes = _collect_storyboard_scenes(parsed)
                        all_scenes.extend(parsed_scenes)
                finally:
                    if hasattr(chat_fn, "on_chunk"):
                        chat_fn.on_chunk = previous_chunk
            
            _apply_storyboard(recipe, {"scenes": all_scenes}, goal)
            _finish_agent_tracker(tracker, {"scenes": all_scenes})
            _normalize_recipe_dialogue_fields(recipe)
            if _recipe_shot_count(recipe) == 0:
                recipe["scenes"] = []
                set_agent_status(recipe, agent_id, "failed", "分镜未按剧本拆出镜头，请重试生成分镜")
                return recipe
            if _storyboard_dialogue_coverage_low(recipe, goal):
                set_agent_status(recipe, agent_id, "running", message="正在从剧本补全对白")
                emit()
                assigned = _apply_script_dialogue_fallback(recipe, goal)
                if assigned > 0:
                    set_agent_status(
                        recipe,
                        agent_id,
                        "running",
                        message=f"已从剧本补全 {assigned} 条对白",
                    )
                    emit()
            if chat_fn and _recipe_shot_count(recipe) > 0:
                chunk_size = 5
                continuity_window_warnings: list[str] = []
                
                # --- Timing Pass ---
                timing_payload = _recipe_shots_timing_payload(recipe)
                all_shots = [shot for scene in (timing_payload.get("scenes") or []) for shot in (scene.get("shots") or [])]
                chunks = [all_shots[i:i + chunk_size] for i in range(0, len(all_shots), chunk_size)]
                
                previous_chunk = getattr(chat_fn, "on_chunk", None) if chat_fn else None
                try:
                    for i, chunk in enumerate(chunks):
                        set_agent_status(recipe, agent_id, "running", message=f"正在按秒分配对白与动作 ({i+1}/{len(chunks)})")
                        emit()
                        
                        def timing_report(accumulated: str, idx=i) -> None:
                            n = len(accumulated or "")
                            if n > 0:
                                set_agent_status(recipe, agent_id, "running", message=f"正在按秒分配对白与动作 ({idx+1}/{len(chunks)}) - 已收 {n} 字")
                                try: emit()
                                except: pass
                        if hasattr(chat_fn, "on_chunk"):
                            chat_fn.on_chunk = timing_report

                        chunk_payload = {"scenes": [{"shots": chunk}]}
                        timing_raw = _chat_text(chat_fn, [
                            {"role": "system", "content": build_shot_timing_polish_prompt()},
                            {"role": "user", "content": json.dumps(chunk_payload, ensure_ascii=False)},
                        ], retries=1)
                        timing_parsed = _parse_storyboard_reply(timing_raw, goal)
                        if _collect_storyboard_scenes(timing_parsed):
                            _apply_shot_timing_polish(recipe, timing_parsed)
                    
                    # --- Continuity Pass ---
                    cont_payload = _recipe_shots_timing_payload(recipe)
                    all_shots = [shot for scene in (cont_payload.get("scenes") or []) for shot in (scene.get("shots") or [])]
                    continuity_windows = _overlapping_continuity_windows(
                        all_shots,
                        size=chunk_size,
                        overlap=1,
                    )
                    
                    for i, window in enumerate(continuity_windows):
                        set_agent_status(recipe, agent_id, "running", message=f"正在校验镜头衔接 ({i+1}/{len(continuity_windows)})")
                        emit()
                        
                        def cont_report(accumulated: str, idx=i) -> None:
                            n = len(accumulated or "")
                            if n > 0:
                                set_agent_status(recipe, agent_id, "running", message=f"正在校验镜头衔接 ({idx+1}/{len(continuity_windows)}) - 已收 {n} 字")
                                try: emit()
                                except: pass
                        if hasattr(chat_fn, "on_chunk"):
                            chat_fn.on_chunk = cont_report

                        window_payload = {
                            "scenes": [{"shots": window["shots"]}],
                            "contextShotNumbers": window["contextShotNumbers"],
                            "editableShotNumbers": window["editableShotNumbers"],
                        }
                        user_content = json.dumps(window_payload, ensure_ascii=False)
                        patch_applied = False
                        patch_error = ""
                        for attempt in range(2):
                            if attempt:
                                user_content = (
                                    json.dumps(window_payload, ensure_ascii=False)
                                    + "\n上一次响应无效："
                                    + patch_error
                                    + "。请只返回带有正确全局 shotNumber 的合法 JSON，并覆盖全部 editableShotNumbers。"
                                )
                            continuity_raw = _chat_text(chat_fn, [
                                {"role": "system", "content": build_storyboard_continuity_polish_prompt()},
                                {"role": "user", "content": user_content},
                            ], retries=1)
                            continuity_parsed = _parse_storyboard_reply(continuity_raw, goal)
                            patch_applied, patch_error = _apply_continuity_patch(
                                recipe,
                                continuity_parsed,
                                editable_shot_numbers=window["editableShotNumbers"],
                                window_shot_numbers=window["windowShotNumbers"],
                            )
                            if patch_applied:
                                break
                        if not patch_applied:
                            continuity_window_warnings.append(
                                f"连续性窗口 {i + 1} 未应用：{patch_error or '返回格式无效'}"
                            )
                finally:
                    if chat_fn and hasattr(chat_fn, "on_chunk"):
                        chat_fn.on_chunk = previous_chunk
                        
                enforce_recipe_shot_dialogue_timing(recipe)
                _normalize_recipe_dialogue_fields(recipe)
            else:
                continuity_window_warnings = []

            continuity_qa = validate_continuity_pairs(recipe)
            repair_attempted = 0
            repair_applied = 0
            repair_errors: list[str] = []
            resplit_required: list[dict[str, int]] = []
            if chat_fn and continuity_qa.get("status") == "warning":
                repair_payload, requested_pairs = _continuity_repair_payload(
                    recipe,
                    list(continuity_qa.get("pairs") or []),
                )
                repair_attempted = len(requested_pairs)
                if requested_pairs:
                    set_agent_status(
                        recipe,
                        agent_id,
                        "running",
                        message=f"正在修复镜头因果衔接 ({repair_attempted} 处)",
                    )
                    emit()
                    try:
                        repair_raw = _chat_text(chat_fn, [
                            {"role": "system", "content": build_storyboard_continuity_repair_prompt()},
                            {"role": "user", "content": json.dumps(repair_payload, ensure_ascii=False)},
                        ], retries=1)
                        repair_parsed = parse_json_payload(repair_raw)
                        if not isinstance(repair_parsed, dict):
                            repair_errors.append("连续性修复响应不是合法 JSON 对象")
                        else:
                            repair_applied, repair_errors, resplit_required = _apply_continuity_repair(
                                recipe,
                                repair_parsed,
                                requested_pairs=requested_pairs,
                            )
                            _normalize_recipe_dialogue_fields(recipe)
                    except LlmTemporaryError as error:
                        repair_errors.append(f"连续性因果修复暂时未完成：{error}")

            # Re-run the deterministic checks after a repair so the payload
            # records the remaining risk, not the stale pre-repair diagnosis.
            continuity_qa = validate_continuity_pairs(recipe)
            if continuity_window_warnings:
                continuity_qa["status"] = "warning"
                continuity_qa["issues"] = list(continuity_qa.get("issues") or []) + continuity_window_warnings
            if repair_errors:
                continuity_qa["status"] = "warning"
                continuity_qa["issues"] = list(continuity_qa.get("issues") or []) + repair_errors
            if resplit_required:
                continuity_qa["status"] = "warning"
                continuity_qa["issues"] = list(continuity_qa.get("issues") or []) + [
                    f"第{pair['fromShot']}镜→第{pair['toShot']}镜需要重拆后再生成"
                    for pair in resplit_required
                ]
            continuity_qa["repair"] = {
                "attempted": repair_attempted,
                "applied": repair_applied,
                "resplitRequired": resplit_required,
                "errors": repair_errors,
            }
            recipe["continuityQa"] = continuity_qa
            gaps = _continuity_coverage_gaps(recipe)
            if gaps or continuity_qa.get("issues"):
                issue_count = max(len(gaps), len(continuity_qa.get("issues") or []))
                risky_pairs = [
                    f"第 {pair['fromShot']} 镜 → 第 {pair['toShot']} 镜"
                    for pair in continuity_qa.get("pairs") or []
                    if pair.get("status") == "warning"
                ]
                risk_count = min(len(risky_pairs), 3) if risky_pairs else min(issue_count, 3)
                risk_suffix = f"：{'、'.join(risky_pairs[:3])}" if risky_pairs else ""
                set_agent_status(
                    recipe,
                    agent_id,
                    "completed",
                    message=f"已写出 {_recipe_shot_count(recipe)} 个镜头；发现 {risk_count} 处衔接风险{risk_suffix}",
                )
            else:
                set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "characters":
            tracker = _make_agent_tracker(agent_id, on_stream)
            _attach_agent_tracker(tracker, chat_fn)
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(
                    agent_id,
                    "你是影视角色设定师。从完整剧本中先建立可长期复用的身份锨点，再建立服装造型；角色与道具分开。"
                    "description 用简体中文说清用户能看见的特征；promptText 用英文，只写视觉事实，不写性格、气质、镜头或场景。"
                    "identitySpec 必须含 ageRange, regionalAppearance, faceFeatures, hair, skinTone, bodyBuild, "
                    "distinguishingMarks, immutableAccessories, avoidChanges。未在剧本明说的外貌可谨慎补全，但必须逐条写入 aiAssumptions。"
                    "looks 至少一个基础造型，appearanceDetails 用中文写服装、材质、色彩与鞋子，promptText 用英文。"
                    "输出 JSON：{\"characters\":[{\"name\":\"\",\"role\":\"\",\"description\":\"\",\"promptText\":\"\","
                    "\"gender\":\"unspecified\",\"identitySpec\":{\"ageRange\":\"\",\"regionalAppearance\":\"\",\"faceFeatures\":\"\","
                    "\"hair\":\"\",\"skinTone\":\"\",\"bodyBuild\":\"\",\"distinguishingMarks\":\"\",\"immutableAccessories\":\"\",\"avoidChanges\":\"\"},"
                    "\"aiAssumptions\":[],\"looks\":[{\"id\":\"look-default\",\"name\":\"基础造型\",\"appearanceDetails\":\"\",\"promptText\":\"\"}]}],"
                    "\"props\":[{\"name\":\"\",\"description\":\"\",\"promptText\":\"\"}]}",
                )},
                {"role": "user", "content": _story_context(recipe, goal)},
            ]) if chat_fn else None
            _apply_characters(recipe, parsed or {})
            _finish_agent_tracker(tracker, parsed)
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "locations":
            tracker = _make_agent_tracker(agent_id, on_stream)
            _attach_agent_tracker(tracker, chat_fn)
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(
                    agent_id,
                    "从完整剧本中抽取所有会承载镜头的独立场景，合并同地点同时段的别名。description 用中文空景说明给用户看；promptText 必须是空景、无人物的英文环境描述。"
                    "输出 {\"locations\":[{\"name\":\"\",\"description\":\"\",\"promptText\":\"\"}]}",
                )},
                {"role": "user", "content": _story_context(recipe, goal)},
            ]) if chat_fn else None
            _apply_locations(recipe, parsed or {})
            _finish_agent_tracker(tracker, parsed)
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "voice":
            tracker = _make_agent_tracker(agent_id, on_stream)
            _attach_agent_tracker(tracker, chat_fn)
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(
                    agent_id,
                    "输出可播放配音元数据，不要生成音频文件。TTS 由工作台稍后调用 OpenAI 兼容 /audio/speech。"
                    "为每个角色选 voiceId：alloy/echo/fable/onyx/nova/shimmer；男声优先 onyx，女声优先 nova。"
                    "台词保留原文，不要翻译；为每镜写 speakerName（角色名）。"
                    "输出 {\"characters\":[{\"name\":\"\",\"voiceId\":\"onyx\"}],"
                    "\"shots\":[{\"shotNumber\":1,\"dialogue\":\"\",\"speakerName\":\"\"}]}。"
                    "无对白的镜头 dialogue 为空字符串。",
                )},
                {"role": "user", "content": json.dumps({
                    "characters": recipe.get("characters") or [],
                    "scenes": recipe.get("scenes") or [],
                }, ensure_ascii=False)[:7000]},
            ]) if chat_fn else None
            _apply_voice(recipe, parsed or {})
            _finish_agent_tracker(tracker, parsed)
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "music":
            tracker = _make_agent_tracker(agent_id, on_stream)
            _attach_agent_tracker(tracker, chat_fn)
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(
                    agent_id,
                    "输出可播放配乐元数据，不要生成音频文件。用户稍后上传 BGM；本步只写音量/淡化与 H3 声音提示词。"
                    "globalMusic 即 non_diegetic_music：英文写乐器、速度、力度变化，禁止空洞情绪词；无配乐写 N/A。"
                    "globalSoundscape 即 overall_soundscape：英文写环境声与物理交互声，不重复台词。"
                    "bgmVolume 为 0-1 小数，bgmFadeInSec / bgmFadeOutSec 为秒。"
                    "输出 {\"globalMusic\":\"\",\"globalSoundscape\":\"\",\"bgmVolume\":0.25,"
                    "\"bgmFadeInSec\":1.2,\"bgmFadeOutSec\":2.0,\"shotSfx\":[{\"shotNumber\":1,\"sfx\":\"\"}]}",
                )},
                {"role": "user", "content": _story_context(recipe, goal)},
            ]) if chat_fn else None
            _apply_music(recipe, parsed or {})
            _finish_agent_tracker(tracker, parsed)
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        compile_recipe_media(recipe)
        set_agent_status(recipe, agent_id, "completed")
        return recipe
    except LlmError as error:
        set_agent_status(recipe, agent_id, "failed", str(error))
        if on_progress:
            on_progress(recipe)
        raise
    except Exception as error:
        set_agent_status(recipe, agent_id, "failed", str(error))
        return recipe


def run_recipe_pipeline(
    recipe: dict[str, Any] | None,
    *,
    goal: str,
    chat_fn: ChatFn | None = None,
    art_style_id: str | None = None,
    agents: list[str] | None = None,
    skip_research: bool | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    on_stream: Callable[[dict[str, Any]], None] | None = None,
    clarifications: Any = None,
) -> dict[str, Any]:
    current = normalize_recipe_payload(recipe or empty_recipe_payload(title=_text(goal)[:24], full_story=goal))
    if not _text((current.get("script") or {}).get("fullStory")):
        current["script"]["fullStory"] = goal
    order = list(agents or PIPELINE_AGENT_ORDER)
    current["pipelineRun"] = {"agents": order, "active": True}
    for agent_id in order:
        set_agent_status(current, agent_id, "pending")
    if on_progress:
        on_progress(current)
    try:
        for agent_id in order:
            set_agent_status(current, agent_id, "running")
            if on_progress:
                on_progress(current)
            current = run_agent(
                agent_id,
                current,
                goal=goal,
                chat_fn=chat_fn,
                art_style_id=art_style_id,
                skip_research=skip_research,
                on_progress=on_progress,
                on_stream=on_stream,
                clarifications=clarifications,
            )
            if on_progress:
                on_progress(current)
            status = next((item for item in current.get("agentStatus") or [] if item.get("id") == agent_id), None)
            if status and status.get("status") == "failed":
                error_text = _text(status.get("error"))
                if is_upstream_llm_failure(error_text):
                    raise LlmBillingError(error_text) if looks_like_llm_billing(error_text) else LlmError(error_text)
                remaining = order[order.index(agent_id) + 1 :]
                if remaining and remaining[0] == "storyboard":
                    continue
                break
        current["pipelineRun"] = {"agents": order, "active": False}
        return normalize_recipe_payload(current)
    except LlmError as error:
        current["pipelineRun"] = {"agents": order, "active": False}
        if "agent_id" in locals():
            set_agent_status(current, agent_id, "failed", str(error))
        if on_progress:
            on_progress(current)
        raise
    except Exception:
        current["pipelineRun"] = {"agents": order, "active": False}
        if on_progress:
            on_progress(current)
        raise


def fission_batch_scripts(
    *,
    theme: str,
    count: int,
    duration_sec: int,
    aspect_ratio: str,
    art_style: dict[str, Any] | None = None,
    chat_fn: ChatFn | None = None,
) -> list[dict[str, str]]:
    count = max(1, min(20, int(count)))
    duration = snap_h3_duration_sec(duration_sec)
    style_hint = ""
    if isinstance(art_style, dict) and art_style.get("name"):
        style_hint = f"画风：{art_style.get('name')}。画面前缀：{art_style.get('promptPrefix') or ''}\n"
    parsed = None
    if chat_fn is not None:
        parsed = _chat_json(chat_fn, [
            {"role": "system", "content": build_h3_batch_fission_prompt(
                count=count, duration_sec=duration, aspect_ratio=aspect_ratio,
            )},
            {"role": "user", "content": f"{style_hint}主题：{theme}"},
        ])
    items: list[dict[str, str]] = []
    for index, raw in enumerate(_list((parsed or {}).get("items"))[:count]):
        if not isinstance(raw, dict):
            continue
        title = _text(raw.get("title"), f"{theme} · {index + 1}")
        script = _text(raw.get("script") or raw.get("prompt"), theme)
        raw_description = _text(raw.get("description"))
        if raw_description == script:
            raw_description = ""
        description, _prompt = split_display_and_prompt(
            title=title,
            description=raw_description,
            prompt_text=script,
            fallback_zh=title,
        )
        items.append({
            "title": title,
            "description": description,
            "script": script,
        })
    while len(items) < count:
        index = len(items) + 1
        items.append({
            "title": f"{theme} · {index}",
            "description": f"{theme}。版本 {index}。",
            "script": f"{theme}。版本 {index}，{duration} 秒，{aspect_ratio} 构图，电影级运镜。",
        })
    return items[:count]
