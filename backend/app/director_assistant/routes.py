from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from .knowledge import MAX_UPLOAD
from .protocol import MessageCreate, SessionCreate
from .repository import AssistantConflict, AssistantNotFound
from .service import AssistantService, TERMINAL


def register_assistant_routes(app: Any, *, current_user: Callable, mutating_user: Callable):
    router = APIRouter(prefix="/api/director-assistant", tags=["导演台"])

    def service() -> AssistantService:
        return app.state.director_assistant

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AssistantNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except AssistantConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def manages_platform(user: dict) -> bool:
        return str(user.get("role") or "") in {"admin", "super_admin"}

    def manage_resource(user: dict, resource_id: str) -> tuple[dict, bool]:
        resource = call(service().repo.get, user["id"], resource_id, "resource", shared=True)
        if resource.get("builtin"):
            raise HTTPException(403, "内置资源不可修改")
        platform = bool(resource.get("platform"))
        if platform and not manages_platform(user):
            raise HTTPException(403, "需要管理员权限")
        return resource, platform

    @router.get("/catalog", summary="读取助手资源、知识库及可选模型")
    def catalog(user: dict = Depends(current_user)):
        return call(service().catalog, user["id"], can_manage_platform=manages_platform(user))

    @router.get("/sessions", summary="读取当前账号的助手历史会话")
    def sessions(user: dict = Depends(current_user)):
        return sorted(service().repo.list(user["id"], "session", limit=1000), key=lambda s: s["updated_at"], reverse=True)

    @router.post("/sessions", status_code=201, summary="创建可选关联工程的助手会话")
    def create_session(payload: SessionCreate, user: dict = Depends(mutating_user)):
        return call(service().create_session, user["id"], payload.model_dump())

    @router.get("/sessions/{sid}", summary="读取会话、消息、草稿与媒体提案")
    def detail(sid: str, user: dict = Depends(current_user)):
        return call(service().detail, user["id"], sid)

    @router.patch("/sessions/{sid}", summary="更新会话选择或名称")
    def update_session(sid: str, payload: dict, user: dict = Depends(mutating_user)):
        return call(service().update_session, user["id"], sid, payload)

    @router.post("/sessions/{sid}/messages", status_code=202, summary="发送消息或提交澄清问题答案")
    def send(sid: str, payload: MessageCreate, user: dict = Depends(mutating_user)):
        return call(service().send, user["id"], sid, payload.model_dump())

    @router.get("/runs/{rid}", summary="读取助手本轮运行状态")
    def get_run(rid: str, user: dict = Depends(current_user)):
        return call(service().repo.get, user["id"], rid, "run")

    @router.post("/runs/{rid}/cancel", summary="停止助手当前回复")
    def cancel(rid: str, user: dict = Depends(mutating_user)):
        return call(service().cancel, user["id"], rid)

    @router.post("/runs/{rid}/retry", status_code=202, summary="重试中断的助手创作")
    def retry(rid: str, payload: dict, user: dict = Depends(mutating_user)):
        key = str(payload.get("client_message_id") or "")
        if not 8 <= len(key) <= 96:
            raise HTTPException(400, "请提供有效的提交标识")
        return call(service().retry, user["id"], rid, key)

    @router.get("/runs/{rid}/events", summary="订阅可恢复的助手运行事件")
    async def events(rid: str, request: Request, since: int = 0, user: dict = Depends(current_user)):
        call(service().repo.get, user["id"], rid, "run")
        try:
            cursor = max(0, since, int(request.headers.get("last-event-id") or 0))
        except ValueError:
            raise HTTPException(400, "事件序号无效")

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
                    # A terminal snapshot also covers the tiny commit/emit gap.
                    yield f"event: terminal\ndata: {json.dumps({'status': run['status']})}\n\n"
                    return
                idle += 1
                if idle % 30 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(.35)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/resources", status_code=201, summary="创建个人或平台 Skill 或专家")
    def create_resource(payload: dict, user: dict = Depends(mutating_user)):
        scope = str(payload.get("scope") or "personal")
        if scope not in {"personal", "platform"}:
            raise HTTPException(400, "资源范围无效")
        if scope == "platform":
            if not manages_platform(user):
                raise HTTPException(403, "需要管理员权限")
            return call(service().resources.save, "", payload, platform=True)
        return call(service().resources.save, user["id"], payload)

    @router.put("/resources/{resource_id}", summary="编辑个人或平台资源并创建新版本")
    def update_resource(resource_id: str, payload: dict, user: dict = Depends(mutating_user)):
        _, platform = manage_resource(user, resource_id)
        return call(service().resources.save, "" if platform else user["id"], payload, resource_id=resource_id, platform=platform)

    @router.delete("/resources/{resource_id}", summary="删除个人或平台资源并保留历史引用")
    def delete_resource(resource_id: str, user: dict = Depends(mutating_user)):
        resource, platform = manage_resource(user, resource_id)
        return call(service().repo.update, "" if platform else user["id"], resource, {}, status="deleted")

    @router.put("/resources/{resource_id}/favorite", summary="收藏或取消收藏创作资源")
    def favorite(resource_id: str, payload: dict, user: dict = Depends(mutating_user)):
        call(service().resources.favorite, user["id"], resource_id, bool(payload.get("enabled")))
        return {"status": "ok"}

    @router.post("/resources/import-preview", summary="预览 Skill 文本或资料包导入内容")
    async def import_preview(file: UploadFile = File(...), user: dict = Depends(mutating_user)):
        content = await file.read(5 * 1024 * 1024 + 1)
        return call(service().resources.import_preview, file.filename or "", content)

    @router.get("/resources/{resource_id}/export", summary="导出 Skill 或专家文本资料包")
    def export_resource(resource_id: str, user: dict = Depends(current_user)):
        data = call(service().resources.export, user["id"], resource_id)
        return Response(data, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="skill.zip"'})

    @router.post("/knowledge", status_code=201, summary="创建个人知识库")
    def create_knowledge(payload: dict, user: dict = Depends(mutating_user)):
        name = str(payload.get("name") or "").strip()
        if not name or len(name) > 100:
            raise HTTPException(400, "知识库名称需为1–100字")
        return service().repo.insert(user["id"], "knowledge", {"name": name, "description": str(payload.get("description") or "")[:500], "builtin": False})

    @router.delete("/knowledge/{kid}", summary="删除个人知识库并保留历史引用")
    def delete_knowledge(kid: str, user: dict = Depends(mutating_user)):
        kb = call(service().repo.get, user["id"], kid, "knowledge")
        return call(service().repo.update, user["id"], kb, {}, status="deleted")

    @router.post("/knowledge/{kid}/documents", status_code=202, summary="上传并解析知识库资料")
    async def upload_knowledge(kid: str, file: UploadFile = File(...), user: dict = Depends(mutating_user)):
        content = await file.read(MAX_UPLOAD + 1)
        return call(service().knowledge.upload, user["id"], kid, file.filename or "", content)

    @router.post("/knowledge/documents/{did}/retry", status_code=202, summary="重试失败的文档解析")
    def retry_document(did: str, user: dict = Depends(mutating_user)):
        return call(service().knowledge.retry, user["id"], did)

    @router.delete("/knowledge/documents/{did}", summary="移除个人知识库中的文档")
    def delete_document(did: str, user: dict = Depends(mutating_user)):
        doc = call(service().repo.get, user["id"], did, "knowledge_document")
        return call(service().repo.update, user["id"], doc, {}, status="deleted")

    @router.post("/artifacts/{aid}/preview", summary="预览采纳草稿对目标工程的变更")
    def preview(aid: str, payload: dict, user: dict = Depends(mutating_user)):
        return call(service().actions.preview, user["id"], aid, str(payload.get("project_id") or ""), payload.get("mapping"))

    @router.post("/applications/{application_id}/apply", summary="采纳预览并幂等写入项目")
    def apply(application_id: str, user: dict = Depends(mutating_user)):
        return call(service().actions.apply, user["id"], application_id)

    @router.get("/artifacts/{aid}/export", summary="导出完整创作草稿")
    def export_artifact(aid: str, user: dict = Depends(current_user)):
        artifact = call(service().repo.get, user["id"], aid, "artifact")
        return Response(artifact["content"], media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="artifact.md"'})

    @router.post("/media/{pid}/confirm", status_code=202, summary="确认并执行媒体生成提案")
    def confirm_media(pid: str, user: dict = Depends(mutating_user)):
        return call(service().actions.confirm_media, user["id"], pid)

    app.include_router(router)
