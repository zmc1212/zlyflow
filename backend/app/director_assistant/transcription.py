"""Audio transcription for the smart edit assistant.

Only media already placed on the timeline and still audible is downloaded from
the configured object storage; the audio track is extracted locally and sent to
the configured OpenAI-compatible transcription endpoint. Segment timestamps are
source-local (relative to the media file), never output-timeline local, and no
timeline data is modified here. The audio for one source can appear at several
positions, so `spans` records every audible range on the timeline.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from ..media_studio.services import smart_edit_service
from ..media_studio.services.smart_edit_render import probe
from .editing import EditingActions
from .repository import AssistantConflict, AssistantNotFound, AssistantRepository, timestamp

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="assistant-transcription")
ACTIVE = {"queued", "running"}
STALE_SECONDS = 15 * 60
MAX_MEDIA_PER_RUN = 40
MAX_AUDIO_SECONDS_PER_RUN = 600.0
MAX_SEGMENTS_PER_ASSET = 200
MAX_SPANS_PER_ASSET = 200
MAX_SEGMENT_TEXT_CHARS = 400
KIND = "media_transcript"


class _Superseded(Exception):
    pass


def record_id(owner: str, project: str, sequence: str) -> str:
    digest = hashlib.sha256(f"media-transcript|{owner}|{project}|{sequence}".encode()).hexdigest()
    return f"trn-{digest[:40]}"


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _seconds(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(result, 3) if result > 0 else 0.0


def _empty_summary(media_count: int = 0, failed_count: int = 0) -> dict:
    return {"media_count": media_count, "transcribed_count": 0, "failed_count": failed_count,
            "skipped_count": failed_count, "segment_count": 0, "audio_seconds": 0.0}


def extract_audio(source: Path, destination: Path) -> Path:
    """16 kHz mono WAV: the smallest lossless form the transcription endpoint accepts."""
    binary = shutil.which("ffmpeg")
    if not binary:
        raise RuntimeError("系统未安装 FFmpeg，无法提取音轨")
    result = subprocess.run(
        [binary, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-vn", "-ac", "1", "-ar", "16000", str(destination)],
        capture_output=True, timeout=1800,
    )
    if result.returncode or not destination.is_file() or destination.stat().st_size <= 44:
        detail = result.stderr.decode("utf-8", errors="replace")[-600:]
        raise RuntimeError(f"音频提取失败：{detail or '素材可能没有音轨'}")
    return destination


class MediaTranscription:
    def __init__(self, repo: AssistantRepository, llm_provider: Any = None, *,
                 downloader: Callable | None = None, probe_media: Callable | None = None,
                 audio_extractor: Callable | None = None, transcriber: Callable | None = None,
                 run_async: bool = True, executor=None):
        self.repo = repo
        self.llm = llm_provider
        self.downloader = downloader or smart_edit_service.download_asset
        self.probe_media = probe_media or probe
        self.extract = audio_extractor or extract_audio
        self.transcriber = transcriber or self._transcribe
        self.run_async = run_async
        self.executor = executor or _EXECUTOR

    def _transcribe(self, path: Path) -> dict:
        return self.llm.transcribe_audio(path)

    @staticmethod
    def public(record: dict) -> dict:
        return {key: value for key, value in record.items() if not key.startswith("_") and key != "run_token"}

    def _existing(self, owner: str, project: str, sequence: str) -> dict | None:
        try:
            return self.repo.get(owner, record_id(owner, project, sequence), KIND)
        except AssistantNotFound:
            return None

    @staticmethod
    def _signature(items: list[dict]) -> str:
        values = sorted((str(item.get("beat_id") or item.get("asset_id") or ""), str(item.get("url") or ""),
                         round(float(item.get("duration") or 0), 3)) for item in items)
        return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()

    def _source_media(self, owner: str, project: str, sequence: str) -> list[dict]:
        """Audible media referenced by the saved timeline, in timeline order."""
        with self.repo.store.connection() as conn:
            snapshot = EditingActions.snapshot(conn, owner, project, sequence)
        document = snapshot["document"]
        assets = {asset["id"]: asset for asset in document.get("assets") or []}
        collected: dict[str, dict] = {}
        for clip in sorted(document.get("clips") or [], key=lambda item: (float(item.get("start") or 0),
                                                                         str(item.get("id") or ""))):
            if clip.get("track") not in {"video", "audio"} or clip.get("muted"):
                continue
            if float(clip.get("volume") if clip.get("volume") is not None else 1) <= 0:
                continue
            asset = assets.get(str(clip.get("asset_id") or ""))
            if not asset or asset.get("kind") not in {"video", "audio"} or not asset.get("url"):
                continue
            duration = float(asset.get("duration") or 0)
            start = float(clip.get("start") or 0)
            entry = collected.get(str(asset["id"]))
            if entry is None:
                entry = {"asset_id": str(asset["id"]), "beat_id": asset.get("beat_id"),
                         "name": str(asset.get("name") or "素材"), "kind": str(asset["kind"]),
                         "url": str(asset["url"]), "duration": round(duration, 3),
                         "start": round(start, 3), "spans": []}
                collected[str(asset["id"])] = entry
            entry["spans"].append({"clip_id": str(clip.get("id") or ""), "timeline_start": round(start, 3),
                                   "timeline_duration": _seconds(clip.get("duration")),
                                   "in_point": _seconds(clip.get("in_point")), "speed": float(clip.get("speed") or 1)})
        items = []
        for entry in collected.values():
            entry["spans"] = entry["spans"][:MAX_SPANS_PER_ASSET]
            items.append(entry)
        return items

    def _target(self, project: str, sequence: str) -> None:
        with self.repo.store.connection() as conn:
            EditingActions.target(conn, project, sequence)

    def _model(self) -> tuple[str | None, str | None]:
        if self.llm is None:
            return None, "语音转写尚未配置。请在管理设置 → 大模型 中启用服务后再使用音频转写。"
        try:
            available, reason = self.llm.transcription_availability()
            model = self.llm.transcription_model()
        except Exception as error:
            return None, _text(error, 300) or "语音转写服务不可用"
        if not available or not model:
            return None, reason or "语音转写服务不可用，请先在管理设置中检查大模型配置。"
        return model, None

    def _source_changed(self, owner: str, project: str, sequence: str, record: dict) -> bool:
        try:
            return record.get("source_signature") != self._signature(self._source_media(owner, project, sequence))
        except Exception:
            return False

    @staticmethod
    def _stale(record: dict) -> bool:
        if record.get("status") not in ACTIVE:
            return False
        from datetime import datetime, timezone
        try:
            updated = datetime.fromisoformat(str(record.get("updated_at") or ""))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - updated).total_seconds() > STALE_SECONDS
        except ValueError:
            return False

    def read(self, owner: str, project: str, sequence: str) -> dict:
        self._target(project, sequence)
        record = self._existing(owner, project, sequence)
        if not record:
            return {"status": "missing", "project_id": project, "sequence_id": sequence,
                    "model": None, "items": [], "summary": _empty_summary()}
        if self._stale(record):
            record = self.repo.update(owner, record, {"message": "音频转写已中断，请重新开始", "run_token": None},
                                      status="failed")
        result = self.public(record)
        if record.get("status") not in ACTIVE and self._source_changed(owner, project, sequence, record):
            result["stale"] = True
        return result

    def start(self, owner: str, project: str, sequence: str, *, force: bool = False) -> dict:
        self._target(project, sequence)
        items = self._source_media(owner, project, sequence)
        signature = self._signature(items)
        existing = self._existing(owner, project, sequence)
        if existing and existing.get("status") in ACTIVE:
            if not self._stale(existing):
                raise AssistantConflict("音频转写正在进行，请稍候查看结果")
            existing = self.repo.update(owner, existing, {"message": "音频转写已中断，请重新开始", "run_token": None},
                                        status="failed")
        model, reason = self._model()
        if not items:
            return self._store(owner, project, sequence, existing, {
                "project_id": project, "sequence_id": sequence, "model": model,
                "source_signature": signature, "progress": 100,
                "message": "时间线上还没有可转写的有声素材，请先铺轨或放入配音",
                "summary": _empty_summary(), "items": [], "finished_at": timestamp(), "run_token": None,
            }, "empty")
        if reason:
            return self._store(owner, project, sequence, existing, {
                "project_id": project, "sequence_id": sequence, "model": None,
                "source_signature": signature, "progress": 0, "message": reason,
                "summary": _empty_summary(len(items), len(items)), "items": [],
                "finished_at": timestamp(), "run_token": None,
            }, "failed")
        if existing and not force and existing.get("source_signature") == signature \
                and existing.get("model") == model \
                and existing.get("status") in {"succeeded", "partial", "empty", "failed"}:
            return self.public(existing)
        token = hashlib.sha256(f"{timestamp()}|{owner}|{project}|{sequence}".encode()).hexdigest()[:20]
        payload = {
            "project_id": project, "sequence_id": sequence, "model": model,
            "source_signature": signature, "progress": 0, "message": "正在准备音频转写",
            "summary": _empty_summary(len(items)), "items": [], "started_at": timestamp(),
            "finished_at": None, "run_token": token, "_media_count": len(items),
        }
        record = self._store(owner, project, sequence, existing, payload, "queued")
        if self.run_async:
            self.executor.submit(self._run, owner, record["id"], token, items)
        else:
            self._run(owner, record["id"], token, items)
        return self.public(self.repo.get(owner, record["id"], KIND))

    def _store(self, owner: str, project: str, sequence: str, existing: dict | None,
               payload: dict, status: str) -> dict:
        if existing:
            return self.repo.update(owner, existing, payload, status=status)
        return self.repo.insert(owner, KIND, payload, record_id=record_id(owner, project, sequence),
                                parent=smart_edit_service.document_id(project, owner, sequence), status=status)

    def _save(self, owner: str, ride: str, token: str, changes: dict, status: str) -> dict:
        record = self.repo.get(owner, ride, KIND)
        if record.get("run_token") != token:
            raise _Superseded()
        return self.repo.update(owner, record, changes, status=status)

    @staticmethod
    def _segments(raw: Any) -> list[dict]:
        segments = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            text = _text(item.get("text"), MAX_SEGMENT_TEXT_CHARS)
            start = _seconds(item.get("start"))
            end = _seconds(item.get("end"))
            if not text or end <= start:
                continue
            segments.append({"id": str(len(segments)), "start": start, "end": end, "text": text})
            if len(segments) >= MAX_SEGMENTS_PER_ASSET:
                break
        return segments

    @staticmethod
    def _summary(items: list[dict]) -> dict:
        done = [item for item in items if item.get("status") == "succeeded"]
        failed = [item for item in items if item.get("status") in {"failed", "skipped"}]
        return {
            "media_count": len(items),
            "transcribed_count": len(done),
            "failed_count": len(failed),
            "skipped_count": len([item for item in items if item.get("status") == "skipped"]),
            "segment_count": sum(int(item.get("segment_count") or 0) for item in items),
            "audio_seconds": round(sum(float(item.get("audio_seconds") or 0) for item in done), 2),
        }

    def _run(self, owner: str, ride: str, token: str, items: list[dict]) -> None:
        budget = MAX_AUDIO_SECONDS_PER_RUN
        for index, entry in enumerate(items, 1):
            entry["_item"] = {
                "asset_id": entry["asset_id"], "beat_id": entry.get("beat_id"), "name": entry["name"],
                "kind": entry["kind"], "duration": round(float(entry.get("duration") or 0), 3),
                "timeline_start": entry.get("start"), "spans": entry.get("spans") or [],
                "status": "failed", "segments": [], "segment_count": 0, "audio_seconds": 0.0,
                "language": None, "error": "等待转写",
            }
            if index > MAX_MEDIA_PER_RUN:
                entry["_item"]["status"] = "skipped"
                entry["_item"]["error"] = f"单次转写最多处理 {MAX_MEDIA_PER_RUN} 个素材，本次未处理"
        results = [entry["_item"] for entry in items]
        try:
            with tempfile.TemporaryDirectory(prefix="zly-transcription-") as directory:
                root = Path(directory)
                total = len(items)
                for index, entry in enumerate(items, 1):
                    item = entry["_item"]
                    if item["status"] == "skipped":
                        continue
                    if budget <= 0:
                        item["status"] = "skipped"
                        item["error"] = f"已达单次转写时长上限 {MAX_AUDIO_SECONDS_PER_RUN:.0f} 秒，本次未处理"
                        self._save(owner, ride, token, {
                            "items": results,
                            "message": f"正在转写 {index}/{total}（已达单次时长上限）",
                            "progress": 5 + round(index * 92 / max(1, total)),
                        }, "running")
                        continue
                    try:
                        path = self.downloader(entry, root / f"source-{index}.media")
                        info = self.probe_media(path)
                        if not info.get("has_audio"):
                            raise ValueError("素材没有音轨，无法转写")
                        duration = _seconds(info.get("duration") or entry.get("duration"))
                        if duration <= 0:
                            raise ValueError("音频时长无效，无法转写")
                        budget -= duration
                        item["duration"] = round(duration, 3)
                        self._save(owner, ride, token, {
                            "items": results,
                            "message": f"正在提取音轨 {index}/{total}",
                            "progress": 5 + round(index * 92 / max(1, total)),
                        }, "running")
                        wav = self.extract(path, root / f"source-{index}.wav")
                        result = self.transcriber(wav)
                        segments = self._segments(result.get("segments") if isinstance(result, dict) else None)
                        item["language"] = _text(result.get("language") if isinstance(result, dict) else None, 32) or None
                        item["audio_seconds"] = _seconds(result.get("usage_seconds") if isinstance(result, dict) else None) or duration
                        item["segments"] = segments
                        item["segment_count"] = len(segments)
                        if segments:
                            item["status"] = "succeeded"
                            item["error"] = None
                        else:
                            item["status"] = "empty"
                            item["error"] = "这段音轨没有识别到语音"
                    except Exception as error:
                        item["status"] = "failed"
                        item["error"] = _text(error, 500) or "音频转写失败"
                        item["segments"], item["segment_count"] = [], 0
                    self._save(owner, ride, token, {
                        "items": results,
                        "message": f"正在转写 {index}/{total}",
                        "progress": 5 + round(index * 92 / max(1, total)),
                    }, "running")
                summary = self._summary(results)
                processed = [item for item in results if item["status"] != "skipped"]
                if not any(item["status"] == "succeeded" for item in processed):
                    status = "empty" if not any(item["status"] == "failed" for item in processed) else "failed"
                    message = ("音轨已转写，但没有识别到任何语音" if status == "empty"
                               else "音频转写没有成功，请检查素材音轨与转写服务配置")
                elif summary["failed_count"]:
                    status, message = "partial", (f"已转写 {summary['transcribed_count']} 条素材，"
                                                 f"{summary['failed_count'] + summary['skipped_count']} 条未成功")
                else:
                    status, message = "succeeded", (f"已转写 {summary['transcribed_count']} 条素材、"
                                                   f"{summary['segment_count']} 段语音")
                self._save(owner, ride, token, {
                    "items": results, "progress": 100, "message": message,
                    "summary": summary, "finished_at": timestamp(), "run_token": None,
                }, status)
        except _Superseded:
            return
        except Exception as error:
            try:
                self._save(owner, ride, token, {"message": _text(error, 500) or "音频转写中断",
                                                "finished_at": timestamp(), "run_token": None}, "failed")
            except Exception:
                logger.debug("音频转写失败状态写回失败（owner=%s）", owner, exc_info=True)

    def summary(self, owner: str, project: str, sequence: str) -> dict:
        record = self._existing(owner, project, sequence)
        if not record:
            return {"status": "missing", "segment_count": 0, "transcribed_count": 0}
        changed = self._source_changed(owner, project, sequence, record)
        stored = record.get("summary") or {}
        return {"status": record.get("status"), "model": record.get("model"),
                "transcribed_at": record.get("finished_at"), "stale": changed,
                "message": record.get("message"),
                "media_count": int(stored.get("media_count") or 0),
                "transcribed_count": int(stored.get("transcribed_count") or 0),
                "segment_count": 0 if changed else int(stored.get("segment_count") or 0),
                "audio_seconds": 0.0 if changed else float(stored.get("audio_seconds") or 0),
                "progress": int(record.get("progress") or 0)}

    def evidence(self, owner: str, project: str, sequence: str) -> tuple[dict[str, dict], dict]:
        record = self._existing(owner, project, sequence)
        if not record or record.get("status") not in {"succeeded", "partial", "empty"}:
            return {}, {"status": record.get("status") if record else "missing", "used_count": 0, "segment_count": 0}
        if self._source_changed(owner, project, sequence, record):
            return {}, {"status": "stale", "used_count": 0, "segment_count": 0}
        evidence = {}
        for item in record.get("items") or []:
            if item.get("status") != "succeeded" or not item.get("segments"):
                continue
            evidence[str(item["asset_id"])] = item
        stored = record.get("summary") or {}
        return evidence, {"status": record.get("status"), "model": record.get("model"),
                          "transcribed_at": record.get("finished_at"),
                          "transcribed_count": int(stored.get("transcribed_count") or 0),
                          "used_count": len(evidence),
                          "segment_count": sum(len(item.get("segments") or []) for item in evidence.values()),
                          "audio_seconds": round(sum(float(item.get("audio_seconds") or 0) for item in evidence.values()), 2)}

    def recover(self) -> None:
        with self.repo.store.connection() as conn:
            rows = conn.execute(f"SELECT id,owner_id FROM ai_assistant_records WHERE kind='{KIND}' "
                                "AND status IN ('queued','running')").fetchall()
        for row in rows:
            try:
                record = self.repo.get(row["owner_id"], row["id"], KIND)
                self.repo.update(row["owner_id"], record, {
                    "message": "服务重启，音频转写已中断，请重新开始", "run_token": None,
                    "finished_at": timestamp(),
                }, status="failed")
            except Exception:
                logger.debug("重启恢复时音频转写中断状态写回失败（record=%s）", row["id"], exc_info=True)
                continue
