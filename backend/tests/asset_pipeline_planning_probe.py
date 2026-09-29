"""Opt-in, read-only three-run old/new planning comparison on adopted source scenes.

python -X utf8 -m backend.tests.asset_pipeline_planning_probe
Uses an explicitly labelled reference fixture, not a production confirmed manifest.
Stores exact calls and candidates in a project verification job; never adopts.
"""
import argparse
import json
import re
import time
import uuid
from copy import deepcopy
from unittest.mock import patch

from backend.app.media_studio.db import query_one, query_all, execute_sql, now_str
from backend.app.media_studio.provider_bridge import llm_row
from backend.app.media_studio.services.llm_service import LlmService
from backend.app.media_studio.services.shot_asset_audit import plan_shots, audit
from backend.app.media_studio.services.workshop_contract import digest
from backend.app.llm_request_policy import chat_policy, chat_parameters


def main(repeat=None, source_job=None, token_budget=None):
    project = "proj-0f9c8015281149f0"
    doc = query_one("SELECT * FROM ai_project_documents WHERE id=%s AND project_id=%s", ("doc-e2e8c8efba96", project))
    analysis = json.loads(doc["analysis_json"])
    body = analysis["episodes"][0]["body"]
    # Exact adopted scene text, including every dialogue line, without old shot prompts.
    headings = list(re.finditer(r"(?m)^#{1,6}\s*场景([0-9]+)[｜|：:].*$", body))
    excerpts = [body[m.start():headings[i+1].start() if i+1 < len(headings) else len(body)]
                for i, m in enumerate(headings) if int(m.group(1)) in (3, 5)]
    if len(excerpts) != 2:
        raise ValueError("Expected the two labelled adopted scenes; refusing a guessed sample")
    episode = {"episode_num": 1, "title": "只读规划对照：母亲出现与最后半袋米", "body": "\n".join(excerpts)}
    entries = []
    for asset in query_all("SELECT * FROM ai_project_assets WHERE project_id=%s", (project,)):
        looks = json.loads(asset.get("extra_json") or "{}").get("identities") if asset["kind"] == "character" else None
        for look in looks or [{"id": None, "name": "未明确"}]:
            entries.append({"id": "fixture-" + digest([asset["id"], look["id"]])[:12], "kind": asset["kind"],
                            "name": asset["name"], "identity": asset["name"], "era": look.get("name"),
                            "asset_id": asset["id"], "look_id": look["id"]})
    manifest = {"version": "fixture-" + digest(entries), "entries": entries}
    jid = "job-" + uuid.uuid4().hex[:12]
    provider = llm_row() or {}
    previous = None
    if source_job:
        row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s AND project_id=%s", (source_job, project))
        previous = json.loads(row["payload_json"]) if row else {}
        if previous.get("scope") != "planning-ab" or previous.get("model") != provider.get("model"):
            raise ValueError("Comparison snapshot/model mismatch")
        episode, manifest = deepcopy(previous["source"]), deepcopy(previous["manifest_fixture"])
    policy = chat_policy(provider.get("model") or "", provider.get("base_url") or "")
    payload = {"scope": "planning-ab", "document_id": doc["id"], "source_revision": analysis.get("script_development", {}).get("revision"),
               "source": episode, "source_fingerprint": digest(episode), "manifest_fixture": manifest,
               "model": provider.get("model"), "transport_calls": [], "runs": [],
               "note": "Existing asset snapshot is a labelled comparison fixture, not an adopted production manifest. No adoption or generation of media. Costs unavailable."}
    payload.update(source_job=source_job, token_budget=token_budget, validation_revision="source-identities-dialogue-2026-09-28", repeats=[repeat] if repeat else [1, 2, 3])
    if previous and previous.get("token_budget") == token_budget:
        payload["runs"] = [{**deepcopy(r), "reused_from_job_id": source_job} for r in previous["runs"]
                           if r.get("status") == "completed" and r["route"] == "old" and r["run"] in payload["repeats"]]
    execute_sql("INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,payload_json,created_at,updated_at) VALUES (%s,%s,'asset_pipeline_probe',%s,'running',0,%s,%s,%s)",
                (jid, project, "原剧本拆镜三轮旧新对照（只读）", json.dumps(payload, ensure_ascii=False), now_str(), now_str()))
    def save():
        execute_sql("UPDATE ai_project_jobs SET payload_json=%s,updated_at=%s WHERE id=%s", (json.dumps(payload, ensure_ascii=False), now_str(), jid))
    original_chat = LlmService.chat_text
    active = {}
    def capture(system, user, **kwargs):
        if (llm_row() or {}).get("model") != payload["model"]:
            raise ValueError("MODEL_CHANGED: comparison requires the same configured model")
        original_parameters = {k:v for k,v in kwargs.items() if k != "meta_out"}
        if token_budget:
            kwargs["max_tokens"] = max(kwargs.get("max_tokens", 6000), token_budget)
        record = {**active, "system": system, "user": user, "parameters": {k:v for k,v in kwargs.items() if k != "meta_out"}, "original_parameters": original_parameters,
                  "effective_parameters": chat_parameters(policy, temperature=kwargs.get("temperature", 0.4),
                      max_tokens=kwargs.get("max_tokens", 6000), reasoning_effort=provider.get("reasoning_effort")), "status": "running"}
        payload["transport_calls"].append(record)
        kwargs.setdefault("meta_out", {})
        record["response_metadata"] = kwargs["meta_out"]
        save()
        start = time.monotonic()
        try:
            raw = original_chat(system, user, **kwargs)
            record.update(raw=raw, status="returned")
            return raw
        except Exception as error:
            record.update(status="failed", error_type=type(error).__name__)
            raise
        finally:
            record["elapsed_ms"] = round((time.monotonic()-start)*1000)
            save()
    print(jid, flush=True)
    with patch.object(LlmService, "chat_text", new=staticmethod(capture)):
        for run in payload["repeats"]:
            for route in ("old", "new"):
                if any(r["run"] == run and r["route"] == route and r.get("status") == "completed" for r in payload["runs"]):
                    continue
                active.update(run=run, route=route)
                result = {"run": run, "route": route, "evidence": []}
                payload["runs"].append(result)
                try:
                    if route == "old":
                        shots = LlmService.plan_episode_shots(deepcopy(episode), aspect_ratio="16:9")
                    else:
                        shots = plan_shots(deepcopy(episode), "16:9", manifest, "minimax-h3-director-accel-r2v", result["evidence"], save)
                        result["before_audit"] = deepcopy(shots)
                        shots, result["audit"] = audit([{**s, "id": f"shot-{i}"} for i,s in enumerate(shots, 1)], episode["body"], manifest, result["evidence"], save)
                    result.update(status="completed", shots=shots, shot_count=len(shots), duration=sum(s.get("duration_sec", 0) for s in shots))
                except Exception as error:
                    result.update(status="failed", error=str(error))
                save()
                print(json.dumps({k:v for k,v in result.items() if k in ("run", "route", "status", "error", "shot_count", "duration")}, ensure_ascii=False), flush=True)
    failed = any(r["status"] == "failed" for r in payload["runs"])
    execute_sql("UPDATE ai_project_jobs SET status=%s,progress=100 WHERE id=%s", ("failed" if failed else "completed", jid))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, choices=[1, 2, 3])
    parser.add_argument("--source-job")
    parser.add_argument("--token-budget", type=int, choices=[32768])
    args = parser.parse_args()
    main(args.repeat, args.source_job, args.token_budget)
