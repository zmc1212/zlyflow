from __future__ import annotations

from typing import Any

from .models import JobMode
from .workflow_registry import (
    H3_TURBO_LORA_NAME,
    h3_diffusion_unet,
    h3_dimensions,
    h3_length,
    h3_lora_loader_class,
    h3_turbo_lora_compatible,
)


VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
TEXT_ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"


def build_minimax_h3_workflow(
    mode: JobMode,
    prompt: str,
    references: list[str],
    options: dict[str, Any],
    seed: int,
) -> dict[str, dict[str, Any]]:
    width, height = h3_dimensions(options)
    is_reference_mode = mode is JobMode.MINIMAX_H3_R2V
    conditioning_class = "MiniMaxH3ReferenceToVideo" if is_reference_mode else "MiniMaxH3ImageToVideo"
    steps = int(options.get("steps", 20))
    lora_strength = float(options.get("lora_strength", 0))
    unet = h3_diffusion_unet(is_reference_mode, lora_strength)
    if not h3_turbo_lora_compatible(unet):
        lora_strength = 0.0
    model_source: list[Any] = ["1", 0]

    workflow: dict[str, dict[str, Any]] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["8", 0], "guider": ["6", 0], "sampler": ["9", 0], "sigmas": ["7", 0], "latent_image": ["5", 1]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["10", 0], "vae": ["4", 0]}},
        "13": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "audio": ["12", 0], "fps": 24.0, "bit_depth": 8}},
        "14": {"class_type": "SaveVideo", "inputs": {"video": ["13", 0], "filename_prefix": "video/ZLY_AI_VIDEO_STUDIO_MiniMax_H3", "format": "auto", "codec": "auto"}},
    }
    if lora_strength:
        workflow["15"] = {
            "class_type": h3_lora_loader_class(unet),
            "inputs": {
                "model": model_source,
                "lora_name": options.get("lora_name", H3_TURBO_LORA_NAME),
                "strength_model": lora_strength,
            },
        }
        model_source = ["15", 0]
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


def _image_nodes(workflow: dict[str, dict[str, Any]], references: list[str]) -> list[str]:
    node_ids: list[str] = []
    for index, filename in enumerate(references, start=20):
        node_id = str(index)
        workflow[node_id] = {"class_type": "LoadImage", "inputs": {"image": filename}}
        node_ids.append(node_id)
    return node_ids
