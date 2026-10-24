from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from typing import Any, Iterator

from ..db import Database, DbConnection, open_database


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class McpStore:
    """Durable gateway records, using the studio's existing database adapter.

    Token and code IDs are SHA-256 fingerprints, never raw credentials. All
    authorization state transitions use a transaction and a locking read.
    """

    def __init__(self, database: Database):
        self.db = open_database(database)
        with self.db.connection() as connection:
            if self.db.dialect == "mysql":
                # MySQL DDL is applied once by AuthStore at studio startup.
                return
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS mcp_gateway_records (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, owner_id TEXT NOT NULL DEFAULT '',
                    parent_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
                    payload_json TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mcp_owner ON mcp_gateway_records(owner_id, kind, created_at);
                CREATE INDEX IF NOT EXISTS idx_mcp_parent ON mcp_gateway_records(parent_id, kind);
            """)

    @contextmanager
    def transaction(self) -> Iterator[DbConnection]:
        with self.db.connection() as connection:
            if self.db.dialect == "sqlite":
                connection.execute("BEGIN IMMEDIATE")
            yield connection

    @staticmethod
    def decode(row: Any) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def get(self, record_id: str, connection: DbConnection | None = None, *, lock: bool = False) -> dict | None:
        if connection is None:
            with self.db.connection() as current:
                return self.get(record_id, current)
        return self.decode(connection.execute("SELECT * FROM mcp_gateway_records WHERE id=?", (record_id,), for_update=lock).fetchone())

    def insert(self, record_id: str, kind: str, payload: dict, *, owner_id: str = "", parent_id: str = "",
               status: str = "active", connection: DbConnection | None = None, ignore: bool = False) -> None:
        if connection is None:
            with self.transaction() as current:
                return self.insert(record_id, kind, payload, owner_id=owner_id, parent_id=parent_id, status=status, connection=current, ignore=ignore)
        now = time.time()
        statement = "INSERT OR IGNORE" if ignore else "INSERT"
        connection.execute(statement + """ INTO mcp_gateway_records
            (id,kind,owner_id,parent_id,status,payload_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
            (record_id, kind, owner_id, parent_id, status, json.dumps(payload, ensure_ascii=False), now, now))

    def update(self, record_id: str, *, payload: dict | None = None, status: str | None = None,
               owner_id: str | None = None, connection: DbConnection | None = None) -> None:
        if connection is None:
            with self.transaction() as current:
                return self.update(record_id, payload=payload, status=status, owner_id=owner_id, connection=current)
        fields: dict[str, Any] = {"updated_at": time.time()}
        if payload is not None:
            fields["payload_json"] = json.dumps(payload, ensure_ascii=False)
        if status is not None:
            fields["status"] = status
        if owner_id is not None:
            fields["owner_id"] = owner_id
        assignment = ",".join(f"{key}=?" for key in fields)
        connection.execute(f"UPDATE mcp_gateway_records SET {assignment} WHERE id=?", (*fields.values(), record_id))

    def list(self, kind: str, owner_id: str, limit: int = 100, *, active_only: bool = False) -> list[dict]:
        with self.db.connection() as connection:
            rows = connection.execute("SELECT * FROM mcp_gateway_records WHERE kind=? AND owner_id=?"
                + (" AND status='active'" if active_only else "") + " ORDER BY created_at DESC LIMIT ?",
                (kind, owner_id, max(1, min(limit, 200)))).fetchall()
        return [self.decode(row) for row in rows]

    def revoke(self, grant_id: str, connection: DbConnection | None = None) -> None:
        if connection is None:
            with self.transaction() as current:
                return self.revoke(grant_id, current)
        connection.execute("UPDATE mcp_gateway_records SET status='revoked',updated_at=? WHERE id=? OR parent_id=?",
                           (time.time(), grant_id, grant_id))
