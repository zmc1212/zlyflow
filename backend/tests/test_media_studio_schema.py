from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import unittest

from backend.app.db import (
    Database,
    _split_statements,
    is_isolated_sqlite_runtime,
    mysql_schema_sql,
    skip_mysql_ddl_statement,
)
from backend.app.media_studio import db as media_db
from backend.app.storage import JobStore


class MediaStudioSchemaTests(unittest.TestCase):
    def test_new_mysql_llm_schema_includes_assistant_models(self) -> None:
        create = next(
            item for item in _split_statements(mysql_schema_sql())
            if item.strip().upper().startswith("CREATE TABLE") and "llm_provider_settings" in item
        )
        self.assertIn("assistant_models_json TEXT NULL", create)

    def test_existing_mysql_llm_table_is_migrated_once_on_startup(self) -> None:
        database = MagicMock(spec=Database)
        database.dialect = "mysql"
        connection = database.connection.return_value.__enter__.return_value
        columns = {
            "llm_provider_settings": {"id", "enabled", "base_url", "model", "api_key_encrypted"},
            "vlm_provider_settings": {"use_llm_credentials"},
            "canvas_projects": {"tags_json", "is_favorite", "deleted_at", "preview_json", "linked_director_project_id"},
            "generation_items": {"refine_state_json"},
            "job_rounds": {"display_prompt"},
            # 当前基线 music_jobs 已含 chat_id；本用例只验证 LLM 迁移恰好执行一次。
            "music_jobs": {"chat_id"},
        }
        database.column_names.side_effect = lambda conn, table: columns[table]
        database.ensure_column.side_effect = lambda *args: Database.ensure_column(database, *args)

        def apply_column(sql: str) -> None:
            parts = sql.split()
            self.assertEqual(parts[:2], ["ALTER", "TABLE"])
            self.assertNotIn(parts[5], columns[parts[2]])
            columns[parts[2]].add(parts[5])

        connection.execute.side_effect = apply_column
        store = JobStore.__new__(JobStore)
        store._db = database
        with patch.object(store, "_ensure_job_list_indexes"), patch.object(store, "_seed_runtime_defaults"):
            store.initialize()
            store.initialize()
        connection.execute.assert_called_once_with(
            "ALTER TABLE llm_provider_settings ADD COLUMN assistant_models_json TEXT"
        )

    def test_docker_mysql_backend_is_not_forced_to_sqlite(self) -> None:
        self.assertFalse(
            is_isolated_sqlite_runtime("mysql", argv=["uvicorn", "backend.app.main:app"], unittest_loaded=False)
        )
        self.assertTrue(
            is_isolated_sqlite_runtime("sqlite", argv=["uvicorn", "backend.app.main:app"], unittest_loaded=False)
        )
        self.assertTrue(is_isolated_sqlite_runtime("mysql", argv=["python", "-m", "unittest"], unittest_loaded=False))

    def test_mysql_schema_replays_ai_project_jobs_create_table(self) -> None:
        statements = _split_statements(mysql_schema_sql())
        create = next(
            item for item in statements
            if "ai_project_jobs" in item and item.strip().upper().startswith("CREATE TABLE")
        )
        self.assertFalse(skip_mysql_ddl_statement(create), create)

    def test_ensure_schema_applies_mysql_ddl_when_forced(self) -> None:
        media_db._schema_ready = False
        fake_db = MagicMock()
        try:
            with patch("backend.app.db.MysqlDatabase", return_value=fake_db):
                media_db.ensure_schema(force=True)
            fake_db.connection.assert_called_once()
            connection = fake_db.connection.return_value.__enter__.return_value
            fake_db.apply_mysql_schema.assert_called_once_with(connection)
        finally:
            media_db._schema_ready = False
