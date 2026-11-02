"""视频等后台任务的实例归属与心跳租约。

任务表 ai-media 由多套后端实例共享，进程启动时不能无条件把「进行中」的任务判为中断：
别的实例正在渲染的行会被误标。这里用 worker_id 记录认领该行的进程，用 lease_updated_at
记录它最后一次心跳，启动扫描只收敛心跳已停的行。
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Sequence

from ..db import execute_sql, now_str, query_all

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
HEARTBEAT_INTERVAL_SECONDS = 20
# 远大于心跳间隔，容忍一次网络 / 连接池抖动把租约判死。
LEASE_STALE_AFTER_SECONDS = 300
# 不带归属信息的行（旧版本实例写入）只能按这个保守阈值收敛。
UNOWNED_GRACE_AFTER_SECONDS = 24 * 3600

_worker_id = ""
_keeper_lock = threading.Lock()
_keeper_thread: threading.Thread | None = None
_keeper_status: dict[str, tuple[str, ...]] = {}


def worker_id() -> str:
    global _worker_id
    if not _worker_id:
        host = (socket.gethostname() or "worker").split(".")[0]
        _worker_id = f"{host}-{os.getpid()}-{uuid.uuid4().hex[:8]}"[:96]
    return _worker_id


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value or "").strip()[:19], _TIME_FORMAT)
    except ValueError:
        return None


def ensure_lease_schema() -> None:
    """给共享任务表补上归属两列；新库由 sql/013 内联建好，这里负责已有库。"""
    from ...db import MysqlDatabase, is_isolated_sqlite_runtime
    from ..db import get_mysql_config

    if is_isolated_sqlite_runtime():
        return
    database = MysqlDatabase(get_mysql_config())
    with database.connection() as connection:
        database.ensure_column(connection, "ai_project_jobs", "worker_id", "VARCHAR(96) NOT NULL DEFAULT ''")
        database.ensure_column(
            connection, "ai_project_jobs", "lease_updated_at", "VARCHAR(64) DEFAULT NULL"
        )
        database.ensure_index(connection, "ai_project_jobs", "idx_ai_job_lease", "job_type, status")


def heartbeat_once() -> int:
    timestamp = now_str()
    touched = 0
    for job_type, statuses in list(_keeper_status.items()):
        placeholders = ", ".join(["%s"] * len(statuses))
        touched += (
            execute_sql(
                f"UPDATE ai_project_jobs SET lease_updated_at = %s "
                f"WHERE job_type = %s AND worker_id = %s AND status IN ({placeholders})",
                (timestamp, job_type, worker_id(), *statuses),
            )
            or 0
        )
    return touched


def start_heartbeat(job_type: str, active_statuses: Sequence[str]) -> None:
    global _keeper_thread
    with _keeper_lock:
        _keeper_status[job_type] = tuple(active_statuses)
        if _keeper_thread is not None and _keeper_thread.is_alive():
            return
        _keeper_thread = threading.Thread(
            target=_heartbeat_loop, name="job-lease-heartbeat", daemon=True
        )
        _keeper_thread.start()


def _heartbeat_loop() -> None:
    while True:
        time.sleep(HEARTBEAT_INTERVAL_SECONDS)
        try:
            heartbeat_once()
        except Exception:
            # 心跳只是续租，连接抖动不能影响出片线程；租约变旧最坏是被别的进程按超时收敛。
            continue


def orphaned_jobs(job_type: str, active_statuses: Sequence[str]) -> list[dict[str, Any]]:
    placeholders = ", ".join(["%s"] * len(active_statuses))
    return query_all(
        f"""
        SELECT id, status, worker_id, lease_updated_at, updated_at, payload_json
        FROM ai_project_jobs
        WHERE job_type = %s AND status IN ({placeholders})
        """,
        (job_type, *active_statuses),
    ) or []


def converge_orphaned_jobs(job_type: str, active_statuses: Sequence[str]) -> int:
    """只收敛认领进程已经停止心跳的行，返回收敛条数。"""
    now = datetime.now()
    converged = 0
    for row in orphaned_jobs(job_type, active_statuses):
        owner = str(row.get("worker_id") or "").strip()
        if owner == worker_id():
            continue
        lease = _parse_time(row.get("lease_updated_at"))
        updated = _parse_time(row.get("updated_at"))
        if owner:
            reason = "lease_expired"
            message = (
                f"渲染实例 {owner} 心跳已超过 {LEASE_STALE_AFTER_SECONDS // 60} 分钟，"
                "后台视频任务已中断，请点击重试。"
            )
            marker = lease or updated
            deadline = now - timedelta(seconds=LEASE_STALE_AFTER_SECONDS)
        else:
            reason = "unowned_stale"
            message = (
                f"任务超过 {UNOWNED_GRACE_AFTER_SECONDS // 3600} 小时没有进展且无实例心跳，"
                "已按中断处理，请点击重试。"
            )
            marker = updated or lease
            deadline = now - timedelta(seconds=UNOWNED_GRACE_AFTER_SECONDS)
        if marker is None or marker >= deadline:
            continue
        timestamp = now_str()
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            payload["recovery"] = {
                "reason": reason,
                "owner_worker_id": owner,
                "lease_updated_at": str(row.get("lease_updated_at") or ""),
                "converged_at": timestamp,
            }
            execute_sql(
                """
                UPDATE ai_project_jobs SET status = 'failed', progress = 0, error_message = %s,
                  payload_json = %s, updated_at = %s
                WHERE id = %s AND status = %s AND worker_id = %s
                """,
                (
                    message,
                    json.dumps(payload, ensure_ascii=False),
                    timestamp,
                    row["id"],
                    row["status"],
                    owner,
                ),
            )
        else:
            execute_sql(
                """
                UPDATE ai_project_jobs SET status = 'failed', progress = 0, error_message = %s,
                  updated_at = %s
                WHERE id = %s AND status = %s AND worker_id = %s
                """,
                (message, timestamp, row["id"], row["status"], owner),
            )
        converged += 1
    return converged
