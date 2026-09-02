from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .db import Database, DbConnection, open_database
from .storage import now
from .xiaji_parser import billed_char_count, estimated_episode_count, parse_chapters


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS xiaji_documents (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    source_format TEXT NOT NULL,
    original_text TEXT NOT NULL,
    status TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    billed_char_count INTEGER NOT NULL DEFAULT 0,
    chapter_count INTEGER NOT NULL DEFAULT 0,
    estimated_episodes INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS xiaji_chapters (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES xiaji_documents(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_xiaji_documents_owner_updated
    ON xiaji_documents(owner_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_xiaji_documents_project
    ON xiaji_documents(project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_xiaji_chapters_document
    ON xiaji_chapters(document_id, sequence);
CREATE TABLE IF NOT EXISTS xiaji_document_analyses (
    document_id TEXT PRIMARY KEY REFERENCES xiaji_documents(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    summary TEXT,
    analysis_json TEXT NOT NULL,
    logs TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class XiajiIngestStore:
    def __init__(self, database: Database | Path) -> None:
        self._db = open_database(database)
        self.initialize()

    def connection(self) -> DbConnection:
        return self._db.connection()

    def initialize(self) -> None:
        with self.connection() as connection:
            if self._db.dialect == "mysql":
                self._db.apply_mysql_schema(connection)
            else:
                connection.executescript(SQLITE_SCHEMA)

    def _document_from_row(self, row: dict[str, Any], chapters: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        record = {
            "id": row["id"],
            "owner_user_id": row["owner_user_id"],
            "project_id": row["project_id"],
            "title": row["title"],
            "filename": row["filename"],
            "source_format": row["source_format"],
            "status": row["status"],
            "char_count": int(row["char_count"] or 0),
            "billed_char_count": int(row["billed_char_count"] or 0),
            "chapter_count": int(row["chapter_count"] or 0),
            "estimated_episodes": int(row["estimated_episodes"] or 0),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if chapters is not None:
            record["chapters"] = chapters
            record["original_text"] = row["original_text"]
        return record

    def _analysis_for(self, connection: DbConnection, document_id: str) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT * FROM xiaji_document_analyses WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["analysis_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            logs = json.loads(row["logs"] or "[]")
        except json.JSONDecodeError:
            logs = []
        payload["model"] = row["model"]
        payload["summary"] = row["summary"] or payload.get("summary") or ""
        payload["logs"] = logs if isinstance(logs, list) else []
        return payload

    def _chapters_for(self, connection: DbConnection, document_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM xiaji_chapters WHERE document_id = ? ORDER BY sequence",
            (document_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "document_id": row["document_id"],
                "sequence": int(row["sequence"]),
                "title": row["title"],
                "content": row["content"],
                "char_count": int(row["char_count"] or 0),
            }
            for row in rows
        ]

    def _replace_chapters(self, connection: DbConnection, document_id: str, chapters: list[dict[str, Any]]) -> None:
        timestamp = now()
        connection.execute("DELETE FROM xiaji_chapters WHERE document_id = ?", (document_id,))
        for index, chapter in enumerate(chapters, start=1):
            content = str(chapter.get("content") or "").strip("\n")
            title = str(chapter.get("title") or f"第{index}章").strip() or f"第{index}章"
            connection.execute(
                """INSERT INTO xiaji_chapters
                (id, document_id, sequence, title, content, char_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(chapter.get("id") or uuid.uuid4()),
                    document_id,
                    index,
                    title[:512],
                    content,
                    len(content),
                    timestamp,
                    timestamp,
                ),
            )

    def _refresh_document_stats(self, connection: DbConnection, document_id: str, *, status: str | None = None) -> None:
        chapters = self._chapters_for(connection, document_id)
        row = connection.execute("SELECT original_text FROM xiaji_documents WHERE id = ?", (document_id,)).fetchone()
        original = row["original_text"] if row else ""
        char_count = len(original)
        billed = billed_char_count(original)
        episode_count = estimated_episode_count(char_count)
        next_status = status
        if next_status is None:
            next_status = "review_required" if len(chapters) <= 1 else "ready"
        connection.execute(
            """UPDATE xiaji_documents SET chapter_count = ?, char_count = ?, billed_char_count = ?,
            estimated_episodes = ?, status = ?, error = NULL, updated_at = ? WHERE id = ?""",
            (len(chapters), char_count, billed, episode_count, next_status, now(), document_id),
        )

    def list_documents(self, owner_user_id: str, project_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM xiaji_documents WHERE owner_user_id = ? AND project_id = ?
                ORDER BY updated_at DESC""",
                (owner_user_id, project_id),
            ).fetchall()
        return [self._document_from_row(dict(row)) for row in rows]

    def get_document(self, document_id: str, owner_user_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM xiaji_documents WHERE id = ? AND owner_user_id = ?",
                (document_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise KeyError(document_id)
            chapters = self._chapters_for(connection, document_id)
            analysis = self._analysis_for(connection, document_id)
        record = self._document_from_row(dict(row), chapters)
        record["analysis"] = analysis
        return record

    def create_from_text(
        self,
        owner_user_id: str,
        *,
        project_id: str,
        filename: str,
        title: str,
        source_format: str,
        original_text: str,
    ) -> dict[str, Any]:
        if not (project_id or "").strip():
            raise ValueError("请选择项目")
        document_id = f"ing-{uuid.uuid4().hex[:16]}"
        timestamp = now()
        chapters = parse_chapters(original_text)
        status = "review_required" if len(chapters) <= 1 else "ready"
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO xiaji_documents (
                    id, owner_user_id, project_id, title, filename, source_format, original_text, status,
                    char_count, billed_char_count, chapter_count, estimated_episodes, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
                (
                    document_id, owner_user_id, project_id, title[:255], filename[:255], source_format, original_text, status,
                    len(original_text), billed_char_count(original_text), len(chapters),
                    estimated_episode_count(len(original_text)), timestamp, timestamp,
                ),
            )
            self._replace_chapters(connection, document_id, chapters)
            self._refresh_document_stats(connection, document_id, status=status)
        return self.get_document(document_id, owner_user_id)

    def replace_chapters(self, document_id: str, owner_user_id: str, chapters: list[dict[str, Any]]) -> dict[str, Any]:
        if not chapters:
            raise ValueError("至少需要保留一章")
        with self.connection() as connection:
            row = connection.execute(
                "SELECT id FROM xiaji_documents WHERE id = ? AND owner_user_id = ?",
                (document_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise KeyError(document_id)
            self._replace_chapters(connection, document_id, chapters)
            self._refresh_document_stats(connection, document_id, status="ready")
        return self.get_document(document_id, owner_user_id)

    def delete_document(self, document_id: str, owner_user_id: str) -> None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT id FROM xiaji_documents WHERE id = ? AND owner_user_id = ?",
                (document_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise KeyError(document_id)
            connection.execute("DELETE FROM xiaji_document_analyses WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM xiaji_chapters WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM xiaji_documents WHERE id = ?", (document_id,))

    def save_analysis(
        self,
        document_id: str,
        owner_user_id: str,
        analysis: dict[str, Any],
        *,
        logs: list[str],
        model: str,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now()
        payload = dict(analysis)
        summary = str(payload.get("summary") or "")[:800]
        with self.connection() as connection:
            row = connection.execute(
                "SELECT id FROM xiaji_documents WHERE id = ? AND owner_user_id = ?",
                (document_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise KeyError(document_id)
            connection.execute("DELETE FROM xiaji_document_analyses WHERE document_id = ?", (document_id,))
            connection.execute(
                """INSERT INTO xiaji_document_analyses
                (document_id, model, summary, analysis_json, logs, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    document_id,
                    (model or "")[:255],
                    summary,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(logs, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE xiaji_documents SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, timestamp, document_id),
            )
        return self.get_document(document_id, owner_user_id)
