from __future__ import annotations

import math
import re
import secrets
from dataclasses import asdict, dataclass
from typing import Any

from .models import JobMode


@dataclass(frozen=True)
class WorkflowDefinition:
    id: JobMode
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

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("option_schema", None)
        data["id"] = self.id.value
        data["reference_labels"] = list(self.reference_labels)
        data["parameters"] = parameter_payload(self)
        return data


def option(label: str, value_type: str, default: Any, *, group: str = "internal", **constraints: Any) -> dict[str, Any]:
    return {"label": label, "type": value_type, "default": default, "ui_group": group, **constraints}


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

GRS_IMAGE_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "aspect_ratio": option(
            "画面比例", "string", "1:1", group="primary", enum=GRS_ASPECT_RATIOS,
            ui_control="visual-settings", ui_companion="resolution", ui_options=GRS_ASPECT_RATIO_UI_OPTIONS,
        ),
        "resolution": option(
            "分辨率", "string", "1K", group="primary", enum=["1K"], ui_control="select",
        ),
        "count": option(
            "生成数量", "integer", 1, group="primary", minimum=1, maximum=4, step=1,
            ui_control="input-number",
        ),
        "provider_model": option("远端模型", "string", "gpt-image-2", enum=["gpt-image-2"]),
        "poll_interval_seconds": option("轮询间隔", "integer", 5, minimum=5, maximum=30),
    },
}

GRS_IMAGE_VIP_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "aspect_ratio": option(
            "画面比例", "string", "1:1", group="primary", enum=GRS_VIP_ASPECT_RATIOS,
            ui_control="visual-settings", ui_companion="resolution", ui_options=GRS_VIP_ASPECT_RATIO_UI_OPTIONS,
        ),
        "resolution": option(
            "分辨率", "string", "1K", group="primary", enum=["1K", "2K", "4K", "CUSTOM"],
            ui_control="select",
        ),
        "count": option(
            "生成数量", "integer", 1, group="primary", minimum=1, maximum=4, step=1,
            ui_control="input-number",
        ),
        "custom_width": option(
            "自定义宽度", "integer", 1024, group="advanced", minimum=16, maximum=3840, step=16,
            unit="px", ui_control="input-number", ui_visible_when={"resolution": "CUSTOM"},
        ),
        "custom_height": option(
            "自定义高度", "integer", 1024, group="advanced", minimum=16, maximum=3840, step=16,
            unit="px", ui_control="input-number", ui_visible_when={"resolution": "CUSTOM"},
        ),
        "provider_model": option("远端模型", "string", "gpt-image-2-vip", enum=["gpt-image-2-vip"]),
        "poll_interval_seconds": option("轮询间隔", "integer", 5, minimum=5, maximum=30),
    },
}


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
            "分辨率", "string", "1K", group="advanced", ui_control="select",
            ui_options=[
                {"value": "1K", "label": "1K"},
                {"value": "2K", "label": "2K"},
                {"value": "4K", "label": "4K"},
            ],
            megapixels_by_quality={"1K": 0.2, "2K": 0.3, "4K": 0.5},
            description="更高分辨率会提高画面细节、显存占用和生成时间。",
        ),
        "megapixels": option(
            "内部像素面积", "number", 0.2, group="internal", minimum=0.1, maximum=16.0, step=0.1, unit="MP",
        ),
        "duration": option(
            "时长", "number", 5, group="primary", minimum=5, maximum=15, step=1, unit="秒",
            ui_control="duration-slider",
        ),
    },
}

T8_ASPECT_RATIOS = [
    "1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)",
    "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)",
]


def t8_option_schema(*, sampler: str) -> dict[str, Any]:
    multirate = sampler == "multirate"
    quality_megapixels = {"1K": 0.4 if multirate else 0.7, "2K": 1.0, "4K": 2.0}
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
            "分辨率", "string", "1K", group="advanced", ui_control="select",
            ui_options=[
                {"value": "1K", "label": "1K"},
                {"value": "2K", "label": "2K"},
                {"value": "4K", "label": "4K"},
            ],
            megapixels_by_quality=quality_megapixels,
            description="更高分辨率会提高画面细节、显存占用和生成时间。",
        ),
        "megapixels": option(
            "内部像素面积", "number", 0.4 if multirate else 0.7, group="internal",
            minimum=0.1, maximum=16.0, step=0.1, unit="MP",
        ),
        "multiple": option("尺寸对齐倍数", "integer", 32, minimum=8, maximum=128, step=4),
        "duration": option(
            "时长", "number", 8 if multirate else 5, group="primary",
            minimum=2, maximum=15, step=1, unit="秒", ui_control="duration-slider",
        ),
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
            "扩散模型", "string", "minimax_h3_fl2va_int8_convrot.safetensors",
            enum=["minimax_h3_fl2va_int8_convrot.safetensors"],
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
            "加速 LoRA", "string", "minimax_h3_turbo_4STEPS_comfyui.safetensors",
            enum=["minimax_h3_turbo_4STEPS_comfyui.safetensors"],
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


WORKFLOWS: tuple[WorkflowDefinition, ...] = (
    WorkflowDefinition(
        JobMode.GRS_GPT_IMAGE_2,
        "GPT Image 2",
        "使用 GRS 生成图片，支持 0–10 张有序参考图。",
        "collection",
        0,
        10,
        option_schema=GRS_IMAGE_OPTION_SCHEMA,
        media_type="image",
        executor="grs",
    ),
    WorkflowDefinition(
        JobMode.GRS_GPT_IMAGE_2_VIP,
        "GPT Image 2 VIP",
        "使用 GRS 高画质图片能力，支持 1K/2K/4K 与自定义尺寸。",
        "collection",
        0,
        10,
        option_schema=GRS_IMAGE_VIP_OPTION_SCHEMA,
        media_type="image",
        executor="grs",
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_T2V,
        "MiniMax H3 文生视频",
        "根据提示词生成带原生音频的视频。",
        "none",
        0,
        0,
        supports_h3_options=True,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_I2V,
        "MiniMax H3 首尾帧视频",
        "首帧和尾帧是时间锚点；可以只使用首帧。",
        "keyframes",
        1,
        2,
        ("首帧", "尾帧（可选）"),
        supports_h3_options=True,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_R2V,
        "MiniMax H3 多参考视频",
        "按顺序添加角色、场景或风格参考，并在提示词中引用 <Picture n>。",
        "collection",
        1,
        9,
        supports_h3_options=True,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_T8_ALL_REFERENCE,
        "MiniMax H3 全能参考（多速率）",
        "支持 0-9 张有序参考图，自动匹配文生或参考图生成。",
        "collection",
        0,
        9,
        supports_h3_options=True,
        option_schema=T8_MULTIRATE_OPTION_SCHEMA,
    ),
    WorkflowDefinition(
        JobMode.MINIMAX_H3_T8_DUAL_CLOCK,
        "MiniMax H3 双时钟 8 步",
        "支持文生或单参考图生成，使用工作流推荐的双时钟采样配置。",
        "collection",
        0,
        1,
        supports_h3_options=True,
        option_schema=T8_DUAL_CLOCK_OPTION_SCHEMA,
    ),
)

WORKFLOW_BY_ID = {definition.id: definition for definition in WORKFLOWS}
T8_WORKFLOWS = {JobMode.MINIMAX_H3_T8_ALL_REFERENCE, JobMode.MINIMAX_H3_T8_DUAL_CLOCK}
IMAGE_WORKFLOWS = {JobMode.GRS_GPT_IMAGE_2, JobMode.GRS_GPT_IMAGE_2_VIP}
H3_WORKFLOWS = {
    JobMode.MINIMAX_H3_T2V,
    JobMode.MINIMAX_H3_I2V,
    JobMode.MINIMAX_H3_R2V,
    *T8_WORKFLOWS,
}

H3_QUALITY_MEGAPIXELS = H3_STANDARD_OPTION_SCHEMA["properties"]["quality"]["megapixels_by_quality"]
H3_LEGACY_MEGAPIXELS = set(H3_QUALITY_MEGAPIXELS.values()) | {0.4}
H3_OPTION_NAMES = {"aspect_ratio", "quality", "megapixels", "duration"}
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
            "description": "固定为当前工作流 ID。", "default": definition.id.value,
            "values": [definition.id.value],
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


def workflow_for(mode: JobMode) -> WorkflowDefinition:
    return WORKFLOW_BY_ID[mode]


def validate_references(mode: JobMode, references: list[object]) -> None:
    definition = WORKFLOW_BY_ID.get(mode)
    if definition is None:
        raise ValueError(f"工作流 {mode.value} 已从当前工作台移除")
    count = len(references)
    if not definition.min_references <= count <= definition.max_references:
        if definition.min_references == definition.max_references:
            raise ValueError(f"{definition.name} 需要 {definition.min_references} 张参考图。")
        raise ValueError(
            f"{definition.name} 支持 {definition.min_references}-{definition.max_references} 张参考图，当前为 {count} 张。"
        )


def normalize_options(mode: JobMode, raw: dict[str, Any] | None) -> dict[str, Any]:
    if mode in IMAGE_WORKFLOWS:
        normalized = _normalize_schema_options(workflow_for(mode).option_schema or {}, raw or {})
        if mode is JobMode.GRS_GPT_IMAGE_2_VIP and normalized["resolution"] == "CUSTOM":
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
        elif mode is JobMode.GRS_GPT_IMAGE_2_VIP and normalized["aspect_ratio"] != "auto":
            if normalized["resolution"] not in GRS_VIP_SIZES.get(normalized["aspect_ratio"], {}):
                raise ValueError("当前画面比例不支持所选分辨率。")
        return normalized
    if mode not in H3_WORKFLOWS:
        return {}
    raw = raw or {}
    if mode in T8_WORKFLOWS:
        return _normalize_schema_options(workflow_for(mode).option_schema or {}, raw)
    unknown_options = set(raw) - H3_OPTION_NAMES
    if unknown_options:
        names = ", ".join(sorted(unknown_options))
        raise ValueError(f"MiniMax H3 does not support options: {names}")
    aspect_ratio, _ = parse_h3_aspect_ratio(raw.get("aspect_ratio", "16:9"))
    quality = raw.get("quality")
    legacy_megapixels = raw.get("megapixels")
    if quality is None and legacy_megapixels is not None and float(legacy_megapixels) not in H3_LEGACY_MEGAPIXELS:
        raise ValueError("MiniMax H3 请选择 1K、2K 或 4K 分辨率。")
    if quality is None and legacy_megapixels is not None:
        quality = min(H3_QUALITY_MEGAPIXELS, key=lambda item: abs(H3_QUALITY_MEGAPIXELS[item] - float(legacy_megapixels)))
    quality = quality or "1K"
    duration = float(raw.get("duration", 5))
    if quality not in H3_QUALITY_MEGAPIXELS:
        raise ValueError("MiniMax H3 请选择 1K、2K 或 4K 分辨率。")
    if not 5 <= duration <= 15:
        raise ValueError("MiniMax H3 时长必须在 5 到 15 秒之间。")
    return {
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "megapixels": float(legacy_megapixels) if raw.get("quality") is None and legacy_megapixels is not None else H3_QUALITY_MEGAPIXELS[quality],
        "duration": duration,
        "reference_image_size": "match",
    }


def _normalize_schema_options(schema: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
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


def validate_option_relationships(mode: JobMode, options: dict[str, Any], reference_count: int) -> None:
    if mode in T8_WORKFLOWS and options.get("task_type") == "Ref2VA" and reference_count == 0:
        raise ValueError("Ref2VA 任务类型至少需要 1 张参考图。")


def grs_request_size(mode: JobMode, options: dict[str, Any]) -> tuple[str, str | None]:
    """Map registry values to the GRS wire-level aspectRatio/imageSize fields."""
    aspect_ratio = options["aspect_ratio"]
    resolution = options["resolution"]
    if mode is JobMode.GRS_GPT_IMAGE_2:
        return aspect_ratio, resolution
    if resolution == "CUSTOM":
        return f"{options['custom_width']}x{options['custom_height']}", None
    if aspect_ratio == "auto":
        return aspect_ratio, resolution
    return GRS_VIP_SIZES[aspect_ratio][resolution], resolution


def h3_dimensions(options: dict[str, Any]) -> tuple[int, int]:
    _, ratio = parse_h3_aspect_ratio(options["aspect_ratio"])
    area = options["megapixels"] * 1_000_000
    if not math.isfinite(area * ratio) or not math.isfinite(area / ratio):
        raise ValueError("MiniMax H3 aspect ratio is outside the supported numeric range")
    width = math.ceil(math.sqrt(area * ratio) / 32) * 32
    height = math.ceil(math.sqrt(area / ratio) / 32) * 32
    max_width, max_height = (1344, 768) if ratio >= 1 else (768, 1344)
    if width > max_width or height > max_height:
        scale = min(max_width / width, max_height / height)
        width = max(32, round(width * scale / 32) * 32)
        height = max(32, round(height * scale / 32) * 32)
    return width, height


def h3_length(options: dict[str, Any]) -> int:
    frames = max(5, round(options["duration"] * 24))
    return frames + (5 - frames % 17) % 17
