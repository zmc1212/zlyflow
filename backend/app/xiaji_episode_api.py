from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.error import URLError

from fastapi import BackgroundTasks, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.routing import APIRouter
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
from .xiaji_asset_api import IMAGE_SUFFIXES, MAX_IMAGE_BYTES, _enqueue_queued_job, _resolve_image_workflow
from .xiaji_asset_prompts import image_options_for_kind
from .xiaji_episode_prompts import beat_render_prompt, beat_sketch_prompt, beat_video_prompt, character_marker_color
from .xiaji_episode_store import XiajiEpisodeStore, first_seen_line, allocate_chapter_text, split_original_lines
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


class BeatPatch(BaseModel):
    heading: str | None = Field(default=None, max_length=255)
    speaker: str | None = Field(default=None, max_length=128)
    dialogue: str | None = None
    action: str | None = None
    character_ids: list[str] | None = None
    scene_id: str | None = None
    prop_ids: list[str] | None = None


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


def _job_media_state(app: Any, job: dict[str, Any] | None, *, kind: str, failed_label: str) -> dict[str, str | None]:
    if not job:
        return {"status": None, "url": None, "error": None}
    status = str(job.get("status") or "")
    url = job_asset_image_url(job, kind=kind, resource_storage=getattr(app.state, "resource_storage", None))
    if status in {JobStatus.SUCCEEDED.value, JobStatus.PARTIAL.value} and url:
        return {"status": "succeeded", "url": url, "error": None}
    if status in {JobStatus.FAILED.value, JobStatus.INTERRUPTED.value, JobStatus.CANCELLED.value}:
        return {"status": "failed", "url": None, "error": str(job.get("error") or failed_label)}
    if status == JobStatus.QUEUED.value:
        return {"status": "queued", "url": None, "error": None}
    if status == JobStatus.RUNNING.value:
        return {"status": "generating", "url": None, "error": None}
    return {"status": None, "url": None, "error": None}


def _hydrate_episode(app: Any, episode: dict[str, Any], owner_user_id: str) -> dict[str, Any]:
    jobs = getattr(app.state, "store", None)
    if jobs is None:
        return _with_assets(app, episode, owner_user_id)
    store = _episodes(app)
    sketched = 0
    generating = 0
    failed = 0
    next_beats = []
    for beat in episode.get("beats") or []:
        current = dict(beat)
        sketch_state = _job_media_state(
            app,
            _lookup_job(app, str(current.get("sketch_job_id") or "")),
            kind="image",
            failed_label="草图生成失败",
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

        render_state = _job_media_state(
            app,
            _lookup_job(app, str(current.get("render_job_id") or "")),
            kind="image",
            failed_label="渲染图生成失败",
        )
        if render_state["status"] == "succeeded" and render_state["url"] and current.get("render_url") != render_state["url"]:
            store.update_beat(current["id"], owner_user_id, render_url=render_state["url"])
            current["render_url"] = render_state["url"]
        elif render_state["url"]:
            current["render_url"] = render_state["url"]
        current["render_status"] = render_state["status"] or ("succeeded" if current.get("render_url") else "draft")
        current["render_error"] = render_state["error"]

        video_state = _job_media_state(
            app,
            _lookup_job(app, str(current.get("video_job_id") or "")),
            kind="video",
            failed_label="视频生成失败",
        )
        if video_state["status"] == "succeeded" and video_state["url"] and current.get("video_url") != video_state["url"]:
            store.update_beat(current["id"], owner_user_id, video_url=video_state["url"])
            current["video_url"] = video_state["url"]
        elif video_state["url"]:
            current["video_url"] = video_state["url"]
        current["video_status"] = video_state["status"] or ("succeeded" if current.get("video_url") else "draft")
        current["video_error"] = video_state["error"]

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
    return _with_assets(app, episode, owner_user_id)


def _with_assets(app: Any, episode: dict[str, Any], owner_user_id: str) -> dict[str, Any]:
    assets = app.state.xiaji_asset_store.list_assets(owner_user_id, episode["project_id"])
    by_id = {item["id"]: item for item in assets}
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
    public = dict(episode)
    public.pop("owner_user_id", None)
    return public


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
    return {
        "original_lines": episode.get("original_lines") or [],
        "characters": [item["name"] for item in episode.get("links") or [] if item.get("kind") == "character"],
        "scenes": [item["name"] for item in episode.get("links") or [] if item.get("kind") == "scene"],
        "props": [item["name"] for item in episode.get("links") or [] if item.get("kind") == "prop"],
        "visual_style": settings.get("visual_style") or "",
        "title": episode.get("title") or "",
        "summary": episode.get("content_summary") or "",
        "name_to_asset": _name_map(episode),
    }


def _run_script_generation_sync(app: Any, episode_id: str, owner_user_id: str) -> None:
    write_request_log("xiaji-generate-script", {"phase": "worker-start", "episode_id": episode_id})
    try:
        episode = _hydrate_episode(app, _episodes(app).get_episode(episode_id, owner_user_id), owner_user_id)
        beats = app.state.llm_provider.generate_xiaji_script(_script_llm_payload(app, episode, owner_user_id))
        _episodes(app).replace_beats(episode_id, owner_user_id, beats, status="script_ready")
        write_request_log(
            "xiaji-generate-script",
            {"phase": "done", "episode_id": episode_id, "beats": len(beats)},
        )
    except Exception as error:
        _episodes(app).update_episode(episode_id, owner_user_id, status="draft", error=str(error))
        write_request_log(
            "xiaji-generate-script",
            {"phase": "failed", "episode_id": episode_id, "error": str(error)[:300]},
        )


async def _run_script_generation(app: Any, episode_id: str, owner_user_id: str) -> None:
    await run_in_threadpool(_run_script_generation_sync, app, episode_id, owner_user_id)


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


def _append_ref_file(app: Any, paths: list[str], seen: set[str], *, job_id: str, url: str, stem: str) -> None:
    if len(paths) >= 9:
        return
    jobs = getattr(app.state, "store", None)
    job_id = str(job_id or "").strip()
    if job_id and jobs is not None:
        try:
            job = jobs.get(job_id)
        except KeyError:
            job = None
        if job:
            path = materialize_job_output_file(job, resource_storage=app.state.resource_storage, kind="image")
            if path is not None:
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    paths.append(key)
                return
    url = str(url or "").strip()
    if url.startswith(("http://", "https://")):
        dest = settings.staging_dir / "xiaji-refs" / f"{stem}.png"
        path = _download_image_url(url, dest)
        if path is not None:
            key = str(path)
            if key not in seen:
                seen.add(key)
                paths.append(key)


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
    )


def _append_character_refs(app: Any, paths: list[str], seen: set[str], beat: dict[str, Any], by_id: dict[str, Any]) -> None:
    for asset_id in [str(item) for item in (beat.get("character_ids") or [])[:4]]:
        asset = by_id.get(asset_id)
        if not asset:
            continue
        definition = asset.get("definition") if isinstance(asset.get("definition"), dict) else {}
        _append_ref_file(
            app,
            paths,
            seen,
            job_id=str(asset.get("image_job_id") or ""),
            url=str(asset.get("image_url") or ""),
            stem=f"{asset['id']}-portrait",
        )
        for look in definition.get("looks") or []:
            if not isinstance(look, dict):
                continue
            look_url = str(look.get("image_url") or "").strip()
            look_job = str(look.get("job_id") or "").strip()
            if look_url or look_job:
                _append_ref_file(
                    app,
                    paths,
                    seen,
                    job_id=look_job,
                    url=look_url,
                    stem=f"{asset['id']}-look-{look.get('id') or '0'}",
                )
                break


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
        visual_style=str(settings.get("visual_style") or ""),
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
        visual_style=str(settings.get("visual_style") or ""),
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
    video_status = str(beat.get("video_status") or "")
    if not payload.force and video_status in {"queued", "generating"} and beat.get("video_job_id"):
        return episode, None
    if not payload.force and beat.get("video_url") and beat.get("video_job_id"):
        return episode, None
    workflow_id = _resolve_video_workflow(payload.family)
    try:
        definition = workflow_for(workflow_id)
    except (KeyError, ValueError):
        definition = None
    route = director_route_key(definition) if definition is not None else "i2v"
    refs: list[str] = []
    seen: set[str] = set()
    _append_ref_file(
        app,
        refs,
        seen,
        job_id=str(beat.get("render_job_id") or ""),
        url=str(beat.get("render_url") or ""),
        stem=f"{beat['id']}-render",
    )
    if route == "r2v":
        assets = app.state.xiaji_asset_store.list_assets(owner_user_id, episode["project_id"])
        by_id = {item["id"]: item for item in assets}
        _append_character_refs(app, refs, seen, beat, by_id)
        scene_id = str(beat.get("scene_id") or "").strip()
        scene = by_id.get(scene_id) if scene_id else None
        if scene:
            _append_scene_ref(app, refs, seen, scene, scene_view=payload.scene_view)
        refs[:] = refs[:9]
    if not refs:
        raise HTTPException(status_code=422, detail="无法读取渲染图文件，请重新生成渲染图")
    prompt = beat_video_prompt(beat, route=route or "i2v", picture_count=len(refs))
    options: dict[str, Any] = {}
    if payload.duration is not None:
        options["duration"] = payload.duration
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
    duration_text = str(payload.duration if payload.duration is not None else "")
    updated = _episodes(app).update_beat(
        beat["id"],
        owner_user_id,
        video_job_id=job["id"],
        video_prompt=prompt,
        video_model=workflow_id,
        video_url=None,
        video_duration=duration_text or None,
    )
    updated["beats"] = _episodes(app).get_episode(episode["id"], owner_user_id)["beats"]
    return updated, job


def register_xiaji_episode_routes(app: Any, *, current_user: Callable, mutating_user: Callable) -> None:
    router = APIRouter(prefix="/api/xiaji", tags=["导台2"])

    @router.get("/episodes", summary="列出当前项目的剧集")
    def list_episodes(
        project_id: str = Query(..., description="导台2 项目 ID"),
        user: dict = Depends(current_user),
    ) -> list[dict]:
        require_xiaji_project(app, project_id, user["id"])
        return [_hydrate_episode(app, item, user["id"]) for item in _episodes(app).list_episodes(user["id"], project_id)]

    @router.post("/episodes/from-analysis", summary="从内容库剧集规划落库")
    def from_analysis(
        project_id: str = Query(..., description="导台2 项目 ID"),
        payload: FromAnalysisRequest = Body(default_factory=FromAnalysisRequest),
        user: dict = Depends(mutating_user),
    ) -> list[dict]:
        require_xiaji_project(app, project_id, user["id"])
        return _materialize_from_analysis(app, user["id"], project_id, payload)

    @router.get("/episodes/{episode_id}", summary="读取剧集脚本与镜头")
    def get_episode(episode_id: str, user: dict = Depends(current_user)) -> dict:
        return _hydrate_episode(app, _episode_or_404(app, episode_id, user["id"]), user["id"])

    @router.patch("/episodes/{episode_id}", summary="更新剧集标题")
    def patch_episode(episode_id: str, payload: EpisodePatch, user: dict = Depends(mutating_user)) -> dict:
        _episode_or_404(app, episode_id, user["id"])
        return _hydrate_episode(
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
        episode_id: str,
        background_tasks: BackgroundTasks,
        user: dict = Depends(mutating_user),
        payload: ScriptGenerateRequest = Body(default_factory=ScriptGenerateRequest),
    ) -> dict:
        write_request_log("xiaji-generate-script", {"phase": "start", "episode_id": episode_id, "user_id": user["id"]})
        episode = _hydrate_episode(app, _episode_or_404(app, episode_id, user["id"]), user["id"])
        if not episode.get("original_lines"):
            raise HTTPException(status_code=422, detail="这一集还没有原文，请先从规划生成剧集")
        if episode.get("status") == "scripting" and not payload.force:
            return {"ok": True, "status": "scripting", "episode": episode, "reused": True}
        _episodes(app).update_episode(episode_id, user["id"], status="scripting", clear_error=True)
        background_tasks.add_task(_run_script_generation, app, episode_id, user["id"])
        write_request_log("xiaji-generate-script", {"phase": "queued", "episode_id": episode_id})
        fresh = _hydrate_episode(app, _episodes(app).get_episode(episode_id, user["id"]), user["id"])
        return {"ok": True, "status": "scripting", "episode": fresh, "reused": False}

    @router.put("/episodes/{episode_id}/beats", summary="保存人工校对后的 Beat")
    def replace_beats(episode_id: str, payload: BeatsReplaceRequest, user: dict = Depends(mutating_user)) -> dict:
        _episode_or_404(app, episode_id, user["id"])
        beats = [item.model_dump() for item in payload.beats]
        updated = _episodes(app).replace_beats(episode_id, user["id"], beats, status="script_ready")
        return _hydrate_episode(app, updated, user["id"])

    @router.patch("/episodes/{episode_id}/beats/{beat_id}", summary="更新单个 Beat 文案与参考资产")
    def patch_beat(episode_id: str, beat_id: str, payload: BeatPatch, user: dict = Depends(mutating_user)) -> dict:
        episode = _episode_or_404(app, episode_id, user["id"])
        beat = next((item for item in episode.get("beats") or [] if item["id"] == beat_id), None)
        if beat is None:
            raise HTTPException(status_code=404, detail="镜头不存在")
        fields = payload.model_dump(exclude_unset=True)
        if "scene_id" in fields and not str(fields.get("scene_id") or "").strip():
            fields["scene_id"] = None
        updated = _episodes(app).update_beat(beat_id, user["id"], **fields)
        return _hydrate_episode(app, updated, user["id"])

    @router.post("/episodes/{episode_id}/beats/{beat_id}/upload-sketch", summary="上传镜头草图")
    async def upload_sketch(
        episode_id: str,
        beat_id: str,
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
        "/episodes/{episode_id}/beats/{beat_id}/generate-sketch",
        status_code=202,
        summary="为单个 Beat 入队镜头草图",
    )
    async def generate_sketch(
        episode_id: str,
        beat_id: str,
        background_tasks: BackgroundTasks,
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
        episode_id: str,
        background_tasks: BackgroundTasks,
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
        episode_id: str,
        beat_id: str,
        background_tasks: BackgroundTasks,
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
        "/episodes/{episode_id}/beats/{beat_id}/generate-video",
        status_code=202,
        summary="用渲染图生成镜头视频（I2V 首帧或 R2V 多参考）",
    )
    async def generate_video(
        episode_id: str,
        beat_id: str,
        background_tasks: BackgroundTasks,
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

    app.include_router(router)
