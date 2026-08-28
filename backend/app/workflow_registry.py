from __future__ import annotations

import math
import re
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .grs_catalog import (
    GRS_PROFILE_GPT_IMAGE_2,
    GRS_PROFILE_GPT_IMAGE_2_VIP,
    GRS_PROFILE_NANO_BANANA,
    GRS_PROFILE_NANO_BANANA_2,
    PROFILE_DESCRIPTIONS,
    builtin_entry,
)
from .models import JobMode


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    description: str
    reference_mode: str
    min_references: int
    max_references: int
    reference_labels: tuple[str, ...] = ()
    accepts_negative_prompt: bool = False
    accepts_image_size: bool = False
    supports_h3_options: bool = False
    option_schema: dict[str, Any] | None = None
    media_type: str = "video"
    executor: str = "comfyui"
    grs_profile: str | None = None
    catalog_group: str = ""

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("option_schema", None)
        data.pop("grs_profile", None)
        data["reference_labels"] = list(self.reference_labels)
        data["parameters"] = parameter_payload(self)
        group = CATALOG_GROUPS.get(self.catalog_group, {})
        data["catalog_group_label"] = group.get("label", "")
        data["catalog_group_order"] = int(group.get("order", 100))
        return data


def mode_key(mode: JobMode | str) -> str:
    return mode.value if isinstance(mode, JobMode) else str(mode)


def option(label: str, value_type: str, default: Any, *, group: str = "internal", **constraints: Any) -> dict[str, Any]:
    return {"label": label, "type": value_type, "default": default, "ui_group": group, **constraints}


def option_visible(definition: dict[str, Any], values: dict[str, Any]) -> bool:
    condition = definition.get("ui_visible_when")
    if not condition:
        return True
    return all(str(values.get(name)) == str(expected) for name, expected in condition.items())


GRS_ASPECT_RATIOS = [
    "auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
    "5:4", "4:5", "21:9", "9:21", "1:2", "2:1",
]

GRS_VIP_ASPECT_RATIOS = [*GRS_ASPECT_RATIOS, "1:3", "3:1"]

GRS_ASPECT_RATIO_UI_OPTIONS = [
    {"value": "auto", "label": "自动"},
    {"value": "1:1", "label": "1:1 方形"},
    {"value": "16:9", "label": "16:9 横屏"},
    {"value": "9:16", "label": "9:16 竖屏"},
    {"value": "4:3", "label": "4:3 标准"},
    {"value": "3:4", "label": "3:4 竖版"},
    {"value": "3:2", "label": "3:2 摄影"},
    {"value": "2:3", "label": "2:3 竖版摄影"},
    {"value": "5:4", "label": "5:4"},
    {"value": "4:5", "label": "4:5"},
    {"value": "21:9", "label": "21:9 超宽屏"},
    {"value": "9:21", "label": "9:21 竖向超宽"},
    {"value": "1:2", "label": "1:2"},
    {"value": "2:1", "label": "2:1"},
]

GRS_VIP_ASPECT_RATIO_UI_OPTIONS = [
    *GRS_ASPECT_RATIO_UI_OPTIONS,
    {"value": "1:3", "label": "1:3"},
    {"value": "3:1", "label": "3:1"},
]

GRS_VIP_SIZES: dict[str, dict[str, str]] = {
    "1:1": {"1K": "1024x1024", "2K": "2048x2048", "4K": "2880x2880"},
    "16:9": {"1K": "1280x720", "2K": "2048x1152", "4K": "3840x2160"},
    "9:16": {"1K": "720x1280", "2K": "1152x2048", "4K": "2160x3840"},
    "4:3": {"1K": "1152x864", "2K": "2304x1728", "4K": "3264x2448"},
    "3:4": {"1K": "864x1152", "2K": "1728x2304", "4K": "2448x3264"},
    "3:2": {"1K": "1536x1024", "2K": "2048x1360", "4K": "3504x2336"},
    "2:3": {"1K": "1024x1536", "2K": "1360x2048", "4K": "2336x3504"},
    "5:4": {"1K": "1120x896", "2K": "2240x1792", "4K": "3200x2560"},
    "4:5": {"1K": "896x1120", "2K": "1792x2240", "4K": "2560x3200"},
    "21:9": {"1K": "1456x624", "2K": "2912x1248", "4K": "3840x1648"},
    "9:21": {"1K": "624x1456", "2K": "1248x2912", "4K": "1648x3840"},
    "1:3": {"2K": "688x2048", "4K": "1280x3840"},
    "3:1": {"2K": "2048x688", "4K": "3840x1280"},
    "2:1": {"1K": "1536x768", "2K": "3072x1536", "4K": "3840x1920"},
    "1:2": {"1K": "768x1536", "2K": "1536x3072", "4K": "1920x3840"},
}

NANO_BANANA_ASPECT_RATIOS = [
    "auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9",
]
NANO_BANANA_2_ASPECT_RATIOS = [*NANO_BANANA_ASPECT_RATIOS, "1:4", "4:1", "1:8", "8:1"]
NANO_BANANA_ASPECT_RATIO_UI_OPTIONS = [
    item for item in GRS_ASPECT_RATIO_UI_OPTIONS if item["value"] in NANO_BANANA_ASPECT_RATIOS
]
NANO_BANANA_2_ASPECT_RATIO_UI_OPTIONS = [
    *NANO_BANANA_ASPECT_RATIO_UI_OPTIONS,
    {"value": "1:4", "label": "1:4"},
    {"value": "4:1", "label": "4:1"},
    {"value": "1:8", "label": "1:8"},
    {"value": "8:1", "label": "8:1"},
]


def grs_option_schema(
    profile: str, provider_model: str, resolutions: list[str] | None = None,
) -> dict[str, Any]:
    if profile == GRS_PROFILE_GPT_IMAGE_2:
        ratio_enum, ratio_ui = GRS_ASPECT_RATIOS, GRS_ASPECT_RATIO_UI_OPTIONS
        resolution_enum = list(resolutions or ["1K"])
        include_custom = False
    elif profile == GRS_PROFILE_GPT_IMAGE_2_VIP:
        ratio_enum, ratio_ui = GRS_VIP_ASPECT_RATIOS, GRS_VIP_ASPECT_RATIO_UI_OPTIONS
        resolution_enum = list(resolutions or ["1K", "2K", "4K", "CUSTOM"])
        include_custom = "CUSTOM" in resolution_enum
    elif profile == GRS_PROFILE_NANO_BANANA:
        ratio_enum, ratio_ui = NANO_BANANA_ASPECT_RATIOS, NANO_BANANA_ASPECT_RATIO_UI_OPTIONS
        resolution_enum = list(resolutions or ["1K", "2K", "4K"])
        include_custom = False
    elif profile == GRS_PROFILE_NANO_BANANA_2:
        ratio_enum, ratio_ui = NANO_BANANA_2_ASPECT_RATIOS, NANO_BANANA_2_ASPECT_RATIO_UI_OPTIONS
        resolution_enum = list(resolutions or ["1K", "2K", "4K"])
        include_custom = False
    else:
        raise ValueError(f"未知 GRS 生图能力档: {profile}")
    companions = ["resolution", "count"]
    if include_custom:
        companions.extend(["custom_width", "custom_height"])
    default_resolution = "1K" if "1K" in resolution_enum else resolution_enum[0]
    properties: dict[str, Any] = {
        "aspect_ratio": option(
            "比例", "string", "1:1", group="primary", enum=ratio_enum,
            ui_control="visual-settings", ui_companion="resolution",
            ui_companions=companions, ui_options=ratio_ui,
        ),
        "resolution": option(
            "分辨率", "string", default_resolution, group="primary", enum=resolution_enum,
            ui_control="select",
        ),
        "count": option(
            "生成数量", "integer", 1, group="primary", minimum=1, maximum=4, step=1,
            ui_control="input-number",
        ),
        "provider_model": option("远端模型", "string", provider_model, group="internal"),
        "poll_interval_seconds": option("轮询间隔", "integer", 5, minimum=5, maximum=30),
    }
    if include_custom:
        properties["custom_width"] = option(
            "自定义宽度", "integer", 1024, group="advanced", minimum=16, maximum=3840, step=16,
            unit="px", ui_control="input-number", ui_visible_when={"resolution": "CUSTOM"},
        )
        properties["custom_height"] = option(
            "自定义高度", "integer", 1024, group="advanced", minimum=16, maximum=3840, step=16,
            unit="px", ui_control="input-number", ui_visible_when={"resolution": "CUSTOM"},
        )
    return {"type": "object", "properties": properties}


def image_workflow_from_catalog(entry: dict[str, Any]) -> WorkflowDefinition:
    profile = entry["profile"]
    return WorkflowDefinition(
        entry["workflow_id"],
        entry["display_name"],
        entry.get("description") or PROFILE_DESCRIPTIONS.get(profile, "使用 GRS 生成图片。"),
        "collection",
        0,
        10,
        option_schema=grs_option_schema(profile, entry["provider_model"], entry.get("resolutions")),
        media_type="image",
        executor="grs",
        grs_profile=profile,
        catalog_group=CATALOG_GROUP_IMAGE,
    )


GRS_IMAGE_OPTION_SCHEMA = grs_option_schema(GRS_PROFILE_GPT_IMAGE_2, "gpt-image-2")
GRS_IMAGE_VIP_OPTION_SCHEMA = grs_option_schema(GRS_PROFILE_GPT_IMAGE_2_VIP, "gpt-image-2-vip")


CATALOG_GROUP_IMAGE = "image"
CATALOG_GROUP_LIGHTX2V = "lightx2v"
CATALOG_GROUP_DUAL_ACCEL = "dual_accel"
CATALOG_GROUP_OFFICIAL_H3 = "official_h3"
CATALOG_GROUP_CUSTOM = "custom"
CATALOG_GROUPS = {
    CATALOG_GROUP_IMAGE: {"label": "图片生成", "order": 0},
    CATALOG_GROUP_LIGHTX2V: {"label": "LightX2V", "order": 10},
    CATALOG_GROUP_DUAL_ACCEL: {"label": "八步双加速", "order": 15},
    CATALOG_GROUP_OFFICIAL_H3: {"label": "官方 MiniMax H3", "order": 20},
    CATALOG_GROUP_CUSTOM: {"label": "自定义", "order": 30},
}

H3_STANDARD_RESOLUTION_PRESETS = {
    "0.2": 0.2,
    "0.3": 0.3,
    "0.4": 0.4,
    "0.5": 0.5,
    "0.6": 0.6,
    "0.7": 0.7,
    "0.8": 0.8,
    "0.9": 0.9,
    "0.98": 0.98,
    "1.0": 1.0,
    "1.2": 1.2,
    "1.5": 1.5,
    "1.8": 1.8,
    "2.0": 2.0,
}
H3_T8_RESOLUTION_PRESETS = {
    "0.2": 0.2,
    "0.3": 0.3,
    "0.4": 0.4,
    "0.5": 0.5,
    "0.6": 0.6,
    "0.7": 0.7,
    "0.8": 0.8,
    "0.9": 0.9,
    "0.98": 0.98,
}
H3_LOCAL_RESOLUTION_PREVIEW = {
    "multiple": 32,
}
H3_DURATION_MIN_SEC = 2
H3_DURATION_MAX_SEC = 15
H3_FPS = 24
H3_TURBO_LORA_NAME = "minimax_h3_turbo_4STEPS_comfyui.safetensors"
LIGHTX2V_FL2V_4STEP_LORA = "minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors"
LIGHTX2V_FL2V_8STEP_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
LIGHTX2V_REF2V_4STEP_LORA = "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
LIGHTX2V_LORA_STRENGTH = 0.75
DUAL_ACCEL_LORA_NAME = LIGHTX2V_FL2V_8STEP_LORA
DUAL_ACCEL_LORA_STRENGTH = 1.0
H3_FL2VA_PRUNED = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
H3_FL2VA_FULL = "minimax_h3_fl2va_int8_convrot.safetensors"
H3_REF2VA_PRUNED = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
H3_REF2VA_FULL = "minimax_h3_ref2va_int8_convrot.safetensors"
H3_WEIGHT_FULL = "full"
H3_WEIGHT_PRUNED = "pruned"


def h3_turbo_lora_compatible(unet_name: str) -> bool:
    """Turbo LoRA AdaLN adapters are 2688-dim; pruned checkpoints use 8-dim AdaLN."""
    return "pruned" not in str(unet_name).lower()


def h3_lora_loader_class(unet_name: str) -> str:
    """Bypass is required for full INT8; pruned AdaLN cannot take the bypass loader."""
    return "LoraLoaderModelOnly" if "pruned" in unet_name else "LoraLoaderBypassModelOnly"


def h3_diffusion_unet(is_reference: bool, lora_strength: float) -> str:
    """Full INT8 for Turbo LoRA; pruned INT8 when acceleration is off."""
    use_turbo = float(lora_strength) != 0.0
    if is_reference:
        return H3_REF2VA_FULL if use_turbo else H3_REF2VA_PRUNED
    return H3_FL2VA_FULL if use_turbo else H3_FL2VA_PRUNED


def h3_weight_profile_option() -> dict[str, Any]:
    return option(
        "模型体积", "string", H3_WEIGHT_FULL, group="primary",
        enum=[H3_WEIGHT_FULL, H3_WEIGHT_PRUNED],
        ui_control="select",
        ui_options=[
            {"value": H3_WEIGHT_FULL, "label": "完整（32 GB）"},
            {"value": H3_WEIGHT_PRUNED, "label": "精简（20 GB）"},
        ],
        description="完整权重可挂加速 LoRA。精简权重关闭加速 LoRA，适合 32 GB 内存，避免加载时页面文件不足。",
    )


def apply_h3_weight_profile(normalized: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    profile = normalized.get("weight_profile", raw.get("weight_profile", H3_WEIGHT_FULL))
    if profile not in {H3_WEIGHT_FULL, H3_WEIGHT_PRUNED}:
        raise ValueError("模型体积请选择完整或精简。")
    normalized["weight_profile"] = profile
    if profile == H3_WEIGHT_PRUNED:
        normalized["lora_strength"] = 0.0
    if "unet_name" in normalized and "unet_name" not in raw:
        normalized["unet_name"] = h3_diffusion_unet(False, float(normalized.get("lora_strength", 0)))
    return normalized


H3_SPEED_FAST = "fast"
H3_SPEED_BALANCED = "balanced"
H3_SPEED_QUALITY = "quality"
H3_SPEED_CUSTOM = "custom"
H3_CUSTOM_STEPS_MIN = 1
H3_CUSTOM_STEPS_MAX = 40
H3_TURBO_STEP_MAX = 8
H3_SPEED_PRESETS = {
    H3_SPEED_FAST: {"steps": 4, "video_steps": 4, "audio_steps": 4, "lora_strength": 1.0},
    H3_SPEED_BALANCED: {"steps": 8, "video_steps": 8, "audio_steps": 10, "lora_strength": 1.0},
    H3_SPEED_QUALITY: {"steps": 20, "video_steps": 20, "audio_steps": 20, "lora_strength": 0.0},
}


def h3_speed_option() -> dict[str, Any]:
    return option(
        "生成速度", "string", H3_SPEED_BALANCED, group="primary",
        enum=[H3_SPEED_FAST, H3_SPEED_BALANCED, H3_SPEED_QUALITY, H3_SPEED_CUSTOM],
        ui_control="select",
        ui_options=[
            {"value": H3_SPEED_FAST, "label": "快速（4 步）"},
            {"value": H3_SPEED_BALANCED, "label": "均衡（8 步）"},
            {"value": H3_SPEED_QUALITY, "label": "高质量（20 步）"},
            {"value": H3_SPEED_CUSTOM, "label": "自定义"},
        ],
        description="快速为 4 步加速，适合预览；均衡为 8 步加速，适合日常成片；高质量关闭加速、使用完整采样；自定义可填 1–40 步。",
    )


def h3_custom_steps_option() -> dict[str, Any]:
    return option(
        "自定义步数", "integer", 8, group="primary",
        minimum=H3_CUSTOM_STEPS_MIN, maximum=H3_CUSTOM_STEPS_MAX, step=1,
        unit="步",
        ui_control="input-number",
        ui_visible_when={"speed": H3_SPEED_CUSTOM},
        description="4–8 步在完整权重下启用加速 LoRA；超过 8 步或选择精简权重时关闭加速。全能参考会把视频和音频采样都设为该步数。",
    )


def _speed_mapping(speed: str, custom_steps: int) -> dict[str, Any]:
    if speed == H3_SPEED_CUSTOM:
        return {
            "steps": custom_steps,
            "video_steps": custom_steps,
            "audio_steps": custom_steps,
            "lora_strength": 1.0 if custom_steps <= H3_TURBO_STEP_MAX else 0.0,
        }
    return H3_SPEED_PRESETS[speed]


def lightx2v_speed_option() -> dict[str, Any]:
    return option(
        "生成速度", "string", H3_SPEED_FAST, group="primary",
        enum=[H3_SPEED_FAST, H3_SPEED_BALANCED, H3_SPEED_QUALITY, H3_SPEED_CUSTOM],
        ui_control="select",
        ui_options=[
            {"value": H3_SPEED_FAST, "label": "快速（4 步 LightX2V）"},
            {"value": H3_SPEED_BALANCED, "label": "均衡（8 步 LightX2V）"},
            {"value": H3_SPEED_QUALITY, "label": "高质量（20 步）"},
            {"value": H3_SPEED_CUSTOM, "label": "自定义"},
        ],
        description="快速为 4 步 LightX2V 加速，默认 1.0 MP，适合日常成片；均衡为 8 步加速；高质量关闭加速、使用完整采样。",
    )


def _lightx2v_lora_for(speed: str, custom_steps: int, *, is_reference: bool) -> tuple[str, float]:
    if speed == H3_SPEED_QUALITY:
        return (LIGHTX2V_REF2V_4STEP_LORA if is_reference else LIGHTX2V_FL2V_4STEP_LORA), 0.0
    if speed == H3_SPEED_BALANCED or (speed == H3_SPEED_CUSTOM and custom_steps > 4):
        if speed == H3_SPEED_CUSTOM and custom_steps > H3_TURBO_STEP_MAX:
            return (LIGHTX2V_REF2V_4STEP_LORA if is_reference else LIGHTX2V_FL2V_8STEP_LORA), 0.0
        return (
            (LIGHTX2V_REF2V_4STEP_LORA, LIGHTX2V_LORA_STRENGTH)
            if is_reference
            else (LIGHTX2V_FL2V_8STEP_LORA, LIGHTX2V_LORA_STRENGTH)
        )
    return (
        (LIGHTX2V_REF2V_4STEP_LORA, LIGHTX2V_LORA_STRENGTH)
        if is_reference
        else (LIGHTX2V_FL2V_4STEP_LORA, LIGHTX2V_LORA_STRENGTH)
    )


def dual_accel_speed_option() -> dict[str, Any]:
    return option(
        "生成速度", "string", H3_SPEED_BALANCED, group="primary",
        enum=[H3_SPEED_BALANCED, H3_SPEED_QUALITY, H3_SPEED_CUSTOM],
        ui_control="select",
        ui_options=[
            {"value": H3_SPEED_BALANCED, "label": "八步双加速"},
            {"value": H3_SPEED_QUALITY, "label": "高质量（20 步）"},
            {"value": H3_SPEED_CUSTOM, "label": "自定义"},
        ],
        description="默认 8 步 FL2V Turbo LoRA，并串联 KJ Sage 与 H3 显存高效 Sage；高质量关闭 LoRA、使用完整采样。",
    )


def apply_dual_accel_speed_preset(normalized: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    speed = normalized.get("speed", H3_SPEED_BALANCED)
    if speed not in {H3_SPEED_BALANCED, H3_SPEED_QUALITY, H3_SPEED_CUSTOM}:
        raise ValueError("八步双加速请选择八步双加速、高质量或自定义。")
    apply_h3_speed_preset(normalized, raw)
    if "lora_name" not in raw:
        normalized["lora_name"] = DUAL_ACCEL_LORA_NAME
    if "lora_strength" not in raw and normalized["speed"] != H3_SPEED_QUALITY:
        if not (normalized["speed"] == H3_SPEED_CUSTOM and int(normalized.get("custom_steps", 8)) > H3_TURBO_STEP_MAX):
            normalized["lora_strength"] = DUAL_ACCEL_LORA_STRENGTH
    apply_h3_weight_profile(normalized, raw)
    normalized.setdefault("sampler_name", "res_multistep")
    normalized.setdefault("shift_video", 12.0)
    normalized.setdefault("shift_audio", 3.0)
    normalized.setdefault("use_sage_attention", True)
    normalized.setdefault("reference_image_size", "match")
    return normalized


def dual_accel_option_schema() -> dict[str, Any]:
    properties = dict(H3_STANDARD_OPTION_SCHEMA["properties"])
    properties["quality"] = option(
        "分辨率", "string", "0.4", group="advanced", ui_control="select",
        enum=list(H3_STANDARD_RESOLUTION_PRESETS),
        ui_options=local_resolution_options(H3_STANDARD_RESOLUTION_PRESETS),
        megapixels_by_quality=H3_STANDARD_RESOLUTION_PRESETS,
        ui_resolution_preview=H3_LOCAL_RESOLUTION_PREVIEW,
        description="八步双加速默认 0.4 MP（16:9 约 864×480），与参考工作流画布一致。",
    )
    properties["megapixels"] = option(
        "内部像素面积", "number", 0.4, group="internal", minimum=0.1, maximum=16.0, step=0.1, unit="MP",
    )
    properties["speed"] = dual_accel_speed_option()
    properties["lora_name"] = option(
        "加速 LoRA", "string", DUAL_ACCEL_LORA_NAME,
        enum=[DUAL_ACCEL_LORA_NAME],
    )
    properties["lora_strength"] = option("LoRA 强度", "number", DUAL_ACCEL_LORA_STRENGTH, minimum=-100, maximum=100, step=0.01)
    properties["sampler_name"] = option("采样器", "string", "res_multistep", enum=["res_multistep", "euler"])
    properties["shift_video"] = option("视频 Shift", "number", 12, minimum=0.01, maximum=100, step=0.01)
    properties["shift_audio"] = option("音频 Shift", "number", 3, minimum=0.01, maximum=100, step=0.01)
    properties["use_sage_attention"] = option("SageAttention", "boolean", True)
    return {"type": "object", "properties": properties}


def apply_lightx2v_speed_preset(
    normalized: dict[str, Any], raw: dict[str, Any], *, is_reference: bool,
) -> dict[str, Any]:
    apply_h3_speed_preset(normalized, raw)
    lora_name, lora_strength = _lightx2v_lora_for(
        normalized["speed"], int(normalized.get("custom_steps", 8)), is_reference=is_reference,
    )
    if "lora_name" not in raw:
        normalized["lora_name"] = lora_name
    if "lora_strength" not in raw:
        normalized["lora_strength"] = lora_strength
    apply_h3_weight_profile(normalized, raw)
    normalized.setdefault("sampler_name", "euler")
    normalized.setdefault("shift_video", 12.0)
    normalized.setdefault("shift_audio", 3.0)
    normalized.setdefault("use_sage_attention", True)
    normalized.setdefault("reference_image_size", "match")
    return normalized


def lightx2v_option_schema() -> dict[str, Any]:
    properties = dict(H3_STANDARD_OPTION_SCHEMA["properties"])
    properties["quality"] = option(
        "分辨率", "string", "1.0", group="advanced", ui_control="select",
        enum=list(H3_STANDARD_RESOLUTION_PRESETS),
        ui_options=local_resolution_options(H3_STANDARD_RESOLUTION_PRESETS),
        megapixels_by_quality=H3_STANDARD_RESOLUTION_PRESETS,
        ui_resolution_preview=H3_LOCAL_RESOLUTION_PREVIEW,
        description="LightX2V 默认 1.0 MP（16:9 约 1376×768）；尺寸会随画面比例变化。",
    )
    properties["megapixels"] = option(
        "内部像素面积", "number", 1.0, group="internal", minimum=0.1, maximum=16.0, step=0.1, unit="MP",
    )
    properties["speed"] = lightx2v_speed_option()
    properties["lora_name"] = option(
        "加速 LoRA", "string", LIGHTX2V_FL2V_4STEP_LORA,
        enum=[LIGHTX2V_FL2V_4STEP_LORA, LIGHTX2V_FL2V_8STEP_LORA, LIGHTX2V_REF2V_4STEP_LORA],
    )
    properties["lora_strength"] = option("LoRA 强度", "number", LIGHTX2V_LORA_STRENGTH, minimum=-100, maximum=100, step=0.01)
    properties["sampler_name"] = option("采样器", "string", "euler", enum=["euler", "res_multistep"])
    properties["shift_video"] = option("视频 Shift", "number", 12, minimum=0.01, maximum=100, step=0.01)
    properties["shift_audio"] = option("音频 Shift", "number", 3, minimum=0.01, maximum=100, step=0.01)
    properties["use_sage_attention"] = option("SageAttention", "boolean", True)
    return {"type": "object", "properties": properties}


def apply_h3_speed_preset(normalized: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    speed = normalized.get("speed", H3_SPEED_BALANCED)
    if speed not in {H3_SPEED_FAST, H3_SPEED_BALANCED, H3_SPEED_QUALITY, H3_SPEED_CUSTOM}:
        raise ValueError("MiniMax H3 请选择快速、均衡、高质量或自定义。")
    custom_steps = normalized.get("custom_steps", raw.get("custom_steps", 8))
    if isinstance(custom_steps, bool) or not isinstance(custom_steps, (int, float)) or not float(custom_steps).is_integer():
        raise ValueError("自定义步数必须为整数。")
    custom_steps = int(custom_steps)
    if not H3_CUSTOM_STEPS_MIN <= custom_steps <= H3_CUSTOM_STEPS_MAX:
        raise ValueError(f"自定义步数必须在 {H3_CUSTOM_STEPS_MIN} 到 {H3_CUSTOM_STEPS_MAX} 之间。")
    normalized["speed"] = speed
    normalized["custom_steps"] = custom_steps
    mapping = _speed_mapping(speed, custom_steps)
    for key in ("steps", "video_steps", "audio_steps", "lora_strength"):
        if key in normalized and key not in raw:
            normalized[key] = mapping[key]
        elif key not in normalized and key in {"steps", "lora_strength"}:
            normalized[key] = mapping[key]
    normalized.setdefault("lora_name", H3_TURBO_LORA_NAME)
    normalized.setdefault("use_sage_attention", True)
    return apply_h3_weight_profile(normalized, raw)


def local_resolution_options(presets: dict[str, float]) -> list[dict[str, str]]:
    return [{"value": key, "label": f"{megapixels:g} MP"} for key, megapixels in presets.items()]


H3_STANDARD_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "aspect_ratio": option(
            "画面比例", "string", "16:9", group="primary",
            pattern=r"^(?:\d+(?:\.\d*)?|\.\d+)\s*:\s*(?:\d+(?:\.\d*)?|\.\d+)$",
            ui_control="visual-settings",
            ui_companion="quality",
            ui_options=[
                {"value": "16:9", "label": "16:9 横屏"},
                {"value": "9:16", "label": "9:16 竖屏"},
                {"value": "1:1", "label": "1:1 方形"},
                {"value": "4:3", "label": "4:3 标准"},
                {"value": "3:4", "label": "3:4 竖版"},
                {"value": "3:2", "label": "3:2 摄影"},
                {"value": "2:3", "label": "2:3 竖版摄影"},
                {"value": "21:9", "label": "21:9 超宽屏"},
            ],
            description="任意有限正数的宽:高比例，例如 16:9、2:3、3:2 或 21:9。",
        ),
        "quality": option(
            "分辨率", "string", "0.2", group="advanced", ui_control="select",
            enum=list(H3_STANDARD_RESOLUTION_PRESETS),
            ui_options=local_resolution_options(H3_STANDARD_RESOLUTION_PRESETS),
            megapixels_by_quality=H3_STANDARD_RESOLUTION_PRESETS,
            ui_resolution_preview=H3_LOCAL_RESOLUTION_PREVIEW,
            description="选择实际输出尺寸；尺寸会随画面比例变化，最高档 16:9 为 1920×1088。",
        ),
        "megapixels": option(
            "内部像素面积", "number", 0.2, group="internal", minimum=0.1, maximum=16.0, step=0.1, unit="MP",
        ),
        "duration": option(
            "时长", "number", 5, group="primary",
            minimum=H3_DURATION_MIN_SEC, maximum=H3_DURATION_MAX_SEC, step=1, unit="秒",
            ui_control="duration-slider",
            description="按秒选择输出时长；实际帧数会对齐 MiniMax H3 的 24fps、17n+5 网格，2 秒约为 56 帧。",
        ),
        "speed": h3_speed_option(),
        "custom_steps": h3_custom_steps_option(),
        "weight_profile": h3_weight_profile_option(),
        "steps": option("采样步数", "integer", H3_SPEED_PRESETS[H3_SPEED_BALANCED]["steps"], minimum=1, maximum=1000, step=1),
        "lora_name": option(
            "加速 LoRA", "string", H3_TURBO_LORA_NAME,
            enum=[H3_TURBO_LORA_NAME],
        ),
        "lora_strength": option("LoRA 强度", "number", 1, minimum=-100, maximum=100, step=0.01),
        "use_sage_attention": option("SageAttention", "boolean", True),
    },
}

T8_ASPECT_RATIOS = [
    "1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)",
    "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)",
]


def t8_option_schema(*, sampler: str) -> dict[str, Any]:
    multirate = sampler == "multirate"
    # The T8 conditioning node rejects canvases larger than 768x1344. 0.98 MP
    # resolves to that maximum at 16:9 with ComfyUI's 32-pixel grid.
    quality_megapixels = H3_T8_RESOLUTION_PRESETS
    default_quality = "0.4" if multirate else "0.7"
    properties: dict[str, Any] = {
        "task_type": option(
            "任务类型", "string", "auto", enum=["auto", "T2VA", "Ref2VA"],
            description="auto 会按参考图数量选择文生或参考图生成。",
        ),
        "aspect_ratio": option(
            "画面比例", "string", "16:9 (Widescreen)", group="primary", enum=T8_ASPECT_RATIOS,
            ui_control="visual-settings", ui_companion="quality",
        ),
        "quality": option(
            "分辨率", "string", default_quality, group="advanced", ui_control="select",
            enum=list(quality_megapixels),
            ui_options=local_resolution_options(quality_megapixels),
            megapixels_by_quality=quality_megapixels,
            ui_resolution_preview=H3_LOCAL_RESOLUTION_PREVIEW,
            description="选择实际输出尺寸；尺寸会随画面比例变化，最高为 1344×768。",
        ),
        "megapixels": option(
            "内部像素面积", "number", quality_megapixels[default_quality], group="internal",
            minimum=0.1, maximum=16.0, step=0.1, unit="MP",
        ),
        "multiple": option("尺寸对齐倍数", "integer", 32, minimum=8, maximum=128, step=4),
        "duration": option(
            "时长", "number", 8 if multirate else 5, group="primary",
            minimum=H3_DURATION_MIN_SEC, maximum=H3_DURATION_MAX_SEC, step=1, unit="秒",
            ui_control="duration-slider",
            description="按秒选择输出时长；实际帧数会对齐 MiniMax H3 的 24fps、17n+5 网格，2 秒约为 56 帧。",
        ),
        "speed": h3_speed_option(),
        "custom_steps": h3_custom_steps_option(),
        "weight_profile": h3_weight_profile_option(),
        "seed": option(
            "随机种子", "integer", 123456789,
            minimum=0, maximum=1125899906842624, step=1,
            description="使用相同种子和参数可获得更接近的结果。",
        ),
        "audio_mode": option(
            "音频模式", "string", "native",
            enum=["lock_source", "remix_source", "reference_only", "native"],
        ),
        "audio_denoise_strength": option("音频去噪强度", "number", 1, minimum=0, maximum=1, step=0.01),
        "add_source_as_reference": option("将源音频作为参考", "boolean", False),
        "prompt_primary_audio_ordinal": option("提示词主音频序号", "integer", 0, minimum=0, maximum=9, step=1),
        "strict_prompt_tags": option("严格校验媒体标签", "boolean", True),
        "ref_image_size": option("参考图尺寸策略", "string", "max" if multirate else "match", enum=["match", "max"]),
        "reference_video_policy": option(
            "参考视频时长策略", "string", "official_2_to_15s",
            enum=["official_2_to_15s", "model_minimum"],
        ),
        "shift_video": option("视频 Shift", "number", 12, minimum=0.01, maximum=100, step=0.01),
        "shift_audio": option("音频 Shift", "number", 3, minimum=0.01, maximum=100, step=0.01),
        "unet_name": option(
            "扩散模型", "string", H3_FL2VA_FULL,
            enum=[H3_FL2VA_FULL, H3_FL2VA_PRUNED, H3_REF2VA_FULL, H3_REF2VA_PRUNED],
        ),
        "weight_dtype": option(
            "模型权重类型", "string", "default",
            enum=["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"],
        ),
        "clip_name": option(
            "文本编码器", "string", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            enum=["qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"],
        ),
        "clip_device": option("文本编码设备", "string", "default", enum=["default", "cpu"]),
        "video_vae": option(
            "视频 VAE", "string", "minimax_h3_video_vae_fp16.safetensors",
            enum=["minimax_h3_video_vae_fp16.safetensors"],
        ),
        "audio_vae": option(
            "音频 VAE", "string", "minimax_h3_audio_vae_fp32.safetensors",
            enum=["minimax_h3_audio_vae_fp32.safetensors"],
        ),
        "lora_name": option(
            "加速 LoRA", "string", H3_TURBO_LORA_NAME,
            enum=[H3_TURBO_LORA_NAME],
        ),
        "lora_strength": option("LoRA 强度", "number", 1, minimum=-100, maximum=100, step=0.01),
        "use_sage_attention": option("启用 SageAttention", "boolean", True),
        "frame_rate": option("输出帧率", "number", 24, minimum=1, maximum=120, step=1, unit="fps"),
        "loop_count": option("额外循环次数", "integer", 0, minimum=0, maximum=100, step=1),
        "output_format": option(
            "输出格式", "string", "video/h264-mp4",
            enum=["video/h264-mp4"],
        ),
        "pixel_format": option("像素格式", "string", "yuv420p", enum=["yuv420p", "yuv420p10le"]),
        "crf": option("编码 CRF", "integer", 19, minimum=0, maximum=100, step=1),
        "save_metadata": option("保存工作流元数据", "boolean", True),
        "trim_to_audio": option("按音频裁剪", "boolean", False),
        "pingpong": option("往返循环", "boolean", False),
    }
    if multirate:
        properties.update({
            "video_steps": option("视频采样步数", "integer", 8, minimum=1, maximum=1000, step=1),
            "audio_steps": option("音频采样步数", "integer", 10, minimum=1, maximum=1000, step=1),
            "reserved_vram": option("预留显存", "number", 1, minimum=-2, maximum=128, step=0.1, unit="GB"),
            "reserved_vram_mode": option("预留显存模式", "string", "manual", enum=["manual", "auto"]),
            "reserved_vram_seed": option("显存策略种子", "integer", 0, minimum=-1, maximum=1125899906842624, step=1),
            "auto_max_reserved_vram": option("自动预留显存上限", "number", 0, minimum=0, maximum=128, step=0.1, unit="GB"),
            "clean_gpu_before": option("运行前清理显存", "boolean", True),
        })
    else:
        properties["steps"] = option("双时钟采样步数", "integer", 8, minimum=1, maximum=1000, step=1)
    return {"type": "object", "properties": properties}


T8_MULTIRATE_OPTION_SCHEMA = t8_option_schema(sampler="multirate")
T8_DUAL_CLOCK_OPTION_SCHEMA = t8_option_schema(sampler="dual-clock")


LIGHTX2V_OPTION_SCHEMA = lightx2v_option_schema()
DUAL_ACCEL_OPTION_SCHEMA = dual_accel_option_schema()

WORKFLOWS: tuple[WorkflowDefinition, ...] = (
    WorkflowDefinition(
        JobMode.MINIMAX_H3_LIGHTX2V_T2V.value,
        "LightX2V 文生视频",
        "使用 LightX2V 4/8 步加速 LoRA 的文生视频；默认 1.0 MP、euler 采样。",
        "none",
        0,
        0,
        supports_h3_options=True,
        option_schema=LIGHTX2V_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_LIGHTX2V,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_LIGHTX2V_I2V.value,
        "LightX2V 首尾帧视频",
        "使用 LightX2V 加速 LoRA 的首尾帧视频；首帧必填，尾帧可选。",
        "keyframes",
        1,
        2,
        ("首帧", "尾帧（可选）"),
        supports_h3_options=True,
        option_schema=LIGHTX2V_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_LIGHTX2V,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_LIGHTX2V_R2V.value,
        "LightX2V 多参考视频",
        "使用 LightX2V Ref2V 加速 LoRA；按顺序添加参考并在提示词中引用 <Picture n>。",
        "collection",
        1,
        9,
        supports_h3_options=True,
        option_schema=LIGHTX2V_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_LIGHTX2V,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_DUAL_ACCEL_T2V.value,
        "八步双加速 文生视频",
        "8 步 FL2V Turbo LoRA，串联 KJ Sage 与 H3 显存高效 Sage；默认 0.4 MP、res_multistep。",
        "none",
        0,
        0,
        supports_h3_options=True,
        option_schema=DUAL_ACCEL_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_DUAL_ACCEL,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_DUAL_ACCEL_I2V.value,
        "八步双加速 首尾帧视频",
        "8 步双 Sage 加速的图生视频；首帧必填，尾帧可选。",
        "keyframes",
        1,
        2,
        ("首帧", "尾帧（可选）"),
        supports_h3_options=True,
        option_schema=DUAL_ACCEL_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_DUAL_ACCEL,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_DUAL_ACCEL_R2V.value,
        "八步双加速 多参考视频",
        "8 步双 Sage 加速的多参考视频；按顺序添加参考并在提示词中引用 <Picture n>。",
        "collection",
        1,
        9,
        supports_h3_options=True,
        option_schema=DUAL_ACCEL_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_DUAL_ACCEL,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_T2V.value,
        "MiniMax H3 文生视频",
        "根据提示词生成带原生音频的视频。",
        "none",
        0,
        0,
        supports_h3_options=True,
        catalog_group=CATALOG_GROUP_OFFICIAL_H3,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_I2V.value,
        "MiniMax H3 首尾帧视频",
        "首帧和尾帧是时间锚点；可以只使用首帧。",
        "keyframes",
        1,
        2,
        ("首帧", "尾帧（可选）"),
        supports_h3_options=True,
        catalog_group=CATALOG_GROUP_OFFICIAL_H3,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_R2V.value,
        "MiniMax H3 多参考视频",
        "按顺序添加角色、场景或风格参考，并在提示词中引用 <Picture n>。",
        "collection",
        1,
        9,
        supports_h3_options=True,
        catalog_group=CATALOG_GROUP_OFFICIAL_H3,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_T8_ALL_REFERENCE.value,
        "MiniMax H3 全能参考（多速率）",
        "支持 0-9 张有序参考图，自动匹配文生或参考图生成。",
        "collection",
        0,
        9,
        supports_h3_options=True,
        option_schema=T8_MULTIRATE_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_CUSTOM,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_T8_DUAL_CLOCK.value,
        "MiniMax H3 双时钟加速",
        "支持文生或单参考图生成，使用双时钟采样；可在快速 4 步、均衡 8 步与高质量 20 步之间切换。",
        "collection",
        0,
        1,
        supports_h3_options=True,
        option_schema=T8_DUAL_CLOCK_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_CUSTOM,
    ),
)

WORKFLOW_BY_ID = {definition.id: definition for definition in WORKFLOWS}
T8_WORKFLOWS = {JobMode.MINIMAX_H3_T8_ALL_REFERENCE, JobMode.MINIMAX_H3_T8_DUAL_CLOCK}
LIGHTX2V_WORKFLOWS = {
    JobMode.MINIMAX_H3_LIGHTX2V_T2V,
    JobMode.MINIMAX_H3_LIGHTX2V_I2V,
    JobMode.MINIMAX_H3_LIGHTX2V_R2V,
}
DUAL_ACCEL_WORKFLOWS = {
    JobMode.MINIMAX_H3_DUAL_ACCEL_T2V,
    JobMode.MINIMAX_H3_DUAL_ACCEL_I2V,
    JobMode.MINIMAX_H3_DUAL_ACCEL_R2V,
}
H3_WORKFLOWS = {
    JobMode.MINIMAX_H3_T2V,
    JobMode.MINIMAX_H3_I2V,
    JobMode.MINIMAX_H3_R2V,
    *LIGHTX2V_WORKFLOWS,
    *DUAL_ACCEL_WORKFLOWS,
    *T8_WORKFLOWS,
}
T8_WORKFLOW_IDS = {item.value for item in T8_WORKFLOWS}
LIGHTX2V_WORKFLOW_IDS = {item.value for item in LIGHTX2V_WORKFLOWS}
DUAL_ACCEL_WORKFLOW_IDS = {item.value for item in DUAL_ACCEL_WORKFLOWS}
DEFAULT_DIRECTOR_WORKFLOW_FAMILY = CATALOG_GROUP_OFFICIAL_H3


def director_route_key(definition: WorkflowDefinition) -> str | None:
    if definition.media_type != "video":
        return None
    if definition.reference_mode == "none":
        return "t2v"
    if definition.reference_mode == "keyframes":
        return "i2v"
    if definition.reference_mode == "collection":
        if definition.min_references == 0:
            return "standalone"
        if definition.max_references >= 3:
            return "r2v"
    return None


def director_workflow_families() -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    standalones: list[dict[str, Any]] = []
    for definition in WORKFLOWS:
        route = director_route_key(definition)
        if route is None:
            continue
        group_meta = CATALOG_GROUPS.get(definition.catalog_group, {})
        if route == "standalone":
            standalones.append({
                "id": definition.id,
                "label": definition.name,
                "order": int(group_meta.get("order", 100)),
                "routes": {"t2v": definition.id, "i2v": definition.id, "r2v": definition.id},
            })
            continue
        group_id = definition.catalog_group or definition.id
        entry = grouped.setdefault(group_id, {
            "id": group_id,
            "label": group_meta.get("label") or definition.name,
            "order": int(group_meta.get("order", 100)),
            "routes": {},
        })
        entry["routes"][route] = definition.id
    families = [item for item in grouped.values() if item["routes"]] + standalones
    families.sort(key=lambda item: (int(item["order"]), str(item["label"])))
    return families


def resolve_director_workflow(family: str | None, route: str) -> str:
    wanted = route if route in {"t2v", "i2v", "r2v"} else "t2v"
    families = {item["id"]: item for item in director_workflow_families()}
    chosen = families.get(str(family or "").strip()) or families.get(DEFAULT_DIRECTOR_WORKFLOW_FAMILY)
    routes = (chosen or {}).get("routes") or {}
    return str(routes.get(wanted) or routes.get("t2v") or JobMode.MINIMAX_H3_T2V.value)
H3_WORKFLOW_IDS = {item.value for item in H3_WORKFLOWS}
_catalog_lookup: Callable[[str], dict[str, Any] | None] | None = None


def set_catalog_lookup(lookup: Callable[[str], dict[str, Any] | None] | None) -> None:
    global _catalog_lookup
    _catalog_lookup = lookup


def is_h3_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in H3_WORKFLOW_IDS


def is_t8_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in T8_WORKFLOW_IDS


def is_lightx2v_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in LIGHTX2V_WORKFLOW_IDS


def is_dual_accel_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in DUAL_ACCEL_WORKFLOW_IDS


def generation_family_label(mode: JobMode | str) -> str:
    if is_lightx2v_workflow(mode):
        return "LightX2V"
    if is_dual_accel_workflow(mode):
        return "八步双加速"
    if is_h3_workflow(mode):
        return "MiniMax H3"
    return ""


def generation_stage(mode: JobMode | str) -> str:
    family = generation_family_label(mode)
    return f"{family} 正在生成视频" if family else "正在生成"


def generation_output_label(mode: JobMode | str) -> str:
    family = generation_family_label(mode)
    return f"{family} 视频" if family else "生成视频"


def is_image_workflow(mode: JobMode | str) -> bool:
    key = mode_key(mode)
    if key in WORKFLOW_BY_ID:
        return WORKFLOW_BY_ID[key].media_type == "image"
    if key == JobMode.IMAGE.value or key.startswith("grs-"):
        return True
    try:
        return workflow_for(key).media_type == "image"
    except KeyError:
        return False


# Historical GRS workflow IDs remain valid for job history and builtin fallback.
IMAGE_WORKFLOWS = {JobMode.GRS_GPT_IMAGE_2, JobMode.GRS_GPT_IMAGE_2_VIP}

H3_QUALITY_MEGAPIXELS = H3_STANDARD_OPTION_SCHEMA["properties"]["quality"]["megapixels_by_quality"]
H3_LEGACY_QUALITY_MEGAPIXELS = {"1K": 0.2, "2K": 0.3, "4K": 0.5}
H3_LEGACY_MEGAPIXELS = set(H3_QUALITY_MEGAPIXELS.values()) | {0.98}
H3_OPTION_NAMES = {"aspect_ratio", "quality", "megapixels", "duration", "speed", "custom_steps", "weight_profile", "use_sage_attention"}
H3_ASPECT_RATIO_PART = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)")


def parse_h3_aspect_ratio(value: Any) -> tuple[str, float]:
    text = str(value).strip()
    parts = [part.strip() for part in text.split(":")]
    if len(parts) != 2 or any(not H3_ASPECT_RATIO_PART.fullmatch(part) for part in parts):
        raise ValueError("MiniMax H3 aspect ratio must use positive numbers, for example 16:9 or 2:3")
    width, height = (float(part) for part in parts)
    ratio = width / height if height else 0.0
    if width <= 0 or height <= 0 or not math.isfinite(ratio):
        raise ValueError("MiniMax H3 aspect ratio values must be finite positive numbers")
    return f"{parts[0]}:{parts[1]}", ratio


def parameter_payload(definition: WorkflowDefinition) -> list[dict[str, Any]]:
    """Describe the exact multipart fields accepted by POST /api/jobs for one workflow."""
    parameters: list[dict[str, Any]] = [
        {
            "name": "mode", "label": "工作流", "type": "string", "required": True,
            "description": "固定为当前工作流 ID。", "default": definition.id,
            "values": [definition.id],
        },
        {
            "name": "prompt", "label": "创作提示词", "type": "string", "required": True,
            "description": "去除首尾空白后不能为空。",
        },
        {
            "name": "references", "label": "参考图", "type": "array",
            "required": definition.min_references > 0,
            "description": "图片文件数组。多图工作流按上传顺序解释参考图。单张文件最大 50 MB。",
            "min_items": definition.min_references, "max_items": definition.max_references,
            "content_type": "image/*",
        },
    ]
    if definition.accepts_negative_prompt:
        parameters.append({
            "name": "negative_prompt", "label": "负面提示词", "type": "string", "required": False,
            "description": "仅图片生成工作流生效。", "default": "",
        })
    if definition.accepts_image_size:
        parameters.append({
            "name": "image_size", "label": "图片尺寸", "type": "string", "required": True,
            "description": "图片生成工作流的输出画布尺寸。",
            "values": ["横版 1280 x 720", "方图 1024 x 1024", "竖版 720 x 1280"],
        })
    if definition.option_schema is not None or definition.supports_h3_options:
        parameters.append({
            "name": "options", "label": "生成参数", "type": "string", "required": False,
            "description": "JSON 字符串；未传时使用各字段默认值。", "default": "{}",
            "schema": definition.option_schema or H3_STANDARD_OPTION_SCHEMA,
        })
    return parameters


def catalog_entry_for(mode: JobMode | str) -> dict[str, Any] | None:
    key = mode_key(mode)
    if _catalog_lookup is not None:
        try:
            found = _catalog_lookup(key)
        except Exception:
            found = None
        if found is not None:
            return found
    return builtin_entry(workflow_id=key)


def workflow_for(mode: JobMode | str) -> WorkflowDefinition:
    key = mode_key(mode)
    if key in WORKFLOW_BY_ID:
        return WORKFLOW_BY_ID[key]
    entry = catalog_entry_for(key)
    if entry is not None:
        return image_workflow_from_catalog(entry)
    raise KeyError(key)


def validate_references(mode: JobMode | str, references: list[object]) -> None:
    try:
        definition = workflow_for(mode)
    except KeyError as error:
        raise ValueError(f"工作流 {mode_key(mode)} 已从当前工作台移除") from error
    count = len(references)
    if not definition.min_references <= count <= definition.max_references:
        if definition.min_references == definition.max_references:
            raise ValueError(f"{definition.name} 需要 {definition.min_references} 张参考图。")
        raise ValueError(
            f"{definition.name} 支持 {definition.min_references}-{definition.max_references} 张参考图，当前为 {count} 张。"
        )


def normalize_options(mode: JobMode | str, raw: dict[str, Any] | None) -> dict[str, Any]:
    if is_image_workflow(mode):
        definition = workflow_for(mode)
        normalized = _normalize_schema_options(definition.option_schema or {}, raw or {})
        provider_default = (definition.option_schema or {}).get("properties", {}).get("provider_model", {}).get("default")
        if provider_default:
            normalized["provider_model"] = provider_default
        if definition.grs_profile == GRS_PROFILE_GPT_IMAGE_2_VIP and normalized["resolution"] == "CUSTOM":
            width = normalized["custom_width"]
            height = normalized["custom_height"]
            if width % 16 or height % 16:
                raise ValueError("VIP 自定义宽高必须是 16 的倍数。")
            ratio = max(width / height, height / width)
            pixels = width * height
            if ratio > 3:
                raise ValueError("VIP 自定义尺寸的长宽比不能超过 3:1。")
            if not 655_360 <= pixels <= 8_294_400:
                raise ValueError("VIP 自定义尺寸总像素必须在 655360 到 8294400 之间。")
        elif definition.grs_profile == GRS_PROFILE_GPT_IMAGE_2_VIP and normalized["aspect_ratio"] != "auto":
            if normalized["resolution"] not in GRS_VIP_SIZES.get(normalized["aspect_ratio"], {}):
                raise ValueError("当前画面比例不支持所选分辨率。")
        return normalized
    if not is_h3_workflow(mode):
        return {}
    raw = raw or {}
    if is_t8_workflow(mode):
        return _normalize_schema_options(workflow_for(mode).option_schema or {}, raw)
    if is_lightx2v_workflow(mode):
        normalized = _normalize_schema_options(workflow_for(mode).option_schema or {}, raw, apply_speed=False)
        return apply_lightx2v_speed_preset(
            normalized, raw, is_reference=mode_key(mode) == JobMode.MINIMAX_H3_LIGHTX2V_R2V.value,
        )
    if is_dual_accel_workflow(mode):
        normalized = _normalize_schema_options(workflow_for(mode).option_schema or {}, raw, apply_speed=False)
        return apply_dual_accel_speed_preset(normalized, raw)
    unknown_options = set(raw) - H3_OPTION_NAMES
    if unknown_options:
        names = ", ".join(sorted(unknown_options))
        raise ValueError(f"MiniMax H3 does not support options: {names}")
    aspect_ratio, _ = parse_h3_aspect_ratio(raw.get("aspect_ratio", "16:9"))
    quality = raw.get("quality")
    legacy_megapixels = raw.get("megapixels")
    legacy_quality = quality in H3_LEGACY_QUALITY_MEGAPIXELS
    if legacy_quality:
        legacy_megapixels = H3_LEGACY_QUALITY_MEGAPIXELS[raw["quality"]]
        quality = min(H3_QUALITY_MEGAPIXELS, key=lambda item: abs(H3_QUALITY_MEGAPIXELS[item] - legacy_megapixels))
    if quality is None and legacy_megapixels is not None and float(legacy_megapixels) not in H3_LEGACY_MEGAPIXELS:
        raise ValueError("MiniMax H3 请选择当前工作流支持的分辨率。")
    if quality is None and legacy_megapixels is not None:
        quality = min(H3_QUALITY_MEGAPIXELS, key=lambda item: abs(H3_QUALITY_MEGAPIXELS[item] - float(legacy_megapixels)))
    quality = quality or next(iter(H3_QUALITY_MEGAPIXELS))
    duration = float(raw.get("duration", 5))
    if quality not in H3_QUALITY_MEGAPIXELS:
        raise ValueError("MiniMax H3 请选择当前工作流支持的分辨率。")
    if not H3_DURATION_MIN_SEC <= duration <= H3_DURATION_MAX_SEC:
        raise ValueError(f"MiniMax H3 时长必须在 {H3_DURATION_MIN_SEC} 到 {H3_DURATION_MAX_SEC} 秒之间。")
    speed = raw.get("speed", H3_SPEED_BALANCED)
    custom_steps = raw.get("custom_steps", 8)
    use_sage = raw.get("use_sage_attention", True)
    if not isinstance(use_sage, bool):
        raise ValueError("SageAttention 必须为布尔值。")
    return apply_h3_speed_preset({
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "megapixels": float(legacy_megapixels) if legacy_megapixels is not None and (raw.get("quality") is None or legacy_quality) else H3_QUALITY_MEGAPIXELS[quality],
        "duration": duration,
        "reference_image_size": "match",
        "speed": speed,
        "custom_steps": custom_steps,
        "weight_profile": raw.get("weight_profile", H3_WEIGHT_FULL),
        "use_sage_attention": use_sage,
    }, raw)


def _normalize_schema_options(
    schema: dict[str, Any], raw: dict[str, Any], *, apply_speed: bool = True,
) -> dict[str, Any]:
    definitions = schema.get("properties", {})
    unknown_options = set(raw) - set(definitions)
    if unknown_options:
        names = ", ".join(sorted(unknown_options))
        raise ValueError(f"当前工作流不支持参数: {names}")
    normalized: dict[str, Any] = {}
    for name, definition in definitions.items():
        if name == "seed":
            normalized[name] = secrets.randbelow(2**63 - 1)
            continue
        value = raw.get(name, definition.get("default"))
        value_type = definition.get("type")
        if value_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{definition['label']} 必须为布尔值。")
        elif value_type == "integer":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not float(value).is_integer():
                raise ValueError(f"{definition['label']} 必须为整数。")
            value = int(value)
        elif value_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{definition['label']} 必须为数字。")
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"{definition['label']} 必须为有限数字。")
        elif value_type == "string":
            if not isinstance(value, str):
                raise ValueError(f"{definition['label']} 必须为字符串。")
            value = value.strip()
        if "enum" in definition and value not in definition["enum"]:
            raise ValueError(f"{definition['label']} 不是有效选项。")
        if "minimum" in definition and value < definition["minimum"]:
            raise ValueError(f"{definition['label']} 不能小于 {definition['minimum']}。")
        if "maximum" in definition and value > definition["maximum"]:
            raise ValueError(f"{definition['label']} 不能大于 {definition['maximum']}。")
        normalized[name] = value
    quality_definition = definitions.get("quality")
    if quality_definition:
        quality_map = quality_definition.get("megapixels_by_quality", {})
        if "quality" in raw:
            normalized["megapixels"] = quality_map[normalized["quality"]]
    if apply_speed and "speed" in definitions:
        apply_h3_speed_preset(normalized, raw)
    if "audio_steps" in normalized and normalized["audio_steps"] < normalized["video_steps"]:
        raise ValueError("音频采样步数不能小于视频采样步数。")
    return normalized


def quality_for_megapixels(schema: dict[str, Any], megapixels: Any) -> str | None:
    """Map legacy stored MP values to the nearest current user-facing quality preset."""
    quality_definition = schema.get("properties", {}).get("quality", {})
    quality_map = quality_definition.get("megapixels_by_quality", {})
    if not quality_map or isinstance(megapixels, bool) or not isinstance(megapixels, (int, float)):
        return None
    return min(quality_map, key=lambda quality: abs(quality_map[quality] - float(megapixels)))


def validate_option_relationships(mode: JobMode | str, options: dict[str, Any], reference_count: int) -> None:
    if is_t8_workflow(mode) and options.get("task_type") == "Ref2VA" and reference_count == 0:
        raise ValueError("Ref2VA 任务类型至少需要 1 张参考图。")


def grs_request_size(mode: JobMode | str, options: dict[str, Any]) -> tuple[str, str | None]:
    """Map registry values to the GRS wire-level aspectRatio/imageSize fields."""
    definition = workflow_for(mode)
    aspect_ratio = options["aspect_ratio"]
    resolution = options["resolution"]
    if definition.grs_profile != GRS_PROFILE_GPT_IMAGE_2_VIP:
        return aspect_ratio, resolution
    if resolution == "CUSTOM":
        return f"{options['custom_width']}x{options['custom_height']}", None
    if aspect_ratio == "auto":
        return aspect_ratio, resolution
    return GRS_VIP_SIZES[aspect_ratio][resolution], resolution


def h3_dimensions(options: dict[str, Any]) -> tuple[int, int]:
    _, ratio = parse_h3_aspect_ratio(options["aspect_ratio"])
    # Keep the workbench calculation byte-for-byte compatible with ComfyUI's
    # ResolutionSelector: MP is based on 1024² and each side is rounded to the
    # configured 32-pixel alignment grid.
    area = options["megapixels"] * 1024 * 1024
    if not math.isfinite(area * ratio) or not math.isfinite(area / ratio):
        raise ValueError("MiniMax H3 aspect ratio is outside the supported numeric range")
    width = round(math.sqrt(area * ratio) / 32) * 32
    height = round(math.sqrt(area / ratio) / 32) * 32
    return width, height


def h3_length(options: dict[str, Any]) -> int:
    frames = max(5, round(float(options["duration"]) * H3_FPS))
    return frames + ((5 - frames) % 17)
