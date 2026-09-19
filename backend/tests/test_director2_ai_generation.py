from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import Mock, patch

from backend.app.media_studio.services.ai_generation_service import (
    AiGenerationService,
    AiOperationCancelled,
)
from backend.app.director_recipe import empty_recipe_payload
from backend.app.llm_minimax_skills import normalize_clarify_questions


class Director2AiActiveJobTests(unittest.TestCase):
    def test_public_terminal_operation_includes_saved_recipe_snapshot(self) -> None:
        row = {
            "id": "aiop-terminal",
            "project_id": "project-1",
            "status": "failed",
            "progress": 80,
            "payload_json": json.dumps({
                "kind": "pipeline",
                "current_stage": "storyboard",
                "recipe": {"script": {"title": "已生成"}},
                "result": {"completed_stages": ["script", "assets", "episodes"]},
            }),
        }
        operation = AiGenerationService._public(row)
        self.assertEqual(operation["result"]["recipe"]["script"]["title"], "已生成")
        self.assertEqual(operation["stage_clarifications"], {})

    def test_public_exposes_stage_clarifications_for_choice_echo(self) -> None:
        row = {
            "id": "aiop-choices",
            "project_id": "project-1",
            "status": "awaiting_review",
            "progress": 40,
            "payload_json": json.dumps({
                "kind": "pipeline",
                "current_stage": "assets",
                "awaiting_stage": "assets",
                "request": {
                    "goal": "都市逆袭",
                    "clarifications": [{"id": "episode_count", "question": "这部剧分多少集？", "answer": "12集"}],
                },
                "stage_clarifications": {
                    "assets": [
                        {"agent": "characters", "question": "气质？", "answer": "更冷"},
                        {"agent": "locations", "question": "气质？", "answer": "更冷"},
                        {"agent": "props", "id": "revise_feedback", "question": "本轮调整诉求", "answer": "道具再少一点"},
                    ],
                    "script": "not-a-list",
                },
                "result": {"completed_stages": ["script"]},
                "recipe": {"script": {"title": "都市逆袭"}},
            }),
        }
        operation = AiGenerationService._public(row)
        self.assertEqual(operation["request"]["clarifications"][0]["answer"], "12集")
        assets = operation["stage_clarifications"]["assets"]
        self.assertEqual(len(assets), 3)
        self.assertEqual(assets[0]["answer"], "更冷")
        self.assertEqual(assets[2]["question"], "本轮调整诉求")
        self.assertNotIn("script", operation["stage_clarifications"])

    def test_director2_clarify_uses_episode_count_and_shots_per_episode(self) -> None:
        questions = normalize_clarify_questions([], include_beat_count=False, include_shots_per_episode=True)
        self.assertEqual(["episode_count", "shots_per_episode"], [item["id"] for item in questions])
        shots = questions[1]
        self.assertEqual(shots["question"], "每一集默认拍多少个镜头？")
        self.assertEqual([item["value"] for item in shots["options"]], ["4", "6", "8", "12"])
        self.assertEqual([item["value"] for item in shots["options"] if item.get("recommended")], ["6"])
        self.assertIn("导入", shots["why"])
        self.assertIn("出片镜", shots["why"])
        self.assertNotIn("还会再拆", shots["why"])

    def test_public_clarify_result_migrates_stale_beat_question(self) -> None:
        row = {
            "id": "aiop-legacy",
            "project_id": "project-1",
            "status": "succeeded",
            "progress": 100,
            "payload_json": json.dumps({
                "kind": "clarify",
                "request": {"goal": "故事"},
                "result": {"questions": [{"id": "beat_count", "question": "旧问题"}]},
            }),
        }
        questions = self._question_ids(AiGenerationService._public(row))
        self.assertEqual(["episode_count", "shots_per_episode"], questions)

    def test_ensure_director2_opening_questions_appends_shots_question(self) -> None:
        from backend.app.llm_minimax_skills import ensure_director2_opening_questions

        questions = ensure_director2_opening_questions([
            {"id": "q1", "question": "结局？", "options": [{"label": "反转", "value": "反转"}]},
            {"id": "episode_count", "question": "这部剧分多少集？"},
        ])
        self.assertEqual(["q1", "episode_count", "shots_per_episode"], [item["id"] for item in questions])
        self.assertEqual(questions[-1]["question"], "每一集默认拍多少个镜头？")
        self.assertEqual([item["value"] for item in questions[-1]["options"] if item.get("recommended")], ["6"])

    @staticmethod
    def _question_ids(operation: dict) -> list[str]:
        return [str(item.get("id")) for item in operation["result"]["questions"]]

    @staticmethod
    def _active_row() -> dict:
        return {
            "id": "aiop-f495dceebe66",
            "project_id": "project-1",
            "job_type": "ai_pipeline",
            "status": "running",
            "progress": 20,
            "error_message": None,
            "created_at": "2026-09-15 10:00:00",
            "updated_at": "2026-09-15 10:00:05",
            "payload_json": json.dumps({"kind": "pipeline", "request": {"goal": "都市逆袭"}, "current_stage": "script"}),
        }

    def test_create_rejects_when_project_has_active_job(self) -> None:
        service = AiGenerationService(None)
        with patch("backend.app.media_studio.services.ai_generation_service.query_one", return_value={"id": "aiop-f495dceebe66"}):
            with self.assertRaises(ValueError) as ctx:
                service.create("project-1", {"kind": "pipeline", "goal": "新的创意"})
        self.assertIn("aiop-f495dceebe66", str(ctx.exception))

    def test_get_active_returns_public_operation(self) -> None:
        service = AiGenerationService(None)
        with patch("backend.app.media_studio.services.ai_generation_service.query_one", return_value=self._active_row()):
            operation = service.get_active("project-1")
        self.assertIsNotNone(operation)
        self.assertEqual(operation["id"], "aiop-f495dceebe66")
        self.assertEqual(operation["status"], "running")
        self.assertEqual(operation["current_stage"], "script")

    def test_get_active_returns_none_without_active_job(self) -> None:
        service = AiGenerationService(None)
        with patch("backend.app.media_studio.services.ai_generation_service.query_one", return_value=None):
            self.assertIsNone(service.get_active("project-1"))

    def test_recover_orphaned_jobs_marks_active_rows_failed(self) -> None:
        service = AiGenerationService(None)
        row = self._active_row()
        with patch("backend.app.media_studio.services.ai_generation_service.query_all", return_value=[row]):
            with patch("backend.app.media_studio.services.ai_generation_service.execute_sql") as execute:
                AiGenerationService.recover_orphaned_jobs()
        sql, params = execute.call_args.args[0], execute.call_args.args[1]
        self.assertIn("status='failed'", sql)
        self.assertIn("服务进程重启", params[0])
        saved_payload = json.loads(params[1])
        self.assertIn("recovery", saved_payload)
        self.assertEqual(params[3], "aiop-f495dceebe66")


class Director2AiCancellationTests(unittest.TestCase):
    def test_failed_operation_records_stage_for_resume(self) -> None:
        service = AiGenerationService(None)
        row = {
            "id": "aiop-1",
            "project_id": "project-1",
            "job_type": "ai_pipeline",
            "status": "running",
            "payload_json": json.dumps({"kind": "pipeline", "current_stage": "storyboard", "result": {"completed_stages": ["script", "assets", "episodes"]}}),
        }
        service._read = Mock(return_value=row)  # type: ignore[method-assign]
        service._run_stage_leg = Mock(side_effect=RuntimeError("模型暂时不可用"))  # type: ignore[method-assign]
        service._update = Mock()  # type: ignore[method-assign]
        service._emit = Mock()  # type: ignore[method-assign]

        service._run_sync("aiop-1")

        payload = service._update.call_args.kwargs["payload"]
        self.assertEqual(payload["result"]["failed_stage"], "storyboard")

    def test_retry_is_idempotent_when_first_request_is_already_active(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value={
            "id": "aiop-1",
            "project_id": "project-1",
            "job_type": "ai_pipeline",
            "status": "queued",
            "payload_json": json.dumps({"kind": "pipeline", "current_stage": "storyboard"}),
        })  # type: ignore[method-assign]
        service.get = Mock(return_value={"id": "aiop-1", "status": "queued"})  # type: ignore[method-assign]
        service.start = Mock()  # type: ignore[method-assign]

        result = service.retry("aiop-1", "project-1")

        self.assertEqual(result["status"], "queued")
        service.start.assert_not_called()

    def test_cancel_persists_flag_and_emits_immediate_status(self) -> None:
        service = AiGenerationService(None)
        row = {
            "id": "aiop-1",
            "project_id": "project-1",
            "job_type": "ai_pipeline",
            "status": "running",
            "progress": 42,
            "payload_json": json.dumps({
                "kind": "pipeline",
                "current_stage": "assets",
                "result": {"completed_stages": ["script"]},
                "cancel_requested": False,
            }),
        }
        operation = {
            "id": "aiop-1",
            "project_id": "project-1",
            "status": "running",
            "progress": 42,
            "current_stage": "assets",
            "result": {"completed_stages": ["script"]},
            "cancel_requested": True,
        }
        service._read = Mock(return_value=row)  # type: ignore[method-assign]
        service.get = Mock(return_value=operation)  # type: ignore[method-assign]
        service._emit = Mock()  # type: ignore[method-assign]

        with patch("backend.app.media_studio.services.ai_generation_service.execute_sql") as execute:
            result = service.cancel("aiop-1", "project-1")

        saved_payload = json.loads(execute.call_args.args[1][0])
        self.assertTrue(saved_payload["cancel_requested"])
        self.assertIs(result, operation)
        emitted = service._emit.call_args.args[1]
        self.assertEqual(emitted["event"], "status")
        self.assertTrue(emitted["data"]["cancel_requested"])
        self.assertEqual(emitted["data"]["stage"], "assets")

    def test_cancel_exception_finishes_operation_as_cancelled(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value={  # type: ignore[method-assign]
            "id": "aiop-1",
            "project_id": "project-1",
            "job_type": "ai_pipeline",
            "status": "running",
            "payload_json": json.dumps({"kind": "pipeline", "request": {}}),
        })
        service._run_stage_leg = Mock(side_effect=AiOperationCancelled("AI 生成已取消"))  # type: ignore[method-assign]
        service._update = Mock()  # type: ignore[method-assign]
        service._emit = Mock()  # type: ignore[method-assign]

        service._run_sync("aiop-1")

        self.assertEqual(service._update.call_args.kwargs["status"], "cancelled")
        terminal = service._emit.call_args.args[1]
        self.assertEqual(terminal["event"], "cancelled")
        self.assertTrue(terminal["terminal"])

    def test_stale_worker_update_cannot_clear_cancel_request(self) -> None:
        service = AiGenerationService(None)
        row = {
            "id": "aiop-1",
            "project_id": "project-1",
            "job_type": "ai_pipeline",
            "status": "running",
            "payload_json": json.dumps({"cancel_requested": True}),
        }
        service._read = Mock(return_value=row)  # type: ignore[method-assign]

        with patch("backend.app.media_studio.services.ai_generation_service.execute_sql") as execute:
            service._update("aiop-1", payload={"cancel_requested": False, "result": {}})

        saved_payload = json.loads(execute.call_args.args[1][0])
        self.assertTrue(saved_payload["cancel_requested"])

    def test_retry_update_can_clear_cancel_request_from_terminal_state(self) -> None:
        service = AiGenerationService(None)
        row = {
            "id": "aiop-1",
            "project_id": "project-1",
            "job_type": "ai_pipeline",
            "status": "cancelled",
            "payload_json": json.dumps({"cancel_requested": True, "current_stage": "script"}),
        }
        service._read = Mock(return_value=row)  # type: ignore[method-assign]

        with patch("backend.app.media_studio.services.ai_generation_service.execute_sql") as execute:
            service._update("aiop-1", status="queued", payload={"cancel_requested": False, "run_stage": "script"})

        saved_payload = json.loads(execute.call_args.args[1][0])
        self.assertFalse(saved_payload["cancel_requested"])
        self.assertEqual(saved_payload["run_stage"], "script")

    def test_pipeline_exposes_episodes_before_storyboard(self) -> None:
        stages = list(AiGenerationService.STAGES)
        self.assertEqual(stages, ["script", "assets", "episodes", "storyboard"])
        self.assertEqual(AiGenerationService.STAGE_AGENTS["episodes"], ["episodes"])
        self.assertEqual(AiGenerationService.STAGE_AGENTS["storyboard"], ["storyboard"])
        self.assertLess(stages.index("episodes"), stages.index("storyboard"))
        self.assertEqual(
            AiGenerationService.AGENTS,
            ("script", "characters", "locations", "episodes", "storyboard"),
        )

        captured: list[list[str]] = []
        episode_recipe = empty_recipe_payload(title="测试", full_story="# 第1集 开场\n甲走进咖啡馆。\n# 第2集 终局\n乙揭开身份。")
        episode_recipe["episodes"] = [
            {"num": 1, "title": "开场", "summary": "落座", "targetShots": 8, "text": "甲走进咖啡馆。"},
            {"num": 2, "title": "终局", "summary": "相认", "targetShots": 12, "text": "乙揭开身份。"},
        ]
        episode_recipe["agentStatus"] = [
            {"id": "episodes", "status": "completed", "message": "正在拆分分集结构与戏剧节奏"},
        ]
        storyboard_recipe = {**episode_recipe, "agentStatus": [
            {"id": "episodes", "status": "completed"},
            {"id": "storyboard", "status": "completed", "message": "正在读剧本并构思 (1/3)"},
        ]}

        class Provider:
            @staticmethod
            def run_director_recipe(recipe, **kwargs):
                agents = list(kwargs.get("agents") or [])
                captured.append(agents)
                if agents == ["episodes"]:
                    running = {
                        **episode_recipe,
                        "agentStatus": [{"id": "episodes", "status": "running", "message": "正在拆分分集结构与戏剧节奏"}],
                    }
                    kwargs["on_progress"](running)
                    kwargs["on_stream"]({"event": "agent_item", "data": {"agent": "episodes", "field": "episodes", "index": 0, "item": {"title": "第 1 集 · 开场"}}})
                    return episode_recipe
                running = {
                    **storyboard_recipe,
                    "agentStatus": [{"id": "storyboard", "status": "running", "message": "正在读剧本并构思 (1/3)"}],
                }
                kwargs["on_progress"](running)
                return storyboard_recipe

        service = AiGenerationService(Provider())
        service._check_cancelled = Mock()  # type: ignore[method-assign]
        service._update = Mock()  # type: ignore[method-assign]
        service._adapt_recipe = Mock()  # type: ignore[method-assign]
        service._emit = Mock()  # type: ignore[method-assign]
        payload = {
            "kind": "pipeline",
            "request": {"project_id": "project-1"},
            "completed_stages": ["script", "assets"],
            "result": {},
            "current_stage": "episodes",
        }

        service._run_stage_leg("aiop-1", payload, {"project_id": "project-1", "goal": "故事"}, "episodes")
        self.assertEqual(payload["awaiting_stage"], "episodes")
        self.assertEqual(payload["result"].get("message"), "分集结构已生成，请确认或提出调整")
        payload["completed_stages"] = ["script", "assets", "episodes"]
        service._run_stage_leg("aiop-1", payload, {"project_id": "project-1", "goal": "故事"}, "storyboard")

        self.assertEqual(captured, [["episodes"], ["storyboard"]])
        adapt_stages = [call.args[2] for call in service._adapt_recipe.call_args_list]
        self.assertEqual(adapt_stages, ["episodes", "storyboard"])
        status_stages = [
            call.args[1]["data"].get("stage")
            for call in service._emit.call_args_list
            if call.args[1].get("event") == "status"
        ]
        self.assertIn("episodes", status_stages)
        self.assertIn("storyboard", status_stages)
        self.assertLess(status_stages.index("episodes"), status_stages.index("storyboard"))
        status_messages = [
            call.args[1]["data"].get("message")
            for call in service._emit.call_args_list
            if call.args[1].get("event") == "status"
        ]
        self.assertIn("正在拆分分集结构与戏剧节奏", status_messages)
        self.assertIn("正在读剧本并构思 (1/3)", status_messages)
        storyboard_status_messages = [
            call.args[1]["data"].get("message")
            for call in service._emit.call_args_list
            if call.args[1].get("event") == "status" and call.args[1]["data"].get("stage") == "storyboard"
        ]
        self.assertNotIn("正在生成 Beat、对白、动作与机位", storyboard_status_messages)

    def test_running_result_keeps_live_message(self) -> None:
        payload = {"completed_stages": ["script", "assets"], "result": {"message": "正在读剧本并构思 (1/3)"}}
        self.assertEqual(
            AiGenerationService._running_result(payload)["message"],
            "正在读剧本并构思 (1/3)",
        )
        self.assertEqual(
            AiGenerationService._running_result(payload, "正在写分镜 (1/3) - 已收 12 字")["message"],
            "正在写分镜 (1/3) - 已收 12 字",
        )

    def test_running_update_clears_stale_error(self) -> None:
        service = AiGenerationService(None)
        row = {
            "id": "aiop-1",
            "project_id": "project-1",
            "job_type": "ai_pipeline",
            "status": "running",
            "payload_json": json.dumps({"result": {}}),
            "error_message": "服务进程重启，AI 任务已中断，请重新提交或重试。",
        }
        service._read = Mock(return_value=row)  # type: ignore[method-assign]
        with patch("backend.app.media_studio.services.ai_generation_service.execute_sql") as execute:
            service._update("aiop-1", status="running", progress=65, payload={"result": {"message": "正在写分镜"}})
        sql = execute.call_args.args[0]
        values = execute.call_args.args[1]
        self.assertIn("error_message=%s", sql)
        self.assertIsNone(values[-2])


class Director2AiCheckpointTests(unittest.TestCase):
    """逐 leg 卡点：暂停确认、采纳推进、对话修订、只重跑当前步。"""

    @staticmethod
    def _review_row(
        *,
        stage: str = "script",
        status: str = "awaiting_review",
        completed: list[str] | None = None,
        extra_payload: dict | None = None,
    ) -> dict:
        payload = {
            "kind": "pipeline",
            "request": {"goal": "都市逆袭", "project_id": "project-1"},
            "awaiting_stage": stage,
            "current_stage": stage,
            "completed_stages": list(completed or []),
            "stage_plan": ["script", "assets", "episodes", "storyboard"],
            "stage_clarifications": {},
            "result": {"message": "请确认", "completed_stages": list(completed or [])},
            "recipe": {"script": {"title": "都市逆袭"}},
            "cancel_requested": False,
        }
        if extra_payload:
            payload.update(extra_payload)
        return {
            "id": "aiop-1",
            "project_id": "project-1",
            "job_type": "ai_pipeline",
            "status": status,
            "progress": 25,
            "error_message": None,
            "payload_json": json.dumps(payload),
            "created_at": "2026-09-16 10:00:00",
            "updated_at": "2026-09-16 10:00:05",
        }

    def test_public_review_operation_includes_recipe_snapshot(self) -> None:
        row = {
            "id": "aiop-review",
            "project_id": "project-1",
            "status": "awaiting_review",
            "progress": 25,
            "payload_json": json.dumps({
                "kind": "pipeline",
                "current_stage": "script",
                "awaiting_stage": "script",
                "recipe": {"script": {"title": "待确认剧本"}},
                "result": {"completed_stages": []},
            }),
        }
        operation = AiGenerationService._public(row)
        self.assertEqual(operation["status"], "awaiting_review")
        self.assertEqual(operation["awaiting_stage"], "script")
        self.assertEqual(operation["result"]["recipe"]["script"]["title"], "待确认剧本")

    def test_create_rejects_when_project_is_awaiting_review_or_revising(self) -> None:
        service = AiGenerationService(None)
        captured: dict[str, str] = {}

        def fake_query_one(sql: str, _params: tuple) -> dict:
            captured["sql"] = sql
            return {"id": "aiop-review"}

        with patch("backend.app.media_studio.services.ai_generation_service.query_one", side_effect=fake_query_one):
            with self.assertRaises(ValueError) as ctx:
                service.create("project-1", {"kind": "pipeline", "goal": "新的创意"})
        self.assertIn("awaiting_review", captured["sql"])
        self.assertIn("revising", captured["sql"])
        self.assertIn("aiop-review", str(ctx.exception))

    def test_get_active_reattaches_awaiting_review(self) -> None:
        service = AiGenerationService(None)
        row = self._review_row(stage="assets", completed=["script"])
        with patch("backend.app.media_studio.services.ai_generation_service.query_one", return_value=row):
            operation = service.get_active("project-1")
        self.assertIsNotNone(operation)
        self.assertEqual(operation["status"], "awaiting_review")
        self.assertEqual(operation["awaiting_stage"], "assets")

    def test_recover_orphaned_jobs_leaves_awaiting_review(self) -> None:
        with patch("backend.app.media_studio.services.ai_generation_service.query_all", return_value=[]) as query_all:
            AiGenerationService.recover_orphaned_jobs()
        sql = query_all.call_args.args[0]
        self.assertIn("revising", sql)
        self.assertNotIn("awaiting_review", sql)

    def test_stage_leg_pauses_at_awaiting_review_without_terminal(self) -> None:
        class Provider:
            @staticmethod
            def run_director_recipe(recipe, **kwargs):
                kwargs["on_progress"]({
                    **recipe,
                    "agentStatus": [{"id": "script", "status": "running", "message": "正在根据创意写剧本"}],
                })
                return {**recipe, "script": {"title": "都市逆袭", "fullStory": "甲走进咖啡馆。"}}

        service = AiGenerationService(Provider())
        service._check_cancelled = Mock()  # type: ignore[method-assign]
        service._update = Mock()  # type: ignore[method-assign]
        service._adapt_recipe = Mock()  # type: ignore[method-assign]
        service._emit = Mock()  # type: ignore[method-assign]
        payload = {
            "kind": "pipeline",
            "request": {"project_id": "project-1"},
            "completed_stages": [],
            "result": {},
            "current_stage": "script",
        }

        service._run_stage_leg("aiop-1", payload, {"project_id": "project-1", "goal": "故事"}, "script")

        self.assertEqual(payload["awaiting_stage"], "script")
        self.assertEqual(payload["completed_stages"], [])
        self.assertEqual(payload["result"].get("message"), "剧本已生成，请确认或提出调整")
        statuses = [call.kwargs.get("status") for call in service._update.call_args_list]
        self.assertIn("awaiting_review", statuses)
        events = [call.args[1] for call in service._emit.call_args_list]
        review_events = [
            event for event in events
            if event.get("event") == "status" and event.get("data", {}).get("status") == "awaiting_review"
        ]
        self.assertEqual(len(review_events), 1)
        self.assertEqual(review_events[0]["data"]["awaiting_stage"], "script")
        self.assertFalse(any(event.get("terminal") for event in events))

    def test_advance_queues_next_stage(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value=self._review_row(stage="script"))  # type: ignore[method-assign]
        service._update = Mock()  # type: ignore[method-assign]
        service._emit = Mock()  # type: ignore[method-assign]
        service.start = Mock()  # type: ignore[method-assign]
        service.get = Mock(return_value={"id": "aiop-1", "status": "queued", "current_stage": "assets"})  # type: ignore[method-assign]

        result = service.advance("aiop-1", "project-1")

        self.assertEqual(result["status"], "queued")
        kwargs = service._update.call_args.kwargs
        self.assertEqual(kwargs["status"], "queued")
        payload = kwargs["payload"]
        self.assertEqual(payload["completed_stages"], ["script"])
        self.assertEqual(payload["run_action"], "leg")
        self.assertEqual(payload["run_stage"], "assets")
        self.assertIsNone(payload.get("awaiting_stage"))
        service.start.assert_called_once_with("aiop-1")
        service._emit.assert_not_called()

    def test_advance_last_stage_succeeds(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value=self._review_row(  # type: ignore[method-assign]
            stage="storyboard",
            completed=["script", "assets", "episodes"],
        ))
        service._update = Mock()  # type: ignore[method-assign]
        service._emit = Mock()  # type: ignore[method-assign]
        service.start = Mock()  # type: ignore[method-assign]
        service.get = Mock(return_value={"id": "aiop-1", "status": "succeeded"})  # type: ignore[method-assign]

        service.advance("aiop-1", "project-1")

        kwargs = service._update.call_args.kwargs
        self.assertEqual(kwargs["status"], "succeeded")
        self.assertEqual(kwargs["progress"], 100)
        self.assertEqual(kwargs["payload"]["completed_stages"], ["script", "assets", "episodes", "storyboard"])
        service.start.assert_not_called()
        terminal = service._emit.call_args.args[1]
        self.assertEqual(terminal["event"], "done")
        self.assertTrue(terminal["terminal"])

    def test_advance_rejects_when_not_awaiting_review(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value=self._review_row(status="running"))  # type: ignore[method-assign]
        with self.assertRaises(ValueError) as ctx:
            service.advance("aiop-1", "project-1")
        self.assertIn("待确认", str(ctx.exception))

    def test_revise_starts_stage_clarify_from_awaiting_review(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value=self._review_row(stage="episodes", completed=["script", "assets"]))  # type: ignore[method-assign]
        service._update = Mock()  # type: ignore[method-assign]
        service.start = Mock()  # type: ignore[method-assign]
        service.get = Mock(return_value={"id": "aiop-1", "status": "revising"})  # type: ignore[method-assign]

        result = service.revise("aiop-1", "project-1", "高潮再往后挪一集")

        self.assertEqual(result["status"], "revising")
        kwargs = service._update.call_args.kwargs
        self.assertEqual(kwargs["status"], "revising")
        payload = kwargs["payload"]
        self.assertEqual(payload["run_action"], "revise")
        self.assertEqual(payload["revise_stage"], "episodes")
        self.assertEqual(payload["revise_feedback"], "高潮再往后挪一集")
        service.start.assert_called_once_with("aiop-1")

    def test_revise_rejects_empty_feedback(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value=self._review_row())  # type: ignore[method-assign]
        with self.assertRaises(ValueError) as ctx:
            service.revise("aiop-1", "project-1", "   ")
        self.assertIn("想怎么调整", str(ctx.exception))

    def test_run_revise_stores_questions_without_terminal(self) -> None:
        captured: dict[str, Any] = {}
        questions = [{"id": "climax", "question": "高潮落在哪一集？"}]

        class Provider:
            @staticmethod
            def run_director_clarify(goal, **kwargs):
                captured.update(kwargs)
                kwargs["on_stream"]({"event": "question", "data": questions[0]})
                return questions

        service = AiGenerationService(Provider())
        service._check_cancelled = Mock()  # type: ignore[method-assign]
        service._update = Mock()  # type: ignore[method-assign]
        service._emit = Mock()  # type: ignore[method-assign]
        payload = {
            "kind": "pipeline",
            "request": {"goal": "都市逆袭"},
            "awaiting_stage": "episodes",
            "revise_stage": "episodes",
            "revise_feedback": "高潮再往后挪一集",
            "completed_stages": ["script", "assets"],
            "result": {},
            "recipe": {"episodes": [{"num": 1, "title": "开场"}]},
        }

        service._run_revise("aiop-1", payload, {"goal": "都市逆袭"})

        self.assertEqual(captured["agent"], "episodes")
        self.assertEqual(captured["feedback"], "高潮再往后挪一集")
        self.assertEqual(payload["result"]["questions"], questions)
        self.assertEqual(service._update.call_args.kwargs["status"], "revising")
        events = [call.args[1] for call in service._emit.call_args_list]
        self.assertTrue(any(event.get("data", {}).get("questions_ready") for event in events))
        self.assertFalse(any(event.get("terminal") for event in events))

    def test_rerun_stage_merges_answers_and_queues_current_leg(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value=self._review_row(  # type: ignore[method-assign]
            stage="assets",
            status="revising",
            completed=["script"],
            extra_payload={
                "revise_stage": "assets",
                "revise_feedback": "道具再少一点",
            },
        ))
        service._update = Mock()  # type: ignore[method-assign]
        service.start = Mock()  # type: ignore[method-assign]
        service.get = Mock(return_value={"id": "aiop-1", "status": "queued"})  # type: ignore[method-assign]

        service.rerun_stage("aiop-1", "project-1", [
            {"id": "prop", "question": "标志性道具？", "answer": "一把旧雨伞", "label": "一把旧雨伞"},
        ])

        payload = service._update.call_args.kwargs["payload"]
        self.assertEqual(service._update.call_args.kwargs["status"], "queued")
        self.assertEqual(payload["run_action"], "leg")
        self.assertEqual(payload["run_stage"], "assets")
        self.assertIsNone(payload.get("awaiting_stage"))
        stored = payload["stage_clarifications"]["assets"]
        answers = {item.get("answer") for item in stored}
        self.assertIn("一把旧雨伞", answers)
        self.assertIn("道具再少一点", answers)
        self.assertTrue(any(item.get("label") == "一把旧雨伞" for item in stored))
        self.assertTrue(any(item.get("agent") == "characters" for item in stored))
        self.assertTrue(any(item.get("agent") == "locations" for item in stored))
        service.start.assert_called_once_with("aiop-1")

    def test_rerun_stage_leg_covers_current_agents_only(self) -> None:
        captured: dict[str, Any] = {}

        class Provider:
            @staticmethod
            def run_director_recipe(recipe, **kwargs):
                captured["agents"] = list(kwargs.get("agents") or [])
                captured["clarifications"] = list(kwargs.get("clarifications") or [])
                return recipe

        service = AiGenerationService(Provider())
        service._check_cancelled = Mock()  # type: ignore[method-assign]
        service._update = Mock()  # type: ignore[method-assign]
        service._adapt_recipe = Mock()  # type: ignore[method-assign]
        service._emit = Mock()  # type: ignore[method-assign]
        recipe = empty_recipe_payload(title="测试", full_story="甲走进咖啡馆。")
        payload = {
            "kind": "pipeline",
            "request": {"project_id": "project-1", "goal": "故事"},
            "completed_stages": ["script"],
            "stage_clarifications": {
                "assets": [{"agent": "characters", "question": "气质", "answer": "更冷"}],
            },
            "result": {},
            "current_stage": "assets",
            "recipe": recipe,
        }

        service._run_stage_leg("aiop-1", payload, {"project_id": "project-1", "goal": "故事"}, "assets")

        self.assertEqual(captured["agents"], ["characters", "locations"])
        self.assertTrue(any(item.get("answer") == "更冷" for item in captured["clarifications"]))
        self.assertEqual(payload["awaiting_stage"], "assets")
        self.assertEqual(payload["completed_stages"], ["script"])
        service._adapt_recipe.assert_called_once()
        self.assertEqual(service._adapt_recipe.call_args.args[2], "assets")

    def _cancelled_row(self, *, current: str = "assets", completed: list[str] | None = None, extra: dict | None = None) -> dict:
        payload = {
            "kind": "pipeline",
            "request": {"goal": "都市逆袭", "project_id": "project-1"},
            "current_stage": current,
            "awaiting_stage": None,
            "completed_stages": list(completed or ["script"]),
            "stage_clarifications": {"script": [{"question": "气质", "answer": "冷"}]},
            "result": {"completed_stages": list(completed or ["script"]), "failed_stage": current},
            "recipe": {
                "script": {"title": "都市逆袭", "fullStory": "甲走进咖啡馆。"},
                "characters": [{"name": "甲"}],
                "locations": [{"name": "咖啡馆"}],
                "episodes": [{"num": 1, "title": "开场"}],
                "scenes": [{"shots": [{}]}],
                "agentStatus": [
                    {"id": "script", "status": "completed"},
                    {"id": "characters", "status": "completed"},
                ],
            },
            "cancel_requested": True,
        }
        if extra:
            payload.update(extra)
        return {
            "id": "aiop-1",
            "project_id": "project-1",
            "job_type": "ai_pipeline",
            "status": "cancelled",
            "progress": 40,
            "error_message": "AI 生成已取消",
            "payload_json": json.dumps(payload),
        }

    def test_retry_without_stage_keeps_completed_and_queues_current(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value=self._cancelled_row())  # type: ignore[method-assign]
        service._update = Mock()  # type: ignore[method-assign]
        service.start = Mock()  # type: ignore[method-assign]
        service.get = Mock(return_value={"id": "aiop-1", "status": "queued", "current_stage": "assets"})  # type: ignore[method-assign]

        with patch("backend.app.media_studio.services.ai_generation_service.execute_sql"):
            service.retry("aiop-1", "project-1")

        payload = service._update.call_args.kwargs["payload"]
        self.assertEqual(service._update.call_args.kwargs["status"], "queued")
        self.assertEqual(payload["run_stage"], "assets")
        self.assertFalse(payload["cancel_requested"])
        self.assertEqual(payload["completed_stages"], ["script"])
        self.assertEqual(payload["recipe"]["characters"][0]["name"], "甲")
        service.start.assert_called_once_with("aiop-1")

    def test_retry_named_stage_truncates_later_completed(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value=self._cancelled_row(  # type: ignore[method-assign]
            current="episodes",
            completed=["script", "assets"],
        ))
        service._update = Mock()  # type: ignore[method-assign]
        service.start = Mock()  # type: ignore[method-assign]
        service.get = Mock(return_value={"id": "aiop-1", "status": "queued"})  # type: ignore[method-assign]

        with patch("backend.app.media_studio.services.ai_generation_service.execute_sql"):
            service.retry("aiop-1", "project-1", "script")

        payload = service._update.call_args.kwargs["payload"]
        self.assertEqual(payload["run_action"], "leg")
        self.assertEqual(payload["run_stage"], "script")
        self.assertEqual(payload["completed_stages"], [])
        self.assertEqual(payload["recipe"]["characters"], [])
        self.assertEqual(payload["recipe"]["episodes"], [])
        self.assertEqual(payload["stage_clarifications"], {})
        service.start.assert_called_once_with("aiop-1")

    def test_retry_named_stage_from_awaiting_review_and_succeeded(self) -> None:
        service = AiGenerationService(None)
        service._update = Mock()  # type: ignore[method-assign]
        service.start = Mock()  # type: ignore[method-assign]
        service.get = Mock(return_value={"id": "aiop-1", "status": "queued"})  # type: ignore[method-assign]

        service._read = Mock(return_value=self._review_row(  # type: ignore[method-assign]
            stage="assets",
            completed=["script"],
        ))
        with patch("backend.app.media_studio.services.ai_generation_service.execute_sql"):
            service.retry("aiop-1", "project-1", "script")
        payload = service._update.call_args.kwargs["payload"]
        self.assertEqual(payload["run_stage"], "script")
        self.assertEqual(payload["completed_stages"], [])

        succeeded = self._review_row(stage="storyboard", status="succeeded", completed=["script", "assets", "episodes", "storyboard"])
        service._read = Mock(return_value=succeeded)  # type: ignore[method-assign]
        with patch("backend.app.media_studio.services.ai_generation_service.execute_sql"):
            service.retry("aiop-1", "project-1", "episodes")
        payload = service._update.call_args.kwargs["payload"]
        self.assertEqual(payload["run_stage"], "episodes")
        self.assertEqual(payload["completed_stages"], ["script", "assets"])
        self.assertEqual(payload["recipe"]["episodes"], [])
        self.assertEqual(payload["recipe"]["scenes"], [])

    def test_retry_named_stage_rejects_while_running_other_stage(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value={  # type: ignore[method-assign]
            "id": "aiop-1",
            "project_id": "project-1",
            "job_type": "ai_pipeline",
            "status": "running",
            "payload_json": json.dumps({"kind": "pipeline", "current_stage": "assets", "run_stage": "assets"}),
        })
        service.get = Mock(return_value={"id": "aiop-1", "status": "running"})  # type: ignore[method-assign]
        with self.assertRaises(ValueError) as ctx:
            service.retry("aiop-1", "project-1", "script")
        self.assertIn("生成进行中", str(ctx.exception))

    def test_retry_clarify_reopens_opening_questions_on_pipeline(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value=self._cancelled_row())  # type: ignore[method-assign]
        service._update = Mock()  # type: ignore[method-assign]
        service.start = Mock()  # type: ignore[method-assign]
        service.get = Mock(return_value={"id": "aiop-1", "status": "revising"})  # type: ignore[method-assign]

        with patch("backend.app.media_studio.services.ai_generation_service.execute_sql"):
            service.retry("aiop-1", "project-1", "clarify")

        payload = service._update.call_args.kwargs["payload"]
        self.assertEqual(service._update.call_args.kwargs["status"], "revising")
        self.assertEqual(payload["run_action"], "opening_clarify")
        self.assertEqual(payload["revise_stage"], "clarify")
        self.assertEqual(payload["current_stage"], "clarify")
        self.assertEqual(payload["completed_stages"], [])
        self.assertEqual(payload["request"]["clarifications"], [])
        service.start.assert_called_once_with("aiop-1")

    def test_run_opening_clarify_stays_revising_without_terminal(self) -> None:
        questions = [{"id": "episode_count", "question": "这部剧分多少集？"}]

        class Provider:
            @staticmethod
            def run_director_clarify(goal, **kwargs):
                return questions

        service = AiGenerationService(Provider())
        service._check_cancelled = Mock()  # type: ignore[method-assign]
        service._update = Mock()  # type: ignore[method-assign]
        service._emit = Mock()  # type: ignore[method-assign]
        payload = {
            "kind": "pipeline",
            "request": {"goal": "都市逆袭", "surface": "director2"},
            "completed_stages": [],
            "result": {},
        }

        service._run_opening_clarify("aiop-1", payload, {"goal": "都市逆袭", "surface": "director2"})

        self.assertEqual(service._update.call_args.kwargs["status"], "revising")
        self.assertEqual(payload["revise_stage"], "clarify")
        self.assertEqual(payload["result"]["questions"][-1]["id"], "shots_per_episode")
        events = [call.args[1] for call in service._emit.call_args_list]
        self.assertTrue(any(event.get("data", {}).get("questions_ready") for event in events))
        self.assertFalse(any(event.get("terminal") for event in events))

    def test_rerun_opening_clarify_queues_script_leg(self) -> None:
        service = AiGenerationService(None)
        service._read = Mock(return_value=self._review_row(  # type: ignore[method-assign]
            stage="clarify",
            status="revising",
            completed=[],
            extra_payload={
                "revise_stage": "clarify",
                "current_stage": "clarify",
                "awaiting_stage": None,
                "recipe": {
                    "script": {"title": "旧剧本", "fullStory": "旧正文"},
                    "characters": [{"name": "甲"}],
                },
            },
        ))
        service._update = Mock()  # type: ignore[method-assign]
        service.start = Mock()  # type: ignore[method-assign]
        service.get = Mock(return_value={"id": "aiop-1", "status": "queued"})  # type: ignore[method-assign]

        service.rerun_stage("aiop-1", "project-1", [
            {"id": "episode_count", "question": "这部剧分多少集？", "answer": "12集"},
        ])

        payload = service._update.call_args.kwargs["payload"]
        self.assertEqual(payload["run_stage"], "script")
        self.assertEqual(payload["current_stage"], "script")
        self.assertEqual(payload["request"]["clarifications"][0]["answer"], "12集")
        self.assertEqual(payload["completed_stages"], [])
        self.assertEqual(payload["recipe"]["characters"], [])
        service.start.assert_called_once_with("aiop-1")

    def test_storyboard_consumes_confirmed_episode_outline(self) -> None:
        from backend.app.director_agents import _episodes_for_storyboard

        recipe = empty_recipe_payload(
            title="测试",
            full_story="# 第1集 开场\n甲走进咖啡馆。\n# 第2集 终局\n乙揭开身份。\n# 第3集 番外\n不应再被切开。",
        )
        recipe["episodes"] = [
            {"num": 1, "title": "开场", "summary": "落座", "targetShots": 8, "text": "甲走进咖啡馆。"},
            {"num": 2, "title": "终局", "summary": "相认", "targetShots": 12, "text": "乙揭开身份。"},
        ]
        consumed = _episodes_for_storyboard(recipe, recipe["script"]["fullStory"])
        self.assertEqual([item["num"] for item in consumed], [1, 2])
        self.assertEqual([item["title"] for item in consumed], ["开场", "终局"])
        self.assertNotIn("番外", [item["title"] for item in consumed])

    def test_beat_payload_binds_existing_asset_ids(self) -> None:
        beat = AiGenerationService._beat_payload(
            {
                "locationName": "开元楼走廊",
                "characterNames": ["吴耐"],
                "propNames": ["寿命系统HUD"],
                "description": "吴耐走进走廊",
                "camera": "中景",
            },
            1,
            "project-1",
            char_map={"吴耐": "char-1"},
            scene_map={"开元楼走廊": "scene-ready"},
            prop_map={"寿命系统HUD": "prop-1"},
        )
        self.assertEqual("scene-ready", beat["scene_id"])
        self.assertEqual(["char-1"], beat["character_ids"])
        self.assertEqual(["prop-1"], beat["prop_ids"])

    def test_beat_payload_inherits_scene_for_continuation_shots(self) -> None:
        beat = AiGenerationService._beat_payload(
            {"description": "看手机", "camera": "特写"},
            2,
            "project-1",
            scene_map={"开元楼走廊": "scene-ready"},
            inherited_scene_name="开元楼走廊",
            inherited_scene_id="scene-ready",
        )
        self.assertEqual("开元楼走廊", beat["scene"])
        self.assertEqual("scene-ready", beat["scene_id"])

    def test_recipe_text_writes_complete_shot_fields(self) -> None:
        recipe = empty_recipe_payload(title="花甲", summary="电梯误会", full_story="电梯寒夜。")
        recipe["episodes"] = [{
            "num": 1,
            "title": "穿越上身",
            "text": "### 镜头1｜电梯里的误会\n- 动作：旧稿薄动作，不应再出现。",
        }]
        recipe["scenes"] = [{
            "shots": [{
                "title": "电梯里的误会",
                "episodeNumber": 1,
                "characterNames": ["吴耐", "沙丽丽"],
                "locationName": "单元楼电梯",
                "propNames": ["绿色苹果手机"],
                "description": "竖屏短剧单镜，时长约 8 秒。空间：不锈钢轿厢。调度：她护着手机后退。收束：定格睁大的眼睛。",
                "dialogue": "该不会想让我那啥吧。",
                "camera": {"scale": "MS", "movement": "zoom_in", "angle": "eye_level"},
                "soundscape": "电梯低频嗡鸣、铃铛细响",
                "promptText": "Photorealistic vertical 9:16 eight-second take, lighting from overhead fluorescent, camera slow push-in, she clutches the phone then freezes.",
                "durationSec": 8,
            }],
        }]
        text = AiGenerationService._recipe_text(recipe)
        self.assertIn("- 人物：吴耐、沙丽丽", text)
        self.assertIn("- 场景：单元楼电梯", text)
        self.assertIn("- 道具：绿色苹果手机", text)
        self.assertIn("- 动作：竖屏短剧单镜", text)
        self.assertIn("- 运镜：MS zoom_in eye_level", text)
        self.assertIn("- 台词：该不会想让我那啥吧。", text)
        self.assertIn("- 音效：电梯低频嗡鸣、铃铛细响", text)
        self.assertIn("- 时长：8秒", text)
        self.assertIn("- 提示词：Photorealistic vertical 9:16", text)
        self.assertNotIn("旧稿薄动作", text)
        self.assertEqual(text.count("### 镜头"), 1)

    def test_beat_payload_keeps_audio_and_concatenated_video_prompt(self) -> None:
        beat = AiGenerationService._beat_payload(
            {
                "description": "竖屏短剧单镜，时长约 8 秒。空间：不锈钢轿厢。调度：她护着手机后退。收束：定格睁大的眼睛。",
                "promptText": "Photorealistic vertical 9:16 eight-second take with fluorescent lighting and a slow camera push-in.",
                "camera": {"scale": "MS", "movement": "zoom_in"},
                "soundscape": "电梯低频嗡鸣、铃铛细响",
                "dialogue": "该不会想让我那啥吧。",
                "durationSec": 8,
            },
            1,
            "project-1",
        )
        self.assertIn("空间：不锈钢轿厢", beat["action"])
        self.assertEqual(
            beat["visual_prompt"],
            "Photorealistic vertical 9:16 eight-second take with fluorescent lighting and a slow camera push-in.",
        )
        self.assertEqual(beat["sketch_prompt"], beat["visual_prompt"])
        self.assertEqual(beat["camera"], "MS zoom_in")
        self.assertEqual(beat["audio"], "电梯低频嗡鸣、铃铛细响")
        self.assertIn("运镜：MS zoom_in", beat["video_prompt_zh"])
        self.assertIn("声音：电梯低频嗡鸣、铃铛细响", beat["video_prompt_zh"])
        self.assertTrue(beat["video_prompt_zh"].startswith("竖屏短剧单镜"))
        self.assertEqual(beat["video_duration"], "8")
        self.assertNotIn("{", beat["camera"])

    def test_beat_payload_bumps_five_second_duration_for_thick_blocking(self) -> None:
        beat = AiGenerationService._beat_payload(
            {
                "description": (
                    "竖屏短剧单镜，一镜到底。空间：老旧不锈钢轿厢，镜面金属壁反青白顶灯，空间逼仄。"
                    "光线：惨白顶灯，皮肤偏青。造型锁定：清瘦花甲男人脏污背心；浓妆红裙租客抱绿色手机。"
                    "调度与表演：电梯门刚合上。她被挤在右后角护着手机；他停在左前方半步，不敢靠近。"
                    "她先扫他的污渍背心，再盯他的花甲脸，开口前肩膀一缩。口型与台词同步。"
                    "收束：误会说出后定格在她睁大的眼睛约一秒。"
                ),
                "dialogue": "该不会想让我那啥吧。",
                "durationSec": 5,
            },
            1,
            "project-1",
        )
        self.assertGreaterEqual(int(beat["video_duration"]), 8)


if __name__ == "__main__":
    unittest.main()
