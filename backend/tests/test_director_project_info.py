from __future__ import annotations

import json
import sqlite3
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from backend.app.media_studio.models import ProjectCreateRequest, ProjectUpdateRequest
from backend.app.media_studio.services.project_service import ProjectService
from backend.app.media_studio.services.ai_generation_service import AiGenerationService


class DirectorProjectInfoTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE ai_projects (
            id TEXT PRIMARY KEY, name TEXT, description TEXT, cover_url TEXT,
            status TEXT, settings_json TEXT, created_at TEXT, updated_at TEXT)""")
        self.db.execute("INSERT INTO ai_projects VALUES ('p1', '未命名导演工程', '', NULL, 'active', ?, 'now', 'now')",
                        (json.dumps({"extra": {"workshop_aspect_ratio": "16:9"}}),))
        self.addCleanup(self.db.close)
        module = "backend.app.media_studio.services.project_service"
        self.query = patch(module + ".query_one", side_effect=self.query_one).start()
        self.execute = patch(module + ".execute_sql", side_effect=self.execute_sql).start()
        self.addCleanup(patch.stopall)

    def query_one(self, sql, params=()):
        row = self.db.execute(sql.replace("%s", "?"), params).fetchone()
        return dict(row) if row else None

    def execute_sql(self, sql, params=()):
        return self.db.execute(sql.replace("%s", "?"), params).rowcount

    def test_generated_script_names_project_and_fills_summary(self):
        ProjectService.sync_generated_script_info("p1", {"title": "雨夜来信", "summary": "一次错寄的来信改变两个人的命运。"})
        saved = ProjectService.get_project("p1")
        self.assertEqual(saved.name, "雨夜来信")
        self.assertEqual(saved.description, "一次错寄的来信改变两个人的命运。")
        self.assertEqual(saved.extra["name_source"], "ai")
        self.assertEqual(saved.extra["workshop_aspect_ratio"], "16:9")
        ProjectService.sync_generated_script_info("p1", {"title": "雨夜回声", "summary": "新的故事梗概"})
        self.assertEqual(ProjectService.get_project("p1").name, "雨夜回声")

    def test_manual_edit_survives_regeneration_and_preserves_settings(self):
        ProjectService.sync_generated_script_info("p1", {"title": "雨夜来信", "summary": "AI 简介"})
        saved = ProjectService.update_project("p1", ProjectUpdateRequest(name="  我的新剧  ", description="我的简介"))
        self.assertEqual(saved.name, "我的新剧")
        self.assertEqual(saved.extra["workshop_aspect_ratio"], "16:9")
        ProjectService.sync_generated_script_info("p1", {"title": "不应覆盖", "summary": "不应覆盖"})
        saved = ProjectService.get_project("p1")
        self.assertEqual((saved.name, saved.description), ("我的新剧", "我的简介"))

    def test_existing_custom_name_without_metadata_is_preserved(self):
        self.db.execute("UPDATE ai_projects SET name='用户原有剧名',description='原有简介'")
        ProjectService.sync_generated_script_info("p1", {"title": "新标题", "summary": "新简介"})
        saved = ProjectService.get_project("p1")
        self.assertEqual((saved.name, saved.description), ("用户原有剧名", "原有简介"))

    def test_manual_empty_summary_stays_empty_and_same_name_is_locked(self):
        ProjectService.sync_generated_script_info("p1", {"title": "雨夜来信", "summary": "AI 简介"})
        ProjectService.update_project("p1", ProjectUpdateRequest(name="雨夜来信", description=""))
        ProjectService.sync_generated_script_info("p1", {"title": "另一个标题", "summary": "新简介"})
        saved = ProjectService.get_project("p1")
        self.assertEqual((saved.name, saved.description), ("雨夜来信", ""))

    def test_concurrent_manual_change_wins_over_ai(self):
        def save_after_manual_edit(sql, params):
            self.db.execute("UPDATE ai_projects SET name='刚刚手动改名'")
            return self.execute_sql(sql, params)
        self.execute.side_effect = save_after_manual_edit
        ProjectService.sync_generated_script_info("p1", {"title": "AI 标题", "summary": "AI 简介"})
        self.assertEqual(ProjectService.get_project("p1").name, "刚刚手动改名")

    def test_rejects_blank_or_too_long_names(self):
        with self.assertRaisesRegex(ValueError, "不能为空"):
            ProjectService.update_project("p1", ProjectUpdateRequest(name="   "))
        for model in (ProjectCreateRequest, ProjectUpdateRequest):
            with self.assertRaises(ValidationError):
                model(name="剧" * 256)
        for title in ("", "   ", "未命名剧本", "剧" * 256):
            ProjectService.sync_generated_script_info("p1", {"title": title})
        self.assertEqual(ProjectService.get_project("p1").name, "未命名导演工程")

    def test_script_adapter_syncs_title_only_at_script_stage(self):
        service = AiGenerationService.__new__(AiGenerationService)
        service.persist_recipe_assets = Mock()
        recipe = {"script": {"title": "雨夜来信", "summary": "简介", "fullStory": "故事正文"}}
        with patch("backend.app.media_studio.services.ai_generation_service.query_one", return_value={"id": "doc1"}), \
             patch("backend.app.media_studio.services.ai_generation_service.execute_sql"), \
             patch.object(ProjectService, "sync_generated_script_info") as sync:
            service._adapt_recipe("p1", recipe, "script")
            sync.assert_called_once_with("p1", recipe["script"])
            sync.reset_mock()
            service._adapt_recipe("p1", recipe, "assets")
            sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()
