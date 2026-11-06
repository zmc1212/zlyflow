from __future__ import annotations

import re
from typing import Any


GRS_PROFILE_GPT_IMAGE_2 = "gpt_image_2"
GRS_PROFILE_GPT_IMAGE_2_VIP = "gpt_image_2_vip"
GRS_PROFILE_GPT_IMAGE_2_5 = "gpt_image_2_5"
GRS_PROFILE_GPT_IMAGE_2_5_VIP = "gpt_image_2_5_vip"
GRS_PROFILE_NANO_BANANA = "nano_banana"
GRS_PROFILE_NANO_BANANA_2 = "nano_banana_2"
GRS_PROFILES = (
    GRS_PROFILE_GPT_IMAGE_2,
    GRS_PROFILE_GPT_IMAGE_2_VIP,
    GRS_PROFILE_GPT_IMAGE_2_5,
    GRS_PROFILE_GPT_IMAGE_2_5_VIP,
    GRS_PROFILE_NANO_BANANA,
    GRS_PROFILE_NANO_BANANA_2,
)

PROVIDER_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

PROFILE_LABELS = {
    GRS_PROFILE_GPT_IMAGE_2: "GPT Image 2（1K）",
    GRS_PROFILE_GPT_IMAGE_2_VIP: "GPT Image 2 VIP（1K/2K/4K/自定义）",
    GRS_PROFILE_GPT_IMAGE_2_5: "GPT Image 2.5（1K）",
    GRS_PROFILE_GPT_IMAGE_2_5_VIP: "GPT Image 2.5 高画质（1K/2K/4K）",
    GRS_PROFILE_NANO_BANANA: "Nano Banana（1K/2K/4K）",
    GRS_PROFILE_NANO_BANANA_2: "Nano Banana 2（含超长画幅）",
}

# 下拉里的一句话能力说明：只写代码或上游已验证的差异（分辨率、比例、画质档位、参考图数量），
# 不要写"更写实/更好看"这类无法核对的营销话术。
PROFILE_CAPABILITIES = {
    GRS_PROFILE_GPT_IMAGE_2: "1K 标准档，最多 10 张参考图",
    GRS_PROFILE_GPT_IMAGE_2_VIP: "最高 4K，可自定义尺寸",
    GRS_PROFILE_GPT_IMAGE_2_5: "1K 快速档，最多 10 张参考图",
    GRS_PROFILE_GPT_IMAGE_2_5_VIP: "高画质档，1K/2K/4K 与画质档位",
    GRS_PROFILE_NANO_BANANA: "最高 4K，21:9 超宽画幅",
    GRS_PROFILE_NANO_BANANA_2: "1:8 超长画幅，最高 4K",
}

# 同能力档内确有区别时，按模型 ID 覆盖；其余走档位文案。
MODEL_CAPABILITY_NOTES = {
    "gpt-image-2.6": "可直出 GIF 动图，出图更快",
    "gpt-image-2.5-flare": "高画质档，画质可选低/中/高",
    "gpt-image-2.5-sunburst": "顶配画质档，画质最高可选 max",
    "nano-banana-fast": "低价快出，最高 4K",
    "nano-banana-2-lite": "1:8 超长画幅，低价快出",
    "nano-banana-2-2k-cl": "1:8 超长画幅，固定 2K",
    "nano-banana-2-4k-cl": "1:8 超长画幅，固定 4K",
}

# 旧版目录（含已入库的内置行）里批量生成过的长句。列在这里只用于识别"这不是管理员自己写的"，
# 让读路径改用当前档位文案，避免平台已经出现 2.6 而行上还写着"使用 GRS GPT Image 2.5 生成图片"。
LEGACY_AUTO_DESCRIPTIONS = frozenset({
    "使用 GRS 生成图片，支持 0–10 张有序参考图。",
    "使用 GRS 高画质图片能力，支持 1K/2K/4K 与自定义尺寸。",
    "使用 GRS GPT Image 2.5 生成图片，支持 0–10 张有序参考图。",
    "使用 GRS GPT Image 2.5 高画质能力，支持 1K/2K/4K 与画质档位。",
    "使用 GRS Nano Banana 生成图片，支持 1K/2K/4K。",
    "使用 GRS Nano Banana 2 生成图片，支持超长画幅与 1K/2K/4K。",
    "使用 GRS 生成图片。",
})


def model_description(profile: str | None, provider_model: str | None = None) -> str:
    note = MODEL_CAPABILITY_NOTES.get(str(provider_model or "").strip().lower())
    if note:
        return note
    return PROFILE_CAPABILITIES.get(str(profile or ""), "GRS 生图模型。")


def effective_description(row: dict[str, Any] | None) -> str:
    """目录行 → 界面展示的描述。

    管理员自填的描述优先；空描述或旧模板批量生成的长句走当前档位文案，
    这样内置清单改文案不需要动共享数据库里的历史行。
    """
    stored = str((row or {}).get("description") or "").strip()
    if stored and stored not in LEGACY_AUTO_DESCRIPTIONS:
        return stored
    return model_description((row or {}).get("profile"), (row or {}).get("provider_model"))


BUILTIN_MODELS: tuple[dict[str, Any], ...] = (
    {
        "provider_model": "gpt-image-2.5",
        "display_name": "GPT Image 2.5",
        "profile": GRS_PROFILE_GPT_IMAGE_2_5,
        "default_enabled": True,
        "sort_order": 5,
        "is_default": True,
    },
    {
        "provider_model": "gpt-image-2.5-flare",
        "display_name": "GPT Image 2.5 Flare",
        "profile": GRS_PROFILE_GPT_IMAGE_2_5_VIP,
        "quality_options": ["low", "medium", "high"],
        "default_quality": "medium",
        "default_enabled": True,
        "sort_order": 6,
    },
    {
        "provider_model": "gpt-image-2.5-sunburst",
        "display_name": "GPT Image 2.5 Sunburst",
        "profile": GRS_PROFILE_GPT_IMAGE_2_5_VIP,
        "quality_options": ["low", "medium", "high", "xhigh", "max"],
        "default_quality": "high",
        "default_enabled": True,
        "sort_order": 7,
    },
    {
        "provider_model": "gpt-image-2",
        "display_name": "GPT Image 2",
        "profile": GRS_PROFILE_GPT_IMAGE_2,
        "default_enabled": True,
        "sort_order": 10,
    },
    {
        "provider_model": "gpt-image-2-vip",
        "display_name": "GPT Image 2 VIP",
        "profile": GRS_PROFILE_GPT_IMAGE_2_VIP,
        "default_enabled": True,
        "sort_order": 20,
    },
    {
        "provider_model": "nano-banana",
        "display_name": "Nano Banana",
        "profile": GRS_PROFILE_NANO_BANANA,
        "sort_order": 30,
    },
    {
        "provider_model": "nano-banana-fast",
        "display_name": "Nano Banana Fast",
        "profile": GRS_PROFILE_NANO_BANANA,
        "sort_order": 40,
    },
    {
        "provider_model": "nano-banana-2",
        "display_name": "Nano Banana 2",
        "profile": GRS_PROFILE_NANO_BANANA_2,
        "sort_order": 50,
    },
    {
        "provider_model": "nano-banana-2-cl",
        "display_name": "Nano Banana 2 CL",
        "profile": GRS_PROFILE_NANO_BANANA_2,
        "sort_order": 60,
    },
    {
        "provider_model": "nano-banana-2-2k-cl",
        "display_name": "Nano Banana 2 2K CL",
        "profile": GRS_PROFILE_NANO_BANANA_2,
        "resolutions": ["2K"],
        "sort_order": 70,
    },
    {
        "provider_model": "nano-banana-2-4k-cl",
        "display_name": "Nano Banana 2 4K CL",
        "profile": GRS_PROFILE_NANO_BANANA_2,
        "resolutions": ["4K"],
        "sort_order": 80,
    },
    {
        "provider_model": "nano-banana-pro",
        "display_name": "Nano Banana Pro",
        "profile": GRS_PROFILE_NANO_BANANA,
        "sort_order": 90,
    },
    {
        "provider_model": "nano-banana-pro-vt",
        "display_name": "Nano Banana Pro VT",
        "profile": GRS_PROFILE_NANO_BANANA,
        "sort_order": 100,
    },
    {
        "provider_model": "nano-banana-pro-cl",
        "display_name": "Nano Banana Pro CL",
        "profile": GRS_PROFILE_NANO_BANANA,
        "sort_order": 110,
    },
    {
        "provider_model": "nano-banana-pro-vip",
        "display_name": "Nano Banana Pro VIP",
        "profile": GRS_PROFILE_NANO_BANANA,
        "sort_order": 120,
    },
    {
        "provider_model": "nano-banana-pro-4k-vip",
        "display_name": "Nano Banana Pro 4K VIP",
        "profile": GRS_PROFILE_NANO_BANANA,
        "resolutions": ["4K"],
        "sort_order": 130,
    },
)


def workflow_id_for(provider_model: str) -> str:
    if provider_model == "gpt-image-2":
        return "grs-gpt-image-2"
    if provider_model == "gpt-image-2-vip":
        return "grs-gpt-image-2-vip"
    return f"grs-{provider_model}"


def validate_provider_model(provider_model: str) -> str:
    value = provider_model.strip()
    if not value or not PROVIDER_MODEL_PATTERN.fullmatch(value):
        raise ValueError("模型 ID 只能包含字母、数字、点、下划线和连字符")
    return value


def split_model_list(text: str | None) -> list[str]:
    return [item.strip() for item in str(text or "").split(",") if item.strip()]


def builtin_entry(provider_model: str | None = None, workflow_id: str | None = None) -> dict[str, Any] | None:
    for item in BUILTIN_MODELS:
        if provider_model and item["provider_model"] == provider_model:
            return catalog_record(item)
        if workflow_id and workflow_id_for(item["provider_model"]) == workflow_id:
            return catalog_record(item)
    return None


def catalog_record(spec: dict[str, Any], *, enabled: bool | None = None, builtin: bool = True) -> dict[str, Any]:
    provider_model = spec["provider_model"]
    profile = spec["profile"]
    return {
        "workflow_id": workflow_id_for(provider_model),
        "provider_model": provider_model,
        "display_name": spec["display_name"],
        "description": spec.get("description") or model_description(profile, provider_model),
        "profile": profile,
        "resolutions": list(spec["resolutions"]) if spec.get("resolutions") else None,
        "quality_options": list(spec["quality_options"]) if spec.get("quality_options") else None,
        "default_quality": spec.get("default_quality"),
        "enabled": spec.get("default_enabled", False) if enabled is None else enabled,
        "sort_order": int(spec.get("sort_order", 100)),
        "is_default": bool(spec.get("is_default", False)),
        "builtin": builtin,
    }


def builtin_catalog_records() -> list[dict[str, Any]]:
    return [catalog_record(item) for item in BUILTIN_MODELS]


# 平台 /v1/models 把对话与生图模型混在一张表里，且不带任何能力描述字段，
# 只能按命名家族识别生图模型。出现新家族时在此登记，未登记的仍可手动添加。
IMAGE_MODEL_PREFIXES = (
    "gpt-image", "nano-banana", "dall-e", "flux", "seedream", "seededit",
    "hunyuan-image", "qwen-image", "grok-image", "imagen", "sd", "sdxl",
    "stable-diffusion", "midjourney", "jimeng",
)
IMAGE_MODEL_SUFFIX = "-image"
GPT_IMAGE_VERSION_PATTERN = re.compile(r"^gpt-image-(\d+)(?:\.(\d+))?")
_ACRONYM_TOKENS = {"gpt", "vip", "cl", "vt", "pro", "gif", "ai", "sd", "ultra"}


def is_image_model_id(provider_model: str | None) -> bool:
    value = str(provider_model or "").strip().lower()
    if not value or not PROVIDER_MODEL_PATTERN.fullmatch(value):
        return False
    return value.startswith(IMAGE_MODEL_PREFIXES) or value.endswith(IMAGE_MODEL_SUFFIX)


def guess_profile(provider_model: str) -> str:
    """平台列表不含能力档，按命名家族推断，调用方需让管理员确认。"""
    value = provider_model.strip().lower()
    if value.startswith("nano-banana"):
        return GRS_PROFILE_NANO_BANANA_2 if value.startswith("nano-banana-2") else GRS_PROFILE_NANO_BANANA
    if value.startswith("gpt-image"):
        vip = value.endswith("-vip") or "-vip-" in value
        match = GPT_IMAGE_VERSION_PATTERN.match(value)
        if match:
            version = (int(match.group(1)), int(match.group(2) or 0))
            if version >= (2, 5):
                return GRS_PROFILE_GPT_IMAGE_2_5_VIP if vip else GRS_PROFILE_GPT_IMAGE_2_5
            return GRS_PROFILE_GPT_IMAGE_2_VIP if vip else GRS_PROFILE_GPT_IMAGE_2
        return GRS_PROFILE_GPT_IMAGE_2_VIP if vip else GRS_PROFILE_GPT_IMAGE_2
    return GRS_PROFILE_NANO_BANANA


def title_from_model_id(provider_model: str) -> str:
    tokens = [item for item in re.split(r"[-_]+", provider_model.strip()) if item]
    labels: list[str] = []
    for token in tokens:
        if re.fullmatch(r"\d+[kK]", token) or token.lower() in _ACRONYM_TOKENS:
            labels.append(token.upper())
        elif token.replace(".", "").isdigit():
            labels.append(token)
        else:
            labels.append(token[:1].upper() + token[1:])
    return " ".join(labels) or provider_model.strip()


def platform_entry(provider_model: str) -> dict[str, Any]:
    """平台 /v1/models 的模型 ID → 目录条目。

    命中内置表时沿用内置的能力档、分辨率与画质参数（平台接口不提供这些字段）；
    未命中时按家族推断能力档，并标记 profile_source 让管理员在界面上确认。
    """
    value = validate_provider_model(provider_model)
    builtin = builtin_entry(provider_model=value)
    if builtin is not None:
        return {**builtin, "profile_source": "builtin"}
    profile = guess_profile(value)
    record = catalog_record(
        {"provider_model": value, "display_name": title_from_model_id(value), "profile": profile, "sort_order": 300},
        builtin=False,
    )
    return {**record, "profile_source": "guess"}
