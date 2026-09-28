"""Opt-in real delivery test; SQLite/media stay under ignored test-results."""
import json
import uuid
from pathlib import Path

import requests

from backend.app.config import Settings
from backend.app.comfy_service import ComfyService
from backend.app.h3_confirmation_jobs import run_creation_confirmation
from backend.app.media_studio.provider_bridge import comfy_row
from backend.app.minimax_h3_confirm_workflow import MODE_ID, confirmation_state
from backend.app.models import JobStatus
from backend.app.resource_storage import BrowserLocalStagingStorage
from backend.app.storage import JobStore


def main():
    root = Path(__file__).resolve().parents[2] / "test-results" / "h3-confirmation"
    evidence = json.loads((root / "state.json").read_text(encoding="utf-8"))
    base_url = str(comfy_row()["base_url"]).rstrip("/")
    if base_url != evidence["base_url"]:
        raise RuntimeError("Configured instance changed")
    queue = requests.get(base_url + "/queue", timeout=15).json()
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("Remote queue busy")
    source = next(r for r in evidence["runs"] if r.get("report", {}).get("segment_count") == 1
                  and r.get("report", {}).get("stage") == "preview_only")
    directory = root / ("business-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    state = confirmation_state([{"graph": source["graph"], "report": source["report"]}], base_url)
    store = JobStore(directory / "isolated.sqlite")
    store.create("source", MODE_ID, "Imported validated test source", "", None, [],
                 {"h3_confirmation": state, "aspect_ratio": "16:9", "seed": 0})
    store.update("source", status=JobStatus.SUCCEEDED)
    child = store.create_confirmation_child("source",
        {"source_revision": state["source_revision"], "refine_quality": 1.0, "request_id": "business-smoke"}, base_url)
    comfy = ComfyService(Settings(comfy_url=base_url, data_dir_override=str(directory)),
                         BrowserLocalStagingStorage(directory / "media"))
    def submitted(prompt_id, client_id, phase):
        store.set_comfy_execution(child["id"], prompt_id, client_id, phase)
        print(json.dumps({"prompt_id": prompt_id, "job_id": child["id"]}), flush=True)
    outputs = run_creation_confirmation(store, comfy, store.get(child["id"], include_references=True),
        lambda stage, progress=None: None, submitted, lambda: False)
    store.update(child["id"], status=JobStatus.SUCCEEDED, outputs=outputs)
    stored = JobStore(directory / "isolated.sqlite").get(child["id"])
    final = stored["options"]["h3_confirmation"]
    result = {"job_id": child["id"], "status": stored["status"], "report": final["report"],
              "media_info": final.get("media_info"), "output": outputs[0]["path"],
              "source_status": store.get("source")["status"]}
    (directory / "evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
