"""H3 two-pass refine graph (accelerated first pass -> H3 latent upscale -> 3-step refine)."""
from __future__ import annotations

import re
from typing import Any

from .minimax_h3_director_accel_workflow import (
    CREATE_VIDEO_NODE,
    DIRECTOR_NODE,
    GROUP_NODE,
    OUTPUT_NODE,
    TASK_TYPE_FL2V,
    TASK_TYPE_I2V,
    TASK_TYPE_R2V,
    TASK_TYPE_T2V,
    director_accel_unet,
)
from .minimax_h3_workflow import (
    AUDIO_VAE,
    OFFICIAL_RESERVED_VRAM_GB,
    TEXT_ENCODER,
    VIDEO_VAE,
    _image_nodes,
)
from .models import JobMode
from .workflow_registry import (
    DIRECTOR_ACCEL_WORKFLOWS,
    DUAL_ACCEL_WORKFLOWS,
    H3_FL2VA_PRUNED,
    H3_FPS,
    H3_REF2VA_PRUNED,
    H3_WORKFLOWS,
    LIGHTX2V_FL2V_4STEP_LORA,
    LIGHTX2V_FL2V_8STEP_LORA,
    LIGHTX2V_REF2V_4STEP_LORA,
    T8_WORKFLOWS,
    h3_diffusion_unet,
    h3_dimensions,
    h3_length,
    h3_lora_loader_class,
    refine_target_megapixels,
)

REFINE_LATENT_UPSCALER = "minimax_h3_latent_upscaler_3d_bf16.safetensors"
REFINE_STEPS = 3
REFINE_DENOISE = 0.2
FIRST_PASS_MEGAPIXELS = 0.4
REFINE_TILING_MIN_FRAMES = 192
REFINE_MORE_TILES_MIN_FRAMES = 243
PREVIEW_VIDEO_NODE = "46"
PREVIEW_OUTPUT_NODE = "47"
PREVIEW_FILENAME_PREFIX = "video/ZLY_AI_VIDEO_STUDIO_MiniMax_H3_Refine_Preview"
OFFICIAL_H3_MODES = {JobMode.MINIMAX_H3_T2V, JobMode.MINIMAX_H3_I2V, JobMode.MINIMAX_H3_R2V}
REFERENCE_ROUTE_MODES = {
    JobMode.MINIMAX_H3_R2V,
    JobMode.MINIMAX_H3_LIGHTX2V_R2V,
    JobMode.MINIMAX_H3_DUAL_ACCEL_R2V,
    JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V,
}
FAMILY_REFINE_DESCRIPTIONS = {
    "official": "开启后先以 0.4 MP 精简权重 8 步加速生成一采，再用 H3 3D latent 放大到目标画质做第二步精修（3 步 beta，denoise 0.2）。",
    "lightx2v": "开启后平台固定以 0.4 MP、完整权重、快速 4 步 LightX2V 与对应加速 LoRA 生成一采，再用 H3 3D latent 放大到目标画质精修。",
    "dual": "开启后平台固定以 0.4 MP、完整权重、八步双加速设置生成一采，再用 H3 3D latent 放大到目标画质精修。",
    "director": "开启后平台固定以 0.4 MP、精简权重、均衡 20 步生成一采，再用 H3 3D latent 放大到目标画质精修。",
    "t8": "开启后一采改用 Director 两段式管线（0.4 MP、完整权重、8 步 Turbo LoRA）；T8 专有采样器与音频模式不参与二采。",
}
NATIVE_ASPECT_RATIO = re.compile(
    r"((?:\d+(?:\.\d*)?|\.\d+)\s*:\s*(?:\d+(?:\.\d*)?|\.\d+))"
)


def first_pass_task_type(mode: JobMode | str, references: list[str]) -> str:
    key = JobMode(mode) if isinstance(mode, str) else mode
    if key is JobMode.MINIMAX_H3_T8_DUAL_CLOCK:
        return TASK_TYPE_I2V if references else TASK_TYPE_T2V
    if key in REFERENCE_ROUTE_MODES:
        return TASK_TYPE_R2V
    if key is JobMode.MINIMAX_H3_T8_ALL_REFERENCE:
        return TASK_TYPE_R2V if references else TASK_TYPE_T2V
    if not references:
        return TASK_TYPE_T2V
    if len(references) == 1:
        return TASK_TYPE_I2V
    return TASK_TYPE_FL2V


def first_pass_lora(steps: int, *, is_reference: bool = False) -> str | None:
    if steps <= 4:
        return LIGHTX2V_REF2V_4STEP_LORA if is_reference else LIGHTX2V_FL2V_4STEP_LORA
    if steps <= 8:
        return LIGHTX2V_FL2V_8STEP_LORA
    return None


def numeric_aspect_ratio(options: dict[str, Any]) -> str:
    raw = str(options.get("aspect_ratio") or "16:9").strip()
    match = NATIVE_ASPECT_RATIO.search(raw)
    return match.group(1).strip() if match else raw


def first_pass_steps(mode: JobMode, options: dict[str, Any]) -> int:
    if mode in OFFICIAL_H3_MODES:
        return 8
    if mode in T8_WORKFLOWS and options.get("video_steps") is not None:
        return int(options["video_steps"])
    return int(options.get("steps") or 8)


def first_pass_unet(mode: JobMode, task_type: str, options: dict[str, Any]) -> str:
    is_reference = task_type == TASK_TYPE_R2V
    if mode in OFFICIAL_H3_MODES:
        return H3_REF2VA_PRUNED if is_reference else H3_FL2VA_PRUNED
    if mode in DIRECTOR_ACCEL_WORKFLOWS:
        return director_accel_unet(is_reference, options)
    return h3_diffusion_unet(is_reference, float(options.get("lora_strength") or 0))


def _family_uses_kj_sage(mode: JobMode) -> bool:
    return mode in OFFICIAL_H3_MODES or mode in DIRECTOR_ACCEL_WORKFLOWS or mode in DUAL_ACCEL_WORKFLOWS


def _family_lora_loader(mode: JobMode, unet: str) -> str:
    if mode in T8_WORKFLOWS:
        return h3_lora_loader_class(unet)
    return "LoraLoaderModelOnly"


def _first_pass_sampler(mode: JobMode, options: dict[str, Any]) -> str:
    if mode in T8_WORKFLOWS:
        return "res_multistep"
    return str(options.get("sampler_name") or options.get("sampler") or "res_multistep")


def refine_tiling(length: int) -> tuple[bool, int]:
    if length > REFINE_MORE_TILES_MIN_FRAMES:
        return True, 4
    if length >= REFINE_TILING_MIN_FRAMES:
        return True, 2
    return False, 2


def build_refine_nodes(
    task_type: str,
    *,
    refine_quality: str,
    aspect_ratio: str,
    length: int,
    first_pass_model: list[Any],
    confirm_first_pass: bool = False,
    refine_mode: str = "auto",
) -> tuple[dict[str, dict[str, Any]], list[Any]]:
    """Second-pass nodes shared by Director-based and timeline graphs.

    The refine leaves ``refine_model`` unwired so the Director reuses the already
    resident first-pass UNET. Loading a second ~12 GB UNET alongside the first
    pass deadlocks DynamicVRAM model init on 16 GB cards for long clips. The
    target canvas is capped by frame count in auto mode; 1.0+ MP on long clips
    costs minutes per step on the same card. ``refine_mode="force"`` skips the
    cap and accepts that cost.
    """
    target_megapixels = refine_target_megapixels(
        refine_quality, length, force=refine_mode == "force",
    )
    target_options = {
        "aspect_ratio": aspect_ratio,
        "quality": f"{target_megapixels:.1f}",
        "megapixels": target_megapixels,
    }
    target_width, target_height = h3_dimensions(target_options)
    enable_tiling, tile_count = refine_tiling(length)
    nodes: dict[str, dict[str, Any]] = {
        "44": {
            "class_type": "BasicScheduler",
            "inputs": {
                "model": first_pass_model,
                "scheduler": "beta",
                "steps": REFINE_STEPS,
                "denoise": REFINE_DENOISE,
            },
        },
        "45": {
            "class_type": "MiniMaxH3DirectorRefine",
            "inputs": {
                "sigmas": ["44", 0],
                "mode": "upscale",
                "upscale_method": "h3_latent",
                "latent_upscale_model": REFINE_LATENT_UPSCALER,
                "sampler": "euler",
                "passes": 1,
                "seed_mode": "inherit",
                "aspect_ratio": "跟随导演台",
                "megapixels": target_megapixels,
                "width": target_width,
                "height": target_height,
                "skip_fl2v": task_type != TASK_TYPE_FL2V,
                "confirm_first_pass": confirm_first_pass,
                "enable_latent_chunking": length > 60,
                "enable_tiling": enable_tiling,
                "tile_count": tile_count,
                "tile_overlap": 128,
                "seed": 0,
            },
        },
    }
    return nodes, ["45", 0]


def build_minimax_h3_refine_workflow(
    mode: JobMode,
    prompt: str,
    references: list[str],
    options: dict[str, Any],
    seed: int,
    *,
    preview: bool = False,
) -> dict[str, dict[str, Any]]:
    if mode not in H3_WORKFLOWS:
        raise ValueError(f"Unsupported H3 refine workflow: {mode}")

    aspect_ratio = numeric_aspect_ratio(options)
    length = h3_length(options)
    task_type = first_pass_task_type(mode, references)
    is_reference_mode = task_type == TASK_TYPE_R2V
    steps = first_pass_steps(mode, options)
    unet = first_pass_unet(mode, task_type, options)
    lora_strength = float(options.get("lora_strength") or 0)
    lora_name = str(options.get("lora_name") or "").strip()
    if mode in OFFICIAL_H3_MODES and not lora_name:
        lora_name = first_pass_lora(steps, is_reference=is_reference_mode) or ""
    use_sage = bool(options.get("use_sage_attention", True))
    sage_allow_compile = bool(options.get("sage_allow_compile", False))
    refine_quality = str(options.get("refine_quality") or "1.0")
    refine_mode = str(options.get("refine_quality_mode") or "auto")
    width, height = h3_dimensions({
        "aspect_ratio": aspect_ratio,
        "quality": str(FIRST_PASS_MEGAPIXELS),
        "megapixels": FIRST_PASS_MEGAPIXELS,
    })

    workflow: dict[str, dict[str, Any]] = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": unet,
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax", "device": "default"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
    }

    model_source: list[Any] = ["1", 0]
    if lora_strength and lora_name:
        workflow["15"] = {
            "class_type": _family_lora_loader(mode, unet),
            "inputs": {"model": model_source, "lora_name": lora_name, "strength_model": lora_strength},
        }
        model_source = ["15", 0]
    if mode in OFFICIAL_H3_MODES:
        workflow["18"] = {
            "class_type": "ReservedVRAMSetter",
            "inputs": {
                "anything": model_source,
                "reserved": OFFICIAL_RESERVED_VRAM_GB,
                "mode": "manual",
                "seed": 0,
                "auto_max_reserved": 0,
                "clean_gpu_before": True,
            },
        }
        model_source = ["18", 0]
    if use_sage:
        if _family_uses_kj_sage(mode):
            workflow["16"] = {
                "class_type": "PathchSageAttentionKJ",
                "inputs": {
                    "model": model_source,
                    "sage_attention": "auto",
                    "allow_compile": sage_allow_compile,
                },
            }
            model_source = ["16", 0]
        workflow["17"] = {
            "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
            "inputs": {"model": model_source},
        }
        model_source = ["17", 0]

    image_nodes = _image_nodes(workflow, references)
    group_inputs: dict[str, Any] = {
        "prompt": prompt,
        "duration_sec": length / H3_FPS,
    }
    if is_reference_mode:
        group_inputs["ref_image_size"] = str(options.get("reference_image_size") or options.get("ref_image_size") or "match")
        for index, image_node in enumerate(image_nodes):
            group_inputs[f"ref_images.ref_image_{index}"] = [image_node, 0]
        group_class = "MiniMaxH3DirectorGroupReferenceToVideo"
        group_link_key = "r2v_groups"
    else:
        if image_nodes:
            group_inputs["first_frame"] = [image_nodes[0], 0]
        if len(image_nodes) > 1:
            group_inputs["last_frame"] = [image_nodes[1], 0]
        group_class = "MiniMaxH3DirectorGroupImageToVideo"
        group_link_key = "i2v_groups"

    workflow[GROUP_NODE] = {"class_type": group_class, "inputs": group_inputs}
    workflow[DIRECTOR_NODE] = {
        "class_type": "MiniMaxH3Director",
        "inputs": {
            "model": model_source,
            "video_vae": ["3", 0],
            "audio_vae": ["4", 0],
            "clip": ["2", 0],
            "refine": ["45", 0],
            "task_type": task_type,
            "global_prompt": "",
            "bd_grp_sample": "采样设置",
            "cfg": float(options.get("cfg", 1.0)),
            "seed": seed,
            "frame_rate": float(H3_FPS),
            "width": width,
            "height": height,
            "ref_max_size": max(width, height),
            "total_frames": length,
            "timeline_data": "",
            group_link_key: [GROUP_NODE, 0],
            "bd_grp_advanced": "高级采样",
            "steps": steps,
            "sampler": _first_pass_sampler(mode, options),
            "scheduler": "simple",
            "shift_video": float(options.get("shift_video", 12.0)),
            "shift_audio": float(options.get("shift_audio", 3.0)),
            "bd_grp_perf": "性能",
            "clear_vram_between_segments": True,
            # 一采模型仍驻留时二采会再暂存一份 20GB 权重，68GB 内存机器随即分页，单步放大到分钟级。
            "clear_vram_before_refine": True,
            "export_source_images": False,
        },
    }

    refine_nodes, refine_link = build_refine_nodes(
        task_type,
        refine_quality=refine_quality,
        aspect_ratio=aspect_ratio,
        length=length,
        first_pass_model=model_source,
        confirm_first_pass=preview,
        refine_mode=refine_mode,
    )
    workflow.update(refine_nodes)
    workflow[DIRECTOR_NODE]["inputs"]["refine"] = refine_link

    workflow[CREATE_VIDEO_NODE] = {
        "class_type": "CreateVideo",
        "inputs": {
            "images": [DIRECTOR_NODE, 0],
            "audio": [DIRECTOR_NODE, 1],
            "fps": [DIRECTOR_NODE, 2],
            "bit_depth": 8,
        },
    }
    workflow[OUTPUT_NODE] = {
        "class_type": "SaveVideo",
        "inputs": {
            "video": [CREATE_VIDEO_NODE, 0],
            "filename_prefix": "video/ZLY_AI_VIDEO_STUDIO_MiniMax_H3_Refine",
            "format": "auto",
            "codec": "auto",
        },
    }
    if preview:
        add_first_pass_preview(workflow, DIRECTOR_NODE, PREVIEW_FILENAME_PREFIX)
    return workflow


def add_first_pass_preview(
    workflow: dict[str, dict[str, Any]],
    director_node: str,
    filename_prefix: str,
    *,
    video_node: str = PREVIEW_VIDEO_NODE,
    output_node: str = PREVIEW_OUTPUT_NODE,
) -> dict[str, dict[str, Any]]:
    workflow[video_node] = {
        "class_type": "CreateVideo",
        "inputs": {
            "images": [director_node, 6],
            "audio": [director_node, 1],
            "fps": [director_node, 2],
            "bit_depth": 8,
        },
    }
    workflow[output_node] = {
        "class_type": "SaveVideo",
        "inputs": {
            "video": [video_node, 0],
            "filename_prefix": filename_prefix,
            "format": "auto",
            "codec": "auto",
        },
    }
    return workflow


def continuation_workflow(
    workflow: dict[str, dict[str, Any]],
    *,
    video_node: str = PREVIEW_VIDEO_NODE,
    output_node: str = PREVIEW_OUTPUT_NODE,
) -> dict[str, dict[str, Any]]:
    """Drop the first-pass preview outputs; the seeded graph keeps the ComfyUI cache key."""
    result = dict(workflow)
    result.pop(video_node, None)
    result.pop(output_node, None)
    return result
