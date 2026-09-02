from __future__ import annotations

import json
import shutil
import time
import uuid
from copy import deepcopy
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .grs_catalog import (
    builtin_catalog_records,
    builtin_entry,
    catalog_record,
    split_model_list,
    validate_provider_model,
    workflow_id_for,
)
from .config import settings
from .db import Database, DbConnection, Row, open_database
from .models import JobMode, JobStatus


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
    JobStatus.INTERRUPTED.value,
}

ACTIVE_STATUSES = {
    JobStatus.QUEUED.value,
    JobStatus.RUNNING.value,
}


class DirectorProjectConflictError(RuntimeError):
    """Raised when a creative update targets an obsolete content revision."""

    def __init__(self, current_project: dict[str, Any]) -> None:
        super().__init__("导演工程已在其他窗口更新")
        self.current_project = current_project


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

    def initialize(self) -> None:
        with self.connection() as connection:
            if self._db.dialect == "mysql":
                self._db.apply_mysql_schema(connection)
                self._ensure_job_list_indexes(connection)
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
                """
            )
            self._ensure_column(connection, "director_projects", "revision", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(connection, "director_projects", "content_revision", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(connection, "generation_items", "cancel_requested", "INTEGER NOT NULL DEFAULT 0")
            for table in ("jobs", "job_rounds", "generation_items"):
                self._ensure_column(connection, table, "finished_at", "TEXT")
                self._ensure_column(connection, table, "execution_elapsed_ms", "INTEGER")
            self._ensure_column(connection, "grs_provider_settings", "models", "TEXT NOT NULL DEFAULT 'gpt-image-2'")
            self._ensure_column(connection, "grs_provider_settings", "vip_models", "TEXT NOT NULL DEFAULT 'gpt-image-2-vip'")
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
        if mode == JobMode.IMAGE.value or mode.startswith("grs-"):
            return "image"
        return "video"

    @staticmethod
    def _executor_for_mode(mode: str) -> str:
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
                    enabled INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 100,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        applied = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE name = ?", (self.GRS_CATALOG_MIGRATION,),
        ).fetchone()
        if applied:
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
        default_id = "gpt-image-2" if gpt_enabled else next(
            (item["provider_model"] for item in seeded.values() if item["enabled"]), None,
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
        connection.execute(
            """INSERT OR IGNORE INTO grs_image_models
            (workflow_id, provider_model, display_name, description, profile, resolutions_json,
             enabled, sort_order, is_default, builtin, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["workflow_id"], record["provider_model"], record["display_name"],
                record.get("description") or "", record["profile"],
                json.dumps(resolutions, ensure_ascii=False) if resolutions else None,
                int(bool(record.get("enabled"))), int(record.get("sort_order", 100)),
                int(bool(record.get("is_default"))), int(bool(record.get("builtin", True))),
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
                image_size, references, options or {}, submitted_options,
            )
        return self.get(job_id)

    def _insert_round(
        self, connection: DbConnection, round_id: str, job_id: str, sequence: int,
        mode: JobMode | str, media_type: str, prompt: str, negative_prompt: str,
        image_size: str | None, references: list[str], options: dict,
        submitted_options: dict | None,
    ) -> None:
        timestamp = now()
        mode_value = self._mode_value(mode)
        connection.execute(
            """INSERT INTO job_rounds
            (id, job_id, sequence, mode, media_type, status, stage, progress, prompt,
             negative_prompt, image_size, options_json, submitted_options_json,
             options_submitted, references_json, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
            (
                round_id, job_id, sequence, mode_value, media_type, JobStatus.QUEUED.value, "等待排队",
                prompt, negative_prompt, image_size, json.dumps(options, ensure_ascii=False),
                json.dumps(submitted_options or {}, ensure_ascii=False), int(submitted_options is not None),
                json.dumps(references, ensure_ascii=False), timestamp, timestamp,
            ),
        )
        count = int(options.get("count", 1)) if media_type == "image" else 1
        executor = self._executor_for_mode(mode_value)
        for index in range(1, count + 1):
            connection.execute(
                """INSERT INTO generation_items
                (id, round_id, item_index, executor, status, stage, progress, outputs_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, '[]', ?, ?)""",
                (str(uuid.uuid4()), round_id, index, executor, JobStatus.QUEUED.value, "等待排队", timestamp, timestamp),
            )

    def create_round(
        self, job_id: str, *, prompt: str, negative_prompt: str = "", image_size: str | None = None,
        references: list[str] | None = None, options: dict | None = None,
        submitted_options: dict | None = None,
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
            self._insert_round(
                connection, round_id, job_id, sequence, mode, job["media_type"], prompt,
                negative_prompt, image_size, refs, effective_options, submitted_options,
            )
            connection.execute("UPDATE jobs SET last_round_id = ?, updated_at = ? WHERE id = ?", (round_id, now(), job_id))
            self._refresh_job(connection, job_id)
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
    ) -> dict:
        incoming_status = status.value if isinstance(status, JobStatus) else status
        updates: dict[str, Any] = {"updated_at": now()}
        with self.connection() as connection:
            row = connection.execute(
                """SELECT r.job_id, i.round_id, i.status, i.cancel_requested, i.finished_at
                FROM generation_items i JOIN job_rounds r ON r.id = i.round_id WHERE i.id = ?""",
                (generation_item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(generation_item_id)
            cancelled = row["status"] == JobStatus.CANCELLED.value or bool(row["cancel_requested"])
            allow_status = not cancelled or incoming_status in {
                JobStatus.QUEUED.value, JobStatus.SUCCEEDED.value, JobStatus.CANCELLED.value,
            }
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
            assignment = ", ".join(f"{column} = ?" for column in updates)
            connection.execute(f"UPDATE generation_items SET {assignment} WHERE id = ?", (*updates.values(), generation_item_id))
            self._refresh_round(connection, row["round_id"])
            self._refresh_job(connection, row["job_id"])
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

    def retry_failed_items(self, job_id: str, round_id: str | None = None) -> list[dict]:
        job = self.get(job_id)
        target = next((item for item in job["rounds"] if item["id"] == round_id), job["rounds"][-1])
        retried: list[dict] = []
        for item in target["generation_items"]:
            if item["status"] in {JobStatus.FAILED.value, JobStatus.INTERRUPTED.value, JobStatus.CANCELLED.value}:
                retried.append(self.update_generation(
                    item["id"], status=JobStatus.QUEUED, stage="等待重新提交", progress=0,
                    outputs=[], error="", remote_status="", cancel_requested=False, clear_execution=True,
                ))
        return retried

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
    def _decode_generation(cls, row: Row) -> dict:
        data = dict(row)
        data["index"] = data.pop("item_index")
        data["outputs"] = cls._decode_outputs(data.pop("outputs_json"))
        data["cancel_requested"] = bool(data.get("cancel_requested") or 0)
        return data

    def _rounds_for_job(self, connection: DbConnection, job_id: str, include_references: bool) -> list[dict]:
        return self._rounds_for_jobs(connection, [job_id], include_references).get(job_id, [])

    def _rounds_for_jobs(
        self, connection: DbConnection, job_ids: list[str], include_references: bool,
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
                items_by_round[str(item["round_id"])].append(self._decode_generation(item))
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
    ) -> list[dict]:
        job_ids = [str(row["id"]) for row in rows]
        rounds_by_job = self._rounds_for_jobs(connection, job_ids, include_references)
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
            return self._hydrate_job_rows(connection, self._job_rows_by_ids(
                connection, [str(row["id"]) for row in id_rows],
            ))

    def list_jobs(self, user_id: str | None = None, limit: int = 100) -> list[dict]:
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
            return self._hydrate_job_rows(connection, self._job_rows_by_ids(connection, job_ids))

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
            return self.decode(row, connection=connection)

    def delete(self, job_id: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cursor.rowcount > 0

    def assign_unowned(self, user_id: str) -> int:
        with self.connection() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET owner_user_id = ?, updated_at = ? WHERE owner_user_id IS NULL", (user_id, now())
            )
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
            "enabled", "base_url", "api_key_encrypted", "model",
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
        return data

    def list_grs_image_models(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM grs_image_models ORDER BY is_default DESC, sort_order ASC, display_name ASC"
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
            "sort_order": payload.get("sort_order", 300),
            "is_default": bool(payload.get("is_default")),
            "builtin": False,
        }
        with self.connection() as connection:
            exists = connection.execute(
                "SELECT workflow_id FROM grs_image_models WHERE workflow_id = ? OR provider_model = ?",
                (workflow_id, provider_model),
            ).fetchone()
            if exists:
                raise ValueError("该生图模型已存在")
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
        self._grs_model_cache.clear()
        return self.list_grs_image_models()

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

        record: dict[str, Any] = {
            "id": row["id"],
            "owner_user_id": row["owner_user_id"],
            "title": row["title"],
            "summary": row["summary"] or "",
            "source_script": source_script,
            "style_vibe": row["style_vibe"],
            "requested_shot_count": row["requested_shot_count"],
            "has_source_script": bool(source_script.strip()),
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

    def request_director_operation_cancel(self, operation_id: str) -> dict[str, Any]:
        operation = self.get_director_operation(operation_id)
        if operation["status"] in {"succeeded", "failed", "interrupted", "cancelled"}:
            return operation
        return self.update_director_operation(operation_id, cancel_requested=True)

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

    def copy_director_project(self, project_id: str, owner_user_id: str) -> dict[str, Any]:
        source = self.get_director_project(project_id)
        title = source["title"].strip() or "未命名分镜工程"
        copy_title = f"{title} 副本"
        return self.create_director_project(
            owner_user_id,
            copy_title,
            summary=source["summary"],
            source_script=source["source_script"],
            style_vibe=source["style_vibe"],
            requested_shot_count=source["requested_shot_count"],
            payload=source["payload"],
        )

    def import_director_projects(
        self, owner_user_id: str, projects: list[dict[str, Any]],
    ) -> dict[str, Any]:
        imported: list[dict[str, Any]] = []
        skipped = 0
        for item in projects:
            requested_id = (item.get("id") or "").strip() or None
            title = (item.get("title") or "").strip() or "未命名分镜工程"
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            try:
                if requested_id:
                    existing = None
                    try:
                        existing = self.get_director_project(requested_id)
                    except KeyError:
                        existing = None
                    if existing is not None:
                        skipped += 1
                        continue
                created = self.create_director_project(
                    owner_user_id,
                    title,
                    project_id=requested_id,
                    summary=item.get("summary") or "",
                    source_script=item.get("source_script") or "",
                    style_vibe=item.get("style_vibe"),
                    requested_shot_count=item.get("requested_shot_count"),
                    payload=payload,
                    created_at=item.get("created_at"),
                    updated_at=item.get("updated_at"),
                )
            except ValueError:
                skipped += 1
                continue
            imported.append(created)
        listed = self.list_director_projects(owner_user_id)
        return {"imported": len(imported), "skipped": skipped, "projects": listed}

    def convert_director_project_to_recipe(self, project_id: str) -> dict[str, Any]:
        from .director_recipe import PAYLOAD_KIND_RECIPE, payload_kind, timeline_to_recipe

        current = self.get_director_project(project_id)
        if payload_kind(current.get("payload")) == PAYLOAD_KIND_RECIPE:
            return current
        recipe = timeline_to_recipe(
            current.get("payload"),
            title=current.get("title") or "",
            summary=current.get("summary") or "",
            source_script=current.get("source_script") or "",
        )
        return self.update_director_project(project_id, payload=recipe)

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
