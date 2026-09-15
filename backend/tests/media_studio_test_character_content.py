from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import unittest
from unittest.mock import Mock, patch

from backend.app.media_studio.services.llm_service import LlmService


class CharacterContentTests(unittest.TestCase):
    def test_parses_fenced_json(self):
        parsed = LlmService._parse_json_object(
            '```json\n{"description":"容貌服饰", "visual_prompt":"生图提示词"}\n```'
        )
        self.assertEqual("容貌服饰", parsed["description"])
        self.assertEqual("生图提示词", parsed["visual_prompt"])

    @patch.object(LlmService, "_runtime_config", return_value=("https://llm.example/v1", "test-model", "key"))
    @patch("backend.app.media_studio.services.llm_service.requests.post")
    def test_generates_complete_character_content(self, post: Mock, _runtime: Mock):
        response = Mock(ok=True)
        response.json.return_value = {
            "choices": [{"message": {"content": (
                '{"description":"26岁，短发，白衬衫与深色长裤",'
                '"visual_prompt":"26岁中国男性，短发，白衬衫，深色长裤，单人全身设定图"}'
            )}}]
        }
        post.return_value = response

        result = LlmService.generate_character_content(
            "26岁现代男硕士，沉稳清瘦",
            name="沈砚",
            role="男主角",
        )

        self.assertIn("白衬衫", result["description"])
        self.assertIn("单人全身", result["visual_prompt"])
        self.assertEqual("test-model", result["model"])
        request_body = post.call_args.kwargs["json"]
        self.assertIn("沈砚", request_body["messages"][1]["content"])
        self.assertEqual({"type": "json_object"}, request_body["response_format"])

    @patch.object(LlmService, "_runtime_config", return_value=("https://llm.example/v1", "test-model", "key"))
    @patch("backend.app.media_studio.services.llm_service.requests.post")
    def test_rejects_incomplete_character_content(self, post: Mock, _runtime: Mock):
        response = Mock(ok=True)
        response.json.return_value = {
            "choices": [{"message": {"content": '{"description":"只有描述"}'}}]
        }
        post.return_value = response

        with self.assertRaisesRegex(ValueError, "缺少容貌服装描述或生图提示词"):
            LlmService.generate_character_content("现代青年")


if __name__ == "__main__":
    unittest.main()
