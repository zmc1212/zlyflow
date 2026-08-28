from __future__ import annotations

from typing import Any

from .models import JobMode
from .workflow_registry import (
    T8_WORKFLOWS,
    h3_diffusion_unet,
    h3_length,
    h3_lora_loader_class,
    h3_turbo_lora_compatible,
)


OUTPUT_NODE = "14"


def resolve_t8_task_type(mode: JobMode, options: dict[str, Any], references: list[str]) -> str:
    """Always return a Combo value the T8 conditioning node accepts."""
    requested = str(options.get("task_type") or "auto").strip() or "auto"
    if requested != "auto":
        return requested
    if not references:
        return "T2VA"
    # Dual-clock is the turbo FL2VA path and only accepts 0–1 images. Official
    # T8 dual-clock graphs wire a single image as first_frame / I2VA. Sending
    # that image through Ref2VA autogrow both skips the first-frame contract
    # and can leave `task_type` unset on the dual-clock branch.
    if mode is JobMode.MINIMAX_H3_T8_DUAL_CLOCK:
        return "I2VA"
    return "Ref2VA"


def build_minimax_h3_t8_workflow(
    mode: JobMode,
    prompt: str,
    references: list[str],
    options: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if mode not in T8_WORKFLOWS:
        raise ValueError(f"Unsupported MiniMax H3 T8 workflow: {mode}")

    task_type = resolve_t8_task_type(mode, options, references)
    lora_strength = float(options["lora_strength"])
    unet_name = h3_diffusion_unet(task_type == "Ref2VA", lora_strength)
    if not h3_turbo_lora_compatible(unet_name):
        lora_strength = 0.0
    workflow: dict[str, dict[str, Any]] = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": unet_name, "weight_dtype": options["weight_dtype"]},
        },
        "4": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": options["clip_name"], "type": "minimax", "device": options["clip_device"]},
        },
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": options["video_vae"]}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": options["audio_vae"]}},
        "7": {
            "class_type": "ResolutionSelector",
            "inputs": {
                "aspect_ratio": options["aspect_ratio"],
                "megapixels": options["megapixels"],
                "multiple": options["multiple"],
            },
        },
        "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": options["seed"]}},
        "11": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["10", 0],
                "guider": ["9", 0],
                "sampler": ["8", 1],
                "sigmas": ["8", 2],
                "latent_image": ["3", 1],
            },
        },
        "12": {
            "class_type": "MiniMaxH3AVDecodeT8",
            "inputs": {"av_latent": ["11", 0], "video_vae": ["5", 0], "audio_vae": ["6", 0]},
        },
        OUTPUT_NODE: {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["12", 0],
                "audio": ["12", 1],
                "frame_rate": options["frame_rate"],
                "loop_count": options["loop_count"],
                "filename_prefix": "MiniMaxH3/ZLY_AI_VIDEO_STUDIO_T8",
                "format": options["output_format"],
                "pingpong": options["pingpong"],
                "save_output": True,
                "pix_fmt": options["pixel_format"],
                "crf": options["crf"],
                "save_metadata": options["save_metadata"],
                "trim_to_audio": options["trim_to_audio"],
            },
        },
    }

    model_source: list[Any] = ["1", 0]
    if mode is JobMode.MINIMAX_H3_T8_ALL_REFERENCE:
        workflow["2"] = {
            "class_type": "ReservedVRAMSetter",
            "inputs": {
                "anything": model_source,
                "reserved": options["reserved_vram"],
                "mode": options["reserved_vram_mode"],
                "seed": options["reserved_vram_seed"],
                "auto_max_reserved": options["auto_max_reserved_vram"],
                "clean_gpu_before": options["clean_gpu_before"],
            },
        }
        model_source = ["2", 0]

    if options["use_sage_attention"]:
        workflow["15"] = {
            "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
            "inputs": {"model": model_source},
        }
        model_source = ["15", 0]

    sampler_model = model_source
    if lora_strength:
        workflow["16"] = {
            "class_type": h3_lora_loader_class(unet_name),
            "inputs": {
                "model": model_source,
                "lora_name": options["lora_name"],
                "strength_model": lora_strength,
            },
        }
        sampler_model = ["16", 0]

    if mode is JobMode.MINIMAX_H3_T8_ALL_REFERENCE:
        workflow["8"] = {
            "class_type": "MiniMaxH3MultiRateSamplerEXPT8",
            "inputs": {
                "model": sampler_model,
                "av_latent": ["3", 1],
                "video_steps": options["video_steps"],
                "audio_steps": options["audio_steps"],
                "shift_video": options["shift_video"],
                "shift_audio": options["shift_audio"],
            },
        }
    else:
        workflow["8"] = {
            "class_type": "MiniMaxH3DualClockSamplerT8",
            "inputs": {
                "model": sampler_model,
                "av_latent": ["3", 1],
                "steps": options["steps"],
                "shift_video": options["shift_video"],
                "shift_audio": options["shift_audio"],
            },
        }

    workflow["9"] = {
        "class_type": "BasicGuider",
        "inputs": {"model": ["8", 0], "conditioning": ["3", 0]},
    }
    conditioning_inputs: dict[str, Any] = {
        "clip": ["4", 0],
        "video_vae": ["5", 0],
        "audio_vae": ["6", 0],
        "prompt": prompt,
        "width": ["7", 0],
        "height": ["7", 1],
        "length": h3_length(options),
        "task_type": task_type,
        "audio_mode": options["audio_mode"],
        "audio_denoise_strength": options["audio_denoise_strength"],
        "add_source_as_reference": options["add_source_as_reference"],
        "prompt_primary_audio_ordinal": options["prompt_primary_audio_ordinal"],
        "strict_prompt_tags": options["strict_prompt_tags"],
        "ref_image_size": options["ref_image_size"],
        "reference_video_policy": options["reference_video_policy"],
    }
    for index, filename in enumerate(references):
        node_id = str(20 + index)
        workflow[node_id] = {"class_type": "LoadImage", "inputs": {"image": filename}}
        if task_type == "I2VA" and index == 0:
            conditioning_inputs["first_frame"] = [node_id, 0]
        elif task_type == "L2VA" and index == 0:
            conditioning_inputs["last_frame"] = [node_id, 0]
        elif task_type == "FL2VA" and index == 0:
            conditioning_inputs["first_frame"] = [node_id, 0]
        elif task_type == "FL2VA" and index == 1:
            conditioning_inputs["last_frame"] = [node_id, 0]
        else:
            conditioning_inputs[f"ref_images.ref_image_{index}"] = [node_id, 0]
    workflow["3"] = {"class_type": "MiniMaxH3AudioConditioningT8", "inputs": conditioning_inputs}
    return workflow
