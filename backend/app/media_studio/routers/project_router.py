from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, HTTPException

from ..models import ProjectCreateRequest, ProjectItem, ProjectUpdateRequest
from ..services.episode_video_service import EpisodeVideoService
from ..services.llm_service import LlmService
from ..services.project_detail_service import ProjectDetailService
from ..services.project_service import ProjectService


def register_project_routes(
    app: Any,
    *,
    current_user: Callable,
    mutating_user: Callable,
) -> None:
    """挂载 AI Media Studio 项目 API（路径与 dev0914 原版完全一致）。

    鉴权：读取走 current_user，写入走 mutating_user（沿用工作台会话体系）。
    """

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
    def get_project(project_id: str, user: dict = Depends(current_user)):
        item = ProjectService.get_project(project_id)
        if not item:
            raise HTTPException(status_code=404, detail="项目不存在")
        return item

    @app.put("/api/projects/{project_id}", response_model=ProjectItem, summary="更新项目")
    def update_project(project_id: str, payload: ProjectUpdateRequest, user: dict = Depends(mutating_user)):
        try:
            return ProjectService.update_project(project_id, payload)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"更新项目失败: {err}")

    @app.delete("/api/projects/{project_id}", summary="删除项目")
    def delete_project(project_id: str, user: dict = Depends(mutating_user)):
        success = ProjectService.delete_project(project_id)
        if not success:
            raise HTTPException(status_code=404, detail="项目不存在或已被删除")
        return {"status": "ok", "message": "项目删除成功", "id": project_id}

    # --- 1. 内容库 Documents ---
    @app.get("/api/projects/{project_id}/documents", summary="获取项目文档列表")
    def list_documents(project_id: str, user: dict = Depends(current_user)):
        return ProjectDetailService.list_documents(project_id)

    @app.post("/api/projects/{project_id}/documents", summary="导入或粘贴项目文档")
    def create_document(project_id: str, payload: dict, user: dict = Depends(mutating_user)):
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
    def delete_document(project_id: str, doc_id: str, user: dict = Depends(mutating_user)):
        success = ProjectDetailService.delete_document(project_id, doc_id)
        if not success:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除")
        return {"status": "ok", "id": doc_id}

    @app.post("/api/projects/{project_id}/documents/{doc_id}/transfer-assets", summary="将文档提取的角色场景道具转入资产库")
    def transfer_assets(project_id: str, doc_id: str, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.transfer_assets_from_document(project_id, doc_id)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/documents/{doc_id}/transfer-episodes", summary="将文档提取的分集与分镜同步至剧集工坊")
    def transfer_episodes(project_id: str, doc_id: str, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.transfer_episodes_from_document(project_id, doc_id)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    # --- 2. 资产库 Assets ---
    @app.get("/api/projects/{project_id}/assets", summary="获取项目资产列表")
    def list_assets(project_id: str, kind: str | None = None, user: dict = Depends(current_user)):
        return ProjectDetailService.list_assets(project_id, kind)

    @app.post("/api/projects/{project_id}/assets", summary="创建项目资产")
    def create_asset(project_id: str, payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.create_asset(project_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/assets/generate-character-content", summary="AI 生成角色容貌、服饰和生图提示词")
    def generate_character_content(project_id: str, payload: dict, user: dict = Depends(mutating_user)):
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
    def update_asset(project_id: str, asset_id: str, payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.update_asset(project_id, asset_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.delete("/api/projects/{project_id}/assets/{asset_id}", summary="删除项目资产")
    def delete_asset(project_id: str, asset_id: str, user: dict = Depends(mutating_user)):
        success = ProjectDetailService.delete_asset(project_id, asset_id)
        if not success:
            raise HTTPException(status_code=404, detail="资产不存在或已被删除")
        return {"status": "ok", "id": asset_id}

    @app.post("/api/projects/{project_id}/assets/{asset_id}/generate", summary="AI 生成或重新生成资产形象图")
    def generate_asset_image(project_id: str, asset_id: str, payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.generate_asset_image(project_id, asset_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    # --- 3. 剧集工坊 Episodes ---
    @app.get("/api/projects/{project_id}/episodes", summary="获取项目剧集工坊列表")
    def list_episodes(project_id: str, user: dict = Depends(current_user)):
        return ProjectDetailService.list_episodes(project_id)

    @app.post("/api/projects/{project_id}/episodes", summary="新建剧集")
    def create_episode(project_id: str, payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.create_episode(project_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.put("/api/projects/{project_id}/episodes/{episode_id}", summary="更新剧集")
    def update_episode(project_id: str, episode_id: str, payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.update_episode(project_id, episode_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.delete("/api/projects/{project_id}/episodes/{episode_id}", summary="删除剧集")
    def delete_episode(project_id: str, episode_id: str, user: dict = Depends(mutating_user)):
        success = ProjectDetailService.delete_episode(project_id, episode_id)
        if not success:
            raise HTTPException(status_code=404, detail="剧集不存在或已被删除")
        return {"status": "ok", "id": episode_id}

    @app.get("/api/projects/{project_id}/episodes/{episode_id}", summary="获取分集详细分镜与资产关联")
    def get_episode_detail(project_id: str, episode_id: str, user: dict = Depends(current_user)):
        try:
            return ProjectDetailService.get_episode_detail(project_id, episode_id)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.put("/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}", summary="更新分集单个分镜信息")
    def update_episode_beat(project_id: str, episode_id: str, beat_id: str, payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.update_episode_beat(project_id, episode_id, beat_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-sketch", status_code=202, summary="AI 生成分镜草图")
    def generate_beat_sketch(project_id: str, episode_id: str, beat_id: str, payload: dict = None, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.generate_beat_sketch(project_id, episode_id, beat_id, payload or {})
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-render", status_code=202, summary="把草图精绘为渲染图")
    def generate_beat_render(project_id: str, episode_id: str, beat_id: str, payload: dict = None, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.generate_beat_render(project_id, episode_id, beat_id, payload or {})
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/episodes/{episode_id}/generate-images", status_code=202, summary="批量生成分镜草图或渲染图")
    def generate_beat_images_batch(project_id: str, episode_id: str, payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.generate_beat_images_batch(project_id, episode_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post(
        "/api/projects/{project_id}/episodes/{episode_id}/generate-video",
        status_code=202,
        summary="一键生成整集 MiniMax H3 视频",
    )
    def generate_episode_video(project_id: str, episode_id: str, user: dict = Depends(mutating_user)):
        try:
            return EpisodeVideoService.create_job(project_id, episode_id)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"创建视频任务失败: {err}")

    # --- 4. 全部任务 Jobs ---
    @app.get("/api/projects/{project_id}/jobs", summary="获取项目生成任务列表")
    def list_jobs(project_id: str, user: dict = Depends(current_user)):
        return ProjectDetailService.list_jobs(project_id)

    @app.post("/api/projects/{project_id}/jobs", summary="创建任务")
    def create_job(project_id: str, payload: dict, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.create_job(project_id, payload)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/projects/{project_id}/jobs/{job_id}/retry", summary="重试任务")
    def retry_job(project_id: str, job_id: str, user: dict = Depends(mutating_user)):
        try:
            return ProjectDetailService.retry_job(project_id, job_id)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))
