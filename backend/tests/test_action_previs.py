"""Contract and state transitions for reviewed Blender action previews."""

from __future__ import annotations

import copy
import json
import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.app.media_studio.services.action_previs_schema import validate_plan
from backend.app.media_studio.services.action_previs_service import ActionPrevisService


def sample_plan():
    return {
        "version": 1, "frame_count": 96,
        "actors": [
            {"id": "A", "label": "男主", "start": [-0.7, 0, 0], "facing_deg": 0},
            {"id": "B", "label": "女主", "start": [0.7, 0, 0], "facing_deg": 180},
        ],
        "beats": [
            {"start": 0, "end": 48, "description": "试探步法与格挡", "actions": [{"actor": "A", "type": "jab"}, {"actor": "B", "type": "block"}],
             "contact": {"frame": 31, "actor": "A", "target_actor": "B", "bone": "hand.L", "target_bone": "forearm.R"}},
            {"start": 48, "end": 96, "description": "闪避后低扫", "actions": [{"actor": "A", "type": "dodge"}, {"actor": "B", "type": "low_kick"}], "contact": None},
        ],
        "shots": [
            {"start": 0, "end": 48, "size": "medium", "angle": "over_shoulder", "move": "follow", "subject": "both", "lens_mm": 50},
            {"start": 48, "end": 96, "size": "close", "angle": "side", "move": "dolly_in", "subject": "both", "lens_mm": 70},
        ],
    }


class PlanContractTests(unittest.TestCase):
    def test_valid_plan_normalizes_ids_and_fps(self):
        plan = validate_plan(sample_plan(), expected_frames=96)
        self.assertEqual(plan["fps"], 24)
        self.assertEqual(plan["beats"][0]["id"], "b1")
        self.assertEqual(plan["shots"][1]["id"], "s2")

    def test_timeline_gaps_and_contact_outside_beat_are_rejected(self):
        plan = sample_plan()
        plan["beats"][1]["start"] = 49
        with self.assertRaisesRegex(ValueError, "连续"):
            validate_plan(plan, expected_frames=96)
        plan = sample_plan()
        plan["beats"][0]["contact"]["frame"] = 49
        with self.assertRaisesRegex(ValueError, "接触帧"):
            validate_plan(plan, expected_frames=96)

    def test_arbitrary_code_and_extra_fields_are_not_forwarded(self):
        plan = sample_plan()
        plan["python"] = "import os; os.system('bad')"
        plan["beats"][0]["actions"][0]["code"] = "arbitrary code"
        cleaned = validate_plan(plan)
        self.assertNotIn("python", cleaned)
        self.assertNotIn("code", cleaned["beats"][0]["actions"][0])

    def test_remote_smoke_plan_matches_backend_contract(self):
        sample = Path(__file__).resolve().parents[2] / "scripts" / "action_previs_worker" / "smoke_plan.json"
        plan = validate_plan(json.loads(sample.read_text(encoding="utf-8")))
        self.assertEqual(len(plan["actors"]), 2)
        self.assertEqual(len(plan["shots"]), 3)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.row = {"id": "job-1", "project_id": "p", "job_type": "action_previs", "status": "awaiting_review", "progress": 35,
                    "result_url": None, "payload_json": json.dumps({"frame_count": 96, "plan": validate_plan(sample_plan()), "plan_revision": 1,
                                                              "approved_revision": None, "artifacts": {}}, ensure_ascii=False)}

    def fake_replace(self, row, payload, *, status=None, progress=None, error=None, result_url=None):
        if row["payload_json"] != self.row["payload_json"] or row["status"] != self.row["status"]:
            return False
        self.row.update(payload_json=json.dumps(payload, ensure_ascii=False), status=status or row["status"],
                        progress=row["progress"] if progress is None else progress, error_message=error,
                        result_url=result_url if result_url is not None else row.get("result_url"))
        return True

    def test_review_conflict_and_explicit_render_approval(self):
        with patch.object(ActionPrevisService, "_row", side_effect=lambda *_: copy.deepcopy(self.row)), \
             patch.object(ActionPrevisService, "_replace", side_effect=self.fake_replace), \
             patch.dict(os.environ, {"ZLY_ACTION_PREVIS_WORKER_TOKEN": "test-token"}):
            with self.assertRaisesRegex(RuntimeError, "REVISION_CONFLICT"):
                ActionPrevisService.revise("p", "job-1", sample_plan(), 0)
            changed = ActionPrevisService.revise("p", "job-1", sample_plan(), 1)
            self.assertEqual(changed["payload"]["plan_revision"], 2)
            with self.assertRaisesRegex(RuntimeError, "REVISION_CONFLICT"):
                ActionPrevisService.render("p", "job-1", 1)
            submitted = ActionPrevisService.render("p", "job-1", 2)
            self.assertEqual(submitted["status"], "queued_remote")
            self.assertEqual(submitted["payload"]["approved_revision"], 2)

    def test_cancel_ends_queued_remote_job(self):
        self.row["status"] = "queued_remote"
        with patch.object(ActionPrevisService, "_row", side_effect=lambda *_: copy.deepcopy(self.row)), \
             patch.object(ActionPrevisService, "_replace", side_effect=self.fake_replace):
            cancelled = ActionPrevisService.cancel("p", "job-1")
            self.assertEqual(cancelled["status"], "cancelled")

    def test_worker_quality_failure_is_never_marked_complete(self):
        payload = json.loads(self.row["payload_json"])
        payload.update(lease={"token": "lease", "worker_id": "w", "expires_at": time.time() + 100},
                       artifacts={key: "https://example.com/" + key for key in ("video", "blend", "contact_sheet", "report")})
        self.row.update(status="remote_running", payload_json=json.dumps(payload, ensure_ascii=False))
        with patch.object(ActionPrevisService, "_row", side_effect=lambda *_: copy.deepcopy(self.row)), \
             patch.object(ActionPrevisService, "_replace", side_effect=self.fake_replace), \
             patch("backend.app.media_studio.services.action_previs_service.resolve_analysis_endpoint", return_value=None):
            outcome = ActionPrevisService.complete("p", "job-1", "lease", {"passed": False, "issues": ["接触点偏离"]})
            self.assertEqual(outcome["status"], "needs_revision")
            self.assertIn("接触点偏离", outcome["payload"]["quality"]["issues"])

    def test_expired_worker_lease_cannot_heartbeat(self):
        payload = json.loads(self.row["payload_json"])
        payload["lease"] = {"token": "old", "worker_id": "w", "expires_at": time.time() - 1}
        self.row.update(status="remote_running", payload_json=json.dumps(payload, ensure_ascii=False))
        with patch.object(ActionPrevisService, "_row", side_effect=lambda *_: copy.deepcopy(self.row)):
            with self.assertRaisesRegex(ValueError, "租约无效"):
                ActionPrevisService.heartbeat("p", "job-1", "old", 60, "rendering")

    def test_failed_reviewed_job_can_retry_without_replanning(self):
        payload = json.loads(self.row["payload_json"])
        payload.update(approved_revision=1, artifacts={"video": "old"})
        self.row.update(status="needs_revision", payload_json=json.dumps(payload, ensure_ascii=False))
        with patch.object(ActionPrevisService, "_row", side_effect=lambda *_: copy.deepcopy(self.row)), \
             patch.object(ActionPrevisService, "_replace", side_effect=self.fake_replace):
            retried = ActionPrevisService.retry("p", "job-1")
            self.assertEqual(retried["status"], "queued_remote")
            self.assertEqual(retried["payload"]["approved_revision"], 1)
            self.assertEqual(retried["payload"]["artifacts"], {})

    def test_artifact_upload_requires_valid_lease_and_records_url(self):
        payload = json.loads(self.row["payload_json"])
        payload["lease"] = {"token": "lease", "worker_id": "w", "expires_at": time.time() + 100}
        self.row.update(status="remote_running", payload_json=json.dumps(payload, ensure_ascii=False))
        with patch.object(ActionPrevisService, "_row", side_effect=lambda *_: copy.deepcopy(self.row)), \
             patch.object(ActionPrevisService, "_replace", side_effect=self.fake_replace), \
             patch("backend.app.media_studio.services.action_previs_service.QiniuService.store_bytes", return_value=("key", "https://example.com/video")):
            with self.assertRaisesRegex(ValueError, "租约无效"):
                ActionPrevisService.artifact("p", "job-1", "bad", "video", b"mp4")
            saved = ActionPrevisService.artifact("p", "job-1", "lease", "video", b"mp4")
            self.assertEqual(saved["url"], "https://example.com/video")
            self.assertEqual(json.loads(self.row["payload_json"])["artifacts"]["video"], saved["url"])

    def test_agent_produces_reviewable_validated_plan(self):
        payload = json.loads(self.row["payload_json"])
        payload.update(description="双人近景对打与侧向运镜", beat_snapshot={"heading": "试探"}, references=[])
        self.row.update(status="planning", payload_json=json.dumps(payload, ensure_ascii=False))
        endpoint = SimpleNamespace(model="test-llm")
        with patch.object(ActionPrevisService, "_row", side_effect=lambda *_: copy.deepcopy(self.row)), \
             patch.object(ActionPrevisService, "_replace", side_effect=self.fake_replace), \
             patch("backend.app.media_studio.services.action_previs_service.credential_manager", return_value=SimpleNamespace(decrypt=lambda value: value)), \
             patch("backend.app.media_studio.services.action_previs_service.llm_row", return_value={}), \
             patch("backend.app.media_studio.services.action_previs_service.resolve_text_endpoint", return_value=endpoint), \
             patch("backend.app.media_studio.services.action_previs_service.chat_on_endpoint", return_value=json.dumps(sample_plan(), ensure_ascii=False)):
            ActionPrevisService._plan("p", "job-1")
        self.assertEqual(self.row["status"], "awaiting_review")
        reviewed = json.loads(self.row["payload_json"])
        self.assertEqual(reviewed["plan_revision"], 1)
        self.assertEqual(reviewed["plan"]["shots"][1]["angle"], "side")


class WorkerApiTests(unittest.TestCase):
    def test_private_claim_requires_token_and_returns_job_shape(self):
        from backend.app.main import app
        client = TestClient(app)
        with patch.dict(os.environ, {"ZLY_ACTION_PREVIS_WORKER_TOKEN": "test-token"}), \
             patch.object(ActionPrevisService, "claim", return_value=None) as claim:
            denied = client.post("/api/internal/action-previs/claim", json={"worker_id": "worker"})
            self.assertEqual(denied.status_code, 401)
            allowed = client.post("/api/internal/action-previs/claim", json={"worker_id": "worker"},
                                  headers={"Authorization": "Bearer test-token"})
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.json(), {"job": None})
            claim.assert_called_once_with("worker")


if __name__ == "__main__":
    unittest.main()
