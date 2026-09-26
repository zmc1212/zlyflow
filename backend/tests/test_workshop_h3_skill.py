import json
import re
import unittest
from copy import deepcopy
from unittest.mock import patch

from backend.app.media_studio.services import workshop_contract as contract
from backend.app.media_studio.services import workshop_group_prompts as prompts
from backend.app.media_studio.services import workshop_h3_skill as skill
from backend.app.media_studio.services.workshop_references import resolve_state


def body(name="阿宁", number=1, dialogue="回来。", start=1, end=6, duration=8, shot_number=1, offset=0.0):
    action = (f"({start + offset:g}–{end + offset:g}秒) {name} (S{number}) 看向门口，压低声音、语速平稳地说：<d>[中文] {dialogue}</d>\n"
              f"({end + offset:g}–{duration + offset:g}秒) 他闭口停住，目光仍落在门口。") if dialogue else f"({0 + offset:g}–{8 + offset:g}秒) 人物缓缓抬头，最后停住。"
    if dialogue and start > 0:
        action = f"({offset:g}–{start + offset:g}秒) 他安静坐在案前，目光转向门口。\n" + action
    return (f"detailed_description:\n[Shot {shot_number}] 00:00.00–00:{duration:05.2f}\n"
            f"【主体】{name} 坐在案前。\n【动作】{action}\n【镜头】固定中景，暖光稳定。\n"
            "【音效】呼吸声与环境底噪。\n【约束】人物、服装、物件与光线一致，口型同步，不提前起身。")


def complete_draft(shots, name="阿宁", number=1, dialogue="回来。", duration=8, common="", durations=None, cumulative=True):
    """Wrap shot bodies in the skill's complete draft container.

    Real groups (and the satisfied write) use cumulative intra-group timecodes,
    so each header is placed at its confirmed group offset here too.
    """
    header = (common or (
        "subject_definitions（主体定义）:\n"
        f"<Subject 1> 是 {name}。\n声音设定：\n{name} (S{number})：自然人声，不提供参考音频。\n"
        + ("阿南 (S2)：低沉男声，不提供参考音频。\n" if any("阿南 (S2)" in shot for shot in shots) and name != "阿南" else "")
    ))
    durations = durations or [duration] * len(shots)
    renumbered = []
    offset = 0.0
    def tc(seconds):
        minutes = int(seconds // 60)
        return f"{minutes:02}:{seconds - minutes * 60:05.2f}"

    for index, (shot, secs) in enumerate(zip(shots, durations), 1):
        start_tc = offset if cumulative else 0.0
        shot = re.sub(r"\[Shot \d+\] \d{2}:\d{2}(?:\.\d+)?–\d{2}:\d{2}(?:\.\d+)?",
                      f"[Shot {index}] {tc(start_tc)}–{tc(start_tc + secs)}", shot)
        offset += secs
        renumbered.append(shot)
    return header + "\ndetailed_description:\n" + "\n".join(renumbered)


class H3SkillTests(unittest.TestCase):
    def setUp(self):
        self.beats = [{"id": "a", "scene": "书房", "speaker": "阿宁", "dialogue": "阿宁：回来。", "video_duration": 8},
                      {"id": "b", "scene": "书房", "speaker": "阿南", "dialogue": "阿南：好的。", "video_duration": 8}]
        self.plan = contract.new_plan(self.beats, "minimax-h3-director-accel-t2v", {"revision": 1, "fingerprint": "src"})
        self.group = self.plan["groups"][0]

    def check(self, text, beat=None):
        return contract.prompt_checks(text, beat or self.beats[0], self.group, h3=True)

    def test_complete_skill_is_loaded_not_an_excerpt(self):
        system = skill.writing_system()
        self.assertIn(skill.SKILL_PATH.read_text(encoding="utf-8").strip(), system)
        self.assertIn("完整模板", system)
        self.assertIn("最后一句对白结束后至少留 0.5 秒", system)
        self.assertIn("示例中的餐厅", system)

    def test_voice_projection_is_read_only_idempotent_and_shared_across_groups(self):
        original = {"beats": self.beats, "prompt_authoring": {"director_plan": self.plan}}
        saved = deepcopy(original)
        resolved = resolve_state(original, [])
        self.assertEqual(original, saved)
        self.assertEqual(resolve_state(resolved, []), resolved)
        other = {"id": "other", "beat_ids": ["b"], "common_prompt": "新场景"}
        skill.ensure_sound_settings([self.group, other], self.beats)
        self.assertIn("阿南 (S2)", other["common_prompt"])
        explicit = deepcopy(other)
        skill.ensure_sound_settings([other], self.beats)
        self.assertEqual(explicit, other)

    def test_valid_dialogue_and_silent_shots(self):
        self.assertEqual(self.check(body()), [])
        self.assertEqual(self.check(body(dialogue=""), {**self.beats[0], "dialogue": ""}), [])

    def test_skill_subject_voice_syntax_is_accepted(self):
        self.group["common_prompt"] = "<Subject 2> 是 <Picture 1> 中的阿宁。\n声音设定：\n<Subject 2> 的说话人标记为 (S1)，全片保持自然人声，不提供参考音频。"
        text = body().replace("阿宁 (S1)", "<Subject 2> (S1)")
        self.assertEqual(self.check(text), [])

    def test_manual_save_and_candidate_adoption_cannot_bypass_tail_check(self):
        from backend.app.media_studio.services.workshop_service import WorkshopService as service
        detail = {"beats": self.beats, "prompt_authoring": {"director_plan": self.plan}}
        invalid = body(end=8)
        saved = deepcopy(detail)
        def mutate(_project, _episode, _revision, operation):
            operation(deepcopy(detail), deepcopy(self.plan), {})
        with patch.object(service, "mutate", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "安全尾部"):
                service.update("p", "e", {"expected_revision": 1, "beat_id": "a", "h3_prompt": invalid})
            candidates = {b["id"]: {"h3_prompt": invalid if b["id"] == "a" else body("阿南", 2, "好的。"),
                          "fingerprint": contract.prompt_fingerprint(b, self.group, self.plan)} for b in self.beats}
            payload = {"episode_id": "e", "source": {"fingerprint": "src"}, "base_plan": self.plan, "beats": self.beats,
                       "prompt_scope": "group", "candidates": candidates, "applied_ids": []}
            with patch("backend.app.media_studio.services.workshop_service.query_one", return_value={"status": "completed", "job_type": "workshop_prompt", "payload_json": json.dumps(payload)}), \
                 patch.object(service, "source", return_value={"fingerprint": "src"}):
                with self.assertRaisesRegex(ValueError, "安全尾部"):
                    service.job_action("p", "e", "j", {"action": "apply", "expected_revision": 1})
        self.assertEqual(detail, saved)

    def test_tail_boundary_missing_times_overlap_and_wrong_owner(self):
        self.assertEqual(self.check(body(end=7.5)), [])
        for text, word in [(body(end=7.51), "安全尾部"), (body(end=8.2), "越界"),
                           (body(start=7, end=6), "越界"), (body().replace("(1–6秒)", "").replace("(0–1秒)", ""), "独立起止"),
                           (body(number=2), "稳定归属"), (body().replace("<d>[中文]", "<d>[English]"), "标签"),
                           (body().replace("【约束】", ""), "【约束】")]:
            with self.subTest(word=word):
                self.assertTrue(any(word in e for e in self.check(text)))

    def test_two_speakers_dialogue_order_duplicate_and_overlap(self):
        beat = {**self.beats[0], "dialogue": "阿宁：回来。\n阿南：好的。"}
        text = body(end=3).replace("(3–8秒)", "(2–6秒) 阿南 (S2) 轻声说：<d>[中文] 好的。</d>\n(6–8秒)")
        self.assertTrue(any("重叠" in e for e in self.check(text, beat)))
        self.assertEqual(self.check(text.replace("(2–6秒)", "(3–6秒)"), beat), [])
        self.assertTrue(any("恰好出现一次" in e for e in self.check(body().replace("回来。", "回来。回来。"))))

    def test_group_and_revision_send_same_contract_with_images(self):
        self.group["timecode_mode"] = "cumulative"
        self.group["reference_slots"] = [{"token": "<Picture 1>", "image_url": "https://example.com/a.png"}]
        self.plan["shot_prompts"] = {"a": {"h3_prompt": body()}, "b": {"h3_prompt": body("阿南", 2, "好的。", offset=8)}}
        raw = complete_draft([body(), body("阿南", 2, "好的。", offset=8)], common=self.group["common_prompt"])
        with patch.object(prompts.LlmService, "author_group", return_value=(raw, {"ok": True})) as chat:
            result = prompts.generate_group(self.plan, self.group, self.beats)
            self.assertEqual([key for key in result if key != "__common_prompt__"], ["a", "b"])
            system = chat.call_args.args[0]
            self.assertIn(skill.SKILL_PATH.read_text(encoding="utf-8").strip(), system)
            self.assertNotIn("你是 MiniMax H3 Full-Reference 六段式", system)
            self.assertNotIn("主体定义", result["a"]["h3_prompt"])
            chat.return_value = (raw, {"ok": True})
            revised = prompts.generate_group(self.plan, self.group, self.beats, revision_beat_id="a", revision_note="克制")
            self.assertEqual([key for key in revised if key != "__common_prompt__"], ["a"])
            self.assertEqual(chat.call_args.args[0], system)
            self.assertIn("克制", chat.call_args.args[1])

    def test_repair_is_bounded_and_no_invalid_group_is_published(self):
        self.group["timecode_mode"] = "cumulative"
        raw = complete_draft([body(end=8), body("阿南", 2, "好的。", offset=8)])
        with patch.object(prompts.LlmService, "author_group", return_value=(raw, {"ok": True})) as chat:
            with self.assertRaisesRegex(ValueError, "安全尾部"):
                prompts.generate_group(self.plan, self.group, self.beats)
            self.assertEqual(chat.call_count, 2)  # identical invalid response stops early
            self.assertIn("待修复原稿", chat.call_args.args[1])

    def test_submission_checks_old_saved_body_without_rewriting_it(self):
        old = "[Shot 1] 00:00.00–00:08.00 阿宁说：回来。"
        for b in self.beats:
            self.plan["shot_prompts"][b["id"]] = {"h3_prompt": old, "fingerprint": contract.prompt_fingerprint(b, self.group, self.plan)}
        detail = {"beats": self.beats, "prompt_authoring": {"director_plan": self.plan}}
        saved = deepcopy(detail)
        with self.assertRaisesRegex(ValueError, "H3 正文"):
            contract.execution_shots(detail)
        self.assertEqual(saved, detail)
        self.assertEqual(contract.project_prompts(self.beats, self.plan)[0]["h3_prompt_reference_state"], "stale")


    def test_cumulative_timecode_generates_shot_numbers_and_offset(self):
        self.group["timecode_mode"] = "cumulative"
        n1, s1, e1 = contract.shot_header(self.beats[0], self.group, self.beats)
        n2, s2, e2 = contract.shot_header(self.beats[1], self.group, self.beats)
        self.assertEqual((n1, s1, e1), (1, 0.0, 8.0))
        self.assertEqual((n2, s2, e2), (2, 8.0, 16.0))
        system = skill.writing_system(timecode_mode="cumulative")
        self.assertIn("组内时间码累计", system)
        self.assertIn("[Shot 2] 00:08.00–00:16.00", system)

    def test_split_complete_draft_maps_storage_headers_per_timecode_mode(self):
        for mode, expect in [("cumulative", ["[Shot 1] 00:00.00–00:08.00", "[Shot 2] 00:08.00–00:16.00"]),
                             ("per_shot", ["[Shot 1] 00:00.00–00:08.00", "[Shot 1] 00:00.00–00:08.00"])]:
            cumulative = mode == "cumulative"
            draft = complete_draft([body(dialogue=""), body(dialogue="", offset=8 if cumulative else 0)],
                                   cumulative=cumulative)
            self.group["timecode_mode"] = mode
            parsed = skill.split_complete_group_draft(draft, self.beats, group=self.group)
            for index, (body_text, header) in enumerate(zip(parsed["shots"], expect)):
                self.assertTrue(body_text.startswith("detailed_description:\n" + header), (mode, index, body_text[:60]))
                self.assertNotIn("[Shot 2]", body_text if mode == "per_shot" else "")
            self.assertIn("subject_definitions", parsed["common_prompt"])
            self.assertIn("声音设定", parsed["common_prompt"])

    def test_split_complete_draft_rejects_wrong_authored_timeline(self):
        self.group["timecode_mode"] = "cumulative"
        draft = complete_draft([body(dialogue=""), body(dialogue="")]).replace(
            "[Shot 2] 00:08.00–00:16.00", "[Shot 2] 00:08.00–00:20.00")
        with self.assertRaisesRegex(ValueError, "确认时长"):
            skill.split_complete_group_draft(draft, self.beats, group=self.group)

    def test_split_complete_draft_rejects_skill_style_header_wrong_timeline(self):
        self.group["timecode_mode"] = "cumulative"
        draft = ("subject_definitions（主体定义）:\n<Subject 1> 是 阿宁。\n声音设定：\n阿宁 (S1)：自然人声。\n"
                 "detailed_description:\n【Shot 1｜0–8秒｜中景】\n【主体】阿宁\n【动作】(0–8秒) 安静坐住\n【镜头】固定\n【音效】呼吸\n【约束】一致\n"
                 "【Shot 2｜0–8秒｜近景】\n【主体】阿宁\n【动作】(0–8秒) 坐住\n【镜头】固定\n【音效】呼吸\n【约束】一致\n")
        with self.assertRaisesRegex(ValueError, "确认时长"):
            skill.split_complete_group_draft(draft, self.beats, group=self.group)

    def test_per_shot_timecode_is_default(self):
        self.assertEqual(contract.shot_header(self.beats[1], self.group, self.beats), (1, 0.0, 8.0))
        self.assertIn("每镜独立时间码", skill.writing_system())

    def test_dialogue_duration_check_rejects_long_line_in_short_window(self):
        long_line = "青山遮不住毕竟东流去这诗风不像宋人笔法"
        beat = {**self.beats[0], "dialogue": long_line}
        text = body(dialogue=long_line, start=2, end=6, duration=8)
        from backend.app.media_studio.services.workshop_review import review_group
        self.assertEqual(self.check(text, beat), [])
        self.assertTrue(any(i["code"] == "speech_rate_risk" for i in review_group([beat], [text], self.group)["issues"]))

    def test_slow_delivery_uses_three_chars_per_second(self):
        line = "青山遮不住毕竟东流去这诗风不像宋人笔法"
        beat = {**self.beats[0], "dialogue": line}
        # normal delivery: no slow marker, 19 chars at 4/s needs 4.75s, 5s passes
        ok = body(dialogue=line, start=1, end=6, duration=8).replace("压低声音、语速平稳地说", "声音平稳地说")
        self.assertEqual(self.check(ok, beat), [])
        # slow delivery at 3/s needs 6.33s, 5s must fail
        slow = ok.replace("声音平稳地说", "声音压低、一字一顿地说")
        from backend.app.media_studio.services.workshop_review import review_group
        self.assertEqual(self.check(slow, beat), [])
        self.assertTrue(any("每秒 3" in i["suggestion"] for i in review_group([beat], [slow], self.group)["issues"]))

    def test_prop_name_semantic_conflict_flagged(self):
        from backend.app.media_studio.services.workshop_references import _prop_name_conflicts
        self.assertIn("语义可能不符", _prop_name_conflicts({"props": ["笔"]}, {"name": "毛笔"}))
        self.assertIsNone(_prop_name_conflicts({"props": ["毛笔"]}, {"name": "毛笔"}))
        self.assertIsNone(_prop_name_conflicts({"props": ["笔"]}, {"name": "笔"}))


if __name__ == "__main__":
    unittest.main()
