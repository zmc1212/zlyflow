# -*- coding: utf-8 -*-
"""MiniMax H3 动作迁移的 ComfyUI API graph 构建器。

官方 Fun ControlNet Union 姿势迁移管线:
SDPose 从动作参考视频抽取全身骨架 → MiniMaxH3FunControlNetApply 以骨架序列锁定
动作节奏,角色形象参考图经 MiniMaxH3ReferenceToVideo 的 ref_images 锁定人物身份,
H3 原生音画一体出片。画面内容跟随提示词,不依赖 Wan/VACE 权重,纯本地免费。
"""
from __future__ import annotations

from typing import Any

H3_UNET_FILENAME = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
H3_CLIP_FILENAME = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
H3_VIDEO_VAE_FILENAME = "minimax_h3_video_vae_int8_convrot.safetensors"
H3_AUDIO_VAE_FILENAME = "minimax_h3_audio_vae_fp32.safetensors"
FUN_CONTROLNET_PATCH_FILENAME = "minimax_h3_fun_controlnet_union_pruned_int8_convrot.safetensors"
SDPOSE_CHECKPOINT_FILENAME = "sdpose_wholebody_fp16.safetensors"
RTDETR_UNET_FILENAME = "rt_detr_v4-x-hgnet_fp16.safetensors"

MOTION_TRANSFER_OUTPUT_NODE = "28"
MOTION_TRANSFER_FPS = 24

# 官方模板默认尺寸:横版 16:9 @ 0.4 MP(32 对齐);帧网格 17n+5(5 秒 = 124 帧)。
MOTION_TRANSFER_SIZES = {"16:9": (864, 480), "9:16": (480, 864), "1:1": (640, 640)}
MOTION_TRANSFER_LENGTHS = {"5s": 124, "10s": 243, "15s": 362}

MOTION_TRANSFER_DEFAULT_PROMPT = (
    "参考图中的角色在画面中完整复刻动作参考视频里的舞蹈动作:动作幅度、节奏与肢体"
    "轨迹与参考视频保持一致,角色形象与服装严格跟随角色参考图,全身可见,运镜稳定,"
    "电影感打光,音画同步。"
)


def snap_h3_length(frames: int) -> int:
    """H3 视频 VAE 帧网格 17n+5,最小 29 帧(约 1.2 秒)。"""
    value = max(1, int(frames))
    n = max(1, round((value - 5) / 17))
    return max(29, 17 * n + 5)


def snap_h3_size(value: int) -> int:
    """画布边长 32 对齐(H3 官方模板约束)。"""
    return max(32, int(value) // 32 * 32)


def resolve_motion_transfer_dimensions(aspect_ratio: str, duration: str) -> tuple[int, int, int]:
    """把 primary 的画面比例与生成时长选项映射为 (width, height, length)。"""
    width, height = MOTION_TRANSFER_SIZES.get(str(aspect_ratio), MOTION_TRANSFER_SIZES["16:9"])
    length = MOTION_TRANSFER_LENGTHS.get(str(duration), MOTION_TRANSFER_LENGTHS["5s"])
    return snap_h3_size(width), snap_h3_size(height), snap_h3_length(length)


def build_h3_motion_transfer_workflow(
    character_image_filename: str,
    motion_video_filename: str,
    prompt: str,
    *,
    width: int,
    height: int,
    length: int,
    control_strength: float = 1.0,
    steps: int = 20,
    seed: int,
    weight_dtype: str = "default",
    fps: int = MOTION_TRANSFER_FPS,
) -> dict[str, dict[str, Any]]:
    """构建"角色形象图 + 动作参考视频 → 动作迁移"工作流。

    character_image_filename / motion_video_filename 均为已上传到 ComfyUI input 的
    文件名;width/height 需 32 对齐,length 自动对齐 17n+5 网格。
    """
    safe_width = snap_h3_size(width)
    safe_height = snap_h3_size(height)
    frame_length = snap_h3_length(length)
    safe_strength = max(0.1, min(1.0, float(control_strength)))
    safe_steps = max(4, min(40, int(steps)))
    text = prompt.strip() or MOTION_TRANSFER_DEFAULT_PROMPT

    workflow: dict[str, dict[str, Any]] = {
        "1": {
            "inputs": {"image": character_image_filename},
            "class_type": "LoadImage",
            "_meta": {"title": "角色形象参考图"},
        },
        "2": {
            "inputs": {"file": motion_video_filename},
            "class_type": "LoadVideo",
            "_meta": {"title": "动作参考视频"},
        },
        "3": {
            "inputs": {"video": ["2", 0]},
            "class_type": "GetVideoComponents",
            "_meta": {"title": "拆帧"},
        },
        "4": {
            "inputs": {"ckpt_name": SDPOSE_CHECKPOINT_FILENAME},
            "class_type": "CheckpointLoaderSimple",
            "_meta": {"title": "SDPose 骨架模型"},
        },
        "5": {
            "inputs": {"unet_name": RTDETR_UNET_FILENAME, "weight_dtype": "default"},
            "class_type": "UNETLoader",
            "_meta": {"title": "RT-DETR 人像检测"},
        },
        "6": {
            "inputs": {
                "model": ["5", 0],
                "image": ["3", 0],
                "threshold": 0.5,
                "class_name": "person",
                "max_detections": 2,
            },
            "class_type": "RTDETR_detect",
            "_meta": {"title": "检测动作主体"},
        },
        "7": {
            "inputs": {
                "model": ["4", 0],
                "vae": ["4", 2],
                "image": ["3", 0],
                "bboxes": ["6", 0],
                "batch_size": 16,
            },
            "class_type": "SDPoseKeypointExtractor",
            "_meta": {"title": "抽取全身骨架序列"},
        },
        "8": {
            "inputs": {
                "keypoints": ["7", 0],
                "draw_body": True,
                "draw_hands": True,
                "draw_face": True,
                "draw_feet": True,
                "stick_width": 4,
                "face_point_size": 2,
                "score_threshold": 0.51,
                "draw_head": True,
            },
            "class_type": "SDPoseDrawKeypoints",
            "_meta": {"title": "绘制骨架控制视频"},
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
                # V3 autogrow API links must be flattened, matching the ordinary
                # H3 R2V builder. A nested dict is accepted but silently ignored.
                "ref_images.ref_image_0": ["1", 0],
            },
            "class_type": "MiniMaxH3ReferenceToVideo",
            "_meta": {"title": "H3 参考生成(身份锁定)"},
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
                "control_video": ["8", 0],
            },
            "class_type": "MiniMaxH3FunControlNetApply",
            "_meta": {"title": "骨架控制动作"},
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
        MOTION_TRANSFER_OUTPUT_NODE: {
            "inputs": {
                "video": ["24", 0],
                "filename_prefix": "video/h3_motion_transfer",
                "format": "auto",
            },
            "class_type": "SaveVideo",
            "_meta": {"title": "保存成片"},
        },
    }
    return workflow
