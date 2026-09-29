import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from backend.app.storage import JobStore
from backend.app.models import JobMode, JobStatus
from backend.app.minimax_h3_confirm_workflow import (
    MODE_ID, build_confirmation_shot, confirmation_state, validate_refine_request, execution_report,
)
from backend.app.workflow_registry import normalize_options, workflow_for


def source_state():
    graph = build_confirmation_shot("A person", ["image.png"], {"duration": 2}, 0)
    report = {"protocol": "zly-h3-confirmation@1", "stage": "preview_only",
        "cache_key": graph["12"]["inputs"]["cache_key"], "source_revision": "graph-rev",
        "instance_id": "remote-one", "segment_count": 1, "first_pass_samples": 1,
        "refine_samples": 0, "cached_segments": [0], "reused_segments": []}
    return confirmation_state([{"graph": graph, "report": report}], "http://remote:8188")


class ConfirmationJobsTests(unittest.TestCase):
    def test_refinement_memory_policy_is_bounded_and_explicit(self):
        from comfyui_nodes.zly_h3_confirmation.protocol import refinement_memory_policy
        policy = refinement_memory_policy(16 * 1024**3)
        self.assertTrue(policy["enable_tiling"])
        self.assertTrue(policy["enable_latent_chunking"])
        self.assertEqual(policy["tile_count"], 4)
        self.assertEqual(refinement_memory_policy(24 * 1024**3), {"policy": "author-default@1"})
        self.assertEqual(refinement_memory_policy(0), {"policy": "author-default@1"})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp.name) / "jobs.sqlite")
        self.state = source_state()
        self.options = {**normalize_options(MODE_ID, {}), "h3_confirmation": self.state}
        self.store.create("source", JobMode(MODE_ID), "original prompt", "", None, [],
                          self.options, title="Original")
        self.store.update("source", status=JobStatus.SUCCEEDED,
                          outputs=[{"kind": "video", "path": "original.mp4", "label": "一采原片"}])
        self.request = {"refine_quality": 1.0, "source_revision": self.state["source_revision"], "request_id": "click-one"}

    def tearDown(self):
        self.temp.cleanup()

    def test_continuity_export_boundaries_override_timeline_header(self):
        from backend.app.minimax_h3_confirm_workflow import executed_segment_frames
        report = ("  #1 [0:192] 192f — r2v\n  #2 [192:384] 192f — r2v\n"
                  "Seg #2: continuity guide — 22f from seg #1 (AV latent, +audio); sample=226f → export 204f\n"
                  "Export mode: all — merged 396 frame(s) on images output.")
        history = {"outputs": {"8": {"text": [report]}}}
        self.assertEqual(executed_segment_frames(history, 2), [192, 204])
        history["outputs"]["8"]["text"] = [report.replace("merged 396", "merged 400")]
        with self.assertRaisesRegex(ValueError, "总帧数"):
            executed_segment_frames(history, 2)

    def test_cached_refine_uses_verified_source_boundaries_and_checks_total(self):
        from backend.app.minimax_h3_confirm_workflow import executed_segment_frames
        report = ("  #1 [0:192] 192f — r2v\n  #2 [192:384] 192f — r2v\n"
                  "Export mode: all — merged 396 frame(s) on images output.")
        history = {"outputs": {"8": {"text": [report]}}}
        self.assertEqual(executed_segment_frames(history, 2, reused_frame_counts=[192, 204]), [192, 204])
        for counts in ([192, 192], [396], [True, 395], [0, 396]):
            with self.assertRaisesRegex(ValueError, "缓存分段"):
                executed_segment_frames(history, 2, reused_frame_counts=counts)
        history["outputs"]["8"]["text"] = [report.split("Export mode")[0]]
        with self.assertRaisesRegex(ValueError, "缓存分段"):
            executed_segment_frames(history, 2, reused_frame_counts=[192, 204])

    def test_confirmation_keeps_original_and_zero_seed(self):
        child = self.store.create_confirmation_child("source", self.request, "http://remote:8188")
        state = child["options"]["h3_confirmation"]
        self.assertEqual(state["graph"]["12"]["inputs"]["seed"], 0)
        self.assertEqual(state["graph"]["12"]["inputs"]["stage"], "refine_only")
        self.assertEqual(self.store.get("source")["status"], "succeeded")
        self.assertEqual(self.store.get("source")["outputs"][0]["path"], "original.mp4")
        self.assertEqual(child["source_job_id"], "source")

    def test_concurrent_clicks_create_one_child(self):
        with ThreadPoolExecutor(4) as pool:
            ids = list(pool.map(lambda _: self.store.create_confirmation_child(
                "source", self.request, "http://remote:8188")["id"], range(4)))
        self.assertEqual(len(set(ids)), 1)

    def test_active_child_and_retry_idempotency(self):
        child = self.store.create_confirmation_child("source", self.request, "http://remote:8188")
        another = {**self.request, "request_id": "another", "refine_quality": 2.0}
        self.assertEqual(child["id"], self.store.create_confirmation_child("source", another, "http://remote:8188")["id"])
        self.store.update(child["id"], status=JobStatus.FAILED)
        self.assertEqual(child["id"], self.store.create_confirmation_child("source", self.request, "http://remote:8188")["id"])
        self.assertNotEqual(child["id"], self.store.create_confirmation_child("source", another, "http://remote:8188")["id"])
        self.assertEqual(self.store.get("source")["status"], "succeeded")

    def test_restart_reads_frozen_snapshot(self):
        child = self.store.create_confirmation_child("source", self.request, "http://remote:8188")
        reopened = JobStore(Path(self.temp.name) / "jobs.sqlite")
        self.assertEqual(reopened.get(child["id"])["options"], child["options"])

    def test_conflicts_and_untrusted_request(self):
        for request, url in [({**self.request, "source_revision": "stale"}, "http://remote:8188"),
            (self.request, "http://different:8188"), ({**self.request, "seed": 123}, "http://remote:8188"),
            ({**self.request, "refine_quality": True}, "http://remote:8188")]:
            with self.assertRaises(ValueError):
                self.store.create_confirmation_child("source", request, url)

    def test_reports_cannot_claim_success_without_stage_proof(self):
        graph = self.state["groups"][0]["graph"]
        report = copy.deepcopy(self.state["groups"][0]["report"])
        history = {"outputs": {"12": {"zly_h3_confirmation": [report]}}}
        self.assertEqual(execution_report(graph, history), report)
        report["first_pass_samples"] = 0
        with self.assertRaises(ValueError):
            execution_report(graph, history)

    def test_creation_schema_has_no_auto_refine_controls(self):
        props = workflow_for(MODE_ID).option_schema["properties"]
        self.assertNotIn("refine_enabled", props)
        self.assertNotIn("refine_quality", props)
        self.assertEqual(normalize_options(MODE_ID, {"seed": 0})["seed"], 0)
        self.assertEqual(normalize_options(MODE_ID, {"seed": 37})["seed"], 37)
        from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
        self.assertEqual(EpisodeVideoService.resolve_generation_options({"workflow": MODE_ID, "seed": 0})["seed"], 0)

    def test_director_retry_skips_saved_group_and_never_adopts(self):
        from backend.app.media_studio.services.h3_confirmation_service import run_refinement
        from backend.app.minimax_h3_confirm_workflow import build_confirmation_refine
        original = self.state["groups"][0]
        graph = build_confirmation_refine(original["graph"], original["report"], 1.0, "test")
        report = {**original["report"], "stage": "refine_only", "first_pass_samples": 0,
                  "refine_samples": 1, "cached_segments": [], "reused_segments": [0]}
        groups = [
            {"graph": graph, "output": {"filename": "saved.mp4"}, "report": report,
             "url": "http://remote/saved.mp4", "media_info": {"width": 1280, "height": 720}},
            {"graph": graph, "media_info": {"width": 864, "height": 480}, "url": "preview.mp4"},
        ]
        payload = {"h3_confirmation": {"stage": "refine_only", "groups": groups,
                   "base_url": "http://remote:8188", "source_video_url": "first.mp4"},
                   "auto_adopt": False, "render_scope": "selection", "project_id": "p", "episode_id": "e"}
        service = Mock()
        service._await_comfy.return_value = ({"outputs": {"12": {"zly_h3_confirmation": [report]}}}, {"filename": "second.mp4"})
        service._merge_chunk_videos.return_value = b"merged"
        prefix = "backend.app.media_studio.services."
        with patch(prefix + "h3_confirmation_service.comfy_row", return_value={"base_url": "http://remote:8188"}), \
             patch(prefix + "h3_confirmation_service.query_one", return_value={"payload_json": "{}"}), \
             patch(prefix + "comfy_video_client.ComfyVideoClient") as client, \
             patch(prefix + "production_media.measure", return_value={"width": 1280, "height": 720}), \
             patch(prefix + "qiniu_service.QiniuService") as qiniu, \
             patch(prefix + "episode_video_service._video_write") as save:
            client.return_value.download_output.return_value = b"video"
            client.return_value.view_url.return_value = "http://remote/second.mp4"
            qiniu.get_config.return_value.available = True
            qiniu.store_bytes.return_value = ("key", "http://storage/video.mp4")
            run_refinement(service, "child", payload)
        self.assertEqual(service._await_comfy.call_count, 1)
        self.assertEqual(payload["h3_confirmation"]["state"], "completed")
        service._write_selected_beat_videos.assert_not_called()
        self.assertFalse(payload["auto_adopt"])
        self.assertEqual(len(payload["h3_confirmation"]["groups"]), 2)
        self.assertEqual(groups[1]["media_info"]["width"], 1280)
        self.assertEqual(groups[1]["url"], "http://storage/video.mp4")

    def test_api_auth_csrf_and_owner(self):
        from fastapi.testclient import TestClient
        from backend.app.main import app
        from backend.app.auth import AuthStore, csrf_token
        from backend.app.models import UserRole
        from unittest.mock import AsyncMock
        auth = AuthStore(Path(self.temp.name) / "auth.sqlite")
        owner = auth.create_user("owner", "Owner", "test-password-123", UserRole.EMPLOYEE, must_change_password=False)
        stranger = auth.create_user("stranger", "Stranger", "test-password-123", UserRole.EMPLOYEE, must_change_password=False)
        token, _ = auth.create_session(owner["id"])
        other, _ = auth.create_session(stranger["id"])
        self.store.create("owned", JobMode(MODE_ID), "prompt", "", None, [], self.options, owner_user_id=owner["id"])
        self.store.update("owned", status=JobStatus.SUCCEEDED)
        prior = {k: getattr(app.state, k, None) for k in ("auth_store", "store", "worker")}
        try:
            app.state.auth_store, app.state.store = auth, self.store
            app.state.worker = Mock(comfy=Mock(comfy_url="http://remote:8188"), enqueue=AsyncMock())
            client = TestClient(app)
            path = "/api/jobs/owned/refine"
            self.assertEqual(client.post(path, json=self.request).status_code, 401)
            client.cookies.set("zly_ai_video_studio_session", other)
            self.assertIn(client.post(path, json=self.request, headers={"X-CSRF-Token": csrf_token(other)}).status_code, (403, 404))
            client.cookies.set("zly_ai_video_studio_session", token)
            self.assertEqual(client.post(path, json=self.request).status_code, 403)
            response = client.post(path, json=self.request, headers={"X-CSRF-Token": csrf_token(token)})
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(client.get(path).status_code, 200)
            stale = client.post(path, json={**self.request, "source_revision": "stale"}, headers={"X-CSRF-Token": csrf_token(token)})
            self.assertEqual(stale.status_code, 409)
        finally:
            for key, value in prior.items():
                setattr(app.state, key, value)

    def test_output_delivery_failure_recovers_without_gpu_resubmit(self):
        from backend.app.h3_confirmation_jobs import run_creation_confirmation
        graph = self.state["groups"][0]["graph"]
        report = self.state["groups"][0]["report"]
        history = {"outputs": {"12": {"zly_h3_confirmation": [report]},
                               "7": {"images": [{"filename": "first.mp4", "subfolder": "", "type": "output"}]}}}
        state = {**self.state, "graph": graph}
        options = {**self.options, "h3_confirmation": state}
        self.store.set_confirmation_options("source", options)
        comfy = Mock(comfy_url="http://remote:8188")
        comfy.run_workflow.return_value = history
        comfy.download.side_effect = RuntimeError("storage unavailable")
        with patch("backend.app.h3_confirmation_jobs.validate_refine_dependencies"):
            with self.assertRaisesRegex(RuntimeError, "storage unavailable"):
                run_creation_confirmation(self.store, comfy, self.store.get("source"), Mock(), Mock(), lambda: False)
            self.assertEqual(comfy.run_workflow.call_count, 1)
            comfy.download.side_effect = None
            comfy.output_payload.return_value = {"path": "first.mp4", "kind": "video", "label": "一采原片"}
            result = run_creation_confirmation(self.store, comfy, self.store.get("source"), Mock(), Mock(), lambda: False)
            self.assertEqual(comfy.run_workflow.call_count, 1)
            self.assertEqual(result[0]["path"], "first.mp4")

    def test_cancel_does_not_interrupt_another_users_prompt(self):
        from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient
        client = ComfyVideoClient("http://remote:8188")
        client.session = Mock()
        client.session.get.return_value.json.return_value = {"queue_running": [[0, "someone-else"]],
                                                            "queue_pending": [[1, "our-prompt"]]}
        with self.assertRaisesRegex(RuntimeError, "H3_CONFIRMATION_CANCELLED"):
            client.wait_for_result("our-prompt", is_cancelled=lambda: True)
        client.session.post.assert_called_once_with("http://remote:8188/queue",
            json={"delete": ["our-prompt"]}, timeout=30)

    def test_director_checkpoint_recovery_never_resubmits(self):
        from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
        prior = copy.deepcopy(self.state["groups"][0])
        prior.update(output={"filename": "first.mp4"}, media_info={"width": 832, "height": 480}, frame_counts=[48])
        payload = {"confirmation_checkpoints": {"1": prior}}
        client = Mock(base_url="http://remote:8188")
        with patch("backend.app.media_studio.provider_bridge.comfy_row", return_value={"base_url":"http://remote:8188"}), \
             patch.object(EpisodeVideoService, "_set_state"):
            history, output = EpisodeVideoService._await_comfy("job", payload, client, prior["graph"], submission_index=1)
        client.submit_and_wait.assert_not_called()
        self.assertEqual(output["filename"], "first.mp4")
        self.assertEqual(payload["h3_confirmation"]["state"], "awaiting_confirmation")

    def test_incomplete_checkpoint_revalidates_existing_prompt_without_submission(self):
        from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
        prior = copy.deepcopy(self.state["groups"][0])
        output = {"filename": "first.mp4"}
        prior.update(output=output, submitted={"prompt_id": "existing", "client_id": "client"})
        history = {"status": {"status_str": "success"}, "outputs": {
            "12": {"zly_h3_confirmation": [prior["report"]]},
            "7": {"images": [output]},
            "8": {"text": ["  #1 [0:48] 48f — r2v\nExport mode: all — merged 48 frame(s)"]}}}
        client = Mock(base_url="http://remote:8188")
        client.session.get.return_value.json.return_value = {"existing": history}
        client.wait_for_result.return_value = (history, output)
        client._find_video.return_value = output
        payload = {"confirmation_checkpoints": {"1": prior}}
        with patch("backend.app.media_studio.provider_bridge.comfy_row", return_value={"base_url":"http://remote:8188"}), \
             patch("backend.app.media_studio.services.production_media.measure", return_value={"frames":48}), \
             patch.object(EpisodeVideoService, "_set_state"):
            EpisodeVideoService._await_comfy("job", payload, client, prior["graph"], submission_index=1)
        client.submit_and_wait.assert_not_called()
        client.wait_for_result.assert_called_once()
        self.assertEqual(prior["frame_counts"], [48])

    def test_real_report_padding_and_media_ranges(self):
        from backend.app.minimax_h3_confirm_workflow import executed_segment_frames
        history = {"outputs": {"8": {"text": ["  #1 [0:56] 56f — r2v\n  #2 [56:112] 56f — r2v"]}}}
        self.assertEqual(executed_segment_frames(history, 2), [56, 56])
        with self.assertRaises(ValueError):
            executed_segment_frames(history, 3)
        from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
        import json
        graph = copy.deepcopy(self.state["groups"][0]["graph"])
        graph["12"]["inputs"]["timeline_data"] = json.dumps({"segments": [{"shotId":"s1"}, {"shotId":"s2"}]})
        payload = {"confirmation_checkpoints": {"1": {"graph":graph, "frame_counts":[56,56]}}}
        with patch("backend.app.media_studio.services.production_media.measure", return_value={}) as measure, \
             patch("backend.app.media_studio.services.production_service.ProductionService.record_output"):
            EpisodeVideoService._record_production_output(payload, "job",
                [{"beat_id":"s1","frame_count":53},{"beat_id":"s2","frame_count":53}], {}, Mock(), url="video",content=b"video")
        self.assertEqual([u["frame_count"] for u in measure.call_args.args[1]], [56,56])


if __name__ == "__main__":
    unittest.main()
