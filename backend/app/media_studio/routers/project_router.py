from __future__ import annotations

from typing import Annotated, Any, Callable

import json

from fastapi import Depends, File, HTTPException, Path, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..models import ProjectCreateRequest, ProjectItem, ProjectUpdateRequest
from ..services.episode_video_service import EpisodeVideoService
from ..services.llm_service import LlmService
from ..services.project_detail_service import ProjectDetailService
from ..services.project_service import ProjectService
from ..services.ai_generation_service import AiGenerationService


def register_project_routes(
    app: Any,
    *,
    current_user: Callable,
    mutating_user: Callable,
) -> None:
    """挂载 AI Media Studio 项目 API（路径与 dev0914 原版完全一致）。

    鉴权：读取走 current_user，写入走 mutating_user（沿用工作台会话体系）。
    """

    def ai_service() -> AiGenerationService:
        service = getattr(app.state, "director2_ai_service", None)
        if service is None:
            service = AiGenerationService(app.state.llm_provider)
            app.state.director2_ai_service = service
        return service

    def operation_or_404(service: AiGenerationService, operation_id: str, project_id: str):
        try:
            return service.get(operation_id, project_id)
        except ValueError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err

    def sse_frame(event: dict) -> str:
        name = str(event.get("event") or "message")
        data = json.dumps(event.get("data") or {}, ensure_ascii=False)
        seq = int(event.get("seq") or 0)
        event_id = f"id: {seq}\n" if seq > 0 else ""
        return f"{event_id}event: {name}\ndata: {data}\n\n"

    @app.post("/api/projects/{project_id}/ai/operations", status_code=202, summary="创建导演台2 AI 生成操作")
    def create_ai_operation(project_id: Annotated[str, Path(description="导台2项目 ID")], payload: dict, user: dict = Depends(mutating_user)):
        try:
            if not ProjectService.get_project(project_id):
                raise HTTPException(status_code=404, detail="项目不存在")
            payload = {**payload, "project_id": project_id}
            return ai_service().create(project_id, payload)
        except HTTPException:
            raise
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.get("/api/projects/{project_id}/ai/operations/active", summary="读取导演台2项目进行中的 AI 生成操作")
    def get_active_ai_operation(project_id: Annotated[str, Path(description="导台2项目 ID")], user: dict = Depends(current_user)):
        # 必须注册在 /{operation_id} 之前，否则 "active" 会被当成任务 ID。
        return ai_service().get_active(project_id)

    @app.get("/api/projects/{project_id}/ai/operations/{operation_id}", summary="读取导演台2 AI 生成操作")
    def get_ai_operation(project_id: Annotated[str, Path(description="导台2项目 ID")], operation_id: Annotated[str, Path(description="AI 操作 ID")], user: dict = Depends(current_user)):
        return operation_or_404(ai_service(), operation_id, project_id)

    @app.get("/api/projects/{project_id}/ai/operations/{operation_id}/events", summary="订阅导演台2 AI 生成事件")
    async def stream_ai_operation(
        project_id: Annotated[str, Path(description="导台2项目 ID")],
        operation_id: Annotated[str, Path(description="AI 操作 ID")],
        request: Request,
        since: Annotated[int, Query(description="只重放 seq 大于该值的缓冲事件")] = 0,
        user: dict = Depends(current_user),
    ):
        service = ai_service()
        operation_or_404(service, operation_id, project_id)

        async def event_stream():
            try:
                last_event_id = int(request.headers.get("last-event-id") or 0)
            except ValueError:
                last_event_id = 0
            resume_from = max(since, last_event_id)
            async for event in service.stream(operation_id, project_id, request, since=resume_from):
                yield sse_frame(event)

        return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/projects/{project_id}/ai/operations/{operation_id}/cancel", summary="取消导演台2 AI 生成操作")
    def cancel_ai_operation(project_id: Annotated[str, Path(description="导台2项目 ID")], operation_id: Annotated[str, Path(description="AI 操作 ID")], user: dict = Depends(mutating_user)):
        try:
            return ai_service().cancel(operation_id, project_id)
        except ValueError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err

    @app.post("/api/projects/{project_id}/ai/operations/{operation_id}/retry", summary="重试导演台2 AI 生成操作")
    def retry_ai_operation(
        project_id: Annotated[str, Path(description="导台2项目 ID")],
        operation_id: Annotated[str, Path(description="AI 操作 ID")],
        payload: dict | None = None,
        user: dict = Depends(mutating_user),
    ):
        try:
            body = payload or {}
            stage = body.get("stage")
            return ai_service().retry(operation_id, project_id, stage if isinstance(stage, str) else None)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.post("/api/projects/{project_id}/ai/operations/{operation_id}/advance", summary="采纳当前阶段并进入下一步")
    def advance_ai_operation(project_id: Annotated[str, Path(description="导台2项目 ID")], operation_id: Annotated[str, Path(description="AI 操作 ID")], user: dict = Depends(mutating_user)):
        service = ai_service()
        operation_or_404(service, operation_id, project_id)
        try:
            return service.advance(operation_id, project_id)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.post("/api/projects/{project_id}/ai/operations/{operation_id}/revise", summary="对当前阶段提出调整并生成澄清问题")
    def revise_ai_operation(
        project_id: Annotated[str, Path(description="导台2项目 ID")],
        operation_id: Annotated[str, Path(description="AI 操作 ID")],
        payload: dict | None = None,
        user: dict = Depends(mutating_user),
    ):
        service = ai_service()
        operation_or_404(service, operation_id, project_id)
        try:
            body = payload or {}
            return service.revise(operation_id, project_id, body.get("feedback") or "")
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.post("/api/projects/{project_id}/ai/operations/{operation_id}/rerun", summary="提交当前阶段澄清答案并只重跑该步")
    def rerun_ai_stage(
        project_id: Annotated[str, Path(description="导台2项目 ID")],
        operation_id: Annotated[str, Path(description="AI 操作 ID")],
        payload: dict | None = None,
        user: dict = Depends(mutating_user),
    ):
        service = ai_service()
        operation_or_404(service, operation_id, project_id)
        try:
            body = payload or {}
            return service.rerun_stage(operation_id, project_id, body.get("clarifications"))
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.get("/api/projects", response_model=list[ProjectItem], summary="获取项目列表")
    def list_projects(user: dict = Depends(current_user)):
        try:
            return ProjectService.list_projects()
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"获取项目列表失败: {err}")

    @app.post("/api/projects", response_model=ProjectItem, summary="创建项目")
    def create_project(payload: ProjectCreateRequest, user: dict = Depends(mutating_user)):
        try:
            return ProjectService.create_project(payload)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"创建项目失败: {err}")

    @app.get("/api/projects/{project_id}", response_model=ProjectItem, summary="获取项目详情")
    def get_project(project_id: Annotated[str, Path(description="项目 ID")], user: dict = Depends(current_user)):
        item = ProjectService.get_project(project_id)
        if not item:
            raise HTTPException(status_code=404, detail="项目不存在")
        return item

    @app.put("/api/projects/{project_id}", response_model=ProjectItem, summary="更新项目")
    def update_project(project_id: Annotated[str, Path(description="项目 ID")], payload: ProjectUpdateRequest, user: dict = Depends(mutating_user)):
        try:
            return ProjectService.update_project(project_id, payload)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"更新项目失败: {err}")

    @app.delete("/api/projects/{project_id}", summary="删除项目")
    def delete_project(project_id: Annotated[str, Path(description="项目 ID")], user: dict = Depends(mutating_user)):
        success = ProjectService.delete_project(project_id)
        if not success:
            raise HTTPException(status_code=404, detail="项目不存在或已被删除")
        return {"status": "ok", "message": "项目删除成功", "id": project_id}

    # --- 1. 内容库 Documents ---
    @app.get("/api/projects/{project_id}/documents", summary="获取项目文档列表")
    def list_documents(project_id: Annotated[str, Path(description="项目 ID")], user: dict = Depends(current_user)):
        return ProjectDetailService.list_documents(project_id)

    @app.post("/api/projects/{project_id}/documents", summary="导入或粘贴项目文档")
    def create_document(project_id: Annotated[str, Path(description="项目 ID")], payload: dict, user: dict = Depends(mutating_user)):
        try:
            filename = payload.get("filename") or "剧本文档"
            raw_text = payload.get("raw_text") or ""
            spine_template = payload.get("spine_template") or "drama"
            visual_style = payload.get("visual_style") or "chinese_period_drama"
            input_mode = payload.get("input_mode") or "paste"
            return ProjectDetailService.create_document(
                project_id=project_id,
                filename=filename,
                raw_text=raw_text,
                spine_template=spine_template,
                visual_style=visual_style,
                input_mode=input_mode,
            )
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.delete("/api/projects/{project_id}/documents/{doc_id}", summary="删除项目文档")
    def delete_document(project_id: Annotated[str, Path(description="项目 ID")], doc_id: Annotated[str, Path(description="项目文档 ID")], user: dict = Depends(mutating_user)):
        success = ProjectDetailService.delete_document(project_id, doc_id)
        if not success:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除")
        return {"status": "ok", "id": doc_id}

    @app.post("/api/projects/{project_id}/documents/{doc_id}/transfer-assets", summary="将文档提取的角色场景道具转入资产库")
    def transfer_assets(project_id: Annotated[str, Path(description="项目 ID")], doc_id: Annotated[str, Path(description="项目文档 ID")], user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.transfer_assets_from_document(project_id, doc_id)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/documents/{doc_id}/transfer-episodes", summary="将文档提取的分集与分镜同步至剧集工坊")
    def transfer_episodes(project_id: Annotated[str, Path(description="项目 ID")], doc_id: Annotated[str, Path(description="项目文档 ID")], user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.transfer_episodes_from_document(project_id, doc_id)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    # --- 2. 资产库 Assets ---
    @app.get("/api/projects/{project_id}/assets", summary="获取项目资产列表")
    def list_assets(project_id: Annotated[str, Path(description="项目 ID")], kind: str | None = None, user: dict = Depends(current_user)):
        return ProjectDetailService.list_assets(project_id, kind)

    @app.post("/api/projects/{project_id}/assets", summary="创建项目资产")
    def create_asset(project_id: Annotated[str, Path(description="项目 ID")], payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.create_asset(project_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/assets/generate-character-content", summary="AI 生成角色容貌、服饰和生图提示词")
    def generate_character_content(project_id: Annotated[str, Path(description="项目 ID")], payload: dict, user: dict = Depends(mutating_user)):
        try:
            return LlmService.generate_character_content(
                payload.get("requirement") or "",
                name=payload.get("name") or "",
                role=payload.get("role") or "",
            )
        except (ValueError, RuntimeError) as err:
            raise HTTPException(status_code=400, detail=str(err))
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"AI 生成角色内容失败: {err}")

    @app.put("/api/projects/{project_id}/assets/{asset_id}", summary="更新项目资产")
    def update_asset(project_id: Annotated[str, Path(description="项目 ID")], asset_id: Annotated[str, Path(description="资产 ID")], payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.update_asset(project_id, asset_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.delete("/api/projects/{project_id}/assets/{asset_id}", summary="删除项目资产")
    def delete_asset(project_id: Annotated[str, Path(description="项目 ID")], asset_id: Annotated[str, Path(description="资产 ID")], user: dict = Depends(mutating_user)):
        success = ProjectDetailService.delete_asset(project_id, asset_id)
        if not success:
            raise HTTPException(status_code=404, detail="资产不存在或已被删除")
        return {"status": "ok", "id": asset_id}

    @app.post("/api/projects/{project_id}/assets/{asset_id}/generate", summary="AI 生成或重新生成资产形象图")
    def generate_asset_image(project_id: Annotated[str, Path(description="项目 ID")], asset_id: Annotated[str, Path(description="资产 ID")], payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.generate_asset_image(project_id, asset_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/assets/{asset_id}/references", summary="上传资产原片参考图")
    async def upload_asset_source_reference(
        project_id: Annotated[str, Path(description="项目 ID")],
        asset_id: Annotated[str, Path(description="资产 ID")],
        file: UploadFile = File(...),
        user: dict = Depends(mutating_user),
    ):
        content = await file.read()
        try:
            return ProjectDetailService.add_asset_source_reference(
                project_id,
                asset_id,
                filename=file.filename or "",
                content=content,
                content_type=file.content_type or "",
            )
        except (ValueError, RuntimeError) as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.delete("/api/projects/{project_id}/assets/{asset_id}/references/{ref_id}", summary="删除资产原片参考图")
    def delete_asset_source_reference(
        project_id: Annotated[str, Path(description="项目 ID")],
        asset_id: Annotated[str, Path(description="资产 ID")],
        ref_id: Annotated[str, Path(description="参考图 ID")],
        user: dict = Depends(mutating_user),
    ):
        try:
            return ProjectDetailService.delete_asset_source_reference(project_id, asset_id, ref_id)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.post("/api/projects/{project_id}/assets/{asset_id}/infer-prompts", summary="根据原片参考图反推并覆盖资产提示词")
    def infer_asset_prompts(
        project_id: Annotated[str, Path(description="项目 ID")],
        asset_id: Annotated[str, Path(description="资产 ID")],
        user: dict = Depends(mutating_user),
    ):
        try:
            return ProjectDetailService.infer_asset_prompts(project_id, asset_id)
        except (ValueError, RuntimeError) as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    # --- 3. 剧集工坊 Episodes ---
    @app.get("/api/projects/{project_id}/episodes", summary="获取项目剧集工坊列表")
    def list_episodes(project_id: Annotated[str, Path(description="项目 ID")], user: dict = Depends(current_user)):
        return ProjectDetailService.list_episodes(project_id)

    @app.post("/api/projects/{project_id}/episodes", summary="新建剧集")
    def create_episode(project_id: Annotated[str, Path(description="项目 ID")], payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.create_episode(project_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.put("/api/projects/{project_id}/episodes/{episode_id}", summary="更新剧集")
    def update_episode(project_id: Annotated[str, Path(description="项目 ID")], episode_id: Annotated[str, Path(description="分集 ID")], payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.update_episode(project_id, episode_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.delete("/api/projects/{project_id}/episodes/{episode_id}", summary="删除剧集")
    def delete_episode(project_id: Annotated[str, Path(description="项目 ID")], episode_id: Annotated[str, Path(description="分集 ID")], user: dict = Depends(mutating_user)):
        success = ProjectDetailService.delete_episode(project_id, episode_id)
        if not success:
            raise HTTPException(status_code=404, detail="剧集不存在或已被删除")
        return {"status": "ok", "id": episode_id}

    @app.get("/api/projects/{project_id}/episodes/{episode_id}", summary="获取分集详细分镜与资产关联")
    def get_episode_detail(project_id: Annotated[str, Path(description="项目 ID")], episode_id: Annotated[str, Path(description="分集 ID")], user: dict = Depends(current_user)):
        try:
            return ProjectDetailService.get_episode_detail(project_id, episode_id)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.put("/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}", summary="更新分集单个分镜信息")
    def update_episode_beat(project_id: Annotated[str, Path(description="项目 ID")], episode_id: Annotated[str, Path(description="分集 ID")], beat_id: Annotated[str, Path(description="Beat ID")], payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.update_episode_beat(project_id, episode_id, beat_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-sketch", status_code=202, summary="AI 生成分镜草图")
    def generate_beat_sketch(project_id: Annotated[str, Path(description="项目 ID")], episode_id: Annotated[str, Path(description="分集 ID")], beat_id: Annotated[str, Path(description="Beat ID")], payload: dict = None, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.generate_beat_sketch(project_id, episode_id, beat_id, payload or {})
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-render", status_code=202, summary="把草图精绘为渲染图")
    def generate_beat_render(project_id: Annotated[str, Path(description="项目 ID")], episode_id: Annotated[str, Path(description="分集 ID")], beat_id: Annotated[str, Path(description="Beat ID")], payload: dict = None, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.generate_beat_render(project_id, episode_id, beat_id, payload or {})
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/h3-prompt", status_code=202, summary="生成或优化本镜 H3 视频提示词")
    def generate_beat_h3_prompt(project_id: Annotated[str, Path(description="项目 ID")], episode_id: Annotated[str, Path(description="分集 ID")], beat_id: Annotated[str, Path(description="Beat ID")], payload: dict = None, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.generate_beat_h3_prompt(project_id, episode_id, beat_id, payload or {})
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/episodes/{episode_id}/generate-images", status_code=202, summary="批量生成分镜草图或渲染图")
    def generate_beat_images_batch(project_id: Annotated[str, Path(description="项目 ID")], episode_id: Annotated[str, Path(description="分集 ID")], payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.generate_beat_images_batch(project_id, episode_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post(
        "/api/projects/{project_id}/episodes/{episode_id}/generate-video",
        status_code=202,
        summary="按工作流一键生成整集或逐镜视频",
    )
    def generate_episode_video(project_id: Annotated[str, Path(description="项目 ID")], episode_id: Annotated[str, Path(description="分集 ID")], payload: dict | None = None, user: dict = Depends(mutating_user)):
        try:
            return EpisodeVideoService.generate_episode_videos(project_id, episode_id, options=payload or {})
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"创建视频任务失败: {err}")

    @app.post(
        "/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-video",
        status_code=202,
        summary="生成单个 Beat 的视频",
    )
    def generate_beat_video(project_id: Annotated[str, Path(description="项目 ID")], episode_id: Annotated[str, Path(description="分集 ID")], beat_id: Annotated[str, Path(description="Beat ID")], payload: dict | None = None, user: dict = Depends(mutating_user)):
        try:
            return EpisodeVideoService.create_job(
                project_id,
                episode_id,
                beat_id=beat_id,
                render_scope="shot",
                options=payload or {},
            )
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"创建单镜视频任务失败: {err}")

    @app.post(
        "/api/projects/{project_id}/episodes/{episode_id}/compose",
        status_code=202,
        summary="拼接各镜视频为分集成片",
    )
    def compose_episode_video(project_id: Annotated[str, Path(description="项目 ID")], episode_id: Annotated[str, Path(description="分集 ID")], payload: dict | None = None, user: dict = Depends(mutating_user)):
        try:
            return EpisodeVideoService.create_compose_job(project_id, episode_id, options=payload or {})
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"创建合成任务失败: {err}")

    # --- 4. 全部任务 Jobs ---
    @app.get("/api/projects/{project_id}/jobs", summary="获取项目生成任务列表")
    def list_jobs(project_id: Annotated[str, Path(description="项目 ID")], user: dict = Depends(current_user)):
        return ProjectDetailService.list_jobs(project_id)

    @app.post("/api/projects/{project_id}/jobs", summary="创建任务")
    def create_job(project_id: Annotated[str, Path(description="项目 ID")], payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.create_job(project_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/jobs/{job_id}/retry", summary="重试任务")
    def retry_job(project_id: Annotated[str, Path(description="项目 ID")], job_id: Annotated[str, Path(description="任务 ID")], user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.retry_job(project_id, job_id)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))
