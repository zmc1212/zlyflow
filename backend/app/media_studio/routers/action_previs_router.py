"""Director shot choreography and private pull-worker endpoints."""

from __future__ import annotations

import os
import secrets
from typing import Any, Callable

from fastapi import Body, Depends, File, Form, HTTPException, Request, UploadFile

from ..services.action_previs_service import ActionPrevisService, _ARTIFACT_LIMITS


def register_action_previs_routes(app: Any, *, current_user: Callable, mutating_user: Callable) -> None:
    def public_error(exc: Exception) -> HTTPException:
        message = str(exc)
        return HTTPException(status_code=409 if "CONFLICT" in message or "状态已变化" in message else 400,
                             detail=message)

    def worker_auth(request: Request) -> None:
        wanted = os.environ.get("ZLY_ACTION_PREVIS_WORKER_TOKEN", "")
        sent = request.headers.get("Authorization", "")
        if not wanted:
            raise HTTPException(
                status_code=503,
                detail=(
                    "远端 Blender 执行器尚未配置；请设置 "
                    "ZLY_ACTION_PREVIS_WORKER_TOKEN，并让远端 worker 使用相同令牌"
                ),
            )
        if not sent.startswith("Bearer ") or not secrets.compare_digest(sent[7:], wanted):
            raise HTTPException(status_code=401, detail="远端执行器凭证无效")

    @app.post("/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/action-previs", status_code=202)
    async def create_action_previs(project_id: str, episode_id: str, beat_id: str,
                                   description: str = Form(...), images: list[UploadFile] | None = File(default=None),
                                   video: UploadFile | None = File(default=None),
                                   user: dict = Depends(mutating_user)):
        try:
            if len(images or []) > 4:
                raise ValueError("最多上传四张参考图片")
            image_files = [(f.filename or "image", await f.read(8 * 1024 * 1024 + 1), f.content_type or "") for f in (images or [])]
            video_file = (video.filename or "video", await video.read(100 * 1024 * 1024 + 1), video.content_type or "") if video else None
            return ActionPrevisService.create(project_id, episode_id, beat_id, description, image_files, video_file)
        except (ValueError, RuntimeError, OSError) as exc:
            raise public_error(exc) from exc

    @app.get("/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/action-previs/latest")
    def latest_action_previs(project_id: str, episode_id: str, beat_id: str, user: dict = Depends(current_user)):
        return ActionPrevisService.latest(project_id, episode_id, beat_id)

    @app.get("/api/projects/{project_id}/action-previs/{job_id}")
    def get_action_previs(project_id: str, job_id: str, user: dict = Depends(current_user)):
        try:
            return ActionPrevisService.get(project_id, job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/projects/{project_id}/action-previs/{job_id}/plan")
    def revise_action_previs(project_id: str, job_id: str, payload: dict = Body(...), user: dict = Depends(mutating_user)):
        try:
            return ActionPrevisService.revise(project_id, job_id, payload.get("plan"), int(payload.get("expected_revision") or 0))
        except (ValueError, RuntimeError) as exc:
            raise public_error(exc) from exc

    @app.post("/api/projects/{project_id}/action-previs/{job_id}/render")
    def render_action_previs(project_id: str, job_id: str, payload: dict = Body(...), user: dict = Depends(mutating_user)):
        try:
            return ActionPrevisService.render(project_id, job_id, int(payload.get("expected_revision") or 0))
        except (ValueError, RuntimeError) as exc:
            raise public_error(exc) from exc

    @app.post("/api/projects/{project_id}/action-previs/{job_id}/cancel")
    def cancel_action_previs(project_id: str, job_id: str, user: dict = Depends(mutating_user)):
        try:
            return ActionPrevisService.cancel(project_id, job_id)
        except (ValueError, RuntimeError) as exc:
            raise public_error(exc) from exc

    @app.post("/api/projects/{project_id}/action-previs/{job_id}/retry")
    def retry_action_previs(project_id: str, job_id: str, user: dict = Depends(mutating_user)):
        try:
            return ActionPrevisService.retry(project_id, job_id)
        except (ValueError, RuntimeError) as exc:
            raise public_error(exc) from exc

    @app.post("/api/internal/action-previs/claim")
    def claim_action_previs(payload: dict = Body(...), _: None = Depends(worker_auth)):
        try:
            return {"job": ActionPrevisService.claim(str(payload.get("worker_id") or ""))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/internal/action-previs/{project_id}/{job_id}/heartbeat")
    def heartbeat_action_previs(project_id: str, job_id: str, payload: dict = Body(...), _: None = Depends(worker_auth)):
        try:
            return ActionPrevisService.heartbeat(project_id, job_id, str(payload.get("lease_token") or ""),
                                                  int(payload.get("progress") or 0), str(payload.get("stage") or ""))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put("/api/internal/action-previs/{project_id}/{job_id}/artifacts/{slot}")
    async def upload_action_previs_artifact(project_id: str, job_id: str, slot: str,
                                            request: Request, _: None = Depends(worker_auth)):
        try:
            token = request.headers.get("X-Action-Lease", "")
            limit = _ARTIFACT_LIMITS.get(slot)
            if not limit:
                raise ValueError("产物类型无效")
            chunks = bytearray()
            async for chunk in request.stream():
                chunks.extend(chunk)
                if len(chunks) > limit:
                    raise ValueError("产物过大")
            return ActionPrevisService.artifact(project_id, job_id, token, slot, bytes(chunks))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/internal/action-previs/{project_id}/{job_id}/complete")
    def complete_action_previs(project_id: str, job_id: str, payload: dict = Body(...), _: None = Depends(worker_auth)):
        try:
            return ActionPrevisService.complete(project_id, job_id, str(payload.get("lease_token") or ""),
                                                 payload.get("report") or {})
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/internal/action-previs/{project_id}/{job_id}/fail")
    def fail_action_previs(project_id: str, job_id: str, payload: dict = Body(...), _: None = Depends(worker_auth)):
        try:
            return ActionPrevisService.fail(project_id, job_id, str(payload.get("lease_token") or ""),
                                             str(payload.get("message") or "远端 Blender 任务失败"))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
