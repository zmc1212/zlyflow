from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ...director_stream import DirectorOperationEventBus, terminal_event_for_status
from ...llm_client import LlmStreamHook
from ..db import execute_sql, now_str, query_all, query_one

JOB_TYPE = "asset_extraction"
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asset-extraction")
_DISPATCH_LOCK = threading.Lock()
_ACTIVE: set[str] = set()
_ACTIVE_LOCK = threading.Lock()
_EVENTS = DirectorOperationEventBus()
_STREAM_LOCK = threading.Lock()
_STREAM_STATE: dict[str, dict[str, Any]] = {}
_STREAM_FLUSH_AT: dict[str, float] = {}
_STREAM_FLUSH_INTERVAL = 1.2
_ACTIVE_STATUSES = ("queued", "preparing", "running")


class AssetExtractionJobService:
    @classmethod
    def enqueue(cls, project_id: str, doc_id: str) -> dict[str, Any]:
        row = query_one(
            "SELECT id, filename, raw_text FROM ai_project_documents WHERE id = %s AND project_id = %s",
            (doc_id, project_id),
        )
        if not row:
            raise ValueError("文档不存在")
        if not str(row.get("raw_text") or "").strip():
            raise ValueError("剧本还没有正文，无法拆解资产")

        for existing in query_all(
            "SELECT id, status, payload_json FROM ai_project_jobs WHERE project_id = %s AND job_type = %s "
            "AND status IN ('queued','preparing','running') ORDER BY created_at DESC",
            (project_id, JOB_TYPE),
        ):
            payload = cls._payload(existing)
            if str(payload.get("document_id") or "") == doc_id:
                return {"job_id": existing["id"], "document_id": doc_id,
                        "status": existing["status"], "duplicate": True}

        filename = str(row.get("filename") or "剧本文档").strip() or "剧本文档"
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        payload = {
            "target_type": JOB_TYPE,
            "project_id": project_id,
            "document_id": doc_id,
            "filename": filename,
            "phase": "queued",
            "message": "已加入拆解队列",
            "chars": 0,
        }
        execute_sql(
            "INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,'queued',0,NULL,%s,%s,%s)",
            (job_id, project_id, JOB_TYPE, f"拆解剧本资产: {filename}",
             json.dumps(payload, ensure_ascii=False), timestamp, timestamp),
        )
        cls.kick()
        return {"job_id": job_id, "document_id": doc_id, "status": "queued"}

    @classmethod
    def active_job_ids_by_document(cls, project_id: str) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for row in query_all(
            "SELECT id, payload_json FROM ai_project_jobs WHERE project_id = %s AND job_type = %s "
            "AND status IN ('queued','preparing','running') ORDER BY created_at ASC",
            (project_id, JOB_TYPE),
        ):
            doc_id = str(cls._payload(row).get("document_id") or "").strip()
            if doc_id and doc_id not in mapping:
                mapping[doc_id] = row["id"]
        return mapping

    @classmethod
    def bind_loop(cls) -> None:
        try:
            _EVENTS.bind_loop()
        except RuntimeError:
            pass

    @classmethod
    async def stream(cls, job_id: str, project_id: str, request: Any, since: int = 0):
        cls.bind_loop()
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (job_id, project_id)) or {}
        if not row or row.get("job_type") != JOB_TYPE:
            raise ValueError("资产拆解任务不存在")
        queue, replay = _EVENTS.subscribe(job_id, since=max(0, since))
        try:
            if not replay:
                snapshot = cls._public_stream_snapshot(row)
                if snapshot:
                    yield snapshot
                    if snapshot.get("terminal"):
                        return
            for event in replay:
                yield event
                if event.get("terminal"):
                    return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    current = query_one(
                        "SELECT status,error_message,payload_json FROM ai_project_jobs WHERE id=%s AND project_id=%s",
                        (job_id, project_id),
                    ) or {}
                    if str(current.get("status") or "") in {"completed", "succeeded", "failed"}:
                        yield cls._terminal_from_row(current)
                        return
                    yield {"event": "keep-alive", "data": {}}
                    continue
                if event is None:
                    return
                yield event
                if event.get("terminal"):
                    return
        finally:
            _EVENTS.unsubscribe(job_id, queue)

    @classmethod
    def _public_stream_snapshot(cls, row: dict[str, Any]) -> dict[str, Any] | None:
        payload = cls._payload(row)
        status = str(row.get("status") or "")
        if status in {"completed", "succeeded", "failed"}:
            return cls._terminal_from_row(row)
        stream = payload.get("stream") if isinstance(payload.get("stream"), dict) else {}
        if not stream and status not in _ACTIVE_STATUSES:
            return None
        return {
            "event": "status",
            "data": {
                "phase": stream.get("phase") or payload.get("phase") or "prepare",
                "message": stream.get("message") or payload.get("message") or "正在准备拆解资产",
                "chars": int(stream.get("chars") or payload.get("chars") or 0),
            },
        }

    @classmethod
    def _terminal_from_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        payload = cls._payload(row)
        if str(row.get("status") or "") == "failed":
            return terminal_event_for_status("failed", message=str(row.get("error_message") or "资产拆解失败"))
        return {
            "event": "done",
            "terminal": True,
            "data": {
                "status": "succeeded",
                "document_id": payload.get("document_id"),
                "transferred": payload.get("transferred") or {},
                "total": payload.get("total") or 0,
                "skipped": payload.get("skipped") or [],
                "skipped_count": payload.get("skipped_count") or 0,
            },
        }

    @classmethod
    def kick(cls) -> None:
        if not _DISPATCH_LOCK.acquire(blocking=False):
            return
        try:
            with _ACTIVE_LOCK:
                capacity = max(0, 1 - len(_ACTIVE))
            if not capacity:
                return
            for row in query_all(
                "SELECT id FROM ai_project_jobs WHERE job_type = %s AND status = 'queued' "
                "ORDER BY created_at ASC LIMIT 20",
                (JOB_TYPE,),
            ):
                if capacity <= 0:
                    break
                job_id = row["id"]
                if execute_sql(
                    "UPDATE ai_project_jobs SET status='preparing',progress=5,updated_at=%s WHERE id=%s AND status='queued'",
                    (now_str(), job_id),
                ) != 1:
                    continue
                with _ACTIVE_LOCK:
                    _ACTIVE.add(job_id)
                _EXECUTOR.submit(cls._run, job_id)
                capacity -= 1
        finally:
            _DISPATCH_LOCK.release()

    @classmethod
    def recover_interrupted_jobs(cls) -> None:
        for row in query_all(
            "SELECT id,status FROM ai_project_jobs WHERE job_type=%s AND status IN ('preparing','running')",
            (JOB_TYPE,),
        ):
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,updated_at=%s WHERE id=%s",
                ("服务重启时资产拆解任务已中断，请重新拆解。", now_str(), row["id"]),
            )
        cls.kick()

    @classmethod
    def _emit(cls, job_id: str, event: dict[str, Any]) -> None:
        _EVENTS.emit(job_id, event)

    @classmethod
    def _progress(cls, job_id: str, *, phase: str, message: str, chars: int | None = None,
                  progress: int | None = None, force: bool = False) -> None:
        with _STREAM_LOCK:
            state = _STREAM_STATE.setdefault(job_id, {"phase": "prepare", "message": "正在准备拆解资产", "chars": 0})
            state["phase"] = phase
            state["message"] = message
            if chars is not None:
                state["chars"] = chars
            now = time.monotonic()
            last = _STREAM_FLUSH_AT.get(job_id) or 0.0
            if not force and now - last < _STREAM_FLUSH_INTERVAL:
                return
            _STREAM_FLUSH_AT[job_id] = now
            snapshot = dict(state)
        cls._emit(job_id, {"event": "status", "data": snapshot})
        execute_sql(
            "UPDATE ai_project_jobs SET progress=%s,updated_at=%s WHERE id=%s",
            (max(0, min(progress if progress is not None else 15, 99)), now_str(), job_id),
        )
        row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        payload = cls._payload(row)
        payload["phase"] = snapshot.get("phase")
        payload["message"] = snapshot.get("message")
        payload["chars"] = snapshot.get("chars")
        payload["stream"] = snapshot
        execute_sql(
            "UPDATE ai_project_jobs SET payload_json=%s,updated_at=%s WHERE id=%s",
            (json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )

    @classmethod
    def _clear_stream_state(cls, job_id: str) -> None:
        with _STREAM_LOCK:
            _STREAM_STATE.pop(job_id, None)
            _STREAM_FLUSH_AT.pop(job_id, None)

    @classmethod
    def _run(cls, job_id: str) -> None:
        from .project_detail_service import ProjectDetailService

        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        payload = cls._payload(row)
        project_id = str(payload.get("project_id") or row.get("project_id") or "").strip()
        doc_id = str(payload.get("document_id") or "").strip()
        chars = 0
        try:
            execute_sql(
                "UPDATE ai_project_jobs SET status='running',progress=10,updated_at=%s WHERE id=%s",
                (now_str(), job_id),
            )
            if not project_id or not doc_id:
                raise ValueError("任务缺少文档")

            stage = {"progress": 12, "phase": "prepare", "message": "正在通读剧本并整理资产"}

            def on_phase(message: str, reset: bool) -> None:
                nonlocal chars
                if reset:
                    chars = 0
                if "重新" in message and "名称" in message:
                    phase, progress = "extract", 20
                elif "确定" in message:
                    phase, progress = "extract", 12
                elif "整理角色" in message:
                    phase, progress = "describe", 35
                elif "整理场景" in message:
                    phase, progress = "describe", 55
                elif "整理道具" in message:
                    phase, progress = "describe", 72
                elif "写入" in message:
                    phase, progress = "save", 94
                else:
                    phase, progress = "extract", 15
                stage.update(progress=progress, phase=phase, message=message)
                cls._progress(job_id, phase=phase, message=message, chars=chars,
                              progress=progress, force=True)

            def on_delta(_kind: str, piece: str) -> None:
                nonlocal chars
                chars += len(piece)
                progress = max(stage["progress"], min(90, 15 + chars // 120))
                cls._progress(job_id, phase=stage["phase"], message=stage["message"],
                              chars=chars, progress=progress)

            cls._progress(job_id, phase="prepare", message="正在通读剧本并整理资产", progress=12, force=True)
            with LlmStreamHook(on_delta=on_delta):
                result = ProjectDetailService.transfer_assets_from_document(
                    project_id, doc_id, mode="append", on_phase=on_phase,
                )
            transferred = result.get("transferred") if isinstance(result, dict) else {}
            total = int(result.get("total") or 0) if isinstance(result, dict) else 0
            skipped = result.get("skipped") if isinstance(result, dict) else []
            skipped = skipped if isinstance(skipped, list) else []
            payload.update({
                "phase": "done",
                "message": "制作资产已写入资产库",
                "transferred": transferred or {},
                "total": total,
                "skipped": skipped[:50],
                "skipped_count": len(skipped),
            })
            payload.pop("stream", None)
            execute_sql(
                "UPDATE ai_project_jobs SET status='completed',progress=100,payload_json=%s,error_message=NULL,updated_at=%s WHERE id=%s",
                (json.dumps(payload, ensure_ascii=False), now_str(), job_id),
            )
            cls._emit(job_id, {
                "event": "done",
                "terminal": True,
                "data": {"status": "succeeded", "document_id": doc_id,
                         "transferred": transferred or {}, "total": total,
                         "skipped": skipped[:50], "skipped_count": len(skipped)},
            })
        except Exception as err:
            message = str(err)[:1000] or "资产拆解失败"
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,updated_at=%s WHERE id=%s",
                (message, now_str(), job_id),
            )
            cls._emit(job_id, terminal_event_for_status("failed", message=message))
        finally:
            cls._clear_stream_state(job_id)
            with _ACTIVE_LOCK:
                _ACTIVE.discard(job_id)
            cls.kick()

    @staticmethod
    def _payload(row: dict[str, Any]) -> dict[str, Any]:
        raw = row.get("payload_json")
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
