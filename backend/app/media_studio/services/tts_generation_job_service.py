from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ...gpu_runtime import occupy_gpu
from ...llm_client import LlmError
from ..db import execute_sql, now_str, query_all, query_one
from .dubbing_lines import estimate_duration_sec
from .dubbing_service import DubbingService, tts_provider_service

JOB_TYPE = "tts_generation"
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts-gen")
_DISPATCH_LOCK = threading.Lock()
_ACTIVE: set[str] = set()
_ACTIVE_LOCK = threading.Lock()
_ACTIVE_STATUSES = ("queued", "preparing", "running")


class TtsGenerationJobService:
    @classmethod
    def enqueue(
        cls,
        project_id: str,
        episode_id: str,
        *,
        line_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        track = DubbingService.sync(project_id, episode_id)
        wanted = [item for item in (line_ids or []) if item]
        lines = track["lines"]
        if wanted:
            known = {str(item.get("id") or "") for item in lines}
            missing = [item for item in wanted if item not in known]
            if missing:
                raise ValueError("台词不存在：" + "、".join(missing))
            targets = [item for item in lines if item.get("id") in set(wanted)]
        else:
            targets = [item for item in lines if item.get("text")]
        if not targets:
            raise ValueError("没有可生成的台词")

        for existing in query_all(
            "SELECT id, status, payload_json FROM ai_project_jobs WHERE project_id = %s AND job_type = %s "
            "AND status IN ('queued','preparing','running') ORDER BY created_at DESC",
            (project_id, JOB_TYPE),
        ):
            payload = cls._payload(existing)
            if str(payload.get("episode_id") or "") != episode_id:
                continue
            existing_ids = [str(item) for item in (payload.get("line_ids") or [])]
            if not wanted or set(existing_ids) == set(wanted):
                return {
                    "job_id": existing["id"],
                    "episode_id": episode_id,
                    "status": existing["status"],
                    "duplicate": True,
                    "line_ids": existing_ids,
                }

        target_ids = [str(item.get("id") or "") for item in targets]
        title = (
            f"配音 {targets[0].get('seq')}"
            if len(targets) == 1
            else f"批量配音 {len(targets)} 句"
        )
        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        payload = {
            "target_type": JOB_TYPE,
            "project_id": project_id,
            "episode_id": episode_id,
            "line_ids": target_ids,
            "scope": "line" if len(target_ids) == 1 else "episode",
            "completed_ids": [],
            "failed_ids": [],
        }
        execute_sql(
            "INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,'queued',0,NULL,%s,%s,%s)",
            (jid, project_id, JOB_TYPE, title, json.dumps(payload, ensure_ascii=False), timestamp, timestamp),
        )
        DubbingService.mark_lines(project_id, episode_id, target_ids, status="queued", job_id=jid)
        cls.kick()
        return {"job_id": jid, "episode_id": episode_id, "status": "queued", "line_ids": target_ids}

    @classmethod
    def kick(cls) -> None:
        if not _DISPATCH_LOCK.acquire(blocking=False):
            return
        try:
            with _ACTIVE_LOCK:
                if _ACTIVE:
                    return
            rows = query_all(
                "SELECT id FROM ai_project_jobs WHERE job_type = %s AND status = 'queued' "
                "ORDER BY created_at ASC LIMIT 1",
                (JOB_TYPE,),
            )
            for row in rows:
                jid = row["id"]
                if execute_sql(
                    "UPDATE ai_project_jobs SET status='preparing',progress=5,updated_at=%s WHERE id=%s AND status='queued'",
                    (now_str(), jid),
                ) != 1:
                    continue
                with _ACTIVE_LOCK:
                    _ACTIVE.add(jid)
                _EXECUTOR.submit(cls._run, jid)
                break
        finally:
            _DISPATCH_LOCK.release()

    @classmethod
    def recover_interrupted_jobs(cls) -> None:
        rows = query_all(
            "SELECT id, payload_json FROM ai_project_jobs WHERE job_type=%s AND status IN ('queued','preparing','running')",
            (JOB_TYPE,),
        )
        timestamp = now_str()
        execute_sql(
            "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,updated_at=%s "
            "WHERE job_type=%s AND status IN ('queued','preparing','running')",
            ("服务重启时配音任务已中断，请重新生成。", timestamp, JOB_TYPE),
        )
        for row in rows:
            payload = cls._payload(row)
            project_id = str(payload.get("project_id") or "").strip()
            episode_id = str(payload.get("episode_id") or "").strip()
            line_ids = [str(item) for item in (payload.get("line_ids") or []) if str(item or "").strip()]
            if not (project_id and episode_id and line_ids):
                continue
            try:
                DubbingService.mark_lines(
                    project_id,
                    episode_id,
                    line_ids,
                    status="failed",
                    job_id=str(row.get("id") or ""),
                    error="服务重启时配音任务已中断，请重新生成。",
                )
            except Exception:
                pass
        cls.kick()

    @classmethod
    def retry(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (job_id, project_id))
        payload = cls._payload(row or {})
        if not row or row.get("job_type") != JOB_TYPE:
            raise ValueError("配音任务不存在")
        episode_id = str(payload.get("episode_id") or "").strip()
        if not episode_id:
            raise ValueError("任务缺少分集")
        return cls.enqueue(project_id, episode_id, line_ids=list(payload.get("line_ids") or []))

    @classmethod
    def _payload(cls, row: dict[str, Any]) -> dict[str, Any]:
        raw = row.get("payload_json")
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @classmethod
    def _patch_payload(cls, job_id: str, payload: dict[str, Any], **fields: Any) -> None:
        execute_sql(
            "UPDATE ai_project_jobs SET status=%s,progress=%s,result_url=%s,error_message=%s,payload_json=%s,updated_at=%s WHERE id=%s",
            (
                fields.get("status") or "running",
                int(fields.get("progress") or 0),
                fields.get("result_url"),
                fields.get("error_message"),
                json.dumps(payload, ensure_ascii=False),
                now_str(),
                job_id,
            ),
        )

    @classmethod
    def _run(cls, job_id: str) -> None:
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        payload = cls._payload(row)
        project_id = str(payload.get("project_id") or row.get("project_id") or "").strip()
        episode_id = str(payload.get("episode_id") or "").strip()
        line_ids = [str(item) for item in (payload.get("line_ids") or []) if str(item or "").strip()]
        try:
            if not project_id or not episode_id or not line_ids:
                raise ValueError("任务缺少台词")
            execute_sql(
                "UPDATE ai_project_jobs SET status='running',progress=10,updated_at=%s WHERE id=%s",
                (now_str(), job_id),
            )
            DubbingService.mark_lines(project_id, episode_id, line_ids, status="running", job_id=job_id)
            assets = DubbingService._assets(project_id)
            tts = tts_provider_service()
            completed: list[str] = []
            failed: list[str] = []
            last_url = ""
            with occupy_gpu("tts"):
                for index, lid in enumerate(line_ids, start=1):
                    track = DubbingService.sync(project_id, episode_id)
                    line = next((item for item in track["lines"] if item.get("id") == lid), None)
                    if not line:
                        failed.append(lid)
                        continue
                    try:
                        audio, suffix = DubbingService.synthesize_line(line, assets, tts=tts)
                        url = DubbingService.store_line_audio(project_id, episode_id, lid, audio, suffix)
                        duration = estimate_duration_sec(audio, str(line.get("text") or ""))
                        DubbingService.write_line_audio(
                            project_id,
                            episode_id,
                            lid,
                            audio_url=url,
                            duration_sec=duration,
                            job_id=job_id,
                        )
                        completed.append(lid)
                        last_url = url
                    except (LlmError, ValueError, RuntimeError) as exc:
                        failed.append(lid)
                        DubbingService.mark_lines(
                            project_id, episode_id, [lid], status="failed", job_id=job_id, error=str(exc),
                        )
                    progress = 10 + int(80 * index / max(1, len(line_ids)))
                    payload["completed_ids"] = completed
                    payload["failed_ids"] = failed
                    cls._patch_payload(job_id, payload, status="running", progress=progress, result_url=last_url or None)
            payload["completed_ids"] = completed
            payload["failed_ids"] = failed
            if failed and not completed:
                raise RuntimeError("全部台词生成失败")
            status = "completed"
            message = None
            if failed:
                message = f"{len(failed)} 句失败，{len(completed)} 句成功"
            execute_sql(
                "UPDATE ai_project_jobs SET status=%s,progress=100,result_url=%s,error_message=%s,payload_json=%s,"
                "completed_at=%s,updated_at=%s WHERE id=%s",
                (
                    status,
                    last_url or None,
                    message,
                    json.dumps(payload, ensure_ascii=False),
                    now_str(),
                    now_str(),
                    job_id,
                ),
            )
        except Exception as exc:
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,updated_at=%s WHERE id=%s",
                (str(exc)[:500], now_str(), job_id),
            )
            if project_id and episode_id and line_ids:
                try:
                    DubbingService.mark_lines(
                        project_id, episode_id, line_ids, status="failed", job_id=job_id, error=str(exc)[:200],
                    )
                except Exception:
                    pass
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE.discard(job_id)
            cls.kick()
