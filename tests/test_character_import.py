from __future__ import annotations

import unittest
from unittest.mock import patch

from server.services.character_import_service import (
    CharacterImportService,
    character_asset_extra,
    complete_character_locally,
)
from server.services.script_parser import StandardScriptParser


NIUDA_SCRIPT = """
# 测试剧

## 视频定位
- 类型：古装 / 穿越
- 世界观：大晟

## 一、主要人物固定设定

### 牛大（牛昊）——男主
现代身份：28岁一线销售，短发衬衫。
古代身份：安侯府庶子牛昊，24岁；清瘦结实；剑眉。
固定道具：炭笔。

### 淼淼——女主 / 公主
20岁；眉眼清亮；微服青裙。

# 四、人物一致性提示词

**牛大（古代）：** 24岁中国古代男子，剑眉，青灰旧直裰。
**牛大（现代，仅1–2集）：** 28岁中国男性，短发，深色衬衫。
**淼淼（微服）：** 20岁中国古代少女，青裙布衣。
"""


class CharacterImportTests(unittest.TestCase):
    def test_parser_extracts_name_aliases_and_looks(self):
        analysis = StandardScriptParser.parse(NIUDA_SCRIPT)
        names = {item["name"]: item for item in analysis["characters"]}
        self.assertIn("牛大", names)
        self.assertIn("牛昊", names["牛大"]["aliases"])
        look_names = {look["name"] for look in names["牛大"]["looks"]}
        self.assertIn("现代身份", look_names)
        self.assertIn("古代身份", look_names)
        self.assertEqual("女主 / 公主", names["淼淼"]["role"])

    def test_local_complete_fills_profile(self):
        filled = complete_character_locally(
            {
                "name": "牛大",
                "aliases": ["牛昊"],
                "role": "男主",
                "age": "28岁",
                "description": "现代身份：28岁一线销售，短发衬衫。古代身份：安侯府庶子牛昊，24岁，剑眉青灰直裰。",
            },
            project_style="chinese_period_drama",
            genre="古装 / 穿越",
            fill_defaults=True,
        )
        self.assertEqual("主角", filled["role_position"])
        self.assertEqual("男", filled["gender"])
        self.assertEqual("青年", filled["age_group"])
        self.assertTrue(filled["face_prompt"])
        look_names = {look["name"] for look in filled["looks"]}
        self.assertIn("现代身份", look_names)
        self.assertIn("古代身份", look_names)

        extra = character_asset_extra(filled, "ast-testlooks", {
            "identities": [{"id": "old", "name": "牛昊 (日常/初始造型)", "description": "旧占位", "image_url": ""}],
        })
        ident_names = {item["name"] for item in extra["identities"]}
        self.assertIn("现代身份", ident_names)
        self.assertIn("古代身份", ident_names)
        self.assertNotIn("牛昊 (日常/初始造型)", ident_names)

    @patch("server.services.llm_service.LlmService.enrich_imported_characters")
    def test_enrich_analysis_uses_llm_then_defaults(self, enrich):
        enrich.return_value = [{
            "name": "淼淼",
            "face_prompt": "女性，青年，乌发，眉眼清亮，瓷白肤色",
            "body_type": "纤细",
            "role_position": "主角",
            "gender": "女",
            "age_group": "青年",
        }]
        analysis = {
            "title": "测试",
            "positioning": {"genre": "古装"},
            "visual_style": {"description": "写实古装"},
            "characters": [{"name": "淼淼", "role": "公主", "description": "20岁公主微服"}],
            "logs": [],
        }
        result = CharacterImportService.enrich_analysis(analysis, project_style="chinese_period_drama")
        char = result["characters"][0]
        self.assertEqual("女性，青年，乌发，眉眼清亮，瓷白肤色", char["face_prompt"])
        self.assertEqual("纤细", char["body_type"])
        self.assertEqual("女", char["gender"])
        self.assertTrue(char["visual_prompt"])
        enrich.assert_called_once()


if __name__ == "__main__":
    unittest.main()
