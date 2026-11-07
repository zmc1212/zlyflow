"""Cache lyric cues derived from the song's audio on first use."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
import threading
import time
import unicodedata
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from difflib import SequenceMatcher
from itertools import chain
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import requests

from .models import MusicLyricLine, MusicLyricsResponse
from .music_job_service import MusicJobService, MusicServiceError
from .music_yue2_client import MAX_AUDIO_BYTES, YuE2Error
from .storage import JobStore

_LOGGER = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="music-lyrics")
_SUBMIT_LOCK = threading.Lock()
_active_alignment: Future[None] | None = None
_RUN_SECONDS = 720
_LEASE_SECONDS = 900
_SECTION = re.compile(r"\[.*\]")
_LINE_TIME = re.compile(r"\[(\d{1,3}):(\d{2}(?:\.\d+)?)\]")
_WORD_TIME = re.compile(r"<\d{1,3}:\d{2}(?:\.\d+)?>")


class MusicLyricsBusy(RuntimeError):
    pass


class MusicLyricsUnavailable(RuntimeError):
    pass


def lyric_text_lines(lyrics: str) -> list[str]:
    lines = (line.strip() for line in lyrics.splitlines())
    return [line for line in lines if line and not _SECTION.fullmatch(line)]


def _key(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", text).casefold() if char.isalnum())


def _mandarin_key(text: str) -> list[str]:
    normalized = _key(text)
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return list(normalized)
    syllables = lazy_pinyin(normalized, errors=list)
    return [char if char == syllable else "~" + syllable for char, syllable in zip(normalized, syllables)]


def apply_lrc(lyrics: list[str], lrc: str) -> list[MusicLyricLine]:
    """Read YuE2's enhanced LRC, keeping the authoring text and its punctuation."""
    entries: list[tuple[float, str]] = []
    for raw in lrc.splitlines():
        stamps = list(_LINE_TIME.finditer(raw))
        if not stamps:
            continue
        text = _key(_WORD_TIME.sub("", raw[stamps[-1].end():]))
        if text:
            entries.extend((int(stamp[1]) * 60 + float(stamp[2]), text) for stamp in stamps)
    entries.sort(key=lambda entry: entry[0])
    result = [MusicLyricLine(text=line) for line in lyrics]
    matcher = SequenceMatcher(None, [_key(line) for line in lyrics], [text for _, text in entries], autojunk=False)
    previous = -1.0
    for left, right, length in matcher.get_matching_blocks():
        for offset in range(length):
            start = entries[right + offset][0]
            if start > previous:
                result[left + offset].start_seconds = start
                previous = start
    return result


def align_lyric_words(
    lyrics: list[str], words: Iterable[tuple[str, float, float]], *, language: str | None = None,
) -> list[MusicLyricLine]:
    """Match written lines to recognised words in order, leaving uncertain lines untimed."""
    tokenize = _mandarin_key if language == "zh" else _key
    written = [tokenize(line) for line in lyrics]
    heard: list[str] = []
    times: list[tuple[float, float]] = []
    for word, start, end in words:
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            continue
        key = tokenize(word)
        heard.extend(key)
        times.extend([(start, end)] * len(key))

    matcher = SequenceMatcher(None, list(chain.from_iterable(written)), heard, autojunk=False)
    matches: dict[int, tuple[float, float]] = {}
    for left, right, length in matcher.get_matching_blocks():
        matches.update((left + offset, times[right + offset]) for offset in range(length))

    result: list[MusicLyricLine] = []
    cursor = 0
    previous = -1.0
    for line, key in zip(lyrics, written):
        offsets = [(index, matches[index]) for index in range(cursor, cursor + len(key)) if index in matches]
        start = end = None
        if offsets and len(offsets) * 5 >= len(key) * 3:
            first, (begin, _) = offsets[0]
            _, (_, finish) = offsets[-1]
            # Reject sparse matches across an instrumental gap and matches only in a line's tail.
            if first - cursor <= len(key) // 3 and begin > previous and 0 < finish - begin <= max(12, len(key) * 1.5):
                start, end = round(begin, 3), round(finish, 3)
                previous = begin
        result.append(MusicLyricLine(text=line, start_seconds=start, end_seconds=end))
        cursor += len(key)
    return result


def _model_path() -> Path:
    try:
        from faster_whisper.utils import download_model
    except ImportError as error:
        raise MusicLyricsUnavailable("需要本机转写模型才能生成同步歌词，当前可阅读原歌词。") from error
    configured = os.getenv("ZLY_AI_VIDEO_STUDIO_MUSIC_ASR_MODEL_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir() and (path / "model.bin").is_file():
            return path
        raise MusicLyricsUnavailable("歌词对齐模型目录不可用，请检查工作台配置。")
    from huggingface_hub.errors import LocalEntryNotFoundError

    for size in ("medium", "small"):
        try:
            return Path(download_model(size, local_files_only=True))
        except LocalEntryNotFoundError:
            continue
    raise MusicLyricsUnavailable("需要本机转写模型才能生成同步歌词，当前可阅读原歌词。")


def _download_audio(url: str, destination: Path, deadline: float) -> None:
    if urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError("歌曲地址无效")
    with requests.get(url, stream=True, timeout=(8, 25)) as response, destination.open("wb") as target:
        response.raise_for_status()
        size = 0
        for chunk in response.iter_content(1024 * 1024):
            size += len(chunk)
            if size > MAX_AUDIO_BYTES or time.monotonic() >= deadline:
                raise ValueError("歌曲音频超出对齐限制")
            target.write(chunk)


def _local_alignment(lyrics: list[str], audio_url: str) -> list[MusicLyricLine]:
    model_path = _model_path()
    from faster_whisper import WhisperModel

    deadline = time.monotonic() + _RUN_SECONDS
    with tempfile.TemporaryDirectory(prefix="zly-music-lyrics-") as directory:
        audio = Path(directory) / "song.audio"
        _download_audio(audio_url, audio, deadline)
        model = WhisperModel(str(model_path), device="cpu", compute_type="int8",
                             cpu_threads=min(8, os.cpu_count() or 4), local_files_only=True)
        segments, info = model.transcribe(str(audio), word_timestamps=True, beam_size=3, condition_on_previous_text=False)
        words = []
        for segment in segments:
            if time.monotonic() >= deadline:
                raise TimeoutError("歌词对齐超时")
            words.extend((word.word, word.start, word.end) for word in segment.words or [])
    return align_lyric_words(lyrics, words, language=info.language)


def _align(lyrics: list[str], job: dict) -> MusicLyricsResponse:
    if song_id := job.get("remote_song_id"):
        try:
            native = apply_lrc(lyrics, MusicJobService.client().get_song_lrc(song_id))
        except (MusicServiceError, YuE2Error):
            native = []
        if any(line.start_seconds is not None for line in native):
            return MusicLyricsResponse(status="ready", lines=native, source="yue2")
    local = _local_alignment(lyrics, job["result_url"])
    if any(line.start_seconds is not None for line in local):
        return MusicLyricsResponse(status="ready", lines=local, source="local")
    return MusicLyricsResponse(status="unavailable", message="成品音频里没有找到可对齐的歌词，当前可阅读原歌词。")


def music_lyrics_status(store: JobStore, job_id: str) -> MusicLyricsResponse:
    record = store.get_music_lyrics(job_id)
    if not record:
        return MusicLyricsResponse()
    status = record["status"]
    if status == "aligning" and record["lease_until"] <= int(time.time()):
        return MusicLyricsResponse(status="failed", message="上次歌词对齐已中断，可以重新对齐。")
    return MusicLyricsResponse(status=status, **json.loads(record["payload_json"] or "{}"))


def _run(store: JobStore, job: dict, lyrics: list[str], token: str) -> None:
    try:
        result = _align(lyrics, job)
    except MusicLyricsUnavailable as error:
        result = MusicLyricsResponse(status="unavailable", message=str(error))
    except Exception as error:
        _LOGGER.warning("Music lyric alignment failed for %s (%s)", job["id"], type(error).__name__)
        result = MusicLyricsResponse(status="failed", message="歌词对齐失败，可以重新对齐。")
    try:
        store.finish_music_lyrics(job["id"], token, result.status, result.model_dump(exclude={"status"}))
    except Exception as error:
        _LOGGER.warning("Could not save lyric alignment for %s (%s)", job["id"], type(error).__name__)


def start_music_lyrics(store: JobStore, job: dict) -> MusicLyricsResponse:
    global _active_alignment
    lyrics = lyric_text_lines(job["lyrics"])
    if not lyrics:
        return MusicLyricsResponse(status="unavailable", message="这是一首纯音乐。")
    job_id = job["id"]
    with _SUBMIT_LOCK:
        current = music_lyrics_status(store, job_id)
        if current.status in {"ready", "aligning"}:
            return current
        if _active_alignment is not None and not _active_alignment.done():
            raise MusicLyricsBusy("另一首歌正在对齐，稍后可以重试。")
        timestamp = int(time.time())
        token = uuid.uuid4().hex
        if store.claim_music_lyrics(job_id, token, timestamp, timestamp + _LEASE_SECONDS):
            try:
                _active_alignment = _EXECUTOR.submit(_run, store, job, lyrics, token)
            except RuntimeError:
                store.finish_music_lyrics(job_id, token, "failed", {"message": "歌词对齐服务正在重启，可以稍后重试。"})
        return music_lyrics_status(store, job_id)
