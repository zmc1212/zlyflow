from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import re
import unittest
from unittest.mock import Mock, patch

import websocket

from backend.app.llm_client import OpenAICompatibleClient
from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient
from backend.app.media_studio.services.episode_image_prompts import beat_reference_urls, beat_render_prompt
from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
from backend.app.media_studio.services.h3_prompt_builder import H3PromptBuilder, _THICKNESS_PAD
from backend.app.media_studio.services.llm_service import LlmService
from backend.app.media_studio.services.project_detail_service import ProjectDetailService
from backend.app.skill_packs import HALF_NARRATED_PACK_ID


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


def short_authored_en(dialogue: str = "你好。") -> str:
    return (
        "subject_definitions:\n"
        "<picture 1> is the protagonist. <picture 2> is the corridor. "
        "<picture 3> is the start frame.\n"
        "summary:\n"
        "[reference generation] A corridor beat.\n"
        "retention_analysis:\n"
        "fully_preserved.\n"
        "detailed_description:\n"
        f"[Shot 1] The camera tracks down the corridor. (S1) says <d>[Chinese] {dialogue}</d>.\n"
        "overall_soundscape:\n"
        "Corridor hum.\n"
        "non_diegetic_music:\n"
        "None."
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

    def test_builds_each_beat_independently_and_keeps_attempt_diagnostics(self):
        shots = [
            {"beat_id": "beat-1", "sequence": 1, "speaker": "沈砚", "dialogue": "第一句。"},
            {"beat_id": "beat-2", "sequence": 2, "speaker": "沈砚", "dialogue": "第二句。"},
        ]
        attempts = []

        prompts = H3PromptBuilder.build_prompts(shots, on_attempt=attempts.append)

        self.assertEqual(["passed", "passed"], [item["status"] for item in attempts])
        self.assertEqual(["beat-1", "beat-2"], [item["beat_id"] for item in attempts])
        self.assertIn("第一句。", prompts[0])
        self.assertIn("第二句。", prompts[1])
        self.assertNotIn("第二句。", prompts[0])
        self.assertIn("<Subject 1>", prompts[0])
        self.assertIn("[Shot 1]", prompts[0])

    def test_build_prompts_does_not_call_llm(self):
        shots = [
            {"beat_id": "beat-1", "sequence": 1, "speaker": "沈砚", "dialogue": "第一句。"},
            {"beat_id": "beat-2", "sequence": 2, "speaker": "沈砚", "dialogue": "第二句。"},
        ]
        with patch("backend.app.media_studio.services.h3_prompt_builder.requests.post") as post:
            H3PromptBuilder.build_prompts(shots)
        post.assert_not_called()

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
        self.assertIn("(S2) <Subject 2> 沙丽丽 says", contract)
        dirty = rich_prompt("沙丽丽：“该不会想让我那啥吧。”").replace("(S1) says", "(S2) 沙丽丽 says")
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

    @patch.object(LlmService, "_runtime_config", return_value=("https://cn3.example/v1", "gpt-5.6-sol", "sk-test"))
    @patch.object(OpenAICompatibleClient, "chat_completion", return_value="packed prompt")
    def test_chat_text_streams_and_lowers_gpt5_reasoning(self, mock_chat, _config):
        text = LlmService.chat_text("sys", "user", max_tokens=6000, temperature=0.4)
        self.assertEqual(text, "packed prompt")
        self.assertTrue(mock_chat.call_args.kwargs["stream"])
        self.assertEqual(mock_chat.call_args.kwargs["reasoning_effort"], "low")
        self.assertEqual(mock_chat.call_args.kwargs["timeout"], 240.0)
        self.assertEqual(mock_chat.call_args.kwargs["max_tokens"], 6000)

    @patch.object(
        LlmService,
        "_runtime_config",
        return_value=("https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct", "sk-test"),
    )
    @patch.object(OpenAICompatibleClient, "chat_completion", return_value="ok")
    def test_chat_text_does_not_send_reasoning_effort_for_qwen(self, mock_chat, _config):
        LlmService.chat_text("sys", "user")
        self.assertNotIn("reasoning_effort", mock_chat.call_args.kwargs)
        self.assertTrue(mock_chat.call_args.kwargs["stream"])

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
        self.assertIn("SOURCE VISUAL DRAFT", text)
        self.assertIn("Photorealistic vertical 9:16 fluorescent lighting", text)
        self.assertIn("电梯低频嗡鸣、铃铛细响", text)
        self.assertIn("竖屏短剧单镜", text)
        self.assertIn("[Shot 1]", text)
        self.assertNotIn("必须展开进画面正文", text)
        self.assertIn("8 秒时序", text)
        self.assertIn("必须在 8 秒内演完", text)
        self.assertIn("原样保留 9:16", text)
        self.assertIn("只锁身份", text)
        self.assertIn("不锁站位", text)
        self.assertNotIn("appearance from", text)
        self.assertIn("Fill only missing", text)

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
            f"沙丽丽：“” 吴耐（内心）：“{inner}” 吴耐：“”。"
            f"本镜对白必须口型同步：{dialogue}。收束：定格。"
        )
        visual = (
            "Photorealistic camera lighting. Lip-sync the exact Chinese line(s): "
            f"{dialogue}. Do not translate the line onto the picture. Closed lips for inner voice. "
            f"沙丽丽：“” 吴耐（内心）：“{inner}” 吴耐：“”."
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
        self.assertIn("SOURCE VISUAL DRAFT", text)
        source_block = text.split("旁白/内心", 1)[0]
        self.assertNotIn(inner, source_block)
        self.assertNotIn("：“”", text)
        self.assertNotIn("本镜对白必须口型同步", text)
        self.assertNotIn("Lip-sync the exact Chinese line(s)", text)
        self.assertNotIn("old prompt repeats", text)
        self.assertNotIn("中文视频提示拼接", text)

    def test_h3_user_prompt_packs_thick_visual_draft(self):
        from backend.app.media_studio.services.llm_service import LlmService

        visual = (
            "Photorealistic vertical 9:16 eight-second take, no internal cuts. "
            "COMPOSITION AND CAMERA: medium-close two-shot, locked-off with one optional slow push-in. "
            "LOCATION: cramped stainless-steel elevator, sickly white fluorescent. "
            "LIGHTING: overhead fluorescent, cyan skin, no beauty rim light. "
            "CAST LOCK: skinny 60-year-old landlord; glamorous young woman in red satin. "
            "EIGHT-SECOND PERFORMANCE: doors shut, she shrinks into the rear-right corner, he freezes. "
            "FORBIDDEN: no costume jump, no 16:9 letterbox, no internal cuts."
        )
        text = LlmService._h3_user_prompt(
            {
                "sequence": 1,
                "heading": "电梯里的误会",
                "action": "空间：不锈钢轿厢。调度：她护着手机后退。",
                "visual_prompt": visual,
                "audio": "电梯低频嗡鸣",
                "dialogue": "该不会想让我那啥吧。",
                "aspect_ratio": "9:16",
                "ref_images": [{"index": 1, "name": "吴耐", "category": "character"}],
            },
            "Ref2VA",
            "8",
        )
        self.assertIn("SOURCE VISUAL DRAFT", text)
        self.assertIn("Pack and preserve", text)
        self.assertIn("pack", text.lower())
        self.assertIn("preserve", text.lower())
        self.assertIn("COMPOSITION AND CAMERA", text)
        self.assertIn("原样保留 9:16", text)
        self.assertNotIn("rewrite-from-scratch", text.lower().replace(" ", "-"))
        self.assertNotIn("rewrite from scratch", text.lower())
        self.assertNotIn("必须展开进画面正文", text)
        self.assertNotIn("Fill only missing", text)

    def test_sanitize_beat_draft_strips_empty_quotes_inner_leak_and_lipsync(self):
        inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
        spoken_a = "大爷，我什么都可以做。"
        spoken_b = "不用想也知道，做的是什么。"
        dialogue = (
            f"沙丽丽：“{spoken_a}” "
            f"吴耐（内心）：“{inner}” "
            f"吴耐：“{spoken_b}”"
        )
        original = {
            "action": (
                f"她讨好。沙丽丽：“” 吴耐（内心）：“{inner}” 吴耐：“”。"
                f"本镜对白必须口型同步：{dialogue}。收束：定格。"
            ),
            "visual_prompt": (
                "Photorealistic camera lighting. Lip-sync the exact Chinese line(s): "
                f"{dialogue}. Do not translate the line onto the picture. "
                f"沙丽丽：“” 吴耐（内心）：“{inner}” 吴耐：“”."
            ),
            "video_prompt_zh": f"本镜对白必须口型同步：{dialogue}。收束：定格。",
            "dialogue": dialogue,
            "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
            "existing_prompt": f"old prompt repeats {inner} and {inner}",
            "audio": "电梯嗡鸣",
        }
        draft = H3PromptBuilder.sanitize_beat_draft(original)
        self.assertNotIn("existing_prompt", draft)
        self.assertIn("existing_prompt", original)
        self.assertNotIn("：“”", draft["action"])
        self.assertNotIn("：“”", draft["visual_prompt"])
        self.assertNotIn(inner, draft["action"])
        self.assertNotIn(inner, draft["visual_prompt"])
        self.assertNotIn(inner, draft["video_prompt_zh"])
        self.assertNotIn("本镜对白必须口型同步", draft["action"])
        self.assertNotIn("本镜对白必须口型同步", draft["video_prompt_zh"])
        self.assertNotIn("Lip-sync the exact Chinese line(s)", draft["visual_prompt"])
        self.assertNotIn(spoken_a.rstrip("。"), draft["visual_prompt"])
        self.assertNotIn(spoken_b.rstrip("。"), draft["visual_prompt"])
        self.assertIn(inner, draft["dialogue"])
        self.assertIn("电梯嗡鸣", draft["audio"])

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
            f"(S1) 沙丽丽 says <d>[Chinese] 八字, 我什么都可以做。</d>. "
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
        self.assertNotIn("八字", prepared)
        tags = [
            item.strip()
            for item in re.findall(r"<d>\[Chinese\]\s*(.*?)</d>", prepared, flags=re.S)
        ]
        self.assertEqual(tags, [spoken_a, inner, spoken_b])
        self.assertIn("<Picture 1>", prepared)
        self.assertIn("<Picture 2>", prepared)
        self.assertIn("<Picture 3>", prepared)
        self.assertRegex(prepared, r"off[\s-]?screen")

        with patch.object(LlmService, "_request_h3_prompt", return_value=flawed) as request:
            generated = LlmService.generate_h3_prompt(beat_info)
        request.assert_not_called()
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", beat_info))
        self.assertIn(spoken_a, generated)
        self.assertNotIn("八字", generated)

        omitted = (
            "subject_definitions:\nTwo people stand in an elevator without reference tags.\n"
            "summary:\n[reference generation + audio reference] An eight-second scene.\n"
            "retention_analysis:\nfully_preserved.\n"
            f"detailed_description:\n[Shot 1] {detail} Someone looks around. "
            "The shot holds long enough for complete unhurried dialogue and a natural pause.\n"
            "overall_soundscape:\nQuiet room sound and synchronized movement.\n"
            "non_diegetic_music:\nRestrained piano at a slow tempo with a soft ending."
        )
        self.assertTrue(
            any("verbatim" in item for item in LlmService._validate_h3_prompt(omitted, "Ref2VA", beat_info))
        )
        recovered = H3PromptBuilder.prepare_generated_prompt(
            omitted,
            H3PromptBuilder.shot_from_beat_info(beat_info),
        )
        self.assertEqual([], LlmService._validate_h3_prompt(recovered, "Ref2VA", beat_info))
        self.assertIn(spoken_a, recovered)
        self.assertIn(spoken_b, recovered)
        self.assertIn(inner, recovered)

    def test_prepare_fills_dialogue_tokens_in_place_before_freeze(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_a = "大爷，我什么都可以做。那个，那个房租下个月一定给你。"
        spoken_b = "不用想也知道，做的是什么。"
        inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
        beat_info = {
            "sequence": 1,
            "dialogue": (
                f"沙丽丽：“{spoken_a}” "
                f"吴耐（内心）：“{inner}” "
                f"吴耐：“{spoken_b}”"
            ),
            "narration": inner,
            "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
            "scene_name": "电梯",
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "沙丽丽", "category": "character"},
                {"index": 3, "name": "电梯", "category": "scene"},
            ],
        }
        detail = " ".join(
            [
                "The camera holds a stable medium composition while natural lighting defines the room, "
                "the subject performs a precise visible action, and synchronized sound follows every contact."
            ]
            * 24
        )
        packed = (
            "subject_definitions:\n"
            "<Subject 1> is Wu Nai in <Picture 1>. "
            "<Subject 2> is Sha Lili in <Picture 2>. "
            "<Subject 3> is the elevator in <Picture 3>.\n"
            "summary:\n[reference generation + audio reference] An elevator beat.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n"
            f"[Shot 1] {detail} A medium-close shot tilts up to Sha Lili's face. "
            "{{D1}} The camera then pushes to Wu Nai's medium-close, where his lips remain closed "
            "as he looks down her outfit. {{D2}} The camera pushes back to his face. "
            "{{D3}} After the last syllable, the shot freezes on Wu Nai's expression for about one second.\n"
            "overall_soundscape:\nElevator hum and synchronized movement.\n"
            "non_diegetic_music:\nN/A"
        )
        prepared = H3PromptBuilder.prepare_generated_prompt(
            packed,
            H3PromptBuilder.shot_from_beat_info(beat_info),
        )
        self.assertEqual([], LlmService._validate_h3_prompt(prepared, "Ref2VA", beat_info))
        self.assertNotIn("{{D1}}", prepared)
        self.assertNotIn("{{D2}}", prepared)
        self.assertNotIn("{{D3}}", prepared)
        self.assertLess(prepared.find("tilts up"), prepared.find(spoken_a))
        self.assertLess(prepared.find(spoken_a), prepared.find(inner))
        self.assertLess(prepared.find(inner), prepared.find(spoken_b))
        self.assertLess(prepared.find(spoken_b), prepared.lower().find("freezes"))
        self.assertIn("medium-close", prepared)
        self.assertNotIn("medium-clos in a casual", prepared)

        leftover = packed.replace("{{D1}}", f"Sha Lili says <d>[Chinese] {spoken_a}</d> in a casual young female voice with a forced pleasant tone,")
        leftover = leftover.replace("{{D2}}", "")
        leftover = leftover.replace(
            "{{D3}}",
            f"Wu Nai says <d>[Chinese] {spoken_b}</d> in a cold, low-pitched male voice with a stern cadence,",
        )
        repaired = H3PromptBuilder.prepare_generated_prompt(
            leftover,
            H3PromptBuilder.shot_from_beat_info(beat_info),
        )
        self.assertEqual([], LlmService._validate_h3_prompt(repaired, "Ref2VA", beat_info))
        self.assertNotIn("in a casual young female voice", repaired)
        self.assertNotIn("in a cold, low-pitched male voice", repaired)
        self.assertIn("medium-close", repaired)
        self.assertLess(repaired.find(spoken_b), repaired.lower().find("freezes"))

    def test_prepare_repairs_speaker_ids_glue_holds_and_location_for_any_two_hander(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_a = "这是第一句对白。"
        inner = "这是听者的内心独白。"
        spoken_b = "这是第二句对白。"
        beat_info = {
            "sequence": 8,
            "dialogue": (
                f"角色乙：“{spoken_a}” "
                f"角色甲（内心）：“{inner}” "
                f"角色甲：“{spoken_b}”"
            ),
            "narration": inner,
            "characters": [{"name": "角色甲"}, {"name": "角色乙"}],
            "scene_name": "走廊",
            "ref_images": [
                {"index": 1, "name": "角色甲", "category": "character"},
                {"index": 2, "name": "角色乙", "category": "character"},
                {"index": 3, "name": "走廊", "category": "scene"},
            ],
        }
        shot = H3PromptBuilder.shot_from_beat_info(beat_info)
        speaker_map = H3PromptBuilder._speaker_map([shot])
        self.assertEqual(speaker_map["角色甲"], "S1")
        self.assertEqual(speaker_map["角色乙"], "S2")
        detail = " ".join(
            [
                "The camera holds a stable medium composition while natural lighting defines the room, "
                "the subject performs a precise visible action, and synchronized sound follows every contact."
            ]
            * 24
        )
        packed = (
            "subject_definitions:\n"
            "<Subject 1> is character A in <Picture 1>. "
            "<Subject 2> is character B in <Picture 2>. "
            "<Location 1> is the corridor in <Picture 3>.\n"
            "summary:\n[reference generation] A two-person beat.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n"
            f"[Shot 1] {detail} The camera tilts up to <Subject 2> (S2). "
            "<Subject 2> (S2) first speaks with {{D1}}. "
            "The camera then pushes to <Subject 1> (S1) and tilts down the outfit. "
            "She then forces a smile before continuing with {{D2}}. "
            "The camera holds on his face. Following this, "
            "{{D3}} spoken by character A (S1). After the last line, the camera holds on "
            "his expression for one second before freezing. All dialogue is lip-synced, and no music "
            "is audible during speech.\n"
            "overall_soundscape:\nCorridor hum and synchronized movement.\n"
            "non_diegetic_music:\nN/A"
        )
        prepared = H3PromptBuilder.prepare_generated_prompt(packed, shot)
        self.assertEqual([], LlmService._validate_h3_prompt(prepared, "Ref2VA", beat_info))
        self.assertIn("(S2) <Subject 2> 角色乙 says", prepared)
        self.assertIn("(S1) <Subject 1> 角色甲 says", prepared)
        self.assertNotIn("(S1) <Subject 2>", prepared)
        self.assertNotIn("speaks with", prepared.lower())
        self.assertNotIn("continuing with", prepared.lower())
        self.assertNotIn("spoken by", prepared.lower())
        self.assertNotIn("<Location 1>", prepared)
        self.assertIn("<Subject 3>", prepared)
        self.assertEqual(
            prepared.lower().count("the shot holds long enough for the complete unhurried speech"),
            2,
        )
        self.assertIn("Spoken lines are lip-synced; inner voice stays off-screen", prepared)
        self.assertLess(prepared.find(spoken_a), prepared.find(inner))
        self.assertLess(prepared.find(inner), prepared.find(spoken_b))
        self.assertLess(prepared.find(spoken_b), prepared.lower().find("freezing"))
        self.assertLess(prepared.find("tilts up"), prepared.find(spoken_a))
        self.assertLess(prepared.find(spoken_a), prepared.find("pushes to"))
        self.assertLess(prepared.find("pushes to"), prepared.find(inner))

    def test_prepare_strips_copied_slot_legends_and_wrong_speaker_cues(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_a = "这是第一句对白。"
        inner = "这是听者的内心独白。"
        spoken_b = "这是第二句对白。"
        beat_info = {
            "sequence": 9,
            "dialogue": (
                f"角色乙：“{spoken_a}” "
                f"角色甲（内心）：“{inner}” "
                f"角色甲：“{spoken_b}”"
            ),
            "narration": inner,
            "characters": [{"name": "角色甲"}, {"name": "角色乙"}],
            "scene_name": "走廊",
            "ref_images": [
                {"index": 1, "name": "角色甲", "category": "character"},
                {"index": 2, "name": "角色乙", "category": "character"},
                {"index": 3, "name": "走廊", "category": "scene"},
            ],
        }
        shot = H3PromptBuilder.shot_from_beat_info(beat_info)
        detail = " ".join(
            [
                "The camera holds a stable medium composition while natural lighting defines the room, "
                "the subject performs a precise visible action, and synchronized sound follows every contact."
            ]
            * 24
        )
        packed = (
            "subject_definitions:\n"
            "<Subject 1> is character A in <Picture 1>. "
            "<Subject 2> is character B in <Picture 2>. "
            "<Subject 3> is the corridor in <Picture 3>.\n"
            "summary:\n[reference generation] A two-person beat.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n"
            f"[Shot 1] {detail} Character A (S1) then speaks, his voice cold and knowing. "
            "{{D1}} spoken lip-sync — Character B (S2) <Subject 2> After Character A's line, "
            "the camera holds on his expression for one second. "
            "In an off-screen inner voiceover, all visible characters keep their lips closed: "
            "{{D2}}.. inner off-screen, lips closed; listener thought, not the previous speaker "
            "continuing — Character A (S1) <Subject 1> "
            "{{D3}}\n"
            "overall_soundscape:\nCorridor hum and synchronized movement.\n"
            "non_diegetic_music:\nN/A"
        )
        prepared = H3PromptBuilder.prepare_generated_prompt(packed, shot)
        self.assertEqual([], LlmService._validate_h3_prompt(prepared, "Ref2VA", beat_info))
        self.assertIn("(S2) <Subject 2> 角色乙 says", prepared)
        self.assertIn("(S1) <Subject 1> 角色甲 says", prepared)
        self.assertIn("(S1) <Subject 1> 角色甲 thinks", prepared)
        self.assertNotIn("then speaks", prepared.lower())
        self.assertNotIn("spoken lip-sync", prepared.lower())
        self.assertNotIn("listener thought, not the previous speaker continuing", prepared.lower())
        self.assertNotIn("After Character A's line", prepared)
        self.assertNotIn("</d>..", prepared)
        self.assertLess(prepared.find(spoken_a), prepared.find(inner))
        self.assertLess(prepared.find(inner), prepared.find(spoken_b))

    def test_prepare_repairs_tone_glue_truncated_names_and_clustered_inner(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_a = "这是第一句对白。"
        inner = "这是听者的内心独白。"
        spoken_b = "这是第二句对白。"
        beat_info = {
            "sequence": 12,
            "dialogue": (
                f"角色乙：“{spoken_a}” "
                f"角色甲（内心）：“{inner}” "
                f"角色甲：“{spoken_b}”"
            ),
            "narration": inner,
            "characters": [{"name": "角色甲"}, {"name": "角色乙"}],
            "scene_name": "走廊",
            "ref_images": [
                {"index": 1, "name": "角色甲", "category": "character"},
                {"index": 2, "name": "角色乙", "category": "character"},
                {"index": 3, "name": "走廊", "category": "scene"},
            ],
        }
        shot = H3PromptBuilder.shot_from_beat_info(beat_info)
        detail = " ".join(
            [
                "The camera holds a stable medium composition while natural lighting defines the room, "
                "the subject performs a precise visible action, and synchronized sound follows every contact."
            ]
            * 24
        )
        packed = (
            "subject_definitions:\n"
            "<Subject 1> is the listener Alan West in <Picture 1>. "
            "<Subject 2> is the speaker Bella Chen in <Picture 2>. "
            "<Subject 3> is the corridor in <Picture 3>.\n"
            "summary:\n[reference generation] A two-person beat.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n"
            f"[Shot 1] {detail} A medium-close shot starts at the waist, slowly tilting up to the face. "
            "She speaks first with a casual tone, {{D1}} "
            "She pauses slightly before continuing, The camera then slowly pushes to Alan West. "
            "He keeps his mouth closed as his eyes travel downward. "
            "The camera follows his gaze downward along the outfit. "
            "After a brief moment, the camera pushes back to focus on Alan Wes{{D2}}{{D3}}\n"
            "overall_soundscape:\nCorridor hum and synchronized movement.\n"
            "non_diegetic_music:\nN/A"
        )
        prepared = H3PromptBuilder.prepare_generated_prompt(packed, shot)
        self.assertEqual([], LlmService._validate_h3_prompt(prepared, "Ref2VA", beat_info))
        self.assertNotIn("speaks first with a casual tone", prepared.lower())
        self.assertNotIn("before continuing", prepared.lower())
        self.assertNotIn("Alan Wes(S1)", prepared)
        self.assertIn("Alan West. (S1)", prepared)
        self.assertIn("holds on the closed mouth", prepared.lower())
        self.assertLess(prepared.find(spoken_a), prepared.find("pushes to Alan West"))
        self.assertLess(prepared.find("follows his gaze"), prepared.find(inner))
        self.assertLess(prepared.find(inner), prepared.find("closed mouth"))
        self.assertLess(prepared.find("closed mouth"), prepared.find(spoken_b))

    def test_speech_contract_rejects_camera_dump_before_all_speech(self):
        spoken_a = "这是第一句对白。"
        inner = "这是听者的内心独白。"
        spoken_b = "这是第二句对白。"
        beat_info = {
            "sequence": 10,
            "dialogue": (
                f"角色乙：“{spoken_a}” "
                f"角色甲（内心）：“{inner}” "
                f"角色甲：“{spoken_b}”"
            ),
            "narration": inner,
            "characters": [{"name": "角色甲"}, {"name": "角色乙"}],
            "scene_name": "走廊",
            "ref_images": [
                {"index": 1, "name": "角色甲", "category": "character"},
                {"index": 2, "name": "角色乙", "category": "character"},
                {"index": 3, "name": "走廊", "category": "scene"},
            ],
        }
        shot = H3PromptBuilder.shot_from_beat_info(beat_info)
        speaker_map = H3PromptBuilder._speaker_map([shot])
        detail = " ".join(
            [
                "The camera holds a stable medium composition while natural lighting defines the room, "
                "the subject performs a precise visible action, and synchronized sound follows every contact."
            ]
            * 24
        )
        dumped = (
            "subject_definitions:\n"
            "<Subject 1> is character A in <Picture 1>. "
            "<Subject 2> is character B in <Picture 2>. "
            "<Subject 3> is the corridor in <Picture 3>.\n"
            "summary:\n[reference generation] A two-person beat.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n"
            f"[Shot 1] {detail} The camera slowly tilts up to the face and pushes in slightly, "
            "then follows his gaze down the outfit. "
            f"(S2) <Subject 2> 角色乙 says <d>[Chinese] {spoken_a}</d>. "
            "The shot holds long enough for the complete unhurried speech and a natural pause. "
            f"(S1) <Subject 1> 角色甲 thinks. In an off-screen inner voiceover, "
            f"all visible characters keep their lips closed: <d>[Chinese] {inner}</d>. "
            f"(S1) <Subject 1> 角色甲 says <d>[Chinese] {spoken_b}</d>. "
            "The shot holds long enough for the complete unhurried speech and a natural pause.\n"
            "overall_soundscape:\nCorridor hum and synchronized movement.\n"
            "non_diegetic_music:\nN/A"
        )
        errors = H3PromptBuilder.speech_contract_errors(dumped, shot)
        self.assertTrue(any("interleave" in item for item in errors))
        retry = H3PromptBuilder.packing_retry_block(errors, dumped)
        self.assertIn("Rewrite only [Shot 1] blocking", retry)
        self.assertIn("(S2) <Subject 2> 角色乙 says", H3PromptBuilder._required_contract(shot, speaker_map))

    def test_packing_user_prompt_keeps_tokens_away_from_slot_legends(self):
        beat_info = {
            "sequence": 11,
            "dialogue": "角色乙：“第一句。” 角色甲（内心）：“心里话。” 角色甲：“第二句。”",
            "narration": "心里话。",
            "characters": [{"name": "角色甲"}, {"name": "角色乙"}],
            "scene_name": "走廊",
            "ref_images": [
                {"index": 1, "name": "角色甲", "category": "character"},
                {"index": 2, "name": "角色乙", "category": "character"},
                {"index": 3, "name": "走廊", "category": "scene"},
            ],
        }
        user = H3PromptBuilder.build_packing_user_prompt(beat_info, "Ref2VA", 15)
        self.assertIn("SPEECH TOKENS", user)
        self.assertIn("SPEECH OWNERS", user)
        self.assertIn("- {{D1}}", user)
        self.assertIn("D1:", user)
        self.assertNotIn("{{D1}} spoken lip-sync", user)
        self.assertNotIn("spoken lip-sync —", user)
        self.assertIn("禁止抄进 [Shot 1]", user)

    def test_prepare_collapses_interleaved_english_spoken_fragments(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_wu = "算了，房租免了。"
        spoken_sha = "啊？大爷你不要房租？该不会想让我那啥吧？我是正经人，卖艺不卖身的。"
        beat_info = {
            "sequence": 2,
            "dialogue": f"吴耐：“{spoken_wu}” 沙丽丽：“{spoken_sha}”",
            "action": (
                "双人中景，吴耐挥手说算了，房租免了。沙丽丽眼睛瞪大啊一声，双手把绿手机护在胸口。"
                "她追问大爷你不要房租，又皱眉护胸：该不会想让我那啥吧。她声明我是正经人。"
                "她补一句卖艺不卖身的。"
                f"本镜对白必须口型同步：吴耐：“{spoken_wu}” 沙丽丽：“{spoken_sha}”。收束：定格。"
            ),
            "visual_prompt": (
                "Photorealistic camera lighting COMPOSITION AND CAMERA. "
                "Lip-sync the exact Chinese line(s): "
                f"吴耐：“{spoken_wu}” 沙丽丽：“{spoken_sha}”. "
                "Do not translate the line onto the picture. SYNCHRONIZED SOUND: 电梯嗡鸣."
            ),
            "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
            "scene_name": "电梯",
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "沙丽丽", "category": "character"},
                {"index": 3, "name": "电梯", "category": "scene"},
            ],
        }
        draft = H3PromptBuilder.sanitize_beat_draft(beat_info)
        self.assertNotIn(spoken_sha, draft["visual_prompt"])
        self.assertNotIn("大爷你不要房租", draft["action"])
        self.assertNotIn("卖艺不卖身的", draft["action"])

        interleaved = (
            "Sha Lili eyes wide 啊 then asks 大爷你不要房租 then "
            "该不会想让我那啥吧 then 我是正经人 then 卖艺不卖身的"
        )
        flawed = (
            rich_prompt(spoken_wu)
            .replace("<Subject 2> is the environment anchored by <Picture 2>.", "")
            .replace(
                f"(S1) says <d>[Chinese] {spoken_wu}</d>.",
                f"{interleaved} (S1) 吴耐 says <d>[Chinese] {spoken_wu}</d>. "
                f"(S2) 沙丽丽 says <d>[Chinese] {spoken_sha}</d>.",
            )
        )
        self.assertGreater(H3PromptBuilder.count_han_line(flawed, spoken_sha), 1)
        prepared = H3PromptBuilder.prepare_generated_prompt(
            flawed,
            H3PromptBuilder.shot_from_beat_info(beat_info),
        )
        self.assertEqual([], LlmService._validate_h3_prompt(prepared, "Ref2VA", beat_info))
        self.assertEqual(1, H3PromptBuilder.count_han_line(prepared, spoken_sha))
        self.assertEqual(1, H3PromptBuilder.count_han_line(prepared, spoken_wu))
        self.assertIn(f"<d>[Chinese] {spoken_sha}</d>", prepared)

        with patch.object(LlmService, "_request_h3_prompt", return_value=flawed) as request:
            generated = LlmService.generate_h3_prompt(beat_info)
        request.assert_not_called()
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", beat_info))

    def test_h3_system_prompt_uses_packing_contract(self):
        from backend.app.media_studio.services.llm_service import LlmService

        system = LlmService._h3_system_prompt("Ref2VA", "8")
        self.assertIn("prompt packer", system)
        self.assertIn("Do not write a new scene", system)
        self.assertIn("preserve", system.lower())
        self.assertIn("SOURCE VISUAL DRAFT", system)
        self.assertIn("[Shot 1]", system)
        self.assertNotIn("Write at least 320", system)
        self.assertNotIn("展开 320", system)
        self.assertNotIn("Expand the beat", system)
        self.assertIn("Shot timing budget", system)
        self.assertIn("do not cram dialogue + walk + turn into 5s", system)
        self.assertIn("Do NOT emit At HH:MM.SSS", system)
        self.assertIn("Never copy the same Chinese sentence twice", system)
        self.assertIn("Never lip-sync inner voice", system)
        self.assertIn("{{D1}}", system)
        self.assertIn("renderer substitutes", system.lower())
        self.assertIn("do not emit", system.lower())
        self.assertIn("Interleave", system)
        self.assertIn("slot legends", system)
        self.assertIn("X then speaks", system)
        self.assertIn("speaks first with a tone", system)
        self.assertIn("closed-mouth camera beat", system)
        self.assertIn("(Sn) is always <Subject n>", system)
        self.assertIn("Location", system)
        self.assertLess(len(system.encode("utf-8")), 12 * 1024)
        self.assertIn("subject_definitions:", system)
        self.assertIn("<Subject 1> is the coffee-shop environment", system)
        self.assertIn("CAST LOCK", system)
        self.assertNotIn("This guide explains how rewrite outputs are organized", system)

        eleven = LlmService._h3_system_prompt("Ref2VA", "11")
        self.assertIn("11-second performance", eleven)
        self.assertIn("lasting 11 seconds", eleven)
        self.assertIn("duration_seconds is 11", eleven)

    def test_generate_h3_prompt_renders_ref2va_without_llm(self):
        from backend.app.media_studio.services.llm_service import LlmService

        with patch.object(LlmService, "_request_h3_prompt") as request:
            generated = LlmService.generate_h3_prompt({
                "dialogue": "你好。",
                "ref_images": [{"index": 1}, {"index": 2}],
            })
        request.assert_not_called()
        self.assertIn("你好。", generated)
        self.assertIn("<Subject 1>", generated)
        self.assertIn("[Shot 1]", generated)
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", {
            "dialogue": "你好。",
            "ref_images": [{"index": 1}, {"index": 2}],
        }))

    def test_generate_h3_prompt_skill_pack_raises_when_author_fails(self):
        from backend.app.media_studio.services.llm_service import LlmService
        from backend.app.skill_packs.recipe import HALF_NARRATED_PACK_ID

        beat_info = {
            "dialogue": "你好。",
            "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
            "skill_pack_id": HALF_NARRATED_PACK_ID,
        }
        with patch.object(LlmService, "author_timestamped_zh_prompt", side_effect=RuntimeError("skip")):
            with patch.object(LlmService, "_request_h3_prompt") as request:
                with self.assertRaises(RuntimeError):
                    LlmService.generate_h3_prompt(beat_info)
        request.assert_not_called()
        self.assertNotIn(_THICKNESS_PAD, str(beat_info.get("h3_prompt") or ""))
        self.assertNotIn("The camera holds a stable medium composition", str(beat_info.get("h3_prompt") or ""))

    def test_generate_h3_prompt_raises_when_packing_breaks_shell(self):
        from backend.app.media_studio.services.llm_service import LlmService

        beat_info = {
            "dialogue": "你好。",
            "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
            "skill_pack_id": HALF_NARRATED_PACK_ID,
        }
        with patch.object(LlmService, "author_timestamped_zh_prompt", side_effect=RuntimeError("skip")):
            with patch.object(LlmService, "_request_h3_prompt") as request:
                with self.assertRaises(RuntimeError):
                    LlmService.generate_h3_prompt(beat_info)
        request.assert_not_called()
        self.assertNotIn(_THICKNESS_PAD, str(beat_info.get("h3_prompt") or ""))

    def test_generate_h3_prompt_skips_second_pack_when_dual_en_valid(self):
        from backend.app.media_studio.services.llm_service import DualShotAuthorResult, LlmService
        from backend.app.vision_runtime import VISION_STATUS_USED, VisionCallMeta

        beat_info = {
            "dialogue": "你好。",
            "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
            "skill_pack_id": HALF_NARRATED_PACK_ID,
        }
        packed = short_authored_en("你好。")
        result = DualShotAuthorResult(
            zh_prompt=(
                "镜头目的：开门\n参考素材：<Picture 1>\n必须出现的视觉内容：门\n"
                "按旁白和画面内容切镜：00:00–00:08 开口\n对白：你好。\n旁白：无\n画面要求：9:16\n负向约束：无分栏"
            ),
            en_prompt=packed,
            en_valid=True,
            vision=VisionCallMeta(status=VISION_STATUS_USED, model="gpt-5.6-sol", image_count=3, source="llm"),
        )
        with patch.object(LlmService, "author_timestamped_zh_prompt", return_value=result):
            with patch.object(LlmService, "_request_h3_prompt") as request:
                generated = LlmService.generate_h3_prompt(beat_info)
        request.assert_not_called()
        self.assertIn("[Shot 1]", generated)
        self.assertIn("你好。", generated)
        self.assertNotIn(_THICKNESS_PAD, generated)
        self.assertEqual("used", beat_info.get("vision_status"))
        self.assertEqual("gpt-5.6-sol", beat_info.get("vision_model"))
        self.assertEqual(3, beat_info.get("vision_image_count"))
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", beat_info))

    def test_generate_h3_prompt_raises_when_dual_en_invalid(self):
        from backend.app.media_studio.services.llm_service import DualShotAuthorError, DualShotAuthorResult, LlmService
        from backend.app.vision_runtime import VISION_STATUS_USED, VisionCallMeta

        beat_info = {
            "dialogue": "你好。",
            "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
            "skill_pack_id": HALF_NARRATED_PACK_ID,
        }
        result = DualShotAuthorResult(
            zh_prompt=(
                "镜头目的：开门\n参考素材：<Picture 1>\n必须出现的视觉内容：门\n"
                "按旁白和画面内容切镜：00:00–00:08 开口\n对白：你好。\n旁白：无\n画面要求：9:16\n负向约束：无分栏"
            ),
            en_prompt="broken packing without headings",
            en_valid=False,
            vision=VisionCallMeta(status=VISION_STATUS_USED, model="gpt-5.6-sol", image_count=3, source="llm"),
        )
        with patch.object(LlmService, "author_timestamped_zh_prompt", return_value=result):
            with patch.object(LlmService, "_request_h3_prompt") as request:
                with self.assertRaises(DualShotAuthorError) as raised:
                    LlmService.generate_h3_prompt(beat_info)
        request.assert_not_called()
        self.assertIn("英文六段", str(raised.exception))
        self.assertNotIn(_THICKNESS_PAD, str(beat_info.get("h3_prompt") or ""))
        self.assertNotIn("The camera holds a stable medium composition", str(beat_info.get("h3_prompt") or ""))

    def test_generate_h3_prompt_skip_program_pack_keeps_authored_en(self):
        from backend.app.media_studio.services.llm_service import DualShotAuthorResult, LlmService
        from backend.app.vision_runtime import VISION_STATUS_USED, VisionCallMeta

        authored = short_authored_en("你好。")
        beat_info = {
            "dialogue": "你好。",
            "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
            "skill_pack_id": HALF_NARRATED_PACK_ID,
        }
        result = DualShotAuthorResult(
            zh_prompt=(
                "镜头目的：走廊\n参考素材：<Picture 1> <Picture 2> <Picture 3>\n必须出现的视觉内容：走廊\n"
                "按旁白和画面内容切镜：00:00–00:08 开口\n对白：你好。\n旁白：无\n画面要求：9:16\n负向约束：无分栏"
            ),
            en_prompt=authored,
            en_valid=True,
            vision=VisionCallMeta(status=VISION_STATUS_USED, model="gpt-5.6-sol", image_count=3, source="llm"),
        )
        with patch.object(LlmService, "author_timestamped_zh_prompt", return_value=result):
            with patch.object(LlmService, "_request_h3_prompt") as request:
                generated = LlmService.generate_h3_prompt(beat_info)
        request.assert_not_called()
        self.assertIn("The camera tracks down the corridor", generated)
        self.assertIn("<Picture 1>", generated)
        self.assertNotIn("<picture 1>", generated)
        self.assertNotIn("The camera holds a stable medium composition", generated)
        self.assertNotIn("Already inside the closed cabin", generated)
        self.assertNotIn(_THICKNESS_PAD, generated)
        self.assertNotRegex(generated, r"00:00\s*[–\-]\s*00:")
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", beat_info))

    def test_prepare_appends_missing_non_diegetic_heading(self):
        prompt = rich_prompt().replace(
            "\nnon_diegetic_music:\nRestrained piano at a slow tempo with a soft ending.",
            "",
        )
        beat_info = {
            "dialogue": "你好。",
            "ref_images": [{"index": 1}, {"index": 2}],
        }
        shot = H3PromptBuilder.shot_from_beat_info(beat_info)
        prepared = H3PromptBuilder.prepare_generated_prompt(prompt, shot)
        self.assertRegex(prepared, r"(?m)^subject_definitions:")
        self.assertRegex(prepared, r"(?m)^summary:")
        self.assertRegex(prepared, r"(?m)^retention_analysis:")
        self.assertRegex(prepared, r"(?m)^detailed_description:")
        self.assertRegex(prepared, r"(?m)^overall_soundscape:")
        self.assertRegex(prepared, r"(?m)^non_diegetic_music:")
        self.assertEqual([], LlmService._validate_h3_prompt(prepared, "Ref2VA", beat_info))

    def test_generate_h3_prompt_raises_when_packing_omits_last_heading(self):
        from backend.app.media_studio.services.llm_service import DualShotAuthorError, DualShotAuthorResult, LlmService
        from backend.app.vision_runtime import VisionCallMeta

        beat_info = {
            "dialogue": "你好。",
            "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
            "skill_pack_id": HALF_NARRATED_PACK_ID,
        }
        authored = short_authored_en("你好。").replace(
            "\nnon_diegetic_music:\nNone.",
            "",
        )
        result = DualShotAuthorResult(
            zh_prompt=(
                "镜头目的：走廊\n参考素材：<Picture 1> <Picture 2> <Picture 3>\n必须出现的视觉内容：走廊\n"
                "按旁白和画面内容切镜：00:00–00:08 开口\n对白：你好。\n旁白：无\n画面要求：9:16\n负向约束：无分栏"
            ),
            en_prompt=authored,
            en_valid=True,
            vision=VisionCallMeta(status="unavailable"),
        )
        with patch.object(LlmService, "author_timestamped_zh_prompt", return_value=result):
            with patch.object(LlmService, "_request_h3_prompt") as request:
                with self.assertRaises(DualShotAuthorError) as raised:
                    LlmService.generate_h3_prompt(beat_info)
        request.assert_not_called()
        self.assertIn("英文六段", str(raised.exception))
        self.assertNotIn(_THICKNESS_PAD, str(beat_info.get("h3_prompt") or ""))

    def test_overlay_packed_detail_skips_retention_shot_marker(self):
        shell = rich_prompt("你好。")
        packed = (
            "retention_analysis:\n"
            "<Subject 1> (appears in [Shot 1]): fully_preserved - identity from <Picture 1> is retained.\n"
            "detailed_description:\n"
            "[Shot 1] The camera holds a medium shot while lighting and ambient sound continue. "
            "(S1) says <d>[Chinese] 你好。</d>.\n"
            "overall_soundscape:\nQuiet room sound.\n"
        )
        merged = H3PromptBuilder.overlay_packed_detail(shell, packed)
        detail = merged.split("detailed_description:", 1)[-1].split("overall_soundscape:", 1)[0]
        self.assertIn("你好。", detail)
        self.assertNotIn("fully_preserved", detail)
        self.assertEqual(1, merged.count("detailed_description:"))
        self.assertEqual(1, merged.count("overall_soundscape:"))

    def test_faithful_zh_pack_keeps_design_schedule_without_coverage_inserts(self):
        from backend.app.director_craft.coverage import CLAUSE_PUSH_IN, CLAUSE_TILT_UP
        from backend.app.skill_packs import get_pack
        from backend.app.skill_packs.handlers import bind_r2v_slot_images

        spoken_a = "大爷，我什么都可以做。"
        spoken_b = "您就当做好事。"
        inner = "浓妆艳抹，黑色小短裙。"
        zh = (
            "镜头1，总时长11秒，内部时间从00:00开始。\n"
            "镜头目的：上摇挂两句，下摇内心，再推近吴耐。\n\n"
            "参考素材：\n- <Picture 1> 吴耐角色卡\n- <Picture 2> 沙丽丽角色卡\n"
            "- <Picture 3> 电梯场景卡\n- <Picture 4> 起幅单帧锚点\n\n"
            "必须出现的视觉内容：\n- 轿厢内站定\n- 上摇两句\n- 下摇内心再推近\n\n"
            "按旁白和画面内容切镜：\n"
            f"- 00:00–00:05：上摇过程中吴耐说「{spoken_a}」「{spoken_b}」。\n"
            f"- 00:05–00:08：下摇到沙丽丽胸腰，内心「{inner}」，画内闭嘴。\n"
            "- 00:08–00:11：推近吴耐并稳住。\n\n"
            "对白：\n"
            f"- 吴耐在 00:00–00:05 说：“{spoken_a}”\n"
            f"- 吴耐在 00:00–00:05 说：“{spoken_b}”\n\n"
            "旁白：\n"
            f"- 00:05–00:08 内心：“{inner}”\n\n"
            "画面要求：\n- 上摇挂两句，再下摇，再推近\n\n"
            "负向约束：\n- 不要分栏，末槽只用起幅"
        )
        padding = " ".join(
            ["Stable photoreal lighting, camera, blocking and ambient sound continue."] * 24
        )
        packed = (
            "subject_definitions:\n"
            "<Subject 1> is 吴耐 in <Picture 1>. "
            "<Subject 2> is 沙丽丽 in <Picture 2>. "
            "<Subject 3> is the elevator in <Picture 3>. "
            "<Subject 4> is the start-frame still in <Picture 4>. "
            "<Picture 4> anchors opening blocking only; do not interpolate a full 16:9 triptych.\n"
            "summary:\n[reference generation] An eleven-second elevator beat.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n"
            f"[Shot 1] {padding} 00:00–00:05 The camera tilts up with small amplitude at slow speed. "
            f"(S1) <Subject 1> 吴耐 says <d>[Chinese] {spoken_a}</d>. "
            f"(S1) <Subject 1> 吴耐 says <d>[Chinese] {spoken_b}</d>. "
            "00:05–00:08 The camera tilts down with small amplitude at slow speed "
            "and holds a static shot on the chest-and-waist so the clothes fill the vertical frame. "
            f"(S1) <Subject 1> 吴耐 thinks. In an off-screen inner voiceover, "
            f"all visible characters keep their lips closed: <d>[Chinese] {inner}</d>. "
            "00:08–00:11 The camera pushes in with small amplitude at slow speed "
            "to a medium-close of Wu Nai and holds a static shot.\n"
            "overall_soundscape:\nElevator hum and synchronized movement.\n"
            "non_diegetic_music:\nN/A"
        )
        beat_info = {
            "sequence": 1,
            "dialogue": f"吴耐：“{spoken_a}” 吴耐：“{spoken_b}” 吴耐（内心）：“{inner}”",
            "camera": "上摇，下摇，推近",
            "action": "上摇说完两句，再下摇内心，再推近吴耐。已在电梯轿厢内站定。",
            "timestamped_zh_prompt": zh,
            "faithful_zh_pack": True,
            "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
            "scene_name": "电梯",
            "duration_seconds": 11,
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "沙丽丽", "category": "character"},
                {"index": 3, "name": "电梯", "category": "scene"},
                {
                    "index": 4,
                    "name": "起幅构图",
                    "category": "composition",
                    "source": "triptych.start",
                    "role": "start",
                    "url": "https://x/start.png",
                },
            ],
        }
        user = H3PromptBuilder.build_packing_user_prompt(beat_info, "Ref2VA", 11)
        self.assertIn("唯一调度权威", user)
        self.assertNotIn("必须写进对应 {{Dn}}", user)
        shot = H3PromptBuilder.shot_from_beat_info(beat_info)
        rendered = H3PromptBuilder.render_ref2va(shot)
        self.assertIn("Follow the Chinese timestamped", rendered)
        self.assertNotIn("tilts up with small amplitude at slow speed from a waist-level medium to a medium close-up", rendered)
        prepared = H3PromptBuilder.prepare_generated_prompt(packed, shot)
        detail = prepared.split("detailed_description:", 1)[-1].split("overall_soundscape:", 1)[0]
        self.assertLess(detail.lower().find("tilts up"), detail.find(spoken_a))
        self.assertLess(detail.find(spoken_a), detail.find(spoken_b))
        self.assertLess(detail.find(spoken_b), detail.lower().find("tilts down"))
        self.assertLess(detail.find(inner), detail.lower().find("pushes in"))
        self.assertEqual(1, detail.lower().count("tilts up"))
        self.assertEqual(2, len(re.findall(r"\bsays\b", detail, flags=re.I)))
        self.assertEqual(1, len(re.findall(r"\bthinks\b", detail, flags=re.I)))
        self.assertNotIn("to a medium close-up of the face and holds a static shot", prepared)
        self.assertNotIn(CLAUSE_TILT_UP, prepared)
        self.assertEqual(1, prepared.count(CLAUSE_PUSH_IN.format(who="Wu Nai")))
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        slots = bind_r2v_slot_images(
            recipe,
            {
                "characters": [{"id": "c-wu", "name": "吴耐", "url": "https://x/wu.png"}],
                "scene": "电梯",
                "scene_id": "s-el",
                "triptych_url": "https://x/triptych.png",
                "triptych_panels": {"start": "https://x/start.png", "mid": "https://x/mid.png"},
            },
            [
                {"id": "c-wu", "name": "吴耐", "extra": {"avatar_url": "https://x/wu.png"}},
                {"id": "s-el", "name": "电梯", "extra": {"master_url": "https://x/scene.png"}},
            ],
        )
        urls = [str(item.get("url") or "") for item in slots]
        self.assertEqual("https://x/start.png", urls[-1])
        self.assertNotIn("https://x/triptych.png", urls)

    def test_faithful_zh_skips_one_line_one_landing_windows(self):
        from backend.app.director_craft.coverage import CLAUSE_PUSH_IN, CLAUSE_TILT_UP
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_a = "大爷，我什么都可以做。"
        spoken_b = "那个，那个房租下个月一定给你。"
        inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
        spoken_c = "不用想也知道，做的是什么。"
        zh = (
            "镜头目的：上摇挂两句，下摇内心，再推近。\n"
            "参考素材：\n- 角色卡\n"
            "必须出现的视觉内容：\n- 已站定\n"
            "按旁白和画面内容切镜：\n"
            f"- 00:00–00:05：上摇过程中说「{spoken_a}」「{spoken_b}」。\n"
            f"- 00:05–00:10：下摇内心「{inner}」。\n"
            f"- 00:10–00:14：推近后说「{spoken_c}」。\n"
            "对白：\n- 有\n"
            "旁白：\n- 有\n"
            "画面要求：\n- 一镜到底\n"
            "负向约束：\n- 不要分栏"
        )
        padding = " ".join(
            ["Stable photoreal lighting, camera, blocking and ambient sound continue."] * 20
        )
        prompt = (
            "subject_definitions:\n"
            "<Subject 1> is 吴耐 in <Picture 1>. <Subject 2> is 沙丽丽 in <Picture 2>. "
            "<Subject 3> is the corridor in <Picture 3>. <Subject 4> is the start still in <Picture 4>.\n"
            "summary:\n[reference generation] A fifteen-second landing take.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n"
            f"[Shot 1] The camera tilts up with small amplitude at slow speed. {padding} "
            f"(S2) <Subject 2> 沙丽丽 says <d>[Chinese] {spoken_a}</d>. "
            f"(S2) <Subject 2> 沙丽丽 says <d>[Chinese] {spoken_b}</d>. "
            "(S1) <Subject 1> 吴耐 thinks. In an off-screen inner voiceover, "
            f"all visible characters keep their lips closed: <d>[Chinese] {inner}</d>. "
            f"(S1) <Subject 1> 吴耐 says <d>[Chinese] {spoken_c}</d>.\n"
            "overall_soundscape:\nAmbient landing sound and synchronized movement.\n"
            "non_diegetic_music:\nN/A"
        )
        beat_info = {
            "dialogue": (
                f"沙丽丽：“{spoken_a}” 沙丽丽：“{spoken_b}” "
                f"吴耐（内心）：“{inner}” 吴耐：“{spoken_c}”"
            ),
            "camera": "上摇，下摇，推近",
            "action": "已在电梯厅站定，不要开门。从腰上摇到脸。",
            "timestamped_zh_prompt": zh,
            "faithful_zh_pack": True,
            "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
            "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}, {"index": 4}],
        }
        errors = LlmService._validate_h3_prompt(prompt, "Ref2VA", beat_info)
        landing = [
            item for item in errors
            if "tilt up" in item or "push-in" in item or "coverage subject" in item
        ]
        self.assertEqual([], landing, errors)
        prepared = H3PromptBuilder.prepare_generated_prompt(
            prompt,
            H3PromptBuilder.shot_from_beat_info(beat_info),
        )
        self.assertNotIn(CLAUSE_TILT_UP, prepared)
        self.assertNotIn(CLAUSE_PUSH_IN.format(who="Wu Nai"), prepared)

    def test_prepare_generated_prompt_repairs_tilt_up_outside_speech_window(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken = "大爷，我什么都可以做。"
        padding = " ".join(["00:00–00:05 already inside the cabin with ambient detail and lighting."] * 12)
        prompt = rich_prompt(spoken).replace(
            f"(S1) says <d>[Chinese] {spoken}</d>.",
            f"The camera tilts up with small amplitude at slow speed from a waist-level medium. {padding} "
            f"(S1) says <d>[Chinese] {spoken}</d>.",
        )
        beat_info = {
            "dialogue": spoken,
            "camera": "上摇到脸",
            "action": "已在电梯轿厢内站定。",
            "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
        }
        shot = H3PromptBuilder.shot_from_beat_info(beat_info)
        self.assertIn("camera landing missing tilt up on first spoken beat", LlmService._validate_h3_prompt(prompt, "Ref2VA", beat_info))
        repaired = H3PromptBuilder.prepare_generated_prompt(prompt, shot)
        self.assertEqual([], LlmService._validate_h3_prompt(repaired, "Ref2VA", beat_info))
        self.assertRegex(repaired, r"tilts?\s+up")

    def test_prepare_generated_prompt_strips_elevator_doors_when_already_inside(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken = "大爷，我什么都可以做。"
        prompt = rich_prompt(spoken).replace(
            "[Shot 1]",
            "[Shot 1] Already inside the closed cabin. The elevator doors close behind them. ",
            1,
        )
        beat_info = {
            "dialogue": spoken,
            "camera": "上摇到脸",
            "action": "已在电梯轿厢内站定，不要开门。",
            "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
        }
        self.assertIn(
            "already-inside take must not show doors opening",
            LlmService._validate_h3_prompt(prompt, "Ref2VA", beat_info),
        )
        repaired = H3PromptBuilder.prepare_generated_prompt(
            prompt,
            H3PromptBuilder.shot_from_beat_info(beat_info),
        )
        self.assertNotIn(
            "already-inside take must not show doors opening",
            LlmService._validate_h3_prompt(repaired, "Ref2VA", beat_info),
        )

    def test_prepare_generated_prompt_repairs_missing_lighting_and_sound(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken = "你好。"
        prompt = (
            "subject_definitions:\n<Subject 1> is the referenced person.\n"
            "summary:\n[reference generation] A short shot.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n[Shot 1] The camera holds a static shot. "
            f"(S1) <Subject 1> says <d>[Chinese] {spoken}</d>. After the last syllable the shot freezes.\n"
            "overall_soundscape:\nN/A\n"
            "non_diegetic_music:\nN/A"
        )
        beat_info = {"dialogue": spoken, "ref_images": [{"index": 1}, {"index": 2}]}
        repaired = H3PromptBuilder.prepare_generated_prompt(
            prompt,
            H3PromptBuilder.shot_from_beat_info(beat_info),
        )
        self.assertEqual([], LlmService._validate_h3_prompt(repaired, "Ref2VA", beat_info))

    def test_render_ref2va_interleaves_one_clause_per_speech_for_any_two_hander(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_a = "这是第一句对白。"
        inner = "这是听者的内心独白。"
        spoken_b = "这是第二句对白。"
        beat_info = {
            "sequence": 12,
            "dialogue": (
                f"角色乙：“{spoken_a}” "
                f"角色甲（内心）：“{inner}” "
                f"角色甲：“{spoken_b}”"
            ),
            "narration": inner,
            "characters": [{"name": "角色甲"}, {"name": "角色乙"}],
            "scene_name": "走廊",
            "visual_prompt": (
                "Photorealistic vertical 9:16. COMPOSITION AND CAMERA: a slow tilt up to the listener. "
                "The camera then pushes to the speaker. The camera follows the gaze down the outfit. "
                "LIGHTING: overhead fluorescent, cyan skin. "
                "After the last syllable the shot freezes on a readable face."
            ),
            "audio": "Corridor hum and synchronized movement.",
            "ref_images": [
                {"index": 1, "name": "角色甲", "category": "character"},
                {"index": 2, "name": "角色乙", "category": "character"},
                {"index": 3, "name": "走廊", "category": "scene"},
            ],
        }
        shot = H3PromptBuilder.shot_from_beat_info(beat_info)
        rendered = H3PromptBuilder.render_ref2va(shot)
        self.assertEqual([], LlmService._validate_h3_prompt(rendered, "Ref2VA", beat_info))
        self.assertIn("<Subject 3>", rendered)
        self.assertNotIn("<Location", rendered)
        self.assertNotIn("Unit Building Elevator", rendered)
        self.assertEqual(rendered.lower().count("thinks"), 1)
        self.assertLess(rendered.find("9:16"), rendered.find("tilts up"))
        self.assertLess(rendered.find("tilts up"), rendered.find(spoken_a))
        self.assertLess(rendered.find(spoken_a), rendered.find("chest-and-waist"))
        self.assertLess(rendered.find("chest-and-waist"), rendered.find(inner))
        self.assertLess(rendered.find(inner), rendered.find(spoken_b))
        self.assertLess(rendered.find(spoken_b), rendered.lower().find("freezes"))
        self.assertNotIn("follows the gaze", rendered)
        self.assertNotIn("follows his gaze", rendered)

    def test_render_ref2va_fills_short_framing_clauses_between_inner_and_spoken(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_a = "大爷，我什么都可以做。"
        inner = "浓妆艳抹，昼伏夜出。"
        spoken_b = "不用想也知道，做的是什么。"
        beat_info = {
            "sequence": 1,
            "dialogue": (
                f"沙丽丽：“{spoken_a}” "
                f"吴耐（内心）：“{inner}” "
                f"吴耐：“{spoken_b}”"
            ),
            "narration": inner,
            "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
            "scene_name": "单元楼电梯",
            "visual_prompt": (
                "Photorealistic modern Chinese urban short drama, vertical 9:16, "
                "one continuous 15-second take, no internal cuts. "
                "COMPOSITION AND CAMERA: medium-close that starts at the waist and tilts up to the face. "
                "Heads sit in the upper third of the vertical frame. "
                "LOCATION: cramped old stainless-steel elevator cabin. "
                "LIGHTING: overhead fluorescent, cyan skin. "
                "After the last syllable the shot freezes on a readable face."
            ),
            "audio": "Elevator hum and synchronized movement.",
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "沙丽丽", "category": "character"},
                {"index": 3, "name": "单元楼电梯", "category": "scene"},
            ],
        }
        generated = LlmService.generate_h3_prompt(beat_info)
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", beat_info))
        self.assertLess(generated.find(inner), generated.find(spoken_b))
        self.assertRegex(
            generated[generated.find(inner):generated.find(spoken_b)],
            r"\b(?:tilts?|push(?:es)?|pans?|tracks?)\b",
        )

    def test_render_ref2va_keeps_picture_lock_and_drops_workshop_echo(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_a = "大爷，我什么都可以做。那个，那个房租下个月一定给你。"
        inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
        spoken_b = "不用想也知道，做的是什么。"
        beat_info = {
            "sequence": 1,
            "duration_seconds": 15,
            "dialogue": (
                f"沙丽丽：“{spoken_a}” "
                f"吴耐（内心）：“{inner}” "
                f"吴耐：“{spoken_b}”"
            ),
            "narration": inner,
            "characters": [
                {
                    "name": "吴耐",
                    "look_desc": (
                        "60 岁花甲男人；秃顶灰白稀疏头发。原主是收废品的穷房东，"
                        "穿越者占据身体后获得“惊讶续命”系统，一心攒满两年寿命好返老还童。"
                    ),
                },
                {
                    "name": "沙丽丽",
                    "look_desc": (
                        "二十出头；波浪棕长发。夜场兼职，有好赌的父亲，交不起房租。"
                    ),
                },
            ],
            "scene_name": "单元楼电梯",
            "visual_prompt": (
                "Photorealistic modern Chinese urban short drama, vertical 9:16, 1080x1920, "
                "one continuous 15-second take, no internal cuts, no timestamp labels, "
                "no black frames, no 16:9 letterbox. "
                "COMPOSITION AND CAMERA: The camera tilts up with small amplitude at slow speed "
                "from waist-level medium to a medium close-up of her face and holds a static shot, "
                "then tilts down with small amplitude at slow speed and holds a static shot on her torso "
                "filling the vertical frame, then pushes in with small amplitude at slow speed "
                "to Wu Nai's medium-close on the left and holds a static shot, one continuous take, no cut. "
                "Heads sit in the upper third of the vertical frame. "
                "Shallow depth of field on the speaking face; the environment behind must still be identifiable as this location. "
                "LOCATION: already inside a closed cramped old stainless-steel elevator cabin, sickly white fluorescent; doors stay shut. "
                "LIGHTING: sickly overhead fluorescent, cyan skin, no beauty rim light. "
                "CAST LOCK, do not beautify or swap faces: skinny 60-year-old Chinese landlord, "
                "receding gray hair, wrinkled tanned skin, sparse stubble, dirty stained yellow-white tank top. "
                "Already inside the closed cabin. Doors stay shut. "
                "Start on Sha Lili's waist: left hand grips the stickered green iPhone. "
                "The camera tilts up with small amplitude at slow speed to a medium close-up of her face, "
                "then holds a static shot. "
                "She first says uncle, then I can do anything, forces a pleasing smile, pauses, "
                "then that, that next month's rent I will definitely give you. "
                "The camera tilts down with small amplitude at slow speed and holds a static shot "
                "on her torso so the red camisole and black mini skirt fill the vertical frame. "
                "Then the camera pushes in with small amplitude at slow speed to Wu Nai's medium-close on the left, "
                "then holds a static shot. "
                "After the last spoken syllable, freeze a readable facial reaction for about one second. "
                "Lip-sync the exact Chinese line(s): "
                f"沙丽丽：“{spoken_a}” 吴耐（内心）：“{inner}” 吴耐：“{spoken_b}”. "
                "Do not translate the line onto the picture. "
                "SYNCHRONIZED SOUND: 电梯运行低频嗡鸣、轿厢金属壁轻响、呼吸和铃铛细响. "
                "FINISH AND FORBIDDEN: hold the last expression. No costume jump. "
                "Episode context: 穿越上身，只剩十四天 / 我什么都可以做."
            ),
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "沙丽丽", "category": "character"},
                {"index": 3, "name": "单元楼电梯", "category": "scene"},
            ],
        }
        generated = LlmService.generate_h3_prompt(beat_info)
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", beat_info))
        self.assertIn("<Subject 1> is 吴耐 in <Picture 1>.", generated)
        self.assertIn("<Picture 1> controls 吴耐 identity only", generated)
        self.assertIn("single-person multi-view design sheet", generated)
        self.assertIn("Do not copy the panel grid", generated)
        self.assertIn("do not transfer pose", generated)
        self.assertIn("do not lock blocking or standing positions", generated)
        self.assertNotIn("惊讶续命", generated.split("detailed_description:")[0])
        self.assertNotIn("好赌的父亲", generated.split("detailed_description:")[0])
        detail = generated.split("detailed_description:", 1)[1]
        self.assertNotIn("CAST LOCK", detail)
        self.assertNotIn("receding gray hair", detail)
        self.assertNotIn("do not beautify", detail)
        self.assertNotIn("Wu Nai stays", detail)
        self.assertEqual(generated.lower().count("thinks"), 1)
        self.assertNotIn("I can do anything", generated)
        self.assertNotIn("no need to guess", generated)
        self.assertNotIn("while the .", generated)
        self.assertNotIn("FINISH AND.", generated)
        self.assertIn("电梯运行低频嗡鸣", generated)
        self.assertLess(generated.find("tilts up"), generated.find(spoken_a))
        self.assertLess(generated.find(spoken_a), generated.find(inner))
        self.assertLess(generated.find(inner), generated.find(spoken_b))
        self.assertRegex(generated, r"\b(?:sound|audio|ambience|ambient)\b")
        self.assertNotIn("1. COMPOSITION", generated)
        self.assertNotIn("The camera then a ", generated)
        self.assertLess(generated.find("Already inside the closed cabin"), generated.find(spoken_a))
        self.assertNotIn("Elevator doors shut", generated)
        self.assertNotIn("Doors just shut", generated)
        self.assertLess(generated.find("left hand grips"), generated.find(spoken_a))
        self.assertNotIn("follows his gaze", generated)
        self.assertNotIn("follows the gaze", generated)
        self.assertLess(generated.find(spoken_a), generated.find("chest-and-waist"))
        self.assertLess(generated.find("chest-and-waist"), generated.find(inner))
        self.assertLess(generated.find("red camisole"), generated.find(inner))
        self.assertNotIn("Push to Wu Nai", generated[generated.find(spoken_a):generated.find(inner)])
        self.assertRegex(
            generated[generated.find(inner):generated.find(spoken_b)],
            r"(?i)push(?:es)? in.{0,80}Wu Nai",
        )
        self.assertIn("clothes fill the vertical frame", generated[generated.find(spoken_a):generated.find(inner)])
        self.assertNotIn("the. camera", generated)
        self.assertNotIn("Then a tilt down her outfit", generated)
        self.assertNotIn("her:.", generated)
        self.assertLess(generated.find(inner), generated.find(spoken_b))
        self.assertLess(generated.find(spoken_b), generated.lower().find("freeze"))
        self.assertNotIn("Yu Qian stays", generated)
        self.assertNotIn("left His lips", generated)
        self.assertNotIn("PERFORMANCE, chronological", generated)

    def test_compile_huajia_shot1_from_chinese_action(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_a = "大爷，我什么都可以做。那个，那个房租下个月一定给你。"
        inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
        spoken_b = "不用想也知道，做的是什么。"
        beat_info = {
            "sequence": 1,
            "duration_seconds": 15,
            "dialogue": (
                f"沙丽丽：“{spoken_a}” "
                f"吴耐（内心）：“{inner}” "
                f"吴耐：“{spoken_b}”"
            ),
            "narration": inner,
            "action": (
                "轿厢内已站定，不要开门。画面先停在沙丽丽腰部，上摇到脸口型同步；"
                "内心时钉在她胸腰，衣服铺满竖屏；再说「做的是什么」时推近吴耐近景。"
            ),
            "camera": "上摇、钉胸腰、再推近",
            "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
            "scene_name": "单元楼电梯",
            "audio": "电梯运行低频嗡鸣、轿厢金属壁轻响。",
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "沙丽丽", "category": "character"},
                {"index": 3, "name": "单元楼电梯", "category": "scene"},
            ],
        }
        generated = LlmService.generate_h3_prompt(beat_info)
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", beat_info))
        self.assertIn("Already inside the closed cabin", generated)
        self.assertIn("Doors stay shut", generated)
        self.assertIn("<Picture 1> controls 吴耐 identity only", generated)
        self.assertIn("single-person multi-view design sheet", generated)
        self.assertIn("Do not copy the panel grid", generated)
        self.assertIn("do not lock blocking or standing positions", generated)
        self.assertNotIn("Elevator doors shut", generated)
        self.assertNotIn("follows his gaze", generated)
        self.assertLess(generated.find("tilts up"), generated.find(spoken_a))
        self.assertLess(generated.find(spoken_a), generated.find("chest-and-waist"))
        self.assertLess(generated.find("chest-and-waist"), generated.find(inner))
        self.assertLess(generated.find(inner), generated.find(spoken_b))
        self.assertIn(spoken_b, generated)
        self.assertRegex(
            generated[generated.find(inner):generated.find(spoken_b)],
            r"(?i)push(?:es)? in.{0,80}Wu Nai",
        )

    def test_render_ref2va_keeps_sound_term_when_audio_is_chinese(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken = "帮我看看上面写的什么。"
        beat_info = {
            "sequence": 3,
            "duration_seconds": 8,
            "dialogue": f"吴耐：“{spoken}”",
            "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
            "scene_name": "9楼老旧走廊",
            "audio": "声控灯启动的电流声、高跟鞋或布鞋踩地砖、远处电梯叮一声。",
            "visual_prompt": (
                "Photorealistic modern Chinese urban short drama, vertical 9:16, 1080x1920, "
                "one continuous 8-second take, no internal cuts. "
                "COMPOSITION AND CAMERA: over-shoulder medium, foreground shoulder frames the listener. "
                "Heads sit in the upper third of the vertical frame. "
                "LOCATION: old 9th-floor corridor, off-white walls, dark green dado, brass door plates. "
                "LIGHTING: warm yellow sensor lamps, glossy-tile bounce, darker door recesses, warm skin. "
                "CAST LOCK, do not beautify or swap faces: skinny 60-year-old Chinese landlord, "
                "receding gray hair, wrinkled tanned skin, sparse stubble, dirty stained yellow-white tank top; "
                "glamorous young Chinese woman, wavy chestnut hair, mole on right cheek, red satin camisole. "
                "Wu Nai stays skinny, tanned, stained yellow-white tank top, never plump. "
                "Sha Lili keeps the cheek mole, black bell choker, red satin camisole and black mini skirt. "
                "HERO PROPS IN FRAME: red-stamped critical-illness notice sheet. "
                "After the last spoken syllable, freeze a readable facial reaction for about one second. "
                "FINISH AND FORBIDDEN: hold the last expression. No costume jump, no location jump."
            ),
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "沙丽丽", "category": "character"},
                {"index": 3, "name": "9楼老旧走廊", "category": "scene"},
            ],
        }
        generated = LlmService.generate_h3_prompt(beat_info)
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", beat_info))
        self.assertIn("声控灯启动的电流声", generated)
        self.assertRegex(generated, r"\b(?:sound|audio|ambience|ambient)\b")

    def test_prepare_does_not_duplicate_inner_thinks_on_rendered_ref2va(self):
        from backend.app.media_studio.services.llm_service import LlmService

        spoken_a = "大爷，我什么都可以做。"
        inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
        spoken_b = "不用想也知道，做的是什么。"
        beat_info = {
            "sequence": 1,
            "duration_seconds": 15,
            "dialogue": (
                f"沙丽丽：“{spoken_a}” "
                f"吴耐（内心）：“{inner}” "
                f"吴耐：“{spoken_b}”"
            ),
            "narration": inner,
            "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
            "scene_name": "单元楼电梯",
            "visual_prompt": (
                "Photorealistic vertical 9:16. "
                "COMPOSITION AND CAMERA: medium-close that starts at the waist and tilts up to the face, "
                "then a slow push to the landlord. "
                "LOCATION: cramped elevator. LIGHTING: cyan skin. "
                "After the last syllable the shot freezes on a readable face."
            ),
            "audio": "电梯运行低频嗡鸣。",
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "沙丽丽", "category": "character"},
                {"index": 3, "name": "单元楼电梯", "category": "scene"},
            ],
        }
        shot = H3PromptBuilder.shot_from_beat_info(beat_info)
        rendered = H3PromptBuilder.render_ref2va(shot)
        prepared = H3PromptBuilder.prepare_generated_prompt(rendered, shot)
        generated = LlmService.generate_h3_prompt(beat_info)
        duplicated = "(S1) <Subject 1> 吴耐 thinks. (S1) <Subject 1> 吴耐 thinks."
        self.assertEqual(prepared.lower().count("thinks"), 1)
        self.assertEqual(generated.lower().count("thinks"), 1)
        self.assertNotIn(duplicated, prepared)
        self.assertNotIn(duplicated, generated)
        collapsed = H3PromptBuilder.prepare_generated_prompt(
            rendered.replace(
                "(S1) <Subject 1> 吴耐 thinks. In an off-screen",
                "(S1) <Subject 1> 吴耐 thinks. (S1) <Subject 1> 吴耐 thinks. In an off-screen",
                1,
            ),
            shot,
        )
        self.assertEqual(collapsed.lower().count("thinks"), 1)
        twice = H3PromptBuilder.prepare_generated_prompt(generated, shot)
        self.assertEqual(twice.lower().count("thinks"), 1)
        self.assertNotIn(duplicated, twice)
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", beat_info))

    def test_ref2va_workshop_excerpt_is_short_and_includes_official_example(self):
        from backend.app.llm_minimax_skills import (
            load_h3_prompt_writing_guide,
            load_h3_prompt_writing_skill,
            load_h3_ref2va_workshop_excerpt,
        )

        excerpt = load_h3_ref2va_workshop_excerpt()
        self.assertLess(len(excerpt.encode("utf-8")), 12 * 1024)
        self.assertIn("## Workflow", excerpt)
        self.assertIn("## Output Rules", excerpt)
        self.assertIn("## Tips", excerpt)
        self.assertIn("subject_definitions:", excerpt)
        self.assertIn("<Subject 1> is the coffee-shop environment", excerpt)
        self.assertIn("CAST LOCK", excerpt)
        self.assertIn("multi-view design sheet", excerpt)
        self.assertIn("panel grid", excerpt)
        self.assertNotIn("This guide explains how rewrite outputs are organized", excerpt)
        self.assertNotIn("## 1. Overall Structure", excerpt)
        full = "\n".join([
            load_h3_prompt_writing_skill(),
            load_h3_prompt_writing_guide(mode="ref"),
            load_h3_prompt_writing_guide(mode="base"),
        ])
        self.assertLess(len(excerpt), len(full) // 3)

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

    def test_workshop_prompts_reuse_manual_prompt_verbatim(self):
        prompt = (
            "subject_definitions:\n<Subject 1> is A in <Picture 1>.\n"
            "summary:\nmanual summary\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n[Shot 1] KEEP_MANUAL_CAMERA_TOKEN holds the frame.\n"
            "overall_soundscape:\nAmbient room sound.\n"
            "non_diegetic_music:\nN/A"
        )
        shot = {
            "sequence": 1,
            "speaker": "沈砚",
            "dialogue": "你好。",
            "h3_prompt": prompt,
            "h3_prompt_source": "manual",
        }
        usable = EpisodeVideoService._workshop_prompts_usable([shot])
        self.assertIsNotNone(usable)
        self.assertIn("KEEP_MANUAL_CAMERA_TOKEN", usable[0])
        self.assertEqual(usable[0], H3PromptBuilder.canonicalize_reference_tags(prompt))

    def test_workshop_prompts_skip_program_pack_keeps_authored_en(self):
        prompt = short_authored_en("你好。")
        shot = {
            "sequence": 1,
            "speaker": "沈砚",
            "dialogue": "你好。",
            "h3_prompt": prompt,
            "skill_pack_id": HALF_NARRATED_PACK_ID,
        }
        usable = EpisodeVideoService._workshop_prompts_usable([shot])
        self.assertIsNotNone(usable)
        self.assertIn("The camera tracks down the corridor", usable[0])
        self.assertIn("<Picture 1>", usable[0])
        self.assertNotIn("The camera holds a stable medium composition", usable[0])
        self.assertNotIn("Already inside the closed cabin", usable[0])
        self.assertNotIn(_THICKNESS_PAD, usable[0])
        self.assertEqual(usable[0], H3PromptBuilder.canonicalize_reference_tags(prompt))

    def test_workshop_prompts_manual_does_not_block_generated_neighbor(self):
        generated = {
            "sequence": 1,
            "speaker": "沈砚",
            "dialogue": "你好。",
            "h3_prompt": rich_prompt(),
        }
        manual = {
            "sequence": 2,
            "speaker": "沈砚",
            "dialogue": "再见。",
            "h3_prompt": (
                "subject_definitions:\nmanual\nsummary:\nmanual\nretention_analysis:\nmanual\n"
                "detailed_description:\nKEEP_SECOND_MANUAL\noverall_soundscape:\nroom\n"
                "non_diegetic_music:\nN/A"
            ),
            "h3_prompt_source": "manual",
        }
        usable = EpisodeVideoService._workshop_prompts_usable([generated, manual])
        self.assertIsNotNone(usable)
        self.assertIn("你好。", usable[0])
        self.assertIn("KEEP_SECOND_MANUAL", usable[1])

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

    def test_beat_info_prompt_finalize_skips_prepare_when_skip_program_pack(self):
        from backend.app.media_studio.services.h3_prompt_job_service import H3PromptJobService

        prompt = short_authored_en("只对十四天。")
        payload = {
            "beat_id": "beat-1",
            "beat_sequence": 1,
            "beat_info": {
                "speaker": "沙丽丽",
                "dialogue": "只对十四天。",
                "skill_pack_id": HALF_NARRATED_PACK_ID,
                "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
            },
        }
        finalized = H3PromptJobService._finalize_prompt(payload, prompt)
        self.assertIn("The camera tracks down the corridor", finalized)
        self.assertIn("<Picture 1>", finalized)
        self.assertNotIn("The camera holds a stable medium composition", finalized)
        self.assertNotIn("Already inside the closed cabin", finalized)
        self.assertNotIn("<Subject 3>", finalized)
        self.assertNotIn(_THICKNESS_PAD, finalized)
        self.assertEqual(finalized, H3PromptBuilder.canonicalize_reference_tags(prompt))

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

    def test_h3_prompt_failure_payload_keeps_author_errors_and_vision(self):
        from backend.app.media_studio.services.h3_prompt_job_service import H3PromptJobService
        from backend.app.media_studio.services.llm_service import DualShotAuthorError
        from backend.app.vision_runtime import VISION_STATUS_USED, VisionCallMeta

        err = DualShotAuthorError(
            "写稿未通过校验：缺 <<<ZH>>> 中文分秒稿",
            errors=["缺 <<<ZH>>> 中文分秒稿"],
            zh_prompt="",
            en_prompt="subject_definitions:\nA leftover English draft.",
            vision=VisionCallMeta(status=VISION_STATUS_USED, model="gpt-5.6-sol", image_count=3, source="llm"),
        )
        payload = H3PromptJobService._attach_failure_payload(
            {"beat_info": {}, "stream": {"text": "partial"}},
            err,
        )
        self.assertEqual(["缺 <<<ZH>>> 中文分秒稿"], payload["author_errors"])
        self.assertEqual("used", payload["vision_status"])
        self.assertEqual("gpt-5.6-sol", payload["vision_model"])
        self.assertEqual(3, payload["vision_image_count"])
        self.assertIn("leftover English draft", payload["author_en_draft"])
        self.assertEqual("partial", payload["stream"]["text"])

    def test_h3_prompt_failure_payload_keeps_raw_stub(self):
        from backend.app.media_studio.services.h3_prompt_job_service import H3PromptJobService
        from backend.app.media_studio.services.llm_service import DualShotAuthorError

        err = DualShotAuthorError(
            "写稿未通过校验：上轮只输出了说明句",
            errors=["上轮只输出了说明句"],
            zh_prompt="官方八块中文分秒稿与",
            en_prompt="英文六段稿。",
            raw_prompt="<<<ZH>>>\n官方八块中文分秒稿与\n<<<EN>>>\n英文六段稿。",
        )
        payload = H3PromptJobService._attach_failure_payload({"beat_info": {}}, err)
        self.assertIn("<<<ZH>>>", payload["author_raw_draft"])
        self.assertIn("官方八块", payload["author_zh_draft"])


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

    def test_triptych_references_omit_avatar_when_look_sheet_exists(self):
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
            },
            assets,
            stage="triptych",
        )
        self.assertEqual(["https://x/new.png"], urls)
        self.assertNotIn("https://x/avatar.png", urls)

    def test_triptych_references_fall_back_to_avatar_without_look_sheet(self):
        assets = [{
            "id": "char-1",
            "kind": "character",
            "image_url": "https://x/avatar.png",
            "extra": {"avatar_url": "https://x/avatar.png", "identities": []},
        }]
        urls = beat_reference_urls(
            {"character_ids": ["char-1"]},
            assets,
            stage="triptych",
        )
        self.assertEqual(["https://x/avatar.png"], urls)

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

    def test_skill_pack_appends_start_panel_not_full_triptych(self):
        beat = self._beat(
            scene_id="scene-ready",
            triptych_url="https://x/triptych.png",
            triptych_panels={
                "start": "https://x/start.png",
                "mid": "https://x/mid.png",
                "end": "https://x/end.png",
            },
        )
        with patch("backend.app.skill_packs.resolve_skill_pack_id", return_value=HALF_NARRATED_PACK_ID):
            shots = EpisodeVideoService._prepare_shots(
                {"beats": [beat], "project_id": "p1"},
                self._assets(),
            )
        urls = shots[0]["reference_urls"]
        self.assertIn("https://x/char.png", urls)
        self.assertIn("https://x/scene.png", urls)
        self.assertIn("https://x/start.png", urls)
        self.assertNotIn("https://x/triptych.png", urls)
        self.assertNotIn("https://x/mid.png", urls)
        self.assertEqual("https://x/start.png", urls[-1])
        sources = [item.get("source") for item in shots[0]["ref_images"]]
        self.assertIn("characters", sources)
        self.assertIn("scene", sources)
        self.assertIn("triptych.start", sources)

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
        self.assertIsNone(create_job.call_args.kwargs.get("beat_ids"))
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

    def test_director_selected_ids_create_one_timeline_job(self):
        with patch.object(EpisodeVideoService, "create_job", return_value={
            "job_id": "job-sel", "status": "queued", "render_scope": "selection", "shot_count": 2,
        }) as create_job:
            result = EpisodeVideoService.generate_episode_videos(
                "p1", "e1",
                options={"workflow": "minimax-h3-director-accel-r2v", "beat_ids": ["beat-1", "beat-2"]},
            )
        create_job.assert_called_once()
        self.assertEqual(["beat-1", "beat-2"], create_job.call_args.kwargs.get("beat_ids"))
        self.assertIsNone(create_job.call_args.kwargs.get("beat_id"))
        self.assertEqual("selection", create_job.call_args.kwargs.get("render_scope"))
        self.assertEqual("episode", result["render_mode"])
        self.assertEqual(["job-sel"], result["job_ids"])
        self.assertEqual(1, result["submitted"])
        self.assertEqual(2, result["shot_count"])
        self.assertEqual(0, result["skipped"])

    def test_director_selected_one_id_still_one_job(self):
        with patch.object(EpisodeVideoService, "create_job", return_value={
            "job_id": "job-beat-1", "status": "queued", "render_scope": "shot", "shot_count": 1,
        }) as create_job:
            result = EpisodeVideoService.generate_episode_videos(
                "p1", "e1",
                options={"workflow": "minimax-h3-director-accel-r2v", "beat_ids": ["beat-1"]},
            )
        create_job.assert_called_once()
        self.assertEqual(["beat-1"], create_job.call_args.kwargs.get("beat_ids"))
        self.assertEqual(["job-beat-1"], result["job_ids"])
        self.assertEqual(1, result["submitted"])
        self.assertEqual(1, result["shot_count"])

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

    def test_selection_lock_blocks_overlapping_beats(self):
        active = [{"id": "job-sel", "payload_json": __import__("json").dumps({
            "render_scope": "selection", "beat_ids": ["beat-1", "beat-2"], "episode_id": "e1",
        })}]
        with patch.object(EpisodeVideoService, "_active_video_jobs", return_value=active):
            EpisodeVideoService._assert_can_enqueue("p1", "e1", "shot", beat_id="beat-3")
            with self.assertRaisesRegex(ValueError, "该镜头已有进行中的视频任务"):
                EpisodeVideoService._assert_can_enqueue("p1", "e1", "selection", beat_ids=["beat-2", "beat-3"])

    def test_compose_rejects_missing_shots_and_director_direct_output(self):
        missing = self._detail(video_urls={"beat-1": "https://cdn/a.mp4"})
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=missing), \
             patch("backend.app.skill_packs.resolve_skill_pack_id", return_value=""):
            with self.assertRaisesRegex(ValueError, "Beat 2"):
                EpisodeVideoService.create_compose_job("p1", "e1")
        director = self._detail(source="director_direct")
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=director), \
             patch("backend.app.skill_packs.resolve_skill_pack_id", return_value=""):
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
             patch("backend.app.skill_packs.resolve_skill_pack_id", return_value=""), \
             patch("backend.app.media_studio.services.episode_video_service.execute_sql") as execute_sql, \
             patch("backend.app.media_studio.services.episode_video_service._EXECUTOR") as executor:
            result = EpisodeVideoService.create_compose_job("p1", "e1")
        self.assertEqual("compose", result["render_scope"])
        self.assertTrue(result["job_id"].startswith("job-"))
        execute_sql.assert_called_once()
        executor.submit.assert_called_once()

    def test_compose_rejects_half_narrated_pack_without_narration_audio(self):
        from backend.app.skill_packs import HALF_NARRATED_PACK_ID

        beats = [
            {
                "id": "beat-1",
                "sequence": 1,
                "video_url": "https://cdn/1.mp4",
                "narration": "夜色里，城市还没睡。",
            }
        ]
        detail = {"number": 1, "title": "解说集", "beats": beats, "data": {"beats": beats}}
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=detail), \
             patch("backend.app.skill_packs.resolve_skill_pack_id", return_value=HALF_NARRATED_PACK_ID):
            with self.assertRaisesRegex(ValueError, "旁白"):
                EpisodeVideoService.create_compose_job("p1", "e1")

    def test_compose_payload_records_mix_dubbing_flag(self):
        detail = self._detail(video_urls={
            "beat-1": "https://cdn/1.mp4",
            "beat-2": "https://cdn/2.mp4",
            "beat-3": "https://cdn/3.mp4",
        })
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=detail), \
             patch.object(EpisodeVideoService, "_active_video_jobs", return_value=[]), \
             patch("backend.app.skill_packs.resolve_skill_pack_id", return_value=""), \
             patch("backend.app.media_studio.services.episode_video_service.execute_sql") as execute_sql, \
             patch("backend.app.media_studio.services.episode_video_service._EXECUTOR"):
            EpisodeVideoService.create_compose_job("p1", "e1", options={"mix_dubbing": False})
        payload = json.loads(execute_sql.call_args.args[1][3])
        self.assertFalse(payload["mix_dubbing"])


class EpisodeVideoUpscaleTests(unittest.TestCase):
    def _detail(self, *, video_urls=None):
        video_urls = video_urls or {}
        beats = []
        for index in range(1, 4):
            beat_id = f"beat-{index}"
            beats.append({
                "id": beat_id,
                "sequence": index,
                "video_url": video_urls.get(beat_id, ""),
                "video_duration": 5,
            })
        return {"number": 1, "title": "测试集", "beats": beats, "data": {"beats": beats}}

    def test_resolve_generation_options_coerces_string_upscale_flag(self):
        resolved = EpisodeVideoService.resolve_generation_options({
            "workflow": "minimax-h3-r2v",
            "upscale_after": "true",
        })
        self.assertTrue(resolved["upscale_after"])
        off = EpisodeVideoService.resolve_generation_options({
            "workflow": "minimax-h3-r2v",
            "upscale_after": "false",
        })
        self.assertFalse(off["upscale_after"])

    def test_vsr_rejection_uses_connected_comfy_vram(self):
        shot = {"sequence": 1, "duration_sec": 15}
        options = {"workflow": "minimax-h3-t2v", "duration_per_beat": 15}
        with patch(
            "backend.app.media_studio.services.episode_video_service.source_video_shape",
            return_value=(864, 480, 362),
        ):
            small = Mock()
            small.vram_total_bytes.return_value = 8 * 1024 * 1024 * 1024
            small.vram_device_name.return_value = "8GB card"
            reason = EpisodeVideoService._vsr_rejection_for_shot(options, shot, "minimax-h3-t2v", comfy=small)
            self.assertIsNotNone(reason)
            self.assertIn("8 GB", reason)
            big = Mock()
            big.vram_total_bytes.return_value = 17170956288
            big.vram_device_name.return_value = "NVIDIA GeForce RTX 4080"
            self.assertIsNone(EpisodeVideoService._vsr_rejection_for_shot(options, shot, "minimax-h3-t2v", comfy=big))

    def test_create_upscale_job_rejects_missing_film_and_vram(self):
        missing = self._detail()
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=missing), \
             patch.object(EpisodeVideoService, "_completed_video_url_for_beat", return_value=""):
            with self.assertRaisesRegex(ValueError, "还没有成片"):
                EpisodeVideoService.create_upscale_job("p1", "e1", "beat-1")
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=self._detail()):
            with self.assertRaisesRegex(ValueError, "指定的镜头不存在"):
                EpisodeVideoService.create_upscale_job("p1", "e1", "beat-missing")
        fallback = self._detail()
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=fallback), \
             patch.object(EpisodeVideoService, "_completed_video_url_for_beat", return_value="https://cdn/from-job.mp4"), \
             patch.object(EpisodeVideoService, "_active_video_jobs", return_value=[]), \
             patch.object(EpisodeVideoService, "_vsr_rejection_for_shot", return_value=None), \
             patch("backend.app.media_studio.services.episode_video_service.ComfyService.get_config") as get_config, \
             patch("backend.app.media_studio.services.episode_video_service.ComfyVideoClient"), \
             patch("backend.app.media_studio.services.episode_video_service.execute_sql") as execute_sql, \
             patch("backend.app.media_studio.services.episode_video_service._EXECUTOR"):
            get_config.return_value.base_url = "http://127.0.0.1:8188"
            EpisodeVideoService.create_upscale_job("p1", "e1", "beat-1")
        payload = json.loads(execute_sql.call_args.args[1][3])
        self.assertEqual("https://cdn/from-job.mp4", payload["source_video_url"])
        ready = self._detail(video_urls={"beat-1": "https://cdn/1.mp4"})
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=ready), \
             patch.object(EpisodeVideoService, "_vsr_rejection_for_shot", return_value="2x 超分预估需要约 12.0 GB 显存"):
            with self.assertRaisesRegex(ValueError, "显存"):
                EpisodeVideoService.create_upscale_job("p1", "e1", "beat-1")

    def test_create_upscale_job_blocks_in_progress_same_beat(self):
        active = [{"id": "job-1", "payload_json": json.dumps({
            "render_scope": "upscale", "beat_id": "beat-1", "episode_id": "e1",
        })}]
        with patch.object(EpisodeVideoService, "_active_video_jobs", return_value=active):
            with self.assertRaisesRegex(ValueError, "该镜头已有进行中的视频任务"):
                EpisodeVideoService._assert_can_enqueue("p1", "e1", "upscale", beat_id="beat-1")
            EpisodeVideoService._assert_can_enqueue("p1", "e1", "upscale", beat_id="beat-2")

    def test_create_upscale_job_enqueues_independent_scope(self):
        ready = self._detail(video_urls={"beat-1": "https://cdn/1.mp4"})
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=ready), \
             patch.object(EpisodeVideoService, "_active_video_jobs", return_value=[]), \
             patch.object(EpisodeVideoService, "_vsr_rejection_for_shot", return_value=None), \
             patch("backend.app.media_studio.services.episode_video_service.ComfyService.get_config") as get_config, \
             patch("backend.app.media_studio.services.episode_video_service.ComfyVideoClient") as client_cls, \
             patch("backend.app.media_studio.services.episode_video_service.execute_sql") as execute_sql, \
             patch("backend.app.media_studio.services.episode_video_service._EXECUTOR") as executor:
            get_config.return_value.base_url = "http://127.0.0.1:8188"
            result = EpisodeVideoService.create_upscale_job("p1", "e1", "beat-1")
        self.assertEqual("upscale", result["render_scope"])
        self.assertTrue(result["job_id"].startswith("job-"))
        payload = json.loads(execute_sql.call_args.args[1][3])
        self.assertEqual("upscale", payload["render_scope"])
        self.assertEqual("https://cdn/1.mp4", payload["source_video_url"])
        self.assertEqual(["beat-1"], payload["beat_ids"])
        client_cls.return_value.ping.assert_called_once()
        client_cls.return_value.require_rtx_vsr_node.assert_called_once()
        executor.submit.assert_called_once()

    def test_create_upscale_job_matches_legacy_beat_sequence(self):
        ready = {
            "number": 1,
            "title": "测试集",
            "beats": [{"id": "uuid-live", "sequence": 1, "video_url": "https://cdn/1.mp4", "video_duration": 5}],
        }
        with patch.object(ProjectDetailService, "get_episode_detail", return_value=ready), \
             patch.object(EpisodeVideoService, "_active_video_jobs", return_value=[]), \
             patch.object(EpisodeVideoService, "_vsr_rejection_for_shot", return_value=None), \
             patch("backend.app.media_studio.services.episode_video_service.ComfyService.get_config") as get_config, \
             patch("backend.app.media_studio.services.episode_video_service.ComfyVideoClient"), \
             patch("backend.app.media_studio.services.episode_video_service.execute_sql") as execute_sql, \
             patch("backend.app.media_studio.services.episode_video_service._EXECUTOR"):
            get_config.return_value.base_url = "http://127.0.0.1:8188"
            EpisodeVideoService.create_upscale_job("p1", "e1", "beat-1")
        payload = json.loads(execute_sql.call_args.args[1][3])
        self.assertEqual(["uuid-live"], payload["beat_ids"])

    def test_create_upscale_job_from_video_job_stale_beat_still_enqueues_clip(self):
        shot_row = {
            "id": "job-shot",
            "job_type": "video_generation",
            "status": "completed",
            "result_url": "https://cdn/shot.mp4",
            "payload_json": json.dumps({
                "render_scope": "shot",
                "episode_id": "e1",
                "beat_id": "stale-beat",
                "source_shots": [{"beat_id": "stale-beat", "sequence": 1, "duration_sec": 8}],
            }),
        }
        with patch("backend.app.media_studio.services.episode_video_service.query_one", return_value=shot_row), \
             patch.object(EpisodeVideoService, "create_upscale_job", side_effect=ValueError("指定的镜头不存在")), \
             patch.object(ProjectDetailService, "get_episode_detail", return_value=self._detail()), \
             patch.object(EpisodeVideoService, "_active_video_jobs", return_value=[]), \
             patch.object(EpisodeVideoService, "_vsr_rejection_for_shot", return_value=None), \
             patch("backend.app.media_studio.services.episode_video_service.ComfyService.get_config") as get_config, \
             patch("backend.app.media_studio.services.episode_video_service.ComfyVideoClient"), \
             patch("backend.app.media_studio.services.episode_video_service.execute_sql") as execute_sql, \
             patch("backend.app.media_studio.services.episode_video_service._EXECUTOR"):
            get_config.return_value.base_url = "http://127.0.0.1:8188"
            result = EpisodeVideoService.create_upscale_job_from_video_job("p1", "job-shot")
        payload = json.loads(execute_sql.call_args.args[1][3])
        self.assertEqual("upscale", result["render_scope"])
        self.assertEqual("https://cdn/shot.mp4", payload["source_video_url"])
        self.assertEqual("job-shot", payload["source_job_id"])
        self.assertEqual([], payload["beat_ids"])

    def test_create_upscale_job_from_video_job_uses_result_and_blocks_upscale_rows(self):
        shot_row = {
            "id": "job-shot",
            "job_type": "video_generation",
            "status": "completed",
            "result_url": "https://cdn/shot.mp4",
            "payload_json": json.dumps({
                "render_scope": "shot",
                "episode_id": "e1",
                "beat_id": "beat-1",
                "project_id": "p1",
            }),
        }
        with patch("backend.app.media_studio.services.episode_video_service.query_one", return_value=shot_row), \
             patch.object(EpisodeVideoService, "create_upscale_job", return_value={"job_id": "job-vsr", "render_scope": "upscale"}) as create:
            result = EpisodeVideoService.create_upscale_job_from_video_job("p1", "job-shot")
        self.assertEqual("job-vsr", result["job_id"])
        create.assert_called_once()
        self.assertEqual("https://cdn/shot.mp4", create.call_args.kwargs["source_url"])
        self.assertEqual("job-shot", create.call_args.kwargs["source_job_id"])

        vsr_row = {
            "id": "job-vsr",
            "job_type": "video_generation",
            "status": "completed",
            "result_url": "https://cdn/2x.mp4",
            "payload_json": json.dumps({"render_scope": "upscale", "episode_id": "e1"}),
        }
        with patch("backend.app.media_studio.services.episode_video_service.query_one", return_value=vsr_row):
            with self.assertRaisesRegex(ValueError, "超分任务本身不能再超分"):
                EpisodeVideoService.create_upscale_job_from_video_job("p1", "job-vsr")

        selection_row = {
            "id": "job-sel",
            "job_type": "video_generation",
            "status": "completed",
            "result_url": "https://cdn/last.mp4",
            "payload_json": json.dumps({
                "render_scope": "selection",
                "episode_id": "e1",
                "beat_ids": ["beat-1", "beat-2"],
            }),
        }
        with patch("backend.app.media_studio.services.episode_video_service.query_one", return_value=selection_row):
            with self.assertRaisesRegex(ValueError, "逐镜点"):
                EpisodeVideoService.create_upscale_job_from_video_job("p1", "job-sel")

    def test_create_upscale_job_from_episode_job_enqueues_without_beat(self):
        episode_row = {
            "id": "job-ep",
            "job_type": "video_generation",
            "status": "completed",
            "result_url": "https://cdn/ep.mp4",
            "payload_json": json.dumps({
                "render_scope": "episode",
                "episode_id": "e1",
                "source_shots": [
                    {"beat_id": "beat-1", "duration_sec": 5},
                    {"beat_id": "beat-2", "duration_sec": 5},
                ],
            }),
        }
        with patch("backend.app.media_studio.services.episode_video_service.query_one", return_value=episode_row), \
             patch.object(ProjectDetailService, "get_episode_detail", return_value=self._detail()), \
             patch.object(EpisodeVideoService, "_active_video_jobs", return_value=[]), \
             patch.object(EpisodeVideoService, "_vsr_rejection_for_shot", return_value=None), \
             patch("backend.app.media_studio.services.episode_video_service.ComfyService.get_config") as get_config, \
             patch("backend.app.media_studio.services.episode_video_service.ComfyVideoClient"), \
             patch("backend.app.media_studio.services.episode_video_service.execute_sql") as execute_sql, \
             patch("backend.app.media_studio.services.episode_video_service._EXECUTOR"):
            get_config.return_value.base_url = "http://127.0.0.1:8188"
            result = EpisodeVideoService.create_upscale_job_from_video_job("p1", "job-ep")
        payload = json.loads(execute_sql.call_args.args[1][3])
        self.assertEqual("upscale", result["render_scope"])
        self.assertEqual("https://cdn/ep.mp4", payload["source_video_url"])
        self.assertEqual("job-ep", payload["source_job_id"])
        self.assertEqual([], payload["beat_ids"])
        self.assertEqual("episode", payload["render_mode"])

    def test_mark_source_job_upscaled_writes_payload(self):
        source = {"payload_json": json.dumps({"result_kind": "shot"})}
        with patch("backend.app.media_studio.services.episode_video_service.query_one", return_value=source), \
             patch("backend.app.media_studio.services.episode_video_service.execute_sql") as execute_sql:
            EpisodeVideoService._mark_source_job_upscaled("job-shot", "https://cdn/2x.mp4", "https://cdn/orig.mp4")
        updated = json.loads(execute_sql.call_args.args[1][0])
        self.assertEqual("https://cdn/2x.mp4", updated["upscaled_video_url"])
        self.assertEqual("https://cdn/orig.mp4", updated["source_video_url"])

    def test_auto_upscale_only_for_shot_and_selection(self):
        comfy = Mock()
        shots = [{"beat_id": "beat-1", "sequence": 1, "video_url": "https://cdn/orig.mp4"}]
        episode_payload = {"render_scope": "episode", "upscale_after": True, "project_id": "p1", "episode_id": "e1"}
        compose_payload = {"render_scope": "compose", "upscale_after": True, "project_id": "p1", "episode_id": "e1"}
        with patch.object(EpisodeVideoService, "_upscale_source_url") as upscale, \
             patch.object(ProjectDetailService, "update_episode_beat") as update:
            EpisodeVideoService._auto_upscale_if_requested("job-ep", episode_payload, comfy, shots)
            EpisodeVideoService._auto_upscale_if_requested("job-co", compose_payload, comfy, shots)
        upscale.assert_not_called()
        update.assert_not_called()
        self.assertNotIn("upscaled_video_url", episode_payload)
        self.assertNotIn("upscale_warning", episode_payload)

    def test_auto_upscale_writes_url_and_keeps_original_on_failure(self):
        comfy = Mock()
        shots = [{"beat_id": "beat-1", "sequence": 1, "video_url": "https://cdn/orig.mp4"}]
        payload = {"render_scope": "shot", "upscale_after": True, "project_id": "p1", "episode_id": "e1"}
        with patch.object(EpisodeVideoService, "_upscale_source_url", return_value="https://cdn/2x.mp4"), \
             patch.object(ProjectDetailService, "update_episode_beat") as update:
            EpisodeVideoService._auto_upscale_if_requested("job-1", payload, comfy, shots)
        self.assertEqual("https://cdn/2x.mp4", payload["upscaled_video_url"])
        self.assertEqual("https://cdn/orig.mp4", shots[0]["video_url"])
        self.assertEqual("https://cdn/2x.mp4", shots[0]["upscaled_video_url"])
        update.assert_called_once_with("p1", "e1", "beat-1", {"upscaled_video_url": "https://cdn/2x.mp4"})
        failed = {"render_scope": "selection", "upscale_after": True, "project_id": "p1", "episode_id": "e1"}
        failed_shots = [{"beat_id": "beat-2", "sequence": 2, "video_url": "https://cdn/orig2.mp4"}]
        with patch.object(EpisodeVideoService, "_upscale_source_url", side_effect=RuntimeError("显存不足")), \
             patch.object(ProjectDetailService, "update_episode_beat") as update_failed:
            EpisodeVideoService._auto_upscale_if_requested("job-2", failed, comfy, failed_shots)
        self.assertEqual("https://cdn/orig2.mp4", failed_shots[0]["video_url"])
        self.assertNotIn("upscaled_video_url", failed_shots[0])
        self.assertIn("显存不足", failed["upscale_warning"])
        update_failed.assert_not_called()

    def test_run_job_routes_upscale_scope_without_h3(self):
        gpu = Mock()
        gpu.__enter__ = Mock(return_value=gpu)
        gpu.__exit__ = Mock(return_value=False)
        payload = {"render_scope": "upscale", "comfy_base_url": "http://127.0.0.1:8188"}
        with patch("backend.app.media_studio.services.episode_video_service.query_one", return_value={"payload_json": json.dumps(payload)}), \
             patch("backend.app.media_studio.services.episode_video_service.occupy_gpu", return_value=gpu), \
             patch.object(EpisodeVideoService, "_run_upscale_job") as run_upscale, \
             patch.object(EpisodeVideoService, "_run_shot_graph_job") as run_h3:
            EpisodeVideoService._run_job("job-vsr")
        run_upscale.assert_called_once()
        run_h3.assert_not_called()
        gpu.__enter__.assert_called_once()

    def test_run_rtx_vsr_frees_models_before_submit(self):
        client = ComfyVideoClient("http://127.0.0.1:8188")
        with patch.object(client, "require_rtx_vsr_node") as require, \
             patch.object(client, "free_resources") as free, \
             patch.object(client, "upload_video_bytes", return_value="orig.mp4"), \
             patch.object(client, "submit_and_wait", return_value=({}, {}, {"filename": "x.mp4"})):
            output = client.run_rtx_vsr(b"data", preferred_name="a.mp4")
        require.assert_called_once()
        free.assert_called_once_with(force=True)
        self.assertEqual("x.mp4", output["filename"])


if __name__ == "__main__":
    unittest.main()
