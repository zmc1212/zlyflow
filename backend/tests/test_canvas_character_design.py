from __future__ import annotations

import unittest

from backend.app.media_studio.services.asset_image_prompts import build_identity_generation


class CanvasCharacterDesignTests(unittest.TestCase):
    def test_explicit_canvas_design_overrides_stored_look_for_request_only(self) -> None:
        look = {"id": "look-1", "description": "旧服装", "appearance_details": "旧服装"}
        spec = build_identity_generation(
            {"name": "角色"}, look, {},
            prompt="新服装\n角色设计：发型：短发；眼神：温柔克制",
            visual_style="手绘水彩",
        )
        self.assertIn("新服装", spec["clean_prompt"])
        self.assertIn("眼神：温柔克制", spec["clean_prompt"])
        self.assertNotIn("旧服装", spec["clean_prompt"])
        self.assertEqual("旧服装", look["appearance_details"])
