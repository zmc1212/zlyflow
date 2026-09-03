from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db import MysqlDatabase, mysql_settings_from_env_or_docs
from backend.app.director_jobs import job_public_output_url
from backend.app.storage import JobStore, now

PROJECT_ID = "proj-5c424da3f20e4109"


def load_job(store: JobStore, job_id: str) -> dict[str, Any] | None:
    try:
        return store.get(job_id)
    except KeyError:
        return None


def patch_shot(shot: dict[str, Any], store: JobStore) -> bool:
    changed = False
    job_id = str(shot.get("jobId") or "").strip()
    if job_id:
        job = load_job(store, job_id)
        url = job_public_output_url(job, kind="video")
        if url and shot.get("outputVideoUrl") != url:
            shot["outputVideoUrl"] = url
            changed = True
    for take in shot.get("takes") or []:
        take_job_id = str(take.get("jobId") or "").strip()
        if not take_job_id:
            continue
        job = load_job(store, take_job_id)
        url = job_public_output_url(job, kind="video")
        if url and take.get("videoUrl") != url:
            take["videoUrl"] = url
            changed = True
    return changed


def main() -> int:
    mysql = MysqlDatabase(mysql_settings_from_env_or_docs())
    store = JobStore(mysql)
    with mysql.connection() as conn:
        row = conn.execute(
            "SELECT id, title, payload_json FROM director_projects WHERE id = %s",
            (PROJECT_ID,),
        ).fetchone()
        if not row:
            print("project not found")
            return 1
        payload = json.loads(row["payload_json"])
        changed = False
        for scene in payload.get("scenes") or []:
            for shot in scene.get("shots") or []:
                if patch_shot(shot, store):
                    changed = True
        if not changed:
            print("no shot video urls needed updating")
            return 0
        conn.execute(
            "UPDATE director_projects SET payload_json = %s, updated_at = %s WHERE id = %s",
            (json.dumps(payload, ensure_ascii=False), now(), PROJECT_ID),
        )
        print(f"updated video urls for {row['title']!r}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
