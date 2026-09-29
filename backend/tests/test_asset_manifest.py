"""Isolated contract and transaction regressions; never calls a production model."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch, MagicMock

from backend.app.media_studio.services import asset_manifest_service as m
from backend.app.media_studio.services import asset_pipeline_prompts as prompts
from backend.app.media_studio.services import shot_asset_audit as audit
from backend.app.media_studio.services.llm_service import LlmService


SOURCE = "沈砚坐着望向母亲。母亲握住沈砚的手。门外传来老张的声音，他提到父亲。"


def entry(name="沈砚", **updates):
    return {"kind": "character", "name": name, "identity": name, "aliases": [], "era": "古代", "evidence": SOURCE, **updates}


def manifest():
    return {"version": "v1", "entries": [{**entry(n), "id": str(i), "asset_id": "a"+str(i), "look_id": "l"+str(i)}
                                         for i, n in enumerate(["沈砚", "母亲", "老张", "父亲"])]}


def result():
    return {"shots": [{"id": "b", "issues": [], "references": [
        {"manifest_id": str(i), "appearance": role, "location": "action", "evidence": SOURCE}
        for i, role in enumerate(["visible", "visible", "offscreen", "mentioned"])]}]}


class AssetContractTests(unittest.TestCase):
    def test_workshop_recovery_does_not_interrupt_live_owner(self):
        from backend.app.media_studio.services import workshop_service as workshop
        jobs = [{"id": "live", "payload_json": '{"owner":{"pid":123}}'},
                {"id": "dead", "payload_json": '{}'}]
        with patch.object(workshop, "query_all", return_value=jobs), patch.object(workshop, "execute_sql") as update, patch.object(m, "owner_alive", side_effect=[True, False]):
            workshop.WorkshopService.recover()
        self.assertEqual(update.call_count, 1)
        self.assertEqual(update.call_args.args[1][-1], "dead")

    def test_source_hash_and_selected_sections_are_real(self):
        for stage in ("assets", "shots"):
            spec = prompts.adapter(stage)
            self.assertEqual(spec["sha256"], hashlib.sha256((prompts.ROOT/spec["path"]).read_bytes()).hexdigest())
            self.assertTrue(spec["sections"])
            self.assertNotIn("完整制作包样例", spec["system"])
        self.assertNotIn("每个场景必须包含", prompts.adapter("assets")["system"])

    def test_entries_reject_invented_evidence_unknown_fields_and_wrong_aliases(self):
        for bad in [entry(evidence="想象的台词"), entry(database_id="evil"), entry(aliases="别名"), entry(era="现代与古代两种造型")]:
            with self.assertRaises(ValueError): m.validate_entries({"entries": [bad], "issues": []}, SOURCE, 1)

    def test_model_only_asset_fields_are_discarded_with_auditable_warning(self):
        raw, warnings = m.normalize_model_asset_fields({"entries": [entry(description="仅供展示", asset_id="model-id")], "issues": []})
        self.assertEqual(set(raw["entries"][0]), {"kind", "name", "identity", "aliases", "era", "evidence"})
        self.assertEqual(warnings, [{"entry": 1, "fields": ["asset_id", "description"]}])
        prop = {"kind": "prop", "name": "钥匙", "identity": "钥匙", "aliases": [], "剧情功能": "开启柜门",
                "所属分类": "道具", "所属角色或场景": "书房", "时代/世界观": "现代", "evidence": SOURCE}
        normalized, warnings = m.normalize_model_asset_fields({"entries": [prop], "issues": []})
        self.assertEqual(normalized["entries"][0]["era"], "现代")
        self.assertEqual(warnings[0]["fields"], ["剧情功能", "所属分类", "所属角色或场景", "时代/世界观"])
        unchanged, warnings = m.normalize_model_asset_fields({"entries": [entry(database_id="evil")], "issues": []})
        self.assertEqual(unchanged["entries"][0].get("database_id"), "evil")
        self.assertEqual(warnings, [])
        mixed, warnings = m.normalize_model_asset_fields({"entries": [entry(database_id="evil", description="展示")], "issues": []})
        self.assertNotIn("description", mixed["entries"][0])
        with self.assertRaisesRegex(ValueError, "未知资产字段"):
            m.validate_entries(mixed, SOURCE, 1)

    def test_identity_and_era_distinguish_entries_and_ids_are_repeatable(self):
        def get(**kw): return m.validate_entries({"entries": [entry("母亲", **kw)], "issues": []}, SOURCE, 1)[0]["id"]
        self.assertEqual(get(), get())
        self.assertNotEqual(get(identity="沈家母亲"), get(identity="张家母亲"))
        self.assertNotEqual(get(era="现代"), get(era="古代"))

    def test_known_identity_can_cite_earlier_source_without_forging_current_scope(self):
        row = m.validate_entries({"entries": [entry()], "issues": []}, "沈砚走进房间。", 2, [SOURCE])[0]
        self.assertEqual(row["evidence"], [{"scope": 1, "quote": SOURCE}])
        with self.assertRaises(ValueError):
            m.validate_entries({"entries": [entry(evidence="不存在的外貌")], "issues": []}, "沈砚走进房间。", 2, [SOURCE])

    def test_evidence_can_contain_multiple_contiguous_excerpts(self):
        source = "两个保洁员停在门前。\n\n吴耐拉开门。\n\n保洁员甲探头往里看。"
        row = m.validate_entries({"entries": [entry("保洁员甲", evidence="两个保洁员停在门前。\n\n保洁员甲探头往里看。")], "issues": []}, source, 1)[0]
        self.assertEqual(row["evidence"], [
            {"scope": 1, "quote": "两个保洁员停在门前。"},
            {"scope": 1, "quote": "保洁员甲探头往里看。"},
        ])
        with self.assertRaisesRegex(ValueError, "INVALID_EVIDENCE"):
            m.validate_entries({"entries": [entry("保洁员甲", evidence="两个保洁员停在门前。\n\n不存在的动作。")], "issues": []}, source, 1)

    def test_evidence_repair_canonicalizes_omitted_speaker_prefix_and_records_it(self):
        source = "吴耐：窝收拾干净了，人也得像个人样。今晚去夜场找沙丽丽，总不能穿成叫花子去砸场子。"
        repairs = []
        row = m.validate_entries({"entries": [entry("沙丽丽", evidence="吴耐：今晚去夜场找沙丽丽，总不能穿成叫花子去砸场子。")], "issues": []}, source, 1, evidence_repairs=repairs)[0]
        self.assertEqual(row["evidence"], [{"scope": 1, "quote": source}])
        self.assertEqual(repairs[0]["kind"], "suffix")

    def test_visible_silent_person_offscreen_and_mention_projection(self):
        beat = {"id": "b", "action": SOURCE, "dialogue": "", "video_url": "existing.mp4"}
        refs = audit.validate_audit(result(), [beat], manifest(), SOURCE)[0]["references"]
        projected = audit.project_references(beat, refs)
        self.assertEqual(projected["character_ids"], ["a0", "a1"])
        self.assertEqual(projected["character_look_ids"], {"a0": "l0", "a1": "l1"})
        self.assertEqual(projected["action"], SOURCE)
        self.assertEqual(projected["video_url"], "existing.mp4")

    def test_planning_keeps_workflow_valid_short_duration_and_records_stages(self):
        evidence = []
        shot = {"shot_num": 1, "title": "背影", "action": "沈砚站在门口。", "dialogue": "", "duration_sec": 2}
        def respond(stage, system, user, records, checkpoint, **kwargs):
            records.append({"stage": stage})
            return json.dumps({"shots": [shot]}, ensure_ascii=False)
        with patch.object(audit, "request", side_effect=respond):
            shots = audit.plan_shots({"body": "沈砚站在门口。"}, "16:9", manifest(), "minimax-h3-director-accel-t2v", evidence, lambda: None)
        self.assertEqual(len(shots), 1)
        self.assertEqual(shots[0]["duration_sec"], 2)
        self.assertEqual(shots[0]["dialogue"], "")
        self.assertTrue(any(e["stage"] == "shot_planning" and e.get("parsed") for e in evidence))

    def test_planning_rejects_out_of_contract_duration_after_one_correction(self):
        def respond(stage, system, user, evidence, checkpoint, **kwargs):
            evidence.append({"stage": stage})
            return '{"shots":[{"action":"沈砚站在门口。","duration_sec":1}]}'
        with patch.object(audit, "request", side_effect=respond) as call:
            with self.assertRaisesRegex(ValueError, "时长"):
                audit.plan_shots({"body": "沈砚站在门口。"}, "16:9", manifest(), "minimax-h3-director-accel-t2v", [], lambda: None)
        self.assertEqual(call.call_count, 2)

    def test_unknown_id_and_story_edits_are_rejected(self):
        beat = {"id": "b", "action": SOURCE}
        for change in [lambda r: r["shots"][0]["references"][0].update(manifest_id="fabricated"),
                       lambda r: r["shots"][0]["references"][0].update(manifest_id=[]),
                       lambda r: r["shots"].__setitem__(0, None),
                       lambda r: r["shots"][0].update(action="改写故事"),
                       lambda r: r["shots"][0]["references"][0].update(evidence="假出处")]:
            r = result(); change(r)
            with self.assertRaises(ValueError): audit.validate_audit(r, [beat], manifest(), SOURCE)

    def test_planning_cannot_name_anonymous_people_from_asset_catalog(self):
        catalog = {"entries": [{"kind": "character", "name": "村民甲", "aliases": ["老张"]}]}
        shot = {"characters": ["村民甲"], "dialogue": "村民甲：田都淹了！"}
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_IDENTITY"):
            audit.validate_source_identities([shot], {"body": "几个村民在远处争论：田都淹了！"}, catalog)
        audit.validate_source_identities([shot], {"body": "老张在远处说：田都淹了！"}, catalog)
        audit.validate_source_identities([{"characters": [], "dialogue": "村民（画外）：田都淹了！"}],
                                         {"body": "几个村民在远处争论：田都淹了！"}, catalog)

    def test_dialogue_coverage_includes_narrated_voices_but_not_written_labels(self):
        source = '母亲：“先喝粥。”\n他沿土路走去，远处传来村民争执的声音——“田都淹了！”“必须堵住！”\n牌匾上写着：“陆府”\n桌上放着《古籍》，书名为“水经”。'
        self.assertEqual(audit.source_dialogue_lines(source), ["先喝粥。", "田都淹了！", "必须堵住！"])

    def test_missing_name_is_only_a_pending_issue_not_automatically_visible(self):
        r = result(); r["shots"][0]["references"] = r["shots"][0]["references"][1:]
        checked = audit.validate_audit(r, [{"id": "b", "opening_state": SOURCE}], manifest(), SOURCE)[0]
        self.assertTrue(checked["issues"])
        self.assertNotIn("a0", audit.project_references({}, checked["references"])["character_ids"])

    def test_ambiguity_gets_at_most_one_retry(self):
        r = result(); r["shots"][0]["issues"] = ["代词指向未明确"]
        with patch.object(audit, "request", return_value=json.dumps(r)) as call:
            evidence = [{}]
            _, checked = audit.audit([{"id": "b", "action": SOURCE}], SOURCE, manifest(), evidence, lambda: None)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(checked["status"], "pending")

    def test_request_is_saved_before_call_and_no_credentials_in_evidence(self):
        evidence, snapshots = [], []
        with patch("backend.app.media_studio.provider_bridge.llm_row", return_value={"model": "test", "api_key": "DO_NOT_RECORD"}), \
             patch.object(LlmService, "chat_text", return_value="{}"):
            prompts.request("test", "system", "user", evidence, lambda: snapshots.append(deepcopy(evidence)))
        self.assertNotIn("raw", snapshots[0][0])
        self.assertEqual(evidence[0]["raw"], "{}")
        self.assertNotIn("DO_NOT_RECORD", json.dumps(evidence))

    def test_reasoning_budget_is_scoped_to_new_pipeline_thinking_models(self):
        for model, stage, budget in [("kimi-k3", "assets", 32768), ("kimi-k3", "asset_audit", 32768), ("test", "assets", 12000)]:
            with self.subTest(model=model, stage=stage), \
                 patch("backend.app.media_studio.provider_bridge.llm_row", return_value={"model": model}), \
                 patch.object(LlmService, "chat_text", return_value="{}") as network:
                prompts.request(stage, "system", "source", [], max_tokens=12000)
                self.assertEqual(network.call_args.kwargs["max_tokens"], budget)

    def test_empty_stream_retains_finish_reason_and_request_evidence(self):
        response = MagicMock(status_code=200)
        response.headers = {"Content-Type": "text/event-stream"}
        response.iter_lines.return_value = [
            'data: {"id":"response-id","model":"kimi-k3","choices":[{"delta":{},"finish_reason":"length"}]}',
            'data: [DONE]',
        ]
        evidence = []
        with patch("requests.Session.post", return_value=response), \
             patch.object(LlmService, "_runtime_config", return_value=("https://example.com/v1", "kimi-k3", "DO_NOT_RECORD")), \
             patch("backend.app.media_studio.provider_bridge.llm_row", return_value={"model": "kimi-k3"}), \
             patch("backend.app.media_studio.services.llm_service.llm_row", return_value={"model": "kimi-k3"}):
            with self.assertRaisesRegex(RuntimeError, "内容为空"):
                prompts.request("assets", "system", "source", evidence)
        self.assertEqual(evidence[0]["status"], "failed")
        self.assertEqual(evidence[0]["response_metadata"]["finish_reason"], "length")
        self.assertEqual(evidence[0]["response_metadata"]["response_model"], "kimi-k3")
        self.assertEqual(evidence[0]["effective_parameters"]["max_tokens"], 32768)
        self.assertNotIn("DO_NOT_RECORD", json.dumps(evidence))


class ManifestTransactions(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          CREATE TABLE ai_project_documents(id TEXT PRIMARY KEY, project_id TEXT, raw_text TEXT,analysis_json TEXT,updated_at TEXT);
          CREATE TABLE ai_projects(id TEXT PRIMARY KEY,settings_json TEXT);
          CREATE TABLE ai_project_assets(id TEXT PRIMARY KEY,project_id TEXT,kind TEXT,name TEXT,description TEXT,extra_json TEXT,image_url TEXT,created_at TEXT,updated_at TEXT);
          CREATE TABLE ai_project_jobs(id TEXT PRIMARY KEY,project_id TEXT,job_type TEXT,title TEXT,status TEXT,progress INTEGER,payload_json TEXT,error_message TEXT,created_at TEXT,updated_at TEXT);
        """)
        self.db.execute("INSERT INTO ai_project_documents VALUES ('d','p',?,'{}','')", (SOURCE,))
        self.db.execute("INSERT INTO ai_projects VALUES ('p','{}')")
        self.db.execute("INSERT INTO ai_project_assets VALUES ('old','p','character','沈砚','人工描述',?,'manual.png','','')", (json.dumps({"identities": [{"id": "old-look", "name": "古代", "image_url": "look.png"}]}),))
        self.db.commit()
        db = self.db
        def query_all(sql, args=()): return [dict(r) for r in db.execute(sql.replace("%s", "?"), args).fetchall()]
        def query_one(sql, args=()): return next(iter(query_all(sql,args)), None)
        def execute(sql,args=()):
            count = db.execute(sql.replace("%s", "?"),args).rowcount; db.commit(); return count
        class Cursor:
            def execute(self,sql,args=()): self.result=db.execute(sql.replace("%s","?").replace(" FOR UPDATE",""),args)
            def fetchone(self):
                r=self.result.fetchone(); return dict(r) if r else None
            def fetchall(self): return [dict(r) for r in self.result.fetchall()]
            @property
            def rowcount(self): return self.result.rowcount
        @contextmanager
        def transaction():
            try: yield Cursor(); db.commit()
            except Exception: db.rollback(); raise
        for key,value in [("query_one",query_one),("query_all",query_all),("execute_sql",execute),("transaction_cursor",transaction)]:
            p=patch.object(m,key,value);p.start();self.addCleanup(p.stop)
        self.addCleanup(db.close)

    def generate(self):
        with patch.object(m.AssetManifestService.executor,"submit"):
            state=m.AssetManifestService.start("p","d")
        jid=state["job"]["id"]
        with patch.object(m,"request",return_value=json.dumps({"entries":[entry()],"issues":[]})):
            # mocked request still needs an evidence record for parsed checkpoint
            raw=json.loads(self.db.execute("SELECT payload_json FROM ai_project_jobs WHERE id=?",(jid,)).fetchone()[0]);raw["evidence"]=[{}]
            self.db.execute("UPDATE ai_project_jobs SET payload_json=? WHERE id=?",(json.dumps(raw),jid));self.db.commit()
            m.AssetManifestService.run("p",jid)
        return m.AssetManifestService.get("p","d")

    def test_extraction_accepts_known_model_display_fields_and_keeps_warning(self):
        with patch.object(m.AssetManifestService.executor, "submit"):
            state = m.AssetManifestService.start("p", "d")

        def respond(stage, system, user, evidence, checkpoint, **kwargs):
            evidence.append({"stage": stage})
            return json.dumps({"entries": [entry(description="模型附加说明", asset_id="model-id")], "issues": []})

        with patch.object(m, "request", side_effect=respond):
            m.AssetManifestService.run("p", state["job"]["id"])
        job = m.AssetManifestService.get("p", "d")["job"]
        self.assertEqual(job["status"], "awaiting_review", job.get("error"))
        self.assertEqual(job["data"]["entries"][0].get("name"), "沈砚")
        payload = json.loads(self.db.execute("SELECT payload_json FROM ai_project_jobs WHERE id=?", (state["job"]["id"],)).fetchone()[0])
        self.assertEqual(payload["evidence"][-1]["normalization_warnings"], [{"entry": 1, "fields": ["asset_id", "description"]}])

    def confirm(self,state,**choice):
        job=state["job"];return m.AssetManifestService.action("p","d",job["id"],{"action":"confirm","revision":job["revision"],"choices":{job["data"]["entries"][0]["id"]:choice}},"user")

    def test_confirm_reuses_manual_image_and_is_idempotent(self):
        state=self.generate(); self.assertEqual(state["job"]["status"],"awaiting_review",state["job"].get("error"))
        adopted=self.confirm(state,asset_id="old",look_id="old-look")
        again=self.confirm(state,asset_id="old",look_id="old-look")
        self.assertEqual(adopted["manifest"]["version"],again["manifest"]["version"])
        self.assertEqual(self.db.execute("SELECT image_url FROM ai_project_assets").fetchone()[0],"manual.png")
        self.assertEqual(len(adopted["assets"]),1)

    def test_production_extraction_retries_invalid_quote_through_configured_llm(self):
        for repaired in (True, False):
            with self.subTest(repaired=repaired):
                self.db.execute("DELETE FROM ai_project_jobs")
                self.db.commit()
                with patch.object(m.AssetManifestService.executor, "submit"):
                    state = m.AssetManifestService.start("p", "d")
                bad = json.dumps({"entries": [entry(evidence="不存在的拼接出处")], "issues": []})
                good = json.dumps({"entries": [entry()], "issues": []})
                with patch("backend.app.media_studio.provider_bridge.llm_row", return_value={"model": "kimi-k3"}), \
                     patch.object(LlmService, "chat_text", side_effect=[bad, good if repaired else bad]) as network:
                    m.AssetManifestService.run("p", state["job"]["id"])
                self.assertEqual(network.call_count, 2)
                self.assertIn("INVALID_EVIDENCE", network.call_args_list[1].args[1])
                row = self.db.execute("SELECT status,payload_json FROM ai_project_jobs").fetchone()
                self.assertEqual(row["status"], "awaiting_review" if repaired else "failed")
                evidence = json.loads(row["payload_json"])["evidence"]
                self.assertEqual([r["model"] for r in evidence], ["kimi-k3", "kimi-k3"])
                self.assertEqual(evidence[0]["raw"], bad)
                self.assertIn("INVALID_EVIDENCE", evidence[0]["validation_error"])
                self.assertEqual(self.db.execute("SELECT COUNT(*) FROM ai_project_assets").fetchone()[0], 1)

    def test_unknown_binding_rolls_back_without_confirming(self):
        state=self.generate()
        with self.assertRaisesRegex(ValueError,"UNKNOWN_ASSET"):self.confirm(state,asset_id="foreign")
        self.assertIsNone(m.AssetManifestService.get("p","d")["manifest"])

    def test_failed_extraction_resumes_only_matching_source_and_model(self):
        extended = SOURCE + "\n# 第二集\n母亲走进房间。"
        self.db.execute("UPDATE ai_project_documents SET raw_text=?", (extended,))
        self.db.commit()
        with patch.object(m.AssetManifestService.executor, "submit"), \
             patch("backend.app.media_studio.provider_bridge.llm_row", return_value={"model": "kimi-k3"}), \
             patch.object(LlmService, "chat_text", side_effect=[json.dumps({"entries": [entry()], "issues": []}), RuntimeError("empty response")]):
            state = m.AssetManifestService.start("p", "d")
            m.AssetManifestService.run("p", state["job"]["id"])
            self.assertEqual(m.AssetManifestService.get("p", "d")["job"]["status"], "failed")
        for model, should_resume in [("different-model", False), ("kimi-k3", True)]:
            with patch.object(m.AssetManifestService.executor, "submit"), \
                 patch("backend.app.media_studio.provider_bridge.llm_row", return_value={"model": model}):
                resumed = m.AssetManifestService.start("p", "d")
            self.assertEqual(bool(resumed["job"]["data"].get("resumed_from_job_id")), should_resume)
            if not should_resume:
                self.db.execute("DELETE FROM ai_project_jobs WHERE id=?", (resumed["job"]["id"],))
                self.db.commit()
        with patch("backend.app.media_studio.provider_bridge.llm_row", return_value={"model": "kimi-k3"}), \
             patch.object(LlmService, "chat_text", return_value=json.dumps({"entries": [entry("母亲", evidence="母亲走进房间。")], "issues": []})) as network:
            m.AssetManifestService.run("p", resumed["job"]["id"])
        self.assertEqual(network.call_count, 1)
        completed = m.AssetManifestService.get("p", "d")["job"]
        self.assertEqual(completed["status"], "awaiting_review")
        self.assertEqual(len(completed["data"]["coverage"]), 2)
        self.assertEqual(len(completed["data"]["entries"]), 2)

    def test_changed_source_rejects_late_confirmation(self):
        state=self.generate();self.db.execute("UPDATE ai_project_documents SET raw_text='新版本'");self.db.commit()
        with self.assertRaisesRegex(ValueError,"SOURCE_CONFLICT"):self.confirm(state,asset_id="old")

    def test_cancel_and_recovery_preserve_evidence(self):
        with patch.object(m.AssetManifestService.executor,"submit"):
            state=m.AssetManifestService.start("p","d")
        job=state["job"]
        m.AssetManifestService.action("p","d",job["id"],{"action":"cancel","revision":job["revision"]},"user")
        m.AssetManifestService.run("p",job["id"])
        self.assertEqual(m.AssetManifestService.get("p","d")["job"]["status"],"cancelled")
        self.db.execute("UPDATE ai_project_jobs SET status='running'");self.db.commit()
        m.AssetManifestService.recover()
        self.assertEqual(m.AssetManifestService.get("p","d")["job"]["status"],"running")
        with patch.object(m, "owner_alive", return_value=False):
            m.AssetManifestService.recover()
        self.assertEqual(m.AssetManifestService.get("p","d")["job"]["status"],"failed")

    def test_get_does_not_rewrite_stale_document(self):
        self.confirm(self.generate(),asset_id="old",look_id="old-look")
        self.db.execute("UPDATE ai_project_documents SET raw_text='新版本'");self.db.commit()
        before=self.db.execute("SELECT analysis_json FROM ai_project_documents").fetchone()[0]
        self.assertEqual(m.AssetManifestService.get("p","d")["manifest"]["status"],"stale")
        self.assertEqual(before,self.db.execute("SELECT analysis_json FROM ai_project_documents").fetchone()[0])

    def test_rerun_does_not_duplicate_assets_and_restore_gets_new_version(self):
        first = self.confirm(self.generate(), asset_id="old", look_id="old-look")
        second = self.confirm(self.generate())
        self.assertEqual(len(second["assets"]), 1)
        self.assertEqual(second["manifest"]["entries"][0]["look_id"], "old-look")
        job = second["job"]
        restored = m.AssetManifestService.action("p", "d", job["id"], {
            "action": "restore", "revision": job["revision"], "expected_version": second["manifest"]["version"],
            "version": first["manifest"]["version"]}, "user")
        self.assertNotEqual(restored["manifest"]["version"], first["manifest"]["version"])
        self.assertEqual(restored["manifest"]["entries"], first["manifest"]["entries"])


class AcceptanceFixtureTests(unittest.TestCase):
    def test_isolation_remaps_ids_but_never_rewrites_media_links_or_source_provenance(self):
        from backend.tests import asset_pipeline_acceptance as fixture
        job = {"id": "job-original", "project_id": "proj-original", "job_type": "asset_manifest", "status": "awaiting_review",
               "payload_json": json.dumps({"document_id": "doc-original", "entries": []})}
        project = {"id": "proj-original", "name": "original", "settings_json": "{}"}
        doc = {"id": "doc-original", "project_id": "proj-original", "analysis_json": "{}"}
        media = "https://example.test/ast-original/image.png"
        episode = {"id": "ep-original", "project_id": "proj-original", "script_text": SOURCE, "data_json": json.dumps({"source_document_id": "doc-original", "character_look_ids": {"ast-original": "look-original"}, "image_url": media,
                   "prompt_authoring": {"director_plan": {"source_fingerprint": fixture.digest(["doc-original", 0, SOURCE])}}})}
        asset = {"id": "ast-original", "project_id": "proj-original", "image_url": media}
        inserts = []
        class Cursor:
            def execute(self, sql, values): inserts.append((sql, values))
        @contextmanager
        def transaction(): yield Cursor()
        with patch.object(fixture, "query_one", side_effect=[job, project, doc]), \
             patch.object(fixture, "query_all", side_effect=[[episode], [asset]]), \
             patch.object(fixture, "transaction_cursor", transaction):
            cloned = fixture.clone("job-original")
        self.assertNotEqual(cloned["project_id"], "proj-original")
        rows = {}
        for sql, values in inserts:
            table = sql.split()[2]
            fields = sql.split("(", 1)[1].split(")", 1)[0].split(",")
            rows[table] = dict(zip(fields, values))
        self.assertEqual(rows["ai_project_assets"]["image_url"], media)
        data = json.loads(rows["ai_project_episodes"]["data_json"])
        self.assertEqual(data["image_url"], media)
        self.assertEqual(data["source_document_id"], cloned["document_id"])
        self.assertEqual(data["prompt_authoring"]["director_plan"]["source_fingerprint"], fixture.digest([cloned["document_id"], 0, SOURCE]))
        self.assertNotIn("ast-original", data["character_look_ids"])
        settings = json.loads(rows["ai_projects"]["settings_json"])
        self.assertEqual(settings["asset_pipeline_acceptance"]["source_project"], "proj-original")


class WorkshopAssetLifecycle(unittest.TestCase):
    def setUp(self):
        from backend.tests.test_workshop_v7 import TransactionTests
        TransactionTests.setUp(self)
        from backend.app.media_studio.services import workshop_service as service
        self.service = service
        self.db.execute("ALTER TABLE ai_project_jobs ADD COLUMN title TEXT")
        self.db.execute("ALTER TABLE ai_project_jobs ADD COLUMN progress INTEGER")
        row, data = service.WorkshopService.row("p", "e")
        data["beats"][0].update(action=SOURCE, characters=["母亲"], character_ids=["a1"], video_url="old.mp4")
        data["source_document_id"] = "d"
        plan = data["prompt_authoring"]["director_plan"]
        source = service.WorkshopService.source("p", row, data)
        plan["source_fingerprint"] = source["fingerprint"]
        self.db.execute("UPDATE ai_project_episodes SET data_json=?", (json.dumps(data),)); self.db.commit()
        p = patch.object(m.AssetManifestService, "confirmed", return_value=manifest()); p.start(); self.patches.append(p)

    def tearDown(self):
        from backend.tests.test_workshop_v7 import TransactionTests
        TransactionTests.tearDown(self)

    def test_local_audit_apply_keeps_media_and_rollback_invalidates_old_prompt(self):
        service = self.service
        row, before = service.WorkshopService.row("p", "e")
        plan = before["prompt_authoring"]["director_plan"]
        with patch.object(service.WorkshopService.executor, "submit"):
            jid = service.WorkshopService.create("p", "e", "workshop_planning", {
                "expected_revision": plan["revision"], "workflow_id": plan["workflow_id"],
                "max_shots_per_group": 1, "asset_pipeline": True, "audit_only": True,
                "audit_beat_ids": ["b1"], "reuse_existing": True})["job_id"]
        refs = audit.validate_audit(result(), [{"id": "b", "action": SOURCE}], manifest(), SOURCE)[0]["references"]
        refs.append({"manifest_id": "scene", "asset_id": "scene-new", "kind": "scene", "name": "清单场景名",
                     "appearance": "visible", "location": "scene", "evidence": SOURCE})
        checked = audit.project_references(before["beats"][0], refs)
        with patch.object(audit, "audit", return_value=([checked], {"status":"passed", "shots":[{"id":"b1","references":refs,"issues":[]}]})):
            service.WorkshopService.run("p", jid)
        job = self.db.execute("SELECT status,error_message FROM ai_project_jobs WHERE id=?", (jid,)).fetchone()
        self.assertEqual(job["status"], "completed", job["error_message"])
        service.WorkshopService.job_action("p", "e", jid, {"action":"apply", "expected_revision":1})
        _, adopted = service.WorkshopService.row("p", "e")
        self.assertEqual(adopted["beats"][0]["character_ids"], ["a0", "a1"])
        self.assertEqual(adopted["beats"][0]["video_url"], "old.mp4")
        self.assertEqual(adopted["beats"][0]["action"], SOURCE)
        self.assertEqual(adopted["beats"][0]["scene"], before["beats"][0]["scene"])
        self.assertEqual(adopted["beats"][0]["scene_id"], "scene-new")
        self.assertEqual([g["beat_ids"] for g in adopted["prompt_authoring"]["director_plan"]["groups"]],
                         [g["beat_ids"] for g in plan["groups"]])
        service.WorkshopService.update("p", "e", {"expected_revision":2,"restore_asset_history":0,"beat_ids":["b1"]})
        _, restored = service.WorkshopService.row("p", "e")
        self.assertEqual(restored["beats"][0]["character_ids"], ["a1"])
        self.assertEqual(restored["beats"][0]["video_url"], "old.mp4")
        record = restored["prompt_authoring"]["director_plan"]["shot_prompts"].get("b1")
        if record:
            self.assertTrue(record["fingerprint"].startswith("rollback-invalidated:"))
