from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import Database, DbConnection, IntegrityError, Row, open_database
from .models import UserRole


SESSION_HOURS = 12
PASSWORD_MIN_LENGTH = 6

# 邮箱自助找回密码：验证码有效期与校验次数上限。
RESET_CODE_TTL_MINUTES = 15
RESET_CODE_MAX_ATTEMPTS = 5
RESET_CODE_LENGTH = 6
EMAIL_MAX_LENGTH = 255
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LastSuperAdminError(RuntimeError):
    """Raised when an update would leave the system without an active super admin."""


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


def _scrypt_encode(secret: str, salt: bytes) -> str:
    digest = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def hash_password(password: str, salt: bytes | None = None) -> str:
    validate_password(password)
    return _scrypt_encode(password, salt or secrets.token_bytes(16))


def hash_secret(secret: str) -> str:
    """Hash a low-entropy secret such as a reset code (no password length floor)."""
    return _scrypt_encode(secret, secrets.token_bytes(16))


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


def verify_secret(secret: str, encoded: str) -> bool:
    """Verify a reset-code hash; shares the scrypt format with passwords."""
    return verify_password(secret, encoded)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email(email: str) -> str:
    normalized = normalize_email(email)
    if not normalized or len(normalized) > EMAIL_MAX_LENGTH or not EMAIL_PATTERN.match(normalized):
        raise ValueError("请输入有效的邮箱地址")
    return normalized


def mask_email(email: str) -> str:
    """脱敏邮箱，用于界面回显（a***@example.com），避免完整暴露收件地址。"""
    normalized = normalize_email(email)
    local, _, domain = normalized.partition("@")
    if not domain:
        return "******"
    if len(local) <= 2:
        masked_local = (local[:1] or "*") + "*"
    else:
        masked_local = local[:2] + "*" * (len(local) - 2)
    return f"{masked_local}@{domain}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token(session_token: str) -> str:
    return hashlib.sha256(f"zly-ai-video-studio-csrf:{session_token}".encode("utf-8")).hexdigest()


class AuthStore:
    def __init__(self, database: Database | Path) -> None:
        self._db = open_database(database)
        self.database_path = getattr(self._db, "path", None)
        self.initialize()

    def connection(self) -> DbConnection:
        return self._db.connection()

    def initialize(self) -> None:
        with self.connection() as connection:
            if self._db.dialect == "mysql":
                self._db.apply_mysql_schema(connection)
            else:
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
                        email TEXT,
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
                    CREATE TABLE IF NOT EXISTS password_reset_codes (
                        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                        code_hash TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                    CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
                    """
                )
            # 老库平滑升级：为已有的 users 表补 email 列，并建立大小写不敏感的唯一索引。
            self._db.ensure_column(connection, "users", "email", "VARCHAR(255) NULL" if self._db.dialect == "mysql" else "TEXT")
            connection.execute("UPDATE users SET email = NULL WHERE email = ''")
            self._db.ensure_unique_index(connection, "users", "uk_users_email", "email")

    @staticmethod
    def public_user(row: Row | dict) -> dict:
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
        *, must_change_password: bool = True, email: str | None = None,
    ) -> dict:
        username = normalize_username(username)
        display_name = display_name.strip()
        if not username or not display_name:
            raise ValueError("账号和姓名不能为空")
        normalized_email = validate_email(email) if email else None
        user_id = secrets.token_urlsafe(12)
        timestamp = iso()
        try:
            with self.connection() as connection:
                if normalized_email and self._email_taken(connection, normalized_email):
                    raise ValueError("该邮箱已被其他账号使用")
                connection.execute(
                    """INSERT INTO users (
                        id, username, display_name, password_hash, role, is_active,
                        must_change_password, email, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                    (
                        user_id, username, display_name, hash_password(password), role.value,
                        int(must_change_password), normalized_email, timestamp, timestamp,
                    ),
                )
        except IntegrityError as error:
            raise ValueError("该账号已存在") from error
        return self.get_user(user_id)

    @staticmethod
    def _email_taken(connection: DbConnection, email: str, *, exclude_user_id: str | None = None) -> bool:
        sql = "SELECT 1 FROM users WHERE email = ?"
        params: list[str] = [email]
        if exclude_user_id is not None:
            sql += " AND id != ?"
            params.append(exclude_user_id)
        return connection.execute(sql, tuple(params)).fetchone() is not None

    def email_taken(self, email: str, *, exclude_user_id: str | None = None) -> bool:
        normalized = validate_email(email)
        with self.connection() as connection:
            return self._email_taken(connection, normalized, exclude_user_id=exclude_user_id)

    def get_user_by_email(self, email: str) -> dict | None:
        try:
            normalized = validate_email(email)
        except ValueError:
            return None
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email = ? AND is_active = 1", (normalized,),
            ).fetchone()
        return self.public_user(row) if row else None

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

    def verify_credentials(self, username: str, password: str) -> dict | None:
        """Read-only password check: unlike authenticate(), it must not touch last_login_at."""
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?", (normalize_username(username),),
            ).fetchone()
        if row is None or not row["is_active"] or not verify_password(password, row["password_hash"]):
            return None
        return self.public_user(row)

    def verify_credentials_by_email(self, email: str, password: str) -> dict | None:
        """按账号绑定的找回邮箱校验密码；用于「账号名或邮箱都能登录」。"""
        try:
            normalized = validate_email(email)
        except ValueError:
            return None
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM users WHERE email = ?", (normalized,)).fetchone()
        if row is None or not row["is_active"] or not verify_password(password, row["password_hash"]):
            return None
        return self.public_user(row)

    def authenticate(self, identifier: str, password: str) -> dict | None:
        """登录标识可填账号名，也可填账号绑定的找回邮箱；先按账号名匹配，失败再按邮箱匹配。"""
        user = self.verify_credentials(identifier, password)
        if user is None:
            user = self.verify_credentials_by_email(identifier, password)
        if user is None:
            return None
        with self.connection() as connection:
            connection.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?", (iso(), iso(), user["id"]),
            )
        return self.get_user(user["id"])

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

    def update_user(
        self, user_id: str, *, display_name: str | None = None,
        role: UserRole | None = None, is_active: bool | None = None,
        email: str | None = None, update_email: bool = False,
    ) -> dict:
        updates: dict[str, object] = {"updated_at": iso()}
        if display_name is not None:
            display_name = display_name.strip()
            if not display_name:
                raise ValueError("姓名不能为空")
            updates["display_name"] = display_name
        if role is not None:
            updates["role"] = role.value
        if is_active is not None:
            updates["is_active"] = int(is_active)
        normalized_email: str | None = None
        if update_email:
            normalized_email = validate_email(email) if email else None
            updates["email"] = normalized_email
        assignment = ", ".join(f"{column} = ?" for column in updates)
        with self.connection() as connection:
            # Check-then-act must share the write transaction: SQLite serializes
            # writers via BEGIN IMMEDIATE; MySQL locking reads observe the latest
            # committed rows, so two concurrent demotions cannot both pass.
            if self._db.dialect == "sqlite":
                connection.execute("BEGIN IMMEDIATE")
            target = connection.execute(
                "SELECT role FROM users WHERE id = ?", (user_id,), for_update=True,
            ).fetchone()
            if target is None:
                raise KeyError(user_id)
            if normalized_email and self._email_taken(connection, normalized_email, exclude_user_id=user_id):
                raise ValueError("该邮箱已被其他账号使用")
            removes_active_super_admin = (
                str(target["role"]) == UserRole.SUPER_ADMIN.value
                and ((role is not None and role is not UserRole.SUPER_ADMIN) or is_active is False)
            )
            if removes_active_super_admin:
                remaining = connection.execute(
                    "SELECT COUNT(*) AS total FROM users WHERE role = ? AND is_active = 1 AND id != ?",
                    (UserRole.SUPER_ADMIN.value, user_id), for_update=True,
                ).fetchone()
                if int(remaining["total"]) < 1:
                    raise LastSuperAdminError("不能停用或降级最后一个超级管理员")
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

    # -- 邮箱找回密码：一次性验证码 -------------------------------------------

    def set_password_reset_code(self, user_id: str, code: str, ttl_minutes: int = RESET_CODE_TTL_MINUTES) -> None:
        """Store a hashed one-time reset code, replacing any previous code for the account."""
        timestamp = now()
        expires_at = timestamp + timedelta(minutes=ttl_minutes)
        with self.connection() as connection:
            if connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                raise KeyError(user_id)
            connection.execute(
                "DELETE FROM password_reset_codes WHERE user_id = ?", (user_id,),
            )
            connection.execute(
                """INSERT INTO password_reset_codes (
                    user_id, code_hash, expires_at, attempts, created_at, updated_at
                ) VALUES (?, ?, ?, 0, ?, ?)""",
                (user_id, hash_secret(code), iso(expires_at), iso(timestamp), iso(timestamp)),
            )

    def consume_password_reset_code(self, user_id: str, code: str) -> bool:
        """Verify and consume the code. Expired or over-attempted codes are dropped."""
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM password_reset_codes WHERE user_id = ?", (user_id,),
            ).fetchone()
            if row is None:
                return False
            try:
                expires_at = datetime.fromisoformat(str(row["expires_at"]))
            except ValueError:
                expires_at = now()
            if expires_at <= now() or int(row["attempts"]) >= RESET_CODE_MAX_ATTEMPTS:
                connection.execute("DELETE FROM password_reset_codes WHERE user_id = ?", (user_id,))
                return False
            if not verify_secret(code, str(row["code_hash"])):
                connection.execute(
                    "UPDATE password_reset_codes SET attempts = attempts + 1, updated_at = ? WHERE user_id = ?",
                    (iso(), user_id),
                )
                return False
            connection.execute("DELETE FROM password_reset_codes WHERE user_id = ?", (user_id,))
        return True

    def clear_password_reset_code(self, user_id: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM password_reset_codes WHERE user_id = ?", (user_id,))

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
