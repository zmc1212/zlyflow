from __future__ import annotations

import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.error import URLError

from fastapi import BackgroundTasks, Body, Depends, File, Form, HTTPException, Path as FastApiPath, Query, Response, UploadFile
from fastapi.routing import APIRouter

_EPISODE_ID_PARAM = FastApiPath(description="剧集 ID")
_BEAT_ID_PARAM = FastApiPath(description="镜头 Beat ID")
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .config import settings
from .director_jobs import create_queued_job, job_asset_image_url, materialize_job_output_file
from .llm_client import LlmError
from .models import JobStatus
from .request_log import write_request_log
from .resource_storage import resource_object_url
from .workflow_registry import (
    CATALOG_GROUP_LIGHTX2V,
    director_route_key,
    resolve_director_workflow,
    workflow_for,
)
from .xiaji_asset_api import (
    IMAGE_SUFFIXES,
    MAX_IMAGE_BYTES,
    _character_slot_sources,
    _enqueue_queued_job,
    _materialize_image_ref,
    _resolve_image_workflow,
)
from .xiaji_asset_prompts import image_options_for_kind
from .xiaji_episode_prompts import (
    SCRIPT_PROMPT_VERSION,
    VIDEO_MOTION_PROMPT_VERSION,
    beat_render_prompt,
    beat_sketch_prompt,
    beat_video_prompt,
    build_script_messages,
    build_video_motion_messages,
    character_marker_color,
    public_video_pictures,
)
from .xiaji_literal_script import LITERAL_LINE_MAX_TOKENS, LITERAL_LINE_TIMEOUT_SECONDS
from .xiaji_episode_store import XiajiEpisodeStore, first_seen_line, allocate_chapter_text, split_original_lines
from .xiaji_episode_run_store import episode_runs_store
from .xiaji_llm_jobs import (
    finish_xiaji_llm_job,
    llm_failure_response,
    llm_jobs_store,
    set_xiaji_job_progress,
    start_xiaji_llm_job,
    start_xiaji_tracked_job,
)
from .xiaji_art_style import art_style_hint, settings_art_style_id
from .xiaji_visual_styles import settings_visual_style, visual_style_contract, visual_style_label
from .xiaji_compose import (
    XiajiComposeError,
    build_episode_zip,
    build_srt_content,
    clips_for_subtitles,
    compose_blockers,
    compose_concat_beats,
    compose_episode_film,
    compose_episode_ready,
    compose_filename,
    ffmpeg_ready,
    load_compose_bytes,
    parse_resolution,
    public_compose_fields,
    require_audio_for_project,
)
from .xiaji_project_api import require_xiaji_project


class FromAnalysisRequest(BaseModel):
    document_id: str | None = None
    force: bool = False


class EpisodePatch(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class BeatWrite(BaseModel):
    id: str | None = None
    kind: str = "action"
    heading: str = ""
    speaker: str = ""
    dialogue: str = ""
    action: str = ""
    character_ids: list[str] = Field(default_factory=list)
    scene_id: str | None = None
    prop_ids: list[str] = Field(default_factory=list)


class BeatsReplaceRequest(BaseModel):
    beats: list[BeatWrite] = Field(min_length=1, max_length=80)


class ScriptGenerateRequest(BaseModel):
    force: bool = False


class SketchRequest(BaseModel):
    force: bool = False
    model: str | None = None
    scene_view: Literal["front", "reverse"] = "front"


class RenderRequest(BaseModel):
    force: bool = False
    model: str | None = None
    scene_view: Literal["front", "reverse"] = "front"


class VideoRequest(BaseModel):
    force: bool = False
    family: str | None = None
    duration: float | None = None
    quality: str | None = None
    aspect_ratio: str | None = None
    speed: str | None = None
    custom_steps: int | None = None
    scene_view: Literal["front", "reverse"] = "front"


class VideoPromptRequest(BaseModel):
    force: bool = False
    family: str | None = None
    duration: float | None = None
    scene_view: Literal["front", "reverse"] = "front"


class ComposeRequest(BaseModel):
    resolution: str = "1280x720"
    add_subtitles: bool = True
    force: bool = False


class AutoRunRequest(BaseModel):
    family: str | None = None
    duration: float | None = None
    quality: str | None = None
    aspect_ratio: str | None = None
    speed: str | None = None
    custom_steps: int | None = None
    scene_view: Literal["front", "reverse"] = "front"


class BeatPatch(BaseModel):
    heading: str | None = Field(default=None, max_length=255)
    speaker: str | None = Field(default=None, max_length=128)
    dialogue: str | None = None
    action: str | None = None
    character_ids: list[str] | None = None
    scene_id: str | None = None
    prop_ids: list[str] | None = None
    video_prompt_zh: str | None = None
    video_duration: str | None = None


def _coerce_duration_seconds(*values: Any, default: float = 5.0) -> float:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        try:
            duration = float(text)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            return duration
    return default


def _episodes(app: Any) -> XiajiEpisodeStore:
    return app.state.xiaji_episode_store


def _episode_or_404(app: Any, episode_id: str, owner_user_id: str) -> dict[str, Any]:
    try:
        return _episodes(app).get_episode(episode_id, owner_user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="剧集不存在") from error


def _asset_index(assets: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for asset in assets:
        kind = str(asset.get("kind") or "")
        names = [str(asset.get("name") or "")]
        definition = asset.get("definition") if isinstance(asset.get("definition"), dict) else {}
        names.extend(str(item) for item in (definition.get("aliases") or []) if item)
        for name in names:
            key = name.strip()
            if key:
                index[(kind, key)] = asset
    return index


def _lookup_job(app: Any, job_id: str) -> dict[str, Any] | None:
    jobs = getattr(app.state, "store", None)
    if jobs is None or not job_id:
        return None
    try:
        return jobs.get(job_id)
    except KeyError:
        return None


def _fetch_episode_jobs_batch(jobs_store: Any, job_ids: set[str]) -> dict[str, Any]:
    if not job_ids or jobs_store is None:
        return {}
    results: dict[str, Any] = {}

    def _fetch_one(jid: str):
        try:
            return jid, jobs_store.get(jid)
        except Exception:
            return jid, None

    workers = min(len(job_ids), 16)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for jid, job in executor.map(_fetch_one, job_ids):
            if job is not None:
                results[jid] = job
    return results


def _lookup_job_cached(app: Any, job_id: str, jobs_cache: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not job_id:
        return None
    if jobs_cache is not None and job_id in jobs_cache:
        return jobs_cache[job_id]
    return _lookup_job(app, job_id)


_FAILED_JOB_STATUSES = {
    JobStatus.FAILED.value,
    JobStatus.INTERRUPTED.value,
    JobStatus.CANCELLED.value,
    "error",
    "failure",
    "timeout",
    "stopped",
    "canceled",
}


def _job_media_state(
    app: Any,
    job: dict[str, Any] | None,
    *,
    kind: str,
    failed_label: str,
    busy_slot: bool = False,
    missing_fails: bool = False,
) -> dict[str, str | None]:
    if not job:
        if missing_fails and busy_slot:
            return {"status": "failed", "url": None, "error": failed_label}
        return {"status": None, "url": None, "error": None}
    status = str(job.get("status") or "").strip().lower()
    url = job_asset_image_url(job, kind=kind, resource_storage=getattr(app.state, "resource_storage", None))
    if status in {JobStatus.SUCCEEDED.value, JobStatus.PARTIAL.value} and url:
        return {"status": "succeeded", "url": url, "error": None}
    if status in {JobStatus.SUCCEEDED.value, JobStatus.PARTIAL.value}:
        return {"status": "failed", "url": None, "error": str(job.get("error") or f"{failed_label}（没有可用成片）")}
    if status in _FAILED_JOB_STATUSES:
        return {"status": "failed", "url": None, "error": str(job.get("error") or failed_label)}
    if status == JobStatus.QUEUED.value:
        return {"status": "queued", "url": None, "error": None}
    if status == JobStatus.RUNNING.value:
        return {"status": "generating", "url": None, "error": None}
    if busy_slot:
        return {"status": "failed", "url": None, "error": str(job.get("error") or failed_label)}
    return {"status": None, "url": None, "error": None}


def _beat_slot_needs_job(job_id: str, status: str, url: Any) -> bool:
    if not str(job_id or "").strip():
        return False
    slot_status = str(status or "")
    if slot_status in {"queued", "generating"}:
        return True
    if slot_status == "failed":
        return False
    return not url


def _sync_beat_media_slot(
    store: Any,
    current: dict[str, Any],
    owner_user_id: str,
    *,
    url_key: str,
    status_key: str,
    error_key: str,
    state: dict[str, str | None],
) -> None:
    next_url = state["url"] or current.get(url_key)
    next_status = state["status"] or ("succeeded" if next_url else (current.get(status_key) or "draft"))
    next_error = state["error"]
    updates: dict[str, Any] = {}
    if state["status"] == "succeeded" and state["url"] and current.get(url_key) != state["url"]:
        updates[url_key] = state["url"]
    if next_status != (current.get(status_key) or ""):
        updates[status_key] = next_status
    if (next_error or "") != (current.get(error_key) or ""):
        updates[error_key] = next_error
    if updates:
        store.update_beat(current["id"], owner_user_id, **updates)
    if next_url:
        current[url_key] = next_url
    current[status_key] = next_status
    current[error_key] = next_error


def video_prompt_pair_from_job(job: dict[str, Any] | None) -> tuple[str, str] | None:
    if not isinstance(job, dict):
        return None
    response = job.get("response") if isinstance(job.get("response"), dict) else None
    if response is None and isinstance(job.get("llm_output"), dict):
        response = job.get("llm_output")
    if response is None and isinstance(job.get("options"), dict):
        nested = job["options"].get("response")
        response = nested if isinstance(nested, dict) else None
    if not isinstance(response, dict):
        return None
    zh = str(response.get("prompt_zh") or "").strip()
    en = str(response.get("prompt_en") or "").strip()
    if not zh or not en:
        return None
    return zh, en


def latest_video_prompt_jobs_by_beat(app: Any, owner_user_id: str, project_id: str) -> dict[str, dict[str, Any]]:
    store = llm_jobs_store(app)
    if store is None or not project_id:
        return {}
    latest: dict[str, dict[str, Any]] = {}
    for job in store.list_project_jobs(owner_user_id, project_id):
        if job.get("kind") != "video_prompt" or job.get("status") != "succeeded":
            continue
        beat_id = str((job.get("options") or {}).get("beat_id") or "").strip()
        if beat_id and beat_id not in latest:
            latest[beat_id] = job
    return latest


def _apply_latest_video_prompt_job(
    store: Any,
    current: dict[str, Any],
    owner_user_id: str,
    job: dict[str, Any] | None,
) -> None:
    pair = video_prompt_pair_from_job(job)
    if pair is None or job is None:
        return
    job_id = str(job.get("id") or job.get("job_id") or "").strip()
    if not job_id:
        return
    bound = str(current.get("video_prompt_job_id") or "").strip()
    zh, en = pair
    if bound == job_id:
        current["video_prompt_zh"] = current.get("video_prompt_zh") or zh
        current["video_prompt"] = current.get("video_prompt") or en
        return
    store.update_beat(
        current["id"],
        owner_user_id,
        video_prompt=en,
        video_prompt_zh=zh,
        video_prompt_job_id=job_id,
    )
    current["video_prompt"] = en
    current["video_prompt_zh"] = zh
    current["video_prompt_job_id"] = job_id


def _hydrate_episode(
    app: Any,
    episode: dict[str, Any],
    owner_user_id: str,
    jobs_cache: dict[str, Any] | None = None,
    assets_by_id: dict[str, Any] | None = None,
) -> dict[str, Any]:
    jobs = getattr(app.state, "store", None)
    if jobs is None:
        return _with_assets(app, episode, owner_user_id, assets_by_id)
    store = _episodes(app)
    prompt_jobs = latest_video_prompt_jobs_by_beat(app, owner_user_id, str(episode.get("project_id") or ""))
    sketched = 0
    generating = 0
    failed = 0
    next_beats = []
    for beat in episode.get("beats") or []:
        current = dict(beat)

        sketch_job_id = str(current.get("sketch_job_id") or "").strip()
        has_sketch = bool(current.get("sketch_url"))
        sketch_status = str(current.get("status") or "")
        need_sketch_check = bool(sketch_job_id and (sketch_status in {"queued", "generating"} or not has_sketch))

        if need_sketch_check:
            sketch_state = _job_media_state(
                app,
                _lookup_job_cached(app, sketch_job_id, jobs_cache),
                kind="image",
                failed_label="草图生成失败",
                busy_slot=sketch_status in {"queued", "generating"},
                missing_fails=False,
            )
            if sketch_state["status"] == "succeeded" and sketch_state["url"]:
                if current.get("sketch_url") != sketch_state["url"] or current.get("status") != "succeeded":
                    store.update_beat(
                        current["id"],
                        owner_user_id,
                        sketch_url=sketch_state["url"],
                        status="succeeded",
                        error=None,
                    )
                current["sketch_url"] = sketch_state["url"]
                current["status"] = "succeeded"
                current["error"] = None
            elif sketch_state["status"] == "failed":
                store.update_beat(current["id"], owner_user_id, status="failed", error=sketch_state["error"])
                current["status"] = "failed"
                current["error"] = sketch_state["error"]
            elif sketch_state["status"] in {"queued", "generating"}:
                if current.get("status") != sketch_state["status"]:
                    store.update_beat(current["id"], owner_user_id, status=sketch_state["status"])
                current["status"] = sketch_state["status"]

        render_job_id = str(current.get("render_job_id") or "").strip()
        has_render = bool(current.get("render_url"))
        render_status = str(current.get("render_status") or "")
        need_render_check = _beat_slot_needs_job(render_job_id, render_status, current.get("render_url"))

        if need_render_check:
            _sync_beat_media_slot(
                store,
                current,
                owner_user_id,
                url_key="render_url",
                status_key="render_status",
                error_key="render_error",
                state=_job_media_state(
                    app,
                    _lookup_job_cached(app, render_job_id, jobs_cache),
                    kind="image",
                    failed_label="渲染图生成失败",
                    busy_slot=True,
                    missing_fails=True,
                ),
            )
        else:
            current["render_status"] = current.get("render_status") or ("succeeded" if has_render else "draft")

        video_job_id = str(current.get("video_job_id") or "").strip()
        has_video = bool(current.get("video_url"))
        video_status = str(current.get("video_status") or "")
        need_video_check = _beat_slot_needs_job(video_job_id, video_status, current.get("video_url"))

        if need_video_check:
            _sync_beat_media_slot(
                store,
                current,
                owner_user_id,
                url_key="video_url",
                status_key="video_status",
                error_key="video_error",
                state=_job_media_state(
                    app,
                    _lookup_job_cached(app, video_job_id, jobs_cache),
                    kind="video",
                    failed_label="视频生成失败",
                    busy_slot=True,
                    missing_fails=True,
                ),
            )
        else:
            current["video_status"] = current.get("video_status") or ("succeeded" if has_video else "draft")

        _apply_latest_video_prompt_job(store, current, owner_user_id, prompt_jobs.get(str(current.get("id") or "")))

        if current.get("status") == "succeeded" and current.get("sketch_url"):
            sketched += 1
        elif current.get("status") in {"queued", "generating"}:
            generating += 1
        elif current.get("status") == "failed":
            failed += 1
        next_beats.append(current)
    episode["beats"] = next_beats
    sketchable = [item for item in next_beats if item.get("kind") != "scene_heading" or item.get("heading")]
    if sketchable and sketched == len(sketchable) and generating == 0:
        if episode.get("status") != "sketched":
            episode = store.update_episode(episode["id"], owner_user_id, status="sketched", clear_error=True)
            episode["beats"] = next_beats
    elif generating:
        if episode.get("status") not in {"sketching", "sketched"}:
            episode = store.update_episode(episode["id"], owner_user_id, status="sketching")
            episode["beats"] = next_beats
    episode["sketch_ready"] = sketched
    episode["sketch_failed"] = failed
    return _with_assets(app, episode, owner_user_id, assets_by_id)


def _with_assets(
    app: Any,
    episode: dict[str, Any],
    owner_user_id: str,
    assets_by_id: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if assets_by_id is None:
        assets = app.state.xiaji_asset_store.list_assets(owner_user_id, episode["project_id"])
        by_id = {item["id"]: item for item in assets}
    else:
        by_id = assets_by_id
    linked = []
    for link in episode.get("links") or []:
        asset = by_id.get(link["asset_id"])
        marker = character_marker_color(link["asset_id"]) if link.get("kind") == "character" else ("", "")
        linked.append(
            {
                **link,
                "name": asset["name"] if asset else link["asset_id"],
                "image_url": (asset or {}).get("image_url"),
                "definition": (asset or {}).get("definition") or {},
                "sketch_color": marker[0] or None,
                "sketch_color_name": marker[1] or None,
            }
        )
    episode["links"] = linked
    for beat in episode.get("beats") or []:
        if not isinstance(beat, dict):
            continue
        beat["video_pictures"] = public_video_pictures(
            _video_picture_slots(beat, by_id, scene_view="front", route="r2v")
        )
    public = dict(episode)
    public.pop("owner_user_id", None)
    public.pop("compose_key", None)
    project = None
    try:
        project = app.state.xiaji_project_store.get_project(str(episode.get("project_id") or ""), owner_user_id)
    except Exception:
        project = None
    require_audio = require_audio_for_project(project)
    blockers = compose_blockers(episode, require_audio=require_audio)
    public.update(public_compose_fields(episode))
    public["compose_blockers"] = blockers
    public["compose_ready"] = compose_episode_ready(episode, require_audio=require_audio)
    return public


def _hydrate_episode_single(app: Any, episode: dict[str, Any], owner_user_id: str) -> dict[str, Any]:
    project_id = str(episode.get("project_id") or "")
    assets = app.state.xiaji_asset_store.list_assets(owner_user_id, project_id) if project_id else []
    assets_by_id = {item["id"]: item for item in assets}

    job_ids_to_fetch: set[str] = set()
    for beat in episode.get("beats") or []:
        s_job = str(beat.get("sketch_job_id") or "").strip()
        if s_job and (beat.get("status") in {"queued", "generating"} or not beat.get("sketch_url")):
            job_ids_to_fetch.add(s_job)
        r_job = str(beat.get("render_job_id") or "").strip()
        if _beat_slot_needs_job(r_job, str(beat.get("render_status") or ""), beat.get("render_url")):
            job_ids_to_fetch.add(r_job)
        v_job = str(beat.get("video_job_id") or "").strip()
        if _beat_slot_needs_job(v_job, str(beat.get("video_status") or ""), beat.get("video_url")):
            job_ids_to_fetch.add(v_job)

    jobs_cache = _fetch_episode_jobs_batch(getattr(app.state, "store", None), job_ids_to_fetch) if job_ids_to_fetch else {}
    return _hydrate_episode(app, episode, owner_user_id, jobs_cache, assets_by_id)


def _pick_document(app: Any, owner_user_id: str, project_id: str, document_id: str | None) -> dict[str, Any]:
    store = app.state.xiaji_store
    if document_id:
        try:
            document = store.get_document(document_id, owner_user_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="文档不存在") from error
        if document.get("project_id") != project_id:
            raise HTTPException(status_code=404, detail="文档不存在")
        return document
    summaries = store.list_documents(owner_user_id, project_id)
    for summary in summaries:
        document = store.get_document(summary["id"], owner_user_id)
        episodes = ((document.get("analysis") or {}).get("episodes") or [])
        if episodes:
            return document
    raise HTTPException(status_code=422, detail="请先在内容库完成导入和分析")


def _materialize_from_analysis(app: Any, owner_user_id: str, project_id: str, payload: FromAnalysisRequest) -> list[dict[str, Any]]:
    document = _pick_document(app, owner_user_id, project_id, payload.document_id)
    analysis = document.get("analysis") or {}
    planned = [item for item in (analysis.get("episodes") or []) if isinstance(item, dict)]
    if not planned:
        raise HTTPException(status_code=422, detail="分析结果里还没有剧集规划")
    chapters = document.get("chapters") or []
    slices = allocate_chapter_text(chapters, len(planned))
    assets = app.state.xiaji_asset_store.list_assets(owner_user_id, project_id)
    index = _asset_index(assets)
    store = _episodes(app)
    created = []
    for offset, item in enumerate(planned):
        number = int(item.get("number") or offset + 1)
        lines = split_original_lines(slices[offset] if offset < len(slices) else "")
        episode = store.upsert_episode(
            owner_user_id,
            project_id=project_id,
            number=number,
            title=str(item.get("title") or f"第{number}集"),
            source_document_id=document["id"],
            content_summary=str(item.get("content_summary") or ""),
            main_conflict=str(item.get("main_conflict") or ""),
            cliffhanger=str(item.get("cliffhanger") or ""),
            key_events=[str(event) for event in (item.get("key_events") or []) if str(event).strip()],
            original_lines=lines,
            overwrite_script=payload.force,
        )
        if episode["status"] == "draft" or payload.force or not episode.get("links"):
            links = []
            for asset in assets:
                if asset.get("kind") not in {"character", "scene", "prop"}:
                    continue
                names = [asset["name"]]
                definition = asset.get("definition") or {}
                names.extend(str(alias) for alias in (definition.get("aliases") or []) if alias)
                seen = first_seen_line(episode["original_lines"], names)
                if seen or asset.get("kind") == "character" and definition.get("is_main"):
                    links.append({"asset_id": asset["id"], "kind": asset["kind"], "first_seen_line": seen})
            # also attach analysis names that exist as assets
            for kind, collection in (("character", analysis.get("characters") or []), ("scene", analysis.get("scenes") or []), ("prop", analysis.get("props") or [])):
                for entry in collection:
                    if not isinstance(entry, dict):
                        continue
                    name = str(entry.get("name") or "").strip()
                    asset = index.get((kind, name))
                    if asset and all(item["asset_id"] != asset["id"] for item in links):
                        aliases = [name, *[str(alias) for alias in (entry.get("aliases") or [])]]
                        links.append(
                            {
                                "asset_id": asset["id"],
                                "kind": kind,
                                "first_seen_line": first_seen_line(episode["original_lines"], aliases),
                            }
                        )
            episode = store.replace_links(episode["id"], owner_user_id, links)
        created.append(_hydrate_episode(app, episode, owner_user_id))
    return created


def _name_map(episode: dict[str, Any]) -> dict[tuple[str, str], str]:
    mapping: dict[tuple[str, str], str] = {}
    for link in episode.get("links") or []:
        name = str(link.get("name") or "").strip()
        if name:
            mapping[(str(link.get("kind")), name)] = str(link["asset_id"])
        definition = link.get("definition") if isinstance(link.get("definition"), dict) else {}
        for alias in definition.get("aliases") or []:
            key = str(alias or "").strip()
            if key:
                mapping[(str(link.get("kind")), key)] = str(link["asset_id"])
    return mapping


def _script_llm_payload(app: Any, episode: dict[str, Any], owner_user_id: str) -> dict[str, Any]:
    project = require_xiaji_project(app, episode["project_id"], owner_user_id)
    settings = project.get("settings") if isinstance(project.get("settings"), dict) else {}
    style_id = settings_art_style_id(settings)
    visual_id = settings_visual_style(settings)
    style_parts = []
    if visual_id:
        style_parts.append(f"{visual_style_label(visual_id)}。{visual_style_contract(visual_id)}".strip("。"))
    art_hint = art_style_hint(style_id)
    if art_hint:
        style_parts.append(art_hint)
    return {
        "original_lines": episode.get("original_lines") or [],
        "characters": [item["name"] for item in episode.get("links") or [] if item.get("kind") == "character"],
        "scenes": [item["name"] for item in episode.get("links") or [] if item.get("kind") == "scene"],
        "props": [item["name"] for item in episode.get("links") or [] if item.get("kind") == "prop"],
        "visual_style": " ".join(style_parts),
        "art_style_id": style_id,
        "title": episode.get("title") or "",
        "summary": episode.get("content_summary") or "",
        "name_to_asset": _name_map(episode),
    }


def _public_name_map(mapping: dict[tuple[str, str], str]) -> dict[str, str]:
    return {f"{kind}:{name}": asset_id for (kind, name), asset_id in mapping.items()}


def _start_script_llm_job(app: Any, episode: dict[str, Any], owner_user_id: str, payload: dict[str, Any]) -> str | None:
    messages = build_script_messages(
        original_lines=list(payload.get("original_lines") or []),
        characters=list(payload.get("characters") or []),
        scenes=list(payload.get("scenes") or []),
        props=list(payload.get("props") or []),
        visual_style=str(payload.get("visual_style") or ""),
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or ""),
    )
    ep_title = f"第{episode.get('number')}集 {episode.get('title') or ''}".strip()
    return start_xiaji_llm_job(
        app,
        owner_user_id=owner_user_id,
        project_id=str(episode.get("project_id") or ""),
        kind="script",
        target=ep_title,
        title=f"生成脚本 · {ep_title}",
        messages=messages,
        parameters={
            "episode_id": episode["id"],
            "episode_number": episode.get("number"),
            "title": payload.get("title") or "",
            "summary": payload.get("summary") or "",
            "visual_style": payload.get("visual_style") or "",
            "original_lines": payload.get("original_lines") or [],
            "characters": payload.get("characters") or [],
            "scenes": payload.get("scenes") or [],
            "props": payload.get("props") or [],
            "name_to_asset": _public_name_map(payload.get("name_to_asset") or {}),
            "prompt_version": SCRIPT_PROMPT_VERSION,
            "script_mode": "literal",
            "line_count": len(payload.get("original_lines") or []),
            "timeout_seconds": LITERAL_LINE_TIMEOUT_SECONDS,
        },
        temperature=0.2,
        max_tokens=LITERAL_LINE_MAX_TOKENS,
    )


def _run_script_generation_sync(app: Any, episode_id: str, owner_user_id: str, job_id: str | None = None) -> None:
    write_request_log("xiaji-generate-script", {"phase": "worker-start", "episode_id": episode_id})
    try:
        episode = _hydrate_episode(app, _episodes(app).get_episode(episode_id, owner_user_id), owner_user_id)
        payload = _script_llm_payload(app, episode, owner_user_id)
        if not job_id:
            job_id = _start_script_llm_job(app, episode, owner_user_id, payload)
        store = llm_jobs_store(app)

        def on_progress(done: int, total: int) -> None:
            if not job_id or store is None:
                return
            store.set_progress(
                job_id,
                10 + int(80 * done / max(1, total)),
                message=f"逐行标注 {done}/{total}",
            )

        payload["on_progress"] = on_progress
        beats = app.state.llm_provider.generate_xiaji_script(payload)
        _episodes(app).replace_beats(episode_id, owner_user_id, beats, status="script_ready")
        finish_xiaji_llm_job(app, job_id, status="succeeded", response={"beats": beats})
        write_request_log(
            "xiaji-generate-script",
            {"phase": "done", "episode_id": episode_id, "beats": len(beats)},
        )
    except Exception as error:
        _episodes(app).update_episode(episode_id, owner_user_id, status="draft", error=str(error))
        finish_xiaji_llm_job(
            app,
            job_id,
            status="failed",
            error=str(error),
            response=llm_failure_response(error),
        )
        write_request_log(
            "xiaji-generate-script",
            {"phase": "failed", "episode_id": episode_id, "error": str(error)[:300]},
        )


async def _run_script_generation(app: Any, episode_id: str, owner_user_id: str, job_id: str | None = None) -> None:
    await run_in_threadpool(_run_script_generation_sync, app, episode_id, owner_user_id, job_id)


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


def _append_ref_file(
    app: Any,
    paths: list[str],
    seen: set[str],
    *,
    job_id: str,
    url: str,
    stem: str,
    object_key: str = "",
) -> None:
    if len(paths) >= 9:
        return
    job_id = str(job_id or "").strip()
    if job_id and f"job:{job_id}" in seen:
        return
    path = _materialize_image_ref(
        app,
        job_id=job_id,
        url=url,
        object_key=object_key,
        stem=stem,
    )
    if not path:
        return
    if path in seen:
        if job_id:
            seen.add(f"job:{job_id}")
        return
    seen.add(path)
    if job_id:
        seen.add(f"job:{job_id}")
    paths.append(path)


def _append_scene_ref(
    app: Any,
    paths: list[str],
    seen: set[str],
    scene: dict[str, Any],
    *,
    scene_view: str,
) -> None:
    definition = scene.get("definition") if isinstance(scene.get("definition"), dict) else {}
    jobs_map = definition.get("scene_jobs") if isinstance(definition.get("scene_jobs"), dict) else {}
    if scene_view == "reverse":
        _append_ref_file(
            app,
            paths,
            seen,
            job_id=str(jobs_map.get("reverse") or ""),
            url=str(definition.get("back_image_url") or ""),
            stem=f"{scene['id']}-reverse",
        )
    _append_ref_file(
        app,
        paths,
        seen,
        job_id=str(scene.get("image_job_id") or jobs_map.get("master") or ""),
        url=str(scene.get("image_url") or ""),
        stem=f"{scene['id']}-front",
        object_key=str(scene.get("image_object_key") or ""),
    )


def _append_character_refs(app: Any, paths: list[str], seen: set[str], beat: dict[str, Any], by_id: dict[str, Any]) -> None:
    for asset_id in [str(item) for item in (beat.get("character_ids") or [])[:4]]:
        asset = by_id.get(asset_id)
        if not asset:
            continue
        portrait_job, portrait_url, portrait_key = _character_slot_sources(asset, "portrait")
        _append_ref_file(
            app,
            paths,
            seen,
            job_id=portrait_job,
            url=portrait_url,
            object_key=portrait_key,
            stem=f"{asset['id']}-portrait",
        )
        for look in (asset.get("definition") or {}).get("looks") or []:
            if not isinstance(look, dict):
                continue
            look_id = str(look.get("id") or "").strip()
            look_job, look_url, look_key = _character_slot_sources(asset, "look", look_id=look_id)
            if not (look_job or look_url or look_key):
                continue
            _append_ref_file(
                app,
                paths,
                seen,
                job_id=look_job,
                url=look_url,
                object_key=look_key,
                stem=f"{asset['id']}-look-{look_id or '0'}",
            )
            break


def _definition_map(asset: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(asset, dict):
        return {}
    definition = asset.get("definition")
    return definition if isinstance(definition, dict) else {}


def _join_bits(*parts: Any) -> str:
    return "；".join(str(part).strip() for part in parts if str(part or "").strip())


def _character_identity_text(asset: dict[str, Any]) -> str:
    definition = _definition_map(asset)
    return _join_bits(
        definition.get("role"),
        definition.get("gender"),
        definition.get("age_group"),
        definition.get("body_type"),
    )


def _character_face_text(asset: dict[str, Any]) -> str:
    definition = _definition_map(asset)
    return str(definition.get("face_prompt") or definition.get("description") or asset.get("name") or "").strip()


def _look_costume_text(look: dict[str, Any]) -> str:
    return str(
        look.get("appearance_details")
        or look.get("costume")
        or look.get("description")
        or look.get("name")
        or ""
    ).strip()


def _scene_environment_text(scene: dict[str, Any]) -> str:
    definition = _definition_map(scene)
    return _join_bits(
        definition.get("scene_type"),
        definition.get("time_of_day"),
        definition.get("environment_prompt") or definition.get("description"),
    )


def _beat_can_make_video(beat: dict[str, Any] | None) -> bool:
    if not isinstance(beat, dict):
        return False
    if str(beat.get("kind") or "") == "scene_heading" and not (beat.get("action") or beat.get("heading")):
        return False
    return True


def previous_video_beat(episode: dict[str, Any], beat: dict[str, Any]) -> dict[str, Any] | None:
    current_seq = int(beat.get("sequence") or 0)
    previous: dict[str, Any] | None = None
    for item in episode.get("beats") or []:
        if not isinstance(item, dict):
            continue
        if int(item.get("sequence") or 0) >= current_seq:
            break
        if _beat_can_make_video(item):
            previous = item
    return previous


def _require_video_bridge(episode: dict[str, Any], beat: dict[str, Any]) -> dict[str, Any] | None:
    previous = previous_video_beat(episode, beat)
    if previous is None:
        return None
    if not str(previous.get("video_url") or "").strip():
        raise HTTPException(status_code=422, detail="请先生成上一镜视频")
    if not str(beat.get("video_in_frame_url") or "").strip():
        raise HTTPException(status_code=422, detail="请先截取上一镜衔接帧")
    return previous


def _video_picture_slots(
    beat: dict[str, Any],
    by_id: dict[str, Any],
    *,
    scene_view: str = "front",
    route: str = "r2v",
) -> list[dict[str, Any]]:
    pictures: list[dict[str, Any]] = []

    def add(
        *,
        role: str,
        name: str,
        label_zh: str,
        label_en: str,
        job_id: str = "",
        url: str = "",
        object_key: str = "",
        stem: str = "",
        material: str = "",
        detail_zh: str = "",
        detail_en: str = "",
    ) -> None:
        if len(pictures) >= 9:
            return
        if not (str(job_id or "").strip() or str(url or "").strip() or str(object_key or "").strip()):
            return
        index = len(pictures) + 1
        pictures.append(
            {
                "index": index,
                "tag": f"<Picture {index}>",
                "role": role,
                "material": material or role,
                "name": name,
                "label_zh": label_zh,
                "label_en": label_en,
                "detail_zh": detail_zh,
                "detail_en": detail_en,
                "job_id": str(job_id or ""),
                "url": str(url or ""),
                "object_key": str(object_key or ""),
                "stem": stem or f"{beat.get('id')}-{role}-{index}",
            }
        )

    cast_names = [
        str((by_id.get(str(item)) or {}).get("name") or "").strip()
        for item in (beat.get("character_ids") or [])
        if str((by_id.get(str(item)) or {}).get("name") or "").strip()
    ]
    scene_id = str(beat.get("scene_id") or "").strip()
    scene_preview = by_id.get(scene_id) if scene_id else None
    heading = str(beat.get("heading") or "").strip()
    action = str(beat.get("action") or "").strip()
    bridge_url = str(beat.get("video_in_frame_url") or "").strip()
    if bridge_url:
        add(
            role="bridge_in",
            material="previous_last_frame",
            name="上一镜衔接帧",
            label_zh="上一镜视频截图，时间码 0.00 秒的衔接起点",
            label_en="previous-shot last-frame still at 0.00 seconds; start here",
            detail_zh=_join_bits(
                "素材=上一镜视频截图（默认末帧，可手动改截）",
                f"镜头={heading}" if heading else "",
                "职责=锁定 t=0，0-1.5s 必须从此帧连续过渡到本镜精绘",
            ),
            detail_en=_join_bits(
                "MATERIAL=previous shot video screenshot",
                f"SLATE={heading}" if heading else "",
                "DUTY=lock t=0; 0-1.5s must transform into the current render",
            ),
            url=bridge_url,
            stem=f"{beat.get('id')}-bridge-in",
        )
        render_detail_zh = _join_bits(
            "素材=本镜精绘目标构图（约 1.5 秒到达，不是全片结尾）",
            f"镜头={heading}" if heading else "",
            f"动作={action}" if action else "",
            f"出场={('、'.join(cast_names))}" if cast_names else "",
            f"场景={scene_preview.get('name')}" if isinstance(scene_preview, dict) and scene_preview.get("name") else "",
            "职责=1.5s 到达此构图，之后从这里按本镜动作向前演",
        )
        render_detail_en = _join_bits(
            "MATERIAL=current beat render as 1.5s target composition, not the final freeze",
            f"SLATE={heading}" if heading else "",
            f"ACTION={action}" if action else "",
            f"CAST={', '.join(cast_names)}" if cast_names else "",
            f"PLACE={scene_preview.get('name')}" if isinstance(scene_preview, dict) and scene_preview.get("name") else "",
            "DUTY=arrive here by 1.5s then continue the beat action",
        )
        if route == "r2v":
            add(
                role="shot_render",
                material="shot_render",
                name="本镜精绘",
                label_zh="本镜精绘，约 1.5 秒到达的构图，不是全片结尾静帧",
                label_en="current beat render; arrive by 1.5 seconds, then continue",
                detail_zh=render_detail_zh,
                detail_en=render_detail_en,
                job_id=str(beat.get("render_job_id") or ""),
                url=str(beat.get("render_url") or ""),
                stem=f"{beat.get('id')}-render",
            )
        if route != "r2v":
            return pictures
    else:
        first_detail_zh = _join_bits(
            "素材=本镜精绘首帧（不是头像、不是空场景）",
            f"镜头={heading}" if heading else "",
            f"动作={action}" if action else "",
            f"出场={('、'.join(cast_names))}" if cast_names else "",
            f"场景={scene_preview.get('name')}" if isinstance(scene_preview, dict) and scene_preview.get("name") else "",
            "职责=锁定 t=0 机位、构图、站位，后续运动只能从此帧向前",
        )
        first_detail_en = _join_bits(
            "MATERIAL=approved shot render as first frame",
            f"SLATE={heading}" if heading else "",
            f"ACTION={action}" if action else "",
            f"CAST={', '.join(cast_names)}" if cast_names else "",
            f"PLACE={scene_preview.get('name')}" if isinstance(scene_preview, dict) and scene_preview.get("name") else "",
            "DUTY=lock camera, composition, blocking at 0.00s",
        )
        add(
            role="first_frame",
            material="shot_render",
            name="本镜精绘首帧",
            label_zh="本镜精绘首帧，时间码 0.00 秒的构图、机位和站位",
            label_en="approved first-frame render at 0.00 seconds; keep this composition",
            detail_zh=first_detail_zh,
            detail_en=first_detail_en,
            job_id=str(beat.get("render_job_id") or ""),
            url=str(beat.get("render_url") or ""),
            stem=f"{beat.get('id')}-render",
        )
        if route != "r2v":
            return pictures
    for asset_id in [str(item) for item in (beat.get("character_ids") or [])[:4]]:
        asset = by_id.get(asset_id)
        if not asset:
            continue
        name = str(asset.get("name") or "角色")
        identity = _character_identity_text(asset)
        face = _character_face_text(asset)
        portrait_job, portrait_url, portrait_key = _character_slot_sources(asset, "portrait")
        add(
            role="portrait",
            material="character_portrait",
            name=name,
            label_zh=f"{name} 头像素材，只锁定脸与身份",
            label_en=f"character portrait still of {name}; FACE identity lock only",
            detail_zh=_join_bits(
                "素材=角色头像",
                f"人物={name}",
                f"身份={identity}" if identity else "",
                f"外貌={face}" if face else "",
                "职责=只锁定脸与身份，不得改首帧站位或构图",
            ),
            detail_en=_join_bits(
                "MATERIAL=character portrait",
                f"SUBJECT={name}",
                f"IDENTITY={identity}" if identity else "",
                f"APPEARANCE={face}" if face else "",
                "DUTY=lock face and identity only",
            ),
            job_id=portrait_job,
            url=portrait_url,
            object_key=portrait_key,
            stem=f"{asset['id']}-portrait",
        )
        for look in (asset.get("definition") or {}).get("looks") or []:
            if not isinstance(look, dict):
                continue
            look_id = str(look.get("id") or "").strip()
            look_job, look_url, look_key = _character_slot_sources(asset, "look", look_id=look_id)
            look_name = str(look.get("name") or "造型")
            costume = _look_costume_text(look)
            add(
                role="look",
                material="character_costume",
                name=f"{name}·{look_name}",
                label_zh=f"{name} 造型素材「{look_name}」，只锁定服装",
                label_en=f"costume still of {name} named {look_name}; COSTUME lock only",
                detail_zh=_join_bits(
                    "素材=角色造型图",
                    f"人物={name}",
                    f"造型名={look_name}",
                    f"服装={costume}" if costume else "",
                    "职责=只锁定服装与体态，不得改首帧站位",
                ),
                detail_en=_join_bits(
                    "MATERIAL=character costume / turnaround",
                    f"SUBJECT={name}",
                    f"LOOK={look_name}",
                    f"COSTUME={costume}" if costume else "",
                    "DUTY=lock clothing only",
                ),
                job_id=look_job,
                url=look_url,
                object_key=look_key,
                stem=f"{asset['id']}-look-{look_id or '0'}",
            )
            break
    scene = scene_preview if isinstance(scene_preview, dict) else None
    if scene:
        definition = _definition_map(scene)
        jobs_map = definition.get("scene_jobs") if isinstance(definition.get("scene_jobs"), dict) else {}
        scene_name = str(scene.get("name") or "场景")
        environment = _scene_environment_text(scene)
        if scene_view == "reverse":
            add(
                role="scene_reverse",
                material="scene_reverse_plate",
                name=f"{scene_name}·背面",
                label_zh=f"场景「{scene_name}」背面环境素材，只锁定空间",
                label_en=f"reverse environment plate of {scene_name}",
                detail_zh=_join_bits("素材=场景背面图", f"场景={scene_name}", f"环境={environment}" if environment else "", "职责=只锁定背面空间"),
                detail_en=_join_bits("MATERIAL=scene reverse plate", f"PLACE={scene_name}", f"ENVIRONMENT={environment}" if environment else "", "DUTY=lock reverse space only"),
                job_id=str(jobs_map.get("reverse") or ""),
                url=str(definition.get("back_image_url") or ""),
                stem=f"{scene['id']}-reverse",
            )
        add(
            role="scene",
            material="scene_plate",
            name=scene_name,
            label_zh=f"场景「{scene_name}」正面环境素材，只锁定空间",
            label_en=f"front environment plate of {scene_name}; space lock only",
            detail_zh=_join_bits(
                "素材=场景正面环境图",
                f"场景={scene_name}",
                f"环境={environment}" if environment else "",
                "职责=只锁定空间与光线，不得改首帧人物站位",
            ),
            detail_en=_join_bits(
                "MATERIAL=scene front plate",
                f"PLACE={scene_name}",
                f"ENVIRONMENT={environment}" if environment else "",
                "DUTY=lock environment only",
            ),
            job_id=str(scene.get("image_job_id") or jobs_map.get("master") or ""),
            url=str(scene.get("image_url") or ""),
            object_key=str(scene.get("image_object_key") or ""),
            stem=f"{scene['id']}-front",
        )
    return pictures


def _materialize_picture_slots(app: Any, pictures: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for item in pictures:
        _append_ref_file(
            app,
            paths,
            seen,
            job_id=str(item.get("job_id") or ""),
            url=str(item.get("url") or ""),
            object_key=str(item.get("object_key") or ""),
            stem=str(item.get("stem") or f"pic-{item.get('index')}"),
        )
    return paths


def _reference_paths(
    app: Any,
    episode: dict[str, Any],
    beat: dict[str, Any],
    owner_user_id: str,
    *,
    scene_view: str = "front",
    stage: Literal["sketch", "render"] = "sketch",
) -> list[str]:
    assets = app.state.xiaji_asset_store.list_assets(owner_user_id, episode["project_id"])
    by_id = {item["id"]: item for item in assets}
    paths: list[str] = []
    seen: set[str] = set()
    scene_id = str(beat.get("scene_id") or "").strip()
    scene = by_id.get(scene_id) if scene_id else None
    if stage == "render":
        _append_ref_file(
            app,
            paths,
            seen,
            job_id=str(beat.get("sketch_job_id") or ""),
            url=str(beat.get("sketch_url") or ""),
            stem=f"{beat['id']}-sketch",
        )
        _append_character_refs(app, paths, seen, beat, by_id)
        if scene:
            _append_scene_ref(app, paths, seen, scene, scene_view=scene_view)
        return paths[:9]
    if scene:
        _append_scene_ref(app, paths, seen, scene, scene_view=scene_view)
    return paths[:9]


def _submit_sketch(
    app: Any,
    owner_user_id: str,
    episode: dict[str, Any],
    beat: dict[str, Any],
    payload: SketchRequest,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if beat.get("kind") == "scene_heading" and not (beat.get("action") or beat.get("heading")):
        raise HTTPException(status_code=422, detail="这一条没有可生成的画面")
    current_status = str(beat.get("status") or "")
    if not payload.force and current_status in {"queued", "generating", "succeeded"} and beat.get("sketch_job_id"):
        return episode, None
    project = require_xiaji_project(app, episode["project_id"], owner_user_id)
    settings = project.get("settings") if isinstance(project.get("settings"), dict) else {}
    assets = app.state.xiaji_asset_store.list_assets(owner_user_id, episode["project_id"])
    prompt = beat_sketch_prompt(
        beat,
        assets=assets,
        visual_style=settings_visual_style(settings),
        art_style_id=settings_art_style_id(settings),
        ethnicity=str(settings.get("ethnicity") or "Chinese"),
    )
    workflow_id = _resolve_image_workflow(app, payload.model)
    refs = _reference_paths(
        app, episode, beat, owner_user_id, scene_view=payload.scene_view, stage="sketch"
    )
    try:
        job = create_queued_job(
            app.state.store,
            owner_user_id=owner_user_id,
            mode=workflow_id,
            prompt=prompt,
            options=image_options_for_kind("sketch"),
            references=refs,
            title=f"导台2 镜头草图 · 第{episode['number']}集 · {beat.get('sequence')}",
        )
    except ValueError:
        job = create_queued_job(
            app.state.store,
            owner_user_id=owner_user_id,
            mode=workflow_id,
            prompt=prompt,
            options=image_options_for_kind("sketch"),
            title=f"导台2 镜头草图 · 第{episode['number']}集 · {beat.get('sequence')}",
        )
    updated = _episodes(app).update_beat(
        beat["id"],
        owner_user_id,
        sketch_job_id=job["id"],
        sketch_prompt=prompt,
        sketch_model=workflow_id,
        status="queued",
        error=None,
    )
    updated = _episodes(app).update_episode(episode["id"], owner_user_id, status="sketching", clear_error=True)
    updated["beats"] = _episodes(app).get_episode(episode["id"], owner_user_id)["beats"]
    return updated, job


def _submit_render(
    app: Any,
    owner_user_id: str,
    episode: dict[str, Any],
    beat: dict[str, Any],
    payload: RenderRequest,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not str(beat.get("sketch_url") or "").strip() and not str(beat.get("sketch_job_id") or "").strip():
        raise HTTPException(status_code=422, detail="请先生成草图")
    render_status = str(beat.get("render_status") or "")
    if not payload.force and render_status in {"queued", "generating"} and beat.get("render_job_id"):
        return episode, None
    if not payload.force and beat.get("render_url") and beat.get("render_job_id"):
        return episode, None
    project = require_xiaji_project(app, episode["project_id"], owner_user_id)
    settings = project.get("settings") if isinstance(project.get("settings"), dict) else {}
    assets = app.state.xiaji_asset_store.list_assets(owner_user_id, episode["project_id"])
    prompt = beat_render_prompt(
        beat,
        assets=assets,
        visual_style=settings_visual_style(settings),
        art_style_id=settings_art_style_id(settings),
        ethnicity=str(settings.get("ethnicity") or "Chinese"),
    )
    workflow_id = _resolve_image_workflow(app, payload.model)
    refs = _reference_paths(
        app, episode, beat, owner_user_id, scene_view=payload.scene_view, stage="render"
    )
    if not refs:
        raise HTTPException(status_code=422, detail="无法读取草图文件，请重新生成草图")
    try:
        job = create_queued_job(
            app.state.store,
            owner_user_id=owner_user_id,
            mode=workflow_id,
            prompt=prompt,
            options=image_options_for_kind("render"),
            references=refs,
            title=f"导台2 镜头渲染 · 第{episode['number']}集 · {beat.get('sequence')}",
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error) or "渲染图参考图无效") from error
    updated = _episodes(app).update_beat(
        beat["id"],
        owner_user_id,
        render_job_id=job["id"],
        render_prompt=prompt,
        render_model=workflow_id,
        render_url=None,
        render_status="queued",
        render_error=None,
    )
    updated["beats"] = _episodes(app).get_episode(episode["id"], owner_user_id)["beats"]
    return updated, job


def _resolve_video_workflow(requested: str | None) -> str:
    requested_id = (requested or "").strip()
    if requested_id:
        try:
            definition = workflow_for(requested_id)
        except (KeyError, ValueError):
            definition = None
        if definition is not None and director_route_key(definition) in {"i2v", "r2v"}:
            return requested_id
        route = "r2v" if requested_id == CATALOG_GROUP_LIGHTX2V else "i2v"
        return resolve_director_workflow(requested_id, route)
    return resolve_director_workflow(CATALOG_GROUP_LIGHTX2V, "r2v")


def _submit_video(
    app: Any,
    owner_user_id: str,
    episode: dict[str, Any],
    beat: dict[str, Any],
    payload: VideoRequest,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not str(beat.get("render_url") or "").strip() and not str(beat.get("render_job_id") or "").strip():
        raise HTTPException(status_code=422, detail="请先生成渲染图")
    _require_video_bridge(episode, beat)
    video_status = str(beat.get("video_status") or "")
    if not payload.force and video_status in {"queued", "generating"} and beat.get("video_job_id"):
        return episode, None
    if not payload.force and beat.get("video_url") and beat.get("video_job_id") and video_status != "failed":
        return episode, None
    workflow_id = _resolve_video_workflow(payload.family)
    try:
        definition = workflow_for(workflow_id)
    except (KeyError, ValueError):
        definition = None
    route = director_route_key(definition) if definition is not None else "i2v"
    if "r2v" in str(workflow_id).lower():
        route = "r2v"
    assets = app.state.xiaji_asset_store.list_assets(owner_user_id, episode["project_id"])
    by_id = {item["id"]: item for item in assets}
    pictures = _video_picture_slots(beat, by_id, scene_view=payload.scene_view, route=route or "i2v")
    refs = _materialize_picture_slots(app, pictures)
    if not refs:
        raise HTTPException(status_code=422, detail="无法读取渲染图文件，请重新生成渲染图")
    stored_en = str(beat.get("video_prompt") or "").strip()
    use_llm_prompt = bool(stored_en and str(beat.get("video_prompt_zh") or "").strip())
    prompt = stored_en if use_llm_prompt else beat_video_prompt(
        beat,
        route=route or "i2v",
        picture_count=len(pictures) or len(refs),
        pictures=pictures,
    )
    options: dict[str, Any] = {}
    options["duration"] = _coerce_duration_seconds(payload.duration, beat.get("video_duration"))
    if payload.quality:
        options["quality"] = payload.quality
    if payload.aspect_ratio:
        options["aspect_ratio"] = payload.aspect_ratio
    if payload.speed:
        options["speed"] = payload.speed
    if payload.custom_steps is not None:
        options["custom_steps"] = payload.custom_steps
    try:
        job = create_queued_job(
            app.state.store,
            owner_user_id=owner_user_id,
            mode=workflow_id,
            prompt=prompt,
            options=options or None,
            references=refs,
            title=f"导台2 镜头视频 · 第{episode['number']}集 · {beat.get('sequence')}",
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error) or "视频参数无效") from error
    duration_text = f"{options['duration']:g}"
    updated = _episodes(app).update_beat(
        beat["id"],
        owner_user_id,
        video_job_id=job["id"],
        video_model=workflow_id,
        video_url=None,
        video_duration=duration_text or None,
        video_status="queued",
        video_error=None,
    )
    updated["beats"] = _episodes(app).get_episode(episode["id"], owner_user_id)["beats"]
    return updated, job


def _video_route_for_family(family: str | None) -> tuple[str, str]:
    workflow_id = _resolve_video_workflow(family)
    try:
        definition = workflow_for(workflow_id)
    except (KeyError, ValueError):
        definition = None
    route = director_route_key(definition) if definition is not None else "i2v"
    if "r2v" in str(workflow_id).lower():
        route = "r2v"
    return workflow_id, route or "i2v"


def generate_beat_video_prompt(
    app: Any,
    owner_user_id: str,
    episode: dict[str, Any],
    beat: dict[str, Any],
    payload: VideoPromptRequest,
) -> dict[str, Any]:
    beat_id = str(beat.get("id") or "")
    if not str(beat.get("render_url") or "").strip() and not str(beat.get("render_job_id") or "").strip():
        raise HTTPException(status_code=422, detail="请先生成渲染图")
    llm_provider = getattr(app.state, "llm_provider", None)
    if llm_provider is None:
        raise HTTPException(status_code=503, detail="大模型未配置")
    available, reason = llm_provider.availability()
    if not available:
        raise HTTPException(status_code=503, detail=reason or "大模型未配置")
    _workflow_id, route = _video_route_for_family(payload.family)
    assets = app.state.xiaji_asset_store.list_assets(owner_user_id, episode["project_id"])
    by_id = {item["id"]: item for item in assets}
    pictures = _video_picture_slots(beat, by_id, scene_view=payload.scene_view, route=route)
    if not pictures:
        raise HTTPException(status_code=422, detail="没有可声明的参考图，请先精绘")
    duration = _coerce_duration_seconds(payload.duration, beat.get("video_duration"))
    project = require_xiaji_project(app, episode["project_id"], owner_user_id)
    settings = project.get("settings") if isinstance(project.get("settings"), dict) else {}
    visual_style = settings_visual_style(settings)
    art_style_id = settings_art_style_id(settings)
    messages = build_video_motion_messages(
        beat=beat,
        pictures=pictures,
        duration=duration,
        visual_style=visual_style,
        art_style_id=art_style_id,
        route=route,
    )
    heading = str(beat.get("heading") or f"镜头 {beat.get('sequence')}")
    job_id = start_xiaji_llm_job(
        app,
        owner_user_id=owner_user_id,
        project_id=str(episode.get("project_id") or ""),
        kind="video_prompt",
        target=f"第{episode.get('number')}集 · {heading}",
        title=f"镜头视频提示词 · 第{episode.get('number')}集 · {heading}",
        messages=messages,
        parameters={
            "episode_id": episode["id"],
            "beat_id": beat_id,
            "duration": duration,
            "route": route,
            "family": payload.family or "",
            "visual_style": visual_style,
            "art_style_id": art_style_id,
            "pictures": public_video_pictures(pictures),
            "prompt_version": VIDEO_MOTION_PROMPT_VERSION,
        },
        temperature=0.75,
        max_tokens=8192,
    )
    try:
        pair = app.state.llm_provider.generate_xiaji_beat_video_prompt(
            {
                "beat": beat,
                "pictures": pictures,
                "duration": duration,
                "visual_style": visual_style,
                "art_style_id": art_style_id,
                "route": route,
            }
        )
    except LlmError as error:
        finish_xiaji_llm_job(
            app,
            job_id,
            status="failed",
            error=str(error),
            response=llm_failure_response(error),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    finish_xiaji_llm_job(
        app,
        job_id,
        status="succeeded",
        response={"prompt_zh": pair["prompt_zh"], "prompt_en": pair["prompt_en"]},
    )
    updated = _episodes(app).update_beat(
        beat_id,
        owner_user_id,
        video_prompt=pair["prompt_en"],
        video_prompt_zh=pair["prompt_zh"],
        video_prompt_job_id=job_id,
        video_duration=f"{duration:g}",
    )
    fresh = _hydrate_episode(app, updated, owner_user_id)
    current = next(item for item in fresh.get("beats") or [] if item["id"] == beat_id)
    return {
        "ok": True,
        "episode": fresh,
        "prompt_zh": current.get("video_prompt_zh"),
        "prompt_en": current.get("video_prompt"),
        "pictures": current.get("video_pictures") or public_video_pictures(pictures),
    }


def store_beat_in_frame(
    app: Any,
    owner_user_id: str,
    beat_id: str,
    *,
    content: bytes,
    filename: str,
    source_job_id: str | None = None,
    sec: str | None = None,
    manual: bool = False,
) -> dict[str, Any]:
    storage = getattr(app.state, "resource_storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="媒体存储未配置")
    stored = storage.store_bytes("xiaji-in-frames", filename, content)
    url = resource_object_url(storage, stored.key) or ""
    if not url:
        raise HTTPException(status_code=503, detail="无法生成衔接帧地址")
    return _episodes(app).update_beat(
        beat_id,
        owner_user_id,
        video_in_frame_url=url,
        video_in_frame_sec=str(sec or "").strip() or None,
        video_in_source_job_id=str(source_job_id or "").strip() or None,
        video_in_frame_manual="1" if manual else "0",
    )


def _start_compose_job(app: Any, episode: dict[str, Any], owner_user_id: str, resolution: str, add_subtitles: bool) -> str | None:
    number = int(episode.get("number") or 1)
    title_text = str(episode.get("title") or "").strip()
    target = f"第{number}集 {title_text}".strip()
    filename = compose_filename(number)
    clips = compose_concat_beats(episode)
    return start_xiaji_tracked_job(
        app,
        owner_user_id=owner_user_id,
        project_id=str(episode.get("project_id") or ""),
        kind="compose",
        target=target,
        title=f"合成成片 · {target}",
        prompt=filename,
        parameters={
            "episode_id": str(episode.get("id") or ""),
            "episode_number": number,
            "title": title_text,
            "resolution": resolution,
            "add_subtitles": add_subtitles,
            "clip_count": len(clips),
            "compose_filename": filename,
        },
    )


def _run_episode_compose(
    app: Any,
    episode_id: str,
    owner_user_id: str,
    resolution: str,
    add_subtitles: bool,
    job_id: str | None = None,
) -> None:
    store = _episodes(app)

    def progress(value: int) -> None:
        try:
            store.update_episode(episode_id, owner_user_id, compose_status="composing", compose_progress=str(int(value)))
        except Exception:
            pass
        set_xiaji_job_progress(app, job_id, value)

    try:
        episode = store.get_episode(episode_id, owner_user_id)
        result = compose_episode_film(
            episode,
            getattr(app.state, "store", None),
            resource_storage=getattr(app.state, "resource_storage", None),
            resolution=resolution,
            add_subtitles=add_subtitles,
            runner=getattr(app.state, "ffmpeg_runner", None),
            progress=progress,
        )
        store.update_episode(
            episode_id,
            owner_user_id,
            compose_status=result["compose_status"],
            compose_url=result.get("compose_url"),
            compose_key=result.get("compose_key"),
            compose_error=None,
            compose_resolution=result.get("compose_resolution"),
            compose_add_subtitles=result.get("compose_add_subtitles"),
            compose_duration_sec=result.get("compose_duration_sec"),
            compose_at=result.get("compose_at"),
            compose_progress="100",
            clear_error=True,
        )
        finish_xiaji_llm_job(
            app,
            job_id,
            status="succeeded",
            response={
                "compose_url": result.get("compose_url"),
                "compose_filename": result.get("compose_filename"),
                "compose_resolution": result.get("compose_resolution"),
                "compose_duration_sec": result.get("compose_duration_sec"),
            },
        )
    except Exception as error:
        try:
            store.update_episode(
                episode_id,
                owner_user_id,
                compose_status="failed",
                compose_error=str(error),
                compose_progress="0",
            )
        except Exception:
            pass
        finish_xiaji_llm_job(
            app,
            job_id,
            status="failed",
            error=str(error),
            response=llm_failure_response(error),
        )


def register_xiaji_episode_routes(app: Any, *, current_user: Callable, mutating_user: Callable) -> None:
    router = APIRouter(prefix="/api/xiaji", tags=["导台2"])

    @router.get("/episodes", summary="列出当前项目的剧集")
    def list_episodes(
        project_id: str = Query(..., description="导台2 项目 ID"),
        user: dict = Depends(current_user),
    ) -> list[dict]:
        require_xiaji_project(app, project_id, user["id"])
        raw_episodes = _episodes(app).list_episodes(user["id"], project_id)
        if not raw_episodes:
            return []

        assets = app.state.xiaji_asset_store.list_assets(user["id"], project_id)
        assets_by_id = {item["id"]: item for item in assets}

        job_ids_to_fetch: set[str] = set()
        for ep in raw_episodes:
            for beat in ep.get("beats") or []:
                s_job = str(beat.get("sketch_job_id") or "").strip()
                if s_job and (beat.get("status") in {"queued", "generating"} or not beat.get("sketch_url")):
                    job_ids_to_fetch.add(s_job)
                r_job = str(beat.get("render_job_id") or "").strip()
                if _beat_slot_needs_job(r_job, str(beat.get("render_status") or ""), beat.get("render_url")):
                    job_ids_to_fetch.add(r_job)
                v_job = str(beat.get("video_job_id") or "").strip()
                if _beat_slot_needs_job(v_job, str(beat.get("video_status") or ""), beat.get("video_url")):
                    job_ids_to_fetch.add(v_job)

        jobs_cache = _fetch_episode_jobs_batch(getattr(app.state, "store", None), job_ids_to_fetch) if job_ids_to_fetch else {}
        return [_hydrate_episode(app, item, user["id"], jobs_cache, assets_by_id) for item in raw_episodes]

    @router.post("/episodes/from-analysis", summary="从内容库剧集规划落库")
    def from_analysis(
        project_id: str = Query(..., description="导台2 项目 ID"),
        payload: FromAnalysisRequest = Body(default_factory=FromAnalysisRequest),
        user: dict = Depends(mutating_user),
    ) -> list[dict]:
        require_xiaji_project(app, project_id, user["id"])
        return _materialize_from_analysis(app, user["id"], project_id, payload)

    @router.get("/episodes/{episode_id}", summary="读取剧集脚本与镜头")
    def get_episode(
        episode_id: str = _EPISODE_ID_PARAM,
        user: dict = Depends(current_user),
    ) -> dict:
        return _hydrate_episode_single(app, _episode_or_404(app, episode_id, user["id"]), user["id"])

    @router.patch("/episodes/{episode_id}", summary="更新剧集标题")
    def patch_episode(
        episode_id: str = _EPISODE_ID_PARAM,
        payload: EpisodePatch = ...,
        user: dict = Depends(mutating_user),
    ) -> dict:
        _episode_or_404(app, episode_id, user["id"])
        return _hydrate_episode_single(
            app,
            _episodes(app).update_episode(episode_id, user["id"], title=payload.title),
            user["id"],
        )

    @router.post(
        "/episodes/{episode_id}/generate-script",
        status_code=202,
        summary="入队生成 Beat 脚本，立即返回；完成后轮询 GET 剧集",
    )
    async def generate_script(
        background_tasks: BackgroundTasks,
        episode_id: str = _EPISODE_ID_PARAM,
        user: dict = Depends(mutating_user),
        payload: ScriptGenerateRequest = Body(default_factory=ScriptGenerateRequest),
    ) -> dict:
        write_request_log("xiaji-generate-script", {"phase": "start", "episode_id": episode_id, "user_id": user["id"]})
        episode = _hydrate_episode_single(app, _episode_or_404(app, episode_id, user["id"]), user["id"])
        if not episode.get("original_lines"):
            raise HTTPException(status_code=422, detail="这一集还没有原文，请先从规划生成剧集")
        if episode.get("status") == "scripting" and not payload.force:
            return {"ok": True, "status": "scripting", "episode": episode, "reused": True}
        llm_payload = _script_llm_payload(app, episode, user["id"])
        job_id = _start_script_llm_job(app, episode, user["id"], llm_payload)
        _episodes(app).update_episode(episode_id, user["id"], status="scripting", clear_error=True)
        background_tasks.add_task(_run_script_generation, app, episode_id, user["id"], job_id)
        write_request_log("xiaji-generate-script", {"phase": "queued", "episode_id": episode_id})
        fresh = _hydrate_episode_single(app, _episodes(app).get_episode(episode_id, user["id"]), user["id"])
        return {"ok": True, "status": "scripting", "episode": fresh, "reused": False}

    @router.put("/episodes/{episode_id}/beats", summary="保存人工校对后的 Beat")
    def replace_beats(
        payload: BeatsReplaceRequest,
        episode_id: str = _EPISODE_ID_PARAM,
        user: dict = Depends(mutating_user),
    ) -> dict:
        _episode_or_404(app, episode_id, user["id"])
        beats = [item.model_dump() for item in payload.beats]
        updated = _episodes(app).replace_beats(episode_id, user["id"], beats, status="script_ready")
        return _hydrate_episode_single(app, updated, user["id"])

    @router.patch("/episodes/{episode_id}/beats/{beat_id}", summary="更新单个 Beat 文案与参考资产")
    def patch_beat(
        payload: BeatPatch,
        episode_id: str = _EPISODE_ID_PARAM,
        beat_id: str = _BEAT_ID_PARAM,
        user: dict = Depends(mutating_user),
    ) -> dict:
        episode = _episode_or_404(app, episode_id, user["id"])
        beat = next((item for item in episode.get("beats") or [] if item["id"] == beat_id), None)
        if beat is None:
            raise HTTPException(status_code=404, detail="镜头不存在")
        fields = payload.model_dump(exclude_unset=True)
        if "scene_id" in fields and not str(fields.get("scene_id") or "").strip():
            fields["scene_id"] = None
        updated = _episodes(app).update_beat(beat_id, user["id"], **fields)
        return _hydrate_episode_single(app, updated, user["id"])

    @router.post("/episodes/{episode_id}/beats/{beat_id}/upload-sketch", summary="上传镜头草图")
    async def upload_sketch(
        episode_id: str = _EPISODE_ID_PARAM,
        beat_id: str = _BEAT_ID_PARAM,
        user: dict = Depends(mutating_user),
        file: UploadFile = File(...),
    ) -> dict:
        episode = _episode_or_404(app, episode_id, user["id"])
        beat = next((item for item in episode.get("beats") or [] if item["id"] == beat_id), None)
        if beat is None:
            raise HTTPException(status_code=404, detail="镜头不存在")
        storage = getattr(app.state, "resource_storage", None)
        if storage is None:
            raise HTTPException(status_code=503, detail="媒体存储未配置")
        filename = Path(file.filename or "sketch.png").name
        suffix = Path(filename).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise HTTPException(status_code=422, detail="仅支持 PNG / JPEG / WebP / GIF")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=422, detail="文件是空的")
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="草图不能超过 12 MB")
        stored = storage.store_bytes("xiaji-sketches", filename, content)
        url = resource_object_url(storage, stored.key) or ""
        if not url:
            raise HTTPException(status_code=503, detail="无法生成草图地址")
        updated = _episodes(app).update_beat(
            beat_id,
            user["id"],
            sketch_url=url,
            sketch_job_id=None,
            status="succeeded",
            error=None,
        )
        return _hydrate_episode(app, updated, user["id"])

    @router.post(
        "/episodes/{episode_id}/beats/{beat_id}/upload-in-frame",
        summary="上传上一镜衔接帧（默认末帧，可手动改截）",
    )
    async def upload_in_frame(
        episode_id: str = _EPISODE_ID_PARAM,
        beat_id: str = _BEAT_ID_PARAM,
        user: dict = Depends(mutating_user),
        file: UploadFile = File(...),
        sec: str | None = Form(default=None),
        manual: str | None = Form(default=None),
        source_job_id: str | None = Form(default=None),
    ) -> dict:
        episode = _episode_or_404(app, episode_id, user["id"])
        beat = next((item for item in episode.get("beats") or [] if item["id"] == beat_id), None)
        if beat is None:
            raise HTTPException(status_code=404, detail="镜头不存在")
        previous = previous_video_beat(episode, beat)
        if previous is None:
            raise HTTPException(status_code=422, detail="第一条镜头不需要上一镜衔接帧")
        if not str(previous.get("video_url") or "").strip():
            raise HTTPException(status_code=422, detail="请先生成上一镜视频")
        storage = getattr(app.state, "resource_storage", None)
        if storage is None:
            raise HTTPException(status_code=503, detail="媒体存储未配置")
        filename = Path(file.filename or "in-frame.png").name
        suffix = Path(filename).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise HTTPException(status_code=422, detail="仅支持 PNG / JPEG / WebP / GIF")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=422, detail="文件是空的")
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="衔接帧不能超过 12 MB")
        stored = storage.store_bytes("xiaji-in-frames", filename, content)
        url = resource_object_url(storage, stored.key) or ""
        if not url:
            raise HTTPException(status_code=503, detail="无法生成衔接帧地址")
        source = str(source_job_id or "").strip() or str(previous.get("video_job_id") or "")
        updated = _episodes(app).update_beat(
            beat_id,
            user["id"],
            video_in_frame_url=url,
            video_in_frame_sec=str(sec or "").strip() or None,
            video_in_source_job_id=source or None,
            video_in_frame_manual="1" if str(manual or "").strip() in {"1", "true", "yes"} else "0",
        )
        return _hydrate_episode(app, updated, user["id"])

    @router.post(
        "/episodes/{episode_id}/beats/{beat_id}/generate-sketch",
        status_code=202,
        summary="为单个 Beat 入队镜头草图",
    )
    async def generate_sketch(
        background_tasks: BackgroundTasks,
        episode_id: str = _EPISODE_ID_PARAM,
        beat_id: str = _BEAT_ID_PARAM,
        user: dict = Depends(mutating_user),
        payload: SketchRequest = Body(default_factory=SketchRequest),
    ) -> dict:
        episode = _hydrate_episode(app, _episode_or_404(app, episode_id, user["id"]), user["id"])
        beat = next((item for item in episode.get("beats") or [] if item["id"] == beat_id), None)
        if beat is None:
            raise HTTPException(status_code=404, detail="镜头不存在")
        updated, job = _submit_sketch(app, user["id"], episode, beat, payload)
        if job is None:
            current = next(item for item in updated.get("beats") or [] if item["id"] == beat_id)
            return {"ok": True, "job_id": current.get("sketch_job_id"), "status": current.get("status"), "episode": updated, "reused": True}
        worker = getattr(app.state, "worker", None)
        if worker is None:
            raise HTTPException(status_code=503, detail="图片任务执行器未启动")
        background_tasks.add_task(_enqueue_queued_job, worker, job)
        fresh = _hydrate_episode(app, updated, user["id"])
        current = next(item for item in fresh.get("beats") or [] if item["id"] == beat_id)
        return {"ok": True, "job_id": job["id"], "status": current.get("status") or "queued", "episode": fresh, "reused": False}

    @router.post(
        "/episodes/{episode_id}/generate-sketches",
        status_code=202,
        summary="为本集可出图 Beat 批量入队草图",
    )
    async def generate_sketches(
        background_tasks: BackgroundTasks,
        episode_id: str = _EPISODE_ID_PARAM,
        user: dict = Depends(mutating_user),
        payload: SketchRequest = Body(default_factory=SketchRequest),
    ) -> dict:
        episode = _hydrate_episode(app, _episode_or_404(app, episode_id, user["id"]), user["id"])
        if not episode.get("beats"):
            raise HTTPException(status_code=422, detail="请先生成脚本")
        worker = getattr(app.state, "worker", None)
        if worker is None:
            raise HTTPException(status_code=503, detail="图片任务执行器未启动")
        job_ids: list[str] = []
        current = episode
        for beat in episode.get("beats") or []:
            if beat.get("kind") == "scene_heading" and not beat.get("action"):
                continue
            current, job = _submit_sketch(app, user["id"], current, beat, payload)
            if job is not None:
                job_ids.append(job["id"])
                background_tasks.add_task(_enqueue_queued_job, worker, job)
        return {
            "ok": True,
            "job_ids": job_ids,
            "episode": _hydrate_episode(app, current, user["id"]),
        }

    @router.post(
        "/episodes/{episode_id}/beats/{beat_id}/generate-render",
        status_code=202,
        summary="把草图精绘为渲染图",
    )
    async def generate_render(
        background_tasks: BackgroundTasks,
        episode_id: str = _EPISODE_ID_PARAM,
        beat_id: str = _BEAT_ID_PARAM,
        user: dict = Depends(mutating_user),
        payload: RenderRequest = Body(default_factory=RenderRequest),
    ) -> dict:
        episode = _hydrate_episode(app, _episode_or_404(app, episode_id, user["id"]), user["id"])
        beat = next((item for item in episode.get("beats") or [] if item["id"] == beat_id), None)
        if beat is None:
            raise HTTPException(status_code=404, detail="镜头不存在")
        updated, job = _submit_render(app, user["id"], episode, beat, payload)
        if job is None:
            current = next(item for item in updated.get("beats") or [] if item["id"] == beat_id)
            return {"ok": True, "job_id": current.get("render_job_id"), "status": current.get("render_status"), "episode": updated, "reused": True}
        worker = getattr(app.state, "worker", None)
        if worker is None:
            raise HTTPException(status_code=503, detail="图片任务执行器未启动")
        background_tasks.add_task(_enqueue_queued_job, worker, job)
        fresh = _hydrate_episode(app, updated, user["id"])
        current = next(item for item in fresh.get("beats") or [] if item["id"] == beat_id)
        return {"ok": True, "job_id": job["id"], "status": current.get("render_status") or "queued", "episode": fresh, "reused": False}

    @router.post(
        "/episodes/{episode_id}/beats/{beat_id}/video-prompt",
        summary="用大模型生成本 Beat 的 LightX2V 多参考视频提示词（界面中文，入队英文）",
    )
    @router.post(
        "/episodes/{episode_id}/beats/{beat_id}/generate-video-prompt",
        summary="用大模型生成本 Beat 的 LightX2V 多参考视频提示词（界面中文，入队英文）",
        include_in_schema=False,
    )
    async def generate_video_prompt(
        episode_id: str = _EPISODE_ID_PARAM,
        beat_id: str = _BEAT_ID_PARAM,
        user: dict = Depends(mutating_user),
        payload: VideoPromptRequest = Body(default_factory=VideoPromptRequest),
    ) -> dict:
        episode = _hydrate_episode(app, _episode_or_404(app, episode_id, user["id"]), user["id"])
        beat = next((item for item in episode.get("beats") or [] if item["id"] == beat_id), None)
        if beat is None:
            raise HTTPException(status_code=404, detail="镜头不存在")
        return await run_in_threadpool(generate_beat_video_prompt, app, user["id"], episode, beat, payload)

    @router.post(
        "/episodes/{episode_id}/beats/{beat_id}/generate-video",
        status_code=202,
        summary="用渲染图生成镜头视频（I2V 首帧或 R2V 多参考；后续镜需上一镜衔接帧）",
    )
    async def generate_video(
        background_tasks: BackgroundTasks,
        episode_id: str = _EPISODE_ID_PARAM,
        beat_id: str = _BEAT_ID_PARAM,
        user: dict = Depends(mutating_user),
        payload: VideoRequest = Body(default_factory=VideoRequest),
    ) -> dict:
        episode = _hydrate_episode(app, _episode_or_404(app, episode_id, user["id"]), user["id"])
        beat = next((item for item in episode.get("beats") or [] if item["id"] == beat_id), None)
        if beat is None:
            raise HTTPException(status_code=404, detail="镜头不存在")
        updated, job = _submit_video(app, user["id"], episode, beat, payload)
        if job is None:
            current = next(item for item in updated.get("beats") or [] if item["id"] == beat_id)
            return {"ok": True, "job_id": current.get("video_job_id"), "status": current.get("video_status"), "episode": updated, "reused": True}
        worker = getattr(app.state, "worker", None)
        if worker is None:
            raise HTTPException(status_code=503, detail="视频任务执行器未启动")
        background_tasks.add_task(_enqueue_queued_job, worker, job)
        fresh = _hydrate_episode(app, updated, user["id"])
        current = next(item for item in fresh.get("beats") or [] if item["id"] == beat_id)
        return {"ok": True, "job_id": job["id"], "status": current.get("video_status") or "queued", "episode": fresh, "reused": False}

    def _public_auto_run(row: dict | None) -> dict:
        if row is None:
            return {"ok": True, "run": None}
        cursor = row.get("cursor") if isinstance(row.get("cursor"), dict) else {}
        step = str(cursor.get("step") or "")
        from .xiaji_episode_run_store import STEP_LABELS

        return {
            "ok": True,
            "run": {
                **row,
                "step_label": STEP_LABELS.get(step, step),
                "message": (
                    f"第{cursor.get('sequence')}镜 · {STEP_LABELS.get(step, step)}"
                    if cursor.get("sequence")
                    else "排队中"
                ),
            },
        }

    @router.post(
        "/episodes/{episode_id}/auto-run",
        status_code=202,
        summary="添加整集自动生成任务（草图→精绘→提示词→视频，视频参数锁定）",
    )
    async def start_auto_run(
        episode_id: str = _EPISODE_ID_PARAM,
        user: dict = Depends(mutating_user),
        payload: AutoRunRequest = Body(default_factory=AutoRunRequest),
    ) -> dict:
        episode = _hydrate_episode(app, _episode_or_404(app, episode_id, user["id"]), user["id"])
        beats = [item for item in (episode.get("beats") or []) if _beat_can_make_video(item)]
        if not beats:
            raise HTTPException(status_code=422, detail="请先生成脚本")
        available, reason = app.state.llm_provider.availability()
        if not available:
            raise HTTPException(status_code=503, detail=reason or "大模型未配置")
        worker = getattr(app.state, "worker", None)
        if worker is None:
            raise HTTPException(status_code=503, detail="任务执行器未启动")
        pipeline = getattr(app.state, "xiaji_auto_pipeline", None)
        if pipeline is None:
            raise HTTPException(status_code=503, detail="自动生成编排未启动")
        runs = episode_runs_store(app)
        if runs is None:
            raise HTTPException(status_code=503, detail="自动生成任务存储未启动")
        active = runs.active_for_episode(user["id"], episode_id)
        if active is not None:
            raise HTTPException(status_code=409, detail="本集已有自动生成任务在进行")
        try:
            _resolve_video_workflow(payload.family)
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error) or "视频工作流无效") from error
        duration = _coerce_duration_seconds(payload.duration)
        video_params = {
            "family": (payload.family or "").strip() or None,
            "duration": duration,
            "quality": payload.quality,
            "aspect_ratio": payload.aspect_ratio or "16:9",
            "speed": payload.speed,
            "custom_steps": payload.custom_steps,
            "scene_view": payload.scene_view,
        }
        created = runs.create(
            owner_user_id=user["id"],
            project_id=str(episode["project_id"]),
            episode_id=episode_id,
            video_params=video_params,
        )
        pipeline.start(created["id"])
        return _public_auto_run(runs.get(created["id"]))

    @router.get("/episodes/{episode_id}/auto-run", summary="读取本集最近一次自动生成任务进度")
    def get_auto_run(
        episode_id: str = _EPISODE_ID_PARAM,
        user: dict = Depends(current_user),
    ) -> dict:
        _episode_or_404(app, episode_id, user["id"])
        runs = episode_runs_store(app)
        if runs is None:
            return {"ok": True, "run": None}
        return _public_auto_run(runs.latest_for_episode(user["id"], episode_id))

    @router.post("/episodes/{episode_id}/auto-run/cancel", summary="取消本集进行中的自动生成任务")
    def cancel_auto_run(
        episode_id: str = _EPISODE_ID_PARAM,
        user: dict = Depends(mutating_user),
    ) -> dict:
        _episode_or_404(app, episode_id, user["id"])
        runs = episode_runs_store(app)
        if runs is None:
            raise HTTPException(status_code=503, detail="自动生成任务存储未启动")
        active = runs.active_for_episode(user["id"], episode_id)
        if active is None:
            raise HTTPException(status_code=404, detail="没有进行中的自动生成任务")
        updated = runs.update(active["id"], cancel_requested=True)
        return _public_auto_run(updated)

    @router.post(
        "/episodes/{episode_id}/compose",
        status_code=202,
        summary="入队本机 ffmpeg 拼接成片；完成后轮询 GET 剧集",
    )
    async def compose_episode(
        background_tasks: BackgroundTasks,
        user: dict = Depends(mutating_user),
        payload: ComposeRequest = Body(default_factory=ComposeRequest, description="合成选项；force 为 true 时强制重新合成。"),
        episode_id: str = _EPISODE_ID_PARAM,
    ) -> dict:
        episode = _hydrate_episode_single(app, _episode_or_404(app, episode_id, user["id"]), user["id"])
        if episode.get("compose_status") == "composing" and not payload.force:
            return {"ok": True, "status": "composing", "episode": episode, "reused": True}
        project = require_xiaji_project(app, str(episode.get("project_id") or ""), user["id"])
        require_audio = require_audio_for_project(project)
        blockers = compose_blockers(episode, require_audio=require_audio)
        audio_blockers = [item for item in blockers if "audio" in item.get("stages", [])]
        if audio_blockers:
            missing = "、".join(f"第{item['sequence']}镜缺配音" for item in audio_blockers[:8])
            raise HTTPException(status_code=422, detail=f"还不能合成：{missing}")
        if not compose_concat_beats(episode):
            raise HTTPException(status_code=422, detail="没有可合成的镜头视频，请先在「镜头」生成视频")
        runner = getattr(app.state, "ffmpeg_runner", None)
        if runner is None and not ffmpeg_ready().get("ffmpeg"):
            raise HTTPException(status_code=503, detail="未找到 ffmpeg/ffprobe。请安装 ffmpeg 并加入 PATH 后重试。")
        storage = getattr(app.state, "resource_storage", None)
        if storage is None:
            raise HTTPException(status_code=503, detail="媒体存储未配置")
        resolution, _width, _height = parse_resolution(payload.resolution)
        job_id = _start_compose_job(app, episode, user["id"], resolution, payload.add_subtitles)
        _episodes(app).update_episode(
            episode_id,
            user["id"],
            compose_status="composing",
            compose_error=None,
            compose_progress="0",
            compose_resolution=resolution,
            compose_add_subtitles="1" if payload.add_subtitles else "0",
        )
        background_tasks.add_task(
            _run_episode_compose, app, episode_id, user["id"], resolution, payload.add_subtitles, job_id
        )
        fresh = _hydrate_episode_single(app, _episodes(app).get_episode(episode_id, user["id"]), user["id"])
        return {"ok": True, "status": "composing", "episode": fresh, "reused": False, "job_id": job_id}

    @router.get("/episodes/{episode_id}/export/video", summary="下载本集成片 MP4")
    def export_episode_video(user: dict = Depends(current_user), episode_id: str = _EPISODE_ID_PARAM) -> Response:
        episode = _episode_or_404(app, episode_id, user["id"])
        try:
            data = load_compose_bytes(episode, getattr(app.state, "resource_storage", None))
        except XiajiComposeError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        filename = compose_filename(int(episode.get("number") or 1))
        return Response(content=data, media_type="video/mp4", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @router.get("/episodes/{episode_id}/export/srt", summary="下载本集字幕 SRT")
    def export_episode_srt(user: dict = Depends(current_user), episode_id: str = _EPISODE_ID_PARAM) -> Response:
        episode = _hydrate_episode_single(app, _episode_or_404(app, episode_id, user["id"]), user["id"])
        text = build_srt_content(clips_for_subtitles(episode))
        if not text.strip():
            raise HTTPException(status_code=404, detail="这一集没有可导出的对白字幕")
        filename = f"ep{int(episode.get('number') or 1):03d}.srt"
        return Response(
            content=text.encode("utf-8"),
            media_type="application/x-subrip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post("/episodes/{episode_id}/export/zip", summary="打包本集镜头视频、成片和字幕")
    def export_episode_zip(user: dict = Depends(mutating_user), episode_id: str = _EPISODE_ID_PARAM) -> Response:
        episode = _hydrate_episode_single(app, _episode_or_404(app, episode_id, user["id"]), user["id"])
        srt_text = build_srt_content(clips_for_subtitles(episode))
        try:
            data = build_episode_zip(
                episode,
                getattr(app.state, "store", None),
                resource_storage=getattr(app.state, "resource_storage", None),
                srt_text=srt_text,
            )
        except XiajiComposeError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not data:
            raise HTTPException(status_code=404, detail="没有可打包的素材")
        filename = f"ep{int(episode.get('number') or 1):03d}.zip"
        return Response(content=data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    app.include_router(router)
