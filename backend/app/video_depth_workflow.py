# -*- coding: utf-8 -*-
"""Depth Anything 3 视频深度提取的 ComfyUI API graph 构建器。

节点结构经过 ComfyUI 0.30 实测验证：VHS_LoadVideo → DA3Inference(mono) →
DA3Render(depth) → VHS_VideoCombine 输出 mp4。DynamicCombo 参数在 API graph
中以点号前缀子键传递（如 output.normalization）。
"""
from __future__ import annotations

from typing import Any

DA3_MODEL_FILENAME = "depth_anything_3_mono_large.safetensors"
DEPTH_OUTPUT_NODE = "5"
DEFAULT_DEPTH_RESOLUTION = 504


def build_depth_video_workflow(
    video_filename: str,
    *,
    fps: int = 16,
    frame_cap: int,
    resolution: int = DEFAULT_DEPTH_RESOLUTION,
) -> dict[str, dict[str, Any]]:
    """构建"参考视频 → 时序稳定深度视频"的工具工作流。

    video_filename 必须是已上传到 ComfyUI input 目录的文件名。
    resolution 为 DA3 推理分辨率（最长边，14 的倍数），输出会回升到原分辨率。
    """
    capped = max(5, int(frame_cap))
    safe_resolution = min(2520, max(140, int(resolution) // 14 * 14))
    return {
        "1": {
            "inputs": {
                "video": video_filename,
                "force_rate": int(fps),
                "custom_width": 0,
                "custom_height": 0,
                "frame_load_cap": capped,
                "skip_first_frames": 0,
                "select_every_nth": 1,
            },
            "class_type": "VHS_LoadVideo",
            "_meta": {"title": "读取参考视频"},
        },
        "2": {
            "inputs": {"model_name": DA3_MODEL_FILENAME, "weight_dtype": "default"},
            "class_type": "LoadDA3Model",
            "_meta": {"title": "加载 DA3 模型"},
        },
        "3": {
            "inputs": {
                "da3_model": ["2", 0],
                "image": ["1", 0],
                "resolution": safe_resolution,
                "resize_method": "lower_bound_resize",
                "mode": "mono",
            },
            "class_type": "DA3Inference",
            "_meta": {"title": "深度推理"},
        },
        "4": {
            "inputs": {
                "da3_geometry": ["3", 0],
                "output": "depth",
                "output.normalization": "v2_style",
                "output.apply_sky_clip": False,
            },
            "class_type": "DA3Render",
            "_meta": {"title": "渲染深度图"},
        },
        DEPTH_OUTPUT_NODE: {
            "inputs": {
                "images": ["4", 0],
                "frame_rate": int(fps),
                "loop_count": 0,
                "filename_prefix": "video/zly_depth_extract",
                "format": "video/h264-mp4",
                "pix_fmt": "yuv420p",
                "crf": 20,
                "save_metadata": True,
                "save_output": True,
                "pingpong": False,
            },
            "class_type": "VHS_VideoCombine",
            "_meta": {"title": "保存深度视频"},
        },
    }
