from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import json
import unittest
from unittest.mock import Mock, patch

from backend.app.media_studio.services import director_plan_quality as quality
from backend.app.media_studio.services import prompt_expansion_service as pipeline
from backend.app.media_studio.services.director_story_design import pack_design
from backend.app.media_studio.services.prompt_templates import DIRECTOR_TEMPLATE_VERSION, DIRECTOR_UNIT_PLANNER_VERSION, PromptTemplateError
from backend.app.workflow_registry import WORKFLOWS
from backend.tests.media_studio_test_script_development import design_fixture

Service = pipeline.PromptExpansionService
# These fixtures have no reference images; catalogue ordering is not a route contract.
WORKFLOW = next(w for w in WORKFLOWS if w.prompt_profile == "director_segments" and w.min_references == 0)


def fixture():
    beats, facts, design = design_fixture()
    parts = pack_design(design, beats, facts, WORKFLOW, 24)
    for part in parts:
        for seg in part["segments"]:
            unit = seg["source_units"][0]
            seg["shots"] = [{"shot_number": unit["generated_shot_number"], "source_beat_id": unit["source_beat_id"]}]
            sections = {"summary": seg["title"], "retention_analysis": "保持人物与服装一致。", "detailed_description": "00:00 指尖略作停顿，目光落在纸面。",
                        "overall_soundscape": "纸张轻响。", "non_diegetic_music": "低音轻奏。"}
            group = Service._compile_director_groups([seg], [{"sections": sections}], "zh")[0]
            seg.update(sections=group["sections"], prompt_text=group["prompt_text"])
    plan = {"id": "plan-1", "revision": 1, "kind": "director_segments", "schema_version": 4, "planning_strategy": "atomic_units",
            "workflow_id": WORKFLOW.id, "template_version": DIRECTOR_TEMPLATE_VERSION, "unit_planner_version": DIRECTOR_UNIT_PLANNER_VERSION,
            "language": "zh", "rewrite_mode": "expand", "aspect_ratio": "16:9", "target_segment_count": None,
            "parts": parts, "director_design": design, "source_facts": facts, "reference_slots": [], "status": "current", "validation_status": "valid",
            "common_setting": {"subject_definitions": "阿宁身着蓝色制服。", "prompt_text": "主体定义: 阿宁身着蓝色制服。"}}
    source = {"episode": {"id": "ep", "episode_num": 1, "script_text": "来信"}, "beats": beats, "assets": [], "data": {"beats": beats}}
    req = {k: plan[k] for k in ("workflow_id", "template_version", "unit_planner_version", "language", "rewrite_mode", "aspect_ratio", "reference_slots", "target_segment_count")}
    req.update(target={"kind": "director_episode"}, story_design=True, prompt_profile="director_segments")
    plan["source_fingerprint"] = Service.source_fingerprint(source, req)
    return plan, source, req


def issue(criterion="camera", sid="story-segment-1", scope="creative"):
    return {"id": f"{sid}:{criterion}", "segment_id": sid, "criterion": criterion,
            "severity": "blocking", "repair_scope": scope, "evidence": "固定机位与推镜冲突。", "suggestion": "只保留固定机位。"}


def changed(plan, *_args):
    result = deepcopy(plan)
    result["parts"][0]["segments"][0]["prompt_text"] += "新细节"
    return result


class QualityTests(unittest.TestCase):
    def test_preflight_rejects_short_dialogue_before_any_job_or_llm_call(self):
        plan, source, req = fixture()
        source["beats"][0]["dialogue"] = "阿宁：" + "请将这封信交给值班的站长。" * 3
        with patch.object(Service, "_load_source", return_value=source), patch.object(pipeline, "execute_sql") as sql, patch.object(pipeline.LlmService, "chat_text") as llm:
            with self.assertRaises(pipeline.PromptPipelineError) as caught:
                Service.enqueue("p", "ep", req)
        self.assertEqual(caught.exception.stage, "preflight")
        self.assertFalse(caught.exception.retryable)
        self.assertIn("分镜仅 4 秒", str(caught.exception))
        sql.assert_not_called()
        llm.assert_not_called()

    def test_preflight_single_scene_and_multiple_errors_are_explained(self):
        beats = [{"id": "a", "scene": "车站·夜", "action": "拿信。", "video_duration": 4},
                 {"id": "b", "scene": "家中·晨", "action": "坐下。", "video_duration": -1}]
        issues = quality.preflight(beats, Service._build_source_facts(beats), WORKFLOW)
        self.assertIn("INVALID_DURATION", [x["code"] for x in issues])
        self.assertEqual(2, sum(x["code"] == "SINGLE_UNIT_SCENE" for x in issues))

    def test_preflight_does_not_guess_unknown_scene_boundaries(self):
        _, source, _ = fixture()
        self.assertEqual([], quality.preflight(source["beats"], Service._build_source_facts(source["beats"]), WORKFLOW))

    def test_structural_retry_stops_when_same_error_repeats(self):
        with patch.object(pipeline.LlmService, "chat_text", return_value="bad") as llm:
            with self.assertRaises(pipeline.PromptPipelineError) as caught:
                Service._generate_with_one_retry("system", "source", Mock(side_effect=PromptTemplateError("重复问题")), max_repairs=2)
        self.assertEqual(2, llm.call_count)
        self.assertFalse(caught.exception.retryable)

    def test_review_repairs_only_failed_segments_and_rechecks_resolved_issues(self):
        plan, source, _ = fixture()
        first, second = issue(), issue("performance", "story-segment-2")
        with patch.object(quality, "review_plan", side_effect=[{"issues": [first, second]}, {"issues": [second]}, {"issues": []}]) as review, patch.object(quality, "repair_segments", side_effect=changed) as repair:
            result = quality.improve_plan(plan, source)
        self.assertEqual("completed", result["revision_stop_reason"])
        self.assertEqual(["story-segment-2"], repair.call_args_list[1].args[-1])
        self.assertIn(first, review.call_args_list[2].args[-1])
        self.assertEqual(2, len([h for h in result["revision_history"] if h["status"] == "accepted"]))
        self.assertNotIn("quality_version", plan)

    def test_regression_discards_candidate_and_stops(self):
        plan, source, _ = fixture()
        with patch.object(quality, "review_plan", side_effect=[{"issues": [issue()]}, {"issues": [issue("continuity")]}]), patch.object(quality, "repair_segments", side_effect=changed) as repair:
            result = quality.improve_plan(plan, source)
        self.assertEqual("no_progress", result["revision_stop_reason"])
        self.assertEqual(plan["parts"], result["parts"])
        self.assertEqual(1, repair.call_count)
        self.assertEqual(["story-segment-1:continuity"], result["revision_history"][-1]["new"])

    def test_planning_conflicts_do_not_trigger_pointless_prose_rewrites(self):
        plan, source, _ = fixture()
        with patch.object(quality, "review_plan", return_value={"issues": [issue("timing", scope="planning")]}), patch.object(quality, "repair_segments") as repair:
            result = quality.improve_plan(plan, source)
        repair.assert_not_called()
        self.assertEqual("planning_required", result["revision_stop_reason"])
        with self.assertRaisesRegex(ValueError, "阻断"):
            quality.assert_ready_for_video(result)

    def test_invalid_user_patch_keeps_request_unresolved(self):
        plan, source, _ = fixture()
        with patch.object(quality, "review_plan", return_value={"issues": []}), patch.object(quality, "repair_segments", side_effect=PromptTemplateError("试图修改对白")):
            result = quality.improve_plan(plan, source, feedback="镜头只推进一次", targets=["story-segment-1"])
        self.assertEqual("invalid_patch", result["revision_stop_reason"])
        self.assertEqual("镜头只推进一次", result["revision_requirements"][0]["feedback"])
        with self.assertRaisesRegex(ValueError, "阻断"):
            quality.assert_ready_for_video(result)

    def test_checkpoint_resume_does_not_repeat_successful_repairs(self):
        plan, source, _ = fixture()
        saved = []
        with patch.object(quality, "review_plan", side_effect=[{"issues": [issue()]}, {"issues": []}]), patch.object(quality, "repair_segments", side_effect=changed):
            result = quality.improve_plan(plan, source, save=lambda s: saved.append(deepcopy(s)))
        with patch.object(quality, "review_plan") as review, patch.object(quality, "repair_segments") as repair:
            resumed = quality.improve_plan(plan, source, state=saved[-1])
        self.assertEqual(result, resumed)
        review.assert_not_called()
        repair.assert_not_called()

    def test_network_interruption_reuses_pending_candidate_instead_of_rewriting(self):
        plan, source, _ = fixture()
        saved = []
        with patch.object(quality, "review_plan", side_effect=[{"issues": [issue()]}, ConnectionError("network")]), patch.object(quality, "repair_segments", side_effect=changed):
            with self.assertRaises(ConnectionError):
                quality.improve_plan(plan, source, save=lambda s: saved.append(deepcopy(s)))
        self.assertIn("pending_review", saved[-1])
        with patch.object(quality, "review_plan", return_value={"issues": []}), patch.object(quality, "repair_segments") as repair:
            result = quality.improve_plan(plan, source, state=saved[-1])
        repair.assert_not_called()
        self.assertEqual("completed", result["revision_stop_reason"])

    def test_refused_candidate_does_not_hide_previously_resolved_issues(self):
        plan, source, _ = fixture()
        a, b = issue(), issue("performance", "story-segment-2")
        with patch.object(quality, "review_plan", side_effect=[{"issues": [a, b]}, {"issues": [b]}, {"issues": [a]}]), patch.object(quality, "repair_segments", side_effect=changed):
            result = quality.improve_plan(plan, source)
        self.assertEqual("no_progress", result["revision_stop_reason"])
        self.assertEqual([b], result["creative_review"]["issues"])
        self.assertEqual("accepted", result["revision_history"][1]["status"])
        self.assertEqual("rejected", result["revision_history"][2]["status"])

    def test_new_plans_need_current_review_but_advisory_and_legacy_plans_can_render(self):
        plan, source, _ = fixture()
        quality.assert_ready_for_video(plan)
        advisory = {**issue(), "severity": "advisory"}
        with patch.object(quality, "review_plan", return_value={"issues": [advisory]}):
            result = quality.improve_plan(plan, source)
        quality.assert_ready_for_video(result)
        result["parts"][0]["segments"][0]["prompt_text"] += "手动修改"
        with self.assertRaisesRegex(ValueError, "复验"):
            quality.assert_ready_for_video(result)

    def test_actual_patch_preserves_unselected_segments_and_immutable_unit_data(self):
        plan, source, _ = fixture()
        segment = plan["parts"][0]["segments"][0]
        unit = segment["source_units"][0]
        response = {"segments": [{"segment_id": segment["id"], "unit_ids": [unit["id"]],
            "unit_designs": [{"unit_id": unit["id"], "movement": "缓慢推进"}],
            **{**segment["sections"], "detailed_description": "00:00 纸面保持清晰，指尖轻微停顿。"}}]}
        with patch.object(pipeline.LlmService, "chat_text", return_value=json.dumps(response, ensure_ascii=False)):
            result = quality.repair_segments(plan, source, [issue()], [], [segment["id"]])
        Service.validate_director_plan(result)
        updated = result["parts"][0]["segments"][0]["source_units"][0]
        self.assertEqual("缓慢推进", updated["movement"])
        self.assertEqual({k: v for k, v in unit.items() if k != "movement"}, {k: v for k, v in updated.items() if k != "movement"})
        self.assertEqual(plan["parts"][0]["segments"][1], result["parts"][0]["segments"][1])
        self.assertEqual(plan["parts"][1], result["parts"][1])
        response["segments"][0]["unit_designs"][0]["duration_seconds"] = 9
        with patch.object(pipeline.LlmService, "chat_text", return_value=json.dumps(response, ensure_ascii=False)):
            with self.assertRaisesRegex(PromptTemplateError, "锁定字段"):
                quality.repair_segments(plan, source, [], [], [segment["id"]])

    def test_review_rejects_unknown_segment_and_normalizes_stable_issue_ids(self):
        plan, source, _ = fixture()
        with patch("backend.app.media_studio.services.script_development.call_json", return_value={"issues": [issue()]}):
            review = quality.review_plan(plan, source, [], [])
        self.assertEqual("story-segment-1:camera", review["issues"][0]["id"])
        with patch("backend.app.media_studio.services.script_development.call_json", return_value={"issues": [issue(sid="unknown")]}):
            with self.assertRaises(PromptTemplateError):
                quality.review_plan(plan, source, [], [])


class RevisionServiceTests(unittest.TestCase):
    def test_job_worker_persists_new_revision_and_final_review_checkpoint(self):
        plan, source, req = fixture()
        payload = {"episode_id": "ep", "request": req, "source_snapshot": source, "revision_base": plan,
                   "revision_request": {"feedback": "减少重复运镜", "segment_ids": ["story-segment-1"]}, "checkpoints": {}}
        row = {"payload_json": json.dumps(payload), "status": "queued"}
        def execute(sql, args):
            if "payload_json=%s" in sql:
                row["payload_json"] = args[0] if "status='failed'" not in sql else args[1]
            if "status='completed'" in sql:
                row["status"] = "completed"
            if "status='failed'" in sql:
                row["status"] = "failed"
        with patch.object(pipeline, "query_one", side_effect=lambda *a: deepcopy(row)), patch.object(pipeline, "execute_sql", side_effect=execute), patch.object(Service, "kick"), patch.object(quality, "review_plan", return_value={"issues": []}), patch.object(quality, "repair_segments", side_effect=changed):
            Service._run("j")
        self.assertEqual("completed", row["status"])
        completed = json.loads(row["payload_json"])
        self.assertEqual(2, completed["preview"]["revision"])
        self.assertNotEqual(plan["id"], completed["preview"]["id"])
        self.assertEqual(plan, completed["revision_base"])
        self.assertTrue(completed["checkpoints"]["quality_revision"]["done"])
        quality.assert_ready_for_video(completed["preview"])

    def test_saved_plan_revision_is_queued_without_overwriting_source(self):
        plan, source, _ = fixture()
        source["data"]["prompt_authoring"] = {"director_plan": plan}
        request = {"expected_plan_id": plan["id"], "expected_revision": 1, "feedback": "固定镜头", "segment_ids": ["story-segment-1"]}
        with patch.object(Service, "_load_source", return_value=source), patch.object(pipeline, "query_all", return_value=[]), patch.object(pipeline, "execute_sql") as sql, patch.object(Service, "kick"):
            result = Service.revise("p", "ep", request)
        self.assertEqual("queued", result["status"])
        payload = json.loads(sql.call_args.args[1][4])
        self.assertEqual(plan, payload["revision_base"])
        self.assertEqual(quality.content_digest(plan), payload["revision_request"]["saved_base_digest"])
        self.assertEqual(1, sql.call_count)

    def test_stale_base_and_changed_source_cannot_enqueue(self):
        plan, source, _ = fixture()
        source["data"]["prompt_authoring"] = {"director_plan": plan}
        req = {"expected_plan_id": plan["id"], "expected_revision": 99, "feedback": "固定镜头", "segment_ids": ["story-segment-1"]}
        with patch.object(Service, "_load_source", return_value=source), patch.object(pipeline, "execute_sql") as sql:
            with self.assertRaisesRegex(RuntimeError, "REVISION_CONFLICT"):
                Service.revise("p", "ep", req)
            req["expected_revision"] = 1
            source["beats"][0]["action"] = "新剧情。"
            with self.assertRaisesRegex(RuntimeError, "SOURCE_CHANGED"):
                Service.revise("p", "ep", req)
        sql.assert_not_called()

    def test_foreign_episode_preview_cannot_be_used(self):
        plan, source, _ = fixture()
        row = {"job_type": pipeline.JOB_TYPE, "status": "completed", "payload_json": json.dumps({"episode_id": "other", "preview": plan})}
        with patch.object(Service, "_load_source", return_value=source), patch.object(pipeline, "query_one", return_value=row):
            with self.assertRaisesRegex(ValueError, "本集"):
                Service.revise("p", "ep", {"base_job_id": "j"})

    def test_apply_does_not_overwrite_plan_changed_during_revision(self):
        plan, source, req = fixture()
        source["data"]["prompt_authoring"] = {"director_plan": plan}
        row = {**source["episode"], "data_json": json.dumps(source["data"])}
        payload = {"episode_id": "ep", "preview": plan, "request": req, "source_fingerprint": plan["source_fingerprint"], "validation_status": "valid",
                   "revision_request": {"saved_base_digest": "previous-version"}}
        job = {"job_type": pipeline.JOB_TYPE, "status": "completed", "payload_json": json.dumps(payload)}
        cursor = Mock()
        cursor.fetchone.return_value = row
        cursor.fetchall.return_value = []
        @contextmanager
        def transaction(): yield cursor
        with patch.object(pipeline, "query_one", return_value=job), patch.object(pipeline, "transaction_cursor", transaction):
            with self.assertRaisesRegex(RuntimeError, "REVISION_CONFLICT"):
                Service.apply_preview("p", "ep", "j")
        self.assertFalse(any(c.args[0].lstrip().startswith("UPDATE") for c in cursor.execute.call_args_list))


if __name__ == "__main__":
    unittest.main()
