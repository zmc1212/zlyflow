"""Durable Comfy submissions; recovery never guesses whether a POST succeeded."""
from __future__ import annotations

from typing import Any


RESTART_ERROR = "服务进程重启，后台视频任务已中断，请点击重试。"


def restore_checkpoints(payload: dict[str, Any]) -> None:
    """Import legacy snapshots without changing prompt IDs or redoing completed chunks."""
    checkpoints = payload.setdefault("comfy_checkpoints", {})
    for chunk in (payload.get("render_plan") or {}).get("chunks", []):
        key = str(int(chunk["index"]) + 1)
        if chunk.get("output") and key not in checkpoints:
            checkpoints[key] = {"output": chunk["output"], "history": {"outputs": {}},
                                "graph": chunk.get("workflow_snapshot")}
    if payload.get("prompt_id"):
        index = int(payload.get("comfy_submission_count") or 1)
        key = str(index)
        if key not in checkpoints:
            chunks = (payload.get("render_plan") or {}).get("chunks", [])
            chunk = next((c for c in chunks if int(c["index"]) + 1 == index), {})
            graph = chunk.get("workflow_snapshot") or payload.get("workflow_request")
            if not graph:
                raise ValueError("原任务缺少工作流快照，无法安全恢复；不会重新提交远端任务")
            checkpoints[key] = {"graph": graph, "submitted": {
                "prompt_id": payload["prompt_id"], "client_id": payload.get("client_id") or "",
                "number": payload.get("queue_number"),
            }}
        if any(str(i) not in checkpoints for i in range(1, index)):
            raise ValueError("原任务缺少已执行分段的检查点，无法安全恢复；不会重复生成")


def remote_state(comfy: Any, prompt_id: str) -> str:
    response = comfy.session.get(f"{comfy.base_url}/history/{prompt_id}", timeout=comfy.timeout)
    response.raise_for_status()
    history = response.json().get(prompt_id)
    if history:
        status = history.get("status") or {}
        if status.get("status_str") in {"error", "failed"}:
            return "failed"
        if status.get("completed") and status.get("status_str") == "success":
            return "completed"
    response = comfy.session.get(f"{comfy.base_url}/queue", timeout=comfy.timeout)
    response.raise_for_status()
    queue = response.json()
    for key, state in (("queue_running", "running"), ("queue_pending", "comfy_queued")):
        if any(item[1] == prompt_id for item in queue.get(key, [])):
            return state
    # A prompt can finish between the history and queue requests.
    response = comfy.session.get(f"{comfy.base_url}/history/{prompt_id}", timeout=comfy.timeout)
    response.raise_for_status()
    history = response.json().get(prompt_id)
    if history:
        status = history.get("status") or {}
        if status.get("status_str") in {"error", "failed"}:
            return "failed"
        if status.get("completed") and status.get("status_str") == "success":
            return "completed"
    return "missing"
