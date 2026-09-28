"""Persisted review lifecycles; no remote models or production writes."""
import json
from unittest.mock import patch

from backend.tests.test_workshop_direct_lifecycle import DirectLifecycleTests
from backend.app.media_studio.services import workshop_service as service
from backend.app.media_studio.services import workshop_h3_skill as skill
from backend.app.media_studio.services.workshop_ai_review import parse_response
from backend.app.media_studio.services.llm_service import LlmService


class AiReviewTests(DirectLifecycleTests):
    def response(self, revised=False):
        return json.dumps({"decision": "revised" if revised else "unchanged",
            "issues": [{"location": "镜头1", "type": "声音", "certainty": "risk", "evidence": "呼吸声与环境底噪", "reason": "可能遮盖对白", "suggestion": "降低环境底噪"}] if revised else [],
            "final_prompt": self.raw.replace("呼吸声与环境底噪", "轻微呼吸声与低环境底噪") if revised else self.raw,
            "changes": [{"location": "镜头1", "reason": "降低遮盖风险", "before": "环境底噪", "after": "低环境底噪"}] if revised else []}, ensure_ascii=False)

    def run_review_job(self, jid, response):
        with patch.object(LlmService, "author_group", side_effect=[(self.raw, {"requested_model": "writer"}), (response, {"requested_model": "reviewer"})]) as calls:
            service.WorkshopService.run("p", jid)
        self.assertEqual(calls.call_count, 2)
        self.assertEqual(calls.call_args_list[1].kwargs["author"]["model"], "reviewer")
        return self.job(jid)

    def create_review_job(self):
        # The production resolver locks the two independently selected profiles.
        with patch.object(skill, "writing_author", side_effect=[self.author, {**self.author, "model": "reviewer"}]), patch.object(service.WorkshopService.executor, "submit"):
            return service.WorkshopService.create("p", "e", "workshop_prompt", {"expected_revision": 1, "beat_ids": ["b1"], "review_enabled": True})["job_id"]

    def test_reviewed_adoption_is_atomic_and_original_is_preserved(self):
        self.prepare()
        jid = self.create_review_job()
        status, payload = self.run_review_job(jid, self.response(True))
        self.assertEqual(status, "completed")
        group = payload["base_plan"]["groups"][0]
        review = payload["ai_reviews"][group["id"]]
        self.assertTrue(review["eligible"], review)
        self.assertEqual(payload["authoring"]["writing_history"][0]["raw"], self.raw)
        self.assertEqual(self.plan()["shot_prompts"], {})
        service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "version": "reviewed", "expected_revision": 1})
        self.assertEqual(self.plan()["shot_prompts"]["b1"]["h3_prompt"], review["candidates"]["b1"]["h3_prompt"])
        self.assertEqual(self.job(jid)[1]["candidates"], payload["candidates"])
        self.assertEqual(self.plan()["groups"][0]["common_prompt"], review["common_prompt"])

    def test_failed_review_keeps_original_and_retry_calls_only_reviewer(self):
        self._failed_review_keeps_original_and_retry_calls_only_reviewer()

    def test_switch_adopted_versions_preserves_evidence(self):
        self.prepare()
        jid = self.create_review_job()
        _, original = self.run_review_job(jid, self.response(True))
        for revision, version in [(1, "original"), (2, "reviewed"), (3, "original")]:
            service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "version": version, "expected_revision": revision, "switch_version": revision > 1})
            self.assertEqual(self.plan()["shot_prompts"]["b1"]["authoring_version"], version)
        self.assertEqual(self.job(jid)[1]["base_plan"], original["base_plan"])
        self.assertEqual(self.job(jid)[1]["candidates"], original["candidates"])

    def test_switch_rejects_manual_edit_without_overwriting_it(self):
        self.prepare()
        jid = self.create_review_job()
        self.run_review_job(jid, self.response(True))
        service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "version": "original", "expected_revision": 1})
        edited = self.plan()["shot_prompts"]["b1"]["h3_prompt"] + "\n窗外传来风声。"
        service.WorkshopService.update("p", "e", {"expected_revision": 2, "beat_id": "b1", "h3_prompt": edited})
        before = self.plan()
        with self.assertRaises(ValueError):
            service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "version": "reviewed", "switch_version": True, "expected_revision": 3})
        self.assertEqual(self.plan(), before)

    def _failed_review_keeps_original_and_retry_calls_only_reviewer(self):
        self.prepare()
        jid = self.create_review_job()
        status, payload = self.run_review_job(jid, "not json")
        self.assertEqual(status, "completed")
        self.assertEqual(payload["failures"], {})
        gid = payload["base_plan"]["groups"][0]["id"]
        self.assertEqual(payload["ai_reviews"][gid]["status"], "failed")
        with patch.object(service.WorkshopService.executor, "submit"):
            service.WorkshopService.job_action("p", "e", jid, {"action": "review", "expected_revision": 1})
        with patch.object(LlmService, "author_group", return_value=(self.response(), {})) as call:
            service.WorkshopService.run("p", jid)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self.job(jid)[1]["ai_reviews"][gid]["status"], "unchanged")
        service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "expected_revision": 1})
        self.assertEqual(self.plan()["shot_prompts"]["b1"]["h3_prompt"], payload["candidates"]["b1"]["h3_prompt"])

    def test_cancelled_review_late_response_cannot_publish(self):
        self.prepare()
        jid = self.create_review_job()
        def respond(*args, **kwargs):
            if args[0].startswith("---") and "h3-dialogue-review" in args[0]:
                service.WorkshopService.job_action("p", "e", jid, {"action": "cancel"})
                return self.response(True), {}
            return self.raw, {}
        with patch.object(LlmService, "author_group", side_effect=respond):
            service.WorkshopService.run("p", jid)
        status, payload = self.job(jid)
        self.assertEqual(status, "cancelled")
        self.assertTrue(payload["candidates"])
        self.assertNotIn("result", next(iter(payload["ai_reviews"].values())))
        with self.assertRaises(ValueError):
            service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "version": "reviewed", "expected_revision": 1})

    def test_unchanged_must_be_byte_exact(self):
        self.prepare()
        value = json.loads(self.response())
        value["final_prompt"] += "\n"
        with self.assertRaisesRegex(ValueError, "不一致"):
            parse_response(json.dumps(value), self.raw)

    def test_polling_omits_frozen_image_bytes_without_mutating_evidence(self):
        from backend.app.media_studio.services.workshop_ai_review import public_evidence
        value = {"history": [{"author": {"frozen_images": ["data:image/png;base64,AA=="], "image_content_sha256": ["hash"]}}]}
        result = public_evidence(value)
        self.assertNotIn("frozen_images", result["history"][0]["author"])
        self.assertEqual(result["history"][0]["author"]["image_content_sha256"], ["hash"])
        self.assertIn("frozen_images", value["history"][0]["author"])

    def test_image_freezing_records_actual_bytes_and_preserves_order(self):
        import base64
        import hashlib
        from backend.tests.test_llm_image_transport import png_bytes
        red, blue = png_bytes(), png_bytes("blue")
        chosen = {"profile_id": "test", "base_url": "https://example.invalid/v1", "api_key": "test-only", "model": "vision-test", "reasoning_effort": "none", "supports_vision": True}
        with patch.object(skill, "writing_author", return_value=chosen), patch("backend.app.llm_image_transport.download_image", side_effect=[red, blue]) as download, patch("backend.app.media_studio.services.llm_service.OpenAICompatibleClient") as client:
            client.return_value.chat_completion.return_value = "draft"
            _, meta = LlmService.author_group("system", "user", ["https://example.invalid/red.png", "https://example.invalid/blue.png", "https://example.invalid/red.png"], freeze_images=True)
            sent = client.return_value.chat_completion.call_args.args[0][1]["content"][1:]
        self.assertEqual(download.call_count, 2)
        self.assertEqual(meta["image_content_sha256"], [hashlib.sha256(item).hexdigest() for item in (red, blue, red)])
        self.assertEqual([base64.b64decode(part["image_url"]["url"].split(",")[1]) for part in sent], [red, blue, red])

    def test_duplicate_review_uses_frozen_result_without_call(self):
        self.prepare()
        jid = self.create_review_job()
        self.run_review_job(jid, self.response())
        with patch.object(service.WorkshopService.executor, "submit"):
            service.WorkshopService.job_action("p", "e", jid, {"action": "review", "expected_revision": 1})
        with patch.object(LlmService, "author_group") as call:
            service.WorkshopService.run("p", jid)
        call.assert_not_called()

    def test_invalid_review_draft_cannot_be_adopted(self):
        self.prepare()
        jid = self.create_review_job()
        value = json.loads(self.response(True))
        value["final_prompt"] = "invalid complete draft"
        self.run_review_job(jid, json.dumps(value))
        with self.assertRaises(ValueError):
            service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "version": "reviewed", "expected_revision": 1})
        service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "expected_revision": 1})

    def test_needs_user_resolution_retains_original_without_adoption(self):
        self.prepare()
        jid = self.create_review_job()
        value = json.loads(self.response(True))
        value.update(decision="needs_user_resolution", final_prompt=None, changes=[])
        status, payload = self.run_review_job(jid, json.dumps(value))
        self.assertEqual(status, "completed")
        review = next(iter(payload["ai_reviews"].values()))
        self.assertEqual(review["status"], "needs_user_resolution")
        self.assertFalse(review.get("eligible"))
        self.assertTrue(payload["candidates"])

    def test_model_failure_does_not_fail_writer_or_switch_model(self):
        self.prepare()
        jid = self.create_review_job()
        with patch.object(LlmService, "author_group", side_effect=[(self.raw, {}), RuntimeError("provider unavailable")]) as calls:
            service.WorkshopService.run("p", jid)
        status, payload = self.job(jid)
        self.assertEqual(status, "completed")
        self.assertEqual(calls.call_count, 2)
        self.assertTrue(payload["candidates"])
        self.assertEqual(next(iter(payload["ai_reviews"].values()))["status"], "failed")

    def test_changed_source_rejects_independent_review(self):
        self.prepare()
        jid = self.create()
        self.run_job(jid)
        with patch.object(service.WorkshopService, "source", return_value={"text": "changed", "fingerprint": "different"}):
            with self.assertRaisesRegex(ValueError, "SOURCE_CONFLICT"):
                service.WorkshopService.job_action("p", "e", jid, {"action": "review", "expected_revision": 1})

    def test_reviewed_execution_uses_both_adopted_components(self):
        from backend.app.media_studio.services.workshop_contract import execution_shots
        self.prepare()
        jid = self.create_review_job()
        _, payload = self.run_review_job(jid, self.response(True))
        review = next(iter(payload["ai_reviews"].values()))
        service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "version": "reviewed", "expected_revision": 1})
        data = service.WorkshopService.row("p", "e")[1]
        shots, _ = execution_shots(data)
        for shot in shots:
            self.assertEqual(shot["prompt"], review["candidates"][shot["beat_id"]]["h3_prompt"])
            self.assertEqual(shot["global_prompt"], review["common_prompt"])

    def test_cancel_retry_new_run_wins_over_old_late_response(self):
        self.prepare()
        jid = self.create_review_job()
        def respond(*args, **kwargs):
            if "h3-dialogue-review" not in args[0]:
                return self.raw, {}
            service.WorkshopService.job_action("p", "e", jid, {"action": "cancel"})
            with patch.object(service.WorkshopService.executor, "submit"):
                service.WorkshopService.job_action("p", "e", jid, {"action": "review", "expected_revision": 1})
            with patch.object(LlmService, "author_group", return_value=(self.response(), {"request_id": "new-run"})):
                service.WorkshopService.run("p", jid)
            return self.response(True), {"request_id": "old-run"}
        with patch.object(LlmService, "author_group", side_effect=respond):
            service.WorkshopService.run("p", jid)
        status, payload = self.job(jid)
        self.assertEqual(status, "completed")
        review = next(iter(payload["ai_reviews"].values()))
        self.assertEqual(review["status"], "unchanged")
        self.assertEqual(review["author"]["request_id"], "new-run")
