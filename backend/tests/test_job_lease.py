from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.media_studio.services import episode_video_service, job_lease
from backend.app.media_studio.services.episode_video_service import (
    EpisodeVideoService,
    _HEARTBEATED_VIDEO_STATUSES,
)
from backend.app.cloud_video.base import CloudTaskSnapshot

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def stamp(offset_seconds: float) -> str:
    return (datetime.now() - timedelta(seconds=offset_seconds)).strftime(_TIME_FORMAT)


def owned_row(*, lease_offset: float, worker: str = "other-host-1111-abcd1234") -> dict:
    return {
        "id": "job-owned",
        "status": "running",
        "worker_id": worker,
        "lease_updated_at": stamp(lease_offset),
        "updated_at": stamp(lease_offset),
        "payload_json": json.dumps({"render_scope": "shot", "project_id": "p1"}),
    }


class JobLeaseWorkerIdTests(unittest.TestCase):
    def test_worker_id_is_stable_per_process(self) -> None:
        self.assertEqual(job_lease.worker_id(), job_lease.worker_id())
        self.assertIn(str(os.getpid()), job_lease.worker_id())

    def test_worker_id_is_bounded_for_the_column(self) -> None:
        self.assertLessEqual(len(job_lease.worker_id()), 96)


class JobLeaseHeartbeatTests(unittest.TestCase):
    def test_heartbeat_touches_only_own_active_rows(self) -> None:
        job_lease._keeper_status["video_generation"] = ("queued", "running")
        try:
            with patch.object(job_lease, "execute_sql", return_value=2) as execute:
                self.assertEqual(job_lease.heartbeat_once(), 2)
            sql, params = execute.call_args.args
            self.assertIn("SET lease_updated_at = %s", sql)
            self.assertNotIn(" updated_at = %s", sql)
            self.assertIn("worker_id = %s", sql)
            self.assertEqual(params[1], "video_generation")
            self.assertEqual(params[2], job_lease.worker_id())
            self.assertEqual(params[3:], ("queued", "running"))
        finally:
            job_lease._keeper_status.clear()

    def test_heartbeat_registration_starts_one_keeper_thread(self) -> None:
        try:
            with patch.object(job_lease.threading, "Thread") as thread:
                thread.return_value.is_alive.return_value = True
                job_lease.start_heartbeat("video_generation", ("running",))
                job_lease.start_heartbeat("video_generation", ("running",))
                thread.assert_called_once()
                self.assertEqual(job_lease._keeper_status["video_generation"], ("running",))
        finally:
            job_lease._keeper_thread = None
            job_lease._keeper_status.clear()


class JobLeaseConvergeTests(unittest.TestCase):
    STATUSES = ("queued", "running")

    def _converge(self, rows: list[dict]):
        with patch.object(job_lease, "query_all", return_value=rows):
            with patch.object(job_lease, "execute_sql", return_value=1) as execute:
                return job_lease.converge_orphaned_jobs("video_generation", self.STATUSES), execute

    def test_fresh_lease_is_left_running(self) -> None:
        count, execute = self._converge([owned_row(lease_offset=30)])
        self.assertEqual(count, 0)
        execute.assert_not_called()

    def test_expired_lease_converges_with_owner_compare_and_set(self) -> None:
        count, execute = self._converge([owned_row(lease_offset=job_lease.LEASE_STALE_AFTER_SECONDS + 60)])
        self.assertEqual(count, 1)
        sql, params = execute.call_args.args
        self.assertIn("status = 'failed'", sql)
        self.assertIn("AND status = %s", sql)
        self.assertIn("AND worker_id = %s", sql)
        self.assertIn("心跳已超过", params[0])
        self.assertEqual(params[-2], "running")
        self.assertEqual(params[-1], "other-host-1111-abcd1234")
        recovery = json.loads(params[1])["recovery"]
        self.assertEqual(recovery["reason"], "lease_expired")
        self.assertEqual(recovery["owner_worker_id"], "other-host-1111-abcd1234")

    def test_rows_claimed_by_this_process_are_never_converged(self) -> None:
        count, execute = self._converge(
            [owned_row(lease_offset=10 ** 6, worker=job_lease.worker_id())]
        )
        self.assertEqual(count, 0)
        execute.assert_not_called()

    def test_unowned_row_waits_for_the_grace_period(self) -> None:
        fresh = owned_row(lease_offset=60) | {"worker_id": "", "lease_updated_at": None}
        count, execute = self._converge([fresh])
        self.assertEqual(count, 0)
        execute.assert_not_called()

    def test_unowned_row_beyond_grace_converges_as_legacy(self) -> None:
        stale = owned_row(lease_offset=job_lease.UNOWNED_GRACE_AFTER_SECONDS + 600)
        stale = {**stale, "worker_id": "", "lease_updated_at": None}
        count, execute = self._converge([stale])
        self.assertEqual(count, 1)
        sql, params = execute.call_args.args
        self.assertIn("无实例心跳", params[0])
        self.assertEqual(json.loads(params[1])["recovery"]["reason"], "unowned_stale")
        self.assertEqual(params[-1], "")

    def test_unparsable_timestamp_falls_back_to_updated_at(self) -> None:
        row = {**owned_row(lease_offset=0), "lease_updated_at": "not-a-time", "updated_at": stamp(10 ** 6)}
        count, _ = self._converge([row])
        self.assertEqual(count, 1)

    def test_reclaim_callback_prevents_failure_when_handled(self) -> None:
        row = owned_row(lease_offset=job_lease.LEASE_STALE_AFTER_SECONDS + 60)
        with patch.object(job_lease, "query_all", return_value=[row]):
            with patch.object(job_lease, "execute_sql", return_value=1) as execute:
                count = job_lease.converge_orphaned_jobs(
                    "video_generation", self.STATUSES, reclaim=lambda candidate: candidate["id"] == "job-owned",
                )
        self.assertEqual(count, 0)
        execute.assert_not_called()


class CloudJobResumeTests(unittest.TestCase):
    def _cloud_row(self, *, owner: str, lease_offset: float = 10) -> dict:
        payload = {
            "workflow_id": "cloud-grs-h3-r2v",
            "render_scope": "shot",
            "source_shots": [{"beat_id": "b1", "sequence": 1}],
            "shots": [{
                "beat_id": "b1", "sequence": 1, "prompt": "saved prompt",
                "remote_task_id": "13-remote-task",
            }],
        }
        return {
            "id": "job-cloud",
            "status": "running",
            "worker_id": owner,
            "lease_updated_at": stamp(lease_offset),
            "updated_at": stamp(lease_offset),
            "payload_json": json.dumps(payload),
        }

    def test_same_host_dead_owner_is_resumed_immediately(self) -> None:
        owner = f"{job_lease._worker_host()}-999999-deadbeef"
        row = self._cloud_row(owner=owner, lease_offset=5)
        with patch.object(episode_video_service, "orphaned_jobs", return_value=[row]), \
                patch.object(episode_video_service, "worker_process_alive", return_value=False), \
                patch.object(episode_video_service, "execute_sql", return_value=1) as execute, \
                patch.object(EpisodeVideoService, "_submit_job") as submit:
            self.assertEqual(EpisodeVideoService._resume_orphaned_cloud_jobs(), 1)
        submit.assert_called_once_with("job-cloud")
        sql, params = execute.call_args.args
        self.assertIn("status = 'queued'", sql)
        self.assertIn("worker_id = %s", sql)
        self.assertEqual(params[2], job_lease.worker_id())
        recovery_marker = json.loads(params[0])["cloud_resume"]
        self.assertEqual(recovery_marker["previous_worker_id"], owner)

    def test_alive_owner_is_not_resumed(self) -> None:
        owner = f"{job_lease._worker_host()}-123-alive123"
        row = self._cloud_row(owner=owner, lease_offset=5)
        with patch.object(episode_video_service, "orphaned_jobs", return_value=[row]), \
                patch.object(episode_video_service, "worker_process_alive", return_value=True), \
                patch.object(EpisodeVideoService, "_claim_cloud_job_for_resume") as claim:
            EpisodeVideoService._resume_orphaned_cloud_jobs()
        claim.assert_not_called()

    def test_cloud_job_without_remote_task_is_not_resumable(self) -> None:
        payload = {
            "workflow_id": "cloud-grs-h3-r2v",
            "render_scope": "shot",
            "shots": [{"beat_id": "b1", "sequence": 1}],
        }
        self.assertFalse(EpisodeVideoService._cloud_payload_resumable(payload))

    def test_resumed_shots_reuse_remote_task_and_prompt(self) -> None:
        shots = [{"beat_id": "b1", "sequence": 1}, {"beat_id": "b2", "sequence": 2}]
        stored = [{
            "beat_id": "b1", "sequence": 1, "prompt": "p1",
            "remote_task_id": "r1", "video_url": "https://cdn/v1.mp4",
        }]
        merged = EpisodeVideoService._merge_resumed_cloud_shots(shots, stored)
        self.assertEqual(merged[0]["remote_task_id"], "r1")
        self.assertEqual(merged[0]["video_url"], "https://cdn/v1.mp4")
        self.assertEqual(merged[0]["prompt"], "p1")
        self.assertNotIn("remote_task_id", merged[1])

    def test_resume_polls_existing_remote_task_without_resubmitting(self) -> None:
        class FakeService:
            resource_storage = object()

            def __init__(self) -> None:
                self.submit_calls = 0
                self.polled: list[str] = []

            def availability(self, provider_key: str):
                return True, None

            def submit_generation(self, *args, **kwargs):
                self.submit_calls += 1
                return "should-not-submit"

            def wait_for_task(self, provider_key: str, remote_task_id: str, on_progress=None):
                self.polled.append(remote_task_id)
                return CloudTaskSnapshot(
                    status="completed", progress=100, video_urls=["https://remote/v.mp4"],
                    remote_status="succeeded",
                )

            def download_and_store(self, urls, *, prefix: str, filename: str):
                return {
                    "kind": "video", "path": "cloud_video/grs/v.mp4", "label": "生成视频",
                    "cloud_url": "https://cdn/v.mp4",
                }

        fake = FakeService()
        payload = {
            "workflow_id": "cloud-grs-h3-r2v",
            "render_scope": "shot",
            "project_id": "p1",
            "episode_id": "e1",
            "cloud_base_options": {
                "model": "minimax-h3", "resolution": "768p", "aspect_ratio": "landscape",
            },
            "billing": {"user_id": "u1", "credits": 0},
            "source_shots": [{"beat_id": "b1", "sequence": 1, "cloud_duration": 15}],
            "shots": [{
                "beat_id": "b1", "sequence": 1, "prompt": "saved prompt",
                "remote_task_id": "13-remote-task", "cloud_duration": 15,
            }],
        }
        with patch.object(episode_video_service.CloudVideoService, "instance", return_value=fake), \
                patch.object(episode_video_service, "execute_sql", return_value=1), \
                patch.object(EpisodeVideoService, "_write_selected_beat_videos") as writeback:
            EpisodeVideoService._run_cloud_job("job-cloud", payload)
        self.assertEqual(fake.submit_calls, 0)
        self.assertEqual(fake.polled, ["13-remote-task"])
        writeback.assert_called_once()
        self.assertEqual(writeback.call_args.args[1][0]["video_url"], "https://cdn/v.mp4")


class EpisodeVideoLeaseWiringTests(unittest.TestCase):
    def test_awaiting_refine_is_not_heartbeated(self) -> None:
        self.assertNotIn("awaiting_refine", _HEARTBEATED_VIDEO_STATUSES)
        self.assertIn("upscaling", _HEARTBEATED_VIDEO_STATUSES)
        self.assertIn("queued", _HEARTBEATED_VIDEO_STATUSES)

    def test_recover_resumes_cloud_jobs_then_converges_leased_statuses(self) -> None:
        with patch.object(EpisodeVideoService, "_resume_orphaned_cloud_jobs") as resume:
            with patch(
                "backend.app.media_studio.services.episode_video_service.converge_orphaned_jobs"
            ) as converge:
                EpisodeVideoService.recover_orphaned_jobs()
        resume.assert_called_once_with()
        converge.assert_called_once()
        args, kwargs = converge.call_args
        self.assertEqual(args, ("video_generation", _HEARTBEATED_VIDEO_STATUSES))
        self.assertTrue(callable(kwargs.get("reclaim")))

    def test_state_update_refreshes_lease(self) -> None:
        with patch("backend.app.media_studio.services.episode_video_service.execute_sql", return_value=1) as execute:
            EpisodeVideoService._set_state("job-1", {"render_scope": "shot"}, "running", 55)
        sql, params = execute.call_args.args
        self.assertIn("lease_updated_at = %s", sql)
        self.assertIn("worker_id = %s", sql)
        self.assertEqual(params[4], job_lease.worker_id())

    def test_submit_claims_the_lease_keeper(self) -> None:
        path = "backend.app.media_studio.services.episode_video_service"
        with patch(f"{path}.start_heartbeat") as start:
            with patch(f"{path}._EXECUTOR") as executor:
                EpisodeVideoService._submit_job("job-1")
        start.assert_called_once_with("video_generation", _HEARTBEATED_VIDEO_STATUSES)
        executor.submit.assert_called_once_with(EpisodeVideoService._run_job, "job-1")


if __name__ == "__main__":
    unittest.main()
