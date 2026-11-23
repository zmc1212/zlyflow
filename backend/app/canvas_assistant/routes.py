"""画布智能助手路由：普通 JSON + 一条可恢复的 SSE 事件流。

与导演台助手路由（director_assistant/routes.py）同构，prefix 换成
/api/canvas-assistant，去掉知识库/资源/剪辑采纳端点，新增提案应用结果上报。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from .protocol import MessageCreate, SessionCreate
from .repository import AssistantConflict, AssistantNotFound
from .service import TERMINAL, CanvasAssistantService


def register_canvas_assistant_routes(app: Any, *, current_user: Callable, mutating_user: Callable):
    router = APIRouter(prefix="/api/canvas-assistant", tags=["画布"])

    def service() -> CanvasAssistantService:
        return app.state.canvas_assistant

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AssistantNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except AssistantConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/catalog", summary="读取画布助手可选模型与可用性")
    def catalog(user: dict = Depends(current_user)):
        return call(service().catalog, user["id"])

    @router.get("/sessions", summary="读取当前账号的画布助手历史会话")
    def sessions(user: dict = Depends(current_user)):
        return sorted(service().repo.list(user["id"], "session", limit=1000), key=lambda s: s["updated_at"], reverse=True)

    @router.post("/sessions", status_code=201, summary="创建绑定画布的助手会话")
    def create_session(payload: SessionCreate, user: dict = Depends(mutating_user)):
        return call(service().create_session, user["id"], payload.model_dump())

    @router.get("/sessions/{sid}", summary="读取会话、消息与画布提案")
    def detail(sid: str, user: dict = Depends(current_user)):
        return call(service().detail, user["id"], sid)

    @router.patch("/sessions/{sid}", summary="更新会话名称或模型选择")
    def update_session(sid: str, payload: dict, user: dict = Depends(mutating_user)):
        return call(service().update_session, user["id"], sid, payload)

    @router.post("/sessions/{sid}/messages", status_code=202, summary="发送消息或提交澄清问题答案")
    def send(sid: str, payload: MessageCreate, user: dict = Depends(mutating_user)):
        return call(service().send, user["id"], sid, payload.model_dump())

    @router.get("/runs/{rid}", summary="读取画布助手本轮运行状态")
    def get_run(rid: str, user: dict = Depends(current_user)):
        return call(service().repo.get, user["id"], rid, "run")

    @router.post("/runs/{rid}/cancel", summary="停止助手当前回复")
    def cancel(rid: str, user: dict = Depends(mutating_user)):
        return call(service().cancel, user["id"], rid)

    @router.post("/runs/{rid}/retry", status_code=202, summary="重试中断的画布操作")
    def retry(rid: str, payload: dict, user: dict = Depends(mutating_user)):
        key = str(payload.get("client_message_id") or "")
        if not 8 <= len(key) <= 96:
            raise HTTPException(400, "请提供有效的提交标识")
        return call(service().retry, user["id"], rid, key)

    @router.get("/runs/{rid}/events", summary="订阅可恢复的画布助手运行事件")
    async def events(rid: str, request: Request, since: int = 0, user: dict = Depends(current_user)):
        call(service().repo.get, user["id"], rid, "run")
        try:
            cursor = max(0, since, int(request.headers.get("last-event-id") or 0))
        except ValueError:
            raise HTTPException(400, "事件序号无效") from None

        async def stream():
            nonlocal cursor
            idle = 0
            while not await request.is_disconnected():
                batch = await asyncio.to_thread(service().repo.events, user["id"], rid, cursor)
                for event in batch:
                    cursor = event["seq"]
                    yield f"id: {cursor}\nevent: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                run = await asyncio.to_thread(service().repo.get, user["id"], rid, "run")
                if run["status"] in TERMINAL and len(batch) < 200:
                    yield f"event: terminal\ndata: {json.dumps({'status': run['status']})}\n\n"
                    return
                idle += 1
                if idle % 30 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(.35)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/proposals/{pid}/apply-result", summary="上报画布提案的应用结果（前端执行后回写）")
    def apply_result(pid: str, payload: dict, user: dict = Depends(mutating_user)):
        return call(service().actions.apply_result, user["id"], pid,
                    str(payload.get("result") or ""), payload.get("detail"))

    app.include_router(router)
