from __future__ import annotations

import re
from typing import Any, Callable

from .llm_client import LlmError
from .xiaji_analyze import parse_llm_json

SCRIPT_PROMPT_VERSION = "episode_script.literal.v1"
LITERAL_LINE_MAX_TOKENS = 800
LITERAL_LINE_TIMEOUT_SECONDS = 90.0
LITERAL_MAX_BEATS = 400

DIALOGUE_RE = re.compile(r"^(?P<speaker>[^：:]{1,24})[：:](?P<speech>.+)$")
IDENTITY_MARK_RE = re.compile(r"\{\{(.+?)\}\}")
PROP_MARK_RE = re.compile(r"\[\[(.+?)\]\]")
BRACKET_HEADING_RE = re.compile(
    r"^【(?P<int_ext>内|外)】\s*(?P<location>.+?)\s+"
    r"(?P<time>日|夜|晨|晚|午|黄昏|清晨|上午|正午|午后|下午|傍晚|夜晚|深夜|凌晨)\s*$"
)
SIMPLE_HEADING_RE = re.compile(
    r"^(?P<location>.{1,40}?)\s+"
    r"(?P<time>日|夜|晨|晚|午|黄昏|清晨|上午|正午|午后|下午|傍晚|夜晚|深夜|凌晨)\s+"
    r"(?P<int_ext>内|外)$"
)
SCENE_BLOCK_RE = re.compile(
    r"^场次[（(]?\d+[）)]?.*地点[：:]\s*(?P<location>.+?)[，,、]\s*"
    r"(?P<time>日|夜|晨|晚|午|黄昏|清晨|上午|正午|午后|下午|傍晚|夜晚|深夜|凌晨)"
    r"[，,、]\s*(?P<int_ext>内|外)"
)
LABELED_LOCATION_RE = re.compile(r"^(?:地点|环境|场景)[：:]\s*(?P<location>.+)$")
CHARACTER_META_RE = re.compile(r"^(?:人物|出场人物|角色)[：:]")
SCENE_MARKER_RE = re.compile(r"^(?:场次|第)[（(]?\d+[）)]?(?:\s*场)?(?:\s*[:：])?\s*$")

LITERAL_SYSTEM_PROMPT = """你是短剧剧本逐行分镜标注师。

任务不是改写整集，而是严格围绕「当前这一行」补全元数据。只输出一个 JSON 对象，不要 Markdown。

JSON 字段：
- audio_type: silence / narration / dialogue 三选一
- speaker: 仅 dialogue 时填写，必须来自已绑定角色名单；对不上则改成 silence 并留空
- visual_description: 只描述当前这一行真正可见的画面，至少 5 个字
- scene_name: 仅当当前场次未锁定时，从已绑定场景名单精确选择；已锁定则留空
- character_names: 本行画面里物理可见、且在角色名单中的名字数组
- prop_names: 本行被拿着/被操作/被看的道具名数组，只能选自名单

规则：
- 一行一个 beat：不改写原行、不合并多行、不总结剧情、不发明原文没有的情节
- 原行是「人名：台词」才用 dialogue；人名必须在角色名单中
- 旁白、解说、画外音、广播用 narration，speaker 留空
- 动作、环境、空镜、镜头提示、舞台说明用 silence，即使带冒号
- visual_description 还原当前行已给出的可见信息；不要替后续分镜做新的导演设计
- 原行有【特写】/俯拍/仰拍/空镜/黑屏等提示时必须保留
- 对白行若只有台词没有括号动作，不要发明肢体动作，最多写开口说话
- 名单里有的资产，当前行没出现就不要写进去
- 角色在 visual_description 里用 {{角色名}}，道具用 [[道具名]]
- 不要解释，不要复述原行"""


def build_script_messages(
    *,
    original_lines: list[str],
    characters: list[str],
    scenes: list[str],
    props: list[str],
    visual_style: str,
    title: str,
    summary: str,
) -> list[dict[str, str]]:
    preview = "\n".join(f"{index}. {line}" for index, line in enumerate(original_lines[:8], start=1))
    user = (
        f"剧集：{title}\n"
        f"摘要：{summary}\n"
        f"画风：{visual_style or '未指定'}\n"
        f"已绑定角色：{', '.join(characters) or '无'}\n"
        f"已绑定场景：{', '.join(scenes) or '无'}\n"
        f"已绑定道具：{', '.join(props) or '无'}\n"
        f"原文行数：{len(original_lines)}\n"
        f"模式：逐行标注，一行一个 Beat，不改写原文。\n\n"
        f"【原文预览】\n{preview or '（空）'}"
    )
    return [
        {"role": "system", "content": LITERAL_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def format_heading(item: dict[str, Any]) -> str:
    existing = str(item.get("heading") or "").strip()
    if existing:
        return existing[:255]
    int_ext = str(item.get("int_ext") or "外").strip() or "外"
    location = str(item.get("location") or "").strip()
    time_of_day = str(item.get("time_of_day") or "日").strip() or "日"
    if not location:
        return ""
    return f"【{int_ext}】{location} {time_of_day}"[:255]


def parse_scene_heading_line(line: str) -> dict[str, str] | None:
    text = (line or "").strip()
    if not text:
        return None
    match = BRACKET_HEADING_RE.match(text) or SIMPLE_HEADING_RE.match(text) or SCENE_BLOCK_RE.match(text)
    if match:
        return {
            "int_ext": match.group("int_ext"),
            "location": match.group("location").strip(),
            "time_of_day": match.group("time"),
        }
    labeled = LABELED_LOCATION_RE.match(text)
    if labeled:
        rest = labeled.group("location").strip()
        nested = SIMPLE_HEADING_RE.match(rest)
        if nested:
            return {
                "int_ext": nested.group("int_ext"),
                "location": nested.group("location").strip(),
                "time_of_day": nested.group("time"),
            }
        if rest:
            return {"int_ext": "外", "location": rest, "time_of_day": "日"}
    if SCENE_MARKER_RE.match(text):
        return {"int_ext": "外", "location": text, "time_of_day": "日"}
    return None


def is_character_meta_line(line: str) -> bool:
    return bool(CHARACTER_META_RE.match((line or "").strip()))


def split_dialogue_line(line: str) -> tuple[str, str]:
    match = DIALOGUE_RE.match((line or "").strip())
    if not match:
        return "", ""
    speaker = re.sub(r"[（(].*?[）)]", "", match.group("speaker")).strip()
    speech = (match.group("speech") or "").strip()
    return speaker, speech


def derive_spoken_text(raw_line: str, audio_type: str) -> str:
    line = (raw_line or "").strip()
    if audio_type == "silence":
        return ""
    if audio_type == "dialogue":
        _, speech = split_dialogue_line(line)
        if speech:
            return speech
    return line


def _clean_visual(text: str) -> str:
    cleaned = IDENTITY_MARK_RE.sub(r"\1", text or "")
    cleaned = PROP_MARK_RE.sub(r"\1", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _resolve_name(raw: str, *, kind: str, names: list[str], name_to_asset: dict[tuple[str, str], str]) -> str:
    token = (raw or "").strip().strip("{}[]")
    if not token:
        return ""
    if token in names:
        return token
    id_to_name = {asset_id: name for (item_kind, name), asset_id in name_to_asset.items() if item_kind == kind}
    if token in id_to_name:
        return id_to_name[token]
    lowered = token.casefold()
    for name in names:
        if name.casefold() == lowered:
            return name
    return ""


def _resolve_names(values: Any, *, kind: str, names: list[str], name_to_asset: dict[tuple[str, str], str]) -> list[str]:
    items = values if isinstance(values, list) else []
    resolved: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = _resolve_name(str(item or ""), kind=kind, names=names, name_to_asset=name_to_asset)
        if not name or name in seen:
            continue
        seen.add(name)
        resolved.append(name)
    return resolved


def _asset_ids(names: list[str], kind: str, name_to_asset: dict[tuple[str, str], str]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for name in names:
        asset_id = name_to_asset.get((kind, name))
        if not asset_id or asset_id in seen:
            continue
        seen.add(asset_id)
        ids.append(asset_id)
    return ids


def _heading_beat(parsed: dict[str, str], *, scenes: list[str], name_to_asset: dict[tuple[str, str], str]) -> dict[str, Any]:
    heading = format_heading(parsed)
    scene_name = _resolve_name(parsed.get("location") or "", kind="scene", names=scenes, name_to_asset=name_to_asset)
    return {
        "kind": "scene_heading",
        "heading": heading,
        "speaker": "",
        "dialogue": "",
        "action": "",
        "character_ids": [],
        "scene_id": name_to_asset.get(("scene", scene_name)) if scene_name else None,
        "prop_ids": [],
        "locked_scene_name": scene_name,
        "locked_heading": heading,
    }


def heuristic_line_meta(raw_line: str, *, characters: list[str]) -> dict[str, Any]:
    speaker, speech = split_dialogue_line(raw_line)
    if speaker and speech and speaker in characters:
        return {
            "audio_type": "dialogue",
            "speaker": speaker,
            "visual_description": f"{{{{{speaker}}}}} 开口说话",
            "scene_name": "",
            "character_names": [speaker],
            "prop_names": [],
        }
    return {
        "audio_type": "silence",
        "speaker": "",
        "visual_description": raw_line.strip()[:500] or "画面延续上一拍",
        "scene_name": "",
        "character_names": [],
        "prop_names": [],
    }


def normalize_audio_type(
    value: str,
    speaker: str,
    *,
    characters: list[str],
    name_to_asset: dict[tuple[str, str], str],
) -> tuple[str, str]:
    audio_type = (value or "silence").strip()
    if audio_type not in {"silence", "narration", "dialogue"}:
        audio_type = "silence"
    speaker_name = _resolve_name(speaker, kind="character", names=characters, name_to_asset=name_to_asset)
    if audio_type == "dialogue" and not speaker_name:
        audio_type = "silence"
        speaker_name = ""
    if audio_type in {"silence", "narration"}:
        speaker_name = ""
    return audio_type, speaker_name


def content_beat_from_meta(
    raw_line: str,
    meta: dict[str, Any],
    *,
    characters: list[str],
    scenes: list[str],
    props: list[str],
    name_to_asset: dict[tuple[str, str], str],
    locked_scene_name: str,
    locked_heading: str,
) -> dict[str, Any]:
    audio_type, speaker = normalize_audio_type(
        str(meta.get("audio_type") or ""),
        str(meta.get("speaker") or ""),
        characters=characters,
        name_to_asset=name_to_asset,
    )

    visual = _clean_visual(str(meta.get("visual_description") or "").strip())
    if len(visual) < 5:
        visual = heuristic_line_meta(raw_line, characters=characters)["visual_description"]
        visual = _clean_visual(visual)

    marked_characters = [
        _resolve_name(item, kind="character", names=characters, name_to_asset=name_to_asset)
        for item in IDENTITY_MARK_RE.findall(str(meta.get("visual_description") or ""))
    ]
    marked_props = [
        _resolve_name(item, kind="prop", names=props, name_to_asset=name_to_asset)
        for item in PROP_MARK_RE.findall(str(meta.get("visual_description") or ""))
    ]
    character_names = _resolve_names(
        list(meta.get("character_names") or []) + marked_characters,
        kind="character",
        names=characters,
        name_to_asset=name_to_asset,
    )
    prop_names = _resolve_names(
        list(meta.get("prop_names") or []) + marked_props,
        kind="prop",
        names=props,
        name_to_asset=name_to_asset,
    )
    if speaker and speaker not in character_names:
        character_names.insert(0, speaker)

    scene_name = locked_scene_name
    if not scene_name:
        scene_name = _resolve_name(
            str(meta.get("scene_name") or meta.get("scene_id") or ""),
            kind="scene",
            names=scenes,
            name_to_asset=name_to_asset,
        )

    spoken = derive_spoken_text(raw_line, audio_type)
    if audio_type == "dialogue":
        kind = "dialogue"
        dialogue = spoken[:2000]
        action = visual[:2000]
    else:
        kind = "action"
        dialogue = spoken[:2000] if audio_type == "narration" else ""
        action = visual[:2000]

    return {
        "kind": kind,
        "heading": "",
        "speaker": speaker[:128],
        "dialogue": dialogue,
        "action": action,
        "character_ids": _asset_ids(character_names, "character", name_to_asset)[:8],
        "scene_id": name_to_asset.get(("scene", scene_name)) if scene_name else None,
        "prop_ids": _asset_ids(prop_names, "prop", name_to_asset)[:6],
        "locked_scene_name": scene_name,
        "locked_heading": locked_heading,
    }


def _build_line_user_prompt(
    *,
    title: str,
    visual_style: str,
    characters: list[str],
    scenes: list[str],
    props: list[str],
    locked_scene_name: str,
    locked_heading: str,
    prev_window: list[str],
    next_line: str,
    index: int,
    total: int,
    raw_line: str,
) -> str:
    scene_lock = (
        f"已锁定为 {locked_heading or locked_scene_name}，scene_name 必须留空"
        if locked_scene_name or locked_heading
        else "未锁定，请从场景名单精确选一个；没有则留空"
    )
    return (
        f"请为当前这一行补全 beat 元数据。\n"
        f"剧集：{title}\n"
        f"画风：{visual_style or '未指定'}\n"
        f"已绑定角色：{', '.join(characters) or '无'}\n"
        f"已绑定场景：{', '.join(scenes) or '无'}\n"
        f"已绑定道具：{', '.join(props) or '无'}\n"
        f"当前场次：{scene_lock}\n"
        f"前文：{prev_window[-1] if prev_window else '无'}\n"
        f"下一行：{next_line or '无'}\n"
        f"行序号：{index}/{total}\n"
        f"当前行：{raw_line}\n"
        f"只输出 JSON。"
    )


def _call_line_llm(
    client: Any,
    model: str,
    *,
    raw_line: str,
    characters: list[str],
    **prompt_kwargs: Any,
) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": LITERAL_SYSTEM_PROMPT},
        {"role": "user", "content": _build_line_user_prompt(raw_line=raw_line, characters=characters, **prompt_kwargs)},
    ]
    last_error: Exception | None = None
    try:
        raw = client.chat_completion(
            messages,
            model=model,
            temperature=0.2,
            max_tokens=LITERAL_LINE_MAX_TOKENS,
            timeout=LITERAL_LINE_TIMEOUT_SECONDS,
        )
        parsed = parse_llm_json(raw)
        if not isinstance(parsed, dict):
            raise LlmError("大模型没有返回 JSON 对象")
        return parsed
    except (LlmError, ValueError) as error:
        last_error = error
    raise LlmError(str(last_error) if last_error else "逐行标注失败")


def generate_script_beats(
    client: Any,
    model: str,
    *,
    original_lines: list[str],
    characters: list[str],
    scenes: list[str],
    props: list[str],
    visual_style: str,
    title: str,
    summary: str,
    name_to_asset: dict[tuple[str, str], str],
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    del summary
    lines = [str(item or "").strip() for item in original_lines if str(item or "").strip()][:LITERAL_MAX_BEATS]
    if not lines:
        raise LlmError("原文为空，无法逐行生成脚本")
    beats: list[dict[str, Any]] = []
    locked_scene_name = ""
    locked_heading = ""
    total = len(lines)
    for index, raw_line in enumerate(lines, start=1):
        if on_progress:
            on_progress(index - 1, total)
        if is_character_meta_line(raw_line):
            continue
        heading = parse_scene_heading_line(raw_line)
        if heading:
            beat = _heading_beat(heading, scenes=scenes, name_to_asset=name_to_asset)
            locked_scene_name = str(beat.get("locked_scene_name") or locked_scene_name)
            locked_heading = str(beat.get("locked_heading") or "")
            beats.append(_public_beat(beat))
            continue
        prev_window = lines[max(0, index - 3) : index - 1]
        next_line = lines[index] if index < total else ""
        try:
            meta = _call_line_llm(
                client,
                model,
                raw_line=raw_line,
                characters=characters,
                title=title,
                visual_style=visual_style,
                scenes=scenes,
                props=props,
                locked_scene_name=locked_scene_name,
                locked_heading=locked_heading,
                prev_window=prev_window,
                next_line=next_line,
                index=index,
                total=total,
            )
        except LlmError:
            meta = heuristic_line_meta(raw_line, characters=characters)
        beat = content_beat_from_meta(
            raw_line,
            meta,
            characters=characters,
            scenes=scenes,
            props=props,
            name_to_asset=name_to_asset,
            locked_scene_name=locked_scene_name,
            locked_heading=locked_heading,
        )
        if beat.get("locked_scene_name"):
            locked_scene_name = str(beat["locked_scene_name"])
        beats.append(_public_beat(beat))
    if on_progress:
        on_progress(total, total)
    if not beats:
        raise LlmError("没有生成可用的 Beat")
    return beats


def _public_beat(beat: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": beat["kind"],
        "heading": beat.get("heading") or "",
        "speaker": beat.get("speaker") or "",
        "dialogue": beat.get("dialogue") or "",
        "action": beat.get("action") or "",
        "character_ids": beat.get("character_ids") or [],
        "scene_id": beat.get("scene_id"),
        "prop_ids": beat.get("prop_ids") or [],
    }
