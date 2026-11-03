# -*- coding: utf-8 -*-
"""MiniMax H3 深度捕捉(即梦同款能力)的 ComfyUI API graph 构建器。

Depth Anything 3 从原片提取时序稳定深度图 → MiniMaxH3FunControlNetApply 以深度
序列锁定运镜与空间结构，提示词重塑画面内容与风格，H3 原生音画一体出片。
深度视频作为独立产物回显，便于排障与复用(对接 Wan VACE 深度复刻)。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .video_analysis import VideoAnalysisError, probe_video

H3_UNET_FILENAME = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
H3_CLIP_FILENAME = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
H3_VIDEO_VAE_FILENAME = "minimax_h3_video_vae_int8_convrot.safetensors"
H3_AUDIO_VAE_FILENAME = "minimax_h3_audio_vae_fp32.safetensors"
FUN_CONTROLNET_PATCH_FILENAME = "minimax_h3_fun_controlnet_union_pruned_int8_convrot.safetensors"
DA3_MODEL_FILENAME = "depth_anything_3_mono_large.safetensors"

DEPTH_OUTPUT_NODE = "28"
DEPTH_PREVIEW_NODE = "7"
DEPTH_FPS = 24
DEPTH_LENGTHS = {"5s": 124, "10s": 243, "15s": 345}
DEFAULT_DEPTH_RESOLUTION = 504

DEPTH_DEFAULT_PROMPT = (
    "重塑这段镜头:空间结构、运镜轨迹与主体位置与原片完全一致,主体与场景风格按描述"
    "重新演绎,光影自然,画面细节丰富,电影质感,音画同步。"
)


def snap_h3_length(frames: int) -> int:
    """H3 视频 VAE 帧网格 17n+5,最小 29 帧。"""
    value = max(1, int(frames))
    n = max(1, round((value - 5) / 17))
    return max(29, 17 * n + 5)


def snap_h3_size(value: int) -> int:
    """画布边长 32 对齐(H3 官方模板约束)。"""
    return max(32, int(value) // 32 * 32)


def validate_depth_source(path: Path, duration: str) -> None:
    """原片必须能解码且时长足够覆盖所选生成时长。"""
    try:
        probe = probe_video(path)
    except (VideoAnalysisError, OSError, ValueError) as error:
        raise ValueError("原片视频无法读取，请使用包含视频画面的 MP4 / MOV / WebM 文件。") from error
    required = float(duration.removesuffix("s"))
    if probe.duration + 0.1 < required:
        raise ValueError(
            f"原片只有 {probe.duration:.1f} 秒，不足 {required:.0f} 秒的深度捕捉时长；"
            "请选择更短的生成时长或上传更长的视频。"
        )


def prepare_depth_source(source: Path, destination: Path, *, fps: int, length: int) -> Path:
    """截取原片前 length 帧并对齐帧率，供深度推理与 H3 采样使用同一份帧序列。"""
    # 延迟导入避免 director_export → workflow_registry 的模块环。
    from .director_export import find_ffmpeg

    ffmpeg = find_ffmpeg("ffmpeg")
    if not ffmpeg:
        raise ValueError("深度捕捉需要 FFmpeg，请安装后再试。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    filters = f"fps={fps},scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
    try:
        subprocess.run(
            [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
             "-vf", filters, "-frames:v", str(length), "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
             "-an", "-movflags", "+faststart", str(destination)],
            check=True, capture_output=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as error:
        destination.unlink(missing_ok=True)
        raise ValueError("原片预处理失败，请换用标准 MP4 文件后重试。") from error
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ValueError("原片预处理没有输出可读视频。")
    return destination


def build_h3_depth_workflow(
    source_video_filename: str,
    prompt: str,
    *,
    width: int,
    height: int,
    length: int,
    control_strength: float = 1.0,
    steps: int = 20,
    seed: int,
    weight_dtype: str = "default",
    fps: int = DEPTH_FPS,
    da3_resolution: int = DEFAULT_DEPTH_RESOLUTION,
) -> dict[str, dict[str, Any]]:
    """构建"原片 → 深度捕捉 → 深度控制重塑"工作流。

    source_video_filename 为已上传到 ComfyUI input 的文件名；width/height 由原片
    尺寸 32 对齐得出；length 自动对齐 17n+5 网格。
    """
    safe_width = snap_h3_size(width)
    safe_height = snap_h3_size(height)
    frame_length = snap_h3_length(length)
    safe_strength = max(0.1, min(1.0, float(control_strength)))
    safe_steps = max(4, min(40, int(steps)))
    safe_resolution = min(2520, max(140, int(da3_resolution) // 14 * 14))
    text = prompt.strip() or DEPTH_DEFAULT_PROMPT

    workflow: dict[str, dict[str, Any]] = {
        "2": {
            "inputs": {"file": source_video_filename},
            "class_type": "LoadVideo",
            "_meta": {"title": "原片视频"},
        },
        "3": {
            "inputs": {"video": ["2", 0]},
            "class_type": "GetVideoComponents",
            "_meta": {"title": "拆原片帧"},
        },
        "4": {
            "inputs": {"model_name": DA3_MODEL_FILENAME, "weight_dtype": "default"},
            "class_type": "LoadDA3Model",
            "_meta": {"title": "加载 Depth Anything 3"},
        },
        "5": {
            "inputs": {
                "da3_model": ["4", 0],
                "image": ["3", 0],
                "resolution": safe_resolution,
                "resize_method": "lower_bound_resize",
                "mode": "mono",
            },
            "class_type": "DA3Inference",
            "_meta": {"title": "深度推理"},
        },
        "6": {
            "inputs": {
                "da3_geometry": ["5", 0],
                "output": "depth",
                "output.normalization": "v2_style",
                "output.apply_sky_clip": False,
            },
            "class_type": "DA3Render",
            "_meta": {"title": "渲染深度图"},
        },
        DEPTH_PREVIEW_NODE: {
            "inputs": {
                "images": ["6", 0],
                "frame_rate": int(fps),
                "loop_count": 0,
                "filename_prefix": "video/h3_depth_capture_depth",
                "format": "video/h264-mp4",
                "pix_fmt": "yuv420p",
                "crf": 20,
                "save_metadata": True,
                "save_output": True,
                "pingpong": False,
            },
            "class_type": "VHS_VideoCombine",
            "_meta": {"title": "保存深度预览"},
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
                "control_video": ["6", 0],
            },
            "class_type": "MiniMaxH3FunControlNetApply",
            "_meta": {"title": "深度控制结构与运镜"},
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
            "_meta": {"title": "解码视频帧"},
        },
        "23": {
            "inputs": {"samples": ["21", 0], "vae": ["15", 0]},
            "class_type": "VAEDecodeAudio",
            "_meta": {"title": "解码音频"},
        },
        "24": {
            "inputs": {
                "images": ["22", 0],
                "fps": int(fps),
                "audio": ["23", 0],
                "bit_depth": "auto",
                "color_space": "sRGB",
            },
            "class_type": "CreateVideo",
            "_meta": {"title": "合成的视频"},
        },
        DEPTH_OUTPUT_NODE: {
            "inputs": {
                "video": ["24", 0],
                "filename_prefix": "video/h3_depth_capture",
                "format": "auto",
            },
            "class_type": "SaveVideo",
            "_meta": {"title": "保存成片"},
        },
    }
    return workflow
