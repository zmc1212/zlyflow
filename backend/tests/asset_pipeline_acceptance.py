"""Opt-in isolated acceptance fixture; never adopts changes into the source project.

python -X utf8 -m backend.tests.asset_pipeline_acceptance --candidate JOB_ID
Copies only project metadata, one document, one episode and existing media links.
The named acceptance project remains available for browser review.
"""
import argparse
from copy import deepcopy
import json
import uuid

from backend.app.media_studio.db import query_one, query_all, transaction_cursor, now_str
from backend.app.media_studio.services.workshop_contract import digest


def clone(candidate_id):
    job = query_one("SELECT * FROM ai_project_jobs WHERE id=%s", (candidate_id,))
    if not job or job["job_type"] != "asset_manifest" or job["status"] != "awaiting_review":
        raise ValueError("Only a finished, unadopted asset candidate can seed acceptance")
    payload = json.loads(job["payload_json"])
    source_project = job["project_id"]
    project = query_one("SELECT * FROM ai_projects WHERE id=%s", (source_project,))
    document = query_one("SELECT * FROM ai_project_documents WHERE id=%s AND project_id=%s", (payload["document_id"], source_project))
    episodes = query_all("SELECT * FROM ai_project_episodes WHERE project_id=%s ORDER BY episode_num", (source_project,))
    episode = next(e for e in episodes if json.loads(e["data_json"]).get("source_document_id") == document["id"])
    assets = query_all("SELECT * FROM ai_project_assets WHERE project_id=%s", (source_project,))
    mapping = {row["id"]: prefix + uuid.uuid4().hex[:16] for prefix, rows in [
        ("proj-", [project]), ("doc-", [document]), ("ep-", [episode]), ("ast-", assets), ("job-", [job])
    ] for row in rows}
    def remap(value):
        if isinstance(value, dict):
            return {remap(k): remap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [remap(v) for v in value]
        if isinstance(value, str):
            if value.startswith(("https://", "http://", "/api/", "data:")):
                return value
            for old, new in mapping.items():
                value = value.replace(old, new)
            return value
        return value
    project["name"] = "资产链路隔离验收 · " + now_str()
    project["description"] = "自动化验收副本。来源 " + source_project + "；不覆盖原工程，媒体仅复用链接。"
    settings = json.loads(project.get("settings_json") or "{}")
    settings["asset_pipeline_acceptance"] = {"source_project": source_project, "source_candidate": candidate_id}
    project["settings_json"] = json.dumps(settings, ensure_ascii=False)
    analysis = json.loads(document["analysis_json"])
    analysis.pop("asset_manifest", None)
    analysis.pop("asset_manifest_history", None)
    document["analysis_json"] = json.dumps(analysis, ensure_ascii=False)
    payload["base_version"] = None
    job["payload_json"] = json.dumps(payload, ensure_ascii=False)
    with transaction_cursor() as cursor:
        for table, rows in [("ai_projects", [project]), ("ai_project_documents", [document]),
                            ("ai_project_assets", assets), ("ai_project_episodes", [episode]), ("ai_project_jobs", [job])]:
            for original in rows:
                row = {k: json.dumps(remap(json.loads(v)), ensure_ascii=False) if k.endswith("_json") and v else remap(v)
                       for k, v in deepcopy(original).items()}
                if table == "ai_projects":
                    row["description"] = project["description"]
                    copied_settings = json.loads(row["settings_json"])
                    copied_settings["asset_pipeline_acceptance"] = settings["asset_pipeline_acceptance"]
                    row["settings_json"] = json.dumps(copied_settings, ensure_ascii=False)
                if table == "ai_project_episodes":
                    copied_data = json.loads(row["data_json"])
                    copied_plan = (copied_data.get("prompt_authoring") or {}).get("director_plan") or {}
                    source_episode = next((e for e in analysis.get("episodes", []) if e.get("episode_num") == episode.get("episode_num")), {})
                    source_text = source_episode.get("body") or episode.get("script_text") or ""
                    source_revision = (analysis.get("script_development") or {}).get("revision") or copied_data.get("script_revision") or 0
                    # Remapping a document ID is not a creative source edit. Preserve
                    # genuine stale state, but do not manufacture it in the clone.
                    if copied_plan.get("source_fingerprint") == digest([document["id"], source_revision, source_text]):
                        copied_plan["source_fingerprint"] = digest([mapping[document["id"]], source_revision, source_text])
                    row["data_json"] = json.dumps(copied_data, ensure_ascii=False)
                row.update(created_at=now_str(), updated_at=now_str())
                fields = list(row)
                cursor.execute("INSERT INTO " + table + " (" + ",".join(fields) + ") VALUES (" + ",".join(["%s"] * len(fields)) + ")", tuple(row[k] for k in fields))
    return {"project_id": mapping[source_project], "document_id": mapping[document["id"]],
            "episode_id": mapping[episode["id"]], "candidate_id": mapping[candidate_id], "name": project["name"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    print(json.dumps(clone(args.candidate), ensure_ascii=False))
