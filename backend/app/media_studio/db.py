from __future__ import annotations

import datetime
from contextlib import contextmanager
from typing import Any, Generator

import pymysql
from pymysql.cursors import DictCursor

from ..db import mysql_settings_from_env_or_docs


def now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_mysql_config() -> dict[str, Any]:
    """MySQL 连接配置复用工作台统一来源（docs/存储配置.md / 环境变量，指向 ai-media 库）。"""
    return mysql_settings_from_env_or_docs()


def get_mysql_connection(*, autocommit: bool = True) -> pymysql.Connection:
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


@contextmanager
def db_cursor() -> Generator[DictCursor, None, None]:
    conn = get_mysql_connection()
    try:
        with conn.cursor() as cursor:
            yield cursor
    finally:
        conn.close()


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
