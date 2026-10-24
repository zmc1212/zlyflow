from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .protocol import MAX_FILE_BYTES, MAX_FILES, DiagnosisCreate
from .repository import DiagnosisConflict, DiagnosisNotFound
from .sources import extract_source


class RetryRequest(BaseModel):
    client_request_id: str = Field(min_length=8, max_length=96, pattern=r"^[a-zA-Z0-9_-]+$", description="本次重试的幂等提交键，网络重试时复用同一值。")


DiagnosisId = Annotated[str, Path(description="当前账号拥有的剧本诊断 ID。")]


def register_diagnosis_routes(app, *, current_user, mutating_user):
    router = APIRouter(prefix="/api/script-diagnoses", tags=["导演台"])

    def service():
        return app.state.script_diagnosis

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DiagnosisNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except DiagnosisConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/capabilities", summary="读取剧本诊断能力与可用状态")
    def capabilities(user: dict = Depends(current_user)):
        return service().capabilities()

    @router.get("/source-document", summary="预览待诊断的项目文档")
    def source_document(project_id: Annotated[str, Query(description="来源导演工程 ID。")],
                        document_id: Annotated[str, Query(description="该工程内的剧本文档 ID。")], user: dict = Depends(current_user)):
        return call(service().document_source, project_id, document_id)

    @router.post("/extract", summary="提取诊断文件正文，不发起模型请求")
    async def extract(files: list[UploadFile] = File(..., description="按选择顺序上传的 1–10 份剧本，每份不超过20MB。"),
                      user: dict = Depends(mutating_user)):
        if not 1 <= len(files) <= MAX_FILES:
            raise HTTPException(400, "一次需要 1–10 份剧本")
        sources = []
        for file in files:
            try:
                data = await file.read(MAX_FILE_BYTES + 1)
                item = await run_in_threadpool(extract_source, file.filename or "剧本", data)
                sources.append(item)
            except ValueError as exc:
                sources.append({"name": file.filename or "剧本", "error": str(exc)})
            finally:
                await file.close()
        return {"sources": sources}

    @router.get("", summary="读取当前账号诊断历史摘要")
    def history(document_id: str | None = Query(None, description="可选来源文档 ID，用于筛选当前剧本的诊断。"),
                offset: int = Query(0, ge=0, description="从零开始的分页偏移。"),
                limit: int = Query(30, ge=1, le=100, description="每页条数，最多100条。"), user: dict = Depends(current_user)):
        return service().repo.list(user["id"], document_id=document_id, offset=offset, limit=limit)

    @router.post("", status_code=202, summary="创建剧本诊断")
    def create(payload: DiagnosisCreate, user: dict = Depends(mutating_user)):
        return call(service().create, user["id"], payload.model_dump())

    @router.get("/{diagnosis_id}", summary="读取输入快照、进度与报告")
    def detail(diagnosis_id: DiagnosisId, user: dict = Depends(current_user)):
        return call(service().repo.get, user["id"], diagnosis_id)

    @router.post("/{diagnosis_id}/cancel", summary="取消剧本诊断")
    def cancel(diagnosis_id: DiagnosisId, user: dict = Depends(mutating_user)):
        return call(service().cancel, user["id"], diagnosis_id)

    @router.post("/{diagnosis_id}/retry", status_code=202, summary="使用原输入快照重新诊断")
    def retry(diagnosis_id: DiagnosisId, payload: RetryRequest, user: dict = Depends(mutating_user)):
        return call(service().retry, user["id"], diagnosis_id, payload.client_request_id)

    @router.delete("/{diagnosis_id}", summary="删除已结束的诊断")
    def delete(diagnosis_id: DiagnosisId, user: dict = Depends(mutating_user)):
        call(service().repo.delete, user["id"], diagnosis_id)
        return {"status": "deleted"}

    app.include_router(router)
