import json
import unittest
from unittest.mock import patch

from backend.app.media_studio.services import workshop_group_prompts as prompts
from backend.app.media_studio.services.workshop_service import WorkshopService
from copy import deepcopy
from backend.tests.test_workshop_h3_skill import body, complete_draft


class GroupPromptTests(unittest.TestCase):
    def setUp(self):
        self.group = {"id": "g", "beat_ids": ["a", "b"], "common_prompt": "人物\n声音设定：\n无对白，不添加人声。", "reference_slots": [], "timecode_mode": "cumulative"}
        self.plan = {"workflow_id": "minimax-h3-director-accel-r2v", "aspect_ratio": "16:9", "groups": [self.group]}
        self.beats = [{"id": x, "video_duration": 8} for x in ["a", "b"]]

    def test_single_selection_expands_in_group_order(self):
        self.assertEqual(prompts.expand_groups(self.plan, ["b"]), ["a", "b"])

    @patch.object(prompts.LlmService, "author_group")
    def test_missing_or_duplicate_shot_rejects_whole_group(self, chat):
        # Wrong shot counts or duplicated numbers all break the 1..N sequence.
        variants = [
            complete_draft([body(dialogue="")]),
            complete_draft([body(dialogue=""), body(dialogue="")]).replace("[Shot 2]", "[Shot 1]"),
            complete_draft([body(dialogue=""), body(dialogue=""), body(dialogue="")]),
        ]
        for draft in variants:
            chat.side_effect = [(draft, {"ok": True})] * 3
            with self.assertRaisesRegex(ValueError, "镜头编号"):
                prompts.generate_group(self.plan, self.group, self.beats)
            chat.side_effect = None

    @patch.object(prompts.contract, "prompt_fingerprint", return_value="fp")
    @patch.object(prompts.LlmService, "author_group")
    def test_one_call_returns_all_shots(self, chat, fingerprint):
        chat.return_value = (complete_draft([body(dialogue=""), body(dialogue="", offset=8)]), {"ok": True})
        result = prompts.generate_group(self.plan, self.group, self.beats)
        self.assertEqual([key for key in result if key != "__common_prompt__"], ["a", "b"])
        self.assertIn("__common_prompt__", result)
        chat.assert_called_once()

    def create_payload(self, request, profile="director_segments", complete=True):
        plan = {**self.plan, "schema_version": 7, "revision": 1, "source_fingerprint": "source",
                "shot_prompts": {bid: {"h3_prompt": bid, "fingerprint": "fp"} for bid in (["a", "b"] if complete else ["a"])}}
        with patch.object(WorkshopService, "row", return_value=({"episode_num": 1}, {"beats": self.beats, "prompt_authoring": {"director_plan": plan}})), \
             patch.object(WorkshopService, "source", return_value={"text": "script", "fingerprint": "source"}), \
             patch.object(WorkshopService, "view", return_value={"jobs": []}), \
             patch.object(WorkshopService.executor, "submit"), \
             patch("backend.app.media_studio.services.workshop_h3_skill.writing_author", return_value={"profile_id": "p", "base_url": "https://example.com/v1", "model": "test", "reasoning_effort": "low", "supports_vision": True}), \
             patch("backend.app.media_studio.services.workshop_service.execute_sql") as sql, \
             patch.object(prompts, "workflow_for") as workflow, \
             patch.object(prompts.contract, "prompt_fingerprint", return_value="fp"):
            workflow.return_value.prompt_profile = profile
            WorkshopService.create("project", "episode", "workshop_prompt", {"expected_revision": 1, **request})
            return json.loads(sql.call_args.args[1][4])

    def test_director_expands_but_regular_stays_single(self):
        self.assertEqual(self.create_payload({"beat_ids": ["b"]})["request"]["beat_ids"], ["a", "b"])
        self.assertEqual(self.create_payload({"beat_ids": ["b"]}, "full_reference")["request"]["beat_ids"], ["b"])

    def test_revision_keeps_only_target_and_requires_group_context(self):
        request = {"beat_ids": ["a"], "prompt_scope": "shot_revision", "revision_note": "动作更克制"}
        payload = self.create_payload(request)
        self.assertEqual(payload["request"]["beat_ids"], ["a"])
        self.assertEqual(payload["prompt_scope"], "shot_revision")
        with self.assertRaisesRegex(ValueError, "整组"):
            self.create_payload(request, complete=False)
        with self.assertRaisesRegex(ValueError, "返修意见"):
            self.create_payload({**request, "revision_note": ""})

    def test_apply_revision_changes_only_target_and_rejects_changed_neighbor(self):
        base = {**self.plan, "revision": 1, "shot_prompts": {bid: {"h3_prompt": bid, "fingerprint": "fp"} for bid in ["a", "b"]}}
        payload = {"episode_id": "episode", "source": {"fingerprint": "source"}, "base_plan": base,
                   "prompt_scope": "shot_revision", "request": {"beat_ids": ["a"]}, "applied_ids": [],
                   "candidates": {"a": {"h3_prompt": body(dialogue=""), "fingerprint": "fp"}}}
        for conflict in [False, True]:
            current = deepcopy(base)
            if conflict:
                current["shot_prompts"]["b"]["h3_prompt"] = "new neighbor"
            def mutate(project, episode, expected, operation):
                operation({"beats": self.beats}, current, {})
            with patch("backend.app.media_studio.services.workshop_service.query_one", return_value={"job_type": "workshop_prompt", "status": "completed", "payload_json": json.dumps(payload)}), \
                 patch("backend.app.media_studio.services.workshop_service.execute_sql"), \
                 patch.object(WorkshopService, "mutate", side_effect=mutate), \
                 patch.object(WorkshopService, "source", return_value={"fingerprint": "source"}), \
                 patch.object(WorkshopService, "view", return_value={}), \
                 patch.object(prompts.contract, "prompt_fingerprint", return_value="fp"):
                if conflict:
                    with self.assertRaisesRegex(ValueError, "同组提示词已变化"):
                        WorkshopService.job_action("project", "episode", "job", {"action": "apply", "beat_ids": ["a"], "expected_revision": 1})
                else:
                    WorkshopService.job_action("project", "episode", "job", {"action": "apply", "beat_ids": ["a"], "expected_revision": 1})
                    self.assertEqual(current["shot_prompts"]["a"]["h3_prompt"], body(dialogue=""))
                    self.assertEqual(current["shot_prompts"]["b"], base["shot_prompts"]["b"])


if __name__ == "__main__":
    unittest.main()
