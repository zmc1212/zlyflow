from __future__ import annotations

import copy
import json
import sqlite3
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.app.media_studio.services import script_development as story
from backend.app.media_studio.services import script_development_service as service
from backend.app.media_studio.services.director_story_design import pack_design
from backend.app.media_studio.services.prompt_expansion_service import PromptExpansionService
from backend.app.media_studio.services.prompt_templates import DIRECTOR_TEMPLATE_VERSION, PromptTemplateError
from backend.app.workflow_registry import WORKFLOWS


def plan():
    return {"title": "旧站来信", "mainline": "保安找到父亲留下的信", "ending": "主角选择公开真相", "locked_facts": ["父亲已故"],
            "characters": [{"name": "阿宁", "description": "夜班保安", "goal": "找父亲", "motivation": "化解误会"}],
            "episodes": [{"episode_num": i, "duration_seconds": 60, **{k: f"第{i}集{k}" for k in story.EPISODE_FIELDS}} for i in (1, 2)]}


def episode(n):
    return {"title": f"信的第{n}页", "summary": "信揭露隐情", "body": f"### 场景1｜车站·夜\n- 动作：阿宁打开第{n}页。\n- 台词：阿宁：原来如此。", "ending_state": f"手持第{n}页", "assets": {"props": [{"name": "信", "description": "父亲留下的信"}]}}


class StoryEngineTests(unittest.TestCase):
    @patch.object(story.LlmService, "chat_text", return_value='{"body":"第一行\n第二行"}')
    def test_literal_newline_json_preserves_story_text(self, chat):
        self.assertEqual(story.call_json("测试", {})["body"], "第一行\n第二行")

    @patch.object(story, "call_json", return_value={"issues": []})
    def test_duration_mismatch_is_visible_even_when_reviewer_misses_it(self, call):
        state = {"source": "原稿", "plan": plan(), "review_round": 2,
                 "episodes": [{**episode(n), "episode_num": n, "estimated_duration_seconds": 90 if n == 1 else 60} for n in (1, 2)]}
        story.develop_story(state, lambda _: None)
        self.assertEqual(state["unresolved_issues"][0]["category"], "duration_contract")
        self.assertIn("60 秒", state["unresolved_issues"][0]["evidence"])
        self.assertEqual(call.call_count, 1)

    def test_plan_rejects_missing_drama_and_nonfinite_duration(self):
        p = plan()
        p["episodes"][0]["duration_seconds"] = float("nan")
        with self.assertRaises(ValueError): story.validate_plan(p)
        p = plan(); p["episodes"][0]["obstacle"] = ""
        with self.assertRaises(ValueError): story.validate_plan(p)

    @patch.object(story, "call_json")
    def test_resume_skips_finished_episode_and_reviews_whole_series(self, call):
        state = {"source": "两集大纲", "plan": plan(), "episodes": [{**episode(1), "episode_num": 1}]}
        call.side_effect = [episode(2), {"issues": []}]
        snapshots = []
        story.develop_story(state, lambda s: snapshots.append(copy.deepcopy(s)))
        self.assertEqual(call.call_count, 2)
        self.assertEqual(len(call.call_args_list[1].args[1]["episodes"]), 2)
        self.assertEqual(state["phase"], "script_review")
        self.assertIn("# 第2集", state["script_text"])
        self.assertTrue(snapshots)

    @patch.object(story, "call_json")
    def test_only_two_repairs_then_preserves_unresolved_findings(self, call):
        issue = {"episode_num": 1, "category": "因果", "evidence": "未交代信来源", "suggestion": "补充来由"}
        state = {"source": "原稿", "plan": plan(), "episodes": [{**episode(n), "episode_num": n} for n in (1, 2)]}
        call.side_effect = [{"issues": [issue]}, episode(1), {"issues": [issue]}, episode(1), {"issues": [issue]}]
        story.develop_story(state, lambda _: None)
        self.assertEqual(call.call_count, 5)
        self.assertEqual(state["unresolved_issues"], [issue])

    @patch.object(story, "call_json")
    def test_targeted_revision_checks_other_episodes_without_rewriting_them(self, call):
        original = {**episode(2), "episode_num": 2}
        state = {"source": "原稿", "plan": plan(), "episodes": [{**episode(1), "episode_num": 1}, copy.deepcopy(original)], "revision_episodes": [1]}
        issue = {"episode_num": 2, "evidence": "前后连接待调整", "suggestion": "检查第二集"}
        call.side_effect = [episode(1), {"issues": [issue]}]
        story.develop_story(state, lambda _: None)
        self.assertEqual(state["episodes"][1], original)
        self.assertEqual(state["unresolved_issues"], [issue])

    @patch.object(story, "call_json")
    def test_failed_episode_keeps_checkpoint(self, call):
        state = {"source": "原稿", "plan": plan()}
        call.side_effect = [episode(1), RuntimeError("网络中断")]
        with self.assertRaises(RuntimeError): story.develop_story(state, lambda _: None)
        self.assertEqual(len(state["episodes"]), 1)


class AdoptionTests(unittest.TestCase):
    """Real SQLite transactions, no production database or external LLM calls."""
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE ai_project_documents(id TEXT, project_id TEXT, raw_text TEXT, analysis_json TEXT, status TEXT,updated_at TEXT);
        CREATE TABLE ai_project_episodes(id TEXT,project_id TEXT,data_json TEXT,updated_at TEXT);
        CREATE TABLE ai_project_jobs(id TEXT,project_id TEXT,status TEXT,progress INTEGER,payload_json TEXT,updated_at TEXT);
        """)
        self.db.execute("INSERT INTO ai_project_documents VALUES ('d','p','原始大纲','{}','ready','')")
        self.db.execute("INSERT INTO ai_project_episodes VALUES ('e','p',?, '')", (json.dumps({"source_document_id": "d", "production": {"url": "existing.mp4"}}),))
        self.db.execute("INSERT INTO ai_project_jobs VALUES ('j','p','awaiting_review',0,'{}','')")
        self.db.commit()
        db = self.db
        class Cursor:
            def execute(self, sql, args=()): self.result = db.execute(sql.replace("%s", "?"), args); return self.result.rowcount
            @property
            def rowcount(self): return self.result.rowcount
            def fetchall(self): return [dict(x) for x in self.result.fetchall()]
        @contextmanager
        def transaction():
            try: yield Cursor(); db.commit()
            except Exception: db.rollback(); raise
        self.patches = [patch.object(service, "query_one", lambda sql, args=(): dict(db.execute(sql.replace("%s", "?"), args).fetchone())), patch.object(service, "transaction_cursor", transaction)]
        for p in self.patches: p.start()
    def tearDown(self):
        for p in self.patches: p.stop()
        self.db.close()
    def data(self):
        row = service.ScriptDevelopmentService.document("p", "d")
        return {"plan": plan(), "script_text": story.render_script(plan(), [{**episode(i), "episode_num": i} for i in (1, 2)]),
                "source_fingerprint": service.ScriptDevelopmentService.fingerprint(row), "episodes": [episode(1), episode(2)]}
    def test_adoption_retains_original_and_media_and_marks_only_linked_episodes(self):
        data = self.data()
        service.ScriptDevelopmentService.apply("p", "d", "j", data)
        row = service.ScriptDevelopmentService.document("p", "d")
        self.assertEqual(row["raw_text"], "原始大纲")
        accepted = json.loads(row["analysis_json"])
        self.assertEqual(accepted["script_development"]["revision"], 1)
        self.assertEqual(accepted["props"][0]["name"], "信")
        ep = json.loads(self.db.execute("SELECT data_json FROM ai_project_episodes").fetchone()[0])
        self.assertEqual(ep["production"]["url"], "existing.mp4")
        self.assertEqual(ep["script_stale"]["revision"], 1)
    def test_source_conflict_prevents_old_draft_adoption(self):
        data = self.data()
        self.db.execute("UPDATE ai_project_documents SET raw_text='新原稿'"); self.db.commit()
        with self.assertRaisesRegex(ValueError, "SOURCE_CONFLICT"):
            service.ScriptDevelopmentService.apply("p", "d", "j", data)
        self.assertEqual(self.db.execute("SELECT analysis_json FROM ai_project_documents").fetchone()[0], "{}")


def design_fixture():
    beats = [{"id": f"b{i}", "sequence": i, "action": f"阿宁翻到第{i}页。", "video_duration": 4} for i in range(1, 5)]
    facts = PromptExpansionService._build_source_facts(beats)
    units = []
    for i, beat in enumerate(beats):
        scene = "车站·夜" if i < 2 else "家中·晨"
        units.append({"source_beat_id": beat["id"], "event_ids": [facts[beat["id"]]["events"][0]["id"]], "dialogue_ids": [],
                      "duration_seconds": 4, "start_state": "坐着持信", "handoff_state": "坐着持信", "scene_key": scene,
                      "transition_type": "cut" if i in (0, 2) else "continuous", "shot_size": "近景", "camera": "平视", "movement": "固定", "performance": "翻页后凝视", "dialogue_timing": "无对白", "purpose": f"第{i+1}个发现"})
    return beats, facts, {"dramatic_intent": "秘密逐步揭示", "visual_strategy": "让信与表情交替成为主体", "common_setting": {"subject_definitions": "阿宁身着蓝色制服。"}, "units": units}


class DirectorStoryDesignTests(unittest.TestCase):
    definition = SimpleNamespace(max_segments=6, max_total_frames=1152)
    def test_dialogue_cannot_be_forced_into_an_unplayable_short_unit(self):
        beats, _, design = design_fixture()
        beats[0]["dialogue"] = "阿宁：" + "我必须把父亲留下的证据公之于众。" * 6
        facts = PromptExpansionService._build_source_facts(beats)
        design["units"][0]["dialogue_ids"] = [x["id"] for x in facts["b1"]["dialogues"]]
        with self.assertRaisesRegex(PromptTemplateError, "对白.*演完"):
            pack_design(design, beats, facts, self.definition, 24)

    def test_scene_changes_create_separate_parts_without_false_continuity(self):
        beats, facts, design = design_fixture()
        parts = pack_design(design, beats, facts, self.definition, 24)
        self.assertEqual([len(p["segments"]) for p in parts], [2, 2])
        self.assertFalse(parts[1]["segments"][0]["continuity_from_prev"])
        self.assertEqual(sum(p["frame_count"] for p in parts), 16 * 24)
    def test_short_scene_does_not_invent_filler(self):
        beats, facts, design = design_fixture()
        design["units"][1]["scene_key"] = "走廊·夜"
        with self.assertRaisesRegex(PromptTemplateError, "逐镜"):
            pack_design(design, beats, facts, self.definition, 24)
    def test_changed_state_and_duplicate_events_rejected(self):
        beats, facts, design = design_fixture()
        design["units"][1]["start_state"] = "站立空手"
        with self.assertRaisesRegex(PromptTemplateError, "开场状态"):
            pack_design(design, beats, facts, self.definition, 24)
        design["units"][1]["start_state"] = "坐着持信"
        design["units"][0]["event_ids"] *= 2
        with self.assertRaisesRegex(PromptTemplateError, "各分配一次"):
            pack_design(design, beats, facts, self.definition, 24)
    def test_persistent_state_is_not_a_one_time_event(self):
        facts = PromptExpansionService._build_source_facts([{"id": "b", "action": "光线：暖黄。阿宁开信。收束：坐着持信。", "camera": "固定"}])["b"]
        self.assertEqual([x["text"] for x in facts["events"]], ["阿宁开信。"])
        self.assertEqual(len(facts["persistent_states"]), 2)

    @patch("backend.app.media_studio.services.script_development.call_json", return_value={"issues": []})
    @patch("backend.app.media_studio.services.llm_service.LlmService.chat_text")
    def test_complete_new_preview_locks_setting_and_compiles_scene_cuts(self, chat, review):
        beats, facts, design = design_fixture()
        workflow = next(w for w in WORKFLOWS if w.prompt_profile == "director_segments")
        parts = pack_design(design, beats, facts, workflow, 24)
        outputs = [json.dumps(design, ensure_ascii=False)]
        for part in parts:
            outputs.append(json.dumps({"common_setting": {"subject_definitions": "不应采用模型再次改写的公共设定"}, "segments": [
                {"segment_id": seg["id"], "unit_ids": [seg["source_units"][0]["id"]], "summary": seg["title"], "retention_analysis": "保持人物服装与场景关系。", "detailed_description": "00:00 画面保持近景，注意力落在指尖细微停顿，最终保持可接续姿势。", "overall_soundscape": "纸张摩擦声清晰。", "non_diegetic_music": "克制的低音持续。"} for seg in part["segments"]]}, ensure_ascii=False))
        chat.side_effect = outputs
        request = {"workflow_id": workflow.id, "template_version": DIRECTOR_TEMPLATE_VERSION, "language": "zh-CN", "story_design": True, "aspect_ratio": "16:9", "reference_slots": [], "rewrite_mode": "expand", "target_segment_count": None}
        payload = {"source_snapshot": {"episode": {"script_text": "来信"}, "beats": beats, "assets": []}, "source_facts": facts}
        preview = PromptExpansionService._generate_director_preview(payload, request)
        self.assertEqual(preview["actual_segment_count"], 4)
        self.assertEqual(preview["common_setting"]["subject_definitions"], design["common_setting"]["subject_definitions"])
        self.assertEqual(preview["quality_status"], "reviewed")
        self.assertNotIn("无硬切", preview["parts"][1]["segments"][0]["sections"]["detailed_description"])
        self.assertIn("已锁定公共设定", chat.call_args_list[2].args[1])
        self.assertEqual(review.call_count, 1)
        # Exercise the saved preview through adoption and video dispatch, including
        # neighbouring episode context in the optimistic source check.
        from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
        request["target"] = {"kind": "director_episode"}
        episode_row = {"id": "e2", "episode_num": 2, "title": "来信", "script_text": "来信", "data_json": json.dumps({"beats": beats})}
        neighbors = [{"episode_num": 3, "title": "后集", "script_text": "兑现"}, {"episode_num": 1, "title": "前集", "script_text": "伏笔"}]
        source = {"episode": episode_row, "data": {"beats": beats}, "beats": beats, "assets": [], "adjacent_episodes": neighbors}
        fingerprint = PromptExpansionService.source_fingerprint(source, request)
        preview["source_fingerprint"] = fingerprint
        # The direct generation fixture attaches provenance after generation.
        from backend.app.media_studio.services.director_plan_quality import content_digest
        preview["reviewed_content_digest"] = content_digest(preview)
        job = {"job_type": "prompt_expansion", "status": "completed", "payload_json": json.dumps({"episode_id": "e2", "request": request, "preview": preview, "source_fingerprint": fingerprint, "validation_status": "valid"})}

        class Cursor:
            def execute(self, sql, args): self.sql = sql
            def fetchone(self): return episode_row
            def fetchall(self): return list(reversed(neighbors)) if "episode_num" in self.sql else []

        @contextmanager
        def transaction(): yield Cursor()

        with patch("backend.app.media_studio.services.prompt_expansion_service.query_one", return_value=job), patch("backend.app.media_studio.services.prompt_expansion_service.transaction_cursor", transaction):
            adopted = PromptExpansionService.apply_preview("p", "e2", "j")
            shots, saved_plan, _ = EpisodeVideoService._director_plan_shots({"prompt_authoring": adopted["prompt_authoring"]}, {})
            self.assertEqual(saved_plan["schema_version"], 4)
            self.assertEqual([s["prompt"] for s in shots], [s["prompt_text"] for p in preview["parts"] for s in p["segments"]])
            neighbors[0]["script_text"] = "后集已经修改"
            with self.assertRaisesRegex(RuntimeError, "SOURCE_CONFLICT"):
                PromptExpansionService.apply_preview("p", "e2", "j")


class AiStoryDevelopmentIntegrationTests(unittest.TestCase):
    def test_script_stage_uses_shared_document_job_and_stops_for_review(self):
        from backend.app.media_studio.services.ai_generation_service import AiGenerationService
        ai = AiGenerationService(Mock())
        ai._check_cancelled = Mock()
        ai._update = Mock()
        ai._emit = Mock()
        payload = {"script_development_version": 1}
        with patch("backend.app.media_studio.services.ai_generation_service.ProjectDetailService.create_document", return_value={"id": "doc-new"}), patch.object(service.ScriptDevelopmentService, "start") as start:
            ai._run_stage_leg("op", payload, {"project_id": "p", "goal": "一句大纲"}, "script")
        self.assertEqual(payload["script_development_document_id"], "doc-new")
        self.assertEqual(payload["awaiting_stage"], "script")
        start.assert_called_once()
        ai.llm_provider.run_director_recipe.assert_not_called()

    def test_newer_adopted_script_blocks_downstream_generation(self):
        from backend.app.media_studio.services.ai_generation_service import AiGenerationService
        ai = AiGenerationService(Mock())
        ai._check_cancelled = Mock()
        with patch.object(service.ScriptDevelopmentService, "document", return_value={"analysis_json": json.dumps({"script_development": {"revision": 2}})}):
            with self.assertRaisesRegex(ValueError, "SOURCE_CONFLICT"):
                ai._run_stage_leg("op", {"script_development_document_id": "doc", "adopted_script_revision": 1}, {"project_id": "p"}, "assets")
        ai.llm_provider.run_director_recipe.assert_not_called()


class StoryActionGateTests(unittest.TestCase):
    def test_complete_original_can_be_kept_without_expansion(self):
        data = {"phase": "plan_review", "source": "# 完整剧本\n原场景与对白", "plan": plan(), "source_fingerprint": "source"}
        job = {"status": "awaiting_review", "data": data}
        with patch.object(service.ScriptDevelopmentService, "get", return_value=job), patch.object(service.ScriptDevelopmentService, "check_source"), patch.object(service.ScriptDevelopmentService, "apply") as apply:
            service.ScriptDevelopmentService.action("p", "d", "j", {"action": "keep_original", "revision": story.digest(data)})
        kept = apply.call_args.args[3]
        self.assertEqual(kept["script_text"], data["source"])
        self.assertEqual(kept["episodes"], [])
        self.assertTrue(kept["kept_original"])

    def test_stale_browser_revision_cannot_confirm_a_plan(self):
        data = {"phase": "plan_review", "plan": plan()}
        with patch.object(service.ScriptDevelopmentService, "get", return_value={"status": "awaiting_review", "data": data}), patch.object(service.ScriptDevelopmentService, "check_source"), patch.object(service.ScriptDevelopmentService, "save") as save:
            with self.assertRaisesRegex(ValueError, "VERSION_CONFLICT"):
                service.ScriptDevelopmentService.action("p", "d", "j", {"action": "confirm_plan", "revision": "old"})
        save.assert_not_called()


if __name__ == "__main__": unittest.main()
