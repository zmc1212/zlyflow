from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import JobMode, JobStatus


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED.value,
    JobStatus.FAILED.value,
    JobStatus.INTERRUPTED.value,
}


class JobStore:
    """SQLite persistence for task aggregates, rounds, generation items and providers.

    The original flat columns on ``jobs`` remain the compatibility mirror of the
    latest round. New code writes normalized rows first and refreshes the mirror.
    """

    MIGRATION_NAME = "2026-08-13-ai-studio-rounds-v1"

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self._backup_before_migration()
        self.initialize()

    def _backup_before_migration(self) -> None:
        if not self.database_path.exists() or self.database_path.stat().st_size == 0:
            return
        backup = self.database_path.with_name(f"{self.database_path.name}.pre-ai-studio-migration.bak")
        if not backup.exists():
            shutil.copy2(self.database_path, backup)

    def connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, name: str, declaration: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    def initialize(self) -> None:
        with self.connection() as connection:
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

                CREATE INDEX IF NOT EXISTS idx_jobs_owner_created ON jobs(owner_user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_rounds_job_sequence ON job_rounds(job_id, sequence DESC);
                CREATE INDEX IF NOT EXISTS idx_items_round_index ON generation_items(round_id, item_index);
                CREATE INDEX IF NOT EXISTS idx_items_remote_task ON generation_items(remote_task_id);
                """
            )
            connection.execute(
                """INSERT OR IGNORE INTO grs_provider_settings
                (id, enabled, base_url, gpt_image_2_enabled, gpt_image_2_vip_enabled, updated_at)
                VALUES (1, 0, 'https://grsai.dakka.com.cn', 1, 1, ?)""",
                (now(),),
            )
            connection.execute(
                """INSERT OR IGNORE INTO qiniu_provider_settings
                (id, enabled, bucket, region, domain, object_prefix, updated_at)
                VALUES (1, 0, '', 'z0', '', 'zly-ai-video-studio/', ?)""",
                (now(),),
            )
            self._migrate_legacy_jobs(connection)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES (?, ?)",
                (self.MIGRATION_NAME, now()),
            )

    @staticmethod
    def _media_for_mode(mode: str) -> str:
        return "image" if mode in {JobMode.IMAGE.value, JobMode.GRS_GPT_IMAGE_2.value, JobMode.GRS_GPT_IMAGE_2_VIP.value} else "video"

    @staticmethod
    def _executor_for_mode(mode: str) -> str:
        return "grs" if mode in {JobMode.GRS_GPT_IMAGE_2.value, JobMode.GRS_GPT_IMAGE_2_VIP.value} else "comfyui"

    def _migrate_legacy_jobs(self, connection: sqlite3.Connection) -> None:
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
        mode: JobMode,
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
        media_type = self._media_for_mode(mode.value)
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
                    job_id, owner_user_id, mode.value, media_type, title, round_id,
                    source.get("job_id"), source.get("generation_item_id"), source.get("output_index"),
                    JobStatus.QUEUED.value, "等待排队", 0, prompt, negative_prompt, image_size,
                    json.dumps(options or {}, ensure_ascii=False),
                    json.dumps(submitted_options or {}, ensure_ascii=False), int(submitted_options is not None),
                    json.dumps(references, ensure_ascii=False), timestamp, timestamp,
                ),
            )
            self._insert_round(
                connection, round_id, job_id, 1, mode, media_type, prompt, negative_prompt,
                image_size, references, options or {}, submitted_options,
            )
        return self.get(job_id)

    def _insert_round(
        self, connection: sqlite3.Connection, round_id: str, job_id: str, sequence: int,
        mode: JobMode, media_type: str, prompt: str, negative_prompt: str,
        image_size: str | None, references: list[str], options: dict,
        submitted_options: dict | None,
    ) -> None:
        timestamp = now()
        connection.execute(
            """INSERT INTO job_rounds
            (id, job_id, sequence, mode, media_type, status, stage, progress, prompt,
             negative_prompt, image_size, options_json, submitted_options_json,
             options_submitted, references_json, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
            (
                round_id, job_id, sequence, mode.value, media_type, JobStatus.QUEUED.value, "等待排队",
                prompt, negative_prompt, image_size, json.dumps(options, ensure_ascii=False),
                json.dumps(submitted_options or {}, ensure_ascii=False), int(submitted_options is not None),
                json.dumps(references, ensure_ascii=False), timestamp, timestamp,
            ),
        )
        count = int(options.get("count", 1)) if media_type == "image" else 1
        executor = self._executor_for_mode(mode.value)
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
        mode = JobMode(job["mode"])
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
    ) -> dict:
        job = self.get(job_id)
        latest = job["rounds"][-1]
        item = latest["generation_items"][0]
        self.update_generation(
            item["id"], status=status, stage=stage, progress=progress, outputs=outputs, error=error,
        )
        return self.get(job_id)

    def update_generation(
        self, generation_item_id: str, *, status: JobStatus | str | None = None,
        stage: str | None = None, progress: int | None = None, outputs: list[dict] | None = None,
        error: str | None = None, remote_task_id: str | None = None, remote_status: str | None = None,
        comfy_prompt_id: str | None = None, comfy_client_id: str | None = None,
        comfy_phase: str | None = None, clear_execution: bool = False,
    ) -> dict:
        updates: dict[str, Any] = {"updated_at": now()}
        if status is not None:
            updates["status"] = status.value if isinstance(status, JobStatus) else status
        if stage is not None:
            updates["stage"] = stage
        if progress is not None:
            updates["progress"] = max(0, min(100, int(progress)))
        if outputs is not None:
            updates["outputs_json"] = json.dumps(outputs, ensure_ascii=False)
        if error is not None:
            updates["error"] = error
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
        assignment = ", ".join(f"{column} = ?" for column in updates)
        with self.connection() as connection:
            row = connection.execute(
                "SELECT r.job_id, i.round_id FROM generation_items i JOIN job_rounds r ON r.id = i.round_id WHERE i.id = ?",
                (generation_item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(generation_item_id)
            connection.execute(f"UPDATE generation_items SET {assignment} WHERE id = ?", (*updates.values(), generation_item_id))
            self._refresh_round(connection, row["round_id"])
            self._refresh_job(connection, row["job_id"])
        return self.get_generation(generation_item_id)

    def _refresh_round(self, connection: sqlite3.Connection, round_id: str) -> None:
        items = connection.execute("SELECT * FROM generation_items WHERE round_id = ? ORDER BY item_index", (round_id,)).fetchall()
        if len(items) == 1:
            item = items[0]
            connection.execute(
                "UPDATE job_rounds SET status = ?, stage = ?, progress = ?, error = ?, updated_at = ? WHERE id = ?",
                (item["status"], item["stage"], item["progress"], item["error"], now(), round_id),
            )
            return
        statuses = [row["status"] for row in items]
        successes = statuses.count(JobStatus.SUCCEEDED.value)
        if statuses and successes == len(statuses):
            status, stage, progress, error = JobStatus.SUCCEEDED.value, "生成完成", 100, None
        elif successes and all(value in TERMINAL_STATUSES for value in statuses):
            status, stage, progress = JobStatus.PARTIAL.value, "部分生成完成", round(100 * successes / len(statuses))
            error = "部分生成项失败，可只重试失败项。"
        elif any(value == JobStatus.RUNNING.value for value in statuses):
            status, stage, progress, error = JobStatus.RUNNING.value, "正在生成", round(sum(row["progress"] for row in items) / len(items)), None
        elif any(value == JobStatus.QUEUED.value for value in statuses):
            status, stage, progress, error = JobStatus.QUEUED.value, "等待排队", round(sum(row["progress"] for row in items) / len(items)), None
        elif statuses and all(value == JobStatus.INTERRUPTED.value for value in statuses):
            status, stage, progress, error = JobStatus.INTERRUPTED.value, "任务已中断", 0, next((row["error"] for row in items if row["error"]), None)
        else:
            status, stage, progress, error = JobStatus.FAILED.value, "生成失败", 0, next((row["error"] for row in items if row["error"]), None)
        connection.execute(
            "UPDATE job_rounds SET status = ?, stage = ?, progress = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, stage, progress, error, now(), round_id),
        )

    def _refresh_job(self, connection: sqlite3.Connection, job_id: str) -> None:
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
            comfy_client_id = ?, comfy_phase = ?, updated_at = ? WHERE id = ?""",
            (
                row["mode"], row["media_type"], row["id"], row["status"], row["stage"], row["progress"],
                row["prompt"], row["negative_prompt"], row["image_size"], row["options_json"],
                row["submitted_options_json"], row["options_submitted"], row["references_json"],
                json.dumps(outputs, ensure_ascii=False), row["error"], first["comfy_prompt_id"] if first else None,
                first["comfy_client_id"] if first else None, first["comfy_phase"] if first else None,
                now(), job_id,
            ),
        )

    def set_comfy_execution(self, job_id: str, prompt_id: str, client_id: str | None, phase: str) -> dict:
        item = self.get(job_id)["rounds"][-1]["generation_items"][0]
        self.update_generation(
            item["id"], status=JobStatus.RUNNING, comfy_prompt_id=prompt_id,
            comfy_client_id=client_id, comfy_phase=phase,
        )
        return self.get(job_id)

    def clear_comfy_execution(self, job_id: str) -> dict:
        item = self.get(job_id)["rounds"][-1]["generation_items"][0]
        self.update_generation(item["id"], clear_execution=True)
        return self.get(job_id)

    def retry_terminal(self, job_id: str) -> dict | None:
        job = self.get(job_id)
        if job.get("legacy_read_only"):
            return None
        item = job["rounds"][-1]["generation_items"][0]
        if item["status"] not in {JobStatus.INTERRUPTED.value, JobStatus.FAILED.value} or item.get("comfy_prompt_id"):
            return None
        self.update_generation(
            item["id"], status=JobStatus.QUEUED, stage="等待重新提交", progress=0,
            outputs=[], error="", clear_execution=True,
        )
        return self.get(job_id)

    def retry_failed_items(self, job_id: str, round_id: str | None = None) -> list[dict]:
        job = self.get(job_id)
        target = next((item for item in job["rounds"] if item["id"] == round_id), job["rounds"][-1])
        retried: list[dict] = []
        for item in target["generation_items"]:
            if item["status"] in {JobStatus.FAILED.value, JobStatus.INTERRUPTED.value}:
                retried.append(self.update_generation(
                    item["id"], status=JobStatus.QUEUED, stage="等待重新提交", progress=0,
                    outputs=[], error="", remote_status="", clear_execution=True,
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
        return [self.decode(row, include_references=True) for row in rows]

    def recoverable_generation_items(self, executor: str) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT i.* FROM generation_items i
                WHERE i.executor = ? AND i.status IN (?, ?) ORDER BY i.created_at""",
                (executor, JobStatus.QUEUED.value, JobStatus.RUNNING.value),
            ).fetchall()
        return [self._decode_generation(row) for row in rows]

    @staticmethod
    def _decode_outputs(value: str) -> list[dict]:
        outputs = json.loads(value or "[]")
        for output in outputs:
            output.setdefault("delivery_status", "pending")
            output.setdefault("delivered_at", None)
        return outputs

    @classmethod
    def _decode_generation(cls, row: sqlite3.Row) -> dict:
        data = dict(row)
        data["index"] = data.pop("item_index")
        data["outputs"] = cls._decode_outputs(data.pop("outputs_json"))
        return data

    def _rounds_for_job(self, connection: sqlite3.Connection, job_id: str, include_references: bool) -> list[dict]:
        rows = connection.execute("SELECT * FROM job_rounds WHERE job_id = ? ORDER BY sequence", (job_id,)).fetchall()
        rounds: list[dict] = []
        for row in rows:
            data = dict(row)
            refs = json.loads(data.pop("references_json") or "[]")
            data["options"] = json.loads(data.pop("options_json") or "{}")
            data["submitted_options"] = json.loads(data.pop("submitted_options_json") or "{}")
            data["options_submitted"] = bool(data.pop("options_submitted", False))
            data["reference_count"] = len(refs)
            if include_references:
                data["references"] = refs
            items = connection.execute(
                "SELECT * FROM generation_items WHERE round_id = ? ORDER BY item_index", (data["id"],)
            ).fetchall()
            data["generation_items"] = [self._decode_generation(item) for item in items]
            rounds.append(data)
        return rounds

    def decode(self, row: sqlite3.Row, *, include_references: bool = False, connection: sqlite3.Connection | None = None) -> dict:
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
            data["rounds"] = self._rounds_for_job(active, data["id"], include_references)
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
            rows = connection.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [self.decode(row, connection=connection) for row in rows]

    def list_for_user(self, user_id: str, limit: int = 100) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE owner_user_id = ? ORDER BY pinned DESC, created_at DESC LIMIT ?", (user_id, limit)
            ).fetchall()
            return [self.decode(row, connection=connection) for row in rows]

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

    def update_qiniu_settings(self, **values: Any) -> dict:
        allowed = {
            "enabled", "access_key_encrypted", "secret_key_encrypted", "bucket", "region", "domain", "object_prefix",
            "last_test_status", "last_test_message", "last_test_at",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        updates["updated_at"] = now()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self.connection() as connection:
            connection.execute(f"UPDATE qiniu_provider_settings SET {assignment} WHERE id = 1", tuple(updates.values()))
        return self.get_qiniu_settings()
