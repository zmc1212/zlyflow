import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from backend.app.media_studio.services.script_parser import StandardScriptParser as Parser
from backend.app.media_studio.services.project_detail_service import ProjectDetailService as Service
from backend.app.media_studio.services.director_story_design import reference_common_setting, design_prompts


SCRIPT = '''# 第1集：穿越危机
**剧情：** 沈砚意外穿越。
### 场景1｜图书馆·深夜
人物：沈砚
动作：沈砚整理古籍。
台词：沈砚：“谁写的？”
### 场景2｜穿越
场景：图书馆
- 动作：古书落地，白光闪过。
- 台词：无
'''


class WorkshopShotStructureTests(unittest.TestCase):
    def legacy(self):
        return [{"id": f"old-{i}", "action": s, "dialogue": "", "scene": "", "video_url": "historical.mp4"}
                for i, s in enumerate(SCRIPT.splitlines()) if s.strip()]

    def test_scene_blocks_keep_dialogue_and_ignore_metadata(self):
        shots = Parser.workshop_shots(SCRIPT)
        self.assertEqual(len(shots), 2)
        self.assertEqual(shots[0]["action"], "沈砚整理古籍。")
        self.assertEqual(shots[0]["characters"], ["沈砚"])
        self.assertEqual(shots[0]["dialogue"], '沈砚：“谁写的？”')
        self.assertEqual(shots[1]["dialogue"], "")
        self.assertEqual(shots[1]["scene"], "图书馆")

    def test_plain_prose_is_not_silently_split(self):
        self.assertEqual(Parser.workshop_shots("第一章\n他走进房间。\n她没有回答。"), [])

    def test_scene_boundary_does_not_inherit_location_or_wrong_speaker(self):
        text = SCRIPT + '\n### 场景3｜母亲出现\n人物：沈砚、母亲\n动作：母亲进门。\n台词：母亲：“醒了？”'
        beats = Service._beats_from_document_shots("ep", Parser.workshop_shots(text), {}, {}, {})
        self.assertEqual(beats[1]["scene"], "图书馆")
        self.assertEqual(beats[2]["scene"], "")
        self.assertEqual(beats[2]["speaker"], "母亲")
        self.assertEqual(beats[2]["dialogue"], '“醒了？”')

    def test_only_exact_fallback_is_repairable(self):
        beats = self.legacy()
        self.assertTrue(Parser.is_line_fallback(SCRIPT, beats))
        beats[0]["action"] = "人工调整的开场"
        self.assertFalse(Parser.is_line_fallback(SCRIPT, beats))

    def test_repair_retains_old_media_and_checks_concurrent_edit(self):
        beats = self.legacy()
        row = {"script_text": SCRIPT, "data_json": json.dumps({"beats": beats, "production": {"revision": 2}})}
        cursor = Mock()
        cursor.fetchone.return_value = row
        cursor.fetchall.return_value = []
        @contextmanager
        def transaction():
            yield cursor
        request = {"script_text": SCRIPT, "beat_ids": [b["id"] for b in beats]}
        with patch("backend.app.media_studio.services.project_detail_service.transaction_cursor", transaction), patch.object(Service, "get_episode_detail", return_value={"ok": True}):
            Service.restore_script_shots("p", "ep", request)
            update = next(c for c in cursor.execute.call_args_list if c.args[0].startswith("UPDATE"))
            saved = json.loads(update.args[1][0])
            self.assertEqual(len(saved["beats"]), 2)
            self.assertEqual(saved["shot_structure_backups"][0]["beats"], beats)
            self.assertEqual(saved["production"], {"revision": 2})
            cursor.reset_mock()
            with self.assertRaisesRegex(ValueError, "已变化"):
                Service.restore_script_shots("p", "ep", {**request, "script_text": "outdated"})
            self.assertFalse(any(c.args[0].startswith("UPDATE") for c in cursor.execute.call_args_list))

    def test_common_setting_uses_selected_reference_identity(self):
        source = {"assets": [{"id": "a", "name": "沈砚"}, {"id": "b", "name": "无关角色"}], "beats": []}
        request = {"reference_slots": [{"asset_id": "a", "name": "沈砚（现代）", "token": "<Picture 1>"}]}
        setting = reference_common_setting(source, request)
        self.assertIn("<Picture 1> 沈砚（现代）", setting["subject_definitions"])
        self.assertNotIn("无关角色", setting["subject_definitions"])
        from types import SimpleNamespace
        _, user = design_prompts(source, {}, request, SimpleNamespace(max_segments=6, max_total_frames=1152))
        self.assertEqual([a["id"] for a in json.loads(user)["source"]["assets"]], ["a"])
        self.assertIsNone(reference_common_setting(source, {}))


if __name__ == "__main__":
    unittest.main()
