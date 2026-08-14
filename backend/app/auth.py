from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import UserRole


SESSION_HOURS = 12
PASSWORD_MIN_LENGTH = 6


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or now()).isoformat()


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_password(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"密码至少需要 {PASSWORD_MIN_LENGTH} 个字符")
    if len(password) > 128:
        raise ValueError("密码不能超过 128 个字符")


def hash_password(password: str, salt: bytes | None = None) -> str:
    validate_password(password)
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(expected_hex)),
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected_hex))
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token(session_token: str) -> str:
    return hashlib.sha256(f"zly-ai-video-studio-csrf:{session_token}".encode("utf-8")).hexdigest()


class AuthStore:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self.initialize()

    def connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT,
                    detail TEXT,
                    ip_address TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
                """
            )

    @staticmethod
    def public_user(row: sqlite3.Row | dict) -> dict:
        data = dict(row)
        data.pop("password_hash", None)
        data["is_active"] = bool(data["is_active"])
        data["must_change_password"] = bool(data["must_change_password"])
        return data

    def setup_required(self) -> bool:
        with self.connection() as connection:
            return connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None

    def create_user(
        self, username: str, display_name: str, password: str, role: UserRole,
        *, must_change_password: bool = True,
    ) -> dict:
        username = normalize_username(username)
        display_name = display_name.strip()
        if not username or not display_name:
            raise ValueError("账号和姓名不能为空")
        user_id = secrets.token_urlsafe(12)
        timestamp = iso()
        try:
            with self.connection() as connection:
                connection.execute(
                    """INSERT INTO users (
                        id, username, display_name, password_hash, role, is_active,
                        must_change_password, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                    (
                        user_id, username, display_name, hash_password(password), role.value,
                        int(must_change_password), timestamp, timestamp,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("该账号已存在") from error
        return self.get_user(user_id)

    def get_user(self, user_id: str) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(user_id)
        return self.public_user(row)

    def list_users(self) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
        return [self.public_user(row) for row in rows]

    def active_super_admin_count(self) -> int:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM users WHERE role = ? AND is_active = 1",
                (UserRole.SUPER_ADMIN.value,),
            ).fetchone()
        return int(row["total"])

    def authenticate(self, username: str, password: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (normalize_username(username),),
            ).fetchone()
            if row is None or not row["is_active"] or not verify_password(password, row["password_hash"]):
                return None
            connection.execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?", (iso(), iso(), row["id"]))
        return self.get_user(row["id"])

    def create_session(self, user_id: str) -> tuple[str, str]:
        raw_token = secrets.token_urlsafe(32)
        created_at = now()
        expires_at = created_at + timedelta(hours=SESSION_HOURS)
        with self.connection() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso(created_at),))
            connection.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token_hash(raw_token), user_id, iso(expires_at), iso(created_at)),
            )
        return raw_token, iso(expires_at)

    def user_for_session(self, raw_token: str | None) -> dict | None:
        if not raw_token:
            return None
        with self.connection() as connection:
            row = connection.execute(
                """SELECT users.* FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ? AND users.is_active = 1""",
                (token_hash(raw_token), iso()),
            ).fetchone()
        return self.public_user(row) if row else None

    def revoke_session(self, raw_token: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(raw_token),))

    def revoke_user_sessions(self, user_id: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def update_user(self, user_id: str, *, role: UserRole | None = None, is_active: bool | None = None) -> dict:
        updates: dict[str, object] = {"updated_at": iso()}
        if role is not None:
            updates["role"] = role.value
        if is_active is not None:
            updates["is_active"] = int(is_active)
        assignment = ", ".join(f"{column} = ?" for column in updates)
        with self.connection() as connection:
            cursor = connection.execute(f"UPDATE users SET {assignment} WHERE id = ?", (*updates.values(), user_id))
            if cursor.rowcount == 0:
                raise KeyError(user_id)
        if is_active is False:
            self.revoke_user_sessions(user_id)
        return self.get_user(user_id)

    def set_password(self, user_id: str, password: str, *, must_change_password: bool) -> dict:
        with self.connection() as connection:
            cursor = connection.execute(
                "UPDATE users SET password_hash = ?, must_change_password = ?, updated_at = ? WHERE id = ?",
                (hash_password(password), int(must_change_password), iso(), user_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(user_id)
        self.revoke_user_sessions(user_id)
        return self.get_user(user_id)

    def audit(
        self, action: str, target_type: str, *, actor_user_id: str | None = None,
        target_id: str | None = None, detail: str | None = None, ip_address: str | None = None,
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO audit_logs (
                    actor_user_id, action, target_type, target_id, detail, ip_address, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (actor_user_id, action, target_type, target_id, detail, ip_address, iso()),
            )
