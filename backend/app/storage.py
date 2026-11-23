from __future__ import annotations

import json
import math
import shutil
import threading
import uuid
from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .grs_catalog import (

    builtin_catalog_records,
    builtin_entry,
    catalog_record,
    split_model_list,
    validate_provider_model,
    workflow_id_for,
)
from .cloud_video.base import cloud_video_provider_defaults
from .config import settings
from .db import Database, DbConnection, IntegrityError, Row, open_database
from .models import MAX_CREDIT_AMOUNT, JobMode, JobStatus


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED.value,
    JobStatus.FAILED.value,
    JobStatus.INTERRUPTED.value,
    JobStatus.CANCELLED.value,
}

FINISHED_STATUSES = TERMINAL_STATUSES | {JobStatus.PARTIAL.value}

CANCELABLE_STATUSES = {
    JobStatus.QUEUED.value,
    JobStatus.RUNNING.value,
    JobStatus.AWAITING_REFINE.value,
    JobStatus.INTERRUPTED.value,
}

ACTIVE_STATUSES = {
    JobStatus.QUEUED.value,
    JobStatus.RUNNING.value,
}

RETRYABLE_GENERATION_STATUSES = {JobStatus.FAILED.value, JobStatus.INTERRUPTED.value, JobStatus.CANCELLED.value}


@dataclass(frozen=True)
class JobCreditQuote:
    total: int
    per_item: int
    price_key: str | None
    reason: str | None

# GPT Image 2.5 系列（默认启用并作为默认生图模型，见 GRS_GPT_IMAGE_25_MIGRATION）。
GPT_IMAGE_25_PROVIDER_MODELS = ("gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst")
GPT_IMAGE_25_DEFAULT_PROVIDER_MODEL = "gpt-image-2.5"


class DirectorProjectConflictError(RuntimeError):
    """Raised when a creative update targets an obsolete content revision."""

    def __init__(self, current_project: dict[str, Any]) -> None:
        super().__init__("导演工程已在其他窗口更新")
        self.current_project = current_project


class CreditInsufficientError(ValueError):
    """积分余额不足；调用方负责映射为 HTTP 402 并提示管理员充值。"""

    def __init__(self, balance: int, required: int) -> None:
        super().__init__(f"积分不足：本次需要 {required} 积分，当前余额 {balance} 积分，请联系管理员充值")
        self.balance = balance
        self.required = required


class EnterpriseMemberQuotaExceededError(CreditInsufficientError):
    """企业成员额度不足；继承余额不足异常以复用既有 HTTP 402 处理路径。"""

    def __init__(self, *, limit: int, used: int, required: int, period: str) -> None:
        self.limit = int(limit)
        self.used = int(used)
        self.required = int(required)
        self.period = period
        # 余额语义映射为「剩余可用额度」，便于上层按余额不足展示。
        self.balance = max(0, self.limit - self.used)
        label = {"monthly": "本月", "total": "累计"}.get(period, "")
        ValueError.__init__(
            self,
            f"{label}企业分配额度不足：上限 {self.limit} 积分，已用 {self.used} 积分，"
            f"本次需要 {self.required} 积分，请联系企业管理员调整额度",
        )


class CreditWalletConflictError(ValueError):
    """The wallet or an adjustment changed since the admin opened it."""


class CreditPriceConflictError(ValueError):
    """The published price has changed since the admin started editing."""


def elapsed_ms_between(created_at: str | None, finished_at: str | None) -> int | None:
    if not created_at or not finished_at:
        return None
    try:
        start = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


class JobStore:
    """Persistence for task aggregates, rounds, generation items and providers.

    The original flat columns on ``jobs`` remain the compatibility mirror of the
    latest round. New code writes normalized rows first and refreshes the mirror.
    Production uses MySQL; unittest isolation uses a local SQLite file.
    """

    MIGRATION_NAME = "2026-08-13-ai-studio-rounds-v1"
    GRS_CATALOG_MIGRATION = "2026-08-25-grs-image-models-v1"
    # v2：首次上线期间一个热重载进程加载了中间态代码，把 v1 标记写入但未插入模型行，
    # v2 让所有库完整重放一次（补插、启用、切默认），并修复 is_default 被清空的状态。
    GRS_GPT_IMAGE_25_MIGRATION = "2026-11-04-grs-gpt-image-25-default-v2"
    DIRECTOR_PROJECTS_MIGRATION = "2026-08-26-director-projects-v1"
    DIRECTOR_LIBRARY_MIGRATION = "2026-08-28-director-library-assets-v1"
    DIRECTOR_CONCURRENCY_MIGRATION = "2026-08-30-director-concurrency-v2"
    DIRECTOR_OPERATIONS_MIGRATION = "2026-08-30-director-operations-v1"

    def __init__(self, database: Database | Path) -> None:
        self._db = open_database(database)
        self.database_path = getattr(self._db, "path", None)
        self._backup_before_migration()
        self.initialize()
        self._grs_model_cache: dict[str, dict[str, Any] | None] = {}
        self._comfy_settings_cache: dict[str, Any] | None = None
        self._content_epoch = 0
        self._content_epoch_lock = threading.Lock()

    def _backup_before_migration(self) -> None:
        path = self.database_path
        if path is None or not path.exists() or path.stat().st_size == 0:
            return
        backup = path.with_name(f"{path.name}.pre-ai-studio-migration.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        concurrency_backup = path.with_name(f"{path.name}.pre-director-concurrency-v2.bak")
        if not concurrency_backup.exists():
            shutil.copy2(path, concurrency_backup)

    def connection(self) -> DbConnection:
        return self._db.connection()

    def _ensure_column(self, connection: DbConnection, table: str, name: str, declaration: str) -> None:
        self._db.ensure_column(connection, table, name, declaration)

    def _ensure_unique_index(self, connection: DbConnection, table: str, name: str, columns: str) -> None:
        if self._db.index_exists(connection, table, name):
            return
        connection.execute(f"CREATE UNIQUE INDEX {name} ON {table} ({columns})")

    def initialize(self) -> None:
        with self.connection() as connection:
            if self._db.dialect == "mysql":
                self._db.apply_mysql_schema(connection)
                self._ensure_column(connection, "canvas_projects", "tags_json", "VARCHAR(512) NOT NULL DEFAULT '[]'")
                self._ensure_column(connection, "canvas_projects", "is_favorite", "INTEGER NOT NULL DEFAULT 0")
                self._ensure_column(connection, "canvas_projects", "deleted_at", "VARCHAR(64) NULL")
                self._ensure_column(connection, "canvas_projects", "preview_json", "TEXT NULL")
                self._ensure_column(connection, "canvas_projects", "linked_director_project_id", "VARCHAR(64) NULL")
                self._ensure_unique_index(
                    connection, "canvas_projects", "uk_canvas_projects_linked", "owner_user_id, linked_director_project_id",
                )
                self._ensure_column(connection, "llm_provider_settings", "assistant_models_json", "TEXT")
                self._ensure_column(connection, "generation_items", "refine_state_json", "LONGTEXT NULL")
                self._ensure_column(connection, "job_rounds", "display_prompt", "LONGTEXT NULL")
                self._ensure_job_list_indexes(connection)
                self._ensure_column(
                    connection,
                    "vlm_provider_settings",
                    "use_llm_credentials",
                    "TINYINT(1) NOT NULL DEFAULT 0",
                )
                self._ensure_column(connection, "music_jobs", "chat_id", "VARCHAR(64) NULL")
                self._ensure_column(connection, "generation_items", "credits_billed", "INTEGER NULL")
                self._ensure_column(connection, "generation_items", "credits_settled", "INTEGER NOT NULL DEFAULT 0")
                self._ensure_column(connection, "generation_items", "credits_wallet_enterprise_id", "VARCHAR(64) NULL")
                self._ensure_column(connection, "credit_transactions", "meta_json", "LONGTEXT NULL")
                self._ensure_column(connection, "enterprise_credit_transactions", "meta_json", "LONGTEXT NULL")
                self._ensure_column(connection, "enterprises", "parent_id", "VARCHAR(64) NULL")
                self._seed_runtime_defaults(connection, migrate_legacy=False)
                return
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    prompt TEXT NOT NULL,
                    negative_prompt TEXT NOT NULL DEFAULT '',
                    image_size TEXT,
                    options_json TEXT NOT NULL DEFAULT '{}',
                    submitted_options_json TEXT NOT NULL DEFAULT '{}',
                    options_submitted INTEGER NOT NULL DEFAULT 0,
                    comfy_prompt_id TEXT,
                    comfy_client_id TEXT,
                    comfy_phase TEXT,
                    references_json TEXT NOT NULL,
                    outputs_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            additions = {
                "owner_user_id": "TEXT",
                "options_json": "TEXT NOT NULL DEFAULT '{}'",
                "submitted_options_json": "TEXT NOT NULL DEFAULT '{}'",
                "options_submitted": "INTEGER NOT NULL DEFAULT 0",
                "progress": "INTEGER NOT NULL DEFAULT 0",
                "comfy_prompt_id": "TEXT",
                "comfy_client_id": "TEXT",
                "comfy_phase": "TEXT",
                "media_type": "TEXT NOT NULL DEFAULT 'video'",
                "title": "TEXT",
                "pinned": "INTEGER NOT NULL DEFAULT 0",
                "last_round_id": "TEXT",
                "source_job_id": "TEXT",
                "source_generation_item_id": "TEXT",
                "source_output_index": "INTEGER",
                "legacy_read_only": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, declaration in additions.items():
                self._ensure_column(connection, "jobs", name, declaration)

            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_rounds (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    prompt TEXT NOT NULL,
                    display_prompt TEXT,
                    negative_prompt TEXT NOT NULL DEFAULT '',
                    image_size TEXT,
                    options_json TEXT NOT NULL DEFAULT '{}',
                    submitted_options_json TEXT NOT NULL DEFAULT '{}',
                    options_submitted INTEGER NOT NULL DEFAULT 0,
                    references_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(job_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS generation_items (
                    id TEXT PRIMARY KEY,
                    round_id TEXT NOT NULL REFERENCES job_rounds(id) ON DELETE CASCADE,
                    item_index INTEGER NOT NULL,
                    executor TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    remote_task_id TEXT,
                    remote_status TEXT,
                    comfy_prompt_id TEXT,
                    comfy_client_id TEXT,
                    comfy_phase TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    outputs_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(round_id, item_index)
                );

                CREATE TABLE IF NOT EXISTS grs_provider_settings (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    base_url TEXT NOT NULL DEFAULT 'https://grsai.dakka.com.cn',
                    api_key_encrypted TEXT,
                    gpt_image_2_enabled INTEGER NOT NULL DEFAULT 1,
                    gpt_image_2_vip_enabled INTEGER NOT NULL DEFAULT 1,
                    models TEXT NOT NULL DEFAULT 'gpt-image-2',
                    vip_models TEXT NOT NULL DEFAULT 'gpt-image-2-vip',
                    last_test_status TEXT,
                    last_test_message TEXT,
                    last_test_at TEXT,
                    last_balance REAL,
                    last_balance_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS qiniu_provider_settings (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    access_key_encrypted TEXT,
                    secret_key_encrypted TEXT,
                    bucket TEXT NOT NULL DEFAULT '',
                    region TEXT NOT NULL DEFAULT 'z0',
                    domain TEXT NOT NULL DEFAULT '',
                    object_prefix TEXT NOT NULL DEFAULT 'zly-ai-video-studio/',
                    last_test_status TEXT,
                    last_test_message TEXT,
                    last_test_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS llm_provider_settings (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    base_url TEXT NOT NULL DEFAULT 'https://api-inference.modelscope.cn/v1',
                    api_key_encrypted TEXT,
                    model TEXT NOT NULL DEFAULT 'Qwen/Qwen2.5-Coder-32B-Instruct',
                    last_test_status TEXT,
                    last_test_message TEXT,
                    last_test_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS llm_endpoint_credentials (
                    base_url TEXT PRIMARY KEY,
                    api_key_encrypted TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS vlm_provider_settings (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    use_llm_credentials INTEGER NOT NULL DEFAULT 0,
                    base_url TEXT NOT NULL DEFAULT 'https://open.bigmodel.cn/api/paas/v4',
                    api_key_encrypted TEXT,
                    model TEXT NOT NULL DEFAULT 'glm-4v-flash',
                    last_test_status TEXT,
                    last_test_message TEXT,
                    last_test_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS comfy_provider_settings (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    base_url TEXT NOT NULL DEFAULT 'http://127.0.0.1:8188',
                    last_test_status TEXT,
                    last_test_message TEXT,
                    last_test_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tts_provider_settings (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    use_llm_credentials INTEGER NOT NULL DEFAULT 1,
                    base_url TEXT NOT NULL DEFAULT '',
                    api_key_encrypted TEXT,
                    model TEXT NOT NULL DEFAULT 'tts-1',
                    voice TEXT NOT NULL DEFAULT 'alloy',
                    last_test_status TEXT,
                    last_test_message TEXT,
                    last_test_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS music_provider_settings (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    base_url TEXT NOT NULL DEFAULT 'http://192.168.10.54:8791',
                    access_key_encrypted TEXT,
                    last_test_status TEXT,
                    last_test_message TEXT,
                    last_test_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cloud_video_provider_settings (
                    provider_key TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    base_url TEXT,
                    api_key_encrypted TEXT,
                    api_secret_encrypted TEXT,
                    extra_config_json TEXT,
                    last_test_status TEXT,
                    last_test_message TEXT,
                    last_test_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mail_provider_settings (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    host TEXT NOT NULL DEFAULT '',
                    port INTEGER NOT NULL DEFAULT 465,
                    security TEXT NOT NULL DEFAULT 'ssl',
                    username TEXT NOT NULL DEFAULT '',
                    password_encrypted TEXT,
                    from_address TEXT NOT NULL DEFAULT '',
                    from_name TEXT NOT NULL DEFAULT 'ZLY AI Studio',
                    last_test_status TEXT,
                    last_test_message TEXT,
                    last_test_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS music_jobs (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    style TEXT NOT NULL,
                    lyrics TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER NOT NULL DEFAULT 0,
                    params_json TEXT,
                    result_url TEXT,
                    result_format TEXT,
                    cover_url TEXT,
                    duration_seconds INTEGER,
                    remote_job_id TEXT,
                    remote_song_id TEXT,
                    error_message TEXT,
                    chat_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_music_jobs_owner_created ON music_jobs(owner_user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS music_job_lyrics (
                    job_id TEXT PRIMARY KEY REFERENCES music_jobs(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    claim_token TEXT,
                    lease_until INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT
                );

                CREATE TABLE IF NOT EXISTS music_chats (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '新对话',
                    anchor_job_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_music_chats_owner ON music_chats(owner_user_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS music_chat_messages (
                    id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL REFERENCES music_chats(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    proposal_json TEXT,
                    job_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_music_chat_messages_chat ON music_chat_messages(chat_id, created_at);

                CREATE TABLE IF NOT EXISTS director_projects (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    source_script TEXT NOT NULL DEFAULT '',
                    style_vibe TEXT,
                    requested_shot_count INTEGER,
                    payload_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    content_revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_owner_created ON jobs(owner_user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_pinned_created ON jobs(pinned, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_owner_pinned_created ON jobs(owner_user_id, pinned, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_rounds_job_sequence ON job_rounds(job_id, sequence DESC);
                CREATE INDEX IF NOT EXISTS idx_items_round_index ON generation_items(round_id, item_index);
                CREATE INDEX IF NOT EXISTS idx_items_remote_task ON generation_items(remote_task_id);
                CREATE INDEX IF NOT EXISTS idx_director_projects_owner_updated
                    ON director_projects(owner_user_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS director_library_assets (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    prompt_text TEXT NOT NULL DEFAULT '',
                    gender TEXT NOT NULL DEFAULT '',
                    image_url TEXT,
                    image_job_id TEXT,
                    image_path TEXT,
                    source_project_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_director_library_assets_owner_kind
                    ON director_library_assets(owner_user_id, kind, updated_at DESC);

                CREATE TABLE IF NOT EXISTS director_operations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES director_projects(id) ON DELETE CASCADE,
                    owner_user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    request_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_director_operations_project_updated
                    ON director_operations(project_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_director_operations_owner_status
                    ON director_operations(owner_user_id, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS canvas_projects (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    linked_director_project_id TEXT,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    deleted_at TEXT,
                    preview_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_canvas_projects_owner_updated
                    ON canvas_projects(owner_user_id, updated_at);

                CREATE TABLE IF NOT EXISTS canvas_drafts (
                    canvas_id TEXT PRIMARY KEY REFERENCES canvas_projects(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL DEFAULT 1,
                    checksum TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    node_count INTEGER NOT NULL DEFAULT 0,
                    updated_by TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS canvas_draft_versions (
                    id TEXT PRIMARY KEY,
                    canvas_id TEXT NOT NULL REFERENCES canvas_projects(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    checksum TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    node_count INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(canvas_id, version)
                );

                CREATE TABLE IF NOT EXISTS ai_featured_works (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    cover_url TEXT,
                    snapshot_json TEXT NOT NULL,
                    episode_count INTEGER NOT NULL DEFAULT 0,
                    shot_count INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'published',
                    published_by TEXT,
                    published_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_featured_status_order
                    ON ai_featured_works(status, sort_order, published_at);

                CREATE TABLE IF NOT EXISTS ai_featured_music (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL UNIQUE,
                    owner_user_id TEXT,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    style TEXT NOT NULL,
                    lyrics TEXT NOT NULL,
                    result_url TEXT NOT NULL,
                    cover_url TEXT,
                    duration_seconds INTEGER,
                    result_format TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'published',
                    published_by TEXT,
                    published_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_featured_music_status_order
                    ON ai_featured_music(status, sort_order, published_at);

                CREATE TABLE IF NOT EXISTS ai_showcase_items (
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL DEFAULT 'general',
                    title TEXT NOT NULL,
                    blurb TEXT NOT NULL DEFAULT '',
                    origin TEXT NOT NULL DEFAULT 'local',
                    mode TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    display_prompt TEXT NOT NULL DEFAULT '',
                    negative_prompt TEXT NOT NULL DEFAULT '',
                    image_size TEXT,
                    options_json TEXT,
                    references_json TEXT,
                    tags_json TEXT,
                    cover_url TEXT,
                    media_url TEXT,
                    media_type TEXT NOT NULL DEFAULT 'video',
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    source_job_id TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'published',
                    published_by TEXT,
                    published_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_showcase_status_category
                    ON ai_showcase_items(status, category, sort_order);
                CREATE INDEX IF NOT EXISTS idx_showcase_source_job
                    ON ai_showcase_items(source_job_id);

                CREATE TABLE IF NOT EXISTS credit_accounts (
                    user_id TEXT PRIMARY KEY,
                    balance INTEGER NOT NULL DEFAULT 0,
                    total_recharged INTEGER NOT NULL DEFAULT 0,
                    total_consumed INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS credit_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    delta INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    reason TEXT,
                    price_key TEXT,
                    ref_type TEXT,
                    ref_id TEXT,
                    balance_after INTEGER NOT NULL,
                    actor_user_id TEXT,
                    meta_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_credit_tx_user_created ON credit_transactions(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_credit_tx_ref ON credit_transactions(ref_type, ref_id);

                CREATE TABLE IF NOT EXISTS credit_price_rules (
                    rule_key TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    pricing_kind TEXT NOT NULL,
                    unit_credits INTEGER NOT NULL DEFAULT 0,
                    unit_by_variant TEXT,
                    extra_config TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    note TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS enterprises (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    code TEXT,
                    parent_id TEXT,
                    contact_name TEXT,
                    contact_phone TEXT,
                    notes TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(code)
                );

                CREATE TABLE IF NOT EXISTS enterprise_credit_accounts (
                    enterprise_id TEXT PRIMARY KEY,
                    balance INTEGER NOT NULL DEFAULT 0,
                    total_recharged INTEGER NOT NULL DEFAULT 0,
                    total_consumed INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS enterprise_credit_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    enterprise_id TEXT NOT NULL,
                    user_id TEXT,
                    delta INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    reason TEXT,
                    price_key TEXT,
                    ref_type TEXT,
                    ref_id TEXT,
                    balance_after INTEGER NOT NULL,
                    actor_user_id TEXT,
                    meta_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ent_credit_tx_created ON enterprise_credit_transactions(enterprise_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_ent_credit_tx_user ON enterprise_credit_transactions(enterprise_id, user_id);

                CREATE TABLE IF NOT EXISTS enterprise_model_policies (
                    enterprise_id TEXT NOT NULL,
                    model_kind TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'all',
                    models_json TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (enterprise_id, model_kind)
                );

                CREATE TABLE IF NOT EXISTS enterprise_member_quotas (
                    enterprise_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    period TEXT NOT NULL DEFAULT 'none',
                    credit_limit INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (enterprise_id, user_id)
                );
                """
            )
            self._ensure_column(connection, "canvas_projects", "tags_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "canvas_projects", "is_favorite", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "canvas_projects", "deleted_at", "TEXT")
            self._ensure_column(connection, "canvas_projects", "preview_json", "TEXT")
            self._ensure_column(connection, "enterprises", "parent_id", "TEXT")
            self._ensure_column(connection, "canvas_projects", "linked_director_project_id", "TEXT")
            self._ensure_unique_index(
                connection, "canvas_projects", "uk_canvas_projects_linked", "owner_user_id, linked_director_project_id",
            )
            self._ensure_column(connection, "director_projects", "revision", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(connection, "director_projects", "content_revision", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(connection, "generation_items", "cancel_requested", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "generation_items", "refine_state_json", "TEXT")
            self._ensure_column(connection, "generation_items", "credits_billed", "INTEGER")
            self._ensure_column(connection, "generation_items", "credits_settled", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "generation_items", "credits_wallet_enterprise_id", "TEXT")
            self._ensure_column(connection, "credit_transactions", "meta_json", "TEXT")
            self._ensure_column(connection, "enterprise_credit_transactions", "meta_json", "TEXT")
            self._ensure_column(connection, "job_rounds", "display_prompt", "TEXT")
            for table in ("jobs", "job_rounds", "generation_items"):
                self._ensure_column(connection, table, "finished_at", "TEXT")
                self._ensure_column(connection, table, "execution_elapsed_ms", "INTEGER")
            self._ensure_column(connection, "grs_provider_settings", "models", "TEXT NOT NULL DEFAULT 'gpt-image-2'")
            self._ensure_column(connection, "grs_provider_settings", "vip_models", "TEXT NOT NULL DEFAULT 'gpt-image-2-vip'")
            self._ensure_column(connection, "llm_provider_settings", "assistant_models_json", "TEXT")
            self._ensure_column(
                connection,
                "vlm_provider_settings",
                "use_llm_credentials",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(connection, "music_jobs", "chat_id", "TEXT")
            self._ensure_job_list_indexes(connection)
            self._seed_runtime_defaults(connection, migrate_legacy=True)

    def _seed_runtime_defaults(self, connection: DbConnection, *, migrate_legacy: bool) -> None:
        connection.execute(
            """INSERT OR IGNORE INTO grs_provider_settings
            (id, enabled, base_url, gpt_image_2_enabled, gpt_image_2_vip_enabled, models, vip_models, updated_at)
            VALUES (1, 0, 'https://grsai.dakka.com.cn', 1, 1, 'gpt-image-2', 'gpt-image-2-vip', ?)""",
            (now(),),
        )
        connection.execute(
            """INSERT OR IGNORE INTO qiniu_provider_settings
            (id, enabled, bucket, region, domain, object_prefix, updated_at)
            VALUES (1, 0, '', 'z0', '', 'zly-ai-video-studio/', ?)""",
            (now(),),
        )
        connection.execute(
            """INSERT OR IGNORE INTO llm_provider_settings
            (id, enabled, base_url, model, updated_at)
            VALUES (1, 0, 'https://api-inference.modelscope.cn/v1', 'Qwen/Qwen2.5-72B-Instruct', ?)""",
            (now(),),
        )
        connection.execute(
            """INSERT OR IGNORE INTO vlm_provider_settings
            (id, enabled, base_url, model, updated_at)
            VALUES (1, 0, 'https://open.bigmodel.cn/api/paas/v4', 'glm-4v-flash', ?)""",
            (now(),),
        )
        connection.execute(
            """INSERT OR IGNORE INTO comfy_provider_settings
            (id, base_url, updated_at)
            VALUES (1, ?, ?)""",
            (settings.comfy_url, now()),
        )
        connection.execute(
            """INSERT OR IGNORE INTO tts_provider_settings
            (id, enabled, use_llm_credentials, base_url, model, voice, updated_at)
            VALUES (1, 0, 1, '', 'tts-1', 'alloy', ?)""",
            (now(),),
        )
        connection.execute(
            """INSERT OR IGNORE INTO music_provider_settings
            (id, base_url, updated_at)
            VALUES (1, ?, ?)""",
            (settings.music_url, now()),
        )
        connection.execute(
            """INSERT OR IGNORE INTO mail_provider_settings
            (id, enabled, host, port, security, username, from_address, from_name, updated_at)
            VALUES (1, 0, '', 465, 'ssl', '', '', 'ZLY AI Studio', ?)""",
            (now(),),
        )
        if migrate_legacy:
            self._migrate_legacy_jobs(connection)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES (?, ?)",
            (self.MIGRATION_NAME, now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES (?, ?)",
            (self.DIRECTOR_PROJECTS_MIGRATION, now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES (?, ?)",
            (self.DIRECTOR_LIBRARY_MIGRATION, now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES (?, ?)",
            (self.DIRECTOR_CONCURRENCY_MIGRATION, now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES (?, ?)",
            (self.DIRECTOR_OPERATIONS_MIGRATION, now()),
        )
        self._ensure_grs_image_models(connection)
        self._seed_credit_price_rules(connection)

    def _seed_credit_price_rules(self, connection: DbConnection) -> None:
        """积分价格表种子：对标 2026 市场价初始化，管理端可随时覆盖（INSERT OR IGNORE 不覆盖已改动行）。"""
        timestamp = now()

        def native_config(native_prices: dict[str, float]) -> dict[str, Any]:
            """上游原生价 + 换算系数；平台价 = ceil(原生价 × 100 × 系数)。"""
            return {
                "native_unit": "rmb_per_second",
                "native_variant_prices": dict(native_prices),
                "credits_per_native_unit": 100,
                "provider_coefficient": 1.0,
                "price_source": "native",
            }

        grs_native = native_config({"480p": 0.05, "768p": 0.07, "1080p": 0.15})
        # GRS 官方模型列表只公布按秒价，未公布输入图片价：显式配成 0（免费），
        # 管理端可在「换算」里改成实际单价后自动计入预扣。
        grs_native["input_image_price"] = {"minimax-h3": 0.0}
        grs_native["input_image_free_quota"] = 5
        grs_note = (
            "GRS 成本直换（上游 ¥0.05/0.07/0.15 每秒 × 100）；"
            "输入图片暂按免费（官方未公布图片价，管理端可改）；"
            "加差价直接改供应商系数或分档单价"
        )
        grs_agnes_native = native_config({"720p": 0.10, "1080p": 0.17, "2k": 0.23})
        grs_agnes_native["input_image_price"] = {"agnes-video-2.5": 0.0}
        grs_agnes_native["input_image_free_quota"] = 5
        grs_agnes_note = (
            "GRS Agnes 2.5 成本直换（上游 ¥0.10/0.17/0.23 每秒 = 2000/3400/4600 积分 ÷ 20000 积分每元）；"
            "参考图前 5 张免费（官方未公布图片价，管理端可改）；加差价直接改供应商系数或分档单价"
        )
        grs_wan_native = native_config({"480p": 0.135, "720p": 0.27, "1080p": 0.54})
        grs_wan_native["input_image_price"] = {"wan-3.0": 0.0}
        grs_wan_native["input_image_free_quota"] = 5
        grs_wan_note = (
            "GRS Wan 3.0 成本直换（上游 ¥0.135/0.27/0.54 每秒 = 2700/5400/10800 积分 ÷ 20000 积分每元）；"
            "参考图前 5 张免费（官方未公布图片价，管理端可改）；加差价直接改供应商系数或分档单价"
        )
        cloud_rules = [
            ("cloud-kling-t2v", {"std": 40, "pro": 80}, None, None),
            ("cloud-kling-i2v", {"std": 40, "pro": 80}, None, None),
            ("cloud-seedance-t2v", {"480p": 20, "720p": 50, "1080p": 90}, None, None),
            ("cloud-seedance-i2v", {"480p": 20, "720p": 50, "1080p": 90}, None, None),
            ("cloud-hailuo-t2v", {"768P": 40, "1080P": 80}, None, None),
            ("cloud-hailuo-i2v", {"768P": 40, "1080P": 80}, None, None),
            ("cloud-scnet-h3-t2v", {"768P": 50, "2K": 100}, None, None),
            ("cloud-scnet-h3-i2v", {"768P": 50, "2K": 100}, None, None),
            ("cloud-scnet-seedance-t2v", {"480p": 20, "720p": 60, "1080p": 100}, None, None),
            ("cloud-scnet-seedance-i2v", {"480p": 20, "720p": 60, "1080p": 100}, None, None),
            ("cloud-scnet-happyhorse-t2v", {"720p": 40, "1080p": 80}, None, None),
            (
                "cloud-grs-h3-t2v",
                {"480p": 5, "768p": 7, "1080p": 15},
                grs_note,
                grs_native,
            ),
            (
                "cloud-grs-h3-r2v",
                {"480p": 5, "768p": 7, "1080p": 15},
                grs_note,
                grs_native,
            ),
            (
                "cloud-grs-h3-fl2v",
                {"480p": 5, "768p": 7, "1080p": 15},
                grs_note,
                grs_native,
            ),
            *(
                (
                    f"cloud-grs-agnes-{kind}",
                    {"720p": 10, "1080p": 17, "2k": 23},
                    grs_agnes_note,
                    grs_agnes_native,
                )
                for kind in ("t2v", "i2v", "fl2v", "r2v")
            ),
            *(
                (
                    f"cloud-grs-wan-{kind}",
                    {"480p": 14, "720p": 27, "1080p": 54},
                    grs_wan_note,
                    grs_wan_native,
                )
                for kind in ("t2v", "i2v", "fl2v", "r2v")
            ),
        ]
        # MiniMax 官方平台（platform.minimax.cn）：积分按「模型档位:分辨率」分档，官方成本直换。
        minimax_variants = {
            "MiniMax-H3-Lite:480P": 16,
            "MiniMax-H3-Lite:768P": 26,
            "MiniMax-H3-Highspeed:480P": 26,
            "MiniMax-H3-Highspeed:768P": 40,
            "MiniMax-H3:768P": 50,
            "MiniMax-H3:2K": 80,
            "MiniMax-H3-Max:480P": 33,
            "MiniMax-H3-Max:768P": 50,
        }
        minimax_native = native_config({
            "MiniMax-H3-Lite:480P": 0.16,
            "MiniMax-H3-Lite:768P": 0.26,
            "MiniMax-H3-Highspeed:480P": 0.26,
            "MiniMax-H3-Highspeed:768P": 0.40,
            "MiniMax-H3:768P": 0.50,
            "MiniMax-H3:2K": 0.80,
            "MiniMax-H3-Max:480P": 0.33,
            "MiniMax-H3-Max:768P": 0.50,
        })
        minimax_native["input_image_price"] = {
            "MiniMax-H3": 0.20,
            "MiniMax-H3-Highspeed": 0.20,
            "MiniMax-H3-Lite": 0.13,
            # 官方截图未单列 H3-Max，按 H3 同价兜底，后续可单独调整。
            "MiniMax-H3-Max": 0.20,
        }
        minimax_native["input_image_free_quota"] = 5
        minimax_note = (
            "MiniMax 官方成本直换（100 积分 = 1 元：Lite ¥0.16/¥0.26、Highspeed ¥0.26/¥0.40、"
            "H3 ¥0.50/2K ¥0.80、H3-Max ¥0.33/¥0.50 每秒）；H3 旗舰档仅 768P/2K；"
            "参考图每任务前 5 张免费，超出后 H3/Highspeed ¥0.20/张、Lite ¥0.13/张（已计入预扣，H3-Max 暂按 H3 同价）；"
            "加差价直接改供应商系数或分档单价"
        )
        cloud_rules.extend(
            (f"cloud-minimax-h3-{kind}", dict(minimax_variants), minimax_note, minimax_native)
            for kind in ("t2v", "i2v", "fl2v", "r2v")
        )
        for workflow_id, variants, note, extra in cloud_rules:
            connection.execute(
                """INSERT OR IGNORE INTO credit_price_rules
                (rule_key, scope, pricing_kind, unit_credits, unit_by_variant, extra_config, enabled, note, updated_at)
                VALUES (?, 'cloud_video', 'per_second', 0, ?, ?, 1, ?, ?)""",
                (
                    f"cloud:{workflow_id}",
                    json.dumps(variants, ensure_ascii=False),
                    json.dumps(extra, ensure_ascii=False) if extra else None,
                    note or "云端视频按秒计费（分档单价）",
                    timestamp,
                ),
            )
        # 旧库回填：已有条目没有 extra_config 时补原生价，但不动管理端已填写的平台单价。
        self._backfill_native_price_config(
            connection,
            {
                **{f"cloud:cloud-grs-h3-{kind}": grs_native for kind in ("t2v", "r2v", "fl2v")},
                **{
                    f"cloud:cloud-grs-agnes-{kind}": grs_agnes_native
                    for kind in ("t2v", "i2v", "fl2v", "r2v")
                },
                **{
                    f"cloud:cloud-grs-wan-{kind}": grs_wan_native
                    for kind in ("t2v", "i2v", "fl2v", "r2v")
                },
                **{
                    f"cloud:cloud-minimax-h3-{kind}": minimax_native
                    for kind in ("t2v", "i2v", "fl2v", "r2v")
                },
            },
        )
        connection.execute(
            """INSERT OR IGNORE INTO credit_price_rules
            (rule_key, scope, pricing_kind, unit_credits, unit_by_variant, extra_config, enabled, note, updated_at)
            VALUES ('grs_image:global', 'grs_image', 'per_item', 0, NULL,
                    ?, 1, '每张 = 上游 credit_cost × 换算系数；model_overrides 可按模型覆盖绝对单价', ?)""",
            (json.dumps({"grs_credits_to_platform": 2.0, "model_overrides": {}}, ensure_ascii=False), timestamp),
        )
        def call_reference(input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> dict[str, Any]:
            """LLM/VLM 成本参考的初始口径：DeepSeek-V4-Flash 公开价 + 典型长度。

            单价来自上游公开价（输入 ¥1 / 缓存命中 ¥0.02 / 输出 ¥4 每百万 tokens），
            tokens 是典型调用长度估算，管理端应按实际模型与真实用量校准。
            """
            return {
                "billing_mode": "per_call",
                "billing_margin": 1.0,
                "min_credits": 1,
                "cost_reference": {
                    "input_per_mtok": 1.0,
                    "cached_input_per_mtok": 0.02,
                    "output_per_mtok": 4.0,
                    "assumed_input_tokens": max(0, input_tokens),
                    "assumed_cached_tokens": max(0, min(cached_tokens, input_tokens)),
                    "assumed_output_tokens": max(0, output_tokens),
                    "provider_coefficient": 1.0,
                    "estimated": True,
                    "model_prices": {},
                    "off_peak": {
                        "enabled": False,
                        "discount": 0.5,
                        "timezone": "Asia/Shanghai",
                        "windows": [{"start": "00:30", "end": "08:30"}],
                    },
                    "reference_note": (
                        "初始参考：按 DeepSeek-V4-Flash 公开价（输入 ¥1 / 缓存 ¥0.02 / 输出 ¥4 每百万 tokens）"
                        "与典型调用长度估算；请按实际模型与用量校准"
                    ),
                },
            }

        llm_rules = [
            ("llm:optimize_prompt", 1, "提示词优化（每次）", call_reference(1500, 600)),
            ("llm:split_script", 3, "剧本拆解（每次）", call_reference(8000, 3000)),
            ("llm:repair_continuity", 2, "连贯性修复（每次）", call_reference(6000, 2000)),
            ("llm:director_plan", 30, "导演台写稿流水线（每次完整方案，含多 Agent 步骤）", call_reference(120000, 30000)),
            ("llm:director_clarify", 1, "导演台创作确认（每次）", call_reference(2000, 400)),
            ("llm:assistant_chat", 1, "导演助手对话（每轮）", call_reference(6000, 800)),
            ("llm:music_chat", 1, "音乐对话（每轮）", call_reference(2000, 500)),
        ]
        for rule_key, unit, note, cost_config in llm_rules:
            connection.execute(
                """INSERT OR IGNORE INTO credit_price_rules
                (rule_key, scope, pricing_kind, unit_credits, unit_by_variant, extra_config, enabled, note, updated_at)
                VALUES (?, 'llm', 'per_call', ?, NULL, ?, 1, ?, ?)""",
                (rule_key, unit, json.dumps(cost_config, ensure_ascii=False), note, timestamp),
            )
        vlm_rules = [
            ("vlm:analyze_subject", 2, "主体分析（每次）", call_reference(2000, 300)),
            ("vlm:reverse_prompt", 2, "反推提示词（每次）", call_reference(2000, 300)),
        ]
        for rule_key, unit, note, cost_config in vlm_rules:
            connection.execute(
                """INSERT OR IGNORE INTO credit_price_rules
                (rule_key, scope, pricing_kind, unit_credits, unit_by_variant, extra_config, enabled, note, updated_at)
                VALUES (?, 'vlm', 'per_call', ?, NULL, ?, 1, ?, ?)""",
                (rule_key, unit, json.dumps(cost_config, ensure_ascii=False), note, timestamp),
            )
        # 旧库回填：只补 extra_config 为空的按次条目，绝不覆盖管理端已保存的成本参考。
        self._backfill_call_cost_reference(
            connection,
            {
                rule_key: cost_config
                for rule_key, _unit, _note, cost_config in [*llm_rules, *vlm_rules]
            },
        )

    @staticmethod
    def _backfill_call_cost_reference(
        connection: DbConnection, defaults: dict[str, dict[str, Any]],
    ) -> None:
        """旧库补 LLM/VLM 成本参考；仅处理 extra_config 为空的历史行。

        管理端一旦保存过 extra_config（含清空成本参考），这里不再覆盖。
        不改 updated_at，避免打断管理端未发布的改价草稿。
        """
        for rule_key, config in defaults.items():
            row = connection.execute(
                "SELECT extra_config, pricing_kind FROM credit_price_rules WHERE rule_key = ?",
                (rule_key,),
            ).fetchone()
            if row is None or row["extra_config"] or row["pricing_kind"] != "per_call":
                continue
            connection.execute(
                "UPDATE credit_price_rules SET extra_config = ? WHERE rule_key = ?",
                (json.dumps(config, ensure_ascii=False), rule_key),
            )

    @staticmethod
    def _backfill_native_price_config(
        connection: DbConnection, defaults: dict[str, dict[str, Any]],
    ) -> None:
        """旧库补原生价配置：只处理 extra_config 为空的行，绝不覆盖管理端已保存的换算设置。

        已有平台单价与「原生价 × 100 × 1.0」一致时标记 native（默认成本直换）；
        不一致时标记 manual，保留运营当前单价，运营可在管理端手动切回原生价换算。
        """
        for rule_key, config in defaults.items():
            row = connection.execute(
                "SELECT extra_config, unit_by_variant FROM credit_price_rules WHERE rule_key = ?",
                (rule_key,),
            ).fetchone()
            if row is None or row["extra_config"]:
                continue
            try:
                stored = json.loads(row["unit_by_variant"]) if row["unit_by_variant"] else {}
            except (TypeError, ValueError):
                stored = {}
            per_unit = float(config.get("credits_per_native_unit") or 0)
            coefficient = float(config.get("provider_coefficient") or 1.0)
            computed = {
                variant: max(0, math.ceil(round(float(price) * per_unit * coefficient, 6)))
                for variant, price in (config.get("native_variant_prices") or {}).items()
            }
            merged = dict(config)
            merged["price_source"] = "native" if stored == computed else "manual"
            connection.execute(
                "UPDATE credit_price_rules SET extra_config = ?, updated_at = ? WHERE rule_key = ?",
                (json.dumps(merged, ensure_ascii=False), now(), rule_key),
            )

    def _ensure_job_list_indexes(self, connection: DbConnection) -> None:
        self._db.ensure_index(connection, "jobs", "idx_jobs_pinned_created", "pinned, created_at")
        self._db.ensure_index(
            connection, "jobs", "idx_jobs_owner_pinned_created", "owner_user_id, pinned, created_at",
        )

    @staticmethod
    def _mode_value(mode: JobMode | str) -> str:
        return mode.value if isinstance(mode, JobMode) else str(mode)

    @staticmethod
    def _media_for_mode(mode: str) -> str:
        # 注册表是工作流能力的唯一来源；无法识别的模式保留旧前缀推断兜底。
        from .workflow_registry import workflow_for
        try:
            return str(workflow_for(mode).media_type) or ("image" if mode.startswith("grs-") else "video")
        except KeyError:
            return "image" if mode == JobMode.IMAGE.value or mode.startswith("grs-") else "video"

    @staticmethod
    def _executor_for_mode(mode: str) -> str:
        # 复合图片工作流（局部重绘/消除笔/扩图）声明 executor=grs；
        # 若只按 grs- 前缀判断会被错路由进 ComfyUI 兜底分支。
        from .workflow_registry import workflow_for
        try:
            return str(workflow_for(mode).executor) or ("grs" if mode.startswith("grs-") else "comfyui")
        except KeyError:
            return "grs" if mode.startswith("grs-") else "comfyui"

    def _ensure_grs_image_models(self, connection: DbConnection) -> None:
        if connection.dialect != "mysql":
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS grs_image_models (
                    workflow_id TEXT PRIMARY KEY,
                    provider_model TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    profile TEXT NOT NULL,
                    resolutions_json TEXT,
                    quality_json TEXT,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 100,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        self._ensure_column(connection, "grs_image_models", "quality_json", "TEXT")
        self._ensure_column(connection, "grs_image_models", "credit_cost", "INTEGER NULL")
        applied = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE name = ?", (self.GRS_CATALOG_MIGRATION,),
        ).fetchone()
        if applied:
            # 既有库不再重新种子，但新增内置模型与默认模型迁移仍要生效。
            self._apply_gpt_image_25_default_migration(connection, now())
            return
        settings_row = connection.execute("SELECT * FROM grs_provider_settings WHERE id = 1").fetchone()
        settings = dict(settings_row) if settings_row else {}
        gpt_enabled = bool(settings.get("gpt_image_2_enabled", 1))
        vip_enabled = bool(settings.get("gpt_image_2_vip_enabled", 1))
        timestamp = now()
        seeded: dict[str, dict[str, Any]] = {}
        for spec in builtin_catalog_records():
            enabled = spec["enabled"]
            if spec["provider_model"] == "gpt-image-2":
                enabled = gpt_enabled
            elif spec["provider_model"] == "gpt-image-2-vip":
                enabled = vip_enabled
            record = {**spec, "enabled": enabled, "is_default": False}
            seeded[record["provider_model"]] = record
        for extra in split_model_list(settings.get("models")):
            if extra == "gpt-image-2":
                continue
            builtin = builtin_entry(provider_model=extra)
            if builtin is not None:
                seeded[extra] = {**builtin, "enabled": gpt_enabled}
                continue
            seeded[extra] = catalog_record(
                {
                    "provider_model": extra,
                    "display_name": extra,
                    "profile": "gpt_image_2",
                    "sort_order": 200,
                },
                enabled=gpt_enabled,
                builtin=False,
            )
        for extra in split_model_list(settings.get("vip_models")):
            if extra == "gpt-image-2-vip":
                continue
            builtin = builtin_entry(provider_model=extra)
            if builtin is not None:
                seeded[extra] = {**builtin, "enabled": vip_enabled}
                continue
            seeded[extra] = catalog_record(
                {
                    "provider_model": extra,
                    "display_name": extra,
                    "profile": "gpt_image_2_vip",
                    "sort_order": 210,
                },
                enabled=vip_enabled,
                builtin=False,
            )
        default_id = (
            "gpt-image-2.5" if seeded.get("gpt-image-2.5", {}).get("enabled")
            else "gpt-image-2" if gpt_enabled
            else next((item["provider_model"] for item in seeded.values() if item["enabled"]), None)
        )
        for record in seeded.values():
            record["is_default"] = record["provider_model"] == default_id
            self._insert_grs_image_model(connection, record, timestamp)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES (?, ?)",
            (self.GRS_CATALOG_MIGRATION, timestamp),
        )

    def _insert_grs_image_model(
        self, connection: DbConnection, record: dict[str, Any], timestamp: str,
    ) -> None:
        resolutions = record.get("resolutions")
        quality_options = record.get("quality_options")
        quality_json = (
            json.dumps(
                {"options": quality_options, "default": record.get("default_quality")},
                ensure_ascii=False,
            )
            if quality_options else None
        )
        connection.execute(
            """INSERT OR IGNORE INTO grs_image_models
            (workflow_id, provider_model, display_name, description, profile, resolutions_json,
             quality_json, enabled, sort_order, is_default, builtin, credit_cost, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["workflow_id"], record["provider_model"], record["display_name"],
                record.get("description") or "", record["profile"],
                json.dumps(resolutions, ensure_ascii=False) if resolutions else None,
                quality_json,
                int(bool(record.get("enabled"))), int(record.get("sort_order", 100)),
                int(bool(record.get("is_default"))), int(bool(record.get("builtin", True))),
                (int(record["credit_cost"]) if record.get("credit_cost") is not None else None),
                timestamp, timestamp,
            ),
        )

    def _migrate_legacy_jobs(self, connection: DbConnection) -> None:
        rows = connection.execute(
            "SELECT * FROM jobs WHERE id NOT IN (SELECT job_id FROM job_rounds) ORDER BY created_at"
        ).fetchall()
        for row in rows:
            data = dict(row)
            media_type = data.get("media_type") or self._media_for_mode(data["mode"])
            if data["mode"] == JobMode.IMAGE.value:
                media_type = "image"
            round_id = f"{data['id']}:round:1"
            item_id = f"{round_id}:item:1"
            connection.execute(
                """INSERT OR IGNORE INTO job_rounds
                (id, job_id, sequence, mode, media_type, status, stage, progress, prompt,
                 negative_prompt, image_size, options_json, submitted_options_json,
                 options_submitted, references_json, error, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    round_id, data["id"], data["mode"], media_type, data["status"], data["stage"],
                    data.get("progress", 0), data["prompt"], data.get("negative_prompt", ""), data.get("image_size"),
                    data.get("options_json", "{}"), data.get("submitted_options_json", "{}"),
                    data.get("options_submitted", 0), data.get("references_json", "[]"), data.get("error"),
                    data["created_at"], data["updated_at"],
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO generation_items
                (id, round_id, item_index, executor, status, stage, progress, remote_task_id,
                 comfy_prompt_id, comfy_client_id, comfy_phase, outputs_json, error, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id, round_id, self._executor_for_mode(data["mode"]), data["status"], data["stage"],
                    data.get("progress", 0), data.get("comfy_prompt_id"), data.get("comfy_client_id"),
                    data.get("comfy_phase"), data.get("outputs_json", "[]"), data.get("error"),
                    data["created_at"], data["updated_at"],
                ),
            )
            legacy_read_only = 1 if data["mode"] == JobMode.IMAGE.value else data.get("legacy_read_only", 0)
            connection.execute(
                "UPDATE jobs SET media_type = ?, last_round_id = ?, legacy_read_only = ? WHERE id = ?",
                (media_type, round_id, legacy_read_only, data["id"]),
            )

    def create(
        self,
        job_id: str,
        mode: JobMode | str,
        prompt: str,
        negative_prompt: str,
        image_size: str | None,
        references: list[str],
        options: dict | None = None,
        submitted_options: dict | None = None,
        owner_user_id: str | None = None,
        *,
        title: str | None = None,
        source: dict[str, Any] | None = None,
        display_prompt: str | None = None,
        credits_per_item: int | None = None,
        credit_quote: JobCreditQuote | None = None,
    ) -> dict:
        mode_value = self._mode_value(mode)
        media_type = self._media_for_mode(mode_value)
        timestamp = now()
        round_id = str(uuid.uuid4())
        source = source or {}
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO jobs (
                    id, owner_user_id, mode, media_type, title, last_round_id,
                    source_job_id, source_generation_item_id, source_output_index,
                    status, stage, progress, prompt, negative_prompt, image_size,
                    options_json, submitted_options_json, options_submitted, references_json,
                    outputs_json, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', NULL, ?, ?)""",
                (
                    job_id, owner_user_id, mode_value, media_type, title, round_id,
                    source.get("job_id"), source.get("generation_item_id"), source.get("output_index"),
                    JobStatus.QUEUED.value, "等待排队", 0, prompt, negative_prompt, image_size,
                    json.dumps(options or {}, ensure_ascii=False),
                    json.dumps(submitted_options or {}, ensure_ascii=False), int(submitted_options is not None),
                    json.dumps(references, ensure_ascii=False), timestamp, timestamp,
                ),
            )
            self._insert_round(
                connection, round_id, job_id, 1, mode_value, media_type, prompt, negative_prompt,
                image_size, references, options or {}, submitted_options, display_prompt,
                credits_per_item=credits_per_item,
                credit_quote=credit_quote, owner_user_id=owner_user_id,
            )
        self._bump_content_epoch()
        return self.get(job_id)

    def _insert_round(
        self, connection: DbConnection, round_id: str, job_id: str, sequence: int,
        mode: JobMode | str, media_type: str, prompt: str, negative_prompt: str,
        image_size: str | None, references: list[str], options: dict,
        submitted_options: dict | None, display_prompt: str | None = None,
        credits_per_item: int | None = None,
        credit_quote: JobCreditQuote | None = None, owner_user_id: str | None = None,
    ) -> None:
        timestamp = now()
        mode_value = self._mode_value(mode)
        connection.execute(
            """INSERT INTO job_rounds
            (id, job_id, sequence, mode, media_type, status, stage, progress, prompt, display_prompt,
             negative_prompt, image_size, options_json, submitted_options_json,
             options_submitted, references_json, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
            (
                round_id, job_id, sequence, mode_value, media_type, JobStatus.QUEUED.value, "等待排队",
                prompt, display_prompt, negative_prompt, image_size, json.dumps(options, ensure_ascii=False),
                json.dumps(submitted_options or {}, ensure_ascii=False), int(submitted_options is not None),
                json.dumps(references, ensure_ascii=False), timestamp, timestamp,
            ),
        )
        count = int(options.get("count", 1)) if media_type == "image" else 1
        executor = self._executor_for_mode(mode_value)
        wallet_enterprise_id = None
        if owner_user_id and credit_quote:
            account = self._deduct_credits(
                connection, owner_user_id, credit_quote.total, price_key=credit_quote.price_key,
                reason=credit_quote.reason, ref_type="job", ref_id=job_id,
            )
            credits_per_item = credit_quote.per_item
            wallet_enterprise_id = account.get("enterprise_id", "")
        for index in range(1, count + 1):
            connection.execute(
                """INSERT INTO generation_items
                (id, round_id, item_index, executor, status, stage, progress, outputs_json,
                 credits_billed, credits_wallet_enterprise_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, '[]', ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), round_id, index, executor, JobStatus.QUEUED.value, "等待排队",
                    credits_per_item if credits_per_item is not None and credits_per_item > 0 else None,
                    wallet_enterprise_id,
                    timestamp, timestamp,
                ),
            )

    def create_round(
        self, job_id: str, *, prompt: str, negative_prompt: str = "", image_size: str | None = None,
        references: list[str] | None = None, options: dict | None = None,
        submitted_options: dict | None = None, display_prompt: str | None = None,
        credits_per_item: int | None = None,
        credit_quote: JobCreditQuote | None = None,
    ) -> dict:
        job = self.get(job_id, include_references=True)
        if job.get("legacy_read_only"):
            raise ValueError("旧版图片工作流仅支持查看，不能再次生成。")
        sequence = len(job["rounds"]) + 1
        round_id = str(uuid.uuid4())
        mode = job["mode"]
        refs = references if references is not None else job.get("references", [])
        effective_options = options if options is not None else job.get("options", {})
        with self.connection() as connection:
            try:
                self._insert_round(
                    connection, round_id, job_id, sequence, mode, job["media_type"], prompt,
                    negative_prompt, image_size, refs, effective_options, submitted_options, display_prompt,
                    credits_per_item=credits_per_item,
                    credit_quote=credit_quote, owner_user_id=job.get("owner_user_id"),
                )
            except IntegrityError as error:
                # UNIQUE(job_id, sequence): a concurrent request created the
                # next round first; the caller should surface 409, not 500.
                raise ValueError("该任务刚刚创建了新的轮次，请刷新后重试。") from error
            connection.execute("UPDATE jobs SET last_round_id = ?, updated_at = ? WHERE id = ?", (round_id, now(), job_id))
            self._refresh_job(connection, job_id)
        self._bump_content_epoch()
        return self.get(job_id)

    def update(
        self, job_id: str, *, status: JobStatus | None = None, stage: str | None = None,
        progress: int | None = None, outputs: list[dict] | None = None, error: str | None = None,
        execution_elapsed_ms: int | None = None,
    ) -> dict:
        job = self.get(job_id)
        latest = job["rounds"][-1]
        item = latest["generation_items"][0]
        self.update_generation(
            item["id"], status=status, stage=stage, progress=progress, outputs=outputs, error=error,
            execution_elapsed_ms=execution_elapsed_ms,
        )
        return self.get(job_id)

    def update_generation(
        self, generation_item_id: str, *, status: JobStatus | str | None = None,
        stage: str | None = None, progress: int | None = None, outputs: list[dict] | None = None,
        error: str | None = None, remote_task_id: str | None = None, remote_status: str | None = None,
        execution_elapsed_ms: int | None = None,
        comfy_prompt_id: str | None = None, comfy_client_id: str | None = None,
        comfy_phase: str | None = None, clear_execution: bool = False,
        cancel_requested: bool | None = None,
        refine_state: dict | None = None, clear_refine_state: bool = False,
    ) -> dict:
        incoming_status = status.value if isinstance(status, JobStatus) else status
        updates: dict[str, Any] = {"updated_at": now()}
        with self.connection() as connection:
            refund_terminal = incoming_status in {JobStatus.FAILED.value, JobStatus.CANCELLED.value}
            if refund_terminal:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("SELECT id FROM generation_items WHERE id = ?", (generation_item_id,), for_update=True).fetchone()
            row = connection.execute(
                """SELECT r.job_id, i.round_id, i.status, i.cancel_requested, i.finished_at,
                i.credits_billed, i.credits_settled, i.credits_wallet_enterprise_id, j.owner_user_id
                FROM generation_items i
                JOIN job_rounds r ON r.id = i.round_id
                JOIN jobs j ON j.id = r.job_id
                WHERE i.id = ?""",
                (generation_item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(generation_item_id)
            cancelled = row["status"] == JobStatus.CANCELLED.value or bool(row["cancel_requested"])
            allow_status = not cancelled or incoming_status in {
                JobStatus.QUEUED.value, JobStatus.SUCCEEDED.value, JobStatus.CANCELLED.value,
            }
            refund_credits = 0
            if allow_status and refund_terminal:
                # 积分退款钩子：预扣过的生成项到达失败/取消终态时全额退回（同事务，防并发重复退款）。
                try:
                    billed = int(row["credits_billed"] or 0)
                except (TypeError, ValueError):
                    billed = 0
                if billed > 0 and not int(row["credits_settled"] or 0) and row["owner_user_id"]:
                    refund_credits = billed
                    updates["credits_settled"] = 1
            if allow_status:
                if incoming_status is not None:
                    updates["status"] = incoming_status
                    if incoming_status in FINISHED_STATUSES:
                        if not row["finished_at"]:
                            updates["finished_at"] = now()
                    elif incoming_status in ACTIVE_STATUSES:
                        updates["finished_at"] = None
                        updates["execution_elapsed_ms"] = None
                if stage is not None:
                    updates["stage"] = stage
                if progress is not None:
                    updates["progress"] = max(0, min(100, int(progress)))
                if outputs is not None:
                    updates["outputs_json"] = json.dumps(outputs, ensure_ascii=False)
                if error is not None:
                    updates["error"] = error
            if execution_elapsed_ms is not None:
                updates["execution_elapsed_ms"] = max(0, int(execution_elapsed_ms))
            if remote_task_id is not None:
                updates["remote_task_id"] = remote_task_id
            if remote_status is not None:
                updates["remote_status"] = remote_status
            if comfy_prompt_id is not None:
                updates["comfy_prompt_id"] = comfy_prompt_id
            if comfy_client_id is not None:
                updates["comfy_client_id"] = comfy_client_id
            if comfy_phase is not None:
                updates["comfy_phase"] = comfy_phase
            if clear_execution:
                updates.update({"comfy_prompt_id": None, "comfy_client_id": None, "comfy_phase": None})
            if cancel_requested is not None:
                updates["cancel_requested"] = 1 if cancel_requested else 0
            if refine_state is not None:
                updates["refine_state_json"] = json.dumps(refine_state, ensure_ascii=False)
            if clear_refine_state:
                updates["refine_state_json"] = None
            assignment = ", ".join(f"{column} = ?" for column in updates)
            connection.execute(f"UPDATE generation_items SET {assignment} WHERE id = ?", (*updates.values(), generation_item_id))
            if refund_credits:
                wallet_enterprise_id = row["credits_wallet_enterprise_id"]
                if wallet_enterprise_id is None:
                    wallet_enterprise_id = self._legacy_job_credit_wallet(connection, row["owner_user_id"], row["job_id"])
                self._route_credit_delta(
                    connection, row["owner_user_id"], refund_credits, type="refund",
                    reason="任务失败，积分退回", ref_type="generation_item", ref_id=generation_item_id,
                    wallet_enterprise_id=wallet_enterprise_id,
                )
            self._refresh_round(connection, row["round_id"])
            self._refresh_job(connection, row["job_id"])
        if outputs is not None:
            self._bump_content_epoch()
        return self.get_generation(generation_item_id)

    @staticmethod
    def _item_has_outputs(row: Row) -> bool:
        try:
            outputs = json.loads(row["outputs_json"] or "[]")
        except (TypeError, ValueError):
            return False
        return bool(outputs)

    def _refresh_round(self, connection: DbConnection, round_id: str) -> None:
        items = connection.execute("SELECT * FROM generation_items WHERE round_id = ? ORDER BY item_index", (round_id,)).fetchall()
        statuses = [row["status"] for row in items]
        successes = statuses.count(JobStatus.SUCCEEDED.value)
        has_outputs = any(self._item_has_outputs(row) for row in items)
        terminal = bool(statuses) and all(value in TERMINAL_STATUSES for value in statuses)
        if statuses and successes == len(statuses):
            status, stage, progress, error = JobStatus.SUCCEEDED.value, "生成完成", 100, None
        elif terminal and (successes or has_outputs):
            status, stage, progress = JobStatus.PARTIAL.value, "部分生成完成", round(100 * max(successes, 1) / len(statuses))
            error = next((row["error"] for row in items if row["error"]), None) or "部分生成项失败，可只重试失败项。"
        elif any(value == JobStatus.AWAITING_REFINE.value for value in statuses):
            waiting = next(row for row in items if row["status"] == JobStatus.AWAITING_REFINE.value)
            status, stage, progress, error = (
                JobStatus.AWAITING_REFINE.value,
                waiting["stage"] or "一采预览待确认",
                int(waiting["progress"] or 90),
                None,
            )
        elif any(value == JobStatus.RUNNING.value for value in statuses):
            status, stage, progress, error = JobStatus.RUNNING.value, "正在生成", round(sum(row["progress"] for row in items) / len(items)), None
        elif any(value == JobStatus.QUEUED.value for value in statuses):
            status, stage, progress, error = JobStatus.QUEUED.value, "等待排队", round(sum(row["progress"] for row in items) / len(items)), None
        elif statuses and all(value == JobStatus.CANCELLED.value for value in statuses):
            status, stage, progress, error = JobStatus.CANCELLED.value, "已停止生成", 0, next((row["error"] for row in items if row["error"]), None)
        elif statuses and all(value == JobStatus.INTERRUPTED.value for value in statuses):
            status, stage, progress, error = JobStatus.INTERRUPTED.value, "任务已中断", 0, next((row["error"] for row in items if row["error"]), None)
        else:
            status, stage, progress, error = JobStatus.FAILED.value, "生成失败", 0, next((row["error"] for row in items if row["error"]), None)
        if statuses and all(value == status for value in statuses):
            item = items[0]
            stage = item["stage"]
            progress = 100 if status == JobStatus.SUCCEEDED.value else item["progress"]
            error = None if status == JobStatus.SUCCEEDED.value else item["error"]
        if status in FINISHED_STATUSES:
            finished_values = [row["finished_at"] for row in items if row["finished_at"]]
            finished_at = max(finished_values) if finished_values else now()
        else:
            finished_at = None
        exec_values = [
            int(row["execution_elapsed_ms"])
            for row in items
            if row["execution_elapsed_ms"] is not None
        ]
        execution_elapsed_ms = sum(exec_values) if exec_values else None
        connection.execute(
            """UPDATE job_rounds SET status = ?, stage = ?, progress = ?, error = ?,
            finished_at = ?, execution_elapsed_ms = ?, updated_at = ? WHERE id = ?""",
            (status, stage, progress, error, finished_at, execution_elapsed_ms, now(), round_id),
        )

    def _refresh_job(self, connection: DbConnection, job_id: str) -> None:
        row = connection.execute(
            "SELECT * FROM job_rounds WHERE job_id = ? ORDER BY sequence DESC LIMIT 1", (job_id,)
        ).fetchone()
        if row is None:
            return
        items = connection.execute("SELECT * FROM generation_items WHERE round_id = ? ORDER BY item_index", (row["id"],)).fetchall()
        outputs: list[dict] = []
        for item in items:
            outputs.extend(json.loads(item["outputs_json"] or "[]"))
        first = items[0] if items else None
        connection.execute(
            """UPDATE jobs SET mode = ?, media_type = ?, last_round_id = ?, status = ?, stage = ?, progress = ?,
            prompt = ?, negative_prompt = ?, image_size = ?, options_json = ?, submitted_options_json = ?,
            options_submitted = ?, references_json = ?, outputs_json = ?, error = ?, comfy_prompt_id = ?,
            comfy_client_id = ?, comfy_phase = ?, finished_at = ?, execution_elapsed_ms = ?, updated_at = ? WHERE id = ?""",
            (
                row["mode"], row["media_type"], row["id"], row["status"], row["stage"], row["progress"],
                row["prompt"], row["negative_prompt"], row["image_size"], row["options_json"],
                row["submitted_options_json"], row["options_submitted"], row["references_json"],
                json.dumps(outputs, ensure_ascii=False), row["error"], first["comfy_prompt_id"] if first else None,
                first["comfy_client_id"] if first else None, first["comfy_phase"] if first else None,
                row["finished_at"], row["execution_elapsed_ms"], now(), job_id,
            ),
        )

    def set_comfy_execution(self, job_id: str, prompt_id: str, client_id: str | None, phase: str) -> dict:
        item = self.get(job_id)["rounds"][-1]["generation_items"][0]
        if item["status"] == JobStatus.CANCELLED.value or item.get("cancel_requested"):
            self.update_generation(
                item["id"], comfy_prompt_id=prompt_id, comfy_client_id=client_id, comfy_phase=phase,
            )
            return self.get(job_id)
        self.update_generation(
            item["id"], status=JobStatus.RUNNING, comfy_prompt_id=prompt_id,
            comfy_client_id=client_id, comfy_phase=phase,
        )
        return self.get(job_id)

    def clear_comfy_execution(self, job_id: str) -> dict:
        item = self.get(job_id)["rounds"][-1]["generation_items"][0]
        self.update_generation(item["id"], clear_execution=True)
        return self.get(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job["status"] == JobStatus.CANCELLED.value:
            return True
        return any(
            item["status"] == JobStatus.CANCELLED.value or item.get("cancel_requested")
            for item in job["rounds"][-1]["generation_items"]
        )

    def mark_cancelled(self, job_id: str) -> tuple[dict | None, list[str]]:
        job = self.get(job_id)
        if job.get("legacy_read_only"):
            return None, []
        prompt_ids: list[str] = []
        changed = False
        for item in job["rounds"][-1]["generation_items"]:
            if item["status"] not in CANCELABLE_STATUSES:
                continue
            prompt_id = item.get("comfy_prompt_id")
            if isinstance(prompt_id, str) and prompt_id:
                prompt_ids.append(prompt_id)
            self.update_generation(
                item["id"], status=JobStatus.CANCELLED, stage="已停止生成",
                error="用户停止生成", cancel_requested=True, clear_execution=True,
            )
            changed = True
        if not changed:
            return None, []
        return self.get(job_id), prompt_ids

    def retry_terminal(self, job_id: str) -> dict | None:
        job = self.get(job_id)
        if job.get("legacy_read_only"):
            return None
        item = job["rounds"][-1]["generation_items"][0]
        if item["status"] not in {
            JobStatus.INTERRUPTED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value,
        } or item.get("comfy_prompt_id"):
            return None
        self.update_generation(
            item["id"], status=JobStatus.QUEUED, stage="等待重新提交", progress=0,
            outputs=[], error="", cancel_requested=False, clear_execution=True,
        )
        return self.get(job_id)

    def retry_failed_items(
        self, job_id: str, round_id: str | None = None, *, credit_quote: JobCreditQuote | None = None,
    ) -> list[dict]:
        job = self.get(job_id)
        if round_id is None:
            round_id = job["rounds"][-1]["id"]
        if all(item["id"] != round_id for item in job["rounds"]):
            raise KeyError(f"轮次不存在: {round_id}")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            items = connection.execute(
                """SELECT id, status, credits_billed, credits_settled, credits_wallet_enterprise_id
                FROM generation_items WHERE round_id = ? ORDER BY item_index""",
                (round_id,), for_update=True,
            ).fetchall()
            retryable = [item for item in items if item["status"] in RETRYABLE_GENERATION_STATUSES]
            if not retryable:
                return []
            needs_charge = {item["id"] for item in retryable if not item["credits_billed"] or item["credits_settled"]}
            owner_user_id = job.get("owner_user_id")
            per_item, wallet_enterprise_id = None, None
            if credit_quote and owner_user_id and needs_charge:
                per_item = credit_quote.per_item
                account = self._deduct_credits(
                    connection, owner_user_id, per_item * len(needs_charge),
                    reason=f"重试 {len(needs_charge)} 项 × {per_item} 积分",
                    price_key=credit_quote.price_key, ref_type="job", ref_id=job_id,
                )
                wallet_enterprise_id = account.get("enterprise_id", "")
            timestamp = now()
            for item in retryable:
                rebill = item["id"] in needs_charge
                connection.execute(
                    """UPDATE generation_items SET status = ?, stage = ?, progress = 0, outputs_json = '[]', error = '',
                    remote_status = '', cancel_requested = 0, comfy_prompt_id = NULL, comfy_client_id = NULL,
                    comfy_phase = NULL, finished_at = NULL, execution_elapsed_ms = NULL, updated_at = ?,
                    credits_billed = ?, credits_wallet_enterprise_id = ?, credits_settled = 0 WHERE id = ?""",
                    (JobStatus.QUEUED.value, "等待重新提交", timestamp,
                     per_item if rebill else item["credits_billed"],
                     wallet_enterprise_id if rebill else item["credits_wallet_enterprise_id"], item["id"]),
                )
            self._refresh_round(connection, round_id)
            self._refresh_job(connection, job_id)
        self._bump_content_epoch()
        return [self.get_generation(item["id"]) for item in retryable]

    # ------------------------------------------------------------------
    # 用户积分体系：账户 / 流水 / 价格表（锚定 100 积分 = 1 元，整数积分）
    # ------------------------------------------------------------------

    def _ensure_credit_account_row(self, connection: DbConnection, user_id: str) -> Row:
        row = connection.execute("SELECT * FROM credit_accounts WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            connection.execute(
                """INSERT OR IGNORE INTO credit_accounts (user_id, balance, total_recharged, total_consumed, updated_at)
                VALUES (?, 0, 0, 0, ?)""",
                (user_id, now()),
            )
            row = connection.execute(
                "SELECT * FROM credit_accounts WHERE user_id = ?", (user_id,), for_update=True,
            ).fetchone()
        if row is None:
            raise ValueError("积分账户初始化失败")
        return row

    def get_or_create_credit_account(self, user_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            return dict(self._ensure_credit_account_row(connection, user_id))

    def _apply_credit_delta(
        self, connection: DbConnection, user_id: str, delta: int, *, type: str,
        reason: str | None = None, price_key: str | None = None, ref_type: str | None = None,
        ref_id: str | None = None, actor_user_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """在给定连接（事务）内变更余额并落一条流水；调用方负责并发控制（deduct 走行锁）。"""
        amount = abs(int(delta))
        timestamp = now()
        self._ensure_credit_account_row(connection, user_id)
        if amount:
            if type == "consume":
                connection.execute(
                    """UPDATE credit_accounts SET balance = balance - ?,
                    total_consumed = total_consumed + ?, updated_at = ? WHERE user_id = ?""",
                    (amount, amount, timestamp, user_id),
                )
            elif type == "refund":
                # MySQL 无两参数 MAX 标量函数，用 CASE 保持双方言兼容。
                connection.execute(
                    """UPDATE credit_accounts SET balance = balance + ?,
                    total_consumed = CASE WHEN total_consumed > ? THEN total_consumed - ? ELSE 0 END,
                    updated_at = ? WHERE user_id = ?""",
                    (amount, amount, amount, timestamp, user_id),
                )
            elif type == "admin_recharge":
                connection.execute(
                    """UPDATE credit_accounts SET balance = balance + ?,
                    total_recharged = total_recharged + ?, updated_at = ? WHERE user_id = ?""",
                    (amount, amount, timestamp, user_id),
                )
            else:  # admin_adjust 及未来扩展类型：仅变动余额，不动累计
                connection.execute(
                    "UPDATE credit_accounts SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
                    (int(delta), timestamp, user_id),
                )
        row = connection.execute(
            "SELECT * FROM credit_accounts WHERE user_id = ?", (user_id,),
        ).fetchone()
        balance_after = int(row["balance"]) if row else 0
        connection.execute(
            """INSERT INTO credit_transactions
            (user_id, delta, type, reason, price_key, ref_type, ref_id, balance_after, actor_user_id, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, int(delta), type, reason, price_key, ref_type, ref_id,
                balance_after, actor_user_id,
                json.dumps(meta, ensure_ascii=False) if meta else None, timestamp,
            ),
        )
        return dict(row) if row is not None else {"user_id": user_id, "balance": balance_after}

    def _route_credit_delta(
        self, connection: DbConnection, user_id: str, delta: int, *, type: str,
        reason: str | None = None, price_key: str | None = None, ref_type: str | None = None,
        ref_id: str | None = None, actor_user_id: str | None = None,
        wallet_enterprise_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """退款可指定预扣钱包。空字符串表示个人钱包，None 按当前企业归属结算。"""
        enterprise_id = wallet_enterprise_id
        if enterprise_id is None:
            enterprise_id = self.get_user_enterprise_id(user_id, connection=connection)
        if enterprise_id:
            if type == "consume":
                self._assert_enterprise_member_quota(connection, enterprise_id, user_id, abs(int(delta)))
            return self._apply_enterprise_credit_delta(
                connection, enterprise_id, delta, type=type,
                spender_user_id=user_id if type in {"consume", "refund"} else None,
                reason=reason, price_key=price_key, ref_type=ref_type, ref_id=ref_id,
                actor_user_id=actor_user_id, meta=meta,
            )
        return self._apply_credit_delta(
            connection, user_id, delta, type=type, reason=reason, price_key=price_key,
            ref_type=ref_type, ref_id=ref_id, actor_user_id=actor_user_id, meta=meta,
        )

    def get_user_enterprise_id(self, user_id: str | None, *, connection: DbConnection | None = None) -> str | None:
        """用户当前绑定的企业 ID；无用户表（纯 JobStore 环境）或未绑定返回 None。

        connection 传入时复用当前事务连接（嵌套事务内调用，避免二次开连接）。
        """
        if not user_id:
            return None
        if connection is not None:
            return self._read_user_enterprise_id(connection, user_id)
        with self.connection() as existing:
            return self._read_user_enterprise_id(existing, user_id)

    def _read_user_enterprise_id(self, connection: DbConnection, user_id: str, *, for_update: bool = False) -> str | None:
        if not self._db.table_exists(connection, "users"):
            return None
        if "enterprise_id" not in self._db.column_names(connection, "users"):
            return None
        row = connection.execute(
            "SELECT enterprise_id FROM users WHERE id = ?", (user_id,), for_update=for_update,
        ).fetchone()
        if row is None:
            return None
        return str(row["enterprise_id"]) if row["enterprise_id"] else None

    def deduct_credits(
        self, user_id: str, amount: int, *, price_key: str | None = None,
        ref_type: str | None = None, ref_id: str | None = None, reason: str | None = None,
    ) -> dict[str, Any]:
        """在当前结算钱包预扣积分并写入流水。"""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._deduct_credits(
                connection, user_id, int(amount), reason=reason, price_key=price_key, ref_type=ref_type, ref_id=ref_id,
            )

    def _deduct_credits(
        self, connection: DbConnection, user_id: str, amount: int, *, reason: str | None,
        price_key: str | None, ref_type: str | None, ref_id: str | None,
    ) -> dict[str, Any]:
        enterprise_id = self.get_user_enterprise_id(user_id, connection=connection)
        if enterprise_id:
            row = connection.execute(
                "SELECT balance FROM enterprise_credit_accounts WHERE enterprise_id = ?",
                (enterprise_id,), for_update=True,
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT balance FROM credit_accounts WHERE user_id = ?", (user_id,), for_update=True,
            ).fetchone()
        balance = int(row["balance"]) if row else 0
        if amount > 0 and balance < amount:
            raise CreditInsufficientError(balance, amount)
        return self._route_credit_delta(
            connection, user_id, -amount, type="consume", reason=reason, price_key=price_key,
            ref_type=ref_type, ref_id=ref_id, wallet_enterprise_id=enterprise_id or "",
        )

    @staticmethod
    def _legacy_job_credit_wallet(connection: DbConnection, user_id: str, job_id: str) -> str | None:
        """历史任务若只有一个记账钱包，使用原扣费流水识别。"""
        wallets = connection.execute(
            """SELECT '' AS wallet FROM credit_transactions
                WHERE ref_type = 'job' AND ref_id = ? AND user_id = ? AND type = 'consume'
            UNION SELECT enterprise_id AS wallet FROM enterprise_credit_transactions
                WHERE ref_type = 'job' AND ref_id = ? AND user_id = ? AND type = 'consume'""",
            (job_id, user_id, job_id, user_id),
        ).fetchall()
        return str(wallets[0]["wallet"]) if len(wallets) == 1 else None

    def refund_credits(
        self, user_id: str, amount: int, *, reason: str | None = None,
        price_key: str | None = None, ref_type: str | None = None, ref_id: str | None = None,
        wallet_enterprise_id: str | None = None, once: bool = False,
    ) -> dict[str, Any]:
        """为在工作台任务表以外保存的任务退款。"""
        amount = int(amount)
        if amount <= 0:
            return self.billing_account_snapshot(user_id)
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if wallet_enterprise_id is None and ref_type == "job" and ref_id:
                wallet_enterprise_id = self._legacy_job_credit_wallet(connection, user_id, ref_id)
            if wallet_enterprise_id is None:
                wallet_enterprise_id = self.get_user_enterprise_id(user_id, connection=connection) or ""
            if once and ref_id:
                if wallet_enterprise_id:
                    table, column, wallet_id = "enterprise_credit", "enterprise_id", wallet_enterprise_id
                else:
                    table, column, wallet_id = "credit", "user_id", user_id
                account = connection.execute(
                    f"SELECT * FROM {table}_accounts WHERE {column} = ?", (wallet_id,), for_update=True,
                ).fetchone()
                recorded = connection.execute(
                    f"""SELECT id FROM {table}_transactions WHERE {column} = ? AND user_id = ?
                    AND type = 'refund' AND ref_type = ? AND ref_id = ?""",
                    (wallet_id, user_id, ref_type, ref_id), for_update=True,
                ).fetchone()
                if recorded and account:
                    return dict(account)
            return self._route_credit_delta(
                connection, user_id, amount, type="refund", reason=reason, price_key=price_key,
                ref_type=ref_type, ref_id=ref_id, wallet_enterprise_id=wallet_enterprise_id,
            )

    def billing_account_snapshot(self, user_id: str) -> dict[str, Any]:
        """计费视角的账户快照：企业绑定用户返回企业钱包（带 scope/enterprise_id），否则个人钱包。"""
        enterprise_id = self.get_user_enterprise_id(user_id)
        if enterprise_id:
            account = self.get_or_create_enterprise_credit_account(enterprise_id)
            return {**account, "scope": "enterprise", "enterprise_id": enterprise_id}
        account = self.get_or_create_credit_account(user_id)
        return {**account, "scope": "user", "enterprise_id": None}

    def canvas_project_credit_stats(self, owner_user_id: str, job_ids: list[str]) -> dict[str, Any]:
        """画布「项目信息」积分消耗：按画布节点引用的任务聚合净消耗（预扣-退款）与任务数。

        只统计有实际消耗的任务（全额退款的失败任务净额为 0，不计入）；个人与企业
        钱包流水都纳入，跨钱包迁移的任务也能正确汇总。返回消耗按媒体类型分组的占比。
        """
        normalized: list[str] = []
        seen: set[str] = set()
        for job_id in job_ids or []:
            value = str(job_id or "").strip()
            if value and value not in seen:
                seen.add(value)
                normalized.append(value)
        if not normalized:
            return {"total_credits": 0, "task_count": 0, "groups": []}
        normalized = normalized[:500]
        placeholders = ", ".join("?" for _ in normalized)
        net_by_job: dict[str, int] = {}
        with self.connection() as connection:
            jobs = connection.execute(
                f"""SELECT id, media_type FROM jobs
                    WHERE owner_user_id = ? AND id IN ({placeholders})""",
                (owner_user_id, *normalized),
            ).fetchall()
            if not jobs:
                return {"total_credits": 0, "task_count": 0, "groups": []}
            for table in ("credit_transactions", "enterprise_credit_transactions"):
                rows = connection.execute(
                    f"""SELECT ref_id,
                            SUM(CASE WHEN type IN ('consume', 'refund') THEN -delta ELSE 0 END) AS net
                        FROM {table}
                        WHERE user_id = ? AND ref_type = 'job' AND ref_id IN ({placeholders})
                        GROUP BY ref_id""",
                    (owner_user_id, *normalized),
                ).fetchall()
                for row in rows:
                    ref_id = str(row["ref_id"])
                    net_by_job[ref_id] = net_by_job.get(ref_id, 0) + int(row["net"] or 0)
        total_credits = 0
        task_count = 0
        per_type: dict[str, dict[str, int]] = {}
        for job in jobs:
            media_type = str(job["media_type"] or "video")
            net = net_by_job.get(str(job["id"]), 0)
            if net <= 0:
                continue
            total_credits += net
            task_count += 1
            bucket = per_type.setdefault(media_type, {"task_count": 0, "credits": 0})
            bucket["task_count"] += 1
            bucket["credits"] += net
        labels = {"image": "图片生成", "video": "视频生成"}
        groups = []
        for media_type, bucket in sorted(per_type.items(), key=lambda item: -item[1]["credits"]):
            groups.append({
                "type": media_type,
                "label": labels.get(media_type, "其他生成"),
                "task_count": bucket["task_count"],
                "credits": bucket["credits"],
                "ratio": round(bucket["credits"] / total_credits, 4) if total_credits else 0.0,
            })
        return {"total_credits": total_credits, "task_count": task_count, "groups": groups}

    def adjust_credit(
        self, user_id: str, delta: int, *, type: str, reason: str | None = None,
        price_key: str | None = None, ref_type: str | None = None, ref_id: str | None = None,
        actor_user_id: str | None = None, meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按次结算沿用用户的当前计费钱包，消费流水记录实际使用人。"""
        with self.connection() as connection:
            if self._db.dialect == "sqlite" and int(delta) < 0:
                # 与任务预扣一致：SQLite 先取写锁，避免额度检查与扣减之间的并发窗口。
                connection.execute("BEGIN IMMEDIATE")
            return self._route_credit_delta(
                connection, user_id, int(delta), type=type, reason=reason, price_key=price_key,
                ref_type=ref_type, ref_id=ref_id, actor_user_id=actor_user_id, meta=meta,
            )

    def adjust_personal_credit(
        self, user_id: str, delta: int, *, reason: str,
        actor_user_id: str | None = None, request_id: str | None = None,
    ) -> dict[str, Any]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._read_user_enterprise_id(connection, user_id, for_update=True):
                raise CreditWalletConflictError("该账号由企业钱包结算，请选择对应的企业钱包调整积分")
            return self._record_admin_credit_change(
                connection, user_id, delta, reason=reason,
                actor_user_id=actor_user_id, request_id=request_id, enterprise=False,
            )

    def _record_admin_credit_change(
        self, connection: DbConnection, wallet_id: str, delta: int, *,
        reason: str, actor_user_id: str | None, request_id: str | None, enterprise: bool,
        type: str | None = None,
    ) -> dict[str, Any]:
        if not delta:
            raise ValueError("调整积分数不能为 0")
        if enterprise:
            self._ensure_enterprise_credit_account_row(connection, wallet_id)
            table_prefix, wallet_column = "enterprise_credit", "enterprise_id"
            apply_delta = self._apply_enterprise_credit_delta
        else:
            self._ensure_credit_account_row(connection, wallet_id)
            table_prefix, wallet_column = "credit", "user_id"
            apply_delta = self._apply_credit_delta
        account = connection.execute(
            f"SELECT * FROM {table_prefix}_accounts WHERE {wallet_column} = ?", (wallet_id,), for_update=True,
        ).fetchone()
        if request_id:
            existing = connection.execute(
                f"""SELECT delta, reason FROM {table_prefix}_transactions WHERE {wallet_column} = ?
                AND ref_type = 'admin_credit_change' AND ref_id = ?""",
                (wallet_id, request_id), for_update=True,
            ).fetchone()
            if existing:
                if int(existing["delta"]) != delta or existing["reason"] != reason:
                    raise CreditWalletConflictError("该操作标识已用于另一笔积分调整")
                return {**dict(account), "replayed": True}
        if delta < 0 and int(account["balance"]) + delta < 0:
            raise ValueError("扣减积分不能超过当前余额")
        if delta > 0 and max(int(account["balance"]), int(account["total_recharged"])) + delta > MAX_CREDIT_AMOUNT:
            raise ValueError("调整后积分超出账户可记录范围")
        return apply_delta(
            connection, wallet_id, delta, type=type or ("admin_recharge" if delta > 0 else "admin_adjust"),
            reason=reason, actor_user_id=actor_user_id,
            ref_type="admin_credit_change" if request_id else None, ref_id=request_id,
        )

    # ---------------- 企业管理：主档 / 钱包 / 流水 / 成员用量 / 模型策略 ----------------

    @staticmethod
    def _normalize_enterprise_status(status: Any) -> str:
        value = str(status or "active").strip().lower()
        return value if value in {"active", "disabled"} else "active"

    def list_enterprises(self, query: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection() as connection:
            has_users = self._db.table_exists(connection, "users")
            member_count = (
                "(SELECT COUNT(*) FROM users u WHERE u.enterprise_id = e.id)" if has_users else "0"
            )
            sql = f"""SELECT e.id, e.name, e.code, e.parent_id, e.contact_name, e.contact_phone, e.notes,
                e.status, e.created_by, e.created_at, e.updated_at,
                {member_count} AS member_count,
                COALESCE(w.balance, 0) AS balance,
                COALESCE(w.total_recharged, 0) AS total_recharged,
                COALESCE(w.total_consumed, 0) AS total_consumed
                FROM enterprises e
                LEFT JOIN enterprise_credit_accounts w ON w.enterprise_id = e.id"""
            params: list[Any] = []
            if query:
                sql += " WHERE e.name LIKE ? OR e.code LIKE ?"
                params.extend([f"%{query}%", f"%{query}%"])
            sql += " ORDER BY e.created_at DESC LIMIT ?"
            params.append(max(1, min(int(limit), 500)))
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def get_enterprise(self, enterprise_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            has_users = self._db.table_exists(connection, "users")
            member_count = (
                "(SELECT COUNT(*) FROM users u WHERE u.enterprise_id = e.id)" if has_users else "0"
            )
            row = connection.execute(
                f"""SELECT e.id, e.name, e.code, e.parent_id, e.contact_name, e.contact_phone, e.notes,
                e.status, e.created_by, e.created_at, e.updated_at,
                {member_count} AS member_count,
                COALESCE(w.balance, 0) AS balance,
                COALESCE(w.total_recharged, 0) AS total_recharged,
                COALESCE(w.total_consumed, 0) AS total_consumed
                FROM enterprises e
                LEFT JOIN enterprise_credit_accounts w ON w.enterprise_id = e.id
                WHERE e.id = ?""",
                (enterprise_id,),
            ).fetchone()
        if row is None:
            raise KeyError(enterprise_id)
        return dict(row)

    def create_enterprise(
        self, name: str, *, code: str | None = None, contact_name: str | None = None,
        contact_phone: str | None = None, notes: str | None = None,
        status: str = "active", created_by: str | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("企业名称不能为空")
        code = (code or "").strip() or None
        parent_id = (parent_id or "").strip() or None
        contact_name = (contact_name or "").strip() or None
        contact_phone = (contact_phone or "").strip() or None
        notes = (notes or "").strip() or None
        enterprise_id = f"ent-{uuid.uuid4().hex[:12]}"
        timestamp = now()
        try:
            with self.connection() as connection:
                if code:
                    taken = connection.execute(
                        "SELECT 1 FROM enterprises WHERE code = ?", (code,),
                    ).fetchone()
                    if taken:
                        raise ValueError("该企业编码已被使用")
                if parent_id:
                    parent = connection.execute(
                        "SELECT id FROM enterprises WHERE id = ?", (parent_id,),
                    ).fetchone()
                    if parent is None:
                        raise ValueError("上级企业不存在")
                connection.execute(
                    """INSERT INTO enterprises
                    (id, name, code, parent_id, contact_name, contact_phone, notes, status, created_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        enterprise_id, name, code, parent_id, contact_name, contact_phone, notes,
                        self._normalize_enterprise_status(status), created_by, timestamp, timestamp,
                    ),
                )
        except IntegrityError as error:
            raise ValueError("该企业编码已被使用") from error
        return self.get_enterprise(enterprise_id)

    def update_enterprise(
        self, enterprise_id: str, *, name: str | None = None, code: str | None = None,
        update_code: bool = False, contact_name: str | None = None, update_contact_name: bool = False,
        contact_phone: str | None = None, update_contact_phone: bool = False,
        notes: str | None = None, update_notes: bool = False,
        status: str | None = None,
        parent_id: str | None = None, update_parent_id: bool = False,
    ) -> dict[str, Any]:
        updates: dict[str, Any] = {"updated_at": now()}
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("企业名称不能为空")
            updates["name"] = name
        if update_code:
            updates["code"] = (code or "").strip() or None
        if update_contact_name:
            updates["contact_name"] = (contact_name or "").strip() or None
        if update_contact_phone:
            updates["contact_phone"] = (contact_phone or "").strip() or None
        if update_notes:
            updates["notes"] = (notes or "").strip() or None
        if status is not None:
            updates["status"] = self._normalize_enterprise_status(status)
        try:
            with self.connection() as connection:
                if update_parent_id:
                    updates["parent_id"] = self._resolve_enterprise_parent(
                        connection, enterprise_id, parent_id,
                    )
                if "code" in updates and updates["code"]:
                    taken = connection.execute(
                        "SELECT 1 FROM enterprises WHERE code = ? AND id != ?",
                        (updates["code"], enterprise_id),
                    ).fetchone()
                    if taken:
                        raise ValueError("该企业编码已被使用")
                assignment = ", ".join(f"{column} = ?" for column in updates)
                cursor = connection.execute(
                    f"UPDATE enterprises SET {assignment} WHERE id = ?",
                    (*updates.values(), enterprise_id),
                )
                if not cursor.rowcount:
                    raise KeyError(enterprise_id)
        except IntegrityError as error:
            raise ValueError("该企业编码已被使用") from error
        return self.get_enterprise(enterprise_id)

    @staticmethod
    def _resolve_enterprise_parent(
        connection: DbConnection, enterprise_id: str, parent_id: str | None,
    ) -> str | None:
        """校验并归一化上级企业：不得指向自己、不得形成循环、上级必存在。"""
        normalized = (parent_id or "").strip() or None
        if not normalized:
            return None
        if normalized == enterprise_id:
            raise ValueError("不能把企业设置为自己的上级")
        seen: set[str] = {enterprise_id}
        cursor: str | None = normalized
        while cursor:
            if cursor in seen:
                raise ValueError("不能形成企业层级循环")
            seen.add(cursor)
            row = connection.execute(
                "SELECT parent_id FROM enterprises WHERE id = ?", (cursor,),
            ).fetchone()
            if row is None:
                raise ValueError("上级企业不存在")
            cursor = str(row["parent_id"]) if row["parent_id"] else None
        return normalized

    def delete_enterprise(self, enterprise_id: str) -> None:
        """删除企业主档：仅限无成员且无钱包流水（含余额）的企业，防止误删结算数据。"""
        with self.connection() as connection:
            row = connection.execute(
                "SELECT id FROM enterprises WHERE id = ?", (enterprise_id,),
            ).fetchone()
            if row is None:
                raise KeyError(enterprise_id)
            if self._db.table_exists(connection, "users"):
                members = connection.execute(
                    "SELECT COUNT(*) AS total FROM users WHERE enterprise_id = ?", (enterprise_id,),
                ).fetchone()
                if members and int(members["total"]) > 0:
                    raise ValueError("企业下仍有成员账号，请先移出全部成员再删除")
            children = connection.execute(
                "SELECT COUNT(*) AS total FROM enterprises WHERE parent_id = ?", (enterprise_id,),
            ).fetchone()
            if children and int(children["total"]) > 0:
                raise ValueError("企业下仍有下级企业，请先调整或删除下级企业")
            wallet = connection.execute(
                "SELECT balance FROM enterprise_credit_accounts WHERE enterprise_id = ?", (enterprise_id,),
            ).fetchone()
            if wallet and int(wallet["balance"] or 0) != 0:
                raise ValueError("企业钱包余额不为 0，仅允许停用（保留流水对账）")
            transactions = connection.execute(
                "SELECT COUNT(*) AS total FROM enterprise_credit_transactions WHERE enterprise_id = ?",
                (enterprise_id,),
            ).fetchone()
            if transactions and int(transactions["total"]) > 0:
                raise ValueError("企业存在积分流水，仅允许停用（保留流水对账）")
            connection.execute(
                "DELETE FROM enterprise_model_policies WHERE enterprise_id = ?", (enterprise_id,),
            )
            connection.execute(
                "DELETE FROM enterprise_member_quotas WHERE enterprise_id = ?", (enterprise_id,),
            )
            connection.execute(
                "DELETE FROM enterprise_credit_accounts WHERE enterprise_id = ?", (enterprise_id,),
            )
            connection.execute(
                "DELETE FROM enterprises WHERE id = ?", (enterprise_id,),
            )

    # ---------------- 企业成员额度 ----------------

    @staticmethod
    def _normalize_quota_period(period: Any) -> str:
        value = str(period or "none").strip().lower()
        if value not in {"none", "monthly", "total"}:
            raise ValueError(f"未知的额度周期：{value or '(空)'}")
        return value

    @staticmethod
    def _quota_month_start_iso() -> str:
        """北京时间自然月起点，转成与流水 created_at 相同的 UTC ISO 格式。"""
        local_now = datetime.now(timezone(timedelta(hours=8)))
        start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _member_net_consumed(
        connection: DbConnection, enterprise_id: str, user_id: str, *,
        month_start: str | None = None,
    ) -> int:
        sql = """SELECT COALESCE(SUM(CASE WHEN type = 'consume' THEN -delta
                    WHEN type = 'refund' THEN -delta ELSE 0 END), 0) AS net
            FROM enterprise_credit_transactions
            WHERE enterprise_id = ? AND user_id = ? AND type IN ('consume', 'refund')"""
        params: list[Any] = [enterprise_id, user_id]
        if month_start:
            sql += " AND created_at >= ?"
            params.append(month_start)
        row = connection.execute(sql, tuple(params)).fetchone()
        return max(0, int(row["net"])) if row else 0

    def get_enterprise_member_quota(self, enterprise_id: str, user_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM enterprise_member_quotas WHERE enterprise_id = ? AND user_id = ?",
                (enterprise_id, user_id),
            ).fetchone()
        if row is None:
            return {
                "enterprise_id": enterprise_id, "user_id": user_id,
                "period": "none", "credit_limit": 0, "updated_at": None,
            }
        return dict(row)

    def list_enterprise_member_quotas(self, enterprise_id: str) -> dict[str, dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM enterprise_member_quotas WHERE enterprise_id = ?", (enterprise_id,),
            ).fetchall()
        return {str(row["user_id"]): dict(row) for row in rows}

    def set_enterprise_member_quota(
        self, enterprise_id: str, user_id: str, *, period: str, credit_limit: int,
    ) -> dict[str, Any]:
        normalized = self._normalize_quota_period(period)
        limit = int(credit_limit or 0)
        if normalized == "none":
            limit = 0
        elif limit <= 0:
            raise ValueError("额度上限必须大于 0")
        if limit > MAX_CREDIT_AMOUNT:
            raise ValueError("额度上限超出账户可记录范围")
        timestamp = now()
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT 1 FROM enterprise_member_quotas WHERE enterprise_id = ? AND user_id = ?",
                (enterprise_id, user_id),
            ).fetchone()
            if existing:
                connection.execute(
                    """UPDATE enterprise_member_quotas SET period = ?, credit_limit = ?, updated_at = ?
                    WHERE enterprise_id = ? AND user_id = ?""",
                    (normalized, limit, timestamp, enterprise_id, user_id),
                )
            else:
                connection.execute(
                    """INSERT INTO enterprise_member_quotas
                    (enterprise_id, user_id, period, credit_limit, updated_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (enterprise_id, user_id, normalized, limit, timestamp),
                )
        return self.get_enterprise_member_quota(enterprise_id, user_id)

    def delete_enterprise_member_quota(self, enterprise_id: str, user_id: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM enterprise_member_quotas WHERE enterprise_id = ? AND user_id = ?",
                (enterprise_id, user_id),
            )

    def enterprise_member_consumed_in_month(self, enterprise_id: str) -> dict[str, int]:
        """按成员聚合北京时间当前自然月的净消耗（consume - refund）。"""
        month_start = self._quota_month_start_iso()
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT user_id,
                COALESCE(SUM(CASE WHEN type = 'consume' THEN -delta
                    WHEN type = 'refund' THEN -delta ELSE 0 END), 0) AS net
                FROM enterprise_credit_transactions
                WHERE enterprise_id = ? AND user_id IS NOT NULL
                  AND type IN ('consume', 'refund') AND created_at >= ?
                GROUP BY user_id""",
                (enterprise_id, month_start),
            ).fetchall()
        return {str(row["user_id"]): max(0, int(row["net"])) for row in rows}

    def _assert_enterprise_member_quota(
        self, connection: DbConnection, enterprise_id: str, user_id: str, amount: int, *,
        lock: bool = True,
    ) -> None:
        amount = int(amount)
        if amount <= 0:
            return
        row = connection.execute(
            "SELECT period, credit_limit FROM enterprise_member_quotas WHERE enterprise_id = ? AND user_id = ?",
            (enterprise_id, user_id),
        ).fetchone()
        if row is None:
            return
        period = self._normalize_quota_period(row["period"])
        limit = int(row["credit_limit"] or 0)
        if period not in {"monthly", "total"} or limit <= 0:
            return
        if lock:
            # 与企业钱包余额共用行锁，串行化同一企业的并发放扣。
            connection.execute(
                "SELECT balance FROM enterprise_credit_accounts WHERE enterprise_id = ?",
                (enterprise_id,), for_update=True,
            )
        used = self._member_net_consumed(
            connection, enterprise_id, user_id,
            month_start=self._quota_month_start_iso() if period == "monthly" else None,
        )
        if used + amount > limit:
            raise EnterpriseMemberQuotaExceededError(
                limit=limit, used=used, required=amount, period=period,
            )

    def check_member_quota(self, user_id: str, amount: int) -> None:
        """LLM/VLM 调用前的额度预检；未绑定企业或未配置额度时直接放行。"""
        enterprise_id = self.get_user_enterprise_id(user_id)
        if not enterprise_id:
            return
        with self.connection() as connection:
            self._assert_enterprise_member_quota(
                connection, enterprise_id, user_id, amount, lock=False,
            )

    def list_enterprise_members(self, enterprise_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            if not self._db.table_exists(connection, "users"):
                return []
            columns = self._db.column_names(connection, "users")
            if "enterprise_id" not in columns:
                return []
            rows = connection.execute(
                """SELECT id, username, display_name, role, is_active, email, created_at, last_login_at
                FROM users WHERE enterprise_id = ? ORDER BY created_at ASC""",
                (enterprise_id,),
            ).fetchall()
        members = []
        for row in rows:
            member = dict(row)
            member["is_active"] = bool(member.get("is_active"))
            members.append(member)
        return members

    def _ensure_enterprise_credit_account_row(
        self, connection: DbConnection, enterprise_id: str,
    ) -> Row | dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM enterprise_credit_accounts WHERE enterprise_id = ?", (enterprise_id,),
        ).fetchone()
        if row is None:
            connection.execute(
                """INSERT OR IGNORE INTO enterprise_credit_accounts
                (enterprise_id, balance, total_recharged, total_consumed, updated_at)
                VALUES (?, 0, 0, 0, ?)""",
                (enterprise_id, now()),
            )
            row = connection.execute(
                "SELECT * FROM enterprise_credit_accounts WHERE enterprise_id = ?", (enterprise_id,),
                for_update=True,
            ).fetchone()
        return row

    def get_or_create_enterprise_credit_account(self, enterprise_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = self._ensure_enterprise_credit_account_row(connection, enterprise_id)
        return dict(row)

    def _apply_enterprise_credit_delta(
        self, connection: DbConnection, enterprise_id: str, delta: int, *, type: str,
        spender_user_id: str | None = None, reason: str | None = None,
        price_key: str | None = None, ref_type: str | None = None, ref_id: str | None = None,
        actor_user_id: str | None = None, meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """在给定连接（事务）内变更企业钱包余额并落一条流水；语义与 _apply_credit_delta 一致。

        spender_user_id 记录消费/退款的实际使用人（成员用量统计依据）；
        充值/管理调整为 NULL（或操作人，由调用方传 actor_user_id）。
        """
        amount = abs(int(delta))
        timestamp = now()
        self._ensure_enterprise_credit_account_row(connection, enterprise_id)
        if amount:
            if type == "consume":
                connection.execute(
                    """UPDATE enterprise_credit_accounts SET balance = balance - ?,
                    total_consumed = total_consumed + ?, updated_at = ? WHERE enterprise_id = ?""",
                    (amount, amount, timestamp, enterprise_id),
                )
            elif type == "refund":
                connection.execute(
                    """UPDATE enterprise_credit_accounts SET balance = balance + ?,
                    total_consumed = CASE WHEN total_consumed > ? THEN total_consumed - ? ELSE 0 END,
                    updated_at = ? WHERE enterprise_id = ?""",
                    (amount, amount, amount, timestamp, enterprise_id),
                )
            elif type == "admin_recharge":
                connection.execute(
                    """UPDATE enterprise_credit_accounts SET balance = balance + ?,
                    total_recharged = total_recharged + ?, updated_at = ? WHERE enterprise_id = ?""",
                    (amount, amount, timestamp, enterprise_id),
                )
            else:  # admin_adjust 及未来扩展类型：仅变动余额，不动累计
                connection.execute(
                    "UPDATE enterprise_credit_accounts SET balance = balance + ?, updated_at = ? WHERE enterprise_id = ?",
                    (int(delta), timestamp, enterprise_id),
                )
        row = connection.execute(
            "SELECT * FROM enterprise_credit_accounts WHERE enterprise_id = ?", (enterprise_id,),
        ).fetchone()
        balance_after = int(row["balance"]) if row else 0
        connection.execute(
            """INSERT INTO enterprise_credit_transactions
            (enterprise_id, user_id, delta, type, reason, price_key, ref_type, ref_id,
             balance_after, actor_user_id, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                enterprise_id, spender_user_id, int(delta), type, reason, price_key,
                ref_type, ref_id, balance_after, actor_user_id,
                json.dumps(meta, ensure_ascii=False) if meta else None, timestamp,
            ),
        )
        return dict(row) if row is not None else {"enterprise_id": enterprise_id, "balance": balance_after}

    def adjust_enterprise_credit(
        self, enterprise_id: str, delta: int, *,
        reason: str, actor_user_id: str | None = None, request_id: str | None = None, type: str | None = None,
    ) -> dict[str, Any]:
        """企业钱包充值/调整入口（正负均可），type 为 admin_recharge / admin_adjust。"""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._record_admin_credit_change(
                connection, enterprise_id, delta, reason=reason,
                actor_user_id=actor_user_id, request_id=request_id, enterprise=True, type=type,
            )

    def list_enterprise_credit_transactions(
        self, enterprise_id: str, *, user_id: str | None = None, type: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self.connection() as connection:
            has_users = self._db.table_exists(connection, "users")
            sql = "SELECT t.*, " + ("u.username, u.display_name" if has_users else "NULL AS username, NULL AS display_name")
            if has_users:
                sql += " FROM enterprise_credit_transactions t LEFT JOIN users u ON u.id = t.user_id"
            else:
                sql += " FROM enterprise_credit_transactions t"
            conditions = ["t.enterprise_id = ?"]
            params: list[Any] = [enterprise_id]
            if user_id:
                conditions.append("t.user_id = ?")
                params.append(user_id)
            if type:
                conditions.append("t.type = ?")
                params.append(type)
            sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY t.created_at DESC, t.id DESC LIMIT ? OFFSET ?"
            params.extend([max(1, min(int(limit), 200)), max(0, int(offset))])
            rows = connection.execute(sql, tuple(params)).fetchall()
        return self._decode_credit_transaction_rows(rows)

    @staticmethod
    def _decode_credit_transaction_rows(rows: list[Row]) -> list[dict[str, Any]]:
        """流水附带的用量/成本明细存 JSON；读接口统一展开为 meta 对象。"""
        decoded: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            raw = data.pop("meta_json", None)
            if raw:
                try:
                    data["meta"] = json.loads(raw)
                except (TypeError, ValueError):
                    data["meta"] = None
            else:
                data["meta"] = None
            decoded.append(data)
        return decoded
        """企业下每个成员的积分用量统计：总消耗（含退款回冲口径见 refunded / net_consumed）。"""
        with self.connection() as connection:
            has_users = self._db.table_exists(connection, "users")
            if not has_users:
                return []
            rows = connection.execute(
                """SELECT t.user_id, u.username, u.display_name, u.role, u.is_active,
                COALESCE(SUM(CASE WHEN t.type = 'consume' THEN -t.delta ELSE 0 END), 0) AS gross_consumed,
                COALESCE(SUM(CASE WHEN t.type = 'refund' THEN t.delta ELSE 0 END), 0) AS refunded,
                COUNT(t.id) AS tx_count,
                MAX(t.created_at) AS last_active_at
                FROM enterprise_credit_transactions t
                LEFT JOIN users u ON u.id = t.user_id
                WHERE t.enterprise_id = ? AND t.user_id IS NOT NULL
                GROUP BY t.user_id, u.username, u.display_name, u.role, u.is_active""",
                (enterprise_id,),
            ).fetchall()
        usage = []
        for row in rows:
            item = dict(row)
            item["is_active"] = bool(item.get("is_active"))
            item["net_consumed"] = int(item["gross_consumed"]) - int(item["refunded"])
            usage.append(item)
        usage.sort(key=lambda entry: (-int(entry["net_consumed"]), str(entry["user_id"])))
        return usage

    def enterprise_usage_by_price_key(self, enterprise_id: str) -> list[dict[str, Any]]:
        """按计价条目（模型/能力）聚合企业净消耗，供企业用量看板使用。"""
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT t.price_key,
                COALESCE(SUM(CASE WHEN t.type = 'consume' THEN -t.delta WHEN t.type = 'refund' THEN -t.delta ELSE 0 END), 0) AS net_consumed,
                COUNT(t.id) AS tx_count
                FROM enterprise_credit_transactions t
                WHERE t.enterprise_id = ? AND t.price_key IS NOT NULL AND t.type IN ('consume', 'refund')
                GROUP BY t.price_key""",
                (enterprise_id,),
            ).fetchall()
        usage = [dict(row) for row in rows]
        usage.sort(key=lambda entry: (-int(entry["net_consumed"]), str(entry["price_key"])))
        return usage

    def get_enterprise_model_policies(self, enterprise_id: str) -> dict[str, dict[str, Any]]:
        """企业模型访问策略：{model_kind: {"mode": all|whitelist|none, "models": [...]}}；未配置类型不在结果中。"""
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT model_kind, mode, models_json FROM enterprise_model_policies WHERE enterprise_id = ?",
                (enterprise_id,),
            ).fetchall()
        policies: dict[str, dict[str, Any]] = {}
        for row in rows:
            raw = row["models_json"]
            try:
                models = json.loads(raw) if raw else []
            except (TypeError, ValueError):
                models = []
            if not isinstance(models, list):
                models = []
            policies[str(row["model_kind"])] = {
                "mode": str(row["mode"] or "all"),
                "models": [str(item) for item in models],
            }
        return policies

    def set_enterprise_model_policies(
        self, enterprise_id: str, policies: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """整表覆盖式保存企业模型策略；model_kind/mode 校验失败抛 ValueError。"""
        from .enterprise_service import MODEL_KINDS, POLICY_MODES

        normalized: dict[str, dict[str, Any]] = {}
        for item in policies:
            kind = str((item or {}).get("model_kind") or "").strip()
            mode = str((item or {}).get("mode") or "").strip()
            if kind not in MODEL_KINDS:
                raise ValueError(f"未知的模型类型：{kind or '(空)'}")
            if mode not in POLICY_MODES:
                raise ValueError(f"未知的开放模式：{mode or '(空)'}")
            models = (item or {}).get("models") or []
            if not isinstance(models, list):
                raise ValueError("模型清单必须为数组")
            normalized[kind] = {
                "mode": mode,
                "models": sorted({str(key).strip() for key in models if str(key).strip()}),
            }
        timestamp = now()
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM enterprise_model_policies WHERE enterprise_id = ?", (enterprise_id,),
            )
            for kind, payload in normalized.items():
                connection.execute(
                    """INSERT INTO enterprise_model_policies
                    (enterprise_id, model_kind, mode, models_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        enterprise_id, kind, payload["mode"],
                        json.dumps(payload["models"], ensure_ascii=False), timestamp,
                    ),
                )
        return self.get_enterprise_model_policies(enterprise_id)

    def list_credit_accounts(self, query: str | None = None, limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
        with self.connection() as connection:
            has_users = self._db.table_exists(connection, "users")
            params: list[Any] = []
            if has_users:
                sql = """SELECT u.id AS user_id, u.username, u.display_name, u.role, u.is_active,
                    CASE WHEN e.id IS NULL THEN COALESCE(a.balance, 0) ELSE COALESCE(w.balance, 0) END AS balance,
                    CASE WHEN e.id IS NULL THEN COALESCE(a.total_recharged, 0) ELSE COALESCE(w.total_recharged, 0) END AS total_recharged,
                    CASE WHEN e.id IS NULL THEN COALESCE(a.total_consumed, 0) ELSE COALESCE(w.total_consumed, 0) END AS total_consumed,
                    COALESCE(CASE WHEN e.id IS NULL THEN a.updated_at ELSE w.updated_at END, u.created_at) AS updated_at,
                    e.id AS enterprise_id, e.name AS enterprise_name, e.status AS enterprise_status, e.code AS enterprise_code
                FROM users u
                LEFT JOIN credit_accounts a ON a.user_id = u.id
                LEFT JOIN enterprises e ON e.id = u.enterprise_id
                LEFT JOIN enterprise_credit_accounts w ON w.enterprise_id = e.id"""
                if query and (query := query.strip()):
                    sql += " WHERE (u.username LIKE ? OR u.display_name LIKE ? OR e.name LIKE ? OR u.id = ?)"
                    params.extend([f"%{query}%"] * 3 + [query])
                sql += " ORDER BY u.username ASC, u.id ASC"
            else:
                sql = "SELECT * FROM credit_accounts ORDER BY user_id ASC"
            sql += " LIMIT ? OFFSET ?"
            params.extend([max(1, min(int(limit), 1000)), max(0, int(offset))])
            rows = connection.execute(sql, tuple(params)).fetchall()
        accounts = [dict(row) for row in rows]
        for account in accounts:
            enterprise_id = account.pop("enterprise_id", None)
            enterprise = {
                "id": enterprise_id, "name": account.pop("enterprise_name", None),
                "status": account.pop("enterprise_status", None), "code": account.pop("enterprise_code", None),
            }
            account.update(scope="enterprise" if enterprise_id else "user", enterprise=enterprise if enterprise_id else None)
        return accounts

    def list_credit_usage_transactions(
        self, *, start_at: str, end_at: str, scope: str = "all",
    ) -> list[dict[str, Any]]:
        """消费与退款流水（含个人/企业钱包），供管理端用量毛利报表聚合。"""
        if scope not in {"user", "enterprise", "all"}:
            raise ValueError(f"未知的钱包范围：{scope}")
        with self.connection() as connection:
            has_users = self._db.table_exists(connection, "users")
            user_fields = "u.username, u.display_name" if has_users else "NULL AS username, NULL AS display_name"
            joins = " LEFT JOIN users u ON u.id = t.user_id" if has_users else ""
            sources: list[str] = []
            params: list[Any] = []
            if scope in {"user", "all"}:
                sources.append(
                    "SELECT t.id, t.user_id, t.delta, t.type, t.price_key, t.ref_type, t.ref_id, "
                    "t.meta_json, t.created_at, 'user' AS scope, NULL AS enterprise_id, "
                    f"NULL AS enterprise_name, {user_fields} FROM credit_transactions t{joins} "
                    "WHERE t.type IN ('consume', 'refund') AND t.created_at >= ? AND t.created_at < ?"
                )
                params.extend([start_at, end_at])
            if scope in {"enterprise", "all"}:
                sources.append(
                    "SELECT t.id, t.user_id, t.delta, t.type, t.price_key, t.ref_type, t.ref_id, "
                    "t.meta_json, t.created_at, 'enterprise' AS scope, t.enterprise_id, "
                    f"e.name AS enterprise_name, {user_fields} FROM enterprise_credit_transactions t{joins} "
                    "LEFT JOIN enterprises e ON e.id = t.enterprise_id "
                    "WHERE t.type IN ('consume', 'refund') AND t.created_at >= ? AND t.created_at < ?"
                )
                params.extend([start_at, end_at])
            sql = " UNION ALL ".join(sources) + " ORDER BY 9 ASC, 1 ASC"
            rows = connection.execute(sql, tuple(params)).fetchall()
        return self._decode_credit_transaction_rows(rows)

    def list_credit_transactions(
        self, *, user_id: str | None = None, type: str | None = None,
        ref_type: str | None = None, ref_id: str | None = None,
        limit: int = 50, offset: int = 0, scope: str = "user", query: str | None = None,
        include_actor: bool = False,
    ) -> list[dict[str, Any]]:
        with self.connection() as connection:
            has_users = self._db.table_exists(connection, "users")
            conditions: list[str] = []
            params: list[Any] = []
            for column, value in (("user_id", user_id), ("type", type), ("ref_type", ref_type), ("ref_id", ref_id)):
                if value:
                    conditions.append(f"t.{column} = ?")
                    params.append(value)
            fields = """t.id AS id, t.user_id, t.delta, t.type, t.reason, t.price_key, t.ref_type, t.ref_id,
                t.balance_after, t.actor_user_id, t.meta_json, t.created_at AS created_at"""
            user_names = "u.username, u.display_name" if has_users else "NULL AS username, NULL AS display_name"
            actor_name = "actor.username AS actor_username" if has_users and include_actor else "NULL AS actor_username"
            joins = " LEFT JOIN users u ON u.id = t.user_id" if has_users else ""
            if has_users and include_actor:
                joins += " LEFT JOIN users actor ON actor.id = t.actor_user_id"
            sources: list[str] = []
            all_params: list[Any] = []
            for ledger in ("user", "enterprise"):
                if scope not in {ledger, "all"}:
                    continue
                enterprise = ledger == "enterprise"
                table = "enterprise_credit_transactions" if enterprise else "credit_transactions"
                wallet = "t.enterprise_id, e.name AS enterprise_name" if enterprise else "NULL AS enterprise_id, NULL AS enterprise_name"
                sql = f"SELECT {fields}, {user_names}, {actor_name}, '{ledger}' AS scope, {wallet} FROM {table} t{joins}"
                if enterprise:
                    sql += " LEFT JOIN enterprises e ON e.id = t.enterprise_id"
                filters = list(conditions)
                all_params.extend(params)
                if query and (keyword := query.strip()):
                    search_fields = ["t.ref_id", "t.price_key"]
                    if has_users:
                        search_fields += ["u.username", "u.display_name"]
                    if enterprise:
                        search_fields.append("e.name")
                    filters.append("(" + " OR ".join(f"{column} LIKE ?" for column in search_fields) + " OR t.user_id = ?)")
                    all_params.extend([f"%{keyword}%"] * len(search_fields) + [keyword])
                if filters:
                    sql += " WHERE " + " AND ".join(filters)
                sources.append(sql)
            sql = " UNION ALL ".join(sources) + " ORDER BY created_at DESC, id DESC, scope ASC LIMIT ? OFFSET ?"
            all_params.extend([max(1, min(int(limit), 200)), max(0, int(offset))])
            rows = connection.execute(sql, tuple(all_params)).fetchall()
        return self._decode_credit_transaction_rows(rows)

    @staticmethod
    def _decode_credit_price_rule(row: Row) -> dict[str, Any]:
        data = dict(row)

        def _loads(raw: Any) -> Any:
            if not raw:
                return None
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return None

        data["unit_by_variant"] = _loads(data.get("unit_by_variant"))
        data["extra_config"] = _loads(data.get("extra_config"))
        data["enabled"] = bool(data.get("enabled"))
        return data

    def list_credit_price_rules(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM credit_price_rules ORDER BY scope ASC, rule_key ASC",
            ).fetchall()
        return [self._decode_credit_price_rule(row) for row in rows]

    def get_credit_price_rule(self, rule_key: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM credit_price_rules WHERE rule_key = ?", (rule_key,),
            ).fetchone()
        return self._decode_credit_price_rule(row) if row else None

    def update_credit_price_rules(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """管理端覆盖价格：只接受白名单字段；rule_key 不存在的行报错。"""
        allowed = {"unit_credits", "unit_by_variant", "extra_config", "enabled", "note"}
        keys = sorted({rule["rule_key"] for rule in rules})
        if len(keys) != len(rules):
            raise ValueError("同一计价条目只能更新一次")
        if not keys:
            return self.list_credit_price_rules()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            placeholders = ", ".join("?" for _ in keys)
            existing = {
                row["rule_key"]: row["updated_at"] for row in connection.execute(
                    f"SELECT rule_key, updated_at FROM credit_price_rules WHERE rule_key IN ({placeholders}) ORDER BY rule_key",
                    tuple(keys), for_update=True,
                ).fetchall()
            }
            unknown = [rule.get("rule_key") for rule in rules if rule.get("rule_key") not in existing]
            if unknown:
                raise ValueError(f"计价条目不存在: {unknown[0]}")
            timestamp = now()
            for rule in rules:
                expected = rule.get("expected_updated_at")
                if expected is not None and expected != existing[rule["rule_key"]]:
                    raise CreditPriceConflictError(f"{rule['rule_key']} 的价格已被更新，请载入最新价格后重新修改")
                updates: dict[str, Any] = {"updated_at": timestamp}
                for field in allowed:
                    if field not in rule or rule[field] is None:
                        continue  # None = 局部更新时不改动该字段
                    value = rule[field]
                    if field in {"unit_by_variant", "extra_config"} and value is not None:
                        value = json.dumps(value, ensure_ascii=False)
                    elif field == "enabled":
                        value = 1 if value else 0
                    elif field == "unit_credits":
                        value = max(0, int(value))
                    updates[field] = value
                assignment = ", ".join(f"{column} = ?" for column in updates)
                connection.execute(
                    f"UPDATE credit_price_rules SET {assignment} WHERE rule_key = ?",
                    (*updates.values(), rule["rule_key"]),
                )
        return self.list_credit_price_rules()

    def claim_generation(self, generation_item_id: str, *, stage: str, progress: int) -> bool:
        """Atomically move one queued generation item to running.

        Returns False when the item was already claimed, finished or cancelled,
        so workers sharing one database never submit the same item twice.
        """
        with self.connection() as connection:
            cursor = connection.execute(
                """UPDATE generation_items SET status = ?, stage = ?, progress = ?, updated_at = ?
                   WHERE id = ? AND status = ? AND cancel_requested = 0""",
                (
                    JobStatus.RUNNING.value,
                    stage,
                    max(0, min(100, int(progress))),
                    now(),
                    generation_item_id,
                    JobStatus.QUEUED.value,
                ),
            )
            claimed = int(getattr(cursor, "rowcount", 0) or 0) > 0
            if claimed:
                row = connection.execute(
                    """SELECT i.round_id, r.job_id FROM generation_items i
                       JOIN job_rounds r ON r.id = i.round_id WHERE i.id = ?""",
                    (generation_item_id,),
                ).fetchone()
                if row is not None:
                    self._refresh_round(connection, row["round_id"])
                    self._refresh_job(connection, row["job_id"])
        return claimed

    def with_statuses(self, *statuses: JobStatus) -> list[dict]:
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at ASC",
                tuple(status.value for status in statuses),
            ).fetchall()
            return self._hydrate_job_rows(connection, rows, include_references=True)

    def recoverable_generation_items(self, executor: str) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT i.* FROM generation_items i
                WHERE i.executor = ? AND i.status IN (?, ?) ORDER BY i.created_at""",
                (executor, JobStatus.QUEUED.value, JobStatus.RUNNING.value),
            ).fetchall()
        return [self._decode_generation(row) for row in rows]

    @staticmethod
    def _decode_outputs(value: Any) -> list[dict]:
        if isinstance(value, list):
            outputs = value
        else:
            outputs = json.loads(value or "[]")
        for output in outputs:
            if isinstance(output, dict):
                output.setdefault("delivery_status", "pending")
                output.setdefault("delivered_at", None)
        return outputs

    @classmethod
    def _decode_generation(cls, row: Row, *, include_refine_state: bool = True) -> dict:
        data = dict(row)
        data["index"] = data.pop("item_index")
        data["outputs"] = cls._decode_outputs(data.pop("outputs_json"))
        raw_refine_state = data.pop("refine_state_json", None)
        data["refine_state"] = {}
        if include_refine_state:
            try:
                data["refine_state"] = json.loads(raw_refine_state) if raw_refine_state else {}
            except (TypeError, ValueError):
                data["refine_state"] = {}
        data["cancel_requested"] = bool(data.get("cancel_requested") or 0)
        return data

    def _rounds_for_job(
        self, connection: DbConnection, job_id: str, include_references: bool,
        *, include_refine_state: bool = True,
    ) -> list[dict]:
        return self._rounds_for_jobs(
            connection, [job_id], include_references, include_refine_state=include_refine_state,
        ).get(job_id, [])

    def _rounds_for_jobs(
        self, connection: DbConnection, job_ids: list[str], include_references: bool,
        *, include_refine_state: bool = True,
    ) -> dict[str, list[dict]]:
        rounds_by_job = {job_id: [] for job_id in job_ids}
        if not job_ids:
            return rounds_by_job
        placeholders = ",".join("?" * len(job_ids))
        round_rows = connection.execute(
            f"SELECT * FROM job_rounds WHERE job_id IN ({placeholders}) ORDER BY sequence",
            tuple(job_ids),
        ).fetchall()
        round_ids = [str(row["id"]) for row in round_rows]
        items_by_round: dict[str, list[dict]] = {round_id: [] for round_id in round_ids}
        if round_ids:
            item_placeholders = ",".join("?" * len(round_ids))
            item_rows = connection.execute(
                f"SELECT * FROM generation_items WHERE round_id IN ({item_placeholders}) ORDER BY item_index",
                tuple(round_ids),
            ).fetchall()
            for item in item_rows:
                items_by_round[str(item["round_id"])].append(
                    self._decode_generation(item, include_refine_state=include_refine_state)
                )
        for row in round_rows:
            data = dict(row)
            job_id = str(data["job_id"])
            refs = json.loads(data.pop("references_json") or "[]")
            data["options"] = json.loads(data.pop("options_json") or "{}")
            data["submitted_options"] = json.loads(data.pop("submitted_options_json") or "{}")
            data["options_submitted"] = bool(data.pop("options_submitted", False))
            data["reference_count"] = len(refs)
            if include_references:
                data["references"] = refs
            data["generation_items"] = items_by_round.get(str(data["id"]), [])
            rounds_by_job.setdefault(job_id, []).append(data)
        return rounds_by_job

    def _hydrate_job_rows(
        self, connection: DbConnection, rows: list[Row], *, include_references: bool = False,
        include_refine_state: bool = True,
    ) -> list[dict]:
        job_ids = [str(row["id"]) for row in rows]
        rounds_by_job = self._rounds_for_jobs(
            connection, job_ids, include_references, include_refine_state=include_refine_state,
        )
        jobs: list[dict] = []
        for row in rows:
            job = self.decode(
                row,
                include_references=include_references,
                connection=connection,
                rounds=rounds_by_job.get(str(row["id"]), []),
            )
            jobs.append(job)
        return jobs

    def decode(
        self,
        row: Row,
        *,
        include_references: bool = False,
        connection: DbConnection | None = None,
        rounds: list[dict] | None = None,
    ) -> dict:
        data = dict(row)
        refs = json.loads(data.pop("references_json") or "[]")
        data["options"] = json.loads(data.pop("options_json", "{}") or "{}")
        data["submitted_options"] = json.loads(data.pop("submitted_options_json", "{}") or "{}")
        data["options_submitted"] = bool(data.pop("options_submitted", False))
        data["legacy_read_only"] = bool(data.get("legacy_read_only", False))
        data["pinned"] = bool(data.get("pinned", False))
        data["outputs"] = self._decode_outputs(data.pop("outputs_json") or "[]")
        data["reference_count"] = len(refs)
        if include_references:
            data["references"] = refs
        owns_connection = connection is None
        active = connection or self.connection()
        try:
            if rounds is None:
                data["rounds"] = self._rounds_for_job(active, data["id"], include_references)
            else:
                data["rounds"] = rounds
        finally:
            if owns_connection:
                active.close()
        if data.get("source_job_id"):
            data["source"] = {
                "job_id": data["source_job_id"],
                "generation_item_id": data.get("source_generation_item_id"),
                "output_index": data.get("source_output_index"),
            }
        else:
            data["source"] = None
        return data

    def get(self, job_id: str, *, include_references: bool = False) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return self.decode(row, include_references=include_references, connection=connection)

    def get_generation(self, generation_item_id: str) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM generation_items WHERE id = ?", (generation_item_id,)).fetchone()
        if row is None:
            raise KeyError(generation_item_id)
        return self._decode_generation(row)

    def generation_context(self, generation_item_id: str) -> dict:
        with self.connection() as connection:
            row = connection.execute(
                """SELECT i.*, r.job_id, r.mode, r.media_type, r.prompt, r.negative_prompt,
                r.image_size, r.options_json, r.references_json, j.owner_user_id
                FROM generation_items i JOIN job_rounds r ON r.id = i.round_id
                JOIN jobs j ON j.id = r.job_id WHERE i.id = ?""",
                (generation_item_id,),
            ).fetchone()
        if row is None:
            raise KeyError(generation_item_id)
        data = self._decode_generation(row)
        data["options"] = json.loads(data.pop("options_json") or "{}")
        data["references"] = json.loads(data.pop("references_json") or "[]")
        return data

    def list(self, limit: int = 100) -> list[dict]:
        with self.connection() as connection:
            id_rows = connection.execute(
                "SELECT id FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,),
            ).fetchall()
            return self._hydrate_job_rows(
                connection,
                self._job_rows_by_ids(connection, [str(row["id"]) for row in id_rows]),
                include_refine_state=False,
            )

    def list_jobs(
        self, user_id: str | None = None, limit: int = 100, *, include_refine_state: bool = False,
    ) -> list[dict]:
        with self.connection() as connection:
            if user_id is not None:
                id_rows = connection.execute(
                    """SELECT id FROM jobs WHERE owner_user_id = ?
                    ORDER BY pinned DESC, created_at DESC LIMIT ?""",
                    (user_id, limit),
                ).fetchall()
            else:
                id_rows = connection.execute(
                    "SELECT id FROM jobs ORDER BY pinned DESC, created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            job_ids = [str(row["id"]) for row in id_rows]
            return self._hydrate_job_rows(
                connection,
                self._job_rows_by_ids(connection, job_ids),
                include_refine_state=include_refine_state,
            )

    def list_library_sources(self, user_id: str | None = None, limit: int = 500) -> list[dict]:
        """Return only the job/round/output fields needed by the media library.

        The full job graph carries option schemas, references and continuation
        state that the library never reads; hydrating hundreds of those rows is
        the main cost of library paging.
        """
        owner_clause = "WHERE owner_user_id = ?" if user_id is not None else ""
        parameters: tuple[Any, ...] = (user_id, limit) if user_id is not None else (limit,)
        with self.connection() as connection:
            rows = connection.execute(
                f"""SELECT j.id AS job_id, j.title, j.prompt,
                    r.id AS round_id, r.created_at AS round_created_at,
                    i.id AS item_id, i.outputs_json
                FROM (
                    SELECT id, title, prompt, pinned, created_at
                    FROM jobs {owner_clause}
                    ORDER BY pinned DESC, created_at DESC
                    LIMIT ?
                ) j
                JOIN job_rounds r ON r.job_id = j.id
                JOIN generation_items i ON i.round_id = r.id
                ORDER BY j.pinned DESC, j.created_at DESC, r.sequence, i.item_index""",
                parameters,
            ).fetchall()
        jobs_by_id: dict[str, dict] = {}
        rounds_by_key: dict[tuple[str, str], dict] = {}
        ordered: list[dict] = []
        for row in rows:
            job_id = str(row["job_id"])
            job = jobs_by_id.get(job_id)
            if job is None:
                job = {
                    "id": job_id,
                    "title": row["title"],
                    "prompt": row["prompt"] or "",
                    "rounds": [],
                }
                jobs_by_id[job_id] = job
                ordered.append(job)
            round_id = str(row["round_id"])
            round_key = (job_id, round_id)
            round_data = rounds_by_key.get(round_key)
            if round_data is None:
                round_data = {
                    "id": round_id,
                    "created_at": row["round_created_at"],
                    "generation_items": [],
                }
                rounds_by_key[round_key] = round_data
                job["rounds"].append(round_data)
            round_data["generation_items"].append({
                "id": str(row["item_id"]),
                "outputs": self._decode_outputs(row["outputs_json"] or "[]"),
            })
        return ordered

    def output_locations(self, user_id: str | None = None, limit: int = 1000) -> dict[str, dict]:
        """Map output paths to their stored output records for media previews."""
        owner_clause = "WHERE owner_user_id = ?" if user_id is not None else ""
        parameters: tuple[Any, ...] = (user_id, limit) if user_id is not None else (limit,)
        with self.connection() as connection:
            rows = connection.execute(
                f"""SELECT i.outputs_json
                FROM (
                    SELECT id FROM jobs {owner_clause}
                    ORDER BY pinned DESC, created_at DESC
                    LIMIT ?
                ) j
                JOIN job_rounds r ON r.job_id = j.id
                JOIN generation_items i ON i.round_id = r.id""",
                parameters,
            ).fetchall()
        locations: dict[str, dict] = {}
        for row in rows:
            for output in self._decode_outputs(row["outputs_json"] or "[]"):
                path = str(output.get("path") or "")
                if path and path not in locations:
                    locations[path] = output
        return locations

    def content_epoch(self) -> int:
        return self._content_epoch

    def _bump_content_epoch(self) -> None:
        with self._content_epoch_lock:
            self._content_epoch += 1

    def _job_rows_by_ids(self, connection: DbConnection, job_ids: list[str]) -> list[Row]:
        if not job_ids:
            return []
        placeholders = ",".join("?" * len(job_ids))
        rows = connection.execute(
            f"SELECT * FROM jobs WHERE id IN ({placeholders})",
            tuple(job_ids),
        ).fetchall()
        by_id = {str(row["id"]): row for row in rows}
        return [by_id[job_id] for job_id in job_ids if job_id in by_id]

    def update_metadata(
        self, job_id: str, *, title: str | None = None, pinned: bool | None = None, update_title: bool = False,
    ) -> dict:
        updates: list[str] = []
        values: list[Any] = []
        if update_title:
            updates.append("title = ?")
            values.append(title.strip() if title and title.strip() else None)
        if pinned is not None:
            updates.append("pinned = ?")
            values.append(1 if pinned else 0)
        if not updates:
            return self.get(job_id)
        values.extend([now(), job_id])
        with self.connection() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {', '.join(updates)}, updated_at = ? WHERE id = ?",
                tuple(values),
            )
            if cursor.rowcount == 0:
                raise KeyError(job_id)
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            result = self.decode(row, connection=connection)
        self._bump_content_epoch()
        return result

    def job_media_in_use(self, job_id: str, keys: list[str], connection: DbConnection) -> bool:
        sources = {
            "jobs": ("source_job_id", "references_json", "outputs_json", "options_json", "submitted_options_json"),
            "job_rounds": ("references_json", "options_json", "submitted_options_json"),
            "generation_items": ("outputs_json", "refine_state_json"),
            "director_projects": ("payload_json",),
            "director_library_assets": ("image_job_id", "image_path", "image_url"),
            "director_operations": ("request_json", "result_json"),
            "canvas_projects": ("preview_json",),
            "canvas_drafts": ("content",),
            "canvas_draft_versions": ("content",),
            "ai_projects": ("cover_url", "settings_json"),
            "ai_project_documents": ("analysis_json",),
            "ai_project_assets": ("image_url", "extra_json"),
            "ai_project_episodes": ("data_json",),
            "ai_project_jobs": ("result_url", "payload_json"),
            "ai_smart_edit_documents": ("document_json",),
            "ai_featured_works": ("cover_url", "snapshot_json"),
            "ai_featured_music": ("result_url", "cover_url"),
            "ai_showcase_items": ("source_job_id", "cover_url", "media_url", "references_json", "options_json"),
        }
        exclusions = {
            "jobs": "id <> ?",
            "job_rounds": "job_id <> ?",
            "generation_items": "round_id NOT IN (SELECT id FROM job_rounds WHERE job_id = ?)",
        }
        needles = {job_id}
        for key in keys:
            for value in (key, quote(key, safe="/"), json.dumps(key, ensure_ascii=True)[1:-1]):
                needles.add(value)
                needles.add(value.replace("/", "\\/"))
        ordered = sorted(needles)
        for table, columns in sources.items():
            if not self._db.table_exists(connection, table):
                continue
            # 只检索已知媒体字段；不把日志、审计里的历史任务 ID 当成使用引用。
            for start in range(0, len(ordered), 64):
                batch = ordered[start:start + 64]
                clauses = [f"INSTR({column}, ?) > 0" for column in columns for _ in batch]
                parameters = [needle for _ in columns for needle in batch]
                exclusion = exclusions.get(table)
                if exclusion:
                    parameters.append(job_id)
                match = connection.execute(
                    f"SELECT 1 FROM {table} WHERE ({' OR '.join(clauses)})"
                    + (f" AND {exclusion}" if exclusion else "") + " LIMIT 1",
                    tuple(parameters),
                ).fetchone()
                if match is not None:
                    return True
        return False

    def delete(
        self, job_id: str, *, before_commit: Callable[[dict, DbConnection], None] | None = None,
    ) -> bool:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,), for_update=True).fetchone()
            if row is None:
                return False
            job = self.decode(row, connection=connection) if before_commit is not None else None
            # 先取得级联删除的全部行锁，让锁冲突发生在不可回滚的云端清理之前。
            cursor = connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            if before_commit is not None:
                before_commit(job, connection)
        if cursor.rowcount > 0:
            self._bump_content_epoch()
        return cursor.rowcount > 0

    def assign_unowned(self, user_id: str) -> int:
        with self.connection() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET owner_user_id = ?, updated_at = ? WHERE owner_user_id IS NULL", (user_id, now())
            )
        if cursor.rowcount > 0:
            self._bump_content_epoch()
        return cursor.rowcount

    def mark_output_delivered(self, job_id: str, output_index: int, delivered_at: str, status: str = "local") -> dict:
        job = self.get(job_id)
        latest = job["rounds"][-1]
        remaining = output_index
        for item in latest["generation_items"]:
            if remaining < len(item["outputs"]):
                self.mark_generation_output_delivered(item["id"], remaining, delivered_at, status)
                return self.get(job_id)
            remaining -= len(item["outputs"])
        raise IndexError(output_index)

    def mark_generation_output_delivered(
        self, generation_item_id: str, output_index: int, delivered_at: str, status: str = "local",
    ) -> dict:
        item = self.get_generation(generation_item_id)
        outputs = item["outputs"]
        if output_index < 0 or output_index >= len(outputs):
            raise IndexError(output_index)
        outputs[output_index]["delivery_status"] = status
        outputs[output_index]["delivered_at"] = delivered_at
        return self.update_generation(generation_item_id, outputs=outputs)

    def get_grs_settings(self) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM grs_provider_settings WHERE id = 1").fetchone()
        data = dict(row)
        for name in ("enabled", "gpt_image_2_enabled", "gpt_image_2_vip_enabled"):
            data[name] = bool(data[name])
        return data

    def update_grs_settings(self, **values: Any) -> dict:
        allowed = {
            "enabled", "base_url", "api_key_encrypted", "gpt_image_2_enabled", "gpt_image_2_vip_enabled",
            "models", "vip_models",
            "last_test_status", "last_test_message", "last_test_at", "last_balance", "last_balance_at",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(f"UPDATE grs_provider_settings SET {assignment} WHERE id = 1", tuple(updates.values()))
        return self.get_grs_settings()

    def get_qiniu_settings(self) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM qiniu_provider_settings WHERE id = 1").fetchone()
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        return data

    def update_qiniu_settings(self, values: dict | None = None, **kwargs: Any) -> dict:
        allowed = {
            "enabled", "access_key_encrypted", "secret_key_encrypted", "bucket", "region", "domain", "object_prefix",
            "last_test_status", "last_test_message", "last_test_at",
        }
        merged = dict(values) if isinstance(values, dict) else {}
        merged.update(kwargs)
        updates = {key: value for key, value in merged.items() if key in allowed}
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(f"UPDATE qiniu_provider_settings SET {assignment} WHERE id = 1", tuple(updates.values()))
        return self.get_qiniu_settings()

    def get_llm_settings(self) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM llm_provider_settings WHERE id = 1").fetchone()
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        return data

    def update_llm_settings(self, values: dict | None = None, **kwargs: Any) -> dict:
        allowed = {
            "enabled", "base_url", "api_key_encrypted", "model", "assistant_models_json",
            "last_test_status", "last_test_message", "last_test_at",
        }
        merged = dict(values) if isinstance(values, dict) else {}
        merged.update(kwargs)
        updates = {key: value for key, value in merged.items() if key in allowed}
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(f"UPDATE llm_provider_settings SET {assignment} WHERE id = 1", tuple(updates.values()))
        return self.get_llm_settings()

    def get_llm_endpoint_credential(self, base_url: str) -> dict | None:
        endpoint = str(base_url or "").strip().rstrip("/")
        if not endpoint:
            return None
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM llm_endpoint_credentials WHERE base_url = ?", (endpoint,)
            ).fetchone()
        return dict(row) if row else None

    def upsert_llm_endpoint_credential(self, base_url: str, api_key_encrypted: str, model: str) -> dict:
        endpoint = str(base_url or "").strip().rstrip("/")
        if not endpoint:
            raise ValueError("LLM 端点凭据档案需要有效的 Base URL")
        stamp = now()
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT base_url FROM llm_endpoint_credentials WHERE base_url = ?", (endpoint,)
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE llm_endpoint_credentials SET api_key_encrypted = ?, model = ?, updated_at = ? "
                    "WHERE base_url = ?",
                    (api_key_encrypted, str(model or ""), stamp, endpoint),
                )
            else:
                connection.execute(
                    "INSERT INTO llm_endpoint_credentials (base_url, api_key_encrypted, model, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (endpoint, api_key_encrypted, str(model or ""), stamp),
                )
        return self.get_llm_endpoint_credential(endpoint)  # type: ignore[return-value]

    def list_llm_endpoint_credentials(self) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM llm_endpoint_credentials ORDER BY updated_at DESC, base_url ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_vlm_settings(self) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM vlm_provider_settings WHERE id = 1").fetchone()
        if not row:
            return {
                "id": 1,
                "enabled": False,
                "use_llm_credentials": False,
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "api_key_encrypted": None,
                "model": "glm-4v-flash",
                "last_test_status": None,
                "last_test_message": None,
                "last_test_at": None,
                "updated_at": now(),
            }
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        data["use_llm_credentials"] = bool(data.get("use_llm_credentials", 0))
        return data

    def update_vlm_settings(self, values: dict | None = None, **kwargs: Any) -> dict:
        allowed = {
            "enabled", "use_llm_credentials", "base_url", "api_key_encrypted", "model",
            "last_test_status", "last_test_message", "last_test_at",
        }
        merged = dict(values) if isinstance(values, dict) else {}
        merged.update(kwargs)
        updates = {key: value for key, value in merged.items() if key in allowed}
        if "use_llm_credentials" in updates:
            updates["use_llm_credentials"] = int(bool(updates["use_llm_credentials"]))
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(f"UPDATE vlm_provider_settings SET {assignment} WHERE id = 1", tuple(updates.values()))
        return self.get_vlm_settings()

    def get_tts_settings(self) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM tts_provider_settings WHERE id = 1").fetchone()
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        data["use_llm_credentials"] = bool(data.get("use_llm_credentials", 1))
        return data

    def update_tts_settings(self, values: dict | None = None, **kwargs: Any) -> dict:
        allowed = {
            "enabled", "use_llm_credentials", "base_url", "api_key_encrypted", "model", "voice",
            "last_test_status", "last_test_message", "last_test_at",
        }
        merged = dict(values) if isinstance(values, dict) else {}
        merged.update(kwargs)
        updates = {key: value for key, value in merged.items() if key in allowed}
        if "enabled" in updates:
            updates["enabled"] = int(bool(updates["enabled"]))
        if "use_llm_credentials" in updates:
            updates["use_llm_credentials"] = int(bool(updates["use_llm_credentials"]))
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(f"UPDATE tts_provider_settings SET {assignment} WHERE id = 1", tuple(updates.values()))
        return self.get_tts_settings()

    def get_music_settings(self) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM music_provider_settings WHERE id = 1").fetchone()
        if not row:
            return {
                "id": 1,
                "base_url": "http://192.168.10.54:8791",
                "access_key_encrypted": None,
                "last_test_status": None,
                "last_test_message": None,
                "last_test_at": None,
                "updated_at": now(),
            }
        return dict(row)

    def update_music_settings(self, values: dict | None = None, **kwargs: Any) -> dict:
        allowed = {
            "base_url", "access_key_encrypted",
            "last_test_status", "last_test_message", "last_test_at",
        }
        merged = dict(values) if isinstance(values, dict) else {}
        merged.update(kwargs)
        updates = {key: value for key, value in merged.items() if key in allowed}
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(f"UPDATE music_provider_settings SET {assignment} WHERE id = 1", tuple(updates.values()))
        return self.get_music_settings()

    # ------------------------------------------------------------------
    # 云端视频供应商设置（多行表：可灵/方舟/海螺/超算互联网各一行；行缺失时补默认行）
    # ------------------------------------------------------------------

    def get_cloud_video_settings(self, provider_key: str) -> dict:
        key = str(provider_key or "").strip()
        if not key:
            raise ValueError("云端视频供应商 provider_key 不能为空")
        defaults = cloud_video_provider_defaults(key)
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM cloud_video_provider_settings WHERE provider_key = ?", (key,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO cloud_video_provider_settings (provider_key, enabled, updated_at) VALUES (?, ?, ?)",
                    (key, defaults["enabled"], now()),
                )
                row = connection.execute(
                    "SELECT * FROM cloud_video_provider_settings WHERE provider_key = ?", (key,)
                ).fetchone()
        settings = dict(row) if row else {}
        return {**defaults, **settings}

    def list_cloud_video_settings(self) -> list[dict]:
        """按注册表顺序返回全部云端视频供应商设置（行缺失时 ensure-row），供管理页与测试使用。"""
        from .cloud_video.base import cloud_video_provider_keys

        return [self.get_cloud_video_settings(key) for key in cloud_video_provider_keys()]

    def update_cloud_video_settings(self, provider_key: str, values: dict | None = None, **kwargs: Any) -> dict:
        allowed = {
            "enabled", "base_url", "api_key_encrypted", "api_secret_encrypted",
            "extra_config_json",
            "last_test_status", "last_test_message", "last_test_at",
        }
        merged = dict(values) if isinstance(values, dict) else {}
        merged.update(kwargs)
        updates = {key: value for key, value in merged.items() if key in allowed}
        # ensure-row：update 前保证行存在
        self.get_cloud_video_settings(provider_key)
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        parameters = tuple(updates.values()) + (str(provider_key).strip(),)
        with self.connection() as connection:
            connection.execute(
                f"UPDATE cloud_video_provider_settings SET {assignment} WHERE provider_key = ?", parameters,
            )
        return self.get_cloud_video_settings(provider_key)


    def get_mail_settings(self) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM mail_provider_settings WHERE id = 1").fetchone()
        if not row:
            return {
                "id": 1,
                "enabled": 0,
                "host": "",
                "port": 465,
                "security": "ssl",
                "username": "",
                "password_encrypted": None,
                "from_address": "",
                "from_name": "ZLY AI Studio",
                "last_test_status": None,
                "last_test_message": None,
                "last_test_at": None,
                "updated_at": now(),
            }
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        return data

    def update_mail_settings(self, values: dict | None = None, **kwargs: Any) -> dict:
        allowed = {
            "enabled", "host", "port", "security", "username", "password_encrypted",
            "from_address", "from_name",
            "last_test_status", "last_test_message", "last_test_at",
        }
        merged = dict(values) if isinstance(values, dict) else {}
        merged.update(kwargs)
        updates = {key: value for key, value in merged.items() if key in allowed}
        if "enabled" in updates:
            updates["enabled"] = int(bool(updates["enabled"]))
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(f"UPDATE mail_provider_settings SET {assignment} WHERE id = 1", tuple(updates.values()))
        return self.get_mail_settings()

    @staticmethod
    def _music_job_from_row(row: Row | dict) -> dict[str, Any]:
        data = dict(row)
        raw_params = data.pop("params_json", None)
        if raw_params:
            try:
                parsed = json.loads(raw_params)
            except json.JSONDecodeError:
                parsed = None
            data["params"] = parsed if isinstance(parsed, dict) else {}
        else:
            data["params"] = {}
        return data

    def create_music_job(self, record: dict[str, Any]) -> dict[str, Any]:
        columns = {
            "id": record["id"],
            "owner_user_id": record["owner_user_id"],
            "title": record.get("title") or "",
            "style": record.get("style") or "",
            "lyrics": record.get("lyrics") or "",
            "status": record.get("status") or "queued",
            "progress": int(record.get("progress") or 0),
            "params_json": json.dumps(record.get("params") or {}, ensure_ascii=False),
            "result_url": record.get("result_url"),
            "result_format": record.get("result_format"),
            "cover_url": record.get("cover_url"),
            "duration_seconds": record.get("duration_seconds"),
            "remote_job_id": record.get("remote_job_id"),
            "remote_song_id": record.get("remote_song_id"),
            "error_message": record.get("error_message"),
            "chat_id": record.get("chat_id"),
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "completed_at": record.get("completed_at"),
        }
        assignment = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        with self.connection() as connection:
            connection.execute(
                f"INSERT INTO music_jobs ({assignment}) VALUES ({placeholders})",
                tuple(columns.values()),
            )
        return self.get_music_job(record["id"])  # type: ignore[return-value]

    def get_music_job(self, job_id: str, owner_user_id: str | None = None) -> dict[str, Any] | None:
        query = "SELECT * FROM music_jobs WHERE id = ?"
        args: list[Any] = [job_id]
        if owner_user_id is not None:
            query += " AND owner_user_id = ?"
            args.append(owner_user_id)
        with self.connection() as connection:
            row = connection.execute(query, tuple(args)).fetchone()
        return self._music_job_from_row(row) if row else None

    def list_music_jobs(self, owner_user_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """按归属列出音乐任务；owner_user_id 为 None 时返回全部账号（管理员查看用）。"""
        if owner_user_id is None:
            sql = "SELECT * FROM music_jobs ORDER BY created_at DESC, id DESC LIMIT ?"
            args: tuple[Any, ...] = (int(limit),)
        else:
            sql = "SELECT * FROM music_jobs WHERE owner_user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?"
            args = (owner_user_id, int(limit))
        with self.connection() as connection:
            rows = connection.execute(sql, args).fetchall()
        return [self._music_job_from_row(row) for row in rows]

    def list_active_music_jobs(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM music_jobs WHERE status IN ('queued', 'running')"
            ).fetchall()
        return [self._music_job_from_row(row) for row in rows]

    def update_music_job(self, job_id: str, **values: Any) -> dict[str, Any] | None:
        allowed = {
            "status", "progress", "result_url", "result_format", "cover_url", "duration_seconds",
            "remote_job_id", "remote_song_id", "error_message", "completed_at",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return self.get_music_job(job_id)
        if "progress" in updates:
            updates["progress"] = int(updates["progress"] or 0)
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(f"UPDATE music_jobs SET {assignment} WHERE id = ?", tuple(updates.values()) + (job_id,))
        return self.get_music_job(job_id)

    def delete_music_job(self, job_id: str, owner_user_id: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM music_jobs WHERE id = ? AND owner_user_id = ?", (job_id, owner_user_id),
            )
        return bool(cursor.rowcount)

    # ------------------------------------------------------------------ #
    # 音乐对话（创建 + 迭代修改）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _music_chat_from_row(row: Row | dict) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _music_chat_message_from_row(row: Row | dict) -> dict[str, Any]:
        data = dict(row)
        raw_proposal = data.pop("proposal_json", None)
        if raw_proposal:
            try:
                parsed = json.loads(raw_proposal)
            except json.JSONDecodeError:
                parsed = None
            data["proposal"] = parsed if isinstance(parsed, dict) else None
        else:
            data["proposal"] = None
        return data

    def create_music_chat(self, record: dict[str, Any]) -> dict[str, Any]:
        columns = {
            "id": record["id"],
            "owner_user_id": record["owner_user_id"],
            "title": record.get("title") or "新对话",
            "anchor_job_id": record.get("anchor_job_id"),
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }
        assignment = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        with self.connection() as connection:
            connection.execute(
                f"INSERT INTO music_chats ({assignment}) VALUES ({placeholders})",
                tuple(columns.values()),
            )
        return self.get_music_chat(record["id"], owner_user_id=record["owner_user_id"])

    def get_music_chat(self, chat_id: str, owner_user_id: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT * FROM music_chats WHERE id = ?"
        parameters: tuple[Any, ...] = (chat_id,)
        if owner_user_id is not None:
            sql += " AND owner_user_id = ?"
            parameters += (owner_user_id,)
        with self.connection() as connection:
            row = connection.execute(sql, parameters).fetchone()
        return self._music_chat_from_row(row) if row else None

    def list_music_chats(self, owner_user_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """按归属列出音乐对话；owner_user_id 为 None 时返回全部账号（管理员查看用）。"""
        if owner_user_id is None:
            sql = "SELECT * FROM music_chats ORDER BY updated_at DESC, id DESC LIMIT ?"
            args: tuple[Any, ...] = (int(limit),)
        else:
            sql = "SELECT * FROM music_chats WHERE owner_user_id = ? ORDER BY updated_at DESC, id DESC LIMIT ?"
            args = (owner_user_id, int(limit))
        with self.connection() as connection:
            rows = connection.execute(sql, args).fetchall()
        return [self._music_chat_from_row(row) for row in rows]

    def update_music_chat(self, chat_id: str, **values: Any) -> dict[str, Any] | None:
        allowed = {"title", "anchor_job_id"}
        updates = {key: value for key, value in values.items() if key in allowed}
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(f"UPDATE music_chats SET {assignment} WHERE id = ?", tuple(updates.values()) + (chat_id,))
        return self.get_music_chat(chat_id)

    def delete_music_chat(self, chat_id: str, owner_user_id: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM music_chats WHERE id = ? AND owner_user_id = ?", (chat_id, owner_user_id),
            )
        return bool(cursor.rowcount)

    def append_music_chat_message(self, record: dict[str, Any]) -> dict[str, Any]:
        columns = {
            "id": record["id"],
            "chat_id": record["chat_id"],
            "role": record["role"],
            "content": record.get("content") or "",
            "proposal_json": json.dumps(record["proposal"], ensure_ascii=False) if record.get("proposal") else None,
            "job_id": record.get("job_id"),
            "created_at": record["created_at"],
        }
        assignment = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        with self.connection() as connection:
            connection.execute(
                f"INSERT INTO music_chat_messages ({assignment}) VALUES ({placeholders})",
                tuple(columns.values()),
            )
        return self.get_music_chat_message(record["id"])

    def get_music_chat_message(self, message_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM music_chat_messages WHERE id = ?", (message_id,),
            ).fetchone()
        return self._music_chat_message_from_row(row) if row else None

    def list_music_chat_messages(self, chat_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM music_chat_messages WHERE chat_id = ? ORDER BY created_at ASC, id ASC LIMIT ?",
                (chat_id, int(limit)),
            ).fetchall()
        return [self._music_chat_message_from_row(row) for row in rows]

    def update_music_chat_message(self, message_id: str, **values: Any) -> dict[str, Any] | None:
        allowed = {"job_id"}
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return self.get_music_chat_message(message_id)
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(
                f"UPDATE music_chat_messages SET {assignment} WHERE id = ?", tuple(updates.values()) + (message_id,),
            )
        return self.get_music_chat_message(message_id)

    def get_music_lyrics(self, job_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT status, lease_until, payload_json FROM music_job_lyrics WHERE job_id = ?", (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def claim_music_lyrics(self, job_id: str, token: str, timestamp: int, deadline: int) -> bool:
        with self.connection() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO music_job_lyrics (job_id, status)
                   SELECT id, 'idle' FROM music_jobs WHERE id = ? AND status = 'succeeded'""", (job_id,),
            )
            cursor = connection.execute(
                """UPDATE music_job_lyrics
                   SET status = 'aligning', claim_token = ?, lease_until = ?, payload_json = NULL
                   WHERE job_id = ? AND status <> 'ready' AND (status <> 'aligning' OR lease_until <= ?)""",
                (token, deadline, job_id, timestamp),
            )
        return bool(cursor.rowcount)

    def finish_music_lyrics(self, job_id: str, token: str, status: str, payload: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                """UPDATE music_job_lyrics SET status = ?, payload_json = ?, claim_token = NULL, lease_until = 0
                   WHERE job_id = ? AND status = 'aligning' AND claim_token = ?""",
                (status, json.dumps(payload, ensure_ascii=False), job_id, token),
            )

    def get_comfy_settings(self) -> dict:
        if self._comfy_settings_cache is not None:
            return dict(self._comfy_settings_cache)
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM comfy_provider_settings WHERE id = 1").fetchone()
        data = dict(row)
        self._comfy_settings_cache = dict(data)
        return data

    def update_comfy_settings(self, values: dict | None = None, **kwargs: Any) -> dict:
        allowed = {"base_url", "last_test_status", "last_test_message", "last_test_at"}
        merged = dict(values) if isinstance(values, dict) else {}
        merged.update(kwargs)
        updates = {key: value for key, value in merged.items() if key in allowed}
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(f"UPDATE comfy_provider_settings SET {assignment} WHERE id = 1", tuple(updates.values()))
        self._comfy_settings_cache = None
        return self.get_comfy_settings()

    @staticmethod
    def _grs_image_model_from_row(row: Row | dict) -> dict[str, Any]:
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        data["is_default"] = bool(data["is_default"])
        data["builtin"] = bool(data["builtin"])
        raw_resolutions = data.pop("resolutions_json", None)
        if raw_resolutions:
            try:
                parsed = json.loads(raw_resolutions)
            except json.JSONDecodeError:
                parsed = None
            data["resolutions"] = parsed if isinstance(parsed, list) else None
        else:
            data["resolutions"] = None
        raw_quality = data.pop("quality_json", None)
        quality_options: list[str] | None = None
        default_quality: str | None = None
        if raw_quality:
            try:
                parsed_quality = json.loads(raw_quality)
            except json.JSONDecodeError:
                parsed_quality = None
            if isinstance(parsed_quality, dict):
                quality_options = parsed_quality.get("options") if isinstance(parsed_quality.get("options"), list) else None
                default_quality = parsed_quality.get("default")
        data["quality_options"] = quality_options
        data["default_quality"] = default_quality
        try:
            data["credit_cost"] = int(data["credit_cost"]) if data.get("credit_cost") is not None else None
        except (TypeError, ValueError):
            data["credit_cost"] = None
        return data

    def list_grs_image_models(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM grs_image_models ORDER BY sort_order ASC, display_name ASC"
            ).fetchall()
        return [self._grs_image_model_from_row(row) for row in rows]

    def get_grs_image_model(self, workflow_id: str) -> dict[str, Any] | None:
        if workflow_id in self._grs_model_cache:
            cached = self._grs_model_cache[workflow_id]
            return dict(cached) if cached is not None else None
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM grs_image_models WHERE workflow_id = ?", (workflow_id,),
            ).fetchone()
        value = self._grs_image_model_from_row(row) if row else None
        self._grs_model_cache[workflow_id] = dict(value) if value is not None else None
        return value

    def update_grs_image_models(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        timestamp = now()
        default_ids = [item["workflow_id"] for item in items if item.get("is_default")]
        default_id = default_ids[0] if default_ids else None
        with self.connection() as connection:
            existing = {
                row["workflow_id"]: dict(row)
                for row in connection.execute("SELECT * FROM grs_image_models").fetchall()
            }
            unknown = [item["workflow_id"] for item in items if item["workflow_id"] not in existing]
            if unknown:
                raise ValueError(f"生图模型不存在: {unknown[0]}")
            if default_id is None:
                enabled = next((item["workflow_id"] for item in items if item.get("enabled")), None)
                default_id = enabled or next(iter(existing), None)
            connection.execute("UPDATE grs_image_models SET is_default = 0")
            for item in items:
                connection.execute(
                    """UPDATE grs_image_models
                    SET display_name = ?, enabled = ?, sort_order = ?, is_default = ?, updated_at = ?
                    WHERE workflow_id = ?""",
                    (
                        item["display_name"].strip(), int(bool(item.get("enabled"))),
                        int(item.get("sort_order", existing[item["workflow_id"]]["sort_order"])),
                        int(item["workflow_id"] == default_id), timestamp, item["workflow_id"],
                    ),
                )
        self._grs_model_cache.clear()
        return self.list_grs_image_models()

    def set_grs_image_model_costs(self, costs: dict[str, Any]) -> int:
        """写入平台标价积分（按 provider_model 匹配），只动目录里已有的行。

        积分是平台侧数据，不属于管理员可编辑项，因此不刷新 updated_at。
        """
        cleaned: dict[str, int] = {}
        for provider_model, cost in costs.items():
            try:
                value = int(cost)
            except (TypeError, ValueError):
                continue
            name = str(provider_model).strip()
            if name and value > 0:
                cleaned[name] = value
        if not cleaned:
            return 0
        with self.connection() as connection:
            known = {
                row["provider_model"]
                for row in connection.execute("SELECT provider_model FROM grs_image_models").fetchall()
            }
            matched = [(name, value) for name, value in cleaned.items() if name in known]
            for name, value in matched:
                connection.execute(
                    "UPDATE grs_image_models SET credit_cost = ? WHERE provider_model = ?",
                    (value, name),
                )
        self._grs_model_cache.clear()
        return len(matched)

    def add_grs_image_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider_model = validate_provider_model(payload["provider_model"])
        workflow_id = workflow_id_for(provider_model)
        timestamp = now()
        record = {
            "workflow_id": workflow_id,
            "provider_model": provider_model,
            "display_name": payload["display_name"].strip(),
            "description": payload.get("description") or "",
            "profile": payload["profile"],
            "resolutions": payload.get("resolutions"),
            "enabled": payload.get("enabled", True),
            "sort_order": payload.get("sort_order"),
            "is_default": bool(payload.get("is_default")),
            "builtin": False,
            "credit_cost": payload.get("credit_cost"),
        }
        with self.connection() as connection:
            exists = connection.execute(
                "SELECT workflow_id FROM grs_image_models WHERE workflow_id = ? OR provider_model = ?",
                (workflow_id, provider_model),
            ).fetchone()
            if exists:
                raise ValueError("该生图模型已存在")
            if record["sort_order"] is None:
                # 新模型一律排在管理员现有顺序之后，避免插进自定义排序的中间。
                last = connection.execute("SELECT MAX(sort_order) AS last_order FROM grs_image_models").fetchone()
                record["sort_order"] = int(last["last_order"] or 0) + 10
            if record["is_default"]:
                connection.execute("UPDATE grs_image_models SET is_default = 0")
            self._insert_grs_image_model(connection, record, timestamp)
        self._grs_model_cache.pop(workflow_id, None)
        saved = self.get_grs_image_model(workflow_id)
        if saved is None:
            raise ValueError("添加生图模型失败")
        return saved

    def sync_builtin_grs_image_models(self) -> list[dict[str, Any]]:
        timestamp = now()
        with self.connection() as connection:
            existing = {
                row["provider_model"]
                for row in connection.execute("SELECT provider_model FROM grs_image_models").fetchall()
            }
            for spec in builtin_catalog_records():
                if spec["provider_model"] in existing:
                    continue
                self._insert_grs_image_model(connection, {**spec, "enabled": False, "is_default": False}, timestamp)
            self._apply_gpt_image_25_default_migration(connection, timestamp)
        self._grs_model_cache.clear()
        return self.list_grs_image_models()

    def _apply_gpt_image_25_default_migration(self, connection: DbConnection, timestamp: str) -> None:
        """补插 GPT Image 2.5 系列内置行；一次性迁移负责启用并切换默认生图模型。

        补插在迁移标记检查之前无条件执行（幂等），保证标记提前写入的半成品
        状态（如热重载加载中间态代码）也能在下次启动自愈；管理员事后的
        停用与默认调整不受影响。
        """
        existing = {
            row["provider_model"]
            for row in connection.execute("SELECT provider_model FROM grs_image_models").fetchall()
        }
        for spec in builtin_catalog_records():
            if spec["provider_model"] in GPT_IMAGE_25_PROVIDER_MODELS and spec["provider_model"] not in existing:
                self._insert_grs_image_model(connection, {**spec}, timestamp)
        applied = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE name = ?", (self.GRS_GPT_IMAGE_25_MIGRATION,),
        ).fetchone()
        if applied:
            return
        placeholders = ", ".join("?" for _ in GPT_IMAGE_25_PROVIDER_MODELS)
        connection.execute(
            f"""UPDATE grs_image_models SET enabled = 1, updated_at = ?
            WHERE provider_model IN ({placeholders})""",
            (timestamp, *GPT_IMAGE_25_PROVIDER_MODELS),
        )
        connection.execute("UPDATE grs_image_models SET is_default = 0")
        connection.execute(
            "UPDATE grs_image_models SET is_default = 1, updated_at = ? WHERE provider_model = ?",
            (timestamp, GPT_IMAGE_25_DEFAULT_PROVIDER_MODEL),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES (?, ?)",
            (self.GRS_GPT_IMAGE_25_MIGRATION, timestamp),
        )

    @staticmethod
    def _new_director_project_id() -> str:
        return f"proj-{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _strip_director_data_urls(value: Any) -> Any:
        """Drop inlined data URLs and File-like keys so SQLite never stores large images."""
        if isinstance(value, str):
            return None if value.startswith("data:") else value
        if isinstance(value, list):
            return [JobStore._strip_director_data_urls(item) for item in value]
        if isinstance(value, dict):
            skipped = {"file", "firstFrameFile", "endFrameFile", "analyzing"}
            return {
                key: JobStore._strip_director_data_urls(item)
                for key, item in value.items()
                if key not in skipped
            }
        return value

    @staticmethod
    def sanitize_director_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
        from .director_recipe import normalize_director_payload

        raw = payload if isinstance(payload, dict) else {}
        cleaned = JobStore._strip_director_data_urls(raw)
        if not isinstance(cleaned, dict):
            cleaned = {}
        return normalize_director_payload(cleaned)

    @staticmethod
    def _payload_shots(payload: dict[str, Any]) -> list[dict[str, Any]]:
        from .director_recipe import flatten_recipe_shots

        return flatten_recipe_shots(payload if isinstance(payload, dict) else {})

    @staticmethod
    def _shot_is_generated(shot: dict[str, Any]) -> bool:
        if shot.get("status") == "succeeded" or shot.get("outputVideoUrl"):
            return True
        takes = shot.get("takes")
        if not isinstance(takes, list):
            return False
        return any(
            isinstance(take, dict) and (take.get("status") == "succeeded" or take.get("videoUrl"))
            for take in takes
        )

    @classmethod
    def director_generation_progress(cls, payload: dict[str, Any]) -> tuple[str, int, int]:
        shots = cls._payload_shots(payload)
        total = len(shots)
        generated = sum(1 for shot in shots if cls._shot_is_generated(shot))
        if total == 0 or generated == 0:
            status = "pending"
        elif generated >= total:
            status = "complete"
        else:
            status = "partial"
        return status, generated, total

    def _director_row_to_dict(self, row: Row, *, include_payload: bool = True) -> dict[str, Any]:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        generation_status, generated_count, shot_count = self.director_generation_progress(payload)
        source_script = row["source_script"] or ""
        from .director_recipe import payload_kind
        script = payload.get("script") if isinstance(payload.get("script"), dict) else {}
        cover_url = script.get("coverUrl") or script.get("cover_url")

        record: dict[str, Any] = {
            "id": row["id"],
            "owner_user_id": row["owner_user_id"],
            "title": row["title"],
            "summary": row["summary"] or "",
            "source_script": source_script,
            "style_vibe": row["style_vibe"],
            "requested_shot_count": row["requested_shot_count"],
            "has_source_script": bool(source_script.strip()),
            "cover_url": cover_url if isinstance(cover_url, str) and cover_url.strip() else None,
            "kind": payload_kind(payload),
            "shot_count": shot_count,
            "generated_count": generated_count,
            "generation_status": generation_status,
            "revision": int(row["revision"] or 1),
            "content_revision": int(row["content_revision"] or 1),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if include_payload:
            record["payload"] = payload
        return record

    def list_director_projects(self, owner_user_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM director_projects
                WHERE owner_user_id = ?
                ORDER BY updated_at DESC""",
                (owner_user_id,),
            ).fetchall()
        return [self._director_row_to_dict(row, include_payload=False) for row in rows]

    def get_director_project(self, project_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM director_projects WHERE id = ?", (project_id,),
            ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return self._director_row_to_dict(row, include_payload=True)

    def create_director_project(
        self,
        owner_user_id: str,
        title: str,
        *,
        project_id: str | None = None,
        summary: str = "",
        source_script: str = "",
        style_vibe: str | None = None,
        requested_shot_count: int | None = None,
        payload: dict[str, Any] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now()
        new_id = (project_id or "").strip() or self._new_director_project_id()
        created = created_at or timestamp
        updated = updated_at or timestamp
        sanitized = self.sanitize_director_payload(payload)
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT id, owner_user_id FROM director_projects WHERE id = ?", (new_id,),
            ).fetchone()
            if existing is not None:
                raise ValueError("导演工程 ID 已存在")
            connection.execute(
                """INSERT INTO director_projects (
                    id, owner_user_id, title, summary, source_script, style_vibe,
                    requested_shot_count, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id, owner_user_id, title.strip(), summary or "", source_script or "",
                    style_vibe, requested_shot_count,
                    json.dumps(sanitized, ensure_ascii=False), created, updated,
                ),
            )
        return self.get_director_project(new_id)

    def update_director_project(
        self,
        project_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        source_script: str | None = None,
        style_vibe: str | None = None,
        requested_shot_count: int | None = None,
        payload: dict[str, Any] | None = None,
        update_style_vibe: bool = False,
        update_requested_shot_count: bool = False,
        expected_content_revision: int | None = None,
        force: bool = False,
        content_update: bool = True,
        payload_merger: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM director_projects WHERE id = ?", (project_id,), for_update=True,
            ).fetchone()
            if row is None:
                raise KeyError(project_id)
            current = self._director_row_to_dict(row, include_payload=True)
            if (
                expected_content_revision is not None
                and not force
                and current["content_revision"] != expected_content_revision
            ):
                raise DirectorProjectConflictError(current)
            next_title = current["title"] if title is None else title.strip()
            next_summary = current["summary"] if summary is None else summary
            next_script = current["source_script"] if source_script is None else source_script
            next_vibe = current["style_vibe"] if not update_style_vibe else style_vibe
            next_count = current["requested_shot_count"] if not update_requested_shot_count else requested_shot_count
            if payload is None:
                next_payload = current["payload"]
            elif payload_merger is not None:
                next_payload = self.sanitize_director_payload(payload_merger(current["payload"], payload))
            else:
                next_payload = self.sanitize_director_payload(payload)
            next_revision = current["revision"] + 1
            next_content_revision = current["content_revision"] + (1 if content_update else 0)
            timestamp = now()
            connection.execute(
                """UPDATE director_projects
                SET title = ?, summary = ?, source_script = ?, style_vibe = ?,
                    requested_shot_count = ?, payload_json = ?, revision = ?,
                    content_revision = ?, updated_at = ?
                WHERE id = ?""",
                (
                    next_title, next_summary or "", next_script or "", next_vibe, next_count,
                    json.dumps(next_payload, ensure_ascii=False), next_revision,
                    next_content_revision, timestamp, project_id,
                ),
            )
        return self.get_director_project(project_id)

    def mutate_director_project_payload(
        self,
        project_id: str,
        mutator: Callable[[dict[str, Any]], dict[str, Any] | None],
        *,
        content_update: bool = False,
        expected_content_revision: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Apply a payload patch against the latest row in one short transaction."""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM director_projects WHERE id = ?", (project_id,), for_update=True,
            ).fetchone()
            if row is None:
                raise KeyError(project_id)
            current = self._director_row_to_dict(row, include_payload=True)
            if (
                expected_content_revision is not None
                and not force
                and current["content_revision"] != expected_content_revision
            ):
                raise DirectorProjectConflictError(current)
            working = deepcopy(current["payload"])
            mutated = mutator(working)
            next_payload = self.sanitize_director_payload(mutated if isinstance(mutated, dict) else working)
            timestamp = now()
            connection.execute(
                """UPDATE director_projects
                SET payload_json = ?, revision = ?, content_revision = ?, updated_at = ?
                WHERE id = ?""",
                (
                    json.dumps(next_payload, ensure_ascii=False),
                    current["revision"] + 1,
                    current["content_revision"] + (1 if content_update else 0),
                    timestamp,
                    project_id,
                ),
            )
        return self.get_director_project(project_id)

    @staticmethod
    def _director_operation_row_to_dict(row: Row) -> dict[str, Any]:
        def decode(name: str) -> dict[str, Any]:
            try:
                value = json.loads(row[name] or "{}")
            except (json.JSONDecodeError, TypeError):
                value = {}
            return value if isinstance(value, dict) else {}

        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "owner_user_id": row["owner_user_id"],
            "kind": row["kind"],
            "status": row["status"],
            "progress": int(row["progress"] or 0),
            "request": decode("request_json"),
            "result": decode("result_json"),
            "error": row["error"],
            "cancel_requested": bool(row["cancel_requested"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_director_operation(
        self,
        *,
        project_id: str,
        owner_user_id: str,
        kind: str,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        operation_id = f"director-op-{uuid.uuid4().hex}"
        timestamp = now()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                """SELECT id FROM director_operations
                WHERE project_id = ? AND status IN ('queued', 'running')
                LIMIT 1""",
                (project_id,),
                for_update=True,
            ).fetchone()
            if active is not None:
                raise ValueError(f"工程已有未完成的导演操作：{active['id']}")
            connection.execute(
                """INSERT INTO director_operations (
                    id, project_id, owner_user_id, kind, status, progress,
                    request_json, result_json, error, cancel_requested, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', 0, ?, '{}', NULL, 0, ?, ?)""",
                (
                    operation_id,
                    project_id,
                    owner_user_id,
                    kind,
                    json.dumps(request or {}, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_director_operation(operation_id)

    def get_director_operation(self, operation_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM director_operations WHERE id = ?", (operation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return self._director_operation_row_to_dict(row)

    def get_active_director_operation(self, project_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                """SELECT * FROM director_operations
                WHERE project_id = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC LIMIT 1""",
                (project_id,),
            ).fetchone()
        return None if row is None else self._director_operation_row_to_dict(row)

    def update_director_operation(
        self,
        operation_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        update_error: bool = False,
        cancel_requested: bool | None = None,
    ) -> dict[str, Any]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM director_operations WHERE id = ?", (operation_id,), for_update=True,
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            next_status = row["status"] if status is None else status
            next_progress = int(row["progress"] or 0) if progress is None else max(0, min(100, int(progress)))
            next_result = row["result_json"] if result is None else json.dumps(result, ensure_ascii=False)
            next_error = row["error"] if not update_error else error
            next_cancel = int(row["cancel_requested"] or 0) if cancel_requested is None else int(cancel_requested)
            connection.execute(
                """UPDATE director_operations
                SET status = ?, progress = ?, result_json = ?, error = ?,
                    cancel_requested = ?, updated_at = ?
                WHERE id = ?""",
                (
                    next_status,
                    next_progress,
                    next_result,
                    next_error,
                    next_cancel,
                    now(),
                    operation_id,
                ),
            )
        return self.get_director_operation(operation_id)

    def interrupt_stale_director_operations(self) -> int:
        timestamp = now()
        with self.connection() as connection:
            cursor = connection.execute(
                """UPDATE director_operations
                SET status = 'interrupted', progress = CASE WHEN progress > 99 THEN 99 ELSE progress END,
                    error = COALESCE(error, '服务重启，操作已中断；不会自动重试，以避免重复计费，请手动重试。'),
                    updated_at = ?
                WHERE status IN ('queued', 'running')""",
                (timestamp,),
            )
        return max(0, cursor.rowcount)

    def interrupt_stale_director_pipelines(self) -> int:
        from .director_recipe import interrupt_stale_pipeline

        with self.connection() as connection:
            rows = connection.execute("SELECT id, payload_json FROM director_projects").fetchall()
        count = 0
        for row in rows:
            raw = row["payload_json"] or ""
            try:
                payload = json.loads(raw or "{}")
            except json.JSONDecodeError:
                continue
            updated = interrupt_stale_pipeline(payload)
            if updated is None:
                continue
            self.update_director_project(row["id"], payload=updated)
            count += 1
        return count

    def delete_director_project(self, project_id: str) -> None:
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM director_projects WHERE id = ?", (project_id,))
        if cursor.rowcount == 0:
            raise KeyError(project_id)

    @staticmethod
    def _new_director_library_asset_id() -> str:
        from .director_library import new_library_asset_id

        return new_library_asset_id()

    def _library_asset_row_to_dict(self, row: Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "owner_user_id": row["owner_user_id"],
            "kind": row["kind"],
            "name": row["name"],
            "description": row["description"] or "",
            "prompt_text": row["prompt_text"] or "",
            "gender": row["gender"] or "",
            "image_url": row["image_url"],
            "image_job_id": row["image_job_id"],
            "image_path": row["image_path"],
            "source_project_id": row["source_project_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_director_library_assets(
        self,
        owner_user_id: str,
        *,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """SELECT * FROM director_library_assets
            WHERE owner_user_id = ?"""
        params: list[Any] = [owner_user_id]
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        query += " ORDER BY updated_at DESC"
        with self.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._library_asset_row_to_dict(row) for row in rows]

    def get_director_library_asset(self, asset_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM director_library_assets WHERE id = ?", (asset_id,),
            ).fetchone()
        if row is None:
            raise KeyError(asset_id)
        return self._library_asset_row_to_dict(row)

    def create_director_library_asset(
        self,
        owner_user_id: str,
        *,
        kind: str,
        name: str,
        description: str = "",
        prompt_text: str = "",
        gender: str = "",
        image_url: str | None = None,
        image_job_id: str | None = None,
        image_path: str | None = None,
        source_project_id: str | None = None,
        asset_id: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now()
        new_id = (asset_id or "").strip() or self._new_director_library_asset_id()
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO director_library_assets (
                    id, owner_user_id, kind, name, description, prompt_text, gender,
                    image_url, image_job_id, image_path, source_project_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id, owner_user_id, kind, name.strip(), description or "", prompt_text or "",
                    gender or "", image_url, image_job_id, image_path, source_project_id,
                    timestamp, timestamp,
                ),
            )
        return self.get_director_library_asset(new_id)

    def update_director_library_asset(
        self,
        asset_id: str,
        *,
        kind: str | None = None,
        name: str | None = None,
        description: str | None = None,
        prompt_text: str | None = None,
        gender: str | None = None,
        image_url: str | None = None,
        image_job_id: str | None = None,
        image_path: str | None = None,
        source_project_id: str | None = None,
        update_image_url: bool = False,
        update_image_job_id: bool = False,
        update_image_path: bool = False,
        update_source_project_id: bool = False,
    ) -> dict[str, Any]:
        current = self.get_director_library_asset(asset_id)
        next_kind = current["kind"] if kind is None else kind
        next_name = current["name"] if name is None else name.strip()
        next_description = current["description"] if description is None else description
        next_prompt = current["prompt_text"] if prompt_text is None else prompt_text
        next_gender = current["gender"] if gender is None else gender
        next_image_url = current["image_url"] if not update_image_url else image_url
        next_image_job = current["image_job_id"] if not update_image_job_id else image_job_id
        next_image_path = current["image_path"] if not update_image_path else image_path
        next_source = current["source_project_id"] if not update_source_project_id else source_project_id
        timestamp = now()
        with self.connection() as connection:
            connection.execute(
                """UPDATE director_library_assets
                SET kind = ?, name = ?, description = ?, prompt_text = ?, gender = ?,
                    image_url = ?, image_job_id = ?, image_path = ?, source_project_id = ?,
                    updated_at = ?
                WHERE id = ?""",
                (
                    next_kind, next_name, next_description or "", next_prompt or "", next_gender or "",
                    next_image_url, next_image_job, next_image_path, next_source, timestamp, asset_id,
                ),
            )
        return self.get_director_library_asset(asset_id)

    def delete_director_library_asset(self, asset_id: str) -> dict[str, Any]:
        current = self.get_director_library_asset(asset_id)
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM director_library_assets WHERE id = ?", (asset_id,))
        if cursor.rowcount == 0:
            raise KeyError(asset_id)
        return current
