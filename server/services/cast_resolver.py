from __future__ import annotations

import re
from typing import Any


LOOK_HINTS = ("现代", "古代", "微服", "宫装", "前期", "后期", "日常", "身份", "造型")
CROWD_MENTION = re.compile(
    r"^(众人|路人|客人|家丁|好友|邻桌|看热闹|蒙面人|地痞|衙役|百官|两个|三个|几位)"
)
PAREN_RE = re.compile(r"[（(]([^）)]+)[）)]")
ATTR_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9（）()]{1,20})[：:]\s*[“\"「]")
IDENTITY_LINE_RE = re.compile(
    r"(现代身份|古代身份|微服(?:造型)?|宫装(?:造型)?)[：:]\s*(.+?)(?=(?:现代身份|古代身份|微服(?:造型)?|宫装(?:造型)?)[：:]|\n|$)"
)
MODERN_RE = re.compile(r"现代|衬衫|西装|会议室|酒馆|电梯|手机|图书馆|电脑|啤酒|工牌|短发")
ANCIENT_RE = re.compile(r"古代|长衫|粗布|发髻|直裰|侯府|茅屋|陶碗|木床|宫装|微服|古装")
CIVILIAN_RE = re.compile(r"微服|青裙|市井")
PALACE_RE = re.compile(r"宫装|淡粉|偏殿|大殿|公主")


def split_header_name(header: str) -> tuple[str, list[str]]:
    """`牛大（牛昊）` → 牛大, aliases [牛大（牛昊）, 牛昊]. Look-like parens stay on the name."""
    raw = (header or "").strip()
    if not raw:
        return "", []
    match = re.match(r"^(.+?)[（(]([^）)]+)[）)]$", raw)
    if not match:
        return raw, [raw]
    base, inner = match.group(1).strip(), match.group(2).strip()
    if _inner_is_look(inner):
        return raw, [raw]
    aliases = [raw, base]
    for part in re.split(r"[、,/，]", inner):
        part = part.strip()
        if part and part not in aliases:
            aliases.append(part)
    return base, aliases


def _inner_is_look(inner: str) -> bool:
    return any(hint in inner for hint in LOOK_HINTS)


def split_prompt_key(key: str) -> tuple[str, str]:
    """`牛大（现代，仅1–2集）` → (牛大, 现代身份). `沈砚` → (沈砚, '')."""
    raw = (key or "").strip()
    match = re.match(r"^(.+?)[（(]([^）)]+)[）)]$", raw)
    if not match:
        return raw, ""
    base, inner = match.group(1).strip(), match.group(2).strip()
    if _inner_is_look(inner):
        return base, normalize_look_name(inner)
    return raw, ""


def normalize_look_name(label: str) -> str:
    text = (label or "").strip()
    if "微服" in text:
        return "微服"
    if "宫装" in text:
        return "宫装"
    if "现代" in text:
        return "现代身份"
    if "古代" in text:
        return "古代身份"
    if "前期" in text:
        return "前期造型"
    if "后期" in text:
        return "后期造型"
    if "日常" in text:
        return "日常造型"
    return text.split("，")[0].strip() or "日常造型"


def looks_from_description(content: str) -> list[dict[str, str]]:
    looks: list[dict[str, str]] = []
    for match in IDENTITY_LINE_RE.finditer(content or ""):
        name = normalize_look_name(match.group(1))
        desc = match.group(2).strip()
        looks.append({
            "name": name,
            "description": desc,
            "visual_prompt": desc,
        })
    return _dedupe_looks(looks)


def ensure_character_looks(character: dict[str, Any]) -> list[dict[str, str]]:
    looks = [item for item in (character.get("looks") or []) if isinstance(item, dict)]
    for look in looks_from_description(str(character.get("description") or "")):
        upsert_look(looks, look)
    for look in looks_from_description(str(character.get("visual_prompt") or "")):
        upsert_look(looks, look)
    character["looks"] = looks
    return looks


def upsert_look(looks: list[dict[str, str]], look: dict[str, str]) -> None:
    name = look.get("name") or "日常造型"
    for existing in looks:
        if existing.get("name") == name:
            if look.get("description") and len(look["description"]) > len(existing.get("description") or ""):
                existing["description"] = look["description"]
            if look.get("visual_prompt") and len(look["visual_prompt"]) > len(existing.get("visual_prompt") or ""):
                existing["visual_prompt"] = look["visual_prompt"]
            return
    looks.append({
        "name": name,
        "description": look.get("description") or "",
        "visual_prompt": look.get("visual_prompt") or look.get("description") or "",
    })


def attach_character_prompts(characters: list[dict[str, Any]], prompts: dict[str, str]) -> None:
    for key, prompt in (prompts or {}).items():
        prompt = (prompt or "").strip()
        if not prompt:
            continue
        base, look_name = split_prompt_key(key)
        character = find_character(characters, base) or find_character(characters, key)
        if not character:
            continue
        looks = character.setdefault("looks", [])
        if look_name:
            upsert_look(looks, {
                "name": look_name,
                "description": prompt,
                "visual_prompt": prompt,
            })
        else:
            character["visual_prompt"] = prompt


def find_character(characters: list[dict[str, Any]], mention: str) -> dict[str, Any] | None:
    return resolve_mention(mention, characters)


def resolve_mention(mention: str, characters: list[dict[str, Any]]) -> dict[str, Any] | None:
    cleaned = _clean_mention(mention)
    if not cleaned:
        return None
    exact: list[tuple[int, dict[str, Any]]] = []
    partial: list[tuple[int, dict[str, Any]]] = []
    for character in characters:
        keys = _character_keys(character)
        if cleaned in keys:
            exact.append((len(cleaned), character))
            continue
        for key in keys:
            if key and (key in cleaned or cleaned in key):
                partial.append((len(key), character))
    if exact:
        exact.sort(key=lambda item: -item[0])
        return exact[0][1]
    if partial:
        partial.sort(key=lambda item: -item[0])
        return partial[0][1]
    return None


def infer_look_name(character: dict[str, Any], *texts: str) -> str:
    looks = [item for item in (character.get("looks") or []) if item.get("name")]
    if not looks:
        return ""
    blob = " ".join(str(text or "") for text in texts)
    scored: list[tuple[int, str]] = []
    for look in looks:
        name = str(look.get("name") or "")
        score = 0
        if name and name in blob:
            score += 6
        if "现代" in name and MODERN_RE.search(blob):
            score += 4
        if "古代" in name and ANCIENT_RE.search(blob):
            score += 4
        if name == "微服" and CIVILIAN_RE.search(blob):
            score += 4
        if name == "宫装" and PALACE_RE.search(blob):
            score += 4
        scored.append((score, name))
    scored.sort(key=lambda item: -item[0])
    if scored[0][0] > 0:
        return scored[0][1]
    if len(looks) == 1:
        return str(looks[0].get("name") or "")
    return ""


def infer_speaker(dialogue: str, resolved_names: list[str], characters: list[dict[str, Any]]) -> str:
    roster = set(resolved_names)
    for attr in ATTR_RE.findall(dialogue or ""):
        matched = resolve_mention(attr, characters)
        if matched and matched["name"] in roster:
            return matched["name"]
        if matched:
            return matched["name"]
    if resolved_names:
        return resolved_names[0]
    return ""


def normalize_shot_cast(shot: dict[str, Any], characters: list[dict[str, Any]]) -> dict[str, Any]:
    raw_chars = list(shot.get("characters") or [])
    resolved: list[dict[str, Any]] = []
    extras: list[str] = []
    looks: dict[str, str] = {}
    context = " ".join(str(shot.get(key) or "") for key in (
        "title", "scene", "action", "dialogue", "visual_prompt", "raw_content",
    ))
    for mention in raw_chars:
        matched = resolve_mention(mention, characters)
        if not matched:
            cleaned = _clean_mention(mention)
            if cleaned:
                extras.append(cleaned)
            continue
        if matched not in resolved:
            resolved.append(matched)
        look_name = infer_look_name(matched, mention, context)
        if look_name:
            looks[matched["name"]] = look_name

    names = [item["name"] for item in resolved]
    speaker = infer_speaker(str(shot.get("dialogue") or ""), names, characters)
    if speaker and speaker not in names:
        matched = resolve_mention(speaker, characters)
        if matched:
            names.insert(0, matched["name"])
            look_name = infer_look_name(matched, shot.get("dialogue") or "", context)
            if look_name:
                looks[matched["name"]] = look_name

    shot["characters"] = names
    shot["character_extras"] = extras
    shot["character_looks"] = looks
    shot["speaker"] = speaker if speaker in names else (names[0] if names else "")
    return shot


def normalize_episodes_cast(characters: list[dict[str, Any]], episodes: list[dict[str, Any]]) -> None:
    for episode in episodes:
        for shot in episode.get("shots") or []:
            normalize_shot_cast(shot, characters)


def match_look_id(identities: list[dict[str, Any]], look_name: str, *texts: str) -> str:
    items = [item for item in identities or [] if isinstance(item, dict) and item.get("id")]
    if not items:
        return ""
    blob = " ".join([look_name, *texts])
    if look_name:
        for item in items:
            name = str(item.get("name") or "")
            if name == look_name or look_name in name or name in look_name:
                return str(item["id"])
            if "现代" in look_name and "现代" in name:
                return str(item["id"])
            if "古代" in look_name and "古代" in name:
                return str(item["id"])
            if look_name == "微服" and "微服" in name:
                return str(item["id"])
            if look_name == "宫装" and "宫装" in name:
                return str(item["id"])
    scored: list[tuple[int, str]] = []
    for item in items:
        name = str(item.get("name") or "")
        desc = " ".join(str(item.get(key) or "") for key in ("name", "description", "visual_prompt"))
        score = 0
        if MODERN_RE.search(blob) and re.search(r"现代|衬衫|西装|短发", desc):
            score += 3
        if ANCIENT_RE.search(blob) and re.search(r"古代|长衫|发髻|直裰|古装", desc):
            score += 3
        if CIVILIAN_RE.search(blob) and "微服" in desc:
            score += 3
        if PALACE_RE.search(blob) and "宫装" in desc:
            score += 3
        scored.append((score, str(item["id"])))
    scored.sort(key=lambda item: -item[0])
    if scored and scored[0][0] > 0:
        return scored[0][1]
    if len(items) == 1:
        return str(items[0]["id"])
    return ""


def identities_from_character(character: dict[str, Any], asset_id: str) -> list[dict[str, Any]]:
    looks = ensure_character_looks(character)
    if not looks:
        desc = character.get("description") or character.get("visual_prompt") or "日常基础造型"
        looks = [{
            "name": f"{character.get('name') or '角色'} (日常造型)",
            "description": desc,
            "visual_prompt": character.get("visual_prompt") or desc,
        }]
    identities = []
    suffix = asset_id[-6:] if len(asset_id) >= 6 else asset_id
    for index, look in enumerate(looks):
        name = look.get("name") or f"造型{index + 1}"
        slug = _look_slug(name)
        desc = look.get("description") or ""
        prompt = look.get("visual_prompt") or desc
        identities.append({
            "id": f"ident-{suffix}-{slug}",
            "name": name,
            "description": desc,
            "visual_prompt": prompt,
            "image_url": look.get("image_url") or "",
        })
    return identities


def merge_identities(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    incoming = [item for item in incoming or [] if isinstance(item, dict)]
    existing = [item for item in existing or [] if isinstance(item, dict)]
    if incoming:
        existing = [
            item for item in existing
            if item.get("image_url") or not _is_placeholder_look(item)
        ]
    by_name = {str(item.get("name") or ""): item for item in existing}
    merged: list[dict[str, Any]] = []
    seen = set()
    for look in incoming or []:
        name = str(look.get("name") or "")
        old = by_name.get(name) or {}
        item = {
            **look,
            "id": old.get("id") or look.get("id"),
            "image_url": old.get("image_url") or look.get("image_url") or "",
        }
        merged.append(item)
        seen.add(name)
    for old in existing or []:
        name = str((old or {}).get("name") or "")
        if name and name not in seen:
            merged.append(old)
    return merged


def _is_placeholder_look(item: dict[str, Any]) -> bool:
    name = str(item.get("name") or "")
    return any(token in name for token in ("日常造型", "日常/初始", "初始造型"))


def _clean_mention(mention: str) -> str:
    text = (mention or "").strip().rstrip("。；;，,")
    text = PAREN_RE.sub(" ", text)
    text = re.sub(r"\s+", "", text)
    if not text or CROWD_MENTION.match(text):
        return ""
    return text


def _character_keys(character: dict[str, Any]) -> list[str]:
    keys = [str(character.get("name") or "").strip()]
    for alias in character.get("aliases") or []:
        keys.append(str(alias).strip())
    return [key for key in keys if key]


def _dedupe_looks(looks: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for look in looks:
        upsert_look(result, look)
    return result


def _look_slug(name: str) -> str:
    mapping = {
        "现代身份": "modern",
        "古代身份": "ancient",
        "微服": "civilian",
        "宫装": "palace",
        "日常造型": "daily",
        "前期造型": "early",
        "后期造型": "late",
    }
    if name in mapping:
        return mapping[name]
    compact = re.sub(r"\W+", "", name)
    return compact[:12] or "look"
