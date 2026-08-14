from __future__ import annotations

from typing import Any

from .models import JobMode
from .workflow_registry import T8_WORKFLOWS, h3_length


OUTPUT_NODE = "14"


def build_minimax_h3_t8_workflow(
    mode: JobMode,
    prompt: str,
    references: list[str],
    options: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if mode not in T8_WORKFLOWS:
        raise ValueError(f"Unsupported MiniMax H3 T8 workflow: {mode}")

    workflow: dict[str, dict[str, Any]] = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": options["unet_name"], "weight_dtype": options["weight_dtype"]},
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

    lora_class = (
        "LoraLoaderModelOnly"
        if mode is JobMode.MINIMAX_H3_T8_ALL_REFERENCE
        else "LoraLoaderBypassModelOnly"
    )
    workflow["16"] = {
        "class_type": lora_class,
        "inputs": {
            "model": model_source,
            "lora_name": options["lora_name"],
            "strength_model": options["lora_strength"],
        },
    }

    if mode is JobMode.MINIMAX_H3_T8_ALL_REFERENCE:
        workflow["8"] = {
            "class_type": "MiniMaxH3MultiRateSamplerEXPT8",
            "inputs": {
                "model": ["16", 0],
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
                "model": ["16", 0],
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
    task_type = options["task_type"]
    if task_type == "auto":
        task_type = "Ref2VA" if references else "T2VA"
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
        conditioning_inputs[f"ref_images.ref_image_{index}"] = [node_id, 0]
    workflow["3"] = {"class_type": "MiniMaxH3AudioConditioningT8", "inputs": conditioning_inputs}
    return workflow
