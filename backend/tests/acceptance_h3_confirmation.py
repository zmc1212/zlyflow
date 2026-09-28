"""Opt-in live acceptance; only writes this run's evidence under test-results.

python -X utf8 -m backend.tests.acceptance_h3_confirmation preview --reference FILE.png
python -X utf8 -m backend.tests.acceptance_h3_confirmation status
python -X utf8 -m backend.tests.acceptance_h3_confirmation refine --quality 1
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

import requests

from backend.app.media_studio.provider_bridge import comfy_row
from backend.app.minimax_h3_confirm_workflow import (
    ADAPTER_CLASS, build_confirmation_preview, build_confirmation_refine,
    validate_confirmation_report,
)

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "test-results" / "h3-confirmation" / "state.json"


def write(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preview", "status", "refine", "missing-cache", "repeat-preview"))
    parser.add_argument("--reference")
    parser.add_argument("--segments", type=int, choices=(1, 2), default=1)
    parser.add_argument("--quality", type=float, choices=(1.0, 2.0), default=2.0)
    args = parser.parse_args()
    base_url = str(comfy_row()["base_url"]).rstrip("/")
    session = requests.Session()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"runs": []}
    if state.get("base_url", base_url) != base_url:
        raise RuntimeError("ComfyUI instance changed; restore previous settings")
    state["base_url"] = base_url
    if args.action == "status":
        summaries = []
        for run in state["runs"]:
            response = session.get(base_url + "/history/" + run["prompt_id"], timeout=20)
            response.raise_for_status()
            history = response.json().get(run["prompt_id"])
            if history is None:
                summaries.append({"prompt_id": run["prompt_id"], "state": "pending"})
                continue
            run["history"] = history
            status = history.get("status", {}).get("status_str")
            outputs = history.get("outputs", {})
            reports = outputs.get("12", {}).get("zly_h3_confirmation", [])
            if status == "success":
                if len(reports) != 1:
                    raise RuntimeError("Successful task missing authoritative stage report")
                validate_confirmation_report(reports[0], run["stage"])
                if not outputs.get("7"):
                    raise RuntimeError("Missing saved video output")
                run["report"] = reports[0]
            errors = [m[1] for m in history.get("status", {}).get("messages", [])
                      if m[0] == "execution_error"]
            summaries.append({"prompt_id": run["prompt_id"], "state": status,
                              "report": reports, "video": outputs.get("7"),
                              "errors": [{k: e.get(k) for k in ("node_id", "exception_type", "exception_message")} for e in errors]})
        write(state)
        print(json.dumps(summaries, ensure_ascii=False, indent=2))
        return
    response = session.get(base_url + "/object_info/" + ADAPTER_CLASS, timeout=20)
    response.raise_for_status()
    if ADAPTER_CLASS not in response.json():
        raise RuntimeError("Adapter not loaded; restart the existing ComfyUI while idle")
    response = session.get(base_url + "/queue", timeout=20)
    response.raise_for_status()
    queue = response.json()
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("Remote queue is busy; acceptance will not add competing GPU work")
    key = uuid.uuid4().hex
    if args.action == "preview":
        if not args.reference:
            parser.error("--reference must name an existing uploaded test image")
        graph = build_confirmation_preview({
            "version": 5, "timelineMode": "prompt_batch", "totalFrames": 53 * args.segments,
            "global": {"refs": [{"index": 0, "imageFile": args.reference, "type": "input", "subfolder": ""}], "prompt": ""},
            "segments": [{"id": f"shot-{i + 1}", "start": 53 * i, "length": 53, "frameCount": 53,
                          "durationSec": 53 / 24, "prompt": "A person looks calmly toward the camera, natural subtle motion, quiet room ambience.",
                          "refs": [], "continuityFromPrev": False} for i in range(args.segments)],
        }, "16:9", 0, key, "video/ZLY_ConfirmedAcceptance_" + key)
        stage = "preview_only"
    else:
        sources = [r for r in state["runs"] if r.get("stage") == "preview_only" and r.get("report")]
        if not sources:
            raise RuntimeError("Run status after a successful first-pass task before confirming")
        source = sources[-1]
        if args.action == "repeat-preview":
            import copy
            graph = copy.deepcopy(source["graph"])
            graph["7"]["inputs"]["filename_prefix"] = "video/ZLY_ConfirmedAcceptance_repeat_" + key
            stage = "preview_only"
        else:
            graph = build_confirmation_refine(source["graph"], source["report"], args.quality,
                                              "video/ZLY_ConfirmedAcceptance_" + key)
            stage = "refine_only"
            if args.action == "missing-cache":
                # A dedicated nonexistent namespace; never removes user/test caches.
                graph["12"]["inputs"]["cache_key"] = key
    response = session.post(base_url + "/prompt", json={"prompt": graph, "client_id": "zly-confirmation-acceptance"}, timeout=30)
    response.raise_for_status()
    result = response.json()
    if not result.get("prompt_id") or result.get("node_errors"):
        raise RuntimeError(str(result))
    state["runs"].append({"prompt_id": result["prompt_id"], "stage": stage, "graph": graph,
                         "scenario": args.action})
    write(state)
    print(json.dumps({"prompt_id": result["prompt_id"], "stage": stage}, ensure_ascii=False))


if __name__ == "__main__":
    main()
