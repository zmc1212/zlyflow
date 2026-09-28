"""Persisted confirmation orchestration shared by the creation-page worker."""
from __future__ import annotations

import copy

from .minimax_h3_confirm_workflow import (
    build_confirmation_shot, confirmation_state, execution_report,
)
from .minimax_h3_director_refine_workflow import validate_refine_dependencies
from .comfy_service import resolve_minimax_picture_prompt, legacy


def run_creation_confirmation(store, comfy, job, update_stage, on_submitted, is_cancelled):
    original_comfy = comfy
    original_comfy.last_execution_elapsed_ms = None
    options = copy.deepcopy(job.get("options") or {})
    state = options.get("h3_confirmation") or {}
    if state and state.get("base_url", "").rstrip("/") != comfy.comfy_url.rstrip("/"):
        raise ValueError("ComfyUI 实例已切换，请恢复原实例或重新生成一采预览")
    # Bind this execution to one URL; an admin edit cannot split upload/submit/download.
    bound_url = comfy.comfy_url.rstrip("/")
    if hasattr(comfy, "_url_resolver"):
        comfy = copy.copy(comfy)
        comfy._url_resolver = lambda: bound_url
    graph = state.get("graph")
    if not graph:
        uploaded = [comfy.upload_image(path, f"h3_reference_{i}")
                    for i, path in enumerate(job["references"], 1)]
        graph = build_confirmation_shot(
            resolve_minimax_picture_prompt(job["prompt"], len(uploaded)), uploaded,
            options, int(options.get("seed", 0)), "video/ZLY_Confirmed_" + job["id"])
        state = {"graph": graph, "base_url": comfy.comfy_url.rstrip("/"), "stage": "preview_only"}
        options["h3_confirmation"] = state
        store.set_confirmation_options(job["id"], options)
    validate_refine_dependencies(graph, comfy.object_info())
    if state.get("result_history"):
        history = state["result_history"]
    elif job.get("comfy_prompt_id"):
        history = comfy.wait_for_existing(job["comfy_prompt_id"], job.get("comfy_client_id"),
            update_stage, "正在恢复确认任务", is_cancelled=is_cancelled)
    else:
        history = comfy.run_workflow(graph, "正在生成二采精修" if state["stage"] == "refine_only" else "正在生成一采预览",
            update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled)
    report = execution_report(graph, history)
    original_comfy.last_execution_elapsed_ms = comfy.execution_elapsed_ms(history)
    state["result_history"] = {"outputs": {k: history["outputs"][k] for k in ("7", "12")}}
    options["h3_confirmation"] = state
    store.set_confirmation_options(job["id"], options)
    media = comfy.download(legacy.output_file(history, "7", ("videos", "gifs", "images")), "h3_confirm", require_local=True)
    output = comfy.output_payload(media, "video", "二采精修版" if state["stage"] == "refine_only" else "一采原片")
    local = output.get("_local_path")
    if local:
        from pathlib import Path
        from .media_studio.services.production_media import probe_file
        state["media_info"] = probe_file(Path(local))
    if state["stage"] == "preview_only":
        state = {**state, **confirmation_state([{"graph": graph, "report": report}], comfy.comfy_url)}
    else:
        state.update(state="completed", report=report)
    options["h3_confirmation"] = state
    store.set_confirmation_options(job["id"], options)
    return [output]
