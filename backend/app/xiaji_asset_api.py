from __future__ import annotations

import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError

from fastapi import BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from .config import settings
from .director_catalog import ArtStyleCatalogError, ensure_art_style_preview
from .director_jobs import create_queued_job, job_asset_image_url, materialize_job_output_file
from .llm_client import LlmError
from .models import JobStatus
from .request_log import write_request_log
from .resource_storage import resource_object_url
from .tts_provider import voice_for_gender
from .workflow_registry import is_image_workflow
from .xiaji_asset_prompts import (
    VOICE_SLOTS,
    character_look_prompt,
    character_portrait_prompt,
    image_options_for_kind,
    image_options_for_look,
    image_options_for_prop_view,
    image_options_for_scene_view,
    look_costume_text,
    prop_view_prompt,
    scene_view_prompt,
)
from .xiaji_analyze import build_voice_define_messages
from .xiaji_art_style import definition_art_style_id, first_art_style_id, settings_art_style_id
from .xiaji_visual_styles import DEFAULT_VISUAL_STYLE, normalize_visual_style, settings_visual_style
from .xiaji_asset_store import ASSET_KINDS, XiajiAssetStore
from .xiaji_episode_run_store import episode_runs_store
from .xiaji_llm_jobs import finish_xiaji_llm_job, llm_failure_response, llm_jobs_store, start_xiaji_llm_job
from .xiaji_project_api import require_xiaji_project

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".webm", ".ogg", ".aac"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_AUDIO_BYTES = 20 * 1024 * 1024
PRIMARY_MEDIA_KINDS = {"portrait", "master"}
VIEW_URL_FIELDS = {
    "reverse": "back_image_url",
    "panorama": "panorama_image_url",
    "turnaround": "turnaround_image_url",
    "detail": "detail_image_url",
}
VIEW_JOBS_KEY = {
    "reverse": "scene_jobs",
    "panorama": "scene_jobs",
    "turnaround": "prop_jobs",
    "detail": "prop_jobs",
}


class XiajiAssetWrite(BaseModel):
    kind: str = Field(max_length=16)
    name: str = Field(min_length=1, max_length=255)
    definition: dict[str, Any] = Field(default_factory=dict)
    source_document_id: str | None = None


class XiajiAssetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    definition: dict[str, Any] | None = None


class XiajiAssetSyncRequest(BaseModel):
    document_id: str | None = None


class XiajiAssetGenerateRequest(BaseModel):
    look_id: str | None = None
    style: str | None = None
    art_style_id: str | None = None
    visual_style: str | None = None
    ethnicity: str | None = None
    model: str | None = None
    scene_view: str | None = None
    prop_view: str | None = None


def _assets(app: Any) -> XiajiAssetStore:
    return app.state.xiaji_asset_store


def _project_settings(app: Any, owner_user_id: str, project_id: str) -> dict[str, Any]:
    project_id = (project_id or "").strip()
    store = getattr(app.state, "xiaji_project_store", None)
    if not project_id or store is None:
        return {}
    try:
        project = store.get_project(project_id, owner_user_id)
    except (KeyError, TypeError, AttributeError):
        return {}
    return project.get("settings") if isinstance(project.get("settings"), dict) else {}


def _project_art_style_id(app: Any, owner_user_id: str, project_id: str) -> str:
    return settings_art_style_id(_project_settings(app, owner_user_id, project_id))


def _project_visual_style(app: Any, owner_user_id: str, project_id: str) -> str:
    return settings_visual_style(_project_settings(app, owner_user_id, project_id))


def _resolved_visual_style(app: Any, asset: dict[str, Any], requested: str = "") -> str:
    definition = asset.get("definition") if isinstance(asset.get("definition"), dict) else {}
    return (
        normalize_visual_style(requested, definition.get("visual_style"))
        or _project_visual_style(
            app,
            str(asset.get("owner_user_id") or ""),
            str(asset.get("project_id") or ""),
        )
        or DEFAULT_VISUAL_STYLE
    )


def _resolved_art_style_id(app: Any, asset: dict[str, Any], requested: str = "") -> str:
    style = first_art_style_id(requested)
    if style:
        return style
    stored = definition_art_style_id(asset.get("definition"))
    if stored:
        return stored
    return _project_art_style_id(
        app,
        str(asset.get("owner_user_id") or ""),
        str(asset.get("project_id") or ""),
    )


def _resolve_image_workflow(app: Any, requested: str | None) -> str:
    from .director_jobs import default_image_workflow_id

    requested_id = (requested or "").strip()
    enabled: list[str] = []
    for item in app.state.grs_provider.enabled_image_workflows() or []:
        workflow_id = getattr(item, "id", None)
        if not workflow_id and isinstance(item, dict):
            workflow_id = item.get("id")
        if workflow_id:
            enabled.append(str(workflow_id))
    if requested_id:
        if requested_id not in enabled:
            raise HTTPException(status_code=422, detail="该生图模型未被启用或不存在")
        workflow_id = requested_id
    else:
        try:
            workflow_id = default_image_workflow_id(app.state.grs_provider)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    available, reason = app.state.grs_provider.availability(workflow_id)
    if not available:
        raise HTTPException(status_code=422, detail=reason or "图片生成不可用")
    if not is_image_workflow(workflow_id):
        raise HTTPException(status_code=422, detail="当前工作流不是图片生成")
    return workflow_id


def _download_image_url(url: str, dest: Path) -> Path | None:
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(str(url), timeout=30) as response:
            dest.write_bytes(response.read())
    except (OSError, URLError, TimeoutError, ValueError):
        dest.unlink(missing_ok=True)
        return None
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.unlink(missing_ok=True)
    return None


def _latest_media(asset: dict[str, Any], media_kind: str, slot: str) -> dict[str, Any]:
    for item in asset.get("media") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("media_kind") or "") == media_kind and str(item.get("slot") or "") == slot:
            return item
    return {}


def _materialize_image_ref(
    app: Any,
    *,
    job_id: str,
    url: str,
    object_key: str,
    stem: str,
) -> str | None:
    jobs = getattr(app.state, "store", None)
    job_key = str(job_id or "").strip()
    if job_key and jobs is not None and hasattr(jobs, "get"):
        try:
            job = jobs.get(job_key)
        except Exception:
            job = None
        if job:
            path = materialize_job_output_file(
                job,
                resource_storage=getattr(app.state, "resource_storage", None),
                kind="image",
            )
            if path is not None:
                return str(path)
    object_key = str(object_key or "").strip()
    storage = getattr(app.state, "resource_storage", None)
    signed = ""
    if object_key and storage is not None:
        getter = getattr(storage, "download_url", None)
        if callable(getter):
            signed = str(getter(object_key) or "").strip()
    candidate = signed or str(url or "").strip()
    if candidate.startswith(("http://", "https://")):
        dest = settings.staging_dir / "xiaji-refs" / f"{stem}.png"
        path = _download_image_url(candidate, dest)
        return str(path) if path is not None else None
    local = Path(candidate) if candidate else None
    if local is not None and local.is_file():
        return str(local)
    return None


def _look_job_ids(asset: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in asset.get("media") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("media_kind") or "") != "look":
            continue
        job_id = str(item.get("job_id") or "").strip()
        if job_id:
            ids.add(job_id)
    for look in (asset.get("definition") or {}).get("looks") or []:
        if not isinstance(look, dict):
            continue
        job_id = str(look.get("job_id") or "").strip()
        if job_id:
            ids.add(job_id)
    return ids


def _character_slot_sources(asset: dict[str, Any], slot: str, *, look_id: str = "") -> tuple[str, str, str]:
    """Portrait and look refs from media slots; never treat a look job as the face."""
    if slot == "look":
        media = _latest_media(asset, "look", look_id) if look_id else {}
        look = next(
            (
                item
                for item in ((asset.get("definition") or {}).get("looks") or [])
                if isinstance(item, dict) and str(item.get("id") or "") == look_id
            ),
            {},
        )
        return (
            str(media.get("job_id") or look.get("job_id") or ""),
            str(media.get("url") or look.get("image_url") or ""),
            str(media.get("object_key") or ""),
        )
    media = _latest_media(asset, "portrait", "portrait")
    look_jobs = _look_job_ids(asset)
    fallback_job = str(asset.get("image_job_id") or "").strip()
    if fallback_job in look_jobs:
        fallback_job = ""
    fallback_url = str(asset.get("image_url") or "").strip()
    look_urls = {
        str(item.get("url") or "").strip()
        for item in (asset.get("media") or [])
        if isinstance(item, dict) and str(item.get("media_kind") or "") == "look" and item.get("url")
    }
    for look in (asset.get("definition") or {}).get("looks") or []:
        if isinstance(look, dict) and look.get("image_url"):
            look_urls.add(str(look.get("image_url") or "").strip())
    if fallback_url in look_urls:
        fallback_url = ""
    return (
        str(media.get("job_id") or fallback_job or ""),
        str(media.get("url") or fallback_url or ""),
        str(media.get("object_key") or asset.get("image_object_key") or ""),
    )


def _scene_slot_sources(asset: dict[str, Any], slot: str) -> tuple[str, str, str]:
    definition = asset.get("definition") if isinstance(asset.get("definition"), dict) else {}
    jobs_map = definition.get("scene_jobs") if isinstance(definition.get("scene_jobs"), dict) else {}
    if slot == "master":
        media = _latest_media(asset, "master", "master")
        return (
            str(asset.get("image_job_id") or jobs_map.get("master") or media.get("job_id") or ""),
            str(asset.get("image_url") or media.get("url") or ""),
            str(asset.get("image_object_key") or media.get("object_key") or ""),
        )
    media = _latest_media(asset, slot, slot)
    url_field = VIEW_URL_FIELDS.get(slot, "")
    return (
        str(jobs_map.get(slot) or media.get("job_id") or ""),
        str(definition.get(url_field) or media.get("url") or ""),
        str(media.get("object_key") or ""),
    )


def _scene_view_reference_paths(app: Any, asset: dict[str, Any], view: str) -> tuple[list[str], bool, bool]:
    """Match sourceXd: reverse uses master only; 360 uses master then reverse."""
    master_job, master_url, master_key = _scene_slot_sources(asset, "master")
    master_path = _materialize_image_ref(
        app,
        job_id=master_job,
        url=master_url,
        object_key=master_key,
        stem=f"{asset['id']}-front",
    )
    paths: list[str] = []
    has_master = bool(master_path)
    if master_path:
        paths.append(master_path)
    has_reverse = False
    if view == "panorama":
        reverse_job, reverse_url, reverse_key = _scene_slot_sources(asset, "reverse")
        reverse_path = _materialize_image_ref(
            app,
            job_id=reverse_job,
            url=reverse_url,
            object_key=reverse_key,
            stem=f"{asset['id']}-reverse",
        )
        if reverse_path:
            paths.append(reverse_path)
            has_reverse = True
    return paths, has_master, has_reverse


def _art_style_preview_reference_path(style_id: str) -> str | None:
    needle = (style_id or "").strip()
    if not needle:
        return None
    try:
        path = ensure_art_style_preview(needle)
    except (KeyError, ArtStyleCatalogError, OSError):
        return None
    if path.is_file() and path.stat().st_size > 0:
        return str(path)
    return None


def _character_portrait_reference_path(app: Any, asset: dict[str, Any]) -> str | None:
    job_id, url, object_key = _character_slot_sources(asset, "portrait")
    return _materialize_image_ref(
        app,
        job_id=job_id,
        url=url,
        object_key=object_key,
        stem=f"{asset['id']}-portrait",
    )


def _prop_master_reference_path(app: Any, asset: dict[str, Any]) -> str | None:
    media = _latest_media(asset, "reference", "reference") or _latest_media(asset, "master", "master")
    return _materialize_image_ref(
        app,
        job_id=str(asset.get("image_job_id") or media.get("job_id") or ""),
        url=str(asset.get("image_url") or media.get("url") or ""),
        object_key=str(asset.get("image_object_key") or media.get("object_key") or ""),
        stem=f"{asset['id']}-prop-master",
    )


def _submit_asset_image_job(
    app: Any,
    owner_user_id: str,
    asset_id: str,
    payload: XiajiAssetGenerateRequest,
) -> dict[str, Any]:
    store = _assets(app)
    asset = _asset_or_404(store, asset_id, owner_user_id)
    if asset["kind"] == "voice":
        raise HTTPException(status_code=422, detail="声线请使用试听生成或上传参考音频")
    workflow_id = _resolve_image_workflow(app, payload.model)
    style = _resolved_art_style_id(app, asset, payload.art_style_id or payload.style or "")
    visual_style = _resolved_visual_style(app, asset, payload.visual_style or "")
    current_def = dict(asset.get("definition") or {})
    patched: dict[str, Any] = {}
    if style and definition_art_style_id(current_def) != style:
        patched["art_style_id"] = style
    if visual_style and normalize_visual_style(current_def.get("visual_style")) != visual_style:
        patched["visual_style"] = visual_style
    if patched:
        asset = store.update_asset(asset_id, owner_user_id, definition=patched)
    ethnicity = (payload.ethnicity or "").strip()
    look_id = (payload.look_id or "").strip()
    look = None
    references: list[str] = []
    if look_id:
        looks = asset.get("definition", {}).get("looks") or []
        look = next((item for item in looks if isinstance(item, dict) and item.get("id") == look_id), None)
        if look is None:
            raise HTTPException(status_code=422, detail="找不到该造型")
        if not look_costume_text(look):
            raise HTTPException(status_code=422, detail="请先填写外观描述，造型图需要服装关键词")
        portrait_path = _character_portrait_reference_path(app, asset)
        if not portrait_path:
            raise HTTPException(
                status_code=422,
                detail="请先生成或上传肖像，造型图需要把它作为身份锚点传入",
            )
        references = [portrait_path]
        prompt = character_look_prompt(asset, look, style=style, visual_style=visual_style, ethnicity=ethnicity)
        title = f"导台2 造型 · {asset['name']} · {look.get('name') or '造型'}"
        media_kind = "look"
        slot = look_id
        options = image_options_for_look()
    elif asset["kind"] == "character":
        style_path = _art_style_preview_reference_path(style)
        if style and not style_path:
            raise HTTPException(status_code=422, detail="无法加载画风预览图，生成头像需要把风格图作为参考图传入")
        references = [style_path] if style_path else []
        prompt = character_portrait_prompt(
            asset,
            style=style,
            visual_style=visual_style,
            ethnicity=ethnicity,
            has_style_reference=bool(style_path),
        )
        title = f"导台2 肖像 · {asset['name']}"
        media_kind = "portrait"
        slot = "portrait"
        options = image_options_for_kind("character")
    elif asset["kind"] == "scene":
        view = (payload.scene_view or "master").strip() or "master"
        if view not in {"master", "reverse", "panorama"}:
            raise HTTPException(status_code=422, detail="场景视角无效，请使用 master、reverse 或 panorama")
        has_master = False
        has_reverse = False
        if view in {"reverse", "panorama"}:
            references, has_master, has_reverse = _scene_view_reference_paths(app, asset, view)
            if not has_master:
                slot_name = "背面图" if view == "reverse" else "360全景"
                raise HTTPException(
                    status_code=422,
                    detail=f"请先生成或上传正面源图，{slot_name}需要把它作为 REFERENCE 1 传入",
                )
        prompt = scene_view_prompt(
            asset,
            view,
            style=style,
            visual_style=visual_style,
            has_master_reference=has_master and view != "master",
            has_reverse_reference=has_reverse and view == "panorama",
        )
        view_titles = {"master": "正面源图", "reverse": "背面", "panorama": "360全景"}
        title = f"导台2 场景{view_titles[view]} · {asset['name']}"
        media_kind = view
        slot = view
        options = image_options_for_scene_view(view)
    else:
        view = (payload.prop_view or "master").strip() or "master"
        if view not in {"master", "turnaround", "detail"}:
            raise HTTPException(status_code=422, detail="道具视角无效，请使用 master、turnaround 或 detail")
        has_master = False
        if view in {"turnaround", "detail"}:
            master_path = _prop_master_reference_path(app, asset)
            if not master_path:
                slot_name = "转面三视图" if view == "turnaround" else "细节特写"
                raise HTTPException(
                    status_code=422,
                    detail=f"请先生成或上传主视图，{slot_name}需要把它作为 REFERENCE 1 传入",
                )
            references = [master_path]
            has_master = True
        prompt = prop_view_prompt(
            asset,
            view,
            style=style,
            visual_style=visual_style,
            has_master_reference=has_master and view != "master",
        )
        view_titles = {"master": "主视图", "turnaround": "转面三视图", "detail": "细节特写"}
        title = f"导台2 道具{view_titles[view]} · {asset['name']}"
        media_kind = view
        slot = view
        options = image_options_for_prop_view(view)
    try:
        job = create_queued_job(
            app.state.store,
            owner_user_id=owner_user_id,
            mode=workflow_id,
            prompt=prompt,
            options=options,
            title=title,
            references=references,
        )
    except ValueError as error:
        if slot == "panorama":
            try:
                job = create_queued_job(
                    app.state.store,
                    owner_user_id=owner_user_id,
                    mode=workflow_id,
                    prompt=prompt,
                    options=image_options_for_kind("scene"),
                    title=title,
                    references=references,
                )
            except ValueError as inner:
                raise HTTPException(status_code=422, detail=str(inner)) from inner
        else:
            raise HTTPException(status_code=422, detail=str(error)) from error
    store.add_media(
        asset_id,
        owner_user_id,
        media_kind=media_kind,
        slot=slot,
        job_id=job["id"],
        prompt=prompt,
        model=workflow_id,
    )
    if look is not None:
        current = store.get_asset(asset_id, owner_user_id)
        looks = list(current.get("definition", {}).get("looks") or [])
        for item in looks:
            if isinstance(item, dict) and item.get("id") == look_id:
                item["job_id"] = job["id"]
        store.update_asset(
            asset_id,
            owner_user_id,
            definition={"looks": looks},
            clear_error=True,
        )
    elif (asset["kind"] == "scene" and slot in {"reverse", "panorama"}) or (
        asset["kind"] == "prop" and slot in {"turnaround", "detail"}
    ):
        jobs_key = "scene_jobs" if asset["kind"] == "scene" else "prop_jobs"
        definition = dict(asset.get("definition") or {})
        jobs_map = dict(definition.get(jobs_key) or {})
        jobs_map[slot] = job["id"]
        definition[jobs_key] = jobs_map
        store.update_asset(
            asset_id,
            owner_user_id,
            definition=definition,
            clear_error=True,
        )
    else:
        store.update_asset(
            asset_id,
            owner_user_id,
            status="generating",
            image_job_id=job["id"],
            clear_error=True,
        )
    record = store.get_asset(asset_id, owner_user_id)
    record["_queued_job"] = job
    return record


def _asset_or_404(store: XiajiAssetStore, asset_id: str, owner_user_id: str) -> dict[str, Any]:
    try:
        return store.get_asset(asset_id, owner_user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="资产不存在") from error


def _fetch_jobs_batch(jobs_store: Any, job_ids: set[str]) -> dict[str, Any]:
    if not job_ids:
        return {}
    results: dict[str, Any] = {}

    def _fetch_one(jid: str):
        try:
            getter = jobs_store.get
            try:
                return jid, getter(jid, include_references=True)
            except TypeError:
                return jid, getter(jid)
        except Exception:
            return jid, None

    workers = min(len(job_ids), 16)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for jid, job in executor.map(_fetch_one, job_ids):
            if job is not None:
                results[jid] = job
    return results


def _hydrate_asset(
    app: Any,
    asset: dict[str, Any],
    owner_user_id: str,
    jobs_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store: XiajiAssetStore = app.state.xiaji_asset_store
    jobs = app.state.store
    success_status = {JobStatus.SUCCEEDED.value, JobStatus.PARTIAL.value}
    failed_status = {JobStatus.FAILED.value, JobStatus.INTERRUPTED.value, JobStatus.CANCELLED.value}
    running_status = {JobStatus.QUEUED.value, JobStatus.RUNNING.value}

    def _get_job(jid: str) -> dict[str, Any] | None:
        if jobs_cache is not None:
            return jobs_cache.get(jid)
        try:
            return jobs.get(jid)
        except KeyError:
            return None

    def _reload() -> dict[str, Any]:
        return store.get_asset(asset["id"], owner_user_id)

    def _apply_primary(url: str | None, status: str, job_id: str, error: str | None = None) -> None:
        nonlocal asset
        current = _reload()
        current_job = str(current.get("image_job_id") or "").strip()
        if current_job and current_job != job_id:
            return
        if status in success_status and url:
            asset = store.update_asset(
                current["id"],
                owner_user_id,
                status="ready",
                image_url=url,
                clear_error=True,
            )
        elif status in failed_status and current_job == job_id:
            asset = store.update_asset(
                current["id"],
                owner_user_id,
                status="failed",
                error=error or "资产生成失败",
            )
        elif status in running_status and current.get("status") != "generating" and current_job == job_id:
            asset = store.update_asset(current["id"], owner_user_id, status="generating")

    def _apply_look(look_id: str, url: str | None, status: str, job_id: str) -> None:
        nonlocal asset
        if not look_id:
            return
        current = _reload()
        looks = list((current.get("definition") or {}).get("looks") or [])
        changed = False
        for look in looks:
            if not isinstance(look, dict) or str(look.get("id") or "") != look_id:
                continue
            if status in success_status and url:
                if look.get("image_url") != url or look.get("job_id"):
                    look["image_url"] = url
                    look["job_id"] = ""
                    changed = True
            elif status in failed_status and str(look.get("job_id") or "") == job_id:
                look["job_id"] = ""
                changed = True
        if changed:
            asset = store.update_asset(current["id"], owner_user_id, definition={"looks": looks})

    def _apply_view(view: str, url: str | None, status: str) -> None:
        nonlocal asset
        field = VIEW_URL_FIELDS.get(view)
        jobs_key = VIEW_JOBS_KEY.get(view)
        if not field or not jobs_key:
            return
        current = _reload()
        definition = dict(current.get("definition") or {})
        extra_jobs = dict(definition.get(jobs_key) or {}) if isinstance(definition.get(jobs_key), dict) else {}
        extra_changed = False
        if status in success_status and url:
            if definition.get(field) != url:
                definition[field] = url
                extra_changed = True
            if view in extra_jobs:
                extra_jobs.pop(view, None)
                extra_changed = True
        elif status in failed_status and view in extra_jobs:
            extra_jobs.pop(view, None)
            extra_changed = True
        if extra_changed:
            definition[jobs_key] = extra_jobs
            asset = store.update_asset(current["id"], owner_user_id, definition=definition)

    applied_jobs: set[str] = set()
    seen_slots: set[tuple[str, str]] = set()
    for item in list(asset.get("media") or []):
        if not isinstance(item, dict):
            continue
        job_id = str(item.get("job_id") or "").strip()
        kind = str(item.get("media_kind") or "").strip()
        slot = str(item.get("slot") or kind).strip()
        slot_key = (kind, slot)
        if slot_key in seen_slots:
            continue
        seen_slots.add(slot_key)
        existing_url = str(item.get("url") or "").strip()
        if existing_url:
            if kind == "look" and slot:
                _apply_look(slot, existing_url, JobStatus.SUCCEEDED.value, job_id)
            elif kind in VIEW_URL_FIELDS:
                _apply_view(kind, existing_url, JobStatus.SUCCEEDED.value)
            elif kind in PRIMARY_MEDIA_KINDS and not (asset.get("image_url") or asset.get("image_object_key")):
                _apply_primary(existing_url, JobStatus.SUCCEEDED.value, job_id)
            if job_id:
                applied_jobs.add(job_id)
            continue
        if not job_id:
            continue
        job = _get_job(job_id)
        if not job:
            continue
        status = str(job.get("status") or "")
        url = job_asset_image_url(job, kind="image", resource_storage=app.state.resource_storage)
        if status in success_status and url:
            store.complete_media_job(job_id, url=url)
            applied_jobs.add(job_id)
            if kind == "look":
                _apply_look(slot, url, status, job_id)
            elif kind in VIEW_URL_FIELDS:
                _apply_view(kind, url, status)
            elif kind in PRIMARY_MEDIA_KINDS:
                _apply_primary(url, status, job_id)
        elif status in failed_status:
            applied_jobs.add(job_id)
            if kind == "look":
                _apply_look(slot, None, status, job_id)
            elif kind in VIEW_URL_FIELDS:
                _apply_view(kind, None, status)
            elif kind in PRIMARY_MEDIA_KINDS:
                _apply_primary(None, status, job_id, str(job.get("error") or "资产生成失败"))
        elif status in running_status and kind in PRIMARY_MEDIA_KINDS:
            _apply_primary(None, status, job_id)

    asset = _reload()
    job_id = str(asset.get("image_job_id") or "").strip()
    media_for_primary = next(
        (
            item
            for item in (asset.get("media") or [])
            if isinstance(item, dict) and str(item.get("job_id") or "") == job_id
        ),
        None,
    )
    primary_kind = str((media_for_primary or {}).get("media_kind") or "")
    look_holds_primary = any(
        isinstance(look, dict) and str(look.get("job_id") or "") == job_id
        for look in ((asset.get("definition") or {}).get("looks") or [])
    )
    if (
        job_id
        and job_id not in applied_jobs
        and primary_kind not in ({"look"} | set(VIEW_URL_FIELDS))
        and not look_holds_primary
    ):
        status_str = str(asset.get("status") or "")
        has_image = bool(asset.get("image_url") or asset.get("image_object_key"))
        need_job_check = bool(
            job_id and (status_str == "generating" or not has_image or status_str not in {"ready", "failed"})
        )
        if need_job_check:
            job = _get_job(job_id)
            if job:
                status = str(job.get("status") or "")
                url = job_asset_image_url(job, kind="image", resource_storage=app.state.resource_storage)
                _apply_primary(url, status, job_id, str(job.get("error") or "资产生成失败"))
                applied_jobs.add(job_id)

    asset = _reload()
    for look in list((asset.get("definition") or {}).get("looks") or []):
        if not isinstance(look, dict):
            continue
        look_job = str(look.get("job_id") or "").strip()
        if not look_job or look_job in applied_jobs:
            continue
        job = _get_job(look_job)
        if not job:
            continue
        status = str(job.get("status") or "")
        url = job_asset_image_url(job, kind="image", resource_storage=app.state.resource_storage)
        _apply_look(str(look.get("id") or ""), url, status, look_job)

    view_job_specs = (
        ("scene_jobs", {"reverse": "back_image_url", "panorama": "panorama_image_url"}),
        ("prop_jobs", {"turnaround": "turnaround_image_url", "detail": "detail_image_url"}),
    )
    for jobs_key, url_fields in view_job_specs:
        definition = dict(_reload().get("definition") or {})
        extra_jobs = definition.get(jobs_key) if isinstance(definition.get(jobs_key), dict) else {}
        for view, view_job_id in list(extra_jobs.items()):
            job_key = str(view_job_id or "").strip()
            if not job_key or job_key in applied_jobs:
                continue
            field = url_fields.get(str(view))
            if field and definition.get(field):
                _apply_view(str(view), str(definition.get(field)), JobStatus.SUCCEEDED.value)
                continue
            job = _get_job(job_key)
            if not job:
                continue
            status = str(job.get("status") or "")
            url = job_asset_image_url(job, kind="image", resource_storage=app.state.resource_storage)
            _apply_view(str(view), url, status)

    asset = _reload()
    latest_urls: dict[tuple[str, str], str] = {}
    for item in list(asset.get("media") or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("media_kind") or "").strip()
        slot = str(item.get("slot") or kind).strip()
        url = str(item.get("url") or "").strip()
        if not url or (kind, slot) in latest_urls:
            continue
        latest_urls[(kind, slot)] = url
    portrait_url = latest_urls.get(("portrait", "portrait")) or latest_urls.get(("master", "master"))
    portrait_media = next(
        (
            item
            for item in (asset.get("media") or [])
            if isinstance(item, dict)
            and str(item.get("media_kind") or "") in PRIMARY_MEDIA_KINDS
            and str(item.get("url") or "") == portrait_url
        ),
        None,
    )
    portrait_job = str((portrait_media or {}).get("job_id") or "").strip()
    look_jobs = {
        str(item.get("job_id") or "").strip()
        for item in (asset.get("media") or [])
        if isinstance(item, dict) and str(item.get("media_kind") or "") == "look" and item.get("job_id")
    }
    current_job = str(asset.get("image_job_id") or "").strip()
    if portrait_url and (
        str(asset.get("image_url") or "") != portrait_url
        or (portrait_job and current_job != portrait_job)
        or current_job in look_jobs
    ):
        asset = store.update_asset(
            asset["id"],
            owner_user_id,
            image_url=portrait_url,
            image_job_id=portrait_job if portrait_job else ("" if current_job in look_jobs else None),
            status="ready",
            clear_error=True,
        )
    looks = list((asset.get("definition") or {}).get("looks") or [])
    look_changed = False
    for look in looks:
        if not isinstance(look, dict):
            continue
        look_id = str(look.get("id") or "")
        look_url = latest_urls.get(("look", look_id))
        if look_url and look.get("image_url") != look_url:
            look["image_url"] = look_url
            look["job_id"] = ""
            look_changed = True
    if look_changed:
        asset = store.update_asset(asset["id"], owner_user_id, definition={"looks": looks})
    return _reload()


def _with_media_urls(asset: dict[str, Any]) -> dict[str, Any]:
    asset_id = asset["id"]
    latest_urls: dict[tuple[str, str], str] = {}
    for item in asset.get("media") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("media_kind") or "").strip()
        slot = str(item.get("slot") or kind).strip()
        url = str(item.get("url") or "").strip()
        if url and (kind, slot) not in latest_urls:
            latest_urls[(kind, slot)] = url
    portrait_url = latest_urls.get(("portrait", "portrait")) or latest_urls.get(("master", "master"))
    if portrait_url:
        asset["image_url"] = portrait_url
    elif not asset.get("image_url"):
        if asset.get("image_object_key"):
            asset["image_url"] = f"/api/xiaji/assets/{asset_id}/image"
        elif asset.get("status") == "ready" and asset.get("image_job_id"):
            asset["image_url"] = f"/api/jobs/{asset['image_job_id']}/outputs/0/download"
    looks = (asset.get("definition") or {}).get("looks")
    if isinstance(looks, list):
        for look in looks:
            if not isinstance(look, dict):
                continue
            look_url = latest_urls.get(("look", str(look.get("id") or "")))
            if look_url:
                look["image_url"] = look_url
    for item in asset.get("media") or []:
        if item.get("url"):
            continue
        if item.get("object_key"):
            item["url"] = f"/api/xiaji/assets/{asset_id}/media/{item['id']}"
    for slot in asset.get("voice_slots") or []:
        if slot.get("media_id") and not slot.get("url"):
            slot["url"] = f"/api/xiaji/assets/{asset_id}/media/{slot['media_id']}"
    return asset


async def _enqueue_queued_job(worker: Any, job: dict[str, Any]) -> None:
    job_id = str(job.get("id") or "")
    if not job_id or worker is None:
        return
    items = ((job.get("rounds") or [{}])[-1].get("generation_items") or [])
    if items and items[0].get("executor") == "grs":
        for item in items:
            if item.get("status") == JobStatus.QUEUED.value:
                worker.enqueue_generation(item["id"])
        return
    await worker.enqueue(job_id)


def _stamp_media_job_status(app: Any, asset: dict[str, Any], jobs_cache: dict[str, Any] | None = None) -> dict[str, Any]:
    jobs = getattr(app.state, "store", None)
    success_status = {JobStatus.SUCCEEDED.value, JobStatus.PARTIAL.value}
    failed_status = {JobStatus.FAILED.value, JobStatus.INTERRUPTED.value, JobStatus.CANCELLED.value}
    for item in asset.get("media") or []:
        if not isinstance(item, dict):
            continue
        job_id = str(item.get("job_id") or "").strip()
        if str(item.get("url") or "").strip():
            item["job_status"] = JobStatus.SUCCEEDED.value
            item.pop("job_error", None)
            continue
        if not job_id:
            item["job_status"] = ""
            item.pop("job_error", None)
            continue
        job = jobs_cache.get(job_id) if jobs_cache is not None else None
        if job is None and jobs is not None and hasattr(jobs, "get"):
            try:
                job = jobs.get(job_id)
            except Exception:
                job = None
        if not job:
            item["job_status"] = "unknown"
            continue
        status = str(job.get("status") or "")
        item["job_status"] = status
        error = str(job.get("error") or "").strip()
        if error and status in failed_status:
            item["job_error"] = error
        elif status in success_status:
            item.pop("job_error", None)
    return asset


def _public_asset(app: Any, asset: dict[str, Any], owner_user_id: str, jobs_cache: dict[str, Any] | None = None) -> dict[str, Any]:
    hydrated = _with_media_urls(_hydrate_asset(app, asset, owner_user_id, jobs_cache))
    return _stamp_media_job_status(app, hydrated, jobs_cache)


SLOT_LABELS = {
    "portrait": "肖像",
    "look": "造型",
    "master": "主图",
    "reverse": "背面",
    "panorama": "360全景",
    "turnaround": "转面",
    "detail": "特写",
    "sketch": "草图",
    "render": "精绘",
    "video": "视频",
    "ingest": "内容导入",
    "script": "生成脚本",
    "voice": "声线定义",
    "auto_run": "整集自动生成",
    "compose": "合成成片",
}


def _collect_project_job_refs(app: Any, owner_user_id: str, project_id: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(job_id: str, *, source: str, target: str, slot: str, bound_url: str = "", created_at: str = "") -> None:
        key = str(job_id or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        refs.append(
            {
                "job_id": key,
                "source": source,
                "target": target,
                "slot": slot,
                "slot_label": SLOT_LABELS.get(slot, slot or "任务"),
                "bound_url": bound_url,
                "created_at": created_at,
            }
        )

    for asset in _assets(app).list_assets(owner_user_id, project_id):
        name = str(asset.get("name") or "资产")
        kind = str(asset.get("kind") or "")
        created = str(asset.get("updated_at") or "")
        for item in asset.get("media") or []:
            if not isinstance(item, dict) or item.get("media_kind") == "voice_sample":
                continue
            _add(
                str(item.get("job_id") or ""),
                source="asset",
                target=f"{kind} · {name}",
                slot=str(item.get("media_kind") or item.get("slot") or ""),
                bound_url=str(item.get("url") or ""),
                created_at=str(item.get("created_at") or created),
            )
        _add(
            str(asset.get("image_job_id") or ""),
            source="asset",
            target=f"{kind} · {name}",
            slot="portrait" if kind == "character" else "master",
            bound_url=str(asset.get("image_url") or ""),
            created_at=created,
        )
        for look in (asset.get("definition") or {}).get("looks") or []:
            if not isinstance(look, dict):
                continue
            _add(
                str(look.get("job_id") or ""),
                source="asset",
                target=f"{kind} · {name} · {look.get('name') or '造型'}",
                slot="look",
                bound_url=str(look.get("image_url") or ""),
                created_at=created,
            )
    episode_store = getattr(app.state, "xiaji_episode_store", None)
    if episode_store is not None:
        for episode in episode_store.list_episodes(owner_user_id, project_id):
            ep_title = f"第{episode.get('number')}集 {episode.get('title') or ''}".strip()
            for beat in episode.get("beats") or []:
                if not isinstance(beat, dict):
                    continue
                heading = str(beat.get("heading") or f"镜头 {beat.get('sequence')}")
                target = f"{ep_title} · {heading}"
                for slot, job_key, url_key in (
                    ("sketch", "sketch_job_id", "sketch_url"),
                    ("render", "render_job_id", "render_url"),
                    ("video", "video_job_id", "video_url"),
                ):
                    _add(
                        str(beat.get(job_key) or ""),
                        source="beat",
                        target=target,
                        slot=slot,
                        bound_url=str(beat.get(url_key) or ""),
                        created_at=str(episode.get("updated_at") or ""),
                    )
    llm_store = llm_jobs_store(app)
    if llm_store is not None:
        for item in llm_store.list_project_jobs(owner_user_id, project_id):
            _add(
                str(item["job_id"]),
                source="llm",
                target=str(item.get("target") or item.get("title") or "大模型"),
                slot=str(item.get("kind") or "llm"),
                bound_url="",
                created_at=str(item.get("created_at") or ""),
            )
    run_store = episode_runs_store(app)
    if run_store is not None:
        for item in run_store.list_project_runs(owner_user_id, project_id):
            _add(
                str(item["id"]),
                source="auto_run",
                target=str((item.get("cursor") or {}).get("step") or "整集自动生成"),
                slot="auto_run",
                bound_url="",
                created_at=str(item.get("created_at") or ""),
            )
    refs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return refs


def _job_reference_count(job: dict[str, Any]) -> int:
    """Count attached stills from the job row or its rounds."""
    count = 0
    refs = job.get("references")
    if isinstance(refs, list):
        count = max(count, len(refs))
    try:
        count = max(count, int(job.get("reference_count") or 0))
    except (TypeError, ValueError):
        pass
    for rnd in job.get("rounds") or []:
        if not isinstance(rnd, dict):
            continue
        rrefs = rnd.get("references")
        if isinstance(rrefs, list):
            count = max(count, len(rrefs))
        try:
            count = max(count, int(rnd.get("reference_count") or 0))
        except (TypeError, ValueError):
            pass
    return count


def _job_input_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    job_id = str(job.get("id") or "").strip()
    count = _job_reference_count(job)
    references = [
        {
            "index": index,
            "url": f"/api/jobs/{job_id}/references/{index}",
            "label": "REFERENCE 1（正面源图）" if index == 1 else f"参考图 {index}",
        }
        for index in range(1, count + 1)
    ]
    options = job.get("options") if isinstance(job.get("options"), dict) else {}
    parameters: list[dict[str, Any]] = [
        {"name": "mode", "label": "工作流", "value": job.get("mode") or ""},
        {"name": "title", "label": "任务标题", "value": job.get("title") or ""},
        {"name": "prompt", "label": "创作提示词", "value": job.get("prompt") or ""},
    ]
    if job.get("negative_prompt"):
        parameters.append({"name": "negative_prompt", "label": "负面提示词", "value": job.get("negative_prompt")})
    if job.get("image_size"):
        parameters.append({"name": "image_size", "label": "图片尺寸", "value": job.get("image_size")})
    if job.get("media_type"):
        parameters.append({"name": "media_type", "label": "媒体类型", "value": job.get("media_type")})
    if job.get("stage"):
        parameters.append({"name": "stage", "label": "阶段", "value": job.get("stage")})
    parameters.append({"name": "references", "label": "参考图数量", "value": count})
    for name, value in options.items():
        parameters.append({"name": f"options.{name}", "label": str(name), "value": value})
    return {
        "reference_count": count,
        "references": references,
        "options": options,
        "negative_prompt": job.get("negative_prompt") or "",
        "image_size": job.get("image_size"),
        "parameters": parameters,
    }


def _job_list_item(app: Any, ref: dict[str, Any], job: dict[str, Any] | None) -> dict[str, Any]:
    preview = ""
    outputs: list[dict[str, Any]] = []
    snapshot = {
        "reference_count": 0,
        "references": [],
        "options": {},
        "negative_prompt": "",
        "image_size": None,
        "parameters": [],
    }
    if job:
        snapshot = _job_input_snapshot(job)
        preview = job_asset_image_url(job, kind="image", resource_storage=app.state.resource_storage) or ""
        if not preview:
            preview = job_asset_image_url(job, kind="video", resource_storage=app.state.resource_storage) or ""
        for output in job.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            outputs.append(
                {
                    "kind": output.get("kind"),
                    "cloud_url": output.get("cloud_url"),
                    "download_url": output.get("download_url") or (
                        f"/api/jobs/{job['id']}/outputs/0/download" if job.get("id") else None
                    ),
                    "path": output.get("path"),
                }
            )
    return {
        **ref,
        "id": ref["job_id"],
        "title": (job or {}).get("title") or ref["target"],
        "status": (job or {}).get("status") or "unknown",
        "mode": (job or {}).get("mode"),
        "prompt": (job or {}).get("prompt") or "",
        "error": (job or {}).get("error"),
        "progress": (job or {}).get("progress") or 0,
        "preview_url": preview or ref.get("bound_url") or "",
        "outputs": outputs,
        "job_created_at": (job or {}).get("created_at"),
        "job_updated_at": (job or {}).get("updated_at"),
        "missing": job is None,
        **snapshot,
    }


def register_xiaji_asset_routes(app: Any, *, current_user: Callable, mutating_user: Callable) -> None:
    router = APIRouter(prefix="/api/xiaji", tags=["导台2"])

    @router.get("/assets", summary="列出导台2 资产")
    def list_assets(
        project_id: str = Query(..., description="导台2 项目 ID"),
        user: dict = Depends(current_user),
        kind: str | None = None,
    ) -> list[dict]:
        require_xiaji_project(app, project_id, user["id"])
        if kind and kind not in ASSET_KINDS:
            raise HTTPException(status_code=422, detail="资产类型无效")
        items = _assets(app).list_assets(user["id"], project_id, kind)
        if not items:
            return []

        view_job_specs = (
            ("scene_jobs", {"reverse": "back_image_url", "panorama": "panorama_image_url"}),
            ("prop_jobs", {"turnaround": "turnaround_image_url", "detail": "detail_image_url"}),
        )
        job_ids_to_fetch: set[str] = set()
        for asset in items:
            job_id = str(asset.get("image_job_id") or "").strip()
            status_str = str(asset.get("status") or "")
            has_image = bool(asset.get("image_url") or asset.get("image_object_key"))
            if job_id and (status_str == "generating" or not has_image or status_str not in {"ready", "failed"}):
                job_ids_to_fetch.add(job_id)
            definition = dict(asset.get("definition") or {})
            for look in definition.get("looks") or []:
                if isinstance(look, dict) and look.get("job_id"):
                    job_ids_to_fetch.add(str(look["job_id"]).strip())
            for item in asset.get("media") or []:
                if not isinstance(item, dict):
                    continue
                media_job = str(item.get("job_id") or "").strip()
                if media_job and not str(item.get("url") or "").strip():
                    job_ids_to_fetch.add(media_job)
            for jobs_key, url_fields in view_job_specs:
                extra_jobs = definition.get(jobs_key) or {}
                if isinstance(extra_jobs, dict):
                    for view, view_job_id in extra_jobs.items():
                        field = url_fields.get(str(view))
                        if not (field and definition.get(field)) and view_job_id:
                            job_ids_to_fetch.add(str(view_job_id).strip())

        jobs_cache = _fetch_jobs_batch(app.state.store, job_ids_to_fetch) if job_ids_to_fetch else {}
        return [_public_asset(app, item, user["id"], jobs_cache) for item in items]

    @router.post("/assets/sync", summary="把内容库角色/场景/道具转入资产库")
    def sync_assets(
        payload: XiajiAssetSyncRequest,
        project_id: str = Query(..., description="导台2 项目 ID"),
        user: dict = Depends(mutating_user),
    ) -> dict:
        require_xiaji_project(app, project_id, user["id"])
        store = _assets(app)
        if payload.document_id:
            rows = [(payload.document_id, analysis)] if (analysis := store.latest_analysis(user["id"], project_id, payload.document_id)[1]) else []
            document_id = payload.document_id
            if not rows:
                raise HTTPException(status_code=422, detail="这篇文稿还没有分析结果")
        else:
            rows = store.list_analyses(user["id"], project_id)
            document_id = rows[-1][0] if rows else None
            if not rows:
                raise HTTPException(status_code=422, detail="请先在内容库完成导入分析")
        created = 0
        transferred = {"characters": 0, "scenes": 0, "props": 0}
        result: dict[str, Any] = {}
        for doc_id, analysis in rows:
            result = store.sync_from_analysis(user["id"], analysis, project_id=project_id, document_id=doc_id)
            created += int(result.get("created") or 0)
            counts = result.get("transferred") or {}
            for key in transferred:
                transferred[key] += int(counts.get(key) or 0)
        assets = [_public_asset(app, item, user["id"]) for item in store.list_assets(user["id"], project_id)]
        return {
            "created": created,
            "document_id": document_id,
            "transferred": transferred if payload.document_id else {
                "characters": sum(1 for item in assets if item.get("kind") == "character"),
                "scenes": sum(1 for item in assets if item.get("kind") == "scene"),
                "props": sum(1 for item in assets if item.get("kind") == "prop"),
            },
            "assets": assets,
        }

    @router.post("/assets", status_code=201, summary="新建资产")
    def create_asset(
        payload: XiajiAssetWrite,
        project_id: str = Query(..., description="导台2 项目 ID"),
        user: dict = Depends(mutating_user),
    ) -> dict:
        project = require_xiaji_project(app, project_id, user["id"])
        definition = dict(payload.definition or {})
        settings = project.get("settings") if isinstance(project.get("settings"), dict) else {}
        if not definition_art_style_id(definition):
            inherited = settings_art_style_id(settings)
            if inherited:
                definition["art_style_id"] = inherited
        if not normalize_visual_style(definition.get("visual_style")):
            inherited_visual = settings_visual_style(settings)
            if inherited_visual:
                definition["visual_style"] = inherited_visual
        try:
            return _public_asset(
                app,
                _assets(app).create_asset(
                    user["id"],
                    project_id=project_id,
                    kind=payload.kind,
                    name=payload.name,
                    definition=definition,
                    source_document_id=payload.source_document_id,
                ),
                user["id"],
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/assets/{asset_id}", summary="读取资产")
    def get_asset(asset_id: str, user: dict = Depends(current_user)) -> dict:
        return _public_asset(app, _asset_or_404(_assets(app), asset_id, user["id"]), user["id"])

    @router.put("/assets/{asset_id}", summary="更新资产定义")
    def update_asset(asset_id: str, payload: XiajiAssetUpdate, user: dict = Depends(mutating_user)) -> dict:
        _asset_or_404(_assets(app), asset_id, user["id"])
        try:
            return _public_asset(
                app,
                _assets(app).update_asset(
                    asset_id,
                    user["id"],
                    name=payload.name,
                    definition=payload.definition,
                ),
                user["id"],
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.delete("/assets/{asset_id}", summary="删除资产")
    def delete_asset(asset_id: str, user: dict = Depends(mutating_user)) -> dict:
        try:
            _assets(app).delete_asset(asset_id, user["id"])
        except KeyError as error:
            raise HTTPException(status_code=404, detail="资产不存在") from error
        return {"ok": True}

    @router.post(
        "/assets/{asset_id}/generate-image",
        status_code=202,
        summary="入队生成角色肖像/造型、场景主图或道具参考图",
    )
    async def generate_image(
        asset_id: str,
        background_tasks: BackgroundTasks,
        user: dict = Depends(mutating_user),
        payload: XiajiAssetGenerateRequest = Body(default_factory=XiajiAssetGenerateRequest),
    ) -> dict:
        write_request_log("xiaji-generate-image", {"phase": "start", "asset_id": asset_id, "user_id": user["id"]})
        record = _submit_asset_image_job(app, user["id"], asset_id, payload)
        job = record.pop("_queued_job", None) or {}
        job_id = str(job.get("id") or "")
        worker = getattr(app.state, "worker", None)
        if not job_id or worker is None:
            raise HTTPException(status_code=503, detail="图片任务执行器未启动")
        background_tasks.add_task(_enqueue_queued_job, worker, job)
        write_request_log(
            "xiaji-generate-image",
            {"phase": "queued", "asset_id": asset_id, "job_id": job_id, "mode": job.get("mode")},
        )
        return {
            "ok": True,
            "job_id": job_id,
            "status": "generating",
            "asset": _with_media_urls(record),
        }

    @router.post("/assets/{asset_id}/upload-image", summary="上传参考图")
    async def upload_image(
        asset_id: str,
        user: dict = Depends(mutating_user),
        file: UploadFile = File(...),
        look_id: str | None = Form(None),
        slot: str | None = Form(None),
    ) -> dict:
        store = _assets(app)
        asset = _asset_or_404(store, asset_id, user["id"])
        filename = Path(file.filename or "image.png").name
        suffix = Path(filename).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise HTTPException(status_code=422, detail="仅支持 PNG / JPEG / WebP / GIF")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=422, detail="文件是空的")
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="参考图不能超过 12 MB")
        stored = app.state.resource_storage.store_bytes("xiaji-assets", filename, content)
        url = resource_object_url(app.state.resource_storage, stored.key) or f"/api/xiaji/assets/{asset_id}"
        look_id = (look_id or "").strip() or None
        view_slot = (slot or "").strip() or None
        if look_id:
            looks = list(asset.get("definition", {}).get("looks") or [])
            found = False
            for item in looks:
                if isinstance(item, dict) and item.get("id") == look_id:
                    item["image_url"] = url
                    found = True
            if not found:
                raise HTTPException(status_code=422, detail="找不到该造型")
            store.update_asset(asset_id, user["id"], definition={"looks": looks}, clear_error=True)
            store.add_media(asset_id, user["id"], media_kind="look", slot=look_id, object_key=stored.key, url=url)
        elif view_slot in {"reverse", "panorama", "turnaround", "detail"}:
            definition = dict(asset.get("definition") or {})
            url_fields = {
                "reverse": "back_image_url",
                "panorama": "panorama_image_url",
                "turnaround": "turnaround_image_url",
                "detail": "detail_image_url",
            }
            definition[url_fields[view_slot]] = url
            jobs_key = "prop_jobs" if view_slot in {"turnaround", "detail"} else "scene_jobs"
            jobs_map = dict(definition.get(jobs_key) or {})
            jobs_map.pop(view_slot, None)
            definition[jobs_key] = jobs_map
            store.update_asset(asset_id, user["id"], definition=definition, clear_error=True)
            store.add_media(
                asset_id,
                user["id"],
                media_kind=view_slot,
                slot=view_slot,
                object_key=stored.key,
                url=url,
            )
        else:
            store.update_asset(
                asset_id,
                user["id"],
                status="ready",
                image_object_key=stored.key,
                image_url=url,
                clear_error=True,
            )
            kind_map = {"character": "portrait", "scene": "master", "prop": "reference"}
            store.add_media(
                asset_id,
                user["id"],
                media_kind=kind_map.get(asset["kind"], "portrait"),
                slot=kind_map.get(asset["kind"], "portrait"),
                object_key=stored.key,
                url=url,
            )
        return _public_asset(app, store.get_asset(asset_id, user["id"]), user["id"])

    @router.post("/assets/{asset_id}/define-voice", summary="用大模型生成声线定义")
    def define_voice(asset_id: str, user: dict = Depends(mutating_user)) -> dict:
        store = _assets(app)
        asset = _asset_or_404(store, asset_id, user["id"])
        if asset["kind"] not in {"character", "voice"}:
            raise HTTPException(status_code=422, detail="只有角色和声线可以生成声线定义")
        definition = dict(asset.get("definition") or {})
        payload = {
            "name": asset["name"],
            "role": definition.get("role") or ("解说" if asset["kind"] == "voice" else ""),
            "gender": definition.get("gender") or "",
            "age_group": definition.get("age_group") or "",
            "description": definition.get("description") or definition.get("prompt") or "",
            "purpose": "旁白解说" if asset["kind"] == "voice" else "角色对白",
        }
        job_id = start_xiaji_llm_job(
            app,
            owner_user_id=user["id"],
            project_id=str(asset.get("project_id") or ""),
            kind="voice",
            target=f"{asset['kind']} · {asset['name']}",
            title=f"声线定义 · {asset['name']}",
            messages=build_voice_define_messages(payload),
            parameters={
                "asset_id": asset_id,
                "asset_kind": asset["kind"],
                **payload,
            },
            temperature=0.4,
            max_tokens=800,
        )
        try:
            profile = app.state.llm_provider.define_xiaji_voice(payload)
        except LlmError as error:
            finish_xiaji_llm_job(
                app,
                job_id,
                status="failed",
                error=str(error),
                response=llm_failure_response(error),
            )
            raise HTTPException(status_code=422, detail=str(error)) from error
        finish_xiaji_llm_job(app, job_id, status="succeeded", response=profile)
        store.update_asset(asset_id, user["id"], definition={"voice_profile": profile}, status=asset["status"] or "draft")
        return _public_asset(app, store.get_asset(asset_id, user["id"]), user["id"])

    @router.post("/assets/{asset_id}/generate-voice", summary="按声线定义合成试听")
    def generate_voice(
        asset_id: str,
        user: dict = Depends(mutating_user),
        slot: str = "default",
    ) -> dict:
        store = _assets(app)
        asset = _asset_or_404(store, asset_id, user["id"])
        if asset["kind"] not in {"character", "voice"}:
            raise HTTPException(status_code=422, detail="只有角色和声线可以合成试听")
        slot = (slot or "default").strip()
        if slot not in VOICE_SLOTS:
            raise HTTPException(status_code=422, detail="声线槽位无效")
        profile = (asset.get("definition") or {}).get("voice_profile") or {}
        line = str(profile.get("sample_line") or "").strip() or f"我是{asset['name']}。"
        tts_voice = str(profile.get("tts_voice") or "").strip() or voice_for_gender(
            str((asset.get("definition") or {}).get("gender") or "")
        )
        try:
            audio = app.state.tts_provider.synthesize(line, voice=tts_voice)
        except LlmError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        stored = app.state.resource_storage.store_bytes("xiaji-voices", f"{asset_id}-{slot}.mp3", audio)
        url = resource_object_url(app.state.resource_storage, stored.key) or ""
        store.add_media(
            asset_id,
            user["id"],
            media_kind="voice_sample",
            slot=slot,
            object_key=stored.key,
            url=url,
            prompt=line,
            model=tts_voice,
        )
        return _public_asset(app, store.get_asset(asset_id, user["id"]), user["id"])

    @router.post("/assets/{asset_id}/upload-voice", summary="上传声线参考音频")
    async def upload_voice(
        asset_id: str,
        user: dict = Depends(mutating_user),
        file: UploadFile = File(...),
        slot: str = Form("default"),
    ) -> dict:
        store = _assets(app)
        _asset_or_404(store, asset_id, user["id"])
        slot = (slot or "default").strip()
        if slot not in VOICE_SLOTS:
            raise HTTPException(status_code=422, detail="声线槽位无效")
        filename = Path(file.filename or "voice.mp3").name
        suffix = Path(filename).suffix.lower()
        if suffix not in AUDIO_SUFFIXES:
            raise HTTPException(status_code=422, detail="仅支持 MP3 / WAV / M4A / WEBM / OGG")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=422, detail="文件是空的")
        if len(content) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="参考音频不能超过 20 MB")
        stored = app.state.resource_storage.store_bytes("xiaji-voices", filename, content)
        url = resource_object_url(app.state.resource_storage, stored.key) or ""
        store.add_media(
            asset_id,
            user["id"],
            media_kind="voice_sample",
            slot=slot,
            object_key=stored.key,
            url=url,
        )
        return _public_asset(app, store.get_asset(asset_id, user["id"]), user["id"])

    @router.get("/assets/{asset_id}/image", summary="读取资产主图")
    def download_asset_image(asset_id: str, user: dict = Depends(current_user)):
        asset = _asset_or_404(_assets(app), asset_id, user["id"])
        key = str(asset.get("image_object_key") or "").strip()
        if not key:
            raise HTTPException(status_code=404, detail="还没有参考图")
        path = app.state.resource_storage.resolve(key)
        if path is not None:
            return FileResponse(path)
        signed = app.state.resource_storage.download_url(key)
        if signed:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(signed, status_code=307)
        raise HTTPException(status_code=404, detail="参考图不可用")

    @router.get("/assets/{asset_id}/media/{media_id}", summary="读取资产媒体")
    def download_asset_media(asset_id: str, media_id: str, user: dict = Depends(current_user)):
        asset = _asset_or_404(_assets(app), asset_id, user["id"])
        item = next((row for row in asset.get("media") or [] if row.get("id") == media_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="媒体不存在")
        key = str(item.get("object_key") or "").strip()
        if key:
            path = app.state.resource_storage.resolve(key)
            if path is not None:
                return FileResponse(path)
            signed = app.state.resource_storage.download_url(key)
            if signed:
                from fastapi.responses import RedirectResponse
                return RedirectResponse(signed, status_code=307)
        if item.get("url"):
            from fastapi.responses import RedirectResponse
            return RedirectResponse(item["url"], status_code=307)
        raise HTTPException(status_code=404, detail="媒体不可用")

    @router.get("/jobs", summary="列出当前导台2 项目的生成任务")
    def list_project_jobs(
        project_id: str = Query(..., description="导台2 项目 ID"),
        user: dict = Depends(current_user),
    ) -> list[dict]:
        require_xiaji_project(app, project_id, user["id"])
        refs = _collect_project_job_refs(app, user["id"], project_id)
        job_ids = {str(item["job_id"]) for item in refs if item.get("source") not in {"llm", "auto_run"}}
        cache = _fetch_jobs_batch(app.state.store, job_ids)
        llm_cache = {}
        llm_store = llm_jobs_store(app)
        if llm_store is not None:
            for item in llm_store.list_project_jobs(user["id"], project_id):
                llm_cache[str(item["job_id"])] = item
        run_cache = {}
        run_store = episode_runs_store(app)
        if run_store is not None:
            for item in run_store.list_project_runs(user["id"], project_id):
                run_cache[str(item["id"])] = run_store.to_job_list_item(item)
        items = []
        for ref in refs:
            if ref.get("source") == "llm":
                row = llm_cache.get(ref["job_id"])
                items.append(row if row else {**ref, "id": ref["job_id"], "missing": True, "status": "unknown"})
                continue
            if ref.get("source") == "auto_run":
                row = run_cache.get(ref["job_id"])
                items.append(row if row else {**ref, "id": ref["job_id"], "missing": True, "status": "unknown"})
                continue
            items.append(_job_list_item(app, ref, cache.get(ref["job_id"])))
        items.sort(key=lambda row: str(row.get("job_created_at") or row.get("created_at") or ""), reverse=True)
        return items

    app.include_router(router)
