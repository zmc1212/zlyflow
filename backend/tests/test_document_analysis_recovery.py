from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.media_studio.services.project_detail_service import ProjectDetailService

SCRIPT = """# 夜班守则

# 第1集 午夜禁地

### 镜头 1
**场景**：开放式办公区 - 夜
**人物**：李明
**时长**：15秒
**画面**：
办公室异常安静。

### 镜头 2
**场景**：诡异洗手间 - 夜
**人物**：李明
**时长**：20秒
**画面**：
感应灯忽明忽暗。
"""


class DocumentAnalysisRecoveryTests(unittest.TestCase):
    def _row(self, analysis: dict) -> dict:
        return {
            "id": "doc-1",
            "project_id": "proj-1",
            "input_mode": "assistant_v2",
            "raw_text": SCRIPT,
            "analysis_json": json.dumps(analysis, ensure_ascii=False),
        }

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_reparses_parser_derived_document_when_scenes_are_missing(self, execute_sql) -> None:
        row = self._row({
            "episodes": [{
                "episode_num": 1,
                "shots_count": 2,
                "shots": [{"shot_num": 1, "scene": ""}, {"shot_num": 2, "scene": ""}],
            }],
            "scenes": [],
            "summary": "共解析出 1 集剧情、2 个分镜头；识别到 0 位主要人物、0 处拍摄场景、0 件核心道具。",
        })

        analysis = ProjectDetailService._analysis_for_document_row(row, persist=True)

        self.assertEqual(["开放式办公区 - 夜", "诡异洗手间 - 夜"], [scene["name"] for scene in analysis["scenes"]])
        self.assertEqual(["开放式办公区 - 夜", "诡异洗手间 - 夜"], [shot["scene"] for shot in analysis["episodes"][0]["shots"]])
        self.assertEqual(2, analysis["scene_analysis_revision"])
        self.assertIn("2 处拍摄场景", analysis["summary"])
        execute_sql.assert_called_once()
        self.assertIn("UPDATE ai_project_documents", execute_sql.call_args.args[0])

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_repairs_legacy_scene_title_on_read(self, execute_sql) -> None:
        row = self._row({
            "episodes": [{
                "episode_num": 1,
                "shots": [
                    {"shot_num": 1, "title": "**场景**：开放式办公区 - 夜", "scene": "开放式办公区 - 夜"},
                    {"shot_num": 2, "title": "**场景**：诡异洗手间 - 夜", "scene": "诡异洗手间 - 夜"},
                ],
            }],
            "scenes": [{"name": "开放式办公区 - 夜"}, {"name": "诡异洗手间 - 夜"}],
            "scene_analysis_revision": 1,
        })

        analysis = ProjectDetailService._analysis_for_document_row(row, persist=True)

        self.assertEqual(["镜头 1", "镜头 2"], [shot["title"] for shot in analysis["episodes"][0]["shots"]])
        self.assertEqual(2, analysis["scene_analysis_revision"])
        execute_sql.assert_called_once()

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_refreshes_stale_asset_summary_on_read(self, execute_sql) -> None:
        row = self._row({
            "episodes": [{"episode_num": 1, "shots": [{"shot_num": 1, "scene": "开放式办公区 - 夜"}]}],
            "scenes": [{"name": "开放式办公区 - 夜"}],
            "scene_analysis_revision": 1,
            "summary": "共解析出 1 集剧情、1 个分镜头；识别到 0 位主要人物、0 处拍摄场景、0 件核心道具。",
        })

        analysis = ProjectDetailService._analysis_for_document_row(row, persist=True)

        self.assertIn("1 处拍摄场景", analysis["summary"])
        execute_sql.assert_called_once()
        self.assertIn("1 处拍摄场景", json.loads(execute_sql.call_args.args[1][0])["summary"])

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_keeps_asset_counts_when_analysis_has_no_asset_arrays(self, execute_sql) -> None:
        row = self._row({
            "episodes": [{"episode_num": 1, "shots": [{"shot_num": 1, "scene": "开放式办公区 - 夜"}]}],
            "summary": "共解析出 1 集剧情、1 个分镜头；识别到 3 位主要人物、5 处拍摄场景、2 件核心道具。",
        })
        row["raw_text"] = "# 第1集 无标签\n\n正文没有场景标签。"

        analysis = ProjectDetailService._analysis_for_document_row(row, persist=True)

        self.assertIn("3 位主要人物、5 处拍摄场景、2 件核心道具", analysis["summary"])
        execute_sql.assert_not_called()

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_keeps_llm_planned_episodes_untouched(self, execute_sql) -> None:
        row = self._row({
            "episodes": [{"episode_num": 1, "shots_source": "llm", "shots_count": 1, "shots": [{"shot_num": 1, "scene": ""}]}],
            "scenes": [],
        })

        analysis = ProjectDetailService._analysis_for_document_row(row, persist=True)

        self.assertEqual([], analysis["scenes"])
        self.assertEqual("", analysis["episodes"][0]["shots"][0]["scene"])
        execute_sql.assert_not_called()


if __name__ == "__main__":
    unittest.main()
