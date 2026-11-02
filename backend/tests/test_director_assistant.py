from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.director_assistant.knowledge import extract_document, split_sections
from backend.app.director_assistant.protocol import NATIVE_SYSTEM_PROMPT, SYSTEM_PROMPT, ArtifactDraft, AssistantTurn, Question
from backend.app.director_assistant.repository import AssistantConflict, AssistantNotFound, dumps
from backend.app.director_assistant.routes import register_assistant_routes
from backend.app.director_assistant.service import AssistantService
from backend.app.director_assistant.resources import ResourceService
from backend.app.llm_provider import LlmProviderService
from backend.app.storage import JobStore


SCRIPT_TEXT = """《雨夜回声》

第1集 巷口来电

场景一 老城区巷口·夜·外
暴雨砸在青石板上，林夏撑着黑伞快步穿过巷口。手机在口袋里震动。
林夏（接起）：喂？
陌生男声（电话）：别回头，他就在你身后。
林夏猛地停住，伞沿的水珠连成一线。她缓缓回头，巷子尽头只有一盏忽明忽暗的路灯。
林夏（低声）：你是谁？
陌生男声：明天零点前，别让那卷录音带离开你。

场景二 林夏家·夜·内
林夏反锁房门，把录音带塞进随身包，又用椅子顶住门把手。
旁白：她不知道，录音带里的声音，正是三年前的自己。
"""


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = JobStore(Path(self.temp.name) / "assistant.db")
        self.llm = Mock()
        self.llm.assistant_models.return_value = ["model-a", "model-b"]
        self.llm.availability.return_value = (True, None)
        self.service = AssistantService(self.store, self.llm, Path(self.temp.name) / "uploads")
        self.repo = self.service.repo
        with self.store.connection() as conn:
            for table, fields in [
                ("ai_projects", "name TEXT,description TEXT,settings_json TEXT"),
                ("ai_project_documents", "filename TEXT,file_size INTEGER,input_mode TEXT,status TEXT,spine_template TEXT,visual_style TEXT,raw_text TEXT,analysis_json TEXT"),
                ("ai_project_assets", "kind TEXT,name TEXT,role TEXT,description TEXT,visual_prompt TEXT,image_url TEXT,voice_id TEXT,extra_json TEXT"),
                ("ai_project_episodes", "episode_num INTEGER,title TEXT,status TEXT,script_text TEXT,shots_count INTEGER,data_json TEXT"),
                ("ai_project_jobs", "job_type TEXT,status TEXT,payload_json TEXT"),
            ]:
                conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id VARCHAR(64) PRIMARY KEY,project_id TEXT,{fields},created_at TEXT,updated_at TEXT)")
            conn.execute("INSERT INTO ai_projects (id,name,description,settings_json,created_at,updated_at) VALUES ('p','未命名工程','','{}','now','now')")

    def session(self, **kwargs):
        return self.service.create_session("alice", kwargs)

    def draft(self, kind="script", **kwargs):
        session = self.session(project_id="p")
        args = {"artifact_type": kind, "title": "雨夜取经", "content": "# 雨夜取经\n\n完整剧本正文。", "data": {"summary": "一段新的梗概"}, **kwargs}
        return self.service.actions.create_draft("alice", session, args, "run-test")

    def run_message(self, session, envelope, client_message_id="request-12345"):
        self.llm.assistant_chat.side_effect = lambda messages, model, callback=None: self.reply(envelope, callback)
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "帮我做西游悬疑故事", "client_message_id": client_message_id})
        self.service.run("alice", run["id"])
        return self.service.detail("alice", session["id"])

    @staticmethod
    def reply(envelope, callback):
        raw = dumps(envelope)
        if callback:
            callback(raw[:25]); callback(raw)
        return raw

    def test_builtin_catalog_and_personal_isolation(self):
        self.assertEqual(len(self.service.catalog("alice")["resources"]), 9)
        session = self.session()
        with self.assertRaises(AssistantNotFound):
            self.service.detail("bob", session["id"])

    def test_resource_revision_stays_available_after_edit_and_delete(self):
        resource = self.service.resources.save("alice", {"name": "写作", "instructions": "先问方向"})
        session = self.session(selections={"skill_id": resource["version_id"]})
        updated = self.service.resources.save("alice", {**resource, "instructions": "直接交付"}, resource_id=resource["id"])
        self.assertNotEqual(resource["version_id"], updated["version_id"])
        self.repo.update("alice", updated, {}, status="deleted")
        _, snapshot = self.service.validate_selections("alice", session["selections"])
        self.assertEqual(snapshot["skill"]["instructions"], "先问方向")
        with self.assertRaises(AssistantNotFound):
            self.repo.get("bob", resource["version_id"], "resource_version", shared=True)

    def test_cannot_edit_builtin(self):
        builtin = self.service.catalog("alice")["resources"][0]
        with self.assertRaises(AssistantNotFound):
            self.service.resources.save("alice", builtin, resource_id=builtin["id"])

    def test_platform_resource_is_shared_and_manageable_by_admins(self):
        platform = self.service.resources.save("", {"name": "平台技能", "instructions": "平台方法", "category": "短剧"}, platform=True)
        user_view = {r["id"]: r for r in self.service.catalog("alice")["resources"]}
        admin_view = {r["id"]: r for r in self.service.catalog("alice", can_manage_platform=True)["resources"]}
        self.assertTrue(user_view[platform["id"]]["platform"])
        self.assertFalse(user_view[platform["id"]]["manageable"])
        self.assertTrue(admin_view[platform["id"]]["manageable"])
        builtin = next(r for r in user_view.values() if r["builtin"])
        self.assertFalse(user_view[builtin["id"]]["manageable"])
        self.service.create_session("bob", {"selections": {"skill_id": platform["version_id"]}})
        updated = self.service.resources.save("", {**platform, "instructions": "管理员更新"}, resource_id=platform["id"], platform=True)
        self.assertNotEqual(platform["version_id"], updated["version_id"])
        self.assertEqual(self.service.repo.get("alice", platform["version_id"], "resource_version", shared=True)["instructions"], "平台方法")

    def test_http_platform_resources_require_admin_and_protect_builtins(self):
        app = FastAPI(); app.state.director_assistant = self.service
        actor = {"id": "bob", "role": "employee"}
        register_assistant_routes(app, current_user=lambda: actor, mutating_user=lambda: actor)
        platform = self.service.resources.save("", {"name": "平台技能", "instructions": "平台方法"}, platform=True)
        builtin = next(r for r in self.service.catalog("alice")["resources"] if r["builtin"])
        with TestClient(app) as client:
            catalog = client.get("/api/director-assistant/catalog").json()
            self.assertFalse(catalog["can_manage_platform"])
            self.assertFalse(next(r for r in catalog["resources"] if r["id"] == platform["id"])["manageable"])
            self.assertEqual(client.post("/api/director-assistant/resources", json={"name": "平台新增", "instructions": "方法", "scope": "platform"}).status_code, 403)
            self.assertEqual(client.put(f"/api/director-assistant/resources/{platform['id']}", json={**platform, "instructions": "越权"}).status_code, 403)
            self.assertEqual(client.delete(f"/api/director-assistant/resources/{platform['id']}").status_code, 403)
            actor.update(id="admin1", role="admin")
            catalog = client.get("/api/director-assistant/catalog").json()
            self.assertTrue(catalog["can_manage_platform"])
            self.assertTrue(next(r for r in catalog["resources"] if r["id"] == platform["id"])["manageable"])
            created = client.post("/api/director-assistant/resources", json={"name": "平台新增", "instructions": "方法", "scope": "platform"})
            self.assertEqual(created.status_code, 201)
            self.assertTrue(created.json()["platform"])
            with self.store.connection() as conn:
                row = conn.execute("SELECT owner_id FROM ai_assistant_records WHERE id=?", (created.json()["id"],)).fetchone()
            self.assertEqual(row["owner_id"], "")
            updated = client.put(f"/api/director-assistant/resources/{platform['id']}", json={**platform, "instructions": "管理员更新"})
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["instructions"], "管理员更新")
            self.assertEqual(client.put(f"/api/director-assistant/resources/{builtin['id']}", json=builtin).status_code, 403)
            self.assertEqual(client.delete(f"/api/director-assistant/resources/{builtin['id']}").status_code, 403)
            self.assertEqual(client.delete(f"/api/director-assistant/resources/{platform['id']}").status_code, 200)
            self.assertNotIn(platform["id"], [r["id"] for r in client.get("/api/director-assistant/catalog").json()["resources"]])

    def test_import_preview_rejects_traversal_and_ignores_scripts(self):
        for name in ("../SKILL.md", "C:/SKILL.md", "..\\SKILL.md"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr(name, "bad")
            with self.assertRaises(ValueError):
                ResourceService.import_preview("skill.zip", buf.getvalue())
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("pack/SKILL.md", "---\nname: 西游创作\ndescription: 示例\n---\n先问用户方向")
            z.writestr("pack/references/style.md", "风格规范")
            z.writestr("pack/scripts/run.py", "raise RuntimeError('never run')")
        preview = ResourceService.import_preview("skill.zip", buf.getvalue())
        self.assertEqual(preview["name"], "西游创作")
        self.assertEqual(len(preview["references"]), 1)
        self.assertEqual(preview["ignored_files"], ["pack/scripts/run.py"])

    def test_export_roundtrip(self):
        original = self.service.resources.save("alice", {"name": "个人技能", "description": "简介", "instructions": "问一个问题", "references": {"x.md": "参考"}})
        imported = ResourceService.import_preview("skill.zip", self.service.resources.export("alice", original["id"]))
        self.assertEqual(imported["name"], original["name"])
        self.assertEqual(imported["instructions"].strip(), original["instructions"])

    def test_chinese_search_returns_actual_source_only(self):
        results = self.service.knowledge.search("alice", ["builtin-kb-journey"], "孙悟空大闹天宫")
        self.assertTrue(results)
        self.assertIn("孙悟空", results[0]["text"])
        self.assertIn("示例", results[0]["filename"])
        self.assertEqual(self.service.knowledge.search("alice", ["builtin-kb-journey"], "zxqv9999"), [])
        self.assertEqual(self.service.knowledge.search("alice", [], "孙悟空"), [])
        with self.assertRaises(ValueError):
            self.service.knowledge.read("alice", [], results[0]["id"])

    def test_private_knowledge_not_readable_by_another_account(self):
        kb = self.repo.insert("alice", "knowledge", {"name": "秘密"})
        with self.assertRaises(AssistantNotFound):
            self.service.knowledge.search("bob", [kb["id"]], "秘密")

    def test_docx_and_long_sections(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>西游人物设定</w:t></w:r></w:p></w:body></w:document>')
        self.assertIn("西游人物设定", extract_document("a.docx", buf.getvalue())[0][1])
        chunks = split_sections([("正文", "# 第一章\n" + "悬疑故事" * 2000)])
        self.assertGreater(len(chunks), 3)
        self.assertTrue(all(len(c["text"]) <= 1401 for c in chunks))
        with self.assertRaises(ValueError):
            split_sections([("空白页", "")])

    def test_selected_model_is_per_run_not_global(self):
        session = self.session(selections={"model_id": "model-b"})
        detail = self.run_message(session, {"text": "先聊人物。"})
        self.assertEqual(detail["messages"][-1]["selections"]["model_id"], "model-b")
        self.assertEqual(self.llm.assistant_chat.call_args.args[1], "model-b")
        self.assertNotEqual(self.store.get_llm_settings()["model"], "model-b")
        self.assertIsNone(detail["session"]["active_run_id"])

    def test_web_search_selection_defaults_off_and_updates(self):
        session = self.session()
        self.assertFalse(session["selections"]["web_search"])
        updated = self.service.update_session("alice", session["id"], {
            "version": session["version"],
            "selections": {**session["selections"], "web_search": True},
        })
        self.assertTrue(updated["selections"]["web_search"])
        self.assertTrue(self.service.detail("alice", session["id"])["session"]["selections"]["web_search"])

    def test_model_not_in_allowlist_rejected(self):
        with self.assertRaises(ValueError):
            self.session(selections={"model_id": "private-model"})

    def test_resolution_answer_is_persisted_to_project_settings(self):
        session = self.session(project_id="p")
        detail = self.run_message(session, {"text": "先确认规格。", "question": {
            "title": "出片分辨率（整集统一）", "type": "single",
            "options": [
                {"label": "768P：先快速过一遍节奏", "value": "768p"},
                {"label": "2K：直接上高清", "value": "2k"},
            ],
        }})
        question = detail["session"]["pending_question"]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            self.service.send("alice", session["id"], {"question_id": question["id"], "answer_values": ["768p"], "client_message_id": "resolution-answer-123"})
        with self.store.connection() as conn:
            row = conn.execute("SELECT settings_json FROM ai_projects WHERE id='p'").fetchone()
        extra = json.loads(row["settings_json"])["extra"]
        self.assertEqual(extra["video_resolution"], "768p")
        self.assertEqual(extra["video_resolution_label"], "768P")

    def test_non_resolution_answer_leaves_project_settings_untouched(self):
        session = self.session(project_id="p")
        detail = self.run_message(session, {"text": "先定方向。", "question": {
            "title": "更喜欢哪种悬疑？", "type": "single",
            "options": [{"label": "古风悬疑", "value": "period"}, {"label": "现代悬疑", "value": "modern"}],
        }})
        question = detail["session"]["pending_question"]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            self.service.send("alice", session["id"], {"question_id": question["id"], "answer_values": ["period"], "client_message_id": "direction-answer-123"})
        with self.store.connection() as conn:
            row = conn.execute("SELECT settings_json FROM ai_projects WHERE id='p'").fetchone()
        self.assertNotIn("video_resolution", json.loads(row["settings_json"]).get("extra", {}))

    def test_parse_failure_hides_raw_validation_details(self):
        with self.assertRaises(ValueError) as raised:
            AssistantService._parse(dumps({"tool_calls": [{"name": "project_read", "arguments": {}, "unexpected": True}]}))
        self.assertEqual(str(raised.exception), "模型返回格式无法解析，请重试；若多次失败请换一个模型。")
        self.assertNotIn("validation error", str(raised.exception))

    def test_question_card_is_typed_and_answered_in_free_text(self):
        session = self.session()
        detail = self.run_message(session, {"text": "我们先定方向。", "question": {"title": "更喜欢哪种悬疑？", "type": "single", "options": [{"label": "古风悬疑", "value": "period"}, {"label": "现代悬疑", "value": "modern"}]}})
        question = detail["session"]["pending_question"]
        part = detail["messages"][-1]["parts"][-1]
        self.assertEqual(part["type"], "question")
        self.assertEqual(part["question"]["id"], question["id"])
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            self.service.send("alice", session["id"], {"text": "想做古代志怪，别太恐怖", "client_message_id": "free-answer-123"})
        self.assertIsNone(self.service.detail("alice", session["id"])["session"]["pending_question"])
        self.assertEqual(self.service.detail("alice", session["id"])["messages"][-2]["answer_to"], question["id"])

    def test_repeated_message_and_stale_question(self):
        session = self.session()
        request = {"text": "开始", "client_message_id": "same-request-123"}
        with patch("backend.app.director_assistant.service._EXECUTOR.submit") as submit:
            first = self.service.send("alice", session["id"], request)
            second = self.service.send("alice", session["id"], request)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(submit.call_count, 1)
        with self.assertRaises(AssistantConflict):
            self.service.send("alice", session["id"], {"text": "另一个", "client_message_id": "other-request-123"})

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(ValueError):
            AssistantTurn.model_validate({"tool_calls": [{"name": "run_shell", "arguments": {}}]})

    def test_prompt_requires_question_card_for_exclusive_choices(self):
        for prompt in (SYSTEM_PROMPT, NATIVE_SYSTEM_PROMPT):
            self.assertIn("互斥选项", prompt)
            self.assertIn("问题卡通道", prompt)
            self.assertIn("不能在正文用列表", prompt)
            self.assertIn("2到4个选项", prompt)
            self.assertIn("description", prompt)
            self.assertIn("不要为“自定义/其他”单独设选项", prompt)
        self.assertIn("调用 ask_question", NATIVE_SYSTEM_PROMPT)

    def test_choice_question_requires_two_to_four_options(self):
        with self.assertRaises(ValueError):
            Question.model_validate({"title": "方向？", "options": [{"label": "A", "value": "a"}]})
        with self.assertRaises(ValueError):
            Question.model_validate({"title": "方向？", "options": [{"label": str(i), "value": str(i)} for i in range(5)]})
        question = Question.model_validate({"title": "方向？", "options": [
            {"label": "A", "value": "a", "description": "代价是失去退路"},
            {"label": "B", "value": "b"},
        ]})
        self.assertEqual(question.options[0].description, "代价是失去退路")
        self.assertEqual(Question.model_validate({"title": "想说什么？", "type": "text"}).options, [])

    def test_model_history_uses_dialogue_instead_of_ui_event_arrays(self):
        history = AssistantService._history_content({"parts": [
            {"type": "markdown", "text": "想走温情结尾。"},
            {"type": "question", "question": {"id": "q1", "title": "结尾方向", "options": [{"value": "warm", "label": "温情"}]}},
            {"type": "artifact", "artifact_id": "draft-existing"},
            {"type": "tool", "name": "project_read", "status": "succeeded"},
        ]})
        self.assertEqual(history, "想走温情结尾。")
        self.assertEqual(
            AssistantService._strip_history_echo('先确定方向。\n\n此前的澄清问题（仅作历史数据）：{"title":"结尾方向"}'),
            "先确定方向。",
        )

        session = self.session()
        self.run_message(session, {"text": "先确定方向。", "question": {"title": "结尾方向", "type": "single", "options": [{"label": "温情", "value": "warm"}, {"label": "冷峻", "value": "cold"}]}})
        self.run_message(session, {"text": "先确定方向。"}, client_message_id="request-67890")
        messages = self.llm.assistant_chat.call_args.args[0]
        self.assertEqual(["帮我做西游悬疑故事", "帮我做西游悬疑故事"], [message["content"] for message in messages if message["role"] == "user"])
        self.assertIn("结尾方向", "\n".join(str(message["content"]) for message in messages if message["role"] == "system"))
        self.assertNotIn("仅作历史数据", "\n".join(str(message["content"]) for message in messages if message["role"] != "system"))

    def test_ui_record_echo_is_stripped_from_reply(self):
        detail = self.run_message(self.session(), {"text": "这个设定很有张力。\n\n此前的澄清问题（仅作历史数据）：{\"title\":\"结尾方向\"}"})
        self.assertEqual(detail["messages"][-1]["parts"][0]["text"], "这个设定很有张力。")

    def test_generation_creates_draft_without_project_write(self):
        session = self.session(project_id="p")
        detail = self.run_message(session, {"text": "剧本已写好，先看看。", "tool_calls": [{"name": "create_draft", "arguments": {"artifact_type": "script", "title": "西游悬疑", "content": "# 西游悬疑\n完整故事。", "data": {"summary": "悬疑"}}}]})
        self.assertEqual(len(detail["artifacts"]), 1)
        with self.store.connection() as conn:
            self.assertEqual(len(conn.execute("SELECT * FROM ai_project_documents").fetchall()), 0)

    def test_inline_tool_call_format_is_normalized(self):
        turn = AssistantService._parse('<tool_call>load_skill_reference{"path":"剧本创作"}</tool_call>')
        self.assertEqual(turn.tool_calls[0].name, "load_skill_reference")
        self.assertEqual(turn.tool_calls[0].arguments, {"path": "剧本创作"})
        bare = AssistantService._parse("<tool_call>editor_read</tool_call>")
        self.assertEqual(bare.tool_calls[0].arguments, {})
        with self.assertRaises(ValueError):
            AssistantService._parse('<tool_call>load_skill_reference{not-json}</tool_call>')
        with self.assertRaises(ValueError):
            AssistantService._parse('<tool_call>run_shell{"cmd":"ls"}</tool_call>')

    def test_qwen_style_json_tool_call_and_stray_response_tag_are_tolerated(self):
        turn = AssistantService._parse(
            '<tool_call>\n{"name": "project_read", "arguments": {"stage": "storyboard"}}\n</tool_call>\n</tool_response>'
        )
        self.assertEqual(turn.tool_calls[0].name, "project_read")
        self.assertEqual(turn.tool_calls[0].arguments, {"stage": "storyboard"})
        with self.assertRaises(ValueError):
            AssistantService._parse('<tool_call>{"name": "run_shell", "arguments": {}}</tool_call>')
        with self.assertRaises(ValueError):
            AssistantService._parse('<tool_call>{"name": "project_read", "arguments": {}, "permission": "write"}</tool_call>')

    def test_paired_tag_script_draft_survives_invalid_summary_and_escaped_newlines(self):
        raw = (
            "<tool_call>create_draft"
            "<param_key>artifact_type</param_key><param_value>script</param_value>"
            "<param_key>title</param_key><param_value>《雨夜回声》第1集</param_value>"
            "<param_key>content</param_key><param_value># 雨夜回声\\n\\n## 故事定位\\n雨夜，她收到一封信。</param_value>"
            "<param_key>data</param_key><param_value>{\"summary\": \"收到信\"别回头\"\"}</param_value>"
            "<param_key>revises_id</param_key><param_value>null</param_value>"
            "</tool_call>"
        )
        turn = AssistantService._parse(raw)
        args = turn.tool_calls[0].arguments
        self.assertEqual(args["artifact_type"], "script")
        self.assertIn("\n", args["content"])
        self.assertNotIn("\\n", args["content"])
        self.assertEqual(args["data"], {})

    def test_asset_draft_tolerates_null_optional_text_from_model(self):
        raw = dumps({"text": "资产设定已整理。", "tool_calls": [{"name": "create_draft", "arguments": {
            "artifact_type": "assets",
            "title": "雨夜回声资产",
            "content": "# 资产",
            "data": {"assets": [
                {"kind": "character", "name": "林深", "role": "主角", "description": "侦探", "visual_prompt": "雨夜风衣"},
                {"kind": "scene", "name": "公寓楼下", "role": None, "description": None, "visual_prompt": None},
            ]},
        }}]})
        assets = AssistantService._parse(raw).tool_calls[0].arguments
        assets = ArtifactDraft.model_validate(assets).data["assets"]
        self.assertEqual(assets[1]["role"], "")
        self.assertEqual(assets[1]["description"], "")
        self.assertEqual(assets[1]["visual_prompt"], "")

    def test_envelope_tolerates_raw_control_characters_in_content(self):
        raw = '{"text": "已整理。", "tool_calls": [{"name": "create_draft", "arguments": {"artifact_type": "script", "title": "雨夜回声", "content": "# 第一集\n\n林深回头。"}}]}'
        turn = AssistantService._parse(raw)
        self.assertIn("\n\n林深回头。", turn.tool_calls[0].arguments["content"])

    def test_top_level_tool_array_is_strictly_normalized(self):
        flat = AssistantService._parse(dumps([{
            "type": "create_draft",
            "artifact_type": "script",
            "title": "雨夜回声",
            "content": SCRIPT_TEXT,
        }]))
        self.assertEqual(flat.tool_calls[0].name, "create_draft")
        self.assertEqual(flat.tool_calls[0].arguments["artifact_type"], "script")
        nested = AssistantService._parse(dumps([{
            "type": "create_draft",
            "arguments": {"artifact_type": "script", "title": "雨夜回声", "content": SCRIPT_TEXT},
        }]))
        self.assertEqual(nested.tool_calls[0].arguments["content"], SCRIPT_TEXT)
        with self.assertRaises(ValueError):
            AssistantService._parse(dumps([flat.tool_calls[0].model_dump(), {"type": "run_shell", "cmd": "dir"}]))
        with self.assertRaises(ValueError):
            AssistantService._parse(dumps([{"type": "editor_read", "permission": "write"}]))
        with self.assertRaises(ValueError):
            AssistantService._parse(dumps([{"type": "create_draft", "artifact_type": "script", "title": "坏参数", "content": 123}]))

    def test_tool_id_alias_is_narrow_and_still_uses_protocol_validation(self):
        payload = {"tool_calls": [{"id": "create_draft", "arguments": {
            "artifact_type": "script", "title": "雨夜回声", "content": SCRIPT_TEXT,
        }}]}
        turn = AssistantService._parse(dumps(payload))
        self.assertEqual(turn.tool_calls[0].name, "create_draft")
        with self.assertRaises(ValueError):
            AssistantService._parse(dumps({"tool_calls": [{"id": "run_shell", "arguments": {}}]}))
        with self.assertRaises(ValueError):
            AssistantService._parse(dumps({"tool_calls": [{"id": "create_draft", "name": "create_draft", "arguments": payload["tool_calls"][0]["arguments"]}]}))

    def test_tool_call_display_metadata_is_stripped_but_unknown_fields_still_fail(self):
        payload = {"tool_calls": [{
            "name": "create_draft",
            "label": "分镜设计",
            "description": "生成4镜分镜",
            "arguments": {"artifact_type": "plan", "title": "雨夜回声 第1集资产设定", "content": "资产设定"},
        }]}
        turn = AssistantService._parse(dumps(payload))
        self.assertEqual(turn.tool_calls[0].name, "create_draft")
        self.assertEqual(turn.tool_calls[0].arguments["artifact_type"], "plan")
        with self.assertRaises(ValueError):
            AssistantService._parse(dumps({"tool_calls": [{
                "name": "create_draft",
                "permission": "write",
                "arguments": {"artifact_type": "plan", "title": "x", "content": "x"},
            }]}))

    def test_tool_call_input_alias_is_normalized_without_widening_protocol(self):
        turn = AssistantService._parse(dumps({"tool_calls": [{
            "name": "project_read",
            "input": {"stage": "storyboard"},
            "label": "读取工程",
        }]}))
        self.assertEqual(turn.tool_calls[0].name, "project_read")
        self.assertEqual(turn.tool_calls[0].arguments, {"stage": "storyboard"})
        with self.assertRaises(ValueError):
            AssistantService._parse(dumps({"tool_calls": [{
                "name": "project_read",
                "input": {"stage": "storyboard"},
                "arguments": {"stage": "assets"},
            }]}))

    def test_invalid_script_array_repair_preserves_write_obligation(self):
        session = self.session()
        invalid = dumps([{"type": "create_draft", "artifact_type": "script", "title": "雨夜回声", "content": 123}])
        self.llm.assistant_chat.side_effect = [invalid, dumps({"text": SCRIPT_TEXT})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "写一集完整剧本", "client_message_id": "script-array-repair-123"})
        self.service.run("alice", run["id"])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        artifacts = self.repo.list("alice", "artifact", parent=session["id"])
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["artifact_type"], "script")

    def test_format_repair_preserves_media_proposal(self):
        with self.store.connection() as conn:
            conn.execute("INSERT INTO ai_project_assets (id,project_id,kind,name) VALUES ('hero','p','character','悟空')")
        session = self.session(project_id="p")
        invalid = dumps([{"type": "propose_media", "title": "角色定妆", "media_type": "asset_image"}])
        repaired = dumps({"text": "已经准备好定妆提案。", "tool_calls": [{"name": "propose_media", "arguments": {"title": "角色定妆", "media_type": "asset_image", "asset_id": "hero"}}]})
        self.llm.assistant_chat.side_effect = [invalid, repaired]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "准备生图", "client_message_id": "repair-media-123"})
        self.service.run("alice", run["id"])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        self.assertEqual(len(self.repo.list("alice", "media_proposal")), 1)

    def test_top_level_tool_array_creates_draft_through_normal_tool_path(self):
        session = self.session()
        self.llm.assistant_chat.side_effect = [dumps([{
            "type": "create_draft",
            "artifact_type": "script",
            "title": "雨夜回声",
            "content": SCRIPT_TEXT,
        }])]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {
                "text": "给我一集完整的剧本",
                "client_message_id": "script-array-tool-123",
            })
        self.service.run("alice", run["id"])
        artifacts = self.repo.list("alice", "artifact", parent=session["id"])
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["artifact_type"], "script")
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")

    def test_blockquote_wrapped_envelope_is_normalized(self):
        turn = AssistantService._parse('>{"text":"已整理","tool_calls":[],"citation_ids":[]}')
        self.assertEqual(turn.text, "已整理")
        fenced = AssistantService._parse('> ```json\n{"text":"第二段","tool_calls":[],"citation_ids":[]}\n```')
        self.assertEqual(fenced.text, "第二段")

    def test_parse_ignores_content_after_the_first_envelope(self):
        envelope = {
            "text": "接下来明确核心冲突。",
            "question": {"title": "明确核心冲突", "type": "single", "options": [{"label": "人际关系", "value": "interpersonal"}, {"label": "利益冲突", "value": "interest"}]},
            "tool_calls": [], "citation_ids": [],
        }
        aside = AssistantService._parse(dumps(envelope) + "\n\n（等待用户明确创作方向后，可继续检索相关题材范例。）")
        self.assertEqual(aside.text, "接下来明确核心冲突。")
        self.assertEqual(aside.question.title, "明确核心冲突")
        stray = AssistantService._parse(dumps({"text": "已整理", "tool_calls": [], "citation_ids": []}) + "%")
        self.assertEqual(stray.text, "已整理")
        repeated = AssistantService._parse(
            dumps({"text": "第一版", "tool_calls": [], "citation_ids": []})
            + "\n\n" + dumps({"text": "第一版", "tool_calls": [], "citation_ids": []})
        )
        self.assertEqual(repeated.text, "第一版")
        with self.assertRaises(ValueError):
            AssistantService._parse("不是 JSON")
        # A second value carrying the real tool call must not be dropped silently.
        with self.assertRaises(ValueError):
            AssistantService._parse(
                dumps({"text": "已经准备好定妆提案。", "tool_calls": [], "citation_ids": []})
                + "\n" + dumps({"tool_calls": [{"name": "propose_media", "arguments": {"title": "主角定妆", "media_type": "asset_image", "asset_id": "hero"}}]})
            )

    def test_turn_with_trailing_model_note_is_not_a_format_error(self):
        session = self.session()
        raw = dumps({
            "text": "接下来明确核心冲突。",
            "question": {"title": "明确核心冲突", "type": "single", "options": [{"label": "人际关系", "value": "interpersonal"}, {"label": "利益冲突", "value": "interest"}]},
            "tool_calls": [], "citation_ids": [],
        }) + "\n\n（等待用户选择后再继续。）"
        self.llm.assistant_chat.side_effect = lambda messages, model, callback=None: raw
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "帮我做西游悬疑故事", "client_message_id": "trailing-note-123"})
        self.service.run("alice", run["id"])
        self.assertEqual(self.llm.assistant_chat.call_count, 1)
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        parts = self.service.detail("alice", session["id"])["messages"][-1]["parts"]
        self.assertEqual([p["type"] for p in parts if p["type"] == "question"], ["question"])
        markdown = [p for p in parts if p["type"] == "markdown"][0]
        self.assertEqual(markdown["text"], "接下来明确核心冲突。")

    def test_stream_preview_accepts_blockquote_wrapped_envelope(self):
        session = self.session()
        long_text = SCRIPT_TEXT * 2
        raw = ">" + dumps({"text": long_text})
        previews = []
        original_emit = self.repo.emit

        def emit(owner, run_id, event, payload):
            if event == "text":
                previews.append(payload["text"])
            return original_emit(owner, run_id, event, payload)

        def chat(messages, model, callback=None):
            if callback:
                callback(raw[:25])
                callback(raw)
            return raw

        self.llm.assistant_chat.side_effect = chat
        with patch.object(self.repo, "emit", side_effect=emit), patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "继续", "client_message_id": "request-blockquote"})
            self.service.run("alice", run["id"])
        self.assertTrue(previews)
        self.assertTrue(previews[-1].startswith("《雨夜回声》"))
        markdown = [p for p in self.service.detail("alice", session["id"])["messages"][-1]["parts"] if p["type"] == "markdown"][0]
        self.assertEqual(markdown["text"], long_text)

    def test_script_request_repairs_text_only_reply_into_draft(self):
        session = self.session()
        repaired = {
            "text": "已整理成可采纳的剧本草稿。",
            "tool_calls": [{"name": "create_draft", "arguments": {"artifact_type": "script", "title": "雨夜回声", "content": SCRIPT_TEXT}}],
        }
        self.llm.assistant_chat.side_effect = [dumps({"text": SCRIPT_TEXT}), dumps(repaired)]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "帮我写第一集完整剧本", "client_message_id": "script-repair-123"})
        self.service.run("alice", run["id"])
        self.assertEqual(self.llm.assistant_chat.call_count, 2)
        self.assertIn("create_draft", self.llm.assistant_chat.call_args.args[0][-1]["content"])
        artifacts = self.repo.list("alice", "artifact")
        self.assertEqual([a["artifact_type"] for a in artifacts], ["script"])
        self.assertEqual(artifacts[0]["content"], SCRIPT_TEXT)
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")

    def test_script_request_creates_draft_when_repair_stays_text_only(self):
        session = self.session()
        self.llm.assistant_chat.side_effect = [dumps({"text": SCRIPT_TEXT}), dumps({"text": SCRIPT_TEXT})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "写一集悬疑短剧剧本", "client_message_id": "script-fallback-123"})
        self.service.run("alice", run["id"])
        self.assertEqual(self.llm.assistant_chat.call_count, 2)
        artifacts = self.repo.list("alice", "artifact")
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["title"], "雨夜回声")
        self.assertEqual(artifacts[0]["content"], SCRIPT_TEXT.strip())

    def test_script_format_repair_extracts_content_from_legacy_artifact_shape(self):
        session = self.session()
        previous = self.service.actions.create_draft(
            "alice", session, {"artifact_type": "script", "title": "初稿", "content": SCRIPT_TEXT}, "seed-run"
        )
        legacy = dumps({
            "artifact_id": previous["id"], "revision": 2, "applied": True,
            "content": SCRIPT_TEXT, "extra": "ignored",
        })
        self.llm.assistant_chat.side_effect = ['{"text": "第一段"', legacy]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {
                "text": "把最后一句改成新的结尾",
                "client_message_id": "script-legacy-artifact-repair-123",
            })
        self.service.run("alice", run["id"])
        artifacts = self.repo.list("alice", "artifact", parent=session["id"])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        self.assertEqual(len(artifacts), 2)
        self.assertEqual(artifacts[-1]["revises_id"], previous["id"])
        self.assertEqual(artifacts[-1]["revision"], previous["revision"] + 1)
        self.assertEqual(artifacts[-1]["content"], SCRIPT_TEXT.strip())

    def test_script_intent_accepts_creation_revision_and_context_followups_without_consultation_overmatch(self):
        self.assertTrue(AssistantService._has_script_intent("给我一集完整的剧本"))
        self.assertTrue(AssistantService._has_script_intent("我想做一个短剧，先从剧本开始"))
        self.assertTrue(AssistantService._has_script_intent("把这个想法发展成一集剧本"))
        self.assertTrue(AssistantService._has_script_intent("修改现有剧本的结局"))
        self.assertFalse(AssistantService._has_script_intent("把最后一句改成‘原来，你一直在等我回家。’，删掉手机短信这个细节，其余镜头和60秒时长保持。"))
        self.assertTrue(AssistantService._has_script_intent("把最后一句改成‘原来，你一直在等我回家。’，删掉手机短信这个细节，其余镜头和60秒时长保持。", script_context=True))
        self.assertFalse(AssistantService._has_script_intent("不要写完整剧本"))
        self.assertTrue(AssistantService._has_script_intent("不要只给大纲，直接写完整剧本"))
        self.assertFalse(AssistantService._has_script_intent("给我一个剧本标题"))
        self.assertFalse(AssistantService._has_script_intent("给我一个剧本简介"))
        self.assertFalse(AssistantService._has_script_intent("删除最后一个镜头"))
        self.assertTrue(AssistantService._has_script_intent("删除最后一个镜头", script_context=True))
        self.assertFalse(AssistantService._has_script_intent("给我几个剧本方向"))
        self.assertFalse(AssistantService._has_script_intent("给修改建议"))
        self.assertFalse(AssistantService._has_script_intent("不要改动"))
        self.assertFalse(AssistantService._has_script_intent("剧本怎么写"))
        self.assertFalse(AssistantService._has_script_intent("不要写剧本，先讨论方向"))

        history = [{"role": "user", "parts": [{"type": "markdown", "text": "我要创作一部悬疑剧本"}]}]
        for index in range(5):
            history.append({"role": "assistant", "parts": [{"type": "question", "question": {"title": f"问题{index}"}}]})
            history.append({"role": "user", "parts": [{"type": "markdown", "text": f"第{index + 1}轮回答"}]})
        self.assertTrue(AssistantService._script_requested(history))
        self.assertTrue(AssistantService._script_requested(history + [
            {"role": "user", "parts": [{"type": "markdown", "text": "按刚才方向继续"}]},
        ]))
        self.assertFalse(AssistantService._script_requested([
            {"role": "user", "parts": [{"type": "markdown", "text": "继续"}]},
        ]))
        existing_script = [
            {"role": "user", "parts": [{"type": "markdown", "text": "我要创作一部悬疑剧本"}]},
            {"role": "assistant", "parts": [{"type": "artifact", "artifact_id": "draft-1"}]},
            {"role": "user", "parts": [{"type": "markdown", "text": "给我几个剧本方向"}]},
        ]
        self.assertFalse(AssistantService._script_requested(existing_script))
        self.assertFalse(AssistantService._script_requested(existing_script[:-1] + [
            {"role": "user", "parts": [{"type": "markdown", "text": "继续"}]},
        ]))
        self.assertTrue(AssistantService._script_requested(existing_script[:-1] + [
            {"role": "user", "parts": [{"type": "markdown", "text": "删除最后一个镜头"}]},
        ], script_context=True))
        self.assertFalse(AssistantService._script_requested([
            {"role": "user", "parts": [{"type": "markdown", "text": "我要创作一部悬疑剧本"}]},
            {"role": "assistant", "parts": [{"type": "artifact", "artifact_id": "draft-1"}]},
            {"role": "user", "parts": [{"type": "markdown", "text": "我要三个角色设定"}]},
            {"role": "assistant", "parts": [{"type": "question", "question": {"title": "角色数量"}}]},
            {"role": "user", "parts": [{"type": "markdown", "text": "三个角色"}]},
        ], script_context=True))
        self.assertFalse(AssistantService._script_revision_requested([
            {"role": "user", "parts": [{"type": "markdown", "text": "写第二集，保留原来角色"}]},
        ], script_context=True))
        self.assertTrue(AssistantService._script_revision_requested([
            {"role": "user", "parts": [{"type": "markdown", "text": "修改上一版，不要写超自然情节"}]},
        ], script_context=True))
        self.assertFalse(AssistantService._script_revision_requested([
            {"role": "user", "parts": [{"type": "markdown", "text": "不要修改上一版"}]},
        ], script_context=True))
        self.assertTrue(AssistantService._script_revision_requested([
            {"role": "user", "parts": [{"type": "markdown", "text": "修改第二集的结尾"}]},
        ], script_context=True))

    def test_script_fallback_revises_latest_script_draft(self):
        session = self.session()
        previous = self.service.actions.create_draft(
            "alice",
            session,
            {"artifact_type": "script", "title": "初稿", "content": SCRIPT_TEXT},
            "seed-run",
        )
        self.llm.assistant_chat.side_effect = [dumps({"text": SCRIPT_TEXT}), dumps({"text": SCRIPT_TEXT})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {
                "text": "把这个想法发展成一集剧本",
                "client_message_id": "script-revise-fallback-123",
            })
        self.service.run("alice", run["id"])
        artifacts = self.repo.list("alice", "artifact", parent=session["id"])
        self.assertEqual(len(artifacts), 2)
        self.assertEqual(artifacts[-1]["revises_id"], previous["id"])
        self.assertEqual(artifacts[-1]["revision"], previous["revision"] + 1)

    def test_new_episode_fallback_starts_a_new_revision_chain(self):
        session = self.session()
        previous = self.service.actions.create_draft(
            "alice",
            session,
            {"artifact_type": "script", "title": "初稿", "content": SCRIPT_TEXT},
            "seed-run",
        )
        self.llm.assistant_chat.side_effect = [dumps({"text": SCRIPT_TEXT}), dumps({"text": SCRIPT_TEXT})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {
                "text": "写第二集完整剧本，保留原来角色",
                "client_message_id": "script-new-episode-fallback-123",
            })
        self.service.run("alice", run["id"])
        artifacts = self.repo.list("alice", "artifact", parent=session["id"])
        self.assertEqual(len(artifacts), 2)
        self.assertEqual(artifacts[-1]["revises_id"], None)
        self.assertEqual(artifacts[-1]["revision"], 1)
        self.assertNotEqual(artifacts[-1]["id"], previous["id"])

    def test_smart_edit_shot_request_does_not_force_script_draft(self):
        session = self.session(project_id="p", context={"kind": "smart_edit", "sequence_id": "main"})
        self.llm.assistant_chat.side_effect = [dumps({"text": "我会按剪辑工作区处理这个请求。"})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {
                "text": "删除最后一个镜头",
                "client_message_id": "smart-edit-shot-123",
            })
        self.service.run("alice", run["id"])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        self.assertEqual(self.repo.list("alice", "artifact", parent=session["id"]), [])
        self.assertEqual(self.llm.assistant_chat.call_count, 1)

    def test_retry_preserves_script_source_without_turning_all_retries_into_script(self):
        def failed_run(text, *, artifact=None):
            session = self.session()
            if artifact:
                self.service.actions.create_draft("alice", session, {"artifact_type": "script", "title": "初稿", "content": SCRIPT_TEXT}, "seed")
            user = self.repo.insert("alice", "message", {
                "session_id": session["id"], "role": "user", "run_id": "old-run", "sequence": 1,
                "parts": [{"type": "markdown", "text": text}],
            }, parent=session["id"])
            response = self.repo.insert("alice", "message", {
                "session_id": session["id"], "role": "assistant", "run_id": "old-run", "sequence": 2, "parts": [],
            }, parent=session["id"], status="failed")
            run = self.repo.insert("alice", "run", {
                "session_id": session["id"], "user_message_id": user["id"], "message_id": response["id"],
                "context": None,
            }, parent=session["id"], status="failed")
            return session, run

        script_session, script_run = failed_run("写一集完整剧本")
        with patch.object(self.service, "send", return_value={"id": "retry-script"}) as send:
            self.service.retry("alice", script_run["id"], "retry-script-123")
        self.assertIn("剧本创作", send.call_args.args[2]["text"])

        edit_session, edit_run = failed_run("把最后一句改成新的结尾", artifact=True)
        with patch.object(self.service, "send", return_value={"id": "retry-edit"}) as send:
            self.service.retry("alice", edit_run["id"], "retry-edit-123")
        self.assertIn("剧本修改", send.call_args.args[2]["text"])

        ordinary_session, ordinary_run = failed_run("给我三个角色方向")
        with patch.object(self.service, "send", return_value={"id": "retry-ordinary"}) as send:
            self.service.retry("alice", ordinary_run["id"], "retry-ordinary-123")
        self.assertNotIn("剧本创作", send.call_args.args[2]["text"])
        self.assertNotIn("剧本修改", send.call_args.args[2]["text"])

    def test_script_repair_read_only_tool_cannot_finish_without_draft(self):
        session = self.session()
        self.llm.assistant_chat.side_effect = [
            dumps({"text": SCRIPT_TEXT}),
            dumps({"text": "正在读取工程。", "tool_calls": [{"name": "project_read", "arguments": {}}]}),
            dumps({"text": SCRIPT_TEXT}),
        ]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {
                "text": "帮我写第一集完整剧本",
                "client_message_id": "script-read-only-loop-123",
            })
        self.service.run("alice", run["id"])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        artifacts = self.repo.list("alice", "artifact", parent=session["id"])
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["artifact_type"], "script")

    def test_script_idea_request_is_not_forced_into_a_draft(self):
        session = self.session()
        self.llm.assistant_chat.side_effect = [dumps({"text": "可以先从职场、家庭、悬疑三个方向考虑。"})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "给我几个剧本方向", "client_message_id": "script-idea-123"})
        self.service.run("alice", run["id"])
        self.assertEqual(self.llm.assistant_chat.call_count, 1)
        self.assertEqual(self.repo.list("alice", "artifact"), [])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")

    def test_script_request_without_usable_text_fails_honestly(self):
        session = self.session()
        self.llm.assistant_chat.side_effect = [dumps({"text": "好的，我先梳理一下。"}), dumps({"text": "好的。"})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "写剧本", "client_message_id": "script-empty-123"})
        self.service.run("alice", run["id"])
        saved = self.repo.get("alice", run["id"])
        self.assertEqual(saved["status"], "failed")
        self.assertIn("没有生成可采纳的剧本草稿", saved["error"])
        self.assertEqual(self.repo.list("alice", "artifact"), [])

    def test_preview_does_not_write_and_adoption_is_idempotent(self):
        artifact = self.draft()
        first = self.service.actions.preview("alice", artifact["id"], "p")
        second = self.service.actions.preview("alice", artifact["id"], "p")
        with self.store.connection() as conn:
            self.assertEqual(len(conn.execute("SELECT * FROM ai_project_documents").fetchall()), 0)
        adopted = self.service.actions.apply("alice", first["id"])
        self.assertEqual(adopted["status"], "applied")
        self.assertEqual(self.service.actions.apply("alice", first["id"])["id"], adopted["id"])
        self.assertEqual(self.service.actions.apply("alice", second["id"])["id"], adopted["id"])
        with self.store.connection() as conn:
            self.assertEqual(len(conn.execute("SELECT * FROM ai_project_documents").fetchall()), 1)
            self.assertEqual(conn.execute("SELECT name FROM ai_projects WHERE id='p'").fetchone()["name"], "雨夜取经")

    def test_existing_manual_metadata_is_preserved(self):
        with self.store.connection() as conn:
            conn.execute("UPDATE ai_projects SET name='手动名称',description='手动简介',settings_json=? WHERE id='p'", (dumps({"extra": {"name_source": "manual", "description_source": "manual"}}),))
        a = self.draft(); preview = self.service.actions.preview("alice", a["id"], "p"); self.service.actions.apply("alice", preview["id"])
        with self.store.connection() as conn:
            project = conn.execute("SELECT * FROM ai_projects WHERE id='p'").fetchone()
        self.assertEqual((project["name"], project["description"]), ("手动名称", "手动简介"))

    def test_concurrent_target_edit_rejects_entire_adoption(self):
        with self.store.connection() as conn:
            conn.execute("INSERT INTO ai_project_documents (id,project_id,filename,raw_text) VALUES ('d','p','旧稿','旧正文')")
        artifact = self.draft()
        preview = self.service.actions.preview("alice", artifact["id"], "p", {"document": "d"})
        with self.store.connection() as conn:
            conn.execute("UPDATE ai_project_documents SET raw_text='人工编辑的新正文' WHERE id='d'")
        with self.assertRaises(AssistantConflict):
            self.service.actions.apply("alice", preview["id"])
        with self.store.connection() as conn:
            self.assertEqual(conn.execute("SELECT raw_text FROM ai_project_documents WHERE id='d'").fetchone()["raw_text"], "人工编辑的新正文")

    def test_episode_collision_requires_explicit_target(self):
        with self.store.connection() as conn:
            conn.execute("INSERT INTO ai_project_episodes (id,project_id,episode_num,title,data_json) VALUES ('ep','p',1,'旧分集','{}')")
        a = self.draft("episodes", data={"episodes": [{"episode_num": 1, "title": "新分集", "summary": "大纲"}]})
        with self.assertRaises(AssistantConflict):
            self.service.actions.preview("alice", a["id"], "p")
        preview = self.service.actions.preview("alice", a["id"], "p", {"episode:1": "ep"})
        self.assertEqual(preview["changes"][0]["operation"], "update")

    def test_legacy_operation_blocks_adoption(self):
        a = self.draft()
        with self.store.connection() as conn:
            conn.execute("INSERT INTO ai_project_jobs (id,project_id,job_type,status) VALUES ('legacy','p','ai_pipeline','awaiting_review')")
        with self.assertRaises(AssistantConflict):
            self.service.actions.preview("alice", a["id"], "p")

    def test_recipe_is_frozen_per_run_and_separate_from_conversation_skill(self):
        from backend.app.skill_packs.recipe import HALF_NARRATED_PACK_ID
        with self.store.connection() as conn:
            conn.execute("UPDATE ai_projects SET settings_json=? WHERE id='p'", (dumps({"extra": {"skill_pack_id": HALF_NARRATED_PACK_ID}}),))
        skill = next(r for r in self.service.catalog("alice")["resources"] if r["resource_type"] == "skill")
        session = self.session(project_id="p", selections={"skill_id": skill["version_id"]})
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "写剧本", "client_message_id": "recipe-freeze-123"})
        with self.store.connection() as conn:
            conn.execute("UPDATE ai_projects SET settings_json='{}' WHERE id='p'")
        saved = self.repo.get("alice", run["id"], "run")
        self.assertEqual(saved["production_recipe"]["id"], HALF_NARRATED_PACK_ID)
        self.assertTrue(saved["production_recipe"]["stages"]["script"])
        self.assertEqual(saved["selections"]["skill_id"], skill["version_id"])

    def test_script_request_auto_reads_recipe_before_first_create_draft(self):
        from backend.app.skill_packs.recipe import HALF_NARRATED_PACK_ID
        with self.store.connection() as conn:
            conn.execute("UPDATE ai_projects SET settings_json=? WHERE id='p'", (dumps({"extra": {"skill_pack_id": HALF_NARRATED_PACK_ID}}),))
        session = self.session(project_id="p")
        self.llm.assistant_chat.side_effect = [dumps({
            "text": "已整理成可采纳的剧本草稿。",
            "tool_calls": [{"name": "create_draft", "arguments": {
                "artifact_type": "script", "title": "雨夜回声", "content": SCRIPT_TEXT,
            }}],
        })]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {
                "text": "请直接写一集完整剧本",
                "client_message_id": "script-auto-recipe-123",
            })
        self.service.run("alice", run["id"])

        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        self.assertEqual(self.llm.assistant_chat.call_count, 1)
        messages = self.llm.assistant_chat.call_args.args[0]
        recipe_instructions = run["production_recipe"]["stages"]["script"]
        self.assertTrue(any("工作台已读取本轮剧本制作规范" in message["content"] for message in messages))
        self.assertTrue(any(
            "visual_lock=photoreal-live-action-short-drama" in message["content"]
            and "## 2. Story and script" in message["content"]
            for message in messages
        ))
        tool_calls = self.repo.list("alice", "tool_call", parent=run["id"])
        self.assertEqual(tool_calls[0]["name"], "project_read")
        self.assertEqual(tool_calls[0]["arguments"], {"stage": "script"})
        self.assertEqual(tool_calls[1]["name"], "create_draft")
        self.assertEqual(len(self.repo.list("alice", "artifact", parent=session["id"])), 1)

    def test_non_script_request_does_not_auto_read_script_recipe(self):
        from backend.app.skill_packs.recipe import HALF_NARRATED_PACK_ID
        with self.store.connection() as conn:
            conn.execute("UPDATE ai_projects SET settings_json=? WHERE id='p'", (dumps({"extra": {"skill_pack_id": HALF_NARRATED_PACK_ID}}),))
        session = self.session(project_id="p")
        self.llm.assistant_chat.side_effect = [dumps({"text": "可以先从人物关系和冲突方向展开。"})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {
                "text": "给我几个剧本方向",
                "client_message_id": "non-script-no-recipe-123",
            })
        self.service.run("alice", run["id"])

        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        self.assertEqual(self.repo.list("alice", "tool_call", parent=run["id"]), [])
        messages = self.llm.assistant_chat.call_args.args[0]
        self.assertFalse(any("工作台已读取本轮剧本制作规范" in message["content"] for message in messages))

    def test_smart_edit_request_does_not_auto_read_script_recipe(self):
        from backend.app.skill_packs.recipe import HALF_NARRATED_PACK_ID
        with self.store.connection() as conn:
            conn.execute("UPDATE ai_projects SET settings_json=? WHERE id='p'", (dumps({"extra": {"skill_pack_id": HALF_NARRATED_PACK_ID}}),))
        session = self.session(project_id="p", context={"kind": "smart_edit", "sequence_id": "main"})
        self.llm.assistant_chat.side_effect = [dumps({"text": "我会按智能剪辑工作区处理这个请求。"})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {
                "text": "删除最后一个镜头",
                "client_message_id": "smart-edit-no-recipe-123",
            })
        self.service.run("alice", run["id"])

        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        self.assertEqual(self.repo.list("alice", "tool_call", parent=run["id"]), [])
        messages = self.llm.assistant_chat.call_args.args[0]
        self.assertFalse(any("工作台已读取本轮剧本制作规范" in message["content"] for message in messages))

    def test_project_draft_requires_reading_frozen_recipe_stage(self):
        session = self.session(project_id="p")
        run = {"id": "r", "project_id": "p", "production_recipe": {"id": "recipe", "name": "制作规范", "stages": {"script": "本阶段必须保留对白与画面双通道"}}}
        args = {"artifact_type": "script", "title": "剧本", "content": "正文"}
        with self.assertRaises(ValueError):
            self.service._tool("alice", session, run, "create_draft", args, {})
        context = self.service._tool("alice", session, run, "project_read", {"stage": "script"}, {})
        self.assertEqual(context["production_recipe"]["instructions"], "本阶段必须保留对白与画面双通道")
        result = self.service._tool("alice", session, run, "create_draft", args, {})
        self.assertEqual(self.repo.get("alice", result["id"], "artifact")["content"], "正文")

    def test_load_skill_reference_error_lists_available_files(self):
        session = self.session(project_id="p")
        run = {"id": "r", "resource_snapshot": {"skill": {"references": {"SKILL.md": "方法", "references/范例.md": "范例"}}}}
        with self.assertRaises(ValueError) as ctx:
            self.service._tool("alice", session, run, "load_skill_reference", {"path": "剧本创作规范.md"}, {})
        self.assertIn("「SKILL.md」", str(ctx.exception))
        self.assertIn("「references/范例.md」", str(ctx.exception))
        empty_run = {"id": "r2", "resource_snapshot": {"skill": {"references": {}}}}
        with self.assertRaises(ValueError) as ctx2:
            self.service._tool("alice", session, empty_run, "load_skill_reference", {"path": "方法.md"}, {})
        self.assertIn("没有任何参考文件", str(ctx2.exception))
        self.assertIn("不要再次调用", str(ctx2.exception))

    def test_prompt_constrains_skill_reference_and_single_draft(self):
        for prompt in (SYSTEM_PROMPT, NATIVE_SYSTEM_PROMPT):
            self.assertIn("列表为空表示该 Skill 没有参考文件", prompt)
            self.assertIn("不要调用本工具", prompt)
            self.assertIn("同一轮只创建一份待采纳文字草稿", prompt)
            self.assertIn("不要再同时生成分集大纲、计划或资产等其他草稿", prompt)

    def test_episode_created_after_preview_requires_refresh(self):
        first = self.draft("episodes", data={"episodes": [{"episode_num": 1, "title": "甲", "summary": "大纲"}]})
        second = self.draft("episodes", data={"episodes": [{"episode_num": 1, "title": "乙", "summary": "另一版"}]})
        previews = [self.service.actions.preview("alice", draft["id"], "p") for draft in (first, second)]
        self.service.actions.apply("alice", previews[0]["id"])
        with self.assertRaises(AssistantConflict):
            self.service.actions.apply("alice", previews[1]["id"])
        with self.store.connection() as conn:
            self.assertEqual(len(conn.execute("SELECT id FROM ai_project_episodes WHERE project_id='p'").fetchall()), 1)

    def test_explicit_add_cannot_fall_back_to_model_update_target(self):
        with self.store.connection() as conn:
            conn.execute("INSERT INTO ai_project_episodes (id,project_id,episode_num,title,data_json) VALUES ('ep','p',1,'原分集','{}')")
        draft = self.draft("episodes", data={"episodes": [{"episode_num": 1, "episode_id": "ep", "title": "另一版"}]})
        with self.assertRaises(AssistantConflict):
            self.service.actions.preview("alice", draft["id"], "p", {"episode:1": ""})

    def test_media_requires_confirmation_and_confirmation_is_idempotent(self):
        with self.store.connection() as conn:
            conn.execute("INSERT INTO ai_project_assets (id,project_id,kind,name) VALUES ('hero','p','character','悟空')")
        session = self.session(project_id="p")
        with patch("backend.app.director_assistant.actions._MEDIA_EXECUTOR.submit") as submit:
            proposal = self.service.actions.propose_media("alice", session, {"title": "角色定妆", "media_type": "asset_image", "asset_id": "hero"}, "run-test")
            self.assertEqual(submit.call_count, 0)
            first = self.service.actions.confirm_media("alice", proposal["id"])
            second = self.service.actions.confirm_media("alice", proposal["id"])
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(submit.call_count, 1)

    def test_cancelled_run_does_not_execute_draft_tool(self):
        session = self.session()
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "开始", "client_message_id": "cancel-request-12"})
        self.service.cancel("alice", run["id"])
        self.service.run("alice", run["id"])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "cancelled")
        self.assertEqual(self.repo.list("alice", "artifact"), [])
        self.assertIsNone(self.service.detail("alice", session["id"])["session"]["active_run_id"])

    def test_events_are_persistent_ordered_and_private(self):
        session = self.session()
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "开始", "client_message_id": "event-request-123"})
        self.repo.emit("alice", run["id"], "status", {"label": "检索"})
        self.repo.emit("alice", run["id"], "status", {"label": "生成"})
        self.assertEqual([e["seq"] for e in self.repo.events("alice", run["id"], 1)], [2])
        with self.assertRaises(AssistantNotFound):
            self.repo.events("bob", run["id"])

    def test_restart_recovery_leaves_waiting_questions_and_interrupts_active_runs(self):
        waiting = self.session()
        active = self.session()
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", active["id"], {"text": "开始", "client_message_id": "recover-request-123"})
        self.service.recover()
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "interrupted")
        self.assertIsNone(self.repo.get("alice", active["id"])["active_run_id"])
        self.assertEqual(self.repo.get("alice", waiting["id"])["status"], "ready")

    def test_http_ownership_and_catalog(self):
        app = FastAPI(); app.state.director_assistant = self.service
        register_assistant_routes(app, current_user=lambda: {"id": "bob"}, mutating_user=lambda: {"id": "bob"})
        session = self.session()
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/director-assistant/catalog").status_code, 200)
            self.assertEqual(client.get(f"/api/director-assistant/sessions/{session['id']}").status_code, 404)

    def test_full_text_workflow_commits_structured_assets_episodes_and_beats(self):
        script = self.draft()
        app = self.service.actions.preview("alice", script["id"], "p")
        self.service.actions.apply("alice", app["id"])
        assets = self.draft("assets", data={"assets": [{"kind": "character", "name": "悟空", "description": "识破替身"}, {"kind": "scene", "name": "古寺", "description": "雨夜"}]})
        asset_app = self.service.actions.preview("alice", assets["id"], "p")
        self.service.actions.apply("alice", asset_app["id"])
        char_id, scene_id = [row["target_id"] for row in asset_app["changes"]]
        outline = self.draft("episodes", data={"episodes": [{"episode_num": 1, "title": "真假", "summary": "古寺疑案"}]})
        outline_app = self.service.actions.preview("alice", outline["id"], "p")
        self.service.actions.apply("alice", outline_app["id"])
        episode_id = outline_app["changes"][0]["target_id"]
        board = self.draft("storyboard", data={"episodes": [{"episode_num": 1, "episode_id": episode_id, "title": "真假", "beats": [{"action": "悟空抬眼", "duration": 8, "character_ids": [char_id], "scene_id": scene_id, "prompt": "A rainy temple."}]}]})
        board_app = self.service.actions.preview("alice", board["id"], "p")
        self.service.actions.apply("alice", board_app["id"])
        with self.store.connection() as conn:
            episode = conn.execute("SELECT * FROM ai_project_episodes WHERE id=?", (episode_id,)).fetchone()
        beat = json.loads(episode["data_json"])["beats"][0]
        self.assertEqual(episode["shots_count"], 1)
        self.assertEqual(beat["character_ids"], [char_id])
        self.assertEqual(beat["scene_id"], scene_id)
        self.assertEqual(beat["duration_sec"], 8)
        self.assertEqual(beat["promptText"], "A rainy temple.")

    def test_storyboard_invalid_asset_reference_error_lists_catalog(self):
        assets = self.draft("assets", data={"assets": [{"kind": "prop", "name": "黑卡", "description": "金属卡"}]})
        asset_app = self.service.actions.preview("alice", assets["id"], "p")
        self.service.actions.apply("alice", asset_app["id"])
        board = self.draft("storyboard", data={"episodes": [{"episode_num": 1, "title": "真假", "beats": [
            {"action": "亮出卡片", "duration": 5, "character_ids": [], "scene_id": None,
             "prop_ids": ["asset-fa7c102d766c429b932928372214"]}]}]})
        with self.assertRaises(ValueError) as ctx:
            self.service.actions.preview("alice", board["id"], "p")
        message = str(ctx.exception)
        self.assertIn("道具 asset-fa7c102d766c429b932928372214", message)
        self.assertIn("黑卡", message)
        self.assertIn("有效资产", message)

    def test_message_sequence_is_stable_when_timestamps_are_identical(self):
        session = self.session()
        with patch("backend.app.director_assistant.repository.timestamp", return_value="2026-10-19T00:00:00Z"):
            detail = self.run_message(session, {"text": "回复"})
        self.assertEqual([m["role"] for m in detail["messages"]], ["user", "assistant"])
        self.assertEqual([m["sequence"] for m in detail["messages"]], [1, 2])

    def test_invalid_json_is_repaired_once_without_unvalidated_actions(self):
        session = self.session()
        self.llm.assistant_chat.side_effect = ["broken JSON", dumps({"text": "我们从人物开始。"})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "开始", "client_message_id": "repair-request-123"})
        self.service.run("alice", run["id"])
        self.assertEqual(self.llm.assistant_chat.call_count, 2)
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        self.assertEqual(self.repo.list("alice", "artifact"), [])

    def test_format_repair_cannot_claim_a_draft_was_created_without_tool(self):
        session = self.session()
        invalid = {"text": "准备草稿。", "tool_calls": [{"name": "create_draft", "arguments": {"artifact_type": "asset", "title": "角色", "content": "设定"}}]}
        self.llm.assistant_chat.side_effect = [dumps(invalid), dumps({"text": "资产草稿已提交，等待采纳。"})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "资产设定", "client_message_id": "repair-no-tool-123"})
        with self.assertLogs("backend.app.director_assistant.service", level="ERROR"):
            self.service.run("alice", run["id"])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "failed")
        self.assertEqual(self.repo.list("alice", "artifact"), [])
        reply = self.service.detail("alice", session["id"])["messages"][-1]
        self.assertNotIn("已提交", reply["parts"][-1]["text"])

    def test_format_repair_preserves_non_script_creation_action(self):
        session = self.session()
        invalid = {"text": "准备草稿。", "tool_calls": [{"name": "create_draft", "arguments": {"artifact_type": "asset", "title": "角色", "content": "设定"}}]}
        valid = {"text": "先查看这份设定。", "tool_calls": [{"name": "create_draft", "arguments": {"artifact_type": "assets", "title": "角色", "content": "悟空设定", "data": {"assets": [{"kind": "character", "name": "悟空"}]}}}]}
        self.llm.assistant_chat.side_effect = [dumps(invalid), dumps(valid)]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "资产设定", "client_message_id": "repair-keep-tool-123"})
        self.service.run("alice", run["id"])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        artifacts = self.repo.list("alice", "artifact")
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["artifact_type"], "assets")
        self.assertTrue(any("均未执行" in message["content"] for message in self.llm.assistant_chat.call_args.args[0]))

    def test_script_format_repair_cannot_fall_back_to_text_without_script_intent(self):
        session = self.session()
        invalid = dumps([{"type": "create_draft", "artifact_type": "script", "title": "雨夜回声", "content": 123}])
        self.llm.assistant_chat.side_effect = [invalid, dumps({"text": SCRIPT_TEXT})]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "先聊聊方向", "client_message_id": "script-repair-no-intent-123"})
        with self.assertLogs("backend.app.director_assistant.service", level="ERROR"):
            self.service.run("alice", run["id"])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "failed")
        self.assertEqual(self.repo.list("alice", "artifact"), [])

    def test_missing_tool_prerequisite_returns_to_conversation(self):
        session = self.session()
        self.llm.assistant_chat.side_effect = [
            dumps({"text": "先检查生图条件。", "tool_calls": [{"name": "propose_media", "arguments": {"title": "定妆", "media_type": "asset_image", "asset_id": "missing"}}]}),
            dumps({"text": "请先选择工程并采纳角色设定。"}),
        ]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "生图", "client_message_id": "missing-target-123"})
        self.service.run("alice", run["id"])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        self.assertEqual(self.repo.list("alice", "media_execution"), [])
        self.assertIn("error", self.repo.list("alice", "tool_call", parent=run["id"])[0]["result"])

    def test_long_stream_replaces_cumulative_text(self):
        session = self.session()
        text = "先把人物动机说清楚。" * 80
        detail = self.run_message(session, {"text": text})
        self.assertEqual(detail["messages"][-1]["parts"][0]["text"], text)
        events = self.repo.events("alice", detail["messages"][-1]["run_id"])
        previews = [e for e in events if e["event"] == "text"]
        self.assertTrue(previews)
        self.assertEqual(previews[-1]["data"]["text"], text)

    def test_selected_video_model_context_is_frozen_for_worker(self):
        from backend.app.director_assistant.model_context import model_scope
        from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
        from backend.app.media_studio.services.llm_service import LlmService
        row = {"enabled": True, "base_url": "http://localhost:1234/v1", "model": "default", "assistant_models_json": '["model-b"]'}
        with model_scope("model-b"), patch("backend.app.media_studio.services.llm_service.llm_row", return_value=row):
            self.assertEqual(LlmService._runtime_config()[1], "model-b")
            self.assertEqual(EpisodeVideoService.resolve_generation_options({})["assistant_model_id"], "model-b")
        self.assertNotIn("assistant_model_id", EpisodeVideoService.resolve_generation_options({}))

    def test_media_confirmation_blocks_other_project_mutations(self):
        with self.store.connection() as conn:
            conn.execute("INSERT INTO ai_project_assets (id,project_id,kind,name) VALUES ('hero','p','character','悟空')")
        session = self.session(project_id="p")
        proposal = self.service.actions.propose_media("alice", session, {"title": "定妆", "media_type": "asset_image", "asset_id": "hero"}, "r")
        with patch("backend.app.director_assistant.actions._MEDIA_EXECUTOR.submit"):
            self.service.actions.confirm_media("alice", proposal["id"])
        artifact = self.draft()
        with self.assertRaises(AssistantConflict):
            self.service.actions.preview("alice", artifact["id"], "p")

    def test_stale_media_target_must_be_reconfirmed(self):
        with self.store.connection() as conn:
            conn.execute("INSERT INTO ai_project_assets (id,project_id,kind,name) VALUES ('hero','p','character','悟空')")
        session = self.session(project_id="p")
        proposal = self.service.actions.propose_media("alice", session, {"title": "定妆", "media_type": "asset_image", "asset_id": "hero"}, "r")
        with self.store.connection() as conn:
            conn.execute("UPDATE ai_project_assets SET description='用户刚修改了造型' WHERE id='hero'")
        with patch("backend.app.director_assistant.actions._MEDIA_EXECUTOR.submit") as submit:
            with self.assertRaises(AssistantConflict):
                self.service.actions.confirm_media("alice", proposal["id"])
            submit.assert_not_called()

    def test_concurrent_media_confirmation_returns_one_execution(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        with self.store.connection() as conn:
            conn.execute("INSERT INTO ai_project_assets (id,project_id,kind,name) VALUES ('hero','p','character','悟空')")
        session = self.session(project_id="p")
        proposal = self.service.actions.propose_media("alice", session, {"title": "定妆", "media_type": "asset_image", "asset_id": "hero"}, "r")
        barrier, original_get = threading.Barrier(2), self.repo.get
        def synchronized_get(*args, **kwargs):
            result = original_get(*args, **kwargs)
            if args[1] == proposal["id"] and kwargs.get("conn") is None:
                barrier.wait(timeout=5)
            return result
        with patch.object(self.repo, "get", side_effect=synchronized_get), patch("backend.app.director_assistant.actions._MEDIA_EXECUTOR.submit") as submit, ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.service.actions.confirm_media("alice", proposal["id"]), range(2)))
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(submit.call_count, 1)

    def native_run(self, replies, *, capabilities=None, selections=None):
        from backend.app.llm_client import ChatResult
        caps = capabilities or {
            "provider": "dashscope", "native_tools": True, "structured_output": "json_schema",
            "prompt_cache": "explicit", "web_search": True, "usage_reporting": True, "degraded": [],
        }
        self.llm.assistant_capabilities.return_value = caps
        queue = list(replies)
        self.llm.assistant_chat_with_meta.side_effect = lambda messages, model_id, on_chunk=None, **kwargs: queue.pop(0)
        session = self.session(project_id="p", selections=selections or {})
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "帮我做西游悬疑故事", "client_message_id": "request-12345"})
        self.service.run("alice", run["id"])
        self.assertTrue(all(isinstance(reply, ChatResult) for reply in replies))
        return self.service.detail("alice", session["id"]), self.llm.assistant_chat_with_meta

    @staticmethod
    def native_call(name, **arguments):
        return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": dumps(arguments)}}

    def test_native_text_reply_skips_json_protocol(self):
        from backend.app.llm_client import ChatResult
        detail, caller = self.native_run([
            ChatResult(content="好的，我们从雨夜巷口开始。", usage={"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42}),
        ])
        message = detail["messages"][-1]
        self.assertEqual([part["text"] for part in message["parts"] if part["type"] == "markdown"], ["好的，我们从雨夜巷口开始。"])
        self.assertEqual([part["usage"]["total_tokens"] for part in message["parts"] if part["type"] == "usage"], [42])
        self.assertFalse(self.llm.assistant_chat.called)
        sent = caller.call_args.args[0]
        self.assertNotIn("只输出一个 JSON 对象", sent[0]["content"])
        self.assertTrue(caller.call_args.kwargs["tools"])
        self.assertTrue(caller.call_args.kwargs["enable_search"] is False)

    def test_native_read_tool_round_trips_tool_messages(self):
        from backend.app.llm_client import ChatResult
        detail, caller = self.native_run([
            ChatResult(tool_calls=[self.native_call("project_read", stage="script")]),
            ChatResult(content="工程内容已读取。"),
        ])
        self.assertEqual(caller.call_count, 2)
        messages = caller.call_args_list[1].args[0]
        assistant = next(message for message in messages if message["role"] == "assistant")
        self.assertEqual(assistant["tool_calls"][0]["id"], "call_project_read")
        tool_message = next(message for message in messages if message["role"] == "tool")
        self.assertEqual(tool_message["tool_call_id"], "call_project_read")
        self.assertTrue(tool_message["content"].startswith("{"))
        self.assertTrue(any(part["type"] == "tool" for part in detail["messages"][-1]["parts"]))

    def test_native_create_draft_finishes_with_artifact(self):
        from backend.app.llm_client import ChatResult
        detail, caller = self.native_run([
            ChatResult(content="剧本草稿已准备好。", tool_calls=[self.native_call(
                "create_draft", artifact_type="script", title="雨夜回声", content="# 雨夜回声\n\n场景一 巷口·夜·外\n林夏撑着黑伞。",
            )]),
        ])
        self.assertEqual(caller.call_count, 1)
        parts = detail["messages"][-1]["parts"]
        artifacts = [part for part in parts if part["type"] == "artifact"]
        self.assertEqual(len(artifacts), 1)
        artifact = next(item for item in detail["artifacts"] if item["id"] == artifacts[0]["artifact_id"])
        self.assertEqual(artifact["title"], "雨夜回声")

    def test_native_question_and_citations_are_extracted(self):
        raw, executable, _text = AssistantService._native_turn("", [
            self.native_call("ask_question", title="共几集", type="single", options=[{"label": "12集", "value": "12", "description": "标准短剧长度"}, {"label": "24集", "value": "24"}], allow_custom=True),
            self.native_call("cite_sources", chunk_ids=["chunk-1", "chunk-2"]),
            self.native_call("editor_read"),
        ])
        envelope = AssistantService._parse(raw)
        self.assertEqual(envelope.question.title, "共几集")
        self.assertEqual(envelope.question.options[0].description, "标准短剧长度")
        self.assertEqual(envelope.citation_ids, ["chunk-1", "chunk-2"])
        self.assertEqual([tool.name for tool in envelope.tool_calls], ["editor_read"])
        self.assertEqual([call["id"] for call in executable], ["call_editor_read"])

    def test_native_web_search_results_are_rendered(self):
        from backend.app.llm_client import ChatResult
        reply = ChatResult(content="今天有一则新消息。", usage={"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28})
        reply.extra["search_info"] = {"search_results": [
            {"title": "行业新闻", "url": "https://example.com/news", "site_name": "Example"},
            {"title": "重复来源", "url": "https://example.com/news", "site_name": "Example"},
        ]}
        detail, caller = self.native_run([reply], selections={"web_search": True})
        self.assertTrue(caller.call_args.kwargs["enable_search"])
        web = [part for part in detail["messages"][-1]["parts"] if part["type"] == "web_search"]
        self.assertEqual(len(web), 1)
        self.assertEqual(len(web[0]["results"]), 1)
        self.assertEqual(web[0]["results"][0]["url"], "https://example.com/news")

    def test_native_tools_degraded_restores_json_reply(self):
        from backend.app.llm_client import ChatResult
        detail, caller = self.native_run([
            ChatResult(content='{"text":"已改用兼容模式。","question":null,"tool_calls":[],"citation_ids":[]}', extra={"degraded": ["native_tools"]}),
        ])
        parts = detail["messages"][-1]["parts"]
        self.assertEqual([part["text"] for part in parts if part["type"] == "markdown"], ["已改用兼容模式。"])
        self.assertEqual(caller.call_count, 1)
        self.assertFalse(self.llm.assistant_chat.called)

    def test_native_capabilities_exposed_in_catalog(self):
        self.llm.assistant_model_catalog.return_value = [
            {"id": "model-a", "label": "model-a", "capabilities": {"web_search": True, "native_tools": True}},
        ]
        catalog = self.service.catalog("alice")
        self.assertTrue(catalog["models"][0]["capabilities"]["web_search"])


class AssistantModelSettingsTests(unittest.TestCase):
    def test_new_api_path_parameters_have_documentation(self):
        from backend.app.main import app
        schema = app.openapi()
        for path, methods in schema["paths"].items():
            if not path.startswith("/api/director-assistant/"):
                continue
            for operation in methods.values():
                if not isinstance(operation, dict):
                    continue
                for parameter in operation.get("parameters", []):
                    self.assertTrue(parameter.get("description"), (path, parameter["name"]))

    def test_old_settings_clients_preserve_allowlist(self):
        with tempfile.TemporaryDirectory() as root:
            store = JobStore(Path(root) / "settings.db")
            provider = LlmProviderService(store, None)
            provider.update({"base_url": "http://localhost:1234/v1", "model": "default", "assistant_models": ["a", "b"]})
            provider.update({"base_url": "http://localhost:1234/v1", "model": "default"})
            self.assertEqual(provider.assistant_models(), ["a", "b"])
            provider.update({"base_url": "http://localhost:1234/v1", "model": "default", "assistant_models": []})
            self.assertEqual(provider.assistant_models(), ["default"])
