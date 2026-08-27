from __future__ import annotations

import re
from typing import Any


GRS_PROFILE_GPT_IMAGE_2 = "gpt_image_2"
GRS_PROFILE_GPT_IMAGE_2_VIP = "gpt_image_2_vip"
GRS_PROFILE_NANO_BANANA = "nano_banana"
GRS_PROFILE_NANO_BANANA_2 = "nano_banana_2"
GRS_PROFILES = (
    GRS_PROFILE_GPT_IMAGE_2,
    GRS_PROFILE_GPT_IMAGE_2_VIP,
    GRS_PROFILE_NANO_BANANA,
    GRS_PROFILE_NANO_BANANA_2,
)

PROVIDER_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

PROFILE_LABELS = {
    GRS_PROFILE_GPT_IMAGE_2: "GPT Image 2（1K）",
    GRS_PROFILE_GPT_IMAGE_2_VIP: "GPT Image 2 VIP（1K/2K/4K/自定义）",
    GRS_PROFILE_NANO_BANANA: "Nano Banana（1K/2K/4K）",
    GRS_PROFILE_NANO_BANANA_2: "Nano Banana 2（含超长画幅）",
}

PROFILE_DESCRIPTIONS = {
    GRS_PROFILE_GPT_IMAGE_2: "使用 GRS 生成图片，支持 0–10 张有序参考图。",
    GRS_PROFILE_GPT_IMAGE_2_VIP: "使用 GRS 高画质图片能力，支持 1K/2K/4K 与自定义尺寸。",
    GRS_PROFILE_NANO_BANANA: "使用 GRS Nano Banana 生成图片，支持 1K/2K/4K。",
    GRS_PROFILE_NANO_BANANA_2: "使用 GRS Nano Banana 2 生成图片，支持超长画幅与 1K/2K/4K。",
}

BUILTIN_MODELS: tuple[dict[str, Any], ...] = (
    {
        "provider_model": "gpt-image-2",
        "display_name": "GPT Image 2",
        "profile": GRS_PROFILE_GPT_IMAGE_2,
        "default_enabled": True,
        "sort_order": 10,
        "is_default": True,
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
        "description": spec.get("description") or PROFILE_DESCRIPTIONS.get(profile, "使用 GRS 生成图片。"),
        "profile": profile,
        "resolutions": list(spec["resolutions"]) if spec.get("resolutions") else None,
        "enabled": spec.get("default_enabled", False) if enabled is None else enabled,
        "sort_order": int(spec.get("sort_order", 100)),
        "is_default": bool(spec.get("is_default", False)),
        "builtin": builtin,
    }


def builtin_catalog_records() -> list[dict[str, Any]]:
    return [catalog_record(item) for item in BUILTIN_MODELS]
