from __future__ import annotations

import secrets
import shutil
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError

from .config import settings
from .director_compiler import (
    H3_MAX_REFERENCE_IMAGES,
    apply_recipe_continuity,
    h3_prompt_mode,
    recipe_assets_as_slots,
    recipe_style_prefix,
    resolve_recipe_shot_submission,
    validate_h3_polished_prompt,
)
from .workflow_registry import resolve_director_workflow
from .director_recipe import (
    PAYLOAD_KIND_RECIPE,
    active_rendition_version,
    approved_rendition_version,
    character_approved_portrait_version,
    character_look,
    find_recipe_shot,
    flatten_recipe_shots,
    normalize_recipe_payload,
    payload_kind,
    rendition_version,
)
from .director_takes import preferred_usable_take, take_key
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
from .llm_client import LlmError


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


def _iter_asset_renditions(recipe: dict[str, Any]):
    for character in recipe.get("characters") or []:
        if not isinstance(character, dict):
            continue
        portrait = character.get("portrait")
        if isinstance(portrait, dict):
            yield "character_portrait", character, None, portrait
        for look in character.get("looks") or []:
            if isinstance(look, dict) and isinstance(look.get("sheet"), dict):
                yield "character_sheet", character, look, look["sheet"]
    for location in recipe.get("locations") or []:
        if isinstance(location, dict) and isinstance(location.get("plate"), dict):
            yield "location", location, None, location["plate"]
    for prop in recipe.get("props") or []:
        if isinstance(prop, dict) and isinstance(prop.get("turnaround"), dict):
            yield "prop", prop, None, prop["turnaround"]


def _refresh_asset_projection(recipe: dict[str, Any]) -> None:
    for character in recipe.get("characters") or []:
        if not isinstance(character, dict):
            continue
        look = character_look(character)
        sheet = look.get("sheet") if isinstance(look, dict) and isinstance(look.get("sheet"), dict) else {}
        active = active_rendition_version(sheet) or active_rendition_version(character.get("portrait"))
        approved = approved_rendition_version(sheet) or approved_rendition_version(character.get("portrait"))
        character["imageJobId"] = str((active or {}).get("jobId") or "").strip() or None
        character["imageUrl"] = str((approved or {}).get("imageUrl") or "").strip() or None
    for collection, rendition_key in (("locations", "plate"), ("props", "turnaround")):
        for asset in recipe.get(collection) or []:
            if not isinstance(asset, dict):
                continue
            rendition = asset.get(rendition_key) if isinstance(asset.get(rendition_key), dict) else {}
            active = active_rendition_version(rendition)
            approved = approved_rendition_version(rendition)
            asset["imageJobId"] = str((active or {}).get("jobId") or "").strip() or None
            asset["imageUrl"] = str((approved or {}).get("imageUrl") or "").strip() or None


def _bind_recipe_job_image(recipe: dict[str, Any], job_id: str, image_url: str) -> tuple[dict[str, Any], bool]:
    recipe = normalize_recipe_payload(recipe)
    changed = False
    for _kind, _asset, _look, rendition in _iter_asset_renditions(recipe):
        for version in rendition.get("versions") or []:
            if not isinstance(version, dict) or version.get("jobId") != job_id:
                continue
            if version.get("imageUrl") != image_url or version.get("status") != "succeeded":
                version["imageUrl"] = image_url
                version["status"] = "succeeded"
                changed = True
            if version.get("autoApprove") and rendition.get("approvedVersionId") != version.get("id"):
                rendition["approvedVersionId"] = version.get("id")
                changed = True
    for shot in flatten_recipe_shots(recipe):
        if shot.get("stillJobId") == job_id and shot.get("stillUrl") != image_url:
            shot["stillUrl"] = image_url
            shot["stillStatus"] = "succeeded"
            changed = True
        if shot.get("firstFrameJobId") == job_id and shot.get("firstFrameUrl") != image_url:
            shot["firstFrameUrl"] = image_url
            changed = True
        if shot.get("endFrameJobId") == job_id and shot.get("endFrameUrl") != image_url:
            shot["endFrameUrl"] = image_url
            changed = True
    _refresh_asset_projection(recipe)
    return recipe, changed


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
        _, changed = _bind_recipe_job_image(payload, job_id, image_url)
        if changed:
            store.mutate_director_project_payload(
                project["id"],
                lambda latest: _bind_recipe_job_image(latest, job_id, image_url)[0],
                content_update=False,
            )
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
    for _kind, _asset, _look, rendition in _iter_asset_renditions(recipe):
        for version in rendition.get("versions") or []:
            if not isinstance(version, dict):
                continue
            job_id = str(version.get("jobId") or "").strip()
            if not job_id:
                continue
            try:
                job = store.get(job_id)
            except KeyError:
                continue
            url = job_asset_image_url(job, kind="image", resource_storage=resource_storage)
            status = str(job.get("status") or version.get("status") or "queued")
            if status == JobStatus.PARTIAL.value and url:
                status = JobStatus.SUCCEEDED.value
            if status:
                version["status"] = status
            if url:
                version["imageUrl"] = url
            if version.get("autoApprove") and status == JobStatus.SUCCEEDED.value and url:
                rendition["approvedVersionId"] = version.get("id")
    _refresh_asset_projection(recipe)
    for shot in flatten_recipe_shots(recipe):
        still_job_id = shot.get("stillJobId")
        if still_job_id:
            try:
                still_job = store.get(still_job_id)
            except KeyError:
                still_job = None
            if still_job:
                still_status = still_job.get("status")
                still_url = job_asset_image_url(still_job, kind="image", resource_storage=resource_storage) or job_public_output_url(still_job, kind="image")
                if still_status:
                    shot["stillStatus"] = "succeeded" if still_status == JobStatus.PARTIAL.value and still_url else still_status
                if still_url:
                    shot["stillUrl"] = still_url
        takes = [take for take in (shot.get("takes") or []) if isinstance(take, dict)]
        if not takes and shot.get("jobId"):
            takes.append({
                "id": shot.get("jobId"),
                "takeNumber": 1,
                "jobId": shot.get("jobId"),
                "status": shot.get("status") or "idle",
                "progress": shot.get("progress") or 0,
                "videoUrl": shot.get("outputVideoUrl"),
                "createdAt": "",
                "promptSnapshot": shot.get("compiledPrompt") or "",
            })
        for take in takes:
            take_job_id = take.get("jobId") or take.get("id")
            if not take_job_id:
                continue
            try:
                take_job = store.get(take_job_id)
            except KeyError:
                continue
            take_status = take_job.get("status")
            if take_status == JobStatus.PARTIAL.value and job_public_output_url(take_job, kind="video"):
                take["status"] = "succeeded"
            elif take_status:
                take["status"] = take_status
            video_url = job_public_output_url(take_job, kind="video")
            if video_url:
                take["videoUrl"] = video_url
            if isinstance(take_job.get("progress"), (int, float)):
                take["progress"] = take_job["progress"]
            error = str(take_job.get("error") or "").strip()
            if take.get("status") in {JobStatus.FAILED.value, JobStatus.INTERRUPTED.value, JobStatus.CANCELLED.value}:
                take["error"] = error or take.get("error")
            elif take.get("status") == JobStatus.SUCCEEDED.value:
                take["error"] = None
        shot["takes"] = takes
        # Execution state belongs to the current submission, never to the
        # approved preview.  In particular, polling an approved old Take must
        # not hide a newer queued/running/failed job.
        job_id = str(shot.get("jobId") or "")
        if not job_id:
            continue
        try:
            job = store.get(job_id)
        except KeyError:
            continue
        status = str(job.get("status") or "")
        current_take = next(
            (take for take in takes if str(take.get("jobId") or take_key(take)) == job_id),
            None,
        )
        current_url = job_public_output_url(job, kind="video")
        normalized_status = (
            "succeeded"
            if status == JobStatus.PARTIAL.value and current_url
            else status
        )
        failed_statuses = {
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
            JobStatus.INTERRUPTED.value,
        }
        fallback_take = preferred_usable_take(shot, takes)
        previous_url = str((fallback_take or {}).get("videoUrl") or shot.get("outputVideoUrl") or "")
        if status in failed_statuses and (fallback_take is not None or previous_url):
            # Preserve the last good cut while retaining this submission's
            # failure for the retry affordance and diagnostics.
            shot["status"] = JobStatus.SUCCEEDED.value
            shot["progress"] = 100
            shot["error"] = str(job.get("error") or (current_take or {}).get("error") or "生成失败")
            if previous_url:
                shot["outputVideoUrl"] = previous_url
        else:
            if normalized_status in {
                JobStatus.SUCCEEDED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
                JobStatus.INTERRUPTED.value,
                JobStatus.RUNNING.value,
                JobStatus.QUEUED.value,
            }:
                shot["status"] = normalized_status
            if normalized_status == JobStatus.SUCCEEDED.value:
                shot["error"] = None
            elif status in failed_statuses:
                shot["error"] = str(job.get("error") or (current_take or {}).get("error") or "生成失败")
        url = current_url
        if url:
            shot["outputVideoUrl"] = url
            shot["progress"] = 100 if shot.get("status") == "succeeded" else shot.get("progress") or job.get("progress") or 0
        elif isinstance(job.get("progress"), (int, float)):
            shot["progress"] = job["progress"]
        shot["jobId"] = job_id
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
        for index, source in enumerate(refs, start=1):
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


def _identity_spec_text(character: dict[str, Any]) -> str:
    spec = character.get("identitySpec") if isinstance(character.get("identitySpec"), dict) else {}
    labels = (
        ("age", "ageRange"),
        ("regional appearance", "regionalAppearance"),
        ("face", "faceFeatures"),
        ("hair", "hair"),
        ("skin", "skinTone"),
        ("build", "bodyBuild"),
        ("distinguishing marks", "distinguishingMarks"),
        ("immutable accessories", "immutableAccessories"),
        ("never change", "avoidChanges"),
    )
    return "; ".join(
        f"{label}: {str(spec.get(field) or '').strip()}"
        for label, field in labels
        if str(spec.get(field) or "").strip()
    )


def compile_character_portrait_prompt(character: dict[str, Any], recipe: dict[str, Any]) -> str:
    prefix = recipe_style_prefix(recipe)
    identity = _identity_spec_text(character)
    body = str(character.get("promptText") or character.get("description") or character.get("name") or "").strip()
    instruction = (
        "single production identity portrait of one character, head and shoulders, front-facing with a slight three-quarter turn, "
        "neutral expression, eyes clearly visible, even studio lighting, plain mid-gray background, centered, no text, no collage, "
        "no duplicate person, no dramatic pose; prioritize stable facial geometry, hairline and immutable identity details"
    )
    return ". ".join(part for part in (prefix, instruction, identity, body) if part)


def compile_character_sheet_prompt(
    character: dict[str, Any], look: dict[str, Any], recipe: dict[str, Any],
) -> str:
    prefix = recipe_style_prefix(recipe)
    identity = _identity_spec_text(character)
    character_body = str(character.get("promptText") or character.get("description") or "").strip()
    look_body = str(
        look.get("promptText") or look.get("appearanceDetails") or look.get("name") or ""
    ).strip()
    instruction = (
        "<Picture 1> is the approved identity portrait and is the sole source of facial identity. "
        "Create one clean four-panel production character sheet: panel 1 facial close-up, panel 2 front full-body view, "
        "panel 3 three-quarter full-body view, panel 4 back full-body view. Preserve the exact same face, apparent age, "
        "hair, body proportions and immutable accessories in every panel. Neutral standing pose, hands visible, entire shoes visible, "
        "consistent costume construction and colors, orthographic reference feel, plain light-gray background, even studio lighting, "
        "no scenery, no captions, no labels, no extra characters, no cropped feet"
    )
    return ". ".join(part for part in (prefix, instruction, identity, character_body, look_body) if part)


def compile_prop_turnaround_prompt(prop: dict[str, Any], recipe: dict[str, Any]) -> str:
    prefix = recipe_style_prefix(recipe)
    body = str(prop.get("promptText") or prop.get("description") or prop.get("name") or "").strip()
    instruction = (
        "single object production turnaround sheet with four aligned views: front, side, three-quarter and back; "
        "identical shape, materials, scale cues and wear details in every view, centered, plain light-gray background, "
        "even studio lighting, no person, no hands, no text, no labels"
    )
    return ". ".join(part for part in (prefix, instruction, body) if part)


def compile_location_plate_prompt(location: dict[str, Any], recipe: dict[str, Any]) -> str:
    prefix = recipe_style_prefix(recipe)
    body = str(location.get("promptText") or location.get("description") or location.get("name") or "").strip()
    instruction = (
        "empty production environment master plate, wide establishing composition, clearly readable spatial layout and landmarks, "
        "no people, no silhouettes, no faces, no text, no watermark; preserve architecture, season, time of day, weather and key lighting"
    )
    return ". ".join(part for part in (prefix, instruction, body) if part)


def _plate_prompt(asset: dict[str, Any], recipe: dict[str, Any], *, kind: str) -> str:
    if kind == "location":
        return compile_location_plate_prompt(asset, recipe)
    if kind in {"object", "prop"} or str(asset.get("type") or "") == "object":
        return compile_prop_turnaround_prompt(asset, recipe)
    look = character_look(asset) or {}
    return compile_character_sheet_prompt(asset, look, recipe)


def _append_asset_version(
    rendition: dict[str, Any],
    *,
    job: dict[str, Any],
    prompt: str,
    workflow_id: str,
    options: dict[str, Any],
    auto_approve: bool = False,
) -> dict[str, Any]:
    version = {
        "id": f"assetv-{new_job_id()}",
        "jobId": job["id"],
        "imageUrl": None,
        "status": "queued",
        "promptSnapshot": prompt,
        "workflowId": workflow_id,
        "options": dict(options),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "autoApprove": auto_approve,
    }
    versions = [item for item in (rendition.get("versions") or []) if isinstance(item, dict)]
    versions.append(version)
    rendition["versions"] = versions
    rendition["activeVersionId"] = version["id"]
    return version


def _rendition_ready_or_running(rendition: dict[str, Any]) -> bool:
    active = active_rendition_version(rendition)
    return bool(active and active.get("status") in {"queued", "running"})


def _find_recipe_asset(recipe: dict[str, Any], collection: str, asset_id: str) -> dict[str, Any]:
    asset = next(
        (
            item for item in recipe.get(collection) or []
            if isinstance(item, dict) and str(item.get("id") or "") == asset_id
        ),
        None,
    )
    if asset is None:
        raise ValueError(f"找不到资产 {asset_id}")
    return asset


def _target_rendition(
    recipe: dict[str, Any], kind: str, asset_id: str, look_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    if kind in {"character_portrait", "character_sheet"}:
        asset = _find_recipe_asset(recipe, "characters", asset_id)
        if kind == "character_portrait":
            return asset, None, asset["portrait"]
        look = character_look(asset, look_id)
        if look is None:
            raise ValueError(f"角色 {asset.get('name') or asset_id} 找不到造型 {look_id or ''}")
        return asset, look, look["sheet"]
    if kind == "location":
        asset = _find_recipe_asset(recipe, "locations", asset_id)
        return asset, None, asset["plate"]
    if kind == "prop":
        asset = _find_recipe_asset(recipe, "props", asset_id)
        return asset, None, asset["turnaround"]
    raise ValueError(f"不支持的定妆类型：{kind}")


def _approved_portrait_file(
    store: JobStore,
    character: dict[str, Any],
    *,
    resource_storage: Any | None = None,
) -> Path:
    version = character_approved_portrait_version(character)
    if version is None or not version.get("imageUrl"):
        raise ValueError(f"请先生成并批准「{character.get('name') or '角色'}」的身份肖像")
    job_id = str(version.get("jobId") or "").strip()
    job = None
    if job_id:
        try:
            job = store.get(job_id)
        except KeyError:
            job = None
    source = materialize_job_output_file(job, resource_storage=resource_storage, kind="image")
    if source is None:
        raise ValueError(f"「{character.get('name') or '角色'}」已批准肖像的源文件不可用，请重新生成肖像")
    return source


def approve_recipe_asset_version(
    recipe: dict[str, Any],
    *,
    kind: str,
    asset_id: str,
    version_id: str,
    look_id: str | None = None,
) -> dict[str, Any]:
    recipe = normalize_recipe_payload(recipe)
    asset, look, rendition = _target_rendition(recipe, kind, asset_id, look_id)
    version = rendition_version(rendition, version_id)
    if version is None:
        raise ValueError("找不到要批准的候选版本")
    if version.get("status") != JobStatus.SUCCEEDED.value or not version.get("imageUrl"):
        raise ValueError("只能批准已生成成功的候选图")
    rendition["approvedVersionId"] = version_id
    if kind == "character_portrait":
        asset["specStatus"] = "approved"
    elif kind == "character_sheet" and look is not None:
        look["status"] = "approved"
    _refresh_asset_projection(recipe)
    return recipe


def generate_recipe_assets(
    store: JobStore,
    grs_provider: Any,
    *,
    owner_user_id: str,
    recipe: dict[str, Any],
    character_ids: list[str] | None = None,
    location_ids: list[str] | None = None,
    prop_ids: list[str] | None = None,
    targets: list[dict[str, Any]] | None = None,
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
    wanted_props = {item for item in (prop_ids or []) if item}
    explicit_targets = [item for item in (targets or []) if isinstance(item, dict)]
    plan: list[dict[str, Any]] = []
    if explicit_targets:
        plan = explicit_targets
    else:
        generate_all = not wanted_chars and not wanted_locs and not wanted_props
        for character in recipe.get("characters") or []:
            if not isinstance(character, dict):
                continue
            character_id = str(character.get("id") or "")
            if generate_all or character_id in wanted_chars:
                plan.append({
                    "kind": "character_sheet" if character_approved_portrait_version(character) else "character_portrait",
                    "asset_id": character_id,
                    "look_id": str((character_look(character) or {}).get("id") or "look-default"),
                })
        for location in recipe.get("locations") or []:
            if isinstance(location, dict) and (generate_all or location.get("id") in wanted_locs):
                plan.append({"kind": "location", "asset_id": str(location.get("id") or "")})
        for prop in recipe.get("props") or []:
            if isinstance(prop, dict) and (generate_all or prop.get("id") in wanted_props):
                plan.append({"kind": "prop", "asset_id": str(prop.get("id") or "")})

    seen_targets: set[tuple[str, str, str]] = set()
    job_ids: list[str] = []
    for target in plan:
        kind = str(target.get("kind") or "").strip()
        asset_id = str(target.get("asset_id") or target.get("assetId") or "").strip()
        look_id = str(target.get("look_id") or target.get("lookId") or "").strip() or None
        target_key = (kind, asset_id, look_id or "")
        if not asset_id or target_key in seen_targets:
            continue
        seen_targets.add(target_key)
        asset, look, rendition = _target_rendition(recipe, kind, asset_id, look_id)
        if not force and (approved_rendition_version(rendition) or _rendition_ready_or_running(rendition)):
            continue
        references: list[str] = []
        if kind == "character_portrait":
            prompt = compile_character_portrait_prompt(asset, recipe)
            options = {"aspect_ratio": "1:1", "resolution": "1K", "count": 1}
            title = f"身份肖像 · {asset.get('name') or '角色'}"
        elif kind == "character_sheet":
            prompt = compile_character_sheet_prompt(asset, look or {}, recipe)
            options = {"aspect_ratio": "4:3", "resolution": "1K", "count": 1}
            references = [str(_approved_portrait_file(
                store, asset, resource_storage=resource_storage,
            ))]
            title = f"定妆板 · {asset.get('name') or '角色'} · {(look or {}).get('name') or '基础造型'}"
        elif kind == "prop":
            prompt = compile_prop_turnaround_prompt(asset, recipe)
            options = {"aspect_ratio": "4:3", "resolution": "1K", "count": 1}
            title = f"道具转面 · {asset.get('name') or '道具'}"
        else:
            prompt = compile_location_plate_prompt(asset, recipe)
            location_aspect = "16:9" if (recipe.get("aspectRatio") or "16:9") != "9:16" else "9:16"
            options = {"aspect_ratio": location_aspect, "resolution": "1K", "count": 1}
            title = f"场景母版 · {asset.get('name') or '地点'}"
        job = create_queued_job(
            store,
            owner_user_id=owner_user_id,
            mode=workflow_id,
            prompt=prompt,
            options=options,
            references=references,
            title=title,
        )
        _append_asset_version(
            rendition,
            job=job,
            prompt=prompt,
            workflow_id=workflow_id,
            options=options,
        )
        job_ids.append(job["id"])
    _refresh_asset_projection(recipe)
    return recipe, job_ids


def _still_prompt(shot: dict[str, Any], recipe: dict[str, Any]) -> str:
    prefix = recipe_style_prefix(recipe)
    body = (
        shot.get("promptText")
        or shot.get("description")
        or shot.get("title")
        or ""
    ).strip()
    names = [str(name).strip() for name in (shot.get("characterNames") or []) if str(name).strip()]
    location = str(shot.get("locationName") or "").strip()
    extras = []
    if names:
        extras.append("characters: " + ", ".join(names))
    if location:
        extras.append(f"location: {location}")
    instruction = "cinematic still frame, single keyframe, no motion, storyboard composition"
    parts = [prefix, instruction, body, *extras]
    return ". ".join(part for part in parts if part)


def generate_recipe_stills(
    store: JobStore,
    grs_provider: Any,
    *,
    owner_user_id: str,
    recipe: dict[str, Any],
    shot_ids: list[str] | None = None,
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
    wanted = {item for item in (shot_ids or []) if item}
    aspect = recipe.get("aspectRatio") or "16:9"
    options = {
        "aspect_ratio": aspect if aspect in {"1:1", "16:9", "9:16", "4:3", "3:4"} else "16:9",
        "resolution": "1K",
        "count": 1,
    }
    job_ids: list[str] = []
    for _scene, shot in _iter_shots(recipe):
        if wanted and shot.get("id") not in wanted:
            continue
        if not force and shot.get("stillUrl"):
            continue
        refs = _plate_paths_for_shot(store, recipe, shot, resource_storage=resource_storage)
        job = create_queued_job(
            store,
            owner_user_id=owner_user_id,
            mode=workflow_id,
            prompt=_still_prompt(shot, recipe),
            options=options,
            references=refs,
            title=f"静帧 · {shot.get('title') or '分镜'}",
        )
        shot["stillJobId"] = job["id"]
        shot["stillUrl"] = None
        shot["stillStatus"] = "queued"
        job_ids.append(job["id"])
    return recipe, job_ids


def _job_id_from_media_url(url: str | None) -> str | None:
    text = str(url or "").strip()
    marker = "/api/jobs/"
    if marker not in text:
        return None
    rest = text.split(marker, 1)[1]
    job_id = rest.split("/", 1)[0].strip()
    return job_id or None


def _materialize_frame_file(
    store: JobStore,
    shot: dict[str, Any],
    *,
    role: str,
    resource_storage: Any | None = None,
) -> Path | None:
    if role == "end":
        job_id = shot.get("endFrameJobId")
        path = shot.get("endFramePath")
        url = shot.get("endFrameUrl")
    else:
        job_id = shot.get("firstFrameJobId")
        path = shot.get("firstFramePath")
        url = shot.get("firstFrameUrl")
    if path:
        candidate = Path(str(path))
        if candidate.is_file():
            return candidate
    resolved_job = str(job_id or "").strip() or _job_id_from_media_url(str(url or ""))
    if resolved_job:
        try:
            job = store.get(resolved_job)
        except KeyError:
            job = None
        if job:
            file_path = materialize_job_output_file(job, resource_storage=resource_storage, kind="image")
            if file_path is not None:
                return file_path
    return None


def recipe_frame_file(
    *,
    owner_user_id: str,
    project_id: str,
    shot_id: str,
    slot: str,
    suffix: str = ".png",
) -> Path:
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return settings.uploads_dir / owner_user_id / project_id / f"{shot_id}_{slot}{safe_suffix}"


def find_recipe_frame_file(
    *,
    owner_user_id: str,
    project_id: str,
    shot_id: str,
    slot: str,
) -> Path | None:
    directory = settings.uploads_dir / owner_user_id / project_id
    if not directory.is_dir():
        return None
    matches = sorted(path for path in directory.glob(f"{shot_id}_{slot}.*") if path.is_file())
    return matches[0] if matches else None


def save_recipe_shot_frame(
    recipe: dict[str, Any],
    *,
    owner_user_id: str,
    project_id: str,
    shot_id: str,
    slot: str,
    source: Path,
) -> dict[str, Any]:
    shot = find_recipe_shot(recipe, shot_id)
    if shot is None:
        raise ValueError("分镜不存在")
    if slot not in {"first", "end"}:
        raise ValueError("槽位必须是 first 或 end")
    dest = recipe_frame_file(
        owner_user_id=owner_user_id,
        project_id=project_id,
        shot_id=shot_id,
        slot=slot,
        suffix=source.suffix or ".png",
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    pending = dest.with_name(f".{dest.name}.{secrets.token_hex(4)}.tmp")
    try:
        shutil.copy2(source, pending)
        pending.replace(dest)
    finally:
        pending.unlink(missing_ok=True)
    for leftover in dest.parent.glob(f"{shot_id}_{slot}.*"):
        if leftover != dest:
            leftover.unlink(missing_ok=True)
    public_url = f"/api/director/recipes/{project_id}/frames/{shot_id}/{slot}"
    if slot == "first":
        shot["firstFramePath"] = str(dest)
        shot["firstFrameUrl"] = public_url
        shot["firstFrameJobId"] = None
        shot["usePreviousEndFrame"] = False
    else:
        shot["endFramePath"] = str(dest)
        shot["endFrameUrl"] = public_url
        shot["endFrameJobId"] = None
    return recipe


def _plate_file_for_slot(
    store: JobStore,
    slot: dict[str, Any],
    *,
    resource_storage: Any | None = None,
) -> Path | None:
    job_id = slot.get("imageJobId") or slot.get("image_job_id")
    if job_id:
        try:
            job = store.get(str(job_id))
        except KeyError:
            job = None
        if job:
            file_path = materialize_job_output_file(job, resource_storage=resource_storage, kind="image")
            if file_path is not None:
                return file_path
    library_id = str(slot.get("libraryAssetId") or slot.get("library_asset_id") or "").strip()
    from .director_library import find_library_asset_file, parse_library_asset_id_from_url

    if not library_id:
        library_id = parse_library_asset_id_from_url(slot.get("previewUrl") or slot.get("imageUrl")) or ""
    if library_id:
        try:
            asset = store.get_director_library_asset(library_id)
        except KeyError:
            asset = None
        if asset:
            path = find_library_asset_file(
                str(asset.get("owner_user_id") or ""),
                library_id,
                asset.get("image_path") if isinstance(asset.get("image_path"), str) else None,
            )
            if path is not None:
                return path
    return None


def _plate_paths_for_shot(
    store: JobStore,
    recipe: dict[str, Any],
    shot: dict[str, Any],
    *,
    resource_storage: Any | None = None,
    reserve: int = 0,
) -> list[str]:
    paths: list[str] = []
    for slot in recipe_assets_as_slots(recipe, shot, reserve=reserve):
        file_path = _plate_file_for_slot(store, slot, resource_storage=resource_storage)
        if file_path is not None:
            paths.append(str(file_path))
    return paths


def _reference_paths_for_shot(
    store: JobStore,
    recipe: dict[str, Any],
    shot: dict[str, Any],
    *,
    resource_storage: Any | None = None,
) -> list[str]:
    resolved = apply_recipe_continuity(recipe, shot)
    paths: list[str] = []
    first = _materialize_frame_file(store, resolved, role="first", resource_storage=resource_storage)
    if first is not None:
        paths.append(str(first))
    plates = _plate_paths_for_shot(
        store,
        recipe,
        resolved,
        resource_storage=resource_storage,
        reserve=1 if first is not None else 0,
    )
    if not plates:
        last = _materialize_frame_file(store, resolved, role="end", resource_storage=resource_storage)
        if last is not None:
            paths.append(str(last))
    paths.extend(plates)
    return paths[:H3_MAX_REFERENCE_IMAGES]


def render_recipe_shots(
    store: JobStore,
    *,
    owner_user_id: str,
    recipe: dict[str, Any],
    shot_ids: list[str] | None = None,
    render_pass: str = "final",
    resource_storage: Any | None = None,
    h3_prompt_refiner: Callable[[str, str], str] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    recipe = sync_recipe_asset_images(store, recipe, resource_storage=resource_storage)
    wanted = {item for item in (shot_ids or []) if item}
    job_ids: list[str] = []
    matched = 0
    for _scene, shot in _iter_shots(recipe):
        if wanted and shot.get("id") not in wanted:
            continue
        matched += 1
        resolved = apply_recipe_continuity(recipe, shot)
        submission = resolve_recipe_shot_submission(recipe, resolved, render_pass)
        errors = list(submission.get("errors") or [])
        if errors:
            shot["status"] = "failed"
            shot["error"] = "；".join(str(item) for item in errors if item)
            continue
        previous_render_state = {
            "jobId": shot.get("jobId"),
            "status": shot.get("status") or "idle",
            "progress": shot.get("progress") or 0,
            "outputVideoUrl": shot.get("outputVideoUrl"),
            "outputPath": shot.get("outputPath"),
        }
        previous_takes = [take for take in (shot.get("takes") or []) if isinstance(take, dict)]
        has_usable_previous_take = any(
            take.get("status") == "succeeded" or bool(take.get("videoUrl"))
            for take in previous_takes
        ) or bool(shot.get("outputVideoUrl"))
        shot["error"] = None
        refs = _reference_paths_for_shot(store, recipe, resolved, resource_storage=resource_storage)
        plan_items = list((submission.get("plan") or {}).get("items") or [])
        needs_first = any(item.get("role") == "first_frame" for item in plan_items)
        if needs_first and not refs:
            shot["status"] = "failed"
            shot["error"] = "缺少可提交的首帧文件"
            continue
        workflow_id = submission["workflowId"]
        if not refs:
            workflow_id = resolve_director_workflow(
                recipe.get("videoWorkflowFamily") or recipe.get("video_workflow_family"),
                "t2v",
            )
        shot["jobId"] = None
        shot["status"] = "queued"
        shot["progress"] = 4
        if on_progress is not None:
            on_progress(recipe)
        if h3_prompt_refiner is not None and (refs or not plan_items):
            try:
                prompt_mode = h3_prompt_mode(submission.get("plan") or {})
                polished_prompt = h3_prompt_refiner(str(submission["prompt"]), prompt_mode)
                polish_errors = validate_h3_polished_prompt(polished_prompt, submission.get("plan") or {})
                if polish_errors:
                    revision_request = (
                        f"{polished_prompt}\n\n"
                        "Validation feedback: " + "; ".join(polish_errors)
                        + f"\nRewrite the complete final {prompt_mode} prompt and fix every validation issue."
                    )
                    polished_prompt = h3_prompt_refiner(revision_request, prompt_mode)
                    polish_errors = validate_h3_polished_prompt(polished_prompt, submission.get("plan") or {})
                if polish_errors:
                    raise ValueError("；".join(polish_errors))
                submission["prompt"] = polished_prompt
            except Exception as error:
                if has_usable_previous_take:
                    shot.update(previous_render_state)
                else:
                    shot["jobId"] = None
                    shot["status"] = "failed"
                    shot["progress"] = 0
                shot["error"] = f"H3 提示词润色失败：{error}"
                if on_progress is not None:
                    on_progress(recipe)
                if isinstance(error, LlmError):
                    raise
                continue
        job = create_queued_job(
            store,
            owner_user_id=owner_user_id,
            mode=workflow_id,
            prompt=submission["prompt"],
            options={
                "aspect_ratio": submission.get("aspectRatio") or recipe.get("aspectRatio") or "16:9",
                "quality": submission.get("quality") or "1.0",
                "speed": submission.get("speed") or "balanced",
                "weight_profile": submission.get("weight_profile") or recipe.get("weightProfile") or "full",
                "duration": submission.get("durationSec") or 5,
            },
            references=refs,
            title=str(shot.get("title") or "分镜"),
        )
        shot["jobId"] = job["id"]
        shot["compiledPrompt"] = submission["prompt"]
        shot["status"] = "queued"
        shot["progress"] = 0
        pass_name = "preview" if render_pass == "preview" else "final"
        takes = [take for take in (shot.get("takes") or []) if isinstance(take, dict)]
        takes.append({
            "id": job["id"],
            "takeNumber": len(takes) + 1,
            "jobId": job["id"],
            "status": "queued",
            "progress": 0,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "promptSnapshot": submission.get("prompt") or "",
            "renderPass": pass_name,
        })
        shot["takes"] = takes
        job_ids.append(job["id"])
    if wanted and matched == 0:
        raise ValueError("没有找到要生成的镜头，请先保存后再试")
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
                "weight_profile": payload.get("weightProfile") or payload.get("weight_profile") or "full",
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
