from __future__ import annotations

from typing import Any

from .minimax_h3_workflow import AUDIO_VAE, TEXT_ENCODER, VIDEO_VAE, _image_nodes
from .models import JobMode
from .workflow_registry import (
    DIRECTOR_ACCEL_WORKFLOWS,
    H3_FL2VA_FULL,
    H3_FL2VA_PRUNED,
    H3_FPS,
    H3_REF2VA_FULL,
    H3_REF2VA_PRUNED,
    H3_WEIGHT_FULL,
    H3_WEIGHT_PRUNED,
    h3_dimensions,
    h3_length,
)


OUTPUT_NODE = "14"
GROUP_NODE = "30"
DIRECTOR_NODE = "12"
CREATE_VIDEO_NODE = "13"

TASK_TYPE_T2V = "t2v — 文生视频(Text to Video)"
TASK_TYPE_I2V = "i2v — 图生视频(Image to Video)"
TASK_TYPE_FL2V = "fl2v — 首尾帧生视频(First-Last Frame)"
TASK_TYPE_R2V = "r2v — 参考主体生视频(Reference to Video)"


def director_accel_unet(is_reference: bool, options: dict[str, Any]) -> str:
    """Pick FL2VA / REF2VA by route; honor weight_profile (no Turbo LoRA on this family)."""
    profile = str(options.get("weight_profile") or H3_WEIGHT_PRUNED)
    use_full = profile == H3_WEIGHT_FULL
    if is_reference:
        return H3_REF2VA_FULL if use_full else H3_REF2VA_PRUNED
    return H3_FL2VA_FULL if use_full else H3_FL2VA_PRUNED


def resolve_director_accel_task_type(mode: JobMode, references: list[str]) -> str:
    """Map workbench mode + uploaded frames to the Director Combo string."""
    if mode is JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V:
        return TASK_TYPE_R2V
    if mode is JobMode.MINIMAX_H3_DIRECTOR_ACCEL_T2V or not references:
        return TASK_TYPE_T2V
    if len(references) == 1:
        return TASK_TYPE_I2V
    return TASK_TYPE_FL2V


def build_minimax_h3_director_accel_workflow(
    mode: JobMode,
    prompt: str,
    references: list[str],
    options: dict[str, Any],
    seed: int,
) -> dict[str, dict[str, Any]]:
    if mode not in DIRECTOR_ACCEL_WORKFLOWS:
        raise ValueError(f"Unsupported Director Accel workflow: {mode}")

    width, height = h3_dimensions(options)
    length = h3_length(options)
    duration_sec = float(options.get("duration", length / H3_FPS))
    is_reference_mode = mode is JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V
    unet = director_accel_unet(is_reference_mode, options)
    task_type = resolve_director_accel_task_type(mode, references)
    steps = int(options.get("steps", 20))
    sampler_name = str(options.get("sampler_name") or "res_multistep")
    shift_video = float(options.get("shift_video", 12))
    shift_audio = float(options.get("shift_audio", 3))
    cfg = float(options.get("cfg", 1))
    use_sage = bool(options.get("use_sage_attention", True))
    sage_allow_compile = bool(options.get("sage_allow_compile", True))
    ref_max_size = max(width, height)
    model_source: list[Any] = ["1", 0]

    workflow: dict[str, dict[str, Any]] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax", "device": "default"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
    }

    if use_sage:
        workflow["15"] = {
            "class_type": "PathchSageAttentionKJ",
            "inputs": {
                "model": model_source,
                "sage_attention": "auto",
                "allow_compile": sage_allow_compile,
            },
        }
        workflow["16"] = {
            "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
            "inputs": {"model": ["15", 0]},
        }
        model_source = ["16", 0]

    image_nodes = _image_nodes(workflow, references)
    group_inputs: dict[str, Any] = {
        "prompt": prompt,
        "duration_sec": duration_sec,
    }
    if is_reference_mode:
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
            "task_type": task_type,
            "global_prompt": "",
            "bd_grp_sample": "采样设置",
            "cfg": cfg,
            "seed": seed,
            "frame_rate": float(H3_FPS),
            "width": width,
            "height": height,
            "ref_max_size": ref_max_size,
            "total_frames": length,
            "timeline_data": "",
            group_link_key: [GROUP_NODE, 0],
            "bd_grp_advanced": "高级采样",
            "steps": steps,
            "sampler": sampler_name,
            "scheduler": "simple",
            "shift_video": shift_video,
            "shift_audio": shift_audio,
            "bd_grp_perf": "性能",
            "clear_vram_between_segments": True,
            "export_source_images": False,
        },
    }
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
            "filename_prefix": "video/ZLY_AI_VIDEO_STUDIO_DirectorAccel_MiniMax_H3",
            "format": "auto",
            "codec": "auto",
        },
    }
    return workflow
