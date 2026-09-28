"""Versioned author recipe; deliberately independent of Director Accel presets."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .models import JobMode
from .workflow_registry import h3_dimensions, h3_length, normalize_options

MODE = JobMode.MINIMAX_H3_DIRECTOR_REFINE_ACCEL_R2V
RECIPE_VERSION = "director-refine-accel@1"
RECIPE_DIR = Path(__file__).resolve().parents[1] / "workflows" / "director_refine_accel"
FINAL_NODE = "7"
FIRST_PASS_NODE = "20"
REFINE_NODES = {"23", "30", "31", "32", "33", "38", "19", "20"}


def baseline() -> dict[str, Any]:
    return json.loads((RECIPE_DIR / "baseline.api.json").read_text(encoding="utf-8"))


def build_refine_workflow(
    timeline: dict[str, Any], options: dict[str, Any], filename_prefix: str,
    seed: int = 666,
) -> dict[str, Any]:
    if options.get("recipe_version", RECIPE_VERSION) != RECIPE_VERSION:
        raise ValueError("不支持的 H3 二采配方版本")
    refs = (timeline.get("global") or {}).get("refs") or []
    segments = timeline.get("segments") or []
    if not segments or any(not (segment.get("refs") or refs) for segment in segments):
        raise ValueError("H3 Director 二采加速版每段至少需要 1 张参考图，不会自动切换文生视频")
    if any(segment.get("taskType") not in (None, "", "r2v", "r2v — 参考主体生视频(Reference to Video)") for segment in segments):
        raise ValueError("H3 Director 二采加速版仅支持 R2V")
    values = normalize_options(MODE, {key: options[key] for key in
        ("aspect_ratio", "refine_enabled", "refine_quality", "recipe_version") if key in options})
    width, height = h3_dimensions(values)
    timeline = copy.deepcopy(timeline)
    timeline.update(width=width, height=height, refMaxSize=max(width, height), frameRate=24)
    timeline["output"] = {"mode": "fixed", "aspectRatio": values["aspect_ratio"],
        "width": width, "height": height, "megapixels": 0.4, "multiple": 32,
        "longEdge": max(width, height), "maxExportFrames": 0, "exportMode": "all",
        "audioMode": "source", "continuityEnabled": True, "continuityOverlapFrames": 22}
    # Do not let stale UI workspace copies override the supplied task segments.
    timeline.pop("batchWorkspaces", None)
    graph = baseline()
    director = graph["12"]["inputs"]
    director.update(width=width, height=height, ref_max_size=max(width, height), seed=seed,
        total_frames=int(timeline["totalFrames"]), timeline_data=json.dumps(timeline, ensure_ascii=False),
        global_prompt=str((timeline.get("global") or {}).get("prompt") or ""),
        clear_vram_before_refine=False, clear_vram_before_face_refine=False,
        cache_frames_codec="raw", export_pre_face_refine=False)
    graph["7"]["inputs"]["filename_prefix"] = filename_prefix + ("-refined" if values["refine_enabled"] else "-first")
    if values["refine_enabled"]:
        graph["38"]["inputs"].update(megapixels=float(values["refine_quality"]),
            confirm_first_pass=False, enable_latent_chunking=False, enable_tiling=False,
            tile_count=2, tile_overlap=128, seed=0)
        graph["20"]["inputs"]["filename_prefix"] = filename_prefix + "-first"
    else:
        director.pop("refine")
        for node in REFINE_NODES:
            graph.pop(node)
    return graph


def build_refine_shot(prompt: str, references: list[str], options: dict[str, Any], seed: int,
                      filename_prefix: str = "video/ZLY_DirectorRefine") -> dict[str, Any]:
    if not 1 <= len(references) <= 9:
        raise ValueError("H3 Director 二采加速版需要 1–9 张参考图")
    frames = h3_length({"duration": 5, **options})
    refs = [{"index": index, "imageFile": name, "type": "input", "subfolder": ""}
            for index, name in enumerate(references)]
    timeline = {"version": 5, "timelineMode": "prompt_batch", "totalFrames": frames,
        "global": {"refs": refs, "prompt": "", "commonEnabled": True},
        "segments": [{"id": "shot-1", "start": 0, "length": frames, "frameCount": frames,
            "durationSec": frames / 24, "prompt": prompt, "refs": [], "continuityFromPrev": False}]}
    return build_refine_workflow(timeline, options, filename_prefix, seed)


def is_refine_graph(graph: dict[str, Any] | None) -> bool:
    return bool(graph and graph.get("16", {}).get("class_type") == "LoraLoaderModelOnly"
                and graph.get("12", {}).get("class_type") == "MiniMaxH3Director"
                and graph.get("7", {}).get("class_type") == "SaveVideo")


def validate_refine_dependencies(graph: dict[str, Any], object_info: dict[str, Any]) -> None:
    """Validate exact installed node inputs/models without substituting dependencies."""
    missing = []
    for node in graph.values():
        kind = node["class_type"]
        schema = object_info.get(kind)
        if not schema:
            missing.append(kind)
            continue
        inputs = {**schema.get("input", {}).get("required", {}), **schema.get("input", {}).get("optional", {})}
        for key, value in node["inputs"].items():
            if key not in inputs:
                missing.append(f"{kind}.{key}")
            elif isinstance(value, str) and isinstance(inputs[key][0], list) and value not in inputs[key][0]:
                missing.append(f"{kind}.{key}={value}")
            elif isinstance(value, (int, float)) and not isinstance(value, bool) and len(inputs[key]) > 1:
                limits = inputs[key][1] if isinstance(inputs[key][1], dict) else {}
                if value < limits.get("min", float('-inf')) or value > limits.get("max", float('inf')):
                    missing.append(f"{kind}.{key}={value} 超出远端范围")
    if missing:
        raise ValueError("远端二采工作流依赖缺失或不兼容：" + "；".join(dict.fromkeys(missing)))
