import json
import unittest
from unittest.mock import patch

from backend.app.media_studio.services.storyboard_image_service import StoryboardImageService

MODULE = "backend.app.media_studio.services.storyboard_image_service"
PAYLOAD = {"project_id": "p", "episode_id": "ep", "beat_id": "b", "target_type": "beat_triptych", "remote_task_id": "paid-upstream-task"}


class StoryboardImageResumeTests(unittest.TestCase):
    @patch(MODULE + ".StoryboardImageService.retry", return_value={"job_id": "job", "resumed": True})
    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_task_center_routes_triptych_retry_to_the_actual_executor(self, query, execute, retry):
        from backend.app.media_studio.services.project_detail_service import ProjectDetailService

        query.return_value = {"id": "job", "job_type": "image_generation", "payload_json": json.dumps(PAYLOAD)}
        self.assertEqual({"job_id": "job", "resumed": True}, ProjectDetailService.retry_job("p", "job"))
        retry.assert_called_once_with("p", "job")
        execute.assert_not_called()

    @patch(MODULE + ".StoryboardImageService.enqueue")
    @patch(MODULE + ".StoryboardImageService.kick")
    @patch(MODULE + ".execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.ProjectDetailService._update_episode_beat_atomic")
    @patch(MODULE + ".query_one")
    def test_failed_paid_job_resumes_same_job_without_new_generation(self, query, update, execute, kick, enqueue):
        query.return_value = {"status": "failed", "payload_json": json.dumps(PAYLOAD)}
        result = StoryboardImageService.retry("p", "job")
        self.assertEqual({"job_id": "job", "beat_id": "b", "status": "queued", "resumed": True}, result)
        enqueue.assert_not_called()
        self.assertEqual("job", update.call_args.kwargs["expected_job_id"])
        kick.assert_called_once()

    @patch(MODULE + ".StoryboardImageService.kick")
    @patch(MODULE + ".StoryboardImageService._complete")
    @patch(MODULE + ".grs_row")
    @patch(MODULE + ".query_one")
    def test_cached_panels_are_committed_without_contacting_provider(self, query, provider, complete, kick):
        payload = {**PAYLOAD, "api_url": "sheet.png", "triptych_panels": {"first": "first.png"}}
        query.return_value = {"payload_json": json.dumps(payload)}
        StoryboardImageService._run("job")
        provider.assert_not_called()
        complete.assert_called_once_with("job", payload, "sheet.png")

    @patch(MODULE + ".StoryboardImageService.kick")
    @patch(MODULE + ".execute_sql")
    @patch(MODULE + ".StoryboardImageService._complete", side_effect=RuntimeError("commit failed"))
    @patch(MODULE + ".query_one")
    def test_failed_commit_keeps_upstream_and_stored_outputs_for_recovery(self, query, complete, execute, kick):
        payload = {**PAYLOAD, "api_url": "sheet.png", "triptych_panels": {"first": "first.png"}}
        query.return_value = {"payload_json": json.dumps(payload)}
        StoryboardImageService._run("job")
        self.assertEqual(payload, json.loads(execute.call_args.args[1][1]))
