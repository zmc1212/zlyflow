from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .logging_setup import (
    debugger_hint,
    setup_logging,
    start_heartbeat,
    track_request_end,
    track_request_start,
)
from .routers.project_router import router as project_router
from .routers.provider_router import router as provider_router
from .services.episode_video_service import EpisodeVideoService
from .services.storyboard_image_service import StoryboardImageService

setup_logging()
logger = logging.getLogger("server.http")

app = FastAPI(
    title="AI Media SaaS API",
    description="AI 智能媒体生成平台服务端 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:8]
        path = f"{request.method} {request.url.path}"
        quiet = request.method == "GET" and (
            path.endswith("/health") or path.endswith("/jobs") or path.endswith("/docs") or path.endswith("/openapi.json")
        )
        track_request_start(request_id, path)
        started = time.monotonic()
        if not quiet:
            logger.info("start %s id=%s", path, request_id)
        try:
            response = await call_next(request)
            elapsed_ms = (time.monotonic() - started) * 1000
            if not quiet or elapsed_ms >= 2000:
                logger.info("done %s id=%s status=%s %.0fms", path, request_id, response.status_code, elapsed_ms)
            return response
        except Exception:
            logger.exception("fail %s id=%s", path, request_id)
            raise
        finally:
            track_request_end(request_id)


app.add_middleware(RequestLogMiddleware)
app.include_router(provider_router)
app.include_router(project_router)


@app.on_event("startup")
def recover_interrupted_video_jobs():
    hint = debugger_hint()
    logging.getLogger("server").info("startup %s", hint)
    if hint["debugpy"]:
        logging.getLogger("server").warning(
            "process is attached to debugpy; a breakpoint or debugger freeze will hang all HTTP including /api/health"
        )
    start_heartbeat()
    try:
        EpisodeVideoService.recover_orphaned_jobs()
        StoryboardImageService.recover_interrupted_jobs()
        from .services.llm_fill_job_service import LlmFillJobService
        LlmFillJobService.kick()
        logging.getLogger("server").info("startup recover finished")
    except Exception:
        logging.getLogger("server").exception("startup recover failed")


@app.get("/api/health", summary="健康检查")
async def health_check():
    return {"status": "ok", "service": "ai-media-sass-server"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
