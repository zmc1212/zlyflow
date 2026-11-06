"""KEEP video face repair protocol; the registry owns all parameter defaults."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .video_analysis import VideoAnalysisError, probe_video

KEEP_NODE = "ZLYKeepFaceRestore"
KEEP_OUTPUT_NODE = "1"
KEEP_OUTPUT_LABEL = "人脸高清修复"
KEEP_MODEL = "KEEP-b76feb75.pth"
KEEP_DETECTOR = "detection_Resnet50_Final.pth"
KEEP_PARSER = "parsing_parsenet.pth"
KEEP_DEFAULT_PROMPT = "修复选中的视频人脸，保留其他画面与原声"
KEEP_MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def normalize_face_point(value: Any) -> str:
    try:
        point = json.loads(value) if isinstance(value, str) else value
        if not isinstance(point, dict) or set(point) != {"x", "y"}:
            raise ValueError
        for key in ("x", "y"):
            number = point[key]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not 0 <= number <= 1 or not math.isfinite(number):
                raise ValueError
        return json.dumps({"x": float(point["x"]), "y": float(point["y"])}, separators=(",", ":"))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("请先在视频首帧点击要修复的人脸中心。") from error


def validate_face_restore_sources(paths: list[str], duration: str) -> dict[str, int | float]:
    try:
        base = probe_video(Path(paths[0]))
        if any(not math.isfinite(value) or value <= 0 for value in (base.width, base.height, base.fps, base.duration)):
            raise ValueError("视频尺寸或帧率无法读取，请换用标准 MP4 文件。")
        if len(paths) > 1:
            original = probe_video(Path(paths[1]))
            if any(not math.isfinite(value) or value <= 0 for value in (original.width, original.height, original.fps, original.duration)):
                raise ValueError("高清前原片无法读取，请换用包含视频画面的完整文件。")
            if abs(original.width / original.height - base.width / base.height) > .01:
                raise ValueError("高清前原片与待修复视频的画面比例不同，请上传同一片段。")
            if abs(original.duration - base.duration) > max(.25, 2 / base.fps):
                raise ValueError("高清前原片与待修复视频的时长不同，请上传同一片段。")
        seconds = min(base.duration, 5) if duration == "5s" else base.duration
        return {"width": base.width, "height": base.height, "fps": base.fps,
                "frames": max(1, round(seconds * base.fps))}
    except (VideoAnalysisError, OSError, ZeroDivisionError) as error:
        raise ValueError("视频无法读取，请使用包含视频画面的 MP4 / MOV / WebM 文件。") from error


def build_keep_face_restore_workflow(base_video: str, source_video: str, options: dict[str, Any]) -> dict:
    point = json.loads(normalize_face_point(options.get("target_point")))
    return {KEEP_OUTPUT_NODE: {
        "class_type": KEEP_NODE,
        "inputs": {
            "video": base_video,
            "face_source_video": source_video,
            "point_x": point["x"], "point_y": point["y"],
            "duration": options["duration"], "preserve_audio": options["preserve_audio"],
            "model_name": options["model_name"], "detector_model": options["detector_model"],
            "parser_model": options["parser_model"], "chunk_length": options["chunk_length"],
            "overlap": options["overlap"], "landmark_sigma": options["landmark_sigma"],
            "filename_prefix": "ZLY_KEEP_FACE_RESTORE",
        },
    }}


def keep_missing_message(object_info: dict) -> str | None:
    node = object_info.get(KEEP_NODE)
    if not isinstance(node, dict):
        return "当前渲染机尚未安装人脸高清修复（KEEP）节点，请联系管理员安装后重试。"
    fields = node.get("input", {}).get("required", {})
    for name, filename in [("model_name", KEEP_MODEL), ("detector_model", KEEP_DETECTOR), ("parser_model", KEEP_PARSER)]:
        field = fields.get(name, [])
        choices = field[0] if field and isinstance(field[0], list) else (
            field[1].get("options", []) if len(field) > 1 and isinstance(field[1], dict) else []
        )
        if filename not in choices:
            return f"当前渲染机缺少人脸高清修复模型 {filename}，请联系管理员配置。"
    return None
