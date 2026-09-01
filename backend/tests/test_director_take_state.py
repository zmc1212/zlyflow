from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.director_export import shot_is_muxable
from backend.app.director_jobs import sync_recipe_asset_images
from backend.app.director_recipe import flatten_recipe_shots, normalize_recipe_payload
from backend.app.models import JobMode, JobStatus
from backend.app.storage import JobStore


def recipe_for_job(*, job_id: str, with_old_take: bool = True) -> dict:
    takes = []
    if with_old_take:
        takes.append({
            "id": "take-old",
            "jobId": "job-old",
            "status": "succeeded",
            "progress": 100,
            "videoUrl": "/old.mp4",
            "createdAt": "2026-08-30T00:00:00Z",
        })
    takes.append({
        "id": "take-new",
        "jobId": job_id,
        "status": "queued",
        "progress": 0,
        "createdAt": "2026-08-30T00:01:00Z",
    })
    return normalize_recipe_payload({
        "kind": "director_recipe",
        "scenes": [{
            "id": "scene-1",
            "shots": [{
                "id": "shot-1",
                "title": "镜头",
                "description": "雨夜",
                "durationSec": 5,
                "jobId": job_id,
                "status": "queued",
                "outputVideoUrl": "/old.mp4" if with_old_take else None,
                "approvedTakeId": "take-old" if with_old_take else None,
                "takes": takes,
            }],
        }],
    })


class DirectorTakeStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "jobs.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_job(self, job_id: str) -> None:
        self.store.create(
            job_id,
            JobMode.MINIMAX_H3_T2V,
            "prompt",
            "",
            None,
            [],
            owner_user_id="user-1",
        )

    def test_approved_old_take_does_not_mask_current_queued_job(self) -> None:
        self._create_job("job-new")
        shot = flatten_recipe_shots(sync_recipe_asset_images(
            self.store,
            recipe_for_job(job_id="job-new"),
        ))[0]
        self.assertEqual(shot["jobId"], "job-new")
        self.assertEqual(shot["status"], "queued")
        self.assertEqual(shot["outputVideoUrl"], "/old.mp4")

    def test_failed_current_job_restores_old_take_and_retains_error(self) -> None:
        self._create_job("job-new")
        self.store.update("job-new", status=JobStatus.FAILED, error="ComfyUI OOM")
        shot = flatten_recipe_shots(sync_recipe_asset_images(
            self.store,
            recipe_for_job(job_id="job-new"),
        ))[0]
        self.assertEqual(shot["status"], "succeeded")
        self.assertEqual(shot["jobId"], "job-new")
        self.assertEqual(shot["outputVideoUrl"], "/old.mp4")
        self.assertEqual(shot["error"], "ComfyUI OOM")
        self.assertEqual(shot["takes"][-1]["status"], "failed")
        self.assertTrue(shot_is_muxable(shot))

    def test_orphaned_queued_shot_without_job_is_reverted_to_idle(self) -> None:
        recipe = normalize_recipe_payload({
            "kind": "director_recipe",
            "scenes": [{
                "id": "scene-1",
                "shots": [{
                    "id": "shot-1",
                    "title": "镜头",
                    "description": "雨夜",
                    "durationSec": 5,
                    "status": "queued",
                    "progress": 4,
                    "jobId": None,
                }],
            }],
        })
        shot = flatten_recipe_shots(sync_recipe_asset_images(self.store, recipe))[0]
        self.assertEqual(shot["status"], "idle")
        self.assertEqual(shot["progress"], 0)
        self.assertIsNone(shot.get("jobId"))

    def test_orphaned_queued_shot_restores_previous_take(self) -> None:
        recipe = normalize_recipe_payload({
            "kind": "director_recipe",
            "scenes": [{
                "id": "scene-1",
                "shots": [{
                    "id": "shot-1",
                    "title": "镜头",
                    "description": "雨夜",
                    "durationSec": 5,
                    "status": "queued",
                    "progress": 4,
                    "jobId": None,
                    "outputVideoUrl": "/old.mp4",
                    "takes": [{
                        "id": "take-old",
                        "jobId": "job-old",
                        "status": "succeeded",
                        "progress": 100,
                        "videoUrl": "/old.mp4",
                        "createdAt": "2026-08-30T00:00:00Z",
                    }],
                }],
            }],
        })
        shot = flatten_recipe_shots(sync_recipe_asset_images(self.store, recipe))[0]
        self.assertEqual(shot["status"], "succeeded")
        self.assertEqual(shot["outputVideoUrl"], "/old.mp4")

    def test_failed_current_job_without_old_take_stays_failed(self) -> None:
        self._create_job("job-new")
        self.store.update("job-new", status=JobStatus.FAILED, error="ComfyUI OOM")
        shot = flatten_recipe_shots(sync_recipe_asset_images(
            self.store,
            recipe_for_job(job_id="job-new", with_old_take=False),
        ))[0]
        self.assertEqual(shot["status"], "failed")
        self.assertEqual(shot["error"], "ComfyUI OOM")
        self.assertFalse(shot_is_muxable(shot))


if __name__ == "__main__":
    unittest.main()
