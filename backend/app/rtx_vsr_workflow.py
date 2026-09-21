# -*- coding: utf-8 -*-
"""独立 RTX Video Super Resolution API graph。

对照固定 ComfyUI 节点包示例 rtx_video_upscale.json：
LoadVideo → GetVideoComponents → RTXVideoSuperResolution → CreateVideo → SaveVideo。

DynamicCombo 按本仓库惯例用点号子键（与 video_depth_workflow 的 output.normalization 相同）。
已用 GET /object_info/RTXVideoSuperResolution 核对：resize_type 选项为
"scale by multiplier"，子键 scale；quality 默认 ULTRA。
输出节点不用 14，避免占用 MiniMax H3 SaveVideo。
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from .models import JobMode

VSR_LOAD_NODE = "20"
VSR_COMPONENTS_NODE = "21"
VSR_UPSCALE_NODE = "22"
VSR_CREATE_NODE = "23"
VSR_OUTPUT_NODE = "24"
VSR_SCALES = (2, 4)
VSR_DEFAULT_SCALE = 2
VSR_SCALE = VSR_DEFAULT_SCALE
UPSCALE_AFTER_OFF = "off"
VSR_QUALITY = "ULTRA"
VSR_RESIZE_TYPE = "scale by multiplier"
RTX_VSR_NODE_TYPE = "RTXVideoSuperResolution"
RTX_VSR_PHASE = "rtx-vsr"
UPSCALE_OUTPUT_LABEL = "2x 超分"
VSR_FILENAME_PREFIX = "video/ZLY_AI_VIDEO_STUDIO_RTX_VSR"
# 卸 H3 后仍要给 CUDA/运行时留余量；真正额度来自当前连接 ComfyUI /system_stats 的 vram_total。
VSR_VRAM_RESERVE_BYTES = 2 * 1024 * 1024 * 1024
VSR_CHANNELS = 3
VSR_ITEMSIZE = 4
_ASPECT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)")


def parse_vsr_scale(value: Any, *, default: int | None = VSR_DEFAULT_SCALE) -> int:
    """Accept 2 / 4, 2x / 4x, and legacy booleans. Missing values use the default."""
    if value is None or value == "":
        if default is None:
            raise ValueError("超分倍数只能是 2x 或 4x")
        return int(default)
    if isinstance(value, bool):
        if value:
            return 2
        if default is not None:
            return int(default)
        raise ValueError("超分倍数只能是 2x 或 4x")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)) and float(value).is_integer() and int(value) in VSR_SCALES:
            return int(value)
        raise ValueError("超分倍数只能是 2x 或 4x")
    text = str(value).strip().lower()
    if text in {"off", "false", "0", "none", "no"}:
        if default is not None:
            return int(default)
        raise ValueError("超分倍数只能是 2x 或 4x")
    if text in {"true", "yes", "on", "2", "2x", "2.0"}:
        return 2
    if text in {"4", "4x", "4.0"}:
        return 4
    raise ValueError("超分倍数只能是 2x 或 4x")


def normalize_upscale_after_choice(value: Any) -> str:
    """Normalize generate-time upscale_after to off / 2 / 4. Legacy true means 2x."""
    if value is None or value == "":
        return UPSCALE_AFTER_OFF
    if isinstance(value, bool):
        return "2" if value else UPSCALE_AFTER_OFF
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise ValueError("出片后超分只能是关闭、2x 或 4x")
        if float(value).is_integer() and int(value) in VSR_SCALES:
            return str(int(value))
        if int(value) == 0:
            return UPSCALE_AFTER_OFF
        raise ValueError("出片后超分只能是关闭、2x 或 4x")
    text = str(value).strip().lower()
    if text in {"off", "false", "0", "none", "no"}:
        return UPSCALE_AFTER_OFF
    if text in {"true", "yes", "on", "2", "2x", "2.0"}:
        return "2"
    if text in {"4", "4x", "4.0"}:
        return "4"
    raise ValueError("出片后超分只能是关闭、2x 或 4x")


def vsr_scale_from_options(options: dict[str, Any] | None) -> int:
    raw = options or {}
    for key in ("scale", "upscale_scale"):
        if raw.get(key) not in (None, ""):
            return parse_vsr_scale(raw.get(key))
    choice = normalize_upscale_after_choice(raw.get("upscale_after"))
    if choice in {"2", "4"}:
        return int(choice)
    return VSR_DEFAULT_SCALE


def vsr_scale_label(scale: int | None = None) -> str:
    return f"{parse_vsr_scale(scale)}x"


def upscale_output_label(scale: int | None = None) -> str:
    return f"{vsr_scale_label(scale)} 超分"


def is_upscale_output_label(label: Any) -> bool:
    return "超分" in str(label or "")


def build_rtx_vsr_workflow(video_filename: str, scale: int | None = None) -> dict[str, dict[str, Any]]:
    """构建「已上传原片 → RTX 2x/4x ULTRA → SaveVideo」的独立 API graph。"""
    filename = str(video_filename or "").strip()
    if not filename:
        raise ValueError("超分需要已上传到 ComfyUI 的视频文件名。")
    resolved = parse_vsr_scale(scale)
    label = vsr_scale_label(resolved)
    return {
        VSR_LOAD_NODE: {
            "class_type": "LoadVideo",
            "inputs": {"file": filename},
            "_meta": {"title": "读取原片"},
        },
        VSR_COMPONENTS_NODE: {
            "class_type": "GetVideoComponents",
            "inputs": {"video": [VSR_LOAD_NODE, 0]},
            "_meta": {"title": "拆出画面与音频"},
        },
        VSR_UPSCALE_NODE: {
            "class_type": RTX_VSR_NODE_TYPE,
            "inputs": {
                "images": [VSR_COMPONENTS_NODE, 0],
                "resize_type": VSR_RESIZE_TYPE,
                "resize_type.scale": float(resolved),
                "quality": VSR_QUALITY,
            },
            "_meta": {"title": f"RTX {label} 超分"},
        },
        VSR_CREATE_NODE: {
            "class_type": "CreateVideo",
            "inputs": {
                "images": [VSR_UPSCALE_NODE, 0],
                "audio": [VSR_COMPONENTS_NODE, 1],
                "fps": [VSR_COMPONENTS_NODE, 2],
            },
            "_meta": {"title": "合成超分视频"},
        },
        VSR_OUTPUT_NODE: {
            "class_type": "SaveVideo",
            "inputs": {
                "video": [VSR_CREATE_NODE, 0],
                "filename_prefix": VSR_FILENAME_PREFIX,
                "format": "auto",
                "codec": "auto",
            },
            "_meta": {"title": f"保存 {label} 超分"},
        },
    }


AUTO_UPSCALE_SCOPES = frozenset({"shot", "selection"})


def comfy_has_rtx_vsr_node(object_info: dict[str, Any] | None) -> bool:
    node = (object_info or {}).get(RTX_VSR_NODE_TYPE)
    return isinstance(node, dict) and bool(node)


RTX_VSR_NODE_PACK = "Nvidia_RTX_Nodes_ComfyUI"
RTX_VSR_NODE_REPO = "https://github.com/Comfy-Org/Nvidia_RTX_Nodes_ComfyUI"
RTX_VSR_PIP_PACKAGE = "nvidia-vfx==0.1.0.1"
RTX_VSR_PIP_INDEX = "https://pypi.nvidia.com"


def rtx_vsr_node_missing_message(comfy_url: str = "", device_name: str = "") -> str:
    where = str(comfy_url or "").strip().rstrip("/") or "当前连接的实例"
    gpu = str(device_name or "").strip()
    extra = f"（{gpu}）" if gpu else ""
    probe = f"{where}/object_info/{RTX_VSR_NODE_TYPE}"
    return (
        f"当前连接的 ComfyUI {where}{extra} 未安装 RTX Video Super Resolution 节点"
        f"（{RTX_VSR_NODE_TYPE}）。请在这台 ComfyUI 的 custom_nodes 安装 {RTX_VSR_NODE_PACK}："
        "可从本机整合包拷贝 custom_nodes/Nvidia_RTX_Nodes_ComfyUI，"
        f"或 git clone {RTX_VSR_NODE_REPO}.git ；"
        "再用启动这台 ComfyUI 的同一个 Python 执行 "
        f"python -m pip install -U --no-build-isolation {RTX_VSR_PIP_PACKAGE} --index-url {RTX_VSR_PIP_INDEX} "
        "（正式 wheel 在 NVIDIA 源，pypi.org 只有 2.7KB 空壳源码包）；"
        "然后完全退出并重启 ComfyUI，不要另开第二套实例。"
        f"需要 NVIDIA RTX 显卡。重启后打开 {probe} 应能看到该节点。"
        "LoadVideo / GetVideoComponents / CreateVideo / SaveVideo 是 ComfyUI 核心节点，一般不用另装。"
    )


def explain_comfy_prompt_rejection(
    status: int,
    body: str,
    *,
    comfy_url: str = "",
    device_name: str = "",
) -> str:
    text = str(body or "")
    payload: dict[str, Any] | None
    try:
        loaded = json.loads(text)
        payload = loaded if isinstance(loaded, dict) else None
    except Exception:
        payload = None
    error = payload.get("error") if payload else None
    extra = error.get("extra_info") if isinstance(error, dict) else None
    class_type = str((extra or {}).get("class_type") or "") if isinstance(extra, dict) else ""
    missing = isinstance(error, dict) and error.get("type") == "missing_node_type"
    mentions_vsr = class_type == RTX_VSR_NODE_TYPE or RTX_VSR_NODE_TYPE in text
    if mentions_vsr and (missing or "missing_node_type" in text or "not found" in text.lower()):
        return rtx_vsr_node_missing_message(comfy_url, device_name)
    return f"ComfyUI 提交失败，HTTP {status}: {text[:1000]}"


def wants_upscale(options: dict[str, Any] | None) -> bool:
    return normalize_upscale_after_choice((options or {}).get("upscale_after")) != UPSCALE_AFTER_OFF


def should_auto_upscale(render_scope: str | None, options: dict[str, Any] | None) -> bool:
    """整集直出和拼接片不自动超分；只对逐镜 / 选中镜接跑。"""
    return str(render_scope or "") in AUTO_UPSCALE_SCOPES and wants_upscale(options)


def original_video_output(outputs: list[dict] | None) -> dict | None:
    videos = [
        item for item in (outputs or [])
        if isinstance(item, dict) and item.get("kind") == "video"
    ]
    if not videos:
        return None
    for item in videos:
        if not is_upscale_output_label(item.get("label")):
            return item
    return videos[0]


def original_video_locator(job: dict | None) -> tuple[dict, str | None, int] | None:
    """Locate the first non-upscaled video on a job, preferring generation items."""
    for round_data in reversed((job or {}).get("rounds") or []):
        if not isinstance(round_data, dict):
            continue
        for item in reversed(round_data.get("generation_items") or []):
            if not isinstance(item, dict):
                continue
            for index, output in enumerate(item.get("outputs") or []):
                if isinstance(output, dict) and output.get("kind") == "video" and not is_upscale_output_label(output.get("label")):
                    return output, item.get("id"), index
    for index, output in enumerate((job or {}).get("outputs") or []):
        if isinstance(output, dict) and output.get("kind") == "video" and not is_upscale_output_label(output.get("label")):
            return output, None, index
    return None


def estimate_vsr_vram_bytes(width: int, height: int, frames: int, *, scale: int = VSR_SCALE) -> int:
    """按节点会同时持有输入帧 + 选定倍数输出帧张量估算显存。"""
    safe_frames = max(1, int(frames))
    safe_width = max(1, int(width))
    safe_height = max(1, int(height))
    safe_scale = max(1, int(scale))
    input_pixels = safe_frames * safe_height * safe_width
    output_pixels = safe_frames * safe_height * safe_scale * safe_width * safe_scale
    return (input_pixels + output_pixels) * VSR_CHANNELS * VSR_ITEMSIZE


def comfy_vram_total_bytes(stats: dict[str, Any] | None) -> int | None:
    """从 ComfyUI /system_stats 取当前连接 GPU 的总显存（字节）。"""
    totals: list[int] = []
    for device in (stats or {}).get("devices") or []:
        if not isinstance(device, dict):
            continue
        total = device.get("vram_total")
        if isinstance(total, bool) or not isinstance(total, (int, float)):
            continue
        if total > 0:
            totals.append(int(total))
    return max(totals) if totals else None


def comfy_vram_device_name(stats: dict[str, Any] | None) -> str:
    devices = [item for item in ((stats or {}).get("devices") or []) if isinstance(item, dict)]
    if not devices:
        return ""
    chosen = max(devices, key=lambda item: int(item.get("vram_total") or 0))
    name = str(chosen.get("name") or "").strip()
    return name.split(" : ")[0].replace("cuda:0 ", "").strip()


def vsr_vram_budget_bytes(vram_total: int | None) -> int | None:
    """卸模型后留给 VSR 整段帧张量的额度；读不到显存时不编造限额。"""
    if vram_total is None or int(vram_total) <= 0:
        return None
    return max(0, int(vram_total) - VSR_VRAM_RESERVE_BYTES)


def vsr_memory_rejection(
    width: int,
    height: int,
    frames: int,
    *,
    scale: int = VSR_DEFAULT_SCALE,
    budget_bytes: int | None = None,
    vram_total: int | None = None,
    device_name: str = "",
) -> str | None:
    resolved = parse_vsr_scale(scale)
    budget = budget_bytes if budget_bytes is not None else vsr_vram_budget_bytes(vram_total)
    if budget is None:
        return None
    estimated = estimate_vsr_vram_bytes(width, height, frames, scale=resolved)
    if estimated <= budget:
        return None
    gigabytes = estimated / (1024 * 1024 * 1024)
    budget_gb = budget / (1024 * 1024 * 1024)
    total = int(vram_total) if vram_total else budget + VSR_VRAM_RESERVE_BYTES
    total_gb = total / (1024 * 1024 * 1024)
    gpu = f"（{device_name}）" if device_name else ""
    hint = "请改用 2x、更低分辨率档或缩短时长后再试。" if resolved >= 4 else "请改用更低分辨率档或缩短时长后再试。"
    return (
        f"{resolved}x 超分预估需要约 {gigabytes:.1f} GB 显存（{width}×{height}、{frames} 帧）。"
        f"当前连接的 ComfyUI{gpu} 总显存约 {total_gb:.0f} GB，卸模型后可用额度约 {budget_gb:.0f} GB。"
        f"{hint}"
    )


def source_video_shape(mode: JobMode | str, options: dict[str, Any] | None) -> tuple[int, int, int] | None:
    """从任务参数还原原片宽、高、帧数，供超分前提交检查。"""
    raw = options or {}
    stored = _shape_from_stored_fields(raw)
    if stored is not None:
        return stored
    try:
        from .workflow_registry import h3_dimensions, h3_length, is_h3_workflow, is_t8_workflow
    except Exception:
        return None
    try:
        if is_t8_workflow(mode):
            patched = dict(raw)
            match = _ASPECT_RE.search(str(raw.get("aspect_ratio") or "16:9"))
            if not match:
                return None
            patched["aspect_ratio"] = f"{match.group(1)}:{match.group(2)}"
            return (*h3_dimensions(patched), h3_length(patched))
        if is_h3_workflow(mode):
            return (*h3_dimensions(raw), h3_length(raw))
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _shape_from_stored_fields(options: dict[str, Any]) -> tuple[int, int, int] | None:
    width = options.get("width")
    height = options.get("height")
    frames = options.get("frames", options.get("length"))
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (width, height, frames)):
        return None
    if not all(math.isfinite(float(value)) and float(value) > 0 for value in (width, height, frames)):
        return None
    return int(width), int(height), int(frames)
