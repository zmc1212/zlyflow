from __future__ import annotations

from typing import Any

from .minimax_h3_workflow import AUDIO_VAE, VIDEO_VAE, _image_nodes
from .models import JobMode
from .workflow_registry import (
    ACTION_BASE_STEPS,
    ACTION_COMBAT_LORA,
    ACTION_FRAMERUSH_LORA,
    ACTION_MAX_FRAMES,
    ACTION_REF_RESIZE,
    ACTION_SAMPLER,
    ACTION_TURBO_LORA,
    ACTION_WORKFLOWS,
    H3_ACTION_CLIP,
    H3_FPS,
    H3_HYBRID_UNET,
    h3_dimensions,
    h3_length,
)


# 官方 H3 分支固定按节点 "14" 取 SaveVideo，打斗图必须沿用同一位号。
OUTPUT_NODE = "14"
CREATE_VIDEO_NODE = "13"
CONDITIONING_NODE = "40"
VIDEO_DECODE_NODE = "41"
AUDIO_DECODE_NODE = "42"
REFERENCE_RESIZE_BASE = 50


def build_minimax_h3_action_workflow(
    mode: JobMode,
    prompt: str,
    references: list[str],
    options: dict[str, Any],
    seed: int,
) -> dict[str, dict[str, Any]]:
    """作者打斗 V2 管线：三层 LoRA + 距离注意力 + 动态 CFG + Sigma 收敛。"""
    if mode not in ACTION_WORKFLOWS:
        raise ValueError(f"Unsupported action workflow: {mode}")

    width, height = h3_dimensions(options)
    # 导演台逐镜会把分镜时长直接写进 duration；距离注意力节点的 num_frames 上限 256，
    # 超出会整单被远端拒绝，这里按 10 秒（243 帧）封顶。
    length = min(h3_length(options), ACTION_MAX_FRAMES)
    is_reference_mode = mode is JobMode.MINIMAX_H3_ACTION_R2V
    steps = int(options.get("steps", ACTION_BASE_STEPS))
    extra_steps = int(options.get("extra_steps", 1))
    sampler_name = str(options.get("sampler_name") or ACTION_SAMPLER)
    shift_video = float(options.get("shift_video", 12))
    shift_audio = float(options.get("shift_audio", 3))
    refiner_start_at_sigma = float(options.get("refiner_start_at_sigma", 0.7))
    receptive_field_scale = float(options.get("receptive_field_scale", 2.0))
    temporal_weight = float(options.get("temporal_weight", 3.0))
    cfg_low = float(options.get("cfg_low", 0.9))
    cfg_high = float(options.get("cfg_high", 1.1))
    ref_resize_size = int(options.get("ref_resize_size", ACTION_REF_RESIZE))
    use_sage = bool(options.get("use_sage_attention", True))

    workflow: dict[str, dict[str, Any]] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": H3_HYBRID_UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": H3_ACTION_CLIP, "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        # 加速 → 运镜 → 打斗，顺序决定动作幅度；作者实测不可调换。
        "5": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": ACTION_TURBO_LORA, "strength_model": 1.0}},
        "6": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["5", 0], "lora_name": ACTION_FRAMERUSH_LORA, "strength_model": 1.0}},
        "7": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["6", 0], "lora_name": ACTION_COMBAT_LORA, "strength_model": 1.0}},
    }
    model_source: list[Any] = ["7", 0]
    if use_sage:
        workflow["8"] = {"class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch", "inputs": {"model": model_source}}
        model_source = ["8", 0]
    workflow["9"] = {
        "class_type": "MiniMaxH3SigmaShift",
        "inputs": {"model": model_source, "shift_video": shift_video, "shift_audio": shift_audio},
    }
    workflow["10"] = {
        "class_type": "H3DistanceAttentionPatcher",
        "inputs": {
            "model": ["9", 0],
            "receptive_field_scale": receptive_field_scale,
            "temporal_weight": temporal_weight,
            "start_at_sigma": 1.0,
            "end_at_sigma": 0.0,
            "num_frames": length,
            "original_width": width,
            "original_height": height,
        },
    }
    workflow["11"] = {
        "class_type": "H3DynamicCFGScheduler",
        "inputs": {
            "model": ["10", 0],
            "cfg_low": cfg_low,
            "cfg_high": cfg_high,
            "start_at_sigma": 1.0,
            "end_at_sigma": 0.0,
        },
    }

    conditioning_inputs: dict[str, Any] = {
        "clip": ["2", 0],
        "vae": ["3", 0],
        "prompt": prompt,
        "width": width,
        "height": height,
        "length": length,
    }
    image_nodes = _image_nodes(workflow, references)
    if is_reference_mode:
        conditioning_inputs["audio_vae"] = ["4", 0]
        conditioning_inputs["ref_image_size"] = str(options.get("reference_image_size") or "match")
        for index, image_node in enumerate(_resized_reference_nodes(workflow, image_nodes, ref_resize_size)):
            conditioning_inputs[f"ref_images.ref_image_{index}"] = [image_node, 0]
        conditioning_class = "MiniMaxH3ReferenceToVideo"
    else:
        if image_nodes:
            conditioning_inputs["first_frame"] = [image_nodes[0], 0]
        if len(image_nodes) > 1:
            conditioning_inputs["last_frame"] = [image_nodes[1], 0]
        conditioning_class = "MiniMaxH3ImageToVideo"
    workflow[CONDITIONING_NODE] = {"class_type": conditioning_class, "inputs": conditioning_inputs}

    workflow["15"] = {
        "class_type": "BasicScheduler",
        "inputs": {"model": ["11", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0},
    }
    workflow["16"] = {
        "class_type": "H3SigmaRefiner",
        "inputs": {
            "sigmas": ["15", 0],
            "extra_steps": extra_steps,
            "start_at_sigma": refiner_start_at_sigma,
            "end_at_sigma": 0.0,
            "spacing": "cosine",
        },
    }
    workflow["17"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": sampler_name}}
    workflow["18"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}}
    workflow["19"] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": ["18", 0],
            "guider": ["12", 0],
            "sampler": ["17", 0],
            "sigmas": ["16", 0],
            "latent_image": [CONDITIONING_NODE, 1],
        },
    }
    # BasicGuider 挂在动态 CFG 之后的模型上；cfg 交给调度器分段，这里保持 1.0。
    workflow["12"] = {
        "class_type": "BasicGuider",
        "inputs": {"model": ["11", 0], "conditioning": [CONDITIONING_NODE, 0], "cfg": 1.0},
    }
    workflow[VIDEO_DECODE_NODE] = {"class_type": "VAEDecode", "inputs": {"samples": ["19", 0], "vae": ["3", 0]}}
    workflow[AUDIO_DECODE_NODE] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["19", 0], "vae": ["4", 0]}}
    workflow[CREATE_VIDEO_NODE] = {
        "class_type": "CreateVideo",
        "inputs": {
            "images": [VIDEO_DECODE_NODE, 0],
            "audio": [AUDIO_DECODE_NODE, 0],
            "fps": H3_FPS,
            "bit_depth": 8,
        },
    }
    workflow[OUTPUT_NODE] = {
        "class_type": "SaveVideo",
        "inputs": {
            "video": [CREATE_VIDEO_NODE, 0],
            "filename_prefix": "video/ZLY_AI_VIDEO_STUDIO_Action_MiniMax_H3",
            "format": "auto",
            "codec": "auto",
        },
    }
    return workflow


def _resized_reference_nodes(
    workflow: dict[str, dict[str, Any]], image_nodes: list[str], size: int,
) -> list[str]:
    """作者图把每张参考图归一到同一像素尺寸，参考主体一致性依赖这一步。"""
    resized: list[str] = []
    for index, image_node in enumerate(image_nodes, start=REFERENCE_RESIZE_BASE):
        node_id = str(index)
        workflow[node_id] = {
            "class_type": "ImageResizeKJv2",
            "inputs": {
                "image": [image_node, 0],
                "width": size,
                "height": size,
                "upscale_method": "nearest-exact",
                "keep_proportion": "resize",
                "pad_color": "0, 0, 0",
                "crop_position": "center",
                "divisible_by": 32,
                "device": "cpu",
            },
        }
        resized.append(node_id)
    return resized
