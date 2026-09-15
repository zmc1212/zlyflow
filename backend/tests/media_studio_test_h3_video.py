from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import unittest
from unittest.mock import Mock, patch

from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient
from backend.app.media_studio.services.episode_image_prompts import beat_reference_urls, beat_render_prompt
from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
from backend.app.media_studio.services.h3_prompt_builder import H3PromptBuilder


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

    def test_finds_nested_video_output(self):
        output = ComfyVideoClient._find_video({"7": {"videos": [{
            "filename": "result.mp4", "subfolder": "video", "type": "output"
        }]}})
        self.assertEqual("result.mp4", output["filename"])


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


if __name__ == "__main__":
    unittest.main()
