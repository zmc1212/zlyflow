# -*- coding: utf-8 -*-
"""参考片拉片的 ffmpeg 工具集：探测、分镜切分、关键帧与片段裁剪。

仅依赖本机 ffmpeg/ffprobe（与 director_export 共用查找逻辑），不引入新 Python 依赖。
所有函数对无效输入抛出 VideoAnalysisError，由调用方转成 4xx/操作错误。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class VideoAnalysisError(RuntimeError):
    """ffmpeg 缺失、视频不可读或分镜失败。"""


@dataclass(frozen=True)
class VideoProbe:
    width: int
    height: int
    fps: float
    duration: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "fps": round(self.fps, 3),
            "durationSec": round(self.duration, 3),
        }


@dataclass(frozen=True)
class Segment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _find_binary(binary: str) -> str:
    from .director_export import find_ffmpeg

    resolved = find_ffmpeg(binary)
    if not resolved:
        raise VideoAnalysisError(f"未找到 {binary}，请安装 ffmpeg 并加入 PATH 后重试。")
    return resolved


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as error:
        raise VideoAnalysisError("未找到 ffmpeg/ffprobe，请先安装并加入 PATH。") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error))[-600:]
        raise VideoAnalysisError(f"ffmpeg 处理失败：{detail}") from error
    return completed.stdout or ""


def probe_video(path: Path) -> VideoProbe:
    """读取视频分辨率、帧率与时长。"""
    ffprobe = _find_binary("ffprobe")
    output = _run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate:format=duration",
        "-of", "json", str(path),
    ])
    try:
        payload = json.loads(output or "{}")
    except json.JSONDecodeError as error:
        raise VideoAnalysisError("ffprobe 返回内容无法解析。") from error
    streams = [s for s in payload.get("streams") or [] if s.get("width")]
    if not streams:
        raise VideoAnalysisError("视频文件不包含可读的视频轨。")
    stream = streams[0]
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise VideoAnalysisError("视频分辨率无效。")
    rate_raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    try:
        numerator, _, denominator = str(rate_raw).partition("/")
        fps = float(numerator) / float(denominator or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        fps = 0.0
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if fps <= 0 or duration <= 0:
        raise VideoAnalysisError("视频帧率或时长无效，无法用于拉片。")
    return VideoProbe(width=width, height=height, fps=fps, duration=duration)


def detect_scenes(
    path: Path,
    *,
    threshold: float = 0.35,
    min_duration: float = 1.0,
    max_duration: float = 20.0,
) -> list[Segment]:
    """按镜头切换点切分视频，返回成段的 (start, end) 列表。

    使用 ffmpeg scene 检测：低于 min_duration 的相邻段合并，超过 max_duration 的段按
    max_duration 均分（保证每镜都在生成模型能力范围内）。
    """
    ffmpeg = _find_binary("ffmpeg")
    output = _run([
        ffmpeg, "-hide_banner", "-i", str(path),
        "-vf", f"select='gt(scene,{max(0.05, min(0.95, threshold))})',showinfo",
        "-an", "-f", "null", "-",
    ])
    boundaries: list[float] = [0.0]
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("[Parsed_showinfo"):
            continue
        marker = "pts_time:"
        index = line.find(marker)
        if index < 0:
            continue
        raw = line[index + len(marker):].split("]")[0].split(" ")[0]
        try:
            time_value = float(raw)
        except ValueError:
            continue
        if time_value > boundaries[-1] + 0.2:
            boundaries.append(time_value)
    duration = probe_video(path).duration
    if boundaries[-1] < duration - 0.2:
        boundaries.append(duration)
    segments = [
        Segment(start=float(start), end=float(end))
        for start, end in zip(boundaries, boundaries[1:])
    ]
    return _normalize_segments(segments, duration, min_duration=min_duration, max_duration=max_duration)


def fixed_segments(duration: float, segment_seconds: float, *, min_duration: float = 1.0) -> list[Segment]:
    """按固定秒数切段，末段不足 min_duration 时并入前一段。"""
    length = max(2.0, float(segment_seconds))
    if duration <= 0:
        return []
    bounds: list[float] = []
    cursor = 0.0
    while cursor < duration - 1e-3:
        bounds.append(round(min(cursor, duration), 3))
        cursor += length
    if not bounds:
        bounds = [0.0]
    bounds.append(duration)
    segments = [
        Segment(start=float(start), end=float(end))
        for start, end in zip(bounds, bounds[1:])
    ]
    merged: list[Segment] = []
    for segment in segments:
        if segment.duration < min_duration and merged:
            previous = merged[-1]
            merged[-1] = Segment(start=previous.start, end=segment.end)
            continue
        merged.append(segment)
    return merged


def _normalize_segments(
    segments: list[Segment],
    duration: float,
    *,
    min_duration: float,
    max_duration: float,
) -> list[Segment]:
    merged: list[Segment] = []
    for segment in segments:
        if segment.duration < min_duration and merged:
            previous = merged[-1]
            merged[-1] = Segment(start=previous.start, end=segment.end)
            continue
        merged.append(segment)
    if not merged:
        return [Segment(start=0.0, end=duration)]
    normalized: list[Segment] = []
    for segment in merged:
        if segment.duration <= max_duration:
            normalized.append(segment)
            continue
        pieces = int(segment.duration // max_duration) + 1
        step = segment.duration / pieces
        for index in range(pieces):
            start = segment.start + index * step
            end = segment.start + (index + 1) * step if index < pieces - 1 else segment.end
            normalized.append(Segment(start=start, end=end))
    return normalized


def extract_keyframes(
    path: Path,
    *,
    times: list[float],
    dest_dir: Path,
    stem: str,
) -> list[Path]:
    """在指定时间点各抽一帧 JPG，返回按输入顺序的文件列表。"""
    ffmpeg = _find_binary("ffmpeg")
    dest_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for index, time_value in enumerate(times):
        dest = dest_dir / f"{stem}_{index}.jpg"
        _run([
            ffmpeg, "-y", "-ss", f"{max(0.0, float(time_value)):.3f}", "-i", str(path),
            "-frames:v", "1", "-q:v", "3", str(dest),
        ])
        if dest.is_file() and dest.stat().st_size > 0:
            outputs.append(dest)
    return outputs


def cut_segment(
    path: Path,
    *,
    start: float,
    end: float,
    dest: Path,
) -> Path:
    """精确裁剪 (start, end] 片段，重编码为 h264/yuv420p 以保证时间轴准确。"""
    ffmpeg = _find_binary("ffmpeg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.2, float(end) - float(start))
    pending = dest.with_name(f".{dest.stem}.{dest.suffix}.tmp")
    try:
        _run([
            ffmpeg, "-y", "-ss", f"{max(0.0, float(start)):.3f}", "-i", str(path),
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-an", str(pending),
        ])
        pending.replace(dest)
    finally:
        pending.unlink(missing_ok=True)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise VideoAnalysisError("片段裁剪失败，请检查源视频。")
    return dest
