from __future__ import annotations

from typing import Any

from .minimax_h3_workflow import AUDIO_VAE, TEXT_ENCODER, VIDEO_VAE, _image_nodes
from .models import JobMode
from .workflow_registry import (
    DUAL_ACCEL_WORKFLOWS,
    LIGHTX2V_FL2V_8STEP_LORA,
    h3_diffusion_unet,
    h3_dimensions,
    h3_length,
)


OUTPUT_NODE = "14"


def build_minimax_h3_dual_accel_workflow(
    mode: JobMode,
    prompt: str,
    references: list[str],
    options: dict[str, Any],
    seed: int,
) -> dict[str, dict[str, Any]]:
    if mode not in DUAL_ACCEL_WORKFLOWS:
        raise ValueError(f"Unsupported dual-accel workflow: {mode}")

    width, height = h3_dimensions(options)
    is_reference_mode = mode is JobMode.MINIMAX_H3_DUAL_ACCEL_R2V
    conditioning_class = "MiniMaxH3ReferenceToVideo" if is_reference_mode else "MiniMaxH3ImageToVideo"
    steps = int(options.get("steps", 8))
    lora_strength = float(options.get("lora_strength", 0))
    unet = h3_diffusion_unet(is_reference_mode, lora_strength)
    model_source: list[Any] = ["1", 0]
    sampler_name = str(options.get("sampler_name") or "res_multistep")
    shift_video = float(options.get("shift_video", 12))
    shift_audio = float(options.get("shift_audio", 3))
    use_sage = bool(options.get("use_sage_attention", True))

    workflow: dict[str, dict[str, Any]] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": sampler_name}},
        "10": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["8", 0],
                "guider": ["6", 0],
                "sampler": ["9", 0],
                "sigmas": ["7", 0],
                "latent_image": ["5", 1],
            },
        },
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["10", 0], "vae": ["4", 0]}},
        "13": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "audio": ["12", 0], "fps": 24.0, "bit_depth": 8}},
        OUTPUT_NODE: {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["13", 0],
                "filename_prefix": "video/ZLY_AI_VIDEO_STUDIO_DualAccel_MiniMax_H3",
                "format": "auto",
                "codec": "auto",
            },
        },
    }
    if lora_strength:
        workflow["15"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": model_source,
                "lora_name": options.get("lora_name", LIGHTX2V_FL2V_8STEP_LORA),
                "strength_model": lora_strength,
            },
        }
        model_source = ["15", 0]
    if use_sage:
        workflow["16"] = {
            "class_type": "PathchSageAttentionKJ",
            "inputs": {
                "model": model_source,
                "sage_attention": "auto",
                "allow_compile": False,
            },
        }
        workflow["17"] = {
            "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
            "inputs": {"model": ["16", 0]},
        }
        model_source = ["17", 0]
    workflow["18"] = {
        "class_type": "MiniMaxH3SigmaShift",
        "inputs": {"model": model_source, "shift_video": shift_video, "shift_audio": shift_audio},
    }
    model_source = ["18", 0]
    workflow["6"] = {"class_type": "BasicGuider", "inputs": {"model": model_source, "conditioning": ["5", 0]}}
    workflow["7"] = {
        "class_type": "BasicScheduler",
        "inputs": {"model": model_source, "scheduler": "simple", "steps": steps, "denoise": 1.0},
    }
    conditioning_inputs: dict[str, Any] = {
        "clip": ["2", 0],
        "vae": ["3", 0],
        "prompt": prompt,
        "width": width,
        "height": height,
        "length": h3_length(options),
    }
    if is_reference_mode:
        conditioning_inputs["audio_vae"] = ["4", 0]
        conditioning_inputs["ref_image_size"] = options.get("reference_image_size", "match")
        for index, image_node in enumerate(_image_nodes(workflow, references), start=0):
            conditioning_inputs[f"ref_images.ref_image_{index}"] = [image_node, 0]
    else:
        image_nodes = _image_nodes(workflow, references)
        if image_nodes:
            conditioning_inputs["first_frame"] = [image_nodes[0], 0]
        if len(image_nodes) > 1:
            conditioning_inputs["last_frame"] = [image_nodes[1], 0]
    workflow["5"] = {"class_type": conditioning_class, "inputs": conditioning_inputs}
    return workflow
