from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import URLError
from .config import settings
from .director_export import (
    DirectorExportError,
    FfmpegRunner,
    MuxClip,
    SystemFfmpegRunner,
    build_ass_subtitles,
    default_subtitle_style,
    ffmpeg_available,
)
from .director_jobs import materialize_job_output_file
from .resource_storage import resource_object_url

COMPOSE_RESOLUTIONS = {
    "1280x720": (1280, 720),
    "1920x1080": (1920, 1080),
}
DEFAULT_RESOLUTION = "1280x720"


class XiajiComposeError(ValueError):
    """Invalid or failed episode compose request."""


@dataclass
class ComposeClip:
    beat_id: str
    sequence: int
    title: str
    dialogue: str
    duration_sec: float
    video_path: Path
    audio_path: Path | None
    start_sec: float = 0.0


def beat_can_make_video(beat: dict[str, Any] | None) -> bool:
    if not isinstance(beat, dict):
        return False
    if str(beat.get("kind") or "") == "scene_heading" and not (beat.get("action") or beat.get("heading")):
        return False
    return True


def video_beats(episode: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (episode.get("beats") or []) if beat_can_make_video(item)]


def beat_has_video(beat: dict[str, Any] | None) -> bool:
    return isinstance(beat, dict) and bool(str(beat.get("video_url") or "").strip())


def compose_shot_beats(episode: dict[str, Any]) -> list[dict[str, Any]]:
    """Action/dialogue clips listed in compose UI. Scene headings are cards, not required clips."""
    return [item for item in video_beats(episode) if str(item.get("kind") or "") != "scene_heading"]


def compose_concat_beats(episode: dict[str, Any]) -> list[dict[str, Any]]:
    """Beats that actually mux: any kind with a finished video, in script order."""
    ordered = [item for item in (episode.get("beats") or []) if beat_has_video(item)]
    ordered.sort(key=lambda item: int(item.get("sequence") or 0))
    return ordered


def require_audio_for_project(project: dict[str, Any] | None) -> bool:
    settings_payload = (project or {}).get("settings") if isinstance(project, dict) else None
    if not isinstance(settings_payload, dict):
        return False
    return str(settings_payload.get("spine_template") or "").strip() == "narrated"


def compose_filename(episode_number: int) -> str:
    return f"ep{max(1, int(episode_number or 1)):03d}_final.mp4"


def parse_resolution(value: str | None) -> tuple[str, int, int]:
    raw = str(value or DEFAULT_RESOLUTION).strip()
    if raw not in COMPOSE_RESOLUTIONS:
        raw = DEFAULT_RESOLUTION
    width, height = COMPOSE_RESOLUTIONS[raw]
    return raw, width, height


def coerce_duration(*values: Any, default: float = 5.0) -> float:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        try:
            duration = float(text)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            return duration
    return default


def estimated_duration_sec(episode: dict[str, Any]) -> float:
    total = 0.0
    for beat in compose_concat_beats(episode):
        total += coerce_duration(beat.get("video_duration"))
    return round(total, 3)


def compose_episode_ready(episode: dict[str, Any], *, require_audio: bool) -> bool:
    clips = compose_concat_beats(episode)
    if not clips:
        return False
    if require_audio:
        return all(str(item.get("audio_url") or "").strip() for item in clips)
    return True


def compose_blockers(episode: dict[str, Any], *, require_audio: bool) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for beat in compose_shot_beats(episode):
        stages: list[str] = []
        has_video = beat_has_video(beat)
        if not has_video:
            stages.append("video")
        if require_audio and has_video and not str(beat.get("audio_url") or "").strip():
            stages.append("audio")
        if stages:
            missing.append(
                {
                    "beat_id": str(beat.get("id") or ""),
                    "sequence": int(beat.get("sequence") or 0),
                    "stages": stages,
                }
            )
    return missing


def format_srt_time(seconds: float) -> str:
    total = max(0.0, seconds)
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = int(total % 60)
    millis = int(round((total - int(total)) * 1000))
    if millis >= 1000:
        millis = 0
        secs += 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt_content(clips: list[ComposeClip]) -> str:
    lines: list[str] = []
    index = 0
    for clip in clips:
        text = (clip.dialogue or "").strip()
        if not text:
            continue
        index += 1
        start = format_srt_time(clip.start_sec)
        end = format_srt_time(clip.start_sec + clip.duration_sec)
        lines.append(str(index))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def work_dir_for(episode_id: str) -> Path:
    path = settings.staging_dir / "xiaji-compose" / episode_id / f"work-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download_url(url: str, dest: Path, timeout: int = 120) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            dest.write_bytes(response.read())
    except (OSError, URLError, TimeoutError, ValueError) as error:
        dest.unlink(missing_ok=True)
        raise XiajiComposeError(f"无法下载镜头媒体：{error}") from error
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise XiajiComposeError("下载的镜头媒体是空的")
    return dest


def _local_or_download(url: str, dest: Path) -> Path | None:
    text = str(url or "").strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_file():
        return candidate
    if text.startswith("http://") or text.startswith("https://"):
        return _download_url(text, dest)
    return None


def materialize_beat_video(
    beat: dict[str, Any],
    store: Any,
    *,
    resource_storage: Any | None,
    dest_dir: Path,
) -> Path:
    job_id = str(beat.get("video_job_id") or "").strip()
    if job_id and store is not None:
        try:
            job = store.get(job_id)
        except KeyError:
            job = None
        if job:
            local = materialize_job_output_file(job, resource_storage=resource_storage, kind="video")
            if local is not None and local.is_file():
                return local
    dest = dest_dir / f"{beat.get('id') or uuid.uuid4().hex[:8]}.mp4"
    local = _local_or_download(str(beat.get("video_url") or ""), dest)
    if local is not None:
        return local
    raise XiajiComposeError(f"镜头 {beat.get('sequence') or ''} 没有可合成的视频文件")


def materialize_beat_audio(
    beat: dict[str, Any],
    *,
    resource_storage: Any | None,
    dest_dir: Path,
) -> Path | None:
    url = str(beat.get("audio_url") or "").strip()
    if not url:
        return None
    dest = dest_dir / f"{beat.get('id') or uuid.uuid4().hex[:8]}.mp3"
    return _local_or_download(url, dest)


def video_has_audio_stream(path: Path, runner: FfmpegRunner) -> bool:
    probe = getattr(runner, "probe_has_audio", None)
    if callable(probe):
        try:
            return bool(probe(path))
        except Exception:
            return False
    if not isinstance(runner, SystemFfmpegRunner):
        return False
    try:
        _ffmpeg, ffprobe = runner.require()
    except DirectorExportError:
        return False
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, FileNotFoundError):
        return False
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return False
    streams = payload.get("streams") if isinstance(payload, dict) else None
    return bool(streams)


def _prepare_clip(
    clip: ComposeClip,
    dest: Path,
    runner: FfmpegRunner,
    *,
    width: int,
    height: int,
) -> Path:
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=yuv420p"
    )
    args: list[str] = ["-i", str(clip.video_path)]
    if clip.audio_path is not None and clip.audio_path.is_file():
        args.extend(
            [
                "-i",
                str(clip.audio_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
            ]
        )
    elif video_has_audio_stream(clip.video_path, runner):
        args.extend(["-map", "0:v:0", "-map", "0:a:0"])
    else:
        args.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=stereo",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
            ]
        )
    args.extend(
        [
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(dest),
        ]
    )
    try:
        runner.run(args)
    except DirectorExportError as error:
        raise XiajiComposeError(str(error)) from error
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise XiajiComposeError(f"镜头 {clip.sequence} 转码失败")
    return dest


def _concat_clips(paths: list[Path], dest: Path, runner: FfmpegRunner) -> Path:
    concat_list = dest.parent / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in paths),
        encoding="utf-8",
    )
    try:
        runner.run(["-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(dest)])
    except DirectorExportError:
        runner.run(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(dest),
            ]
        )
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise XiajiComposeError("拼接成片失败")
    return dest


def _burn_subtitles(
    source: Path,
    clips: list[ComposeClip],
    dest: Path,
    runner: FfmpegRunner,
    *,
    width: int,
    height: int,
) -> Path:
    mux_clips = [
        MuxClip(
            shot_id=item.beat_id,
            shot_number=item.sequence,
            title=item.title,
            dialogue=item.dialogue,
            duration_sec=item.duration_sec,
            video_path=item.video_path,
            start_sec=item.start_sec,
        )
        for item in clips
    ]
    ass_path = dest.parent / "captions.ass"
    ass_path.write_text(
        build_ass_subtitles(mux_clips, default_subtitle_style(), width=width, height=height),
        encoding="utf-8",
    )
    escaped = ass_path.as_posix().replace("\\", "/").replace(":", r"\:")
    try:
        runner.run(["-i", str(source), "-vf", f"ass='{escaped}'", "-c:a", "copy", str(dest)])
    except DirectorExportError as error:
        raise XiajiComposeError(str(error)) from error
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    return source


def _upload_film(storage: Any, filename: str, path: Path) -> tuple[str, str]:
    if storage is None:
        raise XiajiComposeError("媒体存储未配置")
    stored = storage.store_bytes("xiaji-compose", filename, path.read_bytes())
    key = str(getattr(stored, "key", "") or "")
    url = resource_object_url(storage, key) or ""
    if not url:
        getter = getattr(storage, "download_url", None)
        if callable(getter):
            url = str(getter(key) or "")
    if not url:
        raise XiajiComposeError("无法生成成片地址")
    return url, key


def compose_episode_film(
    episode: dict[str, Any],
    store: Any,
    *,
    resource_storage: Any,
    resolution: str,
    add_subtitles: bool,
    runner: FfmpegRunner | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    ffmpeg = runner or SystemFfmpegRunner()
    if isinstance(ffmpeg, SystemFfmpegRunner):
        try:
            ffmpeg.require()
        except DirectorExportError as error:
            raise XiajiComposeError(str(error)) from error
    label, width, height = parse_resolution(resolution)
    beats = [item for item in compose_concat_beats(episode) if str(item.get("video_url") or "").strip()]
    if not beats:
        raise XiajiComposeError("没有可合成的镜头，请先生成脚本和视频")
    work_dir = work_dir_for(str(episode.get("id") or "episode"))
    clips: list[ComposeClip] = []
    cursor = 0.0
    try:
        prepared: list[Path] = []
        for index, beat in enumerate(beats):
            if callable(progress):
                progress(int((index / max(1, len(beats))) * 80))
            video_path = materialize_beat_video(beat, store, resource_storage=resource_storage, dest_dir=work_dir)
            audio_path = materialize_beat_audio(beat, resource_storage=resource_storage, dest_dir=work_dir)
            duration = coerce_duration(beat.get("video_duration"))
            clip = ComposeClip(
                beat_id=str(beat.get("id") or ""),
                sequence=int(beat.get("sequence") or index + 1),
                title=str(beat.get("heading") or beat.get("action") or f"镜头 {index + 1}")[:80],
                dialogue=str(beat.get("dialogue") or "").strip(),
                duration_sec=duration,
                video_path=video_path,
                audio_path=audio_path,
                start_sec=cursor,
            )
            dest = work_dir / f"beat_{clip.sequence:04d}.mp4"
            prepared_path = _prepare_clip(clip, dest, ffmpeg, width=width, height=height)
            probed = ffmpeg.probe_duration(prepared_path)
            if probed > 0:
                clip.duration_sec = probed
            clip.video_path = prepared_path
            clips.append(clip)
            prepared.append(prepared_path)
            cursor += clip.duration_sec
        if callable(progress):
            progress(85)
        concat_path = work_dir / "concat.mp4"
        current = _concat_clips(prepared, concat_path, ffmpeg)
        if add_subtitles:
            burned = work_dir / "burned.mp4"
            current = _burn_subtitles(current, clips, burned, ffmpeg, width=width, height=height)
        if callable(progress):
            progress(95)
        filename = compose_filename(int(episode.get("number") or 1))
        url, key = _upload_film(resource_storage, filename, current)
        probed = ffmpeg.probe_duration(current)
        duration = probed if probed > 0 else round(cursor, 3)
        return {
            "compose_status": "succeeded",
            "compose_url": url,
            "compose_key": key,
            "compose_error": None,
            "compose_resolution": label,
            "compose_add_subtitles": "1" if add_subtitles else "0",
            "compose_duration_sec": str(round(duration, 3)),
            "compose_at": datetime.now(timezone.utc).isoformat(),
            "compose_filename": filename,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def resolve_compose_file(episode: dict[str, Any], resource_storage: Any | None) -> Path | None:
    key = str(episode.get("compose_key") or "").strip()
    if key and resource_storage is not None:
        resolve = getattr(resource_storage, "resolve", None)
        if callable(resolve):
            path = resolve(key)
            if path is not None and Path(path).is_file():
                return Path(path)
    url = str(episode.get("compose_url") or "").strip()
    candidate = Path(url) if url else None
    if candidate is not None and candidate.is_file():
        return candidate
    return None


def load_compose_bytes(episode: dict[str, Any], resource_storage: Any | None) -> bytes:
    path = resolve_compose_file(episode, resource_storage)
    if path is not None:
        return path.read_bytes()
    url = str(episode.get("compose_url") or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                data = response.read()
        except (OSError, URLError, TimeoutError, ValueError) as error:
            raise XiajiComposeError(f"无法下载成片：{error}") from error
        if data:
            return data
    raise XiajiComposeError("成片不存在")


def build_episode_zip(
    episode: dict[str, Any],
    store: Any,
    *,
    resource_storage: Any | None,
    srt_text: str,
) -> bytes:
    buffer = BytesIO()
    number = int(episode.get("number") or 1)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        work = settings.staging_dir / "xiaji-compose" / str(episode.get("id") or "episode") / "zip"
        work.mkdir(parents=True, exist_ok=True)
        try:
            for beat in compose_concat_beats(episode):
                try:
                    video = materialize_beat_video(beat, store, resource_storage=resource_storage, dest_dir=work)
                except XiajiComposeError:
                    continue
                archive.write(video, f"video/beat_{int(beat.get('sequence') or 0):02d}{video.suffix or '.mp4'}")
            try:
                film = load_compose_bytes(episode, resource_storage)
            except XiajiComposeError:
                film = b""
            if film:
                archive.writestr(compose_filename(number), film)
            if srt_text.strip():
                archive.writestr(f"ep{number:03d}.srt", srt_text.encode("utf-8"))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return buffer.getvalue()


def clips_for_subtitles(episode: dict[str, Any]) -> list[ComposeClip]:
    clips: list[ComposeClip] = []
    cursor = 0.0
    dummy = Path(".")
    for index, beat in enumerate(compose_concat_beats(episode)):
        duration = coerce_duration(beat.get("video_duration"))
        clips.append(
            ComposeClip(
                beat_id=str(beat.get("id") or ""),
                sequence=int(beat.get("sequence") or index + 1),
                title=str(beat.get("heading") or beat.get("action") or f"镜头 {index + 1}"),
                dialogue=str(beat.get("dialogue") or "").strip(),
                duration_sec=duration,
                video_path=dummy,
                audio_path=None,
                start_sec=cursor,
            )
        )
        cursor += duration
    return clips


def public_compose_fields(episode: dict[str, Any]) -> dict[str, Any]:
    status = str(episode.get("compose_status") or "idle") or "idle"
    return {
        "compose_status": status,
        "compose_url": episode.get("compose_url") or None,
        "compose_error": episode.get("compose_error"),
        "compose_resolution": episode.get("compose_resolution") or DEFAULT_RESOLUTION,
        "compose_add_subtitles": str(episode.get("compose_add_subtitles") or "1") != "0",
        "compose_duration_sec": coerce_duration(episode.get("compose_duration_sec"), default=0.0) or None,
        "compose_at": episode.get("compose_at"),
        "compose_filename": compose_filename(int(episode.get("number") or 1)),
        "compose_progress": int(float(episode.get("compose_progress") or 0) or 0),
    }


def ffmpeg_ready() -> dict[str, Any]:
    return ffmpeg_available()
