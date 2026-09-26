from copy import deepcopy
import json
import time
import unittest
from unittest.mock import patch, MagicMock

from backend.app.media_studio.services import director_reliable as reliable
from backend.app.media_studio.services import prompt_expansion_service as pipeline
from backend.app.media_studio.services.director_story_design import pack_design
from backend.app.media_studio.services.director_plan_quality import assert_ready_for_video, content_digest, review_plan
from backend.tests.media_studio_test_director_quality import fixture, WORKFLOW
from backend.app.media_studio.services.episode_video_service import EpisodeVideoService as Video
from backend.app.media_studio.services import episode_video_service as video_module
from backend.app.media_studio.services import production_state
from backend.app.media_studio.services.timeline_rendering import frame_count, duration_seconds

Service = pipeline.PromptExpansionService


class ShotPlanningCompletenessTests(unittest.TestCase):
    def test_truncated_outer_json_never_accepts_first_nested_shot(self):
        from backend.app.media_studio.services.episode_shot_planner import parse_shot_plan_response
        with self.assertRaisesRegex(ValueError, "JSON 不完整"):
            parse_shot_plan_response('{"shots":[{"action":"拿信","duration_sec":10},{"action":"')

    def test_explicit_scenes_have_isolated_source_and_preserve_total_budget(self):
        from backend.app.media_studio.services.episode_shot_planner import shot_plan_scene_batches
        episode = {"body": "# 第1集\n### 场景1｜书房\n拿信。\n### 场景2｜走廊\n灯亮。", "dramatic_design": {"duration_seconds": 60}}
        batches = shot_plan_scene_batches(episode)
        self.assertEqual(2, len(batches))
        self.assertNotIn("灯亮", batches[0]["body"])
        self.assertNotIn("拿信", batches[1]["body"])
        self.assertEqual(60, sum(b["dramatic_design"]["duration_seconds"] for b in batches))

    def test_plan_missing_source_dialogue_is_rejected(self):
        from backend.app.media_studio.services.llm_service import LlmService
        with patch.object(LlmService, "chat_text", return_value='{"shots":[{"action":"拿信","duration_sec":10}]}'):
            with self.assertRaisesRegex(ValueError, "遗漏来源对白"):
                LlmService.plan_episode_shots({"body": "沈砚：“先解决温饱。”", "dramatic_design": {"duration_seconds": 300}})


def setup_case():
    plan, source, request = fixture()
    for beat in source["beats"]:
        beat["scene"] = "旧站值班室·夜"
    source["beats"][-1]["scene"] = "走廊·夜"
    request.update(pipeline_version=5, language="zh-CN")
    design = deepcopy(plan["director_design"])
    prepared = reliable.normalize_design(design, source["beats"], plan["source_facts"])
    parts = pack_design(prepared, source["beats"], plan["source_facts"], WORKFLOW, 24, mixed=True)
    outputs = []
    for part in parts:
        for seg in part["segments"]:
            outputs.append(json.dumps({"segments": [{"segment_id": seg["id"],
                "unit_ids": [u["id"] for u in seg["source_units"]],
                "summary": seg["title"], "retention_analysis": "保持人物形象一致。",
                "detailed_description": "光线柔和，目光停留纸面，呼吸自然。",
                "overall_soundscape": "纸张轻响。", "non_diegetic_music": "无配乐。"}]}, ensure_ascii=False))
    payload = {"request": request, "source_snapshot": source, "source_facts": plan["source_facts"],
               "source_fingerprint": Service.source_fingerprint(source, request), "checkpoints": {}}
    return payload, request, design, outputs


def grouped_designs(design):
    return [json.dumps({**design, "units": deepcopy(design["units"][:3])}, ensure_ascii=False),
            json.dumps({**design, "units": deepcopy(design["units"][3:])}, ensure_ascii=False)]


class ReliableDirectorTests(unittest.TestCase):
    def test_twenty_seven_beats_are_bounded_and_cover_each_source_once(self):
        beats = [{"id": f"beat-{i}", "scene": f"场景 {i // 3}", "video_duration": 8,
                  "action": f"动作 {i}"} for i in range(27)]
        groups = reliable.source_groups(beats, WORKFLOW, 3)
        self.assertEqual(9, len(groups))
        self.assertEqual([beat["id"] for beat in beats], [bid for group in groups for bid in group["beat_ids"]])
        self.assertTrue(all(len(group["beat_ids"]) <= 3 and group["frame_count"] <= WORKFLOW.max_total_frames
                            for group in groups))
        self.assertTrue(all(group["scene_key"] == f"场景 {index}" for index, group in enumerate(groups)))

    def test_twenty_seven_beats_are_reviewed_in_bounded_group_calls(self):
        source = {"episode": {"id": "ep"}, "assets": [],
                  "beats": [{"id": f"b{i}", "action": f"动作 {i}"} for i in range(27)]}
        parts = [{"id": f"p{group}", "source_group_id": f"g{group}",
                  "segments": [{"id": f"s{group}-{offset}", "source_beat_ids": [f"b{group * 3 + offset}"]}
                               for offset in range(3)]} for group in range(9)]
        plan = {"schema_version": 5, "parts": parts, "director_design": {"groups": []}}
        with patch("backend.app.media_studio.services.script_development.call_json", return_value={"issues": []}) as call:
            self.assertEqual({"issues": []}, review_plan(plan, source, [], []))
        self.assertEqual(9, call.call_count)
        self.assertTrue(all(len(item.args[1]["source"]["beats"]) == 3
                            and len(item.args[1]["plan"]["parts"]) == 1
                            for item in call.call_args_list))

    def test_input_budget_seals_group_before_shot_count_limit(self):
        beats = [{"id": f"b{i}", "scene": "同场", "video_duration": 8,
                  "action": "动作" * 1800} for i in range(4)]
        groups = reliable.source_groups(beats, WORKFLOW, 4, max_input_chars=9000)
        self.assertEqual([2, 2], [len(group["beat_ids"]) for group in groups])
        self.assertTrue(all(group["input_chars_estimate"] <= 9000 for group in groups))

    def test_group_references_are_related_ordered_and_renumbered(self):
        slots = [{"asset_id": "elsewhere", "name": "外景", "token": "<Picture 1>"},
                 {"asset_id": "hero", "name": "主角", "token": "<Picture 2>"},
                 {"asset_id": "room", "name": "书房", "token": "<Picture 3>"}]
        result = reliable.group_reference_slots(slots, [{"character_ids": ["hero"], "scene_id": "room"}], 1)
        self.assertEqual(["hero", "room"], [slot["asset_id"] for slot in result])
        self.assertEqual(["<Picture 1>", "<Picture 2>"], [slot["token"] for slot in result])

    def test_new_job_reuses_unchanged_group_design_checkpoints(self):
        payload, request, design, _ = setup_case()
        with patch.object(pipeline.LlmService, "chat_text", side_effect=grouped_designs(design)) as first_chat:
            Service._plan_reliable_groups(payload, request, "")
        self.assertEqual(2, first_chat.call_count)
        old = {**payload, "episode_id": "ep", "request": request}
        current = {"project_id": "project", "episode_id": "ep", "request": request,
                   "source_snapshot": payload["source_snapshot"], "source_facts": payload["source_facts"],
                   "checkpoints": {}}
        def save(_job_id, job_payload, key, value):
            job_payload.setdefault("checkpoints", {})[key] = value
        with patch.object(pipeline, "query_all", return_value=[{"payload_json": json.dumps(old, ensure_ascii=False)}]), \
             patch.object(Service, "_save_checkpoint", side_effect=save), \
             patch.object(pipeline.LlmService, "chat_text") as next_chat:
            Service._plan_reliable_groups(current, request, "job-new")
        next_chat.assert_not_called()
        self.assertEqual(payload["source_groups"], current["source_groups"])

    def test_new_job_reuses_unchanged_segment_text_by_input_digest(self):
        payload, request, design, outputs = setup_case()
        with patch.object(pipeline.LlmService, "chat_text", side_effect=[*grouped_designs(design), *outputs]):
            first = Service._generate_director_preview(payload, request)
        reusable = {row["input_digest"]: row for row in payload["checkpoints"]["segment_generation"].values()}
        current = deepcopy(payload)
        current["checkpoints"].pop("part_generation")
        current["checkpoints"].pop("segment_generation")
        current["reusable_segment_checkpoints"] = reusable
        with patch.object(pipeline.LlmService, "chat_text") as chat:
            second = Service._generate_director_preview(current, request)
        chat.assert_not_called()
        self.assertEqual([s["prompt_text"] for p in first["parts"] for s in p["segments"]],
                         [s["prompt_text"] for p in second["parts"] for s in p["segments"]])

    def test_review_blocker_only_stops_its_own_group(self):
        plan = {"schema_version": 5, "quality_version": 1, "quality_status": "review_required",
                "parts": [{"id": "p1", "source_group_id": "g1", "segments": [{"id": "s1"}]},
                          {"id": "p2", "source_group_id": "g2", "segments": [{"id": "s2"}]}],
                "creative_review": {"issues": [{"id": "s2:timing", "segment_id": "s2", "severity": "blocking"}]}}
        plan["reviewed_content_digest"] = content_digest(plan)
        assert_ready_for_video(plan, "g1")
        with self.assertRaisesRegex(ValueError, "阻断问题"):
            assert_ready_for_video(plan, "g2")

    def test_new_plan_keeps_only_verified_unchanged_group_material(self):
        def plan(plan_id, groups):
            return {"id": plan_id, "schema_version": 5, "revision": 1, "source_fingerprint": plan_id,
                    "source_groups": [{"id": gid, "fingerprint": fingerprint} for gid, fingerprint in groups],
                    "parts": [{"id": f"p{i}", "source_group_id": gid, "render_mode": "director",
                               "workflow_id": "h3", "reference_slots": [], "execution_options": {},
                               "segments": [{"id": f"s{i}", "prompt_text": f"prompt {i}",
                                             "frame_count": 192, "source_beat_ids": [f"b{i}"]}]}
                              for i, (gid, _) in enumerate(groups, 1)]}
        old = plan("old", [("g1", "same"), ("g2", "before")])
        new = plan("new", [("g1", "same"), ("g2", "after")])
        new["parts"][0]["id"] = "p7"
        new["parts"][0]["segments"][0]["id"] = "s7"
        old_key = production_state.digest(["old", 1, "old"])
        new_key = production_state.digest(["new", 1, "new"])
        state = {"modes": {"director": {"materials": [
            {"id": "m1", "plan_key": old_key, "unit_ids": ["s1"], "url": "https://cdn/1.mp4", "verified": True},
            {"id": "m2", "plan_key": old_key, "unit_ids": ["s2"], "url": "https://cdn/2.mp4", "verified": True}],
            "versions": {old_key: {"adopted": {"s1": "m1", "s2": "m2"}}}}}}
        self.assertEqual(1, production_state.carry_unchanged_director_materials(state, old, new))
        self.assertEqual({"s7"}, set(state["modes"]["director"]["versions"][new_key]["adopted"]))
        self.assertEqual("https://cdn/1.mp4", state["modes"]["director"]["materials"][-1]["url"])

    def test_unrelated_asset_or_other_episode_does_not_invalidate_v5_source(self):
        source = {"episode": {"id": "ep", "script_text": "开门"}, "data": {},
                  "beats": [{"id": "b1", "action": "开门", "character_ids": ["hero"]}],
                  "assets": [{"id": "hero", "name": "主角", "image_url": "https://cdn/hero.png"},
                             {"id": "other", "name": "路人", "image_url": "https://cdn/other.png"}],
                  "adjacent_episodes": [{"episode_num": 2, "script_text": "旧剧情"}]}
        request = {"pipeline_version": 5, "target": {"kind": "director_episode"}, "reference_slots": []}
        before = Service.source_fingerprint(source, request)
        changed = deepcopy(source)
        changed["assets"][1]["image_url"] = "https://cdn/new-other.png"
        changed["adjacent_episodes"][0]["script_text"] = "新剧情"
        self.assertEqual(before, Service.source_fingerprint(changed, request))
        changed["assets"][0]["image_url"] = "https://cdn/new-hero.png"
        self.assertNotEqual(before, Service.source_fingerprint(changed, request))

    def test_review_dispatch_and_checkpoint_outage_cannot_fail_delivered_preview(self):
        payload, request, _, _ = setup_case()
        request["prompt_profile"] = "director_segments"
        payload["episode_id"] = "episode"
        row = {"project_id": "project", "payload_json": json.dumps(payload)}
        with patch.object(pipeline, "query_one", return_value=row), patch.object(pipeline, "_write_job", return_value=1) as writes, \
             patch.object(Service, "_generate_director_preview", return_value={"id": "plan", "revision": 1}), \
             patch.object(Service, "revise", side_effect=RuntimeError("review unavailable")), \
             patch.object(Service, "_save_checkpoint", side_effect=RuntimeError("storage outage")), \
             patch.object(Service, "kick"):
            Service._run("job")
        sql = "\n".join(c.args[0] for c in writes.call_args_list)
        self.assertIn("status='completed'", sql)
        self.assertNotIn("status='failed'", sql)

    def test_scene_resolution_is_saved_once_and_reused(self):
        source = {"beats": [{"id": "a", "action": "开门"}, {"id": "b", "scene": "走廊·夜", "action": "点灯"}]}
        payload = {"request": {"pipeline_version": 5}, "checkpoints": {}}
        with patch.object(pipeline.LlmService, "chat_text", return_value='{"scenes":{"a":"走廊·夜"}}') as chat:
            first = Service._resolve_scenes(source, payload, "")
            second = Service._resolve_scenes(source, payload, "")
        self.assertEqual({"a": "走廊·夜", "b": "走廊·夜"}, first)
        self.assertEqual(first, second)
        self.assertEqual(1, chat.call_count)

    def test_final_error_points_at_actual_segment_or_global_scope(self):
        parts = [{"id": "p1", "segments": [{"id": "s1"}]}, {"id": "p2", "segments": [{"id": "s2"}]}]
        self.assertEqual(("p1", ["s1"]), reliable.failure_location("第 1 段遗漏原始动作", parts))
        self.assertEqual(("", []), reliable.failure_location("事实覆盖不完整", parts))

    def test_structural_checks_allow_original_repetition_but_reject_duplicate_fact_ids(self):
        payload, request, design, outputs = setup_case()
        item = json.loads(outputs[1])
        item["segments"][0]["detailed_description"] = "不要重新演出前面的动作。室内声音回响。"
        outputs[1] = json.dumps(item)
        with patch.object(pipeline.LlmService, "chat_text", side_effect=[*grouped_designs(design), *outputs]):
            plan = Service._generate_director_preview(payload, request)
        Service.validate_director_plan(plan)
        plan["parts"][0]["segments"][1]["source_units"][0]["event_ids"].extend(plan["parts"][0]["segments"][0]["source_units"][0]["event_ids"])
        with self.assertRaises(ValueError):
            Service.validate_director_plan(plan)

    def test_mixed_video_retry_reuses_completed_group_and_preserves_order(self):
        shots = [{"beat_id": str(i), "prompt": "test", "duration_sec": 4, "uploaded_refs": [],
                  "group_render_mode": "director" if i < 3 else "shot", "part_boundary": i == 3,
                  "group_workflow_id": "minimax-h3-t2v", "planned_frame_count": 96}
                 for i in range(1, 4)]
        payload = {"project_id": "test", "episode_id": "ep", "render_scope": "episode", "production_context": {"mode": "director"}}
        comfy = MagicMock()
        comfy.build_render_request.return_value = {"timeline_data": {"segments": []}}
        first, second = {"filename": "group1.mp4"}, {"filename": "group2.mp4"}
        with patch.object(Video, "_set_state"), patch.object(Video, "_record_production_output") as record, \
             patch.object(Video, "_await_comfy", side_effect=[({}, first), RuntimeError("worker restart")]):
            with self.assertRaisesRegex(RuntimeError, "worker restart"):
                Video._run_timeline_job("job", payload, comfy, "t2v", shots, WORKFLOW, WORKFLOW.id)
            self.assertEqual(1, record.call_count)
        self.assertEqual(first, payload["render_plan"]["chunks"][0]["output"])
        with patch.object(Video, "_set_state"), patch.object(Video, "_record_production_output") as record, \
             patch.object(Video, "_await_comfy", return_value=({}, second)) as submit, \
             patch.object(Video, "_merge_chunk_videos", return_value=b"merged") as merge, \
             patch.object(video_module.QiniuService, "get_config", return_value=MagicMock(available=True)), \
             patch.object(video_module.QiniuService, "store_bytes", return_value=("key", "https://test/merged.mp4")):
            result = Video._run_timeline_job("job", payload, comfy, "t2v", shots, WORKFLOW, WORKFLOW.id)
        self.assertEqual("https://test/merged.mp4", result)
        self.assertEqual(1, submit.call_count)
        self.assertEqual(1, record.call_count)
        self.assertEqual(1, comfy.build_workflow.call_count)
        self.assertEqual([first, second], merge.call_args.args[1])

    def test_saved_frames_are_not_silently_clamped_or_requantized(self):
        shot = {"planned_frame_count": 391, "duration_sec": 391 / 24}
        self.assertEqual(391, frame_count(shot))
        self.assertEqual(391 / 24, duration_seconds(shot))

    def test_missing_common_setting_uses_program_owned_setting(self):
        payload, request, design, outputs = setup_case()
        design.pop("common_setting")
        with patch.object(pipeline.LlmService, "chat_text", side_effect=[*grouped_designs(design), *outputs]):
            plan = Service._generate_director_preview(payload, request)
        Service.validate_director_plan(plan)
        self.assertTrue(plan["common_setting"]["subject_definitions"])

    def test_explicit_scene_beats_model_spelling_and_headings_do_not_create_scenes(self):
        payload, _, design, _ = setup_case()
        beats = payload["source_snapshot"]["beats"]
        for i, beat in enumerate(beats):
            beat.update(scene="同一房间·夜", heading=f"镜头 {i + 1}")
        design["units"][0]["scene_key"] = "房 间"
        result = reliable.normalize_design(design, beats, payload["source_facts"])
        self.assertEqual({"同一房间·夜"}, {u["scene_key"] for u in result["units"]})

    def test_mixed_preview_is_complete_before_review_and_keeps_facts(self):
        payload, request, design, outputs = setup_case()
        with patch.object(pipeline.LlmService, "chat_text", side_effect=[*grouped_designs(design), *outputs]), patch.object(Service, "_improve_director_plan") as review:
            plan = Service._generate_director_preview(payload, request)
        Service.validate_director_plan(plan)
        self.assertEqual(5, plan["schema_version"])
        self.assertEqual(["director", "shot", "shot"], [p["render_mode"] for p in plan["parts"]])
        self.assertTrue(all(p["workflow_id"] for p in plan["parts"]))
        self.assertEqual(4, len(payload["checkpoints"]["segment_generation"]))
        review.assert_not_called()
        with self.assertRaisesRegex(ValueError, "尚未复验"):
            assert_ready_for_video(plan)

    def test_missing_camera_repairs_only_that_field(self):
        payload, request, design, outputs = setup_case()
        del design["units"][0]["camera"]
        designs = grouped_designs(design)
        with patch.object(pipeline.LlmService, "chat_text", side_effect=[designs[0], '{"camera":"平视"}', designs[1], *outputs]) as chat:
            Service._generate_director_preview(payload, request)
        patch_input = json.loads(chat.call_args_list[1].args[1])
        self.assertEqual("camera", patch_input["required_field"])
        self.assertEqual("b1", patch_input["unit"]["source_beat_id"])

    def test_segment_network_failure_resumes_without_regenerating_success(self):
        payload, request, design, outputs = setup_case()
        with patch.object(pipeline.LlmService, "chat_text", side_effect=[*grouped_designs(design), outputs[0], RuntimeError("network")]):
            with self.assertRaisesRegex(RuntimeError, "network"):
                Service._generate_director_preview(payload, request)
        self.assertEqual(["story-segment-1"], list(payload["checkpoints"]["segment_generation"]))
        with patch.object(pipeline.LlmService, "chat_text", side_effect=outputs[1:]) as chat:
            plan = Service._generate_director_preview(payload, request)
        self.assertEqual(3, chat.call_count)
        Service.validate_director_plan(plan)

    def test_program_inherits_state_and_restores_exact_frames(self):
        payload, _, design, _ = setup_case()
        design["units"][1].pop("start_state")
        design["units"][0]["duration_seconds"] = 3.14159
        result = reliable.normalize_design(design, payload["source_snapshot"]["beats"], payload["source_facts"])
        self.assertEqual(result["units"][0]["handoff_state"], result["units"][1]["start_state"])
        self.assertEqual(4, result["units"][0]["duration_seconds"])

    def test_unavailable_route_is_explicit_not_another_model(self):
        with patch.object(reliable, "WORKFLOWS", []):
            route, error = reliable.shot_route(WORKFLOW.id, 0, 4)
        self.assertIsNone(route)
        self.assertIn("没有支持", error)

    def test_recovery_leaves_live_lease_and_requeues_expired(self):
        rows = [{"id": name, "status": "running", "payload_json": json.dumps({"request": {"pipeline_version": 5},
                 "lease": {"owner": name, "expires_at": expires}, "checkpoints": {"part_generation": {"p1": {"status": "completed"}}}})}
                for name, expires in [("live", time.time()+60), ("expired", time.time()-1)]]
        with patch.object(pipeline, "query_all", return_value=rows), patch.object(pipeline, "execute_sql") as write, patch.object(Service, "kick"):
            Service.recover_interrupted_jobs(include_legacy=False)
        self.assertEqual(1, write.call_count)
        self.assertEqual("expired", write.call_args.args[1][1])
        self.assertIn("status='queued'", write.call_args.args[0])

    def test_video_old_owner_and_startup_lease_guard(self):
        video_module._VIDEO_LEASE.owner = "old"
        try:
            with patch.object(video_module, "execute_sql", return_value=0) as sql:
                with self.assertRaisesRegex(RuntimeError, "租约已转移"):
                    video_module._video_write("UPDATE ai_project_jobs SET status='failed' WHERE id=%s", ("job",))
                self.assertIn("$.execution_lease.owner", sql.call_args.args[0])
        finally:
            video_module._VIDEO_LEASE.owner = None
        with patch.object(video_module, "execute_sql") as sql:
            Video.recover_orphaned_jobs()
        self.assertIn("$.execution_lease.expires_at", sql.call_args.args[0])
        self.assertGreater(sql.call_args.args[1][1], time.time() - 5)

    def test_old_worker_cannot_overwrite_new_owner(self):
        pipeline._LEASE_LOCAL.owner = "old"
        try:
            with patch.object(pipeline, "execute_sql", return_value=0) as sql:
                with self.assertRaisesRegex(RuntimeError, "租约已转移"):
                    pipeline._write_job("UPDATE ai_project_jobs SET status='failed' WHERE id=%s", ("job",))
            self.assertIn("$.lease.owner", sql.call_args.args[0])
        finally:
            pipeline._LEASE_LOCAL.owner = None


if __name__ == "__main__":
    unittest.main()
