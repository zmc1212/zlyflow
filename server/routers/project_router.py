from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models import ProjectCreateRequest, ProjectItem, ProjectUpdateRequest
from ..services.project_detail_service import ProjectDetailService
from ..services.episode_video_service import EpisodeVideoService
from ..services.llm_service import LlmService
from ..services.project_service import ProjectService

router = APIRouter(prefix="/api/projects", tags=["项目管理"])


@router.get("", response_model=list[ProjectItem], summary="获取项目列表")
def list_projects():
    try:
        return ProjectService.list_projects()
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"获取项目列表失败: {err}")


@router.post("", response_model=ProjectItem, summary="创建项目")
def create_project(payload: ProjectCreateRequest):
    try:
        return ProjectService.create_project(payload)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"创建项目失败: {err}")


@router.get("/{project_id}", response_model=ProjectItem, summary="获取项目详情")
def get_project(project_id: str):
    item = ProjectService.get_project(project_id)
    if not item:
        raise HTTPException(status_code=404, detail="项目不存在")
    return item


@router.put("/{project_id}", response_model=ProjectItem, summary="更新项目")
def update_project(project_id: str, payload: ProjectUpdateRequest):
    try:
        return ProjectService.update_project(project_id, payload)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"更新项目失败: {err}")


@router.delete("/{project_id}", summary="删除项目")
def delete_project(project_id: str):
    success = ProjectService.delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="项目不存在或已被删除")
    return {"status": "ok", "message": "项目删除成功", "id": project_id}


# --- 1. 内容库 Documents ---
@router.get("/{project_id}/documents", summary="获取项目文档列表")
def list_documents(project_id: str):
    return ProjectDetailService.list_documents(project_id)


@router.post("/{project_id}/documents", summary="导入或粘贴项目文档")
def create_document(project_id: str, payload: dict):
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


@router.delete("/{project_id}/documents/{doc_id}", summary="删除项目文档")
def delete_document(project_id: str, doc_id: str):
    success = ProjectDetailService.delete_document(project_id, doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="文档不存在或已被删除")
    return {"status": "ok", "id": doc_id}


@router.post("/{project_id}/documents/{doc_id}/transfer-assets", summary="将文档提取的角色场景道具转入资产库")
def transfer_assets(project_id: str, doc_id: str):
    try:
        return ProjectDetailService.transfer_assets_from_document(project_id, doc_id)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/{project_id}/documents/{doc_id}/transfer-episodes", summary="将文档提取的分集与分镜同步至剧集工坊")
def transfer_episodes(project_id: str, doc_id: str):
    try:
        return ProjectDetailService.transfer_episodes_from_document(project_id, doc_id)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


# --- 2. 资产库 Assets ---
@router.get("/{project_id}/assets", summary="获取项目资产列表")
def list_assets(project_id: str, kind: str | None = None):
    return ProjectDetailService.list_assets(project_id, kind)


@router.post("/{project_id}/assets", summary="创建项目资产")
def create_asset(project_id: str, payload: dict):
    try:
        return ProjectDetailService.create_asset(project_id, payload)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/{project_id}/assets/generate-character-content", summary="AI 生成角色容貌、服饰和生图提示词")
def generate_character_content(project_id: str, payload: dict):
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


@router.put("/{project_id}/assets/{asset_id}", summary="更新项目资产")
def update_asset(project_id: str, asset_id: str, payload: dict):
    try:
        return ProjectDetailService.update_asset(project_id, asset_id, payload)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.delete("/{project_id}/assets/{asset_id}", summary="删除项目资产")
def delete_asset(project_id: str, asset_id: str):
    success = ProjectDetailService.delete_asset(project_id, asset_id)
    if not success:
        raise HTTPException(status_code=404, detail="资产不存在或已被删除")
    return {"status": "ok", "id": asset_id}


@router.post("/{project_id}/assets/generate-batch", status_code=202, summary="按最大并发批量提交角色头像或造型图任务")
def generate_character_images_batch(project_id: str, payload: dict = None):
    try:
        return ProjectDetailService.enqueue_character_images_batch(project_id, payload or {})
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/{project_id}/assets/{asset_id}/generate", summary="AI 生成或重新生成资产形象图")
def generate_asset_image(project_id: str, asset_id: str, payload: dict):
    try:
        return ProjectDetailService.generate_asset_image(project_id, asset_id, payload)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/{project_id}/assets/{asset_id}/enrich-llm", summary="为单个资产排队大模型档案补全")
def enrich_asset_llm(project_id: str, asset_id: str):
    try:
        return ProjectDetailService.enqueue_asset_llm_fill(project_id, asset_id)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


# --- 3. 剧集工坊 Episodes ---
@router.get("/{project_id}/episodes", summary="获取项目剧集工坊列表")
def list_episodes(project_id: str):
    return ProjectDetailService.list_episodes(project_id)


@router.post("/{project_id}/episodes", summary="新建剧集")
def create_episode(project_id: str, payload: dict):
    try:
        return ProjectDetailService.create_episode(project_id, payload)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.put("/{project_id}/episodes/{episode_id}", summary="更新剧集")
def update_episode(project_id: str, episode_id: str, payload: dict):
    try:
        return ProjectDetailService.update_episode(project_id, episode_id, payload)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.delete("/{project_id}/episodes/{episode_id}", summary="删除剧集")
def delete_episode(project_id: str, episode_id: str):
    success = ProjectDetailService.delete_episode(project_id, episode_id)
    if not success:
        raise HTTPException(status_code=404, detail="剧集不存在或已被删除")
    return {"status": "ok", "id": episode_id}


@router.get("/{project_id}/episodes/{episode_id}", summary="获取分集详细分镜与资产关联")
def get_episode_detail(project_id: str, episode_id: str):
    try:
        return ProjectDetailService.get_episode_detail(project_id, episode_id)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.put("/{project_id}/episodes/{episode_id}/beats/{beat_id}", summary="更新分集单个分镜信息")
def update_episode_beat(project_id: str, episode_id: str, beat_id: str, payload: dict):
    try:
        return ProjectDetailService.update_episode_beat(project_id, episode_id, beat_id, payload)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-sketch", status_code=202, summary="AI 生成分镜草图")
def generate_beat_sketch(project_id: str, episode_id: str, beat_id: str, payload: dict = None):
    try:
        return ProjectDetailService.generate_beat_sketch(project_id, episode_id, beat_id, payload or {})
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-render", status_code=202, summary="把草图精绘为渲染图")
def generate_beat_render(project_id: str, episode_id: str, beat_id: str, payload: dict = None):
    try:
        return ProjectDetailService.generate_beat_render(project_id, episode_id, beat_id, payload or {})
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/{project_id}/episodes/{episode_id}/beats/{beat_id}/h3-prompt", status_code=202, summary="调用大模型生成或优化 H3 视频生成提示词")
def generate_beat_h3_prompt(project_id: str, episode_id: str, beat_id: str, payload: dict = None):
    try:
        return ProjectDetailService.generate_beat_h3_prompt(project_id, episode_id, beat_id, payload or {})
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/{project_id}/episodes/{episode_id}/generate-images", status_code=202, summary="批量生成分镜草图或渲染图")
def generate_beat_images_batch(project_id: str, episode_id: str, payload: dict):
    try:
        return ProjectDetailService.generate_beat_images_batch(project_id, episode_id, payload)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post(
    "/{project_id}/episodes/{episode_id}/generate-required-assets",
    status_code=202,
    summary="提交当前集尚未出图的主角头像、场景主图和道具参考图",
)
def generate_episode_required_assets(project_id: str, episode_id: str, payload: dict = None):
    try:
        return ProjectDetailService.enqueue_episode_required_assets(project_id, episode_id, payload or {})
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post(
    "/{project_id}/episodes/{episode_id}/generate-video",
    status_code=202,
    summary="一键生成整集 MiniMax H3 视频",
)
def generate_episode_video(project_id: str, episode_id: str, payload: dict = None):
    try:
        return EpisodeVideoService.create_job(project_id, episode_id, payload or {})
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"创建视频任务失败: {err}")


# --- 4. 全部任务 Jobs ---
@router.get("/{project_id}/jobs", summary="获取项目生成任务列表")
def list_jobs(project_id: str):
    return ProjectDetailService.list_jobs(project_id)


@router.get("/{project_id}/jobs/{job_id}", summary="获取指定任务详情")
def get_job(project_id: str, job_id: str):
    job = ProjectDetailService.get_job(project_id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")
    return job


@router.post("/{project_id}/jobs", summary="创建任务")
def create_job(project_id: str, payload: dict):
    try:
        return ProjectDetailService.create_job(project_id, payload)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/{project_id}/jobs/cancel-all", summary="取消项目下全部未完成任务")
def cancel_all_jobs(project_id: str):
    try:
        return ProjectDetailService.cancel_all_jobs(project_id)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/{project_id}/jobs/{job_id}/retry", summary="重试任务")
def retry_job(project_id: str, job_id: str):
    try:
        return ProjectDetailService.retry_job(project_id, job_id)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))

