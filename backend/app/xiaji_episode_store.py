from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .db import Database, open_database
from .storage import now

BEAT_KINDS = ("scene_heading", "action", "dialogue")
EPISODE_STATUSES = ("draft", "scripting", "script_ready", "sketching", "sketched")
BEAT_STATUSES = ("draft", "queued", "generating", "succeeded", "failed")

BEAT_MEDIA_COLUMNS = (
    ("render_job_id", "TEXT"),
    ("render_url", "TEXT"),
    ("render_prompt", "TEXT"),
    ("render_model", "TEXT"),
    ("video_job_id", "TEXT"),
    ("video_url", "TEXT"),
    ("video_prompt", "TEXT"),
    ("video_model", "TEXT"),
    ("video_duration", "TEXT"),
)


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        keys = set(row.keys())
    except Exception:
        keys = None
    if keys is not None and key not in keys:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


SQLITE_EPISODE_SCHEMA = """
CREATE TABLE IF NOT EXISTS xiaji_episodes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    source_document_id TEXT,
    content_summary TEXT,
    main_conflict TEXT,
    cliffhanger TEXT,
    key_events_json TEXT NOT NULL,
    original_lines_json TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, number)
);
CREATE INDEX IF NOT EXISTS idx_xiaji_episodes_project
    ON xiaji_episodes(project_id, number);
CREATE TABLE IF NOT EXISTS xiaji_episode_links (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL REFERENCES xiaji_episodes(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    first_seen_line INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_xiaji_episode_links_episode
    ON xiaji_episode_links(episode_id, kind);
CREATE TABLE IF NOT EXISTS xiaji_beats (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL REFERENCES xiaji_episodes(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    beat_kind TEXT NOT NULL,
    heading TEXT,
    speaker TEXT,
    dialogue TEXT,
    action TEXT,
    character_ids_json TEXT NOT NULL,
    scene_id TEXT,
    prop_ids_json TEXT NOT NULL,
    sketch_job_id TEXT,
    sketch_url TEXT,
    sketch_prompt TEXT,
    sketch_model TEXT,
    render_job_id TEXT,
    render_url TEXT,
    render_prompt TEXT,
    render_model TEXT,
    video_job_id TEXT,
    video_url TEXT,
    video_prompt TEXT,
    video_model TEXT,
    video_duration TEXT,
    status TEXT NOT NULL,
    error TEXT,
    UNIQUE(episode_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_xiaji_beats_episode
    ON xiaji_beats(episode_id, sequence);
"""


def _parse_json(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        parsed = json.loads(raw or ("[]" if isinstance(fallback, list) else "{}"))
    except json.JSONDecodeError:
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def split_original_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if line:
            lines.append(line[:800])
    return lines[:400]


def allocate_chapter_text(chapters: list[dict[str, Any]], episode_count: int) -> list[str]:
    count = max(1, episode_count)
    bodies = [str(item.get("content") or "").strip() for item in chapters]
    combined = "\n\n".join(part for part in bodies if part)
    if not combined:
        return [""] * count
    if count == 1:
        return [combined]
    total = len(combined)
    chunk = max(1, total // count)
    slices: list[str] = []
    cursor = 0
    for index in range(count):
        if index == count - 1:
            slices.append(combined[cursor:].strip())
            break
        end = cursor + chunk
        cut = combined.find("\n", end)
        if cut < 0 or cut - end > 400:
            cut = end
        slices.append(combined[cursor:cut].strip())
        cursor = cut
    while len(slices) < count:
        slices.append("")
    return slices[:count]


def first_seen_line(lines: list[str], names: list[str]) -> int:
    needles = [name.strip() for name in names if str(name or "").strip()]
    if not needles:
        return 0
    for index, line in enumerate(lines, start=1):
        if any(name in line for name in needles):
            return index
    return 0


class XiajiEpisodeStore:
    def __init__(self, database: Database | Path) -> None:
        self._db = database if isinstance(database, Database) else open_database(database)
        self.initialize()

    def initialize(self) -> None:
        with self._db.connection() as connection:
            if self._db.dialect == "mysql":
                self._db.apply_mysql_schema(connection)
            else:
                connection.executescript(SQLITE_EPISODE_SCHEMA)
            if self._db.table_exists(connection, "xiaji_beats"):
                for name, declaration in BEAT_MEDIA_COLUMNS:
                    self._db.ensure_column(connection, "xiaji_beats", name, declaration)

    def delete_project_episodes(self, project_id: str, owner_user_id: str) -> None:
        with self._db.connection() as connection:
            if not self._db.table_exists(connection, "xiaji_episodes"):
                return
            rows = connection.execute(
                "SELECT id FROM xiaji_episodes WHERE project_id = ? AND owner_user_id = ?",
                (project_id, owner_user_id),
            ).fetchall()
            for row in rows:
                episode_id = row["id"]
                connection.execute("DELETE FROM xiaji_beats WHERE episode_id = ?", (episode_id,))
                connection.execute("DELETE FROM xiaji_episode_links WHERE episode_id = ?", (episode_id,))
            connection.execute(
                "DELETE FROM xiaji_episodes WHERE project_id = ? AND owner_user_id = ?",
                (project_id, owner_user_id),
            )

    def _links_for(self, connection: Any, episode_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM xiaji_episode_links WHERE episode_id = ? ORDER BY kind, first_seen_line, id",
            (episode_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "asset_id": row["asset_id"],
                "kind": row["kind"],
                "first_seen_line": int(row["first_seen_line"] or 0),
            }
            for row in rows
        ]

    def _beats_for(self, connection: Any, episode_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM xiaji_beats WHERE episode_id = ? ORDER BY sequence",
            (episode_id,),
        ).fetchall()
        return [self._beat_from_row(row) for row in rows]

    def _beat_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "episode_id": row["episode_id"],
            "sequence": int(row["sequence"] or 0),
            "kind": row["beat_kind"],
            "heading": row["heading"] or "",
            "speaker": row["speaker"] or "",
            "dialogue": row["dialogue"] or "",
            "action": row["action"] or "",
            "character_ids": _parse_json(row["character_ids_json"], []),
            "scene_id": row["scene_id"],
            "prop_ids": _parse_json(row["prop_ids_json"], []),
            "sketch_job_id": row["sketch_job_id"],
            "sketch_url": row["sketch_url"],
            "sketch_prompt": row["sketch_prompt"],
            "sketch_model": row["sketch_model"],
            "render_job_id": _row_value(row, "render_job_id"),
            "render_url": _row_value(row, "render_url"),
            "render_prompt": _row_value(row, "render_prompt"),
            "render_model": _row_value(row, "render_model"),
            "video_job_id": _row_value(row, "video_job_id"),
            "video_url": _row_value(row, "video_url"),
            "video_prompt": _row_value(row, "video_prompt"),
            "video_model": _row_value(row, "video_model"),
            "video_duration": _row_value(row, "video_duration"),
            "status": row["status"],
            "error": row["error"],
        }

    def _from_row(
        self,
        row: dict[str, Any],
        *,
        links: list[dict[str, Any]] | None = None,
        beats: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        record = {
            "id": row["id"],
            "project_id": row["project_id"],
            "owner_user_id": row["owner_user_id"],
            "number": int(row["number"] or 0),
            "title": row["title"],
            "source_document_id": row["source_document_id"],
            "content_summary": row["content_summary"] or "",
            "main_conflict": row["main_conflict"] or "",
            "cliffhanger": row["cliffhanger"] or "",
            "key_events": _parse_json(row["key_events_json"], []),
            "original_lines": _parse_json(row["original_lines_json"], []),
            "status": row["status"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "links": links if links is not None else [],
            "beats": beats if beats is not None else [],
        }
        record["beat_count"] = len(record["beats"])
        record["character_count"] = sum(1 for item in record["links"] if item.get("kind") == "character")
        record["scene_count"] = sum(1 for item in record["links"] if item.get("kind") == "scene")
        record["prop_count"] = sum(1 for item in record["links"] if item.get("kind") == "prop")
        record["line_count"] = len(record["original_lines"])
        return record

    def _links_for_episodes(self, connection: Any, episode_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not episode_ids:
            return {}
        placeholders = ", ".join(["?"] * len(episode_ids))
        rows = connection.execute(
            f"SELECT * FROM xiaji_episode_links WHERE episode_id IN ({placeholders}) ORDER BY kind, first_seen_line, id",
            tuple(episode_ids),
        ).fetchall()
        result: dict[str, list[dict[str, Any]]] = {eid: [] for eid in episode_ids}
        for row in rows:
            eid = row["episode_id"]
            if eid in result:
                result[eid].append(
                    {
                        "id": row["id"],
                        "asset_id": row["asset_id"],
                        "kind": row["kind"],
                        "first_seen_line": int(row["first_seen_line"] or 0),
                    }
                )
        return result

    def _beats_for_episodes(self, connection: Any, episode_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not episode_ids:
            return {}
        placeholders = ", ".join(["?"] * len(episode_ids))
        rows = connection.execute(
            f"SELECT * FROM xiaji_beats WHERE episode_id IN ({placeholders}) ORDER BY sequence",
            tuple(episode_ids),
        ).fetchall()
        result: dict[str, list[dict[str, Any]]] = {eid: [] for eid in episode_ids}
        for row in rows:
            eid = row["episode_id"]
            if eid in result:
                result[eid].append(self._beat_from_row(row))
        return result

    def list_episodes(self, owner_user_id: str, project_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM xiaji_episodes WHERE owner_user_id = ? AND project_id = ?
                ORDER BY number""",
                (owner_user_id, project_id),
            ).fetchall()
            if not rows:
                return []
            episode_ids = [row["id"] for row in rows]
            links_map = self._links_for_episodes(connection, episode_ids)
            beats_map = self._beats_for_episodes(connection, episode_ids)
            return [
                self._from_row(
                    dict(row),
                    links=links_map.get(row["id"]) or [],
                    beats=beats_map.get(row["id"]) or [],
                )
                for row in rows
            ]

    def get_episode(self, episode_id: str, owner_user_id: str) -> dict[str, Any]:
        with self._db.connection() as connection:
            row = connection.execute(
                "SELECT * FROM xiaji_episodes WHERE id = ? AND owner_user_id = ?",
                (episode_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise KeyError(episode_id)
            return self._from_row(
                dict(row),
                links=self._links_for(connection, episode_id),
                beats=self._beats_for(connection, episode_id),
            )

    def find_by_number(self, project_id: str, number: int) -> dict[str, Any] | None:
        with self._db.connection() as connection:
            row = connection.execute(
                "SELECT * FROM xiaji_episodes WHERE project_id = ? AND number = ?",
                (project_id, number),
            ).fetchone()
            if row is None:
                return None
            episode_id = row["id"]
            return self._from_row(
                dict(row),
                links=self._links_for(connection, episode_id),
                beats=self._beats_for(connection, episode_id),
            )

    def upsert_episode(
        self,
        owner_user_id: str,
        *,
        project_id: str,
        number: int,
        title: str,
        source_document_id: str | None,
        content_summary: str,
        main_conflict: str,
        cliffhanger: str,
        key_events: list[str],
        original_lines: list[str],
        overwrite_script: bool,
    ) -> dict[str, Any]:
        existing = self.find_by_number(project_id, number)
        timestamp = now()
        protected = existing is not None and existing["status"] != "draft" and not overwrite_script
        with self._db.connection() as connection:
            if existing is None:
                episode_id = f"xje-{uuid.uuid4().hex[:16]}"
                connection.execute(
                    """INSERT INTO xiaji_episodes (
                        id, project_id, owner_user_id, number, title, source_document_id,
                        content_summary, main_conflict, cliffhanger, key_events_json, original_lines_json,
                        status, error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', NULL, ?, ?)""",
                    (
                        episode_id,
                        project_id,
                        owner_user_id,
                        int(number),
                        (title or f"第{number}集")[:255],
                        source_document_id,
                        content_summary[:800],
                        main_conflict[:400],
                        cliffhanger[:400],
                        json.dumps(key_events[:20], ensure_ascii=False),
                        json.dumps(original_lines, ensure_ascii=False),
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                episode_id = existing["id"]
                next_lines = existing["original_lines"] if protected else original_lines
                connection.execute(
                    """UPDATE xiaji_episodes SET title = ?, source_document_id = ?, content_summary = ?,
                    main_conflict = ?, cliffhanger = ?, key_events_json = ?, original_lines_json = ?,
                    updated_at = ? WHERE id = ?""",
                    (
                        (title or existing["title"])[:255],
                        source_document_id,
                        content_summary[:800],
                        main_conflict[:400],
                        cliffhanger[:400],
                        json.dumps(key_events[:20], ensure_ascii=False),
                        json.dumps(next_lines, ensure_ascii=False),
                        timestamp,
                        episode_id,
                    ),
                )
        return self.get_episode(episode_id, owner_user_id)

    def replace_links(self, episode_id: str, owner_user_id: str, links: list[dict[str, Any]]) -> dict[str, Any]:
        self.get_episode(episode_id, owner_user_id)
        timestamp = now()
        with self._db.connection() as connection:
            connection.execute("DELETE FROM xiaji_episode_links WHERE episode_id = ?", (episode_id,))
            seen: set[str] = set()
            for item in links:
                asset_id = str(item.get("asset_id") or "").strip()
                kind = str(item.get("kind") or "").strip()
                if not asset_id or kind not in {"character", "scene", "prop"} or asset_id in seen:
                    continue
                seen.add(asset_id)
                connection.execute(
                    """INSERT INTO xiaji_episode_links (id, episode_id, asset_id, kind, first_seen_line)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        f"xjl-{uuid.uuid4().hex[:16]}",
                        episode_id,
                        asset_id,
                        kind,
                        int(item.get("first_seen_line") or 0),
                    ),
                )
            connection.execute(
                "UPDATE xiaji_episodes SET updated_at = ? WHERE id = ?",
                (timestamp, episode_id),
            )
        return self.get_episode(episode_id, owner_user_id)

    def replace_beats(self, episode_id: str, owner_user_id: str, beats: list[dict[str, Any]], *, status: str) -> dict[str, Any]:
        self.get_episode(episode_id, owner_user_id)
        timestamp = now()
        with self._db.connection() as connection:
            connection.execute("DELETE FROM xiaji_beats WHERE episode_id = ?", (episode_id,))
            for index, item in enumerate(beats, start=1):
                kind = str(item.get("kind") or "action").strip()
                if kind not in BEAT_KINDS:
                    kind = "action"
                connection.execute(
                    """INSERT INTO xiaji_beats (
                        id, episode_id, sequence, beat_kind, heading, speaker, dialogue, action,
                        character_ids_json, scene_id, prop_ids_json, sketch_job_id, sketch_url,
                        sketch_prompt, sketch_model, status, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 'draft', NULL)""",
                    (
                        str(item.get("id") or f"xjb-{uuid.uuid4().hex[:16]}"),
                        episode_id,
                        index,
                        kind,
                        str(item.get("heading") or "")[:255],
                        str(item.get("speaker") or "")[:128],
                        str(item.get("dialogue") or "")[:2000],
                        str(item.get("action") or "")[:2000],
                        json.dumps(item.get("character_ids") or [], ensure_ascii=False),
                        item.get("scene_id"),
                        json.dumps(item.get("prop_ids") or [], ensure_ascii=False),
                    ),
                )
            connection.execute(
                "UPDATE xiaji_episodes SET status = ?, error = NULL, updated_at = ? WHERE id = ?",
                (status, timestamp, episode_id),
            )
        return self.get_episode(episode_id, owner_user_id)

    def update_episode(
        self,
        episode_id: str,
        owner_user_id: str,
        *,
        title: str | None = None,
        status: str | None = None,
        error: str | None = None,
        clear_error: bool = False,
    ) -> dict[str, Any]:
        current = self.get_episode(episode_id, owner_user_id)
        next_title = (title.strip() if isinstance(title, str) else current["title"])[:255]
        next_status = status or current["status"]
        next_error = None if clear_error else (error if error is not None else current.get("error"))
        with self._db.connection() as connection:
            connection.execute(
                "UPDATE xiaji_episodes SET title = ?, status = ?, error = ?, updated_at = ? WHERE id = ?",
                (next_title, next_status, next_error, now(), episode_id),
            )
        return self.get_episode(episode_id, owner_user_id)

    def update_beat(
        self,
        beat_id: str,
        owner_user_id: str,
        **fields: Any,
    ) -> dict[str, Any]:
        with self._db.connection() as connection:
            row = connection.execute(
                """SELECT b.*, e.owner_user_id FROM xiaji_beats b
                JOIN xiaji_episodes e ON e.id = b.episode_id
                WHERE b.id = ?""",
                (beat_id,),
            ).fetchone()
            if row is None or row["owner_user_id"] != owner_user_id:
                raise KeyError(beat_id)
            allowed = {
                "heading",
                "speaker",
                "dialogue",
                "action",
                "scene_id",
                "sketch_job_id",
                "sketch_url",
                "sketch_prompt",
                "sketch_model",
                "render_job_id",
                "render_url",
                "render_prompt",
                "render_model",
                "video_job_id",
                "video_url",
                "video_prompt",
                "video_model",
                "video_duration",
                "status",
                "error",
            }
            updates: list[str] = []
            values: list[Any] = []
            for key, value in fields.items():
                if key == "character_ids":
                    updates.append("character_ids_json = ?")
                    values.append(json.dumps(value or [], ensure_ascii=False))
                elif key == "prop_ids":
                    updates.append("prop_ids_json = ?")
                    values.append(json.dumps(value or [], ensure_ascii=False))
                elif key in allowed:
                    updates.append(f"{key} = ?")
                    values.append(value)
            if updates:
                values.append(beat_id)
                connection.execute(f"UPDATE xiaji_beats SET {', '.join(updates)} WHERE id = ?", tuple(values))
                connection.execute(
                    "UPDATE xiaji_episodes SET updated_at = ? WHERE id = ?",
                    (now(), row["episode_id"]),
                )
            episode_id = row["episode_id"]
        return self.get_episode(episode_id, owner_user_id)

    def get_beat(self, beat_id: str, owner_user_id: str) -> dict[str, Any]:
        with self._db.connection() as connection:
            row = connection.execute(
                """SELECT b.*, e.owner_user_id FROM xiaji_beats b
                JOIN xiaji_episodes e ON e.id = b.episode_id
                WHERE b.id = ?""",
                (beat_id,),
            ).fetchone()
            if row is None or row["owner_user_id"] != owner_user_id:
                raise KeyError(beat_id)
            beat = self._beat_from_row(row)
            beat["episode_id"] = row["episode_id"]
            return beat
