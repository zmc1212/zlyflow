from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import unittest
from unittest.mock import patch

from backend.app.media_studio.services.episode_image_prompts import beat_sketch_prompt
from backend.app.media_studio.services.storyboard_image_service import StoryboardImageService, _ACTIVE
from backend.app.media_studio.services.project_detail_service import resolve_shot_scene


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
