from __future__ import annotations

import hashlib
from typing import Any

from .xiaji_art_style import art_style_prefix, definition_art_style_id, is_animation_art_style

VISUAL_STYLE_LABELS = {
    "chinese_period_drama": "写实古装剧",
    "anime": "动漫",
    "guoman_fantasy": "国漫奇幻",
    "post_apocalyptic": "末世废土",
    "realistic": "写实",
    "republican_era_drama": "民国剧",
}

VOICE_SLOT_LABELS = {
    "default": "默认（兜底）",
    "child": "幼年",
    "youth": "青年",
    "middle": "中年",
    "elder": "老年",
}

VOICE_SLOTS = tuple(VOICE_SLOT_LABELS.keys())

VOICE_DEFINE_PROMPT = """你是影视配音导演。根据角色资料写一条可执行的声线定义，只返回 JSON。

字段：
1. language: 配音语言（如 中文普通话）
2. timbre: 音色（如 清亮女声、沉稳男中音）
3. pitch: 音高（偏高 / 适中 / 偏低）
4. speaking_style: 说话方式（节奏、气息、情绪底色）
5. sample_line: 一句 15 字以内的试听对白，符合角色口吻
6. tts_voice: 从 alloy / echo / fable / onyx / nova / shimmer 选一个最接近的合成音色
7. prompt: 给配音演员或 TTS 的完整口头说明（80 字以内）

规则：不要写画面；不要编造原文没有的身份。"""


def visual_style_prefix(visual_style: str) -> str:
    prefix = art_style_prefix(visual_style)
    if prefix:
        return prefix
    label = VISUAL_STYLE_LABELS.get((visual_style or "").strip(), "")
    if not label:
        return ""
    return f"cinematic still in {label} visual style"


def ethnicity_instruction(ethnicity: str) -> str:
    value = (ethnicity or "").strip() or "Chinese"
    return (
        f"Default ethnicity for people in this image: {value}. "
        "If the character description already names another origin, follow that description."
    )


def _style_and_ethnicity(asset: dict[str, Any], *, style: str = "", ethnicity: str = "") -> tuple[str, str]:
    definition = asset.get("definition") if isinstance(asset.get("definition"), dict) else {}
    visual = (style or definition_art_style_id(definition) or str(definition.get("visual_style") or "")).strip()
    race = (ethnicity or str(definition.get("ethnicity") or "")).strip() or "Chinese"
    return visual, race


def character_portrait_prompt(
    asset: dict[str, Any],
    *,
    style: str = "",
    ethnicity: str = "",
    has_style_reference: bool = False,
) -> str:
    definition = asset.get("definition") if isinstance(asset.get("definition"), dict) else {}
    visual, race = _style_and_ethnicity(asset, style=style, ethnicity=ethnicity)
    face = str(definition.get("face_prompt") or "").strip()
    body = str(definition.get("body_type") or "").strip()
    desc = str(definition.get("description") or "").strip()
    name = str(asset.get("name") or "").strip()
    instruction = (
        "single production identity portrait of one character, head and shoulders, "
        "front-facing with a slight three-quarter turn, neutral expression, eyes clearly visible, "
        "centered, no text, no collage, no duplicate person, no dramatic pose"
    )
    style_ref = ""
    if has_style_reference:
        style_ref = (
            "The first attached image is REFERENCE 1, the mandatory art-style and color bible. "
            "Match its color palette, hue, saturation, color temperature, lighting, medium and rendering exactly. "
            "Do not shift toward gray studio lighting, a cooler grade, or any other palette. "
            "Keep identity-portrait framing; do not copy any person, face, costume or composition from that sample."
        )
    else:
        instruction = (
            f"{instruction}, even studio lighting, plain mid-gray background"
        )
    return ". ".join(
        part
        for part in (
            visual_style_prefix(visual),
            ethnicity_instruction(race),
            style_ref,
            instruction,
            face,
            body,
            desc,
            name,
        )
        if part
    )


def _character_tag(name: str) -> str:
    value = (name or "").strip() or "character"
    suffix = hashlib.md5(value.encode("utf-8")).hexdigest()[:4]
    return f"[{value}_{suffix}]"


def _animation_medium_phrase(visual_style: str) -> str:
    label = (visual_style or "").strip()
    if label == "guoman_fantasy" or "国漫" in label:
        return "stylized hybrid mixed-media animated character rendering"
    return "stylized 2D animated character rendering"


def look_costume_text(look: dict[str, Any]) -> str:
    return str(look.get("appearance_details") or "").strip()


def image_options_for_look() -> dict[str, Any]:
    return {"aspect_ratio": "16:9", "resolution": "1K", "count": 1}


def character_look_prompt(
    asset: dict[str, Any],
    look: dict[str, Any],
    *,
    style: str = "",
    ethnicity: str = "",
    has_costume_reference: bool = False,
) -> str:
    visual, _race = _style_and_ethnicity(asset, style=style, ethnicity=ethnicity)
    name = str(asset.get("name") or "").strip() or "未命名角色"
    tag = _character_tag(name)
    costume = look_costume_text(look)
    style_line = visual_style_prefix(visual)
    costume_block = ""
    if has_costume_reference:
        costume_block = """
COSTUME REFERENCE IMAGE (CRITICAL):
A second reference image is provided showing the target costume/clothing.
- MATCH the clothing, fabric, accessories, colors, and styling from the costume reference image EXACTLY
- The costume reference takes PRIORITY over the text description for visual details
- Combine the FACE from the identity anchor (first reference) with the CLOTHING from the costume reference (second reference)
"""
    details = costume if costume and not has_costume_reference else ""
    if is_animation_art_style(visual) or visual in {"anime", "guoman_fantasy"}:
        medium = _animation_medium_phrase(visual)
        return f"""Animated character turnaround / identity sheet. Neutral presentation setup.
PLAIN SOLID WHITE or LIGHT GRAY background ONLY — no environment, no scenery, no props. {style_line}

Using the reference image as IDENTITY ANCHOR for {tag} ({name}),
create a 4-panel animated character reference sheet arranged LEFT to RIGHT:

- Panel 1 (LEFT): FACE CLOSEUP — head and shoulders, filling the panel
- Panel 2 (CENTER-LEFT): FRONT full body — head to feet, standing pose, facing camera
- Panel 3 (CENTER-RIGHT): THREE-QUARTER VIEW full body — head to feet, body rotated about 45 degrees
- Panel 4 (RIGHT): BACK VIEW full body — head to feet, facing away from camera

IDENTITY LOCKING (CRITICAL):
Preserve the same character identity EXACTLY from the reference image:
- face shape and proportions
- eye shape and spacing
- nose and mouth shape
- hairline, hairstyle, and silhouette
- skin tone and age impression
- Preserve the reference identity exactly; do not change face structure, skin tone, hair identity, or silhouette.

CHARACTER DETAILS (CRITICAL - use this for clothing and appearance):
{details}
{costume_block}
PRESENTATION RULES:
- Final medium must be {medium}
- All 4 panels must keep the same character, same outfit, same hair, same proportions
- Panel 1 must visually match Panel 2's head area
- Panels 2-4 must show a complete figure from head to feet
- Plain neutral production-reference background only

STRICT REQUIREMENTS (MUST AVOID):
- Do not allow facial feature drift from reference
- Do not mix rendering families or switch back to realistic actor rendering
- Do not include multiple characters
- No text, labels, or panel numbers on the image
- Do not add environment scenery, props, or poster composition
""".strip()

    return f"""Character identity reference sheet. Neutral studio setup.
PLAIN SOLID WHITE or LIGHT GRAY background ONLY — no environment, no scenery, no props. {style_line}

Using the reference image as IDENTITY ANCHOR for {tag} ({name}),
create a 4-panel character reference sheet arranged LEFT to RIGHT:

- Panel 1 (LEFT): FACE CLOSEUP — head and shoulders, filling the panel. This is a zoomed-in crop of Panel 2's head: SAME hairstyle, SAME visible clothing (neckline, collar, shoulders)
- Panel 2 (CENTER-LEFT): FRONT full body — head to feet, standing pose, facing camera
- Panel 3 (CENTER-RIGHT): THREE-QUARTER VIEW full body — head to feet, body rotated approximately 45 degrees from the left, both eyes still visible, standing pose
- Panel 4 (RIGHT): BACK VIEW full body — head to feet, facing away from camera, showing back of head and body

IDENTITY LOCKING (CRITICAL):
Preserve the facial structure, facial proportions, and overall likeness
of {tag} EXACTLY as in the reference image, allowing NO alteration,
stylization, or reinterpretation of the face under any circumstance.

MUST PRESERVE (from reference):
- Facial structure and bone structure
- Eye shape, size, spacing, color
- Nose shape and size
- Lip shape and fullness
- Skin tone
- Hair color, style, texture
- Preserve the reference identity exactly; do not change face structure, skin tone, hair identity, or silhouette.

DO NOT PRESERVE FROM REFERENCE:
- Beauty-filter smoothing or retouching
- Plastic / waxy / overly perfect skin treatment
- Any rendering finish that conflicts with the selected project style preset
- The final rendering medium should follow the project style preset, not the reference image

CHARACTER DETAILS (CRITICAL - use this for clothing and appearance):
{details}
{costume_block}
BACKGROUND (CRITICAL — STRICTLY ENFORCED):
- ALL 4 panels MUST have a PLAIN SOLID-COLOR background (white, light gray, or soft neutral gradient)
- Do NOT render ANY environment: no rooms, no furniture, no walls, no floors, no scenery
- This is a production character identity reference sheet, not a fashion catalog, not a glossy poster

FULL BODY FRAMING (Panels 2-4):
- MUST show COMPLETE figure from top of head to bottom of feet including shoes
- Standing in neutral pose on a visible ground line
- Ample space above head and below feet
- Do NOT crop any body part

CONSISTENCY:
- ALL 4 panels = SAME person, SAME outfit, SAME hair
- Panel 1 is a ZOOMED-IN CROP of Panel 2's head area — hairstyle, neckline, collar, and shoulder clothing MUST be identical
- Panel 1 face MUST match Panels 2-3 face exactly
- Panel 4 shows the SAME person from behind — SAME hair, SAME outfit, SAME body proportions
- Only viewing angle changes between Panel 2 (front), Panel 3 (three-quarter), and Panel 4 (back)

STRICT REQUIREMENTS (MUST AVOID):
- Do not allow ANY facial feature drift from reference.
- Do not mix styles or reinterpret the character.
- Do not include multiple characters.
- No text, labels, or panel numbers on the image
- Do NOT create beauty-retouched, glamorized, cosmetic-ad, or fashion-editorial output
- Keep the project style consistent across all 4 panels
""".strip()


def scene_master_prompt(asset: dict[str, Any], *, style: str = "") -> str:
    return scene_view_prompt(asset, "master", style=style, has_master_reference=False)


def scene_view_prompt(
    asset: dict[str, Any],
    view: str,
    *,
    style: str = "",
    has_master_reference: bool = False,
    has_reverse_reference: bool = False,
) -> str:
    view = (view or "master").strip() or "master"
    if view == "reverse":
        return _scene_reverse_prompt(asset, style=style, has_master_reference=has_master_reference)
    if view == "panorama":
        return _scene_panorama_prompt(
            asset,
            has_master_reference=has_master_reference,
            has_reverse_reference=has_reverse_reference,
        )
    return _scene_front_prompt(asset, style=style)


def _scene_text_block(asset: dict[str, Any]) -> str:
    definition = asset.get("definition") if isinstance(asset.get("definition"), dict) else {}
    name = str(asset.get("name") or "").strip() or "未命名场景"
    scene_type = str(definition.get("scene_type") or "interior").strip() or "interior"
    time_of_day = str(definition.get("time_of_day") or "").strip()
    description = str(
        definition.get("environment_prompt") or definition.get("description") or ""
    ).strip()
    lines = [
        f"SCENE NAME: {name}",
        f"SCENE TYPE: {scene_type}",
    ]
    if time_of_day:
        lines.append(f"TARGET TIME-OF-DAY PLATE: {time_of_day}")
    lines.append("SCENE DESCRIPTION:")
    lines.append(description or name)
    return "\n".join(lines)


def _scene_front_prompt(asset: dict[str, Any], *, style: str = "") -> str:
    visual, _race = _style_and_ethnicity(asset, style=style)
    style_line = visual_style_prefix(visual)
    style_block = f"PROJECT STYLE PRESET:\n- {style_line}" if style_line else ""
    return f"""Generate ONE master reference image for this scene.

{_scene_text_block(asset)}

{style_block}

PURPOSE:
- This image is the primary visual master for storyboard, render, and first-frame production.
- Spatial coverage: the front-facing 180-degree half of the scene (front center plus roughly half of the left side and half of the right side).
- Keep a clean canonical front-facing wide scene reference.

ANCHOR THE FRONT WALL FROM THE TEXT:
- Read SCENE DESCRIPTION for 正面 / front side / 主面 / 主入口 / 正前方.
- Whatever the text describes as the FRONT (正面) is the wall the camera looks at.
- If the text says "正面是 X", X is the main feature across the back of the frame.
- Do NOT swap front and back. Labels 背面 / 后面 are BEHIND the camera and must not appear.
- Labels 左侧 / 右侧 are side zones visible as partial left/right coverage.

COMPOSITION:
- Canonical FRONT-FACING establishing angle. Eye-level horizon.
- No back view, no rear angle, no aerial, no fisheye, no VR, no 360 panorama.
- Wide establishing framing with about 160-180 degrees of horizontal coverage.

HARD REQUIREMENTS:
- FRONT-FACING HALF ONLY.
- No people, no characters, no temporary story props.
- Preserve only fixed environment objects.
- No readable text, labels, UI, watermarks, collage, floorplan, or diagrams.
- Output one finished scene reference image only.
""".strip()


def _scene_reverse_prompt(
    asset: dict[str, Any],
    *,
    style: str = "",
    has_master_reference: bool = False,
) -> str:
    definition = asset.get("definition") if isinstance(asset.get("definition"), dict) else {}
    scene_type = str(definition.get("scene_type") or "").strip().lower()
    is_exterior = scene_type in {"exterior", "outdoor", "outside", "室外", "street", "nature"}
    space_word = "location" if is_exterior else "room"
    back_word = "back side / opposite side of the location" if is_exterior else "back wall"
    location_word = "outdoor location" if is_exterior else "interior space"
    if has_master_reference:
        style_block = (
            "STYLE SOURCE:\n"
            "- Visual style comes ENTIRELY from REFERENCE 1 (the front master). "
            "Match its art style, materials, palette, lighting and exposure. "
            "Do not re-derive style from text."
        )
        input_block = f"""INPUT IMAGE:
- REFERENCE 1 = the FRONT-FACING master of this {space_word}.
- It covers front center plus roughly half of left and right. It does NOT show the back-facing half.
- You are showing what is BEHIND REFERENCE 1's camera after a 180-degree yaw.
- Do NOT copy REFERENCE 1's front-center composition."""
    else:
        visual, _race = _style_and_ethnicity(asset, style=style)
        style_line = visual_style_prefix(visual)
        style_block = f"PROJECT STYLE PRESET:\n- {style_line}" if style_line else ""
        input_block = "INPUT:\n- No master reference attached. Build the reverse view from SCENE DESCRIPTION only."
    return f"""Generate ONE reverse-angle establishing image of the SAME {location_word}.

Stand where the front master camera stood, then yaw-rotate 180 degrees to face the {back_word}.
The two views are the SAME {space_word} at the SAME moment.

{input_block}

{style_block}

{_scene_text_block(asset)}

COMPOSITION:
- Eye-level horizon, wide ~160-180° coverage: back center plus half of left and right.
- Camera faces the {back_word} (SCENE DESCRIPTION 背面 / back / 后).
- If the text says "背面是 X", X is the focal content of this image.
- The front-facing subject of the master is now behind the camera and should not dominate this frame.

REQUIRED EDGE OVERLAP:
- Reverse LEFT edge must connect to the same physical side as master's RIGHT edge.
- Reverse RIGHT edge must connect to the same physical side as master's LEFT edge.

CENTER REGION:
- Show what is behind the master's camera. Fill from 背面 notes. Do not invent objects absent from text and master.

HARD REQUIREMENTS:
- Eye-level wide rectilinear perspective. NO fisheye, NO equirectangular panorama, NO 360 unwrap, NO floorplan, NO collage.
- 16:9 aspect ratio. One finished establishing image.
- No people, no readable text, labels, or watermarks.
""".strip()


def _scene_panorama_prompt(
    asset: dict[str, Any],
    *,
    has_master_reference: bool = False,
    has_reverse_reference: bool = False,
) -> str:
    name = str(asset.get("name") or "").strip() or "the target scene"
    reference_lines = ["INPUT IMAGE ROLES:"]
    if has_master_reference:
        reference_lines.extend(
            [
                "- Reference image 1 (master.png) = PRIMARY VISUAL BIBLE.",
                "- It locks the scene identity, art style, materials, palette, lighting and front-half fixtures.",
                "- It shows the FRONT-FACING HEMISPHERE: front center plus visible left and right halves.",
                "- It does NOT show the back hemisphere behind the camera.",
                "- Preserve the visual DNA of master.png. Expand the same location into 360 degrees.",
            ]
        )
    if has_reverse_reference:
        reverse_index = 2 if has_master_reference else 1
        reference_lines.extend(
            [
                f"- Reference image {reverse_index} (reverse_master.png) = BACK-HALF VISUAL BIBLE.",
                "- It locks the BACK-FACING HEMISPHERE of the same scene.",
                "- Stitch with master.png: reverse left edge connects to master right edge,",
                "  reverse right edge connects to master left edge.",
                "- It is the exact yaw-180 opposite of master, not another forward view.",
                "- Do NOT invent a different back side when reverse_master.png is attached.",
            ]
        )
    if not has_master_reference and not has_reverse_reference:
        reference_lines.extend(
            [
                "- No image reference is attached.",
                "- Build the full environment from SCENE DESCRIPTION. Do not output a single frontal wide shot.",
            ]
        )
    input_role = "\n".join(reference_lines)
    return f"""Generate a 360-degree equirectangular panorama image in exact 2:1 aspect ratio for scene `{name}`.

{input_role}

{_scene_text_block(asset)}

LAYER MODE: FULL ENVIRONMENT
- Complete environment and fixed fixtures only. No people, no story action, no temporary props.

PROJECTION REQUIREMENTS:
- Correct equirectangular spherical panorama, one continuous 2:1 image for a VR/360 viewer.
- Camera fixed at scene center at human eye height. Full 360-degree environment.
- Left and right edges must connect with no visible seam. Horizon level and centered.
- No single flat wide shot, no cubemap atlas, no borders, no multi-panel sheet.

NEGATIVE REQUIREMENTS:
- Not a normal wide-angle illustration. Not fisheye. Not cubemap faces.
- No labels, UI, watermark, broken seam, duplicated doorway at seam, or mirrored halves.
""".strip()


def image_options_for_scene_view(view: str) -> dict[str, Any]:
    if view == "panorama":
        return {"aspect_ratio": "2:1", "resolution": "1K", "count": 1}
    return {"aspect_ratio": "16:9", "resolution": "1K", "count": 1}


def prop_reference_prompt(asset: dict[str, Any], *, style: str = "") -> str:
    return prop_view_prompt(asset, "master", style=style, has_master_reference=False)


def prop_view_prompt(
    asset: dict[str, Any],
    view: str,
    *,
    style: str = "",
    has_master_reference: bool = False,
) -> str:
    view = (view or "master").strip() or "master"
    if view == "turnaround":
        return _prop_turnaround_prompt(asset, style=style, has_master_reference=has_master_reference)
    if view == "detail":
        return _prop_detail_prompt(asset, style=style, has_master_reference=has_master_reference)
    return _prop_master_prompt(asset, style=style)


def _prop_text_block(asset: dict[str, Any]) -> str:
    definition = asset.get("definition") if isinstance(asset.get("definition"), dict) else {}
    name = str(asset.get("name") or "").strip() or "未命名道具"
    prop_type = str(definition.get("prop_type") or "object").strip() or "object"
    owner = str(definition.get("owner") or "").strip()
    visual_prompt = str(definition.get("visual_prompt") or "").strip()
    description = str(definition.get("description") or "").strip()
    lines = [
        f"PROP NAME: {name}",
        f"PROP TYPE: {prop_type}",
    ]
    if owner:
        lines.append(f"OWNER / WIELDER: {owner}")
    lines.append("PROP DESCRIPTION:")
    lines.append(visual_prompt or description or name)
    if description and visual_prompt and description != visual_prompt:
        lines.append("STORY NOTES:")
        lines.append(description)
    return "\n".join(lines)


def _prop_style_block(asset: dict[str, Any], *, style: str = "") -> str:
    visual, _race = _style_and_ethnicity(asset, style=style)
    style_line = visual_style_prefix(visual)
    return f"VISUAL STYLE:\n{style_line}" if style_line else ""


def _prop_studio_rules(*, multi_panel: bool = False) -> str:
    fill = "each panel" if multi_panel else "the frame"
    consistency = ""
    if multi_panel:
        consistency = (
            "- Each panel must be distinguishable by object angle only, never by written labels\n"
            "- Consistent lighting, scale, silhouette, and material identity across all three panels\n"
        )
    return f"""PRODUCT PHOTOGRAPHY STYLE:
- Clean white or light gray seamless background
- Soft studio lighting, no harsh shadows
- Object centered, filling approximately 70% of {fill}
- High detail rendering of materials, textures, and surface finishes
- Professional product shot quality

STRICT REQUIREMENTS:
- NO people, hands, fingers, or living creatures
- Object only, isolated on clean background
{consistency}- Show fine details: gems, stitching, weathering, non-text surface marks, etc.
- No readable writing anywhere, even if the description mentions a cover title, sign, label, document text, engraving, or lettering
- If text-like markings are necessary for the prop design, render them as abstract unreadable strokes or blank surface texture

MUST AVOID:
- Do NOT add text, labels, panel titles, captions, numbers, arrows, logos, watermarks, signatures, readable letters, Chinese characters, or English words
- Do NOT include any people, hands, or body parts
- Do NOT show the prop being held or worn
- Do NOT add busy or distracting backgrounds"""


def _prop_master_prompt(asset: dict[str, Any], *, style: str = "") -> str:
    return f"""Generate ONE isolated FRONT product photograph of this story prop.

{_prop_text_block(asset)}

{_prop_style_block(asset, style=style)}

PURPOSE:
- This is the primary visual master (主视图): the FRONT / most characteristic face of the prop.
- Straight-on frontal view of a SINGLE object, showing its face/main side.
- Not a 3-PANEL sheet, not a collage, not a 4-panel grid, not a macro crop of one fragment.

COMPOSITION:
- 16:9 overall. Object centered, filling approximately 70% of the frame.
- One finished product shot only.

{_prop_studio_rules(multi_panel=False)}
""".strip()


def _prop_turnaround_prompt(
    asset: dict[str, Any],
    *,
    style: str = "",
    has_master_reference: bool = False,
) -> str:
    if has_master_reference:
        input_block = (
            "INPUT IMAGE:\n"
            "- REFERENCE 1 = the FRONT hero master of this same prop.\n"
            "- Keep identical silhouette, materials, wear, palette and construction.\n"
            "- Do NOT copy REFERENCE 1 as a single frontal photo; expand it into the 1x3 three-panel sheet."
        )
        style_block = (
            "STYLE SOURCE:\n"
            "- Visual style comes ENTIRELY from REFERENCE 1. Match art style, materials, palette and lighting."
        )
    else:
        input_block = "INPUT:\n- No master reference attached. Build the three-panel sheet from PROP DESCRIPTION only."
        style_block = _prop_style_block(asset, style=style)
    return f"""Generate a 3-PANEL product reference sheet for a story prop.

LAYOUT (1x3, 16:9 overall):
- Three equal unlabeled panels arranged left to right
- Left panel: front view
- Middle panel: side profile
- Right panel: back view
- Do not draw panel titles, angle labels, captions, numbers, arrows, or divider text

{input_block}

{style_block}

{_prop_text_block(asset)}

FRONT VIEW: Straight-on frontal view of the prop, showing its face/main side
SIDE PROFILE: 90-degree side view showing the prop's profile and thickness
BACK VIEW: Straight-on rear view of the same prop, showing rear-side details, straps, seams, closures, ports, or worn backside surfaces

{_prop_studio_rules(multi_panel=True)}
""".strip()


def _prop_detail_prompt(
    asset: dict[str, Any],
    *,
    style: str = "",
    has_master_reference: bool = False,
) -> str:
    if has_master_reference:
        input_block = (
            "INPUT IMAGE:\n"
            "- REFERENCE 1 = the FRONT hero master of this same prop.\n"
            "- Zoom into its real materials. Do NOT redraw the full object at product-shot distance, and do not make a 3-PANEL sheet."
        )
        style_block = (
            "STYLE SOURCE:\n"
            "- Match REFERENCE 1 materials, palette, wear and construction exactly."
        )
    else:
        input_block = "INPUT:\n- No master reference attached. Invent the close-up from PROP DESCRIPTION only."
        style_block = _prop_style_block(asset, style=style)
    return f"""Generate ONE extreme close-up / macro detail still of this story prop.

{input_block}

{style_block}

{_prop_text_block(asset)}

PURPOSE:
- This is 细节特写: fill the frame with signature surface details (gems, stitching, weathering, joints, grain, chips, non-text marks).
- Not a second full-object hero shot and not a 3-PANEL reference sheet.
- Keep the same physical object. Do not invent a different prop.

COMPOSITION:
- 16:9 overall. Macro / ECU framing. The full silhouette may be cropped.
- One coherent close-up, not a collage of many callouts.

{_prop_studio_rules(multi_panel=False)}
""".strip()


def image_options_for_prop_view(view: str) -> dict[str, Any]:
    return {"aspect_ratio": "16:9", "resolution": "1K", "count": 1}


def image_options_for_kind(kind: str) -> dict[str, Any]:
    if kind == "character":
        return {"aspect_ratio": "1:1", "resolution": "1K", "count": 1}
    if kind in {"scene"}:
        return {"aspect_ratio": "16:9", "resolution": "1K", "count": 1}
    if kind in {"sketch", "render"}:
        return {"aspect_ratio": "2:3", "resolution": "1K", "count": 1}
    return {"aspect_ratio": "16:9", "resolution": "1K", "count": 1}
