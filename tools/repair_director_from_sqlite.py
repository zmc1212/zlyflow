from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import settings
from backend.app.db import MysqlDatabase, mysql_settings_from_env_or_docs

PROJECT_COLUMNS = (
    "id",
    "owner_user_id",
    "title",
    "summary",
    "source_script",
    "style_vibe",
    "requested_shot_count",
    "payload_json",
    "revision",
    "content_revision",
    "created_at",
    "updated_at",
)

OPERATION_COLUMNS = (
    "id",
    "project_id",
    "owner_user_id",
    "kind",
    "status",
    "progress",
    "request_json",
    "result_json",
    "error",
    "cancel_requested",
    "created_at",
    "updated_at",
)


def sqlite_conn() -> sqlite3.Connection:
    path = settings.database_path
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def row_values(row: sqlite3.Row, columns: tuple[str, ...]) -> list:
    return [row[column] for column in columns]


def main() -> int:
    sconn = sqlite_conn()
    mysql = MysqlDatabase(mysql_settings_from_env_or_docs())

    with mysql.connection() as mconn:
        mysql_revisions = {
            row["id"]: int(row["revision"])
            for row in mconn.execute("SELECT id, revision FROM director_projects").fetchall()
        }

    updated_projects: list[str] = []
    for row in sconn.execute(f"SELECT {', '.join(PROJECT_COLUMNS)} FROM director_projects"):
        project_id = row["id"]
        sqlite_revision = int(row["revision"])
        mysql_revision = mysql_revisions.get(project_id)
        if mysql_revision is not None and sqlite_revision <= mysql_revision:
            continue
        values = row_values(row, PROJECT_COLUMNS)
        placeholders = ", ".join("%s" for _ in PROJECT_COLUMNS)
        assignments = ", ".join(f"{column} = %s" for column in PROJECT_COLUMNS[1:])
        with mysql.connection() as mconn:
            if mysql_revision is None:
                mconn.execute(
                    f"INSERT INTO director_projects ({', '.join(PROJECT_COLUMNS)}) VALUES ({placeholders})",
                    values,
                )
            else:
                mconn.execute(
                    f"UPDATE director_projects SET {assignments} WHERE id = %s",
                    (*values[1:], project_id),
                )
        updated_projects.append(project_id)
        print(
            f"project {project_id}: sqlite_rev={sqlite_revision} "
            f"mysql_rev={mysql_revision if mysql_revision is not None else '-'} -> synced"
        )

    inserted_ops = 0
    for row in sconn.execute(f"SELECT {', '.join(OPERATION_COLUMNS)} FROM director_operations"):
        values = row_values(row, OPERATION_COLUMNS)
        with mysql.connection() as mconn:
            existing = mconn.execute(
                "SELECT id FROM director_operations WHERE id = %s",
                (row["id"],),
            ).fetchone()
            if existing:
                continue
            placeholders = ", ".join("%s" for _ in OPERATION_COLUMNS)
            mconn.execute(
                f"INSERT INTO director_operations ({', '.join(OPERATION_COLUMNS)}) VALUES ({placeholders})",
                values,
            )
            inserted_ops += 1

    sconn.close()
    print(f"updated_projects={len(updated_projects)} inserted_operations={inserted_ops}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
