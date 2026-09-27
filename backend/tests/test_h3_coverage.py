from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.director_craft.coverage import (
    COVERAGE_CONTRACT_EXCERPT,
    compile_coverage_plan,
    fidelity_conflict,
    plan_production_takes,
)
from backend.app.llm_minimax_skills import build_script_agent_prompt, build_shots_per_episode_question
from backend.app.media_studio.services.h3_prompt_builder import H3PromptBuilder
from backend.app.media_studio.services.h3_take_split import (
    merge_episode_beats,
    should_split_beat,
    split_episode_beats,
)
from backend.app.media_studio.services.project_detail_service import ProjectDetailService


HUAJIA_BEAT = {
    "id": "beat-1",
    "sequence": 1,
    "heading": "电梯里的误会",
    "action": (
        "轿厢内已站定，不要开门。画面先停在沙丽丽腰部，上摇到脸口型同步；"
        "内心时钉在她胸腰，衣服铺满竖屏；再说「做的是什么」时推近吴耐近景。"
    ),
    "camera": "上摇、钉胸腰、再推近",
    "dialogue": (
        "沙丽丽：“大爷，我什么都可以做。” "
        "吴耐（内心）：“浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。” "
        "吴耐：“不用想也知道，做的是什么。”"
    ),
    "characters": [{"name": "吴耐"}, {"name": "沙丽丽"}],
    "scene": "单元楼电梯",
}


class CoverageCompilerTests(unittest.TestCase):
    def test_excerpt_stays_one_screen(self) -> None:
        self.assertIn("画面停在谁身上", COVERAGE_CONTRACT_EXCERPT)
        self.assertLess(len(COVERAGE_CONTRACT_EXCERPT), 400)

    def test_shots_per_episode_is_a_soft_rhythm_hint(self) -> None:
        question = build_shots_per_episode_question()
        self.assertIn("节奏建议", question["why"])
        self.assertIn("可超过", question["why"])
        self.assertIn("出片镜", question["why"])
        self.assertIn("导入", question["why"])
        self.assertNotIn("还会再拆", question["why"])
        self.assertNotIn("生成提示词时还会再拆", question["why"])

    def test_script_agent_prompt_defers_take_split_to_import_planner(self) -> None:
        prompt = build_script_agent_prompt(episode_count=3, shots_per_episode=6)
        self.assertIn("节奏建议", prompt)
        self.assertIn("导入内容库", prompt)
        self.assertIn("规划出片镜", prompt)
        self.assertNotIn("还会再拆", prompt)
        self.assertIn("不要按口型/内心/近景关键词模板拆镜", prompt)

    def test_huajia_plan_uses_official_camera(self) -> None:
        events = H3PromptBuilder.ordered_speech_events(HUAJIA_BEAT)
        plan = compile_coverage_plan(HUAJIA_BEAT, events)
        kinds = [item.kind for item in plan.moves]
        self.assertEqual(["tilt_up", "inner_hold", "push_in"], kinds)
        self.assertTrue(plan.already_inside)
        self.assertIn("Doors stay shut", " ".join(plan.blocking))
        self.assertTrue(all("follows" not in item.clause.lower() for item in plan.moves))

    def test_fidelity_conflict_requires_spoken_inner_and_second_move(self) -> None:
        events = H3PromptBuilder.ordered_speech_events(HUAJIA_BEAT)
        self.assertTrue(fidelity_conflict(HUAJIA_BEAT, events))
        locked = dict(HUAJIA_BEAT)
        locked["action"] = "两人站在走廊对视。"
        locked["camera"] = "固定机位"
        locked["visual_prompt"] = ""
        locked["dialogue"] = "甲：“你好。” 乙（内心）：“他来了。”"
        self.assertFalse(fidelity_conflict(locked, H3PromptBuilder.ordered_speech_events(locked)))


class ProductionTakeSplitTests(unittest.TestCase):
    def test_huajia_splits_into_three_takes_and_merges_back(self) -> None:
        beats = [
            dict(HUAJIA_BEAT),
            {"id": "beat-2", "sequence": 2, "story_shot": 2, "action": "走出电梯", "dialogue": ""},
        ]
        self.assertTrue(should_split_beat(beats[0], beats))
        split, take_ids = split_episode_beats(beats, "beat-1")
        self.assertEqual(3, len(take_ids))
        self.assertEqual(["lipsync", "inner_hold", "push_close"], [item.get("take_role") for item in split[:3]])
        self.assertEqual([1, 1, 1, 2], [item.get("story_shot") for item in split])
        self.assertIn("口型同步", split[0]["action"])
        self.assertIn("胸腰", split[1]["action"])
        self.assertIn("做的是什么", split[2]["dialogue"])
        self.assertNotIn("做的是什么", split[0]["dialogue"])
        merged, parent_id = merge_episode_beats(split, take_ids[1])
        self.assertEqual("beat-1", parent_id)
        self.assertEqual(2, len(merged))
        self.assertTrue(merged[0].get("merge_as_one"))
        self.assertEqual("", merged[0].get("take_role") or "")
        self.assertIn("做的是什么", merged[0]["dialogue"])
        self.assertFalse(should_split_beat(merged[0], merged))


class GenerateH3PromptNoAutoSplitTests(unittest.TestCase):
    def setUp(self):
        # Legacy-path tests must not query the real project database.
        row = patch("backend.app.media_studio.services.workshop_service.WorkshopService.row",
                    return_value=({}, {}))
        self.workshop_row = row.start()
        self.addCleanup(row.stop)

    def test_v7_routes_to_workshop_without_legacy_split_or_merge(self):
        self.workshop_row.return_value = ({}, {"prompt_authoring": {"director_plan": {"schema_version": 7}}})
        with patch("backend.app.media_studio.services.workshop_service.WorkshopService.create",
                   return_value={"job_id": "workshop-job"}) as create, \
             patch("backend.app.media_studio.services.h3_prompt_job_service.H3PromptJobService.enqueue") as enqueue, \
             patch.object(ProjectDetailService, "replace_episode_beats") as replace:
            result = ProjectDetailService.generate_beat_h3_prompt("proj-1", "ep-1", "beat-1", {})
        create.assert_called_once_with("proj-1", "ep-1", "workshop_prompt", {"beat_ids": ["beat-1"]})
        enqueue.assert_not_called()
        replace.assert_not_called()
        self.assertEqual(result, {"job_id": "workshop-job"})

    @patch("backend.app.media_studio.services.h3_prompt_job_service.H3PromptJobService.enqueue")
    @patch.object(ProjectDetailService, "replace_episode_beats")
    @patch.object(ProjectDetailService, "get_episode_detail")
    def test_huajia_beat_enqueues_one_job_without_splitting(self, get_detail, replace, enqueue):
        get_detail.return_value = {"beats": [dict(HUAJIA_BEAT)]}
        enqueue.return_value = {"job_id": "job-1"}
        result = ProjectDetailService.generate_beat_h3_prompt("proj-1", "ep-1", "beat-1", {})
        enqueue.assert_called_once()
        replace.assert_not_called()
        self.assertFalse(result["split"])
        self.assertFalse(result["merged"])
        self.assertEqual(["beat-1"], result["beat_ids"])
        self.assertEqual(["job-1"], result["job_ids"])
        self.assertEqual("beat-1", enqueue.call_args.args[2])

    @patch("backend.app.media_studio.services.h3_prompt_job_service.H3PromptJobService.enqueue")
    @patch.object(ProjectDetailService, "replace_episode_beats")
    @patch.object(ProjectDetailService, "get_episode_detail")
    def test_merge_as_one_still_merges_then_enqueues_one(self, get_detail, replace, enqueue):
        split, take_ids = split_episode_beats([dict(HUAJIA_BEAT)], "beat-1")
        get_detail.return_value = {"beats": split}
        enqueue.return_value = {"job_id": "job-merge"}
        result = ProjectDetailService.generate_beat_h3_prompt(
            "proj-1",
            "ep-1",
            take_ids[1],
            {"merge_as_one": True},
        )
        replace.assert_called_once()
        enqueue.assert_called_once()
        self.assertTrue(result["merged"])
        self.assertFalse(result["split"])
        self.assertEqual(["beat-1"], result["beat_ids"])
        merged_beats = replace.call_args.args[2]
        self.assertEqual(1, len(merged_beats))
        self.assertTrue(merged_beats[0].get("merge_as_one"))

    def test_plan_production_takes_keeps_story_order(self) -> None:
        events = H3PromptBuilder.ordered_speech_events(HUAJIA_BEAT)
        plans = plan_production_takes(HUAJIA_BEAT, events)
        self.assertEqual(["lipsync", "inner_hold", "push_close"], [item.role for item in plans])
        self.assertEqual(["口型", "内心覆盖", "近景定性"], [item.label for item in plans])


class ReferenceAuthorityTests(unittest.TestCase):
    def test_subject_lines_lock_identity_not_pose_or_blocking(self) -> None:
        from backend.app.director_craft.references import reference_authority_errors

        beat = {
            **HUAJIA_BEAT,
            "characters": [
                {
                    "name": "吴耐",
                    "look_desc": "60岁花甲男人；秃顶灰白稀疏头发。穿越者占据身体后获得惊讶续命系统。",
                },
                {"name": "沙丽丽", "look_desc": "二十出头；波浪棕长发。夜场兼职，有好赌的父亲。"},
            ],
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character", "character_id": "c-wu"},
                {"index": 2, "name": "沙丽丽", "category": "character", "character_id": "c-sha"},
                {"index": 3, "name": "单元楼电梯", "category": "scene"},
            ],
        }
        shot = H3PromptBuilder.shot_from_beat_info(beat)
        lines = " ".join(H3PromptBuilder._subject_definition_lines(shot))
        self.assertIn("<Picture 1> controls 吴耐 identity only", lines)
        self.assertIn("single-person multi-view design sheet", lines)
        self.assertIn("panel grid", lines)
        self.assertIn("white background", lines)
        self.assertIn("repeated mini figures", lines)
        self.assertIn("do not transfer pose", lines)
        self.assertIn("do not lock blocking or standing positions", lines)
        self.assertNotIn("惊讶续命", lines)
        self.assertNotIn("好赌的父亲", lines)
        generated = H3PromptBuilder.render_ref2va(shot)
        self.assertEqual([], reference_authority_errors(generated, shot))
        self.assertNotIn("CAST LOCK", generated.split("detailed_description:", 1)[1])

    def test_character_subject_line_forbids_copying_design_sheet_grid(self) -> None:
        from backend.app.director_craft.references import character_subject_line

        line = character_subject_line(1, "吴耐")
        self.assertIn("<Subject 1> is 吴耐 in <Picture 1>.", line)
        self.assertIn("design sheet", line)
        self.assertIn("hair", line)
        self.assertIn("wardrobe", line)
        self.assertIn("Do not copy the panel grid", line)
        self.assertIn("white background", line)
        self.assertIn("repeated mini figures", line)
        self.assertIn("do not transfer pose", line)

    def test_prop_subject_line_forbids_copying_design_sheet_grid(self) -> None:
        from backend.app.director_craft.references import prop_subject_line

        line = prop_subject_line(3, "旧木书箱")
        self.assertIn("<Subject 3> is 旧木书箱 in <Picture 3>.", line)
        self.assertIn("prop design sheet", line)
        self.assertIn("shape", line)
        self.assertIn("materials", line)
        self.assertIn("Do not copy the panel grid", line)
        self.assertIn("white background", line)
        self.assertIn("repeated mini objects", line)
        self.assertIn("do not transfer pose", line)

    def test_composition_subject_line_uses_time_landmarks(self) -> None:
        from backend.app.director_craft.references import composition_subject_line

        start = composition_subject_line(4, "起幅构图", "start")
        mid = composition_subject_line(5, "中格构图", "mid")
        end = composition_subject_line(6, "结果构图", "end")
        self.assertIn("anchors opening blocking only", start)
        self.assertIn("not a new character", start)
        self.assertIn("00:00 composition landmark", start)
        self.assertIn("main-action composition landmark", mid)
        self.assertIn("closing composition landmark", end)
        self.assertIn("do not show all three panels at once", start)
        self.assertIn("single 9:16 frame", end)
        self.assertNotIn("perform the mid/right panels with local clip ranges", start)

    def test_label_discipline_forbids_copying_design_sheet(self) -> None:
        from backend.app.llm_minimax_skills import H3_REF2VA_LABEL_DISCIPLINE

        self.assertIn("design sheet", H3_REF2VA_LABEL_DISCIPLINE)
        self.assertIn("panel grid", H3_REF2VA_LABEL_DISCIPLINE)
        self.assertIn("white background", H3_REF2VA_LABEL_DISCIPLINE)
        self.assertIn("mini figures", H3_REF2VA_LABEL_DISCIPLINE)
        self.assertIn("prop design sheet", H3_REF2VA_LABEL_DISCIPLINE)
        self.assertIn("repeated mini objects", H3_REF2VA_LABEL_DISCIPLINE)

    def test_packing_rules_forbid_copying_design_sheet_grid(self) -> None:
        from backend.app.llm_minimax_skills import H3_REF2VA_LABEL_DISCIPLINE

        text = H3PromptBuilder.packing_system_prompt("Ref2VA", 8)
        self.assertIn("multi-view design sheets", text)
        self.assertIn("panel grid", text)
        self.assertIn("prop stills", text)
        self.assertIn("repeated mini objects", text)
        self.assertIn("repeated mini figures", H3_REF2VA_LABEL_DISCIPLINE)
        self.assertIn("repeated mini objects", H3_REF2VA_LABEL_DISCIPLINE)

    def test_packing_user_maps_pictures_without_rewriting_bios(self) -> None:
        from backend.app.media_studio.services.llm_service import LlmService

        text = LlmService._h3_user_prompt(
            {
                "sequence": 1,
                "characters": [
                    {"name": "吴耐", "look_desc": "惊讶续命系统，秃顶灰白头发。"},
                    {"name": "沙丽丽", "desc": "好赌的父亲，红色吊带。"},
                ],
                "props": [{"name": "旧木书箱", "desc": "开裂红木箱，铜扣生锈"}],
                "ref_images": [
                    {"index": 1, "name": "吴耐", "category": "character", "character_id": "c-wu"},
                    {"index": 2, "name": "沙丽丽", "category": "character"},
                    {"index": 3, "name": "单元楼电梯", "category": "scene"},
                    {"index": 4, "name": "旧木书箱", "category": "prop"},
                ],
                "dialogue": "你好。",
            },
            "Ref2VA",
            "8",
        )
        self.assertIn("<Picture 1>: 吴耐（角色参考图）", text)
        self.assertIn("<Picture 4>: 旧木书箱（道具参考图）", text)
        self.assertIn("道具 Picture 只锁外形与材质、不抄分格/白底/重复小物件", text)
        self.assertIn("禁止重写小传", text)
        self.assertNotIn("惊讶续命", text)
        self.assertNotIn("好赌的父亲", text)

    def test_subject_definition_lines_use_prop_sheet_lock(self) -> None:
        lines = H3PromptBuilder._subject_definition_lines({
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "旧木书箱", "category": "prop"},
                {"index": 3, "name": "书房", "category": "scene"},
            ],
            "character_references": [{"character_id": "c-wu", "character_name": "吴耐"}],
        })
        joined = "\n".join(lines)
        self.assertIn("prop design sheet", joined)
        self.assertIn("repeated mini objects", joined)
        self.assertIn("<Subject 2> is 旧木书箱 in <Picture 2>.", joined)


class DeterministicCoverageValidationTests(unittest.TestCase):
    def test_validate_rejects_gaze_open_inner_and_door(self) -> None:
        from backend.app.director_craft.coverage import coverage_prompt_errors
        from backend.app.media_studio.services.llm_service import LlmService

        events = H3PromptBuilder.ordered_speech_events(HUAJIA_BEAT)
        prompt = (
            "subject_definitions:\n"
            "<Subject 1> is 吴耐 in <Picture 1>.\n"
            "summary:\nx\nretention_analysis:\nx\n"
            "detailed_description:\n[Shot 1] Already inside. The camera follows his gaze. "
            "(S2) 沙丽丽 says <d>[Chinese] 大爷，我什么都可以做。</d> "
            "(S1) 吴耐 says <d>[Chinese] 浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。</d> "
            "Elevator doors shut. "
            "(S1) 吴耐 says <d>[Chinese] 不用想也知道，做的是什么。</d>\n"
            "overall_soundscape:\nsound\nnon_diegetic_music:\nN/A"
        )
        errors = coverage_prompt_errors(prompt, HUAJIA_BEAT, events)
        joined = " ".join(errors)
        self.assertIn("gaze", joined)
        self.assertIn("closed", joined)
        self.assertIn("coverage subject", joined)
        self.assertIn("doors opening", joined)
        self.assertIn("tilt up", joined)
        self.assertIn("push-in", joined)

        generated = H3PromptBuilder.render_ref2va(H3PromptBuilder.shot_from_beat_info({
            **HUAJIA_BEAT,
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "沙丽丽", "category": "character"},
                {"index": 3, "name": "单元楼电梯", "category": "scene"},
            ],
        }))
        self.assertEqual([], LlmService._validate_h3_prompt(generated, "Ref2VA", {
            **HUAJIA_BEAT,
            "ref_images": [
                {"index": 1, "name": "吴耐", "category": "character"},
                {"index": 2, "name": "沙丽丽", "category": "character"},
                {"index": 3, "name": "单元楼电梯", "category": "scene"},
            ],
        }))

    def test_cast_lock_in_detail_fails_authority_check(self) -> None:
        from backend.app.director_craft.references import reference_authority_errors

        prompt = (
            "subject_definitions:\n<Subject 1> is 吴耐 in <Picture 1>.\n"
            "summary:\nx\nretention_analysis:\nx\n"
            "detailed_description:\nCAST LOCK, do not beautify or swap faces: skinny landlord.\n"
            "overall_soundscape:\nsound\nnon_diegetic_music:\nN/A"
        )
        errors = reference_authority_errors(prompt, HUAJIA_BEAT)
        self.assertTrue(any("CAST LOCK" in item for item in errors))

