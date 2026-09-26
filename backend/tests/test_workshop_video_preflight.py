import unittest
from unittest.mock import patch

from backend.app.media_studio.services.episode_video_service import EpisodeVideoService


class WorkshopVideoPreflightTests(unittest.TestCase):
    def detail(self):
        return {"prompt_authoring": {"director_plan": {
            "schema_version": 7, "revision": 1,
            "workflow_id": "minimax-h3-director-accel-r2v",
            "groups": [{"beat_ids": [str(i)]} for i in range(14)],
        }}}

    def test_identical_blockers_report_count_once(self):
        with patch("backend.app.media_studio.services.episode_video_service.ProjectDetailService.get_episode_detail", return_value=self.detail()), \
             patch("backend.app.media_studio.services.production_state.summary", return_value={"adopted": {}}), \
             patch.object(EpisodeVideoService, "create_job", side_effect=ValueError("缺少参考图")):
            with self.assertRaises(ValueError) as raised:
                EpisodeVideoService.generate_episode_videos("p", "e", {"expected_revision": 1})
            self.assertEqual(str(raised.exception), "没有可提交的镜头组：14 组：缺少参考图")

    def test_partial_success_keeps_structured_blockers_and_successful_job(self):
        with patch("backend.app.media_studio.services.episode_video_service.ProjectDetailService.get_episode_detail", return_value=self.detail()), \
             patch("backend.app.media_studio.services.production_state.summary", return_value={"adopted": {}}), \
             patch.object(EpisodeVideoService, "create_job", side_effect=[{"job_id": "job-ok"}] + [ValueError("缺提示词")] * 13):
            result = EpisodeVideoService.generate_episode_videos("p", "e", {"expected_revision": 1})
            self.assertEqual(result["job_ids"], ["job-ok"])
            self.assertEqual(len(result["blocked"]), 13)
            self.assertEqual(result["blocked"][0]["beat_ids"], ["1"])


if __name__ == "__main__":
    unittest.main()
