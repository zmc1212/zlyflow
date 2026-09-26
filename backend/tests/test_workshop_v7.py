"""Workshop contract and transactional candidate tests; all persistence is SQLite."""
from contextlib import contextmanager
from copy import deepcopy
import json
import sqlite3
import unittest
from unittest.mock import patch

from backend.app.media_studio.services import workshop_contract as c, workshop_service as service, production_state as p
from backend.tests.test_workshop_h3_skill import body as h3_body

WORKFLOW = "minimax-h3-director-accel-t2v"


def fixture(count=3):
    beats = [{"id": f"b{i}", "sequence": i, "scene": "书房", "action": f"看向第{i}封信", "video_duration": 8, "dialogue": "阿宁：回来。"} for i in range(1, count + 1)]
    plan = c.new_plan(beats, WORKFLOW, {"revision": 1, "fingerprint": "source"})
    for b in beats:
        g = next(g for g in plan["groups"] if b["id"] in g["beat_ids"])
        plan["shot_prompts"][b["id"]] = {"h3_prompt": h3_body(), "fingerprint": c.prompt_fingerprint(b, g, plan)}
    return {"beats": beats, "prompt_authoring": {"director_plan": plan}, "data": {}, "script_text": "故事"}


class ContractTests(unittest.TestCase):
    def test_grouping_order_and_capacity_without_ai(self):
        d = fixture(7)
        self.assertEqual([len(g["beat_ids"]) for g in c.plan_of(d)["groups"]], [3, 3, 1])
        groups = deepcopy(c.plan_of(d)["groups"])
        groups[0]["beat_ids"].append("b4")
        with self.assertRaisesRegex(ValueError, "完整覆盖"):
            c.validate_groups(d["beats"], groups, WORKFLOW, 3)

    def test_generation_preserves_identity_and_local_time(self):
        d = fixture()
        original = deepcopy(d)
        shots, execution = c.execution_shots(d)
        self.assertEqual([s["beat_id"] for s in shots], ["b1", "b2", "b3"])
        self.assertEqual(len(execution["parts"]), 1)
        self.assertEqual(d, original)
        self.assertTrue(all("00:00.00" in s["prompt"] for s in shots))

    def test_stale_reference_blocks_without_changing_text(self):
        d = fixture()
        c.plan_of(d)["groups"][0]["common_prompt"] = "新设定"
        with self.assertRaisesRegex(ValueError, "待更新"):
            c.execution_shots(d)

    def test_validation_detects_dialogue_time_and_reference(self):
        d = fixture(); b = d["beats"][0]; g = c.plan_of(d)["groups"][0]
        errors = c.prompt_checks("[Shot 2] 00:08.00–00:16.00 <Picture 1> 他离开。", b, g)
        self.assertTrue(any("遗漏对白" in e for e in errors))
        self.assertTrue(any("参考图" in e for e in errors))
        self.assertTrue(any("拆镜" in e for e in errors))

    def test_prompt_only_change_keeps_production_selection(self):
        d = fixture(); key = p.plan_context(d, "shot")["key"]
        c.plan_of(d)["revision"] += 1
        c.plan_of(d)["shot_prompts"]["b1"]["h3_prompt"] += "新表演"
        self.assertEqual(p.plan_context(d, "director")["key"], key)

    def test_subject_numbers_are_shared_and_unknown_subject_is_blocked(self):
        beats = [{"id":"b1","scene":"书房","characters":["阿宁","阿南"],"video_duration":8},
                 {"id":"b2","scene":"书房","characters":["阿南"],"video_duration":8}]
        group = c.group_shots(beats, WORKFLOW)[0]
        self.assertIn("<Subject 1>：阿宁", group["common_prompt"])
        self.assertIn("<Subject 2>：阿南", group["common_prompt"])
        valid = "[Shot 1] 00:00.00–00:08.00 <Subject 2> 抬头。"
        self.assertEqual(c.prompt_checks(valid, beats[1], group), [])
        self.assertTrue(any("主体编号" in error for error in c.prompt_checks(valid.replace("Subject 2","Subject 3"),beats[1],group)))

    def test_replan_carries_unchanged_verified_ranges_and_retains_history(self):
        d = fixture(); state = p.hydrate(d); key = p.plan_context(d, "director")["key"]
        material = {"id": "take", "plan_key": key, "unit_ids": ["b1", "b2", "b3"], "url": "take.mp4", "verified": True, "duration": 24, "ranges": {f"b{i}": {"start": (i-1)*8, "end": i*8} for i in range(1,4)}}
        p.register_material(state, "director", material)
        newer = deepcopy(d); newer["beats"].append({"id": "b4", "sequence": 4, "scene": "书房", "action": "离开", "video_duration": 8})
        newer["prompt_authoring"]["director_plan"] = c.new_plan(newer["beats"], WORKFLOW, {"revision": 1, "fingerprint": "source"}, c.plan_of(d))
        carried = p.carry_workshop_materials(state, d, newer)
        summary = p.summary(newer, carried)
        self.assertEqual(set(summary["adopted"]), {"b1", "b2", "b3"})
        self.assertEqual(len(summary["timeline"]), 1)
        self.assertEqual(summary["timeline"][0]["end"], 24)
        self.assertEqual(p.version(carried, "director", key)["adopted"]["b1"], "take")

    def test_ambiguous_legacy_mapping_is_not_auto_adopted(self):
        d = fixture(1); old = deepcopy(d)
        old["prompt_authoring"]["director_plan"] = {"schema_version": 6, "id": "old", "revision": 1, "status": "current", "parts": [{"id": "p", "segments": [{"id": s, "source_beat_ids": ["b1"], "duration_seconds": 4} for s in ["s1", "s2"]]}]}
        state = p.hydrate(old); key = p.plan_context(old, "director")["key"]
        p.register_material(state, "director", {"id": "legacy", "url": "legacy.mp4", "unit_ids": ["s1", "s2"], "plan_key": key, "verified": False})
        migrated = p.carry_workshop_materials(state, old, d)
        self.assertEqual(p.summary(d, migrated)["adopted"], {})
        self.assertTrue(any(m["id"] == "legacy" for m in migrated["modes"]["director"]["materials"]))


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:"); self.db.row_factory = sqlite3.Row
        self.db.executescript("CREATE TABLE ai_project_episodes(id TEXT,project_id TEXT,episode_num INTEGER,title TEXT,script_text TEXT,data_json TEXT,shots_count INTEGER,updated_at TEXT); CREATE TABLE ai_project_jobs(id TEXT,project_id TEXT,job_type TEXT,status TEXT,payload_json TEXT,error_message TEXT,created_at TEXT,updated_at TEXT); CREATE TABLE ai_project_documents(id TEXT,project_id TEXT,analysis_json TEXT);")
        self.detail = fixture(1)
        self.db.execute("CREATE TABLE ai_project_assets(id TEXT,project_id TEXT)")
        self.db.execute("CREATE TABLE llm_provider_profiles(profile_id TEXT,model TEXT,reasoning_effort TEXT)")
        data = {"beats": self.detail["beats"], "prompt_authoring": self.detail["prompt_authoring"], "workshop_flow": 7}
        self.db.execute("INSERT INTO ai_project_episodes VALUES ('e','p',1,'集','故事',?,1,'')", (json.dumps(data),)); self.db.commit()
        db = self.db
        def sql(query, args=()): return db.execute(query.replace("%s", "?").replace(" FOR UPDATE", ""), args)
        class Cursor:
            def execute(self, query, args=()): self.result = sql(query,args); return self.result.rowcount
            def fetchone(self):
                r = self.result.fetchone(); return dict(r) if r else None
            def fetchall(self): return [dict(r) for r in self.result.fetchall()]
        @contextmanager
        def transaction():
            try: yield Cursor(); db.commit()
            except Exception: db.rollback(); raise
        def one(q,a=()):
            r = sql(q,a).fetchone(); return dict(r) if r else None
        def execute(q,a=()):
            n = sql(q,a).rowcount; db.commit(); return n
        self.patches = [patch.object(service,"query_one",one), patch.object(service,"query_all",lambda q,a=(): [dict(r) for r in sql(q,a).fetchall()]), patch.object(service,"execute_sql",execute), patch.object(service,"transaction_cursor",transaction)]
        self.patches.append(patch("backend.app.media_studio.provider_bridge.llm_row", return_value={}))
        for item in self.patches: item.start()
    def tearDown(self):
        for item in self.patches: item.stop()
        self.db.close()

    def test_manual_save_is_canonical_and_stale_write_rolls_back(self):
        body = h3_body()
        service.WorkshopService.update("p","e", {"expected_revision":1,"beat_id":"b1","h3_prompt":body})
        _, data = service.WorkshopService.row("p","e")
        self.assertNotIn("h3_prompt",data["beats"][0])
        self.assertEqual(data["prompt_authoring"]["director_plan"]["shot_prompts"]["b1"]["h3_prompt"],body)
        with self.assertRaisesRegex(ValueError,"VERSION_CONFLICT"):
            service.WorkshopService.update("p","e", {"expected_revision":1,"beat_id":"b1","h3_prompt":"bad"})
        self.assertEqual(service.WorkshopService.row("p","e")[1],data)

    def test_candidate_cannot_override_manual_edit(self):
        row,data=service.WorkshopService.row("p","e"); plan=data["prompt_authoring"]["director_plan"]
        payload={"episode_id":"e","source":service.WorkshopService.source("p",row,data),"base_plan":deepcopy(plan),"beats":data["beats"],"prompt_scope":"group","candidates":deepcopy(plan["shot_prompts"]),"applied_ids":[]}
        self.db.execute("INSERT INTO ai_project_jobs VALUES ('j','p','workshop_prompt','completed',?,NULL,'','')", (json.dumps(payload),));self.db.commit()
        service.WorkshopService.update("p","e", {"expected_revision":1,"beat_id":"b1","h3_prompt":h3_body() + "手工稿"})
        with self.assertRaisesRegex(ValueError,"不能覆盖"):
            service.WorkshopService.job_action("p","e","j",{"action":"apply","expected_revision":2})


if __name__ == "__main__": unittest.main()
