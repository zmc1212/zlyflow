from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from .xiaji_project_store import XiajiProjectStore


class XiajiProjectCreate(BaseModel):
    name: str = Field(default="", max_length=255)
    settings: dict[str, Any] = Field(default_factory=dict)


class XiajiProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    settings: dict[str, Any] | None = None


def require_xiaji_project(app: Any, project_id: str, owner_user_id: str) -> dict[str, Any]:
    if not (project_id or "").strip():
        raise HTTPException(status_code=422, detail="请选择项目")
    try:
        return app.state.xiaji_project_store.get_project(project_id.strip(), owner_user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="项目不存在") from error


def register_xiaji_project_routes(app: Any, *, current_user: Callable, mutating_user: Callable) -> None:
    router = APIRouter(prefix="/api/xiaji", tags=["导台2"])

    def store() -> XiajiProjectStore:
        return app.state.xiaji_project_store

    @router.get("/projects", summary="列出当前用户的导台2 项目")
    def list_projects(user: dict = Depends(current_user)) -> list[dict]:
        return store().list_projects(user["id"])

    @router.post("/projects", status_code=201, summary="新建导台2 项目")
    def create_project(payload: XiajiProjectCreate, user: dict = Depends(mutating_user)) -> dict:
        return store().create_project(user["id"], payload.name, payload.settings)

    @router.get("/projects/{project_id}", summary="读取导台2 项目")
    def get_project(project_id: str, user: dict = Depends(current_user)) -> dict:
        return require_xiaji_project(app, project_id, user["id"])

    @router.patch("/projects/{project_id}", summary="更新导台2 项目名称或设置")
    def update_project(project_id: str, payload: XiajiProjectUpdate, user: dict = Depends(mutating_user)) -> dict:
        require_xiaji_project(app, project_id, user["id"])
        try:
            return store().update_project(
                project_id,
                user["id"],
                name=payload.name,
                settings=payload.settings,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.delete("/projects/{project_id}", summary="删除导台2 项目及其内容库、资产")
    def delete_project(project_id: str, user: dict = Depends(mutating_user)) -> dict:
        require_xiaji_project(app, project_id, user["id"])
        store().delete_project(project_id, user["id"])
        return {"ok": True}

    app.include_router(router)
