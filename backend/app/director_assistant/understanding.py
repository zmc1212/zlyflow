from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from ..media_studio.services import smart_edit_service
from ..media_studio.services.smart_edit_render import probe
from ..video_analysis import Segment, detect_scenes, extract_keyframes
from .editing import EditingActions
from .repository import AssistantConflict, AssistantNotFound, AssistantRepository, timestamp

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="assistant-understanding")
ACTIVE = {"queued", "running"}
STALE_SECONDS = 15 * 60
SCENE_THRESHOLD = 0.32
MIN_SHOT_SECONDS = 0.8
MAX_SHOTS_PER_VIDEO = 4
MAX_TOTAL_SHOTS = 40


def _empty_summary(video_count: int = 0, failed_count: int = 0) -> dict:
    return {"video_count": video_count, "analyzed_count": 0, "failed_count": failed_count,
            "detected_shot_count": 0, "shot_count": 0, "shot_analyzed_count": 0, "shot_failed_count": 0}


class _Superseded(Exception):
    pass


def record_id(owner: str, project: str, sequence: str) -> str:
    digest = hashlib.sha256(f"media-understanding|{owner}|{project}|{sequence}".encode()).hexdigest()
    return f"und-{digest[:40]}"


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _subjects(value: Any) -> list[dict]:
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 80)
        if not name:
            continue
        result.append({"name": name, "type": _text(item.get("type"), 24) or "prop",
                       "description": _text(item.get("description"), 300)})
        if len(result) >= 8:
            break
    return result


class MediaUnderstanding:
    """Frame-based visual understanding for the smart edit assistant.

    Only media already used by the timeline is downloaded from the configured
    object storage. Each source is split into shots with ffmpeg scene detection;
    up to four sampled shots per source (40 in total) are analysed at two frames
    each. Audio is not transcribed and no timeline data is changed.
    """

    def __init__(self, repo: AssistantRepository, vlm_provider=None, *, downloader: Callable | None = None,
                 probe_media: Callable | None = None, keyframes: Callable | None = None,
                 detect_shots: Callable | None = None, run_async: bool = True, executor=None):
        self.repo = repo
        self.vlm = vlm_provider
        self.downloader = downloader or smart_edit_service.download_asset
        self.probe_media = probe_media or probe
        self.keyframes = keyframes or extract_keyframes
        self.detect_shots = detect_shots or self._detect_shot_segments
        self.run_async = run_async
        self.executor = executor or _EXECUTOR

    @staticmethod
    def _detect_shot_segments(path: Path, duration: float) -> list[Segment]:
        return detect_scenes(path, threshold=SCENE_THRESHOLD, min_duration=MIN_SHOT_SECONDS,
                             max_duration=max(60.0, duration * 2))

    @staticmethod
    def _sample_segments(segments: list[Segment], limit: int) -> list[Segment]:
        if not segments or limit <= 0:
            return []
        if len(segments) <= limit:
            return list(segments)
        if limit == 1:
            return [max(segments, key=lambda segment: segment.end - segment.start)]
        step = (len(segments) - 1) / (limit - 1)
        indices = sorted({int(round(index * step)) for index in range(limit)})
        return [segments[index] for index in indices]

    @classmethod
    def _plan_samples(cls, videos: list[dict]) -> int:
        for video in videos:
            video["_sample"] = cls._sample_segments(video.get("_segments") or [], MAX_SHOTS_PER_VIDEO)
        total = sum(len(video["_sample"]) for video in videos)
        if total <= MAX_TOTAL_SHOTS:
            return total
        if len(videos) >= MAX_TOTAL_SHOTS:
            step = (len(videos) - 1) / (MAX_TOTAL_SHOTS - 1)
            keep = {int(round(index * step)) for index in range(MAX_TOTAL_SHOTS)}
            for index, video in enumerate(videos):
                video["_sample"] = cls._sample_segments(video.get("_segments") or [], 1) if index in keep else []
            return sum(len(video["_sample"]) for video in videos)
        selected = {id(video): [video["_sample"][0]] for video in videos if video["_sample"]}
        pool = [(video, segment) for video in videos for segment in video["_sample"][1:]]
        remaining = MAX_TOTAL_SHOTS - len(selected)
        if remaining > 0 and pool:
            if remaining == 1:
                indices = {0}
            else:
                step = (len(pool) - 1) / (remaining - 1)
                indices = {int(round(index * step)) for index in range(remaining)}
            for index in sorted(indices):
                video, segment = pool[index]
                selected[id(video)].append(segment)
        for video in videos:
            video["_sample"] = sorted(selected.get(id(video), []), key=lambda segment: segment.start)
        return sum(len(video["_sample"]) for video in videos)

    @staticmethod
    def public(record: dict) -> dict:
        return {key: value for key, value in record.items() if not key.startswith("_") and key not in {"run_token"}}

    def _existing(self, owner: str, project: str, sequence: str) -> dict | None:
        try:
            return self.repo.get(owner, record_id(owner, project, sequence), "media_understanding")
        except AssistantNotFound:
            return None

    @staticmethod
    def _signature(videos: list[dict]) -> str:
        values = sorted((str(video.get("beat_id") or video.get("id") or ""), str(video.get("url") or ""),
                         round(float(video.get("duration") or 0), 3)) for video in videos)
        return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()

    def _source_videos(self, owner: str, project: str, sequence: str) -> list[dict]:
        if sequence == "main":
            with self.repo.store.connection() as conn:
                snapshot = EditingActions.snapshot(conn, owner, project, sequence)
            candidates = [dict(asset) for asset in snapshot["document"].get("assets") or [] if asset.get("kind") == "video"]
        else:
            candidates = [dict(item) for item in smart_edit_service.project_sources(project, sequence) if item.get("kind") == "video"]
        videos, seen = [], set()
        for video in candidates:
            key = str(video.get("beat_id") or video.get("id") or video.get("url") or "")
            if not key or key in seen or not video.get("url"):
                continue
            seen.add(key)
            videos.append({"id": str(video.get("id") or key), "name": str(video.get("name") or "视频"),
                           "url": str(video["url"]), "duration": float(video.get("duration") or 0),
                           "beat_id": video.get("beat_id")})
        return videos

    def _target(self, project: str, sequence: str) -> None:
        with self.repo.store.connection() as conn:
            EditingActions.target(conn, project, sequence)

    def _model(self) -> tuple[str | None, str | None]:
        if self.vlm is None:
            return None, "视觉模型尚未启用。请在管理设置 → VLM 视觉模型 中配置后再使用视频理解。"
        try:
            available, reason = self.vlm.availability()
            model = self.vlm.vision_model_name()
        except Exception as error:
            return None, str(error)
        if not available or not model:
            return None, reason or "视觉模型不可用，请先在管理设置中检查 VLM 配置。"
        return model, None

    def _source_changed(self, owner: str, project: str, sequence: str, record: dict) -> bool:
        try:
            return record.get("source_signature") != self._signature(self._source_videos(owner, project, sequence))
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
                    "items": [], "summary": _empty_summary()}
        if self._stale(record):
            record = self.repo.update(owner, record, {"message": "视频理解已中断，请重新开始", "run_token": None}, status="failed")
        result = self.public(record)
        if record.get("status") not in ACTIVE and self._source_changed(owner, project, sequence, record):
            result["stale"] = True
        return result

    def start(self, owner: str, project: str, sequence: str, *, force: bool = False) -> dict:
        self._target(project, sequence)
        videos = self._source_videos(owner, project, sequence)
        signature = self._signature(videos)
        existing = self._existing(owner, project, sequence)
        if existing and existing.get("status") in ACTIVE:
            if not self._stale(existing):
                raise AssistantConflict("视频理解正在进行，请稍候查看结果")
            existing = self.repo.update(owner, existing, {
                "message": "视频理解已中断，请重新开始", "run_token": None,
            }, status="failed")
        model, reason = self._model()
        if not videos:
            return self._store(owner, project, sequence, existing, {
                "project_id": project, "sequence_id": sequence, "model": model,
                "source_signature": signature, "progress": 100, "message": "时间线上还没有可理解的视频",
                "summary": _empty_summary(),
                "items": [], "finished_at": timestamp(), "run_token": None,
            }, "empty")
        if reason:
            return self._store(owner, project, sequence, existing, {
                "project_id": project, "sequence_id": sequence, "model": None,
                "source_signature": signature, "progress": 0, "message": reason,
                "summary": _empty_summary(len(videos), len(videos)),
                "items": [], "finished_at": timestamp(), "run_token": None,
            }, "failed")
        if existing and not force and existing.get("source_signature") == signature and existing.get("model") == model \
                and existing.get("status") in {"succeeded", "partial", "empty", "failed"}:
            return self.public(existing)
        token = hashlib.sha256(f"{timestamp()}|{owner}|{project}|{sequence}".encode()).hexdigest()[:20]
        payload = {
            "project_id": project, "sequence_id": sequence, "model": model,
            "source_signature": signature, "progress": 0, "message": "正在准备视频理解",
            "summary": _empty_summary(len(videos)),
            "items": [], "started_at": timestamp(), "finished_at": None,
            "run_token": token, "_video_count": len(videos),
        }
        record = self._store(owner, project, sequence, existing, payload, "queued")
        if self.run_async:
            self.executor.submit(self._run, owner, record["id"], token, videos)
        else:
            self._run(owner, record["id"], token, videos)
        return self.public(self.repo.get(owner, record["id"], "media_understanding"))

    def _store(self, owner: str, project: str, sequence: str, existing: dict | None,
               payload: dict, status: str) -> dict:
        if existing:
            return self.repo.update(owner, existing, payload, status=status)
        return self.repo.insert(owner, "media_understanding", payload, record_id=record_id(owner, project, sequence),
                                parent=smart_edit_service.document_id(project, owner, sequence), status=status)

    def _save(self, owner: str, ride: str, token: str, changes: dict, status: str) -> dict:
        record = self.repo.get(owner, ride, "media_understanding")
        if record.get("run_token") != token:
            raise _Superseded()
        return self.repo.update(owner, record, changes, status=status)

    def _analyze(self, encoded: list[str], index: int, duration: float) -> dict:
        last = None
        for attempt in range(2):
            try:
                return self.vlm.analyze_video_shot(frames=encoded, shot_number=index, duration_sec=duration)
            except Exception as error:
                last = error
                if attempt == 0:
                    time.sleep(1.5)
        raise last

    @staticmethod
    def _summary(videos: list[dict], total_shots: int, detected_total: int) -> dict:
        items = [video["_item"] for video in videos]
        videos_ok = sum(1 for item in items if item.get("status") in {"succeeded", "partial"})
        shots = [shot for item in items for shot in item.get("shots") or []]
        shots_ok = sum(1 for shot in shots if shot.get("status") == "succeeded")
        return {
            "video_count": len(videos),
            "analyzed_count": videos_ok,
            "failed_count": len(videos) - videos_ok,
            "detected_shot_count": detected_total,
            "shot_count": total_shots,
            "shot_analyzed_count": shots_ok,
            "shot_failed_count": len(shots) - shots_ok,
        }

    @staticmethod
    def _merge_subjects(shots: list[dict]) -> list[dict]:
        merged, seen = [], set()
        for shot in shots:
            for subject in shot.get("subjects") or []:
                name = _text(subject.get("name"), 80)
                if not name or name in seen:
                    continue
                seen.add(name)
                merged.append(subject)
                if len(merged) >= 8:
                    return merged
        return merged

    def _finish_item(self, video: dict, shots: list[dict]) -> None:
        item = video["_item"]
        item["shots"] = shots
        item["sampled_count"] = len(shots)
        item["detected_count"] = len(video.get("_segments") or [])
        item["frames"] = sum(int(shot.get("frames") or 0) for shot in shots)
        succeeded = [shot for shot in shots if shot.get("status") == "succeeded"]
        if not shots:
            item["status"] = "failed"
            item["error"] = item.get("error") or "本次理解已达单次镜头上限，未分析此素材"
            item["description"], item["camera"], item["subjects"] = "", "", []
            return
        if not succeeded:
            item["status"] = "failed"
            item["error"] = next((shot.get("error") for shot in shots if shot.get("error")), "镜头理解失败")
            item["description"], item["camera"], item["subjects"] = "", "", []
            return
        item["status"] = "succeeded" if len(succeeded) == len(shots) else "partial"
        item["description"] = _text(
            succeeded[0]["description"] if len(succeeded) == 1 else
            "；".join(f"镜头{shot['index']}：{shot['description']}" for shot in succeeded), 1200)
        cameras = list(dict.fromkeys(str(shot.get("camera") or "").strip() for shot in succeeded
                                     if str(shot.get("camera") or "").strip()))
        item["camera"] = _text("；".join(cameras), 200)
        item["subjects"] = self._merge_subjects(succeeded)
        item["error"] = None

    def _analyse_shot(self, video: dict, segment: Segment, shot_number: int, video_index: int,
                      shot_index: int, root: Path) -> dict:
        source_duration = float(video.get("_duration") or 0)
        start = max(0.0, float(segment.start))
        end = min(source_duration, max(start, float(segment.end))) if source_duration else float(segment.end)
        duration = max(0.05, end - start)
        shot = {"index": shot_index, "start": round(start, 3), "end": round(end, 3),
                "duration": round(duration, 3), "status": "failed", "description": "",
                "camera": "", "subjects": [], "frames": 0, "error": None}
        try:
            last = max(start, end - 0.05)
            first = min(last, start + min(0.2, duration / 2))
            middle = min(last, start + duration / 2)
            frames = self.keyframes(video["_path"], times=[first, middle], dest_dir=root,
                                    stem=f"video-{video_index}-shot-{shot_index}")
            if not frames:
                raise ValueError("未能提取关键帧，请检查视频编码")
            encoded = ["data:image/jpeg;base64," + base64.b64encode(Path(frame).read_bytes()).decode("ascii")
                       for frame in frames[:2]]
            result = self._analyze(encoded, shot_number, duration)
            description = _text(result.get("description") or result.get("promptText"), 1200)
            if not description:
                raise ValueError("视觉模型没有返回画面描述")
            shot.update(status="succeeded", description=description, camera=_text(result.get("camera"), 200),
                        subjects=_subjects(result.get("subjects")), frames=len(encoded))
        except Exception as error:
            shot["error"] = _text(error, 500) or "镜头理解失败"
        return shot

    def _run(self, owner: str, ride: str, token: str, videos: list[dict]) -> None:
        try:
            with tempfile.TemporaryDirectory(prefix="zly-understanding-") as directory:
                root = Path(directory)
                total_videos = len(videos)
                detected_total = 0
                for video in videos:
                    video["_item"] = {
                        "beat_id": video.get("beat_id"), "asset_id": video["id"], "name": video["name"],
                        "duration": round(float(video.get("duration") or 0), 3), "status": "failed",
                        "description": "", "camera": "", "subjects": [], "frames": 0,
                        "detected_count": 0, "sampled_count": 0, "shots": [], "error": "等待分析",
                    }
                for index, video in enumerate(videos, 1):
                    item = video["_item"]
                    try:
                        path = self.downloader(video, root / f"source-{index}.media")
                        info = self.probe_media(path)
                        duration = float(info.get("duration") or video.get("duration") or 0)
                        if not info.get("has_video", True):
                            raise ValueError("素材没有视频画面，无法进行画面理解")
                        if duration <= 0:
                            raise ValueError("视频时长无效，无法进行画面理解")
                        video["_path"], video["_duration"] = path, duration
                        item["duration"] = round(duration, 3)
                        try:
                            segments = [segment for segment in self.detect_shots(path, duration)
                                        if segment.end - segment.start >= 0.05]
                            detection_error = None
                        except Exception as error:
                            segments, detection_error = [], _text(error, 300) or "镜头边界检测失败"
                        if not segments:
                            segments = [Segment(start=0.0, end=duration)]
                        video["_segments"] = segments
                        video["_detection_error"] = detection_error
                        item["detected_count"] = len(segments)
                        if detection_error:
                            item["detection_error"] = detection_error
                        item["error"] = None
                        detected_total += len(segments)
                    except Exception as error:
                        item["error"] = _text(error, 500) or "素材读取失败"
                    self._save(owner, ride, token, {
                        "items": [entry["_item"] for entry in videos],
                        "message": f"正在检测镜头边界 {index}/{total_videos}",
                        "progress": 2 + round(index * 10 / max(1, total_videos)),
                    }, "running")
                prepared = [video for video in videos if video.get("_path")]
                total_shots = self._plan_samples(prepared)
                done = 0
                for video_index, video in enumerate(prepared, 1):
                    shots = []
                    for shot_index, segment in enumerate(video["_sample"], 1):
                        done += 1
                        self._save(owner, ride, token, {
                            "message": f"正在理解第 {done}/{total_shots} 个镜头",
                            "progress": 12 + round(done * 83 / max(1, total_shots)),
                        }, "running")
                        shots.append(self._analyse_shot(video, segment, done, video_index, shot_index, root))
                    self._finish_item(video, shots)
                    self._save(owner, ride, token, {
                        "items": [entry["_item"] for entry in videos],
                        "progress": 12 + round(done * 83 / max(1, total_shots)),
                        "summary": self._summary(videos, total_shots, detected_total),
                        "message": f"已检测 {detected_total} 个镜头，已理解 {done}/{total_shots}",
                    }, "running")
                for video in prepared:
                    if not video.get("_sample"):
                        self._finish_item(video, [])
                items = [video["_item"] for video in videos]
                summary = self._summary(videos, total_shots, detected_total)
                if not summary["shot_analyzed_count"]:
                    status, message = "failed", "视频理解没有成功，请检查素材地址与视觉模型配置"
                elif summary["failed_count"] or summary["shot_failed_count"]:
                    status = "partial"
                    message = f"已理解 {summary['shot_analyzed_count']} 个镜头，{summary['shot_failed_count']} 个失败"
                else:
                    status = "succeeded"
                    message = f"已理解 {summary['analyzed_count']} 条素材、{summary['shot_analyzed_count']} 个镜头"
                self._save(owner, ride, token, {
                    "items": items, "progress": 100, "message": message, "finished_at": timestamp(),
                    "summary": summary, "run_token": None,
                }, status)
        except _Superseded:
            return
        except Exception as error:
            try:
                self._save(owner, ride, token, {"message": _text(error, 500) or "视频理解中断",
                                                "finished_at": timestamp(), "run_token": None}, "failed")
            except Exception:
                pass

    def summary(self, owner: str, project: str, sequence: str, *, limit: int = 12) -> dict:
        record = self._existing(owner, project, sequence)
        if not record:
            return {"status": "missing", "visual_analyzed_count": 0}
        changed = self._source_changed(owner, project, sequence, record)
        items = []
        if record.get("status") in {"succeeded", "partial"} and not changed:
            for item in (record.get("items") or [])[:limit]:
                if item.get("status") not in {"succeeded", "partial"}:
                    continue
                items.append({"beat_id": item.get("beat_id"), "name": item.get("name"),
                              "description": _text(item.get("description"), 400),
                              "camera": _text(item.get("camera"), 120),
                              "subjects": [subject.get("name") for subject in item.get("subjects") or []][:6],
                              "status": item.get("status"),
                              "detected_count": int(item.get("detected_count") or 0),
                              "shot_count": int(item.get("sampled_count") or 0)})
        stored = record.get("summary") or {}
        return {"status": record.get("status"), "model": record.get("model"),
                "analyzed_at": record.get("finished_at"), "stale": changed,
                "visual_analyzed_count": int(stored.get("analyzed_count") or 0),
                "video_count": int(stored.get("video_count") or 0),
                "detected_shot_count": int(stored.get("detected_shot_count") or 0),
                "shot_count": int(stored.get("shot_count") or 0),
                "shot_analyzed_count": int(stored.get("shot_analyzed_count") or 0),
                "message": record.get("message"), "items": items}

    def evidence(self, owner: str, project: str, sequence: str) -> tuple[dict[str, dict], dict]:
        record = self._existing(owner, project, sequence)
        if not record or record.get("status") not in {"succeeded", "partial"}:
            return {}, {"status": record.get("status") if record else "missing", "used_count": 0,
                        "shot_used_count": 0}
        if self._source_changed(owner, project, sequence, record):
            return {}, {"status": "stale", "used_count": 0, "shot_used_count": 0}
        evidence = {}
        for item in record.get("items") or []:
            if item.get("status") not in {"succeeded", "partial"}:
                continue
            if item.get("beat_id"):
                evidence[str(item["beat_id"])] = item
            if item.get("asset_id"):
                # Asset-keyed entries (prefix avoids colliding with beat ids) let
                # free-edit sequences and clip-level lookups use the same record.
                evidence.setdefault(f"asset:{item['asset_id']}", item)
        stored = record.get("summary") or {}
        return evidence, {"status": record.get("status"), "model": record.get("model"),
                          "analyzed_count": int(stored.get("analyzed_count") or 0),
                          "shot_count": int(stored.get("shot_count") or 0),
                          "shot_analyzed_count": int(stored.get("shot_analyzed_count") or 0)}

    def recover(self) -> None:
        with self.repo.store.connection() as conn:
            rows = conn.execute("SELECT id,owner_id FROM ai_assistant_records WHERE kind='media_understanding' "
                                "AND status IN ('queued','running')").fetchall()
        for row in rows:
            try:
                record = self.repo.get(row["owner_id"], row["id"], "media_understanding")
                self.repo.update(row["owner_id"], record, {
                    "message": "服务重启，视频理解已中断，请重新开始", "run_token": None,
                    "finished_at": timestamp(),
                }, status="failed")
            except Exception:
                continue
