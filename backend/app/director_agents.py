from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from .director_catalog import art_style_ref_for_recipe, find_art_style, list_art_styles
from .director_compiler import compile_recipe_media, snap_h3_duration_sec
from .director_recipe import (
    AGENT_IDS,
    empty_recipe_payload,
    normalize_recipe_payload,
    set_agent_status,
    split_display_and_prompt,
)
from .llm_client import LlmError, OpenAICompatibleClient
from .llm_minimax_skills import build_h3_batch_fission_prompt, build_h3_storyboard_agent_prompt


ChatFn = Callable[[list[dict[str, Any]]], str]

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


def parse_json_object(raw: str) -> dict[str, Any] | None:
    clean_text = (raw or "").strip()
    if not clean_text:
        return None
    if "```json" in clean_text:
        clean_text = clean_text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in clean_text:
        clean_text = clean_text.split("```", 1)[1].split("```", 1)[0].strip()
    first_brace = clean_text.find("{")
    last_brace = clean_text.rfind("}")
    if first_brace == -1 or last_brace <= first_brace:
        return None
    try:
        parsed = json.loads(clean_text[first_brace:last_brace + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


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
    def _chat(messages: list[dict[str, Any]]) -> str:
        return client.chat_completion(
            messages,
            model=model,
            temperature=0.6,
            max_tokens=8192,
            timeout=120.0,
        )
    return _chat


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _chat_json(chat_fn: ChatFn, messages: list[dict[str, Any]], *, retries: int = 1) -> dict[str, Any] | None:
    last_error: Exception | None = None
    for _ in range(retries + 1):
        try:
            raw = chat_fn(messages)
        except LlmError as error:
            last_error = error
            continue
        parsed = parse_json_object(raw)
        if parsed is not None:
            return parsed
        last_error = ValueError("大模型未返回合法 JSON")
    if last_error:
        return None
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


def _apply_script(recipe: dict[str, Any], data: dict[str, Any], goal: str) -> None:
    script = recipe.setdefault("script", {})
    script["title"] = _text(data.get("title"), script.get("title") or goal[:24] or "未命名短片")
    script["summary"] = _text(data.get("summary"), script.get("summary") or goal)
    script["fullStory"] = _text(data.get("fullStory") or data.get("full_story"), script.get("fullStory") or goal)


def _apply_storyboard(recipe: dict[str, Any], data: dict[str, Any], goal: str) -> None:
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list) or not scenes_raw:
        shots_raw = data.get("shots")
        if isinstance(shots_raw, list) and shots_raw:
            scenes_raw = [{"title": "第一场", "shots": shots_raw}]
        else:
            scenes_raw = [{
                "title": "开场",
                "locationName": "",
                "shots": [{
                    "title": "主镜头",
                    "description": goal,
                    "dialogue": "",
                    "characterNames": [],
                    "durationSec": 8,
                }],
            }]
    scenes: list[dict[str, Any]] = []
    shot_number = 1
    for scene_index, scene_raw in enumerate(scenes_raw[:8]):
        scene_item = scene_raw if isinstance(scene_raw, dict) else {}
        shots_raw = scene_item.get("shots")
        if not isinstance(shots_raw, list) or not shots_raw:
            shots_raw = [scene_item]
        shots: list[dict[str, Any]] = []
        for shot_raw in shots_raw[:6]:
            item = shot_raw if isinstance(shot_raw, dict) else {}
            names = item.get("characterNames") or item.get("character_names") or []
            title = _text(item.get("title"), f"分镜 {shot_number}")
            description, prompt_text = split_display_and_prompt(
                title=title,
                description=_text(item.get("description"), goal),
                prompt_text=_text(item.get("promptText") or item.get("prompt_text") or item.get("prompt")),
                fallback_zh=goal,
            )
            shots.append({
                "title": title,
                "description": description,
                "promptText": prompt_text,
                "dialogue": _text(item.get("dialogue")),
                "characterNames": [str(name).strip() for name in _list(names) if str(name).strip()],
                "locationName": _text(item.get("locationName") or item.get("location_name") or scene_item.get("locationName")),
                "durationSec": snap_h3_duration_sec(item.get("durationSec") or item.get("duration_sec") or 5),
                "camera": _camera(item.get("camera")),
                "soundscape": _text(item.get("soundscape") or item.get("sfx")),
                "status": "idle",
                "shotNumber": shot_number,
            })
            shot_number += 1
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
    mapping: dict[str, str] = {}
    for item in _list(data.get("shots")):
        if not isinstance(item, dict):
            continue
        dialogue = _text(item.get("dialogue"))
        key = _text(item.get("id") or item.get("title") or item.get("shotNumber") or item.get("shot_number"))
        if key:
            mapping[key] = dialogue
        number = item.get("shotNumber") or item.get("shot_number")
        if number is not None:
            mapping[str(number)] = dialogue
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            key_id = _text(shot.get("id"))
            key_title = _text(shot.get("title"))
            key_number = str(shot.get("shotNumber") or "")
            if key_id in mapping:
                shot["dialogue"] = mapping[key_id]
            elif key_number in mapping:
                shot["dialogue"] = mapping[key_number]
            elif key_title in mapping:
                shot["dialogue"] = mapping[key_title]


def _apply_music(recipe: dict[str, Any], data: dict[str, Any]) -> None:
    recipe["globalMusic"] = _text(data.get("globalMusic") or data.get("global_music"), recipe.get("globalMusic") or "")
    soundscape = _text(data.get("globalSoundscape") or data.get("global_soundscape"))
    if soundscape:
        recipe["globalSoundscape"] = soundscape
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
) -> dict[str, Any]:
    if agent_id not in AGENT_IDS:
        raise ValueError(f"未知 Agent：{agent_id}")
    recipe = normalize_recipe_payload(deepcopy(recipe) if recipe else empty_recipe_payload())
    set_agent_status(recipe, agent_id, "running")
    try:
        if agent_id == "research":
            skip = should_run_research(goal) is False if skip_research is None else bool(skip_research)
            if skip or chat_fn is None:
                recipe["researchNotes"] = ""
                set_agent_status(recipe, agent_id, "completed")
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
                {"role": "system", "content": _system(agent_id, "把一句话扩成短片脚本。输出 {\"title\":\"\",\"summary\":\"\",\"fullStory\":\"\"}。fullStory 400-800 字中文，含人物与地点。")},
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
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(agent_id, build_h3_storyboard_agent_prompt())},
                {"role": "user", "content": _story_context(recipe, goal)},
            ]) if chat_fn else None
            _apply_storyboard(recipe, parsed or {}, goal)
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
                    "把对白整理进各镜，供 MiniMax H3 联合音轨使用，不要生成独立音频文件。"
                    "台词保留原文，不要翻译；编译器会包成 (S1) says: <d>[Chinese] ...</d>。"
                    "输出 {\"shots\":[{\"shotNumber\":1,\"dialogue\":\"\"}]}。无对白的镜头 dialogue 为空字符串。",
                )},
                {"role": "user", "content": json.dumps(recipe.get("scenes") or [], ensure_ascii=False)[:6000]},
            ]) if chat_fn else None
            _apply_voice(recipe, parsed or {})
            set_agent_status(recipe, agent_id, "completed")
            return recipe

        if agent_id == "music":
            parsed = _chat_json(chat_fn, [
                {"role": "system", "content": _system(
                    agent_id,
                    "按 MiniMax H3 官方 skill 写声音，不生成音频文件。"
                    "globalMusic 即 non_diegetic_music：英文写乐器、速度、力度变化，禁止空洞情绪词；无配乐写 N/A。"
                    "globalSoundscape 即 overall_soundscape：英文写环境声与物理交互声，不重复台词。"
                    "输出 {\"globalMusic\":\"\",\"globalSoundscape\":\"\",\"shotSfx\":[{\"shotNumber\":1,\"sfx\":\"\"}]}",
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
    for agent_id in order:
        set_agent_status(current, agent_id, "pending")
    if on_progress:
        on_progress(current)
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
        )
        if on_progress:
            on_progress(current)
        status = next((item for item in current.get("agentStatus") or [] if item.get("id") == agent_id), None)
        if status and status.get("status") == "failed":
            break
    return normalize_recipe_payload(current)


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
