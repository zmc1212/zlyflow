from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = WORKSPACE_DIR / ".env"

# 加载根目录 .env 文件
if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=True)
else:
    load_dotenv(override=True)


def get_mysql_config() -> dict[str, Any]:
    """从 .env 环境变量中读取 MySQL 连接配置."""
    return {
        "host": os.getenv("MYSQL_HOST", "192.168.10.125").strip(),
        "port": int(os.getenv("MYSQL_PORT", "3306").strip()),
        "database": os.getenv("MYSQL_DATABASE", "media22").strip(),
        "user": os.getenv("MYSQL_USER", "root").strip(),
        "password": os.getenv("MYSQL_PASSWORD", "123456").strip(),
    }


def get_redis_config() -> dict[str, Any]:
    """从 .env 环境变量中读取 Redis 缓存配置."""
    return {
        "host": os.getenv("REDIS_HOST", "192.168.10.125").strip(),
        "port": int(os.getenv("REDIS_PORT", "6389").strip()),
        "database": int(os.getenv("REDIS_DB", "3").strip()),
        "password": os.getenv("REDIS_PASSWORD", "123456").strip(),
    }


def ensure_credential_key(key_path: Path) -> str:
    """确保本地凭证密钥文件存在并返回密钥."""
    env_key = os.getenv("APP_CREDENTIAL_KEY") or os.getenv("ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY")
    if env_key:
        return env_key.strip()
    if key_path.exists():
        return key_path.read_text(encoding="ascii").strip()
    from cryptography.fernet import Fernet
    generated = Fernet.generate_key().decode("ascii")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(generated, encoding="ascii")
    return generated


@dataclass(frozen=True)
class Settings:
    workspace_dir: Path = WORKSPACE_DIR
    data_dir: Path = WORKSPACE_DIR / "server" / "data"

    @property
    def credential_key(self) -> str:
        key_path = self.data_dir / "credential.key"
        return ensure_credential_key(key_path)

    @property
    def mysql_config(self) -> dict[str, Any]:
        return get_mysql_config()

    @property
    def redis_config(self) -> dict[str, Any]:
        return get_redis_config()


settings = Settings()
