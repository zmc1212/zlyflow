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
from .episode_shot_planner import (
    apply_episode_shot_plan,
    is_ai_pipeline_document,
    needs_episode_shot_plan,
    shot_plan_episode_indexes,
)
from .llm_service import LlmService


JOB_TYPE = "shot_plan"
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="shot-plan")
_DISPATCH_LOCK = threading.Lock()
_ACTIVE: set[str] = set()
_ACTIVE_LOCK = threading.Lock()
_EVENTS = DirectorOperationEventBus()
_STREAM_LOCK = threading.Lock()
_STREAM_STATE: dict[str, dict[str, Any]] = {}
_STREAM_FLUSH_AT: dict[str, float] = {}
_STREAM_FLUSH_INTERVAL = 0.45
_ACTIVE_STATUSES = ("queued", "preparing", "running")


class ShotPlanJobService:
    @classmethod
    def enqueue(cls, project_id: str, doc_id: str) -> dict[str, Any]:
        from .project_detail_service import ProjectDetailService

        row = query_one(
            "SELECT * FROM ai_project_documents WHERE id = %s AND project_id = %s",
            (doc_id, project_id),
        )
        if not row:
            raise ValueError("文档不存在")
        if is_ai_pipeline_document(row.get("input_mode")):
            raise ValueError("AI 流水线文档不需要二次规划出片镜头")
        analysis = ProjectDetailService._analysis_for_document_row(row) or {}
        indexes = shot_plan_episode_indexes(analysis, input_mode=row.get("input_mode"))
        if not indexes:
            raise ValueError("没有需要规划的分集")

        for existing in query_all(
            "SELECT id, status, payload_json FROM ai_project_jobs WHERE project_id = %s AND job_type = %s "
            "AND status IN ('queued','preparing','running') ORDER BY created_at DESC",
            (project_id, JOB_TYPE),
        ):
            payload = cls._payload(existing)
            if str(payload.get("document_id") or "") == doc_id:
                cls._set_document_status(project_id, doc_id, "planning")
                return {
                    "job_id": existing["id"],
                    "document_id": doc_id,
                    "status": existing["status"],
                    "duplicate": True,
                }

        filename = str(row.get("filename") or "剧本文档").strip() or "剧本文档"
        title = f"规划出片镜头: {filename}"
        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        job_payload = {
            "target_type": JOB_TYPE,
            "project_id": project_id,
            "document_id": doc_id,
            "filename": filename,
            "episode_indexes": indexes,
            "episode_total": len(indexes),
            "episodes_done": [],
        }
        execute_sql(
            "INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,'queued',0,NULL,%s,%s,%s)",
            (jid, project_id, JOB_TYPE, title, json.dumps(job_payload, ensure_ascii=False), timestamp, timestamp),
        )
        cls._set_document_status(project_id, doc_id, "planning")
        cls.kick()
        return {"job_id": jid, "document_id": doc_id, "status": "queued"}

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
            raise ValueError("镜头规划任务不存在")
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
                    status = str(current.get("status") or "")
                    if status in {"completed", "succeeded", "failed"}:
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
        stream = payload.get("stream") if isinstance(payload.get("stream"), dict) else {}
        status = str(row.get("status") or "")
        if status in {"completed", "succeeded", "failed"}:
            return cls._terminal_from_row(row)
        if not stream and status not in _ACTIVE_STATUSES:
            return None
        return {
            "event": "status",
            "data": {
                "phase": stream.get("phase") or "plan",
                "message": stream.get("message") or "正在按集规划镜头",
                "reset": False,
                "reasoning": stream.get("reasoning") or "",
                "text": stream.get("text") or "",
                "episode_index": stream.get("episode_index") or payload.get("current_episode_index") or 0,
                "episode_total": stream.get("episode_total") or payload.get("episode_total") or 0,
                "episode_num": stream.get("episode_num") or payload.get("current_episode_num"),
                "episodes_done": payload.get("episodes_done") or [],
            },
        }

    @classmethod
    def _terminal_from_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        payload = cls._payload(row)
        status = str(row.get("status") or "")
        if status == "failed":
            return terminal_event_for_status("failed", message=str(row.get("error_message") or "规划失败"))
        return {
            "event": "done",
            "terminal": True,
            "data": {
                "status": "succeeded",
                "document_id": payload.get("document_id"),
                "planned_episodes": payload.get("planned_episodes") or 0,
                "failed_episodes": payload.get("failed_episodes") or 0,
                "episodes_done": payload.get("episodes_done") or [],
            },
        }

    @classmethod
    def _emit(cls, job_id: str, event: dict[str, Any]) -> None:
        _EVENTS.emit(job_id, event)

    @classmethod
    def _patch_stream(cls, job_id: str, updates: dict[str, Any], *, force: bool = False) -> None:
        with _STREAM_LOCK:
            state = _STREAM_STATE.setdefault(job_id, {
                "phase": "plan",
                "message": "正在按集规划镜头",
                "reasoning": "",
                "text": "",
                "episode_index": 0,
                "episode_total": 0,
                "episode_num": None,
            })
            if updates.get("reset"):
                state["reasoning"] = ""
                state["text"] = ""
            for key in ("phase", "message", "reasoning", "text", "episode_index", "episode_total", "episode_num"):
                if key in updates and updates[key] is not None:
                    state[key] = updates[key]
            now = time.monotonic()
            last = _STREAM_FLUSH_AT.get(job_id) or 0.0
            if not force and now - last < _STREAM_FLUSH_INTERVAL:
                return
            _STREAM_FLUSH_AT[job_id] = now
            snapshot = dict(state)
        row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        payload = cls._payload(row)
        payload["stream"] = snapshot
        if "episode_index" in snapshot:
            payload["current_episode_index"] = snapshot.get("episode_index")
        if "episode_num" in snapshot:
            payload["current_episode_num"] = snapshot.get("episode_num")
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
    def kick(cls) -> None:
        if not _DISPATCH_LOCK.acquire(blocking=False):
            return
        try:
            with _ACTIVE_LOCK:
                capacity = max(0, 2 - len(_ACTIVE))
            if not capacity:
                return
            rows = query_all(
                "SELECT id FROM ai_project_jobs WHERE job_type = %s AND status = 'queued' "
                "ORDER BY created_at ASC LIMIT 20",
                (JOB_TYPE,),
            )
            for row in rows:
                if capacity <= 0:
                    break
                jid = row["id"]
                if execute_sql(
                    "UPDATE ai_project_jobs SET status='preparing',progress=10,updated_at=%s WHERE id=%s AND status='queued'",
                    (now_str(), jid),
                ) != 1:
                    continue
                with _ACTIVE_LOCK:
                    _ACTIVE.add(jid)
                _EXECUTOR.submit(cls._run, jid)
                capacity -= 1
        finally:
            _DISPATCH_LOCK.release()

    @classmethod
    def recover_interrupted_jobs(cls) -> None:
        active_docs: set[str] = set()
        for row in query_all(
            "SELECT id,status,project_id,payload_json FROM ai_project_jobs WHERE job_type=%s "
            "AND status IN ('queued','preparing','running')",
            (JOB_TYPE,),
        ):
            payload = cls._payload(row)
            doc_id = str(payload.get("document_id") or "").strip()
            project_id = str(row.get("project_id") or payload.get("project_id") or "").strip()
            if row["status"] == "queued":
                if doc_id:
                    active_docs.add(doc_id)
                    if project_id:
                        cls._set_document_status(project_id, doc_id, "planning")
                continue
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,updated_at=%s WHERE id=%s",
                ("服务重启时镜头规划任务已中断，请重新规划出片镜头。", now_str(), row["id"]),
            )
            if project_id and doc_id:
                cls._set_document_status(project_id, doc_id, "ready")
        for doc in query_all("SELECT id, project_id FROM ai_project_documents WHERE status = 'planning'"):
            if doc["id"] in active_docs:
                continue
            cls._set_document_status(str(doc.get("project_id") or ""), str(doc["id"]), "ready")
        cls.kick()

    @classmethod
    def retry(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (job_id, project_id))
        payload = cls._payload(row or {})
        if not row or row.get("job_type") != JOB_TYPE:
            raise ValueError("镜头规划任务不存在")
        if row.get("status") not in {"failed", "completed", "succeeded"}:
            raise ValueError("只有失败或已完成的任务可以重试")
        doc_id = str(payload.get("document_id") or "").strip()
        if not doc_id:
            raise ValueError("任务缺少文档")
        return cls.enqueue(project_id, doc_id)

    @classmethod
    def _run(cls, job_id: str) -> None:
        from .project_detail_service import ProjectDetailService

        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        payload = cls._payload(row)
        project_id = str(payload.get("project_id") or row.get("project_id") or "").strip()
        doc_id = str(payload.get("document_id") or "").strip()
        try:
            execute_sql(
                "UPDATE ai_project_jobs SET status='running',progress=15,updated_at=%s WHERE id=%s",
                (now_str(), job_id),
            )
            if not project_id or not doc_id:
                raise ValueError("任务缺少文档")
            doc = query_one(
                "SELECT * FROM ai_project_documents WHERE id = %s AND project_id = %s",
                (doc_id, project_id),
            )
            if not doc:
                raise ValueError("文档不存在")
            analysis = ProjectDetailService._analysis_for_document_row(doc) or {}
            episodes = [item for item in (analysis.get("episodes") or []) if isinstance(item, dict)]
            raw_indexes = payload.get("episode_indexes")
            if not isinstance(raw_indexes, list) or not raw_indexes:
                raw_indexes = shot_plan_episode_indexes(analysis, input_mode=doc.get("input_mode"))
            targets: list[int] = []
            for raw_index in raw_indexes:
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    continue
                if 0 <= index < len(episodes) and needs_episode_shot_plan(episodes[index], input_mode=doc.get("input_mode")):
                    targets.append(index)
            total = len(targets)
            payload["episode_total"] = total
            payload["episodes_done"] = []
            if total == 0:
                cls._finish_success(job_id, payload, project_id, doc_id, planned=0, failed=0)
                return

            cls._emit(job_id, {
                "event": "status",
                "data": {
                    "phase": "plan",
                    "message": f"正在按集规划镜头（共{total}集）",
                    "reset": False,
                    "episode_index": 0,
                    "episode_total": total,
                },
            })
            cls._patch_stream(job_id, {
                "phase": "plan",
                "message": f"正在按集规划镜头（共{total}集）",
                "episode_index": 0,
                "episode_total": total,
            }, force=True)

            current = {"episode_num": None, "episode_index": 0, "episode_total": total}
            planned = 0
            failed = 0

            def on_delta(kind: str, piece: str) -> None:
                with _STREAM_LOCK:
                    state = _STREAM_STATE.setdefault(job_id, {
                        "phase": "plan",
                        "message": "正在按集规划镜头",
                        "reasoning": "",
                        "text": "",
                        "episode_index": current["episode_index"],
                        "episode_total": current["episode_total"],
                        "episode_num": current["episode_num"],
                    })
                    if kind == "reasoning":
                        state["reasoning"] = str(state.get("reasoning") or "") + piece
                        snapshot = str(state["reasoning"])
                        event_name = "reasoning"
                    else:
                        state["text"] = str(state.get("text") or "") + piece
                        snapshot = str(state["text"])
                        event_name = "delta"
                cls._emit(job_id, {
                    "event": event_name,
                    "data": {
                        "text": snapshot,
                        "episode_num": current["episode_num"],
                        "episode_index": current["episode_index"],
                        "episode_total": current["episode_total"],
                    },
                })
                cls._patch_stream(job_id, {})

            def on_status(info: dict[str, Any]) -> None:
                phase = str(info.get("phase") or "plan")
                message = str(info.get("message") or "正在按集规划镜头")
                reset = bool(info.get("reset"))
                cls._emit(job_id, {
                    "event": "status",
                    "data": {
                        "phase": phase,
                        "message": message,
                        "reset": reset,
                        "episode_num": current["episode_num"],
                        "episode_index": current["episode_index"],
                        "episode_total": current["episode_total"],
                    },
                })
                cls._patch_stream(job_id, {"phase": phase, "message": message, "reset": reset}, force=True)

            for step, index in enumerate(targets, start=1):
                doc = query_one(
                    "SELECT * FROM ai_project_documents WHERE id = %s AND project_id = %s",
                    (doc_id, project_id),
                )
                if not doc:
                    raise ValueError("文档不存在")
                analysis = ProjectDetailService._analysis_for_document_row(doc) or {}
                episodes = [item for item in (analysis.get("episodes") or []) if isinstance(item, dict)]
                if index >= len(episodes):
                    continue
                episode = episodes[index]
                if not needs_episode_shot_plan(episode, input_mode=doc.get("input_mode")):
                    continue
                ep_num = episode.get("episode_num")
                current["episode_num"] = ep_num
                current["episode_index"] = step
                message = f"正在规划第{ep_num if ep_num is not None else '?'}集（{step}/{total}）"
                progress = 15 + int(80 * step / total)
                execute_sql(
                    "UPDATE ai_project_jobs SET progress=%s,updated_at=%s WHERE id=%s",
                    (min(progress, 95), now_str(), job_id),
                )
                cls._emit(job_id, {
                    "event": "status",
                    "data": {
                        "phase": "plan",
                        "message": message,
                        "reset": True,
                        "episode_num": ep_num,
                        "episode_index": step,
                        "episode_total": total,
                    },
                })
                cls._patch_stream(job_id, {
                    "phase": "plan",
                    "message": message,
                    "reset": True,
                    "episode_index": step,
                    "episode_total": total,
                    "episode_num": ep_num,
                }, force=True)
                try:
                    with LlmStreamHook(on_delta=on_delta, on_status=on_status):
                        planned_shots = LlmService.plan_episode_shots(episode)
                    updated = apply_episode_shot_plan(episode, planned_shots)
                    shot_count = len(updated.get("shots") or [])
                    log_line = (
                        f"第{updated.get('episode_num') if updated.get('episode_num') is not None else ep_num}"
                        f"集已按动作和对白规划为 {shot_count} 条出片镜头"
                    )
                    ProjectDetailService.persist_shot_plan_episode(
                        project_id,
                        doc_id,
                        episode_num=ep_num,
                        episode_index=index,
                        updated_episode=updated,
                        log_line=log_line,
                    )
                    done = {
                        "episode_num": ep_num,
                        "episode_index": step,
                        "episode_total": total,
                        "shots": updated.get("shots") or [],
                        "shots_count": shot_count,
                        "shots_source": updated.get("shots_source"),
                        "error": None,
                    }
                    planned += 1
                except Exception as err:
                    log_line = f"第{ep_num if ep_num is not None else '?'}集镜头规划失败，已保留解析器镜头：{err}"
                    ProjectDetailService.persist_shot_plan_episode(
                        project_id,
                        doc_id,
                        episode_num=ep_num,
                        episode_index=index,
                        updated_episode=episode,
                        log_line=log_line,
                    )
                    done = {
                        "episode_num": ep_num,
                        "episode_index": step,
                        "episode_total": total,
                        "shots": episode.get("shots") or [],
                        "shots_count": len(episode.get("shots") or []),
                        "shots_source": episode.get("shots_source"),
                        "error": str(err)[:1000],
                    }
                    failed += 1
                payload["episodes_done"] = list(payload.get("episodes_done") or []) + [done]
                cls._write_payload(job_id, payload)
                cls._emit(job_id, {"event": "episode_done", "data": done})

            cls._finish_success(job_id, payload, project_id, doc_id, planned=planned, failed=failed)
        except Exception as err:
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,updated_at=%s WHERE id=%s",
                (str(err)[:1000], now_str(), job_id),
            )
            if project_id and doc_id:
                cls._set_document_status(project_id, doc_id, "ready")
            cls._emit(job_id, terminal_event_for_status("failed", message=str(err)[:1000]))
        finally:
            cls._clear_stream_state(job_id)
            with _ACTIVE_LOCK:
                _ACTIVE.discard(job_id)
            cls.kick()

    @classmethod
    def _finish_success(
        cls,
        job_id: str,
        payload: dict[str, Any],
        project_id: str,
        doc_id: str,
        *,
        planned: int,
        failed: int,
    ) -> None:
        payload["planned_episodes"] = planned
        payload["failed_episodes"] = failed
        payload.pop("stream", None)
        execute_sql(
            "UPDATE ai_project_jobs SET status='completed',progress=100,payload_json=%s,error_message=NULL,updated_at=%s WHERE id=%s",
            (json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )
        cls._set_document_status(project_id, doc_id, "ready")
        cls._emit(job_id, {
            "event": "done",
            "terminal": True,
            "data": {
                "status": "succeeded",
                "document_id": doc_id,
                "planned_episodes": planned,
                "failed_episodes": failed,
                "episodes_done": payload.get("episodes_done") or [],
            },
        })

    @classmethod
    def _write_payload(cls, job_id: str, payload: dict[str, Any]) -> None:
        execute_sql(
            "UPDATE ai_project_jobs SET payload_json=%s,updated_at=%s WHERE id=%s",
            (json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )

    @classmethod
    def _set_document_status(cls, project_id: str, doc_id: str, status: str) -> None:
        if not project_id or not doc_id:
            return
        execute_sql(
            "UPDATE ai_project_documents SET status=%s, updated_at=%s WHERE id=%s AND project_id=%s",
            (status, now_str(), doc_id, project_id),
        )

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
