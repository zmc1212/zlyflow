from __future__ import annotations

import secrets
import shutil
import urllib.request
from pathlib import Path
from typing import Any
from urllib.error import URLError

from .config import settings
from .director_compiler import (
    H3_MAX_REFERENCE_IMAGES,
    recipe_assets_as_slots,
    recipe_style_prefix,
    resolve_recipe_shot_submission,
)
from .workflow_registry import resolve_director_workflow
from .director_recipe import (
    PAYLOAD_KIND_RECIPE,
    flatten_recipe_shots,
    normalize_recipe_payload,
    payload_kind,
)
from .models import JobStatus
from .resource_storage import resource_object_url
from .storage import JobStore
from .workflow_registry import (
    is_image_workflow,
    normalize_options,
    validate_option_relationships,
    validate_references,
    workflow_for,
)


def new_job_id() -> str:
    return secrets.token_urlsafe(9).replace("-", "").replace("_", "")


def default_image_workflow_id(grs_provider: Any) -> str:
    workflows = list(grs_provider.enabled_image_workflows() or [])
    if not workflows:
        raise ValueError("没有可用的 GRS 生图工作流，请在管理设置中启用图片模型。")
    return getattr(workflows[0], "id", None) or workflows[0]["id"]


def job_first_output_file(job: dict[str, Any] | None) -> Path | None:
    if not isinstance(job, dict):
        return None
    for output in job.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        raw = output.get("path")
        if not raw:
            continue
        candidate = Path(str(raw))
        if candidate.is_file():
            return candidate
        fallback = settings.results_dir / candidate.name
        if fallback.is_file():
            return fallback
        staging = settings.staging_dir / candidate.name
        if staging.is_file():
            return staging
    return None


def job_public_output_url(job: dict[str, Any] | None, *, kind: str | None = None) -> str | None:
    if not isinstance(job, dict) or not job.get("id"):
        return None
    outputs = [item for item in (job.get("outputs") or []) if isinstance(item, dict)]
    if kind:
        matched = [item for item in outputs if item.get("kind") == kind]
        outputs = matched or outputs
    if not outputs:
        return None
    return f"/api/jobs/{job['id']}/outputs/0/download"


def job_asset_image_url(
    job: dict[str, Any] | None,
    *,
    kind: str | None = "image",
    resource_storage: Any | None = None,
) -> str | None:
    if not isinstance(job, dict):
        return None
    outputs = [item for item in (job.get("outputs") or []) if isinstance(item, dict)]
    if kind:
        matched = [item for item in outputs if item.get("kind") == kind]
        outputs = matched or outputs
    for output in outputs:
        stored = str(output.get("cloud_url") or "").strip()
        if stored:
            return stored
        if output.get("delivery_status") == "cloud":
            derived = resource_object_url(resource_storage, output.get("path"))
            if derived:
                return derived
    return job_public_output_url(job, kind=kind)


def recipe_asset_image_index(recipe: dict[str, Any] | None) -> dict[str, str | None]:
    index: dict[str, str | None] = {}
    if not isinstance(recipe, dict):
        return index
    for asset in list(recipe.get("characters") or []) + list(recipe.get("locations") or []):
        if not isinstance(asset, dict) or not asset.get("id"):
            continue
        index[str(asset["id"])] = asset.get("imageUrl")
    return index


def bind_director_asset_image(
    store: JobStore,
    *,
    owner_user_id: str,
    job_id: str,
    image_url: str,
) -> int:
    job_id = (job_id or "").strip()
    image_url = (image_url or "").strip()
    owner = (owner_user_id or "").strip()
    if not job_id or not image_url or not owner:
        return 0
    bound = 0
    for summary in store.list_director_projects(owner):
        try:
            project = store.get_director_project(summary["id"])
        except KeyError:
            continue
        payload = project.get("payload")
        if payload_kind(payload) != PAYLOAD_KIND_RECIPE:
            continue
        recipe = normalize_recipe_payload(payload)
        changed = False
        for asset in list(recipe.get("characters") or []) + list(recipe.get("locations") or []):
            if asset.get("imageJobId") != job_id:
                continue
            if asset.get("imageUrl") != image_url:
                asset["imageUrl"] = image_url
                changed = True
        if changed:
            store.update_director_project(project["id"], payload=recipe)
            bound += 1
    return bound


def materialize_job_output_file(
    job: dict[str, Any] | None,
    *,
    resource_storage: Any | None = None,
    kind: str | None = None,
) -> Path | None:
    local = job_first_output_file(job)
    if local is not None:
        return local
    if not isinstance(job, dict) or resource_storage is None:
        return None
    getter = getattr(resource_storage, "download_url", None)
    if not callable(getter):
        return None
    outputs = [item for item in (job.get("outputs") or []) if isinstance(item, dict)]
    if kind:
        matched = [item for item in outputs if item.get("kind") == kind]
        outputs = matched or outputs
    job_id = str(job.get("id") or "plate")
    dest_dir = settings.staging_dir / "director-plates"
    for output in outputs:
        key = str(output.get("path") or "").strip()
        if not key:
            continue
        url = getter(key)
        if not url:
            continue
        suffix = Path(key).suffix or ".png"
        dest = dest_dir / f"{job_id}{suffix}"
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(str(url), timeout=60) as response:
                dest.write_bytes(response.read())
        except (OSError, URLError, TimeoutError, ValueError):
            dest.unlink(missing_ok=True)
            continue
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
    return None


def sync_recipe_asset_images(
    store: JobStore,
    recipe: dict[str, Any],
    *,
    resource_storage: Any | None = None,
) -> dict[str, Any]:
    recipe = normalize_recipe_payload(recipe)
    for asset in list(recipe.get("characters") or []) + list(recipe.get("locations") or []):
        job_id = asset.get("imageJobId")
        if not job_id:
            continue
        try:
            job = store.get(job_id)
        except KeyError:
            continue
        url = job_asset_image_url(job, kind="image", resource_storage=resource_storage)
        if url:
            asset["imageUrl"] = url
    for shot in flatten_recipe_shots(recipe):
        job_id = shot.get("jobId")
        if not job_id:
            continue
        try:
            job = store.get(job_id)
        except KeyError:
            continue
        status = job.get("status")
        if status in {JobStatus.SUCCEEDED.value, JobStatus.PARTIAL.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value, JobStatus.INTERRUPTED.value, JobStatus.RUNNING.value, JobStatus.QUEUED.value}:
            shot["status"] = "succeeded" if status == JobStatus.PARTIAL.value and job_public_output_url(job, kind="video") else status
        url = job_public_output_url(job, kind="video")
        if url:
            shot["outputVideoUrl"] = url
            shot["progress"] = 100 if shot.get("status") == "succeeded" else shot.get("progress") or job.get("progress") or 0
        elif isinstance(job.get("progress"), (int, float)):
            shot["progress"] = job["progress"]
    return recipe


def create_queued_job(
    store: JobStore,
    *,
    owner_user_id: str,
    mode: str,
    prompt: str,
    options: dict[str, Any] | None = None,
    references: list[str] | None = None,
    title: str | None = None,
    image_size: str | None = None,
) -> dict[str, Any]:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("请填写创作提示词")
    workflow_for(mode)
    refs = list(references or [])
    validate_references(mode, refs)
    generation_options = normalize_options(mode, options or {})
    validate_option_relationships(mode, generation_options, len(refs))
    job_id = new_job_id()
    if refs:
        upload_dir = settings.uploads_dir / owner_user_id / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for index, source in enumerate(refs[:H3_MAX_REFERENCE_IMAGES], start=1):
            src = Path(source)
            dest = upload_dir / f"{index}_{src.name}"
            shutil.copy2(src, dest)
            copied.append(str(dest))
        refs = copied
    return store.create(
        job_id,
        mode,
        prompt,
        "",
        image_size,
        refs,
        generation_options,
        submitted_options=options or {},
        owner_user_id=owner_user_id,
        title=title,
    )


def _plate_prompt(asset: dict[str, Any], recipe: dict[str, Any], *, kind: str) -> str:
    prefix = recipe_style_prefix(recipe)
    body = (asset.get("promptText") or asset.get("description") or asset.get("name") or "").strip()
    if kind == "location":
        instruction = "empty establishing environment, no people, no faces, wide cinematic still"
    elif str(asset.get("type") or "") == "object":
        instruction = "product/object design sheet, centered, no people"
    else:
        instruction = "character design sheet, consistent face and costume, full body, plain backdrop"
    parts = [prefix, instruction, body]
    return ". ".join(part for part in parts if part)


def generate_recipe_assets(
    store: JobStore,
    grs_provider: Any,
    *,
    owner_user_id: str,
    recipe: dict[str, Any],
    character_ids: list[str] | None = None,
    location_ids: list[str] | None = None,
    force: bool = False,
    resource_storage: Any | None = None,
) -> tuple[dict[str, Any], list[str]]:
    available, reason = grs_provider.availability()
    if not available:
        raise ValueError(reason or "GRS 图片能力不可用")
    workflow_id = default_image_workflow_id(grs_provider)
    if not is_image_workflow(workflow_id):
        raise ValueError("当前默认工作流不是图片生成")
    recipe = sync_recipe_asset_images(store, recipe, resource_storage=resource_storage)
    wanted_chars = {item for item in (character_ids or []) if item}
    wanted_locs = {item for item in (location_ids or []) if item}
    generate_all = not wanted_chars and not wanted_locs
    aspect = recipe.get("aspectRatio") or "16:9"
    options = {"aspect_ratio": aspect if aspect in {"1:1", "16:9", "9:16", "4:3", "3:4"} else "1:1", "resolution": "1K", "count": 1}
    job_ids: list[str] = []

    def _should_run(asset: dict[str, Any], wanted: set[str]) -> bool:
        if not generate_all and asset.get("id") not in wanted:
            return False
        return force or not asset.get("imageUrl")

    for character in recipe.get("characters") or []:
        if not _should_run(character, wanted_chars):
            continue
        job = create_queued_job(
            store,
            owner_user_id=owner_user_id,
            mode=workflow_id,
            prompt=_plate_prompt(character, recipe, kind="character"),
            options=options,
            title=f"定妆 · {character.get('name') or '角色'}",
        )
        character["imageJobId"] = job["id"]
        character["imageUrl"] = None
        job_ids.append(job["id"])

    location_aspect = "16:9" if (recipe.get("aspectRatio") or "16:9") != "9:16" else "9:16"
    location_options = {**options, "aspect_ratio": location_aspect}
    for location in recipe.get("locations") or []:
        if not _should_run(location, wanted_locs):
            continue
        job = create_queued_job(
            store,
            owner_user_id=owner_user_id,
            mode=workflow_id,
            prompt=_plate_prompt(location, recipe, kind="location"),
            options=location_options,
            title=f"场景 · {location.get('name') or '地点'}",
        )
        location["imageJobId"] = job["id"]
        location["imageUrl"] = None
        job_ids.append(job["id"])
    return recipe, job_ids


def _reference_paths_for_shot(
    store: JobStore,
    recipe: dict[str, Any],
    shot: dict[str, Any],
    *,
    resource_storage: Any | None = None,
) -> list[str]:
    paths: list[str] = []
    for slot in recipe_assets_as_slots(recipe, shot):
        job_id = slot.get("imageJobId")
        if not job_id:
            continue
        try:
            job = store.get(job_id)
        except KeyError:
            continue
        file_path = materialize_job_output_file(job, resource_storage=resource_storage, kind="image")
        if file_path is not None:
            paths.append(str(file_path))
    return paths[:H3_MAX_REFERENCE_IMAGES]


def render_recipe_shots(
    store: JobStore,
    *,
    owner_user_id: str,
    recipe: dict[str, Any],
    shot_ids: list[str] | None = None,
    render_pass: str = "final",
    resource_storage: Any | None = None,
) -> tuple[dict[str, Any], list[str]]:
    recipe = sync_recipe_asset_images(store, recipe, resource_storage=resource_storage)
    wanted = {item for item in (shot_ids or []) if item}
    job_ids: list[str] = []
    for _scene, shot in _iter_shots(recipe):
        if wanted and shot.get("id") not in wanted:
            continue
        submission = resolve_recipe_shot_submission(recipe, shot, render_pass)
        errors = list(submission.get("errors") or [])
        if errors:
            shot["status"] = "failed"
            continue
        refs = _reference_paths_for_shot(store, recipe, shot, resource_storage=resource_storage)
        workflow_id = submission["workflowId"]
        if not refs:
            workflow_id = resolve_director_workflow(
                recipe.get("videoWorkflowFamily") or recipe.get("video_workflow_family"),
                "t2v",
            )
        job = create_queued_job(
            store,
            owner_user_id=owner_user_id,
            mode=workflow_id,
            prompt=submission["prompt"],
            options={
                "aspect_ratio": submission.get("aspectRatio") or recipe.get("aspectRatio") or "16:9",
                "quality": submission.get("quality") or "1.0",
                "speed": submission.get("speed") or "balanced",
                "duration": submission.get("durationSec") or 5,
            },
            references=refs,
            title=str(shot.get("title") or "分镜"),
        )
        shot["jobId"] = job["id"]
        shot["compiledPrompt"] = submission["prompt"]
        shot["status"] = "queued"
        shot["progress"] = 0
        job_ids.append(job["id"])
    return recipe, job_ids


def _iter_shots(recipe: dict[str, Any]):
    for scene in recipe.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if isinstance(shot, dict):
                yield scene, shot


def render_batch_items(
    store: JobStore,
    *,
    owner_user_id: str,
    payload: dict[str, Any],
    item_ids: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    prefix = ""
    art = payload.get("artStyle") if isinstance(payload.get("artStyle"), dict) else {}
    if art:
        prefix = str(art.get("promptPrefix") or "").strip()
    duration = int(payload.get("durationSec") or 8)
    aspect = payload.get("aspectRatio") or "9:16"
    wanted = {item for item in (item_ids or []) if item}
    job_ids: list[str] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        if wanted and item.get("id") not in wanted:
            continue
        script = (item.get("script") or "").strip()
        if not script:
            continue
        prompt = f"{prefix}. {script}".strip(". ") if prefix else script
        job = create_queued_job(
            store,
            owner_user_id=owner_user_id,
            mode=resolve_director_workflow(
                payload.get("videoWorkflowFamily") or payload.get("video_workflow_family"),
                "t2v",
            ),
            prompt=prompt,
            options={
                "aspect_ratio": aspect,
                "quality": payload.get("finalQuality") or "1.0",
                "speed": payload.get("finalSpeed") or "balanced",
                "duration": duration,
            },
            title=str(item.get("title") or payload.get("theme") or "批量短视频"),
        )
        item["jobId"] = job["id"]
        item["status"] = "queued"
        item["error"] = None
        job_ids.append(job["id"])
    return payload, job_ids


def sync_batch_items(store: JobStore, payload: dict[str, Any]) -> dict[str, Any]:
    for item in payload.get("items") or []:
        if not isinstance(item, dict) or not item.get("jobId"):
            continue
        try:
            job = store.get(item["jobId"])
        except KeyError:
            continue
        status = job.get("status")
        if status == JobStatus.PARTIAL.value and job_public_output_url(job, kind="video"):
            item["status"] = "succeeded"
        elif status:
            item["status"] = status
        url = job_public_output_url(job, kind="video")
        if url:
            item["outputVideoUrl"] = url
        error = str(job.get("error") or "").strip()
        if item.get("status") in {JobStatus.FAILED.value, JobStatus.INTERRUPTED.value, JobStatus.CANCELLED.value}:
            item["error"] = error or item.get("error")
        elif item.get("status") == JobStatus.SUCCEEDED.value:
            item["error"] = None
    return payload
