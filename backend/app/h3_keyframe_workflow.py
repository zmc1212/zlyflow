# -*- coding: utf-8 -*-
"""MiniMax H3 关键帧叙事的 ComfyUI API graph 构建器。

官方 fl2va + AddGuide 锚定管线:第一张关键帧经 MiniMaxH3ImageToVideo 的
first_frame 锁定开场(frame 0),其余关键帧按锚定帧号经 MiniMaxH3AddGuide
链式追加进 conditioning 的 minimax_keyframes——关键帧隐变量每步重注入、
永不加噪,模型生成贯穿全部关键帧的叙事过渡,音画一体,纯本地免费。
"""
from __future__ import annotations

from typing import Any

H3_UNET_FILENAME = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
H3_CLIP_FILENAME = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
H3_VIDEO_VAE_FILENAME = "minimax_h3_video_vae_fp16.safetensors"
H3_AUDIO_VAE_FILENAME = "minimax_h3_audio_vae_fp32.safetensors"

KEYFRAME_OUTPUT_NODE = "30"
KEYFRAME_FPS = 24
KEYFRAME_MAX_KEYFRAMES = 4
KEYFRAME_MIN_KEYFRAMES = 2

# 官方模板默认尺寸:横版 16:9 @ 0.4 MP(32 对齐);帧网格 17n+5(5 秒 = 124 帧)。
KEYFRAME_SIZES = {"16:9": (864, 480), "9:16": (480, 864), "1:1": (640, 640)}
KEYFRAME_LENGTHS = {"5s": 124, "10s": 243, "15s": 362}

# 与 I2V 官方模板一致的显存预留(16GB 卡不加会在 SamplerCustomAdvanced OOM)。
OFFICIAL_RESERVED_VRAM_GB = 3.0


def snap_h3_length(frames: int) -> int:
    """H3 视频 VAE 帧网格 17n+5,最小 29 帧。"""
    value = max(1, int(frames))
    n = max(1, round((value - 5) / 17))
    return max(29, 17 * n + 5)


def snap_h3_size(value: int) -> int:
    """画布边长 32 对齐(H3 官方模板约束)。"""
    return max(32, int(value) // 32 * 32)


def resolve_keyframe_dimensions(aspect_ratio: str, duration: str) -> tuple[int, int, int]:
    """把 primary 的画面比例与生成时长选项映射为 (width, height, length)。"""
    width, height = KEYFRAME_SIZES.get(str(aspect_ratio), KEYFRAME_SIZES["16:9"])
    length = KEYFRAME_LENGTHS.get(str(duration), KEYFRAME_LENGTHS["5s"])
    return snap_h3_size(width), snap_h3_size(height), snap_h3_length(length)


def even_keyframe_anchor_frames(keyframe_count: int, length: int) -> list[int]:
    """均匀分布:首张锚 frame 0(经 first_frame),其余均分到 1..length-1,末张锚末帧。"""
    last = length - 1
    return [round(last * index / (keyframe_count - 1)) for index in range(1, keyframe_count - 1 + 1)]


def resolve_keyframe_anchor_frames(
    anchor_seconds: str | None, keyframe_count: int, length: int,
) -> list[int]:
    """解析第 2~N 张关键帧的锚定帧号。

    anchor_seconds 为逗号分隔的秒数(如 "2.5,8"),第 1 张固定锚在 frame 0;
    负整数沿用 AddGuide 语义从末尾计数(-1 = 末帧);留空则均匀分布。
    frame_idx 的合法范围是 0..length-1(AddGuide 对单图 guide_frames=1)。
    """
    if keyframe_count < KEYFRAME_MIN_KEYFRAMES or keyframe_count > KEYFRAME_MAX_KEYFRAMES:
        raise ValueError(f"关键帧数量必须在 {KEYFRAME_MIN_KEYFRAMES}-{KEYFRAME_MAX_KEYFRAMES} 张之间。")
    expected = keyframe_count - 1
    text = str(anchor_seconds or "").strip()
    if not text:
        return even_keyframe_anchor_frames(keyframe_count, length)
    max_seconds = length / KEYFRAME_FPS
    frames: list[int] = []
    for part in text.replace("，", ",").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            seconds = float(token)
        except ValueError as error:
            raise ValueError(f"锚点时间“{token}”不是有效数字。") from error
        if seconds == 0:
            raise ValueError("锚点时间必须大于 0；开场关键帧固定在第 0 帧，无需单独指定。")
        if seconds > 0:
            if seconds > max_seconds + 0.5:
                raise ValueError(f"锚点时间不能超过 {max_seconds:.1f} 秒(当前生成时长)。")
            frames.append(min(length - 1, round(seconds * KEYFRAME_FPS)))
        else:
            frame = round(seconds)
            if abs(frame) >= length:
                raise ValueError(f"锚点 -{abs(frame)} 超出了视频长度({length} 帧)。")
            frames.append(frame)
    if len(frames) != expected:
        raise ValueError(
            f"共 {keyframe_count} 张关键帧时,锚点时间需要 {expected} 个值(逗号分隔)，当前收到 {len(frames)} 个。"
        )
    resolved = [frame if frame >= 0 else length + frame for frame in frames]
    for previous, current in zip(resolved, resolved[1:]):
        if current <= previous:
            raise ValueError("锚点时间必须按关键帧顺序依次增大，且不能重复。")
    return frames


def build_h3_keyframe_workflow(
    keyframe_filenames: list[str],
    prompt: str,
    *,
    width: int,
    height: int,
    length: int,
    anchor_frames: list[int],
    steps: int = 20,
    seed: int,
    weight_dtype: str = "default",
    fps: int = KEYFRAME_FPS,
    use_sage_attention: bool = True,
) -> dict[str, dict[str, Any]]:
    """构建"2-4 张关键帧 → 贯穿关键帧的叙事视频"工作流。

    keyframe_filenames 为已上传到 ComfyUI input 的关键帧图片文件名(按叙事顺序);
    anchor_frames 为第 2~N 张的锚定帧号(第 1 张经 first_frame 锚在 frame 0);
    width/height 需 32 对齐,length 自动对齐 17n+5 网格。
    """
    if not KEYFRAME_MIN_KEYFRAMES <= len(keyframe_filenames) <= KEYFRAME_MAX_KEYFRAMES:
        raise ValueError(f"关键帧数量必须在 {KEYFRAME_MIN_KEYFRAMES}-{KEYFRAME_MAX_KEYFRAMES} 张之间。")
    if len(anchor_frames) != len(keyframe_filenames) - 1:
        raise ValueError("锚定帧号数量必须等于关键帧数减一(第一张固定锚在开场)。")
    safe_width = snap_h3_size(width)
    safe_height = snap_h3_size(height)
    frame_length = snap_h3_length(length)
    safe_steps = max(4, min(40, int(steps)))
    text = prompt.strip()

    workflow: dict[str, dict[str, Any]] = {}
    for index, filename in enumerate(keyframe_filenames, start=1):
        workflow[str(index)] = {
            "inputs": {"image": filename},
            "class_type": "LoadImage",
            "_meta": {"title": f"关键帧 {index}"},
        }

    workflow.update({
        "10": {
            "inputs": {"unet_name": H3_UNET_FILENAME, "weight_dtype": weight_dtype},
            "class_type": "UNETLoader",
            "_meta": {"title": "加载 H3 FL2VA 模型"},
        },
        "11": {
            "inputs": {"clip_name": H3_CLIP_FILENAME, "type": "minimax", "device": "default"},
            "class_type": "CLIPLoader",
            "_meta": {"title": "加载 Qwen3-VL 文本编码器"},
        },
        "12": {
            "inputs": {"vae_name": H3_VIDEO_VAE_FILENAME},
            "class_type": "VAELoader",
            "_meta": {"title": "加载 H3 视频 VAE"},
        },
        "13": {
            "inputs": {"vae_name": H3_AUDIO_VAE_FILENAME},
            "class_type": "VAELoader",
            "_meta": {"title": "加载 H3 音频 VAE"},
        },
        "14": {
            "inputs": {
                "anything": ["10", 0],
                "reserved": OFFICIAL_RESERVED_VRAM_GB,
                "mode": "manual",
                "seed": 0,
                "auto_max_reserved": 0,
                "clean_gpu_before": True,
            },
            "class_type": "ReservedVRAMSetter",
            "_meta": {"title": "预留显存"},
        },
        "16": {
            "inputs": {
                "clip": ["11", 0],
                "vae": ["12", 0],
                "prompt": text,
                "width": safe_width,
                "height": safe_height,
                "length": frame_length,
                "first_frame": ["1", 0],
            },
            "class_type": "MiniMaxH3ImageToVideo",
            "_meta": {"title": "开场关键帧锚定"},
        },
        "20": {
            "inputs": {"noise_seed": int(seed)},
            "class_type": "RandomNoise",
            "_meta": {"title": "噪声"},
        },
        "21": {
            "inputs": {"sampler_name": "res_multistep"},
            "class_type": "KSamplerSelect",
            "_meta": {"title": "采样器"},
        },
        "22": {
            "inputs": {"model": ["14", 0], "scheduler": "simple", "steps": safe_steps, "denoise": 1.0},
            "class_type": "BasicScheduler",
            "_meta": {"title": "调度"},
        },
        "25": {
            "inputs": {"samples": ["24", 0], "vae": ["12", 0]},
            "class_type": "VAEDecode",
            "_meta": {"title": "解码视频帧"},
        },
        "26": {
            "inputs": {"samples": ["24", 0], "vae": ["13", 0]},
            "class_type": "VAEDecodeAudio",
            "_meta": {"title": "解码音频"},
        },
        "27": {
            "inputs": {
                "images": ["25", 0],
                "fps": int(fps),
                "audio": ["26", 0],
                "bit_depth": "auto",
                "color_space": "sRGB",
            },
            "class_type": "CreateVideo",
            "_meta": {"title": "合成视频"},
        },
        KEYFRAME_OUTPUT_NODE: {
            "inputs": {
                "video": ["27", 0],
                "filename_prefix": "video/h3_keyframe_narrative",
                "format": "auto",
            },
            "class_type": "SaveVideo",
            "_meta": {"title": "保存成片"},
        },
    })

    if use_sage_attention:
        workflow["15"] = {
            "inputs": {"model": ["14", 0]},
            "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
            "_meta": {"title": "SageAttention 加速"},
        }
        model_source = ["15", 0]
    else:
        model_source = ["14", 0]
    workflow["22"]["inputs"]["model"] = model_source

    # AddGuide 链:positive 逐级传递,latent 统一取基座输出的 AV latent。
    positive_source: list[Any] = ["16", 0]
    for guide_index, frame_idx in enumerate(anchor_frames, start=1):
        node_id = str(16 + guide_index)
        workflow[node_id] = {
            "inputs": {
                "positive": positive_source,
                "vae": ["12", 0],
                "latent": ["16", 1],
                "image": [str(guide_index + 1), 0],
                "frame_idx": int(frame_idx),
            },
            "class_type": "MiniMaxH3AddGuide",
            "_meta": {"title": f"关键帧 {guide_index + 1} 锚定"},
        }
        positive_source = [node_id, 0]

    workflow["23"] = {
        "inputs": {"model": model_source, "conditioning": positive_source},
        "class_type": "BasicGuider",
        "_meta": {"title": "引导"},
    }
    workflow["24"] = {
        "inputs": {
            "noise": ["20", 0],
            "guider": ["23", 0],
            "sampler": ["21", 0],
            "sigmas": ["22", 0],
            "latent_image": ["16", 1],
        },
        "class_type": "SamplerCustomAdvanced",
        "_meta": {"title": "采样"},
    }
    return workflow
