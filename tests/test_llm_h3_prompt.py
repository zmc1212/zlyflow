from __future__ import annotations

import unittest
from unittest.mock import patch

from server.services.llm_service import LlmService


class LlmH3PromptTests(unittest.TestCase):
    def test_clean_h3_dialogue_removes_speaker_and_quote_wrappers(self):
        dialogue = '李青莲：“君不见，高堂明镜悲白发，朝如青丝暮成雪。”'

        self.assertEqual(
            "君不见，高堂明镜悲白发，朝如青丝暮成雪。",
            LlmService._clean_h3_dialogue(dialogue, "李青莲"),
        )

    @patch.object(LlmService, "chat_text")
    def test_generate_h3_prompt_uses_skill_contract_and_cleans_returned_dialogue(self, chat_text):
        chat_text.return_value = (
            "subject_definitions:\n<Subject 1> is 李青莲 from <Picture 1>.\n"
            "summary:\n[reference generation] A literary portrait.\n"
            "retention_analysis:\n<Subject 1>: fully_preserved - identity is retained.\n"
            "detailed_description:\n[Shot 1] <Subject 1> (S1) says "
            '<d>[Chinese] 李青莲：“君不见，高堂明镜悲白发，朝如青丝暮成雪。”</d>.\n'
            "overall_soundscape:\nQuiet room tone.\n"
            "non_diegetic_music:\nN/A"
        )
        beat_info = {
            "sequence": 1,
            "speaker": "李青莲",
            "dialogue": '李青莲：“君不见，高堂明镜悲白发，朝如青丝暮成雪。”',
            "duration_seconds": 10,
            "ref_images": [{"index": 1, "name": "李青莲", "category": "character"}],
        }

        prompt = LlmService.generate_h3_prompt(beat_info)

        system_prompt, user_prompt = chat_text.call_args.args[:2]
        expected_sections = (
            "subject_definitions:",
            "summary:",
            "retention_analysis:",
            "detailed_description:",
            "overall_soundscape:",
            "non_diegetic_music:",
        )
        positions = [system_prompt.index(section) for section in expected_sections]
        self.assertEqual(sorted(positions), positions)
        self.assertIn("at most one camera move", system_prompt)
        self.assertIn("at slow speed", system_prompt)
        self.assertIn("Full-Reference Mode Rewrite Output Format Guide", system_prompt)
        self.assertIn("Video Prompt Writing Guide (T2VA / I2VA / FL2VA / L2VA)", system_prompt)
        self.assertIn("Target mode: Ref2VA", user_prompt)
        self.assertNotIn("画面广告文案:", system_prompt)
        self.assertIn("对白原文（必须逐字放入 <d>，不得包含说话人姓名和外围引号）：君不见", user_prompt)
        self.assertIn("<d>[Chinese] 君不见，高堂明镜悲白发，朝如青丝暮成雪。</d>", prompt)
        self.assertNotIn("<d>[Chinese] 李青莲：", prompt)
        self.assertEqual(chat_text.call_count, 1)

    @patch.object(LlmService, "chat_text")
    def test_generate_h3_prompt_without_references_uses_t2va_guide(self, chat_text):
        chat_text.return_value = (
            "integrated_multimodal_description:\n"
            "[Shot 1] Live-action, cinematic, a medium shot holds the empty courtyard.\n"
            "overall_soundscape:\n"
            "Wind moves across the courtyard.\n"
            "non_diegetic_music:\n"
            "N/A"
        )

        LlmService.generate_h3_prompt({
            "sequence": 2,
            "duration_seconds": 8,
            "ref_images": [],
        })

        system_prompt, user_prompt = chat_text.call_args.args[:2]
        self.assertIn("Input mode is T2VA", system_prompt)
        self.assertIn("Video Prompt Writing Guide (T2VA / I2VA / FL2VA / L2VA)", system_prompt)
        self.assertNotIn("Full-Reference Mode Rewrite Output Format Guide", system_prompt)
        self.assertIn("Target mode: T2VA", user_prompt)
        self.assertIn("不要编造 <Picture N>", user_prompt)

    def test_camera_budget_rejects_fast_multi_shot_prompt_from_job(self):
        prompt = """subject_definitions:
<Subject 1> is the poet from <Picture 1>.
summary:
[reference generation] A palace shot.
retention_analysis:
<Subject 1>: fully_preserved - identity is retained.
detailed_description:
[Shot 1] The camera pushes in.
[Shot 2] Camera pans 180 degrees and then rotates 360 degrees at fast speed.
overall_soundscape:
Quiet room tone.
non_diegetic_music:
N/A"""

        errors = LlmService._validate_h3_prompt(
            prompt,
            "Ref2VA",
            {"camera": "低角度仰拍，快速推升至俯拍全景", "ref_images": [{"index": 1}]},
        )

        self.assertTrue(any("too many shots" in item for item in errors))
        self.assertTrue(any("too fast or too dizzy" in item for item in errors))
        self.assertTrue(any("too many camera moves" in item for item in errors))

    def test_camera_budget_accepts_one_slow_small_move(self):
        prompt = """subject_definitions:
<Subject 1> is the poet from <Picture 1>.
summary:
[reference generation] A palace shot.
retention_analysis:
<Subject 1>: fully_preserved - identity is retained.
detailed_description:
[Shot 1] The camera pushes in with small amplitude at slow speed and then holds.
overall_soundscape:
Quiet room tone.
non_diegetic_music:
N/A"""

        errors = LlmService._camera_budget_errors(
            prompt,
            "Ref2VA",
            {"camera": "快速推升"},
        )

        self.assertEqual([], errors)

    def test_body_action_tilt_is_not_a_camera_move(self):
        prompt = """subject_definitions:
<Subject 1> is the poet from <Picture 1>.
summary:
[reference generation] A palace shot.
retention_analysis:
<Subject 1>: fully_preserved - identity is retained.
detailed_description:
[Shot 1] The camera rises with small amplitude at slow speed. He tilts his head back and drinks.
overall_soundscape:
Quiet room tone.
non_diegetic_music:
N/A"""

        self.assertEqual([], LlmService._camera_budget_errors(prompt, "Ref2VA", {"camera": "仰拍"}))

    @patch.object(LlmService, "chat_text")
    def test_camera_budget_failure_is_restrained_instead_of_failing_the_job(self, chat_text):
        chat_text.return_value = (
            "subject_definitions:\n<Subject 1> is the poet from <Picture 1>.\n"
            "summary:\n[reference generation] A palace shot.\n"
            "retention_analysis:\n<Subject 1>: fully_preserved - identity is retained.\n"
            "detailed_description:\n[Shot 1] The camera pushes in.\n"
            "[Shot 2] Camera pans 180 degrees and then rotates 360 degrees at fast speed.\n"
            "overall_soundscape:\nQuiet room tone.\n"
            "non_diegetic_music:\nN/A"
        )

        prompt = LlmService.generate_h3_prompt({
            "camera": "低角度仰拍主角特写，快速推升至大殿半空展现俯拍全景",
            "ref_images": [{"index": 1, "name": "李青莲", "category": "character"}],
            "duration_seconds": 10,
        })

        self.assertEqual(chat_text.call_count, 1)
        self.assertNotIn("[Shot 2]", prompt)
        self.assertIn("at slow speed", prompt)
        self.assertIn("with small amplitude", prompt)
        self.assertNotIn("360", prompt)
        self.assertEqual([], LlmService._camera_budget_errors(
            prompt,
            "Ref2VA",
            {"camera": "快速推升", "ref_images": [{"index": 1}]},
        ))

    @patch("server.services.llm_fill_job_service.execute_sql")
    @patch("server.services.llm_fill_job_service.query_one")
    @patch("server.services.llm_fill_job_service.query_all")
    @patch("server.services.project_detail_service.ProjectDetailService.get_episode_detail")
    @patch("server.services.project_detail_service.ProjectDetailService.list_assets")
    def test_enqueue_h3_prompt_creates_job_with_h3_job_type(
        self,
        mock_list_assets,
        mock_get_ep,
        mock_query_all,
        mock_query_one,
        mock_execute_sql,
    ):
        from server.services.llm_fill_job_service import LlmFillJobService

        mock_query_all.return_value = []
        mock_get_ep.return_value = {
            "number": 1,
            "title": "将进酒",
            "beats": [
                {
                    "id": "b-1",
                    "sequence": 1,
                    "heading": "金銮殿醉赋",
                    "action": "李白高歌",
                    "camera": "推镜头",
                    "video_duration": 8,
                }
            ],
        }
        mock_list_assets.return_value = []

        res = LlmFillJobService.enqueue_h3_prompt(
            "proj-1",
            "ep-1",
            "b-1",
            {"ref_images": [{"index": 1, "name": "李青莲", "url": "https://img.example.com/1.png"}]},
        )

        self.assertEqual(res["status"], "queued")
        self.assertTrue(res["job_id"].startswith("job-"))
        self.assertIn("生成H3提示词: 第1集 镜头1", res["title"])

        # Check execute_sql INSERT params
        insert_calls = [c for c in mock_execute_sql.call_args_list if "INSERT INTO ai_project_jobs" in str(c)]
        self.assertTrue(len(insert_calls) >= 1)
        params = insert_calls[0].args[1]
        self.assertEqual(params[2], "h3_prompt")
        self.assertIn("proj-1", params[1])


if __name__ == "__main__":
    unittest.main()
