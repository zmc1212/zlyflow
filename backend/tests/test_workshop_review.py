"""Recovery contract regressions: evidence, bounded repairs and compile fidelity."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.app.media_studio.services import workshop_contract as contract
from backend.app.media_studio.services import workshop_group_prompts as prompts
from backend.app.media_studio.services.workshop_h3_skill import AUTHORING_VERSION, split_complete_group_draft
from backend.app.media_studio.services.workshop_review import review_group
from backend.app.media_studio.services.workshop_service import WorkshopService
from backend.app.media_studio.services.h3_prompt_builder import H3PromptBuilder
from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient
from backend.tests.test_workshop_h3_skill import body, complete_draft


class RecoveryReviewTests(unittest.TestCase):
    def setUp(self):
        self.beats = [{"id": "a", "video_duration": 8, "speaker": "阿宁", "dialogue": "回来。"}]
        self.group = {"id": "g", "beat_ids": ["a"], "reference_slots": [],
                      "common_prompt": "人物\n声音设定：\n阿宁 (S1)：自然人声。"}
        self.plan = {"schema_version": 7, "revision": 1, "source_fingerprint": "source", "workflow_id": "minimax-h3-director-accel-t2v",
                     "aspect_ratio": "16:9", "groups": [self.group], "shot_prompts": {}, "max_shots_per_group": 3}

    def draft(self, text=None):
        return complete_draft([text or body()], common=self.group["common_prompt"])

    def codes(self, text, beat=None):
        return {i["code"] for i in review_group([beat or self.beats[0]], [text], self.group)["issues"]}

    def test_silent_action_still_needs_coverage(self):
        beat = {**self.beats[0], "dialogue": ""}
        self.assertIn("missing_action_timing", self.codes(body(dialogue="").replace("(0–8秒)", ""), beat))
        self.assertIn("action_bounds", self.codes(body(dialogue="").replace("(0–8秒)", "(0–9秒)"), beat))

    def test_parallel_different_hands_is_not_rejected(self):
        text = body(dialogue="").replace("(0–8秒) 人物缓缓抬头，最后停住。",
            "(0–8秒) 右手握笔写字，最后停住。(2–4秒) 同时左手翻页，右手仍握笔。")
        review = review_group([{**self.beats[0], "dialogue": ""}], [text], self.group)
        self.assertEqual(review["issues"], [])
        self.assertEqual(review["semantic_status"], "pending_human")

    def test_low_volume_not_slow_rate_and_risk_not_gate(self):
        line = "青山遮不住毕竟东流去这诗风不像宋人笔法"
        beat = {**self.beats[0], "dialogue": line}
        normal = body(dialogue=line)
        self.assertNotIn("speech_rate_risk", self.codes(normal, beat))
        slow = normal.replace("语速平稳", "一字一顿")
        self.assertIn("speech_rate_risk", self.codes(slow, beat))
        self.assertEqual(contract.prompt_checks(slow, beat, self.group, h3=True), [])

    def test_constraint_and_abstract_ending_have_quoted_evidence(self):
        text = body(dialogue="").replace("人物缓缓抬头，最后停住。", "他选了继续。").replace("口型同步", "禁止翻页")
        review = review_group([{**self.beats[0], "dialogue": "", "action": "翻页"}], [text], self.group)
        self.assertEqual({i["code"] for i in review["issues"]}, {"abstract_closure", "constraint_conflict"})
        self.assertTrue(all(i["evidence"] and i["suggestion"] for i in review["issues"]))

    def test_third_author_call_can_succeed(self):
        with patch.object(prompts.LlmService, "author_group", side_effect=[
            ("bad format", {}), (self.draft(body(number=2)), {}), (self.draft(), {})]) as call:
            result = prompts.generate_group(self.plan, self.group, self.beats)
        self.assertEqual(call.call_count, 3)
        self.assertIn("a", result)
        self.assertEqual(len(self.plan["writing_history"]), 3)

    def test_sound_masking_check_respects_explicit_negation(self):
        for sound in ("不得让环境声盖过台词", "避免音乐掩盖对白",
                      "禁止背景声压过人声", "环境声不盖过台词"):
            with self.subTest(sound=sound):
                text = body().replace("呼吸声与环境底噪。", sound)
                self.assertIn(sound, text)
                self.assertNotIn("masked_dialogue", self.codes(text))
        for sound in ("环境声盖过台词", "音乐完全掩盖对白",
                      "不得让环境声盖过台词；但高潮时音乐盖过台词"):
            with self.subTest(sound=sound):
                text = body().replace("呼吸声与环境底噪。", sound)
                self.assertIn(sound, text)
                self.assertIn("masked_dialogue", self.codes(text))

    def test_no_progress_stops_and_retains_raw(self):
        with patch.object(prompts.LlmService, "author_group", return_value=("bad format", {})) as call:
            with self.assertRaisesRegex(ValueError, "无进展"):
                prompts.generate_group(self.plan, self.group, self.beats)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(self.plan["rejected_groups"]["g"]["raw"], "bad format")
        self.assertTrue(self.plan["rejected_groups"]["g"]["not_approved"])

    def test_regression_preserves_less_broken_version(self):
        first = self.draft(body(number=2))
        worse = self.draft(body(number=2, end=8))
        with patch.object(prompts.LlmService, "author_group", side_effect=[(first, {}), (worse, {})]):
            with self.assertRaisesRegex(ValueError, "退步"):
                prompts.generate_group(self.plan, self.group, self.beats)
        self.assertEqual(self.plan["rejected_groups"]["g"]["raw"], first)

    def test_call_failure_is_recorded_and_never_falls_back(self):
        with patch.object(prompts.LlmService, "author_group", side_effect=RuntimeError("provider unavailable")) as call:
            with self.assertRaises(RuntimeError):
                prompts.generate_group(self.plan, self.group, self.beats, author={"model": "explicit-author"})
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self.plan["writing_history"][0]["author"]["requested_model"], "explicit-author")

    def test_single_revision_cannot_change_shared_settings(self):
        self.plan["shot_prompts"] = {"a": {"h3_prompt": body()}}
        with patch.object(prompts.LlmService, "author_group", return_value=(self.draft().replace("自然人声", "成熟人声"), {})) as call:
            with self.assertRaisesRegex(ValueError, "需整组返修"):
                prompts.generate_group(self.plan, self.group, self.beats, revision_beat_id="a")
        self.assertEqual(call.call_count, 1)

    def test_new_draft_preserves_dialogue_punctuation(self):
        with patch.object(prompts.LlmService, "author_group", return_value=(self.draft(body(dialogue="回来！")), {})):
            with self.assertRaisesRegex(ValueError, "逐句逐字"):
                prompts.generate_group(self.plan, self.group, self.beats)

    def test_adoption_validates_new_common_and_recomputes_fingerprint(self):
        raw = self.draft().replace("人物\n", "<Subject 1> 阿宁坐在书房。\n").replace("【主体】阿宁", "【主体】<Subject 1> 阿宁")
        base = deepcopy(self.plan)
        with patch.object(prompts.LlmService, "author_group", return_value=(raw, {})):
            candidates = prompts.generate_group(self.plan, self.group, self.beats)
        common = candidates.pop("__common_prompt__")
        payload = {"episode_id": "e", "source": {"fingerprint": "source"}, "base_plan": base, "beats": self.beats,
                   "prompt_scope": "group", "candidates": candidates, "common_prompt_candidates": {"g": common}, "applied_ids": []}
        current = deepcopy(base)
        def mutate(p, e, expected, op):
            op({"beats": self.beats}, current, {})
        with patch("backend.app.media_studio.services.workshop_service.query_one", return_value={"job_type": "workshop_prompt", "status": "completed", "payload_json": json.dumps(payload)}), \
             patch("backend.app.media_studio.services.workshop_service.execute_sql"), \
             patch.object(WorkshopService, "source", return_value={"fingerprint": "source"}), \
             patch.object(WorkshopService, "view", return_value={}), patch.object(WorkshopService, "mutate", side_effect=mutate):
            WorkshopService.job_action("p", "e", "j", {"action": "apply", "expected_revision": 1})
        self.assertEqual(current["groups"][0]["common_prompt"], common)
        record = current["shot_prompts"]["a"]
        self.assertEqual(record["fingerprint"], contract.prompt_fingerprint(self.beats[0], current["groups"][0], current))
        self.assertTrue(contract.content_matches(record, current["groups"][0], current))
        self.assertEqual(current["group_prompt_history"][0]["group"], base["groups"][0])

    def test_satisfied_fixture_compiles_without_creative_rewrite(self):
        raw = (Path(__file__).parent / "fixtures/director_ep1_2026-09-26/01_satisfied_prompt.txt").read_text(encoding="utf-8").strip()
        import re
        lines = re.findall(r"<d>\[中文\] (.*?)</d>", raw)
        beats = [{"id": f"s{i}", "video_duration": 8, "speaker": "沈砚", "dialogue": line} for i, line in enumerate(lines)]
        group = {"id": "g", "beat_ids": [b["id"] for b in beats], "timecode_mode": "cumulative",
                 "reference_slots": [{"token": "<Picture 1>", "image_url": "https://example.com/original.png"}]}
        parsed = split_complete_group_draft(raw, beats, group)
        group["common_prompt"] = parsed["common_prompt"]
        for beat, text in zip(beats, parsed["shots"]):
            self.assertEqual(contract.prompt_checks(text, beat, group, h3=True, ordered_beats=beats), [])
            compiled = H3PromptBuilder.compile_director_segment_prompt(parsed["common_prompt"], text)
            self.assertEqual(compiled["segment_prompt"], text)
            self.assertEqual(compiled["global_prompt"], parsed["common_prompt"])
            for field in ["主体", "动作", "镜头", "音效", "约束"]:
                section = text.split(f"【{field}】", 1)[1].split("【", 1)[0].strip()
                self.assertIn(section, raw)
        review = review_group(beats, parsed["shots"], group)
        self.assertEqual(review["structure_status"], "passed")
        self.assertTrue(any(i["code"] == "speech_rate_risk" for i in review["issues"]))
        self.assertEqual(review["media_status"], "not_reviewed")

        # Follow the actual v7 execution projection into the serialized Comfy graph.
        # No request is submitted and the synthetic upload is only a test mapping.
        plan = contract.new_plan(beats, "minimax-h3-director-accel-r2v",
                                 {"revision": 1, "fingerprint": "fixture-source"})
        plan["groups"] = [group]
        for beat, text in zip(beats, parsed["shots"]):
            plan["shot_prompts"][beat["id"]] = {
                "h3_prompt": text, "contract_version": AUTHORING_VERSION,
                "fingerprint": contract.prompt_fingerprint(beat, group, plan),
                "content_digest": contract.digest([text, group["common_prompt"],
                    plan["source_fingerprint"], AUTHORING_VERSION]),
            }
        shots, _ = contract.execution_shots({"beats": beats, "prompt_authoring": {"director_plan": plan}})
        for shot, text in zip(shots, parsed["shots"]):
            self.assertEqual(shot["prompt"], text)
            self.assertEqual(shot["global_prompt"], parsed["common_prompt"])
            self.assertEqual(shot["reference_urls"], [s["image_url"] for s in group["reference_slots"]])
            shot["uploaded_refs"] = [{"imageFile": "fixture-original.png", "fileName": "fixture-original.png",
                                       "type": "input", "subfolder": "refs"}]
        options = {"global_prompt": parsed["common_prompt"], "aspect_ratio": "16:9", "seed": 123}
        timeline = ComfyVideoClient.build_timeline(shots, "r2v — Reference to Video", options=options)
        graph = ComfyVideoClient.build_workflow(timeline, "r2v — Reference to Video", "test/compile-fidelity", options=options)
        inputs = next(node["inputs"] for node in graph.values() if node["class_type"] == "MiniMaxH3Director")
        submitted = json.loads(inputs["timeline_data"])
        self.assertEqual(inputs["global_prompt"], parsed["common_prompt"])
        self.assertEqual(submitted["global"]["prompt"], parsed["common_prompt"])
        self.assertEqual([s["prompt"] for s in submitted["segments"]], parsed["shots"])
        self.assertEqual([s["start"] for s in submitted["segments"]], [0, 192])
        self.assertEqual([s["frameCount"] for s in submitted["segments"]], [192, 192])
        self.assertEqual([s["refs"][0]["imageFile"] for s in submitted["segments"]], ["fixture-original.png"] * 2)
        self.assertEqual(inputs["total_frames"], 384)
        self.assertEqual(inputs["frame_rate"], 24.0)
        self.assertEqual(submitted["output"]["audioMode"], "generate")


if __name__ == "__main__":
    unittest.main()
