from copy import deepcopy
from contextlib import contextmanager
import json
import unittest
from unittest.mock import patch

from backend.app.media_studio.services import workshop_contract as C
from backend.app.media_studio.services.workshop_references import resolve_state, assert_ready
from backend.app.media_studio.services.workshop_service import WorkshopService as W
from backend.tests.test_workshop_h3_skill import body as h3_body


def character(image="https://assets/hero.png", look="ancient", name="主角"):
    return {"id": "hero", "kind": "character", "name": name, "extra": {"identities": [
        {"id": look, "name": "古代粗布衣", "image_url": image}]}}


def state():
    beats = [{"id": "b1", "sequence": 1, "heading": "古代书房", "scene": "书房", "video_duration": 8,
              "action": "主角抬头", "characters": ["主角"], "character_ids": ["hero"], "prop_ids": []}]
    return {"beats": beats, "prompt_authoring": {"director_plan": C.new_plan(
        beats, "minimax-h3-director-accel-r2v", {"revision": 1, "fingerprint": "source"})}}


class ReferenceProjectionTests(unittest.TestCase):
    def test_new_plan_links_bound_images_without_frontend_patch(self):
        raw = state()
        resolved = resolve_state(raw, [character()])
        group = resolved["prompt_authoring"]["director_plan"]["groups"][0]
        self.assertEqual(group["reference_policy"], "auto")
        self.assertEqual([(s["asset_id"], s["look_id"], s["token"]) for s in group["reference_slots"]], [("hero", "ancient", "<Picture 1>")])
        self.assertFalse(group["reference_issues"])
        self.assertEqual(raw["prompt_authoring"]["director_plan"]["groups"][0]["reference_slots"], [])
        self.assertEqual(resolve_state(resolved, [character()]), resolved)

    def test_missing_image_blocks_writing_then_late_generation_resolves_it(self):
        raw = state()
        missing = resolve_state(raw, [character("")])
        with self.assertRaisesRegex(ValueError, "古代粗布衣.*缺少设定图"):
            assert_ready(missing["prompt_authoring"]["director_plan"])
        ready = resolve_state(missing, [character()])
        assert_ready(ready["prompt_authoring"]["director_plan"])
        self.assertEqual(len(ready["prompt_authoring"]["director_plan"]["groups"][0]["reference_slots"]), 1)

    def test_assets_added_after_planning_resolve_unique_names(self):
        raw = state(); raw["beats"][0]["character_ids"] = []
        missing = resolve_state(raw, [])
        self.assertIn("资产不存在", missing["prompt_authoring"]["director_plan"]["groups"][0]["reference_issues"][0])
        ready = resolve_state(missing, [character()])
        self.assertEqual(ready["beats"][0]["character_ids"], ["hero"])
        assert_ready(ready["prompt_authoring"]["director_plan"])

    def test_explicit_removed_binding_is_not_reattached_by_name(self):
        raw = state(); raw["beats"][0].update(character_ids=[], workshop_manual_bindings=["character_ids"])
        resolved = resolve_state(raw, [character()])
        self.assertEqual(resolved["beats"][0]["character_ids"], [])
        self.assertEqual(resolved["prompt_authoring"]["director_plan"]["groups"][0]["reference_slots"], [])

    def test_replaced_asset_invalidates_old_prompt_without_erasing_it(self):
        resolved = resolve_state(state(), [character()]); plan = resolved["prompt_authoring"]["director_plan"]
        beat = resolved["beats"][0]; group = plan["groups"][0]
        plan["shot_prompts"]["b1"] = {"h3_prompt": h3_body(name="主角", dialogue="") + "主角抬头", "fingerprint": C.prompt_fingerprint(beat, group, plan)}
        self.assertEqual(C.project_prompts(resolved["beats"], plan)[0]["h3_prompt_reference_state"], "current")
        changed = resolve_state(resolved, [character("https://assets/replaced.png")])
        projected = C.project_prompts(changed["beats"], changed["prompt_authoring"]["director_plan"])[0]
        self.assertEqual(projected["h3_prompt_reference_state"], "stale")
        self.assertIn("主角抬头", projected["h3_prompt"])
        with self.assertRaisesRegex(ValueError, "提示词缺失或待更新"):
            C.execution_plan({"beats": changed["beats"], "prompt_authoring": changed["prompt_authoring"]})

    def test_explicit_missing_look_never_falls_back_to_another_image(self):
        asset = character("")
        asset["extra"]["identities"].append({"id": "modern", "name": "现代西装", "image_url": "https://assets/modern.png"})
        raw = state(); raw["beats"][0]["character_look_ids"] = {"hero": "ancient"}
        result = resolve_state(raw, [asset]); group = result["prompt_authoring"]["director_plan"]["groups"][0]
        self.assertFalse(group["reference_slots"])
        self.assertIn("古代粗布衣", group["reference_issues"][0])

    def test_ambiguous_looks_and_names_are_not_guessed(self):
        asset = character(); asset["extra"]["identities"].append({"id":"ancient2", "name":"古代礼服", "image_url":"https://assets/two.png"})
        result = resolve_state(state(), [asset])
        self.assertIn("造型未明确", result["prompt_authoring"]["director_plan"]["groups"][0]["reference_issues"][0])
        raw=state(); raw["beats"][0]["character_ids"]=[]
        result=resolve_state(raw,[character(),{**character(),"id":"duplicate"}])
        self.assertIn("重名", result["prompt_authoring"]["director_plan"]["groups"][0]["reference_issues"][0])

    def test_manual_order_survives_asset_updates_and_missing_images(self):
        raw=state(); group=raw["prompt_authoring"]["director_plan"]["groups"][0]
        group.update(reference_policy="manual", reference_slots=[
            {"asset_id":"hero","look_id":"ancient","name":"主角","image_url":"https://assets/old.png","index":1,"token":"<Picture 1>"},
            {"name":"外部图","image_url":"https://assets/external.png","index":2,"token":"<Picture 2>"}])
        missing=resolve_state(raw,[character("")])
        self.assertEqual(len(missing["prompt_authoring"]["director_plan"]["groups"][0]["reference_slots"]),2)
        ready=resolve_state(missing,[character()]); slots=ready["prompt_authoring"]["director_plan"]["groups"][0]["reference_slots"]
        self.assertEqual([s["image_url"] for s in slots],["https://assets/hero.png","https://assets/external.png"])
        assert_ready(ready["prompt_authoring"]["director_plan"])

    def test_no_scenery_or_unrelated_assets_are_added_and_limit_is_not_truncated(self):
        raw=state(); assets=[character(),{"id":"scene","kind":"scene","name":"书房","image_url":"https://assets/scene.png"}]
        ready=resolve_state(raw,assets)
        self.assertEqual(len(ready["prompt_authoring"]["director_plan"]["groups"][0]["reference_slots"]),1)
        for i in range(10):
            raw["beats"][0]["prop_ids"].append(str(i)); assets.append({"id":str(i),"kind":"prop","name":str(i),"image_url":f"https://assets/{i}.png"})
        result=resolve_state(raw,assets); group=result["prompt_authoring"]["director_plan"]["groups"][0]
        self.assertFalse(group["reference_slots"])
        self.assertIn("超过工作流上限", group["reference_issues"][0])

    def test_t2v_has_no_artificial_image_requirement(self):
        raw=state(); raw["prompt_authoring"]["director_plan"]["workflow_id"]="minimax-h3-director-accel-t2v"
        result=resolve_state(raw,[])
        assert_ready(result["prompt_authoring"]["director_plan"])


class ReferenceServiceTests(unittest.TestCase):
    def setUp(self):
        self.assets=[character()]
        self.data=state()
        self.row={"id":"ep", "project_id":"project", "episode_num":1, "script_text":"主角抬头"}
        self.data["prompt_authoring"]["director_plan"]["source_fingerprint"]=W.source("project",self.row,self.data)["fingerprint"]
        self.jobs={}
        for target, value in [("reference_assets",lambda _:deepcopy(self.assets)),("view",lambda *args: {})]:
            p=patch.object(W,target,side_effect=value); p.start(); self.addCleanup(p.stop)
        p=patch("backend.app.media_studio.services.workshop_service.query_one",side_effect=self.query_one); p.start(); self.addCleanup(p.stop)
        p=patch("backend.app.media_studio.services.workshop_service.transaction_cursor",self.cursor); p.start(); self.addCleanup(p.stop)
        p=patch("backend.app.media_studio.services.workshop_service.execute_sql",return_value=1); self.execute=p.start(); self.addCleanup(p.stop)

    def query_one(self,sql,args):
        if "ai_project_jobs" in sql: return deepcopy(self.jobs.get(args[0]))
        return {**self.row,"data_json":json.dumps(self.data)}

    @contextmanager
    def cursor(self):
        owner=self
        class Cursor:
            def execute(self,sql,args):
                if sql.startswith("UPDATE ai_project_episodes"):
                    owner.data=json.loads(args[0])
            def fetchone(self): return {**owner.row,"data_json":json.dumps(owner.data)}
        yield Cursor()

    def candidate(self):
        _,data=W.row("project","ep"); plan=data["prompt_authoring"]["director_plan"]; group=plan["groups"][0]
        record={"h3_prompt":h3_body(name="主角", dialogue=""), "fingerprint":C.prompt_fingerprint(data["beats"][0],group,plan)}
        payload={"episode_id":"ep","source":W.source("project",self.row,data),"base_plan":plan,"beats":data["beats"],"request":{"beat_ids":["b1"]},"prompt_scope":"group","candidates":{"b1":record},"applied_ids":[]}
        self.jobs["job"]={"id":"job","job_type":"workshop_prompt","status":"completed","payload_json":json.dumps(payload)}

    def test_prompt_request_blocks_before_enqueuing_when_image_missing(self):
        self.assets=[character("")]
        with patch.object(W.executor,"submit") as submit, self.assertRaisesRegex(ValueError,"缺少设定图"):
            W.create("project","ep","workshop_prompt",{"expected_revision":1})
        submit.assert_not_called(); self.execute.assert_not_called()

    def test_candidate_apply_and_execution_use_same_reference_snapshot(self):
        self.candidate()
        W.job_action("project","ep","job",{"action":"apply","expected_revision":1})
        resolved=resolve_state(self.data,self.assets)
        shots,_=C.execution_shots({"beats":resolved["beats"],"prompt_authoring":resolved["prompt_authoring"]})
        self.assertEqual(shots[0]["reference_urls"],["https://assets/hero.png"])

    def test_asset_changed_while_model_writes_rejects_old_candidate(self):
        self.candidate(); before=deepcopy(self.data); self.assets=[character("https://assets/new.png")]
        with self.assertRaisesRegex(ValueError,"VERSION_CONFLICT"):
            W.job_action("project","ep","job",{"action":"apply","expected_revision":1})
        self.assertEqual(self.data,before)

    def test_editing_shot_binding_refreshes_auto_group_under_revision_lock(self):
        W.update("project","ep",{"expected_revision":1,"beat_id":"b1","shot_updates":{"character_ids":[]}})
        plan=self.data["prompt_authoring"]["director_plan"]
        self.assertEqual(plan["revision"],2)
        self.assertEqual(plan["groups"][0]["reference_slots"],[])
        self.assertTrue(plan["groups"][0]["reference_issues"])

    def test_explicit_group_selection_becomes_manual_and_can_restore_auto(self):
        _,data=W.row("project","ep"); groups=data["prompt_authoring"]["director_plan"]["groups"]
        groups[0]["reference_slots"]=[{"name":"外部图","image_url":"https://assets/manual.png","index":1,"token":"<Picture 1>"}]
        W.update("project","ep",{"expected_revision":1,"groups":groups})
        group=self.data["prompt_authoring"]["director_plan"]["groups"][0]
        self.assertEqual(group["reference_policy"],"manual")
        W.update("project","ep",{"expected_revision":2,"auto_reference_group_ids":[group["id"]]})
        group=self.data["prompt_authoring"]["director_plan"]["groups"][0]
        self.assertEqual(group["reference_policy"],"auto")
        self.assertEqual(group["reference_slots"][0]["asset_id"],"hero")

    def test_manual_save_from_old_browser_snapshot_rejected_after_image_swap(self):
        _, viewed = W.row("project", "ep")
        expected = viewed["prompt_authoring"]["director_plan"]["reference_fingerprint"]
        self.assets = [character("https://assets/replaced.png")]
        with self.assertRaisesRegex(ValueError, "参考资产或造型已变化"):
            W.update("project", "ep", {"expected_revision": 1, "expected_reference_fingerprint": expected,
                "beat_id": "b1", "h3_prompt": "[Shot 1] 00:00.00–00:08.00 主角抬头"})
        self.assertFalse(self.data["prompt_authoring"]["director_plan"]["shot_prompts"])

    def test_restructured_auto_group_keeps_automatic_updates(self):
        _, viewed = W.row("project", "ep")
        groups = viewed["prompt_authoring"]["director_plan"]["groups"]
        groups[0]["id"] = "new-group"
        W.update("project", "ep", {"expected_revision": 1, "groups": groups})
        self.assertEqual(self.data["prompt_authoring"]["director_plan"]["groups"][0]["reference_policy"], "auto")
        self.assets = [character("https://assets/replaced.png")]
        _, resolved = W.row("project", "ep")
        self.assertEqual(resolved["prompt_authoring"]["director_plan"]["groups"][0]["reference_slots"][0]["image_url"], "https://assets/replaced.png")

    def test_all_prompt_generation_failures_report_failed_not_completed(self):
        _, data = W.row("project", "ep")
        payload = {"episode_id": "ep", "request": {"beat_ids": ["b1"]}, "base_plan": data["prompt_authoring"]["director_plan"],
                   "beats": data["beats"], "candidates": {}, "failures": {}, "prompt_scope": "group",
                   "writing_author": {"model": "test-author", "provider": "test"}}
        self.jobs["job"] = {"id": "job", "status": "running", "job_type": "workshop_prompt", "payload_json": json.dumps(payload)}
        def persist(sql, args):
            if sql.startswith("UPDATE ai_project_jobs SET payload_json"):
                self.jobs["job"]["payload_json"] = args[0]
                if "status=%s" in sql:
                    self.jobs["job"]["status"] = args[1]
            return 1
        self.execute.side_effect = persist
        with patch("backend.app.media_studio.services.workshop_service.generate_group", side_effect=ValueError("模型输出不完整")):
            W.run("project", "job")
        terminal = self.execute.call_args.args[1]
        self.assertEqual(terminal[1], "failed")
        self.assertIn("模型输出不完整", terminal[2])


if __name__ == "__main__": unittest.main()
