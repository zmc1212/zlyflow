"""从原片参考图反推资产库提示词，并覆盖表单字段。"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

import requests

from .asset_source_references import sniff_image_suffix, source_reference_urls

MAX_INFER_IMAGES = 3
MAX_INFER_IMAGE_BYTES = 4 * 1024 * 1024
_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}

AGE_GROUPS = {"幼年", "少年", "青年", "中年", "老年"}
GENDERS = {"男", "女", "未指定"}
BODY_TYPES = {"纤细", "苗条", "标准", "精悍", "健壮", "魁梧"}
ETHNICITIES = {"中国人", "日本人", "韩国人", "欧美人", "混血", "其他"}
ART_STYLES = {
    "chinese_period_drama",
    "chinese_modern_drama",
    "guoman_fantasy",
    "anime",
    "western_realistic",
    "western_cartoon",
}
VISUAL_STYLES = {"realistic", "ancient", "modern", "fantasy", "cyberpunk"}
SCENE_TYPES = {"interior", "exterior", "pano"}
PROP_TYPES = {"weapon", "accessory", "artifact", "document", "furniture", "object"}


def character_infer_system_prompt() -> str:
    return (
        "你是影视美术指导。用户会给出角色名，以及 1-3 张原片截图。"
        "只根据图中该角色实际可见的内容写设定，忽略字幕、水印、Logo、电梯广告和背景路人。"
        "图里没有的衣服、外套、配饰一律不要写。例如截图是背心就写背心，不要写成衬衫或外套。"
        "只返回 JSON 对象，不要 markdown。字段："
        '{"age_group":"幼年|少年|青年|中年|老年","gender":"男|女|未指定","body_type":"纤细|苗条|标准|精悍|健壮|魁梧",'
        '"ethnicity":"中国人|日本人|韩国人|欧美人|混血|其他","art_style_id":"chinese_modern_drama|chinese_period_drama|'
        'guoman_fantasy|anime|western_realistic|western_cartoon","visual_style":"realistic|ancient|modern|fantasy|cyberpunk",'
        '"face_prompt":"中文五官与年龄发型描述","avatar_prompt":"中文头像特写生图提示词","description":"中文角色外观简述",'
        '"appearance":"中文服装与全身外观，只写图中可见的衣服","visual_prompt":"中文全身造型生图提示词"}'
    )


def scene_infer_system_prompt() -> str:
    return (
        "你是影视美术指导。根据原片空镜截图写场景设定。只写图中可见的空间、光线和陈设，不要发明图中没有的家具或招牌。"
        "忽略字幕和水印。只返回 JSON："
        '{"scene_type":"interior|exterior|pano","environment_prompt":"...","reverse_prompt":"...","pano_prompt":"...","description":"..."}'
    )


def prop_infer_system_prompt() -> str:
    return (
        "你是影视美术指导。根据原片道具特写截图写道具设定。只写图中可见的外形、材质和磨损。"
        "忽略字幕和水印。只返回 JSON："
        '{"prop_type":"weapon|accessory|artifact|document|furniture|object","visual_prompt":"...","description":"..."}'
    )


def infer_system_prompt(kind: str) -> str:
    if kind == "character":
        return character_infer_system_prompt()
    if kind == "scene":
        return scene_infer_system_prompt()
    return prop_infer_system_prompt()


def infer_user_text(kind: str, name: str, role: str = "") -> str:
    label = {"character": "角色", "scene": "场景"}.get(kind, "道具")
    parts = [f"请根据原片截图反推这个{label}（{name or '未命名'}）的资产库提示词，并覆盖旧文案。"]
    if role:
        parts.append(f"角色定位：{role}")
    parts.append("只描述图中可见内容。")
    return "\n".join(parts)


def parse_infer_payload(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise ValueError("大模型未返回有效 JSON") from None
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("大模型返回内容必须是 JSON 对象。")
    return value


def _pick(raw: Any, allowed: set[str]) -> str:
    value = str(raw or "").strip()
    return value if value in allowed else ""


def _text(raw: Any) -> str:
    return str(raw or "").strip()


def apply_inferred_prompts(
    *,
    kind: str,
    extra: dict[str, Any] | None,
    inferred: dict[str, Any] | None,
    name: str = "",
    current_description: str = "",
    current_visual_prompt: str = "",
) -> tuple[dict[str, Any], str, str]:
    extra = dict(extra or {})
    inferred = inferred if isinstance(inferred, dict) else {}
    description = current_description
    visual_prompt = current_visual_prompt

    if kind == "character":
        age = _pick(inferred.get("age_group"), AGE_GROUPS)
        if age:
            extra["age_group"] = age
        gender = _pick(inferred.get("gender"), GENDERS)
        if gender:
            extra["gender"] = gender
        body = _pick(inferred.get("body_type"), BODY_TYPES)
        if body:
            extra["body_type"] = body
        ethnicity = _pick(inferred.get("ethnicity"), ETHNICITIES)
        if ethnicity:
            extra["ethnicity"] = ethnicity
        art = _pick(inferred.get("art_style_id") or inferred.get("art_style"), ART_STYLES)
        if art:
            extra["art_style_id"] = art
        visual = _pick(inferred.get("visual_style"), VISUAL_STYLES)
        if visual:
            extra["visual_style"] = visual
        face = _text(inferred.get("face_prompt"))
        if face:
            extra["face_prompt"] = face
        avatar = _text(inferred.get("avatar_prompt"))
        if avatar:
            extra["avatar_prompt"] = avatar
        desc = _text(inferred.get("description"))
        if desc:
            extra["description"] = desc
            description = desc
        appearance = _text(inferred.get("appearance")) or desc
        look_prompt = _text(inferred.get("visual_prompt"))
        if look_prompt:
            visual_prompt = look_prompt
        identities = extra.get("identities")
        if not isinstance(identities, list) or not identities:
            identities = [{
                "id": "ident-inferred",
                "name": f"{name} (日常/初始造型)" if name else "日常/初始造型",
                "description": appearance,
                "visual_prompt": look_prompt,
                "image_url": "",
            }]
            extra["identities"] = identities
        else:
            first = dict(identities[0] or {})
            if appearance:
                first["description"] = appearance
            if look_prompt:
                first["visual_prompt"] = look_prompt
            extra["identities"] = [first, *identities[1:]]
    elif kind == "scene":
        scene_type = _pick(inferred.get("scene_type"), SCENE_TYPES)
        if scene_type:
            extra["scene_type"] = scene_type
        env = _text(inferred.get("environment_prompt"))
        if env:
            extra["environment_prompt"] = env
            visual_prompt = env
        reverse = _text(inferred.get("reverse_prompt"))
        if reverse:
            extra["reverse_prompt"] = reverse
        pano = _text(inferred.get("pano_prompt"))
        if pano:
            extra["pano_prompt"] = pano
        desc = _text(inferred.get("description"))
        if desc:
            extra["description"] = desc
            description = desc
    else:
        prop_type = _pick(inferred.get("prop_type"), PROP_TYPES)
        if prop_type:
            extra["prop_type"] = prop_type
        look_prompt = _text(inferred.get("visual_prompt"))
        if look_prompt:
            extra["visual_prompt"] = look_prompt
            visual_prompt = look_prompt
        desc = _text(inferred.get("description"))
        if desc:
            extra["description"] = desc
            description = desc
    return extra, description, visual_prompt


def reference_urls_to_data_uris(urls: list[str], *, limit: int = MAX_INFER_IMAGES) -> list[str]:
    data_uris: list[str] = []
    errors: list[str] = []
    for url in urls[:limit]:
        try:
            data_uris.append(_url_to_data_uri(url))
        except Exception as err:
            errors.append(f"{url}: {err}")
    if not data_uris:
        detail = "；".join(errors[:2]) if errors else "没有可用的原片参考图"
        raise ValueError(f"无法读取原片参考图：{detail}")
    return data_uris


def _url_to_data_uri(url: str) -> str:
    response = requests.get(url, timeout=20)
    if not response.ok:
        raise ValueError(f"下载失败 HTTP {response.status_code}")
    content = response.content or b""
    if len(content) > MAX_INFER_IMAGE_BYTES:
        raise ValueError("单张超过 4MB")
    suffix = sniff_image_suffix(content, url, response.headers.get("content-type") or "")
    mime = _MIME.get(suffix, "image/jpeg")
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def source_urls_for_inference(extra: dict[str, Any] | None) -> list[str]:
    urls = source_reference_urls(extra)
    if not urls:
        raise ValueError("请先上传至少一张原片参考图")
    return urls
