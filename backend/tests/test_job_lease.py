from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.media_studio.services import job_lease
from backend.app.media_studio.services.episode_video_service import (
    EpisodeVideoService,
    _HEARTBEATED_VIDEO_STATUSES,
)

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


class EpisodeVideoLeaseWiringTests(unittest.TestCase):
    def test_awaiting_refine_is_not_heartbeated(self) -> None:
        self.assertNotIn("awaiting_refine", _HEARTBEATED_VIDEO_STATUSES)
        self.assertIn("upscaling", _HEARTBEATED_VIDEO_STATUSES)
        self.assertIn("queued", _HEARTBEATED_VIDEO_STATUSES)

    def test_recover_only_converges_leased_statuses(self) -> None:
        with patch("backend.app.media_studio.services.episode_video_service.converge_orphaned_jobs") as converge:
            EpisodeVideoService.recover_orphaned_jobs()
        converge.assert_called_once_with("video_generation", _HEARTBEATED_VIDEO_STATUSES)

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
