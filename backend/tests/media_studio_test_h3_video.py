from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import unittest
from unittest.mock import Mock, patch

import websocket

from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient
from backend.app.media_studio.services.episode_image_prompts import beat_reference_urls, beat_render_prompt
from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
from backend.app.media_studio.services.h3_prompt_builder import H3PromptBuilder
from backend.app.media_studio.services.project_detail_service import ProjectDetailService


def rich_prompt(dialogue: str = "你好。") -> str:
    detail = " ".join(
        [
            "The camera holds a stable medium composition while natural lighting defines the room, "
            "the subject performs a precise visible action, and synchronized sound follows every contact."
        ] * 24
    )
    return (
        "subject_definitions:\n<Subject 1> is the protagonist anchored by <Picture 1>. "
        "<Subject 2> is the environment anchored by <Picture 2>.\n"
        "summary:\n[reference generation + audio reference] An eight-second scene.\n"
        "retention_analysis:\n<Subject 1>: fully_preserved. <Subject 2>: fully_preserved.\n"
        f"detailed_description:\n[Shot 1] {detail} (S1) says <d>[Chinese] {dialogue}</d>. "
        "The shot holds long enough for complete unhurried dialogue and a natural pause.\n"
        "overall_soundscape:\nQuiet room sound and synchronized movement.\n"
        "non_diegetic_music:\nRestrained piano at a slow tempo with a soft ending."
    )


class H3PromptTests(unittest.TestCase):
    def test_valid_prompt_contract(self):
        shot = {"sequence": 1, "speaker": "沈砚", "dialogue": "你好。"}
        self.assertEqual([], H3PromptBuilder.validate_prompts([shot], [rich_prompt()]))

    def test_rejects_missing_dialogue_and_wrong_order(self):
        prompt = rich_prompt().replace("你好。", "再见。")
        prompt = prompt.replace("summary:", "z_summary:")
        errors = H3PromptBuilder.validate_prompts(
            [{"sequence": 1, "speaker": "沈砚", "dialogue": "你好。"}], [prompt]
        )
        self.assertGreaterEqual(len(errors), 2)

    def test_multi_character_prompt_requires_every_picture_and_subject(self):
        shot = {
            "sequence": 4,
            "character_references": [{"character_name": "母亲"}, {"character_name": "沈砚"}],
        }
        prompt = rich_prompt().replace(
            "<Subject 2> is the environment anchored by <Picture 2>.",
            "<Subject 2> is 沈砚 anchored by <Picture 2>. "
            "<Subject 3> is the environment anchored by <Picture 3>.",
        )
        self.assertEqual([], H3PromptBuilder.validate_prompts([shot], [prompt]))
        errors = H3PromptBuilder.validate_prompts([shot], [prompt.replace("<Picture 3>", "scene reference")])
        self.assertTrue(any("<Picture 3>" in error for error in errors))

    @staticmethod
    def _llm_response(beat_id: str, prompt: str, *, ok: bool = True):
        content = {"beat_id": beat_id, "prompt": prompt}
        response = Mock()
        response.ok = ok
        response.status_code = 200 if ok else 500
        response.text = "server error" if not ok else "response body"
        response.json.return_value = {
            "choices": [{"message": {"content": __import__("json").dumps(content, ensure_ascii=False)}}]
        }
        return response

    @patch.object(H3PromptBuilder, "_runtime_config", return_value=("http://llm", "model", "key"))
    @patch("backend.app.media_studio.services.h3_prompt_builder.requests.post")
    def test_builds_each_beat_independently_and_keeps_attempt_diagnostics(self, post, _config):
        shots = [
            {"beat_id": "beat-1", "sequence": 1, "speaker": "沈砚", "dialogue": "第一句。"},
            {"beat_id": "beat-2", "sequence": 2, "speaker": "沈砚", "dialogue": "第二句。"},
        ]
        post.side_effect = [
            self._llm_response("beat-1", "too short"),
            self._llm_response("beat-1", rich_prompt("第一句。")),
            self._llm_response("beat-2", rich_prompt("第二句。")),
        ]
        attempts = []

        prompts = H3PromptBuilder.build_prompts(shots, on_attempt=attempts.append)

        self.assertEqual(3, post.call_count)
        self.assertEqual(["failed", "passed", "passed"], [item["status"] for item in attempts])
        self.assertEqual(["beat-1", "beat-1", "beat-2"], [item["beat_id"] for item in attempts])
        self.assertIn("第一句。", prompts[0])
        self.assertIn("第二句。", prompts[1])
        self.assertTrue(all(item["raw_response"] for item in attempts))
        first_request = post.call_args_list[0].kwargs["json"]["messages"][1]["content"]
        second_beat_request = post.call_args_list[2].kwargs["json"]["messages"][1]["content"]
        self.assertIn('"沈砚": "S1"', first_request)
        self.assertIn('"沈砚": "S1"', second_beat_request)

    @patch.object(H3PromptBuilder, "_runtime_config", return_value=("http://llm", "model", "key"))
    @patch("backend.app.media_studio.services.h3_prompt_builder.requests.post")
    def test_stops_before_later_beats_after_two_failures(self, post, _config):
        shots = [
            {"beat_id": "beat-1", "sequence": 1},
            {"beat_id": "beat-2", "sequence": 2},
        ]
        post.side_effect = [
            self._llm_response("beat-1", "bad one"),
            self._llm_response("beat-1", "bad two"),
        ]
        attempts = []

        with self.assertRaisesRegex(ValueError, "Beat 1"):
            H3PromptBuilder.build_prompts(shots, on_attempt=attempts.append)

        self.assertEqual(2, post.call_count)
        self.assertEqual(["beat-1", "beat-1"], [item["beat_id"] for item in attempts])

    def test_normalizes_compact_sections_and_preserves_mandatory_literals(self):
        shot = {
            "beat_id": "beat-1",
            "sequence": 1,
            "speaker": "沈砚",
            "dialogue": "这里是什么地方？",
        }
        compact = rich_prompt("这里是什么地方？").replace("\n", "")

        normalized = H3PromptBuilder._normalize_prompt(shot, compact, {"沈砚": "S1"})

        self.assertIn("\nsummary:\n", normalized)
        self.assertIn("<Subject 1>", normalized)
        self.assertIn("<Picture 1>", normalized)
        self.assertIn("<d>[Chinese] 这里是什么地方？</d>", normalized)

    def test_script_style_dialogue_strips_name_prefix_from_spoken_tag(self):
        shot = {
            "sequence": 1,
            "speaker": "吴耐",
            "dialogue": "沙丽丽：“该不会想让我那啥吧。”",
            "character_references": [
                {"character_id": "c-wu", "character_name": "吴耐"},
                {"character_id": "c-sha", "character_name": "沙丽丽"},
            ],
        }
        turns = H3PromptBuilder._dialogue_turns(shot)
        self.assertEqual(turns[0]["speaker"], "沙丽丽")
        self.assertEqual(turns[0]["text"], "该不会想让我那啥吧。")
        speaker_map = H3PromptBuilder._speaker_map([shot])
        contract = H3PromptBuilder._required_contract(shot, speaker_map)
        self.assertIn("<d>[Chinese] 该不会想让我那啥吧。</d>", contract)
        self.assertNotIn("沙丽丽：", contract)
        self.assertIn("(S1) <Subject 2> 沙丽丽 says", contract)
        dirty = rich_prompt("沙丽丽：“该不会想让我那啥吧。”").replace("(S1) says", "(S1) 沙丽丽 says")
        cleaned = H3PromptBuilder._normalize_prompt(shot, dirty, speaker_map)
        self.assertIn("<d>[Chinese] 该不会想让我那啥吧。</d>", cleaned)
        self.assertNotIn("<d>[Chinese] 沙丽丽：", cleaned)
        self.assertEqual([], H3PromptBuilder.validate_prompts([shot], [cleaned], speaker_map))

    def test_clean_dialogue_strips_matching_speaker_and_quotes(self):
        cleaned = H3PromptBuilder._clean_dialogue("李青莲：“君不见，黄河之水天上来。”", "李青莲")
        self.assertEqual("君不见，黄河之水天上来。", cleaned)

    def test_llm_service_strips_speaker_name_inside_spoken_tag(self):
        from backend.app.media_studio.services.llm_service import LlmService

        dirty = "(S1) 沙丽丽 says <d>[Chinese] 沙丽丽：“该不会想让我那啥吧。”</d>"
        cleaned = LlmService._clean_h3_prompt_dialogue(dirty, ["吴耐", "沙丽丽"])
        self.assertIn("<d>[Chinese] 该不会想让我那啥吧。</d>", cleaned)
        self.assertNotIn("<d>[Chinese] 沙丽丽：", cleaned)

    def test_validate_h3_prompt_rejects_short_english(self):
        from backend.app.media_studio.services.llm_service import LlmService

        prompt = (
            "subject_definitions:\n<Subject 1> is the protagonist anchored by <Picture 1>.\n"
            "summary:\n[reference generation + audio reference] A brief scene.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n[Shot 1] The camera holds while lighting and sound remain quiet. "
            "(S1) says <d>[Chinese] 你好。</d>\n"
            "overall_soundscape:\nQuiet room sound.\n"
            "non_diegetic_music:\nN/A."
        )
        errors = LlmService._validate_h3_prompt(
            prompt,
            "Ref2VA",
            {"dialogue": "你好。", "ref_images": [{"index": 1, "name": "角色", "category": "character"}]},
        )
        self.assertTrue(any("过短" in item for item in errors))

    def test_validate_h3_prompt_rejects_missing_lighting_camera_sound(self):
        from backend.app.media_studio.services.llm_service import LlmService

        prompt = (
            rich_prompt()
            .replace("[reference generation + audio reference]", "[reference generation]")
            .replace("The camera holds", "The framing holds")
            .replace("natural lighting", "natural exposure")
            .replace("synchronized sound", "synchronized noise")
            .replace("Quiet room sound", "Quiet room noise")
        )
        errors = LlmService._validate_h3_prompt(
            prompt,
            "Ref2VA",
            {"dialogue": "你好。", "ref_images": [{"index": 1}, {"index": 2}]},
        )
        self.assertTrue(any("camera" in item for item in errors))
        self.assertTrue(any("lighting" in item for item in errors))
        self.assertTrue(any("sound" in item for item in errors))

    def test_validate_h3_prompt_accepts_rich_ref2va(self):
        from backend.app.media_studio.services.llm_service import LlmService

        errors = LlmService._validate_h3_prompt(
            rich_prompt(),
            "Ref2VA",
            {"dialogue": "你好。", "ref_images": [{"index": 1}, {"index": 2}]},
        )
        self.assertEqual([], errors)

    def test_h3_user_prompt_includes_visual_audio_and_thickness_contract(self):
        from backend.app.media_studio.services.llm_service import LlmService

        text = LlmService._h3_user_prompt(
            {
                "sequence": 1,
                "heading": "电梯里的误会",
                "action": "空间：不锈钢轿厢。调度：她护着手机后退。收束：定格睁大的眼睛。",
                "visual_prompt": "Photorealistic vertical 9:16 fluorescent lighting and a slow camera push-in.",
                "audio": "电梯低频嗡鸣、铃铛细响",
                "video_prompt_zh": "竖屏短剧单镜 运镜：慢推 声音：电梯嗡鸣",
                "dialogue": "该不会想让我那啥吧。",
                "ref_images": [{"index": 1, "name": "吴耐", "category": "character"}],
            },
            "Ref2VA",
            "8",
        )
        self.assertIn("Photorealistic vertical 9:16 fluorescent lighting", text)
        self.assertIn("电梯低频嗡鸣、铃铛细响", text)
        self.assertIn("竖屏短剧单镜", text)
        self.assertIn("320", text)
        self.assertIn("[Shot 1]", text)
        self.assertIn("必须展开进画面正文", text)
        self.assertIn("8 秒时序", text)
        self.assertIn("必须在 8 秒内演完", text)

        eleven = LlmService._h3_user_prompt(
            {
                "sequence": 1,
                "heading": "电梯里的误会",
                "action": "空间：不锈钢轿厢。",
                "dialogue": "该不会想让我那啥吧。",
            },
            "Ref2VA",
            "11",
        )
        self.assertIn("11 秒时序", eleven)
        self.assertIn("必须在 11 秒内演完", eleven)
        self.assertNotIn("8 秒时序", eleven)

    def test_split_inner_voice_out_of_spoken_turns(self):
        shot = {
            "dialogue": (
                "沙丽丽：“大爷，我什么都可以做。那个，那个房租下个月一定给你。” "
                "吴耐（内心）：“浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。” "
                "吴耐：“不用想也知道，做的是什么。”"
            ),
            "characters": ["吴耐", "沙丽丽"],
        }
        spoken, inner = H3PromptBuilder.split_spoken_and_inner(shot)
        self.assertEqual(
            [item["text"] for item in spoken],
            ["大爷，我什么都可以做。那个，那个房租下个月一定给你。", "不用想也知道，做的是什么。"],
        )
        self.assertEqual(inner[0]["speaker"], "吴耐")
        self.assertEqual(inner[0]["text"], "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。")
        self.assertEqual([item["text"] for item in H3PromptBuilder._dialogue_turns(shot)], [item["text"] for item in spoken])

    def test_h3_user_prompt_does_not_echo_inner_line_repeatedly(self):
        from backend.app.media_studio.services.llm_service import LlmService

        inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
        dialogue = (
            "沙丽丽：“大爷，我什么都可以做。那个，那个房租下个月一定给你。” "
            f"吴耐（内心）：“{inner}” "
            "吴耐：“不用想也知道，做的是什么。”"
        )
        action = (
            "竖屏短剧单镜。调度：她讨好。他嘴唇闭合扫视，内心说浓妆艳抹、昼伏夜出。"
            f"本镜对白必须口型同步：{dialogue}。收束：定格。"
        )
        visual = (
            "Photorealistic camera lighting. Lip-sync the exact Chinese line(s): "
            f"{dialogue}. Do not translate the line onto the picture. Closed lips for inner voice."
        )
        text = LlmService._h3_user_prompt(
            {
                "sequence": 1,
                "heading": "我什么都可以做",
                "action": action,
                "visual_prompt": visual,
                "audio": "电梯低频嗡鸣",
                "video_prompt_zh": action + " 运镜：上摇 声音：电梯嗡鸣",
                "dialogue": dialogue,
                "speaker": "吴耐",
                "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
                "existing_prompt": f"old prompt repeats {inner} and {inner}",
            },
            "Ref2VA",
            "15",
        )
        self.assertEqual(text.count(inner), 1)
        self.assertEqual(text.count("浓妆艳抹"), 1)
        self.assertIn("旁白/内心", text)
        self.assertIn("开口对白", text)
        self.assertNotIn("本镜对白必须口型同步", text)
        self.assertNotIn("Lip-sync the exact Chinese line(s)", text)
        self.assertNotIn("old prompt repeats", text)
        self.assertNotIn("中文视频提示拼接", text)

    def test_validate_rejects_duplicated_inner_line_and_lip_sync(self):
        from backend.app.media_studio.services.llm_service import LlmService

        inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
        spoken = "不用想也知道，做的是什么。"
        duplicated = rich_prompt(spoken).replace(
            f"<d>[Chinese] {spoken}</d>",
            f"(S1) says <d>[Chinese] {inner}</d>. (S1) says <d>[Chinese] {inner}</d>. "
            f"(S1) says <d>[Chinese] {spoken}</d>",
        )
        errors = LlmService._validate_h3_prompt(
            duplicated,
            "Ref2VA",
            {
                "dialogue": (
                    f"吴耐（内心）：“{inner}” 吴耐：“{spoken}”"
                ),
                "ref_images": [{"index": 1}, {"index": 2}],
            },
        )
        self.assertTrue(any("duplicated" in item or "lip-synced" in item for item in errors))

        accepted = rich_prompt(spoken).replace(
            f"<d>[Chinese] {spoken}</d>",
            "In an off-screen inner voiceover, all visible characters keep their lips closed: "
            f"<d>[Chinese] {inner}</d>. (S1) says "
            f"<d>[Chinese] {spoken}</d>",
        )
        self.assertEqual(
            [],
            LlmService._validate_h3_prompt(
                accepted,
                "Ref2VA",
                {
                    "dialogue": f"吴耐（内心）：“{inner}” 吴耐：“{spoken}”",
                    "ref_images": [{"index": 1}, {"index": 2}],
                },
            ),
        )

    def test_normalize_does_not_append_second_copy_of_existing_inner_line(self):
        inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
        spoken = "不用想也知道，做的是什么。"
        shot = {
            "sequence": 1,
            "dialogue": f"吴耐（内心）：“{inner}” 吴耐：“{spoken}”",
            "character_references": [{"character_name": "吴耐"}],
        }
        prompt = rich_prompt(spoken).replace(
            f"<d>[Chinese] {spoken}</d>",
            "In an off-screen inner voiceover, all visible characters keep their lips closed: "
            f"<d>[Chinese] {inner}</d>. (S1) says "
            f"<d>[Chinese] {spoken}</d>",
        )
        normalized = H3PromptBuilder._normalize_prompt(shot, prompt, {"吴耐": "S1"})
        self.assertEqual(normalized.count(inner), 1)

    def test_prepare_generated_prompt_fixes_punct_pictures_and_duplicates(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_a = "大爷，我什么都可以做。那个，那个房租下个月一定给你。"
        spoken_b = "不用想也知道，做的是什么。"
        inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
        dialogue = (
            f"沙丽丽：“{spoken_a}” "
            f"吴耐（内心）：“{inner}” "
            f"吴耐：“{spoken_b}”"
        )
        detail = " ".join(
            [
                "The camera holds a stable medium composition while natural lighting defines the room, "
                "the subject performs a precise visible action, and synchronized sound follows every contact."
            ]
            * 24
        )
        flawed = (
            "subject_definitions:\nTwo people stand in an elevator without reference tags.\n"
            "summary:\n[reference generation + audio reference] An eight-second scene.\n"
            "retention_analysis:\nfully_preserved.\n"
            f"detailed_description:\n[Shot 1] {detail} "
            f"(S1) 沙丽丽 says <d>{spoken_a.rstrip('。')}</d>. "
            f"He thinks {inner.rstrip('。')}. "
            f"(S2) says <d>[Chinese] {spoken_b}</d> "
            f"He repeats {spoken_b.rstrip('。')}. "
            "The shot holds long enough for complete unhurried dialogue and a natural pause.\n"
            "overall_soundscape:\nQuiet room sound and synchronized movement.\n"
            "non_diegetic_music:\nRestrained piano at a slow tempo with a soft ending."
        )
        beat_info = {
            "sequence": 1,
            "dialogue": dialogue,
            "narration": inner,
            "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
            "scene_name": "电梯",
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "沙丽丽", "category": "character"},
                {"index": 3, "name": "电梯", "category": "scene"},
            ],
        }
        raw_errors = LlmService._validate_h3_prompt(flawed, "Ref2VA", beat_info)
        self.assertTrue(any("missing <Picture" in item for item in raw_errors))
        self.assertTrue(any("duplicated" in item for item in raw_errors))

        prepared = H3PromptBuilder.prepare_generated_prompt(
            flawed,
            H3PromptBuilder.shot_from_beat_info(beat_info),
        )
        self.assertEqual([], LlmService._validate_h3_prompt(prepared, "Ref2VA", beat_info))
        self.assertEqual(prepared.count(spoken_a), 1)
        self.assertEqual(prepared.count(spoken_b), 1)
        self.assertEqual(prepared.count(inner), 1)
        self.assertIn("<Picture 1>", prepared)
        self.assertIn("<Picture 2>", prepared)
        self.assertIn("<Picture 3>", prepared)
        self.assertRegex(prepared, r"off[\s-]?screen")

        with patch.object(LlmService, "_request_h3_prompt", return_value=flawed):
            generated = LlmService.generate_h3_prompt(beat_info)
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", beat_info))

    def test_h3_system_prompt_requires_expanding_beat_context(self):
        from backend.app.media_studio.services.llm_service import LlmService

        system = LlmService._h3_system_prompt("Ref2VA", "8")
        self.assertIn("visual_prompt", system)
        self.assertIn("320", system)
        self.assertIn("[Shot 1]", system)
        self.assertIn("one-sentence", system)
        self.assertIn("8-second performance", system)
        self.assertNotIn("eight-second performance", system)
        self.assertIn("Shot timing budget", system)
        self.assertIn("do not cram dialogue + walk + turn into 5s", system)
        self.assertIn("Do NOT emit At HH:MM.SSS", system)
        self.assertIn("Never copy the same Chinese sentence twice", system)
        self.assertIn("Never lip-sync inner voice", system)

        eleven = LlmService._h3_system_prompt("Ref2VA", "11")
        self.assertIn("11-second performance", eleven)
        self.assertIn("duration_seconds is 11", eleven)

    def test_workshop_h3_builder_includes_director1_timing_budget(self):
        from backend.app.llm_minimax_skills import build_workshop_h3_timing_rules

        rules = build_workshop_h3_timing_rules(11)
        self.assertIn("do not cram dialogue + walk + turn into 5s", rules)
        self.assertIn("duration_seconds is 11", rules)
        self.assertIn("Do NOT emit At HH:MM.SSS", rules)
        self.assertNotIn("In promptText, place At", rules)
        prompt = H3PromptBuilder._system_prompt(11)
        self.assertIn("do not cram dialogue + walk + turn into 5s", prompt)
        self.assertIn("lasting 11 seconds", prompt)

    def test_workshop_prompts_reject_thin_saved_prompt(self):
        shot = {
            "sequence": 1,
            "speaker": "沈砚",
            "dialogue": "你好。",
            "h3_prompt": "subject_definitions:\nthis saved prompt is longer than thirty characters but still too thin",
        }
        self.assertGreater(len(shot["h3_prompt"]), 30)
        self.assertIsNone(EpisodeVideoService._workshop_prompts_usable([shot]))

    def test_workshop_prompts_accept_rich_saved_prompt(self):
        prompt = rich_prompt()
        shot = {"sequence": 1, "speaker": "沈砚", "dialogue": "你好。", "h3_prompt": prompt}
        usable = EpisodeVideoService._workshop_prompts_usable([shot])
        self.assertIsNotNone(usable)
        self.assertEqual([], H3PromptBuilder.validate_prompts([shot], usable))
        self.assertIn("你好。", usable[0])
        self.assertIn("[Shot 1]", usable[0])

    def test_workshop_prompts_normalize_missing_subject_before_reuse(self):
        prompt = (
            rich_prompt("只对十四天。")
            .replace(
                "<Subject 2> is the environment anchored by <Picture 2>.",
                "<Picture 2> is the environment anchored by <Picture 2>.",
            )
            .replace("<d>[Chinese] 只对十四天。</d>", "<d>只对十四天。</d>")
        )
        shot = {
            "sequence": 1,
            "speaker": "沙丽丽",
            "dialogue": "只对十四天。",
            "h3_prompt": prompt,
            "character_references": [
                {"character_name": "吴耐"},
                {"character_name": "沙丽丽"},
            ],
        }
        raw_errors = H3PromptBuilder.validate_prompts([shot], [prompt])
        self.assertTrue(any("<Subject 3>" in item for item in raw_errors))
        self.assertTrue(any("中文对白标签" in item for item in raw_errors))
        usable = EpisodeVideoService._workshop_prompts_usable([shot])
        self.assertIsNotNone(usable)
        self.assertIn("<Subject 3>", usable[0])
        self.assertIn("<d>[Chinese] 只对十四天。</d>", usable[0])
        self.assertEqual([], H3PromptBuilder.validate_prompts([shot], usable))

    def test_beat_info_prompt_finalize_injects_missing_subject(self):
        from backend.app.media_studio.services.h3_prompt_job_service import H3PromptJobService

        prompt = rich_prompt("只对十四天。").replace(
            "<Subject 2> is the environment anchored by <Picture 2>.",
            "<Picture 2> is the elevator scene anchored by <Picture 2>.",
        )
        payload = {
            "beat_id": "beat-1",
            "beat_sequence": 1,
            "beat_info": {
                "speaker": "沙丽丽",
                "dialogue": "只对十四天。",
                "characters": [
                    {"name": "吴耐", "desc": "elderly man"},
                    {"name": "沙丽丽", "look_desc": "young woman"},
                ],
                "scene_name": "电梯",
            },
        }
        finalized = H3PromptJobService._finalize_prompt(payload, prompt)
        self.assertIn("<Subject 3>", finalized)
        shot = H3PromptJobService._beat_info_shot(payload)
        self.assertEqual([], H3PromptBuilder.validate_prompts([shot], [finalized]))

    def test_beat_context_fields_include_visual_prompt_and_audio(self):
        from backend.app.media_studio.services.h3_prompt_job_service import H3PromptJobService

        fields = H3PromptJobService._beat_context_fields({
            "visual_prompt": "Photorealistic vertical 9:16 fluorescent lighting.",
            "audio": "电梯低频嗡鸣",
            "video_prompt_zh": "竖屏短剧单镜 运镜：慢推 声音：电梯嗡鸣",
        })
        self.assertEqual("Photorealistic vertical 9:16 fluorescent lighting.", fields["visual_prompt"])
        self.assertEqual("电梯低频嗡鸣", fields["audio"])
        self.assertIn("运镜：慢推", fields["video_prompt_zh"])
        fallback = H3PromptJobService._beat_context_fields({"soundscape": "雨声"})
        self.assertEqual("雨声", fallback["audio"])


class ComfyWorkflowTests(unittest.TestCase):
    def test_timeline_uses_two_refs_and_8_second_grid(self):
        shots = []
        for index in range(2):
            shots.append({
                "beat_id": f"beat-{index + 1}",
                "prompt": rich_prompt(),
                "uploaded_refs": [
                    {"imageFile": "char.png", "fileName": "char.png", "type": "input", "subfolder": "refs"},
                    {"imageFile": "scene.png", "fileName": "scene.png", "type": "input", "subfolder": "refs"},
                ],
            })
        timeline = ComfyVideoClient.build_timeline(shots, "r2v — Reference to Video")
        self.assertEqual(384, timeline["totalFrames"])
        self.assertEqual([0, 192], [item["start"] for item in timeline["segments"]])
        self.assertTrue(all(item["frameCount"] == 192 for item in timeline["segments"]))
        self.assertTrue(all(len(item["refs"]) == 2 for item in timeline["segments"]))
        self.assertEqual("generate", timeline["output"]["audioMode"])
        self.assertEqual(timeline["segments"], timeline["batchWorkspaces"]["r2v"]["segments"])

    def test_workflow_contains_acceleration_and_audio_chain(self):
        timeline = ComfyVideoClient.build_timeline([], "r2v — Reference to Video")
        workflow = ComfyVideoClient.build_workflow(timeline, "r2v — Reference to Video", "video/test")
        self.assertEqual("PathchSageAttentionKJ", workflow["14"]["class_type"])
        self.assertEqual(["12", 1], workflow["6"]["inputs"]["audio"])
        self.assertEqual(20, workflow["12"]["inputs"]["steps"])
        self.assertEqual(864, workflow["12"]["inputs"]["width"])

    def test_resolve_generation_options_uses_registry_defaults_and_drops_invalid_speed(self):
        resolved = EpisodeVideoService.resolve_generation_options({
            "workflow": "minimax-h3-director-accel-r2v",
            "quality": 1.0,
            "speed": "fast",
            "weight_profile": "pruned",
        })
        self.assertEqual("1.0", resolved["quality"])
        self.assertEqual("balanced", resolved["speed"])
        self.assertEqual(20, resolved["steps"])
        self.assertEqual(1376, resolved["width"])
        self.assertEqual(768, resolved["height"])

    def test_finds_nested_video_output(self):
        output = ComfyVideoClient._find_video({"7": {"videos": [{
            "filename": "result.mp4", "subfolder": "video", "type": "output"
        }]}})
        self.assertEqual("result.mp4", output["filename"])

    def test_progress_from_message_matches_director_sampler(self):
        workflow = {
            "12": {"class_type": "MiniMaxH3Director"},
            "7": {"class_type": "SaveVideo"},
        }
        self.assertEqual(25, ComfyVideoClient.progress_from_message(
            {
                "type": "progress_state",
                "data": {
                    "prompt_id": "p1",
                    "nodes": {"12": {"state": "running", "value": 5, "max": 20}},
                },
            },
            "p1",
            workflow,
        ))
        self.assertEqual(50, ComfyVideoClient.progress_from_message(
            {
                "type": "progress",
                "data": {"prompt_id": "p1", "node": "12", "value": 10, "max": 20},
            },
            "p1",
            workflow,
        ))

    def test_wait_for_result_uses_websocket_progress_not_fake_increment(self):
        client = ComfyVideoClient("http://127.0.0.1:8188")
        workflow = {"12": {"class_type": "MiniMaxH3Director"}, "7": {"class_type": "SaveVideo"}}
        messages = [
            json.dumps({
                "type": "progress_state",
                "data": {"prompt_id": "p1", "nodes": {"12": {"state": "running", "value": 4, "max": 20}}},
            }),
            json.dumps({
                "type": "progress_state",
                "data": {"prompt_id": "p1", "nodes": {"12": {"state": "running", "value": 10, "max": 20}}},
            }),
        ]
        percents: list[int] = []

        class FakeSocket:
            def recv(self):
                if messages:
                    return messages.pop(0)
                raise websocket.WebSocketTimeoutException("timeout")

            def close(self):
                pass

        success = {
            "p1": {
                "status": {"completed": True, "status_str": "success"},
                "outputs": {"7": {"videos": [{"filename": "a.mp4", "subfolder": "", "type": "output"}]}},
            }
        }

        def fake_get(url, timeout=None):
            response = Mock()
            response.ok = True
            response.raise_for_status = Mock()
            response.json.return_value = {} if len(percents) < 2 else success
            return response

        client.session.get = fake_get
        history, output = client.wait_for_result(
            "p1",
            progress=percents.append,
            workflow=workflow,
            progress_socket=FakeSocket(),
            poll_seconds=0,
        )
        self.assertEqual([20, 50], percents)
        self.assertEqual("a.mp4", output["filename"])
        self.assertTrue(history["status"]["completed"])

    def test_wait_for_result_does_not_fake_progress_without_socket(self):
        client = ComfyVideoClient("http://127.0.0.1:8188")
        percents: list[int] = []
        calls = {"n": 0}
        success = {
            "p1": {
                "status": {"completed": True, "status_str": "success"},
                "outputs": {"7": {"videos": [{"filename": "a.mp4", "subfolder": "", "type": "output"}]}},
            }
        }

        def fake_get(url, timeout=None):
            calls["n"] += 1
            response = Mock()
            response.ok = True
            response.raise_for_status = Mock()
            response.json.return_value = {} if calls["n"] == 1 else success
            return response

        client.session.get = fake_get
        _history, output = client.wait_for_result("p1", progress=percents.append, poll_seconds=0)
        self.assertEqual([], percents)
        self.assertEqual("a.mp4", output["filename"])


class LookSelectionTests(unittest.TestCase):
    def setUp(self):
        self.character = {"id": "char-1", "extra": {"identities": [
            {"id": "old", "description": "17岁古代少年，粗布长衫", "image_url": "https://x/old.png"},
            {"id": "new", "description": "现代26岁研究生，白色衬衫", "image_url": "https://x/new.png"},
        ]}}

    def test_selects_era_appropriate_look(self):
        modern = EpisodeVideoService._select_character_look(self.character, {"scene": "现代大学图书馆"})
        ancient = EpisodeVideoService._select_character_look(self.character, {"scene": "破旧茅屋"})
        self.assertEqual("new", modern["id"])
        self.assertEqual("old", ancient["id"])

    def test_rejects_modern_shot_without_modern_look(self):
        character = {"extra": {"identities": [self.character["extra"]["identities"][0]]}}
        self.assertIsNone(EpisodeVideoService._select_character_look(character, {"scene": "现代图书馆"}))

    def test_explicit_look_overrides_automatic_era_match(self):
        selected = EpisodeVideoService._select_character_look(
            self.character,
            {"scene": "现代大学图书馆", "character_look_id": "old"},
        )
        self.assertEqual("old", selected["id"])

    def test_invalid_explicit_look_does_not_fall_back(self):
        selected = EpisodeVideoService._select_character_look(
            self.character,
            {"scene": "现代大学图书馆", "character_look_ids": {"char-1": "missing"}},
        )
        self.assertIsNone(selected)

    def test_character_look_mapping_selects_each_character_independently(self):
        mother = {"id": "mother-1", "extra": {"identities": [{
            "id": "mother-look", "description": "60岁母亲，灰白棉麻长衫", "image_url": "https://x/mother.png",
        }]}}
        beat = {"character_look_ids": {"char-1": "old", "mother-1": "mother-look"}}
        self.assertEqual("old", EpisodeVideoService._select_character_look(self.character, beat)["id"])
        self.assertEqual("mother-look", EpisodeVideoService._select_character_look(mother, beat)["id"])

    def test_explicit_protagonist_look_is_selected_when_other_character_is_first(self):
        mother = {"extra": {"identities": [{
            "id": "mother-look", "description": "60岁母亲，灰白棉麻长衫", "image_url": "https://x/mother.png",
        }]}}
        beat = {"character_look_id": "new"}
        self.assertEqual("new", EpisodeVideoService._select_character_look(self.character, beat)["id"])
        self.assertEqual("mother-look", EpisodeVideoService._select_character_look(mother, beat)["id"])

    def test_render_references_use_only_selected_look(self):
        assets = [{
            "id": "char-1",
            "kind": "character",
            "image_url": "https://x/avatar.png",
            "extra": {
                "avatar_url": "https://x/avatar.png",
                "identities": self.character["extra"]["identities"],
            },
        }]
        urls = beat_reference_urls(
            {
                "character_ids": ["char-1"],
                "character_look_id": "new",
                "sketch_url": "https://x/sketch.png",
            },
            assets,
            stage="render",
        )
        self.assertEqual(
            ["https://x/sketch.png", "https://x/new.png"],
            urls,
        )

    def test_render_references_do_not_fall_back_to_unselected_look(self):
        assets = [{
            "id": "char-1",
            "kind": "character",
            "image_url": "https://x/avatar.png",
            "extra": {
                "avatar_url": "https://x/avatar.png",
                "identities": self.character["extra"]["identities"],
            },
        }]
        urls = beat_reference_urls(
            {"character_ids": ["char-1"], "sketch_url": "https://x/sketch.png"},
            assets,
            stage="render",
        )
        self.assertEqual(["https://x/sketch.png"], urls)

    def test_render_references_find_selected_look_when_protagonist_is_not_first(self):
        assets = [
            {
                "id": "mother-1",
                "kind": "character",
                "extra": {"identities": [{"id": "mother", "image_url": "https://x/mother.png"}]},
            },
            {
                "id": "char-1",
                "kind": "character",
                "extra": {"identities": [{"id": "new", "image_url": "https://x/new.png"}]},
            },
        ]
        urls = beat_reference_urls(
            {
                "character_ids": ["mother-1", "char-1"],
                "character_look_id": "new",
                "sketch_url": "https://x/sketch.png",
            },
            assets,
            stage="render",
        )
        self.assertEqual(["https://x/sketch.png", "https://x/new.png"], urls)

    def test_render_references_include_one_selected_look_per_character(self):
        assets = [
            {
                "id": "mother-1",
                "kind": "character",
                "extra": {"identities": [{"id": "mother", "image_url": "https://x/mother.png"}]},
            },
            {
                "id": "char-1",
                "kind": "character",
                "extra": {"identities": [{"id": "new", "image_url": "https://x/new.png"}]},
            },
        ]
        urls = beat_reference_urls(
            {
                "character_ids": ["mother-1", "char-1"],
                "character_look_ids": {"mother-1": "mother", "char-1": "new"},
                "sketch_url": "https://x/sketch.png",
            },
            assets,
            stage="render",
        )
        self.assertEqual(
            ["https://x/sketch.png", "https://x/mother.png", "https://x/new.png"],
            urls,
        )

    def test_selected_modern_look_removes_conflicting_default_description(self):
        assets = [{
            "id": "char-1",
            "kind": "character",
            "name": "Protagonist",
            "definition": {
                "face_prompt": "ancient teenage scholar with a historical hair bun",
                "description": "17-year-old wearing an ancient robe",
                "looks": [{
                    "id": "modern",
                    "appearance_details": "26-year-old graduate student, short hair, white modern shirt",
                    "image_url": "https://x/modern.png",
                }],
            },
        }]
        prompt = beat_render_prompt(
            {
                "character_ids": ["char-1"],
                "character_look_id": "modern",
                "heading": "现代大学图书馆",
                "scene": "现代图书馆",
                "action": "在电脑旁阅读",
            },
            assets=assets,
            visual_style="chinese_period_drama",
            ethnicity="Chinese",
        )
        self.assertIn("Image 2 is the sole appearance authority for this character", prompt)
        self.assertIn("26-year-old graduate student, short hair, white modern shirt", prompt)
        self.assertIn("NATURAL PHOTOREALISTIC, CLEAN GRADE", prompt)
        self.assertIn("this Beat is contemporary modern-day", prompt)
        self.assertNotIn("ancient teenage scholar", prompt)
        self.assertNotIn("17-year-old wearing an ancient robe", prompt)


class EpisodeVideoPrepareShotsTests(unittest.TestCase):
    def _beat(self, **overrides):
        beat = {
            "id": "beat-1",
            "sequence": 1,
            "action": "吴耐走进走廊",
            "camera": "中景",
            "scene": "开元楼走廊",
            "scene_id": "scene-empty",
            "character_ids": ["char-1"],
        }
        beat.update(overrides)
        return beat

    def _assets(self, *, empty_scene=True, ready_scene=True):
        assets = [{
            "id": "char-1",
            "kind": "character",
            "name": "吴耐",
            "extra": {"identities": [{"id": "look-1", "image_url": "https://x/char.png"}]},
        }]
        if empty_scene:
            assets.append({
                "id": "scene-empty",
                "kind": "scene",
                "name": "开元楼走廊",
                "image_url": "",
                "extra": {},
            })
        if ready_scene:
            assets.append({
                "id": "scene-ready",
                "kind": "scene",
                "name": "开元楼走廊",
                "image_url": "https://x/scene.png",
                "extra": {"master_url": "https://x/scene.png"},
            })
        return assets

    def test_falls_back_to_same_name_scene_with_master_view(self):
        shots = EpisodeVideoService._prepare_shots({"beats": [self._beat()]}, self._assets())
        self.assertEqual("scene-ready", shots[0]["scene_id"])
        self.assertEqual("https://x/scene.png", shots[0]["reference_urls"][-1])

    def test_binds_scene_by_name_when_scene_id_is_missing(self):
        shots = EpisodeVideoService._prepare_shots(
            {"beats": [self._beat(scene_id=None)]},
            self._assets(empty_scene=False),
        )
        self.assertEqual("scene-ready", shots[0]["scene_id"])

    def test_still_fails_when_no_scene_has_a_master_view(self):
        with self.assertRaises(ValueError) as ctx:
            EpisodeVideoService._prepare_shots(
                {"beats": [self._beat()]},
                self._assets(ready_scene=False),
            )
        self.assertIn("开元楼走廊", str(ctx.exception))
        self.assertIn("主视图", str(ctx.exception))

    def test_selected_beats_skip_other_beats_missing_looks(self):
        character = {
            "id": "char-1",
            "kind": "character",
            "name": "吴耐",
            "extra": {"identities": [{
                "id": "old",
                "description": "17岁古代少年，粗布长衫",
                "image_url": "https://x/old.png",
            }]},
        }
        assets = [character] + [item for item in self._assets() if item["kind"] == "scene"]
        ready = self._beat(scene_id="scene-ready")
        modern = self._beat(
            id="beat-4",
            sequence=4,
            action="吴耐走进现代大学图书馆",
            scene="现代大学图书馆",
            scene_id="scene-ready",
        )
        detail = {"beats": [ready, modern]}
        with self.assertRaises(ValueError) as ctx:
            EpisodeVideoService._prepare_shots(detail, assets)
        self.assertIn("Beat 4 缺少符合时代/年龄/服装的「吴耐」造型图", str(ctx.exception))
        self.assertNotIn("Beat 1", str(ctx.exception))

        shots = EpisodeVideoService._prepare_shots(detail, assets, beat_ids=["beat-1"])
        self.assertEqual(["beat-1"], [shot["beat_id"] for shot in shots])

    def test_prepare_shots_rejects_unknown_beat_ids(self):
        with self.assertRaises(ValueError) as ctx:
            EpisodeVideoService._prepare_shots(
                {"beats": [self._beat(scene_id="scene-ready")]},
                self._assets(),
                beat_ids=["beat-missing"],
            )
        self.assertIn("指定的镜头不存在或无法生成视频：beat-missing", str(ctx.exception))

    def test_sketch_references_use_same_name_scene_master(self):
        urls = beat_reference_urls(self._beat(), self._assets(), stage="sketch")
        self.assertEqual(["https://x/scene.png"], urls)


class EpisodeVideoSubmitTests(unittest.TestCase):
    def _shots(self, count=3):
        return [{"beat_id": f"beat-{index}", "sequence": index} for index in range(1, count + 1)]

    def _detail(self, *, video_urls=None, source=""):
        video_urls = video_urls or {}
        beats = []
        for index in range(1, 4):
            beat_id = f"beat-{index}"
            beats.append({
                "id": beat_id,
                "sequence": index,
                "video_url": video_urls.get(beat_id, ""),
            })
        return {"number": 1, "title": "测试集", "beats": beats, "data": {"beats": beats, "episode_video_source": source}}

    def test_director_one_click_creates_a_single_episode_job(self):
        with patch.object(EpisodeVideoService, "create_job", return_value={"job_id": "job-ep", "status": "queued", "render_scope": "episode"}) as create_job:
            result = EpisodeVideoService.generate_episode_videos(
                "p1", "e1", options={"workflow": "minimax-h3-director-accel-r2v"},
            )
        create_job.assert_called_once()
        self.assertIsNone(create_job.call_args.kwargs.get("beat_id"))
        self.assertEqual("episode", create_job.call_args.kwargs.get("render_scope"))
        self.assertEqual("episode", result["render_mode"])
        self.assertEqual(["job-ep"], result["job_ids"])
        self.assertEqual(1, result["submitted"])
        self.assertEqual(0, result["skipped"])

    def test_shot_one_click_creates_n_jobs_and_skips_existing_video(self):
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=self._detail(video_urls={"beat-2": "https://cdn/b2.mp4"})), \
             patch.object(ProjectDetailService, "list_assets", return_value=[]), \
             patch.object(EpisodeVideoService, "_prepare_shots", return_value=self._shots()), \
             patch.object(EpisodeVideoService, "_active_video_jobs", return_value=[]), \
             patch.object(EpisodeVideoService, "create_job", side_effect=lambda *args, **kwargs: {
                 "job_id": f"job-{kwargs['beat_id']}", "status": "queued", "render_scope": "shot",
             }) as create_job:
            result = EpisodeVideoService.generate_episode_videos(
                "p1", "e1", options={"workflow": "minimax-h3-r2v"},
            )
        self.assertEqual("shot", result["render_mode"])
        self.assertEqual(["job-beat-1", "job-beat-3"], result["job_ids"])
        self.assertEqual(2, result["submitted"])
        self.assertEqual(1, result["skipped"])
        self.assertEqual(["beat-1", "beat-3"], [call.kwargs["beat_id"] for call in create_job.call_args_list])

    def test_shot_selected_ids_create_only_those_jobs_even_if_video_exists(self):
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=self._detail(video_urls={"beat-2": "https://cdn/b2.mp4"})), \
             patch.object(ProjectDetailService, "list_assets", return_value=[]), \
             patch.object(EpisodeVideoService, "_prepare_shots", return_value=self._shots()), \
             patch.object(EpisodeVideoService, "_active_video_jobs", return_value=[]), \
             patch.object(EpisodeVideoService, "create_job", side_effect=lambda *args, **kwargs: {
                 "job_id": f"job-{kwargs['beat_id']}", "status": "queued", "render_scope": "shot",
             }) as create_job:
            result = EpisodeVideoService.generate_episode_videos(
                "p1", "e1",
                options={"workflow": "minimax-h3-r2v", "beat_ids": ["beat-2", "beat-3"]},
            )
        self.assertEqual(["job-beat-2", "job-beat-3"], result["job_ids"])
        self.assertEqual(2, result["submitted"])
        self.assertEqual(0, result["skipped"])
        self.assertEqual(["beat-2", "beat-3"], [call.kwargs["beat_id"] for call in create_job.call_args_list])

    def test_shot_selected_ids_do_not_validate_unselected_beats(self):
        character = {
            "id": "char-1",
            "kind": "character",
            "name": "吴耐",
            "extra": {"identities": [{
                "id": "old",
                "description": "17岁古代少年，粗布长衫",
                "image_url": "https://x/old.png",
            }]},
        }
        scene = {
            "id": "scene-ready",
            "kind": "scene",
            "name": "开元楼走廊",
            "image_url": "https://x/scene.png",
            "extra": {"master_url": "https://x/scene.png"},
        }
        detail = {
            "number": 1,
            "title": "测试集",
            "beats": [
                {
                    "id": "beat-1",
                    "sequence": 1,
                    "action": "吴耐走进走廊",
                    "camera": "中景",
                    "scene": "开元楼走廊",
                    "scene_id": "scene-ready",
                    "character_ids": ["char-1"],
                },
                {
                    "id": "beat-4",
                    "sequence": 4,
                    "action": "吴耐走进现代大学图书馆",
                    "camera": "中景",
                    "scene": "现代大学图书馆",
                    "scene_id": "scene-ready",
                    "character_ids": ["char-1"],
                },
            ],
        }
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=detail), \
             patch.object(ProjectDetailService, "list_assets", return_value=[character, scene]), \
             patch.object(EpisodeVideoService, "_active_video_jobs", return_value=[]), \
             patch.object(EpisodeVideoService, "create_job", return_value={
                 "job_id": "job-beat-1", "status": "queued", "render_scope": "shot",
             }) as create_job:
            result = EpisodeVideoService.generate_episode_videos(
                "p1", "e1",
                options={"workflow": "minimax-h3-r2v", "beat_ids": ["beat-1"]},
            )
        self.assertEqual(["job-beat-1"], result["job_ids"])
        self.assertEqual(1, result["submitted"])
        create_job.assert_called_once()
        self.assertEqual("beat-1", create_job.call_args.kwargs["beat_id"])

    def test_director_rejects_selected_beat_ids(self):
        with patch.object(EpisodeVideoService, "create_job") as create_job:
            with self.assertRaisesRegex(ValueError, "整集直出工作流不支持勾选镜头"):
                EpisodeVideoService.generate_episode_videos(
                    "p1", "e1",
                    options={"workflow": "minimax-h3-director-accel-r2v", "beat_ids": ["beat-1"]},
                )
        create_job.assert_not_called()

    def test_shot_one_click_skips_in_progress_beats_and_errors_when_nothing_left(self):
        active = [{"id": "job-1", "payload_json": __import__("json").dumps({
            "render_scope": "shot", "beat_id": "beat-1", "episode_id": "e1",
        })}]
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=self._detail(video_urls={"beat-2": "https://x/a.mp4", "beat-3": "https://x/b.mp4"})), \
             patch.object(ProjectDetailService, "list_assets", return_value=[]), \
             patch.object(EpisodeVideoService, "_prepare_shots", return_value=self._shots()), \
             patch.object(EpisodeVideoService, "_active_video_jobs", return_value=active), \
             patch.object(EpisodeVideoService, "create_job") as create_job:
            with self.assertRaisesRegex(ValueError, "重新生成本镜"):
                EpisodeVideoService.generate_episode_videos("p1", "e1", options={"workflow": "minimax-h3-r2v"})
        create_job.assert_not_called()

    def test_shot_lock_allows_other_beats_and_blocks_same_beat(self):
        active = [{"id": "job-1", "payload_json": __import__("json").dumps({
            "render_scope": "shot", "beat_id": "beat-1", "episode_id": "e1",
        })}]
        with patch.object(EpisodeVideoService, "_active_video_jobs", return_value=active):
            EpisodeVideoService._assert_can_enqueue("p1", "e1", "shot", beat_id="beat-2")
            with self.assertRaisesRegex(ValueError, "该镜头已有进行中的视频任务"):
                EpisodeVideoService._assert_can_enqueue("p1", "e1", "shot", beat_id="beat-1")
            with self.assertRaisesRegex(ValueError, "该分集已有进行中的视频任务"):
                EpisodeVideoService._assert_can_enqueue("p1", "e1", "episode")
            with self.assertRaisesRegex(ValueError, "该分集已有进行中的视频任务"):
                EpisodeVideoService._assert_can_enqueue("p1", "e1", "compose")

    def test_compose_rejects_missing_shots_and_director_direct_output(self):
        missing = self._detail(video_urls={"beat-1": "https://cdn/a.mp4"})
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=missing):
            with self.assertRaisesRegex(ValueError, "Beat 2"):
                EpisodeVideoService.create_compose_job("p1", "e1")
        director = self._detail(source="director_direct")
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=director):
            with self.assertRaisesRegex(ValueError, "无需再合成"):
                EpisodeVideoService.create_compose_job("p1", "e1")

    def test_compose_enqueues_when_every_shot_has_video(self):
        detail = self._detail(video_urls={
            "beat-1": "https://cdn/1.mp4",
            "beat-2": "https://cdn/2.mp4",
            "beat-3": "https://cdn/3.mp4",
        })
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=detail), \
             patch.object(EpisodeVideoService, "_active_video_jobs", return_value=[]), \
             patch("backend.app.media_studio.services.episode_video_service.execute_sql") as execute_sql, \
             patch("backend.app.media_studio.services.episode_video_service._EXECUTOR") as executor:
            result = EpisodeVideoService.create_compose_job("p1", "e1")
        self.assertEqual("compose", result["render_scope"])
        self.assertTrue(result["job_id"].startswith("job-"))
        execute_sql.assert_called_once()
        executor.submit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
