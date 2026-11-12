from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, HTTPException, Path

from ..services.featured_music_service import FeaturedMusicService


def register_featured_music_routes(
    app: Any,
    *,
    current_user: Callable,
    mutating_admin_user: Callable,
) -> None:
    """音乐页「精选音乐」：登录用户浏览，管理员发布 / 更新 / 下架。"""

    @app.get("/api/featured-music", tags=["音乐"], summary="获取精选音乐列表")
    def list_featured_music(user: dict = Depends(current_user)):
        return FeaturedMusicService.list_published()

    @app.get("/api/featured-music/{featured_id}", tags=["音乐"], summary="获取单首精选音乐")
    def get_featured_music(featured_id: str = Path(description="精选音乐 ID。")):
        song = FeaturedMusicService.get_published(featured_id)
        if not song:
            raise HTTPException(status_code=404, detail="精选音乐不存在或已下架")
        return song

    @app.post("/api/admin/featured-music", tags=["音乐"], summary="发布或更新精选音乐")
    def publish_featured_music(payload: dict | None = None, user: dict = Depends(mutating_admin_user)):
        try:
            return FeaturedMusicService.publish(payload or {}, user["id"])
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.delete("/api/admin/featured-music/{featured_id}", tags=["音乐"], summary="下架精选音乐")
    def unpublish_featured_music(featured_id: str = Path(description="精选音乐 ID。"), user: dict = Depends(mutating_admin_user)):
        if not FeaturedMusicService.unpublish(featured_id):
            raise HTTPException(status_code=404, detail="精选音乐不存在或已下架")
        return {"status": "ok", "id": featured_id}
