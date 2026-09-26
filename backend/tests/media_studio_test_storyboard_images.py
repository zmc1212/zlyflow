from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import unittest
from unittest.mock import patch

from backend.app.media_studio.services.episode_image_prompts import beat_sketch_prompt
from backend.app.media_studio.services.storyboard_image_service import StoryboardImageService, _ACTIVE
from backend.app.media_studio.services.project_detail_service import (
    ProjectDetailService,
    asset_name_id_map,
    resolve_shot_scene,
)
from backend.app.media_studio.services.llm_service import LlmService


class StoryboardPromptTests(unittest.TestCase):
    def test_sketch_prompt_keeps_camera_but_excludes_render_style(self):
        prompt = beat_sketch_prompt(
            {"action": "Water enters the field", "camera": "Medium shot"},
            assets=[], visual_style="chinese_period_drama", ethnicity="Chinese",
        )
        self.assertIn("CAMERA SETUP (source of truth): Medium shot", prompt)
        self.assertIn("ACTION (source of truth): Water enters the field", prompt)
        self.assertNotIn("realistic skin", prompt.lower())
        self.assertNotIn("cinematic lighting", prompt.lower())
        self.assertNotIn("not illustration", prompt.lower())
        self.assertIn("rough symbolic storyboard medium", prompt)

    def test_empty_scene_inherits_instead_of_matching_first_asset(self):
        scene_map = {"Indoor room": "scene-room", "Village field": "scene-field"}
        self.assertEqual(
            ("Village field", "scene-field"),
            resolve_shot_scene("", scene_map, "Village field", "scene-field"),
        )
        self.assertEqual(
            ("Village field", "scene-field"),
            resolve_shot_scene("Village field", scene_map, "Indoor room", "scene-room"),
        )

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_all")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_get_episode_detail_initializes_inherited_scene(self, query_one, query_all, execute_sql):
        query_one.side_effect = [
            {
                "id": "ep-1",
                "project_id": "proj-1",
                "episode_num": 1,
                "title": "第一集",
                "status": "script_ready",
                "script_text": "开场",
                "data_json": "{}",
            },
            {
                "analysis_json": json.dumps({
                    "episodes": [{
                        "episode_num": 1,
                        "shots": [
                            {"shot_num": 1, "title": "开场", "scene": "出租屋", "action": "吴耐醒来"},
                            {"shot_num": 2, "title": "接续", "scene": "", "action": "看手机"},
                        ],
                    }],
                }, ensure_ascii=False),
            },
        ]
        query_all.return_value = [
            {"id": "scene-home", "kind": "scene", "name": "出租屋", "image_url": "", "extra_json": "{}"},
        ]
        detail = ProjectDetailService.get_episode_detail("proj-1", "ep-1")
        self.assertEqual(2, len(detail["beats"]))
        self.assertEqual("出租屋", detail["beats"][0]["scene"])
        self.assertEqual("scene-home", detail["beats"][0]["scene_id"])
        self.assertEqual("出租屋", detail["beats"][1]["scene"])
        self.assertEqual("scene-home", detail["beats"][1]["scene_id"])
        asset_query = query_all.call_args.args[0]
        self.assertIn("description", asset_query)
        self.assertIn("visual_prompt", asset_query)
        self.assertIn("ORDER BY updated_at DESC", asset_query)
        execute_sql.assert_called_once()

    def test_asset_name_map_prefers_the_copy_with_an_image(self):
        mapping = asset_name_id_map(
            [
                {"id": "scene-empty", "kind": "scene", "name": "开元楼走廊", "image_url": ""},
                {"id": "scene-ready", "kind": "scene", "name": "开元楼走廊", "image_url": "https://x/scene.png"},
            ],
            "scene",
        )
        self.assertEqual({"开元楼走廊": "scene-ready"}, mapping)


class StoryboardDispatcherTests(unittest.TestCase):
    def tearDown(self):
        _ACTIVE.clear()

    @patch.object(StoryboardImageService, "kick")
    @patch("backend.app.media_studio.services.storyboard_image_service.execute_sql", return_value=1)
    @patch("backend.app.media_studio.services.storyboard_image_service.query_all")
    def test_recovery_marks_orphaned_asset_images_failed(self, query_all, execute_sql, _kick):
        query_all.return_value = [
            {"id": "asset-job", "status": "running", "payload_json": '{"target_type":"identity"}'},
            {"id": "beat-job", "status": "running", "payload_json": '{"target_type":"beat_triptych"}'},
        ]

        StoryboardImageService.recover_interrupted_jobs()

        self.assertEqual(2, execute_sql.call_count)
        self.assertIn("status='failed'", execute_sql.call_args_list[0].args[0])
        self.assertIn("图片任务被中断", execute_sql.call_args_list[0].args[1][0])
        self.assertIn("status='failed'", execute_sql.call_args_list[1].args[0])

    @patch("backend.app.media_studio.services.storyboard_image_service._EXECUTOR")
    @patch("backend.app.media_studio.services.storyboard_image_service.execute_sql", return_value=1)
    @patch("backend.app.media_studio.services.storyboard_image_service.query_all")
    @patch.object(StoryboardImageService, "_limit", return_value=5)
    def test_dispatches_only_five_of_six_queued_jobs(self, _limit, query_all, _sql, executor):
        query_all.side_effect = [
            [],
            [{"id": f"job-{index}", "payload_json": '{"target_type":"beat_sketch"}'} for index in range(6)],
        ]
        StoryboardImageService.kick()
        self.assertEqual(5, executor.submit.call_count)

    @patch("backend.app.media_studio.services.storyboard_image_service._EXECUTOR")
    @patch("backend.app.media_studio.services.storyboard_image_service.execute_sql", return_value=1)
    @patch("backend.app.media_studio.services.storyboard_image_service.query_all")
    @patch.object(StoryboardImageService, "_limit", return_value=5)
    def test_existing_active_job_reduces_capacity(self, _limit, query_all, _sql, executor):
        query_all.side_effect = [
            [{"id": "running", "payload_json": '{"target_type":"beat_render"}'}],
            [{"id": f"job-{index}", "payload_json": '{"target_type":"beat_sketch"}'} for index in range(6)],
        ]
        StoryboardImageService.kick()
        self.assertEqual(4, executor.submit.call_count)

    @patch("backend.app.media_studio.services.storyboard_image_service._EXECUTOR")
    @patch("backend.app.media_studio.services.storyboard_image_service.execute_sql", return_value=1)
    @patch("backend.app.media_studio.services.storyboard_image_service.query_all")
    @patch.object(StoryboardImageService, "_limit", return_value=5)
    def test_dispatches_triptych_jobs(self, _limit, query_all, _sql, executor):
        query_all.side_effect = [
            [],
            [{"id": "job-t", "payload_json": '{"target_type":"beat_triptych"}'}],
        ]
        StoryboardImageService.kick()
        self.assertEqual(1, executor.submit.call_count)

    @patch("backend.app.skill_packs.binding.resolve_skill_pack_id", return_value="")
    def test_unbound_triptych_prompt_does_not_force_half_narrated(self, _resolve):
        prompt = StoryboardImageService._triptych_prompt("p1", {"action": "她转身关门", "camera": "固定机位"})
        self.assertIn("OUTPUT CANVAS", prompt)
        self.assertNotIn("Generate ONE 16:9 keyframe master image", prompt)

    @patch("backend.app.skill_packs.binding.resolve_skill_pack_id", return_value="half-narrated-live-action-short-drama")
    def test_bound_triptych_prompt_uses_pack_template(self, _resolve):
        prompt = StoryboardImageService._triptych_prompt("p1", {"action": "她转身关门", "camera": "固定机位"})
        self.assertIn("Generate ONE 16:9 keyframe master image", prompt)
        self.assertIn("vertical 9:16", prompt)
        self.assertIn("finished-shot 9:16", prompt)

    @patch("backend.app.skill_packs.binding.resolve_skill_pack_id", return_value="half-narrated-live-action-short-drama")
    def test_bound_triptych_prompt_uses_film_aspect_not_crop_label(self, _resolve):
        prompt = StoryboardImageService._triptych_prompt(
            "p1",
            {"action": "她转身关门", "camera": "固定机位"},
            {"aspect_ratio": "16:9"},
        )
        self.assertIn("Generate ONE 16:9 keyframe master image", prompt)
        self.assertIn("finished-shot 16:9", prompt)
        self.assertIn("horizontal 16:9 composition", prompt)
        self.assertNotIn("vertical 9:16", prompt)
        self.assertNotIn("9:16 裁切", prompt)

    @patch("backend.app.skill_packs.binding.resolve_skill_pack_id", return_value="half-narrated-live-action-short-drama")
    def test_triptych_prompt_left_panel_inherits_previous_landing(self, _resolve):
        prompt = StoryboardImageService._triptych_prompt(
            "p1",
            {
                "action": "开场：仍坐在书桌前。上身前倾伸手接书。",
                "camera": "近景",
                "scene": "大学图书馆",
                "opening_state": "仍坐在同一书桌前",
                "closing_state": "伸手接书时被白光淹没",
                "transition_note": "动作匹配切",
            },
            {"aspect_ratio": "16:9"},
            previous_beat={
                "action": "开场：坐在书桌前翻书。收束：古籍滑向桌沿。",
                "scene": "大学图书馆",
                "closing_state": "仍坐书桌前，古籍滑向桌沿",
                "transition_note": "动作匹配切",
            },
        )
        self.assertIn("LEFT panel MUST inherit", prompt)
        self.assertIn("仍坐书桌前，古籍滑向桌沿", prompt)
        self.assertIn("do not stand if the previous landing was seated", prompt)

        hard = StoryboardImageService._triptych_prompt(
            "p1",
            {
                "action": "走进古代书院",
                "scene": "书院",
                "transition_note": "硬切换场",
            },
            {"aspect_ratio": "16:9"},
            previous_beat={
                "scene": "大学图书馆",
                "closing_state": "仍坐书桌前",
            },
        )
        self.assertNotIn("LEFT panel MUST inherit", hard)


class TransferEpisodesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan_patcher = patch.object(
            LlmService,
            "plan_episode_shots",
            side_effect=RuntimeError("llm unavailable"),
        )
        self.plan_episode_shots = self.plan_patcher.start()
        self.addCleanup(self.plan_patcher.stop)

    def _document_row(self, analysis: dict | None = None, **overrides) -> dict:
        payload = analysis or {
            "episodes": [{
                "episode_num": 1,
                "title": "白雪一惊",
                "summary": "98元粥",
                "shots": [{
                    "shot_num": 1,
                    "title": "98一碗的粥",
                    "characters": ["白雪"],
                    "scene": "餐厅面馆",
                    "action": "白雪看见98元收据",
                    "dialogue": "白雪：“98一碗的粥？”",
                    "camera": "近景",
                    "duration_sec": 12,
                }],
            }],
        }
        row = {
            "id": "doc-1",
            "project_id": "proj-1",
            "input_mode": "paste",
            "raw_text": "",
            "analysis_json": json.dumps(payload, ensure_ascii=False),
        }
        row.update(overrides)
        return row

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_all")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_overwrite_rebuilds_beats_and_deletes_extra_episodes(self, query_one, query_all, execute_sql):
        query_one.return_value = self._document_row()
        query_all.side_effect = [
            [{"id": "ep-old", "episode_num": 1}, {"id": "ep-extra", "episode_num": 8}],
            [{"id": "ast-bai", "kind": "character", "name": "白雪", "image_url": "", "extra_json": "{}"}],
        ]
        result = ProjectDetailService.transfer_episodes_from_document("proj-1", "doc-1", mode="overwrite")
        self.assertEqual("overwrite", result["mode"])
        self.assertEqual(1, result["replaced_episodes"])
        self.assertEqual(0, result["created_episodes"])
        self.assertEqual(1, result["deleted_episodes"])
        self.assertEqual(1, result["transferred_shots"])
        self.plan_episode_shots.assert_not_called()
        update = next(call for call in execute_sql.call_args_list if "data_json" in str(call.args[0]))
        payload = json.loads(update.args[1][3])
        self.assertEqual("白雪：“98一碗的粥？”", payload["beats"][0]["dialogue"])
        self.assertEqual(["白雪"], payload["beats"][0]["characters"])
        self.assertIn("ast-bai", payload["beats"][0]["character_ids"])
        self.assertTrue(any("DELETE FROM ai_project_episodes" in str(call.args[0]) for call in execute_sql.call_args_list))

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_all")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_selected_episode_sync_does_not_replace_or_delete_others(self, query_one, query_all, execute_sql):
        row = self._document_row()
        analysis = json.loads(row["analysis_json"])
        analysis["episodes"].append({"episode_num": 2, "title": "其他集", "shots": []})
        row["analysis_json"] = json.dumps(analysis)
        query_one.return_value = row
        query_all.side_effect = [[{"id": "ep-old", "episode_num": 1}, {"id": "ep-other", "episode_num": 2},
                                 {"id": "ep-extra", "episode_num": 8}], []]
        result = ProjectDetailService.transfer_episodes_from_document("proj-1", "doc-1", episode_num=1)
        self.assertEqual(1, result["replaced_episodes"])
        self.assertEqual(0, result["deleted_episodes"])
        self.assertEqual(1, execute_sql.call_count)
        self.assertEqual("ep-old", execute_sql.call_args.args[1][-1])

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_all")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_identical_sync_preserves_beat_ids(self, query_one, query_all, execute_sql):
        row = self._document_row()
        shots = json.loads(row["analysis_json"])["episodes"][0]["shots"]
        previous = ProjectDetailService._beats_from_document_shots("ep-old", shots, {}, {}, {})
        previous[0]["id"] = "stable-beat"
        query_one.return_value = row
        query_all.side_effect = [[{"id": "ep-old", "episode_num": 1, "data_json": json.dumps({"beats": previous})}], []]
        ProjectDetailService.transfer_episodes_from_document("proj-1", "doc-1", episode_num=1)
        data = json.loads(execute_sql.call_args.args[1][3])
        self.assertEqual("stable-beat", data["beats"][0]["id"])

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_all")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_append_skips_existing_episode_numbers(self, query_one, query_all, execute_sql):
        query_one.return_value = self._document_row()
        query_all.side_effect = [
            [{"id": "ep-old", "episode_num": 1}],
            [],
        ]
        result = ProjectDetailService.transfer_episodes_from_document("proj-1", "doc-1", mode="append")
        self.assertEqual("append", result["mode"])
        self.assertEqual(1, result["skipped_episodes"])
        self.assertEqual(0, result["replaced_episodes"])
        self.assertEqual(0, result["created_episodes"])
        self.assertEqual(0, result["deleted_episodes"])
        self.assertFalse(any("UPDATE ai_project_episodes" in str(call.args[0]) for call in execute_sql.call_args_list))
        self.assertFalse(any("DELETE FROM ai_project_episodes" in str(call.args[0]) for call in execute_sql.call_args_list))
        self.plan_episode_shots.assert_not_called()

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_all")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_overwrite_copies_parser_shots_without_replanning(self, query_one, query_all, execute_sql):
        query_one.return_value = self._document_row()
        query_all.side_effect = [
            [{"id": "ep-old", "episode_num": 1}],
            [],
        ]
        result = ProjectDetailService.transfer_episodes_from_document("proj-1", "doc-1", mode="overwrite")
        self.assertEqual(1, result["transferred_shots"])
        self.plan_episode_shots.assert_not_called()
        self.assertFalse(any("analysis_json" in str(call.args[0]) for call in execute_sql.call_args_list))
        update = next(call for call in execute_sql.call_args_list if "data_json" in str(call.args[0]))
        beats = json.loads(update.args[1][3])["beats"]
        self.assertEqual(1, len(beats))
        self.assertGreaterEqual(int(float(beats[0]["video_duration"])), 5)

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_all")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_skips_planner_when_shots_source_is_llm(self, query_one, query_all, execute_sql):
        analysis = json.loads(self._document_row()["analysis_json"])
        analysis["episodes"][0]["shots_source"] = "llm"
        query_one.return_value = self._document_row(analysis=analysis)
        query_all.side_effect = [[], []]
        result = ProjectDetailService.transfer_episodes_from_document("proj-1", "doc-1", mode="overwrite")
        self.assertEqual(1, result["created_episodes"])
        self.assertEqual(1, result["transferred_shots"])
        self.plan_episode_shots.assert_not_called()

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_all")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_skips_planner_for_ai_pipeline_documents(self, query_one, query_all, execute_sql):
        query_one.return_value = self._document_row(input_mode="ai_pipeline")
        query_all.side_effect = [[], []]
        result = ProjectDetailService.transfer_episodes_from_document("proj-1", "doc-1", mode="overwrite")
        self.assertEqual(1, result["transferred_shots"])
        self.plan_episode_shots.assert_not_called()

    def test_rejects_unknown_sync_mode(self):
        with self.assertRaises(ValueError):
            ProjectDetailService.transfer_episodes_from_document("proj-1", "doc-1", mode="merge")


LONG_DIALOGUE_SCRIPT = """# 第1集 超长对白
**剧情：** 电梯里一次说完。

### 镜头1｜电梯
- 人物：沙丽丽、吴耐
- 场景：单元楼电梯
- 动作：轿厢内已站定，开口后再内心，最后推近。
- 台词：沙丽丽：“大爷，我什么都可以做。” 吴耐（内心）：“浓妆艳抹。” 吴耐：“不用想也知道，做的是什么。”
"""


class CreateDocumentShotPlanTests(unittest.TestCase):
    def setUp(self):
        rename = patch(
            "backend.app.media_studio.services.project_detail_service.maybe_rename_unnamed_project",
            return_value=None,
        )
        self.rename_unnamed = rename.start()
        self.addCleanup(rename.stop)

    @patch("backend.app.media_studio.services.shot_plan_job_service.ShotPlanJobService.enqueue")
    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_create_document_awaits_aspect_and_keeps_parser_shots(self, execute_sql, enqueue):
        result = ProjectDetailService.create_document("proj-1", "花甲", LONG_DIALOGUE_SCRIPT, input_mode="paste")
        episode = result["analysis"]["episodes"][0]
        self.assertEqual("awaiting_aspect", result["status"])
        self.assertIsNone(result["shot_plan_job_id"])
        self.assertTrue(result["needs_shot_plan"])
        self.assertIn("suggested", result["aspect_hint"])
        self.assertEqual(1, episode["episode_num"])
        self.assertNotEqual("llm", episode.get("shots_source"))
        self.assertEqual(1, episode["shots_count"])
        self.assertIn("# 第1集", episode["body"])
        enqueue.assert_not_called()
        insert_params = execute_sql.call_args_list[0].args[1]
        self.assertEqual("awaiting_aspect", insert_params[5])

    @patch("backend.app.media_studio.services.shot_plan_job_service.ShotPlanJobService.enqueue")
    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_create_document_scans_landscape_hint(self, execute_sql, enqueue):
        script = LONG_DIALOGUE_SCRIPT.replace("电梯里一次说完。", "横屏 16:9 拍摄。")
        result = ProjectDetailService.create_document("proj-1", "横屏稿", script, input_mode="paste")
        self.assertEqual("awaiting_aspect", result["status"])
        self.assertEqual("16:9", result["aspect_hint"]["suggested"])
        self.assertIn("横屏", result["aspect_hint"]["hits"])
        enqueue.assert_not_called()

    @patch("backend.app.media_studio.services.shot_plan_job_service.ShotPlanJobService.enqueue")
    def test_enqueue_document_shot_plan_delegates_to_job_service(self, enqueue):
        enqueue.return_value = {"job_id": "job-plan-2", "document_id": "doc-1", "status": "queued"}
        result = ProjectDetailService.enqueue_document_shot_plan("proj-1", "doc-1")
        self.assertEqual("job-plan-2", result["job_id"])
        enqueue.assert_called_once_with("proj-1", "doc-1")

    @patch("backend.app.media_studio.services.project_detail_service.persist_workshop_aspect_ratio")
    @patch("backend.app.media_studio.services.shot_plan_job_service.ShotPlanJobService.enqueue")
    def test_enqueue_document_shot_plan_persists_confirmed_aspect(self, enqueue, persist):
        enqueue.return_value = {"job_id": "job-plan-3", "document_id": "doc-1", "status": "queued"}
        persist.return_value = "16:9"
        result = ProjectDetailService.enqueue_document_shot_plan("proj-1", "doc-1", aspect_ratio="16:9")
        self.assertEqual("job-plan-3", result["job_id"])
        persist.assert_called_once_with("proj-1", "16:9")
        enqueue.assert_called_once_with("proj-1", "doc-1", aspect_ratio="16:9")

    @patch("backend.app.media_studio.services.shot_plan_job_service.ShotPlanJobService.enqueue")
    def test_enqueue_document_shot_plan_passes_force(self, enqueue):
        enqueue.return_value = {"job_id": "job-plan-4", "document_id": "doc-1", "status": "queued"}
        result = ProjectDetailService.enqueue_document_shot_plan("proj-1", "doc-1", force=True)
        self.assertEqual("job-plan-4", result["job_id"])
        enqueue.assert_called_once_with("proj-1", "doc-1", force=True)

    @patch("backend.app.media_studio.services.project_detail_service.persist_workshop_aspect_ratio")
    @patch("backend.app.media_studio.services.shot_plan_job_service.ShotPlanJobService.enqueue")
    def test_enqueue_document_shot_plan_force_keeps_aspect(self, enqueue, persist):
        enqueue.return_value = {"job_id": "job-plan-5", "document_id": "doc-1", "status": "queued"}
        persist.return_value = "16:9"
        result = ProjectDetailService.enqueue_document_shot_plan(
            "proj-1",
            "doc-1",
            aspect_ratio="16:9",
            force=True,
        )
        self.assertEqual("job-plan-5", result["job_id"])
        persist.assert_called_once_with("proj-1", "16:9")
        enqueue.assert_called_once_with("proj-1", "doc-1", aspect_ratio="16:9", force=True)

    @patch("backend.app.media_studio.services.shot_plan_job_service.ShotPlanJobService.enqueue")
    def test_enqueue_document_shot_plan_targets_episode(self, enqueue):
        enqueue.return_value = {"job_id": "job-plan-6", "document_id": "doc-1", "status": "queued"}
        result = ProjectDetailService.enqueue_document_shot_plan("proj-1", "doc-1", force=True, episode_num=3)
        self.assertEqual("job-plan-6", result["job_id"])
        enqueue.assert_called_once_with("proj-1", "doc-1", force=True, episode_num=3)

    @patch("backend.app.media_studio.services.shot_plan_job_service.ShotPlanJobService.enqueue")
    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_create_document_skips_planning_for_ai_pipeline(self, execute_sql, enqueue):
        result = ProjectDetailService.create_document(
            "proj-1",
            "AI 剧本",
            LONG_DIALOGUE_SCRIPT,
            input_mode="ai_pipeline",
        )
        episode = result["analysis"]["episodes"][0]
        self.assertEqual("ready", result["status"])
        self.assertIsNone(result["shot_plan_job_id"])
        self.assertEqual(1, episode["shots_count"])
        self.assertNotEqual("llm", episode.get("shots_source"))
        enqueue.assert_not_called()
        insert_params = execute_sql.call_args_list[0].args[1]
        self.assertEqual("ready", insert_params[5])

    @patch("backend.app.media_studio.services.shot_plan_job_service.ShotPlanJobService.enqueue")
    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_create_document_empty_script_does_not_enqueue(self, execute_sql, enqueue):
        result = ProjectDetailService.create_document("proj-1", "空", "")
        self.assertEqual("ready", result["status"])
        self.assertIsNone(result["shot_plan_job_id"])
        enqueue.assert_not_called()

    @patch("backend.app.media_studio.services.shot_plan_job_service.ShotPlanJobService.enqueue")
    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_create_document_adopts_script_title_for_unnamed_project(self, execute_sql, enqueue):
        script = "# 寒门硕士穿越古代逆袭记\n\n# 第1集 开场\n**剧情：** 开篇。\n"
        self.rename_unnamed.return_value = "寒门硕士穿越古代逆袭记"
        result = ProjectDetailService.create_document("proj-1", "剧本文档", script, input_mode="paste")
        self.assertEqual("寒门硕士穿越古代逆袭记", result["filename"])
        self.assertEqual("寒门硕士穿越古代逆袭记", result["project_name"])
        self.rename_unnamed.assert_called_once_with("proj-1", "寒门硕士穿越古代逆袭记")
        enqueue.assert_not_called()
        execute_sql.assert_called()

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_persist_shot_plan_episode_writes_shots_and_logs(self, query_one, execute_sql):
        analysis = {
            "summary": "共解析出 2 集剧情、2 个分镜头",
            "logs": ["解析完毕"],
            "episodes": [
                {"episode_num": 1, "shots": [{"title": "旧1"}], "shots_count": 1},
                {"episode_num": 2, "shots": [{"title": "旧2"}], "shots_count": 1},
            ],
        }
        query_one.return_value = {"id": "doc-1", "analysis_json": json.dumps(analysis, ensure_ascii=False)}
        updated = {
            "episode_num": 1,
            "shots": [{"title": "开口"}, {"title": "近景"}],
            "shots_count": 2,
            "shots_source": "llm",
        }
        result = ProjectDetailService.persist_shot_plan_episode(
            "proj-1",
            "doc-1",
            episode_num=1,
            episode_index=0,
            updated_episode=updated,
            log_line="第1集已按动作和对白规划为 2 条出片镜头",
        )
        self.assertEqual("llm", result["episodes"][0]["shots_source"])
        self.assertEqual(2, result["episodes"][0]["shots_count"])
        self.assertEqual("旧2", result["episodes"][1]["shots"][0]["title"])
        self.assertIn("第1集已按动作和对白规划为 2 条出片镜头", result["logs"])
        self.assertIn("3 个分镜头", result["summary"])
        execute_sql.assert_called_once()


if __name__ == "__main__":
    unittest.main()
