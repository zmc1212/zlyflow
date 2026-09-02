from __future__ import annotations

from typing import Any

from .xiaji_analyze import parse_llm_json
from .xiaji_asset_prompts import ethnicity_instruction, visual_style_prefix
from .llm_client import LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS, LlmError

SCRIPT_PROMPT_VERSION = "episode_script.v1"
SKETCH_PROMPT_VERSION = "beat_sketch.v2"
RENDER_PROMPT_VERSION = "beat_render.v1"
VIDEO_PROMPT_VERSION = "beat_video.v1"

SKETCH_MARKER_PALETTE = (
    ("#E11D48", "ROSE"),
    ("#2563EB", "BLUE"),
    ("#16A34A", "GREEN"),
    ("#D97706", "AMBER"),
    ("#7C3AED", "VIOLET"),
    ("#0891B2", "CYAN"),
    ("#DB2777", "PINK"),
    ("#4F46E5", "INDIGO"),
)


def character_marker_color(asset_id: str) -> tuple[str, str]:
    total = 0
    for char in str(asset_id or ""):
        total = (total * 31 + ord(char)) & 0xFFFFFFFF
    hex_color, name = SKETCH_MARKER_PALETTE[total % len(SKETCH_MARKER_PALETTE)]
    return hex_color, name

SCRIPT_SYSTEM_PROMPT = """你是影视编剧。把编号原文改写成可拍摄的 Beat 列表。只输出一个 JSON 对象，不要 Markdown。
JSON 字段：beats（数组）。

每个 beat：
- kind: scene_heading / action / dialogue 三选一
- int_ext: 外 或 内（仅 scene_heading）
- location: 地点名称（仅 scene_heading）
- time_of_day: 日 / 夜 / 晨 / 黄昏（仅 scene_heading）
- speaker: 对白说话人，必须来自已绑定角色名单（仅 dialogue）
- text: 台词（仅 dialogue）
- action: 可见的画面动作或场面调度
- character_names: 本镜出场角色名数组，只能选自已绑定角色
- scene_name: 对应的场景资产名，没有则空字符串
- prop_names: 出场道具名数组，只能选自已绑定道具

规则：
- 场景切换必须先写 scene_heading
- 对白无法对应到名单中的角色时，改写成 action，不要编造角色
- 不要发明原文没有的情节
- 每个 beat 都要能单独拍成一张画面
- 控制在 8 到 40 个 beat"""


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
    numbered = "\n".join(f"{index}. {line}" for index, line in enumerate(original_lines, start=1))
    user = (
        f"剧集：{title}\n"
        f"摘要：{summary}\n"
        f"视觉风格：{visual_style or '未指定'}\n"
        f"已绑定角色：{', '.join(characters) or '无'}\n"
        f"已绑定场景：{', '.join(scenes) or '无'}\n"
        f"已绑定道具：{', '.join(props) or '无'}\n\n"
        f"【原文】\n{numbered or '（空）'}"
    )
    return [
        {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
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


def normalize_script_beats(
    parsed: dict[str, Any],
    *,
    name_to_asset: dict[tuple[str, str], str],
    allowed_speakers: set[str],
) -> list[dict[str, Any]]:
    raw_beats = parsed.get("beats") if isinstance(parsed, dict) else None
    if not isinstance(raw_beats, list):
        raise LlmError("大模型没有返回 beats 数组")
    beats: list[dict[str, Any]] = []
    for item in raw_beats:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "action").strip()
        if kind not in {"scene_heading", "action", "dialogue"}:
            kind = "action"
        speaker = str(item.get("speaker") or "").strip()
        dialogue = str(item.get("text") or item.get("dialogue") or "").strip()
        action = str(item.get("action") or "").strip()
        if kind == "dialogue" and speaker and speaker not in allowed_speakers:
            kind = "action"
            if dialogue:
                action = f"{speaker}：{dialogue}" if not action else action
            speaker = ""
            dialogue = ""
        if kind == "dialogue" and not dialogue:
            kind = "action"
        heading = format_heading(item) if kind == "scene_heading" else ""
        if kind == "scene_heading" and not heading:
            continue
        if kind == "action" and not action:
            continue
        character_ids = _resolve_names(item.get("character_names"), "character", name_to_asset)
        if speaker:
            speaker_id = name_to_asset.get(("character", speaker))
            if speaker_id and speaker_id not in character_ids:
                character_ids.insert(0, speaker_id)
        scene_name = str(item.get("scene_name") or "").strip()
        scene_id = name_to_asset.get(("scene", scene_name)) if scene_name else None
        prop_ids = _resolve_names(item.get("prop_names"), "prop", name_to_asset)
        beats.append(
            {
                "kind": kind,
                "heading": heading,
                "speaker": speaker[:128],
                "dialogue": dialogue[:2000],
                "action": action[:2000],
                "character_ids": character_ids[:8],
                "scene_id": scene_id,
                "prop_ids": prop_ids[:6],
            }
        )
        if len(beats) >= 40:
            break
    if not beats:
        raise LlmError("没有生成可用的 Beat")
    return beats


def _resolve_names(value: Any, kind: str, name_to_asset: dict[tuple[str, str], str]) -> list[str]:
    names = value if isinstance(value, list) else []
    ids: list[str] = []
    seen: set[str] = set()
    for item in names:
        name = str(item or "").strip()
        asset_id = name_to_asset.get((kind, name))
        if not asset_id or asset_id in seen:
            continue
        seen.add(asset_id)
        ids.append(asset_id)
    return ids


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
) -> list[dict[str, Any]]:
    messages = build_script_messages(
        original_lines=original_lines,
        characters=characters,
        scenes=scenes,
        props=props,
        visual_style=visual_style,
        title=title,
        summary=summary,
    )
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            raw = client.chat_completion(
                messages,
                model=model,
                temperature=0.4,
                max_tokens=4096,
                timeout=LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
            )
            parsed = parse_llm_json(raw)
            return normalize_script_beats(
                parsed,
                name_to_asset=name_to_asset,
                allowed_speakers=set(characters),
            )
        except (LlmError, ValueError) as error:
            last_error = error
    raise LlmError(str(last_error) if last_error else "脚本生成失败")


def _beat_assets(beat: dict[str, Any], assets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]:
    by_id = {item["id"]: item for item in assets}
    characters = [by_id[item_id] for item_id in beat.get("character_ids") or [] if item_id in by_id]
    scene = by_id.get(str(beat.get("scene_id") or ""))
    props = [by_id[item_id] for item_id in beat.get("prop_ids") or [] if item_id in by_id]
    return characters, scene, props


def _beat_action_line(beat: dict[str, Any]) -> str:
    if beat.get("kind") == "scene_heading":
        heading = str(beat.get("heading") or "").strip()
        action = str(beat.get("action") or "").strip()
        return " ".join(part for part in (heading, action) if part)
    return str(beat.get("action") or "").strip()


def beat_sketch_prompt(
    beat: dict[str, Any],
    *,
    assets: list[dict[str, Any]],
    visual_style: str,
    ethnicity: str,
) -> str:
    characters, scene, props = _beat_assets(beat, assets)
    marker_lines = []
    for character in characters:
        hex_color, color_name = character_marker_color(character["id"])
        marker_lines.append(f"{character['name']} = solid {color_name} fill {hex_color} featureless mannequin")
    parts = [
        "ROLE: You are a MASTER FILM DIRECTOR and storyboard artist.",
        "TASK: Draw ONE panel as a rushed film director storyboard scribble on cheap white paper. This is a blocking thumbnail, not a finished illustration.",
        "STYLE: loose pencil/marker doodle, imperfect strokes, deliberately unpolished, raw thumbnail-grade draft. Completely uninterested in artistic finish.",
        "WHITE PAPER BACKGROUND ONLY. No photographic production still, no cinematic lighting, no grayscale rendering, no gradients, no shadows, no material shading, no texture, no digital art, no vector clean-up.",
        "SYMBOLIC STORYBOARD PEOPLE ONLY: oval head, one spine line, single-stroke arms/legs, tiny facing ticks. NO clothing, no hair, no facial features, no skin, no realistic anatomy.",
        "SINGLE-MOMENT RULE: exactly one camera setup and one frozen story moment. No collage, split-screen, subtitles, watermark, or readable text.",
        "If a scene reference is attached, redraw it as sparse black/gray line art only. Do NOT copy realistic lighting, colors, texture, or rendered detail.",
        f"World/setting cue only (do not render as a finished still): {visual_style_prefix(visual_style)}".strip(": "),
        ethnicity_instruction(ethnicity),
    ]
    if marker_lines:
        parts.append("CHARACTER COLOR MARKERS: " + "; ".join(marker_lines))
    if scene:
        definition = scene.get("definition") or {}
        parts.append(
            f"location {scene['name']}: simplified architectural line art only. "
            f"{definition.get('description') or definition.get('environment_prompt') or ''}"
        )
    for prop in props:
        parts.append(f"named prop {prop['name']}: simple silhouette / marker shape, no material finish")
    action = _beat_action_line(beat)
    if action:
        parts.append(f"ACTION (source of truth): {action}")
    dialogue = str(beat.get("dialogue") or "").strip()
    speaker = str(beat.get("speaker") or "").strip()
    if dialogue:
        parts.append(f"{speaker} speaking, gesture only, no readable text: {dialogue}")
    return ". ".join(part.strip(" .") for part in parts if str(part).strip())


def beat_render_prompt(
    beat: dict[str, Any],
    *,
    assets: list[dict[str, Any]],
    visual_style: str,
    ethnicity: str,
) -> str:
    characters, scene, props = _beat_assets(beat, assets)
    char_lines = []
    for character in characters:
        definition = character.get("definition") or {}
        looks = definition.get("looks") or []
        look = looks[0] if looks and isinstance(looks[0], dict) else {}
        hex_color, color_name = character_marker_color(character["id"])
        char_lines.append(
            " ".join(
                part
                for part in (
                    f"{character['name']} (sketch marker {color_name} {hex_color})",
                    str(definition.get("face_prompt") or ""),
                    str(look.get("appearance_details") or ""),
                    str(definition.get("description") or ""),
                )
                if part
            )
        )
    style_finish = "Cinematic lighting, photorealistic, 8k."
    if (visual_style or "").strip() in {"anime", "guoman_fantasy"}:
        style_finish = "Dynamic cinematic lighting, stylized animated finish, high detail."
    parts = [
        "Render this sketch into a high-quality colored production still.",
        "Image 1 / SKETCH IS the base drawing — preserve ALL composition, crop, poses, and camera angles exactly. Other reference images lock identity only and must not change the sketch layout.",
        "CRITICAL: Keep exact composition from sketch. Only add color, texture, and lighting.",
        visual_style_prefix(visual_style),
        ethnicity_instruction(ethnicity),
        style_finish,
    ]
    if char_lines:
        parts.append("CHARACTERS (match face references): " + "; ".join(char_lines))
    if scene:
        definition = scene.get("definition") or {}
        parts.append(
            f"SCENE: {scene['name']}. {definition.get('description') or definition.get('environment_prompt') or ''}"
        )
    for prop in props:
        definition = prop.get("definition") or {}
        parts.append(f"prop {prop['name']}: {definition.get('visual_prompt') or ''}")
    action = _beat_action_line(beat)
    if action:
        parts.append(action)
    dialogue = str(beat.get("dialogue") or "").strip()
    speaker = str(beat.get("speaker") or "").strip()
    if dialogue:
        parts.append(f"{speaker} speaking, silent acting, no readable text: {dialogue}")
    return ". ".join(part.strip(" .") for part in parts if str(part).strip())


def beat_video_prompt(
    beat: dict[str, Any],
    *,
    route: str = "i2v",
    picture_count: int = 1,
) -> str:
    action = _beat_action_line(beat)
    dialogue = str(beat.get("dialogue") or "").strip()
    speaker = str(beat.get("speaker") or "").strip()
    count = max(1, int(picture_count or 1))
    if route == "r2v":
        mentions = ", ".join(f"<Picture {index}>" for index in range(1, count + 1))
        parts = [
            "Animate a single continuous camera shot.",
            "<Picture 1> is the approved first-frame render at 0.00 seconds; keep composition, identity, costume, and environment from this still.",
            f"Use {mentions} in order. Extra pictures lock character identity or scene only and must not replace the first-frame layout.",
            "No subtitles, no captions, no watermark, no collage.",
        ]
    else:
        parts = [
            "Animate this first-frame still into a single continuous camera shot.",
            "Keep identity, costume, and environment consistent with the first frame.",
            "No subtitles, no captions, no watermark, no collage.",
        ]
    if action:
        parts.append(action)
    if dialogue:
        parts.append(f"{speaker} speaking with matching mouth motion, no readable on-screen text: {dialogue}")
    return ". ".join(part.strip(" .") for part in parts if str(part).strip())
