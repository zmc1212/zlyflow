"""Director confirmation children: frozen groups, atomic creation and retry checkpoints."""
from __future__ import annotations

import copy
import json
import uuid

from ..db import transaction_cursor, now_str, query_one, query_all
from ..provider_bridge import comfy_row
from ...minimax_h3_confirm_workflow import MODE_ID, validate_refine_request, build_confirmation_refine


def create_refinement(project_id, job_id, request, user_id):
    from .episode_video_service import EpisodeVideoService, _EXECUTOR, _ACTIVE_VIDEO_STATUSES
    child_id = str(uuid.uuid4())
    created = False
    existing_status = None
    with transaction_cursor() as cursor:
        cursor.execute("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s FOR UPDATE", (job_id, project_id))
        row = cursor.fetchone()
        if not row or row["status"] not in ("completed", "succeeded"):
            raise ValueError("仅已完成的一采可以确认二采")
        payload = json.loads(row.get("payload_json") or "{}")
        if payload.get("workflow_id") != MODE_ID:
            raise ValueError("不是独立确认工作流")
        state = payload.get("h3_confirmation") or {}
        quality = validate_refine_request(state, request, str(comfy_row()["base_url"]))
        cursor.execute("SELECT id,status,payload_json FROM ai_project_jobs WHERE project_id=%s AND job_type='video_generation' "
                       "AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.h3_confirmation.source_job_id'))=%s ORDER BY created_at DESC",
                       (project_id, job_id))
        for existing in cursor.fetchall():
            child = json.loads(existing.get("payload_json") or "{}").get("h3_confirmation") or {}
            if child.get("request_id") == request["request_id"]:
                if child.get("quality") != quality:
                    raise ValueError("SOURCE_CHANGED: 同一幂等标识不能修改画质")
                child_id = existing["id"]
                existing_status = existing["status"]
                break
            if existing["status"] in _ACTIVE_VIDEO_STATUSES:
                child_id = existing["id"]
                existing_status = existing["status"]
                break
        else:
            child = copy.deepcopy(payload)
            groups = copy.deepcopy(state["groups"])
            for i, group in enumerate(groups):
                group["graph"] = build_confirmation_refine(group["graph"], group["report"], quality,
                    f"video/{project_id}/{child_id}/group-{i + 1}")
                for key in ("output", "report", "media_info", "url", "production_recorded"):
                    group.pop(key, None)
            child["h3_confirmation"] = {"stage": "refine_only", "state": "queued",
                "groups": groups, "base_url": state["base_url"], "source_revision": state["source_revision"],
                "request_id": request["request_id"], "quality": quality, "source_job_id": job_id,
                "source_video_url": row.get("result_url"), "created_by": user_id}
            child.update(pipeline_version=5, auto_adopt=False, source_job_id=job_id)
            child["confirmation_cancel_requested"] = False
            for key in ("execution_lease", "confirmation_checkpoints", "production_material_ids",
                        "prompt_id", "client_id", "refine_outputs", "output_media_info"):
                child.pop(key, None)
            # Keep the source shots/timeline and grouping for material boundaries.
            for chunk in (child.get("render_plan") or {}).get("chunks", []):
                for key in ("output", "production_recorded", "director_report"):
                    chunk.pop(key, None)
                chunk["status"] = "queued"
            timestamp = now_str()
            cursor.execute(
                "INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at)"
                " VALUES (%s,%s,'video_generation',%s,'queued',0,NULL,%s,%s,%s)",
                (child_id, project_id, (row.get("title") or "一采预览") + " · 二采精修",
                 json.dumps(child, ensure_ascii=False), timestamp, timestamp))
            created = True
    if created or existing_status == "queued":
        _EXECUTOR.submit(EpisodeVideoService._run_job, child_id)
    return {"job_id": child_id, "status": "queued" if created else "existing"}


def run_refinement(service, job_id, payload):
    from .comfy_video_client import ComfyVideoClient
    from .qiniu_service import QiniuService
    from .production_media import measure
    from .episode_video_service import _video_write
    state = payload["h3_confirmation"]
    def ensure_not_cancelled():
        latest = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        if json.loads(latest.get("payload_json") or "{}").get("confirmation_cancel_requested"):
            raise RuntimeError("H3_CONFIRMATION_CANCELLED: 二采已取消，原片保留")
    if state["base_url"].rstrip("/") != str(comfy_row()["base_url"]).rstrip("/"):
        raise ValueError("ComfyUI 实例已切换，请恢复原实例或重新生成一采预览")
    comfy = ComfyVideoClient(state["base_url"])
    groups = state["groups"]
    chunks = (payload.get("render_plan") or {}).get("chunks", [])
    source_shots = payload.get("shots") or payload.get("source_shots") or []
    outputs = []
    state["state"] = "running"
    for index, group in enumerate(groups):
        ensure_not_cancelled()
        if not group.get("output"):
            history, output = service._await_comfy(job_id, payload, comfy, group["graph"], submission_index=index + 1)
            from ...minimax_h3_confirm_workflow import execution_report
            group.update(output=output, report=execution_report(group["graph"], history))
            # A child must measure its own output, never inherit preview metadata.
            group.pop("media_info", None)
            group.pop("url", None)
            # Persist before storage/assembly so a retry never repeats successful groups.
            service._set_state(job_id, payload, "running", 90)
        output = group["output"]
        outputs.append(output)
        if not group.get("media_info") or not group.get("url"):
            content = comfy.download_output(output)
            group["media_info"] = measure(content, [])
            group["url"] = comfy.view_url(output)
            if QiniuService.get_config().available:
                _, group["url"] = QiniuService.store_bytes("video", output["filename"], content)
            service._set_state(job_id, payload, "running", 92)
        if payload.get("production_context") and payload.get("render_scope") != "selection" and not group.get("production_recorded"):
            shot_ids = set(chunks[index].get("shot_ids") or []) if index < len(chunks) else set()
            shots = [s for s in source_shots if str(s.get("beat_id")) in shot_ids] or source_shots
            service._record_production_output(payload, job_id, shots, output, comfy, url=group["url"])
            group["production_recorded"] = True
            service._set_state(job_id, payload, "running", 94)
    result_url = groups[0]["url"]
    merged = None
    if len(outputs) > 1:
        service._set_state(job_id, payload, "assembling", 96)
        merged = service._merge_chunk_videos(comfy, outputs)
        if not QiniuService.get_config().available:
            raise ValueError("分组二采已保留，请配置七牛云后重试合成")
        _, result_url = QiniuService.store_bytes("video", f"refined-{job_id}.mp4", merged)
    payload["output_media_info"] = measure(merged, []) if merged else groups[0]["media_info"]
    if payload.get("production_context") and payload.get("render_scope") == "selection":
        service._record_production_output(payload, job_id, source_shots, outputs[0], comfy, url=result_url, content=merged)
    # No beat/episode adopted URL write: this is a candidate until explicitly adopted.
    ensure_not_cancelled()
    payload["refine_outputs"] = [{"label": "一采原片", "url": state["source_video_url"]},
        {"label": "二采精修版", "url": result_url, "media_info": payload["output_media_info"]}]
    state["state"] = "completed"
    payload.pop("execution_lease", None)
    timestamp = now_str()
    _video_write("UPDATE ai_project_jobs SET status='completed',progress=100,result_url=%s,payload_json=%s,"
                 "error_message=NULL,completed_at=%s,updated_at=%s WHERE id=%s",
                 (result_url, json.dumps(payload, ensure_ascii=False), timestamp, timestamp, job_id))


def refinement_status(project_id, job_id):
    row = query_one("SELECT * FROM ai_project_jobs WHERE project_id=%s AND id=%s", (project_id, job_id))
    if not row:
        return {"eligible": False, "children": []}
    state = json.loads(row.get("payload_json") or "{}").get("h3_confirmation") or {}
    if state.get("stage") == "refine_only":
        return refinement_status(project_id, state["source_job_id"])
    children = query_all("SELECT * FROM ai_project_jobs WHERE project_id=%s AND "
        "JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.h3_confirmation.source_job_id'))=%s ORDER BY created_at", (project_id, job_id))
    return {"eligible": state.get("stage") == "preview_only" and row["status"] in ("completed", "succeeded"),
        "source_job_id": job_id, "source_revision": state.get("source_revision"),
        "source_media_info": json.loads(row.get("payload_json") or "{}").get("output_media_info"),
        "source_url": row.get("result_url"), "children": [
            {"id": c["id"], "status": c["status"], "progress": c.get("progress"), "url": c.get("result_url"),
             "error": c.get("error_message"), "created_at": c.get("created_at"),
             "quality": (json.loads(c.get("payload_json") or "{}").get("h3_confirmation") or {}).get("quality"),
             "media_info": json.loads(c.get("payload_json") or "{}").get("output_media_info")}
            for c in children]}


def cancel_refinement(project_id, job_id):
    from ..db import execute_sql
    row = query_one("SELECT payload_json,status FROM ai_project_jobs WHERE project_id=%s AND id=%s", (project_id, job_id))
    state = json.loads((row or {}).get("payload_json") or "{}").get("h3_confirmation") or {}
    if state.get("stage") != "refine_only":
        raise ValueError("仅可取消二采子任务")
    execute_sql("UPDATE ai_project_jobs SET payload_json=JSON_SET(payload_json,'$.confirmation_cancel_requested',true) "
                "WHERE project_id=%s AND id=%s", (project_id, job_id))
    return {"job_id": job_id, "status": "cancelling"}


def regenerate_preview(project_id, job_id):
    from ..db import execute_sql
    from .episode_video_service import EpisodeVideoService, _EXECUTOR
    row = query_one("SELECT * FROM ai_project_jobs WHERE project_id=%s AND id=%s", (project_id, job_id))
    payload = json.loads((row or {}).get("payload_json") or "{}")
    if payload.get("h3_confirmation", {}).get("stage") != "preview_only" or payload.get("workflow_id") != MODE_ID:
        raise ValueError("请选择原一采任务重新生成预览")
    for key in ("h3_confirmation", "confirmation_checkpoints", "execution_lease", "production_material_ids",
                "prompt_id", "client_id", "shots", "render_plan", "workflow_request", "refine_outputs"):
        payload.pop(key, None)
    payload["comfy_base_url"] = str(comfy_row()["base_url"])
    child_id, timestamp = str(uuid.uuid4()), now_str()
    execute_sql("INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at)"
                " VALUES (%s,%s,'video_generation','重新生成一采预览','queued',0,NULL,%s,%s,%s)",
                (child_id, project_id, json.dumps(payload, ensure_ascii=False), timestamp, timestamp))
    _EXECUTOR.submit(EpisodeVideoService._run_job, child_id)
    return {"job_id": child_id, "status": "queued"}
