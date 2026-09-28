"""Read-only audit of the installed H3 confirmation surface; never queues a graph.

Run: python -X utf8 -m backend.scripts.inspect_h3_confirmation
This is evidence collection, not a strict-confirmation capability handshake.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import requests

from backend.app.minimax_h3_director_refine_workflow import build_refine_shot

REFINE_JS = "/extensions/ComfyUI_MiniMaxH3_Director/minimax_refine.js"
CACHE_STATUS = "/minimax/director/first_pass_cache_status"
# A read-only query namespace, NOT a replacement for the author graph node ID.
PROBE_NODE_ID = "2147483000"


def inspection_payload(quality: float = 2.0) -> dict[str, Any]:
    """Synthetic missing-cache witness matching the installed frontend payload.

    No media is uploaded. This cannot establish that a real latent is reusable.
    SelfLift, Semantic Bridge and external groups are absent in this recipe.
    """
    if quality not in (1.0, 2.0):
        raise ValueError("refine_quality must be 1.0 or 2.0")
    graph = build_refine_shot(
        "protocol inspection", ["protocol-inspection-not-uploaded.png"],
        {"refine_quality": str(float(quality))}, 0,
    )
    director = graph["12"]["inputs"]
    refine = graph["38"]["inputs"]
    keys = (
        "timeline_data", "task_type", "global_prompt", "total_frames", "frame_rate",
        "width", "height", "ref_max_size", "seed", "cfg", "steps", "sampler",
        "scheduler", "shift_video", "shift_audio",
    )
    witness = {key: value for key, value in refine.items() if not isinstance(value, list)}
    witness.update(
        enabled=True, confirm_first_pass=True,
        has_sample_model="refine_model" in refine,
        has_upscale_model="upscale_model" in refine,
        has_sigmas_tensor="sigmas" in refine,
    )
    return {
        **{key: director[key] for key in keys},
        "node_id": PROBE_NODE_ID, "sigmas_linked": "sigmas" in director,
        "selflift": None, "semantic_bridge": None, "refine": witness,
    }


def inspect_protocol(base_url: str, session: Any = None) -> dict[str, Any]:
    session = session or requests.Session()
    base_url = base_url.rstrip("/")
    response = session.get(base_url + REFINE_JS, timeout=20)
    response.raise_for_status()
    source = response.text
    response = session.get(base_url + "/object_info/MiniMaxH3DirectorRefine", timeout=20)
    response.raise_for_status()
    schema = response.json()["MiniMaxH3DirectorRefine"]["input"]
    inputs = {**schema.get("required", {}), **schema.get("optional", {})}
    # Do not send even a status query if the installed JS no longer advertises it.
    if CACHE_STATUS not in source:
        raise ValueError("Installed frontend does not advertise the known cache status route")
    samples = []
    for quality in (1.0, 2.0):
        response = session.post(base_url + CACHE_STATUS, json=inspection_payload(quality), timeout=20)
        response.raise_for_status()
        samples.append({"quality": quality, "response": response.json()})
    return {
        "base_url": base_url,
        "frontend_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "frontend_routes": sorted(set(re.findall(r'api\.fetchApi\("([^\"]+)"', source))),
        "refine_inputs": sorted(inputs),
        "confirm_first_pass": inputs.get("confirm_first_pass"),
        "synthetic_cache_samples": samples,
        "strict_confirmation_verified": False,
        "release_blockers": [
            "Python execution source and atomic stage enforcement not verified",
            "Cache hit before preview and cache loss before refinement not verified",
            "Cache identity, expiry, restart persistence and execution reports not verified",
            "Model loading, real 1/2 MP refinement and desktop acceptance not verified",
        ],
    }


def main() -> None:
    # Read actual settings on every invocation; never assume localhost or switch it.
    from backend.app.media_studio.provider_bridge import comfy_row

    result = inspect_protocol(str(comfy_row()["base_url"]))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
