from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import IntegrityError


class DiagnosisNotFound(ValueError):
    pass


class DiagnosisConflict(ValueError):
    pass


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class DiagnosisRepository:
    def __init__(self, store):
        self.store = store
        with store.connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS ai_script_diagnoses (
                id VARCHAR(64) PRIMARY KEY, owner_id VARCHAR(64) NOT NULL,
                client_request_id VARCHAR(96) NOT NULL, title VARCHAR(255) NOT NULL,
                project_id VARCHAR(96), document_id VARCHAR(96),
                status VARCHAR(32) NOT NULL, stage VARCHAR(32) NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
                model VARCHAR(255) NOT NULL DEFAULT '', input_json LONGTEXT NOT NULL,
                report_json LONGTEXT, error TEXT, created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                UNIQUE (owner_id, client_request_id))""")
            store._db.ensure_index(conn, "ai_script_diagnoses", "idx_diagnosis_owner_updated", "owner_id, updated_at")

    @staticmethod
    def decode(row):
        item = dict(row)
        item.pop("owner_id", None)
        item.pop("client_request_id", None)
        item["sources"] = json.loads(item.pop("input_json"))
        item["report"] = json.loads(item["report_json"]) if item.get("report_json") else None
        item.pop("report_json", None)
        return item

    def get(self, owner, diagnosis_id):
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM ai_script_diagnoses WHERE id=? AND owner_id=?", (diagnosis_id, owner)).fetchone()
        if not row:
            raise DiagnosisNotFound("诊断不存在或无权访问")
        return self.decode(row)

    def by_request(self, owner, key):
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM ai_script_diagnoses WHERE owner_id=? AND client_request_id=?", (owner, key)).fetchone()
        return self.decode(row) if row else None

    def create(self, owner, key, title, sources, project_id=None, document_id=None):
        diagnosis_id, now = "diag-" + uuid.uuid4().hex, timestamp()
        try:
            with self.store.connection() as conn:
                conn.execute("""INSERT INTO ai_script_diagnoses
                    (id,owner_id,client_request_id,title,project_id,document_id,status,stage,input_json,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,'queued','queued',?,?,?)""",
                    (diagnosis_id, owner, key, title, project_id, document_id, dumps(sources), now, now))
        except IntegrityError:
            existing = self.by_request(owner, key)
            if existing:
                return existing, False
            raise
        return self.get(owner, diagnosis_id), True

    def list(self, owner, *, document_id=None, offset=0, limit=30):
        clause, args = "owner_id=?", [owner]
        if document_id:
            clause += " AND document_id=?"
            args.append(document_id)
        with self.store.connection() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM ai_script_diagnoses WHERE " + clause, args).fetchone()["n"]
            rows = conn.execute(
                "SELECT id,title,project_id,document_id,status,stage,completed,total,model,error,created_at,updated_at "
                "FROM ai_script_diagnoses WHERE " + clause + " ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total}

    def update_active(self, owner, diagnosis_id, *, status=None, **fields):
        allowed = {"stage", "completed", "total", "model", "report_json", "error"}
        if not set(fields) <= allowed:
            raise ValueError("未知诊断字段")
        if status:
            fields["status"] = status
        fields["updated_at"] = timestamp()
        with self.store.connection() as conn:
            result = conn.execute(
                "UPDATE ai_script_diagnoses SET " + ",".join(name + "=?" for name in fields)
                + " WHERE id=? AND owner_id=? AND status IN ('queued','running')",
                [*fields.values(), diagnosis_id, owner],
            )
        return result.rowcount == 1

    def claim(self, owner, diagnosis_id):
        with self.store.connection() as conn:
            return conn.execute(
                "UPDATE ai_script_diagnoses SET status='running',stage='analyzing',updated_at=? "
                "WHERE id=? AND owner_id=? AND status='queued'", (timestamp(), diagnosis_id, owner),
            ).rowcount == 1

    def recover(self):
        with self.store.connection() as conn:
            conn.execute(
                "UPDATE ai_script_diagnoses SET status='interrupted',stage='interrupted',error=?,updated_at=? "
                "WHERE status IN ('queued','running')", ("服务重启中断了本次诊断，请重试；原始输入已保留", timestamp()),
            )

    def delete(self, owner, diagnosis_id):
        self.get(owner, diagnosis_id)
        with self.store.connection() as conn:
            count = conn.execute(
                "DELETE FROM ai_script_diagnoses WHERE id=? AND owner_id=? AND status NOT IN ('queued','running')",
                (diagnosis_id, owner),
            ).rowcount
        if not count:
            raise DiagnosisConflict("请先取消正在运行的诊断，再删除记录")
