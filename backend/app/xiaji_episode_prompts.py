from __future__ import annotations

from typing import Any

from .xiaji_analyze import parse_llm_json
from .xiaji_art_style import (
    art_style_hint,
    art_style_label,
    is_animation_art_style,
    is_non_live_art_style,
    resolve_beat_art_style,
)
from .xiaji_asset_prompts import ethnicity_instruction, visual_style_prefix
from .llm_client import LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS, LlmError

from .xiaji_literal_script import SCRIPT_PROMPT_VERSION, build_script_messages, generate_script_beats

SKETCH_PROMPT_VERSION = "beat_sketch.v2"
RENDER_PROMPT_VERSION = "beat_render.v2"
VIDEO_PROMPT_VERSION = "beat_video.v2"
VIDEO_MOTION_PROMPT_VERSION = "beat_video_motion.v4"

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
    style_id = resolve_beat_art_style(visual_style, characters)
    style_prefix = visual_style_prefix(style_id) or visual_style_prefix(visual_style)
    style_name = art_style_label(style_id)
    protagonist = next(
        (
            item
            for item in characters
            if isinstance(item.get("definition"), dict) and item["definition"].get("is_main")
        ),
        characters[0] if characters else None,
    )
    protagonist_name = str((protagonist or {}).get("name") or "").strip()
    non_live = is_non_live_art_style(style_id) or is_animation_art_style(visual_style) or (visual_style or "").strip() in {
        "anime",
        "guoman_fantasy",
    }
    if non_live:
        style_finish = "Dynamic cinematic lighting, stylized animated finish, high detail."
        who = f"{protagonist_name} and the other named characters" if protagonist_name else "Named characters"
        not_real = (
            f"{who} are stylized illustrated/animated characters, NOT real people and NOT live-action photography. "
            "Do not generate photoreal human skin, documentary realism, or a real-person likeness."
        )
        if style_name or style_prefix:
            not_real += (
                f" Match the protagonist art style"
                f"{f' ({style_name})' if style_name else ''}"
                f"{f': {style_prefix}' if style_prefix else ''}."
            )
    else:
        style_finish = "Cinematic lighting, photorealistic, 8k."
        not_real = ""
    parts = [
        "Render this sketch into a high-quality colored production still.",
        "Image 1 / SKETCH IS the base drawing — preserve ALL composition, crop, poses, and camera angles exactly. Other reference images lock identity only and must not change the sketch layout.",
        "After the sketch, character attachments are FACE then COSTUME for each named character in order. FACE locks identity; COSTUME locks clothing. Do not treat a costume sheet as the face.",
        "CRITICAL: Keep exact composition from sketch. Only add color, texture, and lighting.",
        not_real,
        style_prefix,
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


def _picture_by_role(pictures: list[dict[str, Any]] | None, *roles: str) -> dict[str, Any] | None:
    for item in pictures or []:
        if isinstance(item, dict) and str(item.get("role") or "") in roles:
            return item
    return None


def pictures_have_bridge(pictures: list[dict[str, Any]] | None) -> bool:
    return _picture_by_role(pictures, "bridge_in") is not None


def _bridge_timing_ok(text: str) -> bool:
    compact = str(text or "").lower().replace("–", "-").replace("—", "-").replace("～", "-").replace("至", "-")
    compact = compact.replace(" ", "")
    if "1.5" not in compact:
        return False
    return any(
        token in compact
        for token in ("0-1.5", "0.00-1.50", "0.0-1.5", "0to1.5", "from0", "0秒-1.5", "前1.5")
    )


def beat_video_prompt(
    beat: dict[str, Any],
    *,
    route: str = "i2v",
    picture_count: int = 1,
    pictures: list[dict[str, Any]] | None = None,
) -> str:
    action = _beat_action_line(beat)
    dialogue = str(beat.get("dialogue") or "").strip()
    speaker = str(beat.get("speaker") or "").strip()
    slots = [item for item in (pictures or []) if isinstance(item, dict) and item.get("tag")]
    count = max(1, len(slots) or int(picture_count or 1))
    bridge = _picture_by_role(slots, "bridge_in")
    target = _picture_by_role(slots, "shot_render", "first_frame")
    target_tag = str((target or {}).get("tag") or "<Picture 2>")
    if route == "r2v":
        mentions = ", ".join(str(item["tag"]) for item in slots) or ", ".join(
            f"<Picture {index}>" for index in range(1, count + 1)
        )
        legend = "; ".join(
            f"{item['tag']} = {item.get('label_en') or item.get('role') or item.get('name')}"
            for item in slots
        )
        if bridge:
            parts = [
                "Animate a LightX2V multi-reference R2V shot with a 1.5-second continuity bridge.",
                "From 0-1.5s start FROM the exact last-frame still of the previous shot in <Picture 1> and continuously transform into the current beat render composition in "
                + target_tag
                + "; no hard cut, no split screen, no collage.",
                f"From 1.5s to the end, continue FROM {target_tag} and play the current beat action.",
                f"Use {mentions} in upload order. Extra pictures lock identity or place only and must not replace the bridged layout.",
                "No subtitles, no captions, no watermark, no collage.",
            ]
        else:
            parts = [
                "Animate a LightX2V multi-reference R2V shot.",
                "<Picture 1> is the approved first-frame render at 0.00 seconds; keep composition, identity, costume, and environment from this still.",
                f"Use {mentions} in upload order. Extra pictures lock identity or place only and must not replace the first-frame layout.",
                "No subtitles, no captions, no watermark, no collage.",
            ]
        if legend:
            parts.append(legend)
    elif bridge:
        parts = [
            "Animate this previous-shot last-frame still into a single continuous camera shot.",
            "From 0-1.5s continuously transform from this first frame into the current beat's approved render composition.",
            "From 1.5s onward continue from that render composition. Keep identity, costume, and environment consistent.",
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


VIDEO_MOTION_SYSTEM_PROMPT = """你是 LightX2V 多参考 R2V（MiniMax H3 Ref2V）运动导演。只输出一个 JSON 对象，不要 Markdown。
JSON 字段：
- prompt_zh: 给创作者看的中文运动提示词（要能当镜头说明书）
- prompt_en: 交给本机 ComfyUI / LightX2V 的英文提示词

必须遵守：
1. 参考图按上传顺序编号。中英都必须原样使用 <Picture 1>、<Picture 2>… 不得改写、不得跳号、不得省略任何一张。
2. 禁止用 the hero / the second character / a man / a woman 这类泛称代替素材。每一句 Use <Picture n> 必须写清这张图的素材类型和素材专名（角色名+头像/哪套造型，或场景名+正面/背面，或本镜精绘，或上一镜衔接帧）。
3. 先写 1–2 句视觉风格（只用项目给定风格，不要写成漫画墨线或夜城屋顶，除非风格就是那个）。
4. 接着逐张锁图：写这张图里具体是谁、穿什么、什么空间、锁什么（脸/服装/环境/t=0构图/1.5秒目标构图），并带上外貌或场景要点。
5. 若清单里有上一镜衔接帧（bridge_in）：它是 t=0。<Picture 1> 永远是上一镜截图，不是本镜精绘。中英都必须写清：0-1.5s 从该衔接帧连续过渡到本镜精绘构图；1.5s 之后才从精绘构图按本镜动作向前演。禁止硬切、禁止分屏、禁止把精绘当成全片结尾静帧。
6. 若没有衔接帧：<Picture 1> 才是本镜精绘首帧：机位、构图、人物站位以它为 t=0，后续只能向前演，不能回到首帧之前，不能把后到的头像/造型/场景图拼成新的分屏。
7. 头像只锁脸和身份；造型图只锁服装；场景图只锁环境。它们不能改掉 t=0 或 1.5s 目标布局。
8. 然后写本镜的详细画面解说（不是锁图摘要）：按指定秒数写连贯动作 + 明确运镜。中英都要写明这段就是该秒数。有衔接时先写 0-1.5s 过渡段，再写 1.5s 到结束的本镜动作。
9. 有对白时写口型和身体配合。不要出现可读字幕、字幕条、水印。不要写 <Audio n>，本机不传音频。
10. 只根据本镜动作/对白/参考图素材来写，禁止抄屋顶小超人、机甲咆哮、漫画大字等示例情节。
11. 只输出 JSON。"""


def format_video_picture_catalog(pictures: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for item in pictures:
        if not isinstance(item, dict) or not item.get("tag"):
            continue
        lines = [
            str(item.get("tag") or ""),
            f"- 素材类型: {item.get('material') or item.get('role') or ''}",
            f"- 素材专名: {item.get('name') or ''}",
            f"- 中文职责: {item.get('label_zh') or ''}",
            f"- English lock: {item.get('label_en') or ''}",
        ]
        detail_zh = str(item.get("detail_zh") or "").strip()
        detail_en = str(item.get("detail_en") or "").strip()
        if detail_zh:
            lines.append(f"- 素材细节: {detail_zh}")
        if detail_en:
            lines.append(f"- material detail: {detail_en}")
        blocks.append("\n".join(part for part in lines if part and not part.endswith(": ")))
    return "\n\n".join(blocks)


def build_video_motion_messages(
    *,
    beat: dict[str, Any],
    pictures: list[dict[str, Any]],
    duration: float,
    visual_style: str,
    route: str,
) -> list[dict[str, str]]:
    action = _beat_action_line(beat)
    heading = str(beat.get("heading") or "").strip()
    dialogue = str(beat.get("dialogue") or "").strip()
    speaker = str(beat.get("speaker") or "").strip()
    style_label = art_style_hint(visual_style) or (visual_style or "").strip()
    catalog = format_video_picture_catalog(pictures) or "（无参考图）"
    lock_lines = []
    for item in pictures:
        if not isinstance(item, dict) or not item.get("tag"):
            continue
        lock_lines.append(
            f"Use {item.get('tag')} as {item.get('label_en') or item.get('name') or item.get('role')}."
        )
    skeleton = "\n".join(lock_lines)
    bridge = _picture_by_role(pictures, "bridge_in")
    target = _picture_by_role(pictures, "shot_render", "first_frame")
    target_tag = str((target or {}).get("tag") or "<Picture 2>")
    if bridge:
        action_chain = (
            f"Action chain for {duration:g} seconds:\n"
            f"0-1.5s: start FROM the exact last-frame still in <Picture 1> (previous shot screenshot) and continuously transform into the current beat render {target_tag}. No hard cut, no split screen.\n"
            f"From 1.5s to {duration:g}s: continue FROM {target_tag}, name the visible people and place, then describe camera move and the current beat action until {duration:g} seconds.\n"
        )
        first_lock = "keep continuity: 0-1.5s bridge from previous last frame into the current render, then play this beat."
    else:
        action_chain = (
            f"Action chain for {duration:g} seconds:\n"
            f"CUT 1: start FROM the exact composition of <Picture 1>, name the visible people and place, then describe camera move and the first beat of action.\n"
            f"Then continue with the next concrete motion (who moves, what changes in space, how the camera follows) until {duration:g} seconds.\n"
        )
        first_lock = "keep continuity with the first frame."
    user = (
        f"工作流：LightX2V 多参考 R2V\n"
        f"模式：{route}\n"
        f"指定时长：{duration:g} 秒。prompt_zh 与 prompt_en 都必须写明这段就是 {duration:g} 秒。\n"
        f"画风代码：{visual_style or '（未设）'}\n"
        f"画风：{style_label or '跟随项目设定，写实电影感，不要强行漫画字效'}\n"
        f"镜头标头：{heading or '（无）'}\n"
        f"本镜动作（画面必须解说这件事）：{action or '（无）'}\n"
        f"说话人：{speaker or '（无）'}\n"
        f"对白：{dialogue or '（无）'}\n"
        f"衔接：{'需要 0-1.5s 从上一镜截图过渡到本镜精绘' if bridge else '无上一镜衔接，直接从本镜精绘开始'}\n\n"
        f"【参考图装箱清单：每张图的素材类型、专名、外貌/服装/场景细节。英文锁图句必须用这些专名，禁止改成 hero / second character】\n"
        f"{catalog}\n\n"
        f"英文稿骨架（只学结构；锁图句换成上面清单里的专名和细节；动作链只写本镜，禁止抄屋顶/机甲）：\n"
        f"{style_label or 'Cinematic realistic period-drama lighting'}, {first_lock}\n"
        f"{skeleton}\n"
        f"{action_chain}"
        f"Hold through the full duration. No <Audio n>. No readable on-screen captions."
    )
    return [
        {"role": "system", "content": VIDEO_MOTION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _normalize_video_motion_pair(parsed: dict[str, Any], pictures: list[dict[str, Any]]) -> dict[str, str]:
    zh = str(parsed.get("prompt_zh") or parsed.get("zh") or "").strip()
    en = str(parsed.get("prompt_en") or parsed.get("en") or "").strip()
    if not zh or not en:
        raise LlmError("大模型没有返回中英双语视频提示词")
    missing = [str(item.get("tag") or "") for item in pictures if item.get("tag") and str(item.get("tag")) not in en]
    missing_zh = [str(item.get("tag") or "") for item in pictures if item.get("tag") and str(item.get("tag")) not in zh]
    unnamed = []
    for item in pictures:
        role = str(item.get("role") or "")
        key = str(item.get("name") or "").split("·")[0].strip()
        if role in {"first_frame", "bridge_in", "shot_render", ""} or len(key) < 2:
            continue
        if key not in zh or key not in en:
            unnamed.append(key)
    if missing or missing_zh or unnamed:
        raise LlmError(
            "提示词缺少参考图素材标注："
            + "，".join(part for part in (*missing, *(f"{tag}中文" for tag in missing_zh), *unnamed) if part)
        )
    if pictures_have_bridge(pictures) and (not _bridge_timing_ok(zh) or not _bridge_timing_ok(en)):
        raise LlmError("提示词必须写明 0-1.5s 从上一镜截图过渡到本镜精绘")
    return {"prompt_zh": zh, "prompt_en": en}


def generate_beat_video_motion_prompt(
    client: Any,
    model: str,
    *,
    beat: dict[str, Any],
    pictures: list[dict[str, Any]],
    duration: float,
    visual_style: str,
    route: str,
) -> dict[str, str]:
    messages = build_video_motion_messages(
        beat=beat,
        pictures=pictures,
        duration=duration,
        visual_style=visual_style,
        route=route,
    )
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            raw = client.chat_completion(
                messages,
                model=model,
                temperature=0.55,
                max_tokens=4096,
                timeout=LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
            )
            parsed = parse_llm_json(raw)
            if not isinstance(parsed, dict):
                raise LlmError("大模型没有返回 JSON 对象")
            return _normalize_video_motion_pair(parsed, pictures)
        except (LlmError, ValueError) as error:
            last_error = error
    raise LlmError(str(last_error) if last_error else "视频提示词生成失败")


def public_video_pictures(pictures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public = []
    for item in pictures:
        if not isinstance(item, dict):
            continue
        public.append(
            {
                "index": item.get("index"),
                "tag": item.get("tag"),
                "role": item.get("role"),
                "material": item.get("material"),
                "name": item.get("name"),
                "label_zh": item.get("label_zh"),
                "label_en": item.get("label_en"),
                "detail_zh": item.get("detail_zh"),
                "detail_en": item.get("detail_en"),
            }
        )
    return public
