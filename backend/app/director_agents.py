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
    default_audio_mix,
    empty_recipe_payload,
    normalize_dialogue,
    normalize_recipe_payload,
    normalize_voice_id,
    set_agent_status,
    split_display_and_prompt,
)
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
from .llm_minimax_skills import build_h3_batch_fission_prompt, build_h3_storyboard_agent_prompt


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
    "每镜 title/description/soundscape 用中文；soundscapeEn 与 promptText 用英文，只写一个从 00:00 开始的 [Shot 1] 片段。"
    "<d> 仅用于实际可听见的台词或歌词；屏幕/招牌/手机上的可见文字必须以英文叙述描述，禁止包进 <d>。"
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
                "dialogue": normalize_dialogue(item.get("dialogue")),
                "characterNames": [_text(name) for name in _list(names) if _text(name)],
                "locationName": _text(item.get("locationName") or item.get("location_name") or scene_item.get("locationName")),
                "durationSec": snap_h3_duration_sec(item.get("durationSec") or item.get("duration_sec") or 5),
                "camera": _camera(item.get("camera")),
                "soundscape": _text(item.get("soundscape") or item.get("sfx")),
                "soundscapeEn": _text(item.get("soundscapeEn") or item.get("soundscape_en")),
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
    by_name: dict[str, dict[str, Any]] = {}
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
        by_name[name] = {
            "name": name,
            "description": description,
            "promptText": prompt_text or _text(raw.get("promptText") or raw.get("prompt_text") or raw.get("description")),
            "gender": _text(raw.get("gender"), "unspecified") or "unspecified",
            "type": char_type,
            "voiceId": normalize_voice_id(raw.get("voiceId") or raw.get("voice_id"), gender=_text(raw.get("gender"), "unspecified")),
        }
    ordered_names = names_from_board or list(by_name.keys())
    characters: list[dict[str, Any]] = []
    for name in ordered_names:
        if name in by_name:
            characters.append(by_name[name])
        else:
            characters.append({
                "name": name,
                "description": name,
                "promptText": f"consistent character named {name}, detailed costume and face, full body design sheet",
                "gender": "unspecified",
                "type": "character",
            })
    recipe["characters"] = characters


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
            "name": name,
            "description": description,
            "promptText": prompt_text or _text(raw.get("promptText") or raw.get("prompt_text") or raw.get("description")),
        }
    ordered = names or list(by_name.keys())
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


def run_agent(
    agent_id: str,
    recipe: dict[str, Any],
    *,
    goal: str,
    chat_fn: ChatFn | None = None,
    art_style_id: str | None = None,
    skip_research: bool | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
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
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(agent_id, "根据常识摘要用户故事里需要核实的设定。不要编造网址。输出 {\"notes\":\"...\",\"skipped\":false}。无事实需求时 notes 为空、skipped 为 true。")},
                {"role": "user", "content": goal},
            ])
            recipe["researchNotes"] = _text((parsed or {}).get("notes"))
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "script":
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(
                    agent_id,
                    "把一句话扩成可拍的短片/短剧脚本。输出 {\"title\":\"\",\"summary\":\"\",\"fullStory\":\"\"}。"
                    "fullStory 800-1500 字中文，必须分场：每场写地点、人物、动作和对白，便于后续一次性拆成全部镜头。"
                    "禁止只写一段摘要。",
                )},
                {"role": "user", "content": goal},
            ]) if chat_fn else None
            _apply_script(recipe, parsed or {}, goal)
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
            user_content = (
                _story_context(recipe, goal)
                + "\n请根据上面的完整故事一次性输出全部镜头，不要只写开场或主镜头。"
            )
            parsed: dict[str, Any] = {}
            if chat_fn:
                previous_chunk = getattr(chat_fn, "on_chunk", None)

                def report_chunk(accumulated: str) -> None:
                    n = len(accumulated or "")
                    if n <= 0:
                        return
                    set_agent_status(recipe, agent_id, "running", message=f"正在写分镜（已收到 {n} 字）")
                    try:
                        emit()
                    except Exception:
                        return

                if hasattr(chat_fn, "on_chunk"):
                    chat_fn.on_chunk = report_chunk
                set_agent_status(recipe, agent_id, "running", message="正在读剧本")
                emit()
                try:
                    raw = _chat_text(chat_fn, [
                        {"role": "system", "content": _system(agent_id, build_h3_storyboard_agent_prompt())},
                        {"role": "user", "content": user_content},
                    ], retries=1)
                    set_agent_status(recipe, agent_id, "running", message="正在整理镜头")
                    emit()
                    parsed = _parse_storyboard_reply(raw, goal)
                    if _is_collapsed_storyboard(parsed, goal):
                        set_agent_status(recipe, agent_id, "running", message="镜头不完整，正在重拆")
                        emit()
                        raw = _chat_text(chat_fn, [
                            {"role": "system", "content": _system(agent_id, STORYBOARD_RETRY_SYSTEM)},
                            {"role": "user", "content": user_content},
                        ], retries=1)
                        set_agent_status(recipe, agent_id, "running", message="正在整理镜头")
                        emit()
                        parsed = _parse_storyboard_reply(raw, goal)
                finally:
                    if hasattr(chat_fn, "on_chunk"):
                        chat_fn.on_chunk = previous_chunk
            _apply_storyboard(recipe, parsed or {}, goal)
            if _recipe_shot_count(recipe) == 0:
                recipe["scenes"] = []
                set_agent_status(recipe, agent_id, "failed", "分镜未按剧本拆出镜头，请重试生成分镜")
                return recipe
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "characters":
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(
                    agent_id,
                    "只从分镜 characterNames 抽角色。道具 type=object。"
                    "description 用中文外貌说明给用户看；promptText 为英文定妆描述，不含地点人名以外的剧情。"
                    "输出 {\"characters\":[{\"name\":\"\",\"description\":\"\",\"promptText\":\"\",\"gender\":\"unspecified\",\"type\":\"character\"}]}",
                )},
                {"role": "user", "content": _story_context(recipe, goal) + "\n分镜：" + json.dumps(recipe.get("scenes") or [], ensure_ascii=False)[:6000]},
            ]) if chat_fn else None
            _apply_characters(recipe, parsed or {})
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "locations":
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(
                    agent_id,
                    "只抽故事里反复出现的地点。description 用中文空景说明给用户看；promptText 必须是空景、无人物的英文环境描述。"
                    "输出 {\"locations\":[{\"name\":\"\",\"description\":\"\",\"promptText\":\"\"}]}",
                )},
                {"role": "user", "content": _story_context(recipe, goal) + "\n分镜：" + json.dumps(recipe.get("scenes") or [], ensure_ascii=False)[:4000]},
            ]) if chat_fn else None
            _apply_locations(recipe, parsed or {})
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "voice":
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
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "music":
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
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        compile_recipe_media(recipe)
        set_agent_status(recipe, agent_id, "completed")
        return recipe
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
) -> dict[str, Any]:
    current = normalize_recipe_payload(recipe or empty_recipe_payload(title=_text(goal)[:24], full_story=goal))
    if not _text((current.get("script") or {}).get("fullStory")):
        current["script"]["fullStory"] = goal
    order = list(agents or AGENT_IDS)
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
