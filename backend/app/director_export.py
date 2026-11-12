from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from .config import settings
from .director_takes import FAILED_TAKE_STATUSES, preferred_usable_take
from .models import JobStatus


FAILED_SHOT_STATUSES = set(FAILED_TAKE_STATUSES)
SUCCEEDED_SHOT_STATUSES = {JobStatus.SUCCEEDED.value, JobStatus.PARTIAL.value, "succeeded", "partial"}


class DirectorExportError(ValueError):
    """Invalid export / TTS / mux request."""


@dataclass
class MuxClip:
    shot_id: str
    shot_number: int
    title: str
    dialogue: str
    duration_sec: float
    video_path: Path
    tts_path: Path | None = None
    start_sec: float = 0.0


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _float(value: Any, default: float, *, minimum: float = 0.0, maximum: float = 100.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def find_ffmpeg(binary: str = "ffmpeg") -> str | None:
    found = shutil.which(binary)
    if found:
        return found
    extra = [
        Path(r"C:\ffmpeg\bin") / f"{binary}.exe",
        Path(r"C:\Program Files\ffmpeg\bin") / f"{binary}.exe",
        Path(r"C:\Program Files\ffmpeg\ffmpeg-8.0-full_build\bin") / f"{binary}.exe",
        Path("/usr/bin") / binary,
        Path("/usr/local/bin") / binary,
        Path("/opt/homebrew/bin") / binary,
    ]
    for candidate in extra:
        if candidate.is_file():
            return str(candidate)
    return None


class SystemFfmpegRunner:
    def __init__(self, ffmpeg: str | None = None, ffprobe: str | None = None) -> None:
        self.ffmpeg = ffmpeg or find_ffmpeg("ffmpeg")
        self.ffprobe = ffprobe or find_ffmpeg("ffprobe")

    def require(self) -> tuple[str, str]:
        if not self.ffmpeg or not self.ffprobe:
            raise DirectorExportError(
                "未找到 ffmpeg/ffprobe。请安装 ffmpeg 并加入 PATH 后重试。成片合成不会改动视频服务端口。"
            )
        return self.ffmpeg, self.ffprobe

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        ffmpeg, _probe = self.require()
        command = [ffmpeg, "-y", *args]
        try:
            return subprocess.run(
                command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or str(error))[-800:]
            raise DirectorExportError(f"ffmpeg 合成失败：{detail}") from error
        except FileNotFoundError as error:
            raise DirectorExportError("未找到 ffmpeg，请先安装并加入 PATH。") from error

    def probe_duration(self, path: Path) -> float:
        _ffmpeg, ffprobe = self.require()
        try:
            completed = subprocess.run(
                [
                    ffprobe, "-v", "error", "-show_entries", "format=duration",
                    "-of", "json", str(path),
                ],
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return 0.0
        try:
            payload = json.loads(completed.stdout or "{}")
            return max(0.0, float((payload.get("format") or {}).get("duration") or 0))
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0.0


def recipe_audio_dir(owner_user_id: str, project_id: str) -> Path:
    return settings.uploads_dir / owner_user_id / project_id / "audio"


def recipe_mux_dir(project_id: str) -> Path:
    return settings.staging_dir / "director-mux" / project_id


def _shot_status(shot: dict[str, Any]) -> str:
    return _text(shot.get("status"), "idle").lower()


def _take_for_mux(shot: dict[str, Any]) -> dict[str, Any] | None:
    return preferred_usable_take(shot)


def shot_is_muxable(shot: dict[str, Any]) -> bool:
    take = _take_for_mux(shot)
    if take is not None:
        return True
    if _shot_status(shot) in FAILED_SHOT_STATUSES:
        return False
    if _shot_status(shot) in SUCCEEDED_SHOT_STATUSES and (shot.get("outputVideoUrl") or shot.get("jobId")):
        return True
    return False


def timeline_duration_sec(clips: list[MuxClip]) -> float:
    return round(sum(max(0.0, clip.duration_sec) for clip in clips), 3)


def _fcpx_time(seconds: float, fps: int = 24) -> str:
    frames = int(round(max(0.0, seconds) * fps))
    return f"{frames}/{fps}s"


def build_fcpxml(
    recipe: dict[str, Any],
    clips: list[MuxClip],
    *,
    project_title: str,
) -> str:
    fps = int(recipe.get("fps") or 24) or 24
    width = int(recipe.get("width") or 1920)
    height = int(recipe.get("height") or 1080)
    total = timeline_duration_sec(clips)
    resources = [
        f'    <format id="r1" name="FFVideoFormat{width}x{height}p{fps}" frameDuration="1/{fps}s" width="{width}" height="{height}"/>'
    ]
    spine: list[str] = []
    audio_resources: list[str] = []
    for index, clip in enumerate(clips, start=2):
        asset_id = f"r{index}"
        src = clip.video_path.resolve().as_uri()
        duration = _fcpx_time(clip.duration_sec, fps)
        resources.append(
            f'    <asset id="{asset_id}" name="{xml_escape(clip.title)}" start="0s" duration="{duration}" '
            f'hasVideo="1" hasAudio="1">\n'
            f'      <media-rep kind="original-media" src="{xml_escape(src)}"/>\n'
            f"    </asset>"
        )
        spine.append(
            f'            <asset-clip ref="{asset_id}" offset="{_fcpx_time(clip.start_sec, fps)}" '
            f'name="{xml_escape(clip.title)}" duration="{duration}" start="0s">'
        )
        if clip.dialogue:
            spine.append(
                f'              <title lane="1" offset="0s" name="Dialogue" duration="{duration}">'
                f'<text>{xml_escape(clip.dialogue)}</text></title>'
            )
        if clip.tts_path and clip.tts_path.is_file():
            audio_id = f"ra{index}"
            audio_resources.append(
                f'    <asset id="{audio_id}" name="{xml_escape(clip.title)} TTS" start="0s" duration="{duration}" '
                f'hasVideo="0" hasAudio="1">\n'
                f'      <media-rep kind="original-media" src="{xml_escape(clip.tts_path.resolve().as_uri())}"/>\n'
                f"    </asset>"
            )
            spine.append(
                f'              <asset-clip ref="{audio_id}" lane="-1" offset="0s" duration="{duration}" start="0s"/>'
            )
        spine.append("            </asset-clip>")
    resources.extend(audio_resources)
    audio = recipe.get("audio") if isinstance(recipe.get("audio"), dict) else {}
    bgm_path = Path(str(audio.get("bgmPath") or "")) if audio.get("bgmPath") else None
    connected = ""
    if bgm_path and bgm_path.is_file():
        resources.append(
            f'    <asset id="rb1" name="BGM" start="0s" duration="{_fcpx_time(total, fps)}" hasVideo="0" hasAudio="1">\n'
            f'      <media-rep kind="original-media" src="{xml_escape(bgm_path.resolve().as_uri())}"/>\n'
            f"    </asset>"
        )
        connected = (
            f'\n            <asset-clip ref="rb1" lane="-2" offset="0s" name="BGM" '
            f'duration="{_fcpx_time(total, fps)}" start="0s"/>'
        )
    title = xml_escape(project_title or "导演成片")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE fcpxml>\n"
        '<fcpxml version="1.11">\n'
        "  <resources>\n"
        + "\n".join(resources)
        + "\n  </resources>\n"
        "  <library>\n"
        f'    <event name="{title}">\n'
        f'      <project name="{title}">\n'
        f'        <sequence format="r1" duration="{_fcpx_time(total, fps)}">\n'
        "          <spine>\n"
        + "\n".join(spine)
        + connected
        + "\n          </spine>\n"
        "        </sequence>\n"
        "      </project>\n"
        "    </event>\n"
        "  </library>\n"
        "</fcpxml>\n"
    )

    return dest if dest.is_file() else None
