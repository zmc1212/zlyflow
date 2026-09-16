"""分镜草图 / 渲染图 Prompt，对齐 source1/app/xiaji_episode_prompts.py。"""
from __future__ import annotations

import re
from typing import Any

from .asset_image_prompts import composed_style_line, ethnicity_instruction
from .visual_styles import (
    is_animation_visual_style,
    normalize_visual_style,
    resolve_visual_style,
    visual_style_label,
)

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


def visual_style_prefix(visual_style: str, art_style_id: str = "") -> str:
    return composed_style_line(visual_style, art_style_id)


def asset_to_prompt_dict(row: dict[str, Any]) -> dict[str, Any]:
    extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    looks: list[dict[str, Any]] = []
    for ident in extra.get("identities") or []:
        if not isinstance(ident, dict):
            continue
        looks.append(
            {
                "id": ident.get("id"),
                "name": ident.get("name"),
                "appearance_details": ident.get("appearance_details") or ident.get("description") or "",
                "image_url": ident.get("image_url") or "",
            }
        )
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "kind": row.get("kind"),
        "definition": {
            "face_prompt": extra.get("face_prompt") or extra.get("avatar_prompt") or "",
            "description": extra.get("description") or row.get("description") or "",
            "environment_prompt": extra.get("environment_prompt") or row.get("visual_prompt") or "",
            "visual_prompt": extra.get("visual_prompt") or row.get("visual_prompt") or "",
            "is_main": bool(extra.get("is_main")),
            "looks": looks,
            "back_image_url": extra.get("reverse_url") or "",
        },
        "image_url": extra.get("master_url") or extra.get("avatar_url") or row.get("image_url") or "",
        "extra": extra,
    }


def scene_master_url(scene: dict[str, Any] | None) -> str:
    if not scene:
        return ""
    extra = scene.get("extra") if isinstance(scene.get("extra"), dict) else {}
    for value in (extra.get("master_url"), scene.get("image_url")):
        url = str(value or "").strip()
        if url.startswith(("http://", "https://")):
            return url
    return ""


def _scene_name_matches(asset_name: str, scene_name: str) -> bool:
    asset_name = str(asset_name or "").strip()
    scene_name = str(scene_name or "").strip()
    if not asset_name or not scene_name:
        return False
    return asset_name == scene_name or asset_name in scene_name or scene_name in asset_name


def resolve_scene_asset(beat: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick a scene asset for a beat, preferring one that already has a master view."""
    by_id = {str(item.get("id")): item for item in assets if item.get("id")}
    bound = by_id.get(str(beat.get("scene_id") or ""))
    if bound and bound.get("kind") not in (None, "", "scene"):
        bound = None
    if scene_master_url(bound):
        return bound
    scenes = [item for item in assets if item.get("kind") == "scene"]
    scene_name = str(beat.get("scene") or (bound or {}).get("name") or "").strip()
    matches = [item for item in scenes if _scene_name_matches(str(item.get("name") or ""), scene_name)] if scene_name else []
    with_url = next((item for item in matches if scene_master_url(item)), None)
    if with_url:
        return with_url
    return bound or (matches[0] if matches else None)


def _beat_assets(
    beat: dict[str, Any], assets: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]:
    by_id = {item["id"]: item for item in assets if item.get("id")}
    characters = [by_id[item_id] for item_id in beat.get("character_ids") or [] if item_id in by_id]
    scene = resolve_scene_asset(beat, assets)
    props = [by_id[item_id] for item_id in beat.get("prop_ids") or [] if item_id in by_id]
    return characters, scene, props


def _beat_action_line(beat: dict[str, Any]) -> str:
    if beat.get("kind") == "scene_heading":
        heading = str(beat.get("heading") or "").strip()
        action = str(beat.get("action") or "").strip()
        return " ".join(part for part in (heading, action) if part)
    return str(beat.get("action") or "").strip()


def _is_modern_beat(beat: dict[str, Any], selected_look: dict[str, Any] | None = None) -> bool:
    context = " ".join(
        str(beat.get(key) or "")
        for key in ("heading", "scene", "action", "visual_prompt", "speaker", "characters")
    )
    if selected_look:
        context += " " + " ".join(
            str(selected_look.get(key) or "")
            for key in ("name", "appearance_details", "description")
        )
    return bool(re.search(r"现代|当代|21世纪|大学|图书馆|电脑|白领|硕士", context))


def beat_sketch_prompt(
    beat: dict[str, Any],
    *,
    assets: list[dict[str, Any]],
    visual_style: str,
    ethnicity: str,
    art_style_id: str = "",
) -> str:
    characters, scene, props = _beat_assets(beat, assets)
    marker_lines = []
    for character in characters:
        hex_color, color_name = character_marker_color(str(character.get("id") or ""))
        marker_lines.append(f"{character['name']} = solid {color_name} fill {hex_color} featureless mannequin")
    parts = [
        "ROLE: You are a MASTER FILM DIRECTOR and storyboard artist.",
        "TASK: Draw ONE panel as a rushed film director storyboard scribble on cheap white paper. This is a blocking thumbnail, not a finished illustration.",
        "STYLE: loose pencil/marker doodle, imperfect strokes, deliberately unpolished, raw thumbnail-grade draft. Completely uninterested in artistic finish.",
        "WHITE PAPER BACKGROUND ONLY. Use sparse contour strokes and flat marker fills. Leave all surfaces, backgrounds, and figures visibly unfinished.",
        "SYMBOLIC STORYBOARD PEOPLE ONLY: oval head, one spine line, single-stroke arms/legs, tiny facing ticks. NO clothing, no hair, no facial features, no skin, no realistic anatomy.",
        "SINGLE-MOMENT RULE: exactly one camera setup and one frozen story moment. No collage, split-screen, subtitles, watermark, or readable text.",
        "If a scene reference is attached, reduce it to sparse black/gray architectural contour lines only.",
    ]
    setting_cues = {
        "chinese_period_drama": "historical Chinese setting",
        "republican_era_drama": "1920s-1940s Republican-era Chinese setting",
        "realistic": "contemporary real-world setting",
        "modern": "contemporary modern-day setting",
        "post_apocalyptic": "post-apocalyptic setting",
    }
    setting_cue = setting_cues.get(normalize_visual_style(art_style_id, visual_style), "")
    if setting_cue:
        parts.append(
            f"SETTING CONTINUITY ONLY: {setting_cue}. This controls era and location cues only; "
            "it must not change the rough symbolic storyboard medium"
        )
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
    camera = str(beat.get("camera") or "").strip()
    if camera:
        parts.append(f"CAMERA SETUP (source of truth): {camera}")
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
    art_style_id: str = "",
) -> str:
    characters, scene, props = _beat_assets(beat, assets)
    char_lines = []
    primary_selected_look: dict[str, Any] | None = None
    selected_look_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
    legacy_look_id = str(beat.get("character_look_id") or "").strip()
    for character_index, character in enumerate(characters):
        definition = character.get("definition") or {}
        looks = definition.get("looks") or []
        mapped_look_id = str(selected_look_ids.get(str(character.get("id") or "")) or "").strip()
        selected_look_id = mapped_look_id or legacy_look_id
        character_has_selected_look = bool(
            selected_look_id
            and any(
                isinstance(item, dict) and str(item.get("id") or "") == selected_look_id
                for item in looks
            )
        )
        character_selected_look_id = selected_look_id if character_has_selected_look else ""
        look = next(
            (item for item in looks if isinstance(item, dict) and str(item.get("id") or "") == character_selected_look_id),
            looks[0] if looks and isinstance(looks[0], dict) else {},
        )
        if character_has_selected_look and look:
            primary_selected_look = look
        hex_color, color_name = character_marker_color(str(character.get("id") or ""))
        if character_has_selected_look and primary_selected_look:
            char_lines.append(
                " ".join(
                    part
                    for part in (
                        f"{character['name']} (sketch marker {color_name} {hex_color})",
                        f"must match Image {character_index + 2} exactly for face identity, apparent age, hairstyle, body shape, and complete outfit.",
                        str(primary_selected_look.get("appearance_details") or ""),
                        f"Image {character_index + 2} is the sole appearance authority for this character; ignore conflicting default descriptions.",
                    )
                    if part
                )
            )
            continue
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
    visual_id = resolve_visual_style(visual_style)
    art_id = (art_style_id or "").strip()
    modern_beat = _is_modern_beat(beat, primary_selected_look)
    effective_visual_style = visual_id
    effective_art_style = art_id
    if modern_beat and visual_id in {"chinese_period_drama", "republican_era_drama"}:
        effective_visual_style = "modern"
        effective_art_style = "chinese_modern_drama"
    style_prefix = composed_style_line(effective_visual_style, effective_art_style)
    style_name = visual_style_label(effective_art_style) or visual_style_label(effective_visual_style)
    protagonist = next(
        (
            item
            for item in characters
            if isinstance(item.get("definition"), dict) and item["definition"].get("is_main")
        ),
        characters[0] if characters else None,
    )
    protagonist_name = str((protagonist or {}).get("name") or "").strip()
    non_live = (
        is_animation_visual_style(effective_visual_style)
        or effective_visual_style in {"anime", "guoman_fantasy"}
        or normalize_visual_style(effective_art_style) in {"anime", "guoman_fantasy"}
    )
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
    reference_map = [
        "Image 1 is the storyboard sketch and controls composition, crop, poses, and camera angle only."
    ]
    for index, character in enumerate(characters, start=2):
        reference_map.append(
            f"Image {index} is the explicitly selected LOOK for {character['name']} and is the sole authority for that character's face, age, hairstyle, body shape, clothing, colors, and accessories."
        )
    reference_map.append(
        f"Image {len(characters) + 2} is the scene reference and controls environment only."
    )
    parts = [
        "Render this sketch into a high-quality colored production still.",
        "REFERENCE MAP: " + " ".join(reference_map),
        "IDENTITY LOCK (CRITICAL): reproduce every referenced character as the distinct person shown in that character's LOOK image, including facial structure and proportions. Reproduce each complete outfit exactly. Do not redesign, reinterpret, age-shift, replace, merge, or swap characters.",
        "CRITICAL: Keep exact composition from sketch. Only add color, texture, and lighting.",
        (
            "ERA OVERRIDE (CRITICAL): this Beat is contemporary modern-day. Do not add ancient clothing, long historical hair, hair buns, period architecture, or historical props unless explicitly present in the Beat."
            if modern_beat else ""
        ),
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


def _append_https(urls: list[str], value: Any) -> None:
    url = str(value or "").strip()
    if url.startswith(("http://", "https://")) and url not in urls:
        urls.append(url)


def beat_reference_urls(
    beat: dict[str, Any],
    assets: list[dict[str, Any]],
    *,
    stage: str,
    scene_view: str = "front",
) -> list[str]:
    by_id = {item["id"]: item for item in assets if item.get("id")}
    urls: list[str] = []
    scene = resolve_scene_asset(beat, assets)
    if stage == "render":
        _append_https(urls, beat.get("sketch_url"))
        character_ids = [str(item) for item in (beat.get("character_ids") or [])]
        selected_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
        legacy_look_id = str(beat.get("character_look_id") or "").strip()
        for asset_id in character_ids:
            asset = by_id.get(asset_id)
            extra = asset.get("extra") if isinstance((asset or {}).get("extra"), dict) else {}
            identities = extra.get("identities") or []
            selected_look_id = str(selected_ids.get(asset_id) or "").strip()
            if not selected_look_id and legacy_look_id:
                if any(str((look or {}).get("id") or "") == legacy_look_id for look in identities):
                    selected_look_id = legacy_look_id
            selected_look = next(
                (
                    look for look in identities
                    if isinstance(look, dict) and str(look.get("id") or "") == selected_look_id
                ),
                None,
            )
            _append_https(urls, (selected_look or {}).get("image_url"))
        if scene:
            extra = scene.get("extra") if isinstance(scene.get("extra"), dict) else {}
            if scene_view == "reverse":
                _append_https(urls, extra.get("reverse_url"))
            _append_https(urls, extra.get("master_url") or scene.get("image_url"))
        return urls[:9]
    if scene:
        extra = scene.get("extra") if isinstance(scene.get("extra"), dict) else {}
        if scene_view == "reverse":
            _append_https(urls, extra.get("reverse_url"))
        _append_https(urls, extra.get("master_url") or scene.get("image_url"))
    return urls[:9]
