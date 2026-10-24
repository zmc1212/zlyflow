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
        _schema_ready = True


def _connect_mysql(*, autocommit: bool = True) -> pymysql.Connection:
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
