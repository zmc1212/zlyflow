"""Exercise the direct contract through persisted jobs without external services."""
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from backend.tests import test_workshop_v7 as fixtures
from backend.tests.test_workshop_h3_skill import body, complete_draft
from backend.app.media_studio.services import workshop_service as service
from backend.app.media_studio.services import workshop_contract as contract
from backend.app.media_studio.services import workshop_h3_skill as skill
from backend.app.media_studio.services.llm_service import LlmService
from backend.app.media_studio.services.workshop_direct_input import VERSION


class DirectLifecycleTests(unittest.TestCase):
    setUp = fixtures.TransactionTests.setUp
    tearDown = fixtures.TransactionTests.tearDown

    def prepare(self):
        self.db.execute("ALTER TABLE ai_project_jobs ADD COLUMN title TEXT")
        self.db.execute("ALTER TABLE ai_project_jobs ADD COLUMN progress INTEGER")
        data = fixtures.fixture(2)
        row = service.WorkshopService.row("p", "e")[0]
        plan = contract.plan_of(data)
        plan["groups"][0]["timecode_mode"] = "cumulative"
        plan["source_fingerprint"] = service.WorkshopService.source("p", row, data)["fingerprint"]
        plan["shot_prompts"] = {}
        self.db.execute("UPDATE ai_project_episodes SET data_json=?", (json.dumps(data),))
        self.db.commit()
        self.author = {"profile_id": "test", "base_url": "https://example.invalid",
                       "model": "test", "reasoning_effort": "none", "supports_vision": True}
        self.raw = complete_draft([body(), body(offset=8)])

    def create(self, **fields):
        request = {"expected_revision": self.plan()["revision"], "beat_ids": ["b1"], **fields}
        with patch.object(skill, "writing_author", return_value=self.author), \
                patch.object(service.WorkshopService.executor, "submit"):
            return service.WorkshopService.create("p", "e", "workshop_prompt", request)["job_id"]

    def plan(self):
        return contract.plan_of(service.WorkshopService.row("p", "e")[1])

    def job(self, jid):
        row = self.db.execute("SELECT status,payload_json FROM ai_project_jobs WHERE id=?", (jid,)).fetchone()
        return row["status"], json.loads(row["payload_json"])

    def run_job(self, jid, raw=None):
        with patch.object(LlmService, "author_group", return_value=(raw or self.raw, {"ok": True})) as author:
            service.WorkshopService.run("p", jid)
        self.assertEqual(author.call_count, 1)
        return self.job(jid)

    def test_create_generate_apply_edit_and_execution_preserve_body(self):
        self.prepare()
        original = self.plan()
        jid = self.create()
        _, queued = self.job(jid)
        self.assertEqual(queued["request"]["beat_ids"], ["b1", "b2"])
        frozen = deepcopy(queued["authoring"]["contracts"])
        self.assertTrue(all(s["version"] == VERSION for s in frozen.values()))
        status, result = self.run_job(jid)
        self.assertEqual(status, "completed", result.get("failures"))
        self.assertEqual(self.plan(), original)
        self.assertEqual(result["authoring"]["contracts"], frozen)
        service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "expected_revision": 1})
        adopted = self.plan()
        for bid, record in result["candidates"].items():
            self.assertEqual(adopted["shot_prompts"][bid]["h3_prompt"], record["h3_prompt"])
            self.assertEqual(adopted["shot_prompts"][bid]["contract_version"], VERSION)
        edited = adopted["shot_prompts"]["b1"]["h3_prompt"] + "\n窗外传来风声。"
        service.WorkshopService.update("p", "e", {"expected_revision": 2, "beat_id": "b1", "h3_prompt": edited})
        self.assertEqual(self.plan()["shot_prompts"]["b1"]["h3_prompt"], edited)
        contract.execution_shots(service.WorkshopService.row("p", "e")[1])
        self.assertEqual(self.job(jid)[1]["authoring"]["contracts"], frozen)

    def test_failed_draft_cancel_retry_keeps_frozen_input(self):
        self.prepare()
        original = self.plan()
        jid = self.create()
        frozen = deepcopy(self.job(jid)[1]["authoring"]["contracts"])
        status, failed = self.run_job(jid, "无法解析的原稿")
        self.assertEqual(status, "failed")
        self.assertIn("无法解析的原稿", json.dumps(failed, ensure_ascii=False))
        with patch.object(service.WorkshopService.executor, "submit"):
            service.WorkshopService.job_action("p", "e", jid, {"action": "retry"})
        service.WorkshopService.job_action("p", "e", jid, {"action": "cancel"})
        self.assertEqual(self.job(jid)[0], "cancelled")
        service.WorkshopService.run("p", jid)
        self.assertEqual(self.job(jid)[0], "cancelled")
        with patch.object(service.WorkshopService.executor, "submit"):
            service.WorkshopService.job_action("p", "e", jid, {"action": "retry"})
        status, retried = self.run_job(jid)
        self.assertEqual(status, "completed", retried.get("failures"))
        self.assertEqual(retried["authoring"]["contracts"], frozen)
        self.assertIn("无法解析的原稿", json.dumps(retried, ensure_ascii=False))
        self.assertEqual(self.plan(), original)

    def test_single_shot_revision_preserves_neighbor_and_shared_prompt(self):
        self.prepare()
        jid = self.create()
        self.run_job(jid)
        service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "expected_revision": 1})
        before = self.plan()
        revision = self.create(prompt_scope="shot_revision", revision_note="第一镜增加窗外风声")
        raw = self.raw.replace("呼吸声与环境底噪", "呼吸声与环境底噪，窗外风声", 1)
        status, result = self.run_job(revision, raw)
        self.assertEqual(status, "completed", result.get("failures"))
        self.assertEqual(set(result["candidates"]), {"b1"})
        service.WorkshopService.job_action("p", "e", revision, {"action": "apply", "expected_revision": 2})
        after = self.plan()
        self.assertEqual(after["shot_prompts"]["b2"], before["shot_prompts"]["b2"])
        self.assertEqual(after["groups"][0]["common_prompt"], before["groups"][0]["common_prompt"])
        self.assertIn("窗外风声", after["shot_prompts"]["b1"]["h3_prompt"])

    def test_cancel_during_author_response_cannot_publish_candidates(self):
        self.prepare()
        original = self.plan()
        jid = self.create()
        def respond(*args, **kwargs):
            service.WorkshopService.job_action("p", "e", jid, {"action": "cancel"})
            return self.raw, {"ok": True}
        with patch.object(LlmService, "author_group", side_effect=respond):
            service.WorkshopService.run("p", jid)
        status, cancelled = self.job(jid)
        self.assertEqual(status, "cancelled")
        self.assertEqual(cancelled["candidates"], {})
        self.assertEqual(self.plan(), original)
        with self.assertRaisesRegex(ValueError, "任务尚未完成"):
            service.WorkshopService.job_action("p", "e", jid, {"action": "apply", "expected_revision": 1})

    def test_regenerate_creates_new_contract_without_mutating_old_job(self):
        self.prepare()
        jid = self.create()
        self.run_job(jid, "无法解析的原稿")
        old = self.job(jid)
        payload = old[1]
        for snapshot in payload["authoring"]["contracts"].values():
            snapshot["version"] = "h3-skill-direct-v1"
        self.db.execute("UPDATE ai_project_jobs SET payload_json=? WHERE id=?", (json.dumps(payload), jid))
        self.db.commit()
        old = self.job(jid)
        before = self.plan()
        with patch.object(skill, "writing_author", return_value=self.author), patch.object(service.WorkshopService.executor, "submit") as submit:
            view = service.WorkshopService.job_action("p", "e", jid, {"action": "regenerate", "expected_revision": 1})
            # Duplicate clicks while queued must not create another billable task.
            service.WorkshopService.job_action("p", "e", jid, {"action": "regenerate", "expected_revision": 1})
        self.assertEqual(submit.call_count, 1)
        new = next(j for j in view["jobs"] if j["id"] != jid)
        self.assertEqual(new["payload"]["regenerated_from_job_id"], jid)
        self.assertTrue(all(s["version"] == VERSION for s in new["payload"]["authoring"]["contracts"].values()))
        self.assertEqual(new["payload"]["prompt_scope"], "group")
        self.assertEqual(new["payload"]["authoring"]["writing_history"], [])
        self.assertEqual(self.job(jid), old)
        self.assertEqual(self.plan(), before)
        with self.assertRaisesRegex(ValueError, "VERSION_CONFLICT"):
            service.WorkshopService.job_action("p", "e", jid, {"action": "regenerate", "expected_revision": 0})
        with self.assertRaisesRegex(ValueError, "不属于"):
            service.WorkshopService.job_action("p", "other", jid, {"action": "regenerate", "expected_revision": 1})
        with self.assertRaisesRegex(ValueError, "已结束"):
            service.WorkshopService.job_action("p", "e", new["id"], {"action": "regenerate", "expected_revision": 1})
