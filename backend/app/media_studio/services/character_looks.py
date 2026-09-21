"""角色造型时代匹配：穿越剧需要现代/古代两套设定板。"""
from __future__ import annotations

import re
from typing import Any

ERA_MODERN_RE = re.compile(r"现代|当代|21世纪|大学|图书馆|电脑|白领|硕士|衬衫|西装|研究生|26岁")
ERA_ANCIENT_RE = re.compile(r"古代|茅屋|长衫|粗布|发髻|陶碗|木床|土墙|米缸|17岁")
LOOK_MODERN_RE = re.compile(r"现代|当代|西装|衬衫|研究生|硕士|26岁")
LOOK_ANCIENT_RE = re.compile(r"古代|长衫|粗布|发髻|17岁")
MODERN_AGE_RE = re.compile(r"现代\s*(\d+\s*岁)")

_BEAT_PRIMARY_KEYS = ("heading", "scene", "speaker", "characters")
_BEAT_FULL_KEYS = (
    "heading", "action", "visual_prompt", "video_prompt_zh", "scene", "speaker", "characters",
)


def look_text(item: dict[str, Any] | None) -> str:
    item = item if isinstance(item, dict) else {}
    return " ".join(str(item.get(key) or "") for key in ("name", "description", "appearance_details", "visual_prompt"))


def looks_with_images(character: dict[str, Any]) -> list[dict[str, Any]]:
    extra = character.get("extra") if isinstance(character.get("extra"), dict) else {}
    return [
        item for item in (extra.get("identities") or [])
        if isinstance(item, dict) and str(item.get("image_url") or "").strip()
    ]


def classify_era(text: str, *, for_look: bool = False) -> str:
    blob = str(text or "")
    modern_re = LOOK_MODERN_RE if for_look else ERA_MODERN_RE
    ancient_re = LOOK_ANCIENT_RE if for_look else ERA_ANCIENT_RE
    modern = bool(modern_re.search(blob))
    ancient = bool(ancient_re.search(blob))
    if modern and ancient:
        return "mixed"
    if modern:
        return "modern"
    if ancient:
        return "ancient"
    return "neutral"


def beat_context(beat: dict[str, Any], *, primary: bool = False) -> str:
    keys = _BEAT_PRIMARY_KEYS if primary else _BEAT_FULL_KEYS
    parts: list[str] = []
    for key in keys:
        value = beat.get(key)
        if isinstance(value, list):
            parts.extend(str(item or "") for item in value)
        else:
            parts.append(str(value or ""))
    return " ".join(parts)


def beat_era(beat: dict[str, Any]) -> str:
    primary = classify_era(beat_context(beat, primary=True))
    if primary in {"modern", "ancient"}:
        return primary
    if primary == "mixed":
        return "modern" if ERA_MODERN_RE.search(beat_context(beat, primary=True)) else "ancient"
    full = classify_era(beat_context(beat))
    if full == "mixed":
        return "modern" if ERA_MODERN_RE.search(beat_context(beat)) else "ancient"
    return full


def is_modern_context(text: str) -> bool:
    return classify_era(text) in {"modern", "mixed"}


def look_covers_era(look: dict[str, Any], era: str) -> bool:
    classified = classify_era(look_text(look), for_look=True)
    if era not in {"modern", "ancient"}:
        return True
    if classified == era or classified in {"neutral", "mixed"}:
        return True
    return False


def character_in_beat(character: dict[str, Any], beat: dict[str, Any]) -> bool:
    cid = str(character.get("id") or "")
    name = str(character.get("name") or "").strip()
    ids = [str(item) for item in (beat.get("character_ids") or [])]
    if cid and cid in ids:
        return True
    if name and name in beat_context(beat):
        return True
    return False


def needed_eras(character: dict[str, Any], beats: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for beat in beats or []:
        if not isinstance(beat, dict) or not character_in_beat(character, beat):
            continue
        era = beat_era(beat)
        if era in {"modern", "ancient"}:
            found.add(era)
    return found


def select_character_look(character: dict[str, Any], beat: dict[str, Any]) -> dict[str, Any] | None:
    looks = looks_with_images(character)
    selected_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
    selected_look_id = str(selected_ids.get(str(character.get("id") or "")) or "").strip()
    if selected_look_id:
        return next((item for item in looks if str(item.get("id") or "") == selected_look_id), None)
    legacy_look_id = str(beat.get("character_look_id") or "").strip()
    if legacy_look_id:
        legacy = next((item for item in looks if str(item.get("id") or "") == legacy_look_id), None)
        if legacy:
            return legacy
    context = beat_context(beat)
    modern = bool(ERA_MODERN_RE.search(context))
    ancient = bool(ERA_ANCIENT_RE.search(context))
    if modern:
        return next((item for item in looks if LOOK_MODERN_RE.search(look_text(item))), None)
    if ancient:
        return next((item for item in looks if LOOK_ANCIENT_RE.search(look_text(item))), None)
    return looks[0] if len(looks) == 1 else None


def character_look_image_url(character: dict[str, Any] | None, beat: dict[str, Any]) -> str:
    """URL for the look that should be uploaded. Never pick the other era's first identity."""
    if not isinstance(character, dict):
        return ""
    look = select_character_look(character, beat)
    url = str((look or {}).get("image_url") or "").strip()
    if url:
        return url
    if looks_with_images(character):
        return ""
    extra = character.get("extra") if isinstance(character.get("extra"), dict) else {}
    return str(extra.get("avatar_url") or character.get("image_url") or "").strip()


def apply_resolved_looks_to_beat(beat: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, str]:
    """Fill missing character_look_ids from era match. Does not overwrite an explicit pick."""
    by_id = {str(item.get("id") or ""): item for item in assets if item.get("id")}
    look_ids = dict(beat.get("character_look_ids") or {}) if isinstance(beat.get("character_look_ids"), dict) else {}
    changed = False
    for cid in [str(item) for item in (beat.get("character_ids") or []) if str(item)]:
        if str(look_ids.get(cid) or "").strip():
            continue
        character = by_id.get(cid)
        if not character:
            continue
        look = select_character_look(character, beat)
        look_id = str((look or {}).get("id") or "").strip()
        if not look_id:
            continue
        look_ids[cid] = look_id
        changed = True
    if changed:
        beat["character_look_ids"] = look_ids
    return look_ids if isinstance(look_ids, dict) else {}


def _short_look_desc(look: dict[str, Any]) -> str:
    text = str(look.get("description") or look.get("appearance_details") or look.get("name") or "").strip()
    text = re.sub(r"\s+", "", text)
    return text[:18] + ("…" if len(text) > 18 else "")


def _beat_era_hint(beat: dict[str, Any]) -> str:
    for key in ("scene", "speaker", "heading"):
        value = str(beat.get(key) or "").strip()
        if value:
            return value[:24]
    return ""


def missing_look_message(
    character: dict[str, Any],
    beat: dict[str, Any],
    sequence: int,
    *,
    selected_look_id: str = "",
) -> str:
    name = str(character.get("name") or "角色")
    if selected_look_id:
        return f"Beat {sequence} 为「{name}」选择的造型无效，请重新选择"
    base = f"Beat {sequence} 缺少符合时代/年龄/服装的「{name}」造型图"
    era = beat_era(beat)
    era_label = {"modern": "现代", "ancient": "古代"}.get(era, "")
    extra = character.get("extra") if isinstance(character.get("extra"), dict) else {}
    identities = [item for item in (extra.get("identities") or []) if isinstance(item, dict)]
    pending = [
        item for item in identities
        if era in {"modern", "ancient"}
        and look_covers_era(item, era)
        and not str(item.get("image_url") or "").strip()
    ]
    existing = looks_with_images(character)
    details: list[str] = []
    hint = _beat_era_hint(beat)
    if era_label:
        details.append(f"本镜偏{era_label}" + (f"（{hint}）" if hint else ""))
    if existing:
        look = existing[0]
        label = str(look.get("name") or "").strip() or "现有设定板"
        desc = _short_look_desc(look)
        details.append(f"现有设定板是「{label}」" + (f"{desc}" if desc else ""))
    if pending:
        details.append(f"请到资产库生成「{pending[0].get('name') or '对应造型'}」设定板")
    elif existing:
        details.append("请到资产库补一套对应造型并生成设定板，或在镜头检视器中指定已有造型")
    else:
        details.append("请先到资产库生成造型图")
    return base + "（" + "；".join(part for part in details if part) + "）"


def _existing_ids(identities: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("id") or "") for item in identities if str(item.get("id") or "")}


def _modern_seed(character: dict[str, Any], beats: list[dict[str, Any]]) -> dict[str, Any]:
    name = str(character.get("name") or "角色").strip() or "角色"
    extra = character.get("extra") if isinstance(character.get("extra"), dict) else {}
    age = "26岁"
    for beat in beats:
        if not character_in_beat(character, beat):
            continue
        match = MODERN_AGE_RE.search(beat_context(beat, primary=True))
        if match:
            age = re.sub(r"\s+", "", match.group(1))
            break
    gender = str(extra.get("gender") or character.get("gender") or "").strip()
    person = "女性" if gender in {"女", "female"} else "男性"
    description = (
        f"{age}现代都市{person}，短发，白色衬衫，当代休闲着装。"
        f"与「{name}」古代造型同一人，五官一致，按现代年龄与服装。"
    )
    visual_prompt = (
        f"{age}中国当代青年{person}，清瘦高挑，清秀脸庞，剑眉，沉静眼神，短发，"
        "白色衬衫，当代休闲着装，写实电影质感"
    )
    suffix = str(character.get("id") or "look")[-6:]
    look_id = f"ident-modern-{suffix}"
    return {
        "id": look_id,
        "name": f"{name} (现代{age})",
        "description": description,
        "appearance_details": description,
        "visual_prompt": visual_prompt,
        "image_url": "",
    }


def _ancient_seed(character: dict[str, Any]) -> dict[str, Any]:
    name = str(character.get("name") or "角色").strip() or "角色"
    extra = character.get("extra") if isinstance(character.get("extra"), dict) else {}
    base = str(
        character.get("description")
        or extra.get("description")
        or "古代少年，粗布长衫，发髻"
    ).strip()
    suffix = str(character.get("id") or "look")[-6:]
    return {
        "id": f"ident-ancient-{suffix}",
        "name": f"{name} (古代造型)",
        "description": base,
        "appearance_details": base,
        "visual_prompt": base,
        "image_url": "",
    }


def ensure_era_identities(character: dict[str, Any], beats: list[dict[str, Any]]) -> bool:
    """若分镜需要现代/古代造型而角色没有对应槽位，则补一条空设定板。原地修改 extra.identities。"""
    extra = character.get("extra")
    if not isinstance(extra, dict):
        extra = {}
        character["extra"] = extra
    identities = extra.get("identities")
    if not isinstance(identities, list):
        identities = []
        extra["identities"] = identities
    packed = [item for item in identities if isinstance(item, dict)]
    extra["identities"] = packed
    needed = needed_eras(character, beats)
    if not needed:
        return False
    changed = False
    known_ids = _existing_ids(packed)
    for era in ("modern", "ancient"):
        if era not in needed:
            continue
        if any(look_covers_era(item, era) for item in packed):
            continue
        seed = _modern_seed(character, beats) if era == "modern" else _ancient_seed(character)
        look_id = str(seed.get("id") or "")
        if look_id in known_ids:
            seed["id"] = f"{look_id}-{len(packed) + 1}"
        packed.append(seed)
        known_ids.add(str(seed["id"]))
        changed = True
    return changed
