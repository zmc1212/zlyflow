"""Bound the pose-extraction input to the selected window without changing graph node IDs."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .director_export import find_ffmpeg
from .video_analysis import VideoAnalysisError, probe_video


def validate_motion_video(path: Path, duration: str) -> None:
    try:
        probe = probe_video(path)
    except (VideoAnalysisError, OSError, ValueError) as error:
        raise ValueError("动作参考视频无法读取，请使用包含视频画面的 MP4 / MOV / WebM 文件。") from error
    required = float(duration.removesuffix("s"))
    # Allow container/timebase rounding, not a materially shorter motion sequence.
    if probe.duration + 0.1 < required:
        raise ValueError(
            f"动作参考视频只有 {probe.duration:.1f} 秒，不能生成 {required:.0f} 秒动作；"
            "请选择更短的生成时长或上传更长的视频。"
        )


def prepare_motion_video(source: Path, destination: Path, *, fps: int, length: int) -> Path:
    ffmpeg = find_ffmpeg("ffmpeg")
    if not ffmpeg:
        raise ValueError("动作迁移需要 FFmpeg，请安装后再试。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the motion's aspect ratio, cap pose-extraction cost and pad only
    # the fractional H3 frame-grid tail (5 seconds -> 124 frames at 24fps).
    filters = (
        f"fps={fps},scale=w='min(1280,iw)':h='min(1280,ih)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2,"
        "tpad=stop_mode=clone:stop_duration=0.75"
    )
    try:
        subprocess.run(
            [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
             "-an", "-vf", filters, "-frames:v", str(length), "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(destination)],
            check=True, capture_output=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as error:
        destination.unlink(missing_ok=True)
        raise ValueError("动作参考视频预处理失败，请换用标准 MP4 文件后重试。") from error
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ValueError("动作参考视频预处理没有输出可读视频。")
    return destination
