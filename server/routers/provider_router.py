from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models import (
    CatalogModelCreateRequest,
    CatalogModelsBatchUpdateRequest,
    CatalogPayload,
    ComfyConfigResponse,
    ComfyTestRequest,
    ComfyUpdateRequest,
    GrsBalanceResponse,
    GrsConfigResponse,
    GrsTestRequest,
    GrsUpdateRequest,
    LlmCatalogResponse,
    LlmConfigResponse,
    LlmTestRequest,
    LlmUpdateRequest,
    QiniuConfigResponse,
    QiniuTestRequest,
    QiniuUpdateRequest,
)
from ..services.comfy_service import ComfyService
from ..services.grs_service import GrsService
from ..services.llm_service import LlmService
from ..services.qiniu_service import QiniuService

router = APIRouter(prefix="/api/admin/providers", tags=["管理设置"])


# --- ComfyUI ---
@router.get("/comfy", response_model=ComfyConfigResponse, summary="获取 ComfyUI 配置")
def get_comfy_config():
    return ComfyService.get_config()


@router.put("/comfy", response_model=ComfyConfigResponse, summary="更新 ComfyUI 配置")
def update_comfy_config(payload: ComfyUpdateRequest):
    try:
        return ComfyService.update_config(payload.base_url)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/comfy/test", response_model=ComfyConfigResponse, summary="测试 ComfyUI 连接")
def test_comfy_connection(payload: ComfyTestRequest | None = None):
    try:
        return ComfyService.test_connection(payload.base_url if payload else None)
    except Exception as err:
        raise HTTPException(status_code=502, detail=str(err))


# --- GRS ---
@router.get("/grs", response_model=GrsConfigResponse, summary="获取 GRS 配置")
def get_grs_config():
    return GrsService.get_config()


@router.put("/grs", response_model=GrsConfigResponse, summary="更新 GRS 配置")
def update_grs_config(payload: GrsUpdateRequest):
    try:
        return GrsService.update_config(payload)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/grs/test", response_model=GrsConfigResponse, summary="测试 GRS 连接")
def test_grs_connection(payload: GrsTestRequest | None = None):
    try:
        return GrsService.test_connection(
            base_url=payload.base_url if payload else None,
            api_key=payload.api_key if payload else None,
        )
    except Exception as err:
        raise HTTPException(status_code=502, detail=str(err))


@router.post("/grs/balance", response_model=GrsBalanceResponse, summary="查询 GRS 余额")
def query_grs_balance():
    return GrsService.get_balance()


@router.get("/grs/models", response_model=CatalogPayload, summary="获取 GRS 生图模型目录")
def get_grs_models():
    return GrsService.get_models_catalog()


@router.put("/grs/models", response_model=CatalogPayload, summary="批量更新 GRS 生图模型")
def batch_update_grs_models(payload: CatalogModelsBatchUpdateRequest):
    return GrsService.batch_update_models(payload.models)


@router.post("/grs/models", response_model=CatalogPayload, summary="新增 GRS 自定义生图模型")
def create_grs_model(payload: CatalogModelCreateRequest):
    return GrsService.create_model(payload)


# --- LLM ---
@router.get("/llm", response_model=LlmConfigResponse, summary="获取 LLM 大模型配置")
def get_llm_config():
    return LlmService.get_config()


@router.put("/llm", response_model=LlmConfigResponse, summary="更新 LLM 大模型配置")
def update_llm_config(payload: LlmUpdateRequest):
    try:
        return LlmService.update_config(payload)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/llm/test", response_model=LlmConfigResponse, summary="测试 LLM 对话连通性")
def test_llm_connection(payload: LlmTestRequest | None = None):
    try:
        return LlmService.test_connection(payload)
    except Exception as err:
        raise HTTPException(status_code=502, detail=str(err))


@router.post("/llm/models", response_model=LlmCatalogResponse, summary="从上游拉取可用模型列表")
def list_llm_models(payload: LlmTestRequest | None = None):
    return LlmService.list_models_catalog(payload)


# --- 七牛云存储 ---
@router.get("/qiniu", response_model=QiniuConfigResponse, summary="获取七牛云存储配置")
def get_qiniu_config():
    return QiniuService.get_config()


@router.put("/qiniu", response_model=QiniuConfigResponse, summary="更新七牛云存储配置")
def update_qiniu_config(payload: QiniuUpdateRequest):
    try:
        return QiniuService.update_config(payload)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/qiniu/test", response_model=QiniuConfigResponse, summary="测试七牛云存储连通性")
def test_qiniu_connection(payload: QiniuTestRequest | None = None):
    try:
        return QiniuService.test_connection(payload)
    except Exception as err:
        raise HTTPException(status_code=502, detail=str(err))
