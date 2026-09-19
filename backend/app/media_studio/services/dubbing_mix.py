from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable

from ...skill_packs.recipe import HALF_NARRATED_PACK_ID
from .dubbing_lines import LINE_KINDS, default_mix

NARRATION_REQUIRED_PACK_IDS = {HALF_NARRATED_PACK_ID}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"0", "false", "off", "no"}:
            return False
        if lowered in {"1", "true", "on", "yes"}:
            return True
        return default
    return bool(value)


def mix_dubbing_enabled(options: dict[str, Any] | None) -> bool:
    payload = options or {}
    if "mix_dubbing" in payload:
        return _truthy(payload.get("mix_dubbing"), True)
    return True


def line_has_ready_audio(line: dict[str, Any] | None) -> bool:
    item = line or {}
    return _text(item.get("status")) == "ready" and bool(_text(item.get("audio_url")))


def line_contributes_tts(line: dict[str, Any] | None) -> bool:
    """Inner/narration overlay, or any line marked replace, is mixed into the shot."""
    item = line or {}
    if not line_has_ready_audio(item):
        return False
    kind = _text(item.get("kind")) or "spoken"
    if kind not in LINE_KINDS:
        kind = "spoken"
    mix = _text(item.get("mix")) or default_mix(kind)
    if mix == "replace":
        return True
    return kind in {"inner", "narration"}


def line_mutes_source(line: dict[str, Any] | None) -> bool:
    item = line or {}
    mix = _text(item.get("mix")) or default_mix(_text(item.get("kind")) or "spoken")
    return line_contributes_tts(item) and mix == "replace"


def missing_narration_lines(lines: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for item in lines or []:
        if not isinstance(item, dict):
            continue
        if _text(item.get("kind")) != "narration":
            continue
        if not _text(item.get("text")):
            continue
        if not line_has_ready_audio(item):
            missing.append(item)
    return missing


def narration_required(pack_id: str | None) -> bool:
    return _text(pack_id) in NARRATION_REQUIRED_PACK_IDS


def compose_dubbing_block(lines: Iterable[dict[str, Any]] | None, pack_id: str | None) -> str:
    if not narration_required(pack_id):
        return ""
    missing = missing_narration_lines(lines)
    if not missing:
        return ""
    labels = "、".join(_text(item.get("seq")) or "?" for item in missing)
    return f"解说剧还有 {len(missing)} 句旁白没有配音（{labels}），请先在「配音」Tab 生成。"


def compose_gate_payload(lines: list[dict[str, Any]], pack_id: str | None) -> dict[str, Any]:
    reason = compose_dubbing_block(lines, pack_id)
    return {
        "skill_pack_id": _text(pack_id),
        "requires_narration": narration_required(pack_id),
        "compose_blocked": bool(reason),
        "compose_block_reason": reason,
        "missing_narration": [
            {"id": _text(item.get("id")), "seq": _text(item.get("seq")), "text": _text(item.get("text"))}
            for item in missing_narration_lines(lines)
        ],
    }


def contributing_lines_for_beat(lines: Iterable[dict[str, Any]] | None, beat_id: str) -> list[dict[str, Any]]:
    wanted = _text(beat_id)
    return [
        item
        for item in (lines or [])
        if isinstance(item, dict) and _text(item.get("beat_id")) == wanted and line_contributes_tts(item)
    ]


def beat_mutes_source(lines: Iterable[dict[str, Any]] | None) -> bool:
    return any(line_mutes_source(item) for item in (lines or []) if isinstance(item, dict))


def _audio_suffix(content: bytes) -> str:
    if content.startswith(b"RIFF"):
        return ".wav"
    if content[:3] == b"ID3" or content[:2] == b"\xff\xfb":
        return ".mp3"
    return ".bin"


def concat_audio_bytes(clips: list[bytes]) -> bytes:
    usable = [item for item in clips if item]
    if not usable:
        raise RuntimeError("没有可拼接的配音")
    if len(usable) == 1:
        return usable[0]
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("系统未安装 ffmpeg，无法拼接配音")
    with tempfile.TemporaryDirectory(prefix="zly-dub-concat-") as directory:
        root = Path(directory)
        inputs: list[str] = []
        for index, content in enumerate(usable):
            path = root / f"clip-{index + 1}{_audio_suffix(content)}"
            path.write_bytes(content)
            inputs.extend(["-i", str(path)])
        output = root / "joined.wav"
        filters = "".join(f"[{index}:a]" for index in range(len(usable))) + f"concat=n={len(usable)}:v=0:a=1[a]"
        command = [ffmpeg, "-y", *inputs, "-filter_complex", filters, "-map", "[a]", str(output)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if completed.returncode != 0 or not output.exists() or not output.stat().st_size:
            raise RuntimeError(f"ffmpeg 拼接配音失败: {(completed.stderr or '')[-1000:]}")
        return output.read_bytes()


def mix_audio_onto_video(video: bytes, audio: bytes, *, mute_source: bool) -> bytes:
    if not video:
        raise RuntimeError("镜头视频为空，无法混音")
    if not audio:
        return video
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("系统未安装 ffmpeg，无法混入配音")
    with tempfile.TemporaryDirectory(prefix="zly-dub-mix-") as directory:
        root = Path(directory)
        video_path = root / "shot.mp4"
        audio_path = root / f"voice{_audio_suffix(audio)}"
        mixed = root / "mixed.mp4"
        video_path.write_bytes(video)
        audio_path.write_bytes(audio)
        replace = [
            ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
            "-shortest", "-movflags", "+faststart", str(mixed),
        ]
        overlay = [
            ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path),
            "-filter_complex",
            "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[va];"
            "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,apad[tts];"
            "[va][tts]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
            "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
            "-shortest", "-movflags", "+faststart", str(mixed),
        ]
        command = replace if mute_source else overlay
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if completed.returncode != 0 or not mixed.exists() or not mixed.stat().st_size:
            if mute_source:
                raise RuntimeError(f"ffmpeg 替换配音失败: {(completed.stderr or '')[-1000:]}")
            completed = subprocess.run(replace, capture_output=True, text=True, timeout=180)
            if completed.returncode != 0 or not mixed.exists() or not mixed.stat().st_size:
                raise RuntimeError(f"ffmpeg 叠配音失败: {(completed.stderr or '')[-1000:]}")
        return mixed.read_bytes()


def mix_shot_with_clips(video: bytes, clips: list[bytes], *, mute_source: bool) -> bytes:
    if not clips:
        return video
    audio = concat_audio_bytes(clips)
    return mix_audio_onto_video(video, audio, mute_source=mute_source)


def mix_shot_with_lines(
    video: bytes,
    lines: Iterable[dict[str, Any]] | None,
    fetch_audio: Callable[[str], bytes],
) -> bytes:
    contributing = [item for item in (lines or []) if isinstance(item, dict) and line_contributes_tts(item)]
    if not contributing:
        return video
    clips: list[bytes] = []
    for item in contributing:
        content = fetch_audio(_text(item.get("audio_url")))
        if content:
            clips.append(content)
    if not clips:
        return video
    return mix_shot_with_clips(video, clips, mute_source=beat_mutes_source(contributing))
