from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, HTTPException, Path, Query

from ..services.showcase_service import ShowcaseService


def register_showcase_routes(
    app: Any,
    *,
    current_user: Callable,
    mutating_admin_user: Callable,
) -> None:
    """「灵感」示例库：登录用户浏览并一键回填创作台，管理员发布/下架。"""

    @app.get("/api/showcase", tags=["灵感示例"], summary="获取灵感示例列表",
             description="返回已发布的示例卡与分类计数。每条示例都冻结了出片时的 mode、prompt、参数与参考素材，"
                         "可直接在工作台复现同一个任务。")
    def list_showcase(
        user: dict = Depends(current_user),
        category: str = Query(default="", description="按分类筛选，留空返回全部分类。"),
    ):
        return {
            "items": ShowcaseService.list_published(category),
            "categories": ShowcaseService.list_categories(),
        }

    @app.get("/api/showcase/{item_id}", tags=["灵感示例"], summary="获取单条灵感示例",
             description="返回一条已发布示例的完整配方；未发布或已下架的 ID 返回 404。")
    def get_showcase(item_id: str = Path(description="示例 ID。"), user: dict = Depends(current_user)):
        item = ShowcaseService.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="示例不存在或已下架")
        return item

    @app.post("/api/admin/showcase", tags=["管理后台"], summary="发布或更新灵感示例",
              description="按 slug 幂等写入；slug 缺省时由标题生成。mode 必须是工作流注册表里存在的工作流。")
    def publish_showcase(payload: dict | None = None, user: dict = Depends(mutating_admin_user)):
        try:
            return ShowcaseService.publish(payload or {}, user["id"])
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.post("/api/admin/showcase/from-job/{job_id}", tags=["管理后台"], summary="从已完成任务登记灵感示例",
              description="复制该任务真实使用的 mode、prompt、参数与参考素材作为示例配方，再用请求体覆盖标题、简介等展示字段。")
    def publish_showcase_from_job(
        job_id: str = Path(description="来源任务 ID。"),
        payload: dict | None = None,
        user: dict = Depends(mutating_admin_user),
    ):
        try:
            return ShowcaseService.publish_from_job(job_id, payload or {}, user["id"])
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.delete("/api/admin/showcase/{item_id}", tags=["管理后台"], summary="下架灵感示例",
                description="按示例 ID 下架一条灵感示例；ID 不存在时返回 404。")
    def unpublish_showcase(
        item_id: str = Path(description="示例 ID。"),
        user: dict = Depends(mutating_admin_user),
    ):
        if not ShowcaseService.unpublish(item_id):
            raise HTTPException(status_code=404, detail="示例不存在或已下架")
        return {"status": "ok", "id": item_id}
