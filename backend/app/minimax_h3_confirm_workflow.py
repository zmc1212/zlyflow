"""Copied author recipe for the separately installed confirmation adapter.

Not registered as a public workflow until real remote and UI acceptance passes.
Legacy director-refine-accel@1 is intentionally untouched.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from typing import Any

from .minimax_h3_director_refine_workflow import build_refine_workflow

RECIPE_VERSION = "director-confirm-accel@1"
ADAPTER_CLASS = "ZlyH3ConfirmedDirector"
PROTOCOL = "zly-h3-confirmation@1"
W4A8_LOADER = "ExperimentalW4A8UNETLoader"
MODE_ID = "minimax-h3-director-confirm-accel-r2v"


def is_confirmation_graph(graph):
    return bool(graph and graph.get("12", {}).get("class_type") == ADAPTER_CLASS)


def build_confirmation_shot(prompt, references, options, seed, filename_prefix="video/ZLY_Confirmed"):
    from .workflow_registry import h3_length
    frames = h3_length({"duration": 5, **options})
    refs = [{"index": i, "imageFile": name, "type": "input", "subfolder": ""}
            for i, name in enumerate(references)]
    timeline = {"version": 5, "timelineMode": "prompt_batch", "totalFrames": frames,
        "global": {"refs": refs, "prompt": ""},
        "segments": [{"id": "shot-1", "start": 0, "length": frames, "frameCount": frames,
                      "durationSec": frames / 24, "prompt": prompt, "refs": [], "continuityFromPrev": False}]}
    return build_confirmation_preview(timeline, options.get("aspect_ratio", "16:9"), seed,
                                      uuid.uuid4().hex, filename_prefix)


def execution_report(graph, history):
    reports = (history.get("outputs") or {}).get("12", {}).get("zly_h3_confirmation", [])
    if len(reports) != 1:
        raise ValueError("缺少唯一的 H3 阶段执行报告")
    report = reports[0]
    inputs = graph["12"]["inputs"]
    validate_confirmation_report(report, inputs["stage"])
    if report["cache_key"] != inputs["cache_key"]:
        raise ValueError("阶段报告与冻结工作流缓存不一致")
    if inputs["stage"] == "refine_only" and (
        report["source_revision"] != inputs["source_revision"]
        or report["instance_id"] != inputs["expected_instance_id"]
    ):
        raise ValueError("二采来源或实例不一致")
    return copy.deepcopy(report)


def executed_segment_frames(history, segment_count, *, reused_frame_counts=None):
    """Read actual boundaries from the pinned author's report, not assumed VAE padding."""
    values = (history.get("outputs") or {}).get("8", {}).get("text") or []
    text = "\n".join(map(str, values)) if isinstance(values, list) else str(values)
    rows = re.findall(r"^\s*#(\d+) \[(\d+):(\d+)\] (\d+)f\b", text, re.MULTILINE)
    if len(rows) != segment_count:
        raise ValueError("缺少实际分段帧数，不能确认素材边界")
    end, counts = 0, []
    for expected, (index, start, stop, count) in enumerate(rows, 1):
        if int(index) != expected or int(start) != end or int(stop) - int(start) != int(count):
            raise ValueError("实际分段边界不连续")
        counts.append(int(count))
        end = int(stop)
    # Continuity samples an extra guide window. The author's timeline header
    # precedes execution; its explicit export count supersedes that segment.
    seen = set()
    for index, count in re.findall(r"^Seg #(\d+): continuity guide[^\n]*→ export (\d+)f\b", text, re.MULTILINE):
        index, count = int(index), int(count)
        if index < 1 or index > segment_count or index in seen or count <= 0:
            raise ValueError("连续镜头导出帧数无效")
        seen.add(index)
        counts[index - 1] = count
    totals = re.findall(r"Export mode: all — merged (\d+) frame\(s\)", text)
    if reused_frame_counts is not None:
        # Cache-only refinement preserves the verified preview's temporal layout.
        # Its author report omits the continuity export overrides on cache hits.
        if (len(reused_frame_counts) != segment_count
                or any(type(n) is not int or n <= 0 for n in reused_frame_counts)
                or len(totals) != 1
                or sum(reused_frame_counts) != int(totals[0])
                or any(counts[i - 1] != reused_frame_counts[i - 1] for i in seen)):
            raise ValueError("缓存分段帧数与二采导出不一致")
        counts = list(reused_frame_counts)
    if totals and (len(totals) != 1 or sum(counts) != int(totals[0])):
        raise ValueError("分段帧数与实际导出总帧数不一致")
    return counts


def confirmation_revision(groups):
    return hashlib.sha256(json.dumps(
        [{"graph": g["graph"], "report": g["report"]} for g in groups],
        sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def confirmation_state(groups, base_url):
    for group in groups:
        validate_confirmation_report(group["report"], "preview_only")
    return {"recipe_version": RECIPE_VERSION, "stage": "preview_only",
            "state": "awaiting_confirmation", "base_url": base_url.rstrip("/"),
            "groups": copy.deepcopy(groups), "source_revision": confirmation_revision(groups)}


def validate_refine_request(state, request, current_url):
    if set(request) - {"refine_quality", "source_revision", "request_id"}:
        raise ValueError("确认请求仅允许画质、来源版本和幂等标识")
    quality = request.get("refine_quality", 2.0)
    if isinstance(quality, bool) or quality not in (1.0, 2.0):
        raise ValueError("二采画质仅支持 1 MP 或 2 MP")
    key = request.get("request_id")
    if not isinstance(key, str) or not 1 <= len(key) <= 128:
        raise ValueError("缺少有效幂等请求标识")
    if not state or state.get("stage") != "preview_only" or not state.get("groups"):
        raise ValueError("该任务没有可确认的一采，请重新生成一采预览")
    if state.get("base_url", "").rstrip("/") != current_url.rstrip("/"):
        raise ValueError("ComfyUI 实例已切换，请恢复原实例或重新生成一采预览")
    revision = confirmation_revision(state["groups"])
    if request.get("source_revision") != revision or state.get("source_revision") != revision:
        raise ValueError("SOURCE_CHANGED: 一采来源版本已变化，请刷新后重新确认")
    for group in state["groups"]:
        validate_confirmation_report(group["report"], "preview_only")
    return float(quality)


def build_confirmation_preview(timeline: dict[str, Any], aspect_ratio: str,
                               seed: int, cache_key: str, filename_prefix: str) -> dict[str, Any]:
    graph = build_refine_workflow(timeline, {
        "aspect_ratio": aspect_ratio, "refine_enabled": True, "refine_quality": "2.0",
    }, filename_prefix, seed)
    graph["12"]["class_type"] = ADAPTER_CLASS
    # The checkpoint stores asym_w4a8_int8; the ordinary loader cannot read it.
    # Change only the copied recipe's loader, preserving its model and output link.
    graph["23"]["class_type"] = W4A8_LOADER
    graph["23"]["inputs"].pop("weight_dtype", None)
    graph["12"]["inputs"].update(stage="preview_only", cache_key=cache_key,
                                 source_revision="", expected_instance_id="")
    graph["38"]["inputs"]["confirm_first_pass"] = True
    graph["7"]["inputs"]["filename_prefix"] = filename_prefix + "-first"
    # One first-pass output in the copied recipe; the legacy two-save graph stays intact.
    graph.pop("20", None)
    graph.pop("19", None)
    return graph


def build_confirmation_refine(frozen_preview: dict[str, Any], report: dict[str, Any],
                              quality: float, filename_prefix: str) -> dict[str, Any]:
    if isinstance(quality, bool) or quality not in (1.0, 2.0):
        raise ValueError("二采画质仅支持 1 MP 或 2 MP")
    validate_confirmation_report(report, "preview_only")
    graph = copy.deepcopy(frozen_preview)
    if graph.get("12", {}).get("class_type") != ADAPTER_CLASS:
        raise ValueError("不是独立确认工作流")
    inputs = graph["12"]["inputs"]
    if inputs.get("stage") != "preview_only" or inputs.get("cache_key") != report["cache_key"]:
        raise ValueError("一采来源不匹配")
    inputs.update(stage="refine_only", source_revision=report["source_revision"],
                  expected_instance_id=report["instance_id"])
    # The 1 MP preset uses H3's native 1344x768 canvas instead of 1376x768.
    graph["38"]["inputs"]["megapixels"] = 0.98 if quality == 1.0 else float(quality)
    graph["7"]["inputs"]["filename_prefix"] = filename_prefix + "-refined"
    return graph


def validate_confirmation_report(report: dict[str, Any], stage: str) -> None:
    if stage not in ("preview_only", "refine_only"):
        raise ValueError("未知确认阶段")
    if report.get("protocol") != PROTOCOL or report.get("stage") != stage:
        raise ValueError("缺少匹配的阶段执行报告")
    count = report.get("segment_count")
    if type(count) is not int or count < 1:
        raise ValueError("缺少分段执行报告")
    for field in ("cache_key", "source_revision", "instance_id"):
        if not isinstance(report.get(field), str) or not report[field]:
            raise ValueError("阶段报告缺少 " + field)
    expected_first, expected_refine = (count, 0) if stage == "preview_only" else (0, count)
    if report.get("first_pass_samples") != expected_first or report.get("refine_samples") != expected_refine:
        raise ValueError("实际执行阶段与请求不符")
    field = "cached_segments" if stage == "preview_only" else "reused_segments"
    if report.get(field) != list(range(count)):
        raise ValueError("缓存分段报告不完整")
