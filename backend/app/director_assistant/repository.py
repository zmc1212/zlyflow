from __future__ import annotations

import json
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from typing import Any


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def identifier(prefix: str = "as") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class AssistantConflict(ValueError):
    pass


class AssistantNotFound(ValueError):
    pass


class AssistantRepository:
    """Typed JSON aggregates, with SQL ownership checks and optimistic revisions.

    The same DbConnection is used by MySQL and isolated SQLite tests. Records
    are soft-deleted so historical citations and resource revisions stay valid.
    """

    def __init__(self, store: Any):
        self.store = store
        with store.connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS ai_assistant_records (
                id VARCHAR(96) PRIMARY KEY, owner_id VARCHAR(64) NOT NULL,
                kind VARCHAR(32) NOT NULL, parent_id VARCHAR(96) NOT NULL DEFAULT '',
                status VARCHAR(32) NOT NULL DEFAULT 'ready', version INTEGER NOT NULL DEFAULT 1,
                payload_json LONGTEXT NOT NULL, created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS ai_assistant_events (
                run_id VARCHAR(96) NOT NULL, seq INTEGER NOT NULL,
                event_json LONGTEXT NOT NULL, created_at VARCHAR(64) NOT NULL,
                PRIMARY KEY (run_id, seq))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS ai_assistant_project_locks (
                project_id VARCHAR(64) PRIMARY KEY, updated_at VARCHAR(64) NOT NULL)""")
            for name, columns in [
                ("idx_assistant_owner_kind", "owner_id, kind, updated_at"),
                ("idx_assistant_parent", "parent_id, kind, created_at"),
            ]:
                store._db.ensure_index(conn, "ai_assistant_records", name, columns)

    @contextmanager
    def transaction(self):
        with self.store.connection() as conn:
            if conn.dialect == "sqlite":
                conn.execute("BEGIN IMMEDIATE")
            yield conn

    @staticmethod
    def decode(row: Any) -> dict:
        return {
            **json.loads(row["payload_json"]), "id": row["id"], "kind": row["kind"],
            "status": row["status"], "version": row["version"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def get(self, owner: str, record_id: str, kind: str | None = None, *, shared=False, conn=None, lock=False) -> dict:
        with nullcontext(conn) if conn is not None else self.store.connection() as db:
            row = db.execute(
                "SELECT * FROM ai_assistant_records WHERE id=? AND (owner_id=? OR owner_id=?)",
                (record_id, owner, "" if shared else owner), for_update=lock,
            ).fetchone()
        if not row or (kind and row["kind"] != kind) or row["status"] == "deleted":
            raise AssistantNotFound("内容不存在或无权访问")
        return self.decode(row)

    def list(self, owner: str, kind: str, *, parent: str | None = None, shared=False, limit=200, conn=None) -> list[dict]:
        sql = "SELECT * FROM ai_assistant_records WHERE kind=? AND status<>'deleted' AND (owner_id=? OR owner_id=?)"
        args: list[Any] = [kind, owner, "" if shared else owner]
        if parent is not None:
            sql += " AND parent_id=?"
            args.append(parent)
        sql += " ORDER BY created_at, id LIMIT ?"
        args.append(limit)
        with nullcontext(conn) if conn is not None else self.store.connection() as db:
            return [self.decode(row) for row in db.execute(sql, args).fetchall()]

    def insert(self, owner: str, kind: str, payload: dict, *, parent="", record_id=None, status="ready", conn=None) -> dict:
        record_id, now = record_id or identifier(), timestamp()
        with nullcontext(conn) if conn is not None else self.store.connection() as db:
            db.execute(
                "INSERT INTO ai_assistant_records (id,owner_id,kind,parent_id,status,version,payload_json,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?)",
                (record_id, owner, kind, parent, status, dumps(payload), now, now),
            )
            return self.get(owner, record_id, conn=db)

    def update(self, owner: str, record: dict, changes: dict, *, status=None, conn=None) -> dict:
        payload = {k: v for k, v in {**record, **changes}.items() if k not in {
            "id", "kind", "status", "version", "created_at", "updated_at",
        }}
        with nullcontext(conn) if conn is not None else self.store.connection() as db:
            result = db.execute(
                "UPDATE ai_assistant_records SET payload_json=?,status=?,version=version+1,updated_at=? WHERE id=? AND owner_id=? AND version=?",
                (dumps(payload), status or record["status"], timestamp(), record["id"], owner, record["version"]),
            )
            if result.rowcount != 1:
                raise AssistantConflict("内容已变化，请刷新后重试")
            if status == "deleted":
                return {"id": record["id"], "status": "deleted"}
            return self.get(owner, record["id"], conn=db)

    def emit(self, owner: str, run_id: str, event: str, data: dict) -> dict:
        with self.transaction() as conn:
            self.get(owner, run_id, "run", conn=conn, lock=True)
            row = conn.execute("SELECT MAX(seq) AS seq FROM ai_assistant_events WHERE run_id=?", (run_id,)).fetchone()
            seq = int(row["seq"] or 0) + 1
            value = {"seq": seq, "event": event, "data": data}
            conn.execute("INSERT INTO ai_assistant_events (run_id,seq,event_json,created_at) VALUES (?,?,?,?)",
                         (run_id, seq, dumps(value), timestamp()))
            return value

    def events(self, owner: str, run_id: str, since=0) -> list[dict]:
        self.get(owner, run_id, "run")
        with self.store.connection() as conn:
            rows = conn.execute("SELECT event_json FROM ai_assistant_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 200", (run_id, since)).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    @contextmanager
    def project_transaction(self, project_id: str, *, replay_id=None, replay_owner=None):
        with self.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO ai_assistant_project_locks (project_id,updated_at) VALUES (?,?)", (project_id, timestamp()))
            conn.execute("SELECT project_id FROM ai_assistant_project_locks WHERE project_id=?", (project_id,), for_update=True).fetchone()
            project = conn.execute("SELECT * FROM ai_projects WHERE id=?", (project_id,), for_update=True).fetchone()
            if not project:
                raise AssistantNotFound("关联工程不存在")
            if replay_id and replay_owner:
                replay = conn.execute("SELECT payload_json FROM ai_assistant_records WHERE id=? AND owner_id=?", (replay_id, replay_owner), for_update=True).fetchone()
                payload = json.loads(replay["payload_json"]) if replay else {}
                if payload.get("application_id") or payload.get("execution_id"):
                    yield conn, dict(project)
                    return
            active = conn.execute("SELECT id FROM ai_project_jobs WHERE project_id=? AND job_type='ai_pipeline' AND status IN ('queued','running','clarifying','revising','awaiting_review') LIMIT 1", (project_id,)).fetchone()
            if active:
                raise AssistantConflict("该工程有旧版 AI 任务，请先继续完成或取消旧任务")
            media = conn.execute("SELECT id FROM ai_assistant_records WHERE kind='media_execution' AND parent_id=? AND status IN ('queued','running') LIMIT 1", (project_id,)).fetchone()
            if media:
                raise AssistantConflict("该工程正在提交媒体任务，请稍后再操作")
            job = conn.execute("SELECT id FROM ai_project_jobs WHERE project_id=? AND status IN ('queued','preparing','running','prompt_generation','uploading','comfy_queued','upscaling','assembling','downloading') LIMIT 1", (project_id,)).fetchone()
            if job:
                raise AssistantConflict("该工程有进行中的生成任务，请在任务中心查看进度")
            yield conn, dict(project)
