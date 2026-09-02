from __future__ import annotations

from typing import Any

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
    label = VISUAL_STYLE_LABELS.get((visual_style or "").strip(), "") or (visual_style or "").strip()
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
    visual = (style or str(definition.get("visual_style") or "")).strip()
    race = (ethnicity or str(definition.get("ethnicity") or "")).strip() or "Chinese"
    return visual, race


def character_portrait_prompt(asset: dict[str, Any], *, style: str = "", ethnicity: str = "") -> str:
    definition = asset.get("definition") if isinstance(asset.get("definition"), dict) else {}
    visual, race = _style_and_ethnicity(asset, style=style, ethnicity=ethnicity)
    face = str(definition.get("face_prompt") or "").strip()
    body = str(definition.get("body_type") or "").strip()
    desc = str(definition.get("description") or "").strip()
    name = str(asset.get("name") or "").strip()
    instruction = (
        "single production identity portrait of one character, head and shoulders, "
        "front-facing with a slight three-quarter turn, neutral expression, eyes clearly visible, "
        "even studio lighting, plain mid-gray background, centered, no text, no collage, "
        "no duplicate person, no dramatic pose"
    )
    return ". ".join(
        part for part in (visual_style_prefix(visual), ethnicity_instruction(race), instruction, face, body, desc, name) if part
    )


def character_look_prompt(asset: dict[str, Any], look: dict[str, Any], *, style: str = "", ethnicity: str = "") -> str:
    definition = asset.get("definition") if isinstance(asset.get("definition"), dict) else {}
    visual, race = _style_and_ethnicity(asset, style=style, ethnicity=ethnicity)
    face = str(definition.get("face_prompt") or "").strip()
    look_body = str(look.get("appearance_details") or look.get("name") or "").strip()
    desc = str(definition.get("description") or "").strip()
    instruction = (
        "one clean four-panel production character sheet: panel 1 facial close-up, panel 2 front full-body, "
        "panel 3 three-quarter full-body, panel 4 back full-body. Same face, age, hair and body in every panel. "
        "Neutral standing pose, entire shoes visible, consistent costume, plain light-gray background, "
        "no scenery, no captions, no extra characters"
    )
    return ". ".join(
        part for part in (visual_style_prefix(visual), ethnicity_instruction(race), instruction, face, desc, look_body) if part
    )


def scene_master_prompt(asset: dict[str, Any], *, style: str = "") -> str:
    return scene_view_prompt(asset, "master", style=style, has_master_reference=False)


def scene_view_prompt(
    asset: dict[str, Any],
    view: str,
    *,
    style: str = "",
    has_master_reference: bool = False,
) -> str:
    view = (view or "master").strip() or "master"
    if view == "reverse":
        return _scene_reverse_prompt(asset, style=style, has_master_reference=has_master_reference)
    if view == "panorama":
        return _scene_panorama_prompt(asset, has_master_reference=has_master_reference)
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


def _scene_panorama_prompt(asset: dict[str, Any], *, has_master_reference: bool = False) -> str:
    name = str(asset.get("name") or "").strip() or "the target scene"
    input_role = (
        "INPUT IMAGE ROLE:\n"
        "- Reference image 1 = MASTER VISUAL BIBLE for style, materials, palette, lighting and fixed design.\n"
        "- It is NOT the final camera view. Do NOT copy its single frontal composition.\n"
        "- If a reverse master is also attached, use it as the back-half visual bible."
        if has_master_reference
        else "INPUT:\n- Build the full environment from SCENE DESCRIPTION. Do not output a single frontal wide shot."
    )
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


def _prop_studio_rules() -> str:
    return """PRODUCT PHOTOGRAPHY STYLE:
- Clean white or light gray seamless background
- Soft studio lighting, no harsh shadows
- High detail rendering of materials, textures, and surface finishes
- Professional product shot quality

STRICT REQUIREMENTS:
- NO people, hands, fingers, or living creatures
- Object only, isolated on clean background
- No readable writing anywhere, even if the description mentions a cover title, sign, label, document text, engraving, or lettering
- If text-like markings are necessary, render them as abstract unreadable strokes or blank surface texture
- No labels, panel titles, captions, numbers, arrows, logos, watermarks, or signatures
- Do NOT show the prop being held or worn
- Do NOT add busy or distracting backgrounds"""


def _prop_master_prompt(asset: dict[str, Any], *, style: str = "") -> str:
    return f"""Generate ONE isolated hero product photograph of this story prop.

{_prop_text_block(asset)}

{_prop_style_block(asset, style=style)}

PURPOSE:
- This is the primary visual master for storyboard and first-frame production.
- Show the FRONT / most characteristic face of the prop (主视图): the side that identifies it at a glance.
- Straight-on frontal view of a SINGLE object. Not a turnaround sheet, not a collage, not a 3-panel or 4-panel grid, not a macro crop of one fragment.

COMPOSITION:
- Object centered, filling approximately 70% of the frame.
- One finished product shot only.

{_prop_studio_rules()}
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
            "- Do NOT copy REFERENCE 1 as a single frontal photo; expand it into four aligned angles."
        )
        style_block = (
            "STYLE SOURCE:\n"
            "- Visual style comes ENTIRELY from REFERENCE 1. Match art style, materials, palette and lighting."
        )
    else:
        input_block = "INPUT:\n- No master reference attached. Build all four views from PROP DESCRIPTION only."
        style_block = _prop_style_block(asset, style=style)
    return f"""Generate ONE 2x2 four-panel production turnaround sheet of the SAME story prop.

LAYOUT (2x2, 16:9 overall):
- Four equal unlabeled panels
- Top-left: FRONT view (straight-on main face)
- Top-right: SIDE profile (90-degree, thickness and silhouette)
- Bottom-left: THREE-QUARTER view (about 45 degrees)
- Bottom-right: BACK view (rear straps, seams, closures, ports, worn backside)
- Do not draw panel titles, angle labels, captions, numbers, arrows, or divider text

{input_block}

{style_block}

{_prop_text_block(asset)}

IDENTITY LOCK:
- Identical shape, materials, scale cues and wear in every panel.
- Each panel must be distinguishable by object angle only.

{_prop_studio_rules()}
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
            "- Zoom into its real materials. Do NOT redraw the full object at product-shot distance."
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
- Fill the frame with signature surface details: gems, stitching, weathering, joints, grain, chips, non-text marks.
- This is 细节特写, not a second hero product shot and not a turnaround sheet.
- Keep the same physical object. Do not invent a different prop.

COMPOSITION:
- Macro / ECU framing. The full silhouette may be cropped.
- One coherent close-up, not a collage of many callouts.

{_prop_studio_rules()}
""".strip()


def image_options_for_prop_view(view: str) -> dict[str, Any]:
    if view == "turnaround":
        return {"aspect_ratio": "16:9", "resolution": "1K", "count": 1}
    if view == "detail":
        return {"aspect_ratio": "1:1", "resolution": "1K", "count": 1}
    return {"aspect_ratio": "4:3", "resolution": "1K", "count": 1}


def image_options_for_kind(kind: str) -> dict[str, Any]:
    if kind == "character":
        return {"aspect_ratio": "1:1", "resolution": "1K", "count": 1}
    if kind in {"scene"}:
        return {"aspect_ratio": "16:9", "resolution": "1K", "count": 1}
    if kind in {"sketch", "render"}:
        return {"aspect_ratio": "2:3", "resolution": "1K", "count": 1}
    return {"aspect_ratio": "4:3", "resolution": "1K", "count": 1}
