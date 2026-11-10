# -*- coding: utf-8 -*-
"""SeedVR2 生成式视频超分 API graph（ComfyUI 原生 SeedVR2 节点）。

对照官方模板 utility_seedvr2_3b_int8_upscale_video.json 展开子图：
LoadVideo → GetVideoComponents → ResizeImageMaskNode(scale by multiplier 2x)
→ SeedVR2Preprocess → VAEEncodeTiled → SeedVR2TemporalChunk(auto)
→ SeedVR2Conditioning → KSampler(1 step) → SeedVR2TemporalMerge
→ VAEDecodeTiled → SeedVR2PostProcessing → CreateVideo → SaveVideo。

官方模板用 ComfySwitchNode 分别处理「先截取片段」和「按显存切分 latent」。
本工作台只做整段超分，固定走 split_latent=true 分支（SeedVR2TemporalChunk
auto：放得下时原样返回一整段），因此把开关分支拍平。
DynamicCombo 按本仓库惯例用点号子键（同 RTX VSR 的 resize_type.scale）。
输出节点编号避开 H3 的 14 与 RTX VSR 的 20-24。
"""
from __future__ import annotations

from typing import Any

SEEDVR2_LOAD_NODE = "30"
SEEDVR2_COMPONENTS_NODE = "31"
SEEDVR2_RESIZE_NODE = "32"
SEEDVR2_PREPROCESS_NODE = "33"
SEEDVR2_VAE_NODE = "34"
SEEDVR2_ENCODE_NODE = "35"
SEEDVR2_CHUNK_NODE = "36"
SEEDVR2_MODEL_NODE = "37"
SEEDVR2_CONDITIONING_NODE = "38"
SEEDVR2_SAMPLER_NODE = "39"
SEEDVR2_MERGE_NODE = "40"
SEEDVR2_DECODE_NODE = "41"
SEEDVR2_POST_NODE = "42"
SEEDVR2_CREATE_NODE = "43"
SEEDVR2_OUTPUT_NODE = "44"

SEEDVR2_MODEL_NAME = "seedvr2_3b_int8_convrot.safetensors"
SEEDVR2_VAE_NAME = "seedvr2_ema_vae_fp16.safetensors"
SEEDVR2_NODE_TYPES = (
    "SeedVR2Preprocess",
    "SeedVR2TemporalChunk",
    "SeedVR2Conditioning",
    "SeedVR2TemporalMerge",
    "SeedVR2PostProcessing",
)
# /object_info 单独取这几类节点：节点是否存在 + 模型是否已装进枚举列表。
SEEDVR2_OBJECT_INFO_TYPES = (*SEEDVR2_NODE_TYPES, "UNETLoader", "VAELoader")
SEEDVR2_SCALE = 2.0
SEEDVR2_STEPS = 1
SEEDVR2_CFG = 1.0
SEEDVR2_SAMPLER = "euler"
SEEDVR2_SCHEDULER = "simple"
SEEDVR2_DENOISE = 1.0
SEEDVR2_SEED = 42
SEEDVR2_TILE_SIZE = 512
SEEDVR2_TILE_OVERLAP = 128
SEEDVR2_TEMPORAL_SIZE = 64
SEEDVR2_TEMPORAL_TILE_OVERLAP = 8
SEEDVR2_TEMPORAL_OVERLAP = 0
SEEDVR2_COLOR_CORRECTION = "none"
SEEDVR2_PHASE = "seedvr2-upscale"
SEEDVR2_OUTPUT_LABEL = "2x 高清增强"
SEEDVR2_FILENAME_PREFIX = "video/ZLY_AI_VIDEO_STUDIO_SEEDVR2"

UPSCALE_ENGINE_RTX = "rtx"
UPSCALE_ENGINE_SEEDVR2 = "seedvr2"
UPSCALE_ENGINE_RELAYVSR = "relayvsr"
UPSCALE_ENGINES = {
    UPSCALE_ENGINE_RTX: "RTX 快速超分",
    UPSCALE_ENGINE_SEEDVR2: "SeedVR2 高清增强",
    UPSCALE_ENGINE_RELAYVSR: "RelayVSR 细节超分",
}
DEFAULT_UPSCALE_ENGINE = UPSCALE_ENGINE_RTX


def normalize_upscale_engine(value: Any) -> str:
    engine = str(value or "").strip().lower()
    return engine if engine in UPSCALE_ENGINES else DEFAULT_UPSCALE_ENGINE


def build_seedvr2_upscale_workflow(
    video_filename: str,
    *,
    seed: int = SEEDVR2_SEED,
    color_correction: str = SEEDVR2_COLOR_CORRECTION,
) -> dict[str, dict[str, Any]]:
    filename = str(video_filename or "").strip()
    if not filename:
        raise ValueError("超分需要已上传到 ComfyUI 的视频文件名。")
    return {
        SEEDVR2_LOAD_NODE: {
            "class_type": "LoadVideo",
            "inputs": {"file": filename},
            "_meta": {"title": "读取原片"},
        },
        SEEDVR2_COMPONENTS_NODE: {
            "class_type": "GetVideoComponents",
            "inputs": {"video": [SEEDVR2_LOAD_NODE, 0]},
            "_meta": {"title": "拆出画面与音频"},
        },
        SEEDVR2_RESIZE_NODE: {
            "class_type": "ResizeImageMaskNode",
            "inputs": {
                "input": [SEEDVR2_COMPONENTS_NODE, 0],
                "resize_type": "scale by multiplier",
                "resize_type.multiplier": float(SEEDVR2_SCALE),
                "scale_method": "lanczos",
            },
            "_meta": {"title": "放大到 2x 尺寸"},
        },
        SEEDVR2_PREPROCESS_NODE: {
            "class_type": "SeedVR2Preprocess",
            "inputs": {"resized_images": [SEEDVR2_RESIZE_NODE, 0]},
            "_meta": {"title": "SeedVR2 预处理"},
        },
        SEEDVR2_VAE_NODE: {
            "class_type": "VAELoader",
            "inputs": {"vae_name": SEEDVR2_VAE_NAME},
            "_meta": {"title": "SeedVR2 VAE"},
        },
        SEEDVR2_ENCODE_NODE: {
            "class_type": "VAEEncodeTiled",
            "inputs": {
                "pixels": [SEEDVR2_PREPROCESS_NODE, 0],
                "vae": [SEEDVR2_VAE_NODE, 0],
                "tile_size": SEEDVR2_TILE_SIZE,
                "overlap": SEEDVR2_TILE_OVERLAP,
                "temporal_size": SEEDVR2_TEMPORAL_SIZE,
                "temporal_overlap": SEEDVR2_TEMPORAL_TILE_OVERLAP,
            },
            "_meta": {"title": "分块编码"},
        },
        SEEDVR2_CHUNK_NODE: {
            "class_type": "SeedVR2TemporalChunk",
            "inputs": {
                "latent": [SEEDVR2_ENCODE_NODE, 0],
                "temporal_overlap": SEEDVR2_TEMPORAL_OVERLAP,
                "chunking_mode": "auto",
            },
            "_meta": {"title": "按显存自动分块"},
        },
        SEEDVR2_MODEL_NODE: {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": SEEDVR2_MODEL_NAME, "weight_dtype": "default"},
            "_meta": {"title": "SeedVR2 3B Int8"},
        },
        # 条件必须和采样器拿到同一份（按显存切分后的）latent：官方模板里
        # 开关的两种走法都是把同一个输出同时接到 SeedVR2Conditioning 与
        # KSampler，形状不匹配时 KSampler 会直接报错。
        SEEDVR2_CONDITIONING_NODE: {
            "class_type": "SeedVR2Conditioning",
            "inputs": {
                "model": [SEEDVR2_MODEL_NODE, 0],
                "vae_conditioning": [SEEDVR2_CHUNK_NODE, 0],
            },
            "_meta": {"title": "SeedVR2 条件"},
        },
        SEEDVR2_SAMPLER_NODE: {
            "class_type": "KSampler",
            "inputs": {
                "model": [SEEDVR2_MODEL_NODE, 0],
                "seed": int(seed),
                "steps": SEEDVR2_STEPS,
                "cfg": SEEDVR2_CFG,
                "sampler_name": SEEDVR2_SAMPLER,
                "scheduler": SEEDVR2_SCHEDULER,
                "positive": [SEEDVR2_CONDITIONING_NODE, 0],
                "negative": [SEEDVR2_CONDITIONING_NODE, 1],
                "latent_image": [SEEDVR2_CHUNK_NODE, 0],
                "denoise": SEEDVR2_DENOISE,
            },
            "_meta": {"title": "一步采样"},
        },
        SEEDVR2_MERGE_NODE: {
            "class_type": "SeedVR2TemporalMerge",
            "inputs": {
                "latents": [SEEDVR2_SAMPLER_NODE, 0],
                "temporal_overlap": [SEEDVR2_CHUNK_NODE, 1],
            },
            "_meta": {"title": "合并分块"},
        },
        SEEDVR2_DECODE_NODE: {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": [SEEDVR2_MERGE_NODE, 0],
                "vae": [SEEDVR2_VAE_NODE, 0],
                "tile_size": SEEDVR2_TILE_SIZE,
                "overlap": SEEDVR2_TILE_OVERLAP,
                "temporal_size": SEEDVR2_TEMPORAL_SIZE,
                "temporal_overlap": SEEDVR2_TEMPORAL_TILE_OVERLAP,
            },
            "_meta": {"title": "分块解码"},
        },
        SEEDVR2_POST_NODE: {
            "class_type": "SeedVR2PostProcessing",
            "inputs": {
                "images": [SEEDVR2_DECODE_NODE, 0],
                "original_resized_images": [SEEDVR2_RESIZE_NODE, 0],
                "color_correction_method": color_correction,
            },
            "_meta": {"title": "后处理校色"},
        },
        SEEDVR2_CREATE_NODE: {
            "class_type": "CreateVideo",
            "inputs": {
                "images": [SEEDVR2_POST_NODE, 0],
                "audio": [SEEDVR2_COMPONENTS_NODE, 1],
                "fps": [SEEDVR2_COMPONENTS_NODE, 2],
                "bit_depth": [SEEDVR2_COMPONENTS_NODE, 3],
            },
            "_meta": {"title": "合成超分视频"},
        },
        SEEDVR2_OUTPUT_NODE: {
            "class_type": "SaveVideo",
            "inputs": {
                "video": [SEEDVR2_CREATE_NODE, 0],
                "filename_prefix": SEEDVR2_FILENAME_PREFIX,
                "format": "auto",
                "codec": "auto",
            },
            "_meta": {"title": "保存高清增强"},
        },
    }


def _enum_values(node: dict[str, Any] | None, field: str) -> list[str]:
    if not isinstance(node, dict):
        return []
    spec = ((node.get("input") or {}).get("required") or {}).get(field)
    if not isinstance(spec, (list, tuple)) or not spec:
        return []
    values = spec[0]
    if not isinstance(values, list):
        return []
    return [str(item) for item in values]


def seedvr2_missing_message(
    object_info: dict[str, Any] | None,
    *,
    comfy_url: str = "",
    device_name: str = "",
) -> str | None:
    """返回缺失说明；节点和模型都齐时返回 None。"""
    info = object_info or {}
    where = str(comfy_url or "").strip().rstrip("/") or "当前连接的实例"
    gpu = str(device_name or "").strip()
    where = f"{where}（{gpu}）" if gpu else where
    missing_nodes = [name for name in SEEDVR2_NODE_TYPES if not isinstance(info.get(name), dict)]
    if missing_nodes:
        return (
            f"{where} 的 ComfyUI 缺少 SeedVR2 原生节点（{'、'.join(missing_nodes)}）。"
            "请升级到自带 SeedVR2 原生节点（comfy_extras/nodes_seedvr.py）的 ComfyUI 后再试。"
        )
    if SEEDVR2_MODEL_NAME not in _enum_values(info.get("UNETLoader"), "unet_name"):
        return (
            f"{where} 未找到 SeedVR2 扩散模型 {SEEDVR2_MODEL_NAME}。"
            "请把 Comfy-Org/SeedVR2 的 diffusion_models/seedvr2_3b_int8_convrot.safetensors "
            "放进该实例的 models/diffusion_models（或 extra_model_paths 指向的目录）后重启 ComfyUI。"
        )
    if SEEDVR2_VAE_NAME not in _enum_values(info.get("VAELoader"), "vae_name"):
        return (
            f"{where} 未找到 SeedVR2 VAE {SEEDVR2_VAE_NAME}。"
            "请把 Comfy-Org/SeedVR2 的 vae/seedvr2_ema_vae_fp16.safetensors "
            "放进该实例的 models/vae（或 extra_model_paths 指向的目录）后重启 ComfyUI。"
        )
    return None
