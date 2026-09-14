"""画风合同文本，对齐 source1/app/xiaji_visual_styles.py。"""
from __future__ import annotations

from typing import Any

DEFAULT_VISUAL_STYLE = "chinese_period_drama"

# 前端「风格」下拉值 → 画风合同 id
ART_STYLE_TO_VISUAL: dict[str, str] = {
    "chinese_period_drama": "chinese_period_drama",
    "chinese_modern_drama": "realistic",
    "guoman_fantasy": "guoman_fantasy",
    "anime": "anime",
    "western_realistic": "realistic",
    "western_cartoon": "anime",
}

# 前端「画风」下拉：时代/题材味道，不是整套画风合同
VISUAL_FLAVOR_HINTS: dict[str, str] = {
    "ancient": (
        "ERA/SETTING CUE (古风): traditional ancient Chinese period atmosphere. "
        "Favor period architecture and historical wardrobe cues when the character description allows. "
        "This is an era cue only and must not override the selected art medium (live-action vs 国漫/anime)."
    ),
    "modern": (
        "ERA/SETTING CUE (现代): contemporary modern-day setting and wardrobe unless the character description says otherwise."
    ),
    "fantasy": (
        "ERA/SETTING CUE (奇幻): xianxia / high-fantasy atmosphere, mystical lighting, unless the character description says otherwise."
    ),
    "cyberpunk": (
        "ERA/SETTING CUE (赛博朋克): neon night-city, techwear, rain-slick streets, unless the character description says otherwise."
    ),
    "realistic": (
        "FINISH CUE (写实): grounded photographic finish only if the selected art style is live-action; "
        "do not force live-action if the art style is 国漫 or anime."
    ),
}

ART_STYLE_EXTRA_HINTS: dict[str, str] = {
    "chinese_modern_drama": "Art style: Chinese contemporary live-action TV drama.",
    "western_realistic": "Art style: Western live-action cinematic realism.",
    "western_cartoon": (
        "Art style: Western cartoon / comic illustration, bold graphic shapes, NOT photoreal photography and NOT Japanese anime."
    ),
}

VISUAL_STYLE_PRESETS: dict[str, dict[str, str]] = {
    "chinese_period_drama": {
        "id": "chinese_period_drama",
        "label": "写实古装剧",
        "style_tag": "CINEMATIC FILMIC REALISM, WARM SOFT GRADE",
        "style_family": "live_action",
        "style_instructions": (
            "Create a live-action Chinese period drama image with grounded historical realism when the beat or scene context "
            "calls for a period setting. Use natural lighting appropriate to the time of day with soft realistic falloff and "
            "restrained contrast. Ensure realistic skin texture with visible pores, subtle imperfections, and no beauty-retouching. "
            "Use a natural 50mm cinematic lens feel with moderate depth of field, not glossy fashion photography. Follow the beat, "
            "scene, character, and prop descriptions for exact era, wardrobe, architecture, technology, and materials; do not "
            "override explicit modern, foreign, or traversal-story details. Keep color grading restrained and filmic, avoiding "
            "poster-like polish or painterly haze."
        ),
        "avoid_instructions": (
            "NOT anime, NOT cartoon, NOT illustration. No plastic skin or airbrushed texture. No AI artifacts or oversaturated HDR. "
            "No extra limbs, mutated hands, or deformed faces. No text, watermarks, or labels on image."
        ),
    },
    "anime": {
        "id": "anime",
        "label": "动漫风格",
        "style_tag": "ANIME",
        "style_family": "animation",
        "style_instructions": (
            "Create a high-quality Japanese anime key visual illustration. Style: 2D cel animation with crisp black outlines "
            "(medium weight), flat color fills with 2-layer cel shading (base color + single shadow tone). Eyes: large, detailed "
            "with multi-layer reflections and catchlights. Hair: flowing strands with distinct highlight bands. Background: painted "
            "watercolor-style environment with softer detail than foreground characters. Color palette: vibrant and saturated with "
            "high contrast between light and shadow areas. Render at anime production key frame quality."
        ),
        "avoid_instructions": (
            "FORBIDDEN: photorealistic rendering, 3D CGI, photograph textures. NOT realistic skin pores or film grain. No gradient "
            "shading or soft blending — use FLAT cel-shading only. No watermarks, signatures, or text overlays. No bad anatomy, extra "
            "limbs, or mutated hands."
        ),
    },
    "guoman_fantasy": {
        "id": "guoman_fantasy",
        "label": "3D玄幻国漫",
        "style_tag": "3D GUOMAN FANTASY",
        "style_family": "animation",
        "style_instructions": (
            "Create a premium 3D Chinese fantasy animation image with next-generation realistic CG quality. Use high-precision PBR "
            "materials, cinematic lighting, refined 3D edge light, clean high-definition rendering, and polished Unreal Engine / "
            "Octane style finish. Blend xianxia fantasy, orthodox Dunhuang flying-apsera elegance, new-Chinese minimalist design, "
            "and dark fantasy atmosphere as the preset's default flavor. When character descriptions or reference images do not "
            "specify facial style, favor refined mature 3D Guoman character aesthetics with clear readable facial structure, elegant "
            "proportions, and polished high-end animated-drama modeling. Always follow explicit character descriptions, identity "
            "reference images, scene era, wardrobe, nationality, regional appearance, expression, temperament, and prop descriptions "
            "over these default style flavors."
        ),
        "avoid_instructions": (
            "FORBIDDEN: live-action photography, Western comic style, flat 2D cel anime, chibi, childish face, influencer face, oily "
            "vulgar glamour, cheap web-novel cover look, low-poly game asset, plastic toy texture, wax figure appearance, "
            "over-smoothed skin, excessive HDR, messy ornament overload, deformed hands, extra limbs, broken anatomy, text, labels, "
            "watermarks."
        ),
    },
    "post_apocalyptic": {
        "id": "post_apocalyptic",
        "label": "写实末日风格",
        "style_tag": "DESATURATED GRITTY REALISM, HARSH LIGHT",
        "style_family": "live_action",
        "style_instructions": (
            "Create in PHOTOREALISTIC live-action film style. REAL WORLD scene with REAL PEOPLE — NOT animation, NOT illustration, "
            "NOT CGI. When the beat or scene context calls for a post-apocalyptic setting, use desaturated muted tones, dusty grays "
            "and browns, harsh natural light, weathering, dirt, sweat, cracked concrete, rusted metal, peeling paint, overgrown "
            "vegetation, and practical survival detail. Follow the beat, scene, character, and prop descriptions for exact era, "
            "location, wardrobe, technology, and materials; do not override explicit non-apocalyptic, modern, ancient, foreign, or "
            "traversal-story details."
        ),
        "avoid_instructions": (
            "ABSOLUTELY FORBIDDEN: anime, manga, cartoon, illustrated, or painted styles. NOT CGI, NOT 3D animated. No smooth "
            "flawless skin — must show natural texture and weathering. No text, watermarks, or labels on image."
        ),
    },
    "realistic": {
        "id": "realistic",
        "label": "写实现代",
        "style_tag": "NATURAL PHOTOREALISTIC, CLEAN GRADE",
        "style_family": "live_action",
        "style_instructions": (
            "Create a live-action image with grounded realism. Use natural lighting and restrained contrast, avoiding glossy "
            "fashion-editorial polish. Ensure realistic skin texture with visible pores, subtle imperfections, and no beauty-retouching. "
            "Use a natural 50mm cinematic lens feel with moderate depth of field. Keep the final image photographic and human, with "
            "subtle film grain and controlled color grading. Follow the beat, scene, character, and prop descriptions for exact era, "
            "wardrobe, architecture, technology, and materials."
        ),
        "avoid_instructions": (
            "FORBIDDEN: anime, cartoon, illustration, painting styles. NOT CGI or 3D rendered. No plastic skin, wax figure, or "
            "mannequin appearance. No AI artifacts, uncanny valley effects, or HDR overprocessing. No extra limbs, mutated hands, or "
            "deformed features. No text, watermarks, or labels on image."
        ),
    },
    "republican_era_drama": {
        "id": "republican_era_drama",
        "label": "民国年代剧",
        "style_tag": "VINTAGE FADED FILM, WARM NOSTALGIC GRADE",
        "style_family": "live_action",
        "style_instructions": (
            "Create a live-action Republican-era Chinese drama image with grounded historical realism and a 1920s to 1940s atmosphere "
            "when the beat or scene context calls for it. Use natural lighting appropriate to the time of day with soft realistic "
            "falloff and restrained contrast. Keep the image photographic and human, with realistic skin texture, visible pores, "
            "subtle imperfections, and no beauty-retouching. Use a natural 50mm cinematic lens feel with moderate depth of field. "
            "Follow the beat, scene, character, and prop descriptions for exact era, wardrobe, architecture, technology, and "
            "materials; do not override explicit modern, ancient, foreign, or traversal-story details."
        ),
        "avoid_instructions": (
            "Do not create anime, cartoon, or illustration styles. Never add plastic skin, airbrushed texture, or wax figure "
            "appearance. Ensure no AI artifacts, oversaturated colors, or HDR overprocessing. Do not include extra limbs, mutated "
            "hands, or deformed faces. No text, watermarks, or labels on image."
        ),
    },
}


def normalize_visual_style(*candidates: Any) -> str:
    for item in candidates:
        text = str(item or "").strip()
        if not text:
            continue
        if text in VISUAL_STYLE_PRESETS:
            return text
        mapped = ART_STYLE_TO_VISUAL.get(text, "")
        if mapped in VISUAL_STYLE_PRESETS:
            return mapped
    return ""


def visual_style_preset(style_id: str) -> dict[str, str] | None:
    return VISUAL_STYLE_PRESETS.get(normalize_visual_style(style_id))


def visual_style_label(style_id: str) -> str:
    preset = visual_style_preset(style_id)
    return str((preset or {}).get("label") or "").strip()


def visual_style_contract(style_id: str) -> str:
    preset = visual_style_preset(style_id)
    if not preset:
        return ""
    return " ".join(
        part
        for part in (
            preset.get("style_tag"),
            preset.get("style_instructions"),
            preset.get("avoid_instructions"),
        )
        if part
    )


def is_animation_visual_style(style_id: str) -> bool:
    preset = visual_style_preset(style_id)
    return bool(preset) and preset.get("style_family") == "animation"


def resolve_visual_style(*candidates: Any) -> str:
    return normalize_visual_style(*candidates) or DEFAULT_VISUAL_STYLE
