# -*- coding: utf-8 -*-
"""RelayVSR 2x 超分 API graph（Comfyui-Relay-VSR 社区节点）。

远端实测（RTX 4080 16 GB，2026-11-10）：
- 864×486 / 121 帧整段超分成功，约 75 秒出 1728×972；
- 1920×1080 / 224 帧整段超分 OOM（帧张量合计约 26 GB），
  因此提交前必须按「帧数 × 像素」做显存预检。

走 IMAGE 进 / IMAGE 出 + CreateVideo + SaveVideo 的组合而不是
RelayVSRUpscaleStreaming：前者能把原片音轨交回 CreateVideo，后者只输出无声视频文件。
节点参数已用 GET /object_info 核对：RelayVSRModelLoader(bundle/dtype/offload/path)、
RelayVSRUpscale(sr_ratio/chunk_len/seed)。
输出节点编号避开 H3(14)、RTX VSR(20-24)、SeedVR2(30-44)。
"""
from __future__ import annotations

from typing import Any

RELAY_VSR_LOAD_NODE = "50"
RELAY_VSR_COMPONENTS_NODE = "51"
RELAY_VSR_MODEL_NODE = "52"
RELAY_VSR_UPSCALE_NODE = "53"
RELAY_VSR_CREATE_NODE = "54"
RELAY_VSR_OUTPUT_NODE = "55"

RELAY_VSR_MODEL_NODE_TYPE = "RelayVSRModelLoader"
RELAY_VSR_UPSCALE_NODE_TYPE = "RelayVSRUpscale"
RELAY_VSR_NODE_TYPES = (RELAY_VSR_MODEL_NODE_TYPE, RELAY_VSR_UPSCALE_NODE_TYPE)
RELAY_VSR_BUNDLE = "RelayVSR_X2"
RELAY_VSR_DTYPE = "bf16"
RELAY_VSR_SCALE = 2
RELAY_VSR_CHUNK_LEN = 16
RELAY_VSR_SEED = 0
RELAY_VSR_PHASE = "relay-vsr-upscale"
RELAY_VSR_OUTPUT_LABEL = "2x 细节超分"
RELAY_VSR_FILENAME_PREFIX = "video/ZLY_AI_VIDEO_STUDIO_RELAYVSR"
# 与 RTX VSR 相同：卸模型后仍要给 CUDA/运行时留余量。
RELAY_VSR_VRAM_RESERVE_BYTES = 2 * 1024 * 1024 * 1024
RELAY_VSR_CHANNELS = 3
RELAY_VSR_ITEMSIZE = 4


def build_relay_vsr_workflow(video_filename: str) -> dict[str, dict[str, Any]]:
    """构建「已上传原片 → RelayVSR 2x → 保留原音轨 → SaveVideo」的独立 API graph。"""
    filename = str(video_filename or "").strip()
    if not filename:
        raise ValueError("超分需要已上传到视频服务的视频文件名。")
    return {
        RELAY_VSR_LOAD_NODE: {
            "class_type": "LoadVideo",
            "inputs": {"file": filename},
            "_meta": {"title": "读取原片"},
        },
        RELAY_VSR_COMPONENTS_NODE: {
            "class_type": "GetVideoComponents",
            "inputs": {"video": [RELAY_VSR_LOAD_NODE, 0]},
            "_meta": {"title": "拆出画面与音频"},
        },
        RELAY_VSR_MODEL_NODE: {
            "class_type": RELAY_VSR_MODEL_NODE_TYPE,
            "inputs": {
                "bundle": RELAY_VSR_BUNDLE,
                "dtype": RELAY_VSR_DTYPE,
                "offload": True,
                "path": "",
            },
            "_meta": {"title": "RelayVSR 2x 权重"},
        },
        RELAY_VSR_UPSCALE_NODE: {
            "class_type": RELAY_VSR_UPSCALE_NODE_TYPE,
            "inputs": {
                "model": [RELAY_VSR_MODEL_NODE, 0],
                "images": [RELAY_VSR_COMPONENTS_NODE, 0],
                "sr_ratio": RELAY_VSR_SCALE,
                "chunk_len": RELAY_VSR_CHUNK_LEN,
                "seed": RELAY_VSR_SEED,
            },
            "_meta": {"title": "RelayVSR 2x 超分"},
        },
        RELAY_VSR_CREATE_NODE: {
            "class_type": "CreateVideo",
            "inputs": {
                "images": [RELAY_VSR_UPSCALE_NODE, 0],
                "audio": [RELAY_VSR_COMPONENTS_NODE, 1],
                "fps": [RELAY_VSR_COMPONENTS_NODE, 2],
            },
            "_meta": {"title": "合成超分视频（保留原音轨）"},
        },
        RELAY_VSR_OUTPUT_NODE: {
            "class_type": "SaveVideo",
            "inputs": {
                "video": [RELAY_VSR_CREATE_NODE, 0],
                "filename_prefix": RELAY_VSR_FILENAME_PREFIX,
                "format": "auto",
                "codec": "auto",
            },
            "_meta": {"title": "保存 2x 细节超分"},
        },
    }


def _combo_values(node: dict[str, Any] | None, field: str) -> list[str]:
    """读取 COMBO 输入的可选值（新版 object_info 把 options 放在第二项里）。"""
    if not isinstance(node, dict):
        return []
    spec = ((node.get("input") or {}).get("required") or {}).get(field)
    if not isinstance(spec, (list, tuple)) or not spec:
        return []
    if isinstance(spec[0], list):
        return [str(item) for item in spec[0]]
    for extra in spec[1:]:
        if isinstance(extra, dict) and isinstance(extra.get("options"), list):
            return [str(item) for item in extra["options"]]
    return []


def relay_vsr_bundles(object_info: dict[str, Any] | None) -> list[str]:
    return _combo_values((object_info or {}).get(RELAY_VSR_MODEL_NODE_TYPE), "bundle")


def relay_vsr_missing_message(
    object_info: dict[str, Any] | None,
    *,
    comfy_url: str = "",
    device_name: str = "",
) -> str | None:
    """节点、2x 权重都齐时返回 None，否则给出可执行的缺失说明。"""
    info = object_info or {}
    where = str(comfy_url or "").strip().rstrip("/") or "当前连接的实例"
    gpu = str(device_name or "").strip()
    where = f"{where}（{gpu}）" if gpu else where
    missing = [name for name in RELAY_VSR_NODE_TYPES if not isinstance(info.get(name), dict)]
    if missing:
        return (
            f"{where} 的视频服务未安装 RelayVSR 节点（{'、'.join(missing)}）。"
            "请在 custom_nodes 安装 Comfyui-Relay-VSR 后重启视频服务；"
            "FL-RelayVSR 需要 Python 3.11+，当前实例若为 3.10 不能使用。"
        )
    bundles = relay_vsr_bundles(info)
    if RELAY_VSR_BUNDLE not in bundles:
        found = "、".join(bundles) if bundles else "无"
        return (
            f"{where} 的 RelayVSR 没有可用的 2x 权重包（当前可选：{found}）。"
            f"请把 {RELAY_VSR_BUNDLE}（wan_x2.safetensors + flash_x2.safetensors）"
            "放进该实例 models/relayvsr/RelayVSR_X2 后重启视频服务。"
        )
    return None


def estimate_relay_vsr_vram_bytes(width: int, height: int, frames: int) -> int:
    """RelayVSRUpscale 会同时持有原尺寸帧与 2x 输出帧张量，按两者之和估算。"""
    safe_frames = max(1, int(frames))
    safe_width = max(1, int(width))
    safe_height = max(1, int(height))
    pixels = safe_width * safe_height
    in_and_out = pixels + pixels * RELAY_VSR_SCALE * RELAY_VSR_SCALE
    return safe_frames * in_and_out * RELAY_VSR_CHANNELS * RELAY_VSR_ITEMSIZE


def relay_vsr_memory_rejection(
    width: int,
    height: int,
    frames: int,
    *,
    vram_total: int | None = None,
    device_name: str = "",
) -> str | None:
    """按当前实例总显存判断这一条原片能否整段进 RelayVSR；读不到显存时不编造限额。"""
    if vram_total is None or int(vram_total) <= 0:
        return None
    budget = max(0, int(vram_total) - RELAY_VSR_VRAM_RESERVE_BYTES)
    estimated = estimate_relay_vsr_vram_bytes(width, height, frames)
    if estimated <= budget:
        return None
    gpu = f"（{device_name}）" if device_name else ""
    return (
        f"RelayVSR 2x 超分这段原片预估需要约 {estimated / 1024 ** 3:.1f} GB 显存"
        f"（{width}×{height}、{frames} 帧），当前视频服务{gpu} 卸模型后可用约 {budget / 1024 ** 3:.0f} GB。"
        "请改用更短的片段或更低分辨率原片，或改用 RTX 快速超分 / SeedVR2 高清增强。"
    )
