"""MiniMax H3 口型同步（minimax-h3-lip-sync）API graph 生成。

把已有视频 + 新音频交给 H3 ref2va 管线：源视频帧作为 ref_videos 参考锁定身份与场景，
新音频经 AudioWindow 对齐后以 lock_source 驱动口型重新生成，实现"同画面换口播"。
链路与远端实测实验图一致：VHS_LoadVideo(源视频帧) + LoadAudio(目标音频) →
AudioWindowT8(17n+5 对齐) → AudioConditioningT8(auto→ref2va, lock_source) →
原生 res_multistep/simple 采样（ref2va INT8 + ref2v Turbo LoRA）→ AVDecode → OutputTrim → 24fps MP4。

references 顺序由 registry 约定：[0] 原视频（参考），[1] 目标音频（驱动口型）。
画布（width/height）与窗口时长（scene_duration_seconds）由提交侧探测源视频/音频后写入 options。
"""

from __future__ import annotations

from typing import Any

from .minimax_h3_workflow import OFFICIAL_RESERVED_VRAM_GB
from .workflow_registry import (
    H3_REF2VA_FULL,
    H3_REF2VA_PRUNED,
    LIGHTX2V_LORA_STRENGTH,
    LIGHTX2V_REF2V_4STEP_LORA,
    h3_turbo_lora_compatible,
)


CONDITIONING_NODE = "3"
OUTPUT_NODE = "14"


def lipsync_prompt(prompt: str) -> str:
    """补充口型同步场景描述；提示词不携带媒体标签（源媒体不进参考媒体表）。"""
    scene = prompt.strip() or "真实感人物面对镜头自然说话，画面稳定，光线柔和"
    return f"{scene}\n同一位人物在相同的场景中面对镜头自然说话，保持画面构图、服装与背景一致，口型与语音精确同步。"


def build_minimax_h3_lipsync_workflow(
    prompt: str,
    references: list[str],
    options: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if len(references) != 2:
        raise ValueError("口型同步需要原视频与目标音频各 1 份。")
    source_video, target_audio = references
    steps = int(options["steps"])
    use_turbo = bool(options.get("use_turbo", steps <= 4))
    lora_strength = float(options.get("lora_strength", LIGHTX2V_LORA_STRENGTH)) if use_turbo else 0.0
    unet_name = options.get("unet_name") or (H3_REF2VA_FULL if use_turbo else H3_REF2VA_PRUNED)
    if not h3_turbo_lora_compatible(unet_name):
        lora_strength = 0.0

    # 模型链：ReservedVRAM → SageAttention → 可选 ref2v Turbo LoRA。
    model_source: list[Any] = ["2", 0]
    if bool(options.get("use_sage_attention", True)):
        workflow_sage: dict[str, dict[str, Any]] = {
            "15": {
                "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
                "inputs": {"model": model_source},
            },
        }
        model_source = ["15", 0]
    else:
        workflow_sage = {}
    if lora_strength:
        workflow_sage["16"] = {
            "class_type": "LoraLoaderBypassModelOnly",
            "inputs": {"model": model_source, "lora_name": options.get("lora_name", LIGHTX2V_REF2V_4STEP_LORA), "strength_model": lora_strength},
        }
        model_source = ["16", 0]

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
        "2": {
            "class_type": "ReservedVRAMSetter",
            "inputs": {
                "anything": ["1", 0],
                "reserved": OFFICIAL_RESERVED_VRAM_GB,
                "mode": "manual",
                "seed": 0,
                "auto_max_reserved": 0,
                "clean_gpu_before": True,
            },
        },
        **workflow_sage,
        "20": {
            "class_type": "VHS_LoadVideo",
            "inputs": {
                "video": source_video,
                "force_rate": int(options["frame_rate"]),
                "custom_width": 0,
                "custom_height": 0,
                "frame_load_cap": 0,
                "skip_first_frames": 0,
                "select_every_nth": 1,
            },
        },
        "21": {"class_type": "LoadAudio", "inputs": {"audio": target_audio}},
        "22": {
            "class_type": "MiniMaxH3AudioWindowT8",
            "inputs": {
                "audio": ["21", 0],
                "scene_start_seconds": 0.0,
                "scene_duration_seconds": options["scene_duration_seconds"],
                "warmup_seconds": 0.0,
                "cooldown_seconds": 0.0,
                "ensure_minimum_context": True,
            },
        },
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": options["seed"]}},
        "18": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "19": {
            "class_type": "BasicScheduler",
            "inputs": {"model": model_source, "scheduler": "simple", "steps": steps, "denoise": 1.0},
        },
        "9": {"class_type": "BasicGuider", "inputs": {"model": model_source, "conditioning": [CONDITIONING_NODE, 0]}},
        "11": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["8", 0],
                "guider": ["9", 0],
                "sampler": ["18", 0],
                "sigmas": ["19", 0],
                "latent_image": [CONDITIONING_NODE, 1],
            },
        },
        "12": {
            "class_type": "MiniMaxH3AVDecodeT8",
            "inputs": {"av_latent": ["11", 0], "video_vae": ["5", 0], "audio_vae": ["6", 0]},
        },
        "13": {
            "class_type": "MiniMaxH3OutputTrimT8",
            "inputs": {
                "frames": ["12", 0],
                "audio": [CONDITIONING_NODE, 2],
                "fps": options["frame_rate"],
                "start_seconds": ["22", 2],
                "duration_seconds": ["22", 3],
            },
        },
        OUTPUT_NODE: {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["13", 0],
                "audio": ["13", 1],
                "frame_rate": options["frame_rate"],
                "loop_count": options["loop_count"],
                "filename_prefix": "MiniMaxH3/ZLY_AI_VIDEO_STUDIO_LIPSYNC",
                "format": options["output_format"],
                "pingpong": options["pingpong"],
                "save_output": True,
                "pix_fmt": options["pixel_format"],
                "crf": options["crf"],
                "save_metadata": options["save_metadata"],
                "trim_to_audio": options["trim_to_audio"],
            },
        },
        CONDITIONING_NODE: {
            "class_type": "MiniMaxH3AudioConditioningT8",
            "inputs": {
                "clip": ["4", 0],
                "video_vae": ["5", 0],
                "audio_vae": ["6", 0],
                "prompt": lipsync_prompt(prompt),
                "width": options["width"],
                "height": options["height"],
                "length": ["22", 1],
                # ref_videos 参考在、无关键帧 → auto 路由 ref2va；源音频不进参考媒体表。
                "task_type": "auto",
                "audio_mode": options["audio_mode"],
                "audio_denoise_strength": options["audio_denoise_strength"],
                "add_source_as_reference": False,
                "prompt_primary_audio_ordinal": 0,
                "strict_prompt_tags": options["strict_prompt_tags"],
                "ref_image_size": options["ref_image_size"],
                "reference_video_policy": options["reference_video_policy"],
                "ref_videos.ref_video_0": ["20", 0],
                "drive_audio": ["22", 0],
            },
        },
    }
    return workflow
