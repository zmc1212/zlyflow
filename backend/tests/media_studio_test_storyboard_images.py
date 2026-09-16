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


if __name__ == "__main__":
    unittest.main()
