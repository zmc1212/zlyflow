from __future__ import annotations

import asyncio
import json
import re
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Annotated
from urllib.parse import urlencode

import requests
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, Security, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse

from fastapi.security import APIKeyCookie
from fastapi.openapi.utils import get_openapi

from .api_documentation import enrich_openapi_documentation
from .auth import AuthStore, SESSION_HOURS, csrf_token
from .comfy_service import ComfyService
from .config import settings
from .grs_provider import GrsProviderService
from .llm_client import LlmError, LlmTemporaryError
from .llm_provider import LlmProviderService
from .models import (
    AuthStatusResponse, BrowserDirectOutputResponse, ChangePasswordRequest, CreateUserRequest, HealthResponse, JobMode, JobResponse,
    DesktopDeliveryTicketResponse, GrsBalanceResponse, GrsBalanceSnapshotResponse, GrsProviderResponse, GrsProviderTestRequest, GrsProviderUpdateRequest,
    LibraryItemResponse, LoginRequest, ModeResponse, ModesResponse, ResetPasswordRequest, SetupAdminRequest, JobStatus,
    QiniuProviderResponse, QiniuProviderUpdateRequest, StorageCapabilityResponse, UpdateUserRequest, UserResponse, UserRole,
    JobMetadataUpdateRequest,
    LlmProviderResponse, LlmProviderUpdateRequest, LlmProviderTestRequest, LlmStatusResponse,
    PromptOptimizeRequest, PromptOptimizeResponse, SkillsListResponse,
)

from .qiniu_provider import QiniuProviderService

from .resource_storage import create_resource_storage
from .storage import JobStore
from .worker import JobWorker
from .workflow_registry import (
    H3_WORKFLOWS, IMAGE_WORKFLOWS, WORKFLOWS, WORKFLOW_BY_ID, normalize_options, quality_for_megapixels,
    validate_option_relationships, validate_references, workflow_for,
)


MODES = [ModeResponse(**workflow.payload()) for workflow in WORKFLOWS]

PRESETS = {
    "电影感运镜": "电影级中景，人物缓步前行，镜头平稳向前推进，清晨侧逆光，细腻的空间层次。",
    "人物特写": "人物半身特写，自然微笑和轻微转头，浅景深，柔和窗边光，镜头缓慢推近。",
    "旅行航拍": "广阔山谷与蜿蜒道路，无人机由高处缓慢下降并向前飞行，金色日落，真实航拍质感。",
}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
SESSION_COOKIE = "zly_ai_video_studio_session"
session_cookie_scheme = APIKeyCookie(name=SESSION_COOKIE, auto_error=False, description="登录接口设置的 HttpOnly 会话 Cookie。")
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 5
DESKTOP_DELIVERY_TICKET_SECONDS = 5 * 60
BROWSER_LOCAL_COMFY_VIEW_URL = "http://127.0.0.1:8188/view"
login_failures: dict[str, list[float]] = {}
login_failures_lock = Lock()


@dataclass(frozen=True)
class DesktopDeliveryTicket:
    user_id: str
    job_id: str
    output_index: int
    expires_at: float
    generation_item_id: str | None = None


class DesktopDeliveryTickets:
    def __init__(self) -> None:
        self._tickets: dict[str, DesktopDeliveryTicket] = {}
        self._lock = Lock()

    def issue(self, user_id: str, job_id: str, output_index: int, generation_item_id: str | None = None) -> str:
        now = time.monotonic()
        token = secrets.token_urlsafe(32)
        ticket = DesktopDeliveryTicket(user_id, job_id, output_index, now + DESKTOP_DELIVERY_TICKET_SECONDS, generation_item_id)
        with self._lock:
            self._tickets = {key: value for key, value in self._tickets.items() if value.expires_at > now}
            self._tickets[token] = ticket
        return token

    def resolve(
        self, token: str, job_id: str, output_index: int, generation_item_id: str | None = None,
    ) -> DesktopDeliveryTicket | None:
        now = time.monotonic()
        with self._lock:
            self._tickets = {key: value for key, value in self._tickets.items() if value.expires_at > now}
            ticket = self._tickets.get(token)
        if (
            ticket is None or ticket.job_id != job_id or ticket.output_index != output_index
            or ticket.generation_item_id != generation_item_id
        ):
            return None
        return ticket


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def public_api_path(path: str) -> str:
    return f"{settings.public_api_prefix}/{path.lstrip('/')}"


def stored_output_path(output: dict) -> Path | None:
    path = app.state.resource_storage.resolve(output["path"])
    if path is not None:
        return path
    legacy_path = settings.results_dir / Path(output["path"]).name
    return legacy_path if legacy_path.is_file() else None


def streamed_output_response(output: dict) -> StreamingResponse:
    source_info = output.get("_comfy_source")
    try:
        response = app.state.worker.comfy.open_output_stream(source_info)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"ComfyUI 输出暂时不可读取: {error}") from error

    headers = {
        name: value
        for name in ("Content-Length", "Content-Disposition")
        if (value := response.headers.get(name)) is not None
    }

    def stream_chunks():
        try:
            yield from response.iter_content(chunk_size=1024 * 1024)
        finally:
            response.close()

    media_type = response.headers.get("Content-Type", "application/octet-stream")
    return StreamingResponse(stream_chunks(), media_type=media_type, headers=headers)


def output_response(output: dict) -> Response:
    path = stored_output_path(output)
    if path is not None:
        return FileResponse(path)
    remote_url = app.state.resource_storage.download_url(output["path"])
    if remote_url:
        return RedirectResponse(remote_url, status_code=307)
    if app.state.worker.comfy.can_stream_output(output.get("_comfy_source")):
        return streamed_output_response(output)
    raise HTTPException(status_code=410, detail="资源暂存已过期")


def public_output_download_url(output: dict, fallback_url: str) -> str:
    """Prefer a short-lived object-storage URL when the active provider has one."""
    if output.get("delivery_status") != "cloud":
        return fallback_url
    storage = getattr(app.state, "resource_storage", None)
    if storage is not None:
        remote_url = storage.download_url(output["path"])
        if remote_url:
            return remote_url
    return fallback_url


def output_available(output: dict) -> bool:
    return (
        stored_output_path(output) is not None
        or app.state.worker.comfy.can_stream_output(output.get("_comfy_source"))
        or app.state.resource_storage.download_url(output["path"]) is not None
    )


def browser_direct_view_url(source_info: dict) -> str:
    source = ComfyService.output_source_info(source_info)
    if source["type"] != "output":
        raise HTTPException(status_code=409, detail="Only ComfyUI output resources support browser direct delivery")
    return f"{BROWSER_LOCAL_COMFY_VIEW_URL}?{urlencode(source)}"


def current_user(
    request: Request,
    token: Annotated[str | None, Security(session_cookie_scheme)],
) -> dict:
    user = app.state.auth_store.user_for_session(token)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    request.state.session_token = token
    return user


def optional_current_user(token: Annotated[str | None, Security(session_cookie_scheme)]) -> dict | None:
    return app.state.auth_store.user_for_session(token)


def csrf_user(
    request: Request,
    user: Annotated[dict, Depends(current_user)],
    supplied: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    expected = csrf_token(request.state.session_token)
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="安全校验失败，请刷新页面后重试")
    return user


def mutating_user(request: Request, user: Annotated[dict, Depends(csrf_user)]) -> dict:
    if user["must_change_password"] and request.url.path != "/api/auth/password":
        raise HTTPException(status_code=403, detail="请先修改初始密码")
    return user


def ensure_admin(user: dict) -> dict:
    if user["role"] not in {UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value}:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def admin_user(user: Annotated[dict, Depends(current_user)]) -> dict:
    return ensure_admin(user)


def mutating_admin_user(user: Annotated[dict, Depends(mutating_user)]) -> dict:
    return ensure_admin(user)


def super_admin_user(user: Annotated[dict, Depends(current_user)]) -> dict:
    if user["role"] != UserRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return user


def mutating_super_admin_user(user: Annotated[dict, Depends(mutating_user)]) -> dict:
    if user["role"] != UserRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return user


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True,
        secure=settings.secure_cookies, samesite="lax", path="/",
    )


def auth_payload(user: dict, token: str) -> dict:
    return {"setup_required": False, "authenticated": True, "user": user, "csrf_token": csrf_token(token)}


def rate_limit_key(request: Request, username: str) -> str:
    return f"{client_ip(request)}:{username.strip().lower()}"


def enforce_login_limit(key: str) -> None:
    cutoff = time.monotonic() - LOGIN_WINDOW_SECONDS
    with login_failures_lock:
        attempts = [value for value in login_failures.get(key, []) if value > cutoff]
        login_failures[key] = attempts
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="登录失败次数过多，请 15 分钟后再试")


def record_login_failure(key: str) -> None:
    with login_failures_lock:
        login_failures.setdefault(key, []).append(time.monotonic())


def clear_login_failure_key(key: str) -> None:
    with login_failures_lock:
        login_failures.pop(key, None)


def clear_login_failures_for_username(username: str) -> int:
    suffix = f":{username.strip().lower()}"
    with login_failures_lock:
        keys = [key for key in login_failures if key.endswith(suffix)]
        for key in keys:
            login_failures.pop(key, None)
    return len(keys)


def job_or_404(store: JobStore, job_id: str, user: dict, *, include_references: bool = False) -> dict:
    try:
        job = store.get(job_id, include_references=include_references)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error
    if job.get("owner_user_id") != user["id"] and user["role"] not in {
        UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value,
    }:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


def generation_item_or_404(store: JobStore, job_id: str, generation_item_id: str, user: dict) -> tuple[dict, dict]:
    job = job_or_404(store, job_id, user)
    item = next((
        item for round_data in job.get("rounds", []) for item in round_data.get("generation_items", [])
        if item["id"] == generation_item_id
    ), None)
    if item is None:
        raise HTTPException(status_code=404, detail="生成项不存在")
    return job, item


def public_job(job: dict) -> dict:
    data = dict(job)
    data["request_parameters"] = request_parameters(job)
    data.pop("submitted_options", None)
    data.pop("options_submitted", None)
    data["references"] = [
        {"index": index, "url": public_api_path(f"jobs/{job['id']}/references/{index}")}
        for index in range(1, int(job.get("reference_count", 0)) + 1)
    ]
    data["outputs"] = []
    for output_index, raw_output in enumerate(job.get("outputs", [])):
        output = dict(raw_output)
        output.pop("_comfy_source", None)
        if job.get("status") in {"succeeded", "partial"} and output.get("delivery_status", "pending") != "local":
            output["download_url"] = public_output_download_url(
                output, public_api_path(f"jobs/{job['id']}/outputs/{output_index}/download"),
            )
        else:
            output["download_url"] = None
        data["outputs"].append(output)
    public_rounds: list[dict] = []
    for round_data in job.get("rounds", []):
        public_round = dict(round_data)
        public_round["request_parameters"] = request_parameters(round_data)
        public_round.pop("submitted_options", None)
        public_round.pop("options_submitted", None)
        public_round["references"] = [
            {
                "index": index,
                "url": public_api_path(f"jobs/{job['id']}/rounds/{round_data['id']}/references/{index}"),
            }
            for index in range(1, int(round_data.get("reference_count", 0)) + 1)
        ]
        public_items: list[dict] = []
        for item in round_data.get("generation_items", []):
            public_item = dict(item)
            public_item.pop("comfy_prompt_id", None)
            public_item.pop("comfy_client_id", None)
            public_item.pop("comfy_phase", None)
            public_outputs: list[dict] = []
            for output_index, raw_output in enumerate(item.get("outputs", [])):
                output = dict(raw_output)
                output.pop("_comfy_source", None)
                if item.get("status") == "succeeded" and output.get("delivery_status", "pending") != "local":
                    output["download_url"] = public_output_download_url(
                        output,
                        public_api_path(f"jobs/{job['id']}/generations/{item['id']}/outputs/{output_index}/download"),
                    )
                else:
                    output["download_url"] = None
                public_outputs.append(output)
            public_item["outputs"] = public_outputs
            public_items.append(public_item)
        public_round["generation_items"] = public_items
        public_rounds.append(public_round)
    data["rounds"] = public_rounds
    data.pop("owner_user_id", None)
    return data


def request_parameters(job: dict) -> list[dict]:
    definition = WORKFLOW_BY_ID.get(JobMode(job["mode"]))
    if definition is None:
        parameters = [
            {"name": "mode", "label": "工作流", "value": job["mode"], "visibility": "internal"},
            {"name": "prompt", "label": "创作提示词", "value": job["prompt"], "visibility": "primary"},
        ]
        if job.get("negative_prompt"):
            parameters.append({"name": "negative_prompt", "label": "负面提示词", "value": job["negative_prompt"], "visibility": "internal"})
        if job.get("image_size"):
            parameters.append({"name": "image_size", "label": "图片尺寸", "value": job["image_size"], "visibility": "internal"})
        if job.get("reference_count", 0):
            parameters.append({"name": "references", "label": "参考图", "value": job["reference_count"], "visibility": "primary"})
        return parameters
    definitions = {item["name"]: item for item in definition.payload()["parameters"]}
    parameters = [
        {"name": "mode", "label": definitions["mode"]["label"], "value": job["mode"], "visibility": "primary"},
        {"name": "prompt", "label": definitions["prompt"]["label"], "value": job["prompt"], "visibility": "primary"},
    ]
    if job.get("negative_prompt"):
        parameters.append({"name": "negative_prompt", "label": definitions["negative_prompt"]["label"], "value": job["negative_prompt"], "visibility": "primary"})
    if job.get("image_size"):
        parameters.append({"name": "image_size", "label": definitions["image_size"]["label"], "value": job["image_size"], "visibility": "primary"})
    if job.get("reference_count", 0):
        parameters.append({"name": "references", "label": definitions["references"]["label"], "value": job["reference_count"], "visibility": "primary"})

    option_schema = definitions.get("options", {}).get("schema", {})
    option_definitions = option_schema.get("properties", {})
    for name in option_definitions:
        value = job.get("options", {}).get(name)
        if name == "quality" and value is None:
            value = quality_for_megapixels(option_schema, job.get("options", {}).get("megapixels"))
        if value is not None:
            parameter = {
                "name": f"options.{name}",
                "label": option_definitions[name].get("label", name),
                "value": value,
                "visibility": option_definitions[name].get("ui_group", "internal"),
            }
            if option_definitions[name].get("unit"):
                parameter["unit"] = option_definitions[name]["unit"]
            parameters.append(parameter)
    return parameters


def safe_name(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)
    return cleaned or "upload.png"


async def save_upload(upload: UploadFile, destination: Path) -> None:
    total = 0
    with destination.open("wb") as target:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                target.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="单张参考图不能超过 50 MB")
            target.write(chunk)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.results_dir.mkdir(exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.staging_dir.mkdir(parents=True, exist_ok=True)
    auth_store = AuthStore(settings.database_path)
    store = JobStore(settings.database_path)
    qiniu_provider = QiniuProviderService(store, settings.credential_key)
    resource_storage = qiniu_provider.enabled_storage() or create_resource_storage(settings.resource_provider, settings.staging_dir)
    grs_provider = GrsProviderService(store, settings.credential_key)
    llm_provider = LlmProviderService(store, settings.credential_key)
    worker = JobWorker(store, ComfyService(settings, resource_storage), grs_provider, resource_storage)
    app.state.auth_store = auth_store
    app.state.store = store
    app.state.resource_storage = resource_storage
    app.state.grs_provider = grs_provider
    app.state.qiniu_provider = qiniu_provider
    app.state.llm_provider = llm_provider
    app.state.worker = worker
    app.state.desktop_delivery_tickets = DesktopDeliveryTickets()
    await worker.start()
    yield
    await worker.stop()



app = FastAPI(
    title="ZLY AI 视频创作平台 API",
    version="2.0.0",
    summary="带企业账号隔离与浏览器本地资源交付的 ComfyUI 工作台 API。",
    description=(
        "监听本机与局域网 IPv4 地址的 `7865` 端口。除健康检查和登录初始化外，业务接口需要会话认证；"
        "任务创建使用 `multipart/form-data`，参考图按上传顺序传入 `references`；生成状态请轮询任务接口。"
    ),
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_tags=[
        {"name": "系统", "description": "工作台与固定 ComfyUI 实例的可用性。"},
        {"name": "账号", "description": "首次初始化、登录会话与密码。"},
        {"name": "管理后台", "description": "管理员创建、启停、授权和重置员工账号。"},
        {"name": "工作流", "description": "可用生成模式及其输入能力。"},
        {"name": "任务", "description": "创建、查询生成任务。任务由单 worker 串行执行。"},
        {"name": "资源", "description": "把临时结果交付到员工电脑并清理服务器暂存。"},
        {"name": "作品库", "description": "已生成媒体的列表与文件访问。"},
        {"name": "创作台", "description": "创作页面需要的供应商状态与余额快照。"},
        {"name": "大模型", "description": "提示词优化服务与 MiniMax H3 技能。"},
    ],
    lifespan=lifespan,
)


def public_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, description=app.description,
        routes=app.routes, tags=app.openapi_tags,
    )
    schema = enrich_openapi_documentation(schema)
    if settings.public_api_prefix != "/api":
        schema["paths"] = {
            path.removeprefix("/api") or "/": operation
            for path, operation in schema["paths"].items()
        }
        schema["servers"] = [{"url": settings.public_api_prefix, "description": "公开工作台 API"}]
    app.openapi_schema = schema
    return schema


app.openapi = public_openapi


@app.get("/api/auth/status", response_model=AuthStatusResponse, tags=["账号"], summary="获取登录与初始化状态")
def authentication_status(request: Request) -> dict:
    auth_store: AuthStore = app.state.auth_store
    setup_required = auth_store.setup_required()
    token = request.cookies.get(SESSION_COOKIE)
    user = auth_store.user_for_session(token)
    if user is None:
        return {"setup_required": setup_required, "authenticated": False}
    return auth_payload(user, token)


@app.post("/api/auth/setup", response_model=AuthStatusResponse, tags=["账号"], summary="初始化首位超级管理员")
def setup_admin(payload: SetupAdminRequest, request: Request, response: Response) -> dict:
    if client_ip(request) not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="首次管理员只能在工作站本机初始化")
    auth_store: AuthStore = app.state.auth_store
    if not auth_store.setup_required():
        raise HTTPException(status_code=409, detail="工作台已经完成初始化")
    try:
        user = auth_store.create_user(
            payload.username, payload.display_name, payload.password,
            UserRole.SUPER_ADMIN, must_change_password=False,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    migrated_jobs = app.state.store.assign_unowned(user["id"])
    token, _ = auth_store.create_session(user["id"])
    set_session_cookie(response, token)
    auth_store.audit(
        "setup_admin", "user", actor_user_id=user["id"], target_id=user["id"],
        detail=f"接管 {migrated_jobs} 个历史任务", ip_address=client_ip(request),
    )
    return auth_payload(user, token)


@app.post("/api/auth/login", response_model=AuthStatusResponse, tags=["账号"], summary="账号登录")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    auth_store: AuthStore = app.state.auth_store
    if auth_store.setup_required():
        raise HTTPException(status_code=409, detail="请先在工作站本机完成管理员初始化")
    key = rate_limit_key(request, payload.username)
    enforce_login_limit(key)
    user = auth_store.authenticate(payload.username, payload.password)
    if user is None:
        record_login_failure(key)
        auth_store.audit(
            "login_failed", "session", detail=f"username={payload.username.strip().lower()}",
            ip_address=client_ip(request),
        )
        raise HTTPException(status_code=401, detail="账号或密码错误")
    clear_login_failure_key(key)
    token, _ = auth_store.create_session(user["id"])
    set_session_cookie(response, token)
    auth_store.audit("login", "session", actor_user_id=user["id"], ip_address=client_ip(request))
    return auth_payload(user, token)


@app.post("/api/auth/logout", tags=["账号"], summary="退出登录")
def logout(request: Request, response: Response, user: Annotated[dict, Depends(csrf_user)]) -> dict:
    app.state.auth_store.revoke_session(request.state.session_token)
    app.state.auth_store.audit("logout", "session", actor_user_id=user["id"], ip_address=client_ip(request))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.post("/api/auth/password", response_model=AuthStatusResponse, tags=["账号"], summary="修改当前账号密码")
def change_password(
    payload: ChangePasswordRequest, request: Request, response: Response,
    user: Annotated[dict, Depends(csrf_user)],
) -> dict:
    auth_store: AuthStore = app.state.auth_store
    if auth_store.authenticate(user["username"], payload.current_password) is None:
        raise HTTPException(status_code=422, detail="当前密码不正确")
    try:
        updated = auth_store.set_password(user["id"], payload.new_password, must_change_password=False)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    token, _ = auth_store.create_session(user["id"])
    set_session_cookie(response, token)
    auth_store.audit("change_password", "user", actor_user_id=user["id"], target_id=user["id"], ip_address=client_ip(request))
    return auth_payload(updated, token)


@app.get("/api/admin/users", response_model=list[UserResponse], tags=["管理后台"], summary="列出员工账号")
def list_users(_: Annotated[dict, Depends(admin_user)]) -> list[dict]:
    return app.state.auth_store.list_users()


def ensure_manageable_role(actor: dict, role: UserRole) -> None:
    if actor["role"] == UserRole.ADMIN.value and role != UserRole.EMPLOYEE:
        raise HTTPException(status_code=403, detail="管理员只能管理员工账号")


@app.post("/api/admin/users", response_model=UserResponse, status_code=201, tags=["管理后台"], summary="创建员工账号")
def create_user(
    payload: CreateUserRequest, request: Request, actor: Annotated[dict, Depends(mutating_admin_user)],
) -> dict:
    ensure_manageable_role(actor, payload.role)
    try:
        user = app.state.auth_store.create_user(
            payload.username, payload.display_name, payload.password, payload.role, must_change_password=True,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "create_user", "user", actor_user_id=actor["id"], target_id=user["id"],
        detail=f"role={user['role']}", ip_address=client_ip(request),
    )
    return user


@app.patch("/api/admin/users/{user_id}", response_model=UserResponse, tags=["管理后台"], summary="更新员工角色或状态")
def update_user(
    user_id: str, payload: UpdateUserRequest, request: Request,
    actor: Annotated[dict, Depends(mutating_admin_user)],
) -> dict:
    try:
        target = app.state.auth_store.get_user(user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="账号不存在") from error
    if actor["role"] == UserRole.ADMIN.value and target["role"] != UserRole.EMPLOYEE.value:
        raise HTTPException(status_code=403, detail="管理员只能管理员工账号")
    if payload.role is not None:
        ensure_manageable_role(actor, payload.role)
    removing_last_super_admin = (
        target["role"] == UserRole.SUPER_ADMIN.value
        and (payload.role not in {None, UserRole.SUPER_ADMIN} or payload.is_active is False)
        and app.state.auth_store.active_super_admin_count() <= 1
    )
    if removing_last_super_admin:
        raise HTTPException(status_code=409, detail="不能停用或降级最后一个超级管理员")
    if actor["id"] == user_id and payload.is_active is False:
        raise HTTPException(status_code=409, detail="不能停用当前登录账号")
    try:
        updated = app.state.auth_store.update_user(user_id, role=payload.role, is_active=payload.is_active)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="账号不存在") from error
    app.state.auth_store.audit(
        "update_user", "user", actor_user_id=actor["id"], target_id=user_id,
        detail=f"role={updated['role']},active={updated['is_active']}", ip_address=client_ip(request),
    )
    return updated


@app.post("/api/admin/users/{user_id}/reset-password", response_model=UserResponse, tags=["管理后台"], summary="重置员工密码")
def reset_user_password(
    user_id: str, payload: ResetPasswordRequest, request: Request,
    actor: Annotated[dict, Depends(mutating_admin_user)],
) -> dict:
    try:
        target = app.state.auth_store.get_user(user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="账号不存在") from error
    if actor["role"] == UserRole.ADMIN.value and target["role"] != UserRole.EMPLOYEE.value:
        raise HTTPException(status_code=403, detail="管理员只能管理员工账号")
    try:
        updated = app.state.auth_store.set_password(user_id, payload.password, must_change_password=True)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    cleared_login_blocks = clear_login_failures_for_username(target["username"])
    app.state.auth_store.audit(
        "reset_password", "user", actor_user_id=actor["id"], target_id=user_id,
        detail=f"cleared_login_blocks={cleared_login_blocks}", ip_address=client_ip(request),
    )
    return updated


@app.get("/api/storage", response_model=StorageCapabilityResponse, tags=["资源"], summary="获取资源交付能力")
def storage_capability(_: Annotated[dict, Depends(current_user)]) -> dict:
    return {
        "provider": app.state.resource_storage.provider_id,
        "delivery": "browser-directory",
        "temporary_server_staging": not app.state.resource_storage.persistent_outputs,
        "requires_local_directory": not app.state.resource_storage.persistent_outputs,
        "qiniu_compatible": True,
    }


@app.get("/api/health", response_model=HealthResponse, tags=["系统"], summary="检查服务状态")
def health() -> dict:
    provider = app.state.grs_provider
    config = provider.public_config()
    return {
        "webui": "ok",
        "comfy": ComfyService(settings).health(),
        "grs": {
            "configured": config["has_api_key"],
            "enabled": config["enabled"],
            "credential_ready": config["credential_ready"],
            "available": config["available"],
            "last_test_status": config["last_test_status"],
            "last_test_at": config["last_test_at"],
            "message": config["unavailable_reason"] or config["last_test_message"],
        },
    }


def mode_payload(definition) -> dict:
    payload = definition.payload()
    if definition.id in IMAGE_WORKFLOWS:
        available, reason = app.state.grs_provider.availability(definition.id)
        payload["available"] = available
        payload["unavailable_reason"] = reason
    return payload


@app.get("/api/modes", response_model=ModesResponse, tags=["工作流"], summary="获取工作流注册表")
def modes(_: Annotated[dict, Depends(current_user)]) -> dict:
    return {"modes": [mode_payload(item) for item in WORKFLOWS], "image_sizes": [], "presets": PRESETS}


@app.get(
    "/api/modes/{mode_id}",
    response_model=ModeResponse,
    tags=["工作流"],
    summary="获取指定工作流的参数定义",
    description="返回 `POST /api/jobs` 中该工作流可提交的 multipart 字段、参考图约束与 H3 options schema。",
)
def mode_detail(mode_id: JobMode, _: Annotated[dict, Depends(current_user)]) -> dict:
    try:
        return mode_payload(workflow_for(mode_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="工作流不存在") from error


@app.get("/api/admin/providers/grs", response_model=GrsProviderResponse, tags=["管理后台"])
def get_grs_provider(_: Annotated[dict, Depends(super_admin_user)]) -> dict:
    return app.state.grs_provider.public_config()


@app.get("/api/providers/grs/balance", response_model=GrsBalanceSnapshotResponse, tags=["创作台"])
async def get_grs_balance_snapshot(_: Annotated[dict, Depends(current_user)]) -> dict:
    return await asyncio.to_thread(app.state.grs_provider.refresh_balance_snapshot)


def refresh_resource_storage() -> None:
    storage = app.state.qiniu_provider.enabled_storage() or create_resource_storage(
        settings.resource_provider, settings.staging_dir,
    )
    app.state.resource_storage = storage
    app.state.worker.resource_storage = storage
    app.state.worker.comfy.resource_storage = storage


@app.get("/api/admin/providers/qiniu", response_model=QiniuProviderResponse, tags=["管理后台"])
def get_qiniu_provider(_: Annotated[dict, Depends(super_admin_user)]) -> dict:
    return app.state.qiniu_provider.public_config()


@app.put("/api/admin/providers/qiniu", response_model=QiniuProviderResponse, tags=["管理后台"])
def update_qiniu_provider(
    payload: QiniuProviderUpdateRequest, request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        result = app.state.qiniu_provider.update(payload.model_dump())
        refresh_resource_storage()
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    app.state.auth_store.audit(
        "update_qiniu_provider", "provider", actor_user_id=user["id"], target_id="qiniu",
        detail="updated qiniu storage configuration", ip_address=client_ip(request),
    )
    return result


@app.post("/api/admin/providers/qiniu/test", response_model=QiniuProviderResponse, tags=["管理后台"])
async def test_qiniu_provider(
    request: Request, user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: QiniuProviderUpdateRequest | None = None,
) -> dict:
    try:
        arguments = None if payload is None else payload.model_dump()
        result = await asyncio.to_thread(app.state.qiniu_provider.test_connection, arguments)
    except Exception as error:
        app.state.auth_store.audit(
            "test_qiniu_provider_failed", "provider", actor_user_id=user["id"], target_id="qiniu",
            detail=type(error).__name__, ip_address=client_ip(request),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "test_qiniu_provider", "provider", actor_user_id=user["id"], target_id="qiniu",
        detail="success", ip_address=client_ip(request),
    )
    return result


@app.put("/api/admin/providers/grs", response_model=GrsProviderResponse, tags=["管理后台"])
def update_grs_provider(
    payload: GrsProviderUpdateRequest, request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        result = app.state.grs_provider.update(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    app.state.auth_store.audit(
        "update_grs_provider", "provider", actor_user_id=user["id"], target_id="grs",
        detail="updated provider configuration", ip_address=client_ip(request),
    )
    return result


@app.post("/api/admin/providers/grs/test", response_model=GrsProviderResponse, tags=["管理后台"])
async def test_grs_provider(
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: GrsProviderTestRequest | None = None,
) -> dict:
    try:
        arguments = {} if payload is None else {"base_url": payload.base_url, "api_key": payload.api_key}
        result = await asyncio.to_thread(app.state.grs_provider.test_connection, **arguments)
    except Exception as error:
        app.state.auth_store.audit(
            "test_grs_provider_failed", "provider", actor_user_id=user["id"], target_id="grs",
            detail=type(error).__name__, ip_address=client_ip(request),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "test_grs_provider", "provider", actor_user_id=user["id"], target_id="grs",
        detail="success", ip_address=client_ip(request),
    )
    return result


@app.post("/api/admin/providers/grs/balance", response_model=GrsBalanceResponse, tags=["管理后台"])
async def query_grs_balance(
    request: Request, user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        credits, queried_at = await asyncio.to_thread(app.state.grs_provider.balance)
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "query_grs_balance", "provider", actor_user_id=user["id"], target_id="grs",
        detail="balance queried", ip_address=client_ip(request),
    )
    return {"credits": credits, "queried_at": queried_at}


@app.get("/api/admin/providers/llm", response_model=LlmProviderResponse, tags=["管理后台"], summary="获取 LLM 大模型配置")
def get_llm_provider(_: Annotated[dict, Depends(super_admin_user)]) -> dict:
    return app.state.llm_provider.public_config()


@app.put("/api/admin/providers/llm", response_model=LlmProviderResponse, tags=["管理后台"], summary="更新 LLM 大模型配置")
def update_llm_provider(
    payload: LlmProviderUpdateRequest, request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        result = app.state.llm_provider.update(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "update_llm_provider", "provider", actor_user_id=user["id"], target_id="llm",
        detail=f"model={payload.model}", ip_address=client_ip(request),
    )
    return result


@app.post("/api/admin/providers/llm/test", response_model=LlmProviderResponse, tags=["管理后台"], summary="测试 LLM 大模型连接")
async def test_llm_provider(
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: LlmProviderTestRequest | None = None,
) -> dict:
    try:
        arguments = None if payload is None else payload.model_dump()
        result = await asyncio.to_thread(app.state.llm_provider.test, arguments)
    except Exception as error:
        app.state.auth_store.audit(
            "test_llm_provider_failed", "provider", actor_user_id=user["id"], target_id="llm",
            detail=type(error).__name__, ip_address=client_ip(request),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "test_llm_provider", "provider", actor_user_id=user["id"], target_id="llm",
        detail="success", ip_address=client_ip(request),
    )
    return result


@app.get("/api/llm/skills", response_model=SkillsListResponse, tags=["大模型"], summary="获取 MiniMax H3 官方提示词技能列表")
def get_llm_skills(_: Annotated[dict, Depends(current_user)]) -> dict:
    from .llm_minimax_skills import list_h3_skills_payload
    return {"skills": list_h3_skills_payload()}


@app.get("/api/llm/status", response_model=LlmStatusResponse, tags=["大模型"], summary="查询大模型服务可用状态")
def get_llm_status(_: Annotated[dict, Depends(current_user)]) -> dict:
    available, reason = app.state.llm_provider.availability()
    return {"available": available, "message": reason}


@app.post("/api/llm/optimize-prompt", response_model=PromptOptimizeResponse, tags=["大模型"], summary="优化视频或图片生成提示词")
async def optimize_prompt_endpoint(
    payload: PromptOptimizeRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    available, reason = app.state.llm_provider.availability()
    if not available:
        raise HTTPException(status_code=503, detail=reason or "大模型服务暂未启用或不可用")

    try:
        optimized = await asyncio.to_thread(
            app.state.llm_provider.optimize_prompt,
            payload.prompt,
            media_type=payload.media_type,
            workflow_name=payload.workflow_name,
            skill_id=payload.skill_id,
            reference_count=payload.reference_count or 0,
            workflow_id=payload.workflow_id,
        )
    except (LlmTemporaryError, requests.exceptions.RequestException) as error:
        raise HTTPException(status_code=502, detail=f"大模型响应超时或网络异常：{error}") from error
    except LlmError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"提示词优化异常：{error}") from error


    app.state.auth_store.audit(
        "optimize_prompt", "llm", actor_user_id=user["id"], target_id="prompt",
        detail=f"media_type={payload.media_type}; skill_id={payload.skill_id or 'default'}; refs={payload.reference_count or 0}",
        ip_address=client_ip(request),
    )
    return {
        "original_prompt": payload.prompt,
        "optimized_prompt": optimized,
        "skill_id": payload.skill_id,
    }




@app.post(
    "/api/jobs",
    status_code=202,
    response_model=JobResponse,
    tags=["任务"],
    summary="创建生成任务",
    description="请求成功只表示任务已入队。轮询 `GET /api/jobs/{job_id}` 直到任务进入终态。",
)
async def create_job(
    user: Annotated[dict, Depends(mutating_user)],
    mode: Annotated[JobMode, Form(description="生成模式；具体能力由 GET /api/modes 返回。")],
    prompt: Annotated[str, Form(description="创作提示词，去除首尾空白后不能为空。")],
    negative_prompt: Annotated[str, Form(description="仅 image 模式生效。")]= "",
    image_size: Annotated[str | None, Form(description="仅 image 模式必填，值来自 image_sizes。")]= None,
    options: Annotated[str | None, Form(description="MiniMax H3 参数 JSON；其他模式传 {}。")]= None,
    title: Annotated[str | None, Form(description="任务标题。")]= None,
    source_job_id: Annotated[str | None, Form(description="图片转视频来源任务 ID。")]= None,
    source_generation_item_id: Annotated[str | None, Form(description="图片转视频来源生成项 ID。")]= None,
    source_output_index: Annotated[int | None, Form(description="图片转视频来源输出序号。")]= None,
    references: list[UploadFile] = File(default=[], description="参考图文件；多图时顺序具有业务含义。"),
) -> dict:
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="请填写创作提示词")
    try:
        raw_options = json.loads(options) if options is not None else {}
        if not isinstance(raw_options, dict):
            raise ValueError("生成参数必须为对象。")
        validate_references(mode, references)
        generation_options = normalize_options(mode, raw_options)
        validate_option_relationships(mode, generation_options, len(references))
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if mode in IMAGE_WORKFLOWS:
        available, reason = app.state.grs_provider.availability(mode)
        if not available:
            raise HTTPException(status_code=409, detail=reason or "GRS 图片能力不可用")

    source: dict | None = None
    if source_job_id:
        if workflow_for(mode).media_type != "video":
            raise HTTPException(status_code=422, detail="只有视频任务可以记录图片转视频来源")
        source_job = job_or_404(app.state.store, source_job_id, user)
        source_item = next((
            item for round_data in source_job.get("rounds", []) for item in round_data.get("generation_items", [])
            if item["id"] == source_generation_item_id
        ), None)
        if source_item is None or source_output_index is None or not 0 <= source_output_index < len(source_item["outputs"]):
            raise HTTPException(status_code=422, detail="图片转视频来源不存在")
        if source_item["outputs"][source_output_index].get("kind") != "image":
            raise HTTPException(status_code=422, detail="图片转视频来源必须是图片")
        source = {"job_id": source_job_id, "generation_item_id": source_generation_item_id, "output_index": source_output_index}

    job_id = secrets.token_urlsafe(9).replace("-", "").replace("_", "")
    upload_dir = settings.uploads_dir / user["id"] / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    references_paths: list[str] = []
    for index, upload in enumerate(references, start=1):
        if upload.content_type and not upload.content_type.startswith("image/"):
            shutil.rmtree(upload_dir, ignore_errors=True)
            raise HTTPException(status_code=422, detail="参考素材必须为图片")
        destination = upload_dir / f"{index}_{safe_name(upload.filename or 'upload.png')}"
        await save_upload(upload, destination)
        references_paths.append(str(destination))

    store: JobStore = app.state.store
    job = store.create(
        job_id,
        mode,
        prompt,
        negative_prompt.strip(),
        image_size,
        references_paths,
        generation_options,
        submitted_options=raw_options if options is not None else None,
        owner_user_id=user["id"],
        title=title.strip() if title else None,
        source=source,
    )
    await app.state.worker.enqueue(job_id)
    return public_job(job)


@app.post(
    "/api/jobs/{job_id}/rounds", status_code=202, response_model=JobResponse,
    tags=["任务"], summary="为同媒介任务创建下一轮",
)
async def create_job_round(
    job_id: str,
    user: Annotated[dict, Depends(mutating_user)],
    prompt: Annotated[str, Form()],
    negative_prompt: Annotated[str, Form()] = "",
    image_size: Annotated[str | None, Form()] = None,
    options: Annotated[str | None, Form()] = None,
    references: list[UploadFile] = File(default=[]),
) -> dict:
    existing = job_or_404(app.state.store, job_id, user, include_references=True)
    if existing.get("legacy_read_only"):
        raise HTTPException(status_code=409, detail="旧版图片结果仅支持查看，不能再次生成")
    mode = JobMode(existing["mode"])
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="请填写创作提示词")
    try:
        raw_options = json.loads(options) if options is not None else existing.get("options", {})
        if not isinstance(raw_options, dict):
            raise ValueError("生成参数必须为对象。")
        reused_references = existing["rounds"][-1].get("references", []) if not references else []
        validate_references(mode, references or reused_references)
        generation_options = normalize_options(mode, raw_options) if options is not None else existing.get("options", {})
        validate_option_relationships(mode, generation_options, len(references or reused_references))
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if mode in IMAGE_WORKFLOWS:
        available, reason = app.state.grs_provider.availability(mode)
        if not available:
            raise HTTPException(status_code=409, detail=reason or "GRS 图片能力不可用")
    sequence = len(existing["rounds"]) + 1
    upload_dir = settings.uploads_dir / user["id"] / job_id / f"round-{sequence}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    reference_paths: list[str] = list(reused_references)
    for index, upload in enumerate(references, start=1):
        if upload.content_type and not upload.content_type.startswith("image/"):
            shutil.rmtree(upload_dir, ignore_errors=True)
            raise HTTPException(status_code=422, detail="参考素材必须为图片")
        destination = upload_dir / f"{index}_{safe_name(upload.filename or 'upload.png')}"
        await save_upload(upload, destination)
        reference_paths.append(str(destination))
    job = app.state.store.create_round(
        job_id, prompt=prompt, negative_prompt=negative_prompt.strip(), image_size=image_size,
        references=reference_paths, options=generation_options,
        submitted_options=raw_options if options is not None else None,
    )
    await app.state.worker.enqueue(job_id)
    return public_job(job)


@app.post(
    "/api/jobs/{job_id}/rounds/{round_id}/retry-failed-items", status_code=202,
    response_model=JobResponse, tags=["任务"], summary="只重试轮次中的失败生成项",
)
async def retry_failed_generation_items(
    job_id: str, round_id: str, user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    job_or_404(app.state.store, job_id, user)
    retried = app.state.store.retry_failed_items(job_id, round_id)
    if not retried:
        raise HTTPException(status_code=409, detail="当前轮次没有可重试的失败项")
    for item in retried:
        if item["executor"] == "grs":
            app.state.worker.enqueue_generation(item["id"])
        else:
            await app.state.worker.enqueue(job_id)
    return public_job(app.state.store.get(job_id))


@app.get("/api/jobs", response_model=list[JobResponse], tags=["任务"], summary="列出最近任务")
def list_jobs(user: Annotated[dict, Depends(current_user)], limit: int = 100) -> list[dict]:
    jobs = app.state.store.list_for_user(user["id"], max(1, min(limit, 200)))
    return [public_job(job) for job in jobs]


@app.get("/api/jobs/{job_id}", response_model=JobResponse, tags=["任务"], summary="查询任务状态")
def get_job(job_id: str, user: Annotated[dict, Depends(current_user)]) -> dict:
    return public_job(job_or_404(app.state.store, job_id, user))


@app.patch("/api/jobs/{job_id}", response_model=JobResponse, tags=["任务"], summary="更新任务标题与置顶状态")
def update_job_metadata(
    job_id: str, payload: JobMetadataUpdateRequest, user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    job_or_404(app.state.store, job_id, user)
    try:
        job = app.state.store.update_metadata(
            job_id,
            title=payload.title,
            pinned=payload.pinned,
            update_title="title" in payload.model_fields_set,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error
    return public_job(job)


@app.delete("/api/jobs/{job_id}", tags=["任务"], summary="删除任务记录")
def delete_job(job_id: str, user: Annotated[dict, Depends(mutating_user)]) -> dict:
    job = job_or_404(app.state.store, job_id, user)
    if job["status"] in {JobStatus.QUEUED.value, JobStatus.RUNNING.value}:
        raise HTTPException(status_code=409, detail="任务生成中，完成后才能删除")
    if not app.state.store.delete(job_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"id": job_id}


@app.post(
    "/api/jobs/{job_id}/retry",
    status_code=202,
    response_model=JobResponse,
    tags=["任务"],
    summary="重新提交已中断任务",
)
async def retry_job(job_id: str, user: Annotated[dict, Depends(mutating_user)]) -> dict:
    existing = job_or_404(app.state.store, job_id, user, include_references=True)
    if JobMode(existing["mode"]) not in H3_WORKFLOWS:
        raise HTTPException(status_code=409, detail="当前工作流不支持重新提交")
    job = app.state.store.retry_terminal(job_id)
    if job is None:
        raise HTTPException(status_code=409, detail="仅已中断或失败且未在 ComfyUI 执行的任务可以重新提交")
    await app.state.worker.enqueue(job_id)
    return public_job(job)


@app.get(
    "/api/jobs/{job_id}/references/{reference_index}",
    tags=["任务"],
    summary="Preview a task reference image",
    responses={200: {"content": {"image/*": {}}}},
)
def job_reference(job_id: str, reference_index: int, user: Annotated[dict, Depends(current_user)]) -> FileResponse:
    if reference_index < 1:
        raise HTTPException(status_code=404, detail="Reference image not found")
    job = job_or_404(app.state.store, job_id, user, include_references=True)
    references = job.get("references", [])
    if reference_index > len(references):
        raise HTTPException(status_code=404, detail="Reference image not found")
    uploads_root = settings.uploads_dir.resolve()
    path = Path(references[reference_index - 1]).resolve()
    if uploads_root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Reference image not found")
    return FileResponse(path)


@app.get(
    "/api/jobs/{job_id}/rounds/{round_id}/references/{reference_index}", tags=["任务"],
    summary="预览指定轮次参考图", responses={200: {"content": {"image/*": {}}}},
)
def round_reference(
    job_id: str, round_id: str, reference_index: int,
    user: Annotated[dict, Depends(current_user)],
) -> FileResponse:
    if reference_index < 1:
        raise HTTPException(status_code=404, detail="参考图不存在")
    job = job_or_404(app.state.store, job_id, user, include_references=True)
    round_data = next((item for item in job["rounds"] if item["id"] == round_id), None)
    references = round_data.get("references", []) if round_data else []
    if reference_index > len(references):
        raise HTTPException(status_code=404, detail="参考图不存在")
    uploads_root = settings.uploads_dir.resolve()
    path = Path(references[reference_index - 1]).resolve()
    if uploads_root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="参考图不存在")
    return FileResponse(path)


@app.get("/api/library", response_model=list[LibraryItemResponse], tags=["作品库"], summary="列出作品库媒体")
def library(user: Annotated[dict, Depends(current_user)]) -> list[dict]:
    return [
        {
            **output,
            "download_url": public_output_download_url(
                output,
                public_api_path(f"jobs/{job['id']}/generations/{item['id']}/outputs/{output_index}/download"),
            ) if output.get("delivery_status", "pending") != "local" else None,
            "job_id": job["id"],
            "generation_item_id": item["id"],
            "output_index": output_index,
            "created_at": round_data["created_at"],
        }
        for job in app.state.store.list_for_user(user["id"], 500)
        for round_data in job.get("rounds", [])
        for item in round_data.get("generation_items", [])
        if item["status"] == "succeeded"
        for output_index, output in enumerate(item["outputs"])
    ]


@app.get(
    "/api/media/{filename}",
    tags=["作品库"],
    summary="下载或预览生成媒体",
    responses={200: {"content": {"image/*": {}, "video/*": {}, "application/octet-stream": {}}}},
)
def media(filename: str, user: Annotated[dict, Depends(current_user)]) -> Response:
    output = next((
        output
        for job in app.state.store.list_for_user(user["id"], 500)
        for output in job["outputs"]
        if output["path"] == filename
    ), None)
    if output is None:
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    if output.get("delivery_status") == "local":
        raise HTTPException(status_code=410, detail="资源已经保存到员工电脑，请从本地资源目录查看")
    return output_response(output)


@app.get(
    "/api/jobs/{job_id}/outputs/{output_index}/download",
    tags=["资源"], summary="下载待交付资源",
)
def download_output(
    job_id: str,
    output_index: int,
    desktop_ticket: str | None = None,
    user: Annotated[dict | None, Depends(optional_current_user)] = None,
) -> Response:
    if desktop_ticket:
        ticket = app.state.desktop_delivery_tickets.resolve(desktop_ticket, job_id, output_index)
        if ticket is None:
            raise HTTPException(status_code=401, detail="桌面客户端下载凭证无效或已过期")
        try:
            user = app.state.auth_store.get_user(ticket.user_id)
        except KeyError as error:
            raise HTTPException(status_code=401, detail="桌面客户端下载凭证所属账号不存在") from error
        if not user["is_active"]:
            raise HTTPException(status_code=401, detail="桌面客户端下载凭证所属账号已停用")
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    job = job_or_404(app.state.store, job_id, user)
    if job["status"] not in {"succeeded", "partial"} or output_index < 0 or output_index >= len(job["outputs"]):
        raise HTTPException(status_code=404, detail="资源不存在")
    output = job["outputs"][output_index]
    if output.get("delivery_status") == "local":
        raise HTTPException(status_code=410, detail="资源已经保存到员工电脑并清理服务器暂存")
    return output_response(output)


@app.get(
    "/api/jobs/{job_id}/outputs/{output_index}/browser-direct",
    response_model=BrowserDirectOutputResponse,
    tags=["资源"], summary="获取任务输出的同机 ComfyUI 直连地址",
)
def browser_direct_output(
    job_id: str,
    output_index: int,
    user: Annotated[dict, Depends(current_user)],
) -> dict:
    job = job_or_404(app.state.store, job_id, user)
    if job["status"] not in {"succeeded", "partial"} or output_index < 0 or output_index >= len(job["outputs"]):
        raise HTTPException(status_code=404, detail="Resource not found")
    output = job["outputs"][output_index]
    if output.get("delivery_status") == "local":
        raise HTTPException(status_code=410, detail="Resource has already been delivered locally")
    if not output_available(output):
        raise HTTPException(status_code=410, detail="Resource is no longer available")
    if not app.state.worker.comfy.can_stream_output(output.get("_comfy_source")):
        raise HTTPException(status_code=409, detail="Resource does not support browser direct delivery")
    return {"view_url": browser_direct_view_url(output["_comfy_source"])}


@app.post(
    "/api/jobs/{job_id}/outputs/{output_index}/desktop-ticket",
    response_model=DesktopDeliveryTicketResponse,
    tags=["资源"], summary="签发 ZLYUN AI 客户端临时下载凭证",
)
def issue_desktop_delivery_ticket(
    job_id: str, output_index: int, request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    job = job_or_404(app.state.store, job_id, user)
    if job["status"] not in {"succeeded", "partial"} or output_index < 0 or output_index >= len(job["outputs"]):
        raise HTTPException(status_code=404, detail="资源不存在")
    output = job["outputs"][output_index]
    if output.get("delivery_status") == "local":
        raise HTTPException(status_code=410, detail="资源已经保存到员工电脑并清理服务器暂存")
    if not output_available(output):
        raise HTTPException(status_code=410, detail="资源暂存已过期")
    ticket = app.state.desktop_delivery_tickets.issue(user["id"], job_id, output_index)
    app.state.auth_store.audit(
        "issue_desktop_delivery_ticket", "job", actor_user_id=user["id"], target_id=job_id,
        detail=f"output_index={output_index}", ip_address=client_ip(request),
    )
    return {
        "download_url": f"{public_api_path(f'jobs/{job_id}/outputs/{output_index}/download')}?desktop_ticket={ticket}",
        "expires_in_seconds": DESKTOP_DELIVERY_TICKET_SECONDS,
    }


@app.post(
    "/api/jobs/{job_id}/outputs/{output_index}/delivered",
    tags=["资源"], summary="确认资源已写入员工电脑并清理暂存",
)
def confirm_output_delivered(
    job_id: str, output_index: int, request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    job = job_or_404(app.state.store, job_id, user)
    if job["status"] not in {"succeeded", "partial"} or output_index < 0 or output_index >= len(job["outputs"]):
        raise HTTPException(status_code=404, detail="资源不存在")
    output = job["outputs"][output_index]
    if output.get("delivery_status") == "local":
        return public_job(job)
    if not app.state.worker.comfy.finalize_output_source(output.get("_comfy_source")):
        raise HTTPException(status_code=500, detail="ComfyUI 原始输出清理失败，服务器暂存已保留，请重试")
    persistent = app.state.resource_storage.persistent_outputs
    if not persistent:
        deleted = app.state.resource_storage.delete(output["path"])
        if not deleted:
            legacy_path = settings.results_dir / Path(output["path"]).name
            if legacy_path.is_file():
                legacy_path.unlink()
                deleted = True
        if not deleted:
            raise HTTPException(status_code=410, detail="资源暂存已过期")
    delivered_at = datetime.now(timezone.utc).isoformat()
    updated = app.state.store.mark_output_delivered(
        job_id, output_index, delivered_at, "cloud" if persistent else "local",
    )
    app.state.auth_store.audit(
        "deliver_local_resource", "job", actor_user_id=user["id"], target_id=job_id,
        detail=f"output_index={output_index}", ip_address=client_ip(request),
    )
    return public_job(updated)


@app.get(
    "/api/jobs/{job_id}/generations/{generation_item_id}/outputs/{output_index}/download",
    tags=["资源"], summary="下载指定生成项的待交付资源",
)
def download_generation_output(
    job_id: str, generation_item_id: str, output_index: int,
    desktop_ticket: str | None = None,
    user: Annotated[dict | None, Depends(optional_current_user)] = None,
) -> Response:
    if desktop_ticket:
        ticket = app.state.desktop_delivery_tickets.resolve(
            desktop_ticket, job_id, output_index, generation_item_id,
        )
        if ticket is None:
            raise HTTPException(status_code=401, detail="桌面客户端下载凭证无效或已过期")
        try:
            user = app.state.auth_store.get_user(ticket.user_id)
        except KeyError as error:
            raise HTTPException(status_code=401, detail="桌面客户端下载凭证所属账号不存在") from error
        if not user["is_active"]:
            raise HTTPException(status_code=401, detail="桌面客户端下载凭证所属账号已停用")
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    _, item = generation_item_or_404(app.state.store, job_id, generation_item_id, user)
    if item["status"] != "succeeded" or output_index < 0 or output_index >= len(item["outputs"]):
        raise HTTPException(status_code=404, detail="资源不存在")
    output = item["outputs"][output_index]
    if output.get("delivery_status") == "local":
        raise HTTPException(status_code=410, detail="资源已经保存到员工电脑并清理服务器暂存")
    return output_response(output)


@app.get(
    "/api/jobs/{job_id}/generations/{generation_item_id}/outputs/{output_index}/browser-direct",
    response_model=BrowserDirectOutputResponse, tags=["资源"], summary="获取生成项的同机 ComfyUI 输出地址",
)
def browser_direct_generation_output(
    job_id: str, generation_item_id: str, output_index: int,
    user: Annotated[dict, Depends(current_user)],
) -> dict:
    _, item = generation_item_or_404(app.state.store, job_id, generation_item_id, user)
    if item["status"] != "succeeded" or output_index < 0 or output_index >= len(item["outputs"]):
        raise HTTPException(status_code=404, detail="资源不存在")
    output = item["outputs"][output_index]
    if not app.state.worker.comfy.can_stream_output(output.get("_comfy_source")):
        raise HTTPException(status_code=409, detail="该资源不支持浏览器直连交付")
    return {"view_url": browser_direct_view_url(output["_comfy_source"])}


@app.post(
    "/api/jobs/{job_id}/generations/{generation_item_id}/outputs/{output_index}/desktop-ticket",
    response_model=DesktopDeliveryTicketResponse, tags=["资源"], summary="签发生成项桌面下载凭证",
)
def issue_generation_desktop_ticket(
    job_id: str, generation_item_id: str, output_index: int, request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    _, item = generation_item_or_404(app.state.store, job_id, generation_item_id, user)
    if item["status"] != "succeeded" or output_index < 0 or output_index >= len(item["outputs"]):
        raise HTTPException(status_code=404, detail="资源不存在")
    output = item["outputs"][output_index]
    if output.get("delivery_status") == "local" or not output_available(output):
        raise HTTPException(status_code=410, detail="资源暂存已过期或已交付")
    ticket = app.state.desktop_delivery_tickets.issue(user["id"], job_id, output_index, generation_item_id)
    app.state.auth_store.audit(
        "issue_generation_delivery_ticket", "generation_item", actor_user_id=user["id"],
        target_id=generation_item_id, detail=f"output_index={output_index}", ip_address=client_ip(request),
    )
    path = public_api_path(
        f"jobs/{job_id}/generations/{generation_item_id}/outputs/{output_index}/download"
    )
    return {"download_url": f"{path}?desktop_ticket={ticket}", "expires_in_seconds": DESKTOP_DELIVERY_TICKET_SECONDS}


@app.post(
    "/api/jobs/{job_id}/generations/{generation_item_id}/outputs/{output_index}/delivered",
    tags=["资源"], summary="确认指定生成项资源已写入员工电脑",
)
def confirm_generation_output_delivered(
    job_id: str, generation_item_id: str, output_index: int, request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    job, item = generation_item_or_404(app.state.store, job_id, generation_item_id, user)
    if item["status"] != "succeeded" or output_index < 0 or output_index >= len(item["outputs"]):
        raise HTTPException(status_code=404, detail="资源不存在")
    output = item["outputs"][output_index]
    if output.get("delivery_status") == "local":
        return public_job(job)
    if not app.state.worker.comfy.finalize_output_source(output.get("_comfy_source")):
        raise HTTPException(status_code=500, detail="ComfyUI 原始输出清理失败，服务器暂存已保留")
    persistent = app.state.resource_storage.persistent_outputs
    if not persistent:
        deleted = app.state.resource_storage.delete(output["path"])
        if not deleted:
            legacy_path = settings.results_dir / Path(output["path"]).name
            if legacy_path.is_file():
                legacy_path.unlink()
                deleted = True
        if not deleted:
            raise HTTPException(status_code=410, detail="资源暂存已过期")
    delivered_at = datetime.now(timezone.utc).isoformat()
    app.state.store.mark_generation_output_delivered(
        generation_item_id, output_index, delivered_at, "cloud" if persistent else "local",
    )
    app.state.auth_store.audit(
        "deliver_generation_resource", "generation_item", actor_user_id=user["id"],
        target_id=generation_item_id, detail=f"output_index={output_index}", ip_address=client_ip(request),
    )
    return public_job(app.state.store.get(job_id))


if settings.frontend_dist_dir.is_dir():
    ASSET_MEDIA_TYPES = {
        ".js": "application/javascript",
        ".css": "text/css",
        ".svg": "image/svg+xml",
        ".json": "application/json",
        ".woff2": "font/woff2",
    }

    @app.get("/assets/{asset_path:path}", include_in_schema=False)
    def frontend_asset(asset_path: str) -> FileResponse:
        assets_dir = (settings.frontend_dist_dir / "assets").resolve()
        asset = (assets_dir / asset_path).resolve()
        if assets_dir not in asset.parents or not asset.is_file():
            raise HTTPException(status_code=404, detail="前端资源不存在")
        return FileResponse(asset, media_type=ASSET_MEDIA_TYPES.get(asset.suffix.lower()))

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        return FileResponse(settings.frontend_dist_dir / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=7865, reload=False)
