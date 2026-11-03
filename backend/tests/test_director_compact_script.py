from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.app.media_studio.services.script_parser import StandardScriptParser
from backend.app.media_studio.services.project_detail_service import ProjectDetailService

SCRIPT = (Path(__file__).parent / "fixtures" / "director_compact_script.md").read_text(encoding="utf-8")


class DirectorCompactScriptTests(unittest.TestCase):
    def test_generated_markdown_keeps_cast_references_timing_and_full_action(self):
        result = StandardScriptParser.parse(SCRIPT)
        self.assertEqual("雨夜留灯·流程验收", result["title"])
        self.assertEqual(["林夏", "陈默"], [c["name"] for c in result["characters"]])
        self.assertEqual(["雨夜，咖啡店门口"], [s["name"] for s in result["scenes"]])
        self.assertEqual(["一杯热咖啡"], [p["name"] for p in result["props"]])
        self.assertEqual("都市写实 / 竖屏 9:16", result["positioning"]["genre"])
        shots = result["episodes"][0]["shots"]
        self.assertEqual([10, 10], [s["duration_sec"] for s in shots])
        self.assertTrue(all(set(s["characters"]) == {"林夏", "陈默"} for s in shots))
        self.assertTrue(all(s["scene"] == "雨夜，咖啡店门口" and s["props"] == ["一杯热咖啡"] for s in shots))
        self.assertIn("缩在屋檐下查看手机", shots[0]["action"])
        self.assertIn("将咖啡递到陈默手中", shots[0]["action"])
        self.assertIn("趁热喝", shots[0]["dialogue"])
        self.assertNotIn("**", shots[0]["dialogue"])
        self.assertNotIn("制作提示", shots[1]["dialogue"])
        self.assertIn("调亮", result["episodes"][0]["summary"])
        self.assertEqual(SCRIPT.strip(), result["episodes"][0]["body"])

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_previously_adopted_empty_analysis_recovers_on_read(self, execute):
        analysis = ProjectDetailService._analysis_for_document_row({"id": "doc", "raw_text": SCRIPT, "analysis_json": json.dumps({"episodes": [], "characters": [], "scenes": [], "props": []})}, persist=True)
        self.assertEqual(2, len(analysis["characters"]))
        self.assertEqual(2, analysis["episodes"][0]["shots_count"])
        self.assertTrue(execute.called)

    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    @patch("backend.app.media_studio.services.project_detail_service.query_all")
    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    def test_empty_breakdown_stops_before_creating_assets(self, execute, query_all, query_one):
        query_one.return_value = {"id": "doc", "raw_text": "一段尚无制作设定的文字", "analysis_json": "{}"}
        with self.assertRaisesRegex(ValueError, "未识别到制作资产"):
            ProjectDetailService.transfer_assets_from_document("p", "doc", mode="append")
        query_all.assert_not_called()
        execute.assert_not_called()

    def test_modern_scene_defaults_do_not_insert_a_historical_setting(self):
        scene = ProjectDetailService._hydrate_asset({"id": "s", "kind": "scene", "name": "咖啡店门口", "description": "都市雨夜的咖啡店门口", "extra_json": "{}"})
        self.assertEqual("都市雨夜的咖啡店门口", scene["extra"]["environment_prompt"])
        self.assertNotIn("宋式", scene["extra"]["pano_prompt"])

    def test_transfer_keeps_references_and_uses_the_actual_speaking_character(self):
        shots = StandardScriptParser.parse(SCRIPT)["episodes"][0]["shots"]
        beats = ProjectDetailService._beats_from_document_shots("ep", shots, {"林夏": "c1", "陈默": "c2"}, {"雨夜，咖啡店门口": "s1"}, {"一杯热咖啡": "p1"})
        self.assertEqual(["林夏", "陈默"], [b["speaker"] for b in beats])
        self.assertTrue(all(set(b["character_ids"]) == {"c1", "c2"} and b["scene_id"] == "s1" and b["prop_ids"] == ["p1"] for b in beats))

    @patch("backend.app.media_studio.services.project_detail_service.grs_row")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_invalid_asset_kind_stops_before_contacting_image_provider(self, query_one, provider):
        query_one.return_value = {"id": "c", "kind": "character", "name": "林夏", "extra_json": "{}"}
        with self.assertRaisesRegex(ValueError, "资产类型不匹配"):
            ProjectDetailService.generate_asset_image("p", "c", {"target_type": "scene_master"})
        provider.assert_not_called()
