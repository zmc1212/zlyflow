from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from .director_jobs import create_queued_job, job_asset_image_url
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
    image_options_for_prop_view,
    image_options_for_scene_view,
    prop_view_prompt,
    scene_view_prompt,
)
from .xiaji_asset_store import ASSET_KINDS, XiajiAssetStore
from .xiaji_project_api import require_xiaji_project

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".webm", ".ogg", ".aac"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_AUDIO_BYTES = 20 * 1024 * 1024


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
    ethnicity: str | None = None
    model: str | None = None
    scene_view: str | None = None
    prop_view: str | None = None


def _assets(app: Any) -> XiajiAssetStore:
    return app.state.xiaji_asset_store


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
    style = (payload.style or "").strip()
    ethnicity = (payload.ethnicity or "").strip()
    look_id = (payload.look_id or "").strip()
    look = None
    if look_id:
        looks = asset.get("definition", {}).get("looks") or []
        look = next((item for item in looks if isinstance(item, dict) and item.get("id") == look_id), None)
        if look is None:
            raise HTTPException(status_code=422, detail="找不到该造型")
        prompt = character_look_prompt(asset, look, style=style, ethnicity=ethnicity)
        title = f"导台2 造型 · {asset['name']} · {look.get('name') or '造型'}"
        media_kind = "look"
        slot = look_id
        options = {"aspect_ratio": "4:3", "resolution": "1K", "count": 1}
    elif asset["kind"] == "character":
        prompt = character_portrait_prompt(asset, style=style, ethnicity=ethnicity)
        title = f"导台2 肖像 · {asset['name']}"
        media_kind = "portrait"
        slot = "portrait"
        options = image_options_for_kind("character")
    elif asset["kind"] == "scene":
        view = (payload.scene_view or "master").strip() or "master"
        if view not in {"master", "reverse", "panorama"}:
            raise HTTPException(status_code=422, detail="场景视角无效，请使用 master、reverse 或 panorama")
        has_master = bool(str(asset.get("image_url") or "").strip() or asset.get("image_object_key"))
        prompt = scene_view_prompt(asset, view, style=style, has_master_reference=has_master and view != "master")
        view_titles = {"master": "正面源图", "reverse": "背面", "panorama": "360全景"}
        title = f"导台2 场景{view_titles[view]} · {asset['name']}"
        media_kind = view
        slot = view
        options = image_options_for_scene_view(view)
    else:
        view = (payload.prop_view or "master").strip() or "master"
        if view not in {"master", "turnaround", "detail"}:
            raise HTTPException(status_code=422, detail="道具视角无效，请使用 master、turnaround 或 detail")
        has_master = bool(str(asset.get("image_url") or "").strip() or asset.get("image_object_key"))
        prompt = prop_view_prompt(asset, view, style=style, has_master_reference=has_master and view != "master")
        view_titles = {"master": "主视图", "turnaround": "转面四视图", "detail": "细节特写"}
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
        looks = list(asset.get("definition", {}).get("looks") or [])
        for item in looks:
            if isinstance(item, dict) and item.get("id") == look_id:
                item["job_id"] = job["id"]
        store.update_asset(
            asset_id,
            owner_user_id,
            definition={"looks": looks},
            status="generating",
            image_job_id=job["id"],
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


def _hydrate_asset(app: Any, asset: dict[str, Any], owner_user_id: str) -> dict[str, Any]:
    store: XiajiAssetStore = app.state.xiaji_asset_store
    jobs = app.state.store
    changed = False
    job_id = str(asset.get("image_job_id") or "").strip()
    if job_id:
        try:
            job = jobs.get(job_id)
        except KeyError:
            job = None
        if job:
            status = str(job.get("status") or "")
            url = job_asset_image_url(job, kind="image", resource_storage=app.state.resource_storage)
            if status in {JobStatus.SUCCEEDED.value, JobStatus.PARTIAL.value} and url:
                asset = store.update_asset(
                    asset["id"],
                    owner_user_id,
                    status="ready",
                    image_url=url,
                    clear_error=True,
                )
                changed = True
            elif status in {JobStatus.FAILED.value, JobStatus.INTERRUPTED.value, JobStatus.CANCELLED.value}:
                asset = store.update_asset(
                    asset["id"],
                    owner_user_id,
                    status="failed",
                    error=str(job.get("error") or "资产生成失败"),
                )
                changed = True
            elif status in {JobStatus.QUEUED.value, JobStatus.RUNNING.value} and asset.get("status") != "generating":
                asset = store.update_asset(asset["id"], owner_user_id, status="generating")
                changed = True
    definition = dict(asset.get("definition") or {})
    looks = definition.get("looks") if isinstance(definition.get("looks"), list) else []
    look_changed = False
    for look in looks:
        if not isinstance(look, dict):
            continue
        look_job = str(look.get("job_id") or "").strip()
        if not look_job:
            continue
        try:
            job = jobs.get(look_job)
        except KeyError:
            continue
        url = job_asset_image_url(job, kind="image", resource_storage=app.state.resource_storage)
        status = str(job.get("status") or "")
        if url and status in {JobStatus.SUCCEEDED.value, JobStatus.PARTIAL.value} and look.get("image_url") != url:
            look["image_url"] = url
            look_changed = True
    if look_changed:
        asset = store.update_asset(asset["id"], owner_user_id, definition={"looks": looks})
        changed = True
    view_job_specs = (
        ("scene_jobs", {"reverse": "back_image_url", "panorama": "panorama_image_url"}),
        ("prop_jobs", {"turnaround": "turnaround_image_url", "detail": "detail_image_url"}),
    )
    for jobs_key, url_fields in view_job_specs:
        definition = dict(asset.get("definition") or {})
        extra_jobs = definition.get(jobs_key) if isinstance(definition.get(jobs_key), dict) else {}
        extra_changed = False
        next_jobs = dict(extra_jobs)
        for view, view_job_id in list(extra_jobs.items()):
            job_key = str(view_job_id or "").strip()
            if not job_key:
                continue
            try:
                job = jobs.get(job_key)
            except KeyError:
                continue
            status = str(job.get("status") or "")
            url = job_asset_image_url(job, kind="image", resource_storage=app.state.resource_storage)
            if url and status in {JobStatus.SUCCEEDED.value, JobStatus.PARTIAL.value}:
                field = url_fields.get(str(view))
                if field:
                    definition[field] = url
                next_jobs.pop(view, None)
                extra_changed = True
            elif status in {JobStatus.FAILED.value, JobStatus.INTERRUPTED.value, JobStatus.CANCELLED.value}:
                next_jobs.pop(view, None)
                extra_changed = True
        if extra_changed:
            definition[jobs_key] = next_jobs
            asset = store.update_asset(asset["id"], owner_user_id, definition=definition)
            changed = True
    return store.get_asset(asset["id"], owner_user_id) if changed else asset


def _with_media_urls(asset: dict[str, Any]) -> dict[str, Any]:
    asset_id = asset["id"]
    if not asset.get("image_url"):
        if asset.get("image_object_key"):
            asset["image_url"] = f"/api/xiaji/assets/{asset_id}/image"
        elif asset.get("status") == "ready" and asset.get("image_job_id"):
            asset["image_url"] = f"/api/jobs/{asset['image_job_id']}/outputs/0/download"
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


def _public_asset(app: Any, asset: dict[str, Any], owner_user_id: str) -> dict[str, Any]:
    return _with_media_urls(_hydrate_asset(app, asset, owner_user_id))


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
        return [_public_asset(app, item, user["id"]) for item in items]

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
        require_xiaji_project(app, project_id, user["id"])
        try:
            return _public_asset(
                app,
                _assets(app).create_asset(
                    user["id"],
                    project_id=project_id,
                    kind=payload.kind,
                    name=payload.name,
                    definition=payload.definition,
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
            store.update_asset(asset_id, user["id"], definition={"looks": looks}, status="ready", image_url=url, clear_error=True)
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
        try:
            profile = app.state.llm_provider.define_xiaji_voice(payload)
        except LlmError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
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

    app.include_router(router)
