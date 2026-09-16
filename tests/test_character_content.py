from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from server.services.llm_service import LlmService


class CharacterContentTests(unittest.TestCase):
    def test_parses_fenced_json(self):
        parsed = LlmService._parse_json_object(
            '```json\n{"description":"容貌服饰", "visual_prompt":"生图提示词"}\n```'
        )
        self.assertEqual("容貌服饰", parsed["description"])
        self.assertEqual("生图提示词", parsed["visual_prompt"])

    @patch.object(LlmService, "_runtime_config", return_value=("https://llm.example/v1", "test-model", "key"))
    @patch("server.services.llm_service.requests.post")
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
    @patch("server.services.llm_service.requests.post")
    def test_rejects_incomplete_character_content(self, post: Mock, _runtime: Mock):
        response = Mock(ok=True)
        response.json.return_value = {
            "choices": [{"message": {"content": '{"description":"只有描述"}'}}]
        }
        post.return_value = response

        with self.assertRaisesRegex(ValueError, "缺少容貌服装描述或生图提示词"):
            LlmService.generate_character_content("现代青年")


    @patch.object(LlmService, "_runtime_config", return_value=("https://llm.example/v1", "test-model", "key"))
    @patch("server.services.llm_service.requests.post")
    def test_enriches_imported_character_profiles(self, post: Mock, _runtime: Mock):
        response = Mock(ok=True)
        response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "characters": [{
                    "name": "牛大",
                    "role_position": "主角",
                    "gender": "男",
                    "age_group": "青年",
                    "face_prompt": "男性，青年，剑眉，短发",
                    "art_style_id": "chinese_period_drama",
                    "visual_style": "ancient",
                }]
            }, ensure_ascii=False)}}]
        }
        post.return_value = response
        rows = LlmService.enrich_imported_characters(
            [{"name": "牛大", "role": "男主", "description": "销售穿越"}],
            title="测试",
            genre="古装",
            project_style="chinese_period_drama",
        )
        self.assertEqual("主角", rows[0]["role_position"])
        self.assertIn("牛大", post.call_args.kwargs["json"]["messages"][1]["content"])

    @patch.object(LlmService, "_runtime_config", return_value=("https://llm.example/v1", "test-model", "key"))
    @patch("server.services.llm_service.requests.post")
    def test_enriches_one_character(self, post: Mock, _runtime: Mock):
        response = Mock(ok=True)
        response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "name": "牛大",
                "gender": "男",
                "age_group": "青年",
                "face_prompt": "男性，青年，剑眉",
            }, ensure_ascii=False)}}]
        }
        post.return_value = response
        filled = LlmService.enrich_one_character({"name": "牛大", "role": "男主"})
        self.assertEqual("男", filled["gender"])
        user_msg = post.call_args.kwargs["json"]["messages"][1]["content"]
        self.assertIn("牛大", user_msg)
        self.assertNotIn("characters", post.call_args.kwargs["json"]["messages"][0]["content"])


