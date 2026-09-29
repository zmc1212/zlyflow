"""Opt-in, read-only production sample comparison. No assets/shots/media are adopted.

python -X utf8 -m backend.tests.asset_pipeline_live_probe
Evidence is stored as project jobs, rather than temporary files or credentials.
"""
import json
import uuid
from copy import deepcopy

from backend.app.media_studio.db import query_one, query_all, execute_sql, now_str
from backend.app.media_studio.services.shot_asset_audit import audit
from backend.app.media_studio.services.workshop_contract import digest


def main():
    project = "proj-0f9c8015281149f0"
    doc = query_one("SELECT * FROM ai_project_documents WHERE id=%s AND project_id=%s", ("doc-e2e8c8efba96", project))
    analysis = json.loads(doc["analysis_json"])
    episode = analysis["episodes"][0]
    assets = query_all("SELECT * FROM ai_project_assets WHERE project_id=%s", (project,))
    entries = []
    for asset in assets:
        if asset["kind"] != "character":
            continue
        looks = json.loads(asset.get("extra_json") or "{}").get("identities") or [{"id": None, "name": "未明确"}]
        for look in looks:
            entries.append({"id": "probe-" + digest([asset["id"], look["id"]])[:12], "kind": "character",
                            "name": asset["name"], "era": look.get("name"), "asset_id": asset["id"], "look_id": look["id"]})
    manifest = {"version": "probe-" + digest(entries), "entries": entries}
    samples = [{**deepcopy(s), "id": "source-" + str(s["shot_num"])} for s in episode["shots"] if s["shot_num"] in [8, 23]]
    samples.append({"id": "negative", "action": "画面只拍沈砚的背影。母亲在门外画外说话，没有入画。沈砚提到村民甲，村民甲没有出现。", "dialogue": "母亲（画外）：砚儿。沈砚：村民甲还没来。", "characters": ["沈砚"]})
    source = episode["body"] + "\n反例独立场景：" + samples[-1]["action"] + samples[-1]["dialogue"]
    jid = "job-" + uuid.uuid4().hex[:12]
    payload = {"document_id": doc["id"], "source_revision": (analysis.get("script_development") or {}).get("revision"),
               "source_sha256": digest(source), "manifest": manifest, "samples": samples,
               "expected": {"source-8": "沈砚古代、母亲可见", "source-23": "母亲开场可见性需人工确认，不按姓名直接补", "negative": "沈砚可见、母亲画外、村民甲提及"},
               "runs": [], "evidence": [], "note": "只读核对对照，清单为现有资产快照；未验证新拆镜全过程或成片。费用接口未返回，不能推算实际账单。"}
    execute_sql("INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,payload_json,created_at,updated_at) VALUES (%s,%s,'asset_pipeline_probe',%s,'running',0,%s,%s,%s)",
                (jid, project, "资产核对三次真实模型对照", json.dumps(payload, ensure_ascii=False), now_str(), now_str()))
    def save():
        execute_sql("UPDATE ai_project_jobs SET payload_json=%s,updated_at=%s WHERE id=%s AND project_id=%s", (json.dumps(payload, ensure_ascii=False), now_str(), jid, project))
    try:
        for index in range(3):
            output, checked = audit(samples, source, manifest, payload["evidence"], save)
            summary = [{"id": b["id"], "visible": b["characters"], "look_ids": b["character_look_ids"],
                        "roles": [{k: r[k] for k in ("name", "appearance", "era")} for r in b["asset_references"]],
                        "issues": checked["shots"][i]["issues"]} for i, b in enumerate(output)]
            payload["runs"].append({"run": index+1, "summary": summary, "audit": checked})
            save()
            print(json.dumps({"job_id": jid, "run": index+1, "summary": summary}, ensure_ascii=False), flush=True)
        execute_sql("UPDATE ai_project_jobs SET status='completed',progress=100 WHERE id=%s", (jid,))
    except Exception as err:
        payload["failure"] = str(err)
        save()
        execute_sql("UPDATE ai_project_jobs SET status='failed',error_message=%s WHERE id=%s", (str(err), jid))
        raise


if __name__ == "__main__":
    main()
