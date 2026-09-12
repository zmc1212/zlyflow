# -*- coding: utf-8 -*-
"""Wan2.1 VACE 深度控制镜头复刻的 ComfyUI API graph 构建器。

深度视频作为 control_video 锁定运镜与构图，提示词与参考图重塑画面内容。
- 有参考图（原片首帧/主体/风格）时使用 toonflow_vace_multi_reference 自定义节点；
- 无参考图时回退核心 WanVaceToVideo（reference_image 可选）。
两节点接口一致：positive/negative/vae/width/height/length/batch_size/strength，
输出 (positive, negative, latent, trim_latent)。
"""
from __future__ import annotations

from typing import Any

VACE_UNET_FILENAME = "wan2.1_vace_1.3B.safetensors"
VACE_CLIP_FILENAME = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VACE_VAE_FILENAME = "wan_2.1_vae.safetensors"
VACE_OUTPUT_NODE = "30"
VACE_FPS = 16
MAX_REFERENCE_IMAGES = 9

VACE_DEFAULT_NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
    "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，"
    "畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
)

_CONTROL_VIDEO_NODE = "7"
_REFERENCE_FIRST_ID = 8
_BATCH_FIRST_ID = 17
_CONDITIONING_NODE = "25"
_KSAMPLER_NODE = "26"


def snap_vace_length(frames: int) -> int:
    """Wan VACE 帧数约束 4n+1，最小 5 帧。"""
    value = max(1, int(frames))
    snapped = (value - 1) // 4 * 4 + 1
    return max(5, snapped)


def build_vace_depth_workflow(
    control_video_filename: str,
    references: list[str],
    prompt: str,
    *,
    negative_prompt: str = VACE_DEFAULT_NEGATIVE,
    width: int,
    height: int,
    length: int,
    vace_strength: float = 1.0,
    steps: int = 30,
    cfg: float = 5.0,
    shift: float = 16.0,
    sampler: str = "uni_pc",
    scheduler: str = "simple",
    seed: int,
    weight_dtype: str = "default",
) -> dict[str, dict[str, Any]]:
    """构建"深度视频 + 参考图 + 提示词 → 复刻镜头"工作流。

    control_video_filename / references 均为已上传到 ComfyUI input 的文件名；
    width/height 需 16 对齐；length 自动对齐 4n+1。
    """
    safe_width = max(16, int(width) // 16 * 16)
    safe_height = max(16, int(height) // 16 * 16)
    frame_length = snap_vace_length(length)
    safe_strength = max(0.0, min(1000.0, float(vace_strength)))
    images = [str(item) for item in references if str(item).strip()][:MAX_REFERENCE_IMAGES]

    workflow: dict[str, dict[str, Any]] = {
        "1": {
            "inputs": {"unet_name": VACE_UNET_FILENAME, "weight_dtype": weight_dtype},
            "class_type": "UNETLoader",
            "_meta": {"title": "加载 Wan VACE 模型"},
        },
        "2": {
            "inputs": {"model": ["1", 0], "shift": float(shift)},
            "class_type": "ModelSamplingSD3",
            "_meta": {"title": "Wan 采样配置"},
        },
        "3": {
            "inputs": {"clip_name": VACE_CLIP_FILENAME, "type": "wan", "device": "cpu"},
            "class_type": "CLIPLoader",
            "_meta": {"title": "加载 UMT5 文本编码器"},
        },
        "4": {
            "inputs": {"text": prompt.strip(), "clip": ["3", 0]},
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "正向提示词"},
        },
        "5": {
            "inputs": {"text": (negative_prompt or VACE_DEFAULT_NEGATIVE).strip(), "clip": ["3", 0]},
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "负向提示词"},
        },
        "6": {
            "inputs": {"vae_name": VACE_VAE_FILENAME},
            "class_type": "VAELoader",
            "_meta": {"title": "加载 Wan VAE"},
        },
        _CONTROL_VIDEO_NODE: {
            "inputs": {
                "video": control_video_filename,
                "force_rate": VACE_FPS,
                "custom_width": 0,
                "custom_height": 0,
                "frame_load_cap": frame_length,
                "skip_first_frames": 0,
                "select_every_nth": 1,
            },
            "class_type": "VHS_LoadVideo",
            "_meta": {"title": "读取深度控制视频"},
        },
    }

    reference_output: list[str] | None = None
    if images:
        load_ids = []
        for index, filename in enumerate(images):
            node_id = str(_REFERENCE_FIRST_ID + index)
            load_ids.append(node_id)
            workflow[node_id] = {
                "inputs": {"image": filename},
                "class_type": "LoadImage",
                "_meta": {"title": f"参考图 {index + 1}"},
            }
        reference_output = [load_ids[0], 0]
        if len(load_ids) > 1:
            batch_ids = []
            for index in range(len(load_ids) - 1):
                node_id = str(_BATCH_FIRST_ID + index)
                batch_ids.append(node_id)
            for index, node_id in enumerate(batch_ids):
                left = load_ids[0] if index == 0 else batch_ids[index - 1]
                workflow[node_id] = {
                    "inputs": {"image1": [left, 0], "image2": [load_ids[index + 1], 0]},
                    "class_type": "ImageBatch",
                    "_meta": {"title": f"合并参考图 {index + 2}"},
                }
            reference_output = [batch_ids[-1], 0]

        workflow[_CONDITIONING_NODE] = {
            "inputs": {
                "positive": ["4", 0],
                "negative": ["5", 0],
                "vae": ["6", 0],
                "width": safe_width,
                "height": safe_height,
                "length": frame_length,
                "batch_size": 1,
                "strength": safe_strength,
                "reference_images": reference_output,
                "control_video": [_CONTROL_VIDEO_NODE, 0],
            },
            "class_type": "WanVaceMultiReference",
            "_meta": {"title": "VACE 深度控制编码（多参考）"},
        }
    else:
        workflow[_CONDITIONING_NODE] = {
            "inputs": {
                "positive": ["4", 0],
                "negative": ["5", 0],
                "vae": ["6", 0],
                "width": safe_width,
                "height": safe_height,
                "length": frame_length,
                "batch_size": 1,
                "strength": safe_strength,
                "control_video": [_CONTROL_VIDEO_NODE, 0],
            },
            "class_type": "WanVaceToVideo",
            "_meta": {"title": "VACE 深度控制编码"},
        }

    workflow[_KSAMPLER_NODE] = {
        "inputs": {
            "model": ["2", 0],
            "seed": int(seed),
            "steps": max(1, int(steps)),
            "cfg": float(cfg),
            "sampler_name": sampler,
            "scheduler": scheduler,
            "positive": [_CONDITIONING_NODE, 0],
            "negative": [_CONDITIONING_NODE, 1],
            "latent_image": [_CONDITIONING_NODE, 2],
            "denoise": 1.0,
        },
        "class_type": "KSampler",
        "_meta": {"title": "VACE 采样"},
    }
    workflow["27"] = {
        "inputs": {"samples": [_KSAMPLER_NODE, 0], "trim_amount": [_CONDITIONING_NODE, 3]},
        "class_type": "TrimVideoLatent",
        "_meta": {"title": "移除参考帧"},
    }
    workflow["28"] = {
        "inputs": {"samples": ["27", 0], "vae": ["6", 0]},
        "class_type": "VAEDecode",
        "_meta": {"title": "解码视频帧"},
    }
    workflow["29"] = {
        "inputs": {"images": ["28", 0], "fps": VACE_FPS},
        "class_type": "CreateVideo",
        "_meta": {"title": "创建视频"},
    }
    workflow[VACE_OUTPUT_NODE] = {
        "inputs": {
            "video": ["29", 0],
            "filename_prefix": "video/zly_shot_replication",
            "format": "mp4",
            "codec": "h264",
        },
        "class_type": "SaveVideo",
        "_meta": {"title": "保存复刻视频"},
    }
    return workflow
