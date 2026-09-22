from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient
from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
from backend.app.media_studio.services.prompt_expansion_service import PromptExpansionService
from backend.app.media_studio.services.prompt_templates import (
    FULL_REFERENCE_TEMPLATE_VERSION,
    PromptTemplateError,
    parse_director_output,
    parse_full_reference,
)
from backend.app.workflow_registry import WORKFLOWS


def full_reference_text() -> str:
    return """主体定义: <Subject 1> 是身穿蓝色外套的青年，外观参考 <Picture 1>。

摘要: 青年穿过雨夜车站。

保留分析: <Picture 1> 的脸部与服装 fully_preserved。

详细描述: [Shot 1] 00:00 青年沿站台前进，镜头平稳跟拍，霓虹倒映在地面。

整体声景: 雨声、脚步声与远处列车声保持清晰层次。

非叙事配乐: 低音弦乐缓慢推进，不覆盖环境声。"""


def director_text() -> str:
    return """===== 公共设定 =====
主体定义: <Subject 1> 是身穿蓝色外套的青年，外观参考 <Picture 1>。

===== 提示词组 1 =====
摘要: 青年进入雨夜车站。
保留分析: <Picture 1> 的人物身份 fully_preserved。
详细描述: [Shot 1] 00:00 青年走入站台，镜头跟随，最后停在抬头望向列车的稳定姿态。不要乱说话
整体声景: 雨声与脚步声连续。
非叙事配乐: 低音弦乐持续，不淡出。

===== 提示词组 2 =====
摘要: 青年发现远处来车。
保留分析: <Picture 1> 的人物身份 fully_preserved。
详细描述: 无硬切。紧接上一段。[Shot 2] [Shot 3] 00:00 青年保持抬头姿态，列车灯光扫过脸部，最后停在转身的稳定姿态。不要乱说话
整体声景: 上一段雨声延续并加入列车摩擦声。
非叙事配乐: 同一低音弦乐主题继续推进。
"""


def director_atomic_text(groups: list[dict[str, object]]) -> str:
    lines = ["===== 公共设定 =====", "主体定义: 16:9 横屏连续剧情，人物与场景保持一致。"]
    for index, group in enumerate(groups, start=1):
        prefix = "" if index == 1 else "无硬切。紧接上一段。"
        lines.extend([
            "",
            f"===== 提示词组 {index} =====",
            f"摘要: {group['summary']}",
            "保留分析: 严格保留已分配动作单元，不增加剧情事件。",
            f"详细描述: {prefix}[Shot {group['shot']}] 00:00 {group['detail']}，最后保持稳定交接姿态，不要乱说话",
            "整体声景: 环境底噪与人物动作声连续。",
            "非叙事配乐: 同一低音弦乐主题连续推进。",
        ])
    return "\n".join(lines)


class PromptTemplateTests(unittest.TestCase):
    slots = [{"index": 1, "token": "<Picture 1>", "asset_id": "asset-1"}]

    def test_full_reference_requires_six_sections_and_valid_references(self):
        parsed = parse_full_reference(full_reference_text(), "zh-CN", self.slots)
        self.assertEqual(
            [
                "subject_definitions",
                "summary",
                "retention_analysis",
                "detailed_description",
                "overall_soundscape",
                "non_diegetic_music",
            ],
            list(parsed["sections"]),
        )
        with self.assertRaisesRegex(PromptTemplateError, "不存在的参考图"):
            parse_full_reference(full_reference_text().replace("<Picture 1>", "<Picture 2>"), "zh-CN", self.slots)

    def test_full_reference_rejects_wrong_language_and_undefined_subject(self):
        wrong_language = full_reference_text()
        for chinese, english in (
            ("主体定义", "subject_definitions"),
            ("摘要", "summary"),
            ("保留分析", "retention_analysis"),
            ("详细描述", "detailed_description"),
            ("整体声景", "overall_soundscape"),
            ("非叙事配乐", "non_diegetic_music"),
        ):
            wrong_language = wrong_language.replace(chinese, english)
        with self.assertRaisesRegex(PromptTemplateError, "不是英文"):
            parse_full_reference(wrong_language, "en", self.slots)
        with self.assertRaisesRegex(PromptTemplateError, "未定义的主体"):
            parse_full_reference(full_reference_text().replace("[Shot 1]", "<Subject 2> [Shot 1]"), "zh-CN", self.slots)

    def test_director_requires_group_count_continuity_and_exact_shots(self):
        parsed = parse_director_output(
            director_text(),
            "zh-CN",
            self.slots,
            expected_groups=2,
            expected_shots=[[1], [2, 3]],
        )
        self.assertEqual([[1], [2, 3]], [group["shot_numbers"] for group in parsed["groups"]])
        with self.assertRaisesRegex(PromptTemplateError, "镜头编号应为"):
            parse_director_output(
                director_text().replace("[Shot 3]", "[Shot 4]"),
                "zh-CN",
                self.slots,
                expected_groups=2,
                expected_shots=[[1], [2, 3]],
            )
        with self.assertRaisesRegex(PromptTemplateError, "连续性语句"):
            parse_director_output(
                director_text().replace("无硬切。紧接上一段。", "随后，"),
                "zh-CN",
                self.slots,
                expected_groups=2,
            )

    @patch("backend.app.media_studio.services.prompt_expansion_service.LlmService.chat_text")
    def test_structure_error_retries_same_template_once(self, chat_text: MagicMock):
        chat_text.side_effect = ["主体定义: 截断", full_reference_text()]
        parsed, raw, retried = PromptExpansionService._generate_with_one_retry(
            "system-template",
            "source-material",
            lambda value: parse_full_reference(value, "zh-CN", self.slots),
        )
        self.assertTrue(retried)
        self.assertEqual(full_reference_text(), raw)
        self.assertIn("summary", parsed["sections"])
        self.assertEqual(2, chat_text.call_count)
        self.assertEqual("system-template", chat_text.call_args_list[0].args[0])
        self.assertEqual("system-template", chat_text.call_args_list[1].args[0])


class PromptPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = next(item for item in WORKFLOWS if item.prompt_profile == "director_segments")

    def test_director_part_shapes_for_2_6_7_12_segments(self):
        expected = {2: [2], 6: [6], 7: [4, 3], 12: [6, 6]}
        for count, shape in expected.items():
            with self.subTest(count=count):
                beats = [
                    {"id": f"beat-{index}", "sequence": index + 1, "video_duration": 8}
                    for index in range(count)
                ]
                parts = PromptExpansionService.plan_director_parts(beats, self.workflow, count)
                self.assertEqual(shape, [len(part["segments"]) for part in parts])
                self.assertTrue(all(2 <= len(part["segments"]) <= 6 for part in parts))
                self.assertTrue(all(part["frame_count"] <= 1152 for part in parts))

    def test_director_split_units_are_unique_and_non_overlapping(self):
        beats = [
            {"id": "beat-1", "sequence": 1, "story_shot": 1, "action": "整理古籍后白光爆发", "dialogue": "这篇古文", "video_duration": 15},
            {"id": "beat-2", "sequence": 2, "story_shot": 2, "action": "醒来并环顾破屋", "dialogue": "这里是什么地方？", "video_duration": 15},
            {"id": "beat-3", "sequence": 3, "story_shot": 3, "action": "打开米缸查看余粮", "dialogue": "最后半袋米", "video_duration": 10},
        ]
        parts = PromptExpansionService.plan_director_parts(beats, self.workflow, 5)
        units = [unit for part in parts for segment in part["segments"] for unit in segment["source_units"]]
        self.assertEqual(len(units), len({unit["id"] for unit in units}))
        self.assertEqual(len(units), len({unit["generated_shot_number"] for unit in units}))
        for beat_id in {beat["id"] for beat in beats}:
            beat_units = sorted((unit for unit in units if unit["source_beat_id"] == beat_id), key=lambda item: item["start_sec"])
            source_duration = next(beat["video_duration"] for beat in beats if beat["id"] == beat_id)
            self.assertAlmostEqual(0, beat_units[0]["start_sec"])
            self.assertAlmostEqual(source_duration, beat_units[-1]["end_sec"])
            self.assertAlmostEqual(source_duration, sum(unit["duration_seconds"] for unit in beat_units))
            for previous, current in zip(beat_units, beat_units[1:]):
                self.assertAlmostEqual(current["start_sec"], previous["end_sec"])

    def test_atomic_allocation_rejects_events_repeated_across_units(self):
        units = [
            {"id": "unit-1", "source_beat_id": "beat-1", "start_sec": 0, "end_sec": 7.5},
            {"id": "unit-2", "source_beat_id": "beat-1", "start_sec": 7.5, "end_sec": 15},
        ]
        parsed = {
            "unit-1": {"required_events": ["沈砚伸手接住古籍"], "dialogue_owner": [], "start_state": "坐在桌前", "handoff_state": "手伸向古籍"},
            "unit-2": {"required_events": ["沈砚伸手接住古籍"], "dialogue_owner": [], "start_state": "手伸向古籍", "handoff_state": "被白光吞没"},
        }
        with self.assertRaisesRegex(PromptTemplateError, "动作事件跨单元重复"):
            PromptExpansionService._validate_atomic_unit_allocation(
                parsed,
                units,
                [{"id": "beat-1", "action": "沈砚伸手接住古籍，随后被白光吞没"}],
            )

    def test_source_fingerprint_changes_with_beats_assets_and_workflow(self):
        source = {
            "episode": {"id": "ep-1", "title": "第一集", "script_text": "原剧本"},
            "data": {},
            "beats": [{"id": "beat-1", "sequence": 1, "action": "走入房间", "video_duration": 8}],
            "assets": [{"id": "asset-1", "kind": "character", "name": "主角", "image_url": "https://a/1.png"}],
        }
        request = {
            "template_version": FULL_REFERENCE_TEMPLATE_VERSION,
            "workflow_id": "workflow-a",
            "language": "zh-CN",
            "rewrite_mode": "strict",
            "aspect_ratio": "16:9",
            "target_segment_count": None,
            "reference_slots": [],
            "target": {"kind": "beat", "beat_id": "beat-1"},
        }
        first = PromptExpansionService.source_fingerprint(source, request)
        changed_source = json.loads(json.dumps(source, ensure_ascii=False))
        changed_source["beats"][0]["action"] = "跑入房间"
        self.assertNotEqual(first, PromptExpansionService.source_fingerprint(changed_source, request))
        changed_request = {**request, "workflow_id": "workflow-b"}
        self.assertNotEqual(first, PromptExpansionService.source_fingerprint(source, changed_request))


class DirectorGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = next(item for item in WORKFLOWS if item.prompt_profile == "director_segments")

    def payload_and_request(self, beats: list[dict], count: int) -> tuple[dict, dict]:
        planned_parts = PromptExpansionService.plan_director_parts(beats, self.workflow, count)
        return (
            {
                "planned_parts": planned_parts,
                "source_snapshot": {"beats": beats},
                "source_fingerprint": "fingerprint-1",
            },
            {
                "workflow_id": self.workflow.id,
                "template_version": "prompt-master/continuous-story@2",
                "language": "zh-CN",
                "rewrite_mode": "expand",
                "aspect_ratio": "16:9",
                "reference_slots": [],
            },
        )

    @staticmethod
    def planner_json(rows: list[dict[str, object]]) -> str:
        return json.dumps({"units": rows}, ensure_ascii=False)

    def two_segment_fixture(self) -> tuple[dict, dict, str, str, str]:
        beats = [
            {"id": "beat-1", "sequence": 1, "story_shot": 1, "action": "沈砚整理古籍", "dialogue": "第一句", "video_duration": 8},
            {"id": "beat-2", "sequence": 2, "story_shot": 2, "action": "苏婉打开米缸", "dialogue": "第二句", "video_duration": 8},
        ]
        payload, request = self.payload_and_request(beats, 2)
        planning = self.planner_json([
            {"unit_id": "unit-1-1", "required_events": ["沈砚整理古籍"], "dialogue_owner": ["第一句"], "start_state": "沈砚坐在桌前", "handoff_state": "沈砚双手扶住古籍"},
            {"unit_id": "unit-2-1", "required_events": ["苏婉打开米缸"], "dialogue_owner": ["第二句"], "start_state": "苏婉站在米缸前", "handoff_state": "苏婉扶住缸沿"},
        ])
        valid = director_atomic_text([
            {"shot": 1, "summary": "沈砚整理古籍", "detail": "沈砚整理古籍并说出第一句"},
            {"shot": 2, "summary": "苏婉打开米缸", "detail": "苏婉打开米缸并说出第二句"},
        ])
        duplicate = director_atomic_text([
            {"shot": 1, "summary": "沈砚整理古籍", "detail": "沈砚整理古籍并说出第一句"},
            {"shot": 2, "summary": "苏婉打开米缸", "detail": "苏婉打开米缸并再次说出第一句，随后说出第二句"},
        ])
        return payload, request, planning, valid, duplicate

    @patch("backend.app.media_studio.services.prompt_expansion_service.LlmService.chat_text")
    def test_director_generation_repairs_duplicate_once(self, chat_text: MagicMock):
        payload, request, planning, valid, duplicate = self.two_segment_fixture()
        chat_text.side_effect = [planning, duplicate, valid]

        preview = PromptExpansionService._generate_director_preview(payload, request)

        self.assertTrue(preview["retried"])
        PromptExpansionService.validate_director_plan(preview)
        self.assertEqual(3, chat_text.call_count)
        self.assertIn("对白在多个 Director 段重复或未落地", chat_text.call_args_list[2].args[1])
        prompts = [segment["prompt_text"] for part in preview["parts"] for segment in part["segments"]]
        self.assertEqual(1, sum(prompt.count("第一句") for prompt in prompts))
        self.assertEqual(1, sum(prompt.count("第二句") for prompt in prompts))

    @patch("backend.app.media_studio.services.prompt_expansion_service.LlmService.chat_text")
    def test_director_generation_fails_when_repair_still_duplicates(self, chat_text: MagicMock):
        payload, request, planning, _valid, duplicate = self.two_segment_fixture()
        chat_text.side_effect = [planning, duplicate, duplicate]

        with self.assertRaises(PromptTemplateError):
            PromptExpansionService._generate_director_preview(payload, request)
        self.assertEqual(3, chat_text.call_count)

    @patch("backend.app.media_studio.services.prompt_expansion_service.LlmService.chat_text")
    def test_part_boundary_passes_structured_handoff(self, chat_text: MagicMock):
        beats = [
            {"id": f"beat-{index}", "sequence": index, "story_shot": index, "action": f"事件{index}", "video_duration": 8}
            for index in range(1, 8)
        ]
        payload, request = self.payload_and_request(beats, 7)
        planning = self.planner_json([
            {
                "unit_id": f"unit-{index}-1",
                "required_events": [f"事件{index}"],
                "dialogue_owner": [],
                "start_state": f"状态{index - 1}",
                "handoff_state": f"状态{index}",
            }
            for index in range(1, 8)
        ])
        first_part = director_atomic_text([
            {"shot": index, "summary": f"事件{index}", "detail": f"事件{index}"}
            for index in range(1, 5)
        ])
        second_part = director_atomic_text([
            {"shot": index, "summary": f"事件{index}", "detail": f"事件{index}"}
            for index in range(5, 8)
        ])
        chat_text.side_effect = [planning, first_part, second_part]

        preview = PromptExpansionService._generate_director_preview(payload, request)

        self.assertEqual(2, len(preview["parts"]))
        self.assertEqual("状态4", preview["parts"][1]["handoff_from_previous_part"]["state"])
        self.assertIn('\"state\":\"状态4\"', chat_text.call_args_list[2].args[1])

    @patch.object(PromptExpansionService, "kick")
    @patch("backend.app.media_studio.services.prompt_expansion_service._EVENTS.emit")
    @patch("backend.app.media_studio.services.prompt_expansion_service.execute_sql")
    @patch("backend.app.media_studio.services.prompt_expansion_service.query_one")
    @patch("backend.app.media_studio.services.prompt_expansion_service.LlmService.chat_text")
    def test_failed_semantic_repair_marks_job_failed_without_preview(
        self,
        chat_text: MagicMock,
        query_one: MagicMock,
        execute_sql: MagicMock,
        _emit: MagicMock,
        _kick: MagicMock,
    ):
        payload, request, planning, _valid, duplicate = self.two_segment_fixture()
        payload["request"] = {**request, "prompt_profile": "director_segments"}
        row = {"payload_json": json.dumps(payload, ensure_ascii=False)}
        query_one.side_effect = [row, row]
        chat_text.side_effect = [planning, duplicate, duplicate]

        PromptExpansionService._run("job-1")

        sql_calls = [call.args for call in execute_sql.call_args_list]
        self.assertTrue(any("status='failed'" in sql for sql, _params in sql_calls))
        self.assertFalse(any("UPDATE ai_project_episodes" in sql for sql, _params in sql_calls))
        failed_params = next(params for sql, params in sql_calls if "status='failed'" in sql)
        self.assertNotIn("preview", json.loads(failed_params[1]))


class PromptPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.workflow = next(item for item in WORKFLOWS if item.prompt_profile == "full_reference")
        self.source = {
            "episode": {"id": "ep-1", "title": "第一集", "script_text": "原剧本"},
            "data": {"beats": [{"id": "beat-1", "sequence": 1, "action": "走入房间", "video_duration": 8}]},
            "beats": [{"id": "beat-1", "sequence": 1, "action": "走入房间", "video_duration": 8}],
            "assets": [],
        }

    @patch.object(PromptExpansionService, "kick")
    @patch("backend.app.media_studio.services.prompt_expansion_service.query_all", return_value=[])
    @patch("backend.app.media_studio.services.prompt_expansion_service.execute_sql")
    @patch.object(PromptExpansionService, "_load_source")
    def test_enqueue_creates_preview_job_without_writing_episode(self, load_source, execute_sql, _query_all, _kick):
        load_source.return_value = self.source
        result = PromptExpansionService.enqueue("proj-1", "ep-1", {
            "workflow_id": self.workflow.id,
            "target": {"kind": "beat", "beat_id": "beat-1"},
            "language": "zh-CN",
            "rewrite_mode": "strict",
            "aspect_ratio": "16:9",
            "reference_slots": [],
        })
        self.assertEqual("queued", result["status"])
        sql = execute_sql.call_args.args[0]
        self.assertIn("INSERT INTO ai_project_jobs", sql)
        self.assertNotIn("UPDATE ai_project_episodes", sql)

    def test_apply_is_atomic_and_rejects_changed_source(self):
        request = {
            "workflow_id": self.workflow.id,
            "template_version": FULL_REFERENCE_TEMPLATE_VERSION,
            "prompt_profile": "full_reference",
            "target": {"kind": "beat", "beat_id": "beat-1"},
            "language": "zh-CN",
            "rewrite_mode": "strict",
            "aspect_ratio": "16:9",
            "target_segment_count": None,
            "reference_slots": [],
        }
        fingerprint = PromptExpansionService.source_fingerprint(self.source, request)
        preview = {
            "kind": "full_reference",
            "beat_id": "beat-1",
            "template_version": FULL_REFERENCE_TEMPLATE_VERSION,
            "language": "zh-CN",
            "source_fingerprint": fingerprint,
            "reference_slots": [],
            **parse_full_reference(full_reference_text().replace("<Picture 1>", "人物参考"), "zh-CN", []),
        }
        job = {
            "job_type": "prompt_expansion",
            "status": "completed",
            "payload_json": json.dumps({
                "episode_id": "ep-1",
                "source_fingerprint": fingerprint,
                "request": request,
                "preview": preview,
            }, ensure_ascii=False),
        }

        class Cursor:
            def __init__(self, episode_data):
                self.last_sql = ""
                self.updates = []
                self.episode_data = episode_data

            def execute(self, sql, params):
                self.last_sql = sql
                if "UPDATE ai_project_episodes" in sql:
                    self.updates.append(params)

            def fetchone(self):
                return {
                    "id": "ep-1",
                    "title": "第一集",
                    "script_text": "原剧本",
                    "data_json": json.dumps(self.episode_data, ensure_ascii=False),
                }

            def fetchall(self):
                return []

        self_data = self.source["data"]
        cursor = Cursor(self_data)

        @contextmanager
        def transaction():
            yield cursor

        with (
            patch("backend.app.media_studio.services.prompt_expansion_service.query_one", return_value=job),
            patch("backend.app.media_studio.services.prompt_expansion_service.transaction_cursor", transaction),
        ):
            result = PromptExpansionService.apply_preview(
                "proj-1", "ep-1", "job-1", {"expected_source_fingerprint": fingerprint}
            )
        self.assertEqual("applied", result["status"])
        saved = json.loads(cursor.updates[0][0])
        self.assertEqual("prompt_master_full_reference", saved["beats"][0]["h3_prompt_source"])

        changed_data = json.loads(json.dumps(self.source["data"], ensure_ascii=False))
        changed_data["beats"][0]["action"] = "内容已经变化"
        changed_cursor = Cursor(changed_data)

        @contextmanager
        def changed_transaction():
            yield changed_cursor

        with (
            patch("backend.app.media_studio.services.prompt_expansion_service.query_one", return_value=job),
            patch("backend.app.media_studio.services.prompt_expansion_service.transaction_cursor", changed_transaction),
        ):
            with self.assertRaisesRegex(RuntimeError, "SOURCE_CONFLICT"):
                PromptExpansionService.apply_preview(
                    "proj-1", "ep-1", "job-1", {"expected_source_fingerprint": fingerprint}
                )

    def test_patch_director_plan_rejects_revision_conflict(self):
        class Cursor:
            def __init__(self):
                self.updates = []

            def execute(self, sql, params):
                if "UPDATE ai_project_episodes" in sql:
                    self.updates.append(params)

            def fetchone(self):
                return {
                    "data_json": json.dumps(
                        {"prompt_authoring": {"director_plan": {"revision": 3}}},
                        ensure_ascii=False,
                    )
                }

        cursor = Cursor()

        @contextmanager
        def transaction():
            yield cursor

        with patch(
            "backend.app.media_studio.services.prompt_expansion_service.transaction_cursor",
            transaction,
        ):
            with self.assertRaisesRegex(RuntimeError, "REVISION_CONFLICT"):
                PromptExpansionService.patch_director_plan(
                    "proj-1",
                    "ep-1",
                    {"expected_revision": 2},
                )
        self.assertEqual([], cursor.updates)


class DirectorVideoTests(unittest.TestCase):
    @staticmethod
    def plan() -> dict:
        def segment(index: int) -> dict:
            sections = {
                "summary": f"摘要 {index}",
                "retention_analysis": "保留",
                "detailed_description": f"[Shot {index}] 详细描述",
                "overall_soundscape": "声景",
                "non_diegetic_music": "配乐",
            }
            unit = {
                "id": f"unit-{index}",
                "source_beat_id": f"beat-{index}",
                "source_shot_number": index,
                "generated_shot_number": index,
                "chunk_index": 0,
                "chunk_count": 1,
                "start_sec": 0,
                "end_sec": 8,
                "duration_seconds": 8,
                "required_events": [f"事件 {index}"],
                "dialogue_owner": [],
                "start_state": "",
                "handoff_state": "",
            }
            return {
                "id": f"seg-{index}", "title": f"段 {index}", "duration_seconds": 8, "frame_count": 192,
                "sections": sections, "prompt_text": "\n".join(f"{key}: {value}" for key, value in sections.items()),
                "source_beat_ids": [f"beat-{index}"], "source_units": [unit],
                "shots": [{"shot_number": index, "source_beat_id": f"beat-{index}"}],
            }
        return {
            "id": "plan-1",
            "revision": 3,
            "status": "current",
            "schema_version": 2,
            "planning_strategy": "atomic_units",
            "common_setting": {"subject_definitions": "公共主体定义"},
            "reference_slots": [{"image_url": "https://a/ref.png"}],
            "parts": [
                {
                    "id": "part-1", "segments": [segment(index) for index in range(1, 4)],
                },
                {
                    "id": "part-2", "segments": [segment(index) for index in range(4, 6)],
                },
            ],
        }

    def test_episode_and_contiguous_selection_mapping(self):
        detail = {"prompt_authoring": {"director_plan": self.plan()}}
        shots, _plan, scope = EpisodeVideoService._director_plan_shots(detail, {
            "render_scope": "episode",
            "director_plan_revision": 3,
        })
        self.assertEqual("episode", scope)
        self.assertEqual([False, True, True, False, True], [shot["continuity_from_prev"] for shot in shots])
        self.assertTrue(shots[3]["part_boundary"])

        selected, _plan, scope = EpisodeVideoService._director_plan_shots(detail, {
            "render_scope": "selection",
            "director_plan_revision": 3,
            "part_id": "part-1",
            "segment_ids": ["seg-2", "seg-3"],
        })
        self.assertEqual("selection", scope)
        self.assertEqual([False, True], [shot["continuity_from_prev"] for shot in selected])
        with self.assertRaisesRegex(ValueError, "连续"):
            EpisodeVideoService._director_plan_shots(detail, {
                "render_scope": "selection",
                "part_id": "part-1",
                "segment_ids": ["seg-1", "seg-3"],
            })
        with self.assertRaisesRegex(ValueError, "不属于同一 Part"):
            EpisodeVideoService._director_plan_shots(detail, {
                "render_scope": "selection",
                "part_id": "part-1",
                "segment_ids": ["seg-2", "seg-4"],
            })

    def test_legacy_or_unitless_director_plan_cannot_render(self):
        legacy = self.plan()
        legacy.pop("schema_version")
        with self.assertRaisesRegex(ValueError, "结构已升级"):
            EpisodeVideoService._director_plan_shots(
                {"prompt_authoring": {"director_plan": legacy}},
                {"render_scope": "episode"},
            )

        unitless = self.plan()
        unitless["parts"][0]["segments"][0].pop("source_units")
        with self.assertRaisesRegex(ValueError, "结构已升级"):
            EpisodeVideoService._director_plan_shots(
                {"prompt_authoring": {"director_plan": unitless}},
                {"render_scope": "episode"},
            )

    def test_legacy_director_plan_is_hydrated_as_stale(self):
        legacy = self.plan()
        legacy.pop("schema_version")
        state = PromptExpansionService.hydrated_authoring_state(
            "proj-1",
            {"id": "ep-1", "title": "第一集"},
            {"prompt_authoring": {"director_plan": legacy}},
            [],
            [],
        )
        hydrated = state["director_plan"]
        self.assertEqual("stale", hydrated["status"])
        self.assertEqual("DIRECTOR_PLAN_SCHEMA_OUTDATED", hydrated["invalid_reason"])

    def test_timeline_receives_global_prompt_and_continuity(self):
        shots = [
            {"beat_id": "seg-1", "prompt": "one", "duration_sec": 8, "continuity_from_prev": False, "uploaded_refs": []},
            {"beat_id": "seg-2", "prompt": "two", "duration_sec": 8, "continuity_from_prev": True, "uploaded_refs": []},
        ]
        timeline = ComfyVideoClient.build_timeline(
            shots,
            "r2v",
            options={"global_prompt": "公共主体定义", "continuity_enabled": True},
        )
        self.assertEqual("公共主体定义", timeline["global"]["prompt"])
        self.assertTrue(timeline["output"]["continuityEnabled"])
        self.assertEqual([False, True], [item["continuityFromPrev"] for item in timeline["segments"]])

    @patch("backend.app.media_studio.services.episode_video_service._EXECUTOR.submit")
    @patch("backend.app.media_studio.services.episode_video_service.execute_sql")
    @patch("backend.app.media_studio.services.llm_service.LlmService.chat_text")
    @patch.object(EpisodeVideoService, "_assert_can_enqueue")
    @patch("backend.app.media_studio.services.episode_video_service.ComfyVideoClient.preflight", return_value="r2v")
    @patch("backend.app.media_studio.services.episode_video_service.ComfyService.get_config")
    @patch("backend.app.media_studio.services.episode_video_service.ProjectDetailService.list_assets", return_value=[])
    @patch("backend.app.media_studio.services.episode_video_service.ProjectDetailService.get_episode_detail")
    def test_video_submission_never_calls_llm(self, get_detail, _assets, config, _preflight, _enqueue, chat_text, execute_sql, submit):
        plan = self.plan()
        get_detail.return_value = {"number": 1, "title": "第一集", "prompt_authoring": {"director_plan": plan}}
        config.return_value = SimpleNamespace(base_url="http://127.0.0.1:8188")
        workflow = next(item for item in WORKFLOWS if item.prompt_profile == "director_segments")
        result = EpisodeVideoService.create_job(
            "proj-1",
            "ep-1",
            options={
                "workflow": workflow.id,
                "render_scope": "episode",
                "director_plan_revision": 3,
            },
        )
        self.assertEqual("queued", result["status"])
        chat_text.assert_not_called()
        execute_sql.assert_called_once()
        submit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
