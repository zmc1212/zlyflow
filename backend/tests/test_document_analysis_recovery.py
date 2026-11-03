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


class DocumentAnalysisSectionRecoveryTests(unittest.TestCase):
    """旧文档存的是当时那版解析器的结果：人物恒为空、章节名写成「故事定位」时整节丢失。"""

    SCRIPT = """# 闪婚蜜爱

## 故事定位
现代都市情感短剧。讲述苏念在民政局门口偶遇厉景深，两人一拍即合闪婚。

## 主要人物
*   **苏念**（女，24岁）：插画师，性格倔强独立。
*   **厉景深**（男，28岁）：集团总裁，外表高冷。

## 第一集：冤家路窄

### 镜头 1
**场景**：民政局门口 / 日 / 外
**人物**：苏念、厉景深
**时长**：15秒
**动作**：两人在台阶上对视。
"""

    def _row(self, analysis: dict, raw_text: str | None = None) -> dict:
        return {
            "id": "doc-2",
            "project_id": "proj-2",
            "input_mode": "assistant_v2",
            "raw_text": raw_text if raw_text is not None else self.SCRIPT,
            "analysis_json": json.dumps(analysis, ensure_ascii=False),
        }

    def _stale_analysis(self, **overrides: object) -> dict:
        base: dict = {
            "episodes": [{"episode_num": 1, "shots": [{"shot_num": 1, "scene": "民政局门口 / 日 / 外"}]}],
            "scenes": [{"name": "民政局门口 / 日 / 外"}],
            "scene_analysis_revision": 2,
            "characters": [],
            "positioning": {
                "genre": "",
                "worldview": "",
                "duration_per_episode": "",
                "shots_per_episode": "",
                "main_storyline": "",
                "items": [],
            },
            "visual_style": {"description": "", "prohibited": ""},
            "production_advice": "",
            "summary": "共解析出 1 集剧情、1 个分镜头；识别到 0 位主要人物、1 处拍摄场景、0 件核心道具。",
        }
        base.update(overrides)
        return base

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_fills_stale_characters_and_positioning_from_raw_text(self, execute_sql) -> None:
        analysis = ProjectDetailService._analysis_for_document_row(self._row(self._stale_analysis()), persist=True)

        self.assertEqual(["苏念", "厉景深"], [item["name"] for item in analysis["characters"]])
        self.assertIn("现代都市情感短剧", analysis["positioning"]["items"][0])
        self.assertEqual(1, analysis["analysis_sections_revision"])
        self.assertIn("识别到 2 位主要人物", analysis["summary"])
        execute_sql.assert_called_once()
        stored = json.loads(execute_sql.call_args.args[1][0])
        self.assertEqual(["苏念", "厉景深"], [item["name"] for item in stored["characters"]])

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_never_overwrites_sections_that_already_have_content(self, execute_sql) -> None:
        row = self._row(self._stale_analysis(
            characters=[{"name": "旧人物"}],
            positioning={"genre": "既定类型", "items": []},
            visual_style={"description": "既定风格", "prohibited": ""},
            production_advice="既定建议",
        ))

        analysis = ProjectDetailService._analysis_for_document_row(row, persist=True)

        self.assertEqual(["旧人物"], [item["name"] for item in analysis["characters"]])
        self.assertEqual("既定类型", analysis["positioning"]["genre"])
        self.assertEqual("既定风格", analysis["visual_style"]["description"])
        self.assertNotIn("analysis_sections_revision", analysis)
        for call in execute_sql.call_args_list:
            self.assertNotIn("苏念", call.args[1][0])

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_skips_reparsing_once_revision_is_stamped(self, execute_sql) -> None:
        row = self._row(self._stale_analysis(analysis_sections_revision=1))

        analysis = ProjectDetailService._analysis_for_document_row(row, persist=True)

        self.assertEqual([], analysis["characters"])
        execute_sql.assert_not_called()

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_leaves_script_without_those_sections_untouched(self, execute_sql) -> None:
        row = self._row(self._stale_analysis(), raw_text="# 第1集 无标签\n\n正文没有场景与人物标签。")

        analysis = ProjectDetailService._analysis_for_document_row(row, persist=True)

        self.assertEqual([], analysis["characters"])
        self.assertNotIn("analysis_sections_revision", analysis)
        execute_sql.assert_not_called()


class DocumentAssetAppendTests(unittest.TestCase):
    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_all", return_value=[{"id": "scene", "kind": "scene", "name": "民政局门口"}])
    @patch("backend.app.media_studio.services.project_detail_service.query_one", return_value={"id": "d"})
    @patch.object(ProjectDetailService, "_analysis_for_document_row", return_value={"scenes": [{"name": "民政局门口 / 日 / 外"}, {"name": "民政局门口 / 夜 / 外"}]})
    def test_time_and_interior_exterior_labels_reuse_same_scene(self, analysis, query, assets, execute) -> None:
        result = ProjectDetailService.transfer_assets_from_document("p", "d", mode="append")
        self.assertEqual(0, result["total"])
        self.assertEqual(1, execute.call_count)
        self.assertIn("assets_extracted_episode_nums", execute.call_args.args[0])

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_all")
    @patch("backend.app.media_studio.services.project_detail_service.query_one", return_value={"id": "d"})
    @patch.object(ProjectDetailService, "_analysis_for_document_row")
    def test_append_keeps_all_existing_customized_asset_fields(self, analysis, query, assets, execute) -> None:
        analysis.return_value = {"characters": [{"name": "苏念", "description": "剧本旧设定"}], "scenes": [{"name": "夜市"}], "props": [{"name": "手机"}]}
        assets.return_value = [{"id": "character", "kind": "character", "name": "苏念"}, {"id": "scene", "kind": "scene", "name": "夜市"}, {"id": "prop", "kind": "prop", "name": "手机"}]
        result = ProjectDetailService.transfer_assets_from_document("p", "d", mode="append")
        self.assertEqual(0, result["total"])
        self.assertTrue(all("ai_project_assets" not in call.args[0] for call in execute.call_args_list))

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_all", return_value=[])
    @patch("backend.app.media_studio.services.project_detail_service.query_one", return_value={"id": "d"})
    @patch.object(ProjectDetailService, "_analysis_for_document_row")
    def test_append_creates_new_assets_without_update_statements(self, analysis, query, assets, execute) -> None:
        analysis.return_value = {"characters": [{"name": "苏念"}], "scenes": [{"name": "夜市"}], "props": [{"name": "手机"}]}
        result = ProjectDetailService.transfer_assets_from_document("p", "d", mode="append")
        self.assertEqual(3, result["total"])
        self.assertEqual(4, execute.call_count)
        for call in execute.call_args_list[:-1]:
            self.assertIn("INSERT INTO ai_project_assets", call.args[0])
        self.assertIn("assets_extracted_episode_nums", execute.call_args_list[-1].args[0])

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql", return_value=1)
    @patch("backend.app.media_studio.services.project_detail_service.query_all", return_value=[])
    @patch("backend.app.media_studio.services.project_detail_service.query_one", return_value={"id": "d", "raw_text": "original"})
    @patch.object(ProjectDetailService, "_analysis_for_document_row", return_value={"characters": [{"name": "阿文"}], "episodes": [{"episode_num": 1}, {"episode_num": 2}]})
    def test_extraction_locks_current_body_numbers_without_overwriting_other_analysis(self, analysis, query, assets, execute):
        ProjectDetailService.transfer_assets_from_document("p", "d", mode="append")
        sql, args = execute.call_args.args
        self.assertIn("JSON_SET", sql)
        self.assertIn("COALESCE(raw_text,'')=%s", sql)
        self.assertEqual(args[:2], (1, 2))
        self.assertEqual(args[-1], "original")
        execute.return_value = 0
        query.side_effect = [{"id": "d", "raw_text": "original"}, {"raw_text": "changed"}]
        with self.assertRaisesRegex(ValueError, "剧本已更新"):
            ProjectDetailService.transfer_assets_from_document("p", "d", mode="append")


class DocumentEditingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.row = {"id": "doc-edit", "project_id": "project-edit", "raw_text": "旧剧本", "input_mode": "paste", "analysis_json": "{}"}
        self.query = patch("backend.app.media_studio.services.project_detail_service.query_one", return_value=self.row).start()
        self.execute = patch("backend.app.media_studio.services.project_detail_service.execute_sql", return_value=1).start()
        self.productions = patch("backend.app.media_studio.services.project_detail_service.query_all", return_value=[]).start()
        self.active = patch("backend.app.media_studio.services.shot_plan_job_service.ShotPlanJobService.active_job_ids_by_document", return_value={}).start()
        self.addCleanup(patch.stopall)

    def test_save_keeps_document_id_and_updates_only_document(self) -> None:
        updated = ProjectDetailService.update_document("project-edit", "doc-edit", SCRIPT, "旧剧本")
        self.assertEqual("doc-edit", updated["id"])
        self.assertEqual(SCRIPT, updated["raw_text"])
        self.assertEqual(len(SCRIPT.encode("utf-8")), updated["file_size"])
        self.assertEqual(2, len(updated["analysis"]["episodes"][0]["shots"]))
        self.execute.assert_called_once()
        sql, args = self.execute.call_args.args
        self.assertIn("AND COALESCE(raw_text, '') = %s", sql)
        self.assertEqual("旧剧本", args[-1])
        self.assertNotIn("ai_project_assets", sql)
        self.assertNotIn("ai_project_episodes", sql)

    def test_stale_editor_does_not_overwrite_newer_script(self) -> None:
        with self.assertRaisesRegex(ValueError, "已更新"):
            ProjectDetailService.update_document("project-edit", "doc-edit", SCRIPT, "更早的剧本")
        self.execute.assert_not_called()

    def test_running_plan_cannot_be_replaced(self) -> None:
        self.active.return_value = {"doc-edit": "planning-job"}
        with self.assertRaisesRegex(ValueError, "正在进行"):
            ProjectDetailService.update_document("project-edit", "doc-edit", SCRIPT, "旧剧本")
        self.execute.assert_not_called()

    def test_concurrent_write_after_read_is_rejected(self) -> None:
        self.execute.return_value = 0
        with self.assertRaisesRegex(ValueError, "已更新"):
            ProjectDetailService.update_document("project-edit", "doc-edit", SCRIPT, "旧剧本")

    def test_empty_script_does_not_erase_document(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能为空"):
            ProjectDetailService.update_document("project-edit", "doc-edit", "  ", "旧剧本")
        self.execute.assert_not_called()

    def test_full_document_editor_cannot_bypass_extracted_episode_lock(self):
        from backend.app.director_assistant.script_documents import parsed_script
        self.row.update(raw_text=SCRIPT, analysis_json=json.dumps({**parsed_script(SCRIPT), "assets_extracted_episode_nums": [1]}))
        with self.assertRaisesRegex(ValueError, "资产已拆解"):
            ProjectDetailService.update_document("project-edit", "doc-edit", SCRIPT.replace("办公室异常安静", "修改第一集"), SCRIPT)
        self.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
