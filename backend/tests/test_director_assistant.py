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
from backend.app.director_assistant.protocol import AssistantTurn
from backend.app.director_assistant.repository import AssistantConflict, AssistantNotFound, dumps
from backend.app.director_assistant.routes import register_assistant_routes
from backend.app.director_assistant.service import AssistantService
from backend.app.director_assistant.resources import ResourceService
from backend.app.llm_provider import LlmProviderService
from backend.app.storage import JobStore


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

    def run_message(self, session, envelope):
        self.llm.assistant_chat.side_effect = lambda messages, model, callback=None: self.reply(envelope, callback)
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "帮我做西游悬疑故事", "client_message_id": "request-12345"})
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

    def test_model_not_in_allowlist_rejected(self):
        with self.assertRaises(ValueError):
            self.session(selections={"model_id": "private-model"})

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

    def test_generation_creates_draft_without_project_write(self):
        session = self.session(project_id="p")
        detail = self.run_message(session, {"text": "剧本已写好，先看看。", "tool_calls": [{"name": "create_draft", "arguments": {"artifact_type": "script", "title": "西游悬疑", "content": "# 西游悬疑\n完整故事。", "data": {"summary": "悬疑"}}}]})
        self.assertEqual(len(detail["artifacts"]), 1)
        with self.store.connection() as conn:
            self.assertEqual(len(conn.execute("SELECT * FROM ai_project_documents").fetchall()), 0)

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

    def test_format_repair_keeps_the_original_creation_action(self):
        session = self.session()
        invalid = {"text": "准备草稿。", "tool_calls": [{"name": "create_draft", "arguments": {"artifact_type": "asset", "title": "角色", "content": "设定"}}]}
        valid = {"text": "先查看这份设定。", "tool_calls": [{"name": "create_draft", "arguments": {"artifact_type": "assets", "title": "角色", "content": "悟空设定", "data": {"assets": [{"kind": "character", "name": "悟空"}]}}}]}
        self.llm.assistant_chat.side_effect = [dumps(invalid), dumps(valid)]
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "资产设定", "client_message_id": "repair-keep-tool-123"})
        self.service.run("alice", run["id"])
        self.assertEqual(self.repo.get("alice", run["id"])["status"], "succeeded")
        self.assertEqual(len(self.repo.list("alice", "artifact")), 1)
        self.assertTrue(any("均未执行" in message["content"] for message in self.llm.assistant_chat.call_args.args[0]))

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
