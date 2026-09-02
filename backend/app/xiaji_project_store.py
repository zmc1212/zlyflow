from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .db import Database, open_database
from .storage import now

SQLITE_PROJECT_SCHEMA = """
CREATE TABLE IF NOT EXISTS xiaji_projects (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xiaji_projects_owner_updated
    ON xiaji_projects(owner_user_id, updated_at DESC);
"""

DEFAULT_PROJECT_NAME = "默认项目"


def _parse_settings(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class XiajiProjectStore:
    def __init__(self, database: Database | Path) -> None:
        self._db = database if isinstance(database, Database) else open_database(database)
        self.initialize()

    def initialize(self) -> None:
        with self._db.connection() as connection:
            if self._db.dialect == "mysql":
                self._db.apply_mysql_schema(connection)
            else:
                connection.executescript(SQLITE_PROJECT_SCHEMA)
            self._ensure_child_columns(connection)
            self._backfill_orphans(connection)
            self._ensure_asset_unique(connection)

    def _ensure_child_columns(self, connection: Any) -> None:
        declaration = "VARCHAR(64) NULL" if self._db.dialect == "mysql" else "TEXT"
        if self._db.table_exists(connection, "xiaji_documents"):
            self._db.ensure_column(connection, "xiaji_documents", "project_id", declaration)
            self._ensure_index(
                connection,
                "xiaji_documents",
                "idx_xiaji_documents_project",
                "CREATE INDEX idx_xiaji_documents_project ON xiaji_documents(project_id, updated_at)",
            )
        if self._db.table_exists(connection, "xiaji_assets"):
            self._db.ensure_column(connection, "xiaji_assets", "project_id", declaration)
            self._ensure_index(
                connection,
                "xiaji_assets",
                "idx_xiaji_assets_project",
                "CREATE INDEX idx_xiaji_assets_project ON xiaji_assets(project_id, kind, updated_at)",
            )

    def _ensure_index(self, connection: Any, table: str, name: str, sql: str) -> None:
        if self._index_exists(connection, table, name):
            return
        try:
            connection.execute(sql)
        except Exception:
            return

    def _index_exists(self, connection: Any, table: str, index_name: str) -> bool:
        if self._db.dialect == "mysql":
            row = connection.execute(
                """SELECT 1 AS ok FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND INDEX_NAME = ? LIMIT 1""",
                (table, index_name),
            ).fetchone()
            return row is not None
        row = connection.execute(
            "SELECT 1 AS ok FROM sqlite_master WHERE type = 'index' AND name = ?",
            (index_name,),
        ).fetchone()
        return row is not None

    def _backfill_orphans(self, connection: Any) -> None:
        owners: set[str] = set()
        if self._db.table_exists(connection, "xiaji_documents"):
            for row in connection.execute(
                "SELECT DISTINCT owner_user_id FROM xiaji_documents WHERE project_id IS NULL OR project_id = ''",
            ).fetchall():
                owners.add(str(row["owner_user_id"]))
        if self._db.table_exists(connection, "xiaji_assets"):
            for row in connection.execute(
                "SELECT DISTINCT owner_user_id FROM xiaji_assets WHERE project_id IS NULL OR project_id = ''",
            ).fetchall():
                owners.add(str(row["owner_user_id"]))
        for owner_user_id in owners:
            existing = connection.execute(
                "SELECT id FROM xiaji_projects WHERE owner_user_id = ? ORDER BY created_at ASC LIMIT 1",
                (owner_user_id,),
            ).fetchone()
            if existing is None:
                project_id = self._insert_project(connection, owner_user_id, DEFAULT_PROJECT_NAME, {})
            else:
                project_id = existing["id"]
            if self._db.table_exists(connection, "xiaji_documents"):
                connection.execute(
                    "UPDATE xiaji_documents SET project_id = ? WHERE owner_user_id = ? AND (project_id IS NULL OR project_id = '')",
                    (project_id, owner_user_id),
                )
            if self._db.table_exists(connection, "xiaji_assets"):
                connection.execute(
                    "UPDATE xiaji_assets SET project_id = ? WHERE owner_user_id = ? AND (project_id IS NULL OR project_id = '')",
                    (project_id, owner_user_id),
                )

    def _ensure_asset_unique(self, connection: Any) -> None:
        if not self._db.table_exists(connection, "xiaji_assets"):
            return
        if self._db.dialect == "mysql":
            self._drop_mysql_index(connection, "xiaji_assets", "uk_xiaji_assets_owner_kind_name")
            if not self._index_exists(connection, "xiaji_assets", "uk_xiaji_assets_project_kind_name"):
                try:
                    connection.execute(
                        "ALTER TABLE xiaji_assets ADD UNIQUE KEY uk_xiaji_assets_project_kind_name (project_id, kind, name)",
                    )
                except Exception:
                    return
            return
        self._ensure_index(
            connection,
            "xiaji_assets",
            "uk_xiaji_assets_project_kind_name",
            "CREATE UNIQUE INDEX uk_xiaji_assets_project_kind_name ON xiaji_assets(project_id, kind, name)",
        )

    def _drop_mysql_index(self, connection: Any, table: str, index_name: str) -> None:
        if not self._index_exists(connection, table, index_name):
            return
        try:
            connection.execute(f"ALTER TABLE `{table}` DROP INDEX `{index_name}`")
        except Exception:
            return

    def _from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "owner_user_id": row["owner_user_id"],
            "name": row["name"],
            "settings": _parse_settings(row["settings_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _insert_project(
        self,
        connection: Any,
        owner_user_id: str,
        name: str,
        settings: dict[str, Any],
    ) -> str:
        project_id = f"xjp-{uuid.uuid4().hex[:16]}"
        timestamp = now()
        connection.execute(
            """INSERT INTO xiaji_projects (id, owner_user_id, name, settings_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                owner_user_id,
                name[:255],
                json.dumps(settings, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        return project_id

    def list_projects(self, owner_user_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM xiaji_projects WHERE owner_user_id = ? ORDER BY updated_at DESC",
                (owner_user_id,),
            ).fetchall()
        return [self._from_row(dict(row)) for row in rows]

    def get_project(self, project_id: str, owner_user_id: str) -> dict[str, Any]:
        with self._db.connection() as connection:
            row = connection.execute(
                "SELECT * FROM xiaji_projects WHERE id = ? AND owner_user_id = ?",
                (project_id, owner_user_id),
            ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return self._from_row(dict(row))

    def create_project(
        self,
        owner_user_id: str,
        name: str,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trimmed = (name or "").strip() or "未命名项目"
        with self._db.connection() as connection:
            project_id = self._insert_project(connection, owner_user_id, trimmed, dict(settings or {}))
        return self.get_project(project_id, owner_user_id)

    def update_project(
        self,
        project_id: str,
        owner_user_id: str,
        *,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.get_project(project_id, owner_user_id)
        next_name = (name.strip() if isinstance(name, str) else current["name"])[:255]
        if not next_name:
            raise ValueError("请填写项目名称")
        payload = dict(current["settings"])
        if settings is not None:
            payload.update(settings)
        timestamp = now()
        with self._db.connection() as connection:
            connection.execute(
                "UPDATE xiaji_projects SET name = ?, settings_json = ?, updated_at = ? WHERE id = ? AND owner_user_id = ?",
                (next_name, json.dumps(payload, ensure_ascii=False), timestamp, project_id, owner_user_id),
            )
        return self.get_project(project_id, owner_user_id)

    def delete_project(self, project_id: str, owner_user_id: str) -> None:
        self.get_project(project_id, owner_user_id)
        with self._db.connection() as connection:
            if self._db.table_exists(connection, "xiaji_episodes"):
                episodes = connection.execute(
                    "SELECT id FROM xiaji_episodes WHERE project_id = ? AND owner_user_id = ?",
                    (project_id, owner_user_id),
                ).fetchall()
                for row in episodes:
                    connection.execute("DELETE FROM xiaji_beats WHERE episode_id = ?", (row["id"],))
                    connection.execute("DELETE FROM xiaji_episode_links WHERE episode_id = ?", (row["id"],))
                connection.execute(
                    "DELETE FROM xiaji_episodes WHERE project_id = ? AND owner_user_id = ?",
                    (project_id, owner_user_id),
                )
            if self._db.table_exists(connection, "xiaji_assets"):
                rows = connection.execute(
                    "SELECT id FROM xiaji_assets WHERE project_id = ? AND owner_user_id = ?",
                    (project_id, owner_user_id),
                ).fetchall()
                for row in rows:
                    connection.execute("DELETE FROM xiaji_asset_media WHERE asset_id = ?", (row["id"],))
                connection.execute(
                    "DELETE FROM xiaji_assets WHERE project_id = ? AND owner_user_id = ?",
                    (project_id, owner_user_id),
                )
            if self._db.table_exists(connection, "xiaji_documents"):
                docs = connection.execute(
                    "SELECT id FROM xiaji_documents WHERE project_id = ? AND owner_user_id = ?",
                    (project_id, owner_user_id),
                ).fetchall()
                for row in docs:
                    connection.execute("DELETE FROM xiaji_document_analyses WHERE document_id = ?", (row["id"],))
                    connection.execute("DELETE FROM xiaji_chapters WHERE document_id = ?", (row["id"],))
                connection.execute(
                    "DELETE FROM xiaji_documents WHERE project_id = ? AND owner_user_id = ?",
                    (project_id, owner_user_id),
                )
            connection.execute(
                "DELETE FROM xiaji_projects WHERE id = ? AND owner_user_id = ?",
                (project_id, owner_user_id),
            )
