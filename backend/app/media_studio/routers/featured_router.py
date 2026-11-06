from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, HTTPException, Path

from ..services.featured_works_service import FeaturedWorksService


def register_featured_work_routes(
    app: Any,
    *,
    current_user: Callable,
    mutating_admin_user: Callable,
    canvas_store: Any = None,
) -> None:
    """首页「精选作品」：登录用户只读 + 可复制到我的短剧，管理员发布/下架。

    canvas_store 在 lifespan 里才挂到 app.state，这里接受惰性 getter 以免模块导入期取值。
    """
    canvas_store_getter = canvas_store if callable(canvas_store) else (lambda: canvas_store)

    @app.get("/api/featured-works", summary="获取精选作品列表")
    def list_featured_works(user: dict = Depends(current_user)):
        return FeaturedWorksService.list_published()

    @app.get("/api/featured-works/{featured_id}", summary="获取精选作品只读详情")
    def get_featured_work(featured_id: str = Path(description="精选作品 ID。"), user: dict = Depends(current_user)):
        work = FeaturedWorksService.get_published(featured_id)
        if not work:
            raise HTTPException(status_code=404, detail="精选作品不存在或已下架")
        return work

    @app.post("/api/featured-works/{featured_id}/copy", summary="复制精选作品到我的短剧")
    def copy_featured_work(featured_id: str = Path(description="精选作品 ID。"), user: dict = Depends(current_user)):
        try:
            return FeaturedWorksService.copy_to_user(featured_id, user["id"], canvas_store=canvas_store_getter())
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.post("/api/admin/featured-works", summary="发布或更新精选作品")
    def publish_featured_work(payload: dict | None = None, user: dict = Depends(mutating_admin_user)):
        try:
            return FeaturedWorksService.publish(payload or {}, user["id"])
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.delete("/api/admin/featured-works/{featured_id}", summary="下架精选作品")
    def unpublish_featured_work(featured_id: str = Path(description="精选作品 ID。"), user: dict = Depends(mutating_admin_user)):
        if not FeaturedWorksService.unpublish(featured_id):
            raise HTTPException(status_code=404, detail="精选作品不存在或已下架")
        return {"status": "ok", "id": featured_id}
