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
from .director_service import DirectorService
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
                        listed_workflows, mode_payload, cancel_job, confirm_refine, skip_refine,
                        output_response, output_available, config: McpConfig | None = None):
    config = config or McpConfig.from_env()
    provider = StudioOAuthProvider(app, config)
    service = CreativeService(app, config, settings=settings, submit_generation=submit_generation, public_job=public_job,
        listed_workflows=listed_workflows, mode_payload=mode_payload, cancel_job=cancel_job,
        confirm_refine=confirm_refine, skip_refine=skip_refine,
        output_response=output_response, output_available=output_available)
    editing = EditingService(app, config)
    director = DirectorService(app, config)
    app.state.mcp_config, app.state.mcp_oauth, app.state.mcp_service, app.state.mcp_editing = config, provider, service, editing
    app.state.mcp_director = director
    registration = ClientRegistrationOptions(enabled=True, valid_scopes=SCOPES, default_scopes=SCOPES)
    revocation = RevocationOptions(enabled=True)
    sdk = MCPServer("ZLY AI Studio", version="1.0.0", token_verifier=provider,
        instructions="先查询可用工作流与参数，再创建图片或视频任务。参考图先在工作台 /mcp 上传并按 ID 顺序引用，只有图片参考的工作流会出现在 studio_list_workflows 中。每次新创作生成唯一 request_id，重试保持该标识和参数不变。任务异步执行，使用 studio_get_job 查询，完成后 studio_get_results 获取临时下载链接；状态为 awaiting_refine 时说明一采预览已就绪并暂停，需要精修成片调 studio_confirm_refine，保留一采调 studio_skip_refine，不处理则不会继续出片。导演台整片流程：studio_list_projects 与 studio_get_project 看清现状，studio_get_script 取正文和 base_raw_text，studio_save_script 写剧本，studio_plan_script 入队拆解并用 studio_list_project_jobs 轮询，studio_extract_script_assets 转入资产库，studio_generate_asset_image 出资产图，studio_apply_script_episodes 把分集分镜同步进工坊，studio_get_episode 与 studio_update_beat 核对角色场景绑定，studio_generate_beat_prompt 出 H3 提示词，studio_generate_episode_video 一键出片（工坊任务停在 awaiting_refine 时用 studio_confirm_project_refine 或 studio_skip_project_refine），studio_generate_dubbing 出配音，最后用 studio_prepare_edit_episode、studio_preview_edit、studio_confirm_edit、studio_export_edit 完成剪辑与整集导出。剪辑时间线先 studio_list_edit_projects 获取工程与 sequence_id，studio_get_timeline 读取版本，studio_preview_edit 生成待确认方案后再 studio_confirm_edit；标题用 studio_add_text。音轨字幕先 studio_start_transcript 并轮询 studio_get_transcript。成片用 studio_export_edit 导出，可传本机绝对 output_dir 指定保存目录，再用 studio_get_edit_export 轮询。创作任务、参考图与剪辑时间线只覆盖当前授权账号自己的内容；导演台项目列表与新建工程同样按账号隔离，各账号只能列出和创建自己名下的短剧项目，同名剧目在不同账号下互不可见，写入前先读取最新状态，删除类操作请留在工作台人工执行。",
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
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

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
        """列出自己的参考图 ID、名称和尺寸。提交创作时用 reference_asset_ids 按顺序引用（<Picture n> 与此顺序一致）；库里没有的图先用 studio_import_reference 导入（在线图用 url，本地图用 image_base64）。"""
        return await run("studio:read", lambda user: {"references": service.list_references(user)})

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True), structured_output=True)
    async def studio_import_reference(url: str | None = None, image_base64: str | None = None, name: str | None = None) -> dict[str, Any]:
        """把图片导入用户的参考图库并返回素材 ID，之后用 reference_asset_ids 引用。url 与 image_base64 二选一：url 为在线图片直链（http/https，≤ 50 MB）；image_base64 为本地图片的 base64（允许 data: 前缀，PNG/JPEG/WebP，≤ 50 MB）——用户在对话里附了本地图片时，读取该文件并转 base64 后传入。"""
        return await run("studio:generate", lambda user: asyncio.to_thread(service.import_reference, user, url, image_base64, name))

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

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True), structured_output=True)
    async def studio_confirm_refine(job_id: str) -> dict[str, Any]:
        """任务停在 awaiting_refine 时确认一采预览并继续只跑二采精修，复用同一 seed 与清晰度策略；精修完成后用 studio_get_results 取成片。"""
        return await run("studio:generate", lambda user: service.confirm_refine(user, job_id))

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False), structured_output=True)
    async def studio_skip_refine(job_id: str) -> dict[str, Any]:
        """任务停在 awaiting_refine 时放弃二采精修，把已完成的一采预览直接作为最终成片。"""
        return await run("studio:generate", lambda user: service.skip_refine(user, job_id))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_list_projects(limit: int = 30) -> dict[str, Any]:
        """列出自己账号名下的导演台项目（轻量：ID、名称、状态、更新时间），按最近更新排序，最多 100 条。"""
        return await run("studio:read", lambda user: director.projects(limit, user))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_get_project(project_id: str) -> dict[str, Any]:
        """读取项目全景：剧本文档摘要（不含正文）、资产清单（含造型 has_image）、工坊分集与每集分镜数、已有成片的镜头数。开工前必查。"""
        return await run("studio:read", lambda user: director.project_detail(project_id))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_get_script(project_id: str, document_id: str) -> dict[str, Any]:
        """读取剧本文档正文与拆解摘要，并回显 base_raw_text；整篇改写或按集编辑都要把它原样带回，避免覆盖别人的修改。"""
        return await run("studio:read", lambda user: director.script(project_id, document_id))

    @sdk.tool(annotations=write, structured_output=True)
    async def studio_save_script(project_id: str, raw_text: str, document_id: str = "", base_raw_text: str = "",
                                 filename: str = "", episode_num: int | None = None) -> dict[str, Any]:
        """写剧本：不给 document_id 就新建文档；给 document_id 需同时给 base_raw_text 整篇改写；给 episode_num 只改该集正文。拆解中或已进入制作的集返回冲突，不会覆盖。"""
        return await run("studio:generate", lambda user: director.save_script(
            user, project_id, raw_text, document_id, base_raw_text, filename, episode_num))

    @sdk.tool(annotations=create, structured_output=True)
    async def studio_create_project(name: str, description: str = "") -> dict[str, Any]:
        """在当前账号名下新建导演台项目，返回 project_id 和工作台链接。"""
        return await run("studio:generate", lambda user: director.create_project(name, description, user))

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True), structured_output=True)
    async def studio_plan_script(project_id: str, document_id: str, aspect_ratio: str = "") -> dict[str, Any]:
        """为剧本文档入队镜头拆解（分集与分镜规划），返回任务后请用 studio_list_project_jobs 轮询；同稿重复调用返回同一任务。aspect_ratio 留空沿用项目设置。"""
        return await run("studio:generate", lambda user: director.plan_script(project_id, document_id, aspect_ratio))

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False), structured_output=True)
    async def studio_extract_script_assets(project_id: str, document_id: str, mode: str = "merge") -> dict[str, Any]:
        """把已拆解文档里的角色/场景/道具转入资产库；mode=merge 同名合并，append 追加。拆解标记按集写入，不生成资产图片。"""
        return await run("studio:generate", lambda user: director.extract_script_assets(project_id, document_id, mode))

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False), structured_output=True)
    async def studio_apply_script_episodes(project_id: str, document_id: str, mode: str = "overwrite") -> dict[str, Any]:
        """把已拆解文档的分集与分镜同步进工坊；mode=overwrite 覆盖同名集，append 追加新集。已进入制作的集会受锁定保护。"""
        return await run("studio:generate", lambda user: director.apply_script_episodes(project_id, document_id, mode))

    @sdk.tool(annotations=create, structured_output=True)
    async def studio_create_asset(project_id: str, name: str, kind: str, role: str = "", description: str = "",
                                  visual_prompt: str = "") -> dict[str, Any]:
        """补建角色/场景/道具资产（kind 为 character、scene 或 prop）；角色会自动生成日常造型槽位。"""
        return await run("studio:generate", lambda user: director.create_asset(
            project_id, name, kind, role, description, visual_prompt))

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True), structured_output=True)
    async def studio_generate_asset_image(project_id: str, asset_id: str, target_type: str = "", prompt: str = "",
                                           identity_id: str = "") -> dict[str, Any]:
        """为资产出图，服务端同步完成并返回最新资产；target_type 留空按资产类型取默认（角色生成首个造型卡 identity，场景 scene_master，道具 prop_reference）。出片参考图取角色造型卡与场景主图，头像仅用于界面展示；角色造型可传 identity_id 指定造型。会消耗图片供应商额度。"""
        return await run("studio:generate", lambda user: director.generate_asset_image(
            project_id, asset_id, target_type, prompt, identity_id))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_get_episode(project_id: str, episode_id: str) -> dict[str, Any]:
        """读取工坊单集的分镜表：每镜的绑定（角色/场景/造型）、提示词、成片与超清地址、状态和配音计数。"""
        return await run("studio:read", lambda user: director.episode(project_id, episode_id))

    @sdk.tool(annotations=write, structured_output=True)
    async def studio_update_beat(project_id: str, episode_id: str, beat_id: str,
                                 patch: dict[str, Any]) -> dict[str, Any]:
        """修改单个分镜：绑定角色场景（character_ids/scene_id/character_look_ids）、改动作台词、写 h3_prompt 或 video_duration。只接受白名单字段，媒体地址由生成流程写入。"""
        return await run("studio:generate", lambda user: director.update_beat(project_id, episode_id, beat_id, patch))

    @sdk.tool(annotations=create, structured_output=True)
    async def studio_generate_beat_prompt(project_id: str, episode_id: str, beat_id: str,
                                         merge_as_one: bool = False) -> dict[str, Any]:
        """为本镜生成或优化 H3 视频提示词（出片的必填前置）；merge_as_one=true 先把相邻分镜合并成一条再出提示词。完成后用 studio_get_episode 查看 h3_prompt。"""
        return await run("studio:generate", lambda user: director.generate_beat_prompt(
            project_id, episode_id, beat_id, merge_as_one))

    @sdk.tool(annotations=create, structured_output=True)
    async def studio_generate_episode_video(project_id: str, episode_id: str, beat_ids: list[str] | None = None,
                                            force: bool = False, workflow: str = "", strategy: str = "",
                                            options: dict[str, Any] | None = None) -> dict[str, Any]:
        """一键出片：留 beat_ids 生成整集（已有成片的镜头自动跳过，force=true 重做），传 beat_ids 只出勾选镜头（此时忽略 strategy）。
        strategy=gap_fill 按最大连续缺失区间只补跑未生成镜头，每区间以上一镜真实尾帧做严格首帧锚定；
        strategy=continue 在已出片构成连续前缀时从第 k+1 镜续写整集，不构成前缀自动回退 gap_fill。
        workflow 选 H3 工作流，options 只接受工作流的创作参数（如 aspect_ratio、refine_enabled），技术参数由工作台托管。任务排队后用 studio_list_project_jobs 轮询；缺角色/场景/提示词会直接返回原因。"""
        return await run("studio:generate", lambda user: director.generate_episode_video(
            project_id, episode_id, beat_ids, force, workflow, strategy, options))

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True), structured_output=True)
    async def studio_confirm_project_refine(project_id: str, job_id: str) -> dict[str, Any]:
        """工坊任务停在 awaiting_refine 时确认一采预览并继续二采精修（生成页任务请用 studio_confirm_refine）。"""
        return await run("studio:generate", lambda user: director.confirm_refine(project_id, job_id))

    @sdk.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False), structured_output=True)
    async def studio_skip_project_refine(project_id: str, job_id: str) -> dict[str, Any]:
        """工坊任务停在 awaiting_refine 时放弃二采，保留一采预览作为本镜成片。"""
        return await run("studio:generate", lambda user: director.skip_refine(project_id, job_id))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_get_dubbing(project_id: str, episode_id: str) -> dict[str, Any]:
        """读取本集台词轨：每句的状态与音频、角色配音绑定计数，以及合成前置是否被旁白要求挡住。"""
        return await run("studio:read", lambda user: director.dubbing(project_id, episode_id))

    @sdk.tool(annotations=create, structured_output=True)
    async def studio_generate_dubbing(project_id: str, episode_id: str, line_ids: list[str] | None = None) -> dict[str, Any]:
        """生成本集配音：line_ids 留空表示所有有台词的句子，指定则只出这些句；会先从分镜同步台词轨，同范围重复调用返回同一任务。完成后用 studio_get_dubbing 看 ready 计数。"""
        return await run("studio:generate", lambda user: director.generate_dubbing(project_id, episode_id, line_ids or []))

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_list_project_jobs(project_id: str, job_id: str = "", limit: int = 30) -> dict[str, Any]:
        """轮询导演台任务：拆解、资产图、H3 提示词、出片、超分、配音都在 ai_project_jobs。传 job_id 查单条；返回 next_poll_seconds 建议下次轮询间隔。"""
        return await run("studio:read", lambda user: director.jobs(project_id, job_id or None, limit))

    edit = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

    @sdk.tool(annotations=read, structured_output=True)
    async def studio_list_edit_projects() -> dict[str, Any]:
        """列出自己账号名下的可剪辑导演工程与分集；sequence_id 为 main 表示工程自由剪辑，其余为分集剪辑。"""
        return await run("studio:read", lambda user: editing.projects(user))

    @sdk.tool(annotations=edit, structured_output=True)
    async def studio_prepare_edit_episode(project_name: str, episode_code: str, title: str = "",
                                           version: str = "v001", script_text: str = "") -> dict[str, Any]:
        """按准确剧名、集号和版本复用或建立剪辑目标，返回 project_id/sequence_id。同版本剧本不覆盖，版本隔离既有剪辑；同名歧义时报错。只用于用户指定的本地剧目。"""
        return await run("studio:edit", lambda user: editing.prepare_episode(
            user, project_name, episode_code, title=title, version=version, script_text=script_text))

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
        """生成待确认剪辑方案，不修改时间线。operation：video_arrange 智能铺轨、subtitle_arrange 自动字幕、audio_subtitle 音轨字幕、subtitle_translate 字幕翻译（把文字轨已有字幕翻成简体中文，只改文本）、dialogue_cut 对白精剪、quick_cut 成片速剪、highlight_cut 高光合集、hook_cut 引流剪辑、remove_waste 废片清理（只依据画面理解的明确废片证据移除镜头）。asset_ids 仅用于 video_arrange；strategy 仅用于 hook_cut（conflict_3s、climax_only、quote_open、ending_hook、trailer）。"""
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
