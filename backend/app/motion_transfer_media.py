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


def has_audio_stream(path: Path) -> bool:
    """ffprobe 探测源文件是否含音轨;无法探测时按无音轨处理,避免误接 AV latent 链。"""
    ffprobe = find_ffmpeg("ffprobe")
    if not ffprobe:
        return False
    try:
        completed = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
            capture_output=True, timeout=20, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return "audio" in completed.stdout.decode(errors="ignore")


def prepare_motion_reference_video(
    source: Path, destination: Path, *, fps: int, length: int, width: int, height: int,
) -> tuple[Path, bool]:
    """多人参考视频版预处理:等比缩放并居中补边到生成画布、对齐帧率与帧数。

    与 prepare_motion_video 不同,这里必须保留原片音轨(重编码为 aac),供
    VAEEncodeAudio → LTXVConcatAVLatent 链路还原原声与口型节奏;返回
    (输出路径, 是否含音轨),调用方据此决定是否开启音频链。
    """
    ffmpeg = find_ffmpeg("ffmpeg")
    if not ffmpeg:
        raise ValueError("多人动作迁移需要 FFmpeg，请安装后再试。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with_audio = has_audio_stream(source)
    filters = (
        f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        "tpad=stop_mode=clone:stop_duration=0.75"
    )
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:v:0", "-vf", filters, "-frames:v", str(length),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
    ]
    if with_audio:
        command += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-an"]
    command += ["-movflags", "+faststart", str(destination)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as error:
        destination.unlink(missing_ok=True)
        raise ValueError("动作参考视频预处理失败，请换用标准 MP4 文件后重试。") from error
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ValueError("动作参考视频预处理没有输出可读视频。")
    return destination, with_audio


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
