# -*- coding: utf-8 -*-
"""MiniMax H3 视频局部重绘的 ComfyUI API graph 构建器。

官方 Fun ControlNet Union 的 inpaint 路径:遮罩图(白色=重绘区)标记要重生的区域,
原片帧作为 mask 背后的保留内容注入条件,采样后把原片像素硬合成到遮罩之外,
音轨沿用原片——域外像素级保持,域内按提示词重生。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .director_export import find_ffmpeg

H3_UNET_FILENAME = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
H3_CLIP_FILENAME = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
H3_VIDEO_VAE_FILENAME = "minimax_h3_video_vae_int8_convrot.safetensors"
H3_AUDIO_VAE_FILENAME = "minimax_h3_audio_vae_fp32.safetensors"
FUN_CONTROLNET_PATCH_FILENAME = "minimax_h3_fun_controlnet_union_pruned_int8_convrot.safetensors"

INPAINT_OUTPUT_NODE = "28"
INPAINT_FPS = 24
INPAINT_LENGTHS = {"5s": 124, "10s": 243, "15s": 345}


def snap_h3_length(frames: int) -> int:
    """H3 视频 VAE 帧网格 17n+5,最小 29 帧。"""
    value = max(1, int(frames))
    n = max(1, round((value - 5) / 17))
    return max(29, 17 * n + 5)


def snap_h3_size(value: int) -> int:
    """画布边长 32 对齐(H3 官方模板约束)。"""
    return max(32, int(value) // 32 * 32)



def prepare_inpaint_source(source: Path, destination: Path, *, fps: int, length: int) -> Path:
    """截取原片前 length 帧并对齐帧率；保留音轨供成片沿用。"""
    ffmpeg = find_ffmpeg("ffmpeg")
    if not ffmpeg:
        raise ValueError("视频局部重绘需要 FFmpeg，请安装后再试。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    filters = f"fps={fps},scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
    try:
        subprocess.run(
            [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
             "-vf", filters, "-frames:v", str(length), "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(destination)],
            check=True, capture_output=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as error:
        destination.unlink(missing_ok=True)
        raise ValueError("原片预处理失败，请换用标准 MP4 文件后重试。") from error
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ValueError("原片预处理没有输出可读视频。")
    return destination


def build_h3_inpaint_workflow(
    mask_image_filename: str,
    source_video_filename: str,
    prompt: str,
    *,
    width: int,
    height: int,
    length: int,
    inpaint_strength: float = 1.0,
    steps: int = 20,
    seed: int,
    weight_dtype: str = "default",
    fps: int = INPAINT_FPS,
) -> dict[str, dict[str, Any]]:
    """构建"遮罩图 + 原片 → 局部重绘"工作流。

    mask_image_filename 为已上传的遮罩图（白色=重绘区）；source_video_filename 为
    已预处理的视频文件名；width/height 由原片尺寸 32 对齐得出；length 对齐 17n+5。
    """
    safe_width = snap_h3_size(width)
    safe_height = snap_h3_size(height)
    frame_length = snap_h3_length(length)
    safe_strength = max(0.1, min(1.0, float(inpaint_strength)))
    safe_steps = max(4, min(40, int(steps)))
    text = prompt.strip()

    workflow: dict[str, dict[str, Any]] = {
        "1": {
            "inputs": {"image": mask_image_filename},
            "class_type": "LoadImage",
            "_meta": {"title": "重绘遮罩图"},
        },
        "2": {
            "inputs": {"image": ["1", 0], "channel": "red"},
            "class_type": "ImageToMask",
            "_meta": {"title": "遮罩图转蒙版(白色=重绘)"},
        },
        "3": {
            "inputs": {"file": source_video_filename},
            "class_type": "LoadVideo",
            "_meta": {"title": "原片视频"},
        },
        "4": {
            "inputs": {"video": ["3", 0]},
            "class_type": "GetVideoComponents",
            "_meta": {"title": "拆原片帧与音轨"},
        },
        "10": {
            "inputs": {"unet_name": H3_UNET_FILENAME, "weight_dtype": weight_dtype},
            "class_type": "UNETLoader",
            "_meta": {"title": "加载 H3 Ref2VA 模型"},
        },
        "11": {
            "inputs": {"clip_name": H3_CLIP_FILENAME, "type": "minimax", "device": "default"},
            "class_type": "CLIPLoader",
            "_meta": {"title": "加载 Qwen3-VL 文本编码器"},
        },
        "12": {
            "inputs": {
                "clip": ["11", 0],
                "vae": ["14", 0],
                "audio_vae": ["15", 0],
                "prompt": text,
                "width": safe_width,
                "height": safe_height,
                "length": frame_length,
                "ref_image_size": "match",
            },
            "class_type": "MiniMaxH3ReferenceToVideo",
            "_meta": {"title": "H3 参考生成"},
        },
        "13": {
            "inputs": {"name": FUN_CONTROLNET_PATCH_FILENAME},
            "class_type": "ModelPatchLoader",
            "_meta": {"title": "加载 Fun ControlNet Union"},
        },
        "14": {
            "inputs": {"vae_name": H3_VIDEO_VAE_FILENAME},
            "class_type": "VAELoader",
            "_meta": {"title": "加载 H3 视频 VAE"},
        },
        "15": {
            "inputs": {"vae_name": H3_AUDIO_VAE_FILENAME},
            "class_type": "VAELoader",
            "_meta": {"title": "加载 H3 音频 VAE"},
        },
        "16": {
            "inputs": {
                "model": ["10", 0],
                "model_patch": ["13", 0],
                "vae": ["14", 0],
                "strength": safe_strength,
                "start_percent": 0.0,
                "end_percent": 1.0,
                "mask": ["2", 0],
                "source_video": ["4", 0],
            },
            "class_type": "MiniMaxH3FunControlNetApply",
            "_meta": {"title": "遮罩局部重绘"},
        },
        "17": {
            "inputs": {"noise_seed": int(seed)},
            "class_type": "RandomNoise",
            "_meta": {"title": "噪声"},
        },
        "18": {
            "inputs": {"sampler_name": "res_multistep"},
            "class_type": "KSamplerSelect",
            "_meta": {"title": "采样器"},
        },
        "19": {
            "inputs": {"model": ["16", 0], "scheduler": "simple", "steps": safe_steps, "denoise": 1.0},
            "class_type": "BasicScheduler",
            "_meta": {"title": "调度"},
        },
        "20": {
            "inputs": {"model": ["16", 0], "conditioning": ["12", 0]},
            "class_type": "BasicGuider",
            "_meta": {"title": "引导"},
        },
        "21": {
            "inputs": {
                "noise": ["17", 0],
                "guider": ["20", 0],
                "sampler": ["18", 0],
                "sigmas": ["19", 0],
                "latent_image": ["12", 1],
            },
            "class_type": "SamplerCustomAdvanced",
            "_meta": {"title": "采样"},
        },
        "22": {
            "inputs": {"samples": ["21", 0], "vae": ["14", 0]},
            "class_type": "VAEDecode",
            "_meta": {"title": "解码重绘帧"},
        },
        "25": {
            "inputs": {
                "image": ["4", 0],
                "width": safe_width,
                "height": safe_height,
                "upscale_method": "lanczos",
                "crop": "disabled",
            },
            "class_type": "ImageScale",
            "_meta": {"title": "原片帧对齐画布"},
        },
        "26": {
            "inputs": {"mask": ["2", 0]},
            "class_type": "InvertMask",
            "_meta": {"title": "反转遮罩(保留区)"},
        },
        "27": {
            "inputs": {
                "destination": ["22", 0],
                "source": ["25", 0],
                "x": 0,
                "y": 0,
                "resize_source": False,
                "mask": ["26", 0],
            },
            "class_type": "ImageCompositeMasked",
            "_meta": {"title": "域外贴回原片像素"},
        },
        "24": {
            "inputs": {
                "images": ["27", 0],
                "fps": int(fps),
                "audio": ["4", 1],
                "bit_depth": "auto",
                "color_space": "sRGB",
            },
            "class_type": "CreateVideo",
            "_meta": {"title": "合成视频(沿用原声)"},
        },
        "28": {
            "inputs": {
                "video": ["24", 0],
                "filename_prefix": "video/h3_inpaint",
                "format": "auto",
            },
            "class_type": "SaveVideo",
            "_meta": {"title": "保存成片"},
        },
    }
    return workflow
