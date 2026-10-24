from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from collections import OrderedDict, deque
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import Depends, File, HTTPException, Path, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.routes import build_metadata, cors_middleware, create_auth_routes
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, BaseModel, Field
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from .config import SCOPES, McpConfig
from .editing_service import EditingService
from .oauth import StudioOAuthProvider
from .service import MAX_REFERENCE_BYTES, CreativeService
from .store import digest

LOGGER = logging.getLogger(__name__)


class ConsentDecision(BaseModel):
    allow: bool = Field(description="true 表示允许本次授权，false 表示拒绝。")


class OutputReference(BaseModel):
    job_id: str = Field(min_length=1, max_length=128, description="来源任务 ID。")
    generation_item_id: str = Field(min_length=1, max_length=128, description="来源生成项 ID。")
    output_index: int = Field(ge=0, description="来源生成项输出数组的从 0 开始索引。")


class GatewayGuard:
    def __init__(self, app, config: McpConfig):
        self.app, self.config = app, config
        self.buckets: OrderedDict = OrderedDict()
        self.lock = Lock()

    def limited(self, client: str, route: str, limit: int) -> bool:
        now = time.monotonic()
        key = (client, route)
        with self.lock:
            bucket = self.buckets.setdefault(key, deque())
            self.buckets.move_to_end(key)
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            limited = len(bucket) >= limit
            if not limited:
                bucket.append(now)
            while len(self.buckets) > 4096:
                self.buckets.popitem(last=False)
            return limited

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def reject(status, message, code="invalid_request", headers=None):
            await JSONResponse({"error": code, "error_description": message}, status_code=status,
                               headers={"Cache-Control": "no-store", **(headers or {})})(scope, receive, send)

        if self.config.error:
            return await reject(503, self.config.error, "temporarily_unavailable")
        headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope.get("headers", [])}
        configured = urlsplit(self.config.base)
        try:
            incoming = urlsplit("//" + headers.get("host", ""))
            if incoming.netloc.lower() != configured.netloc.lower() and incoming.hostname not in {"127.0.0.1", "localhost", "::1"}:
                return await reject(403, "Host 与配置的 MCP 地址不匹配")
        except ValueError:
            return await reject(403, "Host 无效")
        path, method = scope.get("path", ""), scope.get("method", "GET")
        if path == "/api/mcp" and headers.get("origin") and headers["origin"].rstrip("/").lower() != self.config.base.lower():
            return await reject(403, "Origin 与配置的工作台地址不匹配")
        client = str((scope.get("client") or ("unknown",))[0])
        if method == "POST" and path.endswith(("/register", "/token", "/revoke")):
            if self.limited(client, path, 10 if path.endswith("/register") else 60):
                return await reject(429, "请求过于频繁，请稍后重试", headers={"Retry-After": "60"})
        body = b""
        if method == "POST":
            maximum = 128 * 1024 if path == "/api/mcp" else 16 * 1024
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body += message.get("body", b"")
                if len(body) > maximum:
                    return await reject(413, "请求内容过大")
                if not message.get("more_body", False):
                    break
        if path.endswith(("/authorize", "/token")) and method in {"GET", "POST"}:
            raw = scope.get("query_string", b"") if method == "GET" else body
            try:
                params = parse_qs(raw.decode("utf8"), max_num_fields=30)
            except (UnicodeDecodeError, ValueError):
                return await reject(400, "授权参数无效")
            # The SDK validates PKCE exchange, but currently treats resource as
            # optional. Enforce RFC 8707 on both legs at the HTTP boundary.
            if params.get("resource") != [self.config.resource]:
                return await reject(400, "resource 必须与当前 MCP 地址完全一致", "invalid_target")
            if path.endswith("/authorize") and (params.get("code_challenge_method") != ["S256"] or
                    not re.fullmatch(r"[A-Za-z0-9_-]{43}", (params.get("code_challenge") or [""])[0])):
                return await reject(400, "必须使用 PKCE S256")
        replayed = False

        async def replay():
            nonlocal replayed
            if method == "POST" and not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def register_mcp_routes(app, *, current_user, mutating_user, settings, submit_generation, public_job,
                        listed_workflows, mode_payload, cancel_job, output_response, output_available,
                        config: McpConfig | None = None):
    config = config or McpConfig.from_env()
    provider = StudioOAuthProvider(app, config)
    service = CreativeService(app, config, settings=settings, submit_generation=submit_generation, public_job=public_job,
        listed_workflows=listed_workflows, mode_payload=mode_payload, cancel_job=cancel_job,
        output_response=output_response, output_available=output_available)
    editing = EditingService(app, config)
    app.state.mcp_config, app.state.mcp_oauth, app.state.mcp_service, app.state.mcp_editing = config, provider, service, editing
    registration = ClientRegistrationOptions(enabled=True, valid_scopes=SCOPES, default_scopes=SCOPES)
    revocation = RevocationOptions(enabled=True)
    sdk = MCPServer("ZLY AI Studio", version="1.0.0", token_verifier=provider,
        instructions="先查询可用工作流与参数，再创建图片或视频任务。参考图先在工作台 /mcp 上传并按 ID 顺序引用。每次新创作生成唯一 request_id，重试保持该标识和参数不变。任务异步执行，使用 studio_get_job 查询，完成后 studio_get_results 获取临时下载链接。剪辑时间线先 studio_list_edit_projects 获取工程与 sequence_id，studio_get_timeline 读取版本，studio_preview_edit 生成待确认方案后再 studio_confirm_edit；标题用 studio_add_text。音轨字幕先 studio_start_transcript 并轮询 studio_get_transcript。成片用 studio_export_edit 导出，可传本机绝对 output_dir 指定保存目录，再用 studio_get_edit_export 轮询。仅操作当前授权账号自己的内容。",
        auth=AuthSettings(issuer_url=AnyHttpUrl(config.issuer), resource_server_url=AnyHttpUrl(config.resource),
                          required_scopes=[], validate_token_resource=True))

    async def run(scope: str, action):
        token = get_access_token()
        if not token or scope not in token.scopes:
            raise ToolError("缺少 " + scope + " 权限，请在客户端重新授权")
        user = provider.active_user(token.subject or "")
        if not user:
            raise ToolError("账号不可用，请重新登录工作台")
        try:
            result = action(user)
            return await result if inspect.isawaitable(result) else result
        except HTTPException as error:
            raise ToolError(str(error.detail)) from error
        except (ValueError, KeyError) as error:
            raise ToolError("创作参数或素材无效，请查询工作流与参考图后重试") from error
        except Exception as error:
            LOGGER.exception("MCP tool failed")
            raise ToolError("工作台暂时无法执行此操作，请稍后重试或在工作台查看任务") from error

    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    create = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_list_workflows(media_type: str | None = None) -> dict[str, Any]:
        """查询当前可用的图片/视频工作流；media_type 可为 image 或 video。"""
        return await run("studio:read", lambda user: {"workflows": service.workflows(media_type)})

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_get_workflow(workflow_id: str) -> dict[str, Any]:
        """查询指定工作流的创作参数、默认值、约束、参考图数量与顺序。创建前必查。"""
        return await run("studio:read", lambda user: service.workflow_detail(workflow_id))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_list_reference_assets() -> dict[str, Any]:
        """列出自己的参考图 ID、名称和尺寸。用户可在工作台 /mcp 上传或选取生成图片。"""
        return await run("studio:read", lambda user: {"references": service.list_references(user)})

    @sdk.tool(annotations=create, structured_output=True)
    async def studio_create_image(workflow_id: str, prompt: str, request_id: str, options: dict[str, Any] | None = None,
                                  reference_asset_ids: list[str] | None = None, negative_prompt: str = "",
                                  image_size: str | None = None, title: str | None = None) -> dict[str, Any]:
        """提交图片创作，将消耗当前图片供应商服务。options 只接受工作流公开的创作参数。新创作使用唯一 request_id，重试保持不变。"""
        return await run("studio:generate", lambda user: service.create(user, "image", workflow_id, prompt, request_id,
            options, reference_asset_ids, negative_prompt, image_size, title))

    @sdk.tool(annotations=create, structured_output=True)
    async def studio_create_video(workflow_id: str, prompt: str, request_id: str, options: dict[str, Any] | None = None,
                                  reference_asset_ids: list[str] | None = None, title: str | None = None) -> dict[str, Any]:
        """提交视频创作到当前视频队列。参考图 ID 的顺序对应 <Picture n>。任务异步执行，新创作使用唯一 request_id，重试保持不变。"""
        return await run("studio:generate", lambda user: service.create(user, "video", workflow_id, prompt, request_id,
            options, reference_asset_ids, title=title))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_list_jobs(limit: int = 20) -> dict[str, Any]:
        """列出自己最近的创作任务及工作台链接，最多 100 条。"""
        return await run("studio:read", lambda user: {"jobs": service.list_jobs(user, limit)})

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_get_job(job_id: str) -> dict[str, Any]:
        """查询自己的任务进度、各生成项状态、创作参数与失败信息。"""
        return await run("studio:read", lambda user: service.summary(service.owned_job(user, job_id)))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_get_results(job_id: str) -> dict[str, Any]:
        """获取自己任务的成功输出及 5 分钟下载链接；部分失败也返回成功项。链接过期后再次调用。"""
        return await run("studio:read", lambda user: service.results(user, job_id))

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True), structured_output=True)
    async def studio_cancel_job(job_id: str) -> dict[str, Any]:
        """停止自己的排队中或生成中任务。"""
        return await run("studio:generate", lambda user: service.cancel(user, job_id))

    edit = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_list_edit_projects() -> dict[str, Any]:
        """列出可剪辑的导演工程与分集；sequence_id 为 main 表示工程自由剪辑，其余为分集剪辑。"""
        return await run("studio:read", lambda user: editing.projects())

    @sdk.tool(annotations=edit, structured_output=True)
    async def studio_prepare_edit_episode(project_name: str, episode_code: str, title: str = "",
                                           version: str = "v001", script_text: str = "") -> dict[str, Any]:
        """按准确剧名、集号和版本复用或建立剪辑目标，返回 project_id/sequence_id。同版本剧本不覆盖，版本隔离既有剪辑；同名歧义时报错。只用于用户指定的本地剧目。"""
        return await run("studio:edit", lambda user: editing.prepare_episode(
            project_name, episode_code, title=title, version=version, script_text=script_text))

    @sdk.tool(annotations=edit, structured_output=True)
    async def studio_import_edit_media(project_id: str, sequence_id: str, paths: list[str],
                                        revision: int, document_name: str = "") -> dict[str, Any]:
        """按清单顺序引用 1–200 个明确的本机文件，保存到自己的素材库，不复制、不上传、不改现有片段。先 get_timeline 取 revision；返回同序 asset_ids 供 video_arrange。沿用本机目录权限，重复文件复用；任一文件失败则整批不保存。"""
        return await run("studio:edit", lambda user: editing.import_media(
            user, project_id, sequence_id, paths=paths, revision=revision, document_name=document_name))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_get_timeline(project_id: str, sequence_id: str) -> dict[str, Any]:
        """读取自己的剪辑时间线：revision、设置、素材、片段，以及画面理解与音轨转写摘要。预览和确认剪辑前必须先读取。"""
        return await run("studio:read", lambda user: editing.timeline(user["id"], project_id, sequence_id))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_get_transcript(project_id: str, sequence_id: str) -> dict[str, Any]:
        """读取音轨转写状态与带时间戳的真实语音段落；音轨字幕只使用这里成功的段落。"""
        return await run("studio:read", lambda user: editing.transcript(user["id"], project_id, sequence_id))

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True), structured_output=True)
    async def studio_start_transcript(project_id: str, sequence_id: str, force: bool = False) -> dict[str, Any]:
        """提取时间线有声素材的音轨并提交语音转写。转写异步执行、按音频秒数消耗转写服务，需先获得用户同意；用 studio_get_transcript 查询进度和段落。"""
        return await run("studio:edit", lambda user: editing.start_transcript(user["id"], project_id, sequence_id, force=force))

    @sdk.tool(annotations=edit, structured_output=True)
    async def studio_preview_edit(project_id: str, sequence_id: str, operation: str, revision: int | None = None,
                                  asset_ids: list[str] | None = None, strategy: str | None = None) -> dict[str, Any]:
        """生成待确认剪辑方案，不修改时间线。operation：video_arrange 智能铺轨、subtitle_arrange 自动字幕、audio_subtitle 音轨字幕、dialogue_cut 对白精剪、quick_cut 成片速剪、highlight_cut 高光合集、hook_cut 引流剪辑。asset_ids 仅用于 video_arrange；strategy 仅用于 hook_cut（conflict_3s、climax_only、quote_open、ending_hook、trailer）。"""
        return await run("studio:edit", lambda user: editing.preview(
            user["id"], project_id, sequence_id, operation=operation, revision=revision,
            asset_ids=asset_ids, strategy=strategy))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_get_edit_action(project_id: str, sequence_id: str, action_id: str) -> dict[str, Any]:
        """查询待确认剪辑方案的清单、真实执行状态和结果。"""
        return await run("studio:read", lambda user: editing.action(user["id"], project_id, sequence_id, action_id))

    @sdk.tool(annotations=edit, structured_output=True)
    async def studio_reorder_edit(project_id: str, sequence_id: str, action_id: str,
                                  asset_ids: list[str]) -> dict[str, Any]:
        """按新顺序调整待确认的智能铺轨清单，不修改时间线。"""
        return await run("studio:edit", lambda user: editing.reorder(
            user["id"], project_id, sequence_id, action_id, asset_ids))

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False), structured_output=True)
    async def studio_confirm_edit(project_id: str, sequence_id: str, action_id: str) -> dict[str, Any]:
        """确认并执行剪辑方案，原子写入自己的时间线。幂等：重复调用返回同一结果。"""
        return await run("studio:edit", lambda user: editing.confirm(user["id"], project_id, sequence_id, action_id))

    @sdk.tool(annotations=edit, structured_output=True)
    async def studio_add_text(project_id: str, sequence_id: str, text: str, preset: str = "title",
                              start: float = 0.0, duration: float = 3.0, font_size: float | None = None,
                              color: str = "", x: float = 0.0, y: float | None = None) -> dict[str, Any]:
        """在文字轨添加标题或字幕文字，不改动画面和音频。preset：title 大标题或 subtitle 对白；start/duration 为输出时间线秒数；颜色为 #RRGGBB。"""
        return await run("studio:edit", lambda user: editing.add_text(
            user["id"], project_id, sequence_id, text=text, preset=preset, start=start,
            duration=duration, font_size=font_size, color=color, x=x, y=y))

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False), structured_output=True)
    async def studio_export_edit(project_id: str, sequence_id: str, output_dir: str | None = None,
                                 quality: int = 1080) -> dict[str, Any]:
        """把已保存的剪辑时间线导出为 MP4。output_dir 为本机绝对文件夹路径，留空保存到 data/exports/smart-edit；员工只能写入管理员配置的允许目录。返回任务 ID、output_path 与 download_url，用 studio_get_edit_export 轮询。"""
        return await run("studio:edit", lambda user: editing.export(
            user, project_id, sequence_id, output_dir=output_dir, quality=quality))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_get_edit_export(project_id: str, job_id: str) -> dict[str, Any]:
        """查询自己的剪辑导出任务进度、成片本机路径 output_path 和下载地址。"""
        return await run("studio:read", lambda user: editing.export_status(user["id"], project_id, job_id))

    @app.get("/api/mcp/info", tags=["MCP"], summary="MCP 连接配置状态")
    def info(user: dict = Depends(current_user)):
        return config.public_info()

    @app.get("/api/mcp/connections", tags=["MCP"], summary="列出自己的 MCP 授权")
    def connections(user: dict = Depends(current_user)):
        return provider.connections(user["id"])

    @app.delete("/api/mcp/connections/{connection_id}", tags=["MCP"], summary="撤销自己的 MCP 授权")
    def disconnect(connection_id: str = Path(description="MCP 连接 ID"), user: dict = Depends(mutating_user)):
        provider.revoke_connection(connection_id, user["id"])
        return {"ok": True}

    @app.get("/api/mcp/authorization-requests/{request_id}", tags=["MCP"], summary="查看待确认的 MCP 授权")
    def authorization_request(request_id: str = Path(description="待确认的授权请求 ID"), user: dict = Depends(current_user)):
        return provider.request_details(request_id, user)

    @app.post("/api/mcp/authorization-requests/{request_id}", tags=["MCP"], summary="允许或拒绝 MCP 授权")
    def decision(payload: ConsentDecision, request_id: str = Path(description="待确认的授权请求 ID"), user: dict = Depends(mutating_user)):
        if config.error:
            raise HTTPException(503, config.error)
        return provider.decide(request_id, user, payload.allow)

    @app.get("/api/mcp/references", tags=["MCP"], summary="列出自己的 MCP 参考图")
    def references(user: dict = Depends(current_user)):
        return service.list_references(user)

    @app.post("/api/mcp/references", tags=["MCP"], status_code=201, summary="上传 MCP 参考图")
    async def upload_reference(file: UploadFile = File(...), user: dict = Depends(mutating_user)):
        content = await file.read(MAX_REFERENCE_BYTES + 1)
        return await asyncio.to_thread(service.save_reference, user, content, file.filename or "参考图")

    @app.get("/api/mcp/references/{asset_id}/preview", tags=["MCP"], summary="预览自己的 MCP 参考图")
    def preview_reference(asset_id: str = Path(description="MCP 参考图素材 ID"), user: dict = Depends(current_user)):
        asset, path = service.asset_path(user, asset_id)
        return FileResponse(path, media_type=asset["payload"]["mime_type"], headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @app.delete("/api/mcp/references/{asset_id}", tags=["MCP"], summary="删除自己的 MCP 上传参考图")
    def delete_reference(asset_id: str = Path(description="MCP 参考图素材 ID"), user: dict = Depends(mutating_user)):
        service.delete_reference(user, asset_id)
        return {"ok": True}

    @app.get("/api/mcp/generated-images", tags=["MCP"], summary="选择自己的已生成图片")
    def generated_images(user: dict = Depends(current_user)):
        return service.generated_images(user)

    @app.post("/api/mcp/references/from-output", tags=["MCP"], status_code=201, summary="将自己的生成图片复制为 MCP 参考图")
    async def reference_from_output(payload: OutputReference, user: dict = Depends(mutating_user)):
        return await service.reference_from_output(user, payload.job_id, payload.generation_item_id, payload.output_index)

    # Register ASGI endpoints at their full paths. Mounting /api/mcp with an
    # inner '/' route introduces a slash redirect and changes the OAuth resource.
    host = urlsplit(config.base).netloc
    sdk_guard = GatewayGuard(None, config)

    def prepare_transport():
        # SDK managers are single-use. A fresh transport also permits repeated
        # application lifespans in existing integration tests and ASGI hosting.
        sdk_guard.app = sdk.streamable_http_app(streamable_http_path="/api/mcp", stateless_http=True, json_response=True,
            max_request_body_size=128 * 1024,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                allowed_hosts=[host, "127.0.0.1:*", "localhost:*", "[::1]:*"], allowed_origins=[config.base]))
        return sdk.session_manager

    prepare_transport()
    app.state.mcp_prepare_transport = prepare_transport
    app.router.routes.append(Route("/api/mcp", endpoint=sdk_guard))
    for route in create_auth_routes(provider, AnyHttpUrl(config.issuer), client_registration_options=registration, revocation_options=revocation):
        if route.path.startswith("/.well-known/") or route.path == "/revoke":
            continue
        app.router.routes.append(Route("/api/mcp/oauth" + route.path, endpoint=GatewayGuard(route.app, config), methods=route.methods))

    async def revoke_request(request: Request):
        # SDK 2.3.0's RevocationRequest requires a client_secret field even for
        # public clients. Reuse its authenticator, with RFC 7009's optional secret.
        try:
            client = await ClientAuthenticator(provider).authenticate_request(request)
        except AuthenticationError:
            return JSONResponse({"error": "invalid_client"}, status_code=401, headers={"Cache-Control": "no-store"})
        form = await request.form()
        token = form.get("token")
        if not isinstance(token, str) or not token or len(token) > 512:
            return JSONResponse({"error": "invalid_request"}, status_code=400, headers={"Cache-Control": "no-store"})
        for kind in ("access", "refresh"):
            row = provider.store.get(kind + ":" + digest(token))
            if row and row["payload"]["client_id"] == client.client_id:
                provider.store.revoke(row["parent_id"])
                break
        return Response(status_code=200, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    app.router.routes.append(Route("/api/mcp/oauth/revoke", endpoint=GatewayGuard(cors_middleware(revoke_request, ["POST", "OPTIONS"]), config), methods=["POST", "OPTIONS"]))

    async def metadata_response(scope, receive, send):
        if "oauth-protected-resource" in scope["path"]:
            data = {"resource": config.resource, "authorization_servers": [config.issuer], "scopes_supported": SCOPES,
                    "bearer_methods_supported": ["header"], "resource_name": "ZLY AI Studio"}
        else:
            data = build_metadata(AnyHttpUrl(config.issuer), None, registration, revocation).model_dump(mode="json", exclude_none=True)
            data["token_endpoint_auth_methods_supported"] = ["none", "client_secret_post", "client_secret_basic"]
            data["authorization_response_iss_parameter_supported"] = True
        await JSONResponse(data, headers={"Cache-Control": "no-store"})(scope, receive, send)

    # Functions passed to Route are treated as Request endpoints, so wrap the
    # ASGI callable with CORSMiddleware first.
    metadata_app = GatewayGuard(CORSMiddleware(metadata_response, allow_origins=["*"], allow_methods=["GET", "OPTIONS"]), config)
    for path in ("/.well-known/oauth-protected-resource/api/mcp", "/.well-known/oauth-protected-resource",
                 "/.well-known/oauth-authorization-server/api/mcp/oauth"):
        app.router.routes.append(Route(path, endpoint=metadata_app, methods=["GET", "OPTIONS"]))
    app.state.mcp_server = sdk
    return sdk
