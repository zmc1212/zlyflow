from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import requests

from ..db import execute_sql, now_str, query_all, query_one
from ...director_export import find_ffmpeg
from .dubbing_lines import expand_beat_lines
from .qiniu_service import QiniuService
from .voice_profile import clone_voice_id, merge_voice

VOICE_EXTRACT_MIN_SEC = 1.0
VOICE_EXTRACT_MAX_SEC = 15.0
VOICE_EXTRACT_DURATION_SLACK = 0.05
VOICE_EXTRACT_DOWNLOAD_TIMEOUT = 120
LINE_PREVIEW_MAX = 36
WINDOW_HINT = "请框选该角色单独说话的片段"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def beat_duration_sec(beat: dict[str, Any]) -> float:
    for key in ("video_duration", "duration_sec", "duration"):
        parsed = _float(beat.get(key) if isinstance(beat, dict) else None)
        if parsed is not None and parsed > 0:
            return parsed
    return 0.0


def beat_video_url(beat: dict[str, Any]) -> str:
    if not isinstance(beat, dict):
        return ""
    return _text(beat.get("video_url"))


def parse_episode_beats(episode: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(episode, dict):
        return []
    beats: Any = episode.get("beats")
    if not isinstance(beats, list):
        raw = episode.get("data_json")
        data: Any = {}
        if isinstance(raw, dict):
            data = raw
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {}
            data = parsed if isinstance(parsed, dict) else {}
        beats = data.get("beats") if isinstance(data, dict) else []
    if not isinstance(beats, list):
        return []
    return [item for item in beats if isinstance(item, dict)]


def preview_spoken_lines(texts: list[str]) -> str:
    joined = " / ".join(part for part in texts if part)
    if len(joined) <= LINE_PREVIEW_MAX:
        return joined
    return joined[: LINE_PREVIEW_MAX - 1].rstrip() + "…"


def validate_extract_window(
    start_sec: Any,
    end_sec: Any,
    duration_sec: float = 0.0,
) -> tuple[float, float]:
    start = _float(start_sec)
    end = _float(end_sec)
    if start is None or end is None:
        raise ValueError(WINDOW_HINT)
    duration = _float(duration_sec) or 0.0
    if start < -VOICE_EXTRACT_DURATION_SLACK or not (start < end):
        raise ValueError(WINDOW_HINT)
    if start < 0:
        start = 0.0
    if duration > 0 and end > duration + VOICE_EXTRACT_DURATION_SLACK:
        raise ValueError("提取片段超出成片时长")
    if duration > 0:
        end = min(end, duration)
        start = min(max(0.0, start), end)
    span = end - start
    if span < VOICE_EXTRACT_MIN_SEC - 1e-6:
        raise ValueError("提取片段至少 1 秒")
    if span > VOICE_EXTRACT_MAX_SEC + 1e-6:
        raise ValueError("提取片段不能超过 15 秒")
    return start, end


def collect_voice_extract_sources(
    episodes: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    asset_id: str,
) -> list[dict[str, Any]]:
    target = _text(asset_id)
    if not target:
        return []
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    ordered_episodes = sorted(
        [item for item in episodes if isinstance(item, dict)],
        key=lambda item: int(item.get("episode_num") or 0),
    )
    for episode in ordered_episodes:
        episode_id = _text(episode.get("id") or episode.get("episode_id"))
        beats = sorted(
            parse_episode_beats(episode),
            key=lambda item: int(item.get("sequence") or 0),
        )
        for beat in beats:
            video_url = beat_video_url(beat)
            if not video_url:
                continue
            beat_id = _text(beat.get("id"))
            key = (episode_id, beat_id)
            if not beat_id or key in seen:
                continue
            spoken = [
                _text(line.get("text"))
                for line in expand_beat_lines(beat, assets)
                if _text(line.get("kind")) == "spoken" and _text(line.get("character_id")) == target
            ]
            spoken = [text for text in spoken if text]
            if not spoken:
                continue
            seen.add(key)
            seq = _text(beat.get("sequence")) or "?"
            sources.append({
                "episode_id": episode_id,
                "episode_num": int(episode.get("episode_num") or 0),
                "title": _text(episode.get("title")),
                "beat_id": beat_id,
                "seq": seq,
                "line_preview": preview_spoken_lines(spoken),
                "duration_sec": beat_duration_sec(beat),
                "video_url": video_url,
            })
    return sources


def build_ffmpeg_extract_command(
    ffmpeg: str,
    input_path: str | Path,
    output_path: str | Path,
    start_sec: float,
    duration_sec: float,
) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-i",
        str(input_path),
        "-t",
        f"{duration_sec:.3f}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(output_path),
    ]


def _looks_like_missing_audio(stderr: str, output_path: Path) -> bool:
    text = (stderr or "").lower()
    needles = (
        "does not contain any stream",
        "does not contain any audio",
        "output file is empty",
        "matches no streams",
        "no audio",
    )
    if any(needle in text for needle in needles):
        return True
    if not output_path.is_file() or output_path.stat().st_size < 64:
        return True
    return not output_path.read_bytes()[:4] == b"RIFF"


def _download_video(url: str, dest: Path) -> None:
    try:
        response = requests.get(url, timeout=VOICE_EXTRACT_DOWNLOAD_TIMEOUT, stream=True)
        response.raise_for_status()
    except requests.RequestException as error:
        raise ValueError("下载成片失败") from error
    with dest.open("wb") as handle:
        empty = True
        for chunk in response.iter_content(256 * 1024):
            if not chunk:
                continue
            empty = False
            handle.write(chunk)
        if empty:
            raise ValueError("下载成片失败")


def extract_wav_bytes(video_url: str, start_sec: float, end_sec: float) -> bytes:
    ffmpeg = find_ffmpeg("ffmpeg")
    if not ffmpeg:
        raise ValueError("未找到 ffmpeg，无法从成片提取参考音")
    duration = end_sec - start_sec
    with tempfile.TemporaryDirectory(prefix="voice-extract-") as tmp:
        folder = Path(tmp)
        source_path = folder / "shot.bin"
        wav_path = folder / "voice.wav"
        _download_video(video_url, source_path)
        command = build_ffmpeg_extract_command(ffmpeg, source_path, wav_path, start_sec, duration)
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as error:
            raise ValueError("未找到 ffmpeg，无法从成片提取参考音") from error
        except subprocess.CalledProcessError as error:
            stderr = error.stderr or error.stdout or str(error)
            if _looks_like_missing_audio(stderr, wav_path):
                raise ValueError("成片没有音轨，无法提取参考音") from error
            raise ValueError("从成片提取参考音失败") from error
        if _looks_like_missing_audio(completed.stderr or "", wav_path):
            raise ValueError("成片没有音轨，无法提取参考音")
        return wav_path.read_bytes()


def _require_character(project_id: str, asset_id: str) -> dict[str, Any]:
    from .project_detail_service import ProjectDetailService

    raw_row = query_one(
        "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
        (asset_id, project_id),
    )
    if not raw_row:
        raise ValueError("资产不存在")
    if _text(raw_row.get("kind")) != "character":
        raise ValueError("只有角色可以从成片提取参考音")
    return ProjectDetailService._hydrate_asset(raw_row)


def list_voice_extract_sources(project_id: str, asset_id: str) -> list[dict[str, Any]]:
    from .project_detail_service import ProjectDetailService

    _require_character(project_id, asset_id)
    assets = ProjectDetailService.list_assets(project_id)
    episodes = query_all(
        """
        SELECT id, episode_num, title, data_json
        FROM ai_project_episodes
        WHERE project_id = %s
        ORDER BY episode_num ASC
        """,
        (project_id,),
    )
    return collect_voice_extract_sources(episodes, assets, asset_id)


def _find_shot(
    project_id: str,
    asset_id: str,
    episode_id: str,
    beat_id: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    from .project_detail_service import ProjectDetailService

    episode = query_one(
        "SELECT id, episode_num, title, data_json FROM ai_project_episodes WHERE id = %s AND project_id = %s",
        (episode_id, project_id),
    )
    if not episode:
        raise ValueError("分集不存在")
    beats = parse_episode_beats(episode)
    beat = next((item for item in beats if _text(item.get("id")) == beat_id), None)
    if beat is None:
        raise ValueError("镜头不存在")
    video_url = beat_video_url(beat)
    if not video_url:
        raise ValueError("该镜头没有 H3 原片")
    assets = ProjectDetailService.list_assets(project_id)
    spoken = [
        line
        for line in expand_beat_lines(beat, assets)
        if _text(line.get("kind")) == "spoken" and _text(line.get("character_id")) == asset_id
    ]
    if not spoken:
        raise ValueError("该镜头没有该角色的开口对白")
    return episode, beat, assets


def extract_asset_voice_from_shot(
    project_id: str,
    asset_id: str,
    *,
    episode_id: str,
    beat_id: str,
    start_sec: Any,
    end_sec: Any,
) -> dict[str, Any]:
    from .project_detail_service import ProjectDetailService

    raw = _require_character(project_id, asset_id)
    episode_id = _text(episode_id)
    beat_id = _text(beat_id)
    if not episode_id or not beat_id:
        raise ValueError(WINDOW_HINT)
    _episode, beat, _assets = _find_shot(project_id, asset_id, episode_id, beat_id)
    start, end = validate_extract_window(start_sec, end_sec, beat_duration_sec(beat))
    wav = extract_wav_bytes(beat_video_url(beat), start, end)
    _key, audio_url = QiniuService.store_bytes("asset-voice", f"{asset_id}.wav", wav)
    extra = merge_voice(
        raw.get("extra") or {},
        {
            "preset_id": "",
            "ref_audio_url": audio_url,
            "preview_url": "",
            "source": {
                "kind": "shot",
                "episode_id": episode_id,
                "beat_id": beat_id,
                "start_sec": start,
                "end_sec": end,
            },
        },
    )
    hydrated = ProjectDetailService._persist_asset_extra(project_id, asset_id, extra)
    voice_id = clone_voice_id(hydrated.get("voice_id") or raw.get("voice_id"))
    execute_sql(
        "UPDATE ai_project_assets SET voice_id = %s, extra_json = %s, updated_at = %s WHERE id = %s AND project_id = %s",
        (voice_id, json.dumps(hydrated.get("extra") or extra, ensure_ascii=False), now_str(), asset_id, project_id),
    )
    hydrated["voice_id"] = voice_id
    return hydrated
