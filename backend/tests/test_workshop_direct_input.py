import unittest
import json
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch

from backend.app.media_studio.services import workshop_contract as contract
from backend.app.media_studio.services import workshop_group_prompts as prompts
from backend.app.media_studio.services.workshop_direct_input import (
    build_input, VERSION as CURRENT_VERSION, dialogues_match, unavailable_audio_references,
)
from backend.app.media_studio.services.workshop_h3_skill import DIRECT_SKILL_PATH, SKILL_PATH, ensure_sound_settings
from backend.tests.test_workshop_h3_skill import body, complete_draft


# Frozen v2 validation regression coverage; new v3 behavior is tested separately.
VERSION = "h3-skill-direct-v2"

class DirectInputTests(unittest.TestCase):
    def setUp(self):
        self.beats = [{"id": "a", "video_duration": 8, "action": "抬头看向窗外", "audio": "远处鸟鸣"},
                      {"id": "b", "video_duration": 8, "action": "低头翻书", "dramatic_intent": "查证真相"}]
        self.group = {"id": "g", "beat_ids": ["a", "b"], "common_prompt": "旧稿污染",
                      "reference_slots": [], "timecode_mode": "cumulative"}
        self.plan = {"schema_version": 7, "workflow_id": "minimax-h3-director-accel-r2v", "aspect_ratio": "16:9",
                     "groups": [self.group], "source_fingerprint": "source", "shot_prompts": {}}
        self.source = {"text": "已经确认的完整分集剧本", "revision": 3, "source_type": "adopted_document_episode"}

    def snapshot(self):
        snapshot = build_input(self.plan, self.group, self.beats, self.source)
        snapshot["version"] = VERSION
        return snapshot

    def test_full_skill_and_creative_details_without_cache(self):
        result = self.snapshot()
        self.assertEqual(result["system"], DIRECT_SKILL_PATH.read_bytes().decode("utf-8"))
        for text in (self.source["text"], "抬头看向窗外", "远处鸟鸣", "查证真相"):
            self.assertIn(text, result["user"])
        self.assertNotIn("旧稿污染", result["user"])
        self.assertNotIn("beat_ids", result["user"])

    def test_original_skill_remains_byte_identical(self):
        import hashlib
        self.assertEqual(hashlib.sha256(SKILL_PATH.read_bytes()).hexdigest(),
                         "1bcdbc65ead1a4f32d8f9c13f03fd60d4b6d356f74a844e9b3ab3fac19ea1780")

    def test_source_overlap_does_not_erase_shot_dialogue_assignment(self):
        self.source["text"] = "甲说：先等等。随后乙说：现在走。甲抬头看向窗外。"
        self.beats[0].update(speaker="甲", dialogue="先等等。")
        self.beats[1].update(speaker="乙", dialogue="现在走。")
        material = self.snapshot()["user"].split("已确认的镜头创作材料：", 1)[1]
        first, second = material.split("镜头 2，", 1)
        self.assertIn("dialogue：先等等。", first)
        self.assertIn("speaker：甲", first)
        self.assertIn("action：抬头看向窗外", first)
        self.assertIn("dialogue：现在走。", second)
        self.assertIn("speaker：乙", second)

    def test_quote_comparison_preserves_words_pauses_order_and_apostrophes(self):
        for quoted in ("‘雨过天晴’……先等等。", '"雨过天晴"……先等等。', "「雨过天晴」……先等等。"):
            with self.subTest(quoted=quoted):
                self.assertTrue(dialogues_match([quoted], ["雨过天晴……先等等。"], VERSION))
                self.assertFalse(dialogues_match([quoted], ["雨过天晴……先等等。"], "h3-skill-direct-v1"))
        for changed in ("雨过天晴，先等等。", "雨过晴……先等等。", "雨过天晴……先等等。先等等。", "雨过天晴……先等。", "‘雨过天晴……先等等。"):
            with self.subTest(changed=changed):
                self.assertFalse(dialogues_match(["‘雨过天晴’……先等等。"], [changed], VERSION))
        self.assertFalse(dialogues_match(["don't", "John's"], ["dont", "Johns"], VERSION))
        self.assertFalse(dialogues_match(["先。", "后。"], ["后。", "先。"], VERSION))
        self.assertFalse(dialogues_match(["先。", "后。"], ["先。后。"], VERSION))

    def test_actual_audio_reference_checks_ignore_negative_and_spoken_mentions(self):
        for text in ("参考音频 1", "参考音频二", "音频参考 #2", "第 3 段参考音频", "<audio 1>"):
            self.assertTrue(unavailable_audio_references(text), text)
        for text in ("未提供参考音频。", "没有提供参考音频 1", "不使用<Audio 1>",
                     "自然人声由 H3 生成，全片保持一致。", "<d>[中文] 请打开参考音频1。</d>"):
            self.assertFalse(unavailable_audio_references(text), text)
        self.assertEqual(unavailable_audio_references("没有参考音频1，使用参考音频2"), ["参考音频2"])

    def test_real_failed_sample_v2_identifies_missing_audio_not_quote_typography(self):
        root = Path(__file__).parent / "fixtures/director_ep1_2026-09-26"
        frozen = json.loads((root / "08_skill_direct_controlled_snapshot.json").read_text(encoding="utf8"))
        sample = json.loads((root / "09_authorized_batch_2026-09-27/new.json").read_text(encoding="utf8"))
        from backend.app.media_studio.services.workshop_h3_skill import split_complete_group_draft
        beats = frozen["beats"]
        group = {"id": "real", "beat_ids": [b["id"] for b in beats], "timecode_mode": "cumulative",
                 "reference_slots": [frozen["reference"]], "contract_version": VERSION}
        parsed = split_complete_group_draft(sample["raw"], beats, group)
        group["common_prompt"] = parsed["common_prompt"]
        errors = contract.prompt_checks(parsed["shots"][0], beats[0], group, h3=True, ordered_beats=beats)
        self.assertEqual(errors, ["引用了未提供的参考音频"])
        old_errors = contract.prompt_checks(parsed["shots"][0], beats[0], group, h3=True,
                                           ordered_beats=beats, contract_version="h3-skill-direct-v1")
        self.assertTrue(any("对白" in e for e in old_errors))
        self.assertEqual(sample["raw_sha256"], __import__("hashlib").sha256(sample["raw"].encode()).hexdigest())

    @patch.object(prompts.LlmService, "author_group")
    def test_v1_retry_uses_frozen_system_and_single_call(self, chat):
        from backend.app.media_studio.services.workshop_direct_input import sha
        snapshot = self.snapshot()
        snapshot.update(version="h3-skill-direct-v1", system=SKILL_PATH.read_bytes().decode("utf8"))
        snapshot["system_sha256"] = sha(snapshot["system"])
        snapshot["input_sha256"] = contract.digest([snapshot["system"], snapshot["user"], []])
        chat.return_value = (complete_draft([body(dialogue=""), body(dialogue="", offset=8)]), {"ok": True})
        result = prompts.generate_group(self.plan, self.group, self.beats, contract_snapshot=snapshot)
        chat.assert_called_once()
        self.assertEqual(chat.call_args.args[0], snapshot["system"])
        self.assertEqual(result["a"]["contract_version"], "h3-skill-direct-v1")

    def test_real_director_v2_drafts_distinguish_missing_dialogue_from_solo_label(self):
        from backend.app.media_studio.services.workshop_h3_skill import split_complete_group_draft
        root = Path(__file__).parent / "fixtures/director_ep1_2026-09-26"
        beats = json.loads((root / "08_skill_direct_controlled_snapshot.json").read_text(encoding="utf8"))["beats"]
        group = {"id":"replay", "beat_ids":[b["id"] for b in beats], "timecode_mode":"cumulative",
                 "reference_slots":[{"token":"<Picture 1>"}], "contract_version":VERSION}
        for jid, valid in (("job-3ec1fad9a9b7", False), ("job-5d27b58865d7", True), ("job-3f9c325ed132", True)):
            with self.subTest(job=jid):
                evidence = json.loads((root / "10_v2_director_2026-09-27" / (jid + ".json")).read_text(encoding="utf8"))
                raw = evidence["raw"]
                parsed = split_complete_group_draft(raw, beats, group)
                group["common_prompt"] = parsed["common_prompt"]
                errors = [error for beat, text in zip(beats, parsed["shots"])
                          for error in contract.prompt_checks(text, beat, group, h3=True, ordered_beats=beats)]
                self.assertEqual(not errors, valid, errors)
                self.assertEqual(evidence["raw_sha256"], __import__("hashlib").sha256(raw.encode()).hexdigest())

    @patch.object(prompts.LlmService, "author_group")
    def test_v2_quote_tolerance_keeps_raw_and_generated_body_unchanged(self, chat):
        self.beats[0].update(speaker="阿宁", dialogue="‘回来’。")
        raw = complete_draft([body(dialogue="回来。"), body(dialogue="", offset=8)])
        chat.return_value = (raw, {"ok": True})
        audit = {}
        result = prompts.generate_group(self.plan, self.group, self.beats, contract_snapshot=self.snapshot(), audit=audit)
        self.assertEqual(audit["writing_history"][0]["raw"], raw)
        self.assertIn("<d>[中文] 回来。</d>", result["a"]["h3_prompt"])
        self.assertNotIn("‘回来’", result["a"]["h3_prompt"])
        chat.assert_called_once()

    @patch.object(prompts.LlmService, "author_group")
    def test_v2_missing_audio_rejects_once_and_retains_draft(self, chat):
        raw = complete_draft([body(dialogue=""), body(dialogue="", offset=8)])
        raw = raw.replace("声音设定：", "声音设定：\n人物参考音频 2。")
        chat.return_value = (raw, {"ok": True})
        audit = {}
        with self.assertRaisesRegex(ValueError, "未提供的参考音频"):
            prompts.generate_group(self.plan, self.group, self.beats, contract_snapshot=self.snapshot(), audit=audit)
        self.assertEqual(audit["writing_history"][0]["raw"], raw)
        chat.assert_called_once()

    def test_frozen_real_source_two_shot_fixture_is_isolated(self):
        import hashlib
        root = Path(__file__).parent / "fixtures/director_ep1_2026-09-26"
        frozen = json.loads((root / "08_skill_direct_controlled_snapshot.json").read_text(encoding="utf-8"))
        source = dict(frozen["source"])
        source_bytes = (root / source.pop("text_file")).read_bytes()
        self.assertEqual(hashlib.sha256(source_bytes).hexdigest(), source.pop("text_sha256"))
        source["text"] = source_bytes.decode("utf-8")
        group = {"id": "isolated-test", "beat_ids": [b["id"] for b in frozen["beats"]],
                 "timecode_mode": frozen["scope"]["timecode_mode"], "common_prompt": "",
                 "reference_slots": [{**frozen["reference"], "image_url": "https://example.com/test-only.png"}]}
        plan = {"aspect_ratio": "16:9", "groups": [group], "shot_prompts": {}}
        before = deepcopy(frozen)
        snapshot = build_input(plan, group, frozen["beats"], source)
        self.assertEqual(snapshot["beat_ids"], group["beat_ids"])
        self.assertEqual(len(snapshot["references"]), 1)
        self.assertEqual(snapshot["source"]["text"], source["text"])
        self.assertEqual(frozen, before)

    def test_cache_and_state_do_not_change_input(self):
        before = self.snapshot()
        self.group["common_prompt"] = "完全不同的旧声音及主体"
        self.beats[0].update(video_prompt_zh="缓存稿", status="failed", h3_prompt="另一个旧稿")
        self.plan["status"] = "changed"
        self.assertEqual(before, self.snapshot())

    def test_source_locks_materials_and_images_change_hash(self):
        before = self.snapshot()["input_sha256"]
        self.beats[0]["action"] += "，右手抬起"
        self.assertNotEqual(before, self.snapshot()["input_sha256"])
        before = self.snapshot()["input_sha256"]
        self.group["locked_common_lines"] = ["用户明确锁定的光线"]
        self.assertNotEqual(before, self.snapshot()["input_sha256"])
        before = self.snapshot()["input_sha256"]
        self.group["reference_slots"] = [{"token": "<Picture 1>", "name": "阿宁", "kind": "character", "image_url": "https://example.com/image?a=secret"}]
        result = self.snapshot()
        self.assertNotEqual(before, result["input_sha256"])
        self.assertNotIn("secret", str(result))

    def test_budget_and_conflict_fail_without_truncation(self):
        self.source["conflict"] = "版本冲突"
        with self.assertRaisesRegex(ValueError, "来源冲突"):
            self.snapshot()
        self.source.pop("conflict")
        self.source["text"] = "长" * 180001
        with self.assertRaisesRegex(ValueError, "未静默裁剪"):
            self.snapshot()

    @patch.object(prompts.LlmService, "author_group")
    def test_parse_failure_keeps_exact_raw_and_never_rewrites(self, chat):
        chat.return_value = ("不能解析的完整原稿\n", {"ok": True})
        audit = {}
        with self.assertRaisesRegex(ValueError, "不自动返修"):
            prompts.generate_group(self.plan, self.group, self.beats, contract_snapshot=self.snapshot(), audit=audit)
        chat.assert_called_once()
        self.assertEqual(audit["writing_history"][0]["raw"], chat.return_value[0])
        self.assertEqual(self.plan["shot_prompts"], {})

    @patch.object(prompts.LlmService, "author_group")
    def test_native_draft_no_timing_template_and_single_call(self, chat):
        raw = complete_draft([body(dialogue=""), body(dialogue="", offset=8)])
        # Native Skill permits untimed actions. Missing silent keywords are advisory.
        import re
        raw = re.sub(r"\([0-9.]+–[0-9.]+秒\)", "", raw)
        chat.return_value = (raw, {"ok": True})
        snapshot = self.snapshot()
        audit = {}
        result = prompts.generate_group(self.plan, self.group, self.beats, contract_snapshot=snapshot, audit=audit)
        chat.assert_called_once()
        self.assertEqual(chat.call_args.args[:2], (snapshot["system"], snapshot["user"]))
        self.assertEqual(result["a"]["contract_version"], VERSION)
        effective = {**self.group, "common_prompt": result["__common_prompt__"], "contract_version": VERSION}
        self.assertEqual(contract.prompt_checks(result["a"]["h3_prompt"], self.beats[0], effective, h3=True, ordered_beats=self.beats), [])
        before = deepcopy(effective)
        ensure_sound_settings([effective], self.beats)
        self.assertEqual(effective, before)

    @patch.object(prompts.LlmService, "author_group")
    def test_snapshot_tampering_never_calls_model(self, chat):
        snapshot = self.snapshot()
        snapshot["user"] += "changed"
        with self.assertRaisesRegex(ValueError, "冻结快照"):
            prompts.generate_group(self.plan, self.group, self.beats, contract_snapshot=snapshot)
        chat.assert_not_called()

    def test_unknown_contract_is_read_only(self):
        errors = contract.prompt_checks(body(dialogue=""), self.beats[0], self.group, h3=True, contract_version="future-version")
        self.assertIn("未知写稿合同版本，仅允许查看", errors)

    @patch.object(prompts.LlmService, "author_group")
    def test_three_shots_multiple_speakers_and_local_timecodes(self, chat):
        self.beats = [{"id": "a", "video_duration": 8, "speaker": "阿宁", "dialogue": "回来。"},
                      {"id": "b", "video_duration": 8, "speaker": "阿南", "dialogue": "好的。"},
                      {"id": "c", "video_duration": 8, "action": "默默起身"}]
        self.group.update(beat_ids=["a", "b", "c"], timecode_mode="local")
        raw = complete_draft([body(), body(name="阿南", number=2, dialogue="好的。"), body(dialogue="")], cumulative=False)
        chat.return_value = (raw, {"ok": True})
        result = prompts.generate_group(self.plan, self.group, self.beats, contract_snapshot=self.snapshot())
        self.assertEqual(set(result), {"a", "b", "c", "__common_prompt__"})
        chat.assert_called_once()

    def test_manual_edit_keeps_old_record_version_in_mixed_group(self):
        from backend.app.media_studio.services.workshop_service import WorkshopService
        self.group["contract_version"] = VERSION
        self.plan.update(revision=1, shot_prompts={"a": {"h3_prompt": "old-without-version"}})
        data = {"beats": self.beats, "prompt_authoring": {"director_plan": self.plan}}
        def mutate(project, episode, expected, operation):
            operation(data, self.plan, {})
        with patch.object(WorkshopService, "mutate", side_effect=mutate), patch.object(WorkshopService, "view", return_value={}), \
             patch.object(contract, "prompt_checks", return_value=[]) as check:
            WorkshopService.update("p", "e", {"expected_revision": 1, "beat_id": "a", "h3_prompt": "edited old"})
        self.assertEqual(check.call_args.kwargs["contract_version"], "h3-complete-group-v1")
        self.assertEqual(self.plan["shot_prompts"]["a"]["contract_version"], "h3-complete-group-v1")

    def test_manual_edit_preserves_direct_body_and_evidence(self):
        from backend.app.media_studio.services.workshop_service import WorkshopService
        self.group.update(contract_version=VERSION, common_prompt="subject_definitions:\n<Subject 1> 是阿宁。\n声音设定：\n无对白。")
        self.plan.update(revision=1, shot_prompts={"a": {"h3_prompt": "old", "contract_version": VERSION}})
        text = body(dialogue="").replace("(0–8秒)", "")
        data = {"beats": self.beats, "prompt_authoring": {"director_plan": self.plan}}
        def mutate(project, episode, expected, operation):
            operation(data, self.plan, {})
        with patch.object(WorkshopService, "mutate", side_effect=mutate), patch.object(WorkshopService, "view", return_value={}):
            WorkshopService.update("p", "e", {"expected_revision": 1, "beat_id": "a", "h3_prompt": text})
        record = self.plan["shot_prompts"]["a"]
        self.assertEqual(record["h3_prompt"], text)
        self.assertEqual(record["origin"], "manual")
        self.assertTrue(contract.content_matches(record, self.group, self.plan))

    def test_revision_freezes_neighbors_and_shared_text_in_input(self):
        self.plan["shot_prompts"] = {"a": {"h3_prompt": "镜头一正文"}, "b": {"h3_prompt": "镜头二正文"}}
        result = build_input(self.plan, self.group, self.beats, self.source, revision_beat_id="a", revision_note="抬手更慢")
        for text in ("旧稿污染", "镜头一正文", "镜头二正文", "抬手更慢"):
            self.assertIn(text, result["user"])

    def test_satisfied_draft_through_execution_timeline_and_graph(self):
        from backend.app.media_studio.services.workshop_h3_skill import split_complete_group_draft
        from backend.app.media_studio.services.h3_prompt_builder import H3PromptBuilder
        from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient
        import re
        raw = (Path(__file__).parent / "fixtures/director_ep1_2026-09-26/01_satisfied_prompt.txt").read_text(encoding="utf-8")
        dialogues = re.findall(r"<d>\s*\[中文\]\s*(.*?)</d>", raw)
        for beat, spoken in zip(self.beats, dialogues):
            beat.update(speaker="沈砚", dialogue=spoken, scene="图书馆")
        self.group.update(reference_slots=[{"token": "<Picture 1>", "name": "沈砚", "image_url": "https://example.com/reference.png"}], contract_version=VERSION)
        parsed = split_complete_group_draft(raw, self.beats, self.group)
        self.group["common_prompt"] = parsed["common_prompt"]
        self.plan.update(schema_version=7, max_shots_per_group=2)
        for beat, text in zip(self.beats, parsed["shots"]):
            self.plan["shot_prompts"][beat["id"]] = {"h3_prompt": text, "contract_version": VERSION,
                "fingerprint": contract.prompt_fingerprint(beat, self.group, self.plan),
                "content_digest": contract.digest([text, parsed["common_prompt"], "source", VERSION])}
        detail = {"beats": self.beats, "prompt_authoring": {"director_plan": self.plan}}
        before = deepcopy(detail)
        shots, _ = contract.execution_shots(detail)
        for shot, text in zip(shots, parsed["shots"]):
            compiled = H3PromptBuilder.compile_director_segment_prompt(parsed["common_prompt"], shot["h3_prompt"])
            self.assertEqual(compiled["segment_prompt"], text)
            shot.update(prompt=compiled["segment_prompt"], uploaded_refs=[{"imageFile": "test-reference.png"}])
        opts = {"aspect_ratio": "16:9", "megapixels": 0.4, "global_prompt": parsed["common_prompt"], "seed": 888, "continuity_enabled": True, "weight_profile": "pruned"}
        timeline = ComfyVideoClient.build_timeline(shots, "r2v", options=opts)
        graph = ComfyVideoClient.build_workflow(timeline, "r2v", "test-only", options=opts)
        director = next(n["inputs"] for n in graph.values() if n["class_type"] == "MiniMaxH3Director")
        submitted = json.loads(director["timeline_data"])
        self.assertEqual([s["prompt"] for s in submitted["segments"]], parsed["shots"])
        self.assertEqual(submitted["global"]["prompt"], parsed["common_prompt"])
        self.assertEqual([s["frameCount"] for s in submitted["segments"]], [192, 192])
        for original, projected in zip(re.split(r"【Shot \d+[^】]*】", raw)[1:], parsed["shots"]):
            self.assertEqual(original.strip(), projected.split("\n", 2)[2].strip())
        self.assertEqual(detail, before)

    def test_timing_bounds_and_wrong_speaker_remain_hard_errors(self):
        self.beats[0].update(dialogue="回来。", speaker="阿宁")
        self.group.update(common_prompt="<Subject 1> 是阿宁\n声音设定：\n阿宁 (S1)：自然人声。", contract_version=VERSION)
        for text in (body().replace("(1–6秒)", "(1–9秒)"), body().replace("阿宁 (S1)", "阿宁 (S2)")):
            self.assertTrue(contract.prompt_checks(text, self.beats[0], self.group, h3=True, ordered_beats=self.beats))

    def test_named_solo_voice_does_not_require_repeated_number_but_conflicts_fail(self):
        self.beats[0].update(dialogue="回来。", speaker="阿宁")
        self.group.update(common_prompt="<Subject 1> 是阿宁\n声音设定：\n阿宁 (S1)：自然人声。", contract_version=VERSION)
        named = body().replace("阿宁 (S1)", "阿宁")
        self.assertEqual(contract.prompt_checks(named, self.beats[0], self.group, h3=True, ordered_beats=self.beats), [])
        for changed in (named.replace("阿宁", "陌生人"), body().replace("(S1)", "(S2)")):
            self.assertTrue(contract.prompt_checks(changed, self.beats[0], self.group, h3=True, ordered_beats=self.beats))
        self.group["common_prompt"] += "\n阿南 (S2)：另一人的声音。"
        self.assertTrue(contract.prompt_checks(named, self.beats[0], self.group, h3=True, ordered_beats=self.beats))

    @patch("backend.app.media_studio.services.workshop_h3_skill.writing_author")
    @patch("backend.app.media_studio.services.llm_service.OpenAICompatibleClient")
    def test_transport_preserves_text_and_reports_actual_sent_hashes(self, client, author):
        from backend.app.media_studio.services.llm_service import LlmService
        author.return_value = {"profile_id": "test", "base_url": "https://example.com/v1", "api_key": "test-secret", "model": "test", "reasoning_effort": "low", "supports_vision": True}
        raw = "\n  原稿正文\r\n"
        client.return_value.chat_completion.return_value = raw
        snapshot = self.snapshot()
        result, meta = LlmService.author_group(snapshot["system"], snapshot["user"], ["https://example.com/reference.png"])
        self.assertEqual(result, raw)
        self.assertEqual(meta["sent_system_sha256"], snapshot["system_sha256"])
        self.assertEqual(meta["sent_user_sha256"], snapshot["user_sha256"])
        self.assertNotIn("test-secret", str(meta))
        sent = client.return_value.chat_completion.call_args.args[0]
        self.assertEqual(sent[1]["content"][0]["text"], snapshot["user"])


if __name__ == "__main__":
    unittest.main()
