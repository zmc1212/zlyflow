"""MiniMax H3 数字人口播（minimax-h3-avatar）API graph 生成。

链路复刻 comfyui-minimax-h3-audio-T8 的 audio_lock 示例：口播音频 → AudioWindow 对齐
17n+5 渲染窗口 → AudioConditioningT8(I2VA + lock_source) 锁定口型 → H3 Turbo 双时钟
采样 → AV 联合解码 → OutputTrim 裁回精确口播时长 → 24fps MP4。

references 顺序由 registry 约定：[0] 人物形象图（first_frame），[1] 口播音频（drive_audio）。
"""

from __future__ import annotations

from typing import Any

from .minimax_h3_workflow import OFFICIAL_RESERVED_VRAM_GB
from .workflow_registry import (
    h3_diffusion_unet,
    h3_lora_loader_class,
    h3_turbo_lora_compatible,
)


CONDITIONING_NODE = "3"
OUTPUT_NODE = "14"
# 16GB cards OOM in SamplerCustomAdvanced unless ComfyUI keeps headroom and
# unloads CLIP/VAE before the INT8 QKV projection (~2.5 GiB extra).


def avatar_prompt(prompt: str) -> str:
    """补充说话场景描述。

    注意：当前构建 `add_source_as_reference=False`（Hybrid 被禁用），源音频只进入
    AV latent、不进参考媒体表，因此提示词不能携带 `<Audio n>` 标签（strict 校验会
    因 available audio count is 0 失败）；口型同步由 latent 锁定的源音频驱动。
    """
    text = prompt.strip()
    return f"{text}\n人物正对镜头自然说话，口型与语音精确同步，头部与肢体动作自然。"


def build_minimax_h3_avatar_workflow(
    prompt: str,
    references: list[str],
    options: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if len(references) != 2:
        raise ValueError("数字人口播需要人物形象图与口播音频各 1 份。")
    portrait, speech_audio = references
    lora_strength = float(options["lora_strength"])
    unet_name = h3_diffusion_unet(False, lora_strength)
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
        "20": {"class_type": "LoadImage", "inputs": {"image": portrait}},
        "21": {"class_type": "LoadAudio", "inputs": {"audio": speech_audio}},
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
        "11": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["8", 0],
                "guider": ["9", 0],
                "sampler": ["9", 1],
                "sigmas": ["9", 2],
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
                "filename_prefix": "MiniMaxH3/ZLY_AI_VIDEO_STUDIO_AVATAR",
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
    workflow["2"] = {
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
    model_source = ["2", 0]
    if bool(options.get("use_sage_attention", True)):
        workflow["15"] = {
            "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
            "inputs": {"model": model_source},
        }
        model_source = ["15", 0]
    if lora_strength:
        workflow["16"] = {
            "class_type": h3_lora_loader_class(unet_name),
            "inputs": {
                "model": model_source,
                "lora_name": options["lora_name"],
                "strength_model": lora_strength,
            },
        }
        model_source = ["16", 0]
    # 0.43 核心已原生接管 H3 双时钟音频承载（model_sampling.audio_scale），T8 包的
    # DualClockSamplerT8 仍在替换 model_sampling，会触发
    # "'MiniMaxH3FlowSampling' object has no attribute 'audio_scale'"。改用与
    # lightx2v/dual-accel 工作流相同的生产采样路径（res_multistep + simple）。
    workflow["18"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}}
    workflow["19"] = {
        "class_type": "BasicScheduler",
        "inputs": {
            "model": model_source,
            "scheduler": "simple",
            "steps": int(options["steps"]),
            "denoise": 1.0,
        },
    }
    workflow["9"] = {
        "class_type": "BasicGuider",
        "inputs": {"model": model_source, "conditioning": [CONDITIONING_NODE, 0]},
    }
    workflow["11"]["inputs"]["sampler"] = ["18", 0]
    workflow["11"]["inputs"]["sigmas"] = ["19", 0]

    workflow[CONDITIONING_NODE] = {
        "class_type": "MiniMaxH3AudioConditioningT8",
        "inputs": {
            "clip": ["4", 0],
            "video_vae": ["5", 0],
            "audio_vae": ["6", 0],
            "prompt": avatar_prompt(prompt),
            "width": ["7", 0],
            "height": ["7", 1],
            "length": ["22", 1],
            # I2VA 契约不允许携带参考媒体（add_source_as_reference 会把源音频挂进参考），
            # 与 audio_lock 示例一致使用 auto，由 T8 节点按 first_frame + drive_audio 自行路由。
            "task_type": "auto",
            "audio_mode": options["audio_mode"],
            "audio_denoise_strength": options["audio_denoise_strength"],
            "add_source_as_reference": options["add_source_as_reference"],
            "prompt_primary_audio_ordinal": options["prompt_primary_audio_ordinal"],
            "strict_prompt_tags": options["strict_prompt_tags"],
            "ref_image_size": options["ref_image_size"],
            "reference_video_policy": options["reference_video_policy"],
            "first_frame": ["20", 0],
            "drive_audio": ["22", 0],
        },
    }
    return workflow
