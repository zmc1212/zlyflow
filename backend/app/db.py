from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

IntegrityError: tuple[type[Exception], ...] = (sqlite3.IntegrityError,)
try:
    import pymysql
    from pymysql.cursors import DictCursor

    IntegrityError = (sqlite3.IntegrityError, pymysql.err.IntegrityError)
except ImportError:  # pragma: no cover - tests can run sqlite-only
    pymysql = None  # type: ignore[assignment]
    DictCursor = None  # type: ignore[misc, assignment]


Row = Mapping[str, Any]
SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
STORAGE_CONFIG_PATH = Path(__file__).resolve().parents[2] / "docs" / "存储配置.md"


def mysql_schema_sql() -> str:
    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        raise FileNotFoundError(f"未找到 {SQL_DIR} 下的 SQL 文件")
    return "\n".join(path.read_text(encoding="utf-8") for path in files)

_INSERT_OR_IGNORE = re.compile(r"INSERT\s+OR\s+IGNORE\s+INTO", re.IGNORECASE)
_AUTOINCREMENT = re.compile(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", re.IGNORECASE)
_COLLATE_NOCASE = re.compile(r"\s+COLLATE\s+NOCASE", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\?")
_SQLITE_BEGIN = re.compile(r"^BEGIN(\s+(DEFERRED|IMMEDIATE|EXCLUSIVE))?$", re.IGNORECASE)


def parse_storage_config(path: Path | None = None) -> dict[str, Any]:
    """Read MySQL (and Redis) connection fields from docs/存储配置.md."""
    config_path = path or STORAGE_CONFIG_PATH
    text = config_path.read_text(encoding="utf-8")
    mysql_block = text.split("### 1.2")[0] if "### 1.2" in text else text
    redis_block = text.split("### 1.2")[1] if "### 1.2" in text else ""

    def field(block: str, label: str) -> str:
        match = re.search(rf"\*\*\s*{re.escape(label)}\s*\*\*[：:]\s*`([^`]+)`", block)
        if not match:
            raise ValueError(f"未在 {config_path} 中找到 {label}")
        return match.group(1).strip()

    host_port = field(mysql_block, "数据库服务地址")
    host, _, port_text = host_port.partition(":")
    return {
        "mysql": {
            "host": host.strip(),
            "port": int(port_text or "3306"),
            "database": field(mysql_block, "数据库名称"),
            "user": field(mysql_block, "用户名"),
            "password": field(mysql_block, "密码"),
        },
        "redis": {
            "host": field(redis_block, "主机地址") if redis_block else "",
            "port": int(field(redis_block, "端口")) if redis_block else 6379,
            "database": int(field(redis_block, "数据库索引 (Database)")) if redis_block else 1,
            "password": field(redis_block, "认证密码") if redis_block else "",
        },
    }


logger = logging.getLogger("zly-ai-video-studio.db")


def mysql_connect_timeout() -> int:
    return max(5, int(os.getenv("ZLY_MYSQL_CONNECT_TIMEOUT", "20")))


def mysql_connect_attempts() -> int:
    return max(1, int(os.getenv("ZLY_MYSQL_CONNECT_ATTEMPTS", "3")))


def is_unreachable_mysql_error(error: BaseException) -> bool:
    if isinstance(error, TimeoutError):
        return True
    if pymysql is not None and isinstance(error, pymysql.err.OperationalError):
        code = error.args[0] if error.args else 0
        return code in {2003, 2006, 2013}
    return isinstance(error, OSError)


def _pymysql_connect(
    config: Mapping[str, Any],
    *,
    database: str | None,
    autocommit: bool,
    cursorclass: Any | None = None,
) -> Any:
    if pymysql is None:
        raise RuntimeError("未安装 pymysql，请执行 pip install -r backend/requirements.txt")
    kwargs: dict[str, Any] = {
        "host": str(config["host"]),
        "port": int(config["port"]),
        "user": str(config["user"]),
        "password": str(config["password"]),
        "charset": "utf8mb4",
        "connect_timeout": mysql_connect_timeout(),
        "read_timeout": 60,
        "write_timeout": 60,
        "autocommit": autocommit,
    }
    if database:
        kwargs["database"] = database
    if cursorclass is not None:
        kwargs["cursorclass"] = cursorclass
    return pymysql.connect(**kwargs)


def connect_mysql_with_retry(
    config: Mapping[str, Any],
    *,
    database: str | None,
    autocommit: bool = False,
    cursorclass: Any | None = None,
) -> Any:
    last_error: BaseException | None = None
    attempts = mysql_connect_attempts()
    for attempt in range(1, attempts + 1):
        try:
            return _pymysql_connect(
                config, database=database, autocommit=autocommit, cursorclass=cursorclass,
            )
        except Exception as error:
            last_error = error
            if not is_unreachable_mysql_error(error) or attempt >= attempts:
                break
            logger.warning(
                "连接 MySQL %s:%s 第 %s/%s 次失败：%s",
                config.get("host"), config.get("port"), attempt, attempts, error,
            )
            time.sleep(min(1.5 * attempt, 4))
    assert last_error is not None
    raise last_error


def mysql_settings_from_env_or_docs() -> dict[str, Any]:
    parsed = parse_storage_config()["mysql"]
    host = os.getenv("ZLY_MYSQL_HOST", parsed["host"])
    port_default = str(parsed["port"])
    if ":" in host and os.getenv("ZLY_MYSQL_HOST") and os.getenv("ZLY_MYSQL_PORT") is None:
        host, _, port_in_host = host.partition(":")
        port_default = port_in_host or port_default
    return {
        "host": host,
        "port": int(os.getenv("ZLY_MYSQL_PORT", port_default)),
        "database": os.getenv("ZLY_MYSQL_DATABASE", parsed["database"]),
        "user": os.getenv("ZLY_MYSQL_USER", parsed["user"]),
        "password": os.getenv("ZLY_MYSQL_PASSWORD", parsed["password"]),
    }


def rewrite_sql(sql: str, dialect: str) -> str:
    if dialect != "mysql":
        return sql
    sql = _INSERT_OR_IGNORE.sub("INSERT IGNORE INTO", sql)
    sql = _AUTOINCREMENT.sub("INTEGER PRIMARY KEY AUTO_INCREMENT", sql)
    sql = _COLLATE_NOCASE.sub("", sql)
    sql = _PLACEHOLDER.sub("%s", sql)
    return sql


def _split_statements(script: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
    trailing = "\n".join(current).strip()
    if trailing:
        statements.append(trailing)
    return statements


class DictRow(dict):
    """dict row that also supports sqlite-style numeric indexing."""

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _CursorAdapter:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount or 0)

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        return DictRow(row) if row is not None else None

    def fetchall(self) -> list[dict[str, Any]]:
        return [DictRow(row) for row in self._cursor.fetchall()]


class _EmptyCursor:
    rowcount = 0
    lastrowid = None

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[dict[str, Any]]:
        return []


class DbConnection:
    def __init__(self, dialect: str, raw: Any, *, on_close: Any | None = None) -> None:
        self.dialect = dialect
        self._raw = raw
        self._on_close = on_close
        self._closed = False

    def execute(self, sql: str, parameters: Sequence[Any] | None = None, *, for_update: bool = False) -> _CursorAdapter | _EmptyCursor:
        stripped = sql.strip().rstrip(";")
        if _SQLITE_BEGIN.match(stripped):
            if self.dialect == "sqlite":
                cursor = self._raw.execute(stripped)
                return _CursorAdapter(cursor)
            return _EmptyCursor()
        if stripped.upper().startswith("PRAGMA"):
            if self.dialect == "sqlite":
                cursor = self._raw.execute(sql, parameters or ())
                return _CursorAdapter(cursor)
            return _EmptyCursor()
        if self.dialect == "mysql" and stripped.upper().startswith("CREATE TABLE") and "TEXT PRIMARY KEY" in stripped.upper():
            return _EmptyCursor()
        if for_update and self.dialect == "mysql" and stripped.upper().startswith("SELECT"):
            stripped = f"{stripped} FOR UPDATE"
        rewritten = rewrite_sql(stripped, self.dialect)
        if self.dialect == "mysql":
            cursor = self._raw.cursor()
            cursor.execute(rewritten, tuple(parameters or ()))
            return _CursorAdapter(cursor)
        cursor = self._raw.execute(rewritten, parameters or ())
        return _CursorAdapter(cursor)

    def executescript(self, script: str) -> None:
        if self.dialect == "sqlite":
            self._raw.executescript(script)
            return
        for statement in _split_statements(script):
            stripped = statement.strip()
            upper = stripped.upper()
            if upper.startswith("PRAGMA") or upper.startswith("CREATE INDEX"):
                continue
            if upper.startswith("CREATE TABLE") and "TEXT PRIMARY KEY" in upper:
                continue
            rewritten = rewrite_sql(stripped.rstrip(";"), self.dialect)
            with self._raw.cursor() as cursor:
                cursor.execute(rewritten)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._on_close is not None:
            self._on_close(self._raw)
            return
        self._raw.close()

    def __enter__(self) -> DbConnection:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any) -> None:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()


class Database:
    dialect: str

    def connection(self) -> DbConnection:
        raise NotImplementedError

    def ensure_column(self, connection: DbConnection, table: str, name: str, declaration: str) -> None:
        if name in self.column_names(connection, table):
            return
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    def apply_mysql_schema(self, connection: DbConnection) -> None:
        return

    def index_exists(self, connection: DbConnection, table: str, name: str) -> bool:
        raise NotImplementedError

    def ensure_index(self, connection: DbConnection, table: str, name: str, columns: str) -> None:
        if self.index_exists(connection, table, name):
            return
        connection.execute(f"CREATE INDEX {name} ON {table} ({columns})")

    def column_names(self, connection: DbConnection, table: str) -> set[str]:
        raise NotImplementedError

    def table_exists(self, connection: DbConnection, table: str) -> bool:
        raise NotImplementedError


class SqliteDatabase(Database):
    dialect = "sqlite"

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    def connection(self) -> DbConnection:
        raw = sqlite3.connect(self.path, timeout=30)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        return DbConnection("sqlite", raw)

    def column_names(self, connection: DbConnection, table: str) -> set[str]:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        names: set[str] = set()
        for row in rows:
            names.add(str(row.get("name") or row.get("NAME") or ""))
        return {name for name in names if name}

    def table_exists(self, connection: DbConnection, table: str) -> bool:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def index_exists(self, connection: DbConnection, table: str, name: str) -> bool:
        row = connection.execute(
            "SELECT 1 AS ok FROM sqlite_master WHERE type = 'index' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None


class MysqlDatabase(Database):
    dialect = "mysql"

    def __init__(self, config: Mapping[str, Any], *, pool_size: int = 8) -> None:
        if pymysql is None:
            raise RuntimeError("未安装 pymysql，请执行 pip install -r backend/requirements.txt")
        self.config = dict(config)
        self._pool_size = pool_size
        self._pool: list[Any] = []
        self._lock = threading.Lock()
        self._schema_lock = threading.Lock()
        self._schema_applied = False
        ensure_mysql_database(self.config)

    def _connect(self) -> Any:
        return connect_mysql_with_retry(
            self.config,
            database=str(self.config["database"]),
            autocommit=False,
            cursorclass=DictCursor,
        )

    def _acquire(self) -> Any:
        while True:
            with self._lock:
                candidate = self._pool.pop() if self._pool else None
            if candidate is None:
                return self._connect()
            try:
                candidate.ping(reconnect=True)
                return candidate
            except Exception:
                try:
                    candidate.close()
                except Exception:
                    pass

    def _release(self, raw: Any) -> None:
        try:
            raw.rollback()
        except Exception:
            try:
                raw.close()
            except Exception:
                return
            return
        with self._lock:
            if len(self._pool) < self._pool_size:
                self._pool.append(raw)
                return
        raw.close()

    def connection(self) -> DbConnection:
        return DbConnection("mysql", self._acquire(), on_close=self._release)

    def apply_mysql_schema(self, connection: DbConnection) -> None:
        with self._schema_lock:
            if self._schema_applied:
                return
            connection.executescript(mysql_schema_sql())
            self._schema_applied = True

    def column_names(self, connection: DbConnection, table: str) -> set[str]:
        rows = connection.execute(
            """SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?""",
            (table,),
        ).fetchall()
        return {str(row["name"]) for row in rows}

    def table_exists(self, connection: DbConnection, table: str) -> bool:
        row = connection.execute(
            """SELECT 1 AS present FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?""",
            (table,),
        ).fetchone()
        return row is not None

    def index_exists(self, connection: DbConnection, table: str, name: str) -> bool:
        row = connection.execute(
            """SELECT 1 AS ok FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND INDEX_NAME = ? LIMIT 1""",
            (table, name),
        ).fetchone()
        return row is not None


def ensure_mysql_database(config: Mapping[str, Any]) -> None:
    if pymysql is None:
        raise RuntimeError("未安装 pymysql，请执行 pip install -r backend/requirements.txt")
    database = str(config["database"])
    try:
        raw = connect_mysql_with_retry(config, database=database, autocommit=True)
        raw.close()
        return
    except Exception as error:
        unknown_db = (
            pymysql is not None
            and isinstance(error, pymysql.err.OperationalError)
            and error.args
            and error.args[0] == 1049
        )
        if not unknown_db:
            raise
    raw = connect_mysql_with_retry(config, database=None, autocommit=True)
    try:
        with raw.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        raw.close()


def open_database(target: Database | Path | str | None = None) -> Database:
    if isinstance(target, Database):
        return target
    if target is None:
        return MysqlDatabase(mysql_settings_from_env_or_docs())
    return SqliteDatabase(Path(target))


@contextmanager
def connect(database: Database) -> Iterator[DbConnection]:
    connection = database.connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
