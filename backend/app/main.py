from __future__ import annotations

import asyncio
import json
import math
import mimetypes
import re
import subprocess
import secrets
import shutil
import time
import wave
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Annotated, Any
from urllib.parse import urlencode, urlsplit

import requests
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Path as ApiPath, Query, Request, Response, Security, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from fastapi.security import APIKeyCookie
from fastapi.openapi.utils import get_openapi

from .api_documentation import enrich_openapi_documentation
from .auth import (
    AuthStore, LastSuperAdminError, RESET_CODE_TTL_MINUTES, SESSION_HOURS, csrf_token,
    mask_email, normalize_email, validate_email,
)
from .cache import EpochCache, TTLCache
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
from .voice_bank import VoiceBankError, ensure_voice_prompt, list_voice_presets
from .director_export import SystemFfmpegRunner
from .director_jobs import (
    render_batch_items, sync_batch_items, sync_recipe_asset_images,
)
from .director_library import (
    DirectorLibraryError,
    delete_library_asset_files,
    find_library_asset_file,
    library_image_url,
    normalize_library_asset_fields,
    normalize_library_kind,
    public_library_asset,
    save_library_asset_image,
)
from .director_recipe import (
    DirectorPayloadError, PAYLOAD_KIND_BATCH,
    PAYLOAD_KIND_RECIPE, PAYLOAD_KIND_REPLICATION,
    empty_batch_payload, normalize_recipe_payload,
    payload_kind,
)
from .director_replication import (
    find_replication_artifact_file,
    find_replication_depth_file, find_replication_source_file, normalize_replication_payload,
    save_replication_source, validate_source_video,
)
from .video_analysis import VideoAnalysisError, probe_video as probe_source_video
from .director_project_service import merge_recipe_creative, merge_recipe_execution, persist_recipe_execution
from .director_operations import DirectorOperationService
from .director_stream import TERMINAL_OPERATION_STATUSES, terminal_event_for_status
from .grs_provider import GrsProviderService
from .llm_client import LlmError, is_upstream_llm_failure
from .llm_provider import LlmProviderService
from .zhipu_catalog import model_provider_presets
from .tts_provider import TtsProviderService
from .mail_provider import MailProviderError, MailProviderService
from .vlm_provider import ANALYSIS_UNAVAILABLE_MESSAGE, VlmProviderService
from .vision_runtime import llm_status_vision_fields
from .models import (
    AuthStatusResponse, BrowserDirectOutputResponse, ChangePasswordRequest, ComfyProviderResponse,
    ComfyProviderTestRequest, ComfyProviderUpdateRequest, CreateUserRequest, HealthResponse, JobResponse,
    DesktopDeliveryTicketResponse, GrsBalanceResponse, GrsBalanceSnapshotResponse, GrsImageModelCreateRequest,
    GrsImageModelsResponse, GrsImageModelsUpdateRequest, GrsProviderResponse, GrsProviderTestRequest, GrsProviderUpdateRequest,
    GrsPlatformModelImportRequest, GrsPlatformModelImportResponse, GrsPlatformModelsResponse,
    LibraryItemResponse, LibraryQueryResponse, LoginRequest, ModeResponse, ModesResponse, ResetPasswordRequest,
    MailProviderResponse, MailProviderTestRequest, MailProviderUpdateRequest,
    PasswordEmailChallengeRequest, PasswordEmailChallengeResponse, PasswordEmailResetRequest,
    SetupAdminRequest, UpscaleJobRequest, JobMode, JobStatus,
    QiniuProviderResponse, QiniuProviderUpdateRequest, StorageCapabilityResponse, UpdateProfileRequest, UpdateUserRequest, UnlockLoginResponse, UserResponse, UserRole,
    JobMetadataUpdateRequest,
    LlmProviderResponse, LlmProviderUpdateRequest, LlmProviderTestRequest, LlmModelCatalogRequest, LlmModelCatalogResponse, LlmStatusResponse,
    ModelProviderPresetsResponse,
    VlmProviderUpdateRequest, VlmProviderTestRequest, VlmModelCatalogRequest, VlmStatusResponse,
    PromptOptimizeRequest, PromptOptimizeResponse, PromptReverseResponse, AnalyzeSubjectResponse, SkillsListResponse, SkillPackListResponse,
    ProviderSecretRevealRequest, ProviderSecretRevealResponse,
    ScriptSplitRequest, ScriptSplitResponse,
    DirectorContinuityRepairRequest,
    DirectorProjectCreateRequest, DirectorProjectUpdateRequest,
    DirectorProjectResponse,
    DirectorArtStyleCatalogResponse,
    DirectorOperationCreateRequest, DirectorOperationResponse,
    DirectorRenderBatchRequest, DirectorBatchCreateRequest,
    DirectorLibraryAssetCreateRequest, DirectorLibraryAssetUpdateRequest, DirectorLibraryAssetResponse,
    TtsProviderResponse, TtsProviderUpdateRequest, TtsProviderTestRequest,
    MusicJobCreateRequest, MusicJobResponse, MusicLyricsResponse,
    MusicProviderResponse, MusicProviderTestRequest, MusicProviderUpdateRequest, MusicVibeRequest,
    CloudVideoProviderResponse, CloudVideoProviderTestRequest, CloudVideoProviderUpdateRequest,
    MusicChatCreateRequest, MusicChatDetailResponse, MusicChatGenerateRequest, MusicChatMessageRequest,
    MusicChatMessageResponse, MusicChatResponse, MusicChatUpdateRequest,
    CanvasProjectCreateRequest, CanvasProjectUpdateRequest, CanvasDraftSaveRequest,
    CanvasLinkedProjectRequest,
    CanvasProjectListItem, CanvasProjectResponse, CanvasDraftSaveResponse, CanvasDraftVersionItem,
)
from .motion_transfer_media import validate_motion_video
from .keep_face_restore_workflow import KEEP_MAX_UPLOAD_BYTES, validate_face_restore_sources
from .scail2_workflow import probe_scail_canvas, resolve_scail_video_options
from .provider_secret import reveal_secret

from .library_query import (
    LIBRARY_DEFAULT_LIMIT,
    LIBRARY_MAX_LIMIT,
    LIBRARY_MAX_OFFSET,
    build_library_entries,
    query_library_entries,
)
from .media_index import MediaOutputIndex
from .canvas_store import (
    CanvasConflictError,
    CanvasNotFoundError,
    CanvasStore,
    CanvasValidationError,
)
from .media_studio.db import ensure_schema
from .media_studio.routers.project_router import register_project_routes
from .media_studio.routers.featured_router import register_featured_work_routes
from .media_studio.routers.featured_music_router import register_featured_music_routes
from .media_studio.routers.showcase_router import register_showcase_routes
from .director_assistant.routes import register_assistant_routes
from .script_diagnosis.routes import register_diagnosis_routes
from .script_diagnosis.service import DiagnosisService
from .director_assistant.service import AssistantService
from .media_studio.services.ai_generation_service import AiGenerationService
from .media_studio.services.asset_extraction_job_service import AssetExtractionJobService
from .media_studio.services.episode_video_service import EpisodeVideoService
from .media_studio.services.h3_prompt_job_service import H3PromptJobService
from .media_studio.services.job_lease import ensure_lease_schema
from .media_studio.services.project_detail_service import ProjectDetailService
from .media_studio.services.project_service import ProjectService
from .media_studio.services.shot_plan_job_service import ShotPlanJobService
from .media_studio.services.tts_generation_job_service import TtsGenerationJobService
from .cloud_video.base import CloudVideoError, cloud_video_provider_keys
from .cloud_video_service import CloudVideoService
from .music_job_service import MusicJobService, MusicServiceError
from .music_chat import MusicChatError, MusicChatNotFoundError, generate_from_proposal, create_chat as create_music_chat_record, send_music_chat_message, stream_music_chat_message
from .music_lyrics import MusicLyricsBusy, music_lyrics_status, start_music_lyrics
from .music_yue2_client import YuE2Error
from .qiniu_provider import QiniuProviderService
from .request_log import RequestLogMiddleware, write_request_log
from .mcp_gateway.routes import register_mcp_routes
from .mcp_gateway.store import McpStore

from .resource_storage import create_resource_storage, resource_object_url
from .storage import DirectorProjectConflictError, FINISHED_STATUSES, JobStore, elapsed_ms_between
from .worker import JobWorker
from .rtx_vsr_workflow import comfy_vram_device_name, comfy_vram_total_bytes, original_video_locator, source_video_shape, vsr_memory_rejection
from .seedvr2_upscale_workflow import (
    UPSCALE_ENGINE_RELAYVSR,
    UPSCALE_ENGINE_RTX,
    UPSCALE_ENGINE_SEEDVR2,
    UPSCALE_ENGINES,
    normalize_upscale_engine,
)
from .relay_vsr_workflow import relay_vsr_memory_rejection
from .workflow_registry import (
    AVATAR_MAX_SCENE_SECONDS, LIPSYNC_SOURCE_MAX_SECONDS, LIPSYNC_SOURCE_MIN_SECONDS, WORKFLOWS,
    comfy_ram_total_bytes, is_cloud_video_workflow, is_composite_image_workflow, is_depth_workflow,
    is_grs_image_workflow, is_lip_sync_workflow, is_local_comfy_job,
    is_motion_ref_video_workflow, is_relayvsr_upscale_workflow, is_seedvr2_upscale_workflow,
    is_upscale_workflow, normalize_options, option_visible, quality_for_megapixels, set_catalog_lookup,
    set_hardware_profile_resolver, validate_option_relationships, validate_references, workflow_for,
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
        raise HTTPException(status_code=502, detail=f"视频服务输出暂时不可读取: {error}") from error

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
        raise HTTPException(status_code=409, detail="Only video service output resources support browser direct delivery")
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


def enforce_login_limit(key: str, *, detail: str = "登录失败次数过多，请 15 分钟后再试") -> None:
    cutoff = time.monotonic() - LOGIN_WINDOW_SECONDS
    with login_failures_lock:
        attempts = [value for value in login_failures.get(key, []) if value > cutoff]
        if attempts:
            login_failures[key] = attempts
        else:
            # Drop empty keys so failed-login bookkeeping cannot grow unbounded.
            login_failures.pop(key, None)
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail=detail)


def record_login_failure(key: str) -> None:
    with login_failures_lock:
        login_failures.setdefault(key, []).append(time.monotonic())


def clear_login_failure_key(key: str) -> None:
    with login_failures_lock:
        login_failures.pop(key, None)


def clear_login_failures_for_identifiers(*identifiers: str) -> int:
    """Clear failed-login counters for every identifier an account can be typed as.

    A blocked account is keyed by ``<client ip>:<typed identifier>``, and the login
    form accepts either the username or the bound email, so both must be cleared.
    """
    suffixes = tuple(
        f":{value.strip().lower()}" for value in identifiers if value and value.strip()
    )
    if not suffixes:
        return 0
    with login_failures_lock:
        keys = [key for key in login_failures if key.endswith(suffixes)]
        for key in keys:
            login_failures.pop(key, None)
    return len(keys)


def clear_login_failures_for_username(username: str) -> int:
    return clear_login_failures_for_identifiers(username)


def login_identifiers(user: dict) -> list[str]:
    return [
        str(value) for value in (user.get("username"), user.get("email")) if value and str(value).strip()
    ]


def login_block_remaining_seconds(user: dict) -> int:
    """Seconds until the account can try again, across every source address."""
    suffixes = tuple(f":{value.strip().lower()}" for value in login_identifiers(user))
    if not suffixes:
        return 0
    now = time.monotonic()
    cutoff = now - LOGIN_WINDOW_SECONDS
    remaining = 0
    with login_failures_lock:
        for key, values in login_failures.items():
            if not key.endswith(suffixes):
                continue
            attempts = sorted(value for value in values if value > cutoff)
            if len(attempts) >= LOGIN_MAX_ATTEMPTS:
                # The block lifts as soon as fewer than LOGIN_MAX_ATTEMPTS remain in the window.
                unlock_at = attempts[len(attempts) - LOGIN_MAX_ATTEMPTS] + LOGIN_WINDOW_SECONDS
                remaining = max(remaining, max(1, math.ceil(unlock_at - now)))
    return remaining


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


def public_reference(mode: str, index: int, url: str, count: int | None = None) -> dict:
    data = {"index": index, "url": url}
    try:
        definition = workflow_for(mode)
    except KeyError:
        return data
    if not (definition.accepts_video_reference or definition.accepts_audio_reference or definition.reference_slots):
        return data
    labels = definition.reference_labels
    return {
        "index": index, "url": url, "kind": definition.reference_kind(index, count),
        "label": labels[index - 1] if index <= len(labels) else f"参考图 {index}",
    }


def public_job(job: dict) -> dict:
    data = dict(job)
    data["request_parameters"] = request_parameters(job)
    data.pop("submitted_options", None)
    data.pop("options_submitted", None)
    attach_elapsed(data)
    data["references"] = [
        public_reference(job["mode"], index, public_api_path(f"jobs/{job['id']}/references/{index}"),
                             int(job.get("reference_count", 0)))
        for index in range(1, int(job.get("reference_count", 0)) + 1)
    ]
    data["outputs"] = []
    for output_index, raw_output in enumerate(job.get("outputs", [])):
        output = dict(raw_output)
        output.pop("_comfy_source", None)
        output.pop("_local_path", None)
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
            public_reference(round_data["mode"], index,
                             public_api_path(f"jobs/{job['id']}/rounds/{round_data['id']}/references/{index}"),
                             int(round_data.get("reference_count", 0)))
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
            # Continuation workflows are server-side only; they can be megabytes.
            public_item.pop("refine_state", None)
            public_outputs: list[dict] = []
            for output_index, raw_output in enumerate(item.get("outputs", [])):
                output = dict(raw_output)
                output.pop("_comfy_source", None)
                output.pop("_local_path", None)
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


_UPSCALE_ACTIVE_STATUSES = {
    JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.INTERRUPTED.value,
}
upscale_capabilities_cache = TTLCache(ttl_seconds=30)


def active_upscale_job_for(store: JobStore, owner_user_id: str | None, source_job_id: str) -> dict | None:
    for job in store.list_jobs(owner_user_id, 200):
        if not is_upscale_workflow(job.get("mode") or ""):
            continue
        source = job.get("source") or {}
        if source.get("job_id") != source_job_id:
            continue
        if job.get("status") in _UPSCALE_ACTIVE_STATUSES:
            return job
    return None


def vsr_job_options_from_source(source_job: dict) -> dict:
    shape = source_video_shape(source_job.get("mode") or "", source_job.get("options") or {})
    if shape is None:
        return {}
    width, height, frames = shape
    return {"width": width, "height": height, "frames": frames}


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
        negative_definition = definitions.get("negative_prompt")
        parameters.append({
            "name": "negative_prompt",
            "label": negative_definition["label"] if negative_definition else "负面提示词",
            "value": job["negative_prompt"],
            "visibility": "primary" if negative_definition else "internal",
        })
    if job.get("image_size"):
        image_size_definition = definitions.get("image_size")
        parameters.append({
            "name": "image_size",
            "label": image_size_definition["label"] if image_size_definition else "图片尺寸",
            "value": job["image_size"],
            "visibility": "primary" if image_size_definition else "internal",
        })
    if job.get("reference_count", 0):
        parameter = {"name": "references", "label": definitions["references"]["label"], "value": job["reference_count"], "visibility": "primary"}
        if definition.accepts_video_reference or definition.accepts_audio_reference:
            parameter["unit"] = "份"
        parameters.append(parameter)

    option_schema = definitions.get("options", {}).get("schema", {})
    option_definitions = option_schema.get("properties", {})
    options = job.get("options") or {}
    visibility_values = {
        name: options.get(name, field_definition.get("default"))
        for name, field_definition in option_definitions.items()
    }
    for name in option_definitions:
        if not option_visible(option_definitions[name], visibility_values):
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


async def save_upload(upload: UploadFile, destination: Path, *, max_bytes: int = MAX_UPLOAD_BYTES) -> None:
    total = 0
    with destination.open("wb") as target:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                target.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"单份参考素材不能超过 {max_bytes // (1024 * 1024)} MB")
            target.write(chunk)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.results_dir.mkdir(exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.staging_dir.mkdir(parents=True, exist_ok=True)
    database = settings.runtime_database()
    auth_store = AuthStore(database)
    store = JobStore(database)
    app.state.mcp_store = McpStore(database)
    qiniu_provider = QiniuProviderService(store, settings.credential_key)
    resource_storage = qiniu_provider.enabled_storage() or create_resource_storage(settings.resource_provider, settings.staging_dir)
    grs_provider = GrsProviderService(store, settings.credential_key)
    set_catalog_lookup(store.get_grs_image_model)
    llm_provider = LlmProviderService(store, settings.credential_key)
    vlm_provider = VlmProviderService(store, settings.credential_key)
    tts_provider = TtsProviderService(store, settings.credential_key)
    mail_provider = MailProviderService(store, settings.credential_key)
    comfy_provider = ComfyProviderService(store, settings.comfy_url)
    comfy = ComfyService(settings, resource_storage, url_resolver=comfy_provider.current_url)
    worker = JobWorker(store, comfy, grs_provider, resource_storage)
    hardware_cache = TTLCache(ttl_seconds=60)

    def resolve_hardware_profile() -> dict | None:
        """ComfyUI 机器配置探测：采样步数与模型体积等内部参数据此自动托管。"""
        def probe() -> dict | None:
            stats = comfy.system_stats()
            if not stats:
                return None
            return {
                "ram_total": comfy_ram_total_bytes(stats),
                "vram_total": comfy_vram_total_bytes(stats),
                "gpu": comfy_vram_device_name(stats),
            }
        try:
            return hardware_cache.get_or_create("comfy-hardware", probe)
        except Exception:
            return None

    set_hardware_profile_resolver(resolve_hardware_profile)
    app.state.auth_store = auth_store
    app.state.store = store
    app.state.library_cache = EpochCache(max_entries=16)
    app.state.media_index = MediaOutputIndex(store)
    app.state.health_cache = TTLCache(ttl_seconds=10)
    app.state.canvas_store = CanvasStore(store)
    app.state.resource_storage = resource_storage
    app.state.grs_provider = grs_provider
    app.state.qiniu_provider = qiniu_provider
    app.state.llm_provider = llm_provider
    app.state.vlm_provider = vlm_provider
    app.state.tts_provider = tts_provider
    app.state.mail_provider = mail_provider
    app.state.comfy_provider = comfy_provider
    MusicJobService.configure(store, settings.credential_key, resource_storage)
    app.state.music_jobs = MusicJobService
    CloudVideoService.configure(store, settings.credential_key, resource_storage)
    app.state.cloud_video = CloudVideoService
    app.state.worker = worker
    director_operations = DirectorOperationService(
        store,
        llm_provider=llm_provider,
        vlm_provider=vlm_provider,
        worker=worker,
        resource_storage=resource_storage,
    )
    app.state.director_operations = director_operations
    app.state.desktop_delivery_tickets = DesktopDeliveryTickets()
    store.interrupt_stale_director_pipelines()
    store.interrupt_stale_director_operations()
    # SQLite test apps own no MySQL media queue. Startup recovery must never
    # claim or interrupt the real workbench's paid jobs during a regression run.
    if database.dialect == "mysql":
        ensure_schema()
        ensure_lease_schema()
        EpisodeVideoService.recover_orphaned_jobs()
        ProjectDetailService.recover_interrupted_image_jobs()
        H3PromptJobService.recover_interrupted_jobs()
        ShotPlanJobService.recover_interrupted_jobs()
        AssetExtractionJobService.recover_interrupted_jobs()
        TtsGenerationJobService.recover_interrupted_jobs()
        MusicJobService.recover_interrupted_jobs()
        AiGenerationService.recover_orphaned_jobs()
    app.state.director_assistant = AssistantService(store, llm_provider, settings.uploads_dir, vlm_provider)
    app.state.director_assistant.recover()
    app.state.script_diagnosis = DiagnosisService(store, llm_provider)
    app.state.script_diagnosis.repo.recover()
    await worker.start()
    async with app.state.mcp_prepare_transport().run():
        yield
    app.state.script_diagnosis.stop()
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
        {"name": "MCP", "description": "账号隔离的 MCP OAuth 授权、客户端连接与有序参考图。"},
        {"name": "画布", "description": "账号隔离的无限画布、JSON 草稿保存与历史版本。"},
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
        {"name": "智能剪辑", "description": "分集剪辑工程、素材导入、三轨时间线与 MP4 / JSON / XML / OTIO / 剪映基础草稿导出。"},
        {"name": "复刻台", "description": "参考片拉片复刻：上传成片，自动分镜反推提示词与深度视频，用 Wan VACE 深度控制批量转绘。"},
        {"name": "导演台2", "description": "AI Media Studio：按项目组织的内容库、资产库、剧集工坊与全部任务（复刻自 dev0914）。"},
        {"name": "灵感示例", "description": "示例库：管理员把真实出片冻结成可复现配方，所有用户浏览并一键回填创作台。"},
        {"name": "音乐", "description": "远端 YuE2 Studio 音乐生成：任务提交、状态轮询与成品曲库。"},
    ],
    lifespan=lifespan,
)

register_project_routes(app, current_user=current_user, mutating_user=mutating_user, session_cookie=SESSION_COOKIE)
register_featured_work_routes(
    app,
    current_user=current_user,
    mutating_admin_user=mutating_admin_user,
    canvas_store=lambda: app.state.canvas_store,
    resource_storage=lambda: getattr(app.state, "resource_storage", None),
)
register_featured_music_routes(
    app,
    current_user=current_user,
    mutating_admin_user=mutating_admin_user,
)
register_showcase_routes(
    app,
    current_user=current_user,
    mutating_admin_user=mutating_admin_user,
)
register_assistant_routes(app, current_user=current_user, mutating_user=mutating_user)
register_diagnosis_routes(app, current_user=current_user, mutating_user=mutating_user)
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
            UserRole.SUPER_ADMIN, must_change_password=False, email=payload.email,
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


@app.post("/api/auth/login", response_model=AuthStatusResponse, tags=["账号"], summary="账号登录（支持账号名或绑定邮箱）")
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
            "login_failed", "session", detail=f"identifier={payload.username.strip().lower()}",
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
    if auth_store.verify_credentials(user["username"], payload.current_password) is None:
        raise HTTPException(status_code=422, detail="当前密码不正确")
    try:
        updated = auth_store.set_password(user["id"], payload.new_password, must_change_password=False)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    token, _ = auth_store.create_session(user["id"])
    set_session_cookie(response, token)
    auth_store.audit("change_password", "user", actor_user_id=user["id"], target_id=user["id"], ip_address=client_ip(request))
    return auth_payload(updated, token)


@app.patch("/api/auth/profile", response_model=AuthStatusResponse, tags=["账号"], summary="修改当前账号姓名与找回邮箱")
def update_profile(
    payload: UpdateProfileRequest, request: Request,
    user: Annotated[dict, Depends(csrf_user)],
) -> dict:
    auth_store: AuthStore = app.state.auth_store
    update_email = payload.email is not None
    normalized_email: str | None = None
    if update_email:
        email_text = (payload.email or "").strip()
        if email_text:
            try:
                normalized_email = validate_email(email_text)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        if normalized_email != (user.get("email") or None):
            if not payload.current_password or auth_store.verify_credentials(
                user["username"], payload.current_password,
            ) is None:
                raise HTTPException(status_code=422, detail="修改找回邮箱需要验证当前密码")
    try:
        updated = auth_store.update_user(
            user["id"], display_name=payload.display_name,
            email=normalized_email, update_email=update_email,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    auth_store.audit(
        "update_profile", "user", actor_user_id=user["id"], target_id=user["id"],
        detail=f"email={'set' if update_email else 'unchanged'}", ip_address=client_ip(request),
    )
    return auth_payload(updated, request.state.session_token)


@app.post(
    "/api/auth/password/email-challenge",
    response_model=PasswordEmailChallengeResponse,
    tags=["账号"],
    summary="忘记密码：向绑定邮箱发送重置验证码",
)
async def password_email_challenge(payload: PasswordEmailChallengeRequest, request: Request) -> dict:
    auth_store: AuthStore = app.state.auth_store
    mail_provider: MailProviderService = app.state.mail_provider
    if auth_store.setup_required():
        raise HTTPException(status_code=409, detail="请先在工作站本机完成管理员初始化")
    available, reason = mail_provider.availability()
    if not available:
        raise HTTPException(status_code=503, detail=reason or "邮件服务尚未配置，请联系管理员重置密码")
    normalized_email = normalize_email(payload.email)
    key = f"mail-send:{rate_limit_key(request, normalized_email)}"
    enforce_login_limit(key, detail="验证码发送过于频繁，请稍后再试")
    masked = mask_email(normalized_email)
    user = auth_store.get_user_by_email(normalized_email)
    if user is None:
        # 不暴露账号是否存在：统一返回已受理，实际不发送邮件。
        record_login_failure(key)
        return {"sent": True, "masked_email": masked, "expires_in_minutes": RESET_CODE_TTL_MINUTES}
    code = f"{secrets.randbelow(1_000_000):06d}"
    auth_store.set_password_reset_code(user["id"], code)
    try:
        await asyncio.to_thread(
            mail_provider.send_password_reset,
            to=str(user.get("email") or normalized_email),
            code=code,
            display_name=user.get("display_name"),
            ttl_minutes=RESET_CODE_TTL_MINUTES,
        )
    except MailProviderError as error:
        record_login_failure(key)
        auth_store.clear_password_reset_code(user["id"])
        auth_store.audit(
            "password_reset_email_failed", "user", target_id=user["id"],
            detail=str(error)[:200], ip_address=client_ip(request),
        )
        raise HTTPException(status_code=502, detail="验证码邮件发送失败，请稍后重试或联系管理员") from error
    auth_store.audit(
        "password_reset_email_sent", "user", target_id=user["id"], ip_address=client_ip(request),
    )
    return {"sent": True, "masked_email": masked, "expires_in_minutes": RESET_CODE_TTL_MINUTES}


@app.post(
    "/api/auth/password/email-reset",
    response_model=AuthStatusResponse,
    tags=["账号"],
    summary="忘记密码：校验邮箱验证码并重置密码",
)
def password_email_reset(
    payload: PasswordEmailResetRequest, request: Request, response: Response,
) -> dict:
    auth_store: AuthStore = app.state.auth_store
    normalized_email = normalize_email(payload.email)
    key = f"mail-verify:{rate_limit_key(request, normalized_email)}"
    enforce_login_limit(key, detail="验证码错误次数过多，请重新获取验证码")
    user = auth_store.get_user_by_email(normalized_email)
    if user is None or not auth_store.consume_password_reset_code(user["id"], payload.code.strip()):
        record_login_failure(key)
        auth_store.audit(
            "password_reset_failed", "session", detail=f"email={normalized_email}",
            ip_address=client_ip(request),
        )
        raise HTTPException(status_code=400, detail="验证码不正确或已过期")
    try:
        updated = auth_store.set_password(user["id"], payload.new_password, must_change_password=False)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    clear_login_failure_key(key)
    token, _ = auth_store.create_session(updated["id"])
    set_session_cookie(response, token)
    auth_store.audit(
        "password_reset", "user", actor_user_id=updated["id"], target_id=updated["id"],
        detail="via email code", ip_address=client_ip(request),
    )
    return auth_payload(updated, token)


@app.get("/api/admin/users", response_model=list[UserResponse], tags=["管理后台"], summary="列出员工账号")
def list_users(_: Annotated[dict, Depends(admin_user)]) -> list[dict]:
    users = app.state.auth_store.list_users()
    for user in users:
        blocked_seconds = login_block_remaining_seconds(user)
        user["login_blocked"] = blocked_seconds > 0
        user["login_blocked_seconds"] = blocked_seconds
    return users


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
            payload.username, payload.display_name, payload.password, payload.role,
            must_change_password=True, email=payload.email,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "create_user", "user", actor_user_id=actor["id"], target_id=user["id"],
        detail=f"role={user['role']}", ip_address=client_ip(request),
    )
    return user


@app.patch("/api/admin/users/{user_id}", response_model=UserResponse, tags=["管理后台"], summary="更新员工姓名、角色或状态")
def update_user(
    user_id: str, payload: UpdateUserRequest, request: Request,
    actor: Annotated[dict, Depends(mutating_admin_user)],
) -> dict:
    try:
        target = app.state.auth_store.get_user(user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="账号不存在") from error
    if (
        actor["role"] == UserRole.ADMIN.value
        and target["role"] != UserRole.EMPLOYEE.value
        and (payload.role is not None or payload.is_active is not None or payload.email is not None)
    ):
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
    update_email = payload.email is not None
    normalized_email: str | None = None
    if update_email and (payload.email or "").strip():
        try:
            normalized_email = validate_email(payload.email or "")
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        updated = app.state.auth_store.update_user(
            user_id, display_name=payload.display_name, role=payload.role, is_active=payload.is_active,
            email=normalized_email, update_email=update_email,
        )
    except LastSuperAdminError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail="账号不存在") from error
    app.state.auth_store.audit(
        "update_user", "user", actor_user_id=actor["id"], target_id=user_id,
        detail=f"display_name={updated['display_name']},role={updated['role']},active={updated['is_active']}",
        ip_address=client_ip(request),
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


@app.post(
    "/api/admin/users/{user_id}/unlock-login", response_model=UnlockLoginResponse,
    tags=["管理后台"], summary="解除员工登录失败锁定",
)
def unlock_user_login(
    user_id: str, request: Request, actor: Annotated[dict, Depends(mutating_admin_user)],
) -> dict:
    """Clear the 15-minute failed-login block without touching the password.

    Only administrators may clear it: the block exists to slow down password guessing,
    so letting the blocked client lift it would defeat the purpose.
    """
    try:
        target = app.state.auth_store.get_user(user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="账号不存在") from error
    if actor["role"] == UserRole.ADMIN.value and target["role"] != UserRole.EMPLOYEE.value:
        raise HTTPException(status_code=403, detail="管理员只能管理员工账号")
    cleared = clear_login_failures_for_identifiers(*login_identifiers(target))
    app.state.auth_store.audit(
        "unlock_login", "user", actor_user_id=actor["id"], target_id=user_id,
        detail=f"cleared_login_blocks={cleared}", ip_address=client_ip(request),
    )
    return {
        "ok": True,
        "cleared": cleared,
        "username": target["username"],
        "login_blocked_seconds": login_block_remaining_seconds(target),
    }


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
    comfy_url = url_resolver() if url_resolver is not None else settings.comfy_url
    comfy_status = app.state.health_cache.get_or_create(
        comfy_url,
        lambda: ComfyService(settings, url_resolver=url_resolver).health(),
    )
    return {
        "webui": "ok",
        "comfy": comfy_status,
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
    if is_grs_image_workflow(definition.id):
        available, reason = app.state.grs_provider.availability(definition.id)
        payload["available"] = available
        payload["unavailable_reason"] = reason
    elif is_cloud_video_workflow(definition.id):
        available, reason = False, "云端视频服务尚未初始化。"
        if definition.cloud_provider and hasattr(app.state, "cloud_video"):
            try:
                available, reason = CloudVideoService.instance().availability(definition.cloud_provider)
            except CloudVideoError as error:
                available, reason = False, str(error)
        payload["available"] = available
        payload["unavailable_reason"] = reason
    return payload


def listed_workflows():
    image_workflows = []
    if hasattr(app.state, "grs_provider"):
        image_workflows = app.state.grs_provider.enabled_image_workflows()
    visible = [item for item in WORKFLOWS if not item.hidden_from_catalog]
    return [*image_workflows, *visible]


@app.get("/api/modes", response_model=ModesResponse, tags=["工作流"], summary="获取工作流注册表")
def modes(user: Annotated[dict | None, Depends(optional_current_user)]) -> dict:
    # Guests can compose locally; generation and every private resource keep
    # their existing current_user / mutating_user dependencies.
    payload = mode_payload if user else lambda item: item.public_payload()
    return {"modes": [payload(item) for item in listed_workflows()], "image_sizes": [], "presets": PRESETS}


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


@app.post("/api/admin/providers/grs/models/fetch", response_model=GrsPlatformModelsResponse, tags=["管理后台"], summary="动态拉取 GRS 平台在售生图模型")
async def fetch_grs_platform_models(
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: GrsProviderTestRequest | None = None,
) -> dict:
    try:
        arguments = {} if payload is None else {"base_url": payload.base_url, "api_key": payload.api_key}
        result = await asyncio.to_thread(app.state.grs_provider.fetch_platform_models, **arguments)
    except Exception as error:
        app.state.auth_store.audit(
            "fetch_grs_platform_models_failed", "provider", actor_user_id=user["id"], target_id="grs",
            detail=type(error).__name__, ip_address=client_ip(request),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "fetch_grs_platform_models", "provider", actor_user_id=user["id"], target_id="grs",
        detail=f"image={len(result['models'])} total={result['total']}", ip_address=client_ip(request),
    )
    return result


@app.post("/api/admin/providers/grs/models/import", response_model=GrsPlatformModelImportResponse, tags=["管理后台"], summary="把 GRS 平台模型导入生图目录")
async def import_grs_platform_models(
    payload: GrsPlatformModelImportRequest, request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        result = await asyncio.to_thread(
            app.state.grs_provider.import_platform_models,
            [item.model_dump() for item in payload.models],
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    app.state.auth_store.audit(
        "import_grs_platform_models", "provider", actor_user_id=user["id"], target_id="grs",
        detail=f"created={len(result['created'])} skipped={len(result['skipped'])}", ip_address=client_ip(request),
    )
    return result


@app.get("/api/admin/providers/model-presets", response_model=ModelProviderPresetsResponse, tags=["管理后台"], summary="获取文本与视觉模型官方服务预设及费用标记")
def get_model_provider_presets(_: Annotated[dict, Depends(super_admin_user)]) -> dict:
    return model_provider_presets()


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


@app.get("/api/admin/providers/vlm", response_model=LlmProviderResponse, tags=["管理后台"], summary="获取 VLM 视觉模型配置")
def get_vlm_provider(_: Annotated[dict, Depends(super_admin_user)]) -> dict:
    return app.state.vlm_provider.public_config()


@app.put("/api/admin/providers/vlm", response_model=LlmProviderResponse, tags=["管理后台"], summary="更新 VLM 视觉模型配置")
def update_vlm_provider(
    payload: VlmProviderUpdateRequest, request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        result = app.state.vlm_provider.update(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "update_vlm_provider", "provider", actor_user_id=user["id"], target_id="vlm",
        detail=f"model={payload.model}", ip_address=client_ip(request),
    )
    return result


@app.post("/api/admin/providers/vlm/test", response_model=LlmProviderResponse, tags=["管理后台"], summary="测试 VLM 视觉模型连接")
async def test_vlm_provider(
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: VlmProviderTestRequest | None = None,
) -> dict:
    try:
        arguments = None if payload is None else payload.model_dump()
        result = await asyncio.to_thread(app.state.vlm_provider.test, arguments)
    except Exception as error:
        app.state.auth_store.audit(
            "test_vlm_provider_failed", "provider", actor_user_id=user["id"], target_id="vlm",
            detail=type(error).__name__, ip_address=client_ip(request),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "test_vlm_provider", "provider", actor_user_id=user["id"], target_id="vlm",
        detail="success", ip_address=client_ip(request),
    )
    return result


@app.post("/api/admin/providers/vlm/models", response_model=LlmModelCatalogResponse, tags=["管理后台"], summary="拉取上游 VLM 视觉模型目录")
async def list_vlm_models(
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: VlmModelCatalogRequest | None = None,
) -> dict:
    try:
        arguments = None if payload is None else payload.model_dump()
        result = await asyncio.to_thread(app.state.vlm_provider.list_catalog, arguments)
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "list_vlm_models", "provider", actor_user_id=user["id"], target_id="vlm",
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


# ------------------------------ 邮件服务（SMTP 找回密码） ------------------------------


@app.get("/api/admin/providers/mail", response_model=MailProviderResponse, tags=["管理后台"], summary="获取邮件服务配置")
def get_mail_provider(_: Annotated[dict, Depends(super_admin_user)]) -> dict:
    return app.state.mail_provider.public_config()


@app.put("/api/admin/providers/mail", response_model=MailProviderResponse, tags=["管理后台"], summary="更新邮件服务配置")
def update_mail_provider(
    payload: MailProviderUpdateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        result = app.state.mail_provider.update(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "update_mail_provider", "provider", actor_user_id=user["id"], target_id="mail",
        ip_address=client_ip(request),
    )
    return result


@app.post("/api/admin/providers/mail/test", response_model=MailProviderResponse, tags=["管理后台"], summary="测试邮件服务连接")
async def test_mail_provider(
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: MailProviderTestRequest | None = None,
) -> dict:
    arguments = None if payload is None else payload.model_dump(exclude_none=True)
    try:
        result = await asyncio.to_thread(app.state.mail_provider.test, arguments)
    except Exception as error:
        app.state.auth_store.audit(
            "test_mail_provider_failed", "provider", actor_user_id=user["id"], target_id="mail",
            detail=str(error)[:200], ip_address=client_ip(request),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "test_mail_provider", "provider", actor_user_id=user["id"], target_id="mail",
        ip_address=client_ip(request),
    )
    return result


# ------------------------------ 音乐生成（远端 YuE2 Studio） ------------------------------


def _music_job_response(record: dict) -> dict:
    return MusicJobResponse(**record).model_dump()


def _music_scope_owner_id(user: dict, user_id: str | None) -> str | None:
    """音乐任务/对话列表的归属作用域。

    管理员可传 `user_id`（具体账号 id 或 `all`）查看其他用户数据；普通账号始终只看本人。
    """
    if user["role"] in {"admin", "super_admin"} and user_id is not None:
        return None if user_id == "all" else user_id
    return user["id"]


def _music_read_owner_id(user: dict) -> str | None:
    """单项读取（任务详情、歌词、对话详情）的归属过滤：管理员可只读访问任意账号，普通账号仅限本人。"""
    return None if user["role"] in {"admin", "super_admin"} else user["id"]


def _music_retry_owner_id(user: dict) -> str | None:
    """重试的归属过滤：管理员可跨账号重试失败任务，普通账号仅限本人。"""
    return None if user["role"] in {"admin", "super_admin"} else user["id"]


@app.get("/api/admin/providers/music", response_model=MusicProviderResponse, tags=["管理后台"], summary="获取音乐生成服务配置")
def get_music_provider(_: Annotated[dict, Depends(super_admin_user)]) -> dict:
    return app.state.music_jobs.public_config()


@app.put("/api/admin/providers/music", response_model=MusicProviderResponse, tags=["管理后台"], summary="更新音乐生成服务配置")
def update_music_provider(
    payload: MusicProviderUpdateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        result = app.state.music_jobs.update_provider(payload.base_url, payload.access_key)
    except (MusicServiceError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "update_music_provider", "provider", actor_user_id=user["id"], target_id="music",
        ip_address=client_ip(request),
    )
    return result


@app.post("/api/admin/providers/music/test", response_model=MusicProviderResponse, tags=["管理后台"], summary="测试音乐生成服务连接")
async def test_music_provider(
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: MusicProviderTestRequest | None = None,
) -> dict:
    arguments = payload or MusicProviderTestRequest()
    try:
        result = await asyncio.to_thread(app.state.music_jobs.test, arguments.base_url, arguments.access_key)
    except Exception as error:
        app.state.auth_store.audit(
            "test_music_provider_failed", "provider", actor_user_id=user["id"], target_id="music",
            detail=str(error)[:200], ip_address=client_ip(request),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "test_music_provider", "provider", actor_user_id=user["id"], target_id="music",
        ip_address=client_ip(request),
    )
    return result


@app.get("/api/music/status", tags=["音乐"], summary="音乐生成服务状态（供音乐页提示条）")
def music_status(user: Annotated[dict, Depends(current_user)]) -> dict:
    config = app.state.music_jobs.public_config()
    return {"configured": config["configured"], "base_url": config["base_url"], "credential_ready": config["credential_ready"]}


@app.get(
    "/api/admin/providers/cloud-video",
    response_model=list[CloudVideoProviderResponse],
    tags=["管理后台"],
    summary="获取云端视频供应商配置列表（可灵/方舟/海螺）",
)
def get_cloud_video_providers(_: Annotated[dict, Depends(super_admin_user)]) -> list[dict]:
    return CloudVideoService.instance().public_configs()


@app.put(
    "/api/admin/providers/cloud-video/{provider_key}",
    response_model=CloudVideoProviderResponse,
    tags=["管理后台"],
    summary="更新云端视频供应商配置",
)
def update_cloud_video_provider(
    provider_key: Annotated[str, ApiPath(description="云端视频供应商标识（kling / jimeng / hailuo）")],
    payload: CloudVideoProviderUpdateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    if provider_key not in cloud_video_provider_keys():
        raise HTTPException(status_code=404, detail="云端视频供应商不存在")
    try:
        result = CloudVideoService.instance().update_provider(provider_key, payload.model_dump(exclude_unset=True))
    except (CloudVideoError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "update_cloud_video_provider", "provider", actor_user_id=user["id"],
        target_id=f"cloud-video:{provider_key}", ip_address=client_ip(request),
    )
    return result


@app.post(
    "/api/admin/providers/cloud-video/{provider_key}/test",
    response_model=CloudVideoProviderResponse,
    tags=["管理后台"],
    summary="测试云端视频供应商连接",
)
async def test_cloud_video_provider(
    provider_key: Annotated[str, ApiPath(description="云端视频供应商标识（kling / jimeng / hailuo）")],
    request: Request,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
    payload: CloudVideoProviderTestRequest | None = None,
) -> dict:
    arguments = payload or CloudVideoProviderTestRequest()
    if provider_key not in cloud_video_provider_keys():
        raise HTTPException(status_code=404, detail="云端视频供应商不存在")
    try:
        result = await asyncio.to_thread(
            CloudVideoService.instance().test_provider, provider_key,
            base_url=arguments.base_url, api_key=arguments.api_key, api_secret=arguments.api_secret,
        )
    except Exception as error:
        app.state.auth_store.audit(
            "test_cloud_video_provider_failed", "provider", actor_user_id=user["id"],
            target_id=f"cloud-video:{provider_key}", detail=str(error)[:200], ip_address=client_ip(request),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.auth_store.audit(
        "test_cloud_video_provider", "provider", actor_user_id=user["id"],
        target_id=f"cloud-video:{provider_key}", ip_address=client_ip(request),
    )
    return result


@app.get("/api/music/config", tags=["音乐"], summary="音乐创建表单的远端能力快照（LoRA 适配器）")
async def music_config(user: Annotated[dict, Depends(current_user)]) -> dict:
    return await asyncio.to_thread(app.state.music_jobs.remote_config)


@app.get("/api/music/jobs", response_model=list[MusicJobResponse], tags=["音乐"], summary="音乐任务列表（管理员可查全部用户）")
def list_music_jobs(
    user: Annotated[dict, Depends(current_user)],
    limit: int = Query(default=100, ge=1, le=200),
    user_id: str | None = Query(default=None, description="管理员查看指定账号（或 all）的音乐任务"),
) -> list[dict]:
    rows = app.state.store.list_music_jobs(_music_scope_owner_id(user, user_id), limit=limit)
    return [_music_job_response(row) for row in rows]


@app.post("/api/music/jobs", response_model=MusicJobResponse, tags=["音乐"], summary="提交音乐生成任务")
async def create_music_job(
    payload: MusicJobCreateRequest,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        record = await asyncio.to_thread(
            app.state.music_jobs.enqueue,
            user["id"],
            title=payload.title,
            style=payload.style,
            lyrics=payload.lyrics,
            duration_seconds=payload.duration_seconds,
            output_format=payload.output_format,
            steps=payload.steps,
            seed=payload.seed,
            lm_seed=payload.lm_seed,
            cot=payload.cot,
            adapters=[item.model_dump() for item in (payload.adapters or [])] or None,
        )
    except MusicServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except YuE2Error as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return _music_job_response(record)


@app.post("/api/music/vibe", response_model=MusicJobResponse, tags=["音乐"], summary="一句话描述生成音乐（大模型扩写风格与歌词后提交）")
async def create_music_from_vibe(
    payload: MusicVibeRequest,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        record = await asyncio.to_thread(
            app.state.music_jobs.create_from_vibe,
            user["id"],
            description=payload.description,
            duration_seconds=payload.duration_seconds,
            instrumental=payload.instrumental,
            llm_provider=app.state.llm_provider,
        )
    except MusicServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except LlmError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except YuE2Error as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return _music_job_response(record)


@app.post("/api/music/jobs/{job_id}/retry", response_model=MusicJobResponse, tags=["音乐"], summary="重试失败的音乐任务（优先复用远端已生成的歌曲）")
async def retry_music_job(job_id: Annotated[str, ApiPath(description="音乐任务 ID")], user: Annotated[dict, Depends(mutating_user)]) -> dict:
    owner_scope = _music_retry_owner_id(user)
    record = app.state.store.get_music_job(job_id, owner_user_id=owner_scope)
    if not record:
        raise HTTPException(status_code=404, detail="音乐任务不存在")
    try:
        record = await asyncio.to_thread(app.state.music_jobs.retry_job, job_id, owner_scope)
    except MusicServiceError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _music_job_response(record)


def _music_chat_message_response(record: dict) -> dict:
    return MusicChatMessageResponse(**record).model_dump()


def _music_chat_response(record: dict) -> dict:
    return MusicChatResponse(**record).model_dump()


@app.post("/api/music/chats", response_model=MusicChatResponse, tags=["音乐"], summary="新建音乐对话（可锚定已有歌曲迭代）")
async def create_music_chat(
    payload: MusicChatCreateRequest,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        record = await asyncio.to_thread(
            create_music_chat_record, app.state.store, user["id"], anchor_job_id=payload.anchor_job_id,
        )
    except MusicChatNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _music_chat_response(record)


@app.get("/api/music/chats", response_model=list[MusicChatResponse], tags=["音乐"], summary="音乐对话列表（管理员可查全部用户）")
def list_music_chats(
    user: Annotated[dict, Depends(current_user)],
    user_id: str | None = Query(default=None, description="管理员查看指定账号（或 all）的音乐对话"),
) -> dict:
    rows = app.state.store.list_music_chats(_music_scope_owner_id(user, user_id))
    return [_music_chat_response(row) for row in rows]


@app.patch("/api/music/chats/{chat_id}", response_model=MusicChatResponse, tags=["音乐"], summary="重命名音乐对话")
async def rename_music_chat(
    chat_id: Annotated[str, ApiPath(description="音乐对话 ID")],
    payload: MusicChatUpdateRequest,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    chat = app.state.store.get_music_chat(chat_id, owner_user_id=user["id"])
    if not chat:
        raise HTTPException(status_code=404, detail="对话不存在")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="对话名称不能为空")
    record = await asyncio.to_thread(app.state.store.update_music_chat, chat_id, title=title)
    return _music_chat_response(record or chat)


@app.get("/api/music/chats/{chat_id}", response_model=MusicChatDetailResponse, tags=["音乐"], summary="音乐对话详情（消息 + 锚点歌曲摘要；管理员可只读查看）")
def get_music_chat_detail(
    chat_id: Annotated[str, ApiPath(description="音乐对话 ID")],
    user: Annotated[dict, Depends(current_user)],
) -> dict:
    read_owner = _music_read_owner_id(user)
    chat = app.state.store.get_music_chat(chat_id, owner_user_id=read_owner)
    if not chat:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = [_music_chat_message_response(row) for row in app.state.store.list_music_chat_messages(chat_id)]
    anchor_job_id = str(chat.get("anchor_job_id") or "")
    anchor = app.state.store.get_music_job(anchor_job_id, owner_user_id=read_owner) if anchor_job_id else None
    return MusicChatDetailResponse(
        **_music_chat_response(chat),
        messages=messages,
        anchor_job=_music_job_response(anchor) if anchor else None,
    ).model_dump()


@app.post("/api/music/chats/{chat_id}/messages", response_model=MusicChatDetailResponse, tags=["音乐"], summary="音乐对话发消息（返回本轮助手提案）")
async def send_music_chat_message_endpoint(
    chat_id: Annotated[str, ApiPath(description="音乐对话 ID")],
    payload: MusicChatMessageRequest,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    chat = app.state.store.get_music_chat(chat_id, owner_user_id=user["id"])
    if not chat:
        raise HTTPException(status_code=404, detail="对话不存在")
    try:
        result = await asyncio.to_thread(
            send_music_chat_message, app.state.store, chat_id, user["id"], payload.content, app.state.llm_provider,
            duration_seconds=payload.duration_seconds, instrumental=payload.instrumental,
        )
    except MusicChatNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except MusicChatError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except LlmError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    chat = app.state.store.get_music_chat(chat_id, owner_user_id=user["id"]) or result["chat"]
    anchor_job_id = str(chat.get("anchor_job_id") or "")
    anchor = app.state.store.get_music_job(anchor_job_id, owner_user_id=user["id"]) if anchor_job_id else None
    return MusicChatDetailResponse(
        **_music_chat_response(chat),
        messages=[
            _music_chat_message_response(result["user_message"]),
            _music_chat_message_response(result["assistant_message"]),
        ],
        anchor_job=_music_job_response(anchor) if anchor else None,
    ).model_dump()


@app.post("/api/music/chats/{chat_id}/messages/stream", tags=["音乐"], summary="音乐对话发消息（SSE 流式：user_message/delta/done/error）")
async def stream_music_chat_message_endpoint(
    chat_id: Annotated[str, ApiPath(description="音乐对话 ID")],
    payload: MusicChatMessageRequest,
    user: Annotated[dict, Depends(mutating_user)],
) -> StreamingResponse:
    chat = app.state.store.get_music_chat(chat_id, owner_user_id=user["id"])
    if not chat:
        raise HTTPException(status_code=404, detail="对话不存在")
    generator = stream_music_chat_message(
        app.state.store, chat_id, user["id"], payload.content, app.state.llm_provider,
        duration_seconds=payload.duration_seconds, instrumental=payload.instrumental,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/music/chats/{chat_id}/generate", response_model=MusicJobResponse, tags=["音乐"], summary="把对话提案入队生成（幂等）")
async def generate_music_chat_proposal(
    chat_id: Annotated[str, ApiPath(description="音乐对话 ID")],
    payload: MusicChatGenerateRequest,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        record = await asyncio.to_thread(
            generate_from_proposal, app.state.store, chat_id, user["id"], payload.message_id,
        )
    except MusicChatNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except MusicChatError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MusicServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except YuE2Error as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return _music_job_response(record)


@app.delete("/api/music/chats/{chat_id}", tags=["音乐"], summary="删除音乐对话")
async def delete_music_chat(
    chat_id: Annotated[str, ApiPath(description="音乐对话 ID")],
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    chat = app.state.store.get_music_chat(chat_id, owner_user_id=user["id"])
    if not chat:
        raise HTTPException(status_code=404, detail="对话不存在")
    await asyncio.to_thread(app.state.store.delete_music_chat, chat_id, user["id"])
    return {"ok": True}


@app.get("/api/music/jobs/{job_id}", response_model=MusicJobResponse, tags=["音乐"], summary="音乐任务详情（管理员可只读查看）")
def get_music_job(job_id: Annotated[str, ApiPath(description="音乐任务 ID")], user: Annotated[dict, Depends(current_user)]) -> dict:
    record = app.state.store.get_music_job(job_id, owner_user_id=_music_read_owner_id(user))
    if not record:
        raise HTTPException(status_code=404, detail="音乐任务不存在")
    return _music_job_response(record)


@app.get("/api/music/jobs/{job_id}/lyrics", response_model=MusicLyricsResponse, tags=["音乐"], summary="获取歌曲歌词时间轴（管理员可只读查看）")
def get_music_lyrics(job_id: Annotated[str, ApiPath(description="音乐任务 ID")], user: Annotated[dict, Depends(current_user)]) -> MusicLyricsResponse:
    if not app.state.store.get_music_job(job_id, owner_user_id=_music_read_owner_id(user)):
        raise HTTPException(status_code=404, detail="音乐任务不存在")
    return music_lyrics_status(app.state.store, job_id)


@app.post("/api/music/jobs/{job_id}/lyrics", response_model=MusicLyricsResponse, tags=["音乐"], summary="对齐歌曲歌词")
def align_music_lyrics(job_id: Annotated[str, ApiPath(description="音乐任务 ID")], user: Annotated[dict, Depends(mutating_user)]) -> MusicLyricsResponse:
    record = app.state.store.get_music_job(job_id, owner_user_id=user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="音乐任务不存在")
    if record["status"] != "succeeded" or not record["result_url"]:
        raise HTTPException(status_code=409, detail="歌曲生成完成后可对齐歌词")
    try:
        return start_music_lyrics(app.state.store, record)
    except MusicLyricsBusy as error:
        raise HTTPException(status_code=429, detail=str(error)) from error


@app.delete("/api/music/jobs/{job_id}", tags=["音乐"], summary="删除音乐任务记录")
async def delete_music_job(
    job_id: Annotated[str, ApiPath(description="音乐任务 ID")],
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = app.state.store.get_music_job(job_id, owner_user_id=user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="音乐任务不存在")
    if record.get("status") in ("queued", "running"):
        raise HTTPException(status_code=409, detail="任务进行中，暂不能删除")
    await asyncio.to_thread(app.state.store.delete_music_job, job_id, user["id"])
    return {"ok": True}


@app.post(
    "/api/admin/providers/secret",
    response_model=ProviderSecretRevealResponse,
    tags=["管理后台"],
    summary="取回已保存的明文凭据（界面「复制 Key」）",
)
def admin_reveal_provider_secret(
    payload: ProviderSecretRevealRequest,
    request: Request,
    response: Response,
    user: Annotated[dict, Depends(mutating_super_admin_user)],
) -> dict:
    try:
        value = reveal_secret(app.state, payload.provider, payload.field)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    response.headers["Cache-Control"] = "no-store"
    app.state.auth_store.audit(
        "reveal_provider_secret", "provider", actor_user_id=user["id"],
        target_id=f"{payload.provider}.{payload.field}",
        detail="revealed" if value else "empty", ip_address=client_ip(request),
    )
    return {"provider": payload.provider, "field": payload.field, "value": value}


@app.get("/api/llm/skills", response_model=SkillsListResponse, tags=["大模型"], summary="获取 MiniMax H3 官方提示词技能列表")
def get_llm_skills(_: Annotated[dict, Depends(current_user)]) -> dict:
    from .llm_minimax_skills import list_h3_skills_payload
    return {"skills": list_h3_skills_payload()}


@app.get("/api/skill-packs", response_model=SkillPackListResponse, tags=["导演台"], summary="列出导演台技能包配方")
def get_skill_packs(_: Annotated[dict, Depends(current_user)]) -> dict:
    from .skill_packs import list_pack_catalog

    return {"packs": list_pack_catalog()}


@app.get("/api/llm/status", response_model=LlmStatusResponse, tags=["大模型"], summary="查询大模型服务可用状态")
def get_llm_status(_: Annotated[dict, Depends(current_user)]) -> dict:
    available, reason = app.state.llm_provider.availability()
    config = app.state.llm_provider.public_config()
    vlm = getattr(app.state, "vlm_provider", None)
    vlm_available = False
    vlm_model = None
    if vlm is not None:
        vlm_available, _vlm_reason = vlm.availability()
        vlm_config = vlm.public_config()
        vlm_model = vlm_config.get("model")
    vision = llm_status_vision_fields(
        llm_available=available,
        llm_model=config.get("model"),
        vlm_available=vlm_available,
        vlm_model=vlm_model,
    )
    return {
        "available": available,
        "message": reason,
        "model": config.get("model"),
        **vision,
    }


@app.get("/api/vlm/status", response_model=VlmStatusResponse, tags=["大模型"], summary="查询视觉模型服务可用状态")
def get_vlm_status(_: Annotated[dict, Depends(current_user)]) -> dict:
    vlm = getattr(app.state, "vlm_provider", None)
    if vlm is None:
        return {"available": False, "message": "视觉模型尚未启用。请在管理设置 → VLM 视觉模型 中配置后再使用看图功能。", "model": None}
    available, reason = vlm.availability()
    config = vlm.public_config()
    return {
        "available": available,
        "message": reason,
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

    pack_id = str(payload.skill_pack_id or "").strip() or None
    if pack_id:
        from .skill_packs import UnknownSkillPackError, validate_skill_pack_id

        try:
            validate_skill_pack_id(pack_id)
        except UnknownSkillPackError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        optimized = await asyncio.to_thread(
            app.state.llm_provider.optimize_prompt,
            payload.prompt,
            media_type=payload.media_type,
            workflow_name=payload.workflow_name,
            skill_id=payload.skill_id,
            skill_pack_id=pack_id,
            reference_count=payload.reference_count or 0,
            workflow_id=payload.workflow_id,
            image_urls=payload.image_urls,
            duration_seconds=payload.duration_seconds,
        )
    except (LlmError, requests.exceptions.RequestException) as error:
        raise_as_llm_http(error)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"提示词优化异常：{error}") from error


    app.state.auth_store.audit(
        "optimize_prompt", "llm", actor_user_id=user["id"], target_id="prompt",
        detail=f"media_type={payload.media_type}; skill_id={payload.skill_id or 'default'}; skill_pack_id={pack_id or 'default'}; refs={payload.reference_count or 0}",
        ip_address=client_ip(request),
    )
    return {
        "original_prompt": payload.prompt,
        "optimized_prompt": optimized["optimized_prompt"],
        "optimized_prompt_zh": optimized["optimized_prompt_zh"],
        "skill_id": payload.skill_id,
        "skill_pack_id": pack_id,
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
    if app.state.vlm_provider.vision_model_name() is None:
        raise HTTPException(status_code=503, detail=ANALYSIS_UNAVAILABLE_MESSAGE)
    content = await image.read()
    if not content:
        raise HTTPException(status_code=422, detail="请上传主体参考图后再提取外貌")
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="参考图超过 8MB，请压缩后再试")
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="主体分析仅接受图片文件")

    try:
        description = await asyncio.to_thread(
            app.state.vlm_provider.analyze_subject,
            image_data_url=_image_upload_to_data_url(image, content),
            kind=kind,
            name=name,
        )
    except (LlmError, requests.exceptions.RequestException) as error:
        raise_as_llm_http(error)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"主体特征提取异常：{error}") from error

    app.state.auth_store.audit(
        "analyze_subject", "vlm", actor_user_id=user["id"], target_id="director",
        detail=f"kind={kind}; name={name}",
        ip_address=client_ip(request),
    )
    return {"description": description, "kind": kind, "name": name}


@app.post("/api/llm/reverse-prompt", response_model=PromptReverseResponse, tags=["大模型"], summary="根据参考图反推生成提示词")
async def reverse_prompt_endpoint(
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
    image: Annotated[UploadFile, File(description="待反推的参考图")],
    media_type: Annotated[str, Form()] = "video",
    hint: Annotated[str, Form(max_length=200)] = "",
) -> dict:
    if app.state.vlm_provider.vision_model_name() is None:
        raise HTTPException(status_code=503, detail=ANALYSIS_UNAVAILABLE_MESSAGE)
    media_key = str(media_type or "video").strip().lower()
    if media_key not in {"video", "image"}:
        raise HTTPException(status_code=422, detail="media_type 仅支持 video 或 image")
    content = await image.read()
    if not content:
        raise HTTPException(status_code=422, detail="请上传参考图后再反推提示词")
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="参考图超过 8MB，请压缩后再试")
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="提示词反推仅接受图片文件")

    try:
        result = await asyncio.to_thread(
            app.state.vlm_provider.reverse_prompt,
            image_data_url=_image_upload_to_data_url(image, content),
            media_type=media_key,
            hint=str(hint or "").strip()[:200],
        )
    except (LlmError, requests.exceptions.RequestException) as error:
        raise_as_llm_http(error)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"提示词反推异常：{error}") from error

    app.state.auth_store.audit(
        "reverse_prompt", "vlm", actor_user_id=user["id"], target_id="prompt",
        detail=f"media_type={media_key}",
        ip_address=client_ip(request),
    )
    return {
        "chinese_prompt": result["chinese_prompt"],
        "english_prompt": result["english_prompt"],
        "media_type": media_key,
    }


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
            script_mode=payload.script_mode,
        )
    except (LlmError, requests.exceptions.RequestException) as error:
        raise_as_llm_http(error)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"剧本拆解异常：{error}") from error

    app.state.auth_store.audit(
        "split_script", "llm", actor_user_id=user["id"], target_id="director",
        detail=f"shot_count={payload.shot_count or 4}; style={payload.style_vibe or 'default'}; mode={payload.script_mode}",
        ip_address=client_ip(request),
    )
    return split_result

@app.post("/api/llm/repair-continuity", tags=["大模型"], summary="局部修复相邻镜头连续性")
async def repair_continuity_endpoint(
    payload: DirectorContinuityRepairRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    available, reason = app.state.llm_provider.availability()
    if not available:
        raise HTTPException(status_code=503, detail=reason or "大模型服务不可用")
    try:
        result = await asyncio.to_thread(
            app.state.llm_provider.repair_director_continuity,
            payload.recipe,
            from_shot=payload.from_shot,
            to_shot=payload.to_shot,
        )
    except (LlmError, requests.exceptions.RequestException) as error:
        raise_as_llm_http(error)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"连续性局部修复异常：{error}") from error
    app.state.auth_store.audit("repair_continuity", "llm", actor_user_id=user["id"], target_id="director", detail=f"from={payload.from_shot};to={payload.to_shot}", ip_address=client_ip(request))
    return result


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


@app.get("/api/voice-bank", tags=["导演台2"], summary="读取内置短剧配音声线")
def list_builtin_voice_bank(user: Annotated[dict, Depends(current_user)]) -> dict:
    del user
    return {"voices": list_voice_presets()}


@app.get(
    "/api/voice-bank/{preset_id}/audio",
    tags=["导演台2"],
    summary="读取内置声线参考音",
    responses={200: {"content": {"audio/wav": {}}}},
)
def builtin_voice_audio(preset_id: Annotated[str, ApiPath(description="内置声线 ID")], user: Annotated[dict, Depends(current_user)]) -> FileResponse:
    del user
    try:
        path = ensure_voice_prompt(preset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="内置声线不存在")
    except VoiceBankError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=502, detail=f"内置参考音暂不可用：{error}") from error
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.get(
    "/api/canvas/projects",
    response_model=list[CanvasProjectListItem],
    tags=["画布"],
    summary="列出当前用户的无限画布",
)
def list_canvas_projects(
    user: Annotated[dict, Depends(current_user)],
    trashed: bool = False,
) -> list[dict]:
    return app.state.canvas_store.list_projects(user["id"], trashed=trashed)


@app.post(
    "/api/canvas/projects",
    response_model=CanvasProjectResponse,
    status_code=201,
    tags=["画布"],
    summary="创建无限画布",
)
def create_canvas_project(
    payload: CanvasProjectCreateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        created = app.state.canvas_store.create_project(user["id"], payload.title)
    except CanvasValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "create_canvas_project", "canvas", actor_user_id=user["id"], target_id=created["id"],
        detail=f"title={created['title']}",
        ip_address=client_ip(request),
    )
    return created


@app.post(
    "/api/canvas/linked",
    response_model=CanvasProjectResponse,
    tags=["画布"],
    summary="获取或创建导演项目绑定的资产画布",
)
def ensure_linked_canvas_project(
    payload: CanvasLinkedProjectRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    if not ProjectService.allows_user(payload.director_project_id, user["id"]):
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        project = app.state.canvas_store.get_or_create_linked(
            user["id"], payload.director_project_id, payload.title or "资产画布",
        )
    except CanvasValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "ensure_linked_canvas_project", "canvas", actor_user_id=user["id"], target_id=project["id"],
        detail=f"director_project_id={payload.director_project_id}",
        ip_address=client_ip(request),
    )
    return project


@app.get(
    "/api/canvas/projects/{canvas_id}",
    response_model=CanvasProjectResponse,
    tags=["画布"],
    summary="读取画布及当前草稿",
)
def get_canvas_project(canvas_id: str, user: Annotated[dict, Depends(current_user)]) -> dict:
    try:
        return app.state.canvas_store.get_project(user["id"], canvas_id)
    except CanvasNotFoundError as error:
        raise HTTPException(status_code=404, detail="画布不存在") from error


@app.patch(
    "/api/canvas/projects/{canvas_id}",
    response_model=CanvasProjectResponse,
    tags=["画布"],
    summary="更新画布标题、标签或收藏",
)
def update_canvas_project(
    canvas_id: str,
    payload: CanvasProjectUpdateRequest,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        return app.state.canvas_store.update_project(
            user["id"],
            canvas_id,
            title=payload.title,
            tags=payload.tags,
            is_favorite=payload.is_favorite,
        )
    except CanvasNotFoundError as error:
        raise HTTPException(status_code=404, detail="画布不存在") from error
    except CanvasValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post(
    "/api/canvas/projects/{canvas_id}/trash",
    tags=["画布"],
    summary="将画布移入回收站",
)
def trash_canvas_project(
    canvas_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        trashed = app.state.canvas_store.trash_project(user["id"], canvas_id)
    except CanvasNotFoundError as error:
        raise HTTPException(status_code=404, detail="画布不存在") from error
    app.state.auth_store.audit(
        "trash_canvas_project", "canvas", actor_user_id=user["id"], target_id=canvas_id,
        ip_address=client_ip(request),
    )
    return {"ok": True, **trashed}


@app.post(
    "/api/canvas/projects/{canvas_id}/restore",
    response_model=CanvasProjectResponse,
    tags=["画布"],
    summary="从回收站恢复画布",
)
def restore_canvas_project(
    canvas_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        restored = app.state.canvas_store.restore_project(user["id"], canvas_id)
    except CanvasNotFoundError as error:
        raise HTTPException(status_code=404, detail="画布不存在或不在回收站") from error
    app.state.auth_store.audit(
        "restore_canvas_project", "canvas", actor_user_id=user["id"], target_id=canvas_id,
        ip_address=client_ip(request),
    )
    return restored


@app.delete(
    "/api/canvas/projects/{canvas_id}",
    tags=["画布"],
    summary="删除画布及其草稿历史",
)
def delete_canvas_project(
    canvas_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        app.state.canvas_store.delete_project(user["id"], canvas_id)
    except CanvasNotFoundError as error:
        raise HTTPException(status_code=404, detail="画布不存在") from error
    app.state.auth_store.audit(
        "delete_canvas_project", "canvas", actor_user_id=user["id"], target_id=canvas_id,
        ip_address=client_ip(request),
    )
    return {"ok": True}


@app.put(
    "/api/canvas/projects/{canvas_id}/draft",
    response_model=CanvasDraftSaveResponse,
    tags=["画布"],
    summary="保存画布草稿（乐观版本校验）",
)
def save_canvas_draft(
    canvas_id: str,
    payload: CanvasDraftSaveRequest,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        return app.state.canvas_store.save_draft(
            user["id"], canvas_id, payload.base_version, payload.content, payload.checksum,
        )
    except CanvasNotFoundError as error:
        raise HTTPException(status_code=404, detail="画布不存在") from error
    except CanvasConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "current_version": error.current_version},
        ) from error
    except CanvasValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get(
    "/api/canvas/projects/{canvas_id}/versions",
    response_model=list[CanvasDraftVersionItem],
    tags=["画布"],
    summary="列出画布草稿历史版本",
)
def list_canvas_versions(canvas_id: str, user: Annotated[dict, Depends(current_user)]) -> list[dict]:
    try:
        return app.state.canvas_store.list_versions(user["id"], canvas_id)
    except CanvasNotFoundError as error:
        raise HTTPException(status_code=404, detail="画布不存在") from error


@app.post(
    "/api/canvas/projects/{canvas_id}/versions/{version}/restore",
    response_model=CanvasDraftSaveResponse,
    tags=["画布"],
    summary="恢复画布历史版本",
)
def restore_canvas_version(
    canvas_id: str,
    version: int,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    try:
        restored = app.state.canvas_store.restore_version(user["id"], canvas_id, version)
    except CanvasNotFoundError as error:
        raise HTTPException(status_code=404, detail="画布或版本不存在") from error
    except CanvasValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    app.state.auth_store.audit(
        "restore_canvas_version", "canvas", actor_user_id=user["id"], target_id=canvas_id,
        detail=f"version={version}",
        ip_address=client_ip(request),
    )
    return restored


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
    data = public_director_project(record)
    active = app.state.store.get_active_director_operation(project_id)
    if active is not None:
        data["active_operation"] = public_director_operation(active)
    return data


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
                (lambda latest, incoming: merge_recipe_creative(
                    latest, incoming, deleted_take_ids=payload.deleted_take_ids
                ))
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


def _format_sse_event(event: dict) -> str:
    name = str(event.get("event") or "message")
    seq = int(event.get("seq") or 0)
    payload = json.dumps(event.get("data") or {}, ensure_ascii=False)
    return f"id: {seq}\nevent: {name}\ndata: {payload}\n\n"


@app.get(
    "/api/director/operations/{operation_id}/events",
    tags=["导演台"],
    summary="订阅导演操作事件流（SSE）",
    description=(
        "以 `text/event-stream` 推送导演长操作的过程事件：`status`（状态/进度）、"
        "`agent`（Agent 状态变化）、`script_delta`（剧本字段流式增量，field 为 title/summary/fullStory）、"
        "以及终态 `done`/`cancelled`/`error`。连接即重放 `since` 之后的缓冲事件，收到终态事件后服务端关闭流；"
        "事件仅在内存中短期缓冲，重连过旧或服务重启后请回退到轮询接口。"
    ),
)
async def stream_director_operation_events(
    operation_id: str,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
    since: Annotated[int, Query(description="只重放 seq 大于该值的缓冲事件；0 表示从头重放缓冲区")] = 0,
) -> StreamingResponse:
    director_operation_or_404(app.state.store, operation_id, user)
    bus = app.state.director_operations.events

    async def event_stream():
        queue, replay = bus.subscribe(operation_id, since=max(0, since))
        last_seq = max(0, since)
        try:
            for event in replay:
                last_seq = max(last_seq, int(event.get("seq") or 0))
                yield _format_sse_event(event)
                if event.get("terminal"):
                    return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    try:
                        current = app.state.store.get_director_operation(operation_id)
                    except KeyError:
                        current = {"status": "failed", "error": "导演操作不存在"}
                    if current.get("status") in TERMINAL_OPERATION_STATUSES:
                        yield _format_sse_event(
                            terminal_event_for_status(
                                str(current["status"]),
                                result=current.get("result"),
                                message=current.get("error"),
                            )
                        )
                        return
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    return
                seq = int(item.get("seq") or 0)
                if seq <= last_seq:
                    continue
                last_seq = seq
                yield _format_sse_event(item)
                if item.get("terminal"):
                    return
        finally:
            bus.unsubscribe(operation_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# 复刻台（shot_replication）：参考片上传 / 拉片产物服务 / 拉片与转绘操作
# ---------------------------------------------------------------------------


def replication_project_or_404(store: JobStore, project_id: str, user: dict) -> dict:
    record = director_project_or_404(store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_REPLICATION:
        raise HTTPException(status_code=422, detail="只有复刻工程可以使用该接口")
    return record


@app.post(
    "/api/director/replications/{project_id}/source-video",
    response_model=DirectorProjectResponse,
    tags=["复刻台"],
    summary="上传复刻参考片",
)
async def upload_replication_source_video(
    project_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
    file: Annotated[UploadFile, File(description="参考片视频文件（mp4/mov/webm，≤2GB）")],
    expected_content_revision: Annotated[
        int | None,
        Form(ge=1, description="客户端最后读取的创作内容版本；不匹配时返回 409。"),
    ] = None,
) -> dict:
    record = replication_project_or_404(app.state.store, project_id, user)
    suffix = validate_source_video(file.filename or "", file.size)
    staging = settings.staging_dir / f"replication-source-{secrets.token_urlsafe(6)}{suffix}"
    staging.parent.mkdir(parents=True, exist_ok=True)
    await save_upload(file, staging)
    try:
        try:
            probe = probe_source_video(staging)
        except VideoAnalysisError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        saved_path, public_url = save_replication_source(
            user["id"], project_id, source=staging, original_name=file.filename or "reference.mp4",
        )
        try:
            saved = app.state.store.mutate_director_project_payload(
                project_id,
                lambda latest: _bind_replication_source(
                    normalize_replication_payload(latest),
                    path=str(saved_path), url=public_url, name=file.filename or saved_path.name,
                    probe=probe,
                ),
                content_update=True,
                expected_content_revision=expected_content_revision,
            )
        except DirectorProjectConflictError as error:
            raise director_content_conflict_http(error) from error
    finally:
        staging.unlink(missing_ok=True)
    app.state.auth_store.audit(
        "upload_replication_source", "director", actor_user_id=user["id"], target_id=project_id,
        detail=saved_path.name, ip_address=client_ip(request),
    )
    return public_director_project(saved)


def _bind_replication_source(payload: dict, *, path: str, url: str, name: str, probe) -> dict:
    payload["sourceVideo"] = {
        "path": path,
        "url": url,
        "name": name,
        "width": probe.width,
        "height": probe.height,
        "fps": round(probe.fps, 3),
        "durationSec": round(probe.duration, 3),
    }
    analysis = payload.get("analysis") or {}
    analysis.update({"status": "idle", "depthStatus": "idle", "error": None,
                     "depthPath": None, "depthUrl": None})
    payload["shots"] = []
    payload["subjects"] = []
    return payload


@app.get(
    "/api/director/replications/{project_id}/source",
    tags=["复刻台"],
    summary="读取复刻参考片",
)
def download_replication_source(
    project_id: str,
    user: Annotated[dict, Depends(current_user)],
) -> FileResponse:
    replication_project_or_404(app.state.store, project_id, user)
    path = find_replication_source_file(user["id"], project_id)
    if path is None:
        raise HTTPException(status_code=404, detail="尚未上传参考片")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get(
    "/api/director/replications/{project_id}/depth",
    tags=["复刻台"],
    summary="读取全片深度视频",
)
def download_replication_depth(
    project_id: str,
    user: Annotated[dict, Depends(current_user)],
) -> FileResponse:
    replication_project_or_404(app.state.store, project_id, user)
    path = find_replication_depth_file(user["id"], project_id)
    if path is None:
        raise HTTPException(status_code=404, detail="深度视频尚未生成")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get(
    "/api/director/replications/{project_id}/shots/{shot_id}/{slot}",
    tags=["复刻台"],
    summary="读取分镜拉片产物（segment/depth/key0/key1）",
)
def download_replication_shot_artifact(
    project_id: str,
    shot_id: str,
    slot: str,
    user: Annotated[dict, Depends(current_user)],
) -> FileResponse:
    replication_project_or_404(app.state.store, project_id, user)
    path = find_replication_artifact_file(
        owner_user_id=user["id"], project_id=project_id, shot_id=shot_id, slot=slot,
    )
    if path is None:
        raise HTTPException(status_code=404, detail="拉片产物不存在")
    media_type = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "video/mp4"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.post(
    "/api/director/replications/{project_id}/operations",
    response_model=DirectorOperationResponse,
    status_code=202,
    tags=["复刻台"],
    summary="创建复刻台长操作（analyze_reference_video / replicate_shots）",
)
async def create_replication_operation(
    project_id: str,
    payload: DirectorOperationCreateRequest,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    record = replication_project_or_404(app.state.store, project_id, user)
    if payload.kind not in {"analyze_reference_video", "replicate_shots"}:
        raise HTTPException(status_code=422, detail="复刻台仅支持拉片分析与批量转绘操作")
    if payload.kind == "analyze_reference_video":
        source = find_replication_source_file(user["id"], project_id)
        if source is None:
            raise HTTPException(status_code=422, detail="请先上传参考片")
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
        "create_replication_operation", "director", actor_user_id=user["id"], target_id=project_id,
        detail=f"{payload.kind}:{operation['id']}", ip_address=client_ip(request),
    )
    return public_director_operation(operation)


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
    batch_project: dict | None = None
    if payload.project_id:
        batch_project = director_project_or_404(app.state.store, payload.project_id, user)
        if payload_kind(batch_project.get("payload")) != PAYLOAD_KIND_BATCH:
            raise HTTPException(status_code=422, detail="只有批量短视频工程可以重新裂变，请新建批量工程")
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
    if batch_project is not None:
        saved = app.state.store.update_director_project(
            batch_project["id"],
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


def _validate_reference_upload(definition, index: int, upload: UploadFile, count: int | None = None) -> None:
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    kind = definition.reference_kind(index, count) if definition is not None else "image"
    if kind == "audio":
        if content_type and not (content_type.startswith("audio/") or content_type == "application/octet-stream"):
            raise HTTPException(status_code=422, detail="数字人口播的第 2 项素材必须是音频文件")
    elif kind == "media":
        # 音频或视频均可（人声/伴奏分离的 LoadAudio 会自动抽取视频音轨）。
        extension = Path(upload.filename or "").suffix.lower()
        type_ok = (
            not content_type
            or content_type.startswith("audio/")
            or content_type.startswith("video/")
            or content_type == "application/octet-stream"
        )
        extension_ok = extension in {
            ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
            ".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi",
        }
        if not (type_ok and extension_ok):
            raise HTTPException(
                status_code=422,
                detail=f"{definition.name}的第 {index} 项素材必须是音频（MP3 / WAV / FLAC / M4A）或视频（MP4 / MOV / WebM）文件",
            )
    elif kind == "video":
        extension = Path(upload.filename or "").suffix.lower()
        if extension not in {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"} or (
            content_type and not (content_type.startswith("video/") or content_type == "application/octet-stream")
        ):
            if definition is not None and getattr(definition, "reference_slots", ()):
                raise HTTPException(status_code=422, detail=f"{definition.name}的第 {index} 项素材必须是视频文件（MP4 / MOV / WebM）")
            raise HTTPException(status_code=422, detail="动作迁移的第 2 项素材必须是动作参考视频（MP4 / MOV / WebM）")
    elif content_type and not content_type.startswith("image/"):
        detail = f"{definition.name}的第 {index} 项素材必须是角色形象图" if definition is not None and definition.accepts_video_reference else "参考素材必须为图片"
        raise HTTPException(status_code=422, detail=detail)


async def _validate_saved_references(definition, paths: list[str], options: dict, upload_dir: Path) -> None:
    if definition.id == JobMode.KEEP_FACE_RESTORE.value:
        try:
            options.update(await asyncio.to_thread(validate_face_restore_sources, paths, options["duration"]))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return
    if definition.id == JobMode.MINIMAX_H3_VIDEO_EDIT.value:
        from .h3_video_edit_workflow import validate_video_edit_source, video_edit_dimensions

        try:
            source = await asyncio.to_thread(validate_video_edit_source, Path(paths[0]), options.get("duration") or "5s")
            options["width"], options["height"] = video_edit_dimensions(source.width, source.height)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return
    if is_depth_workflow(definition.id):
        # 深度捕捉 references[0] 是原片视频；画布由分发层探测，这里只校验时长。
        from .h3_depth_workflow import validate_depth_source

        try:
            validate_depth_source(Path(paths[0]), options.get("duration") or "5s")
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return
    if is_lip_sync_workflow(definition.id):
        options["width"], options["height"] = await asyncio.to_thread(
            _probe_lipsync_source_canvas, Path(paths[0]), upload_dir,
        )
        options["scene_duration_seconds"] = await asyncio.to_thread(_probe_avatar_scene_duration, paths[1], upload_dir)
        return
    if definition.accepts_video_reference:
        try:
            from PIL import Image

            with Image.open(paths[0]) as image:
                image.verify()
        except Exception as error:
            raise HTTPException(status_code=422, detail="角色形象图无法读取，请上传有效的 PNG / JPEG / WebP 图片。") from error
        try:
            if definition.id == JobMode.SCAIL2_REPLACEMENT.value:
                options.update(await asyncio.to_thread(resolve_scail_video_options, Path(paths[1]), options["duration"]))
                options["width"], options["height"] = await asyncio.to_thread(probe_scail_canvas, Path(paths[1]))
            elif is_motion_ref_video_workflow(definition.id):
                # 多人版约定动作参考视频在 references 末位。
                await asyncio.to_thread(validate_motion_video, Path(paths[-1]), options["duration"])
            else:
                await asyncio.to_thread(validate_motion_video, Path(paths[1]), options["duration"])
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    if definition.accepts_audio_reference:
        options["scene_duration_seconds"] = await asyncio.to_thread(_probe_avatar_scene_duration, paths[1], upload_dir)


def _probe_lipsync_source_canvas(path: Path, upload_dir: Path) -> tuple[int, int]:
    """探测口型同步源视频尺寸并换算 32 对齐画布；时长需在官方 2-15 秒参考视频政策内。"""
    seconds = SystemFfmpegRunner().probe_duration(path)
    if seconds < LIPSYNC_SOURCE_MIN_SECONDS:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(
            status_code=422,
            detail=f"原视频仅 {seconds:.1f} 秒，口型同步要求至少 {LIPSYNC_SOURCE_MIN_SECONDS:.0f} 秒。",
        )
    if seconds > LIPSYNC_SOURCE_MAX_SECONDS:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(
            status_code=422,
            detail=f"原视频 {seconds:.1f} 秒超出 {LIPSYNC_SOURCE_MAX_SECONDS:.0f} 秒上限，请先裁剪视频。",
        )
    try:
        completed = subprocess.run(
            [
                SystemFfmpegRunner().require()[1], "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "json", str(path),
            ],
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        stream = (json.loads(completed.stdout or "{}").get("streams") or [{}])[0]
        width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    except Exception:
        width = height = 0
    if width <= 0 or height <= 0:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail="无法读取原视频尺寸，请使用标准 MP4 / MOV / WebM 文件。")
    max_area = 1344 * 768
    aligned_w, aligned_h = max(256, round(width / 32) * 32), max(256, round(height / 32) * 32)
    if aligned_w * aligned_h > max_area:
        scale = math.sqrt(max_area / (aligned_w * aligned_h))
        aligned_w = max(256, round(aligned_w * scale / 32) * 32)
        aligned_h = max(256, round(aligned_h * scale / 32) * 32)
    return aligned_w, aligned_h


def _probe_avatar_scene_duration(path: str, upload_dir: Path) -> float:
    """探测口播音频时长并按单渲染窗口上限收敛；失败时清理任务目录并拒绝任务。"""
    seconds = 0.0
    try:
        seconds = SystemFfmpegRunner().probe_duration(Path(path))
    except Exception:
        seconds = 0.0
    if seconds <= 0 and str(path).lower().endswith(".wav"):
        try:
            with wave.open(str(path), "rb") as handle:
                seconds = handle.getnframes() / float(handle.getframerate() or 1)
        except Exception:
            seconds = 0.0
    if seconds <= 0:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail="无法读取口播音频时长，请使用标准 WAV 或 MP3 文件。")
    if seconds > AVATAR_MAX_SCENE_SECONDS + 0.2:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(
            status_code=422,
            detail=(
                f"口播音频 {seconds:.1f} 秒超出当前约 {AVATAR_MAX_SCENE_SECONDS:.0f} 秒的单次生成上限，"
                "请裁剪音频后重试；长音频分窗生成将在后续版本支持。"
            ),
        )
    return round(min(seconds, AVATAR_MAX_SCENE_SECONDS), 2)


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
    prompt: Annotated[str, Form(description="创作提示词；支持默认提示词的工作流可留空。")]= "",
    negative_prompt: Annotated[str, Form(description="仅 image 模式生效。")]= "",
    image_size: Annotated[str | None, Form(description="仅 image 模式必填，值来自 image_sizes。")]= None,
    options: Annotated[str | None, Form(description="工作流参数 JSON；字段、默认值与约束见 GET /api/modes/{mode}。")]= None,
    title: Annotated[str | None, Form(description="任务标题。")]= None,
    display_prompt: Annotated[str | None, Form(description="中文展示提示词；省略时界面显示 prompt。")]= None,
    source_job_id: Annotated[str | None, Form(description="来源任务 ID；人脸修复支持视频来源，其他视频生成支持图片来源。")]= None,
    source_generation_item_id: Annotated[str | None, Form(description="来源生成项 ID。")]= None,
    source_output_index: Annotated[int | None, Form(description="来源输出序号。")]= None,
    references: list[UploadFile] = File(default=[], description="参考素材文件；类型、数量与顺序见工作流定义。"),
) -> dict:
    return await submit_generation(
        user=user, mode=mode, prompt=prompt, negative_prompt=negative_prompt, image_size=image_size,
        options=options, title=title, display_prompt=display_prompt, source_job_id=source_job_id,
        source_generation_item_id=source_generation_item_id, source_output_index=source_output_index,
        references=references,
    )


async def _prepare_uploaded_upscale(mode: str, generation_options: dict, source_path: str) -> None:
    """给「AI 工具 → 视频超分」上传的原片补齐宽高/帧数，并在入队前做能力与显存预检。"""
    relay = is_relayvsr_upscale_workflow(mode)
    seedvr2 = is_seedvr2_upscale_workflow(mode)
    try:
        probe = await asyncio.to_thread(probe_source_video, Path(source_path))
    except Exception as error:
        raise HTTPException(status_code=422, detail=f"无法读取原片信息：{error}") from error
    fps = float(getattr(probe, "fps", 0) or 0) or 24.0
    frames = int(round(float(getattr(probe, "duration", 0) or 0) * fps)) or 1
    width, height = int(probe.width), int(probe.height)
    generation_options.update({"width": width, "height": height, "frames": frames})

    comfy = getattr(app.state.worker, "comfy", None)
    if relay or not seedvr2:
        if comfy is not None and hasattr(comfy, "reject_relay_vsr_memory"):
            reason = (
                comfy.reject_relay_vsr_memory(mode, generation_options)
                if relay else comfy.reject_vsr_memory(mode, generation_options)
            )
        else:
            stats = comfy.system_stats() if comfy is not None and hasattr(comfy, "system_stats") else None
            reason = (
                relay_vsr_memory_rejection(
                    width, height, frames,
                    vram_total=comfy_vram_total_bytes(stats),
                    device_name=comfy_vram_device_name(stats),
                )
                if relay else vsr_memory_rejection(width, height, frames)
            )
        if reason:
            raise HTTPException(status_code=422, detail=reason)

    check = (
        getattr(comfy, "require_relay_vsr", None) if relay
        else getattr(comfy, "require_seedvr2", None) if seedvr2
        else getattr(comfy, "require_rtx_vsr_node", None)
    )
    if callable(check):
        try:
            await asyncio.to_thread(check)
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error


async def submit_generation(
    *, user: dict, mode: str, prompt: str, negative_prompt: str = "", image_size: str | None = None,
    options: str | None = None, title: str | None = None, display_prompt: str | None = None,
    source_job_id: str | None = None,
    source_generation_item_id: str | None = None, source_output_index: int | None = None,
    references: list[UploadFile] | None = None, job_id: str | None = None,
) -> dict:
    """Shared creation path for browser forms and authenticated MCP tools."""
    references = references or []
    try:
        definition = workflow_for(mode)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="工作流不存在") from error
    prompt = prompt.strip() or definition.default_prompt or ""
    if not prompt:
        raise HTTPException(status_code=422, detail="请填写创作提示词")
    if is_upscale_workflow(mode):
        # 超分必须有原片：要么对已成功的成片调用 /api/jobs/{id}/upscale，
        # 要么在「AI 工具 → 视频超分」上传一条原片（工作流只接受 1 条参考视频）。
        if len(references) != 1:
            raise HTTPException(
                status_code=422,
                detail="超分需要上传 1 条原片视频，或对已成功的成片调用超分接口",
            )
    if mode == JobMode.KEEP_FACE_RESTORE.value:
        check = getattr(getattr(app.state.worker, "comfy", None), "require_keep_face_restore", None)
        if callable(check):
            try:
                await asyncio.to_thread(check)
            except Exception as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        raw_options = json.loads(options) if options is not None else {}
        if not isinstance(raw_options, dict):
            raise ValueError("生成参数必须为对象。")
        validate_references(mode, references)
        generation_options = normalize_options(mode, raw_options)
        validate_option_relationships(mode, generation_options, len(references))
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if is_composite_image_workflow(mode):
        # 复合图片工作流的生图模型不在任务表单里：跟随管理员启用的目录默认模型，
        # 避免注册表内置默认值被停用后任务必然失败。
        generation_options["provider_model"] = app.state.grs_provider.resolve_composite_model(
            generation_options.get("provider_model"),
        )

    if is_grs_image_workflow(mode):
        available, reason = app.state.grs_provider.availability(mode)
        if not available:
            raise HTTPException(status_code=409, detail=reason or "图片服务能力不可用")

    if is_cloud_video_workflow(mode):
        available, reason = False, "云端视频服务尚未初始化。"
        if definition.cloud_provider and hasattr(app.state, "cloud_video"):
            try:
                available, reason = CloudVideoService.instance().availability(definition.cloud_provider)
            except CloudVideoError as error:
                available, reason = False, str(error)
        if not available:
            raise HTTPException(status_code=409, detail=reason or "云端视频服务不可用")

    source: dict | None = None
    if source_job_id:
        if definition.media_type != "video":
            raise HTTPException(status_code=422, detail="只有视频任务可以记录图片转视频来源")
        source_job = job_or_404(app.state.store, source_job_id, user)
        source_item = next((
            item for round_data in source_job.get("rounds", []) for item in round_data.get("generation_items", [])
            if item["id"] == source_generation_item_id
        ), None)
        if source_item is None or source_output_index is None or not 0 <= source_output_index < len(source_item["outputs"]):
            raise HTTPException(status_code=422, detail="人脸修复来源视频不存在" if mode == JobMode.KEEP_FACE_RESTORE.value else "图片转视频来源不存在")
        expected_kind = "video" if mode == JobMode.KEEP_FACE_RESTORE.value else "image"
        if source_item["outputs"][source_output_index].get("kind") != expected_kind:
            raise HTTPException(status_code=422, detail="人脸修复来源必须是视频" if expected_kind == "video" else "图片转视频来源必须是图片")
        source = {"job_id": source_job_id, "generation_item_id": source_generation_item_id, "output_index": source_output_index}

    job_id = job_id or secrets.token_urlsafe(9).replace("-", "").replace("_", "")
    upload_dir = settings.uploads_dir / user["id"] / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    references_paths: list[str] = []
    try:
        for index, upload in enumerate(references, start=1):
            _validate_reference_upload(definition, index, upload, len(references))
            destination = upload_dir / f"{index}_{safe_name(upload.filename or 'upload.png')}"
            await save_upload(upload, destination, max_bytes=KEEP_MAX_UPLOAD_BYTES if definition is not None and definition.id == JobMode.KEEP_FACE_RESTORE.value else MAX_UPLOAD_BYTES)
            references_paths.append(str(destination))
        await _validate_saved_references(definition, references_paths, generation_options, upload_dir)
        if is_upscale_workflow(mode):
            await _prepare_uploaded_upscale(mode, generation_options, references_paths[0])
    except HTTPException:
        # Never leave partially-saved references behind when a later file
        # fails validation or exceeds the size limit.
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise

    store: JobStore = app.state.store
    normalized_display_prompt = display_prompt.strip() if display_prompt and display_prompt.strip() != prompt else None
    job = await asyncio.to_thread(
        store.create,
        job_id,
        mode,
        prompt,
        negative_prompt.strip() if definition.accepts_negative_prompt else "",
        image_size if definition.accepts_image_size else None,
        references_paths,
        generation_options,
        submitted_options=raw_options if options is not None else None,
        owner_user_id=user["id"],
        title=title.strip() if title else None,
        source=source,
        display_prompt=normalized_display_prompt,
    )
    await app.state.worker.enqueue(job_id)
    return public_job(await asyncio.to_thread(store.get, job_id))


@app.post(
    "/api/jobs/{job_id}/rounds", status_code=202, response_model=JobResponse,
    tags=["任务"], summary="为同媒介任务创建下一轮",
)
async def create_job_round(
    job_id: str,
    user: Annotated[dict, Depends(mutating_user)],
    prompt: Annotated[str, Form()] = "",
    negative_prompt: Annotated[str, Form()] = "",
    image_size: Annotated[str | None, Form()] = None,
    options: Annotated[str | None, Form()] = None,
    display_prompt: Annotated[str | None, Form()] = None,
    references: list[UploadFile] = File(default=[]),
) -> dict:
    existing = job_or_404(app.state.store, job_id, user, include_references=True)
    if existing.get("legacy_read_only"):
        raise HTTPException(status_code=409, detail="旧版图片结果仅支持查看，不能再次生成")
    mode = existing["mode"]
    try:
        definition = workflow_for(mode)
    except KeyError:
        definition = None
    prompt = prompt.strip() or (definition.default_prompt if definition else None) or ""
    if not prompt:
        raise HTTPException(status_code=422, detail="请填写创作提示词")
    try:
        raw_options = json.loads(options) if options is not None else existing.get("options", {})
        if options is None and definition is not None and definition.accepts_video_reference:
            latest = existing["rounds"][-1]
            raw_options = dict(latest.get("options") or {})
            if "seed" in (definition.option_schema or {}).get("properties", {}):
                raw_options["seed"] = (latest.get("submitted_options") or {}).get("seed", 0)
        if not isinstance(raw_options, dict):
            raise ValueError("生成参数必须为对象。")
        reused_references = existing["rounds"][-1].get("references", []) if not references else []
        validate_references(mode, references or reused_references)
        generation_options = normalize_options(mode, raw_options) if options is not None or (
            definition is not None and definition.accepts_video_reference
        ) else existing.get("options", {})
        validate_option_relationships(mode, generation_options, len(references or reused_references))
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if is_grs_image_workflow(mode):
        available, reason = app.state.grs_provider.availability(mode)
        if not available:
            raise HTTPException(status_code=409, detail=reason or "图片服务能力不可用")
    if is_cloud_video_workflow(mode):
        available, reason = False, "云端视频服务尚未初始化。"
        if definition.cloud_provider and hasattr(app.state, "cloud_video"):
            try:
                available, reason = CloudVideoService.instance().availability(definition.cloud_provider)
            except CloudVideoError as error:
                available, reason = False, str(error)
        if not available:
            raise HTTPException(status_code=409, detail=reason or "云端视频服务不可用")
    sequence = len(existing["rounds"]) + 1
    upload_dir = settings.uploads_dir / user["id"] / job_id / f"round-{sequence}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    reference_paths: list[str] = list(reused_references)
    try:
        for index, upload in enumerate(references, start=1):
            _validate_reference_upload(definition, index, upload, len(references))
            destination = upload_dir / f"{index}_{safe_name(upload.filename or 'upload.png')}"
            await save_upload(upload, destination, max_bytes=KEEP_MAX_UPLOAD_BYTES if definition is not None and definition.id == JobMode.KEEP_FACE_RESTORE.value else MAX_UPLOAD_BYTES)
            reference_paths.append(str(destination))
        if definition is not None:
            await _validate_saved_references(definition, reference_paths, generation_options, upload_dir)
    except HTTPException:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise
    try:
        job = await asyncio.to_thread(
            app.state.store.create_round,
            job_id, prompt=prompt,
            negative_prompt=negative_prompt.strip() if definition is not None and definition.accepts_negative_prompt else "",
            image_size=image_size if definition is not None and definition.accepts_image_size else None,
            references=reference_paths, options=generation_options,
            submitted_options=raw_options if options is not None or (
                definition is not None and definition.accepts_video_reference
            ) else None,
            display_prompt=display_prompt.strip() if display_prompt and display_prompt.strip() != prompt else None,
        )
    except ValueError as error:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=409, detail=str(error)) from error
    await app.state.worker.enqueue(job_id)
    return public_job(await asyncio.to_thread(app.state.store.get, job_id))


@app.post(
    "/api/jobs/{job_id}/rounds/{round_id}/retry-failed-items", status_code=202,
    response_model=JobResponse, tags=["任务"], summary="只重试轮次中的失败生成项",
)
async def retry_failed_generation_items(
    job_id: str, round_id: str, user: Annotated[dict, Depends(mutating_user)],
) -> dict:
    job_or_404(app.state.store, job_id, user)
    try:
        retried = await asyncio.to_thread(app.state.store.retry_failed_items, job_id, round_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="轮次不存在") from error
    if not retried:
        raise HTTPException(status_code=409, detail="当前轮次没有可重试的失败项")
    for item in retried:
        if item["executor"] == "grs":
            app.state.worker.enqueue_generation(item["id"])
        else:
            await app.state.worker.enqueue(job_id)
    return public_job(await asyncio.to_thread(app.state.store.get, job_id))


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


@app.delete("/api/jobs/{job_id}", tags=["任务"], summary="删除任务记录与未被引用的云端产物")
def delete_job(job_id: str, user: Annotated[dict, Depends(mutating_user)]) -> dict:
    job_or_404(app.state.store, job_id, user)

    def cleanup(job, connection) -> None:
        items = [item for round_data in job["rounds"] for item in round_data["generation_items"]]
        if any(entry["status"] in {JobStatus.QUEUED.value, JobStatus.RUNNING.value} for entry in [job, *items]):
            raise HTTPException(status_code=409, detail="任务生成中，完成后才能删除")
        outputs = list(job["outputs"])
        for item in items:
            outputs.extend(item["outputs"])
            outputs.extend((item.get("refine_state") or {}).get("preview_outputs") or [])
        cloud_outputs = [output for output in outputs if output.get("cloud_url") or output.get("delivery_status") == "cloud"]
        if not cloud_outputs:
            return
        storage = app.state.resource_storage
        if storage.provider_id != "qiniu":
            raise HTTPException(status_code=409, detail="请先恢复任务产物对应的七牛云配置，再删除任务")
        keys: set[str] = set()
        for output in cloud_outputs:
            key = str(output.get("path") or "")
            saved_url = str(output.get("cloud_url") or "")
            expected_url = resource_object_url(storage, key)
            if not key or not saved_url or not expected_url or (
                urlsplit(saved_url)._replace(query="", fragment="")
                != urlsplit(expected_url)._replace(query="", fragment="")
            ):
                raise HTTPException(status_code=409, detail="无法确认云端产物所属存储，请检查原七牛云配置后重试")
            keys.add(key)
        if app.state.store.job_media_in_use(job_id, sorted(keys), connection):
            raise HTTPException(status_code=409, detail="任务产物仍被其他任务、资产或画布引用，请先解除引用后再删除")
        try:
            for key in sorted(keys):
                if not storage.delete(key):
                    raise RuntimeError("云端对象未删除")
        except Exception as error:
            raise HTTPException(status_code=502, detail="云端产物清理未完成，任务记录已保留；部分文件可能已清理，请重试删除") from error

    if not app.state.store.delete(job_id, before_commit=cleanup):
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
    if not is_local_comfy_job(existing["mode"]):
        raise HTTPException(status_code=409, detail="当前工作流不支持重新提交")
    job = app.state.store.retry_terminal(job_id)
    if job is None:
        raise HTTPException(status_code=409, detail="仅已中断、已停止或失败且未在视频服务执行的任务可以重新提交")
    await app.state.worker.enqueue(job_id)
    return public_job(job)


def awaiting_refine_item(job: dict) -> dict:
    items = job["rounds"][-1]["generation_items"] if job.get("rounds") else []
    item = items[0] if items else None
    if item is None or item["status"] != JobStatus.AWAITING_REFINE.value:
        raise HTTPException(status_code=409, detail="当前任务没有待确认的一采预览")
    return item


@app.post(
    "/api/jobs/{job_id}/refine/confirm",
    status_code=202,
    response_model=JobResponse,
    tags=["任务"],
    summary="确认一采预览并只跑二采精修",
    description="复用一采已保存的 seed 与工作流，ComfyUI 命中一采缓存后只执行二采精修。二采完成后返回精修成片，一采预览保留在结果中。",
)
async def confirm_refine(job_id: str, user: Annotated[dict, Depends(mutating_user)]) -> dict:
    job = job_or_404(app.state.store, job_id, user)
    item = awaiting_refine_item(job)
    refine_state = item.get("refine_state") or {}
    if not refine_state.get("workflow"):
        raise HTTPException(status_code=409, detail="未找到已保存的二采工作流，请重新生成")
    await asyncio.to_thread(
        app.state.store.update_generation,
        item["id"],
        status=JobStatus.QUEUED,
        stage="等待二采精修",
        progress=90,
        error="",
        cancel_requested=False,
        refine_state={**refine_state, "status": "confirmed"},
        clear_execution=True,
    )
    await app.state.worker.enqueue(job_id)
    return public_job(await asyncio.to_thread(app.state.store.get, job_id))


@app.post(
    "/api/jobs/{job_id}/refine/skip",
    status_code=202,
    response_model=JobResponse,
    tags=["任务"],
    summary="保留一采预览，放弃二采",
    description="把一采预览直接作为最终结果，清理二采续跑状态。ComfyUI 输出目录中的二采缓存不影响本任务。",
)
async def skip_refine(job_id: str, user: Annotated[dict, Depends(mutating_user)]) -> dict:
    job = job_or_404(app.state.store, job_id, user)
    item = awaiting_refine_item(job)
    await asyncio.to_thread(
        app.state.store.update_generation,
        item["id"],
        status=JobStatus.SUCCEEDED,
        stage="已保留一采预览",
        progress=100,
        outputs=item.get("outputs") or [],
        clear_refine_state=True,
        clear_execution=True,
    )
    return public_job(await asyncio.to_thread(app.state.store.get, job_id))


@app.post(
    "/api/jobs/{job_id}/upscale",
    status_code=202,
    response_model=JobResponse,
    tags=["任务"],
    summary="对已成功的成片提交 2x 超分（可选 RTX / SeedVR2 引擎）",
    description="根据已成功视频输出新建独立超分任务：engine=rtx 用 RTXVideoSuperResolution（秒级），engine=seedvr2 用 SeedVR2 生成式高清增强（分钟级）。接跑前 worker 会强制 POST /free 卸载 H3。同一原片已有进行中的超分时返回 409。超分失败不影响原片。",
)
async def upscale_job(
    job_id: str,
    user: Annotated[dict, Depends(mutating_user)],
    payload: UpscaleJobRequest | None = None,
) -> dict:
    source = job_or_404(app.state.store, job_id, user)
    if is_upscale_workflow(source["mode"]):
        raise HTTPException(status_code=422, detail="该任务已经是超分结果")
    engine = normalize_upscale_engine(payload.engine if payload else None)
    seedvr2 = engine == UPSCALE_ENGINE_SEEDVR2
    relay = engine == UPSCALE_ENGINE_RELAYVSR
    if source.get("status") != JobStatus.SUCCEEDED.value:
        raise HTTPException(status_code=409, detail="仅已成功出片的视频可以超分")
    located = original_video_locator(source)
    if located is None:
        raise HTTPException(status_code=422, detail="没有可超分的原片视频")
    original, generation_item_id, output_index = located
    owner_id = source.get("owner_user_id") or user["id"]
    active = active_upscale_job_for(app.state.store, owner_id, job_id)
    if active is not None:
        raise HTTPException(status_code=409, detail="该成片已有进行中的超分")
    vsr_options = vsr_job_options_from_source(source)
    comfy = getattr(app.state.worker, "comfy", None)
    if vsr_options and not seedvr2:
        if relay:
            if comfy is not None and hasattr(comfy, "reject_relay_vsr_memory"):
                reason = comfy.reject_relay_vsr_memory(source["mode"], source.get("options") or vsr_options)
            else:
                stats = comfy.system_stats() if comfy is not None and hasattr(comfy, "system_stats") else None
                reason = relay_vsr_memory_rejection(
                    vsr_options["width"],
                    vsr_options["height"],
                    vsr_options["frames"],
                    vram_total=comfy_vram_total_bytes(stats),
                    device_name=comfy_vram_device_name(stats),
                )
        elif comfy is not None and hasattr(comfy, "reject_vsr_memory"):
            reason = comfy.reject_vsr_memory(source["mode"], source.get("options") or vsr_options)
        else:
            reason = vsr_memory_rejection(
                vsr_options["width"],
                vsr_options["height"],
                vsr_options["frames"],
            )
        if reason:
            raise HTTPException(status_code=422, detail=reason)
    upscale_mode = (
        JobMode.SEEDVR2_UPSCALE if seedvr2
        else JobMode.RELAYVSR_UPSCALE if relay
        else JobMode.NVIDIA_RTX_VSR
    )
    try:
        generation_options = normalize_options(upscale_mode, vsr_options)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if comfy is not None:
        check = (
            getattr(comfy, "require_seedvr2", None) if seedvr2
            else getattr(comfy, "require_relay_vsr", None) if relay
            else getattr(comfy, "require_rtx_vsr_node", None)
        )
        if callable(check):
            try:
                check()
            except Exception as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        if comfy is not None:
            local = Path(comfy.local_path_for_output(original))
        else:
            extra = original.get("_local_path")
            local = Path(str(extra)) if extra else Path()
        if not local.is_file():
            raise FileNotFoundError(local)
    except Exception as error:
        raise HTTPException(status_code=422, detail=f"找不到可用于超分的原片文件: {error}") from error

    new_job_id = secrets.token_urlsafe(9).replace("-", "").replace("_", "")
    upload_dir = settings.uploads_dir / user["id"] / new_job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / f"1_{safe_name(local.name or 'source.mp4')}"
    try:
        shutil.copy2(local, destination)
    except OSError as error:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"复制原片失败: {error}") from error

    source_title = str(source.get("title") or source.get("prompt") or "成片").strip()
    engine_label = "高清增强" if seedvr2 else "细节超分" if relay else "2x超分"
    title = f"{source_title[:80]} · {engine_label}"
    default_prompt = "SeedVR2 高清增强" if seedvr2 else "RelayVSR 2x 细节超分" if relay else "2x 超分"
    prompt = str(source.get("prompt") or "").strip() or default_prompt
    store: JobStore = app.state.store
    try:
        job = await asyncio.to_thread(
            store.create,
            new_job_id,
            upscale_mode,
            prompt,
            "",
            None,
            [str(destination)],
            generation_options,
            submitted_options=generation_options,
            owner_user_id=user["id"],
            title=title,
            source={
                "job_id": job_id,
                "generation_item_id": generation_item_id,
                "output_index": output_index,
            },
        )
    except Exception:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise
    await app.state.worker.enqueue(new_job_id)
    return public_job(job)


@app.get("/api/face-restore/capabilities", tags=["任务"], summary="查询当前渲染机的人脸高清修复能力")
def face_restore_capabilities(user: Annotated[dict, Depends(current_user)]) -> dict:
    comfy = getattr(app.state.worker, "comfy", None)
    try:
        if comfy is None:
            raise ValueError("当前渲染服务尚未就绪")
        comfy.require_keep_face_restore()
        return {"available": True, "name": "人脸高清修复", "engine": "KEEP", "reason": ""}
    except Exception as error:
        return {"available": False, "name": "人脸高清修复", "engine": "KEEP", "reason": str(error)}


@app.get(
    "/api/upscale/capabilities",
    tags=["任务"],
    summary="查询当前 ComfyUI 可用的超分引擎",
    description="探测当前连接的 ComfyUI 是否装了 RTX VSR 节点，以及 SeedVR2 节点与模型是否齐全。结果缓存 30 秒。",
)
def upscale_capabilities(user: Annotated[dict, Depends(current_user)]) -> dict:
    def build() -> dict:
        comfy = getattr(app.state.worker, "comfy", None)
        if comfy is None:
            return {
                "engines": [
                    {"id": engine_id, "label": label, "available": False, "reason": "视频服务未配置"}
                    for engine_id, label in UPSCALE_ENGINES.items()
                ],
                "default": UPSCALE_ENGINE_RTX,
            }
        health = comfy.health()
        if not health.get("reachable"):
            reason = f"视频服务连接失败：{health.get('error') or health.get('url')}"
            return {
                "engines": [
                    {"id": engine_id, "label": label, "available": False, "reason": reason}
                    for engine_id, label in UPSCALE_ENGINES.items()
                ],
                "default": UPSCALE_ENGINE_RTX,
            }
        engines = []
        for engine_id, label in UPSCALE_ENGINES.items():
            try:
                if engine_id == UPSCALE_ENGINE_SEEDVR2:
                    comfy.require_seedvr2()
                elif engine_id == UPSCALE_ENGINE_RELAYVSR:
                    comfy.require_relay_vsr()
                else:
                    comfy.require_rtx_vsr_node()
            except Exception as error:
                engines.append({"id": engine_id, "label": label, "available": False, "reason": str(error)})
            else:
                engines.append({"id": engine_id, "label": label, "available": True, "reason": None})
        return {"engines": engines, "default": UPSCALE_ENGINE_RTX}

    return upscale_capabilities_cache.get_or_create("caps", build)


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
    summary="预览任务参考素材",
    responses={200: {"content": {"image/*": {}, "video/*": {}, "audio/*": {}}}},
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
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or _image_media_type(path))


@app.get(
    "/api/jobs/{job_id}/rounds/{round_id}/references/{reference_index}", tags=["任务"],
    summary="预览指定轮次参考素材", responses={200: {"content": {"image/*": {}, "video/*": {}, "audio/*": {}}}},
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
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or _image_media_type(path))


def _library_target_user_id(user: dict, user_id: str | None) -> str | None:
    if user["role"] in {"admin", "super_admin"} and user_id is not None:
        return None if user_id == "all" else user_id
    return user["id"]


def _library_entries(target_user_id: str | None) -> list[dict]:
    store = app.state.store
    return app.state.library_cache.get_or_build(
        (target_user_id, settings.public_api_prefix),
        store.content_epoch(),
        lambda: build_library_entries(
            store.list_library_sources(target_user_id, 500),
            api_prefix=settings.public_api_prefix,
        ),
    )


@app.get("/api/library", response_model=list[LibraryItemResponse], tags=["作品库"], summary="列出作品库媒体")
def library(user: Annotated[dict, Depends(current_user)], user_id: str | None = None) -> list[dict]:
    return _library_entries(_library_target_user_id(user, user_id))


@app.get(
    "/api/library/query",
    response_model=LibraryQueryResponse,
    tags=["作品库"],
    summary="分页检索作品库媒体",
)
def library_query(
    user: Annotated[dict, Depends(current_user)],
    q: Annotated[str | None, Query(max_length=100, description="搜索任务标题、提示词、素材名称、路径或任务号")] = None,
    kind: Annotated[str | None, Query(pattern=r"^(image|video)$", description="只返回图片或视频")] = None,
    limit: Annotated[int, Query(ge=1, le=LIBRARY_MAX_LIMIT, description="每页数量")] = LIBRARY_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, le=LIBRARY_MAX_OFFSET, description="分页偏移")] = 0,
    job_id: Annotated[str | None, Query(max_length=120, description="精确匹配来源任务号")] = None,
    generation_item_id: Annotated[str | None, Query(max_length=120, description="精确匹配生成项")] = None,
    output_index: Annotated[int | None, Query(ge=0, le=999, description="精确匹配生成项输出序号")] = None,
    user_id: str | None = None,
) -> dict:
    target_user_id = _library_target_user_id(user, user_id)
    return query_library_entries(
        _library_entries(target_user_id),
        q=q,
        kind=kind,
        limit=limit,
        offset=offset,
        job_id=job_id,
        generation_item_id=generation_item_id,
        output_index=output_index,
    )


@app.get(
    "/api/media/{filename}",
    tags=["作品库"],
    summary="下载或预览生成媒体",
    responses={200: {"content": {"image/*": {}, "video/*": {}, "application/octet-stream": {}}}},
)
def media(filename: str, request: Request, user: Annotated[dict, Depends(current_user)]) -> Response:
    target_user_id = None if user["role"] in {"admin", "super_admin"} else user["id"]
    output = app.state.media_index.lookup(target_user_id, filename)
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
    request: Request,
) -> dict:
    if request.client and request.client.host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=409, detail="Only local clients support browser direct delivery")
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
        raise HTTPException(status_code=500, detail="视频服务原始输出清理失败，服务器暂存已保留，请重试")
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
    request: Request,
) -> dict:
    if request.client and request.client.host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=409, detail="Only local clients support browser direct delivery")
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
        raise HTTPException(status_code=500, detail="视频服务原始输出清理失败，服务器暂存已保留")
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


register_mcp_routes(
    app, current_user=current_user, mutating_user=mutating_user, settings=settings,
    submit_generation=submit_generation, public_job=public_job, listed_workflows=listed_workflows,
    mode_payload=mode_payload, cancel_job=cancel_job, confirm_refine=confirm_refine, skip_refine=skip_refine,
    output_response=output_response, output_available=output_available,
)


ASSET_MEDIA_TYPES = {
    ".js": "application/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".woff2": "font/woff2",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def dist_static_file(relative: str) -> Path | None:
    """Resolve a build-output file below the frontend dist root, rejecting escapes."""
    if not relative or "\x00" in relative:
        return None
    dist_dir = settings.frontend_dist_dir.resolve()
    candidate = (dist_dir / relative).resolve()
    if dist_dir not in candidate.parents or not candidate.is_file():
        return None
    return candidate


@app.get("/assets/{asset_path:path}", include_in_schema=False)
def frontend_asset(asset_path: str) -> FileResponse:
    asset = dist_static_file(f"assets/{asset_path}")
    if asset is None:
        raise HTTPException(status_code=404, detail="前端资源不存在")
    return FileResponse(asset, media_type=ASSET_MEDIA_TYPES.get(asset.suffix.lower()))


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str) -> FileResponse:
    # Public assets copied by the bundler sit at the dist root (images, icons, fonts);
    # only paths that are not real files fall through to the SPA shell.
    if path != "index.html" and (static_file := dist_static_file(path)) is not None:
        return FileResponse(static_file, media_type=ASSET_MEDIA_TYPES.get(static_file.suffix.lower()))
    index = settings.frontend_dist_dir / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="前端未构建")
    return FileResponse(index, headers={"Cache-Control": "no-store, max-age=0, must-revalidate"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=7865, reload=False)
