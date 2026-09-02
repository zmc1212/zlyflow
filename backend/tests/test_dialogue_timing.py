from __future__ import annotations

import unittest

from backend.app.dialogue_timing import (
    assign_missing_script_dialogue,
    enforce_shot_dialogue_timing,
    is_dialogue_truncated,
    looks_truncated_dialogue,
    replace_dialogue_in_prompt,
    count_script_dialogue_lines,
    dialogue_timing_warning,
    extract_script_dialogue_entries,
    extract_script_dialogue_lines,
    estimate_dialogue_duration_sec,
    estimate_shot_duration_sec,
    script_dialogue_coverage_low,
)
from backend.app.director_agents import (
    _apply_shot_timing_polish,
    _recipe_shots_timing_payload,
    _storyboard_dialogue_coverage_low,
)


class DialogueTimingTests(unittest.TestCase):
    SAMPLE_SCRIPT = """【场次1】
地点：云海仙宗藏经阁外
人物：主角（李元婴）、白衣女子（灵儿）、其他同门
动作：李元婴从藏经阁出来，手里拿着一块散发着微光的灵石，脸上兴奋不已。其他同门看到后，眼神中充满贪婪。
对白：
李元婴：（自言自语）这灵石品质极高，不知能炼制多少法宝。
同门甲：（嫉妒地）李元婴，那灵石从哪里来的？
李元婴：（不耐烦）藏经阁后山，我不过是运气好罢了。"""

    def test_extract_script_dialogue_lines_from_structured_script(self) -> None:
        lines = extract_script_dialogue_lines(self.SAMPLE_SCRIPT)
        self.assertEqual(len(lines), 3)
        self.assertIn("这灵石品质极高", lines[0])
        self.assertIn("那灵石从哪里来的", lines[1])
        self.assertIn("藏经阁后山", lines[2])

    def test_script_dialogue_coverage_low_when_shots_miss_lines(self) -> None:
        self.assertTrue(script_dialogue_coverage_low(self.SAMPLE_SCRIPT, 0))
        self.assertTrue(script_dialogue_coverage_low(self.SAMPLE_SCRIPT, 2))
        self.assertFalse(script_dialogue_coverage_low(self.SAMPLE_SCRIPT, 3))

    def test_count_script_dialogue_lines(self) -> None:
        self.assertEqual(count_script_dialogue_lines(self.SAMPLE_SCRIPT), 3)
        self.assertEqual(count_script_dialogue_lines("雨夜侦探穿过暗巷。"), 0)

    def test_estimate_chinese_dialogue_duration(self) -> None:
        self.assertAlmostEqual(estimate_dialogue_duration_sec("一二三四五六七八九十"), 2.5, places=1)

    def test_dialogue_timing_warning_when_too_short(self) -> None:
        self.assertIsNone(dialogue_timing_warning("一二三四五六七八九十", 5))
        self.assertIn("建议时长", dialogue_timing_warning("一二三四五六七八九十", 2) or "")

    def test_estimate_shot_duration_includes_action_beats(self) -> None:
        self.assertGreaterEqual(estimate_shot_duration_sec("", action_beats=3), 6)


class ShotTimingPolishTests(unittest.TestCase):
    def test_apply_shot_timing_polish_updates_duration_and_note(self) -> None:
        recipe = {
            "scenes": [{
                "title": "场 1",
                "shots": [{
                    "shotNumber": 1,
                    "title": "分镜 1",
                    "description": "她说话",
                    "promptText": "Old prompt",
                    "dialogue": "一二三四五六七八九十",
                    "durationSec": 5,
                }],
            }],
        }
        patch = {
            "scenes": [{
                "shots": [{
                    "shotNumber": 1,
                    "durationSec": 8,
                    "dialogue": "一二三四五六七八",
                    "promptText": "At 00:01.000 she speaks <d>[Chinese] 一二三四五六七八</d>",
                    "timingNote": "对白 8 字，动作 2 拍，时长改为 8s",
                }],
            }],
        }
        _apply_shot_timing_polish(recipe, patch)
        shot = recipe["scenes"][0]["shots"][0]
        self.assertEqual(shot["durationSec"], 8)
        self.assertEqual(shot["dialogue"], "一二三四五六七八九十")
        self.assertIn("一二三四五六七八九十", shot["promptText"])
        self.assertIn("At 00:01.000", shot["promptText"])
        self.assertIn("对白 8 字", shot["timingNote"])

    def test_recipe_shots_timing_payload_preserves_bindings(self) -> None:
        recipe = {
            "scenes": [{
                "title": "场 1",
                "shots": [{
                    "shotNumber": 1,
                    "title": "分镜 1",
                    "description": "描述",
                    "promptText": "Prompt",
                    "dialogue": "你好",
                    "characterBindings": [{"characterId": "c1", "lookId": "look-default"}],
                    "locationId": "loc-1",
                    "propIds": ["p1"],
                    "durationSec": 5,
                }],
            }],
        }
        payload = _recipe_shots_timing_payload(recipe)
        shot = payload["scenes"][0]["shots"][0]
        self.assertEqual(shot["characterBindings"], [{"characterId": "c1", "lookId": "look-default"}])
        self.assertEqual(shot["locationId"], "loc-1")
        self.assertEqual(shot["propIds"], ["p1"])


class StoryboardDialogueAssignmentTests(unittest.TestCase):
    SAMPLE_SCRIPT = DialogueTimingTests.SAMPLE_SCRIPT

    def test_storyboard_dialogue_coverage_low_on_silent_shots(self) -> None:
        recipe = {
            "script": {"fullStory": self.SAMPLE_SCRIPT},
            "scenes": [{
                "shots": [
                    {"shotNumber": 1, "title": "李元婴走出", "description": "李元婴从藏经阁走出", "characterNames": ["李元婴"], "dialogue": ""},
                    {"shotNumber": 2, "title": "灵石特写", "description": "灵石特写", "dialogue": ""},
                    {"shotNumber": 3, "title": "同门嫉妒", "description": "同门贪婪注视", "dialogue": ""},
                ],
            }],
        }
        self.assertTrue(_storyboard_dialogue_coverage_low(recipe, self.SAMPLE_SCRIPT))
        assigned = assign_missing_script_dialogue(recipe, self.SAMPLE_SCRIPT)
        self.assertEqual(assigned, 3)
        shots = recipe["scenes"][0]["shots"]
        self.assertIn("这灵石品质极高", shots[0]["dialogue"])
        self.assertEqual(shots[0]["speakerName"], "李元婴")
        self.assertIn("那灵石从哪里来的", shots[2]["dialogue"])
        self.assertFalse(_storyboard_dialogue_coverage_low(recipe, self.SAMPLE_SCRIPT))

    def test_extract_script_dialogue_entries_parses_delivery(self) -> None:
        entries = extract_script_dialogue_entries(self.SAMPLE_SCRIPT)
        self.assertEqual(entries[0]["delivery"], "自言自语")
        self.assertEqual(entries[0]["speaker"], "李元婴")

    def test_enforce_shot_dialogue_timing_restores_truncated_prompt(self) -> None:
        full_line = "报警了，损失太大了，得赶紧处理。"
        shot = {
            "dialogue": full_line,
            "durationSec": 4,
            "promptText": (
                "[Shot 4] Close-up of an insulated box. At 00:03.000, operator whispers. "
                f"The delivery person says: <d>[Chinese] 报警了，损失...</d>"
            ),
        }
        self.assertTrue(looks_truncated_dialogue("报警了，损失..."))
        self.assertTrue(is_dialogue_truncated("报警了，损失...", full_line))
        enforce_shot_dialogue_timing(shot)
        self.assertEqual(shot["dialogue"], full_line)
        self.assertIn(full_line, shot["promptText"])
        self.assertNotIn("损失...", shot["promptText"])
        self.assertGreaterEqual(shot["durationSec"], 4)

    def test_replace_dialogue_in_prompt_updates_says_tag(self) -> None:
        prompt = "At 00:03.000, he says: <d>[Chinese] 报警了，损失...</d>"
        full = "报警了，损失太大了，得赶紧处理。"
        updated = replace_dialogue_in_prompt(prompt, full)
        self.assertIn(full, updated)
        self.assertNotIn("损失...", updated)


if __name__ == "__main__":
    unittest.main()
