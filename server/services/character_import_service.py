from __future__ import annotations

import re
from typing import Any

from .cast_resolver import ensure_character_looks, identities_from_character, merge_identities


ROLE_POSITIONS = ("主角", "反派/观察", "配角", "龙套", "旁白")
AGE_GROUPS = ("幼年", "少年", "青年", "中年", "老年")
GENDERS = ("男", "女", "未指定")
BODY_TYPES = ("纤细", "苗条", "标准", "精悍", "健壮", "魁梧")
ART_STYLE_IDS = (
    "chinese_period_drama",
    "chinese_modern_drama",
    "guoman_fantasy",
    "anime",
    "western_realistic",
    "western_cartoon",
)
VISUAL_STYLES = ("realistic", "ancient", "modern", "fantasy", "cyberpunk")

PROFILE_FIELDS = (
    "aliases",
    "role",
    "role_position",
    "gender",
    "age",
    "age_group",
    "description",
    "face_prompt",
    "body_type",
    "art_style_id",
    "visual_style",
    "ethnicity",
    "visual_prompt",
    "avatar_prompt",
)


def aliases_to_text(value: Any) -> str:
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ",".join(dict.fromkeys(parts))
    text = str(value or "").strip()
    if not text:
        return ""
    parts = [item.strip() for item in re.split(r"[,，、]", text) if item.strip()]
    return ",".join(dict.fromkeys(parts))


def infer_age_group(age: str, text: str) -> str:
    blob = f"{age} {text}"
    if any(word in blob for word in ("幼童", "幼年", "孩童")):
        return "幼年"
    if "老年" in blob or "花白" in blob or "灰白胡须" in blob:
        return "老年"
    if "中年" in blob:
        return "中年"
    if "少年" in blob:
        return "少年"
    if "青年" in blob:
        return "青年"
    years = [int(item) for item in re.findall(r"(\d+)\s*岁", blob)]
    if years:
        year = years[0]
        if year <= 12:
            return "幼年"
        if year <= 17:
            return "少年"
        if year <= 35:
            return "青年"
        if year <= 55:
            return "中年"
        return "老年"
    return ""


def infer_role_position(role: str, text: str) -> str:
    blob = f"{role} {text}"
    if any(word in blob for word in ("反派", "对手", "奸商", "反面")):
        return "反派/观察"
    if any(word in blob for word in ("旁白",)):
        return "旁白"
    if any(word in blob for word in ("男主", "女主", "主角")):
        return "主角"
    if any(word in blob for word in ("龙套", "路人")):
        return "龙套"
    if role.strip():
        return "配角"
    return ""


def infer_gender(role: str, text: str) -> str:
    blob = f"{role} {text}"
    female_hits = ("女主", "公主", "皇后", "妃", "娘子", "女子", "女性", "小姐")
    male_hits = ("男主", "皇帝", "国王", "少爷", "公子", "男子", "男性", "庶子")
    if any(word in blob for word in female_hits):
        return "女"
    if any(word in blob for word in male_hits):
        return "男"
    if re.search(r"(?<![男])女(?!主)", blob) and "女主" not in blob:
        if "女" in role or "公主" in blob:
            return "女"
    return ""


def infer_body_type(text: str) -> str:
    if any(word in text for word in ("肥胖", "魁梧", "高大壮")):
        return "魁梧"
    if any(word in text for word in ("健壮", "结实")):
        return "健壮"
    if any(word in text for word in ("精悍",)):
        return "精悍"
    if any(word in text for word in ("苗条",)):
        return "苗条"
    if any(word in text for word in ("纤细", "清瘦", "清秀")):
        return "纤细"
    return ""


def infer_art_style(project_style: str, genre: str, text: str) -> tuple[str, str]:
    blob = f"{project_style} {genre} {text}"
    if project_style in ART_STYLE_IDS:
        art = project_style
    elif any(word in blob for word in ("国漫", "奇幻")):
        art = "guoman_fantasy"
    elif "日漫" in blob or "anime" in blob.lower():
        art = "anime"
    elif any(word in blob for word in ("现代",)) and not any(word in blob for word in ("古装", "古代", "穿越")):
        art = "chinese_modern_drama"
    else:
        art = "chinese_period_drama"
    if art == "chinese_modern_drama":
        visual = "modern"
    elif art in {"guoman_fantasy"}:
        visual = "fantasy"
    elif art == "anime":
        visual = "fantasy"
    elif "modern" in art:
        visual = "modern"
    else:
        visual = "ancient" if any(word in blob for word in ("古装", "古代", "穿越", "period")) else "realistic"
    return art, visual


def infer_face_prompt(gender: str, age_group: str, text: str) -> str:
    hair = ""
    if "短发" in text:
        hair = "黑色短发"
    elif "长发" in text or "乌发" in text:
        hair = "黑色长发"
    elif "花白" in text or "灰白" in text:
        hair = "灰白头发"
    eyes = "沉静眼神" if "沉静" in text or "锐利" in text else ""
    brow = "剑眉" if "剑眉" in text else ""
    parts = [gender or "未指定性别", age_group or "适龄", hair, brow, eyes, "五官清晰", "写实面部"]
    return "，".join(part for part in parts if part)


def infer_ethnicity(text: str) -> str:
    if any(word in text for word in ("欧美", "西洋", "Western")):
        return "Caucasian"
    return "Chinese"


def complete_character_locally(
    character: dict[str, Any],
    *,
    project_style: str = "",
    genre: str = "",
    visual_style_desc: str = "",
    fill_defaults: bool = False,
) -> dict[str, Any]:
    item = dict(character)
    name = str(item.get("name") or "").strip()
    role = str(item.get("role") or "").strip()
    description = str(item.get("description") or "").strip()
    prompt = str(item.get("visual_prompt") or "").strip()
    blob = " ".join([name, role, description, prompt, visual_style_desc, genre])

    item["aliases"] = aliases_to_text(item.get("aliases"))
    item["role"] = role or ("主要角色" if fill_defaults else role)
    item["gender"] = _pick(item.get("gender"), GENDERS) or infer_gender(role, blob)
    item["age"] = str(item.get("age") or "").strip()
    item["age_group"] = _pick(item.get("age_group"), AGE_GROUPS) or infer_age_group(item["age"], blob)
    item["role_position"] = _pick(item.get("role_position"), ROLE_POSITIONS) or infer_role_position(role, blob)
    item["description"] = description or prompt
    item["body_type"] = _pick(item.get("body_type"), BODY_TYPES) or infer_body_type(blob)
    art_style, visual_style = infer_art_style(project_style, genre, blob)
    item["art_style_id"] = _pick(item.get("art_style_id"), ART_STYLE_IDS) or art_style
    item["visual_style"] = _pick(item.get("visual_style"), VISUAL_STYLES) or visual_style
    item["ethnicity"] = str(item.get("ethnicity") or "").strip() or infer_ethnicity(blob)
    item["face_prompt"] = str(item.get("face_prompt") or "").strip()
    item["visual_prompt"] = prompt
    item["avatar_prompt"] = str(item.get("avatar_prompt") or "").strip()
    item["looks"] = item.get("looks") if isinstance(item.get("looks"), list) else []
    ensure_character_looks(item)

    if fill_defaults:
        item["role"] = item["role"] or "主要角色"
        item["gender"] = item["gender"] or "未指定"
        item["age_group"] = item["age_group"] or "青年"
        item["role_position"] = item["role_position"] or "配角"
        item["body_type"] = item["body_type"] or "标准"
        item["description"] = item["description"] or f"{name}，{item['role']}。"
        item["face_prompt"] = item["face_prompt"] or infer_face_prompt(item["gender"], item["age_group"], blob)
        item["visual_prompt"] = item["visual_prompt"] or (
            f"{name}，{item['gender']}，{item['age_group']}，{item['description'][:80]}，"
            "单人全身角色设定图，中性背景，五官清晰，无文字"
        )
        item["avatar_prompt"] = item["avatar_prompt"] or (
            f"{name}，{item['face_prompt']}，面部肖像特写，眼神清楚，写实电影光影，8k"
        )
    return item


def missing_profile_fields(character: dict[str, Any]) -> list[str]:
    missing = []
    for key in PROFILE_FIELDS:
        value = character.get(key)
        if isinstance(value, list):
            if not value:
                missing.append(key)
        elif not str(value or "").strip():
            missing.append(key)
    return missing


def merge_character_fill(base: dict[str, Any], fill: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key in PROFILE_FIELDS:
        current = merged.get(key)
        incoming = fill.get(key)
        if key == "aliases":
            if not aliases_to_text(current) and incoming:
                merged[key] = aliases_to_text(incoming)
            continue
        if not str(current or "").strip() and incoming not in (None, ""):
            if key == "role_position":
                merged[key] = _pick(incoming, ROLE_POSITIONS) or merged.get(key)
            elif key == "age_group":
                merged[key] = _pick(incoming, AGE_GROUPS) or merged.get(key)
            elif key == "gender":
                merged[key] = _pick(incoming, GENDERS) or merged.get(key)
            elif key == "body_type":
                merged[key] = _pick(incoming, BODY_TYPES) or merged.get(key)
            elif key == "art_style_id":
                merged[key] = _pick(incoming, ART_STYLE_IDS) or merged.get(key)
            elif key == "visual_style":
                merged[key] = _pick(incoming, VISUAL_STYLES) or merged.get(key)
            else:
                merged[key] = str(incoming).strip()
    if isinstance(fill.get("looks"), list) and fill["looks"] and not merged.get("looks"):
        merged["looks"] = fill["looks"]
    return merged


def character_asset_extra(character: dict[str, Any], asset_id: str, existing_extra: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing_extra if isinstance(existing_extra, dict) else {}
    incoming_identities = identities_from_character(character, asset_id)
    extra = {
        **existing,
        "aliases": aliases_to_text(character.get("aliases")),
        "description": character.get("description") or "",
        "role_position": character.get("role_position") or "配角",
        "age_group": character.get("age_group") or "青年",
        "face_prompt": character.get("face_prompt") or "",
        "gender": character.get("gender") or "未指定",
        "body_type": character.get("body_type") or "标准",
        "art_style_id": character.get("art_style_id") or "chinese_period_drama",
        "visual_style": character.get("visual_style") or "ancient",
        "ethnicity": character.get("ethnicity") or "Chinese",
        "avatar_prompt": character.get("avatar_prompt") or "",
        "identities": merge_identities(existing.get("identities") or [], incoming_identities),
    }
    if existing.get("avatar_url"):
        extra["avatar_url"] = existing["avatar_url"]
    return extra


def _pick(value: Any, allowed: tuple[str, ...]) -> str:
    text = str(value or "").strip()
    return text if text in allowed else ""


class CharacterImportService:
    @classmethod
    def enrich_analysis(
        cls,
        analysis: dict[str, Any],
        *,
        project_style: str = "",
        use_llm: bool = True,
    ) -> dict[str, Any]:
        positioning = analysis.get("positioning") if isinstance(analysis.get("positioning"), dict) else {}
        visual_style = analysis.get("visual_style") if isinstance(analysis.get("visual_style"), dict) else {}
        genre = str(positioning.get("genre") or "")
        style_desc = str(visual_style.get("description") or "")
        characters = analysis.get("characters") or []
        completed = [
            complete_character_locally(
                item,
                project_style=project_style,
                genre=genre,
                visual_style_desc=style_desc,
                fill_defaults=False,
            )
            for item in characters
        ]

        llm_used = False
        llm_error = ""
        if use_llm and completed:
            try:
                from .llm_service import LlmService
                fills = LlmService.enrich_imported_characters(
                    completed,
                    title=str(analysis.get("title") or ""),
                    genre=genre,
                    visual_style=style_desc,
                    project_style=project_style,
                )
                llm_used = True
                by_name = {str(item.get("name") or ""): item for item in fills}
                completed = [
                    merge_character_fill(item, by_name.get(item.get("name") or "", {}))
                    for item in completed
                ]
            except Exception as err:
                llm_error = str(err)

        completed = [
            complete_character_locally(
                item,
                project_style=project_style,
                genre=genre,
                visual_style_desc=style_desc,
                fill_defaults=True,
            )
            for item in completed
        ]

        analysis["characters"] = completed
        logs = list(analysis.get("logs") or [])
        if llm_used:
            logs.append(f"已用大模型补全 {len(completed)} 位角色的定位、别名、性别、年龄段、面部提示词与画风")
        elif llm_error:
            logs.append(f"大模型角色补全未启用或失败，已用规则推理填满字段：{llm_error[:120]}")
        else:
            logs.append(f"已用规则推理补全 {len(completed)} 位角色档案字段")
        if llm_error:
            logs.append("若需更准确的面部提示词，请在系统设置中启用大模型后重新导入")
        analysis["logs"] = logs
        return analysis
