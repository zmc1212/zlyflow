from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Annotated, Any
from urllib.parse import urlencode

import requests
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, Security, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from fastapi.security import APIKeyCookie
from fastapi.openapi.utils import get_openapi

from .api_documentation import enrich_openapi_documentation
from .auth import AuthStore, SESSION_HOURS, csrf_token
from .comfy_provider import ComfyProviderError, ComfyProviderService
from .comfy_service import ComfyService
from .config import settings
from .director_catalog import (
    ArtStyleCatalogError,
    art_style_catalog_payload,
    art_style_ref_for_recipe,
    ensure_art_style_preview,
    find_art_style,
)
from .director_export import (
    DirectorExportError,
    export_timeline_documents,
    ffmpeg_available,
    find_bgm_file,
    find_mux_file,
    find_tts_file,
    find_voice_preview_file,
    generate_recipe_tts,
    mux_recipe_film,
    save_recipe_bgm,
)
from .director_jobs import (
    approve_recipe_asset_version, find_recipe_frame_file, generate_recipe_assets, generate_recipe_stills,
    render_batch_items, render_recipe_shots,
    save_recipe_shot_frame, sync_batch_items, sync_recipe_asset_images,
)
from .director_library import (
    DirectorLibraryError,
    delete_library_asset_files,
    find_library_asset_file,
    insert_library_assets_into_recipe,
    library_image_url,
    normalize_library_asset_fields,
    normalize_library_kind,
    public_library_asset,
    recipe_items_for_library,
    save_library_asset_image,
)
from .director_recipe import (
    AGENT_IDS, DirectorPayloadError, PAYLOAD_KIND_BATCH, PAYLOAD_KIND_RECIPE, empty_batch_payload,
    empty_recipe_payload, normalize_batch_payload, normalize_recipe_payload, payload_kind,
    set_agent_status,
)
from .director_project_service import merge_recipe_creative, merge_recipe_execution, persist_recipe_execution
from .director_operations import DirectorOperationService
from .grs_provider import GrsProviderService
from .llm_client import LlmError, is_upstream_llm_failure
from .llm_provider import LlmProviderService
from .tts_provider import TtsProviderService
from .models import (
    AuthStatusResponse, BrowserDirectOutputResponse, ChangePasswordRequest, ComfyProviderResponse,
    ComfyProviderTestRequest, ComfyProviderUpdateRequest, CreateUserRequest, HealthResponse, JobResponse,
    DesktopDeliveryTicketResponse, GrsBalanceResponse, GrsBalanceSnapshotResponse, GrsImageModelCreateRequest,
    GrsImageModelsResponse, GrsImageModelsUpdateRequest, GrsProviderResponse, GrsProviderTestRequest, GrsProviderUpdateRequest,
    LibraryItemResponse, LoginRequest, ModeResponse, ModesResponse, ResetPasswordRequest, SetupAdminRequest, JobStatus,
    QiniuProviderResponse, QiniuProviderUpdateRequest, StorageCapabilityResponse, UpdateUserRequest, UserResponse, UserRole,
    JobMetadataUpdateRequest,
    LlmProviderResponse, LlmProviderUpdateRequest, LlmProviderTestRequest, LlmModelCatalogRequest, LlmModelCatalogResponse, LlmStatusResponse,
    PromptOptimizeRequest, PromptOptimizeResponse, AnalyzeSubjectResponse, SkillsListResponse,
    ScriptSplitRequest, ScriptSplitResponse,
    DirectorProjectCreateRequest, DirectorProjectUpdateRequest, DirectorProjectListItem,
    DirectorProjectResponse, DirectorProjectMigrateRequest, DirectorProjectMigrateResponse,
    DirectorArtStyleCatalogResponse, DirectorRecipeRunRequest, DirectorRecipeStepRequest,
    DirectorApproveAssetVersionRequest, DirectorGenerateAssetsRequest, DirectorGenerateStillsRequest, DirectorRenderShotsRequest,
    DirectorOperationCreateRequest, DirectorOperationResponse,
    DirectorRenderBatchRequest, DirectorBatchCreateRequest,
    DirectorLibraryAssetCreateRequest, DirectorLibraryAssetUpdateRequest, DirectorLibraryAssetResponse,
    DirectorLibraryFromRecipeRequest, DirectorLibraryFromRecipeResponse, DirectorInsertLibraryAssetsRequest,
    TtsProviderResponse, TtsProviderUpdateRequest, TtsProviderTestRequest,
    DirectorTtsRequest, DirectorMuxRequest, DirectorExportCapabilitiesResponse,
)

from .xiaji_api import register_xiaji_routes
from .xiaji_asset_api import register_xiaji_asset_routes
from .xiaji_asset_store import XiajiAssetStore
from .xiaji_episode_api import register_xiaji_episode_routes
from .xiaji_episode_store import XiajiEpisodeStore
from .xiaji_project_api import register_xiaji_project_routes
from .xiaji_project_store import XiajiProjectStore
from .xiaji_store import XiajiIngestStore
from .qiniu_provider import QiniuProviderService
from .request_log import RequestLogMiddleware, write_request_log

from .resource_storage import create_resource_storage, resource_object_url
from .storage import DirectorProjectConflictError, FINISHED_STATUSES, JobStore, elapsed_ms_between
from .worker import JobWorker
from .workflow_registry import (
    WORKFLOWS, is_h3_workflow, is_image_workflow, normalize_options, option_visible,
    quality_for_megapixels, set_catalog_lookup, validate_option_relationships, validate_references,
    workflow_for,
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


def streamed_remote_output_response(remote_url: str, request: Request | None = None) -> StreamingResponse:
    """Proxy object-storage bytes so download clients receive HTTP 200, not a 307 they may not follow."""
    upstream_headers = {}
    if request is not None and (range_header := request.headers.get("range")):
        upstream_headers["Range"] = range_header
    try:
        upstream = requests.get(
            remote_url, stream=True, timeout=(10, 600), headers=upstream_headers, allow_redirects=True,
        )
    except requests.RequestException as error:
        raise HTTPException(status_code=502, detail=f"云端媒体暂时不可读取: {error}") from error
    if upstream.status_code >= 400:
        status = upstream.status_code
        upstream.close()
        raise HTTPException(status_code=502, detail=f"云端媒体读取失败（HTTP {status}）")

    headers = {
        name: value
        for name in ("Content-Length", "Content-Disposition", "Content-Range", "Accept-Ranges")
        if (value := upstream.headers.get(name)) is not None
    }

    def stream_chunks():
        try:
            yield from upstream.iter_content(chunk_size=1024 * 1024)
        finally:
            upstream.close()

    media_type = upstream.headers.get("Content-Type", "application/octet-stream")
    return StreamingResponse(
        stream_chunks(), status_code=upstream.status_code, media_type=media_type, headers=headers,
    )


def output_response(output: dict, request: Request | None = None) -> Response:
    path = stored_output_path(output)
    if path is not None:
        return FileResponse(path)
    remote_url = app.state.resource_storage.download_url(output["path"])
    if remote_url:
        return streamed_remote_output_response(remote_url, request)
    if app.state.worker.comfy.can_stream_output(output.get("_comfy_source")):
        return streamed_output_response(output)
    raise HTTPException(status_code=410, detail="资源暂存已过期")


def attach_output_cloud_url(output: dict) -> dict:
    if output.get("cloud_url"):
        return output
    if output.get("delivery_status") != "cloud":
        return output
    storage = getattr(app.state, "resource_storage", None)
    derived = resource_object_url(storage, output.get("path"))
    if derived:
        output["cloud_url"] = derived
    return output


def public_output_download_url(output: dict, fallback_url: str) -> str:
    """Keep a stable same-origin download path in job JSON.

    Presigned object-storage URLs change on every poll and break frontend structural
    sharing, which makes videos flicker. The download route streams the signed object
    so clients that do not follow HTTP 307 still receive the file bytes.
    """
    return fallback_url


def output_available(output: dict) -> bool:
    return (
        stored_output_path(output) is not None
        or app.state.worker.comfy.can_stream_output(output.get("_comfy_source"))
        or app.state.resource_storage.download_url(output["path"]) is not None
    )


def output_exposes_download(output: dict) -> bool:
    return output.get("delivery_status", "pending") not in {"local", "expired"}


def browser_direct_view_url(source_info: dict) -> str:
    source = ComfyService.output_source_info(source_info)
    if source["type"] != "output":
        raise HTTPException(status_code=409, detail="Only ComfyUI output resources support browser direct delivery")
    return f"{BROWSER_LOCAL_COMFY_VIEW_URL}?{urlencode(source)}"


def raise_as_llm_http(error: BaseException) -> None:
    """Map LLM client failures to HTTP errors, keeping the upstream log in detail."""
    if isinstance(error, requests.exceptions.RequestException):
        raise HTTPException(status_code=502, detail=f"大模型网络异常：{error}") from error
    if isinstance(error, LlmError):
        status = 502 if is_upstream_llm_failure(error) else 422
        raise HTTPException(status_code=status, detail=str(error)) from error
    raise HTTPException(status_code=400, detail=str(error)) from error


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


def director_project_or_404(store: JobStore, project_id: str, user: dict) -> dict:
    try:
        project = store.get_director_project(project_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="工程不存在") from error
    if project.get("owner_user_id") != user["id"] and user["role"] not in {
        UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value,
    }:
        raise HTTPException(status_code=404, detail="工程不存在")
    return project


def director_library_asset_or_404(store: JobStore, asset_id: str, user: dict) -> dict:
    try:
        asset = store.get_director_library_asset(asset_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="资产不存在") from error
    if asset.get("owner_user_id") != user["id"] and user["role"] not in {
        UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value,
    }:
        raise HTTPException(status_code=404, detail="资产不存在")
    return asset


def public_director_project(record: dict, *, include_document: bool = True) -> dict:
    data = dict(record)
    data.pop("owner_user_id", None)
    if not include_document:
        data.pop("payload", None)
        data.pop("source_script", None)
    return data


def director_operation_or_404(store: JobStore, operation_id: str, user: dict) -> dict:
    try:
        operation = store.get_director_operation(operation_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="导演操作不存在") from error
    if operation.get("owner_user_id") != user["id"] and user["role"] not in {
        UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value,
    }:
        raise HTTPException(status_code=404, detail="导演操作不存在")
    return operation


def public_director_operation(operation: dict) -> dict:
    data = dict(operation)
    data.pop("owner_user_id", None)
    return data


def director_content_conflict_http(error: DirectorProjectConflictError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "DIRECTOR_CONTENT_CONFLICT",
            "message": "工程已在其他窗口更新，请选择加载云端版本或明确覆盖。",
            "current_revision": error.current_project["content_revision"],
            "current_project": public_director_project(error.current_project),
        },
    )


def generation_item_or_404(store: JobStore, job_id: str, generation_item_id: str, user: dict) -> tuple[dict, dict]:
    job = job_or_404(store, job_id, user)
    item = next((
        item for round_data in job.get("rounds", []) for item in round_data.get("generation_items", [])
        if item["id"] == generation_item_id
    ), None)
    if item is None:
        raise HTTPException(status_code=404, detail="生成项不存在")
    return job, item


def attach_elapsed(record: dict) -> dict:
    finished_at = record.get("finished_at")
    if not finished_at and record.get("status") in FINISHED_STATUSES:
        finished_at = record.get("updated_at")
    record["finished_at"] = finished_at or None
    record["elapsed_ms"] = elapsed_ms_between(record.get("created_at"), record.get("finished_at"))
    raw_exec = record.get("execution_elapsed_ms")
    try:
        record["execution_elapsed_ms"] = int(raw_exec) if raw_exec is not None and raw_exec != "" else None
    except (TypeError, ValueError):
        record["execution_elapsed_ms"] = None
    return record


def public_job(job: dict) -> dict:
    data = dict(job)
    data["request_parameters"] = request_parameters(job)
    data.pop("submitted_options", None)
    data.pop("options_submitted", None)
    attach_elapsed(data)
    data["references"] = [
        {"index": index, "url": public_api_path(f"jobs/{job['id']}/references/{index}")}
        for index in range(1, int(job.get("reference_count", 0)) + 1)
    ]
    data["outputs"] = []
    for output_index, raw_output in enumerate(job.get("outputs", [])):
        output = dict(raw_output)
        output.pop("_comfy_source", None)
        attach_output_cloud_url(output)
        if output_exposes_download(output):
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
            attach_elapsed(public_item)
            public_item.pop("comfy_prompt_id", None)
            public_item.pop("comfy_client_id", None)
            public_item.pop("comfy_phase", None)
            public_item.pop("cancel_requested", None)
            public_outputs: list[dict] = []
            for output_index, raw_output in enumerate(item.get("outputs", [])):
                output = dict(raw_output)
                output.pop("_comfy_source", None)
                attach_output_cloud_url(output)
                if output_exposes_download(output):
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
        attach_elapsed(public_round)
        public_rounds.append(public_round)
    data["rounds"] = public_rounds
    data.pop("owner_user_id", None)
    return data


def request_parameters(job: dict) -> list[dict]:
    try:
        definition = workflow_for(job["mode"])
    except KeyError:
        definition = None
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
    options = job.get("options") or {}
    for name in option_definitions:
        if not option_visible(option_definitions[name], options):
            continue
        value = options.get(name)
        if name == "quality" and value is None:
            value = quality_for_megapixels(option_schema, options.get("megapixels"))
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
    database = settings.runtime_database()
    auth_store = AuthStore(database)
    store = JobStore(database)
    xiaji_store = XiajiIngestStore(database)
    xiaji_asset_store = XiajiAssetStore(database)
    xiaji_episode_store = XiajiEpisodeStore(database)
    xiaji_project_store = XiajiProjectStore(database)
    qiniu_provider = QiniuProviderService(store, settings.credential_key)
    resource_storage = qiniu_provider.enabled_storage() or create_resource_storage(settings.resource_provider, settings.staging_dir)
    grs_provider = GrsProviderService(store, settings.credential_key)
    set_catalog_lookup(store.get_grs_image_model)
    llm_provider = LlmProviderService(store, settings.credential_key)
    tts_provider = TtsProviderService(store, settings.credential_key)
    comfy_provider = ComfyProviderService(store, settings.comfy_url)
    comfy = ComfyService(settings, resource_storage, url_resolver=comfy_provider.current_url)
    worker = JobWorker(store, comfy, grs_provider, resource_storage)
    app.state.auth_store = auth_store
    app.state.store = store
    app.state.xiaji_store = xiaji_store
    app.state.xiaji_asset_store = xiaji_asset_store
    app.state.xiaji_episode_store = xiaji_episode_store
    app.state.xiaji_project_store = xiaji_project_store
    app.state.resource_storage = resource_storage
    app.state.grs_provider = grs_provider
    app.state.qiniu_provider = qiniu_provider
    app.state.llm_provider = llm_provider
    app.state.tts_provider = tts_provider
    app.state.comfy_provider = comfy_provider
    app.state.worker = worker
    director_operations = DirectorOperationService(
        store,
        llm_provider=llm_provider,
        worker=worker,
        resource_storage=resource_storage,
    )
    app.state.director_operations = director_operations
    app.state.desktop_delivery_tickets = DesktopDeliveryTickets()
    store.interrupt_stale_director_pipelines()
    store.interrupt_stale_director_operations()
    await worker.start()
    yield
    set_catalog_lookup(None)
    await director_operations.stop()
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
        {"name": "导演台", "description": "员工隔离的导演工程库：Recipe 双引擎、画风目录、9 Agent 流水线与批量短视频。"},
        {"name": "导台2", "description": "按项目组织的内容库、资产库与剧集工坊（脚本 Beat 与镜头草图）。"},
    ],
    lifespan=lifespan,
)

register_xiaji_project_routes(app, current_user=current_user, mutating_user=mutating_user)
register_xiaji_routes(app, current_user=current_user, mutating_user=mutating_user)
register_xiaji_asset_routes(app, current_user=current_user, mutating_user=mutating_user)
register_xiaji_episode_routes(app, current_user=current_user, mutating_user=mutating_user)
app.add_middleware(RequestLogMiddleware)


@app.exception_handler(RequestValidationError)
async def request_validation_log(request: Request, exc: RequestValidationError) -> JSONResponse:
    write_request_log(
        "422",
        {
            "method": request.method,
            "path": request.url.path,
            "errors": exc.errors(),
            "body": exc.body,
        },
    )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


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
    comfy_provider = getattr(app.state, "comfy_provider", None)
    url_resolver = comfy_provider.current_url if comfy_provider is not None else None
    return {
        "webui": "ok",
        "comfy": ComfyService(settings, url_resolver=url_resolver).health(),
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
    if is_image_workflow(definition.id):
        available, reason = app.state.grs_provider.availability(definition.id)
        payload["available"] = available
        payload["unavailable_reason"] = reason
    return payload


def listed_workflows():
    image_workflows = []
    if hasattr(app.state, "grs_provider"):
        image_workflows = app.state.grs_provider.enabled_image_workflows()
    return [*image_workflows, *WORKFLOWS]


@app.get("/api/modes", response_model=ModesResponse, tags=["工作流"], summary="获取工作流注册表")
def modes(_: Annotated[dict, Depends(current_user)]) -> dict:
    return {"modes": [mode_payload(item) for item in listed_workflows()], "image_sizes": [], "presets": PRESETS}


@app.get(
    "/api/modes/{mode_id}",
    response_model=ModeResponse,
    tags=["工作流"],
    summary="获取指定工作流的参数定义",
    description="返回 `POST /api/jobs` 中该工作流可提交的 multipart 字段、参考图约束与 H3 options schema。",
)
def mode_detail(mode_id: str, _: Annotated[dict, Depends(current_user)]) -> dict:
    try:
        return mode_payload(workflow_for(mode_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="工作流不存在") from error


@app.get("/api/admin/providers/grs", response_model=GrsProviderResponse, tags=["管理后台"])
def get_grs_provider(_: Annotated[dict, Depends(super_admin_user)]) -> dict:
    return app.state.grs_provider.public_config()


@app.get("/api/admin/providers/comfy", response_model=ComfyProviderResponse, tags=["管理后台"], summary="获取 ComfyUI 连接地址")
def get_comfy_provider(_: Annotated[dict, Depends(super_admin_user)]) -> dict:
    return app.state.comfy_provider.public_config()


@app.put("/api/admin/providers/comfy", response_model=ComfyProviderResponse, tags=["管理后台"], summary="更新 ComfyUI 连接地址")
def update_comfy_provider(
    payload: ComfyProviderUpdateRequest, request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        result = app.state.comfy_provider.update(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "update_comfy_provider", "provider", actor_user_id=user["id"], target_id="comfy",
        detail=f"base_url={result['base_url']}", ip_address=client_ip(request),
    )
    return result


@app.post("/api/admin/providers/comfy/test", response_model=ComfyProviderResponse, tags=["管理后台"], summary="测试 ComfyUI 连接")
async def test_comfy_provider(
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: ComfyProviderTestRequest | None = None,
) -> dict:
    try:
        arguments = None if payload is None else payload.model_dump()
        result = await asyncio.to_thread(app.state.comfy_provider.test, arguments)
    except (ValueError, ComfyProviderError) as error:
        app.state.auth_store.audit(
            "test_comfy_provider_failed", "provider", actor_user_id=user["id"], target_id="comfy",
            detail=type(error).__name__, ip_address=client_ip(request),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "test_comfy_provider", "provider", actor_user_id=user["id"], target_id="comfy",
        detail="success", ip_address=client_ip(request),
    )
    return result


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


@app.get("/api/admin/providers/grs/models", response_model=GrsImageModelsResponse, tags=["管理后台"], summary="获取 GRS 生图模型目录")
def list_grs_image_models(_: Annotated[dict, Depends(super_admin_user)]) -> dict:
    return app.state.grs_provider.catalog_payload()


@app.put("/api/admin/providers/grs/models", response_model=GrsImageModelsResponse, tags=["管理后台"], summary="更新 GRS 生图模型目录")
def update_grs_image_models(
    payload: GrsImageModelsUpdateRequest, request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        app.state.store.update_grs_image_models([item.model_dump() for item in payload.models])
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    app.state.auth_store.audit(
        "update_grs_image_models", "provider", actor_user_id=user["id"], target_id="grs",
        detail=f"updated {len(payload.models)} image models", ip_address=client_ip(request),
    )
    return app.state.grs_provider.catalog_payload()


@app.post("/api/admin/providers/grs/models", response_model=GrsImageModelsResponse, tags=["管理后台"], summary="添加 GRS 生图模型")
def add_grs_image_model(
    payload: GrsImageModelCreateRequest, request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        created = app.state.store.add_grs_image_model(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    app.state.auth_store.audit(
        "add_grs_image_model", "provider", actor_user_id=user["id"], target_id="grs",
        detail=created["workflow_id"], ip_address=client_ip(request),
    )
    return app.state.grs_provider.catalog_payload()


@app.post("/api/admin/providers/grs/models/sync", response_model=GrsImageModelsResponse, tags=["管理后台"], summary="同步 GRS 内置生图模型目录")
def sync_grs_image_models(
    request: Request, user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    app.state.store.sync_builtin_grs_image_models()
    app.state.auth_store.audit(
        "sync_grs_image_models", "provider", actor_user_id=user["id"], target_id="grs",
        detail="synced builtin image model catalog", ip_address=client_ip(request),
    )
    return app.state.grs_provider.catalog_payload()


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


@app.post("/api/admin/providers/llm/models", response_model=LlmModelCatalogResponse, tags=["管理后台"], summary="拉取上游 LLM 模型目录")
async def list_llm_models(
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: LlmModelCatalogRequest | None = None,
) -> dict:
    try:
        arguments = None if payload is None else payload.model_dump()
        result = await asyncio.to_thread(app.state.llm_provider.list_catalog, arguments)
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "list_llm_models", "provider", actor_user_id=user["id"], target_id="llm",
        detail=f"count={len(result.get('models') or [])}", ip_address=client_ip(request),
    )
    return result


@app.get("/api/admin/providers/tts", response_model=TtsProviderResponse, tags=["管理后台"], summary="获取独立 TTS 配置")
def get_tts_provider(_: Annotated[dict, Depends(super_admin_user)]) -> dict:
    return app.state.tts_provider.public_config()


@app.put("/api/admin/providers/tts", response_model=TtsProviderResponse, tags=["管理后台"], summary="更新独立 TTS 配置")
def update_tts_provider(
    payload: TtsProviderUpdateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        result = app.state.tts_provider.update(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "update_tts_provider", "provider", actor_user_id=user["id"], target_id="tts",
        ip_address=client_ip(request),
    )
    return result


@app.post("/api/admin/providers/tts/test", response_model=TtsProviderResponse, tags=["管理后台"], summary="测试独立 TTS 连接")
async def test_tts_provider(
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: TtsProviderTestRequest | None = None,
) -> dict:
    arguments = None if payload is None else payload.model_dump(exclude_none=True)
    try:
        result = await asyncio.to_thread(app.state.tts_provider.test, arguments)
    except Exception as error:
        app.state.auth_store.audit(
            "test_tts_provider_failed", "provider", actor_user_id=user["id"], target_id="tts",
            detail=str(error)[:200], ip_address=client_ip(request),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "test_tts_provider", "provider", actor_user_id=user["id"], target_id="tts",
        ip_address=client_ip(request),
    )
    return result


@app.get("/api/llm/skills", response_model=SkillsListResponse, tags=["大模型"], summary="获取 MiniMax H3 官方提示词技能列表")
def get_llm_skills(_: Annotated[dict, Depends(current_user)]) -> dict:
    from .llm_minimax_skills import list_h3_skills_payload
    return {"skills": list_h3_skills_payload()}


@app.get("/api/llm/status", response_model=LlmStatusResponse, tags=["大模型"], summary="查询大模型服务可用状态")
def get_llm_status(_: Annotated[dict, Depends(current_user)]) -> dict:
    available, reason = app.state.llm_provider.availability()
    config = app.state.llm_provider.public_config()
    return {
        "available": available,
        "message": reason,
        "supports_vision": bool(config.get("supports_vision")),
        "model": config.get("model"),
    }


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
    except (LlmError, requests.exceptions.RequestException) as error:
        raise_as_llm_http(error)
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


def _image_upload_to_data_url(upload: UploadFile, content: bytes) -> str:
    import base64

    mime = upload.content_type or "image/png"
    if not mime.startswith("image/"):
        mime = "image/png"
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@app.post("/api/llm/analyze-subject", response_model=AnalyzeSubjectResponse, tags=["大模型"], summary="根据参考图提取主体外貌描述")
async def analyze_subject_endpoint(
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
    image: Annotated[UploadFile, File(description="主体参考图")],
    kind: Annotated[str, Form()] = "character",
    name: Annotated[str, Form()] = "主体",
) -> dict:
    available, reason = app.state.llm_provider.availability()
    if not available:
        raise HTTPException(status_code=503, detail=reason or "大模型服务暂未启用或不可用")
    content = await image.read()
    if not content:
        raise HTTPException(status_code=422, detail="请上传主体参考图后再提取外貌")
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="参考图超过 8MB，请压缩后再试")
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="主体分析仅接受图片文件")

    try:
        description = await asyncio.to_thread(
            app.state.llm_provider.analyze_subject,
            image_data_url=_image_upload_to_data_url(image, content),
            kind=kind,
            name=name,
        )
    except (LlmError, requests.exceptions.RequestException) as error:
        raise_as_llm_http(error)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"主体特征提取异常：{error}") from error

    app.state.auth_store.audit(
        "analyze_subject", "llm", actor_user_id=user["id"], target_id="director",
        detail=f"kind={kind}; name={name}",
        ip_address=client_ip(request),
    )
    return {"description": description, "kind": kind, "name": name}


@app.post("/api/llm/split-script", response_model=ScriptSplitResponse, tags=["大模型"], summary="AI 剧本智能拆解为分镜头脚本")
async def split_script_endpoint(
    payload: ScriptSplitRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    available, reason = app.state.llm_provider.availability()
    if not available:
        raise HTTPException(status_code=503, detail=reason or "大模型服务暂未启用或不可用")

    try:
        split_result = await asyncio.to_thread(
            app.state.llm_provider.split_script,
            payload.script,
            shot_count=payload.shot_count or 4,
            style_vibe=payload.style_vibe,
            cast_names=payload.cast_names,
        )
    except (LlmError, requests.exceptions.RequestException) as error:
        raise_as_llm_http(error)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"剧本拆解异常：{error}") from error

    app.state.auth_store.audit(
        "split_script", "llm", actor_user_id=user["id"], target_id="director",
        detail=f"shot_count={payload.shot_count or 4}; style={payload.style_vibe or 'default'}",
        ip_address=client_ip(request),
    )
    return split_result


@app.get(
    "/api/director/art-styles",
    response_model=DirectorArtStyleCatalogResponse,
    tags=["导演台"],
    summary="读取 34 条画风目录",
)
def list_director_art_styles(user: Annotated[dict, Depends(current_user)]) -> dict:
    del user
    return art_style_catalog_payload()


@app.get(
    "/api/director/art-styles/{style_id}/preview",
    tags=["导演台"],
    summary="读取画风预览图",
    responses={200: {"content": {"image/jpeg": {}}}},
)
def director_art_style_preview(style_id: str, user: Annotated[dict, Depends(current_user)]) -> FileResponse:
    del user
    try:
        path = ensure_art_style_preview(style_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="画风不存在")
    except ArtStyleCatalogError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=502, detail=f"画风预览暂不可用：{error}") from error
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.get(
    "/api/director/projects",
    response_model=list[DirectorProjectListItem],
    tags=["导演台"],
    summary="列出当前用户的导演工程",
)
def list_director_projects(user: Annotated[dict, Depends(current_user)]) -> list[dict]:
    return [
        public_director_project(item, include_document=False)
        for item in app.state.store.list_director_projects(user["id"])
    ]


@app.post(
    "/api/director/projects",
    response_model=DirectorProjectResponse,
    status_code=201,
    tags=["导演台"],
    summary="创建导演工程",
)
def create_director_project(
    payload: DirectorProjectCreateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="请填写工程标题")
    try:
        created = app.state.store.create_director_project(
            user["id"],
            title,
            project_id=payload.id,
            summary=payload.summary,
            source_script=payload.source_script,
            style_vibe=payload.style_vibe,
            requested_shot_count=payload.requested_shot_count,
            payload=payload.payload,
            created_at=payload.created_at,
            updated_at=payload.updated_at,
        )
    except DirectorPayloadError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    app.state.auth_store.audit(
        "create_director_project", "director", actor_user_id=user["id"], target_id=created["id"],
        detail=f"title={title}",
        ip_address=client_ip(request),
    )
    return public_director_project(created)


@app.post(
    "/api/director/projects/migrate",
    response_model=DirectorProjectMigrateResponse,
    tags=["导演台"],
    summary="将浏览器 localStorage 导演工程迁入 SQLite",
)
def migrate_director_projects(
    payload: DirectorProjectMigrateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    items = []
    for project in payload.projects:
        title = project.title.strip() or "未命名分镜工程"
        items.append({
            "id": project.id,
            "title": title,
            "summary": project.summary,
            "source_script": project.source_script,
            "style_vibe": project.style_vibe,
            "requested_shot_count": project.requested_shot_count,
            "payload": project.payload,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        })
    result = app.state.store.import_director_projects(user["id"], items)
    app.state.auth_store.audit(
        "migrate_director_projects", "director", actor_user_id=user["id"], target_id="library",
        detail=f"imported={result['imported']}; skipped={result['skipped']}",
        ip_address=client_ip(request),
    )
    return {
        "imported": result["imported"],
        "skipped": result["skipped"],
        "projects": [public_director_project(item, include_document=False) for item in result["projects"]],
    }


@app.get(
    "/api/director/projects/{project_id}",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="读取导演工程（含原文与时间轴）",
)
def get_director_project(project_id: str, user: Annotated[dict, Depends(current_user)]) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    kind = payload_kind(record.get("payload"))
    if kind == PAYLOAD_KIND_RECIPE:
        record = dict(record)
        storage = getattr(app.state, "resource_storage", None)
        latest_recipe = normalize_recipe_payload(record["payload"])
        recipe = sync_recipe_asset_images(app.state.store, latest_recipe, resource_storage=storage)
        merged_execution = merge_recipe_execution(latest_recipe, recipe, scope="all")
        if merged_execution != latest_recipe:
            record = persist_recipe_execution(app.state.store, project_id, recipe, scope="all")
        else:
            record["payload"] = recipe
    elif kind == PAYLOAD_KIND_BATCH:
        record = dict(record)
        record["payload"] = sync_batch_items(app.state.store, record["payload"])
    return public_director_project(record)


@app.put(
    "/api/director/projects/{project_id}",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="更新导演工程",
)
def update_director_project(
    project_id: str,
    payload: DirectorProjectUpdateRequest,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    current = director_project_or_404(app.state.store, project_id, user)
    title = payload.title.strip() if payload.title is not None else None
    if title is not None and not title:
        raise HTTPException(status_code=422, detail="请填写工程标题")
    try:
        updated = app.state.store.update_director_project(
            project_id,
            title=title,
            summary=payload.summary,
            source_script=payload.source_script,
            style_vibe=payload.style_vibe,
            requested_shot_count=payload.requested_shot_count,
            payload=payload.payload,
            update_style_vibe="style_vibe" in payload.model_fields_set,
            update_requested_shot_count="requested_shot_count" in payload.model_fields_set,
            expected_content_revision=payload.expected_content_revision,
            force=payload.force,
            content_update=True,
            payload_merger=(
                merge_recipe_creative
                if payload.payload is not None
                and payload_kind(current.get("payload")) == PAYLOAD_KIND_RECIPE
                and payload_kind(payload.payload) == PAYLOAD_KIND_RECIPE
                else None
            ),
        )
    except DirectorProjectConflictError as error:
        raise director_content_conflict_http(error) from error
    except DirectorPayloadError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return public_director_project(updated)


@app.delete(
    "/api/director/projects/{project_id}",
    status_code=204,
    tags=["导演台"],
    summary="删除导演工程",
)
def delete_director_project(
    project_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> Response:
    director_project_or_404(app.state.store, project_id, user)
    try:
        app.state.store.delete_director_project(project_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="工程不存在") from error
    app.state.auth_store.audit(
        "delete_director_project", "director", actor_user_id=user["id"], target_id=project_id,
        ip_address=client_ip(request),
    )
    return Response(status_code=204)


@app.post(
    "/api/director/projects/{project_id}/copy",
    response_model=DirectorProjectResponse,
    status_code=201,
    tags=["导演台"],
    summary="复制导演工程",
)
def copy_director_project(
    project_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    director_project_or_404(app.state.store, project_id, user)
    copied = app.state.store.copy_director_project(project_id, user["id"])
    app.state.auth_store.audit(
        "copy_director_project", "director", actor_user_id=user["id"], target_id=copied["id"],
        detail=f"source={project_id}",
        ip_address=client_ip(request),
    )
    return public_director_project(copied)


@app.post(
    "/api/director/projects/{project_id}/convert-to-recipe",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="将旧时间轴工程转为 Recipe",
)
def convert_director_project_to_recipe(
    project_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    director_project_or_404(app.state.store, project_id, user)
    try:
        converted = app.state.store.convert_director_project_to_recipe(project_id)
    except DirectorPayloadError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "convert_director_project_to_recipe", "director", actor_user_id=user["id"], target_id=project_id,
        ip_address=client_ip(request),
    )
    return public_director_project(converted)


@app.get(
    "/api/director/library-assets",
    response_model=list[DirectorLibraryAssetResponse],
    tags=["导演台"],
    summary="列出当前用户的人物/场景/道具资产",
)
def list_director_library_assets(
    user: Annotated[dict, Depends(current_user)],
    kind: str | None = None,
) -> list[dict]:
    filter_kind = None
    if kind:
        try:
            filter_kind = normalize_library_kind(kind)
        except DirectorLibraryError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    return [
        public_library_asset(item)
        for item in app.state.store.list_director_library_assets(user["id"], kind=filter_kind)
    ]


@app.post(
    "/api/director/library-assets",
    response_model=DirectorLibraryAssetResponse,
    tags=["导演台"],
    summary="新建员工级资产",
)
def create_director_library_asset(
    payload: DirectorLibraryAssetCreateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        fields = normalize_library_asset_fields(payload.model_dump())
    except DirectorLibraryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    created = app.state.store.create_director_library_asset(
        user["id"],
        kind=fields["kind"],
        name=fields["name"],
        description=fields.get("description") or "",
        prompt_text=fields.get("prompt_text") or "",
        gender=fields.get("gender") or "",
        image_url=fields.get("image_url"),
        image_job_id=fields.get("image_job_id"),
    )
    app.state.auth_store.audit(
        "create_director_library_asset", "director", actor_user_id=user["id"], target_id=created["id"],
        detail=created["kind"], ip_address=client_ip(request),
    )
    return public_library_asset(created)


@app.post(
    "/api/director/library-assets/from-recipe",
    response_model=DirectorLibraryFromRecipeResponse,
    tags=["导演台"],
    summary="把 Recipe 人物/场景/道具存入资产库",
)
def save_director_library_assets_from_recipe(
    payload: DirectorLibraryFromRecipeRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = director_project_or_404(app.state.store, payload.project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以存入资产库")
    try:
        items = recipe_items_for_library(
            record["payload"],
            character_ids=payload.character_ids,
            location_ids=payload.location_ids,
            prop_ids=payload.prop_ids,
        )
    except DirectorLibraryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    imported: list[dict] = []
    for item in items:
        created = app.state.store.create_director_library_asset(
            user["id"],
            kind=item["kind"],
            name=item["name"] or "未命名资产",
            description=item.get("description") or "",
            prompt_text=item.get("prompt_text") or "",
            gender=item.get("gender") or "",
            image_url=item.get("image_url"),
            image_job_id=item.get("image_job_id"),
            source_project_id=payload.project_id,
        )
        imported.append(public_library_asset(created))
    app.state.auth_store.audit(
        "save_director_library_from_recipe", "director", actor_user_id=user["id"],
        target_id=payload.project_id, detail=f"imported={len(imported)}", ip_address=client_ip(request),
    )
    return {"imported": len(imported), "assets": imported}


@app.put(
    "/api/director/library-assets/{asset_id}",
    response_model=DirectorLibraryAssetResponse,
    tags=["导演台"],
    summary="更新员工级资产",
)
def update_director_library_asset(
    asset_id: str,
    payload: DirectorLibraryAssetUpdateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    director_library_asset_or_404(app.state.store, asset_id, user)
    raw = payload.model_dump(exclude_unset=True)
    try:
        fields = normalize_library_asset_fields(raw, partial=True) if raw else {}
    except DirectorLibraryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    updated = app.state.store.update_director_library_asset(
        asset_id,
        kind=fields.get("kind"),
        name=fields.get("name"),
        description=fields.get("description"),
        prompt_text=fields.get("prompt_text"),
        gender=fields.get("gender"),
        image_url=fields.get("image_url"),
        image_job_id=fields.get("image_job_id"),
        update_image_url="image_url" in fields,
        update_image_job_id="image_job_id" in fields,
    )
    app.state.auth_store.audit(
        "update_director_library_asset", "director", actor_user_id=user["id"], target_id=asset_id,
        ip_address=client_ip(request),
    )
    return public_library_asset(updated)


@app.delete(
    "/api/director/library-assets/{asset_id}",
    status_code=204,
    tags=["导演台"],
    summary="删除员工级资产",
)
def delete_director_library_asset(
    asset_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> Response:
    current = director_library_asset_or_404(app.state.store, asset_id, user)
    app.state.store.delete_director_library_asset(asset_id)
    delete_library_asset_files(str(current.get("owner_user_id") or user["id"]), asset_id)
    app.state.auth_store.audit(
        "delete_director_library_asset", "director", actor_user_id=user["id"], target_id=asset_id,
        ip_address=client_ip(request),
    )
    return Response(status_code=204)


@app.post(
    "/api/director/library-assets/{asset_id}/image",
    response_model=DirectorLibraryAssetResponse,
    tags=["导演台"],
    summary="上传资产参考图",
)
async def upload_director_library_asset_image(
    asset_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
    file: Annotated[UploadFile, File(description="人物/场景/道具参考图")],
) -> dict:
    current = director_library_asset_or_404(app.state.store, asset_id, user)
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="资产图必须为图片")
    suffix = Path(file.filename or "image.png").suffix or ".png"
    staging = settings.staging_dir / f"director-library-{secrets.token_urlsafe(6)}{suffix}"
    staging.parent.mkdir(parents=True, exist_ok=True)
    await save_upload(file, staging)
    try:
        dest = save_library_asset_image(
            owner_user_id=str(current.get("owner_user_id") or user["id"]),
            asset_id=asset_id,
            source=staging,
        )
    finally:
        staging.unlink(missing_ok=True)
    updated = app.state.store.update_director_library_asset(
        asset_id,
        image_url=library_image_url(asset_id),
        image_path=str(dest),
        update_image_url=True,
        update_image_path=True,
    )
    app.state.auth_store.audit(
        "upload_director_library_image", "director", actor_user_id=user["id"], target_id=asset_id,
        ip_address=client_ip(request),
    )
    return public_library_asset(updated)


@app.get(
    "/api/director/library-assets/{asset_id}/image",
    tags=["导演台"],
    summary="读取资产参考图",
)
def download_director_library_asset_image(
    asset_id: str,
    user: Annotated[dict, Depends(current_user)],
) -> FileResponse:
    current = director_library_asset_or_404(app.state.store, asset_id, user)
    path = find_library_asset_file(
        str(current.get("owner_user_id") or user["id"]),
        asset_id,
        current.get("image_path") if isinstance(current.get("image_path"), str) else None,
    )
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="资产图不存在")
    media = "image/png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        media = "image/jpeg"
    elif path.suffix.lower() == ".webp":
        media = "image/webp"
    elif path.suffix.lower() == ".gif":
        media = "image/gif"
    return FileResponse(path, media_type=media)


def _persist_director_recipe(project_id: str, recipe: dict[str, Any], *, source_script: str | None = None) -> dict:
    title = (recipe.get("script") or {}).get("title") or None
    summary = (recipe.get("script") or {}).get("summary") or None
    return app.state.store.update_director_project(
        project_id,
        title=title,
        summary=summary,
        source_script=source_script,
        payload=recipe,
    )


async def _enqueue_job_ids(job_ids: list[str]) -> None:
    for job_id in job_ids:
        await app.state.worker.enqueue(job_id)


@app.post(
    "/api/director/recipes/{project_id}/operations",
    response_model=DirectorOperationResponse,
    status_code=202,
    tags=["导演台"],
    summary="创建导演长操作",
)
async def create_director_operation(
    project_id: str,
    payload: DirectorOperationCreateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以创建导演操作")
    if payload.kind == "plan_pipeline":
        available, reason = app.state.llm_provider.availability()
        if not available:
            raise HTTPException(status_code=503, detail=reason or "大模型服务暂未启用或不可用")
        requested_agents = payload.agents or []
        unknown = [agent_id for agent_id in requested_agents if agent_id not in AGENT_IDS]
        if unknown:
            raise HTTPException(status_code=422, detail=f"未知 Agent：{', '.join(unknown)}")
        if payload.art_style_id and find_art_style(payload.art_style_id) is None:
            raise HTTPException(status_code=422, detail="画风必须选自目录")
    body = payload.model_dump(exclude_none=True)
    try:
        operation = app.state.store.create_director_operation(
            project_id=project_id,
            owner_user_id=user["id"],
            kind=payload.kind,
            request=body,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    app.state.director_operations.start(operation["id"])
    app.state.auth_store.audit(
        "create_director_operation",
        "director",
        actor_user_id=user["id"],
        target_id=project_id,
        detail=f"{payload.kind}:{operation['id']}",
        ip_address=client_ip(request),
    )
    return public_director_operation(operation)


@app.get(
    "/api/director/operations/{operation_id}",
    response_model=DirectorOperationResponse,
    tags=["导演台"],
    summary="读取导演长操作",
)
def get_director_operation(
    operation_id: str,
    user: Annotated[dict, Depends(current_user)],
) -> dict:
    return public_director_operation(director_operation_or_404(app.state.store, operation_id, user))


@app.post(
    "/api/director/operations/{operation_id}/cancel",
    response_model=DirectorOperationResponse,
    tags=["导演台"],
    summary="取消导演长操作",
)
def cancel_director_operation(
    operation_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    operation = director_operation_or_404(app.state.store, operation_id, user)
    updated = app.state.store.request_director_operation_cancel(operation["id"])
    app.state.auth_store.audit(
        "cancel_director_operation",
        "director",
        actor_user_id=user["id"],
        target_id=operation["project_id"],
        detail=operation_id,
        ip_address=client_ip(request),
    )
    return public_director_operation(updated)


@app.post(
    "/api/director/recipes/run",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="启动导演 9 Agent 流水线",
    deprecated=True,
)
async def run_director_recipe(
    payload: DirectorRecipeRunRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    available, reason = app.state.llm_provider.availability()
    if not available:
        raise HTTPException(status_code=503, detail=reason or "大模型服务暂未启用或不可用")
    goal = payload.goal.strip()
    if payload.art_style_id and find_art_style(payload.art_style_id) is None:
        raise HTTPException(status_code=422, detail="画风必须选自目录")
    agents = None
    if payload.agents:
        unknown = [agent_id for agent_id in payload.agents if agent_id not in AGENT_IDS]
        if unknown:
            raise HTTPException(status_code=422, detail=f"未知 Agent：{', '.join(unknown)}")
        agents = [agent_id for agent_id in payload.agents if agent_id in AGENT_IDS]
        if not agents:
            raise HTTPException(status_code=422, detail="agents 不能为空")
    if payload.project_id:
        record = director_project_or_404(app.state.store, payload.project_id, user)
        if payload_kind(record.get("payload")) == PAYLOAD_KIND_BATCH:
            raise HTTPException(status_code=422, detail="批量工程不能跑导演流水线")
        recipe = record.get("payload") or empty_recipe_payload()
        if payload_kind(recipe) != PAYLOAD_KIND_RECIPE:
            recipe = empty_recipe_payload(title=payload.title or record["title"], full_story=goal)
        project_id = record["id"]
    else:
        title = (payload.title or goal[:24] or "未命名导演工程").strip()
        created = app.state.store.create_director_project(
            user["id"],
            title,
            summary="",
            source_script=goal,
            payload=empty_recipe_payload(title=title, full_story=goal),
        )
        recipe = created["payload"]
        project_id = created["id"]

    def persist(current: dict) -> None:
        _persist_director_recipe(project_id, current, source_script=goal)

    persist(recipe)
    try:
        updated = await asyncio.to_thread(
            app.state.llm_provider.run_director_recipe,
            recipe,
            goal=goal,
            art_style_id=payload.art_style_id,
            agents=agents,
            skip_research=payload.skip_research,
            on_progress=persist,
        )
    except LlmError as error:
        raise_as_llm_http(error)
    except DirectorPayloadError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    saved = _persist_director_recipe(project_id, updated, source_script=goal)
    app.state.auth_store.audit(
        "run_director_recipe", "director", actor_user_id=user["id"], target_id=project_id,
        ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.post(
    "/api/director/recipes/{project_id}/step",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="重跑单个导演 Agent",
)
async def run_director_recipe_step(
    project_id: str,
    payload: DirectorRecipeStepRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以单步重跑")
    available, reason = app.state.llm_provider.availability()
    if not available and payload.agent_id != "media":
        raise HTTPException(status_code=503, detail=reason or "大模型服务暂未启用或不可用")
    goal = (payload.goal or record.get("source_script") or (record.get("payload") or {}).get("script", {}).get("fullStory") or record["title"]).strip()
    running_recipe = normalize_recipe_payload(record.get("payload") or empty_recipe_payload())
    running_recipe["pipelineRun"] = {"agents": [payload.agent_id], "active": True}
    set_agent_status(running_recipe, payload.agent_id, "running")
    source_script = record.get("source_script")

    def persist_step(current: dict) -> None:
        _persist_director_recipe(project_id, current, source_script=source_script)

    persist_step(running_recipe)
    try:
        if payload.agent_id == "media":
            from .director_agents import run_agent
            updated = run_agent(
                "media",
                running_recipe,
                goal=goal,
                chat_fn=None,
                art_style_id=payload.art_style_id,
                on_progress=persist_step,
            )
        else:
            updated = await asyncio.to_thread(
                app.state.llm_provider.run_director_agent_step,
                running_recipe,
                goal=goal,
                agent_id=payload.agent_id,
                art_style_id=payload.art_style_id,
                skip_research=payload.skip_research,
                on_progress=persist_step,
            )
    except LlmError as error:
        set_agent_status(running_recipe, payload.agent_id, "failed", str(error))
        running_recipe["pipelineRun"] = {"agents": [payload.agent_id], "active": False}
        persist_step(running_recipe)
        raise_as_llm_http(error)
    except (DirectorPayloadError, ValueError) as error:
        set_agent_status(running_recipe, payload.agent_id, "failed", str(error))
        running_recipe["pipelineRun"] = {"agents": [payload.agent_id], "active": False}
        persist_step(running_recipe)
        raise HTTPException(status_code=422, detail=str(error)) from error
    updated["pipelineRun"] = {"agents": [payload.agent_id], "active": False}
    saved = _persist_director_recipe(project_id, updated, source_script=source_script)
    app.state.auth_store.audit(
        "run_director_recipe_step", "director", actor_user_id=user["id"], target_id=project_id,
        detail=payload.agent_id, ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.post(
    "/api/director/recipes/{project_id}/generate-assets",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="为角色与场景提交 GRS 定妆图",
)
async def generate_director_recipe_assets(
    project_id: str,
    payload: DirectorGenerateAssetsRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以生成定妆")
    try:
        recipe, job_ids = generate_recipe_assets(
            app.state.store,
            app.state.grs_provider,
            owner_user_id=user["id"],
            recipe=record["payload"],
            character_ids=payload.character_ids,
            location_ids=payload.location_ids,
            prop_ids=payload.prop_ids,
            targets=[item.model_dump() for item in payload.targets],
            force=payload.force,
            resource_storage=getattr(app.state, "resource_storage", None),
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    saved = persist_recipe_execution(app.state.store, project_id, recipe, scope="assets")
    await _enqueue_job_ids(job_ids)
    app.state.auth_store.audit(
        "generate_director_assets", "director", actor_user_id=user["id"], target_id=project_id,
        detail=f"jobs={len(job_ids)}", ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.post(
    "/api/director/recipes/{project_id}/approve-asset-version",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="批准角色、场景或道具的定妆候选版本",
)
def approve_director_recipe_asset_version(
    project_id: str,
    payload: DirectorApproveAssetVersionRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以批准定妆")

    def approve_latest(latest: dict[str, Any]) -> dict[str, Any]:
        synced = sync_recipe_asset_images(
            app.state.store,
            latest,
            resource_storage=getattr(app.state, "resource_storage", None),
        )
        return approve_recipe_asset_version(
            synced,
            kind=payload.kind,
            asset_id=payload.asset_id,
            version_id=payload.version_id,
            look_id=payload.look_id,
        )

    try:
        saved = app.state.store.mutate_director_project_payload(
            project_id,
            approve_latest,
            content_update=True,
            expected_content_revision=payload.content_revision,
        )
    except DirectorProjectConflictError as error:
        raise director_content_conflict_http(error) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    app.state.auth_store.audit(
        "approve_director_asset", "director", actor_user_id=user["id"], target_id=project_id,
        detail=f"{payload.kind}:{payload.asset_id}:{payload.version_id}", ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.post(
    "/api/director/recipes/{project_id}/insert-library-assets",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="从员工资产库插入人物/场景/道具",
)
def insert_director_library_assets(
    project_id: str,
    payload: DirectorInsertLibraryAssetsRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以从资产库插入")
    if not payload.asset_ids:
        raise HTTPException(status_code=422, detail="请选择要插入的资产")
    assets = []
    for asset_id in payload.asset_ids:
        asset = director_library_asset_or_404(app.state.store, asset_id, user)
        if asset.get("owner_user_id") != user["id"]:
            raise HTTPException(status_code=404, detail="资产不存在")
        assets.append(asset)
    try:
        recipe = insert_library_assets_into_recipe(record["payload"], assets)
    except DirectorLibraryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        saved = app.state.store.update_director_project(
            project_id,
            payload=recipe,
            expected_content_revision=payload.expected_content_revision,
            content_update=True,
            payload_merger=merge_recipe_creative,
        )
    except DirectorProjectConflictError as error:
        raise director_content_conflict_http(error) from error
    app.state.auth_store.audit(
        "insert_director_library_assets", "director", actor_user_id=user["id"], target_id=project_id,
        detail=f"count={len(assets)}", ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.post(
    "/api/director/recipes/{project_id}/generate-stills",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="为分镜提交 GRS 静帧",
)
async def generate_director_recipe_stills(
    project_id: str,
    payload: DirectorGenerateStillsRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以生成静帧")
    try:
        recipe, job_ids = generate_recipe_stills(
            app.state.store,
            app.state.grs_provider,
            owner_user_id=user["id"],
            recipe=record["payload"],
            shot_ids=payload.shot_ids,
            force=payload.force,
            resource_storage=getattr(app.state, "resource_storage", None),
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    saved = persist_recipe_execution(
        app.state.store, project_id, recipe, scope="still", shot_ids=payload.shot_ids,
    )
    await _enqueue_job_ids(job_ids)
    app.state.auth_store.audit(
        "generate_director_stills", "director", actor_user_id=user["id"], target_id=project_id,
        detail=f"jobs={len(job_ids)}", ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.post(
    "/api/director/recipes/{project_id}/frames",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="上传分镜首帧或尾帧",
)
async def upload_director_recipe_frame(
    project_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
    shot_id: Annotated[str, Form(description="分镜 ID")],
    slot: Annotated[str, Form(description="first 或 end")],
    file: Annotated[UploadFile, File(description="帧图片")],
    expected_content_revision: Annotated[
        int | None,
        Form(ge=1, description="客户端最后读取的创作内容版本；不匹配时返回 409。"),
    ] = None,
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以上传分镜帧")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="首尾帧必须为图片")
    suffix = Path(file.filename or "frame.png").suffix or ".png"
    staging = settings.staging_dir / f"director-frame-{secrets.token_urlsafe(6)}{suffix}"
    staging.parent.mkdir(parents=True, exist_ok=True)
    await save_upload(file, staging)
    try:
        saved = app.state.store.mutate_director_project_payload(
            project_id,
            lambda latest: save_recipe_shot_frame(
                normalize_recipe_payload(latest),
                owner_user_id=user["id"],
                project_id=project_id,
                shot_id=shot_id,
                slot=slot,
                source=staging,
            ),
            content_update=True,
            expected_content_revision=expected_content_revision,
        )
    except DirectorProjectConflictError as error:
        raise director_content_conflict_http(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        staging.unlink(missing_ok=True)
    app.state.auth_store.audit(
        "upload_director_frame", "director", actor_user_id=user["id"], target_id=project_id,
        detail=f"{shot_id}:{slot}", ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.get(
    "/api/director/recipes/{project_id}/frames/{shot_id}/{slot}",
    tags=["导演台"],
    summary="读取分镜首帧或尾帧",
)
def download_director_recipe_frame(
    project_id: str,
    shot_id: str,
    slot: str,
    user: Annotated[dict, Depends(current_user)],
) -> FileResponse:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=404, detail="分镜帧不存在")
    if slot not in {"first", "end"}:
        raise HTTPException(status_code=404, detail="分镜帧不存在")
    path = find_recipe_frame_file(
        owner_user_id=user["id"],
        project_id=project_id,
        shot_id=shot_id,
        slot=slot,
    )
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="分镜帧不存在")
    media = "image/png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        media = "image/jpeg"
    elif path.suffix.lower() == ".webp":
        media = "image/webp"
    elif path.suffix.lower() == ".gif":
        media = "image/gif"
    return FileResponse(path, media_type=media)


@app.post(
    "/api/director/recipes/{project_id}/render-shots",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="按镜提交 MiniMax H3 视频任务",
    deprecated=True,
)
async def render_director_recipe_shots(
    project_id: str,
    payload: DirectorRenderShotsRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以提交分镜")
    llm_available, _ = app.state.llm_provider.availability()
    def persist_progress(current: dict) -> None:
        persist_recipe_execution(
            app.state.store, project_id, current, scope="render", shot_ids=payload.shot_ids,
        )

    try:
        recipe, job_ids = await asyncio.to_thread(
            render_recipe_shots,
            app.state.store,
            owner_user_id=user["id"],
            recipe=record["payload"],
            shot_ids=payload.shot_ids,
            render_pass=payload.render_pass,
            resource_storage=getattr(app.state, "resource_storage", None),
            h3_prompt_refiner=(
                app.state.llm_provider.polish_director_h3_prompt
                if llm_available and payload.polish_prompt
                else None
            ),
            on_progress=persist_progress,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except LlmError as error:
        raise_as_llm_http(error)
    saved = persist_recipe_execution(
        app.state.store, project_id, recipe, scope="render", shot_ids=payload.shot_ids,
    )
    await _enqueue_job_ids(job_ids)
    app.state.auth_store.audit(
        "render_director_shots", "director", actor_user_id=user["id"], target_id=project_id,
        detail=f"jobs={len(job_ids)}", ip_address=client_ip(request),
    )
    return public_director_project(saved)


def _audio_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".mp4": "video/mp4",
    }.get(suffix, "application/octet-stream")


def _image_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith("image/"):
        return guessed
    try:
        header = path.read_bytes()[:16]
    except OSError:
        return "image/png"
    signatures = (
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
        (b"BM", "image/bmp"),
    )
    for signature, media in signatures:
        if header.startswith(signature):
            return media
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _safe_export_filename(title: str, suffix: str) -> str:
    stem = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in {"-", "_"}) else "_"
        for ch in (title or "director")[:40]
    ).strip("_") or "director"
    return f"{stem}{suffix}"


@app.get(
    "/api/director/export-capabilities",
    response_model=DirectorExportCapabilitiesResponse,
    tags=["导演台"],
    summary="查询 TTS 与 ffmpeg 成片能力",
)
def get_director_export_capabilities(_: Annotated[dict, Depends(current_user)]) -> dict:
    ffmpeg = ffmpeg_available()
    tts = app.state.tts_provider.public_config()
    available, reason = app.state.tts_provider.availability()
    return {
        **ffmpeg,
        "tts_available": available,
        "tts_reason": reason,
        "voices": tts.get("voices") or [],
    }


@app.post(
    "/api/director/recipes/{project_id}/tts",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="为分镜或角色生成 TTS 配音",
)
async def generate_director_recipe_tts(
    project_id: str,
    payload: DirectorTtsRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以生成配音")
    try:
        recipe = await asyncio.to_thread(
            generate_recipe_tts,
            normalize_recipe_payload(record["payload"]),
            app.state.tts_provider,
            owner_user_id=user["id"],
            project_id=project_id,
            shot_ids=payload.shot_ids,
            character_id=payload.character_id,
            text=payload.text,
        )
    except DirectorExportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except LlmError as error:
        raise_as_llm_http(error)
    saved = persist_recipe_execution(
        app.state.store,
        project_id,
        recipe,
        scope="tts",
        shot_ids=payload.shot_ids,
        character_id=payload.character_id,
    )
    app.state.auth_store.audit(
        "generate_director_tts", "director", actor_user_id=user["id"], target_id=project_id,
        ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.get(
    "/api/director/recipes/{project_id}/tts/{shot_id}",
    tags=["导演台"],
    summary="读取分镜 TTS 音频",
)
def download_director_shot_tts(
    project_id: str,
    shot_id: str,
    user: Annotated[dict, Depends(current_user)],
) -> FileResponse:
    director_project_or_404(app.state.store, project_id, user)
    path = find_tts_file(user["id"], project_id, shot_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="配音不存在")
    return FileResponse(path, media_type=_audio_media_type(path))


@app.get(
    "/api/director/recipes/{project_id}/voices/{character_id}",
    tags=["导演台"],
    summary="读取角色 TTS 试听",
)
def download_director_character_voice(
    project_id: str,
    character_id: str,
    user: Annotated[dict, Depends(current_user)],
) -> FileResponse:
    director_project_or_404(app.state.store, project_id, user)
    path = find_voice_preview_file(user["id"], project_id, character_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="试听不存在")
    return FileResponse(path, media_type=_audio_media_type(path))


@app.post(
    "/api/director/recipes/{project_id}/bgm",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="上传导演工程配乐",
)
async def upload_director_recipe_bgm(
    project_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
    file: Annotated[UploadFile, File(description="配乐音频")],
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以上传配乐")
    if file.content_type and not (
        file.content_type.startswith("audio/") or file.content_type in {"application/octet-stream", "video/mp4"}
    ):
        raise HTTPException(status_code=422, detail="配乐必须为音频文件")
    suffix = Path(file.filename or "bgm.mp3").suffix or ".mp3"
    staging = settings.staging_dir / f"director-bgm-{secrets.token_urlsafe(6)}{suffix}"
    staging.parent.mkdir(parents=True, exist_ok=True)
    await save_upload(file, staging)
    try:
        recipe = save_recipe_bgm(
            normalize_recipe_payload(record["payload"]),
            owner_user_id=user["id"],
            project_id=project_id,
            source=staging,
        )
    except DirectorExportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        staging.unlink(missing_ok=True)
    saved = persist_recipe_execution(app.state.store, project_id, recipe, scope="audio")
    app.state.auth_store.audit(
        "upload_director_bgm", "director", actor_user_id=user["id"], target_id=project_id,
        ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.get(
    "/api/director/recipes/{project_id}/bgm",
    tags=["导演台"],
    summary="读取导演工程配乐",
)
def download_director_recipe_bgm(
    project_id: str,
    user: Annotated[dict, Depends(current_user)],
) -> FileResponse:
    director_project_or_404(app.state.store, project_id, user)
    path = find_bgm_file(user["id"], project_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="配乐不存在")
    return FileResponse(path, media_type=_audio_media_type(path))


@app.post(
    "/api/director/recipes/{project_id}/mux",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="用 ffmpeg 合成工作台内成片 MP4",
)
async def mux_director_recipe_film(
    project_id: str,
    payload: DirectorMuxRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以导出成片")
    try:
        recipe = await asyncio.to_thread(
            mux_recipe_film,
            normalize_recipe_payload(record["payload"]),
            app.state.store,
            owner_user_id=user["id"],
            project_id=project_id,
            burn_subtitles=payload.burn_subtitles,
            resource_storage=getattr(app.state, "resource_storage", None),
            runner=getattr(app.state, "ffmpeg_runner", None),
        )
    except DirectorExportError as error:
        message = str(error)
        status = 503 if "ffmpeg" in message.lower() else 422
        raise HTTPException(status_code=status, detail=message) from error
    saved = persist_recipe_execution(app.state.store, project_id, recipe, scope="mux")
    app.state.auth_store.audit(
        "mux_director_film", "director", actor_user_id=user["id"], target_id=project_id,
        ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.get(
    "/api/director/recipes/{project_id}/mux",
    tags=["导演台"],
    summary="下载工作台内成片 MP4",
)
def download_director_recipe_mux(
    project_id: str,
    user: Annotated[dict, Depends(current_user)],
) -> FileResponse:
    record = director_project_or_404(app.state.store, project_id, user)
    path = find_mux_file(project_id, record.get("payload"))
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="成片不存在")
    return FileResponse(path, media_type="video/mp4", filename=_safe_export_filename(record.get("title") or "film", ".mp4"))


@app.get(
    "/api/director/recipes/{project_id}/export.fcpxml",
    tags=["导演台"],
    summary="下载 FCPXML 时间线",
)
def download_director_fcpxml(
    project_id: str,
    user: Annotated[dict, Depends(current_user)],
) -> Response:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以导出 FCPXML")
    try:
        _clips, xml, _edl = export_timeline_documents(
            normalize_recipe_payload(record["payload"]),
            app.state.store,
            owner_user_id=user["id"],
            project_id=project_id,
            title=record.get("title") or "导演成片",
            resource_storage=getattr(app.state, "resource_storage", None),
        )
    except DirectorExportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    filename = _safe_export_filename(record.get("title") or "director", ".fcpxml")
    return Response(
        content=xml.encode("utf-8"),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get(
    "/api/director/recipes/{project_id}/export.edl",
    tags=["导演台"],
    summary="下载 EDL 时间线",
)
def download_director_edl(
    project_id: str,
    user: Annotated[dict, Depends(current_user)],
) -> Response:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以导出 EDL")
    try:
        _clips, _xml, edl = export_timeline_documents(
            normalize_recipe_payload(record["payload"]),
            app.state.store,
            owner_user_id=user["id"],
            project_id=project_id,
            title=record.get("title") or "导演成片",
            resource_storage=getattr(app.state, "resource_storage", None),
        )
    except DirectorExportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    filename = _safe_export_filename(record.get("title") or "director", ".edl")
    return Response(
        content=edl.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post(
    "/api/director/batches",
    response_model=DirectorProjectResponse,
    status_code=201,
    tags=["导演台"],
    summary="短视频批量：主题裂变并排队 H3 文生",
)
async def create_director_batch(
    payload: DirectorBatchCreateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    available, reason = app.state.llm_provider.availability()
    if not available:
        raise HTTPException(status_code=503, detail=reason or "大模型服务暂未启用或不可用")
    art_style = None
    if payload.art_style_id:
        found = find_art_style(payload.art_style_id)
        if found is None:
            raise HTTPException(status_code=422, detail="画风必须选自目录")
        art_style = art_style_ref_for_recipe(found)
    try:
        scripts = await asyncio.to_thread(
            app.state.llm_provider.fission_batch_scripts,
            theme=payload.theme.strip(),
            count=payload.count,
            duration_sec=payload.duration_sec,
            aspect_ratio=payload.aspect_ratio,
            art_style=art_style,
        )
    except LlmError as error:
        raise_as_llm_http(error)
    batch = empty_batch_payload(
        theme=payload.theme.strip(),
        count=payload.count,
        aspect_ratio=payload.aspect_ratio,
        duration_sec=payload.duration_sec,
        video_workflow_family=payload.video_workflow_family,
    )
    batch["artStyle"] = art_style
    batch["items"] = [
        {
            "title": item["title"],
            "description": item.get("description") or item["title"],
            "script": item["script"],
            "status": "idle",
        }
        for item in scripts
    ]
    title = (payload.title or payload.theme.strip()[:24] or "批量短视频").strip()
    if payload.project_id:
        record = director_project_or_404(app.state.store, payload.project_id, user)
        saved = app.state.store.update_director_project(
            record["id"],
            title=title,
            summary=payload.theme.strip(),
            source_script=payload.theme.strip(),
            payload=batch,
        )
    else:
        saved = app.state.store.create_director_project(
            user["id"],
            title,
            summary=payload.theme.strip(),
            source_script=payload.theme.strip(),
            payload=batch,
        )
    try:
        updated_payload, job_ids = render_batch_items(
            app.state.store,
            owner_user_id=user["id"],
            payload=saved["payload"],
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    saved = app.state.store.update_director_project(saved["id"], payload=updated_payload)
    await _enqueue_job_ids(job_ids)
    app.state.auth_store.audit(
        "create_director_batch", "director", actor_user_id=user["id"], target_id=saved["id"],
        detail=f"count={payload.count}", ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.post(
    "/api/director/batches/{project_id}/render",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="短视频批量：重提交指定条目",
)
async def render_director_batch_items(
    project_id: str,
    payload: DirectorRenderBatchRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_BATCH:
        raise HTTPException(status_code=422, detail="只有批量工程可以按条重提交")
    try:
        updated_payload, job_ids = render_batch_items(
            app.state.store,
            owner_user_id=user["id"],
            payload=record["payload"],
            item_ids=payload.item_ids,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not job_ids:
        raise HTTPException(status_code=409, detail="没有可重提交的条目")
    saved = app.state.store.update_director_project(record["id"], payload=updated_payload)
    await _enqueue_job_ids(job_ids)
    app.state.auth_store.audit(
        "render_director_batch", "director", actor_user_id=user["id"], target_id=project_id,
        detail=f"jobs={len(job_ids)}", ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.post(
    "/api/jobs",
    status_code=202,
    response_model=JobResponse,
    tags=["任务"],
    summary="创建生成任务",
    description="请求成功只表示任务已入队。返回体是入队后的当前任务快照：worker 尚未领取时为 queued，若已开始准备或已提交 ComfyUI 则为 running。轮询 `GET /api/jobs/{job_id}` 直到任务进入终态。",
)
async def create_job(
    user: Annotated[dict, Depends(mutating_user)],
    mode: Annotated[str, Form(description="生成模式；具体能力由 GET /api/modes 返回。")],
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
        workflow_for(mode)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="工作流不存在") from error
    try:
        raw_options = json.loads(options) if options is not None else {}
        if not isinstance(raw_options, dict):
            raise ValueError("生成参数必须为对象。")
        validate_references(mode, references)
        generation_options = normalize_options(mode, raw_options)
        validate_option_relationships(mode, generation_options, len(references))
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if is_image_workflow(mode):
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
    return public_job(store.get(job_id))


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
    mode = existing["mode"]
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
    if is_image_workflow(mode):
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
    return public_job(app.state.store.get(job_id))


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
def list_jobs(user: Annotated[dict, Depends(current_user)], limit: int = 100, user_id: str | None = None) -> list[dict]:
    if user["role"] in {"admin", "super_admin"} and user_id is not None:
        target_user_id = None if user_id == "all" else user_id
    else:
        target_user_id = user["id"]
    return [public_job(job) for job in app.state.store.list_jobs(target_user_id, max(1, min(limit, 200)))]


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
    if not is_h3_workflow(existing["mode"]):
        raise HTTPException(status_code=409, detail="当前工作流不支持重新提交")
    job = app.state.store.retry_terminal(job_id)
    if job is None:
        raise HTTPException(status_code=409, detail="仅已中断、已停止或失败且未在 ComfyUI 执行的任务可以重新提交")
    await app.state.worker.enqueue(job_id)
    return public_job(job)


@app.post(
    "/api/jobs/{job_id}/cancel",
    response_model=JobResponse,
    tags=["任务"],
    summary="停止生成任务",
)
async def cancel_job(job_id: str, user: Annotated[dict, Depends(mutating_user)]) -> dict:
    job_or_404(app.state.store, job_id, user)
    job, prompt_ids = app.state.store.mark_cancelled(job_id)
    if job is None:
        raise HTTPException(status_code=409, detail="仅排队中、生成中或已中断的任务可以停止")
    for prompt_id in prompt_ids:
        await asyncio.to_thread(app.state.worker.comfy.stop_prompt, prompt_id)
    return public_job(app.state.store.get(job_id, include_references=True))


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
    return FileResponse(path, media_type=_image_media_type(path))


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
    return FileResponse(path, media_type=_image_media_type(path))


@app.get("/api/library", response_model=list[LibraryItemResponse], tags=["作品库"], summary="列出作品库媒体")
def library(user: Annotated[dict, Depends(current_user)], user_id: str | None = None) -> list[dict]:
    if user["role"] in {"admin", "super_admin"} and user_id is not None:
        target_user_id = None if user_id == "all" else user_id
    else:
        target_user_id = user["id"]
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
        for job in app.state.store.list_jobs(target_user_id, 500)
        for round_data in job.get("rounds", [])
        for item in round_data.get("generation_items", [])
        if item.get("outputs")
        for output_index, output in enumerate(item["outputs"])
    ]


@app.get(
    "/api/media/{filename}",
    tags=["作品库"],
    summary="下载或预览生成媒体",
    responses={200: {"content": {"image/*": {}, "video/*": {}, "application/octet-stream": {}}}},
)
def media(filename: str, request: Request, user: Annotated[dict, Depends(current_user)]) -> Response:
    target_user_id = None if user["role"] in {"admin", "super_admin"} else user["id"]
    output = next((
        output
        for job in app.state.store.list_jobs(target_user_id, 1000)
        for output in job["outputs"]
        if output["path"] == filename
    ), None)
    if output is None:
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    if output.get("delivery_status") == "local":
        raise HTTPException(status_code=410, detail="资源已经保存到员工电脑，请从本地资源目录查看")
    return output_response(output, request)


@app.get(
    "/api/jobs/{job_id}/outputs/{output_index}/download",
    tags=["资源"], summary="下载待交付资源",
)
def download_output(
    job_id: str,
    output_index: int,
    request: Request,
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
    if output_index < 0 or output_index >= len(job["outputs"]):
        raise HTTPException(status_code=404, detail="资源不存在")
    output = job["outputs"][output_index]
    if output.get("delivery_status") == "local":
        raise HTTPException(status_code=410, detail="资源已经保存到员工电脑并清理服务器暂存")
    return output_response(output, request)


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
    if output_index < 0 or output_index >= len(job["outputs"]):
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
    if output_index < 0 or output_index >= len(job["outputs"]):
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
    if output_index < 0 or output_index >= len(job["outputs"]):
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
    job_id: str, generation_item_id: str, output_index: int, request: Request,
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
    if output_index < 0 or output_index >= len(item["outputs"]):
        raise HTTPException(status_code=404, detail="资源不存在")
    output = item["outputs"][output_index]
    if output.get("delivery_status") == "local":
        raise HTTPException(status_code=410, detail="资源已经保存到员工电脑并清理服务器暂存")
    return output_response(output, request)


@app.get(
    "/api/jobs/{job_id}/generations/{generation_item_id}/outputs/{output_index}/browser-direct",
    response_model=BrowserDirectOutputResponse, tags=["资源"], summary="获取生成项的同机 ComfyUI 输出地址",
)
def browser_direct_generation_output(
    job_id: str, generation_item_id: str, output_index: int,
    user: Annotated[dict, Depends(current_user)],
) -> dict:
    _, item = generation_item_or_404(app.state.store, job_id, generation_item_id, user)
    if output_index < 0 or output_index >= len(item["outputs"]):
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
    if output_index < 0 or output_index >= len(item["outputs"]):
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
    if output_index < 0 or output_index >= len(item["outputs"]):
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
    index = settings.frontend_dist_dir / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="前端未构建")
    return FileResponse(index, headers={"Cache-Control": "no-store, max-age=0, must-revalidate"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=7865, reload=False)
