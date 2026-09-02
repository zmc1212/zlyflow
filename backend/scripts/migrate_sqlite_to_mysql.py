from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import settings
from backend.app.db import MysqlDatabase, mysql_schema_sql, mysql_settings_from_env_or_docs


TABLES_IN_ORDER = (
    "users",
    "sessions",
    "audit_logs",
    "jobs",
    "schema_migrations",
    "job_rounds",
    "generation_items",
    "grs_provider_settings",
    "qiniu_provider_settings",
    "llm_provider_settings",
    "comfy_provider_settings",
    "tts_provider_settings",
    "director_projects",
    "director_library_assets",
    "director_operations",
    "grs_image_models",
)


def sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def sqlite_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]


def copy_table(sqlite_conn: sqlite3.Connection, mysql: MysqlDatabase, table: str) -> tuple[int, int]:
    source_columns = sqlite_columns(sqlite_conn, table)
    rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
    if not rows:
        return 0, 0
    inserted = 0
    with mysql.connection() as connection:
        dest_columns = mysql.column_names(connection, table)
        columns = [name for name in source_columns if name in dest_columns]
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        sql = f"INSERT OR IGNORE INTO {table} ({column_sql}) VALUES ({placeholders})"
        for row in rows:
            mapping = dict(row)
            values = [mapping.get(name) for name in columns]
            connection.execute(sql, values)
            inserted += 1
        dest_count = connection.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()["total"]
    return inserted, int(dest_count)


def apply_schema(mysql: MysqlDatabase) -> None:
    with mysql.connection() as connection:
        connection.executescript(mysql_schema_sql())


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy local SQLite rows into remote MySQL.")
    parser.add_argument("--sqlite", type=Path, default=None, help="SQLite file; default is data/zly-ai-video-studio.db")
    args = parser.parse_args()
    sqlite_path = args.sqlite or settings.database_path
    if not sqlite_path.is_file():
        print(f"SQLite 文件不存在: {sqlite_path}")
        return 1

    mysql = MysqlDatabase(mysql_settings_from_env_or_docs())
    print(f"应用 DDL sql/001_init_mysql.sql -> {mysql.config['host']}:{mysql.config['port']}/{mysql.config['database']}")
    apply_schema(mysql)

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    present = sqlite_tables(sqlite_conn)
    print(f"读取 {sqlite_path}")
    for table in TABLES_IN_ORDER:
        if table not in present:
            print(f"  skip {table} (SQLite 中无此表)")
            continue
        copied, dest_count = copy_table(sqlite_conn, mysql, table)
        source_count = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: sqlite={source_count} copied={copied} mysql={dest_count}")
    sqlite_conn.close()
    print("SQLite -> MySQL 导入完成（INSERT IGNORE，可重复执行）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
