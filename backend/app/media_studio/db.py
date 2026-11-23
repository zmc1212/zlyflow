from __future__ import annotations

import datetime
import threading
from contextlib import contextmanager
from typing import Any, Generator

import pymysql
from pymysql.cursors import DictCursor

from ..db import mysql_settings_from_env_or_docs

_schema_lock = threading.Lock()
_schema_ready = False
_pool_lock = threading.Lock()
_pool: list[Any] = []
_POOL_SIZE = 16


def now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_mysql_config() -> dict[str, Any]:
    """MySQL 连接配置复用工作台统一来源（docs/存储配置.md / 环境变量，指向 ai-media 库）。"""
    return mysql_settings_from_env_or_docs()


def ensure_schema(*, force: bool = False) -> None:
    """Replay sql/*.sql (including ai_project_jobs) before any media_studio query."""
    global _schema_ready
    with _schema_lock:
        if _schema_ready:
            return
        from ..db import MysqlDatabase, is_isolated_sqlite_runtime

        if is_isolated_sqlite_runtime() and not force:
            _schema_ready = True
            return
        database = MysqlDatabase(get_mysql_config())
        with database.connection() as connection:
            database.apply_mysql_schema(connection)
            _relax_smart_edit_foreign_key(database, connection)
            _ensure_project_owner(database, connection)
        _schema_ready = True


def _relax_smart_edit_foreign_key(database: Any, connection: Any) -> None:
    """剪除 ai_smart_edit_documents.project_id 对 ai_projects 的外键。

    画布「时间线」节点把剪辑工程挂在 `canvas:<画布id>` scope 下，不属于 ai_projects；
    共享库曾手工给该表加过 fk_smart_edit_project（ON DELETE CASCADE），画布 scope
    的 INSERT 会被 1452 拒绝。级联语义由 ProjectService.delete_project 显式清理补偿。
    幂等：外键不存在时跳过。
    """
    row = connection.execute(
        "SELECT COUNT(*) AS n FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_smart_edit_documents' "
        "AND CONSTRAINT_NAME = 'fk_smart_edit_project' AND CONSTRAINT_TYPE = 'FOREIGN KEY'"
    ).fetchone()
    count = row["n"] if isinstance(row, dict) else row[0]
    if not count:
        return
    connection.execute("ALTER TABLE ai_smart_edit_documents DROP FOREIGN KEY fk_smart_edit_project")


def _ensure_project_owner(database: Any, connection: Any) -> None:
    """给共享的 ai_projects 补归属列；历史无归属项目由最早的超管接管。"""
    database.ensure_column(connection, "ai_projects", "owner_user_id", "VARCHAR(64) NULL")
    database.ensure_index(
        connection, "ai_projects", "idx_ai_projects_owner_updated", "owner_user_id, updated_at"
    )
    owner = connection.execute(
        "SELECT id FROM users WHERE role = ? AND is_active = 1 ORDER BY created_at ASC LIMIT 1",
        ("super_admin",),
    ).fetchone()
    if owner:
        connection.execute(
            "UPDATE ai_projects SET owner_user_id = ? WHERE owner_user_id IS NULL", (owner["id"],)
        )


def _connect_mysql(*, autocommit: bool = True) -> pymysql.Connection:
    from ..db import is_isolated_sqlite_runtime

    if is_isolated_sqlite_runtime():
        raise RuntimeError("隔离测试禁止连接真实 MySQL；请使用临时 SQLite 或 mock 数据库连接")
    cfg = get_mysql_config()
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=autocommit,
    )


def get_mysql_connection(*, autocommit: bool = True) -> pymysql.Connection:
    ensure_schema()
    if not autocommit:
        return _connect_mysql(autocommit=False)
    with _pool_lock:
        while _pool:
            candidate = _pool.pop()
            try:
                candidate.ping(reconnect=True)
                return candidate
            except Exception:
                try:
                    candidate.close()
                except Exception:
                    pass
    return _connect_mysql(autocommit=True)


def release_mysql_connection(conn: Any, *, reuse: bool = True) -> None:
    if not reuse:
        try:
            conn.close()
        except Exception:
            pass
        return
    with _pool_lock:
        if len(_pool) < _POOL_SIZE:
            _pool.append(conn)
            return
    try:
        conn.close()
    except Exception:
        pass


@contextmanager
def db_cursor() -> Generator[DictCursor, None, None]:
    conn = get_mysql_connection()
    try:
        with conn.cursor() as cursor:
            yield cursor
    except Exception:
        release_mysql_connection(conn, reuse=False)
        raise
    else:
        release_mysql_connection(conn)


@contextmanager
def transaction_cursor() -> Generator[DictCursor, None, None]:
    conn = get_mysql_connection(autocommit=False)
    try:
        with conn.cursor() as cursor:
            yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query_one(sql: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    with db_cursor() as cursor:
        cursor.execute(sql, params or ())
        return cursor.fetchone()


def query_all(sql: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
    with db_cursor() as cursor:
        cursor.execute(sql, params or ())
        return cursor.fetchall()


def execute_sql(sql: str, params: tuple | dict | None = None) -> int:
    with db_cursor() as cursor:
        return cursor.execute(sql, params or ())
