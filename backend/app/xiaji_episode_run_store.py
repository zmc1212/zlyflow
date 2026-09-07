from __future__ import annotations

import json
import uuid
from typing import Any

from .db import Database, open_database
from .storage import now

SQLITE_EPISODE_RUN_SCHEMA = """
CREATE TABLE IF NOT EXISTS xiaji_episode_runs (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    video_params_json TEXT NOT NULL,
    cursor_json TEXT,
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xiaji_episode_runs_episode
    ON xiaji_episode_runs(episode_id, created_at);
CREATE INDEX IF NOT EXISTS idx_xiaji_episode_runs_project
    ON xiaji_episode_runs(project_id, created_at);
"""

ACTIVE_STATUSES = ("queued", "running")
STEP_LABELS = {
    "sketch": "草图",
    "render": "精绘",
    "bridge": "衔接帧",
    "prompt": "提示词",
    "video": "视频",
}


def _parse_json(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        parsed = json.loads(raw or ("{}" if isinstance(fallback, dict) else "[]"))
    except json.JSONDecodeError:
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class XiajiEpisodeRunStore:
    def __init__(self, database: Database | Any) -> None:
        self._db = database if isinstance(database, Database) else open_database(database)
        self.initialize()

    def initialize(self) -> None:
        with self._db.connection() as connection:
            if self._db.dialect == "mysql":
                self._db.apply_mysql_schema(connection)
            else:
                connection.executescript(SQLITE_EPISODE_RUN_SCHEMA)

    def create(
        self,
        *,
        owner_user_id: str,
        project_id: str,
        episode_id: str,
        video_params: dict[str, Any],
        status: str = "queued",
    ) -> dict[str, Any]:
        run_id = uuid.uuid4().hex[:16]
        timestamp = now()
        with self._db.connection() as connection:
            connection.execute(
                """INSERT INTO xiaji_episode_runs (
                    id, owner_user_id, project_id, episode_id, status, progress,
                    video_params_json, cursor_json, error, cancel_requested, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, ?, ?)""",
                (
                    run_id,
                    owner_user_id,
                    project_id,
                    episode_id,
                    status,
                    0,
                    _dump(video_params),
                    timestamp,
                    timestamp,
                ),
            )
        return self.get(run_id)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._db.connection() as connection:
            row = connection.execute("SELECT * FROM xiaji_episode_runs WHERE id = ?", (run_id,)).fetchone()
        return self._from_row(row) if row else None

    def latest_for_episode(self, owner_user_id: str, episode_id: str) -> dict[str, Any] | None:
        with self._db.connection() as connection:
            row = connection.execute(
                """SELECT * FROM xiaji_episode_runs
                   WHERE owner_user_id = ? AND episode_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (owner_user_id, episode_id),
            ).fetchone()
        return self._from_row(row) if row else None

    def active_for_episode(self, owner_user_id: str, episode_id: str) -> dict[str, Any] | None:
        with self._db.connection() as connection:
            row = connection.execute(
                """SELECT * FROM xiaji_episode_runs
                   WHERE owner_user_id = ? AND episode_id = ? AND status IN (?, ?)
                   ORDER BY created_at DESC LIMIT 1""",
                (owner_user_id, episode_id, *ACTIVE_STATUSES),
            ).fetchone()
        return self._from_row(row) if row else None

    def list_project_runs(self, owner_user_id: str, project_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM xiaji_episode_runs
                   WHERE owner_user_id = ? AND project_id = ?
                   ORDER BY created_at DESC""",
                (owner_user_id, project_id),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def update(
        self,
        run_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        cursor: dict[str, Any] | None = None,
        error: str | None = None,
        update_error: bool = False,
        cancel_requested: bool | None = None,
    ) -> dict[str, Any]:
        current = self.get(run_id)
        if current is None:
            raise KeyError(run_id)
        next_status = status if status is not None else current["status"]
        next_progress = current["progress"] if progress is None else max(0, min(100, int(progress)))
        next_cursor = current.get("cursor") if cursor is None else cursor
        next_error = error if update_error else current.get("error")
        next_cancel = current["cancel_requested"] if cancel_requested is None else (1 if cancel_requested else 0)
        timestamp = now()
        with self._db.connection() as connection:
            connection.execute(
                """UPDATE xiaji_episode_runs SET status = ?, progress = ?, cursor_json = ?,
                    error = ?, cancel_requested = ?, updated_at = ? WHERE id = ?""",
                (
                    next_status,
                    next_progress,
                    _dump(next_cursor) if next_cursor is not None else None,
                    next_error,
                    int(next_cancel),
                    timestamp,
                    run_id,
                ),
            )
        return self.get(run_id)

    def interrupt_stale(self) -> int:
        timestamp = now()
        with self._db.connection() as connection:
            cursor = connection.execute(
                """UPDATE xiaji_episode_runs SET status = ?, error = ?, updated_at = ?
                   WHERE status IN (?, ?)""",
                (
                    "interrupted",
                    "服务停止，自动生成已中断；不会自动重试，请重新添加任务。",
                    timestamp,
                    *ACTIVE_STATUSES,
                ),
            )
            return int(getattr(cursor, "rowcount", 0) or 0)

    def delete_project_runs(self, project_id: str, owner_user_id: str) -> None:
        with self._db.connection() as connection:
            if not self._db.table_exists(connection, "xiaji_episode_runs"):
                return
            connection.execute(
                "DELETE FROM xiaji_episode_runs WHERE project_id = ? AND owner_user_id = ?",
                (project_id, owner_user_id),
            )

    def to_job_list_item(self, row: dict[str, Any]) -> dict[str, Any]:
        cursor = row.get("cursor") if isinstance(row.get("cursor"), dict) else {}
        step = str(cursor.get("step") or "")
        sequence = cursor.get("sequence")
        target = f"第{sequence}镜 · {STEP_LABELS.get(step, step or '排队')}" if sequence else "整集自动生成"
        params = row.get("video_params") if isinstance(row.get("video_params"), dict) else {}
        parameters = [{"name": key, "label": key, "value": value} for key, value in params.items()]
        if cursor:
            parameters.append({"name": "cursor", "label": "当前步骤", "value": cursor})
        status = str(row.get("status") or "unknown")
        if status == "running":
            list_status = "running"
        elif status == "queued":
            list_status = "queued"
        elif status == "succeeded":
            list_status = "succeeded"
        elif status == "cancelled":
            list_status = "cancelled"
        elif status == "interrupted":
            list_status = "interrupted"
        else:
            list_status = "failed"
        return {
            "id": row["id"],
            "job_id": row["id"],
            "owner_user_id": row.get("owner_user_id"),
            "project_id": row.get("project_id"),
            "kind": "auto_run",
            "source": "auto_run",
            "target": target,
            "slot": "auto_run",
            "slot_label": "整集自动生成",
            "title": f"整集自动生成 · {target}",
            "status": list_status,
            "progress": row.get("progress") or 0,
            "mode": "xiaji-auto-run",
            "prompt": "",
            "error": row.get("error"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "job_created_at": row.get("created_at"),
            "job_updated_at": row.get("updated_at"),
            "bound_url": "",
            "preview_url": "",
            "outputs": [],
            "parameters": parameters,
            "options": params,
            "missing": False,
            "reference_count": 0,
            "references": [],
            "negative_prompt": "",
            "image_size": None,
        }

    def _from_row(self, row: Any) -> dict[str, Any]:
        cursor = _parse_json(row["cursor_json"], {}) if row["cursor_json"] else None
        return {
            "id": row["id"],
            "owner_user_id": row["owner_user_id"],
            "project_id": row["project_id"],
            "episode_id": row["episode_id"],
            "status": row["status"],
            "progress": int(row["progress"] or 0),
            "video_params": _parse_json(row["video_params_json"], {}),
            "cursor": cursor if isinstance(cursor, dict) else None,
            "error": row["error"],
            "cancel_requested": bool(int(row["cancel_requested"] or 0)),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def episode_runs_store(app: Any) -> XiajiEpisodeRunStore | None:
    store = getattr(app.state, "xiaji_episode_run_store", None)
    return store if isinstance(store, XiajiEpisodeRunStore) else None
