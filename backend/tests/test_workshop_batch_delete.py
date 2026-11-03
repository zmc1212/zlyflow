from __future__ import annotations

from contextlib import contextmanager
import json
import unittest
from unittest.mock import Mock, patch

from backend.app.media_studio.services.project_detail_service import ProjectDetailService


class WorkshopBatchDeleteTests(unittest.TestCase):
    def setUp(self):
        self.beats = [
            {"id": "a", "sequence": 1, "description": "保留的新正文", "video_url": "https://cdn/a.mp4", "video_takes": [{"id": "take-a"}]},
            {"id": "b", "sequence": 2, "description": "删除的片段"},
            {"id": "c", "sequence": 3, "character_ids": ["character"], "sketch_url": "https://cdn/c.png"},
        ]
        self.data = {"beats": self.beats, "script_text": "原剧本", "other_setting": {"keep": True}, "episode_video_url": "https://cdn/old-cut.mp4", "episode_video_source": "compose", "episode_video_job_id": "compose-job"}
        self.cursor = Mock()
        self.cursor.fetchone.return_value = {"data_json": json.dumps(self.data, ensure_ascii=False)}
        self.cursor.fetchall.return_value = []

        @contextmanager
        def cursor_context():
            yield self.cursor

        self.transaction = patch("backend.app.media_studio.services.project_detail_service.transaction_cursor", cursor_context)
        self.transaction.start()
        self.addCleanup(self.transaction.stop)

    def updates(self):
        return [call for call in self.cursor.execute.call_args_list if call.args[0].startswith("UPDATE")]

    def test_preserves_latest_remaining_beats_and_scopes_the_transaction(self):
        result = ProjectDetailService.delete_episode_beats("project", "episode", ["b", "b"])
        self.assertEqual(["b"], result["deleted_beat_ids"])
        self.assertEqual([self.beats[0], self.beats[2]], result["beats"])
        first = self.cursor.execute.call_args_list[0]
        self.assertIn("FOR UPDATE", first.args[0])
        self.assertEqual(("episode", "project"), first.args[1])
        write = self.updates()[0]
        saved = json.loads(write.args[1][0])
        self.assertEqual("原剧本", saved["script_text"])
        self.assertEqual({"keep": True}, saved["other_setting"])
        self.assertEqual(result["beats"], saved["beats"])
        self.assertFalse(any(key.startswith("episode_video_") for key in saved))
        self.assertEqual(2, write.args[1][1])
        self.assertEqual(("episode", "project"), write.args[1][-2:])
        self.assertFalse(any("DELETE" in call.args[0] for call in self.cursor.execute.call_args_list))

    def test_returns_deleted_ids_in_episode_order(self):
        result = ProjectDetailService.delete_episode_beats("project", "episode", ["c", "a"])
        self.assertEqual(["a", "c"], result["deleted_beat_ids"])
        self.assertEqual([self.beats[1]], result["beats"])

    def test_empty_or_invalid_selection_never_writes(self):
        for ids in (None, [], "a", [""], [None], [" "]):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, "选择"):
                ProjectDetailService.delete_episode_beats("project", "episode", ids)
        self.cursor.execute.assert_not_called()

    def test_stale_selection_and_deleting_all_are_rejected(self):
        for ids, reason in ((["missing"], "列表已变化"), (["a", "b", "c"], "保留 1")):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, reason):
                ProjectDetailService.delete_episode_beats("project", "episode", ids)
        self.assertEqual([], self.updates())

    def test_missing_or_malformed_episode_never_writes(self):
        for row in (None, {"data_json": "not-json"}, {"data_json": "[]"}, {"data_json": '{"beats":[null]}'}, {"data_json": "{}"}):
            self.cursor.fetchone.return_value = row
            with self.subTest(row=row), self.assertRaises(ValueError):
                ProjectDetailService.delete_episode_beats("project", "episode", ["b"])
        self.assertEqual([], self.updates())

    def test_jobs_touching_selection_or_whole_episode_block_deletion(self):
        for detail in ({"beat_id": "b"}, {"beat_ids": ["b", "c"]}, {"source_shots": [{"beat_id": "b"}]}, {"shots": [{"beat_id": "b"}]}, {"render_scope": "compose", "beat_ids": ["a"]}, {"render_scope": "episode", "beat_ids": ["a"]}, {}):
            self.cursor.fetchall.return_value = [{"job_type": "video_generation", "payload_json": json.dumps({"episode_id": "episode", **detail})}]
            with self.subTest(detail=detail), self.assertRaisesRegex(RuntimeError, "正在生成"):
                ProjectDetailService.delete_episode_beats("project", "episode", ["b"])
        self.assertEqual([], self.updates())

    def test_other_episode_or_other_clip_jobs_do_not_block(self):
        self.cursor.fetchall.return_value = [
            {"payload_json": json.dumps({"episode_id": "other", "beat_id": "b"})},
            {"payload_json": json.dumps({"episode_id": "episode", "beat_id": "a"})},
        ]
        self.assertEqual(["b"], ProjectDetailService.delete_episode_beats("project", "episode", ["b"])["deleted_beat_ids"])
        query = self.cursor.execute.call_args_list[1]
        self.assertIn("status NOT IN", query.args[0])
        self.assertIn("'completed'", query.args[0])
        self.assertIn("'failed'", query.args[0])
        self.assertEqual(("project",), query.args[1])


if __name__ == "__main__":
    unittest.main()
