from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from xml.sax.saxutils import escape as xml_escape

from .config import settings
from .director_jobs import job_first_output_file, materialize_job_output_file
from .director_recipe import (
    default_audio_mix,
    default_subtitle_style,
    empty_export_state,
    flatten_recipe_shots,
    normalize_recipe_payload,
    normalize_voice_id,
)
from .director_takes import FAILED_TAKE_STATUSES, preferred_usable_take
from .llm_client import LlmError
from .models import JobStatus
from .storage import JobStore
from .tts_provider import DEFAULT_TTS_VOICE


FAILED_SHOT_STATUSES = set(FAILED_TAKE_STATUSES)
SUCCEEDED_SHOT_STATUSES = {JobStatus.SUCCEEDED.value, JobStatus.PARTIAL.value, "succeeded", "partial"}
ASS_ALIGN = {"top": 8, "center": 5, "bottom": 2}


class DirectorExportError(ValueError):
    """Invalid export / TTS / mux request."""


class FfmpegRunner(Protocol):
    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        ...

    def probe_duration(self, path: Path) -> float:
        ...


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
                "未找到 ffmpeg/ffprobe。请安装 ffmpeg 并加入 PATH 后重试。成片合成不会改动 ComfyUI 端口。"
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


def ffmpeg_available() -> dict[str, Any]:
    ffmpeg = find_ffmpeg("ffmpeg")
    ffprobe = find_ffmpeg("ffprobe")
    return {
        "ffmpeg": bool(ffmpeg and ffprobe),
        "ffmpeg_path": ffmpeg,
        "ffprobe_path": ffprobe,
    }


def recipe_audio_dir(owner_user_id: str, project_id: str) -> Path:
    return settings.uploads_dir / owner_user_id / project_id / "audio"


def recipe_mux_dir(project_id: str) -> Path:
    return settings.staging_dir / "director-mux" / project_id


def tts_public_url(project_id: str, shot_id: str) -> str:
    return f"/api/director/recipes/{project_id}/tts/{shot_id}"


def bgm_public_url(project_id: str) -> str:
    return f"/api/director/recipes/{project_id}/bgm"


def mux_public_url(project_id: str) -> str:
    return f"/api/director/recipes/{project_id}/mux"


def find_audio_file(directory: Path, stem: str) -> Path | None:
    if not directory.is_dir():
        return None
    matches = sorted(path for path in directory.glob(f"{stem}.*") if path.is_file())
    return matches[0] if matches else None


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


def eligible_mux_shots(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    return [shot for shot in flatten_recipe_shots(recipe) if isinstance(shot, dict) and shot_is_muxable(shot)]


def timeline_duration_sec(clips: list[MuxClip]) -> float:
    return round(sum(max(0.0, clip.duration_sec) for clip in clips), 3)


def _resolve_shot_video(
    shot: dict[str, Any],
    store: JobStore,
    *,
    resource_storage: Any | None = None,
) -> Path | None:
    take = _take_for_mux(shot)
    job_id = None
    if take is not None:
        job_id = take.get("jobId") or take.get("id")
        raw_path = _text(take.get("outputPath"))
        if raw_path:
            candidate = Path(raw_path)
            if candidate.is_file():
                return candidate
    job_id = job_id or shot.get("jobId")
    if job_id:
        try:
            job = store.get(str(job_id))
        except KeyError:
            job = None
        if job:
            local = materialize_job_output_file(job, resource_storage=resource_storage, kind="video")
            if local is None:
                local = job_first_output_file(job)
            if local is not None:
                return local
    for raw in (shot.get("outputPath"),):
        text = _text(raw)
        if text:
            candidate = Path(text)
            if candidate.is_file():
                return candidate
    return None


def build_mux_clips(
    recipe: dict[str, Any],
    store: JobStore,
    *,
    owner_user_id: str,
    project_id: str,
    resource_storage: Any | None = None,
) -> list[MuxClip]:
    clips: list[MuxClip] = []
    cursor = 0.0
    audio_dir = recipe_audio_dir(owner_user_id, project_id)
    for shot in eligible_mux_shots(recipe):
        video = _resolve_shot_video(shot, store, resource_storage=resource_storage)
        if video is None:
            raise DirectorExportError(f"镜头「{shot.get('title') or shot.get('id')}」没有可合成的本地视频文件")
        duration = _float(shot.get("durationSec", shot.get("duration_sec", 5)), 5.0, minimum=0.1, maximum=60.0)
        tts = find_audio_file(audio_dir, f"tts-{shot.get('id')}")
        clips.append(MuxClip(
            shot_id=str(shot.get("id") or ""),
            shot_number=int(shot.get("shotNumber") or len(clips) + 1),
            title=_text(shot.get("title")) or f"分镜 {len(clips) + 1}",
            dialogue=_text(shot.get("dialogue")),
            duration_sec=duration,
            video_path=video,
            tts_path=tts,
            start_sec=cursor,
        ))
        cursor += duration
    if not clips:
        raise DirectorExportError("没有可合成的镜头。失败、中断或未完成的镜头不会进入成片；请先批准成功 Take。")
    return clips


def _write_tts_file(dest: Path, audio: bytes) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for leftover in dest.parent.glob(f"{dest.stem}.*"):
        leftover.unlink(missing_ok=True)
    dest.write_bytes(audio)
    return dest


def generate_recipe_tts(
    recipe: dict[str, Any],
    tts_provider: Any,
    *,
    owner_user_id: str,
    project_id: str,
    shot_ids: list[str] | None = None,
    character_id: str | None = None,
    text: str | None = None,
) -> dict[str, Any]:
    recipe = normalize_recipe_payload(recipe)
    wanted = {item for item in (shot_ids or []) if item}
    audio_dir = recipe_audio_dir(owner_user_id, project_id)

    if character_id:
        character = next(
            (item for item in (recipe.get("characters") or []) if isinstance(item, dict) and item.get("id") == character_id),
            None,
        )
        if character is None:
            raise DirectorExportError("角色不存在")
        sample = (text or character.get("name") or "试听").strip() or "试听"
        voice = normalize_voice_id(character.get("voiceId"), gender=str(character.get("gender") or ""))
        audio = tts_provider.synthesize(sample, voice=voice)
        dest = audio_dir / f"voice-{character_id}.mp3"
        _write_tts_file(dest, audio)
        character["voiceId"] = voice
        character["voicePreviewUrl"] = f"/api/director/recipes/{project_id}/voices/{character_id}"
        character["ttsStatus"] = "succeeded"
        return recipe

    shots = flatten_recipe_shots(recipe)
    generated = 0
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        if wanted and shot.get("id") not in wanted:
            continue
        dialogue = _text(shot.get("dialogue"))
        if not dialogue:
            shot["ttsStatus"] = "idle"
            shot["ttsError"] = None
            continue
        speaker = _text(shot.get("speakerName"))
        voice = _text(shot.get("voiceId"))
        if not voice and speaker:
            for character in recipe.get("characters") or []:
                if isinstance(character, dict) and _text(character.get("name")) == speaker:
                    voice = normalize_voice_id(character.get("voiceId"), gender=str(character.get("gender") or ""))
                    break
        if not voice:
            voice = DEFAULT_TTS_VOICE
        shot["ttsStatus"] = "running"
        shot["ttsError"] = None
        try:
            audio = tts_provider.synthesize(dialogue, voice=voice)
        except LlmError as error:
            shot["ttsStatus"] = "failed"
            shot["ttsError"] = str(error)
            continue
        dest = audio_dir / f"tts-{shot['id']}.mp3"
        _write_tts_file(dest, audio)
        shot["ttsStatus"] = "succeeded"
        shot["ttsUrl"] = tts_public_url(project_id, str(shot["id"]))
        shot["ttsPath"] = str(dest)
        shot["voiceId"] = voice
        generated += 1
    if wanted and generated == 0:
        missing = [shot for shot in shots if isinstance(shot, dict) and shot.get("id") in wanted]
        if missing and not any(_text(item.get("dialogue")) for item in missing):
            raise DirectorExportError("选中镜头没有对白，无法生成配音")
    return recipe


def save_recipe_bgm(
    recipe: dict[str, Any],
    *,
    owner_user_id: str,
    project_id: str,
    source: Path,
) -> dict[str, Any]:
    recipe = normalize_recipe_payload(recipe)
    suffix = source.suffix.lower() if source.suffix else ".mp3"
    if suffix not in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}:
        raise DirectorExportError("配乐必须是 mp3 / wav / m4a / aac / ogg / flac")
    dest = recipe_audio_dir(owner_user_id, project_id) / f"bgm{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for leftover in dest.parent.glob("bgm.*"):
        leftover.unlink(missing_ok=True)
    shutil.copy2(source, dest)
    audio = recipe.get("audio") if isinstance(recipe.get("audio"), dict) else default_audio_mix()
    audio["bgmPath"] = str(dest)
    audio["bgmUrl"] = bgm_public_url(project_id)
    recipe["audio"] = audio
    return recipe


def _hex_to_ass_color(value: str) -> str:
    text = (value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return "&H00FFFFFF"
    red, green, blue = text[0:2], text[2:4], text[4:6]
    return f"&H00{blue}{green}{red}".upper()


def build_ass_subtitles(clips: list[MuxClip], style: dict[str, Any], *, width: int = 1280, height: int = 720) -> str:
    position = style.get("position") or "bottom"
    align = ASS_ALIGN.get(position, 2)
    font_size = int(style.get("fontSize") or 28)
    stroke = int(style.get("strokeWidth") or 2)
    primary = _hex_to_ass_color(str(style.get("textColor") or "#ffffff"))
    outline = _hex_to_ass_color(str(style.get("strokeColor") or "#000000"))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Microsoft YaHei,{font_size},{primary},&H000000FF,{outline},&H64000000,"
        f"0,0,0,0,100,100,0,0,1,{stroke},0,{align},40,40,36,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def ass_time(seconds: float) -> str:
        total = max(0.0, seconds)
        hours = int(total // 3600)
        minutes = int((total % 3600) // 60)
        secs = total % 60
        return f"{hours:d}:{minutes:02d}:{secs:05.2f}"

    for clip in clips:
        dialogue = clip.dialogue.replace("\n", r"\N").strip()
        if not dialogue:
            continue
        start = ass_time(clip.start_sec)
        end = ass_time(clip.start_sec + clip.duration_sec)
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{dialogue}")
    return "\n".join(lines) + "\n"


def _mix_clip_audio(clip: MuxClip, work_dir: Path, runner: FfmpegRunner) -> Path:
    if clip.tts_path is None or not clip.tts_path.is_file():
        return clip.video_path
    dest = work_dir / f"mixed-{clip.shot_id}.mp4"
    runner.run([
        "-i", str(clip.video_path),
        "-i", str(clip.tts_path),
        "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(dest),
    ])
    return dest if dest.is_file() else clip.video_path


def mux_recipe_film(
    recipe: dict[str, Any],
    store: JobStore,
    *,
    owner_user_id: str,
    project_id: str,
    burn_subtitles: bool = False,
    resource_storage: Any | None = None,
    runner: FfmpegRunner | None = None,
) -> dict[str, Any]:
    recipe = normalize_recipe_payload(recipe)
    ffmpeg = runner or SystemFfmpegRunner()
    if isinstance(ffmpeg, SystemFfmpegRunner):
        ffmpeg.require()
    clips = build_mux_clips(
        recipe, store, owner_user_id=owner_user_id, project_id=project_id,
        resource_storage=resource_storage,
    )
    work_dir = recipe_mux_dir(project_id) / f"work-{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    export = recipe.get("export") if isinstance(recipe.get("export"), dict) else empty_export_state()
    export["muxStatus"] = "running"
    export["muxError"] = None
    recipe["export"] = export
    try:
        mixed_paths = [_mix_clip_audio(clip, work_dir, ffmpeg) for clip in clips]
        concat_list = work_dir / "concat.txt"
        concat_list.write_text(
            "".join(f"file '{path.as_posix()}'\n" for path in mixed_paths),
            encoding="utf-8",
        )
        concat_video = work_dir / "concat.mp4"
        try:
            ffmpeg.run(["-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(concat_video)])
        except DirectorExportError:
            ffmpeg.run([
                "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",
                str(concat_video),
            ])
        current = concat_video
        audio = recipe.get("audio") if isinstance(recipe.get("audio"), dict) else default_audio_mix()
        bgm_path = Path(str(audio.get("bgmPath") or "")) if audio.get("bgmPath") else None
        if bgm_path and bgm_path.is_file():
            volume = _float(audio.get("bgmVolume"), 0.25, maximum=1.0)
            fade_in = _float(audio.get("bgmFadeInSec"), 1.0, maximum=15.0)
            fade_out = _float(audio.get("bgmFadeOutSec"), 2.0, maximum=15.0)
            total = max(timeline_duration_sec(clips), 0.1)
            fade_out_start = max(0.0, total - fade_out)
            mixed = work_dir / "with-bgm.mp4"
            ffmpeg.run([
                "-i", str(current),
                "-i", str(bgm_path),
                "-filter_complex",
                (
                    f"[1:a]volume={volume},afade=t=in:st=0:d={fade_in},"
                    f"afade=t=out:st={fade_out_start}:d={fade_out}[bgm];"
                    "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[a]"
                ),
                "-map", "0:v",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                str(mixed),
            ])
            if mixed.is_file():
                current = mixed
        style = recipe.get("subtitles") if isinstance(recipe.get("subtitles"), dict) else default_subtitle_style()
        if burn_subtitles and style.get("enabled"):
            ass_path = work_dir / "captions.ass"
            width = int(recipe.get("width") or 1280)
            height = int(recipe.get("height") or 720)
            ass_path.write_text(build_ass_subtitles(clips, style, width=width, height=height), encoding="utf-8")
            burned = work_dir / "burned.mp4"
            escaped = ass_path.as_posix().replace("\\", "/").replace(":", r"\:")
            ffmpeg.run([
                "-i", str(current),
                "-vf", f"ass='{escaped}'",
                "-c:a", "copy",
                str(burned),
            ])
            if burned.is_file():
                current = burned
        dest_dir = recipe_mux_dir(project_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "film.mp4"
        if dest.exists():
            dest.unlink()
        shutil.copy2(current, dest)
        probed = ffmpeg.probe_duration(dest)
        duration = probed if probed > 0 else timeline_duration_sec(clips)
        export["muxStatus"] = "succeeded"
        export["muxUrl"] = mux_public_url(project_id)
        export["muxPath"] = str(dest)
        export["muxDurationSec"] = round(duration, 3)
        export["muxError"] = None
        export["muxAt"] = datetime.now(timezone.utc).isoformat()
        export["burnSubtitles"] = bool(burn_subtitles)
        recipe["export"] = export
        return recipe
    except Exception as error:
        export["muxStatus"] = "failed"
        export["muxError"] = str(error)
        recipe["export"] = export
        if isinstance(error, DirectorExportError):
            raise
        raise DirectorExportError(str(error)) from error
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _edl_timecode(seconds: float, fps: int = 24) -> str:
    total_frames = int(round(max(0.0, seconds) * fps))
    hours = total_frames // (fps * 3600)
    minutes = (total_frames // (fps * 60)) % 60
    secs = (total_frames // fps) % 60
    frames = total_frames % fps
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


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


def build_edl(
    recipe: dict[str, Any],
    clips: list[MuxClip],
    *,
    project_title: str,
) -> str:
    fps = int(recipe.get("fps") or 24) or 24
    lines = [
        f"TITLE: {project_title or '导演成片'}",
        "FCM: NON-DROP FRAME",
        "",
    ]
    for index, clip in enumerate(clips, start=1):
        src_in = _edl_timecode(0, fps)
        src_out = _edl_timecode(clip.duration_sec, fps)
        rec_in = _edl_timecode(clip.start_sec, fps)
        rec_out = _edl_timecode(clip.start_sec + clip.duration_sec, fps)
        lines.append(
            f"{index:03d}  AX       V     C        {src_in} {src_out} {rec_in} {rec_out}"
        )
        lines.append(f"* FROM CLIP NAME: {clip.video_path.name}")
        if clip.dialogue:
            lines.append(f"* COMMENT: {clip.dialogue}")
        if clip.tts_path:
            lines.append(f"* AUDIO CLIP: {clip.tts_path.name}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_timeline_documents(
    recipe: dict[str, Any],
    store: JobStore,
    *,
    owner_user_id: str,
    project_id: str,
    title: str,
    resource_storage: Any | None = None,
) -> tuple[list[MuxClip], str, str]:
    recipe = normalize_recipe_payload(recipe)
    clips = build_mux_clips(
        recipe, store, owner_user_id=owner_user_id, project_id=project_id,
        resource_storage=resource_storage,
    )
    return clips, build_fcpxml(recipe, clips, project_title=title), build_edl(recipe, clips, project_title=title)


def find_tts_file(owner_user_id: str, project_id: str, shot_id: str) -> Path | None:
    return find_audio_file(recipe_audio_dir(owner_user_id, project_id), f"tts-{shot_id}")


def find_voice_preview_file(owner_user_id: str, project_id: str, character_id: str) -> Path | None:
    return find_audio_file(recipe_audio_dir(owner_user_id, project_id), f"voice-{character_id}")


def find_bgm_file(owner_user_id: str, project_id: str) -> Path | None:
    return find_audio_file(recipe_audio_dir(owner_user_id, project_id), "bgm")


def find_mux_file(project_id: str, recipe: dict[str, Any] | None = None) -> Path | None:
    export = (recipe or {}).get("export") if isinstance((recipe or {}).get("export"), dict) else {}
    raw = _text(export.get("muxPath"))
    if raw:
        candidate = Path(raw)
        if candidate.is_file():
            return candidate
    dest = recipe_mux_dir(project_id) / "film.mp4"
    return dest if dest.is_file() else None
