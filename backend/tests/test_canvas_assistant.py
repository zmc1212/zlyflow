from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.app.canvas_assistant.protocol import OpsProposal
from backend.app.canvas_assistant.repository import AssistantNotFound, dumps
from backend.app.canvas_assistant.service import AssistantServiceCompat, CanvasAssistantService, _collect_job_ids
from backend.app.canvas_store import CanvasStore, canvas_checksum
from backend.app.storage import JobStore


class FakeWorkflow:
    """轻量工作流定义替身：payload() 契约与 WorkflowDefinition 对齐。"""

    id = "fake-image"
    name = "测试生图"
    media_type = "image"
    reference_mode = "optional"
    min_references = 0
    max_references = 1
    credit_cost = 6
    billing_notice = None
    default_prompt = None
    option_schema = {"properties": {
        "aspect_ratio": {"label": "画幅", "type": "string", "default": "1:1", "ui_group": "primary",
                          "ui_options": [{"value": "1:1", "label": "方形"}, {"value": "16:9", "label": "横屏"}]},
        "steps": {"label": "步数", "type": "number", "default": 20, "ui_group": "internal"},
    }}

    def payload(self) -> dict:
        return {"parameters": [{"name": "options", "schema": self.option_schema}]}

    def reference_kind(self, index: int, count: int | None = None) -> str:
        return "image"


def canvas_content(nodes: list[dict] | None = None, edges: list[dict] | None = None) -> str:
    return json.dumps({"nodes": nodes or [], "edges": edges or []}, ensure_ascii=False)


class CanvasAssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = JobStore(Path(self.temp.name) / "canvas-assistant.db")
        self.canvas = CanvasStore(self.store)
        self.project = self.canvas.create_project("alice", "测试画布")
        self.llm = Mock()
        self.llm.assistant_models.return_value = ["model-a", "model-b"]
        self.llm.availability.return_value = (True, None)
        self.credits = Mock()
        self.service = CanvasAssistantService(
            self.store, self.llm, self.canvas, credits=self.credits,
            workflows_for=lambda owner: [FakeWorkflow()],
            workflow_lookup=lambda mode_id: FakeWorkflow() if mode_id == FakeWorkflow.id else None,
        )
        self.repo = self.service.repo

    def session(self, **kwargs):
        return self.service.create_session("alice", {"canvas_id": self.project["id"], **kwargs})

    def save_nodes(self, nodes: list[dict], edges: list[dict] | None = None):
        content = canvas_content(nodes, edges)
        self.canvas.save_draft("alice", self.project["id"], self.canvas.get_project("alice", self.project["id"])["version"],
                               content, canvas_checksum(content))

    @staticmethod
    def reply(envelope, callback=None):
        raw = dumps(envelope)
        if callback:
            callback(raw[:25])
            callback(raw)
        return raw

    def send_and_run(self, session, payload, envelope):
        self.llm.assistant_chat.side_effect = lambda messages, model, callback=None: self.reply(envelope, callback)
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], payload)
        self.service.run("alice", run["id"])
        self.last_run_id = run["id"]
        return run

    def run_message(self, session, envelope, client_message_id="request-12345"):
        self.send_and_run(session, {"text": "帮我在画布上生成一张图", "client_message_id": client_message_id}, envelope)
        return self.service.detail("alice", session["id"])

    # ---------------------------------------------------------------- 会话

    def test_session_requires_owned_canvas(self):
        session = self.session()
        self.assertEqual(session["canvas_id"], self.project["id"])
        other = self.canvas.create_project("bob", "别人画布")
        with self.assertRaises(ValueError):
            self.service.create_session("alice", {"canvas_id": other["id"]})
        with self.assertRaises(AssistantNotFound):
            self.service.detail("bob", session["id"])

    def test_send_is_idempotent_and_validates_canvas(self):
        session = self.session()
        self.llm.assistant_chat.side_effect = lambda messages, model, callback=None: self.reply({"text": "好的"})
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit") as executor:
            first = self.service.send("alice", session["id"], {"text": "你好", "client_message_id": "client-key-0001"})
            second = self.service.send("alice", session["id"], {"text": "你好", "client_message_id": "client-key-0001"})
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(executor.call_count, 1)
        self.canvas.trash_project("alice", self.project["id"])
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            with self.assertRaises(ValueError):
                self.service.send("alice", session["id"], {"text": "你好", "client_message_id": "client-key-0002"})

    def test_active_run_blocks_concurrent_send(self):
        session = self.session()
        self.llm.assistant_chat.side_effect = lambda messages, model, callback=None: self.reply({"text": "回复"})
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            self.service.send("alice", session["id"], {"text": "第一条", "client_message_id": "client-key-0010"})
        detail = self.service.detail("alice", session["id"])
        self.assertIsNotNone(detail["run"])
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            with self.assertRaises(Exception):
                self.service.send("alice", session["id"], {"text": "第二条", "client_message_id": "client-key-0011"})

    def test_workflow_preference_validation(self):
        with self.assertRaises(ValueError):
            self.service.validate_selections("alice", {"model_id": "model-a", "image_workflow_id": "no-such"})
        # 媒体类型不匹配：fake-image 是 image 工作流，不能设为生视频偏好
        class FakeVideoWorkflow(FakeWorkflow):
            id = "fake-i2v"
            name = "测试图生视频"
            media_type = "video"
        with self.assertRaises(ValueError) as ctx:
            self.service.create_session("alice", {"canvas_id": self.project["id"],
                                                   "selections": {"model_id": "model-a", "video_workflow_id": "fake-image"}})
        self.assertIn("不是video工作流", str(ctx.exception))
        class FakeVideoWorkflow(FakeWorkflow):
            id = "fake-i2v"
            name = "测试图生视频"
            media_type = "video"

        service = CanvasAssistantService(
            self.store, self.llm, self.canvas,
            workflows_for=lambda owner: [FakeWorkflow()],
            workflow_lookup=lambda mode_id: FakeVideoWorkflow() if mode_id == "fake-i2v" else (FakeWorkflow() if mode_id == "fake-image" else None),
        )
        session = service.create_session("alice", {"canvas_id": self.project["id"],
                                                    "selections": {"model_id": "model-a", "video_workflow_id": "fake-i2v"}})
        self.assertEqual(session["selections"]["video_workflow_id"], "fake-i2v")
        # skill_id：画布消费导演台技能库（内置技能已播种），快照独立于 selections 存放
        skills = self.service.catalog("alice")["skills"]
        self.assertTrue(skills)
        builtin = next(s for s in skills if s["builtin"])
        session2 = self.service.create_session("alice", {"canvas_id": self.project["id"],
                                                          "selections": {"model_id": "model-a", "skill_id": builtin["version_id"]}})
        self.assertEqual(session2["resource_snapshot"]["skill"]["name"], builtin["name"])
        self.assertEqual(session2["selections"]["skill_id"], builtin["version_id"])
        with self.assertRaises(ValueError):
            self.service.create_session("alice", {"canvas_id": self.project["id"],
                                                   "selections": {"model_id": "model-a", "skill_id": "skill-pkg-1"}})

    def test_question_answer_writes_workflow_preference(self):
        session = self.session()
        envelope = {"text": "需要确认模型", "question": {"title": "用哪个模型生成图片？", "type": "single",
                     "options": [{"label": "测试生图", "value": "fake-image", "recommended": True}, {"label": "换个模型", "value": "other"}]}}
        self.run_message(session, envelope)
        questions = [p["question"] for m in self.service.detail("alice", session["id"])["messages"] for p in m["parts"] if p["type"] == "question"]
        question = questions[0]
        self.send_and_run(session, {"text": "", "client_message_id": "client-key-pref-01",
                                     "question_id": question["id"], "answer_values": ["fake-image"]},
                          {"text": "好的，已记住偏好。"})
        updated = self.service.detail("alice", session["id"])["session"]
        self.assertEqual(updated["selections"]["image_workflow_id"], "fake-image")
        # 后续 run 的上下文里应带偏好
        self.llm.assistant_chat.side_effect = lambda messages, model, callback=None: self.reply({"text": "ok"})
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "随便看看", "client_message_id": "client-key-pref-02"})
        detail = self.service.detail("alice", session["id"])
        self.assertIsNone(detail["session"]["pending_question"])

    def test_question_flow(self):
        session = self.session()
        envelope = {"text": "需要确认画幅", "question": {"title": "要哪种画幅？", "type": "single",
                     "options": [{"label": "横屏", "value": "16:9", "recommended": True}, {"label": "方形", "value": "1:1"}]}}
        detail = self.run_message(session, envelope)
        questions = [p["question"] for m in detail["messages"] for p in m["parts"] if p["type"] == "question"]
        self.assertEqual(len(questions), 1)
        question = questions[0]
        self.assertEqual((detail["session"]["pending_question"] or {}).get("id"), question["id"])
        self.llm.assistant_chat.side_effect = lambda messages, model, callback=None: self.reply({"text": "好的，已按横屏推进。"})
        self.send_and_run(session, {"text": "", "client_message_id": "client-key-0021",
                                    "question_id": question["id"], "answer_values": ["16:9"]},
                          {"text": "好的，已按横屏推进。"})
        detail = self.service.detail("alice", session["id"])
        self.assertIsNone(detail["session"]["pending_question"])
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            with self.assertRaises(ValueError):
                self.service.send("alice", session["id"], {"text": "", "client_message_id": "client-key-0022",
                                                            "question_id": question["id"], "answer_values": ["9:99"]})

    # ---------------------------------------------------------------- 提案校验

    def test_validate_ops_happy_path(self):
        content = json.loads(canvas_content([
            {"id": "gen-1", "type": "generator", "position": {"x": 0, "y": 0},
             "data": {"workflowId": FakeWorkflow.id, "prompt": "旧提示词", "optionValues": {}}},
        ]))
        ops = [
            {"op": "create_text", "ref": "n1", "text": "赛博朋克城市夜景", "label": "提示词"},
            {"op": "create_generator", "ref": "n2", "workflow_id": "fake-image", "prompt": "赛博朋克城市夜景",
             "option_values": {"aspect_ratio": "16:9"}, "connect_from": ["n1"], "position": "right_of:n1"},
            {"op": "connect", "ref": "c1", "source_ref": "n2", "target_ref": "gen-1"},
            {"op": "update_generator", "ref": "gen-1", "prompt": "新提示词"},
            {"op": "submit", "ref": "n2"},
        ]
        proposal = OpsProposal.model_validate({"title": "画布方案", "ops": ops})
        normalized, summary = self.service.actions.validate_ops(proposal.ops, content)
        self.assertEqual(summary["counts"]["create_generator"], 1)
        self.assertEqual(summary["credit_estimate"], 6)
        self.assertEqual(normalized[1]["workflow_name"], "测试生图")
        self.assertEqual(normalized[1]["option_values"], {"aspect_ratio": "16:9"})

    def test_validate_ops_allows_empty_prompt_for_i2v(self):
        # 图生视频场景 prompt 可留空：由前端文字节点/全局提示词/工作流默认值兜底。
        content = json.loads(canvas_content([
            {"id": "img-node-1", "type": "generator", "position": {"x": 0, "y": 0},
             "data": {"workflowId": FakeWorkflow.id, "prompt": "城市", "optionValues": {}, "mediaKind": "image"}},
        ]))

        class FakeVideoWorkflow(FakeWorkflow):
            id = "fake-i2v"
            name = "测试图生视频"
            media_type = "video"

        proposal = OpsProposal.model_validate({"title": "t", "ops": [
            {"op": "create_generator", "ref": "n1", "workflow_id": "fake-i2v", "prompt": "",
             "option_values": {"aspect_ratio": "16:9"}, "connect_from": ["img-node-1"]},
        ]})
        service = CanvasAssistantService(
            self.store, self.llm, self.canvas,
            workflows_for=lambda owner: [FakeWorkflow()],
            workflow_lookup=lambda mode_id: FakeVideoWorkflow() if mode_id == "fake-i2v" else None,
        )
        normalized, summary = service.actions.validate_ops(proposal.ops, content)
        self.assertEqual(normalized[0]["connect_from"], ["img-node-1"])
        self.assertEqual(summary["counts"]["create_generator"], 1)

    def test_validate_ops_rejects_unknown_workflow_and_internal_params(self):
        content = json.loads(canvas_content())
        with self.assertRaises(ValueError):
            proposal = OpsProposal.model_validate({"title": "t", "ops": [
                {"op": "create_generator", "ref": "n1", "workflow_id": "no-such", "prompt": "p"},
            ]})
            self.service.actions.validate_ops(proposal.ops, content)
        with self.assertRaises(ValueError) as ctx:
            proposal = OpsProposal.model_validate({"title": "t", "ops": [
                {"op": "create_generator", "ref": "n1", "workflow_id": "fake-image", "prompt": "p",
                 "option_values": {"steps": 30}},
            ]})
            self.service.actions.validate_ops(proposal.ops, content)
        self.assertIn("托管", str(ctx.exception))
        with self.assertRaises(ValueError):
            proposal = OpsProposal.model_validate({"title": "t", "ops": [
                {"op": "create_generator", "ref": "n1", "workflow_id": "fake-image", "prompt": "p",
                 "option_values": {"aspect_ratio": "4:3"}},
            ]})
            self.service.actions.validate_ops(proposal.ops, content)

    def test_validate_ops_rejects_bad_connections_and_dangling_refs(self):
        content = json.loads(canvas_content([
            {"id": "img-1", "type": "image", "position": {"x": 0, "y": 0}, "data": {"url": "/api/x.png"}},
        ]))
        with self.assertRaises(ValueError) as ctx:
            proposal = OpsProposal.model_validate({"title": "t", "ops": [
                {"op": "connect", "ref": "c1", "source_ref": "img-1", "target_ref": "img-1"},
            ]})
            self.service.actions.validate_ops(proposal.ops, content)
        with self.assertRaises(ValueError) as ctx:
            proposal = OpsProposal.model_validate({"title": "t", "ops": [
                {"op": "create_generator", "ref": "n1", "workflow_id": "fake-image", "prompt": "p", "connect_from": ["n9"]},
            ]})
            self.service.actions.validate_ops(proposal.ops, content)
        self.assertIn("n9", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            proposal = OpsProposal.model_validate({"title": "t", "ops": [
                {"op": "submit", "ref": "img-1"},
            ]})
            self.service.actions.validate_ops(proposal.ops, content)
        self.assertIn("生成器", str(ctx.exception))

    # ---------------------------------------------------------------- 端到端运行

    def test_run_proposes_ops_and_persists_events(self):
        self.save_nodes([])
        session = self.session()
        envelope = {
            "text": "我先读取画布，然后给出方案。",
            "question": None,
            "tool_calls": [
                {"name": "canvas_read", "arguments": {}},
                {"name": "propose_canvas_ops", "arguments": {"title": "生成赛博朋克城市", "ops": [
                    {"op": "create_generator", "ref": "n1", "workflow_id": "fake-image",
                     "prompt": "赛博朋克城市夜景，霓虹灯，16:9", "option_values": {"aspect_ratio": "16:9"}},
                    {"op": "submit", "ref": "n1"},
                ]}},
            ],
        }
        detail = self.run_message(session, envelope)
        run = self.service.repo.get("alice", self.last_run_id, "run")
        self.assertEqual(run["status"], "succeeded")
        proposal_parts = [p for m in detail["messages"] for p in m["parts"] if p["type"] == "proposal"]
        self.assertEqual(len(proposal_parts), 1)
        proposals = detail["proposals"]
        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal["status"], "awaiting_approval")
        self.assertEqual(proposal["summary"]["credit_estimate"], 6)
        self.assertEqual(proposal["ops"][0]["op"], "create_generator")
        events = self.repo.events("alice", run["id"], 0)
        names = [e["event"] for e in events]
        self.assertIn("status", names)
        self.assertIn("snapshot", names)
        self.assertEqual(names[-1], "done")
        replayed = self.repo.events("alice", run["id"], events[0]["seq"])
        self.assertEqual([e["seq"] for e in replayed], [e["seq"] for e in events][1:])

    def test_run_reports_tool_error_without_blocking_finish(self):
        session = self.session()
        bad_envelope = {
            "text": "方案",
            "question": None,
            "tool_calls": [{"name": "propose_canvas_ops", "arguments": {"title": "坏方案", "ops": [
                {"op": "create_generator", "ref": "n1", "workflow_id": "missing-wf", "prompt": "p"},
            ]}}],
        }
        calls = {"n": 0}

        def chat(messages, model, callback=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return self.reply(bad_envelope, callback)
            return self.reply({"text": "该工作流不存在，无法创建方案。"}, callback)

        self.llm.assistant_chat.side_effect = chat
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "生成一张图", "client_message_id": "request-tool-error"})
        self.service.run("alice", run["id"])
        self.last_run_id = run["id"]
        detail = self.service.detail("alice", session["id"])
        self.assertEqual(self.service.repo.get("alice", self.last_run_id, "run")["status"], "succeeded")
        failed_tools = [p for m in detail["messages"] for p in m["parts"] if p["type"] == "tool" and p.get("status") == "failed"]
        self.assertEqual(len(failed_tools), 1)
        self.assertEqual(detail["proposals"], [])

    def test_proposal_apply_result_lifecycle(self):
        session = self.session()
        envelope = {"text": "", "question": None, "tool_calls": [{"name": "propose_canvas_ops", "arguments": {
            "title": "方案", "ops": [{"op": "create_text", "ref": "n1", "text": "提示词"}]}}]}
        detail = self.run_message(session, envelope)
        proposal = detail["proposals"][0]
        updated = self.service.actions.apply_result("alice", proposal["id"], "applied", {"applied_ops": 1})
        self.assertEqual(updated["status"], "applied")
        with self.assertRaises(ValueError):
            self.service.actions.apply_result("alice", proposal["id"], "applied", {})
        with self.assertRaises(ValueError):
            self.service.actions.apply_result("alice", proposal["id"], "bogus", {})

    def test_load_skill_reference_and_run_context(self):
        # 个人技能带参考文件：save → 会话绑定 → 工具读取
        saved = self.service.resources.save("alice", {
            "resource_type": "skill", "name": "画布生图法", "category": "画布",
            "description": "按三步出图", "instructions": "先问主题，再问画幅，最后给方案。",
            "references": {"风格手册.md": "使用胶片颗粒与青紫色调。"},
        })
        skills = self.service.catalog("alice")["skills"]
        mine = next(s for s in skills if s["name"] == "画布生图法")
        self.assertEqual(len(mine["references"]), 1)
        session = self.service.create_session("alice", {"canvas_id": self.project["id"],
                                                          "selections": {"model_id": "model-a", "skill_id": mine["version_id"]}})
        self.assertEqual(session["resource_snapshot"]["skill"]["name"], "画布生图法")
        run = {"canvas_id": self.project["id"], "resource_snapshot": session["resource_snapshot"]}
        read = self.service._tool("alice", session, run, "load_skill_reference", {"path": "风格手册.md"}, {})
        self.assertIn("胶片颗粒", read["text"])
        with self.assertRaises(ValueError) as ctx:
            self.service._tool("alice", session, run, "load_skill_reference", {"path": "不存在.md"}, {})
        self.assertIn("可用参考文件", str(ctx.exception))
        # 发言人名写入助手消息
        self.llm.assistant_chat.side_effect = lambda messages, model, callback=None: self.reply({"text": "收到"})
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            self.service.send("alice", session["id"], {"text": "你好", "client_message_id": "client-key-skill-01"})
        detail = self.service.detail("alice", session["id"])
        assistant_msg = [m for m in detail["messages"] if m["role"] == "assistant"][-1]
        self.assertEqual(assistant_msg.get("resource_names"), {"skill": "画布生图法"})

    def test_propose_twice_in_one_run_is_rejected(self):
        session = self.session()
        envelope = {"text": "", "question": None, "tool_calls": [{"name": "propose_canvas_ops", "arguments": {
            "title": "方案一", "ops": [{"op": "create_text", "ref": "n1", "text": "a"}]}}]}
        self.run_message(session, envelope)
        run_id = self.last_run_id
        # 同一轮第二次 propose：直接经 _tool 复现 guard
        run = self.service.repo.get("alice", run_id, "run")
        run["_proposed_this_run"] = True
        with self.assertRaises(ValueError) as ctx:
            self.service._tool("alice", session, run, "propose_canvas_ops",
                               {"title": "方案二", "ops": [{"op": "create_text", "ref": "n2", "text": "b"}]}, {})
        self.assertIn("重复创建", str(ctx.exception))

    def test_canvas_read_filter_narrows_overview(self):
        self.save_nodes([
            {"id": "t1", "type": "text", "position": {"x": 0, "y": 0}, "data": {"text": "提示词"}},
            {"id": "g1", "type": "generator", "position": {"x": 100, "y": 0},
             "data": {"workflowId": FakeWorkflow.id, "prompt": "城市夜景", "jobStatus": "succeeded", "jobId": "job-1"}},
            {"id": "g2", "type": "generator", "position": {"x": 200, "y": 0},
             "data": {"workflowId": FakeWorkflow.id, "prompt": "海边日出", "jobStatus": "failed"}},
        ])
        run = {"canvas_id": self.project["id"], "request_context": {"selection_ids": [], "viewport_node_ids": []}}
        filtered = self.service._tool_canvas_read("alice", run, {"filter": {"job_status": "failed"}})
        self.assertEqual(filtered["node_count"], 3)
        self.assertEqual(filtered["listed_count"], 1)
        self.assertEqual(filtered["nodes"][0]["id"], "g2")
        by_type = self.service._tool_canvas_read("alice", run, {"filter": {"type": "generator", "query": "日出"}})
        self.assertEqual(by_type["listed_count"], 1)
        self.assertEqual(by_type["nodes"][0]["id"], "g2")
        unfiltered = self.service._tool_canvas_read("alice", run, {})
        self.assertEqual(unfiltered["listed_count"], 3)

    def test_billing_consumed_on_success_only(self):
        session = self.session()
        self.run_message(session, {"text": "完成", "question": None, "tool_calls": []})
        self.credits.consume_call.assert_called_once()
        args, _kwargs = self.credits.consume_call.call_args
        self.assertEqual(args[1], "llm")
        self.assertEqual(args[2], "assistant_chat")
        self.credits.consume_call.reset_mock()
        self.llm.assistant_chat.side_effect = RuntimeError("上游超时")
        self.send_and_run(session, {"text": "再来一次", "client_message_id": "client-key-0030"}, {"text": ""})
        self.credits.consume_call.assert_not_called()

    def test_workflow_catalog_exposes_user_params_only(self):
        catalog = self.service._tool_workflow_catalog("alice")
        self.assertEqual(catalog["total"], 1)
        entry = catalog["workflows"][0]
        self.assertEqual(entry["id"], "fake-image")
        self.assertEqual(entry["media_type"], "image")
        self.assertIn("aspect_ratio", entry["params"])
        self.assertNotIn("steps", entry["params"])
        self.assertEqual(entry["credit_cost"], 6)

    def test_canvas_read_focus_and_edges(self):
        self.save_nodes([
            {"id": "t1", "type": "text", "position": {"x": 0, "y": 0}, "data": {"text": "一个很长的提示词" * 20}},
            {"id": "g1", "type": "generator", "position": {"x": 100, "y": 0},
             "data": {"workflowId": FakeWorkflow.id, "prompt": "p", "optionValues": {"aspect_ratio": "1:1"},
                       "jobStatus": "succeeded", "jobId": "job-1"}},
        ], [{"id": "e1", "source": "t1", "target": "g1", "sourceHandle": "out", "targetHandle": "in", "type": "smoothstep"}])
        session = self.session()
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "看看画布", "client_message_id": "client-key-0040",
                                                             "context": {"selection_ids": ["g1"], "viewport_node_ids": []}})
        result = self.service._tool_canvas_read("alice", run, {})
        self.assertEqual(result["node_count"], 2)
        self.assertEqual(result["edge_count"], 1)
        self.assertEqual(result["focus_nodes"][0]["id"], "g1")
        self.assertEqual(result["focus_nodes"][0]["option_values"], {"aspect_ratio": "1:1"})

    def test_job_status_collects_ids_from_draft(self):
        payload = {"nodes": [
            {"id": "g1", "type": "generator", "data": {"jobId": "job-a", "sourceJobId": "job-b",
                                                        "lastRun": {"jobId": "job-c"},
                                                        "resultHistory": [{"jobId": "job-a"}]}},
        ]}
        self.assertEqual(_collect_job_ids(payload), ["job-a", "job-b", "job-c"])
        self.save_nodes([{"id": "g1", "type": "generator", "position": {"x": 0, "y": 0},
                          "data": {"jobId": "job-a", "sourceJobId": "job-b", "lastRun": {"jobId": "job-c"}}}])
        result = self.service._tool_job_status("alice", {"canvas_id": self.project["id"]}, {})
        self.assertEqual(result["total"], 3)

    def test_recover_marks_running_runs_interrupted(self):
        session = self.session()
        self.llm.assistant_chat.side_effect = lambda messages, model, callback=None: self.reply({"text": "x"})
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "被中断", "client_message_id": "client-key-0050"})
        self.service.recover()
        recovered = self.service.repo.get("alice", run["id"], "run")
        self.assertEqual(recovered["status"], "interrupted")
        self.llm.assistant_chat.side_effect = lambda messages, model, callback=None: self.reply({"text": "继续"})
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            retried = self.service.retry("alice", run["id"], "client-key-0051")
        self.assertNotEqual(retried["id"], run["id"])

    def test_native_tool_turn_conversion(self):
        raw, executable, text = CanvasAssistantService._native_turn(
            "正文", [{"function": {"name": "propose_canvas_ops", "arguments": json.dumps({"title": "t", "ops": []})}},
                     {"function": {"name": "ask_question", "arguments": json.dumps({"title": "选一个？", "type": "text"})}}],
        )
        envelope = json.loads(raw)
        self.assertEqual(envelope["tool_calls"][0]["name"], "propose_canvas_ops")
        self.assertEqual(envelope["question"]["title"], "选一个？")
        self.assertEqual(text, "正文")
        self.assertEqual(len(executable), 1)

    def test_parse_oversized_proposal_gives_actionable_error(self):
        """25 个 ops 的提案触发带拆分指引的错误，而不是泛化的格式失败（批量删除死循环兜底）。

        泛化错误会让修复轮模型原样重发超限提案：实测 25 个 delete 连续 3 轮失败。
        """
        oversized = dumps({
            "text": "删除全部节点",
            "tool_calls": [{"name": "propose_canvas_ops", "arguments": {
                "title": "全部删除",
                "ops": [{"op": "delete_node", "ref": f"node-{index}"} for index in range(25)],
            }}],
        })
        with self.assertRaises(ValueError) as ctx:
            AssistantServiceCompat._parse(oversized)
        message = str(ctx.exception)
        self.assertIn("24", message)
        self.assertIn("25", message)
        self.assertIn("修复", message)
        # 修复轮拿到的错误必须可执行：明确说明只保留前 24 个并分批
        self.assertIn("前 24 个", message)
        # 24 个 ops 的提案仍然合法
        boundary = dumps({
            "text": "删除全部节点",
            "tool_calls": [{"name": "propose_canvas_ops", "arguments": {
                "title": "全部删除",
                "ops": [{"op": "delete_node", "ref": f"node-{index}"} for index in range(24)],
            }}],
        })
        turn = AssistantServiceCompat._parse(boundary)
        self.assertEqual(len(turn.tool_calls), 1)
        # 工具数组形态（<tool_call>/裸数组）同样要触发超限指引
        array_form = dumps([{"name": "propose_canvas_ops", "arguments": {
            "title": "全部删除",
            "ops": [{"op": "delete_node", "ref": f"node-{index}"} for index in range(25)],
        }}])
        with self.assertRaises(ValueError) as array_ctx:
            AssistantServiceCompat._parse(array_form)
        self.assertIn("前 24 个", str(array_ctx.exception))

    # ---------------------------------------------------------------- 行为加固（2026-11-21 E2E 缺陷修复）

    def test_trim_repetition_collapses_spam(self):
        # 复读机退化：同一行反复输出时只保留首次出现
        spam = "\n\n".join(["让我用问题卡来澄清这个关键信息：", "我需要确认参考图片的来源。您希望我：", "先生成选中节点的图片？", "还是有其他图片素材可以使用？"] * 5)
        trimmed = CanvasAssistantService._trim_repetition(spam)
        self.assertLess(len(trimmed), len(spam) // 3)
        self.assertEqual(trimmed.count("让我用问题卡来澄清这个关键信息"), 1)
        # 短文本与正常回复不受影响
        self.assertEqual(CanvasAssistantService._trim_repetition("短回复"), "短回复")
        normal = "\n\n".join([
            "第一段正常内容，讲述晨雾中的山峦如何在水墨笔触下层层晕染开来的构图思路。",
            "第二段正常内容，说明画幅选择 16:9 横屏能容纳连绵远山与近景溪流的完整层次。",
            "第三段正常内容，建议用 GPT Image 2.5 出图，再按需转成五秒的缓慢推镜视频。",
            "第四段正常内容，确认积分单价与提交时机，等待用户点应用后再真正执行任务。",
        ])
        self.assertEqual(CanvasAssistantService._trim_repetition(normal), normal)

    def test_acknowledgment_stripped_after_reminder(self):
        # reminder 兜底后的"我明白了，需要直接创建画布方案。"不能泄漏给用户
        session = self.session()
        calls = {"n": 0}

        def chat(messages, model, callback=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return self.reply({"text": "让我为您准备生成方案："})
            return self.reply({"text": "我明白了，需要直接创建画布方案。已为您创建方案，请在下方确认。",
                               "tool_calls": [{"name": "propose_canvas_ops", "arguments": {
                                   "title": "方案", "ops": [{"op": "create_text", "ref": "n1", "text": "a"}]}}]})

        self.llm.assistant_chat.side_effect = chat
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "生成一张图", "client_message_id": "client-key-ack-01"})
        self.service.run("alice", run["id"])
        self.assertEqual(calls["n"], 2)
        detail = self.service.detail("alice", session["id"])
        assistant_text = "\n".join(
            p.get("text", "") for m in detail["messages"] if m["role"] == "assistant"
            for p in m["parts"] if p["type"] == "markdown"
        )
        self.assertNotIn("我明白了", assistant_text)
        self.assertIn("已为您创建方案", assistant_text)
        self.assertEqual(len(detail["proposals"]), 1)

    def test_inventory_question_does_not_trigger_reminder(self):
        # 纯问答轮里的"生成"（哪些已经生成完了）不能触发强制提案兜底
        session = self.session()
        calls = {"n": 0}

        def chat(messages, model, callback=None):
            calls["n"] += 1
            return self.reply({"text": "画布上有 3 个节点，均未提交。"})

        self.llm.assistant_chat.side_effect = chat
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"],
                                    {"text": "画布上现在都有什么？哪些已经生成完了？", "client_message_id": "client-key-inv-01"})
        self.service.run("alice", run["id"])
        self.assertEqual(calls["n"], 1)
        self.assertEqual(self.service.repo.get("alice", run["id"], "run")["status"], "succeeded")
        self.assertEqual(self.service.detail("alice", session["id"])["proposals"], [])

    def test_promise_tail_triggers_reminder_for_short_followup(self):
        # 上一轮悬空承诺 + 用户省略式短指令（无动作动词）也应触发兜底
        session = self.session()
        calls = {"n": 0}

        def chat(messages, model, callback=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return self.reply({"text": "根据您的需求，我将为您准备生成方案："})
            if calls["n"] == 2:
                return self.reply({"text": "好的，已按您的选择创建方案。", "tool_calls": [
                    {"name": "propose_canvas_ops", "arguments": {
                        "title": "晨雾山峦", "ops": [{"op": "create_text", "ref": "n1", "text": "晨雾山峦"}]}}]})
            return self.reply({"text": "完成。"})

        self.llm.assistant_chat.side_effect = chat
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            first = self.service.send("alice", session["id"], {"text": "随便介绍一下", "client_message_id": "client-key-pr-01"})
        self.service.run("alice", first["id"])
        self.assertEqual(calls["n"], 1)  # 第一轮无意图无承诺前文，不触发兜底
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            second = self.service.send("alice", session["id"], {"text": "第一个吧，晨雾中的山峦", "client_message_id": "client-key-pr-02"})
        self.service.run("alice", second["id"])
        self.assertEqual(calls["n"], 2)
        detail = self.service.detail("alice", session["id"])
        self.assertEqual([p["title"] for p in detail["proposals"]], ["晨雾山峦"])

    def test_list_options_upgraded_to_question_card(self):
        # 正文罗列选项代替问题卡时，服务端升级为问题卡
        session = self.session()
        text = ("为了给您提供符合期待的内容，我需要了解一些具体方向：\n\n"
                "- 自然风光：如晨雾中的山峦、极光下的雪原\n"
                "- 抽象艺术：流体渐变、几何光效\n"
                "- 人像美学：胶片质感肖像、水墨写意\n"
                "- 静物意境：茶席上的光影、旧书与咖啡\n\n"
                "您更倾向哪种类型？")
        detail = self.run_message(session, {"text": text}, client_message_id="client-key-list-01")
        questions = [p["question"] for m in detail["messages"] for p in m["parts"] if p["type"] == "question"]
        self.assertEqual(len(questions), 1)
        question = questions[0]
        self.assertEqual(question["type"], "single")
        self.assertEqual(len(question["options"]), 4)
        self.assertEqual(question["options"][0]["label"], "自然风光")
        self.assertIn("晨雾", question["options"][0]["description"])
        self.assertTrue(question["allow_custom"])
        # 盘点类清单（非选择题）不误转
        inventory = ("当前画布上有 3 个节点：\n- 柴犬横版生成器\n- 柴犬竖版生成器\n- 橘猫视频生成器\n\n"
                     "需要我把它们全部提交生成吗？")
        self.assertIsNone(CanvasAssistantService._derive_question_from_list(inventory))
        # 问句在尾部附近但正文以陈述句收尾（"请告诉我你的倾向，我立刻…。"）也能升级
        trailing_statement = ("为了确保效果符合期待，你更倾向哪种风格？\n\n"
                              "- 赛博朋克霓虹都市（未来感+雨夜+全息广告）\n"
                              "- 东方水墨山水（留白/晕染/诗意）\n- 极简3D产品渲染（干净背景+金属材质）\n\n"
                              "请告诉我你的倾向，我立刻为你构建画布提案。")
        upgraded = CanvasAssistantService._derive_question_from_list(trailing_statement)
        self.assertIsNotNone(upgraded)
        self.assertEqual(upgraded["options"][0]["label"], "赛博朋克霓虹都市")
        self.assertIn("全息广告", upgraded["options"][0]["description"])
        self.assertEqual(len(upgraded["options"]), 3)

    def test_canvas_digest_injected_into_context(self):
        self.save_nodes([
            {"id": "g1", "type": "generator", "position": {"x": 0, "y": 0},
             "data": {"workflowId": FakeWorkflow.id, "prompt": "雪地柴犬", "jobStatus": "succeeded", "jobId": "job-1", "url": "https://cdn/x.png"}},
        ])
        session = self.session()
        seen = []

        def chat(messages, model, callback=None):
            seen.append(list(messages))
            return self.reply({"text": "好的"})

        self.llm.assistant_chat.side_effect = chat
        with patch("backend.app.canvas_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "画布上有什么？", "client_message_id": "client-key-digest-01"})
        self.service.run("alice", run["id"])
        joined = dumps(seen[0])
        self.assertIn("canvas_now", joined)
        self.assertIn("succeeded", joined)
        self.assertIn("雪地柴犬", joined)

    def test_answered_question_recorded_in_request_context(self):
        session = self.session()
        envelope = {"text": "需要确认画幅", "question": {"title": "要哪种画幅？", "type": "single",
                     "options": [{"label": "横屏", "value": "16:9", "recommended": True}, {"label": "方形", "value": "1:1"}]}}
        detail = self.run_message(session, envelope, client_message_id="client-key-aq-01")
        question = next(p["question"] for m in detail["messages"] for p in m["parts"] if p["type"] == "question")
        self.send_and_run(session, {"text": "", "client_message_id": "client-key-aq-02",
                                     "question_id": question["id"], "answer_values": ["16:9"]},
                          {"text": "已按横屏推进。"})
        run = self.service.repo.get("alice", self.last_run_id, "run")
        answered = run["request_context"].get("answered_question")
        self.assertIsNotNone(answered)
        self.assertEqual(answered["question"], "要哪种画幅？")
        self.assertIn("横屏", answered["answer"])

    def test_validate_ops_delete_node(self):
        content = json.loads(canvas_content([
            {"id": "gen-1", "type": "generator", "position": {"x": 0, "y": 0},
             "data": {"workflowId": FakeWorkflow.id, "prompt": "p", "optionValues": {}}},
            {"id": "t1", "type": "text", "position": {"x": 10, "y": 0}, "data": {"text": "备注"}},
        ]))
        proposal = OpsProposal.model_validate({"title": "t", "ops": [{"op": "delete_node", "ref": "gen-1"}]})
        normalized, summary = self.service.actions.validate_ops(proposal.ops, content)
        self.assertEqual(summary["counts"]["delete_node"], 1)
        # 删除后同一提案里再引用该节点 → 报错（节点已不存在）
        with self.assertRaises(ValueError) as ctx:
            proposal = OpsProposal.model_validate({"title": "t", "ops": [
                {"op": "delete_node", "ref": "gen-1"},
                {"op": "connect", "ref": "c1", "source_ref": "gen-1", "target_ref": "t1"},
            ]})
            self.service.actions.validate_ops(proposal.ops, content)
        self.assertIn("既不在提案中创建", str(ctx.exception))
        # 同提案新建又删除 → 矛盾操作
        with self.assertRaises(ValueError) as ctx:
            proposal = OpsProposal.model_validate({"title": "t", "ops": [
                {"op": "create_text", "ref": "n1", "text": "x"},
                {"op": "delete_node", "ref": "n1"},
            ]})
            self.service.actions.validate_ops(proposal.ops, content)
        self.assertIn("本提案新建", str(ctx.exception))
        # 不存在的节点 → 报错
        with self.assertRaises(ValueError):
            proposal = OpsProposal.model_validate({"title": "t", "ops": [{"op": "update_text", "ref": "ghost", "text": "x"}]})
            self.service.actions.validate_ops(proposal.ops, content)
        # 同提案重复删除 → 报错
        with self.assertRaises(ValueError):
            proposal = OpsProposal.model_validate({"title": "t", "ops": [
                {"op": "delete_node", "ref": "t1"}, {"op": "delete_node", "ref": "t1"},
            ]})
            self.service.actions.validate_ops(proposal.ops, content)

    def test_validate_ops_update_text(self):
        content = json.loads(canvas_content([
            {"id": "t1", "type": "text", "position": {"x": 0, "y": 0}, "data": {"text": "旧内容", "label": "备注"}},
            {"id": "g1", "type": "generator", "position": {"x": 10, "y": 0},
             "data": {"workflowId": FakeWorkflow.id, "prompt": "p", "optionValues": {}}},
        ]))
        proposal = OpsProposal.model_validate({"title": "t", "ops": [
            {"op": "update_text", "ref": "t1", "text": "新内容 v2"},
        ]})
        normalized, summary = self.service.actions.validate_ops(proposal.ops, content)
        self.assertEqual(summary["counts"]["update_text"], 1)
        # 非 text 节点 → 报错
        with self.assertRaises(ValueError) as ctx:
            proposal = OpsProposal.model_validate({"title": "t", "ops": [{"op": "update_text", "ref": "g1", "text": "x"}]})
            self.service.actions.validate_ops(proposal.ops, content)
        self.assertIn("不是文字节点", str(ctx.exception))
        # 不存在的节点 → 报错
        with self.assertRaises(ValueError):
            proposal = OpsProposal.model_validate({"title": "t", "ops": [{"op": "update_text", "ref": "ghost", "text": "x"}]})
            self.service.actions.validate_ops(proposal.ops, content)
        # 同提案新建后更新 → 冗余操作拒绝
        with self.assertRaises(ValueError) as ctx:
            proposal = OpsProposal.model_validate({"title": "t", "ops": [
                {"op": "create_text", "ref": "n1", "text": "a"},
                {"op": "update_text", "ref": "n1", "text": "b"},
            ]})
            self.service.actions.validate_ops(proposal.ops, content)
        self.assertIn("本提案新建", str(ctx.exception))
        # 协议层：text/label 全空 → 报错
        from backend.app.canvas_assistant.protocol import OpsProposal as Ops
        with self.assertRaises(ValueError):
            Ops.model_validate({"title": "t", "ops": [{"op": "update_text", "ref": "t1"}]})

    def test_library_search_trims_entries(self):
        from backend.app.library_query import build_library_entries
        service = CanvasAssistantService(
            self.store, self.llm, self.canvas,
            workflows_for=lambda owner: [FakeWorkflow()],
            workflow_lookup=lambda mode_id: None,
            library_provider=lambda owner: build_library_entries([{
                "id": "job-1", "title": "夜景", "prompt": "赛博朋克",
                "rounds": [{"created_at": "now", "generation_items": [{"id": "item-1", "outputs": [
                    {"path": "media/x.png", "kind": "image", "label": "输出", "delivery_status": "cloud", "url": "https://cdn/x.png"},
                ]}]}],
            }]),
        )
        result = service._tool_library_search("alice", {"query": "赛博"})
        self.assertEqual(result["total"], 1)
        item = result["items"][0]
        self.assertEqual(item["kind"], "image")
        self.assertEqual(item["url"], "/api/jobs/job-1/generations/item-1/outputs/0/download")
        self.assertIn("job_id", item)


if __name__ == "__main__":
    unittest.main()
