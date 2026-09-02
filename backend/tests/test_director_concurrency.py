from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from backend.app.director_project_service import merge_recipe_creative, merge_recipe_execution, persist_recipe_execution
from backend.app.director_recipe import flatten_recipe_shots, normalize_recipe_payload
from backend.app.storage import DirectorProjectConflictError, JobStore


def sample_recipe() -> dict:
    return normalize_recipe_payload({
        "kind": "director_recipe",
        "script": {"title": "原始片名", "summary": "", "fullStory": "雨夜故事"},
        "scenes": [{
            "id": "scene-1",
            "sceneNumber": 1,
            "title": "暗巷",
            "locationName": "暗巷",
            "shots": [{
                "id": "shot-1",
                "shotNumber": 1,
                "title": "原始镜头",
                "description": "侦探穿过暗巷",
                "promptText": "detective in an alley",
                "dialogue": "",
                "durationSec": 5,
                "status": "succeeded",
                "outputVideoUrl": "/old.mp4",
                "approvedTakeId": "take-old",
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


class DirectorConcurrencyStorageTests(unittest.TestCase):
    def test_tts_execution_merge_does_not_overwrite_user_voice_choices(self) -> None:
        latest = sample_recipe()
        latest_shot = flatten_recipe_shots(latest)[0]
        latest_shot["voiceId"] = "voice-local"
        latest["characters"] = [{
            "id": "character-1",
            "name": "侦探",
            "voiceId": "voice-character-local",
        }]
        incoming = deepcopy(latest)
        incoming_shot = flatten_recipe_shots(incoming)[0]
        incoming_shot.update({
            "voiceId": "voice-stale",
            "ttsStatus": "succeeded",
            "ttsUrl": "/tts.mp3",
        })
        incoming["characters"][0].update({
            "voiceId": "voice-character-stale",
            "voicePreviewUrl": "/preview.mp3",
        })

        merged = merge_recipe_execution(
            latest,
            incoming,
            scope="tts",
            shot_ids=["shot-1"],
            character_id="character-1",
        )

        shot = flatten_recipe_shots(merged)[0]
        self.assertEqual(shot["voiceId"], "voice-local")
        self.assertEqual(shot["ttsStatus"], "succeeded")
        self.assertEqual(shot["ttsUrl"], "/tts.mp3")
        self.assertEqual(merged["characters"][0]["voiceId"], "voice-character-local")
        self.assertEqual(merged["characters"][0]["voicePreviewUrl"], "/preview.mp3")

    def test_creative_merge_accepts_reference_frame_edits(self) -> None:
        latest = sample_recipe()
        latest_shot = flatten_recipe_shots(latest)[0]
        latest_shot.update({
            "firstFrameUrl": "/old-frame.png",
            "firstFrameJobId": "old-frame-job",
            "status": "succeeded",
            "outputVideoUrl": "/old.mp4",
        })
        incoming = deepcopy(latest)
        incoming_shot = flatten_recipe_shots(incoming)[0]
        incoming_shot.update({
            "firstFrameUrl": "/new-frame.png",
            "firstFrameJobId": "new-frame-job",
            "status": "idle",
            "outputVideoUrl": None,
        })

        merged = merge_recipe_creative(latest, incoming)
        shot = flatten_recipe_shots(merged)[0]
        self.assertEqual(shot["firstFrameUrl"], "/new-frame.png")
        self.assertEqual(shot["firstFrameJobId"], "new-frame-job")
        self.assertEqual(shot["status"], "succeeded")
        self.assertEqual(shot["outputVideoUrl"], "/old.mp4")

    def test_migrates_legacy_projects_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    """CREATE TABLE director_projects (
                        id TEXT PRIMARY KEY,
                        owner_user_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        summary TEXT NOT NULL DEFAULT '',
                        source_script TEXT NOT NULL DEFAULT '',
                        style_vibe TEXT,
                        requested_shot_count INTEGER,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )""",
                )
                connection.execute(
                    """INSERT INTO director_projects
                    (id, owner_user_id, title, summary, source_script, payload_json, created_at, updated_at)
                    VALUES ('project-1', 'user-1', '旧工程', '', '', ?, '2026-08-29', '2026-08-29')""",
                    (json.dumps(sample_recipe(), ensure_ascii=False),),
                )
                connection.commit()
            finally:
                connection.close()

            store = JobStore(path)
            project = store.get_director_project("project-1")
            self.assertEqual(project["revision"], 1)
            self.assertEqual(project["content_revision"], 1)
            self.assertTrue(path.with_name("legacy.db.pre-director-concurrency-v2.bak").is_file())
            connection = store.connection()
            try:
                operation_table = store._db.table_exists(connection, "director_operations")
            finally:
                connection.close()
            self.assertTrue(operation_table)

    def test_execution_merge_preserves_concurrent_edit_and_appends_takes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            created = store.create_director_project(
                "user-1", "原始片名", source_script="雨夜故事", payload=sample_recipe(),
            )
            stale_generation = deepcopy(created["payload"])

            edited = deepcopy(created["payload"])
            edited["script"]["title"] = "生成期间修改的片名"
            edited_shot = flatten_recipe_shots(edited)[0]
            edited_shot["title"] = "生成期间修改的镜头"
            edited_shot["durationSec"] = 8
            edited_shot["approvedTakeId"] = "take-old"
            creative = store.update_director_project(
                created["id"],
                payload=edited,
                expected_content_revision=created["content_revision"],
                payload_merger=merge_recipe_creative,
                content_update=True,
            )

            incoming_shot = flatten_recipe_shots(stale_generation)[0]
            incoming_shot.update({
                "jobId": "job-new-1",
                "status": "queued",
                "progress": 4,
                "compiledPrompt": "compiled one",
                "error": None,
            })
            incoming_shot["takes"].append({
                "id": "take-new-1",
                "jobId": "job-new-1",
                "status": "queued",
                "progress": 4,
                "videoUrl": None,
                "createdAt": "2026-08-30T00:01:00Z",
            })
            first = persist_recipe_execution(
                store, created["id"], stale_generation, scope="render", shot_ids=["shot-1"],
            )

            second_generation = deepcopy(created["payload"])
            second_shot = flatten_recipe_shots(second_generation)[0]
            second_shot.update({"jobId": "job-new-2", "status": "queued", "progress": 4})
            second_shot["takes"].append({
                "id": "take-new-2",
                "jobId": "job-new-2",
                "status": "queued",
                "progress": 4,
                "videoUrl": None,
                "createdAt": "2026-08-30T00:02:00Z",
            })
            saved = persist_recipe_execution(
                store, created["id"], second_generation, scope="render", shot_ids=["shot-1"],
            )

            shot = flatten_recipe_shots(saved["payload"])[0]
            self.assertEqual(saved["content_revision"], creative["content_revision"])
            self.assertGreater(saved["revision"], first["revision"])
            self.assertEqual(saved["payload"]["script"]["title"], "生成期间修改的片名")
            self.assertEqual(shot["title"], "生成期间修改的镜头")
            self.assertEqual(shot["durationSec"], 8)
            self.assertEqual(shot["approvedTakeId"], "take-old")
            self.assertEqual(
                [take["id"] for take in shot["takes"]],
                ["take-old", "take-new-1", "take-new-2"],
            )

    def test_stale_content_revision_conflicts_and_force_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            created = store.create_director_project("user-1", "工程", payload=sample_recipe())
            updated = store.update_director_project(
                created["id"], title="窗口 A", expected_content_revision=1,
            )
            with self.assertRaises(DirectorProjectConflictError) as ctx:
                store.update_director_project(
                    created["id"], title="窗口 B", expected_content_revision=1,
                )
            self.assertEqual(ctx.exception.current_project["title"], "窗口 A")
            forced = store.update_director_project(
                created["id"], title="窗口 B", expected_content_revision=1, force=True,
            )
            self.assertEqual(forced["content_revision"], updated["content_revision"] + 1)
            self.assertEqual(forced["title"], "窗口 B")

    def test_operations_are_persistent_exclusive_and_interrupted_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            store = JobStore(path)
            project = store.create_director_project("user-1", "工程", payload=sample_recipe())
            first = store.create_director_operation(
                project_id=project["id"], owner_user_id="user-1", kind="plan_pipeline",
                request={"goal": "雨夜"},
            )
            with self.assertRaises(ValueError):
                store.create_director_operation(
                    project_id=project["id"], owner_user_id="user-1", kind="shot_render_prepare",
                )
            store.update_director_operation(first["id"], status="running", progress=42)

            reopened = JobStore(path)
            self.assertEqual(reopened.get_director_operation(first["id"])["status"], "running")
            self.assertEqual(reopened.interrupt_stale_director_operations(), 1)
            interrupted = reopened.get_director_operation(first["id"])
            self.assertEqual(interrupted["status"], "interrupted")
            self.assertIn("不会自动重试", interrupted["error"])
            second = reopened.create_director_operation(
                project_id=project["id"], owner_user_id="user-1", kind="shot_render_prepare",
            )
            self.assertEqual(second["status"], "queued")


if __name__ == "__main__":
    unittest.main()
