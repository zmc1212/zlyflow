from __future__ import annotations

import math
import json
import re
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .grs_catalog import (
    GRS_PROFILE_GPT_IMAGE_2,
    GRS_PROFILE_GPT_IMAGE_2_VIP,
    GRS_PROFILE_GPT_IMAGE_2_5,
    GRS_PROFILE_GPT_IMAGE_2_5_VIP,
    GRS_PROFILE_NANO_BANANA,
    GRS_PROFILE_NANO_BANANA_2,
    builtin_entry,
    effective_description,
)
from .models import JobMode
from .h3_depth_workflow import DEPTH_DEFAULT_PROMPT, DEPTH_LENGTHS
from .h3_video_edit_workflow import VIDEO_EDIT_MODELS, VIDEO_EDIT_LENGTHS
from .h3_keyframe_workflow import resolve_keyframe_dimensions
from .h3_motion_transfer_workflow import MOTION_TRANSFER_DEFAULT_PROMPT, resolve_motion_transfer_dimensions
from .image_edit_workflow import (
    DEFAULT_SAM3_MODEL,
    DEFAULT_SAM3_REFINE_ITERATIONS,
    DEFAULT_SAM3_THRESHOLD,
    DEFAULT_SUBJECT_PROMPT,
)
from .grs_composite import DEFAULT_COMPOSITE_PROVIDER_MODEL, OUTPAINT_TARGET_ASPECTS
from .scail2_workflow import SCAIL_DEFAULT_PROMPT, SCAIL_MODELS, DPO_LORA, LIGHT_LORA, subject_points

_TRUE_BOOL_TEXTS = {"true", "1", "yes", "on"}
_FALSE_BOOL_TEXTS = {"false", "0", "no", "off", ""}


def coerce_bool_option(value: Any, *, label: str) -> bool:
    """Accept JSON booleans and the string forms the workshop settings persist."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in _TRUE_BOOL_TEXTS:
        return True
    if value is None or (isinstance(value, str) and value.strip().lower() in _FALSE_BOOL_TEXTS):
        return False
    raise ValueError(f"{label} 必须为布尔值。")


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
    hidden_from_catalog: bool = False
    supports_timeline: bool = False
    supports_multi_segment: bool = False
    max_segments: int | None = None
    max_total_frames: int | None = None
    supports_segment_continuity: bool = False
    supports_audio_batch: bool = False
    accepts_audio_reference: bool = False
    accepts_video_reference: bool = False
    default_prompt: str | None = None
    # 显式槽位声明（如口型同步的 ("video", "audio")）；优先于 accepts_* 布尔推断。
    reference_slots: tuple[str, ...] = ()
    # GRS 生图目录的「默认模型」标记：决定创作页预选与导演台自动出图使用的模型，与显示顺序无关。
    is_default: bool = False
    # GRS 平台标价积分（每张），来自上游价格接口，只用于创作页与管理页展示，不参与提交参数。
    credit_cost: int | None = None

    def reference_kind(self, index: int) -> str:
        if self.reference_slots and 1 <= index <= len(self.reference_slots):
            return self.reference_slots[index - 1]
        if index == 2 and self.accepts_video_reference:
            return "video"
        if index == 2 and self.accepts_audio_reference:
            return "audio"
        return "image"

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("option_schema", None)
        data.pop("grs_profile", None)
        data["reference_labels"] = list(self.reference_labels)
        data["parameters"] = parameter_payload(self)
        data["director_controls"] = director_controls(self)
        group = CATALOG_GROUPS.get(self.catalog_group, {})
        data["catalog_group_label"] = group.get("label", "")
        data["catalog_group_order"] = int(group.get("order", 100))
        return data

    def public_payload(self) -> dict[str, Any]:
        """Expose creative controls for browsing, without runtime configuration."""
        data = self.payload()
        data.pop("director_controls", None)
        parameters = []
        for parameter in data["parameters"]:
            parameter = dict(parameter)
            schema = parameter.get("schema")
            if schema is not None:
                properties = {
                    name: dict(value) for name, value in schema.get("properties", {}).items()
                    if value.get("ui_group") in {"primary", "advanced"}
                }
                parameter["schema"] = {"type": "object", "properties": properties}
            parameters.append(parameter)
        data["parameters"] = parameters
        return data


def mode_key(mode: JobMode | str) -> str:
    return mode.value if isinstance(mode, JobMode) else str(mode)


def director_controls(definition: WorkflowDefinition) -> list[dict[str, Any]]:
    """Recipe field bindings are declared here, never inferred by the UI."""
    if not definition.supports_h3_options:
        return []
    properties = (definition.option_schema or H3_STANDARD_OPTION_SCHEMA).get("properties", {})
    bindings = [
        ("aspect_ratio", "aspectRatio", "primary", "画面比例"),
        ("quality", "finalQuality", "advanced", "画质"),
        ("speed", "finalSpeed", "advanced", "生成质量"),
    ]
    result = []
    for name, field, group, label in bindings:
        schema = properties.get(name)
        if not schema:
            continue
        choices = schema.get("ui_options") or [{"value": value, "label": str(value)} for value in schema.get("enum", [])]
        if name == "speed":
            labels = {"fast": "快速", "balanced": "均衡", "quality": "精细"}
            choices = [{"value": item["value"], "label": labels[item["value"]]} for item in choices if item["value"] in labels]
        result.append({"field": field, "option": name, "label": label, "ui_group": group,
                       "default": schema.get("default"), "options": choices,
                       "preview_field": {"quality": "previewQuality", "speed": "previewSpeed"}.get(name)})
    return result


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

# GPT Image 2.5 高画质档（flare/sunburst）的画质档位：影响计费，走 advanced 组。
GPT_IMAGE_25_FLARE_QUALITY = ["low", "medium", "high"]
GPT_IMAGE_25_FLARE_DEFAULT_QUALITY = "medium"

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
    quality_options: list[str] | None = None, default_quality: str | None = None,
) -> dict[str, Any]:
    if profile == GRS_PROFILE_GPT_IMAGE_2:
        ratio_enum, ratio_ui = GRS_ASPECT_RATIOS, GRS_ASPECT_RATIO_UI_OPTIONS
        resolution_enum = list(resolutions or ["1K"])
        include_custom = False
    elif profile == GRS_PROFILE_GPT_IMAGE_2_VIP:
        ratio_enum, ratio_ui = GRS_VIP_ASPECT_RATIOS, GRS_VIP_ASPECT_RATIO_UI_OPTIONS
        resolution_enum = list(resolutions or ["1K", "2K", "4K", "CUSTOM"])
        include_custom = "CUSTOM" in resolution_enum
    elif profile == GRS_PROFILE_GPT_IMAGE_2_5:
        # GPT Image 2.5 系列不接受 "1:1" 等比例字符串，线上协议必须传像素值，
        # 因此比例枚举与 VIP 档保持一致（含 auto），由 grs_request_size 统一映射。
        ratio_enum, ratio_ui = GRS_VIP_ASPECT_RATIOS, GRS_VIP_ASPECT_RATIO_UI_OPTIONS
        resolution_enum = list(resolutions or ["1K"])
        include_custom = False
    elif profile == GRS_PROFILE_GPT_IMAGE_2_5_VIP:
        ratio_enum, ratio_ui = GRS_VIP_ASPECT_RATIOS, GRS_VIP_ASPECT_RATIO_UI_OPTIONS
        resolution_enum = list(resolutions or ["1K", "2K", "4K"])
        include_custom = False
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
    if profile == GRS_PROFILE_GPT_IMAGE_2_5_VIP:
        quality_enum = [item for item in (quality_options or GPT_IMAGE_25_FLARE_QUALITY) if item]
        properties["quality"] = option(
            "画质", "string", default_quality or GPT_IMAGE_25_FLARE_DEFAULT_QUALITY, group="advanced",
            enum=quality_enum, ui_control="select",
        )
    return {"type": "object", "properties": properties}


def image_workflow_from_catalog(entry: dict[str, Any]) -> WorkflowDefinition:
    profile = entry["profile"]
    credit_cost = entry.get("credit_cost")
    return WorkflowDefinition(
        entry["workflow_id"],
        entry["display_name"],
        effective_description(entry),
        "collection",
        0,
        10,
        option_schema=grs_option_schema(
            profile, entry["provider_model"], entry.get("resolutions"),
            entry.get("quality_options"), entry.get("default_quality"),
        ),
        media_type="image",
        executor="grs",
        grs_profile=profile,
        catalog_group=CATALOG_GROUP_IMAGE,
        is_default=bool(entry.get("is_default")),
        credit_cost=int(credit_cost) if credit_cost else None,
    )


GRS_IMAGE_OPTION_SCHEMA = grs_option_schema(GRS_PROFILE_GPT_IMAGE_2, "gpt-image-2")
GRS_IMAGE_VIP_OPTION_SCHEMA = grs_option_schema(GRS_PROFILE_GPT_IMAGE_2_VIP, "gpt-image-2-vip")


CATALOG_GROUP_IMAGE = "image"
CATALOG_GROUP_IMAGE_EDIT = "image_edit"
CATALOG_GROUP_LIGHTX2V = "lightx2v"
CATALOG_GROUP_DUAL_ACCEL = "dual_accel"
CATALOG_GROUP_DIRECTOR_ACCEL = "h3_director_accel"
CATALOG_GROUP_OFFICIAL_H3 = "official_h3"
CATALOG_GROUP_CUSTOM = "custom"
CATALOG_GROUPS = {
    CATALOG_GROUP_IMAGE: {"label": "图片生成", "order": 0},
    CATALOG_GROUP_IMAGE_EDIT: {"label": "图片编辑", "order": 1},
    CATALOG_GROUP_LIGHTX2V: {"label": "LightX2V", "order": 10},
    CATALOG_GROUP_DUAL_ACCEL: {"label": "八步双加速", "order": 15},
    CATALOG_GROUP_DIRECTOR_ACCEL: {"label": "H3 Director 加速版", "order": 17},
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
        "模型体积", "string", H3_WEIGHT_FULL, group="internal",
        enum=[H3_WEIGHT_FULL, H3_WEIGHT_PRUNED],
        ui_control="select",
        ui_options=[
            {"value": H3_WEIGHT_FULL, "label": "完整（32 GB）"},
            {"value": H3_WEIGHT_PRUNED, "label": "精简（20 GB）"},
        ],
        description="完整权重可挂加速 LoRA；精简权重关闭加速 LoRA，适合 32 GB 内存机器。平台按 ComfyUI 机器内存自动选择。",
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
        "生成速度", "string", H3_SPEED_BALANCED, group="internal",
        enum=[H3_SPEED_FAST, H3_SPEED_BALANCED, H3_SPEED_QUALITY, H3_SPEED_CUSTOM],
        ui_control="select",
        ui_options=[
            {"value": H3_SPEED_FAST, "label": "快速（4 步）"},
            {"value": H3_SPEED_BALANCED, "label": "均衡（8 步）"},
            {"value": H3_SPEED_QUALITY, "label": "高质量（20 步）"},
            {"value": H3_SPEED_CUSTOM, "label": "自定义"},
        ],
        description="快速为 4 步加速，适合预览；均衡为 8 步加速，适合日常成片；高质量关闭加速、使用完整采样；自定义可填 1–40 步。平台按工作流默认档位与机器配置自动托管。",
    )


def h3_custom_steps_option() -> dict[str, Any]:
    return option(
        "自定义步数", "integer", 8, group="internal",
        minimum=H3_CUSTOM_STEPS_MIN, maximum=H3_CUSTOM_STEPS_MAX, step=1,
        unit="步",
        ui_control="input-number",
        ui_visible_when={"speed": H3_SPEED_CUSTOM},
        description="4–8 步在完整权重下启用加速 LoRA；超过 8 步或选择精简权重时关闭加速。全能参考会把视频和音频采样都设为该步数。",
    )


# --- 生成档位与模型体积自动托管 -------------------------------------------------
# speed / weight_profile 属于采样步数与设备精度类技术参数，按产品规范由后端托管：
# 创建表单不展示，客户端未显式提交时结合 ComfyUI 机器配置自动取最合适的组合。
# 完整 INT8 权重约 32 GB，加载需要同等量级内存；精简约 20 GB，适合 32 GB 内存机器。
# 阈值取 40 GiB：内存明显高于完整权重体积才托管为完整权重。
H3_WEIGHT_FULL_MIN_RAM_BYTES = 40 * 1024**3

_hardware_profile_resolver: Callable[[], dict[str, Any] | None] | None = None


def set_hardware_profile_resolver(
    resolver: Callable[[], dict[str, Any] | None] | None,
) -> None:
    """注入 ComfyUI 硬件探测；normalize_options 据此托管 speed / weight_profile。"""
    global _hardware_profile_resolver
    _hardware_profile_resolver = resolver


def hardware_profile() -> dict[str, Any] | None:
    if _hardware_profile_resolver is None:
        return None
    try:
        stats = _hardware_profile_resolver()
    except Exception:
        return None
    return stats if isinstance(stats, dict) and stats else None


def comfy_ram_total_bytes(stats: dict[str, Any] | None) -> int | None:
    """从 ComfyUI /system_stats 读取系统内存总量（字节）。"""
    system = (stats or {}).get("system")
    total = system.get("ram_total") if isinstance(system, dict) else None
    if isinstance(total, bool) or not isinstance(total, (int, float)) or total <= 0:
        return None
    return int(total)


def auto_weight_profile(stats: dict[str, Any] | None) -> str:
    ram = comfy_ram_total_bytes(stats)
    if ram is None:
        return H3_WEIGHT_FULL
    return H3_WEIGHT_PRUNED if ram < H3_WEIGHT_FULL_MIN_RAM_BYTES else H3_WEIGHT_FULL


def auto_h3_runtime_options(raw: dict[str, Any], *, default_speed: str) -> dict[str, Any]:
    """客户端未手选时按机器内存托管生成档位与模型体积。

    精简权重挂不了加速 LoRA，8 步无加速属于欠采样组合，因此内存紧张时
    同步切到高质量（20 步完整采样）；显式提交的值始终优先。
    """
    explicit_speed = "speed" in raw
    explicit_weight = "weight_profile" in raw
    if explicit_speed and explicit_weight:
        return {}
    stats = hardware_profile()
    if not stats:
        return {}
    profile = auto_weight_profile(stats)
    auto: dict[str, Any] = {}
    if explicit_speed:
        chosen = str(raw.get("speed"))
        try:
            steps = int(raw.get("custom_steps") or 8)
        except (TypeError, ValueError):
            steps = 8
        needs_turbo = chosen in {H3_SPEED_FAST, H3_SPEED_BALANCED} or (
            chosen == H3_SPEED_CUSTOM and steps <= H3_TURBO_STEP_MAX
        )
        if not explicit_weight:
            auto["weight_profile"] = H3_WEIGHT_FULL if needs_turbo else profile
        return auto
    if explicit_weight:
        if str(raw.get("weight_profile")) == H3_WEIGHT_PRUNED:
            auto["speed"] = H3_SPEED_QUALITY
        return auto
    auto["weight_profile"] = profile
    auto["speed"] = default_speed if profile == H3_WEIGHT_FULL else H3_SPEED_QUALITY
    return auto


def auto_h3_weight_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """仅托管模型体积，用于生成档位不依赖加速权重的管线。"""
    if "weight_profile" in raw:
        return {}
    stats = hardware_profile()
    if not stats:
        return {}
    return {"weight_profile": auto_weight_profile(stats)}


def refine_enabled_option(description: str) -> dict[str, Any]:
    return option("二采精修", "boolean", False, group="primary", description=description)


# Refine sampling cost tracks frames × target megapixels on the 16 GB remote card:
# 328 frames measured 16.9 s/step at 0.4 MP, 29.4 s/step at 0.6 MP, 557 s/step at 1.0 MP.
# Keep the product under this budget so long clips never fall into the paging regime.
REFINE_FRAME_MEGAPIXEL_BUDGET = 200.0
REFINE_MIN_MEGAPIXELS = 0.4


def refine_target_megapixels(refine_quality: str | float, frames: int, *, force: bool = False) -> float:
    requested = float(refine_quality)
    if force:
        return math.floor(requested * 10 + 1e-6) / 10
    budgeted = REFINE_FRAME_MEGAPIXEL_BUDGET / max(1, int(frames))
    return max(REFINE_MIN_MEGAPIXELS, math.floor(min(requested, budgeted) * 10 + 1e-6) / 10)


def refine_quality_mode_option() -> dict[str, Any]:
    return option(
        "清晰度策略", "string", "auto", group="primary", ui_control="select",
        enum=["auto", "force"],
        ui_options=[
            {"value": "auto", "label": "自动（推荐）"},
            {"value": "force", "label": "强制高清"},
        ],
        ui_visible_when={"refine_enabled": True},
        description="自动：按片长控制二采像素（片长×目标像素约 200），长片自动降档，保证出片时间可控。强制：严格按目标清晰度输出，长片会显著变慢并可能因显存不足失败；提交前会再次确认。",
    )


def refine_quality_option() -> dict[str, Any]:
    return option(
        "目标清晰度", "string", "1.0", group="primary", ui_control="select",
        enum=["1.0", "2.0"],
        ui_options=[
            {"value": "1.0", "label": "高清 1.0 MP（16:9 约 1376×768）"},
            {"value": "2.0", "label": "超清 2.0 MP（16:9 约 1920×1088）"},
        ],
        ui_visible_when={"refine_enabled": True},
        description="二采的目标清晰度上限。自动策略下 13 秒长片约 0.6 MP（约 2 分钟二采），8 秒内可用 1.0 MP，4 秒内可用 2.0 MP；强制策略下按此目标原样输出。",
    )


def refine_preview_option() -> dict[str, Any]:
    return option(
        "先预览一采", "boolean", True,
        description="平台固定开启：二采先只跑一采并停下，由你确认后再用同一 seed 只跑二采；一采结果可保留或放弃重来。整集直出无法中途确认，会自动连续跑完两段式。",
    )


# MiniMaxH3DirectorRefine.upscale_method, verified against the live render host
# /object_info. h3_latent is the calibrated path; the others stay platform-owned.
REFINE_DEFAULT_UPSCALE_METHOD = "h3_latent"
REFINE_UPSCALE_METHODS = ("lanczos", "nvidia_rtx_vsr", "h3_latent")


def refine_upscale_method_option() -> dict[str, Any]:
    return option(
        "二采放大方式", "string", REFINE_DEFAULT_UPSCALE_METHOD, group="internal",
        enum=list(REFINE_UPSCALE_METHODS),
        description=(
            "平台内部参数，不在界面暴露。h3_latent：按目标画布放大 H3 视频 latent 再二采（实测有效）；"
            "lanczos：像素插值放大；nvidia_rtx_vsr：需要渲染机安装 nvidia-vfx 扩展。"
        ),
    )


def refine_upscale_method_value(values: dict[str, Any] | None) -> str:
    raw = str((values or {}).get("refine_upscale_method") or "").strip()
    return raw if raw in REFINE_UPSCALE_METHODS else REFINE_DEFAULT_UPSCALE_METHOD


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
        "生成速度", "string", H3_SPEED_FAST, group="internal",
        enum=[H3_SPEED_FAST, H3_SPEED_BALANCED, H3_SPEED_QUALITY, H3_SPEED_CUSTOM],
        ui_control="select",
        ui_options=[
            {"value": H3_SPEED_FAST, "label": "快速（4 步 LightX2V）"},
            {"value": H3_SPEED_BALANCED, "label": "均衡（8 步 LightX2V）"},
            {"value": H3_SPEED_QUALITY, "label": "高质量（20 步）"},
            {"value": H3_SPEED_CUSTOM, "label": "自定义"},
        ],
        description="快速为 4 步 LightX2V 加速，默认 1.0 MP，适合日常成片；均衡为 8 步加速；高质量关闭加速、使用完整采样。平台按工作流默认档位与机器配置自动托管。",
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
        "生成速度", "string", H3_SPEED_BALANCED, group="internal",
        enum=[H3_SPEED_BALANCED, H3_SPEED_QUALITY, H3_SPEED_CUSTOM],
        ui_control="select",
        ui_options=[
            {"value": H3_SPEED_BALANCED, "label": "八步双加速"},
            {"value": H3_SPEED_QUALITY, "label": "高质量（20 步）"},
            {"value": H3_SPEED_CUSTOM, "label": "自定义"},
        ],
        description="默认 8 步 FL2V Turbo LoRA，并串联 KJ Sage 与 H3 显存高效 Sage；高质量关闭 LoRA、使用完整采样。平台按工作流默认档位与机器配置自动托管。",
    )


def apply_dual_accel_speed_preset(normalized: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    normalized.update(auto_h3_runtime_options(raw, default_speed=H3_SPEED_BALANCED))
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
    properties.pop("refine_enabled", None)
    properties.pop("refine_quality", None)
    properties.pop("refine_quality_mode", None)
    properties["quality"] = option(
        "分辨率", "string", "0.4", group="advanced", ui_control="select",
        enum=list(H3_STANDARD_RESOLUTION_PRESETS),
        ui_options=local_resolution_options(H3_STANDARD_RESOLUTION_PRESETS),
        megapixels_by_quality=H3_STANDARD_RESOLUTION_PRESETS,
        ui_resolution_preview=H3_LOCAL_RESOLUTION_PREVIEW,
        ui_visible_when={"refine_enabled": False},
        description="八步双加速默认 0.4 MP（16:9 约 864×480），与参考工作流画布一致。",
    )
    properties["megapixels"] = option(
        "内部像素面积", "number", 0.4, group="internal", minimum=0.1, maximum=16.0, step=0.1, unit="MP",
    )
    properties["speed"] = {**dual_accel_speed_option(), "ui_visible_when": {"refine_enabled": False}}
    properties["custom_steps"] = {
        **properties["custom_steps"],
        "ui_visible_when": {"speed": H3_SPEED_CUSTOM, "refine_enabled": False},
    }
    properties["weight_profile"] = {**h3_weight_profile_option(), "ui_visible_when": {"refine_enabled": False}}
    properties["lora_name"] = option(
        "加速 LoRA", "string", DUAL_ACCEL_LORA_NAME,
        enum=[DUAL_ACCEL_LORA_NAME],
    )
    properties["lora_strength"] = option("LoRA 强度", "number", DUAL_ACCEL_LORA_STRENGTH, minimum=-100, maximum=100, step=0.01)
    properties["sampler_name"] = option("采样器", "string", "res_multistep", enum=["res_multistep", "euler"])
    properties["shift_video"] = option("视频 Shift", "number", 12, minimum=0.01, maximum=100, step=0.01)
    properties["shift_audio"] = option("音频 Shift", "number", 3, minimum=0.01, maximum=100, step=0.01)
    properties["use_sage_attention"] = option("SageAttention", "boolean", True)
    properties["refine_enabled"] = refine_enabled_option(
        "开启后平台固定以 0.4 MP + 八步双加速一采生成底片，再用 H3 3D latent 放大到目标画质精修（3 步 beta，denoise 0.2）。"
    )
    properties["refine_quality_mode"] = refine_quality_mode_option()
    properties["refine_quality"] = refine_quality_option()
    properties["refine_upscale_method"] = refine_upscale_method_option()
    return {"type": "object", "properties": properties}


DIRECTOR_ACCEL_SPEED_PRESETS = {
    H3_SPEED_BALANCED: {"steps": 20, "video_steps": 20, "audio_steps": 20},
    H3_SPEED_QUALITY: {"steps": 25, "video_steps": 25, "audio_steps": 25},
}


def director_accel_speed_option() -> dict[str, Any]:
    return option(
        "生成质量", "string", H3_SPEED_BALANCED, group="internal",
        enum=[H3_SPEED_BALANCED, H3_SPEED_QUALITY],
        ui_control="select",
        ui_options=[
            {"value": H3_SPEED_BALANCED, "label": "均衡（20 步）"},
            {"value": H3_SPEED_QUALITY, "label": "精细（25 步）"},
        ],
        description="无 4 步 Turbo LoRA；均衡为 20 步双 Sage，精细为 25 步完整采样。平台按工作流默认档位托管。",
    )


def director_accel_weight_profile_option() -> dict[str, Any]:
    return option(
        "模型体积", "string", H3_WEIGHT_FULL, group="internal",
        enum=[H3_WEIGHT_FULL, H3_WEIGHT_PRUNED],
        ui_control="select",
        ui_options=[
            {"value": H3_WEIGHT_FULL, "label": "完整（32 GB）"},
            {"value": H3_WEIGHT_PRUNED, "label": "精简（20 GB）"},
        ],
        description="加速版默认完整 INT8；加速来自双 Sage，不挂 Turbo LoRA。精简权重约 20 GB，适合内存紧张的机器。平台按 ComfyUI 机器内存自动选择。",
    )


def apply_director_accel_speed_preset(normalized: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    normalized.update(auto_h3_weight_profile(raw))
    speed = normalized.get("speed", H3_SPEED_BALANCED)
    if speed not in DIRECTOR_ACCEL_SPEED_PRESETS:
        raise ValueError("H3 Director 加速版请选择均衡或精细。")
    mapping = DIRECTOR_ACCEL_SPEED_PRESETS[speed]
    for key in ("steps", "video_steps", "audio_steps"):
        if key not in raw:
            normalized[key] = mapping[key]
        elif key not in normalized:
            normalized[key] = mapping[key]
    apply_h3_weight_profile(normalized, raw)
    normalized["lora_strength"] = 0.0
    normalized.setdefault("sampler_name", "res_multistep")
    normalized.setdefault("shift_video", 12.0)
    normalized.setdefault("shift_audio", 3.0)
    normalized.setdefault("cfg", 1.0)
    normalized.setdefault("use_sage_attention", True)
    normalized.setdefault("sage_allow_compile", True)
    normalized.setdefault("reference_image_size", "match")
    return normalized


def director_accel_option_schema() -> dict[str, Any]:
    properties = dict(H3_STANDARD_OPTION_SCHEMA["properties"])
    properties.pop("refine_enabled", None)
    properties.pop("refine_quality", None)
    properties.pop("refine_quality_mode", None)
    properties["quality"] = option(
        "分辨率", "string", "0.4", group="advanced", ui_control="select",
        enum=list(H3_STANDARD_RESOLUTION_PRESETS),
        ui_options=local_resolution_options(H3_STANDARD_RESOLUTION_PRESETS),
        megapixels_by_quality=H3_STANDARD_RESOLUTION_PRESETS,
        ui_resolution_preview=H3_LOCAL_RESOLUTION_PREVIEW,
        ui_visible_when={"refine_enabled": False},
        description="H3 Director 加速版默认 0.4 MP（16:9 约 864×480），与参考工作流画布一致。",
    )
    properties["megapixels"] = option(
        "内部像素面积", "number", 0.4, group="internal", minimum=0.1, maximum=16.0, step=0.1, unit="MP",
    )
    properties["speed"] = {**director_accel_speed_option(), "ui_visible_when": {"refine_enabled": False}}
    properties["weight_profile"] = {**director_accel_weight_profile_option(), "ui_visible_when": {"refine_enabled": False}}
    properties.pop("custom_steps", None)
    properties.pop("lora_name", None)
    properties.pop("lora_strength", None)
    properties["steps"] = option("采样步数", "integer", 20, minimum=1, maximum=1000, step=1)
    properties["sampler_name"] = option("采样器", "string", "res_multistep", enum=["res_multistep", "euler"])
    properties["shift_video"] = option("视频 Shift", "number", 12, minimum=0.01, maximum=100, step=0.01)
    properties["shift_audio"] = option("音频 Shift", "number", 3, minimum=0.01, maximum=100, step=0.01)
    properties["cfg"] = option("CFG", "number", 1, minimum=0, maximum=20, step=0.1)
    properties["use_sage_attention"] = option("SageAttention", "boolean", True)
    properties["sage_allow_compile"] = option("Sage 允许编译", "boolean", True)
    properties["refine_enabled"] = refine_enabled_option(
        "开启后平台固定以 0.4 MP + 精简权重 + 均衡 20 步一采生成底片，再用 H3 3D latent 放大到目标画质精修（3 步 beta，denoise 0.2）。"
    )
    properties["refine_quality_mode"] = refine_quality_mode_option()
    properties["refine_quality"] = refine_quality_option()
    properties["refine_upscale_method"] = refine_upscale_method_option()
    return {"type": "object", "properties": properties}


def apply_lightx2v_speed_preset(
    normalized: dict[str, Any], raw: dict[str, Any], *, is_reference: bool,
) -> dict[str, Any]:
    normalized.update(auto_h3_runtime_options(raw, default_speed=H3_SPEED_FAST))
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
    properties.pop("refine_enabled", None)
    properties.pop("refine_quality", None)
    properties.pop("refine_quality_mode", None)
    properties["quality"] = option(
        "分辨率", "string", "1.0", group="advanced", ui_control="select",
        enum=list(H3_STANDARD_RESOLUTION_PRESETS),
        ui_options=local_resolution_options(H3_STANDARD_RESOLUTION_PRESETS),
        megapixels_by_quality=H3_STANDARD_RESOLUTION_PRESETS,
        ui_resolution_preview=H3_LOCAL_RESOLUTION_PREVIEW,
        ui_visible_when={"refine_enabled": False},
        description="LightX2V 默认 1.0 MP（16:9 约 1376×768）；尺寸会随画面比例变化。",
    )
    properties["megapixels"] = option(
        "内部像素面积", "number", 1.0, group="internal", minimum=0.1, maximum=16.0, step=0.1, unit="MP",
    )
    properties["speed"] = {**lightx2v_speed_option(), "ui_visible_when": {"refine_enabled": False}}
    properties["custom_steps"] = {
        **properties["custom_steps"],
        "ui_visible_when": {"speed": H3_SPEED_CUSTOM, "refine_enabled": False},
    }
    properties["weight_profile"] = {**h3_weight_profile_option(), "ui_visible_when": {"refine_enabled": False}}
    properties["lora_name"] = option(
        "加速 LoRA", "string", LIGHTX2V_FL2V_4STEP_LORA,
        enum=[LIGHTX2V_FL2V_4STEP_LORA, LIGHTX2V_FL2V_8STEP_LORA, LIGHTX2V_REF2V_4STEP_LORA],
    )
    properties["lora_strength"] = option("LoRA 强度", "number", LIGHTX2V_LORA_STRENGTH, minimum=-100, maximum=100, step=0.01)
    properties["sampler_name"] = option("采样器", "string", "euler", enum=["euler", "res_multistep"])
    properties["shift_video"] = option("视频 Shift", "number", 12, minimum=0.01, maximum=100, step=0.01)
    properties["shift_audio"] = option("音频 Shift", "number", 3, minimum=0.01, maximum=100, step=0.01)
    properties["use_sage_attention"] = option("SageAttention", "boolean", True)
    properties["refine_enabled"] = refine_enabled_option(
        "开启后平台固定以 0.4 MP + 快速 4 步 LightX2V 一采生成底片，再用 H3 3D latent 放大到目标画质精修（3 步 beta，denoise 0.2）。"
    )
    properties["refine_quality_mode"] = refine_quality_mode_option()
    properties["refine_quality"] = refine_quality_option()
    properties["refine_upscale_method"] = refine_upscale_method_option()
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
            ui_visible_when={"refine_enabled": False},
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
        "speed": {
            **h3_speed_option(),
            "ui_visible_when": {"refine_enabled": False},
        },
        "custom_steps": {
            **h3_custom_steps_option(),
            "ui_visible_when": {"speed": H3_SPEED_CUSTOM, "refine_enabled": False},
        },
        "weight_profile": {
            **h3_weight_profile_option(),
            "ui_visible_when": {"refine_enabled": False},
        },
        "refine_enabled": option(
            "二采精修", "boolean", False, group="primary",
            description="开启后先以 0.4 MP 精简权重生成一采，再用 H3 3D latent 放大到目标画质做第二步精修（3 步 beta，denoise 0.2）。二采在大画布上重新采样：5 秒 1.0 MP 约 3.5 分钟，2.0 MP 约 50 分钟（RTX 4080 16 GB 实测）。",
        ),
        "refine_quality_mode": refine_quality_mode_option(),
        "refine_quality": refine_quality_option(),
        "refine_upscale_method": refine_upscale_method_option(),
        "refine_preview": refine_preview_option(),
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
            ui_requires_references_when="Ref2VA",
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
            ui_visible_when={"refine_enabled": False},
            description="选择实际输出尺寸；尺寸会随画面比例变化，最高为 1344×768。",
        ),
        "refine_enabled": refine_enabled_option(
            "开启后平台固定以 Director 两段式 0.4 MP / 8 步一采生成底片；T8 专有采样器与音频模式不参与二采。二采用 H3 3D latent 放大到目标画质精修。"
        ),
        "refine_quality_mode": refine_quality_mode_option(),
        "refine_quality": refine_quality_option(),
        "refine_upscale_method": refine_upscale_method_option(),
        "refine_preview": refine_preview_option(),
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
        "speed": {**h3_speed_option(), "ui_visible_when": {"refine_enabled": False}},
        "custom_steps": {**h3_custom_steps_option(), "ui_visible_when": {"speed": H3_SPEED_CUSTOM, "refine_enabled": False}},
        "weight_profile": {**h3_weight_profile_option(), "ui_visible_when": {"refine_enabled": False}},
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
            "audio_steps": option("音频采样步数", "integer", 10, minimum=1, maximum=1000, step=1, ui_not_less_than="video_steps"),
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
DIRECTOR_ACCEL_OPTION_SCHEMA = director_accel_option_schema()


# Wan VACE 深度复刻：画布尺寸与帧数由源视频/深度视频决定，属 internal 托管；
# primary 只暴露深度控制强度与保留原片首帧两个创作语义选项。
VACE_DEPTH_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "vace_strength": option(
            "深度控制强度", "number", 1.0, group="primary",
            minimum=0.1, maximum=1.0, step=0.05,
            description="越高越严格复刻原片的运镜与构图；调低可让画面内容更自由。",
        ),
        "keep_first_frame": option(
            "保留原片首帧", "boolean", True, group="primary",
            description="将原片首帧作为参考图，帮助保持主体形象一致。",
        ),
        "steps": option(
            "采样步数", "integer", 30, group="advanced",
            minimum=4, maximum=60, step=1,
            description="步数越多细节越精致，耗时也越长。",
        ),
        "seed": option(
            "随机种子", "integer", 0, group="advanced",
            minimum=0, maximum=2147483647, step=1,
            description="固定种子可复现相同结果；0 表示每次随机。",
        ),
        "width": option("画布宽", "integer", 832, group="internal", minimum=16, maximum=16384, step=16),
        "height": option("画布高", "integer", 480, group="internal", minimum=16, maximum=16384, step=16),
        "length": option("生成帧数", "integer", 81, group="internal", minimum=5, maximum=16384, step=4),
        "cfg": option("CFG", "number", 5.0, group="internal", minimum=1.0, maximum=12.0, step=0.1),
        "shift": option("采样 Shift", "number", 16.0, group="internal", minimum=1.0, maximum=20.0, step=0.5),
        "sampler": option("采样器", "string", "uni_pc", group="internal", enum=["uni_pc"]),
        "scheduler": option("调度器", "string", "simple", group="internal", enum=["simple"]),
        "weight_dtype": option(
            "模型精度", "string", "default", group="internal", enum=["default", "fp16", "bf16"],
        ),
        "fps": option("输出帧率", "integer", 16, group="internal", minimum=8, maximum=24, step=1),
    },
}

# MiniMax H3 动作迁移:角色形象图 + 动作参考视频。骨架控制强度、画面比例与生成时长
# 是普通用户可理解且直接影响结果的选项;模型/采样/骨架内部参数由后端默认值托管。
MOTION_TRANSFER_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "control_strength": option(
            "动作跟随强度", "number", 1.0, group="primary",
            minimum=0.1, maximum=1.0, step=0.05, ui_inline_label=True,
            description="越高越严格复刻参考视频的动作与节奏；调低可让角色发挥更自由。",
        ),
        "aspect_ratio": option(
            "画面比例", "string", "16:9", group="primary", enum=["16:9", "9:16", "1:1"],
            description="横版 864×480 / 竖版 480×864 / 方形 640×640。",
        ),
        "duration": option(
            "生成时长", "string", "5s", group="primary", enum=["5s", "10s", "15s"],
            description="复刻动作参考视频前 5/10/15 秒的动作。",
        ),
        "render_quality": option(
            "生成质量", "string", "standard", group="advanced", enum=["preview", "standard", "fine"],
            ui_options=[
                {"value": "preview", "label": "快速预览"},
                {"value": "standard", "label": "标准成片"},
                {"value": "fine", "label": "精细成片"},
            ],
            steps_by_quality={"preview": 8, "standard": 20, "fine": 30},
            description="预览更快；标准兼顾细节与耗时；精细需要更长时间。",
        ),
        "steps": option(
            "采样步数", "integer", 20, group="internal",
            minimum=4, maximum=40, step=1,
        ),
        "seed": option(
            "随机种子", "integer", 0, group="advanced",
            minimum=0, maximum=2147483647, step=1, randomize_when_zero=True,
            description="固定种子可复现相同结果；0 表示每次随机。",
        ),
        "width": option("画布宽", "integer", 864, group="internal", minimum=32, maximum=2048, step=32),
        "height": option("画布高", "integer", 480, group="internal", minimum=32, maximum=2048, step=32),
        "length": option("生成帧数", "integer", 124, group="internal", minimum=29, maximum=362, step=1),
        "fps": option("输出帧率", "integer", 24, group="internal", minimum=16, maximum=24, step=1),
        "sampler": option("采样器", "string", "res_multistep", group="internal", enum=["res_multistep"]),
        "scheduler": option("调度器", "string", "simple", group="internal", enum=["simple"]),
        "weight_dtype": option(
            "模型精度", "string", "default", group="internal", enum=["default", "fp16", "bf16"],
        ),
    },
}

SCAIL2_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "duration": option("生成范围", "string", "5s", group="primary", enum=["5s", "full"],
                           ui_options=[{"value": "5s", "label": "5 秒试片"}, {"value": "full", "label": "完整原片"}],
                           min_source_seconds=1, max_source_seconds=30,
                           description="完整原片支持 1–30 秒，平台自动连续生成并保留原片比例与节奏。"),
        "subject_count": option("替换人数", "string", "1", group="primary", enum=["1", "2"],
                                ui_options=[{"value": "1", "label": "单人"}, {"value": "2", "label": "双人（试用）"}],
                                description="双人按编号配对；实测仍可能出现发型和服装细节失真，建议先生成试片。"),
        "preserve_audio": option("保留原片声音 / BGM", "boolean", True, group="primary",
                                 description="直接沿用参考片的音轨与节拍；关闭后输出无声视频。"),
        "seed": option("随机种子", "integer", 0, group="advanced", minimum=0, maximum=2147483647,
                       step=1, randomize_when_zero=True, description="0 表示随机；固定数值便于复现。"),
        "source_points": option("视频人物标记", "string", "", group="internal"),
        "reference_points": option("形象图人物标记", "string", "", group="internal"),
        "width": option("画布宽", "integer", 512, group="internal", minimum=256, maximum=1280, step=32),
        "height": option("画布高", "integer", 896, group="internal", minimum=256, maximum=1280, step=32),
        "length": option("生成帧数", "integer", 81, group="internal", minimum=16, maximum=481),
        "conditioning_length": option("动作条件帧数", "integer", 81, group="internal", minimum=17, maximum=481),
        "chunk_count": option("连续生成段数", "integer", 1, group="internal", minimum=1, maximum=7),
        "source_duration": option("原片时长", "number", 5.0, group="internal", minimum=0.1, maximum=86400),
        "fps": option("输出帧率", "integer", 16, group="internal", enum=[16]),
        "steps": option("采样步数", "integer", 6, group="internal", enum=[6]),
        "cfg": option("CFG", "number", 1.0, group="internal", enum=[1.0]),
        "shift": option("Shift", "number", 5.0, group="internal", enum=[5.0]),
        "sampler": option("采样器", "string", "euler", group="internal", enum=["euler"]),
        "scheduler": option("调度器", "string", "simple", group="internal", enum=["simple"]),
        **{f"model_{kind}": option(kind, "string", name, group="internal", enum=[name])
           for kind, (_, name) in SCAIL_MODELS.items()},
        "dpo_lora": option("DPO LoRA", "string", DPO_LORA, group="internal", enum=[DPO_LORA]),
        "dpo_strength": option("DPO 强度", "number", 1.0, group="internal", enum=[1.0]),
        "light_lora": option("加速 LoRA", "string", LIGHT_LORA, group="internal", enum=[LIGHT_LORA]),
        "light_strength": option("加速强度", "number", 0.8, group="internal", enum=[0.8]),
    },
}

MOTION_TRANSFER_WORKFLOW_IDS = {JobMode.MINIMAX_H3_MOTION_TRANSFER.value, JobMode.SCAIL2_REPLACEMENT.value}


def is_motion_transfer_workflow(mode: JobMode | str) -> bool:

    return mode_key(mode) in MOTION_TRANSFER_WORKFLOW_IDS


# MiniMax H3 视频局部重绘：遮罩图(白色=重绘区) + 原片。域外像素级保持由图内硬合成
# 完成；画布跟随原片宽高(分发层探测后 32 对齐)，模型/采样等内部参数由后端托管。
INPAINT_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "inpaint_strength": option(
            "重绘强度", "number", 1.0, group="primary",
            minimum=0.1, maximum=1.0, step=0.05,
            description="越高越服从提示词；调低可让重绘内容更贴近原片氛围。",
        ),
        "duration": option(
            "生成时长", "string", "5s", group="primary", enum=["5s", "10s", "15s"],
            description="重绘原片前 5/10/15 秒；音轨沿用原片。",
        ),
        "steps": option(
            "采样步数", "integer", 20, group="advanced",
            minimum=4, maximum=40, step=1,
            description="步数越多细节越精致，耗时也越长。",
        ),
        "seed": option(
            "随机种子", "integer", 0, group="advanced",
            minimum=0, maximum=2147483647, step=1,
            description="固定种子可复现相同结果；0 表示每次随机。",
        ),
        "width": option("画布宽", "integer", 864, group="internal", minimum=32, maximum=2048, step=32),
        "height": option("画布高", "integer", 480, group="internal", minimum=32, maximum=2048, step=32),
        "length": option("生成帧数", "integer", 124, group="internal", minimum=29, maximum=362, step=1),
        "fps": option("输出帧率", "integer", 24, group="internal", minimum=16, maximum=24, step=1),
        "sampler": option("采样器", "string", "res_multistep", group="internal", enum=["res_multistep"]),
        "scheduler": option("调度器", "string", "simple", group="internal", enum=["simple"]),
        "weight_dtype": option(
            "模型精度", "string", "default", group="internal", enum=["default", "fp16", "bf16"],
        ),
    },
}

INPAINT_WORKFLOW_IDS = {JobMode.MINIMAX_H3_INPAINT.value}


def is_inpaint_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in INPAINT_WORKFLOW_IDS


# MiniMax H3 深度捕捉(即梦同款):原片视频。深度结构跟随强度与生成时长是普通用户可
# 理解的选项;DA3 推理分辨率、模型/采样内部参数由后端托管。画布跟随原片宽高
# (分发层探测后 32 对齐)。
DEPTH_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "control_strength": option(
            "结构跟随强度", "number", 1.0, group="primary",
            minimum=0.1, maximum=1.0, step=0.05, ui_inline_label=True,
            description="越高越严格复刻原片的空间结构与运镜；调低可让画面内容更自由发挥。",
        ),
        "duration": option(
            "生成时长", "string", "5s", group="primary", enum=["5s", "10s", "15s"],
            description="提取原片前 5/10/15 秒的深度结构，按提示词重塑画面。",
        ),
        "steps": option(
            "采样步数", "integer", 20, group="advanced",
            minimum=4, maximum=40, step=1,
            description="步数越多细节越精致，耗时也越长。",
        ),
        "seed": option(
            "随机种子", "integer", 0, group="advanced",
            minimum=0, maximum=2147483647, step=1, randomize_when_zero=True,
            description="固定种子可复现相同结果；0 表示每次随机。",
        ),
        "width": option("画布宽", "integer", 864, group="internal", minimum=32, maximum=2048, step=32),
        "height": option("画布高", "integer", 480, group="internal", minimum=32, maximum=2048, step=32),
        "length": option("生成帧数", "integer", 124, group="internal", minimum=29, maximum=362, step=1),
        "fps": option("输出帧率", "integer", 24, group="internal", minimum=16, maximum=24, step=1),
        "da3_resolution": option(
            "深度推理分辨率", "integer", 504, group="internal",
            minimum=140, maximum=2520, step=14,
        ),
        "sampler": option("采样器", "string", "res_multistep", group="internal", enum=["res_multistep"]),
        "scheduler": option("调度器", "string", "simple", group="internal", enum=["simple"]),
        "weight_dtype": option(
            "模型精度", "string", "default", group="internal", enum=["default", "fp16", "bf16"],
        ),
    },
}

DEPTH_WORKFLOW_IDS = {JobMode.MINIMAX_H3_DEPTH.value}


def is_depth_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in DEPTH_WORKFLOW_IDS


VIDEO_EDIT_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "duration": option("生成时长", "string", "5s", group="primary", enum=["5s", "10s", "15s"],
                           ui_options=[{"value": "5s", "label": "5 秒试片"}, {"value": "10s", "label": "10 秒"}, {"value": "15s", "label": "15 秒"}],
                           description="编辑原片开头对应片段；实际时长按 H3 原生帧网格对齐。"),
        "preserve_audio": option("保留原片声音 / BGM", "boolean", True, group="primary",
                                 description="平台直接沿用原片音轨，关闭后输出无声视频。"),
        "seed": option("随机种子", "integer", 0, group="advanced", minimum=0, maximum=2147483647,
                       step=1, randomize_when_zero=True, description="0 表示随机；固定种子便于比较。"),
        "steps": option("采样步数", "integer", 20, group="internal", minimum=20, maximum=25),
        "width": option("画布宽", "integer", 512, group="internal", minimum=32, maximum=2048, step=32),
        "height": option("画布高", "integer", 896, group="internal", minimum=32, maximum=2048, step=32),
        "length": option("生成帧数", "integer", 124, group="internal", minimum=29, maximum=362),
        "fps": option("输出帧率", "integer", 24, group="internal", enum=[24]),
        "sampler": option("采样器", "string", "res_multistep", group="internal", enum=["res_multistep"]),
        "scheduler": option("调度器", "string", "simple", group="internal", enum=["simple"]),
        "reference_image_size": option("参考尺寸策略", "string", "match", group="internal", enum=["match"]),
        **{f"model_{kind}": option(kind, "string", name, group="internal", enum=[name])
           for kind, name in VIDEO_EDIT_MODELS.items()},
    },
}


def is_video_edit_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) == JobMode.MINIMAX_H3_VIDEO_EDIT.value


# MiniMax H3 关键帧叙事：2-4 张关键帧图按叙事顺序上传，第一张锁定开场首帧，
# 其余按锚点时间链式锚定进画面，模型生成贯穿全部关键帧的叙事过渡。锚点时间
# 是普通用户能理解的核心创作选项（工具页提供逐帧时间选择器）；画布/模型/采样
# 等内部参数由后端托管。
KEYFRAME_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "aspect_ratio": option(
            "画面比例", "string", "16:9", group="primary", enum=["16:9", "9:16", "1:1"],
            ui_options=[
                {"value": "16:9", "label": "16:9 横屏"},
                {"value": "9:16", "label": "9:16 竖屏"},
                {"value": "1:1", "label": "1:1 方形"},
            ],
            description="横版 864×480 / 竖版 480×864 / 方形 640×640。",
        ),
        "duration": option(
            "生成时长", "string", "5s", group="primary", enum=["5s", "10s", "15s"],
            description="关键帧之间的过渡由模型生成，音画一体。",
        ),
        "anchor_seconds": option(
            "锚点时间", "string", "", group="primary",
            description=(
                "第 2~N 张关键帧的画面出现时间(秒，逗号分隔，如 2.5,8)；"
                "负数从末尾计数(-1 为末帧)；留空则按顺序均匀分布。"
            ),
        ),
        "steps": option(
            "采样步数", "integer", 20, group="advanced",
            minimum=4, maximum=40, step=1,
            description="步数越多细节越精致，耗时也越长。",
        ),
        "seed": option(
            "随机种子", "integer", 0, group="advanced",
            minimum=0, maximum=2147483647, step=1, randomize_when_zero=True,
            description="固定种子可复现相同结果；0 表示每次随机。",
        ),
        "width": option("画布宽", "integer", 864, group="internal", minimum=32, maximum=2048, step=32),
        "height": option("画布高", "integer", 480, group="internal", minimum=32, maximum=2048, step=32),
        "length": option("生成帧数", "integer", 124, group="internal", minimum=29, maximum=362, step=1),
        "fps": option("输出帧率", "integer", 24, group="internal", minimum=16, maximum=24, step=1),
        "sampler": option("采样器", "string", "res_multistep", group="internal", enum=["res_multistep"]),
        "scheduler": option("调度器", "string", "simple", group="internal", enum=["simple"]),
        "weight_dtype": option(
            "模型精度", "string", "default", group="internal", enum=["default", "fp16", "bf16"],
        ),
        "use_sage_attention": option("启用 SageAttention", "boolean", True, group="internal"),
    },
}

KEYFRAME_WORKFLOW_IDS = {JobMode.MINIMAX_H3_KEYFRAME.value}


def is_keyframe_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in KEYFRAME_WORKFLOW_IDS



# MiniMax H3 数字人口播：形象图 + 口播音频 → 口型锁定的说话视频。
# 生成时长由音频长度决定，不暴露时长选项；画布/模型/采样等内部参数由后端托管。
# v1 单渲染窗口上限约 5 秒（H3 24fps、17n+5 网格的 124 帧训练窗口），长音频分窗渲染后续迭代。
AVATAR_MAX_SCENE_SECONDS = 5.0
AVATAR_MAX_SCENE_FRAMES = 124

AVATAR_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "aspect_ratio": option(
            "画面比例", "string", "16:9 (Widescreen)", group="primary", enum=T8_ASPECT_RATIOS,
            ui_control="visual-settings",
            description="数字人画面的宽高比例；竖屏口播选 9:16。",
        ),
        "speed": {**h3_speed_option()},
        "scene_duration_seconds": option(
            "口播窗口时长", "number", AVATAR_MAX_SCENE_SECONDS, group="internal",
            minimum=1.0, maximum=AVATAR_MAX_SCENE_SECONDS, step=0.01, unit="秒",
            description="提交任务时按口播音频实际时长写入；上限为单渲染窗口 5 秒。",
        ),
        "quality": option(
            "分辨率", "string", "0.4", group="internal", ui_control="select",
            enum=list(H3_T8_RESOLUTION_PRESETS),
            ui_options=local_resolution_options(H3_T8_RESOLUTION_PRESETS),
            megapixels_by_quality=H3_T8_RESOLUTION_PRESETS,
            description="T8 条件节点画布上限 1344×768（0.98 MP），数字人默认 0.4 MP。",
        ),
        "megapixels": option(
            "内部像素面积", "number", 0.4, group="internal", minimum=0.1, maximum=16.0, step=0.1, unit="MP",
        ),
        "multiple": option("尺寸对齐倍数", "integer", 32, minimum=8, maximum=128, step=4),
        "steps": option("双时钟采样步数", "integer", 4, minimum=1, maximum=1000, step=1),
        "seed": option(
            "随机种子", "integer", 123456789,
            minimum=0, maximum=1125899906842624, step=1,
            description="使用相同种子和参数可获得更接近的结果。",
        ),
        "audio_mode": option(
            "音频模式", "string", "lock_source",
            enum=["lock_source", "remix_source", "reference_only", "native"],
            description="lock_source：口型锁定源音频并保留原声；remix_source：重绘源音频；native：模型自生成音频。",
        ),
        "audio_denoise_strength": option("音频重绘强度", "number", 0.35, minimum=0, maximum=1, step=0.01),
        # 当前远端 ComfyUI 0.43 构建禁用了 T8 Hybrid 路径（ref/keyframe latent 组装变更未复验），
        # add_source_as_reference=True 会把源音频挂为参考媒体并强制 Hybrid，因此固定关闭。
        "add_source_as_reference": option("将源音频作为参考", "boolean", False),
        "prompt_primary_audio_ordinal": option("提示词主音频序号", "integer", 0, minimum=0, maximum=9, step=1),
        "strict_prompt_tags": option("严格校验媒体标签", "boolean", True),
        "ref_image_size": option("参考图尺寸策略", "string", "match", enum=["match", "max"]),
        "reference_video_policy": option(
            "参考视频时长策略", "string", "official_2_to_15s",
            enum=["official_2_to_15s", "model_minimum"],
        ),
        "weight_profile": h3_weight_profile_option(),
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
    },
}

AVATAR_WORKFLOW_IDS = {JobMode.MINIMAX_H3_AVATAR.value}


def is_avatar_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in AVATAR_WORKFLOW_IDS


# MiniMax H3 口型同步：已有视频 + 目标音频 → 按新音频重演口型。
# 仅作为 AI 工具入口（hidden_from_catalog），生成页下拉不出现（参考素材含视频）。
# 画布随源视频、窗口时长随目标音频，均由提交侧探测后写入 internal 选项。
LIPSYNC_SOURCE_MIN_SECONDS = 2.0
LIPSYNC_SOURCE_MAX_SECONDS = 15.0

LIPSYNC_SPEED_PRESETS = {
    "fast": {"steps": 4, "use_turbo": True},
    "fine": {"steps": 20, "use_turbo": False},
}
LIPSYNC_TURBO_MAX_STEPS = 8

LIP_SYNC_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "speed": option(
            "生成速度", "string", "fast", group="primary",
            enum=["fast", "fine", "custom"],
            ui_control="select",
            ui_options=[
                {"value": "fast", "label": "快速（4 步加速）"},
                {"value": "fine", "label": "精细（20 步完整采样）"},
                {"value": "custom", "label": "自定义"},
            ],
            description="快速为 4 步加速，适合预览；精细关闭加速、完整采样，细节与口型更稳；自定义可填 1-40 步。",
        ),
        "custom_steps": option(
            "自定义步数", "integer", 4, group="primary",
            minimum=1, maximum=40, step=1, unit="步",
            ui_control="input-number",
            ui_visible_when={"speed": "custom"},
            description="不超过 8 步时启用加速 LoRA，更多步数走完整采样。",
        ),
        "seed": option(
            "随机种子", "integer", 123456789, group="advanced",
            minimum=0, maximum=1125899906842624, step=1,
            description="使用相同种子和参数可获得更接近的结果。",
        ),
        "scene_duration_seconds": option(
            "口播窗口时长", "number", AVATAR_MAX_SCENE_SECONDS, group="internal",
            minimum=1.0, maximum=AVATAR_MAX_SCENE_SECONDS, step=0.01, unit="秒",
            description="提交任务时按目标音频实际时长写入；上限为单渲染窗口 5 秒。",
        ),
        "width": option("画布宽", "integer", 864, group="internal", minimum=256, maximum=1344, step=32),
        "height": option("画布高", "integer", 480, group="internal", minimum=256, maximum=1344, step=32),
        "steps": option("采样步数", "integer", 4, minimum=1, maximum=1000, step=1),
        "use_turbo": option("加速 LoRA", "boolean", True),
        "audio_mode": option(
            "音频模式", "string", "lock_source",
            enum=["lock_source", "remix_source", "reference_only", "native"],
        ),
        "audio_denoise_strength": option("音频重绘强度", "number", 0.35, minimum=0, maximum=1, step=0.01),
        "strict_prompt_tags": option("严格校验媒体标签", "boolean", True),
        "ref_image_size": option("参考尺寸策略", "string", "match", enum=["match", "max"]),
        "reference_video_policy": option(
            "参考视频时长策略", "string", "official_2_to_15s",
            enum=["official_2_to_15s", "model_minimum"],
        ),
        "frame_rate": option("输出帧率", "number", 24, minimum=1, maximum=120, step=1, unit="fps"),
        "unet_name": option(
            "扩散模型", "string", H3_REF2VA_FULL,
            enum=[H3_REF2VA_FULL, H3_REF2VA_PRUNED],
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
            "加速 LoRA", "string", LIGHTX2V_REF2V_4STEP_LORA,
            enum=[LIGHTX2V_REF2V_4STEP_LORA],
        ),
        "lora_strength": option("LoRA 强度", "number", LIGHTX2V_LORA_STRENGTH, minimum=-100, maximum=100, step=0.01),
        "use_sage_attention": option("启用 SageAttention", "boolean", True),
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
    },
}

LIP_SYNC_WORKFLOW_IDS = {JobMode.MINIMAX_H3_LIP_SYNC.value}


def is_lip_sync_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in LIP_SYNC_WORKFLOW_IDS


def is_lip_sync_workflow_by_definition(definition: WorkflowDefinition) -> bool:
    return definition.id in LIP_SYNC_WORKFLOW_IDS


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
        JobMode.MINIMAX_H3_DIRECTOR_ACCEL_T2V.value,
        "H3 Director 加速版 文生视频",
        "MiniMaxH3Director + 双 Sage 加速的文生视频；无 Turbo LoRA，默认 0.4 MP、20 步、pruned INT8。",
        "none",
        0,
        0,
        supports_h3_options=True,
        option_schema=DIRECTOR_ACCEL_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_DIRECTOR_ACCEL,
        supports_timeline=True,
        supports_multi_segment=True,
        max_segments=6,
        max_total_frames=1152,
        supports_segment_continuity=True,
        supports_audio_batch=True,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_DIRECTOR_ACCEL_I2V.value,
        "H3 Director 加速版 首尾帧视频",
        "MiniMaxH3Director 图生视频；首帧必填，尾帧可选。无 Turbo LoRA，默认 0.4 MP、20 步。",
        "keyframes",
        1,
        2,
        ("首帧", "尾帧（可选）"),
        supports_h3_options=True,
        option_schema=DIRECTOR_ACCEL_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_DIRECTOR_ACCEL,
        supports_timeline=True,
        supports_multi_segment=True,
        max_segments=6,
        max_total_frames=1152,
        supports_segment_continuity=True,
        supports_audio_batch=True,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V.value,
        "H3 Director 加速版 多参考视频",
        "MiniMaxH3Director 多参考视频；按顺序添加参考并在提示词中引用 <Picture n>。无 Turbo LoRA。",
        "collection",
        1,
        9,
        supports_h3_options=True,
        option_schema=DIRECTOR_ACCEL_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_DIRECTOR_ACCEL,
        supports_timeline=True,
        supports_multi_segment=True,
        max_segments=6,
        max_total_frames=1152,
        supports_segment_continuity=True,
        supports_audio_batch=True,
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
    WorkflowDefinition(
        JobMode.WAN_VACE_DEPTH_V2V.value,
        "Wan VACE 深度复刻",
        "以深度视频锁定原片运镜与构图，用提示词与参考图重塑画面内容；由复刻台按镜头提交，"
        "references[0] 为深度视频文件，其后为可选参考图。",
        "collection",
        1,
        9,
        option_schema=VACE_DEPTH_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_CUSTOM,
        hidden_from_catalog=True,
    ),
    WorkflowDefinition(
        JobMode.SCAIL2_REPLACEMENT.value,
        "SCAIL-2 人物动作替换",
        "SAM3 跟踪指定人物，迁移原片动作与表情，保留其他人物、场景和原片声音。"
        "请在 AI 工具 → 动作迁移中选定形象图与视频首帧中的目标人物。",
        "collection", 2, 2, ("角色形象图", "动作参考视频"),
        accepts_video_reference=True, default_prompt=SCAIL_DEFAULT_PROMPT,
        option_schema=SCAIL2_OPTION_SCHEMA, catalog_group=CATALOG_GROUP_CUSTOM,
        # Point selection is provided by the dedicated tool, not the generic composer.
        hidden_from_catalog=True,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_MOTION_TRANSFER.value,
        "H3 动作迁移",
        "把动作参考视频里的舞蹈/肢体动作迁移到角色形象图上：SDPose 全身骨架锁定动作，"
        "角色参考图锁定身份，H3 原生音画一体出片，纯本地免费。"
        "references[0] 为角色形象图，references[1] 为动作参考视频。",
        "collection",
        2,
        2,
        ("角色形象图", "动作参考视频"),
        accepts_video_reference=True,
        default_prompt=MOTION_TRANSFER_DEFAULT_PROMPT,
        option_schema=MOTION_TRANSFER_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_OFFICIAL_H3,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_INPAINT.value,
        "H3 局部重绘",
        "上传重绘遮罩图(白色=重绘区)和原片视频，只重生成遮罩内的内容，域外像素级保持"
        "原片，音轨沿用原声。references[0] 为重绘遮罩图，references[1] 为原片视频。",
        "collection",
        2,
        2,
        ("重绘遮罩图(白色=重绘区)", "原片视频"),
        accepts_video_reference=True,
        option_schema=INPAINT_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_OFFICIAL_H3,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_DEPTH.value,
        "H3 深度捕捉",
        "上传原片视频，自动提取时序深度图锁定运镜与空间结构(即梦深度捕捉同款能力)，"
        "用提示词重塑画面内容与风格，H3 原生音画一体出片，同时回显深度预览视频。"
        "references[0] 为原片视频。",
        "collection",
        1,
        1,
        ("原片视频",),
        reference_slots=("video",),
        accepts_video_reference=True,
        default_prompt=DEPTH_DEFAULT_PROMPT,
        option_schema=DEPTH_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_OFFICIAL_H3,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_VIDEO_EDIT.value,
        "H3 视频编辑（试用）",
        "上传已有视频，用提示词修改场景、服装或画面内容。直接以完整视频为编辑参考，"
        "可沿用原片 BGM；人物细节和动作可能发生变化，建议先用 5 秒试片。",
        "collection", 1, 1, ("原片视频",),
        reference_slots=("video",), accepts_video_reference=True,
        option_schema=VIDEO_EDIT_OPTION_SCHEMA, catalog_group=CATALOG_GROUP_OFFICIAL_H3,
        hidden_from_catalog=True,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_KEYFRAME.value,
        "H3 关键帧叙事",
        "上传 2-4 张按叙事顺序排列的关键帧图片，第一张锁定开场画面，其余按锚点时间"
        "依次锚定进画面，模型生成贯穿全部关键帧的叙事过渡，H3 原生音画一体出片，"
        "纯本地免费。锚点时间留空时按顺序均匀分布。"
        "references[0..N] 为按顺序排列的关键帧图片。",
        "collection",
        2,
        4,
        ("开场关键帧", "关键帧 2", "关键帧 3", "关键帧 4"),
        option_schema=KEYFRAME_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_OFFICIAL_H3,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_AVATAR.value,
        "H3 数字人口播",
        "上传人物形象图与口播音频，生成口型与语音精确同步的说话视频：H3 原生音画一体驱动，"
        "纯本地免费。当前单次生成支持约 5 秒以内的口播音频。"
        "references[0] 为人物形象图，references[1] 为口播音频。",
        "collection",
        2,
        2,
        ("人物形象图", "口播音频"),
        accepts_audio_reference=True,
        option_schema=AVATAR_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_OFFICIAL_H3,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_LIP_SYNC.value,
        "H3 口型同步",
        "上传已有视频与目标音频，H3 以源视频锁定身份与场景，按新音频重演口型："
        "纯本地免费。源视频 2-15 秒，目标音频约 5 秒以内，输出画布与时长随素材自动对齐。"
        "references[0] 为原视频，references[1] 为目标音频。",
        "collection",
        2,
        2,
        ("原视频", "目标音频"),
        reference_slots=("video", "audio"),
        hidden_from_catalog=True,
        option_schema=LIP_SYNC_OPTION_SCHEMA,
        catalog_group=CATALOG_GROUP_OFFICIAL_H3,
    ),
    WorkflowDefinition(
        JobMode.NVIDIA_RTX_VSR.value,
        "RTX 2x 超分",
        "把已成功的成片交给当前连接 ComfyUI 的 RTXVideoSuperResolution（固定 2x / ULTRA）。该实例必须已安装 Nvidia_RTX_Nodes_ComfyUI。不出现在创作页模型列表，只给出片后续和超分按钮使用。",
        "collection",
        1,
        1,
        ("原片",),
        option_schema={
            "type": "object",
            "properties": {
                "width": option("原片宽", "integer", 864, group="internal", minimum=8, maximum=8192, step=1),
                "height": option("原片高", "integer", 480, group="internal", minimum=8, maximum=8192, step=1),
                "frames": option("原片帧数", "integer", 120, group="internal", minimum=1, maximum=16384, step=1),
            },
        },
        catalog_group=CATALOG_GROUP_CUSTOM,
        hidden_from_catalog=True,
    ),
    WorkflowDefinition(
        JobMode.SEEDVR2_UPSCALE.value,
        "SeedVR2 高清增强",
        "用当前连接 ComfyUI 的原生 SeedVR2 3B Int8 节点做生成式 2x 重建，比 RTX 超分慢很多，但能补回细节。该实例必须已安装 SeedVR2 节点与模型。不出现在创作页模型列表，只给出片后续和超分按钮使用。",
        "collection",
        1,
        1,
        ("原片",),
        option_schema={
            "type": "object",
            "properties": {
                "width": option("原片宽", "integer", 864, group="internal", minimum=8, maximum=8192, step=1),
                "height": option("原片高", "integer", 480, group="internal", minimum=8, maximum=8192, step=1),
                "frames": option("原片帧数", "integer", 120, group="internal", minimum=1, maximum=16384, step=1),
            },
        },
        catalog_group=CATALOG_GROUP_CUSTOM,
        hidden_from_catalog=True,
    ),
    WorkflowDefinition(
        JobMode.STEM_SPLIT.value,
        "人声/伴奏分离",
        "上传一段音频或视频，用当前连接 ComfyUI 的 MelBand RoFormer 模型分离出人声与伴奏两条音轨："
        "纯本地免费。适合清唱提取、伴奏制作与语音增强。该实例必须已安装 Mel-Band RoFormer 节点与权重。"
        "references[0] 为待分离的音频或视频。",
        "collection",
        1,
        1,
        ("待分离音频或视频",),
        reference_slots=("media",),
        option_schema={
            "type": "object",
            "properties": {
                "model_name": option("分离模型", "string", "MelBandRoformer_fp16.safetensors", group="internal"),
            },
        },
        catalog_group=CATALOG_GROUP_CUSTOM,
        hidden_from_catalog=True,
        default_prompt="分离人声与伴奏",
    ),
    WorkflowDefinition(
        JobMode.IMAGE_BACKGROUND_REMOVE.value,
        "图片去背景",
        "上传一张图片，自动识别并保留主体、移除背景，输出透明背景 PNG。使用当前连接 ComfyUI 实例的 "
        "SAM3.1 分割模型，纯本地免费。提示词填写要保留的主体描述（英文效果更稳，如 person / product）。",
        "collection",
        1,
        1,
        ("原图",),
        option_schema={
            "type": "object",
            "properties": {
                "threshold": option("分割阈值", "number", DEFAULT_SAM3_THRESHOLD, group="internal", minimum=0.05, maximum=0.95, step=0.05),
                "refine_iterations": option("边缘精修次数", "integer", DEFAULT_SAM3_REFINE_ITERATIONS, group="internal", minimum=0, maximum=5, step=1),
                "model_name": option("分割模型", "string", DEFAULT_SAM3_MODEL, group="internal"),
            },
        },
        media_type="image",
        catalog_group=CATALOG_GROUP_IMAGE_EDIT,
        default_prompt=DEFAULT_SUBJECT_PROMPT,
    ),
    WorkflowDefinition(
        JobMode.IMAGE_LAYER_SPLIT.value,
        "图片图层分离",
        "上传一张图片，自动把主体与背景拆成两个透明图层（前景层 / 背景层），可分别插入画布继续编辑"
        "或再创作。提示词填写要分离的主体描述（英文效果更稳，如 person / product）。",
        "collection",
        1,
        1,
        ("原图",),
        option_schema={
            "type": "object",
            "properties": {
                "threshold": option("分割阈值", "number", DEFAULT_SAM3_THRESHOLD, group="internal", minimum=0.05, maximum=0.95, step=0.05),
                "refine_iterations": option("边缘精修次数", "integer", DEFAULT_SAM3_REFINE_ITERATIONS, group="internal", minimum=0, maximum=5, step=1),
                "model_name": option("分割模型", "string", DEFAULT_SAM3_MODEL, group="internal"),
            },
        },
        media_type="image",
        catalog_group=CATALOG_GROUP_IMAGE_EDIT,
        default_prompt=DEFAULT_SUBJECT_PROMPT,
    ),
    WorkflowDefinition(
        JobMode.IMAGE_INPAINT.value,
        "图片局部重绘",
        "上传原图并框选要修改的区域，用一句话描述把选区变成什么；选区外的像素与原图完全一致。"
        "references[0] 为原图，references[1] 为遮罩图（白色=重绘区）。",
        "collection",
        2,
        2,
        ("原图", "遮罩图(白色=编辑区)"),
        option_schema={
            "type": "object",
            "properties": {
                "feather": option("边缘羽化", "integer", 12, group="internal", minimum=0, maximum=64, step=1),
                "provider_model": option("远端模型", "string", DEFAULT_COMPOSITE_PROVIDER_MODEL, group="internal"),
            },
        },
        media_type="image",
        executor="grs",
        catalog_group=CATALOG_GROUP_IMAGE_EDIT,
    ),
    WorkflowDefinition(
        JobMode.IMAGE_ERASER.value,
        "消除笔",
        "涂抹画面中要移除的内容，模型用周围环境自然填补，选区外的像素与原图完全一致。"
        "references[0] 为原图，references[1] 为遮罩图（白色=消除区）。",
        "collection",
        2,
        2,
        ("原图", "遮罩图(白色=消除区)"),
        option_schema={
            "type": "object",
            "properties": {
                "feather": option("边缘羽化", "integer", 12, group="internal", minimum=0, maximum=64, step=1),
                "provider_model": option("远端模型", "string", DEFAULT_COMPOSITE_PROVIDER_MODEL, group="internal"),
            },
        },
        media_type="image",
        executor="grs",
        catalog_group=CATALOG_GROUP_IMAGE_EDIT,
        default_prompt="移除标记区域的内容并自然填补",
    ),
    WorkflowDefinition(
        JobMode.IMAGE_OUTPAINT.value,
        "图片扩图",
        "上传原图并选择目标画幅，模型向四周自然延伸补全画面，原区域像素与原图完全一致。"
        "references[0] 为原图。",
        "collection",
        1,
        1,
        ("原图",),
        option_schema={
            "type": "object",
            "properties": {
                "target_aspect": option(
                    "扩展到", "string", "16:9", group="primary",
                    enum=list(OUTPAINT_TARGET_ASPECTS), ui_control="select",
                ),
                "feather": option("边缘羽化", "integer", 12, group="internal", minimum=0, maximum=64, step=1),
                "provider_model": option("远端模型", "string", DEFAULT_COMPOSITE_PROVIDER_MODEL, group="internal"),
            },
        },
        media_type="image",
        executor="grs",
        catalog_group=CATALOG_GROUP_IMAGE_EDIT,
        default_prompt="扩展画面范围并保持原内容不变",
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
DIRECTOR_ACCEL_WORKFLOWS = {
    JobMode.MINIMAX_H3_DIRECTOR_ACCEL_T2V,
    JobMode.MINIMAX_H3_DIRECTOR_ACCEL_I2V,
    JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V,
}
H3_WORKFLOWS = {
    JobMode.MINIMAX_H3_T2V,
    JobMode.MINIMAX_H3_I2V,
    JobMode.MINIMAX_H3_R2V,
    *LIGHTX2V_WORKFLOWS,
    *DUAL_ACCEL_WORKFLOWS,
    *DIRECTOR_ACCEL_WORKFLOWS,
    *T8_WORKFLOWS,
    JobMode.MINIMAX_H3_AVATAR,
    JobMode.MINIMAX_H3_LIP_SYNC,
}
# Two-pass refine rebuilds the first pass on the Director graph, which has no drive-audio
# input, and refines a video latent while avatar samples an AV latent. Avatar would lose its
# lip-sync source, so it stays out of the contract until an audio-aware second pass exists.
# 口型同步同理：参考视频重建 + AV 联合采样，二采无音频感知契约。
H3_REFINE_WORKFLOWS = H3_WORKFLOWS - {JobMode.MINIMAX_H3_AVATAR, JobMode.MINIMAX_H3_LIP_SYNC}
T8_WORKFLOW_IDS = {item.value for item in T8_WORKFLOWS}
LIGHTX2V_WORKFLOW_IDS = {item.value for item in LIGHTX2V_WORKFLOWS}
DUAL_ACCEL_WORKFLOW_IDS = {item.value for item in DUAL_ACCEL_WORKFLOWS}
DIRECTOR_ACCEL_WORKFLOW_IDS = {item.value for item in DIRECTOR_ACCEL_WORKFLOWS}
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
        if definition.min_references <= 1 and definition.max_references >= 3:
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
RTX_VSR_WORKFLOW_IDS = {JobMode.NVIDIA_RTX_VSR.value}
SEEDVR2_UPSCALE_WORKFLOW_IDS = {JobMode.SEEDVR2_UPSCALE.value}
UPSCALE_WORKFLOW_IDS = RTX_VSR_WORKFLOW_IDS | SEEDVR2_UPSCALE_WORKFLOW_IDS
STEM_SPLIT_WORKFLOW_IDS = {JobMode.STEM_SPLIT.value}
_catalog_lookup: Callable[[str], dict[str, Any] | None] | None = None


def set_catalog_lookup(lookup: Callable[[str], dict[str, Any] | None] | None) -> None:
    global _catalog_lookup
    _catalog_lookup = lookup


def is_h3_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in H3_WORKFLOW_IDS


def is_rtx_vsr_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in RTX_VSR_WORKFLOW_IDS


def is_seedvr2_upscale_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in SEEDVR2_UPSCALE_WORKFLOW_IDS


def is_upscale_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in UPSCALE_WORKFLOW_IDS


COMFY_IMAGE_WORKFLOW_IDS = {
    JobMode.IMAGE_BACKGROUND_REMOVE.value,
    JobMode.IMAGE_LAYER_SPLIT.value,
}

# GRS 生成 + 本地合成的复合图片工作流（executor=grs，但不是 GRS 目录模型）。
COMPOSITE_IMAGE_WORKFLOW_IDS = {
    JobMode.IMAGE_INPAINT.value,
    JobMode.IMAGE_ERASER.value,
    JobMode.IMAGE_OUTPAINT.value,
}


def is_comfy_image_workflow(mode: JobMode | str) -> bool:
    """跑在当前连接 ComfyUI 实例上的图片编辑工作流（media_type=image，executor=comfyui）。"""
    return mode_key(mode) in COMFY_IMAGE_WORKFLOW_IDS


def is_composite_image_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in COMPOSITE_IMAGE_WORKFLOW_IDS


def is_grs_image_workflow(mode: JobMode | str) -> bool:
    """GRS 目录驱动的图片工作流（grs- 前缀）。

    ComfyUI 图片工作流与 GRS+本地合成的复合图片工作流都不在此列：
    前者可用性跟随 ComfyUI，后者的 provider_model 不走目录开关。
    """
    return not is_comfy_image_workflow(mode) and mode_key(mode).startswith("grs-")


def is_stem_split_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in STEM_SPLIT_WORKFLOW_IDS


def is_local_comfy_job(mode: JobMode | str) -> bool:
    """Creation-page ComfyUI jobs that occupy the serial video worker."""
    return (
        is_h3_workflow(mode)
        or is_upscale_workflow(mode)
        or is_motion_transfer_workflow(mode)
        or is_inpaint_workflow(mode)
        or is_depth_workflow(mode)
        or is_video_edit_workflow(mode)
        or is_keyframe_workflow(mode)
        or is_stem_split_workflow(mode)
        or is_comfy_image_workflow(mode)
    )


def is_t8_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in T8_WORKFLOW_IDS


def is_lightx2v_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in LIGHTX2V_WORKFLOW_IDS


def is_dual_accel_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in DUAL_ACCEL_WORKFLOW_IDS


def is_director_accel_workflow(mode: JobMode | str) -> bool:
    return mode_key(mode) in DIRECTOR_ACCEL_WORKFLOW_IDS


def generation_family_label(mode: JobMode | str) -> str:
    if is_lightx2v_workflow(mode):
        return "LightX2V"
    if is_dual_accel_workflow(mode):
        return "八步双加速"
    if is_director_accel_workflow(mode):
        return "H3 Director 加速版"
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
H3_OPTION_NAMES = {
    "aspect_ratio", "quality", "megapixels", "duration", "speed", "custom_steps",
    "weight_profile", "use_sage_attention", "refine_enabled", "refine_quality", "refine_quality_mode",
    "refine_preview", "refine_upscale_method",
}
H3_REFINE_OPTION_NAMES = {
    "refine_enabled", "refine_quality", "refine_quality_mode", "refine_preview", "refine_upscale_method",
}
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
    audio_reference = definition.accepts_audio_reference
    video_reference = definition.accepts_video_reference
    parameters: list[dict[str, Any]] = [
        {
            "name": "mode", "label": "工作流", "type": "string", "required": True,
            "description": "固定为当前工作流 ID。", "default": definition.id,
            "values": [definition.id],
        },
        {
            "name": "prompt", "label": "创作提示词", "type": "string", "required": not bool(definition.default_prompt),
            "description": "留空使用工作流默认提示词。" if definition.default_prompt else "去除首尾空白后不能为空。",
            **({"default": definition.default_prompt} if definition.default_prompt else {}),
        },
        {
            "name": "references", "label": "参考素材", "type": "array",
            "required": definition.min_references > 0,
            "description": (
                "文件数组：第 1 项为人物形象图，第 2 项为口播音频（WAV/MP3，时长不超过"
                f" {AVATAR_MAX_SCENE_SECONDS:.0f} 秒）。"
                if audio_reference else
                "文件数组：第 1 项为原视频（MP4/MOV/WebM，2-15 秒），第 2 项为目标音频（WAV/MP3，约 5 秒以内）。"
                "输出画布与时长随素材自动对齐。"
                if is_lip_sync_workflow_by_definition(definition) else
                "文件数组：1 段原片视频（MP4/MOV/WebM，最大 50 MB），平台截取开头并对齐帧率。"
                if definition.reference_slots == ("video",) else
                "文件数组：第 1 项为角色形象图，第 2 项为动作参考视频（MP4/MOV/WebM）。"
                "单份素材最大 50 MB，视频需至少覆盖所选时长；只取开头片段，帧率由工作流托管。"
                if video_reference else
                "图片文件数组。多图工作流按上传顺序解释参考图。单张文件最大 50 MB。"
            ),
            "min_items": definition.min_references, "max_items": definition.max_references,
            "content_type": (
                "image/*,audio/*" if audio_reference else
                "video/*,audio/*" if is_lip_sync_workflow_by_definition(definition) else
                "video/*" if definition.reference_slots == ("video",) else
                "image/*,video/*" if video_reference else
                "image/*"
            ),
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
        if definition.reference_slots:
            parts = "、".join(f"1 份{label}" for label in definition.reference_labels)
            raise ValueError(f"{definition.name} 需要 {parts}，当前共 {count} 项素材。")
        if definition.accepts_audio_reference:
            raise ValueError(f"{definition.name} 需要 1 张人物形象图和 1 份口播音频，当前共 {count} 项素材。")
        if definition.accepts_video_reference:
            raise ValueError(f"{definition.name} 需要 1 张角色形象图和 1 段动作参考视频，当前共 {count} 项素材。")
        if definition.min_references == definition.max_references:
            raise ValueError(f"{definition.name} 需要 {definition.min_references} 张参考图。")
        raise ValueError(
            f"{definition.name} 支持 {definition.min_references}-{definition.max_references} 张参考图，当前为 {count} 张。"
        )


def _refine_settings(raw: dict[str, Any]) -> tuple[bool, str, bool, str]:
    enabled = coerce_bool_option(raw.get("refine_enabled", False), label="二采精修")
    quality = str(raw.get("refine_quality", "1.0")).strip()
    if quality not in {"1.0", "2.0"}:
        raise ValueError("二采目标清晰度请选择 1.0 或 2.0 MP。")
    quality_mode = str(raw.get("refine_quality_mode", "auto")).strip()
    if quality_mode not in {"auto", "force"}:
        raise ValueError("清晰度策略请选择自动或强制高清。")
    # Preview is platform-managed: every two-pass job pauses after the first pass.
    return enabled, quality, enabled, quality_mode


def _refine_first_pass_defaults(mode: JobMode | str) -> dict[str, Any]:
    """The first pass is an implementation detail: the platform owns its technical settings."""
    key = mode_key(mode)
    # 内存不足以装完整权重时，一采同样换精简权重：加速 LoRA 挂不上，
    # 档位切到高质量（20 步完整采样），避免“8 步无加速”的欠采样底片。
    stats = hardware_profile()
    pruned_first_pass = bool(stats) and auto_weight_profile(stats) == H3_WEIGHT_PRUNED
    if key in LIGHTX2V_WORKFLOW_IDS:
        is_reference = key == JobMode.MINIMAX_H3_LIGHTX2V_R2V.value
        lora_name = LIGHTX2V_REF2V_4STEP_LORA if is_reference else LIGHTX2V_FL2V_4STEP_LORA
        if pruned_first_pass:
            return {
                "weight_profile": H3_WEIGHT_PRUNED,
                "speed": H3_SPEED_QUALITY,
                "custom_steps": 20,
                "steps": 20,
                "lora_name": lora_name,
                "lora_strength": 0.0,
            }
        return {
            "weight_profile": H3_WEIGHT_FULL,
            "speed": H3_SPEED_FAST,
            "custom_steps": 4,
            "steps": 4,
            "lora_name": lora_name,
            "lora_strength": LIGHTX2V_LORA_STRENGTH,
        }
    if key in DUAL_ACCEL_WORKFLOW_IDS:
        if pruned_first_pass:
            return {
                "weight_profile": H3_WEIGHT_PRUNED,
                "speed": H3_SPEED_QUALITY,
                "custom_steps": 20,
                "steps": 20,
                "lora_name": DUAL_ACCEL_LORA_NAME,
                "lora_strength": 0.0,
            }
        return {
            "weight_profile": H3_WEIGHT_FULL,
            "speed": H3_SPEED_BALANCED,
            "custom_steps": 8,
            "steps": 8,
            "lora_name": DUAL_ACCEL_LORA_NAME,
            "lora_strength": DUAL_ACCEL_LORA_STRENGTH,
        }
    if key in DIRECTOR_ACCEL_WORKFLOW_IDS:
        return {
            "weight_profile": H3_WEIGHT_PRUNED,
            "speed": H3_SPEED_BALANCED,
            "steps": 20,
            "video_steps": 20,
            "audio_steps": 20,
            "lora_strength": 0.0,
        }
    if key in T8_WORKFLOW_IDS:
        if pruned_first_pass:
            defaults: dict[str, Any] = {
                "weight_profile": H3_WEIGHT_PRUNED,
                "speed": H3_SPEED_QUALITY,
                "custom_steps": 20,
                "lora_name": H3_TURBO_LORA_NAME,
                "lora_strength": 0.0,
            }
            if key == JobMode.MINIMAX_H3_T8_ALL_REFERENCE.value:
                defaults.update({"steps": 20, "video_steps": 20, "audio_steps": 20})
            else:
                defaults["steps"] = 20
            return defaults
        defaults: dict[str, Any] = {
            "weight_profile": H3_WEIGHT_FULL,
            "speed": H3_SPEED_BALANCED,
            "custom_steps": 8,
            "lora_name": H3_TURBO_LORA_NAME,
            "lora_strength": 1.0,
        }
        if key == JobMode.MINIMAX_H3_T8_ALL_REFERENCE.value:
            defaults.update({"steps": 8, "video_steps": 8, "audio_steps": 10})
        else:
            defaults["steps"] = 8
        return defaults
    return {}


def _apply_refine_first_pass(
    mode: JobMode | str, normalized: dict[str, Any], enabled: bool, quality: str, preview: bool,
    quality_mode: str = "auto",
) -> dict[str, Any]:
    normalized["refine_enabled"] = enabled
    normalized["refine_quality"] = quality
    normalized["refine_quality_mode"] = quality_mode
    normalized["refine_preview"] = preview
    if enabled:
        normalized["quality"] = "0.4"
        normalized["megapixels"] = 0.4
        normalized.update(_refine_first_pass_defaults(mode))
        normalized["refine_megapixels"] = refine_target_megapixels(
            quality, h3_length(normalized), force=quality_mode == "force",
        )
    return normalized


def normalize_options(mode: JobMode | str, raw: dict[str, Any] | None) -> dict[str, Any]:
    if is_video_edit_workflow(mode):
        normalized = _normalize_schema_options(VIDEO_EDIT_OPTION_SCHEMA, raw or {})
        normalized.update(length=VIDEO_EDIT_LENGTHS[normalized["duration"]], fps=24)
        return normalized
    if mode_key(mode) == JobMode.SCAIL2_REPLACEMENT.value:
        normalized = _normalize_schema_options(SCAIL2_OPTION_SCHEMA, raw or {})
        for key, label in [("source_points", "视频首帧"), ("reference_points", "形象图")]:
            normalized[key] = json.dumps(subject_points(normalized[key], label, int(normalized["subject_count"])), ensure_ascii=False)
        return normalized
    if is_motion_transfer_workflow(mode):
        normalized = _normalize_schema_options(MOTION_TRANSFER_OPTION_SCHEMA, raw or {})
        quality = MOTION_TRANSFER_OPTION_SCHEMA["properties"]["render_quality"]
        # Legacy API clients may submit steps directly; new forms submit semantic presets.
        if "steps" not in (raw or {}):
            normalized["steps"] = quality["steps_by_quality"][normalized["render_quality"]]
        width, height, length = resolve_motion_transfer_dimensions(normalized["aspect_ratio"], normalized["duration"])
        normalized.update(width=width, height=height, length=length, fps=24)
        return normalized
    if is_depth_workflow(mode):
        normalized = _normalize_schema_options(DEPTH_OPTION_SCHEMA, raw or {})
        normalized["length"] = DEPTH_LENGTHS[normalized["duration"]]
        normalized["fps"] = 24
        return normalized
    if is_keyframe_workflow(mode):
        normalized = _normalize_schema_options(KEYFRAME_OPTION_SCHEMA, raw or {})
        width, height, length = resolve_keyframe_dimensions(normalized["aspect_ratio"], normalized["duration"])
        normalized.update(width=width, height=height, length=length, fps=24)
        return normalized
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
        elif (
            definition.grs_profile in {GRS_PROFILE_GPT_IMAGE_2_VIP, GRS_PROFILE_GPT_IMAGE_2_5, GRS_PROFILE_GPT_IMAGE_2_5_VIP}
            and normalized["aspect_ratio"] != "auto"
        ):
            if normalized["resolution"] not in GRS_VIP_SIZES.get(normalized["aspect_ratio"], {}):
                raise ValueError("当前画面比例不支持所选分辨率。")
        return normalized
    if not is_h3_workflow(mode):
        definition = workflow_for(mode)
        if definition.option_schema is not None:
            return _normalize_schema_options(definition.option_schema, raw or {})
        return {}
    raw = dict(raw or {})
    raw.pop("upscale_after", None)
    if is_t8_workflow(mode):
        normalized = _normalize_schema_options(workflow_for(mode).option_schema or {}, raw)
        return _apply_refine_first_pass(mode, normalized, *_refine_settings(raw))
    if is_avatar_workflow(mode):
        if raw.keys() & H3_REFINE_OPTION_NAMES:
            raise ValueError("数字人口播暂不支持二采精修：二采改用 Director 管线，会脱离口播音频驱动。")
        return _normalize_schema_options(workflow_for(mode).option_schema or {}, raw)
    if is_lip_sync_workflow(mode):
        if raw.keys() & H3_REFINE_OPTION_NAMES:
            raise ValueError("口型同步暂不支持二采精修：二采会脱离目标音频驱动。")
        normalized = _normalize_schema_options(workflow_for(mode).option_schema or {}, raw, apply_speed=False)
        speed = str(normalized.get("speed", "fast"))
        if speed == "fast":
            steps, use_turbo = 4, True
        elif speed == "fine":
            steps, use_turbo = 20, False
        else:
            steps = int(normalized.get("custom_steps", 4))
            use_turbo = steps <= LIPSYNC_TURBO_MAX_STEPS
        normalized["speed"] = speed
        normalized["steps"] = steps
        normalized["use_turbo"] = use_turbo
        normalized["unet_name"] = H3_REF2VA_FULL if use_turbo else H3_REF2VA_PRUNED
        normalized["lora_strength"] = LIGHTX2V_LORA_STRENGTH if use_turbo else 0.0
        return normalized
    if is_lightx2v_workflow(mode):
        normalized = _normalize_schema_options(workflow_for(mode).option_schema or {}, raw, apply_speed=False)
        normalized = apply_lightx2v_speed_preset(
            normalized, raw, is_reference=mode_key(mode) == JobMode.MINIMAX_H3_LIGHTX2V_R2V.value,
        )
        return _apply_refine_first_pass(mode, normalized, *_refine_settings(raw))
    if is_dual_accel_workflow(mode):
        normalized = _normalize_schema_options(workflow_for(mode).option_schema or {}, raw, apply_speed=False)
        normalized = apply_dual_accel_speed_preset(normalized, raw)
        return _apply_refine_first_pass(mode, normalized, *_refine_settings(raw))
    if is_director_accel_workflow(mode):
        normalized = _normalize_schema_options(workflow_for(mode).option_schema or {}, raw, apply_speed=False)
        normalized = apply_director_accel_speed_preset(normalized, raw)
        return _apply_refine_first_pass(mode, normalized, *_refine_settings(raw))
    unknown_options = set(raw) - H3_OPTION_NAMES
    if unknown_options:
        names = ", ".join(sorted(unknown_options))
        raise ValueError(f"MiniMax H3 does not support options: {names}")
    refine_enabled, refine_quality, refine_preview, refine_quality_mode = _refine_settings(raw)
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
    # Refine first pass is platform-owned (精简权重 + 8 步 LightX2V LoRA)，与机器托管无关。
    auto_runtime = {} if refine_enabled else auto_h3_runtime_options(raw, default_speed=H3_SPEED_BALANCED)
    speed = raw.get("speed", auto_runtime.get("speed", H3_SPEED_BALANCED))
    custom_steps = raw.get("custom_steps", 8)
    use_sage = raw.get("use_sage_attention", True)
    if not isinstance(use_sage, bool):
        raise ValueError("SageAttention 必须为布尔值。")
    if refine_enabled:
        quality = "0.4"
        legacy_megapixels = 0.4
        speed = H3_SPEED_BALANCED
    normalized = apply_h3_speed_preset({
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "megapixels": float(legacy_megapixels) if legacy_megapixels is not None and (raw.get("quality") is None or legacy_quality) else H3_QUALITY_MEGAPIXELS[quality],
        "duration": duration,
        "reference_image_size": "match",
        "speed": speed,
        "custom_steps": custom_steps,
        "weight_profile": H3_WEIGHT_PRUNED if refine_enabled else raw.get("weight_profile", auto_runtime.get("weight_profile", H3_WEIGHT_FULL)),
        "use_sage_attention": use_sage,
        "refine_enabled": refine_enabled,
        "refine_quality": refine_quality,
        "refine_quality_mode": refine_quality_mode,
        "refine_preview": refine_preview,
    }, raw)
    if refine_enabled:
        normalized["lora_name"] = LIGHTX2V_FL2V_8STEP_LORA
        normalized["lora_strength"] = 1.0
        normalized["refine_megapixels"] = refine_target_megapixels(
            refine_quality, h3_length(normalized), force=refine_quality_mode == "force",
        )
    return normalized


def _normalize_schema_options(
    schema: dict[str, Any], raw: dict[str, Any], *, apply_speed: bool = True,
    auto_default_speed: str = H3_SPEED_BALANCED,
) -> dict[str, Any]:
    definitions = schema.get("properties", {})
    unknown_options = set(raw) - set(definitions)
    if unknown_options:
        names = ", ".join(sorted(unknown_options))
        raise ValueError(f"当前工作流不支持参数: {names}")
    normalized: dict[str, Any] = {}
    for name, definition in definitions.items():
        if name == "seed" and not definition.get("randomize_when_zero"):
            minimum = int(definition.get("minimum", 0))
            maximum = int(definition.get("maximum", 2**63 - 2))
            normalized[name] = minimum + secrets.randbelow(maximum - minimum + 1)
            continue
        value = raw.get(name, definition.get("default"))
        value_type = definition.get("type")
        if value_type == "boolean":
            value = coerce_bool_option(value, label=str(definition.get("label") or name))
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
        if name == "seed" and definition.get("randomize_when_zero") and value == 0:
            value = 1 + secrets.randbelow(int(definition["maximum"]))
        normalized[name] = value
    quality_definition = definitions.get("quality")
    if quality_definition:
        # H3 系列的画质联动（quality -> megapixels）；其他工作流的 quality 无此映射。
        quality_map = quality_definition.get("megapixels_by_quality", {})
        if quality_map and "quality" in raw:
            if normalized["quality"] not in quality_map:
                raise ValueError(f"{quality_definition.get('label') or '画质'} 不是有效选项。")
            normalized["megapixels"] = quality_map[normalized["quality"]]
    if apply_speed and "speed" in definitions:
        normalized.update(auto_h3_runtime_options(raw, default_speed=auto_default_speed))
        apply_h3_speed_preset(normalized, raw)
    for name, definition in definitions.items():
        other_name = definition.get("ui_not_less_than")
        if not other_name:
            continue
        current = normalized.get(name)
        other = normalized.get(other_name)
        if (
            isinstance(current, (int, float)) and not isinstance(current, bool)
            and isinstance(other, (int, float)) and not isinstance(other, bool)
            and current < other
        ):
            other_label = definitions.get(other_name, {}).get("label", other_name)
            raise ValueError(f"{definition['label']} 不能小于 {other_label}。")
    return normalized


def quality_for_megapixels(schema: dict[str, Any], megapixels: Any) -> str | None:
    """Map legacy stored MP values to the nearest current user-facing quality preset."""
    quality_definition = schema.get("properties", {}).get("quality", {})
    quality_map = quality_definition.get("megapixels_by_quality", {})
    if not quality_map or isinstance(megapixels, bool) or not isinstance(megapixels, (int, float)):
        return None
    return min(quality_map, key=lambda quality: abs(quality_map[quality] - float(megapixels)))


def validate_option_relationships(mode: JobMode | str, options: dict[str, Any], reference_count: int) -> None:
    definitions = (workflow_for(mode).option_schema or {}).get("properties", {})
    for name, definition in definitions.items():
        trigger = definition.get("ui_requires_references_when")
        if trigger is not None and str(options.get(name)) == str(trigger) and reference_count < 1:
            raise ValueError(f"{definition.get('label', name)}为 {trigger} 时至少需要 1 张参考图。")


def grs_request_size(mode: JobMode | str, options: dict[str, Any]) -> tuple[str, str | None]:
    """Map registry values to the GRS wire-level aspectRatio/imageSize fields."""
    definition = workflow_for(mode)
    aspect_ratio = options["aspect_ratio"]
    resolution = options["resolution"]
    if definition.grs_profile == GRS_PROFILE_GPT_IMAGE_2_VIP and resolution == "CUSTOM":
        return f"{options['custom_width']}x{options['custom_height']}", None
    # GPT Image 2.5 系列只接受像素值或 auto（实测 1:1 会被上游拒绝）。
    if definition.grs_profile in {GRS_PROFILE_GPT_IMAGE_2_VIP, GRS_PROFILE_GPT_IMAGE_2_5, GRS_PROFILE_GPT_IMAGE_2_5_VIP}:
        if aspect_ratio == "auto":
            return aspect_ratio, resolution
        return GRS_VIP_SIZES[aspect_ratio][resolution], resolution
    return aspect_ratio, resolution


def h3_dimensions(options: dict[str, Any]) -> tuple[int, int]:
    _, ratio = parse_h3_aspect_ratio(options["aspect_ratio"])
    # Keep the workbench calculation byte-for-byte compatible with ComfyUI's
    # ResolutionSelector: MP is based on 1024² and each side is rounded to the
    # configured 32-pixel alignment grid.
    # `megapixels` is an internal compatibility field. Older saved drafts and
    # director payloads can retain its default while the user-facing quality
    # has already changed, so the quality preset must be authoritative.
    quality = options.get("quality")
    quality_megapixels = H3_STANDARD_RESOLUTION_PRESETS.get(str(quality)) if quality is not None else None
    megapixels = quality_megapixels if quality_megapixels is not None else options["megapixels"]
    area = megapixels * 1024 * 1024
    if not math.isfinite(area * ratio) or not math.isfinite(area / ratio):
        raise ValueError("MiniMax H3 aspect ratio is outside the supported numeric range")
    width = round(math.sqrt(area * ratio) / 32) * 32
    height = round(math.sqrt(area / ratio) / 32) * 32
    return width, height


def h3_length(options: dict[str, Any]) -> int:
    frames = max(5, round(float(options["duration"]) * H3_FPS))
    return frames + ((5 - frames) % 17)
