from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers.project_router import router as project_router
from .routers.provider_router import router as provider_router
from .services.episode_video_service import EpisodeVideoService
from .services.storyboard_image_service import StoryboardImageService

app = FastAPI(
    title="AI Media SaaS API",
    description="AI 智能媒体生成平台服务端 API",
    version="1.0.0",
)

# 配置跨域中间件，允许前端应用本地调试访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(provider_router)
app.include_router(project_router)


@app.on_event("startup")
def recover_interrupted_video_jobs():
    EpisodeVideoService.recover_orphaned_jobs()
    StoryboardImageService.recover_interrupted_jobs()


@app.get("/api/health", summary="健康检查")
def health_check():
    return {"status": "ok", "service": "ai-media-sass-server"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
