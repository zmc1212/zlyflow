from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import requests

from ..db import execute_sql, now_str, query_all, query_one, transaction_cursor
from .comfy_service import ComfyService
from .comfy_video_client import ComfyVideoClient
from .episode_image_prompts import resolve_scene_asset, scene_master_url
from .h3_prompt_builder import H3PromptBuilder
from .project_detail_service import ProjectDetailService
from .qiniu_service import QiniuService
from .timeline_rendering import (
    TimelineRenderCapabilities,
    duration_seconds,
    episode_video_render_mode,
    frame_count,
    plan_timeline_chunks,
    uses_director_timeline,
)
from ...gpu_runtime import occupy_gpu
from ...rtx_vsr_workflow import should_auto_upscale, source_video_shape, vsr_memory_rejection
from ...workflow_registry import (
    H3_STANDARD_OPTION_SCHEMA,
    coerce_bool_option,
    h3_dimensions,
    h3_length,
    normalize_options,
    workflow_for,
)


_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="h3-video")
_ACTIVE_VIDEO_STATUSES = (
    "queued",
    "preparing",
    "prompt_generation",
    "uploading",
    "comfy_queued",
    "running",
    "upscaling",
    "assembling",
    "downloading",
)


def concat_video_bytes(chunks: list[bytes]) -> bytes:
    if not chunks:
        raise RuntimeError("没有可拼接的视频分段")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("系统未安装 ffmpeg，无法合成视频")
    with tempfile.TemporaryDirectory(prefix="zly-h3-merge-") as directory:
        root = Path(directory)
        files: list[Path] = []
        for index, content in enumerate(chunks):
            path = root / f"segment-{index + 1}.mp4"
            path.write_bytes(content)
            files.append(path)
        concat = root / "concat.txt"
        concat.write_text("".join(f"file '{path.as_posix()}'\n" for path in files), encoding="utf-8")
        merged = root / "episode.mp4"
        command = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(merged)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        if completed.returncode != 0 or not merged.exists():
            fallback = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c:v", "libx264", "-c:a", "aac", str(merged)]
            completed = subprocess.run(fallback, capture_output=True, text=True, timeout=1800)
        if completed.returncode != 0 or not merged.exists():
            raise RuntimeError(f"ffmpeg 合成失败: {completed.stderr[-1000:]}")
        return merged.read_bytes()


def split_timeline_bytes(content: bytes, durations: list[float]) -> list[bytes]:
    if not content:
        raise RuntimeError("Timeline 成片为空，无法按镜拆分")
    if len(durations) <= 1:
        return [content]
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("系统未安装 ffmpeg，无法按镜拆分成片")
    with tempfile.TemporaryDirectory(prefix="zly-h3-split-") as directory:
        root = Path(directory)
        source = root / "timeline.mp4"
        source.write_bytes(content)
        clips: list[bytes] = []
        start = 0.0
        for index, duration in enumerate(durations):
            length = max(0.1, float(duration or 8))
            output = root / f"shot-{index + 1}.mp4"
            command = [
                ffmpeg, "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(source),
                "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(output),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=1800)
            if completed.returncode != 0 or not output.exists() or not output.stat().st_size:
                raise RuntimeError(f"ffmpeg 按镜拆分失败: {(completed.stderr or '')[-1000:]}")
            clips.append(output.read_bytes())
            start += length
        return clips


class EpisodeVideoService:
    DEFAULTS = {
        "workflow": "minimax-h3-director-accel-r2v",
        "duration_per_beat": 8,
        "fps": 24,
        "frames_per_beat": 192,
        "width": 864,
        "height": 480,
        "audio_mode": "generate",
        "seed": 888,
        "steps": 20,
        "sampler": "res_multistep",
        "scheduler": "simple",
    }
    JOB_CONTROL_KEYS = {
        "workflow", "workflow_id", "duration_per_beat", "render_pass", "render_scope",
        "render_mode", "beat_ids", "force",
    }

    @classmethod
    def resolve_generation_options(cls, raw: dict[str, Any] | None) -> dict[str, Any]:
        incoming = dict(raw or {})
        requested = str(incoming.get("workflow") or incoming.get("workflow_id") or cls.DEFAULTS["workflow"])
        fallback_reason = ""
        try:
            definition = workflow_for(requested)
            workflow_id = definition.id
        except KeyError:
            workflow_id = cls.DEFAULTS["workflow"]
            definition = workflow_for(workflow_id)
            fallback_reason = "workflow_not_registered"
        schema = definition.option_schema
        if schema is None and definition.supports_h3_options:
            schema = H3_STANDARD_OPTION_SCHEMA
        properties = (schema or {}).get("properties", {})
        gen_raw: dict[str, Any] = {}
        for key, value in incoming.items():
            if key in cls.JOB_CONTROL_KEYS or key not in properties:
                continue
            if key == "duration":
                continue
            definition_option = properties.get(key) or {}
            if definition_option.get("type") == "boolean":
                gen_raw[key] = coerce_bool_option(
                    value, label=str(definition_option.get("label") or key),
                )
                continue
            gen_raw[key] = str(value) if key == "quality" and not isinstance(value, str) else value
        speed_enum = (properties.get("speed") or {}).get("enum") or []
        if gen_raw.get("speed") is not None and speed_enum and gen_raw["speed"] not in speed_enum:
            gen_raw.pop("speed")
        normalized = normalize_options(workflow_id, gen_raw)
        try:
            width, height = h3_dimensions(normalized)
        except (KeyError, TypeError, ValueError):
            width = int(normalized.get("width") or cls.DEFAULTS["width"])
            height = int(normalized.get("height") or cls.DEFAULTS["height"])
        try:
            duration_per_beat = float(incoming.get("duration_per_beat") or cls.DEFAULTS["duration_per_beat"])
        except (TypeError, ValueError):
            duration_per_beat = float(cls.DEFAULTS["duration_per_beat"])
        resolved = {
            **normalized,
            "workflow": workflow_id,
            "workflow_id": workflow_id,
            "width": width,
            "height": height,
            "duration_per_beat": duration_per_beat,
            "seed": secrets.randbelow(2**31 - 2) + 1,
            "sampler": str(normalized.get("sampler_name") or cls.DEFAULTS["sampler"]),
        }
        if fallback_reason:
            resolved["workflow_fallback"] = {
                "requested": requested,
                "resolved": workflow_id,
                "reason": fallback_reason,
            }
        return resolved

    @staticmethod
    def _requested_beat_ids(options: dict[str, Any] | None) -> list[str] | None:
        if not options or "beat_ids" not in options:
            return None
        raw = options.get("beat_ids")
        if not isinstance(raw, list):
            raise ValueError("beat_ids 必须是镜头 ID 列表")
        ids: list[str] = []
        seen: set[str] = set()
        for item in raw:
            beat_id = str(item or "").strip()
            if beat_id and beat_id not in seen:
                seen.add(beat_id)
                ids.append(beat_id)
        return ids

    @classmethod
    def generate_episode_videos(
        cls,
        project_id: str,
        episode_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        incoming = dict(options or {})
        beat_ids = cls._requested_beat_ids(incoming)
        force = bool(incoming.pop("force", False)) or bool(beat_ids)
        incoming.pop("beat_ids", None)
        settings = cls.resolve_generation_options(incoming)
        workflow_id = str(settings.get("workflow") or cls.DEFAULTS["workflow"])
        render_mode = episode_video_render_mode(workflow_id)
        if render_mode == "episode":
            if beat_ids is not None and not beat_ids:
                raise ValueError("请先勾选要生成的镜头")
            created = cls.create_job(
                project_id,
                episode_id,
                beat_ids=beat_ids,
                render_scope="episode" if beat_ids is None else "selection",
                options=incoming,
            )
            shot_count = len(beat_ids) if beat_ids is not None else 0
            return {
                **created,
                "render_mode": "episode",
                "job_ids": [created["job_id"]],
                "submitted": 1,
                "shot_count": shot_count or created.get("shot_count") or 1,
                "skipped": 0,
            }

        if beat_ids is not None and not beat_ids:
            raise ValueError("请先勾选要生成的镜头")

        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        assets = ProjectDetailService.list_assets(project_id)
        shots = cls._prepare_shots(detail, assets, beat_ids=beat_ids)
        if beat_ids is not None:
            wanted = set(beat_ids)
            shots = [shot for shot in shots if str(shot.get("beat_id") or "") in wanted]
            missing = [beat_id for beat_id in beat_ids if beat_id not in {str(shot.get("beat_id") or "") for shot in shots}]
            if missing:
                raise ValueError("指定的镜头不存在或无法生成视频：" + "、".join(missing))
        beats_by_id = {str(beat.get("id") or ""): beat for beat in (detail.get("beats") or [])}
        cls._assert_can_enqueue(project_id, episode_id, "shot")
        active_beat_ids = {
            cls._job_beat_id(cls._job_payload(row))
            for row in cls._active_video_jobs(project_id, episode_id)
            if str(cls._job_payload(row).get("render_scope") or "shot") == "shot"
        }
        job_ids: list[str] = []
        skipped = 0
        skip_existing = beat_ids is None and not force
        for shot in shots:
            beat_id = str(shot.get("beat_id") or "")
            beat = beats_by_id.get(beat_id) or {}
            if skip_existing and str(beat.get("video_url") or "").strip():
                skipped += 1
                continue
            if beat_id in active_beat_ids:
                skipped += 1
                continue
            created = cls.create_job(
                project_id,
                episode_id,
                beat_id=beat_id,
                render_scope="shot",
                options=incoming,
            )
            job_ids.append(str(created["job_id"]))
        if not job_ids:
            if beat_ids is not None:
                raise ValueError("勾选的镜头都在生成中，请稍后再试或到「全部任务」查看进度。")
            raise ValueError("全部镜头已有成片或正在生成，请点「重新生成本镜」或前往合成。")
        return {
            "render_mode": "shot",
            "job_id": job_ids[0],
            "job_ids": job_ids,
            "submitted": len(job_ids),
            "skipped": skipped,
            "status": "queued",
            "render_scope": "shot",
        }

    @classmethod
    def create_upscale_job(
        cls,
        project_id: str,
        episode_id: str,
        beat_id: str,
        options: dict[str, Any] | None = None,
        *,
        source_url: str | None = None,
        source_job_id: str | None = None,
        duration_sec: float | None = None,
        sequence: Any = None,
    ) -> dict[str, Any]:
        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        beat = cls._find_episode_beat(detail.get("beats") or [], beat_id, sequence)
        if not beat:
            raise ValueError("指定的镜头不存在")
        resolved_source = str(source_url or beat.get("video_url") or "").strip()
        if not resolved_source:
            resolved_source = cls._completed_video_url_for_beat(project_id, episode_id, str(beat.get("id") or beat_id))
        if not resolved_source:
            raise ValueError("该镜头还没有成片，无法超分")
        shot = dict(beat)
        if duration_sec is not None:
            shot["duration_sec"] = duration_sec
        return cls._enqueue_upscale_job(
            project_id=project_id,
            episode_id=episode_id,
            detail=detail,
            source_url=resolved_source,
            options=options,
            beat=shot,
            beat_id=str(beat.get("id") or beat_id),
            source_job_id=source_job_id,
        )

    @classmethod
    def create_upscale_job_from_video_job(
        cls,
        project_id: str,
        job_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = query_one(
            "SELECT * FROM ai_project_jobs WHERE id = %s AND project_id = %s",
            (job_id, project_id),
        )
        if not row or row.get("job_type") != "video_generation":
            raise ValueError("视频任务不存在")
        if row.get("status") not in {"completed", "succeeded"}:
            raise ValueError("成片成功后才能超分")
        payload = cls._job_payload(row)
        scope = str(payload.get("render_scope") or "")
        if scope == "upscale":
            raise ValueError("超分任务本身不能再超分")
        episode_id = str(payload.get("episode_id") or "").strip()
        if not episode_id:
            raise ValueError("该视频任务没有关联分集")
        source_url = cls._original_video_url_from_job(row, payload)
        if not source_url:
            raise ValueError("该任务还没有成片，无法超分")
        beat_ids = cls._job_beat_ids(payload)
        if scope == "selection" and len(beat_ids) > 1:
            raise ValueError("多镜任务请到剧集工坊逐镜点「超分」")
        shots = payload.get("shots") or payload.get("source_shots") or []
        duration = None
        sequence = None
        if isinstance(shots, list) and shots:
            if scope in {"episode", "compose"} or len(beat_ids) != 1:
                duration = sum(duration_seconds(item) for item in shots if isinstance(item, dict))
            else:
                duration = duration_seconds(shots[0] if isinstance(shots[0], dict) else {})
            first = shots[0] if isinstance(shots[0], dict) else {}
            sequence = first.get("sequence")
        beat_id = next(iter(beat_ids), "") if len(beat_ids) == 1 else ""
        if beat_id and scope not in {"episode", "compose"}:
            try:
                return cls.create_upscale_job(
                    project_id,
                    episode_id,
                    beat_id,
                    options,
                    source_url=source_url,
                    source_job_id=job_id,
                    duration_sec=duration,
                    sequence=sequence,
                )
            except ValueError as err:
                if "指定的镜头不存在" not in str(err):
                    raise
        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        shot = {
            "id": "",
            "sequence": sequence or "成片",
            "duration_sec": duration or float(payload.get("duration_per_beat") or cls.DEFAULTS["duration_per_beat"]),
        }
        return cls._enqueue_upscale_job(
            project_id=project_id,
            episode_id=episode_id,
            detail=detail,
            source_url=source_url,
            options=options,
            beat=shot,
            beat_id="",
            source_job_id=job_id,
            title_label=str(sequence or "成片"),
        )

    @classmethod
    def _enqueue_upscale_job(
        cls,
        *,
        project_id: str,
        episode_id: str,
        detail: dict[str, Any],
        source_url: str,
        options: dict[str, Any] | None,
        beat: dict[str, Any],
        beat_id: str,
        source_job_id: str | None = None,
        title_label: str | None = None,
    ) -> dict[str, Any]:
        incoming = dict(options or {})
        incoming.pop("beat_ids", None)
        incoming.pop("force", None)
        settings = {**cls.DEFAULTS, **cls.resolve_generation_options(incoming)}
        workflow_id = str(settings.get("workflow") or cls.DEFAULTS["workflow"])
        rejection = cls._vsr_rejection_for_shot(settings, beat, workflow_id)
        if rejection:
            raise ValueError(rejection)
        cls._assert_can_enqueue(
            project_id,
            episode_id,
            "upscale",
            beat_id=str(beat_id) or None,
            source_job_id=source_job_id,
        )
        comfy_config = ComfyService.get_config()
        comfy = ComfyVideoClient(comfy_config.base_url)
        comfy.ping()
        comfy.require_rtx_vsr_node()
        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        sequence = title_label or beat.get("sequence") or "?"
        payload = {
            **settings,
            "model": "RTX 2x 超分",
            "api_endpoint": f"{comfy_config.base_url}/prompt",
            "target_type": "shot_upscale" if beat_id else "episode_upscale",
            "render_scope": "upscale",
            "render_mode": "shot" if beat_id else "episode",
            "workflow_id": workflow_id,
            "project_id": project_id,
            "episode_id": episode_id,
            "beat_id": str(beat_id or ""),
            "beat_ids": [str(beat_id)] if beat_id else [],
            "source_job_id": str(source_job_id or ""),
            "episode_number": detail.get("number"),
            "episode_title": detail.get("title") or "",
            "shot_count": 1,
            "source_video_url": source_url,
            "comfy_base_url": comfy_config.base_url,
            "source_shots": [{
                "beat_id": str(beat_id or ""),
                "sequence": sequence,
                "video_url": source_url,
                "duration_sec": duration_seconds(beat),
            }],
            "shots": [],
            "render_plan": {"status": "queued", "chunks": [], "assembly": None},
        }
        execute_sql(
            """
            INSERT INTO ai_project_jobs
            (id, project_id, job_type, title, status, progress, result_url, payload_json, created_at, updated_at)
            VALUES (%s, %s, 'video_generation', %s, 'queued', 0, NULL, %s, %s, %s)
            """,
            (
                jid,
                project_id,
                f"2x 超分：第 {detail.get('number')} 集 Beat {sequence}",
                json.dumps(payload, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        _EXECUTOR.submit(cls._run_job, jid)
        return {
            "job_id": jid,
            "status": "queued",
            "render_scope": "upscale",
            "render_mode": payload["render_mode"],
            "shot_count": 1,
        }

    @classmethod
    def create_job(
        cls,
        project_id: str,
        episode_id: str,
        *,
        beat_id: str | None = None,
        beat_ids: list[str] | None = None,
        render_scope: str = "episode",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        settings = {**cls.DEFAULTS, **cls.resolve_generation_options(options)}
        workflow_id = str(settings.get("workflow") or cls.DEFAULTS["workflow"])
        render_mode = episode_video_render_mode(workflow_id)
        try:
            model_name = workflow_for(workflow_id).name
        except KeyError:
            model_name = "MiniMax H3"

        selected_ids: list[str] = []
        if beat_id:
            selected_ids = [str(beat_id)]
        elif beat_ids:
            seen: set[str] = set()
            for item in beat_ids:
                item_id = str(item or "").strip()
                if item_id and item_id not in seen:
                    seen.add(item_id)
                    selected_ids.append(item_id)

        if selected_ids:
            render_scope = "shot" if len(selected_ids) == 1 else "selection"
        elif render_mode == "shot":
            raise ValueError("逐镜工作流必须指定 Beat，请使用一键生成或「生成本镜」")
        else:
            render_scope = "episode"

        llm = H3PromptBuilder.ensure_available()
        comfy_config = ComfyService.get_config()
        comfy = ComfyVideoClient(comfy_config.base_url)
        task_type = comfy.preflight(require_director=uses_director_timeline(workflow_id))
        cls._assert_can_enqueue(
            project_id,
            episode_id,
            render_scope,
            beat_id=selected_ids[0] if len(selected_ids) == 1 else None,
            beat_ids=selected_ids or None,
        )

        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        assets = ProjectDetailService.list_assets(project_id)
        shots = cls._prepare_shots(detail, assets, beat_ids=selected_ids or None)
        if selected_ids and not shots:
            raise ValueError("指定的 Beat 不存在或无法生成视频")
        if options:
            settings["render_pass"] = str(options.get("render_pass") or "final")
        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        if render_scope == "shot":
            scope_label = f"Beat {shots[0].get('sequence')}"
        elif render_scope == "selection":
            sequences = "、".join(str(shot.get("sequence") or "") for shot in shots)
            scope_label = f"选中 {len(shots)} 镜（Beat {sequences}）"
        else:
            scope_label = "整集"
        payload = {
            **settings,
            "model": model_name,
            "api_endpoint": f"{comfy_config.base_url}/prompt",
            "target_type": "shot_video" if render_scope in {"shot", "selection"} else "episode_video",
            "render_scope": render_scope,
            "render_mode": render_mode,
            "render_pass": str((options or {}).get("render_pass") or "final"),
            "workflow_id": workflow_id,
            "project_id": project_id,
            "episode_id": episode_id,
            "beat_id": selected_ids[0] if selected_ids else "",
            "beat_ids": selected_ids,
            "episode_number": detail.get("number"),
            "episode_title": detail.get("title") or "",
            "shot_count": len(shots),
            "total_frames": sum(int(shot.get("frame_count") or 192) for shot in shots),
            "total_duration_seconds": sum(float(shot.get("duration_sec") or 8) for shot in shots),
            "llm_model": llm["model"],
            "comfy_base_url": comfy_config.base_url,
            "task_type": task_type,
            "source_shots": shots,
            "shots": [],
            "render_plan": {"status": "queued", "chunks": [], "assembly": None},
        }
        execute_sql(
            """
            INSERT INTO ai_project_jobs
            (id, project_id, job_type, title, status, progress, result_url, payload_json, created_at, updated_at)
            VALUES (%s, %s, 'video_generation', %s, 'queued', 0, NULL, %s, %s, %s)
            """,
            (
                jid,
                project_id,
                f"生成{scope_label}视频：第 {detail.get('number')} 集 {detail.get('title') or ''}",
                json.dumps(payload, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        _EXECUTOR.submit(cls._run_job, jid)
        return {
            "job_id": jid,
            "status": "queued",
            "render_scope": render_scope,
            "render_mode": render_mode,
            "shot_count": len(shots),
        }

    @classmethod
    def create_compose_job(
        cls,
        project_id: str,
        episode_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        data = detail.get("data") if isinstance(detail.get("data"), dict) else {}
        beats = sorted(detail.get("beats") or [], key=lambda item: int(item.get("sequence") or 0))
        if not beats:
            raise ValueError("该分集没有 Beat，无法合成。")
        missing = [
            f"Beat {item.get('sequence') or '?'}"
            for item in beats
            if not str(item.get("video_url") or "").strip()
        ]
        if str(data.get("episode_video_source") or "") == "director_direct" and missing:
            raise ValueError("本集已由 H3 Director 加速版一次直出，无需再合成")
        if missing:
            raise ValueError("以下镜头还没有视频，无法合成：\n" + "\n".join(f"- {item}" for item in missing))
        mix_options = dict(options or {})
        cls._assert_dubbing_ready_for_compose(project_id, episode_id, beats)
        cls._assert_can_enqueue(project_id, episode_id, "compose")
        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        source_shots = [
            {
                "beat_id": str(item.get("id") or ""),
                "sequence": int(item.get("sequence") or index + 1),
                "video_url": str(item.get("video_url") or "").strip(),
                "duration_sec": duration_seconds(item),
            }
            for index, item in enumerate(beats)
        ]
        from .dubbing_mix import mix_dubbing_enabled

        payload = {
            **mix_options,
            "model": "ffmpeg concat",
            "target_type": "episode_video",
            "render_scope": "compose",
            "render_mode": "shot",
            "project_id": project_id,
            "episode_id": episode_id,
            "episode_number": detail.get("number"),
            "episode_title": detail.get("title") or "",
            "shot_count": len(source_shots),
            "total_duration_seconds": sum(float(item.get("duration_sec") or 8) for item in source_shots),
            "source_shots": source_shots,
            "shots": source_shots,
            "mix_dubbing": mix_dubbing_enabled(mix_options),
            "render_plan": {"status": "queued", "chunks": [], "assembly": {"status": "queued", "method": "ffmpeg_concat"}},
        }
        execute_sql(
            """
            INSERT INTO ai_project_jobs
            (id, project_id, job_type, title, status, progress, result_url, payload_json, created_at, updated_at)
            VALUES (%s, %s, 'video_generation', %s, 'queued', 0, NULL, %s, %s, %s)
            """,
            (
                jid,
                project_id,
                f"合成整集成片：第 {detail.get('number')} 集 {detail.get('title') or ''}",
                json.dumps(payload, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        _EXECUTOR.submit(cls._run_job, jid)
        return {"job_id": jid, "status": "queued", "render_scope": "compose", "render_mode": "shot"}

    @classmethod
    def _assert_dubbing_ready_for_compose(
        cls,
        project_id: str,
        episode_id: str,
        beats: list[dict[str, Any]],
    ) -> None:
        from ...skill_packs import resolve_skill_pack_id
        from .dubbing_lines import expand_episode_lines
        from .dubbing_mix import compose_dubbing_block

        pack_id = ""
        try:
            pack_id = resolve_skill_pack_id(project_id=project_id)
        except Exception:
            pack_id = ""
        reason = compose_dubbing_block(expand_episode_lines(beats, []), pack_id)
        if reason:
            raise ValueError(reason)

    @staticmethod
    def _original_video_url_from_job(row: dict[str, Any] | None, payload: dict[str, Any]) -> str:
        if str(payload.get("render_scope") or "") == "upscale":
            return str(payload.get("source_video_url") or "").strip()
        result = str((row or {}).get("result_url") or "").strip()
        upscaled = str(payload.get("upscaled_video_url") or "").strip()
        if result and result != upscaled:
            return result
        source = str(payload.get("source_video_url") or "").strip()
        if source:
            return source
        shots = payload.get("shots") or payload.get("source_shots") or []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            url = str(shot.get("video_url") or "").strip()
            if url:
                return url
        return result

    @classmethod
    def _completed_video_url_for_beat(cls, project_id: str, episode_id: str, beat_id: str) -> str:
        wanted = str(beat_id or "").strip()
        if not wanted:
            return ""
        try:
            rows = query_all(
                """
                SELECT result_url, payload_json FROM ai_project_jobs
                WHERE project_id = %s AND job_type = 'video_generation'
                  AND status IN ('completed', 'succeeded')
                ORDER BY updated_at DESC
                LIMIT 80
                """,
                (project_id,),
            )
        except Exception:
            return ""
        for row in rows or []:
            payload = cls._job_payload(row)
            if str(payload.get("episode_id") or "") != str(episode_id):
                continue
            if str(payload.get("render_scope") or "") == "upscale":
                continue
            if wanted not in cls._job_beat_ids(payload):
                continue
            url = cls._original_video_url_from_job(row, payload)
            if url:
                return url
        return ""

    @classmethod
    def _mark_source_job_upscaled(cls, source_job_id: str, upscaled_url: str, original_url: str) -> None:
        job_id = str(source_job_id or "").strip()
        if not job_id or not upscaled_url:
            return
        row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id = %s", (job_id,))
        if not row:
            return
        payload = cls._job_payload(row)
        payload["upscaled_video_url"] = upscaled_url
        if original_url:
            payload["source_video_url"] = original_url
        execute_sql(
            "UPDATE ai_project_jobs SET payload_json = %s, updated_at = %s WHERE id = %s",
            (json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )

    @staticmethod
    def _job_payload(row: dict[str, Any] | None) -> dict[str, Any]:
        raw = (row or {}).get("payload_json")
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _find_episode_beat(beats: list[Any], beat_id: str, sequence: Any = None) -> dict[str, Any] | None:
        wanted = str(beat_id or "").strip()
        seq = str(sequence or "").strip()
        for beat in beats or []:
            if not isinstance(beat, dict):
                continue
            aliases = {
                str(beat.get("id") or "").strip(),
                str(beat.get("beat_id") or "").strip(),
            }
            if wanted and wanted in aliases:
                return beat
        if seq and seq not in {"?", "成片"}:
            for beat in beats or []:
                if isinstance(beat, dict) and str(beat.get("sequence") or "").strip() == seq:
                    return beat
        suffix = wanted[5:] if wanted.startswith("beat-") else ""
        if suffix.isdigit():
            for beat in beats or []:
                if isinstance(beat, dict) and str(beat.get("sequence") or "").strip() == suffix:
                    return beat
        return None

    @staticmethod
    def _job_beat_id(payload: dict[str, Any]) -> str:
        beat_id = str(payload.get("beat_id") or "").strip()
        if beat_id:
            return beat_id
        shots = payload.get("source_shots") or []
        if shots and isinstance(shots[0], dict):
            return str(shots[0].get("beat_id") or "").strip()
        return ""

    @classmethod
    def _job_beat_ids(cls, payload: dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        raw = payload.get("beat_ids")
        if isinstance(raw, list):
            ids.update(str(item).strip() for item in raw if str(item or "").strip())
        one = cls._job_beat_id(payload)
        if one:
            ids.add(one)
        for shot in payload.get("source_shots") or []:
            if isinstance(shot, dict):
                beat_id = str(shot.get("beat_id") or "").strip()
                if beat_id:
                    ids.add(beat_id)
        return ids

    @classmethod
    def _active_video_jobs(cls, project_id: str, episode_id: str) -> list[dict[str, Any]]:
        placeholders = ", ".join(["%s"] * len(_ACTIVE_VIDEO_STATUSES))
        return query_all(
            f"""
            SELECT id, status, payload_json FROM ai_project_jobs
            WHERE project_id = %s AND job_type = 'video_generation'
              AND status IN ({placeholders})
              AND JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.episode_id')) = %s
            ORDER BY created_at DESC
            """,
            (project_id, *_ACTIVE_VIDEO_STATUSES, episode_id),
        ) or []

    @classmethod
    def _assert_can_enqueue(
        cls,
        project_id: str,
        episode_id: str,
        render_scope: str,
        *,
        beat_id: str | None = None,
        beat_ids: list[str] | None = None,
        source_job_id: str | None = None,
    ) -> None:
        active = cls._active_video_jobs(project_id, episode_id)
        requested = {str(item).strip() for item in (beat_ids or []) if str(item or "").strip()}
        if beat_id:
            requested.add(str(beat_id).strip())
        wanted_source = str(source_job_id or "").strip()
        if render_scope in {"episode", "compose"}:
            if active:
                raise ValueError(f"该分集已有进行中的视频任务：{active[0]['id']}")
            return
        for row in active:
            payload = cls._job_payload(row)
            scope = str(payload.get("render_scope") or "episode")
            if wanted_source and str(payload.get("source_job_id") or "").strip() == wanted_source:
                raise ValueError(f"该成片已有进行中的超分：{row['id']}")
            if scope in {"episode", "compose"}:
                raise ValueError(f"该分集已有进行中的视频任务：{row['id']}")
            occupied = cls._job_beat_ids(payload)
            if requested and occupied & requested:
                raise ValueError(f"该镜头已有进行中的视频任务：{row['id']}")

    @classmethod
    def retry_job(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one(
            "SELECT * FROM ai_project_jobs WHERE id = %s AND project_id = %s",
            (job_id, project_id),
        )
        if not row or row.get("job_type") != "video_generation":
            raise ValueError("视频任务不存在")
        if row.get("status") not in {"failed", "completed", "succeeded"}:
            raise ValueError("只有失败或已完成的视频任务可以重试")
        payload = json.loads(row.get("payload_json") or "{}")
        for key in (
            "shots", "llm_attempts", "prompt_generation_progress", "timeline", "workflow_request",
            "prompt_id", "client_id", "queue_number", "node_errors", "comfy_output",
            "director_report", "storage_warning", "failure_stage", "comfy_submission_count",
        ):
            payload.pop(key, None)
        payload["shots"] = []
        timestamp = now_str()
        execute_sql(
            """
            UPDATE ai_project_jobs SET status = 'queued', progress = 0, result_url = NULL,
              error_message = NULL, completed_at = NULL, payload_json = %s, updated_at = %s
            WHERE id = %s AND project_id = %s
            """,
            (json.dumps(payload, ensure_ascii=False), timestamp, job_id, project_id),
        )
        _EXECUTOR.submit(cls._run_job, job_id)
        return query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}

    @classmethod
    def recover_orphaned_jobs(cls) -> None:
        timestamp = now_str()
        execute_sql(
            """
            UPDATE ai_project_jobs
            SET status = 'failed', progress = 0,
                error_message = '服务进程重启，后台视频任务已中断，请点击重试。', updated_at = %s
            WHERE job_type = 'video_generation'
              AND status IN ('queued', 'preparing', 'prompt_generation', 'uploading', 'comfy_queued', 'running', 'assembling', 'downloading')
            """,
            (timestamp,),
        )

    @classmethod
    def _prepare_shots(
        cls,
        detail: dict[str, Any],
        assets: list[dict[str, Any]],
        beat_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        all_beats = sorted(detail.get("beats") or [], key=lambda item: int(item.get("sequence") or 0))
        if not all_beats:
            raise ValueError("该分集没有 Beat，无法生成视频。")
        if beat_ids is not None:
            known = {str(beat.get("id") or "") for beat in all_beats}
            missing_ids = [item for item in beat_ids if item not in known]
            if missing_ids:
                raise ValueError("指定的镜头不存在或无法生成视频：" + "、".join(missing_ids))
            wanted = set(beat_ids)
            beats = [beat for beat in all_beats if str(beat.get("id") or "") in wanted]
        else:
            beats = all_beats
        by_id = {str(asset.get("id")): asset for asset in assets if asset.get("id")}
        protagonist = cls._episode_protagonist(all_beats, assets)
        if not protagonist:
            raise ValueError("无法确定分集主角，请为 Beat 关联主角资产。")
        missing: list[str] = []
        shots: list[dict[str, Any]] = []
        for beat in beats:
            sequence = int(beat.get("sequence") or len(shots) + 1)
            action = str(beat.get("video_prompt_zh") or beat.get("action") or "").strip()
            if not action:
                missing.append(f"Beat {sequence} 缺少动作或视频提示词")
            if not str(beat.get("camera") or "").strip():
                missing.append(f"Beat {sequence} 缺少运镜描述")
            if str(beat.get("dialogue") or "").strip() and not str(beat.get("speaker") or "").strip():
                missing.append(f"Beat {sequence} 有对白但缺少说话人")
            scene = resolve_scene_asset(beat, assets)
            scene_url = scene_master_url(scene)
            if not scene:
                missing.append(f"Beat {sequence} 未绑定场景，请在镜头检视器选择场景")
            elif not scene_url:
                missing.append(f"Beat {sequence} 缺少场景「{scene.get('name') or beat.get('scene') or ''}」的主视图")
            beat_characters = [
                by_id[str(asset_id)] for asset_id in (beat.get("character_ids") or [])
                if str(asset_id) in by_id and by_id[str(asset_id)].get("kind") == "character"
            ]
            if not beat_characters:
                beat_characters = [protagonist]
            character_references: list[dict[str, str]] = []
            for character in beat_characters:
                look = cls._select_character_look(character, beat)
                selected_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
                selected_look_id = str(selected_ids.get(str(character.get("id") or "")) or "").strip()
                if not look:
                    if selected_look_id:
                        missing.append(f"Beat {sequence} 为「{character.get('name')}」选择的造型无效，请重新选择")
                    else:
                        missing.append(f"Beat {sequence} 缺少符合时代/年龄/服装的「{character.get('name')}」造型图")
                    continue
                character_url = str(look.get("image_url") or "").strip()
                if not character_url.startswith(("http://", "https://")):
                    missing.append(f"Beat {sequence} 的「{character.get('name')}」造型没有有效图片")
                    continue
                character_references.append({
                    "character_id": str(character.get("id") or ""),
                    "character_name": str(character.get("name") or ""),
                    "look_id": str(look.get("id") or ""),
                    "description": str(look.get("appearance_details") or look.get("description") or ""),
                    "url": character_url,
                })
            reference_urls = [item["url"] for item in character_references] + ([scene_url] if scene_url else [])
            ref_images: list[dict[str, Any]] = []
            scene_picture_index = len(character_references) + 1
            pack_id = ""
            recipe = None
            try:
                from ...skill_packs import get_pack, resolve_skill_pack_id
                from ...skill_packs.handlers import bind_r2v_slot_images, r2v_upload_urls

                pack_id = resolve_skill_pack_id(
                    beat=beat,
                    project_id=str(detail.get("project_id") or ""),
                ) or ""
                recipe = get_pack(pack_id)
            except Exception:
                recipe = None
            if recipe is not None and not recipe.is_default and recipe.r2v_slots:
                bind_beat = {
                    **beat,
                    "character_ids": [],
                    "characters": [
                        {
                            "id": item.get("character_id"),
                            "name": item.get("character_name"),
                            "url": item.get("url"),
                        }
                        for item in character_references
                    ],
                    "scene": str(beat.get("scene") or (scene or {}).get("name") or ""),
                    "scene_id": str((scene or {}).get("id") or beat.get("scene_id") or ""),
                }
                slots = bind_r2v_slot_images(recipe, bind_beat, assets)
                packed_urls = r2v_upload_urls(recipe, bind_beat, assets)
                if packed_urls:
                    reference_urls = packed_urls
                    ref_images = slots
                    scene_picture_index = next(
                        (
                            int(item.get("index") or 0)
                            for item in slots
                            if item.get("source") == "scene"
                        ),
                        scene_picture_index,
                    )
            shot = {
                "beat_id": str(beat.get("id") or f"beat-{sequence}"),
                "sequence": sequence,
                "heading": str(beat.get("heading") or ""),
                "action": action,
                "camera": str(beat.get("camera") or ""),
                "dialogue": str(beat.get("dialogue") or "").strip(),
                "dialogue_turns": beat.get("dialogue_turns") if isinstance(beat.get("dialogue_turns"), list) else [],
                "visible_text": str(beat.get("visible_text") or "").strip(),
                "h3_prompt": str(beat.get("h3_prompt") or "").strip(),
                "h3_prompt_source": str(beat.get("h3_prompt_source") or "").strip(),
                "skill_pack_id": pack_id,
                "narration": str(beat.get("narration") or beat.get("voiceover") or "").strip(),
                "speaker": str(beat.get("speaker") or "").strip(),
                "characters": [item["character_name"] for item in character_references],
                "props": beat.get("props") or [],
                "scene": str(beat.get("scene") or (scene or {}).get("name") or ""),
                "scene_id": str((scene or {}).get("id") or beat.get("scene_id") or ""),
                "scene_description": str((scene or {}).get("description") or (scene or {}).get("visual_prompt") or ""),
                "character_id": str(protagonist.get("id") or ""),
                "character_name": str(protagonist.get("name") or ""),
                "character_look_id": next(
                    (item["look_id"] for item in character_references if item["character_id"] == str(protagonist.get("id") or "")),
                    "",
                ),
                "character_description": next(
                    (item["description"] for item in character_references if item["character_id"] == str(protagonist.get("id") or "")),
                    "",
                ),
                "visual_prompt": str(beat.get("visual_prompt") or "").strip(),
                "audio": str(beat.get("audio") or beat.get("soundscape") or "").strip(),
                "video_prompt_zh": str(beat.get("video_prompt_zh") or beat.get("timestamped_zh_prompt") or "").strip(),
                "timestamped_zh_prompt": str(beat.get("timestamped_zh_prompt") or "").strip(),
                "character_references": character_references,
                "scene_picture_index": scene_picture_index,
                "reference_urls": reference_urls,
                "ref_images": ref_images,
                "duration_sec": duration_seconds(beat),
                "duration_seconds": duration_seconds(beat),
                "frame_count": frame_count(beat),
                "continuity": {"sceneId": str((scene or {}).get("id") or beat.get("scene_id") or ""), "sequence": sequence},
            }
            shots.append(shot)
        if missing:
            raise ValueError("视频生成前置检查失败：\n" + "\n".join(f"- {item}" for item in missing))
        return shots

    @staticmethod
    def _episode_protagonist(beats: list[dict[str, Any]], assets: list[dict[str, Any]]) -> dict[str, Any] | None:
        characters = [asset for asset in assets if asset.get("kind") == "character"]
        by_id = {str(asset.get("id")): asset for asset in characters}
        for beat in beats:
            for asset_id in beat.get("character_ids") or []:
                if str(asset_id) in by_id:
                    return by_id[str(asset_id)]
        searchable = " ".join(
            str(beat.get(key) or "") for beat in beats
            for key in ("heading", "speaker", "action", "dialogue")
        )
        return next((asset for asset in characters if str(asset.get("name") or "") in searchable), None)

    @staticmethod
    def _select_character_look(character: dict[str, Any], beat: dict[str, Any]) -> dict[str, Any] | None:
        extra = character.get("extra") if isinstance(character.get("extra"), dict) else {}
        looks = [item for item in (extra.get("identities") or []) if isinstance(item, dict) and item.get("image_url")]
        selected_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
        selected_look_id = str(selected_ids.get(str(character.get("id") or "")) or "").strip()
        if selected_look_id:
            return next((item for item in looks if str(item.get("id") or "") == selected_look_id), None)
        legacy_look_id = str(beat.get("character_look_id") or "").strip()
        if legacy_look_id:
            legacy = next((item for item in looks if str(item.get("id") or "") == legacy_look_id), None)
            if legacy:
                return legacy
        context = " ".join(str(beat.get(key) or "") for key in (
            "heading", "action", "visual_prompt", "video_prompt_zh", "scene", "speaker"
        ))
        modern = bool(re.search(r"现代|大学|图书馆|电脑|西装|衬衫|研究生|26岁", context))
        ancient = bool(re.search(r"古代|茅屋|长衫|粗布|发髻|陶碗|木床|土墙|米缸|17岁", context))
        def description(item: dict[str, Any]) -> str:
            return " ".join(str(item.get(key) or "") for key in ("name", "description", "appearance_details"))
        if modern:
            return next((item for item in looks if re.search(r"现代|西装|衬衫|研究生|26岁", description(item))), None)
        if ancient:
            return next((item for item in looks if re.search(r"古代|长衫|粗布|发髻|17岁", description(item))), None)
        return looks[0] if len(looks) == 1 else None

    @classmethod
    @staticmethod
    def _is_manual_h3_prompt(shot: dict[str, Any]) -> bool:
        return str(shot.get("h3_prompt_source") or "").strip().lower() == "manual"

    @classmethod
    def _skip_program_pack(cls, shot: dict[str, Any]) -> bool:
        from ...skill_packs import skip_program_pack_enabled

        return skip_program_pack_enabled(str(shot.get("skill_pack_id") or "").strip())

    @classmethod
    def _workshop_prompt_for_shot(cls, shot: dict[str, Any]) -> str | None:
        saved = str(shot.get("h3_prompt") or "").strip()
        if not saved:
            return None
        if cls._is_manual_h3_prompt(shot) or cls._skip_program_pack(shot):
            return H3PromptBuilder.canonicalize_reference_tags(saved)
        prepared = H3PromptBuilder.prepare_generated_prompt(saved, shot)
        if H3PromptBuilder.validate_prompts([shot], [prepared]):
            return None
        return prepared

    @classmethod
    def _workshop_prompts_usable(cls, source_shots: list[dict[str, Any]]) -> list[str] | None:
        if not source_shots:
            return None
        prepared: list[str] = []
        for shot in source_shots:
            item = cls._workshop_prompt_for_shot(shot)
            if item is None:
                return None
            prepared.append(item)
        return prepared

    @classmethod
    def _run_job(cls, job_id: str) -> None:
        gpu_cm = None
        try:
            row = query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}
            payload = json.loads(row.get("payload_json") or "{}")
            if str(payload.get("render_scope") or "") == "compose":
                cls._run_compose_job(job_id, payload)
                return
            gpu_cm = occupy_gpu("comfy")
            gpu_cm.__enter__()
            if str(payload.get("render_scope") or "") == "upscale":
                cls._run_upscale_job(job_id, payload)
                return
            cls._set_state(job_id, payload, "preparing", 10)
            requested_workflow = payload.get("workflow_id") or cls.DEFAULTS["workflow"]
            try:
                definition = workflow_for(requested_workflow)
            except KeyError:
                definition = None
                payload["workflow_fallback"] = {
                    "requested": str(requested_workflow),
                    "resolved": cls.DEFAULTS["workflow"],
                    "reason": "workflow_not_registered",
                }
            resolved_workflow_id = definition.id if definition else cls.DEFAULTS["workflow"]
            timeline_job = uses_director_timeline(resolved_workflow_id)
            comfy = ComfyVideoClient(payload["comfy_base_url"])
            task_type = comfy.preflight(require_director=timeline_job)
            source_shots = payload.get("source_shots") or []

            payload["llm_attempts"] = []
            payload["prompt_generation_progress"] = {"completed": 0, "total": len(source_shots)}
            saved_prompts = cls._workshop_prompts_usable(source_shots)
            if saved_prompts is not None:
                prompts = saved_prompts
                payload["prompt_source"] = "workshop_material"
                payload["prompt_generation_progress"]["completed"] = len(source_shots)
            else:
                payload["prompt_source"] = "configured_llm"
                cls._set_state(job_id, payload, "prompt_generation", 20)

                def record_attempt(attempt: dict[str, Any]) -> None:
                    payload["llm_attempts"].append(attempt)
                    if attempt.get("status") == "passed":
                        payload["prompt_generation_progress"]["completed"] += 1
                    total = max(1, int(payload["prompt_generation_progress"]["total"]))
                    completed = int(payload["prompt_generation_progress"]["completed"])
                    cls._set_state(job_id, payload, "prompt_generation", 20 + (completed * 9 // total))

                prompts = H3PromptBuilder.build_prompts(source_shots, on_attempt=record_attempt)

            generated_shots = [{**shot, "prompt": prompt} for shot, prompt in zip(source_shots, prompts)]
            payload["shots"] = generated_shots
            cls._set_state(job_id, payload, "uploading", 30)

            uploaded_cache: dict[str, dict[str, str]] = {}
            subfolder = f"zly-ai-media/{payload['project_id']}/{payload['episode_id']}/{job_id}"
            for shot in generated_shots:
                uploaded_refs = []
                for ref_index, url in enumerate(shot["reference_urls"], start=1):
                    if url not in uploaded_cache:
                        suffix = PurePosixPath(urlparse(url).path).suffix or ".png"
                        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
                        uploaded_cache[url] = comfy.upload_image(
                            url,
                            subfolder=subfolder,
                            preferred_name=f"beat-{shot['sequence']}-picture-{ref_index}-{digest}{suffix}",
                        )
                    uploaded_refs.append(uploaded_cache[url])
                shot["uploaded_refs"] = uploaded_refs

            if timeline_job:
                result_url = cls._run_timeline_job(
                    job_id, payload, comfy, task_type, generated_shots, definition, resolved_workflow_id,
                )
            else:
                result_url = cls._run_shot_graph_job(
                    job_id, payload, comfy, generated_shots, resolved_workflow_id,
                )
            payload["render_plan"] = payload.get("render_plan") or {}
            payload["render_plan"]["status"] = "succeeded"
            payload["render_plan"]["total_duration"] = payload.get("total_duration_seconds")
            payload["result_kind"] = "episode_video" if payload.get("render_scope") == "episode" else "shot_video"
            if payload.get("render_scope") in {"shot", "selection"} and generated_shots:
                try:
                    cls._write_selected_beat_videos(payload, generated_shots, result_url)
                except Exception as beat_update_error:
                    payload["beat_update_warning"] = str(beat_update_error)
                cls._auto_upscale_if_requested(job_id, payload, comfy, generated_shots)
            if payload.get("render_scope") == "episode":
                try:
                    cls._write_episode_video(
                        payload["project_id"],
                        payload["episode_id"],
                        url=result_url,
                        source="director_direct",
                        job_id=job_id,
                    )
                except Exception as episode_update_error:
                    payload["episode_update_warning"] = str(episode_update_error)
            timestamp = now_str()
            execute_sql(
                """
                UPDATE ai_project_jobs SET status = 'completed', progress = 100, result_url = %s,
                  payload_json = %s, error_message = NULL, completed_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (result_url, json.dumps(payload, ensure_ascii=False), timestamp, timestamp, job_id),
            )
        except Exception as err:
            timestamp = now_str()
            try:
                row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}
                failed_payload = json.loads(row.get("payload_json") or "{}")
                failed_payload["failure_stage"] = failed_payload.get("runtime_stage") or "unknown"
                if isinstance(failed_payload.get("render_plan"), dict):
                    failed_payload["render_plan"]["status"] = "failed"
                execute_sql(
                    """
                    UPDATE ai_project_jobs SET status = 'failed', progress = 0, error_message = %s,
                      payload_json = %s, updated_at = %s WHERE id = %s
                    """,
                    (str(err)[:4000], json.dumps(failed_payload, ensure_ascii=False), timestamp, job_id),
                )
            except Exception:
                execute_sql(
                    "UPDATE ai_project_jobs SET status = 'failed', progress = 0, error_message = %s, updated_at = %s WHERE id = %s",
                    (str(err)[:4000], timestamp, job_id),
                )
        finally:
            if gpu_cm is not None:
                gpu_cm.__exit__(None, None, None)

    @classmethod
    def _run_timeline_job(
        cls,
        job_id: str,
        payload: dict[str, Any],
        comfy: ComfyVideoClient,
        task_type: str,
        generated_shots: list[dict[str, Any]],
        definition: Any,
        resolved_workflow_id: str,
    ) -> str:
        capabilities = TimelineRenderCapabilities(
            supports_timeline=bool(definition and definition.supports_timeline),
            supports_multi_segment=bool(definition and definition.supports_multi_segment),
            max_segments=(definition.max_segments if definition else 1) or 1,
            max_total_frames=(definition.max_total_frames if definition else 192) or 192,
            supports_segment_continuity=bool(definition and definition.supports_segment_continuity),
            supports_audio_batch=bool(definition and definition.supports_audio_batch),
        )
        chunks = plan_timeline_chunks(generated_shots, capabilities)
        previous_chunks = {
            tuple(item.get("shot_ids") or []): item
            for item in (payload.get("render_plan") or {}).get("chunks", [])
            if isinstance(item, dict)
        }
        payload["render_plan"] = {
            "status": "running",
            "mode": "timeline",
            "capabilities": capabilities.as_dict(),
            "chunk_count": len(chunks),
            "chunks": [
                {
                    "index": index,
                    "shot_ids": [str(shot.get("beat_id")) for shot in chunk],
                    "status": "succeeded" if tuple(str(shot.get("beat_id")) for shot in chunk) in previous_chunks and previous_chunks[tuple(str(shot.get("beat_id")) for shot in chunk)].get("output") else "queued",
                    "output_start": sum(float(item.get("duration_sec") or 8) for item in generated_shots[:sum(len(c) for c in chunks[:index])]),
                    "output_duration": sum(float(item.get("duration_sec") or 8) for item in chunk),
                } | ({"output": previous_chunks[tuple(str(shot.get("beat_id")) for shot in chunk)]["output"]} if tuple(str(shot.get("beat_id")) for shot in chunk) in previous_chunks and previous_chunks[tuple(str(shot.get("beat_id")) for shot in chunk)].get("output") else {})
                for index, chunk in enumerate(chunks)
            ],
            "assembly": None,
        }
        chunk_outputs: list[dict[str, str]] = []
        for index, chunk in enumerate(chunks):
            if payload["render_plan"]["chunks"][index].get("status") == "succeeded":
                output_start = payload["render_plan"]["chunks"][index]["output_start"]
                for shot in generated_shots:
                    if str(shot.get("beat_id")) in set(payload["render_plan"]["chunks"][index]["shot_ids"]):
                        shot.update({
                            "segmentIndex": index,
                            "renderStatus": "succeeded",
                            "promptSnapshot": shot.get("prompt") or "",
                            "outputStart": output_start,
                            "outputDuration": float(shot.get("duration_sec") or 8),
                        })
                chunk_outputs.append(payload["render_plan"]["chunks"][index]["output"])
                continue
            render_request = comfy.build_render_request(
                chunk,
                task_type,
                render_scope=str(payload.get("render_scope") or "episode"),
                episode_id=str(payload.get("episode_id") or ""),
                workflow_id=str(resolved_workflow_id),
                render_pass=str(payload.get("render_pass") or "final"),
                options=payload,
            )
            timeline = render_request["timeline_data"]
            workflow = comfy.build_workflow(
                timeline, task_type,
                f"video/{payload['project_id']}/{payload['episode_id']}/{job_id}/segment-{index + 1}",
                options=payload,
            )
            payload["render_plan"]["chunks"][index]["timeline"] = timeline
            payload["render_plan"]["chunks"][index]["render_request"] = render_request
            payload["render_plan"]["chunks"][index]["status"] = "submitted"
            payload["timeline"] = timeline if len(chunks) == 1 else None
            payload["workflow_request"] = workflow if len(chunks) == 1 else None
            history, output = cls._await_comfy(
                job_id, payload, comfy, workflow, submission_index=index + 1,
            )
            payload["render_plan"]["chunks"][index].update({
                "status": "succeeded",
                "output": output,
                "director_report": cls._director_report(history.get("outputs") or {}),
            })
            chunk_shot_ids = set(payload["render_plan"]["chunks"][index]["shot_ids"])
            for shot in generated_shots:
                if str(shot.get("beat_id")) in chunk_shot_ids:
                    shot["segmentIndex"] = index
                    shot["renderStatus"] = "succeeded"
                    shot["promptSnapshot"] = shot.get("prompt") or ""
                    shot["continuityIn"] = shot.get("continuity") or {}
                    shot["continuityOut"] = shot.get("continuity") or {}
                    shot["outputStart"] = payload["render_plan"]["chunks"][index]["output_start"]
                    shot["outputDuration"] = float(shot.get("duration_sec") or 8)
            chunk_outputs.append(output)
            cls._set_state(job_id, payload, "running", 95)

        result_url = comfy.view_url(chunk_outputs[0])
        if len(chunk_outputs) > 1:
            payload["render_plan"]["assembly"] = {"status": "running", "method": "ffmpeg_concat"}
            cls._set_state(job_id, payload, "assembling", 96)
            merged = cls._merge_chunk_videos(comfy, chunk_outputs)
            payload["render_plan"]["assembly"] = {"status": "succeeded", "method": "ffmpeg_concat"}
            if QiniuService.get_config().available:
                _, result_url = QiniuService.store_bytes("video", f"episode-{job_id}.mp4", merged)
            else:
                raise RuntimeError("整集分段已经生成，但七牛云存储未配置，无法发布 ffmpeg 合成结果")
        else:
            payload["comfy_output"] = chunk_outputs[0]
            try:
                if QiniuService.get_config().available:
                    content = comfy.download_output(chunk_outputs[0])
                    _, result_url = QiniuService.store_bytes("video", chunk_outputs[0]["filename"], content)
            except Exception as upload_error:
                payload["storage_warning"] = str(upload_error)
        return result_url

    @classmethod
    def _run_shot_graph_job(
        cls,
        job_id: str,
        payload: dict[str, Any],
        comfy: ComfyVideoClient,
        generated_shots: list[dict[str, Any]],
        resolved_workflow_id: str,
    ) -> str:
        if not generated_shots:
            raise RuntimeError("逐镜任务没有可生成的镜头")
        payload["render_plan"] = {
            "status": "running",
            "mode": "shot_graph",
            "workflow_id": resolved_workflow_id,
            "chunk_count": len(generated_shots),
            "chunks": [],
            "assembly": None,
        }
        result_url = ""
        for index, shot in enumerate(generated_shots):
            shot_options = {**payload, "duration": float(shot.get("duration_sec") or 8)}
            workflow = comfy.build_shot_workflow(
                resolved_workflow_id,
                str(shot.get("prompt") or ""),
                shot.get("uploaded_refs") or [],
                f"video/{payload['project_id']}/{payload['episode_id']}/{job_id}/shot-{index + 1}",
                options=shot_options,
            )
            payload["workflow_request"] = workflow if len(generated_shots) == 1 else payload.get("workflow_request")
            payload["render_plan"]["chunks"].append({
                "index": index,
                "shot_ids": [str(shot.get("beat_id") or "")],
                "status": "submitted",
            })
            _history, output = cls._await_comfy(
                job_id, payload, comfy, workflow, submission_index=index + 1,
            )
            payload["render_plan"]["chunks"][index].update({"status": "succeeded", "output": output})
            shot["renderStatus"] = "succeeded"
            shot["promptSnapshot"] = shot.get("prompt") or ""
            result_url = comfy.view_url(output)
            payload["comfy_output"] = output
            try:
                if QiniuService.get_config().available:
                    content = comfy.download_output(output)
                    _, result_url = QiniuService.store_bytes("video", output["filename"], content)
            except Exception as upload_error:
                payload["storage_warning"] = str(upload_error)
            if len(generated_shots) > 1:
                try:
                    ProjectDetailService.update_episode_beat(
                        payload["project_id"],
                        payload["episode_id"],
                        str(shot.get("beat_id")),
                        {
                            "video_url": result_url,
                            "upscaled_video_url": None,
                            "render_status": "completed",
                            "status": "completed",
                        },
                    )
                    shot["video_url"] = result_url
                except Exception as beat_update_error:
                    payload["beat_update_warning"] = str(beat_update_error)
            cls._set_state(job_id, payload, "running", 95)
        return result_url

    @classmethod
    def _run_compose_job(cls, job_id: str, payload: dict[str, Any]) -> None:
        from .dubbing_lines import expand_episode_lines
        from .dubbing_mix import contributing_lines_for_beat, mix_dubbing_enabled, mix_shot_with_lines

        cls._set_state(job_id, payload, "downloading", 20)
        shots = sorted(payload.get("source_shots") or [], key=lambda item: int(item.get("sequence") or 0))
        if not shots:
            raise RuntimeError("合成任务没有镜头视频")
        mix_dubbing = mix_dubbing_enabled(payload)
        dubbing_lines: list[dict[str, Any]] = []
        if mix_dubbing:
            project_id = str(payload.get("project_id") or "")
            episode_id = str(payload.get("episode_id") or "")
            detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
            dubbing_lines = expand_episode_lines(detail.get("beats") or [], [])
        chunks: list[bytes] = []
        mixed_beats: list[str] = []
        muted_beats: list[str] = []
        for index, shot in enumerate(shots):
            url = str(shot.get("video_url") or "").strip()
            if not url:
                raise RuntimeError(f"Beat {shot.get('sequence') or index + 1} 缺少视频地址")
            response = requests.get(url, timeout=600)
            response.raise_for_status()
            if not response.content:
                raise RuntimeError(f"Beat {shot.get('sequence') or index + 1} 视频下载为空")
            clip = response.content
            beat_id = str(shot.get("beat_id") or "")
            overlay_lines = contributing_lines_for_beat(dubbing_lines, beat_id) if mix_dubbing else []
            if overlay_lines:
                clip = mix_shot_with_lines(clip, overlay_lines, cls._fetch_mix_audio)
                mixed_beats.append(beat_id)
                if any(str(item.get("mix") or "") == "replace" for item in overlay_lines):
                    muted_beats.append(beat_id)
            chunks.append(clip)
            cls._set_state(job_id, payload, "downloading", min(70, 20 + (index + 1) * 40 // max(1, len(shots))))
        payload["render_plan"] = payload.get("render_plan") or {}
        payload["render_plan"]["assembly"] = {"status": "running", "method": "ffmpeg_concat"}
        payload["dubbing_mix"] = {
            "enabled": mix_dubbing,
            "mixed_beats": mixed_beats,
            "muted_beats": muted_beats,
        }
        cls._set_state(job_id, payload, "assembling", 80)
        merged = concat_video_bytes(chunks)
        payload["render_plan"]["assembly"] = {"status": "succeeded", "method": "ffmpeg_concat"}
        if not QiniuService.get_config().available:
            raise RuntimeError("各镜视频已就绪，但七牛云存储未配置，无法发布合成成片")
        _, result_url = QiniuService.store_bytes("video", f"episode-{job_id}.mp4", merged)
        payload["render_plan"]["status"] = "succeeded"
        payload["result_kind"] = "episode_video"
        cls._write_episode_video(
            payload["project_id"],
            payload["episode_id"],
            url=result_url,
            source="composed",
            job_id=job_id,
        )
        timestamp = now_str()
        execute_sql(
            """
            UPDATE ai_project_jobs SET status = 'completed', progress = 100, result_url = %s,
              payload_json = %s, error_message = NULL, completed_at = %s, updated_at = %s
            WHERE id = %s
            """,
            (result_url, json.dumps(payload, ensure_ascii=False), timestamp, timestamp, job_id),
        )

    @staticmethod
    def _fetch_mix_audio(url: str) -> bytes:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        content = response.content or b""
        if not content:
            raise RuntimeError("配音下载为空")
        return content

    @classmethod
    def _write_selected_beat_videos(
        cls,
        payload: dict[str, Any],
        shots: list[dict[str, Any]],
        result_url: str,
    ) -> None:
        project_id = str(payload.get("project_id") or "")
        episode_id = str(payload.get("episode_id") or "")
        if not shots:
            return
        if len(shots) == 1:
            shots[0]["video_url"] = result_url
            ProjectDetailService.update_episode_beat(
                project_id,
                episode_id,
                str(shots[0].get("beat_id")),
                {
                    "video_url": result_url,
                    "upscaled_video_url": None,
                    "render_status": "completed",
                    "status": "completed",
                },
            )
            return
        response = requests.get(result_url, timeout=600)
        response.raise_for_status()
        if not response.content:
            raise RuntimeError("Timeline 成片下载为空，无法按镜拆分")
        durations = [float(shot.get("duration_sec") or 8) for shot in shots]
        clips = split_timeline_bytes(response.content, durations)
        if len(clips) != len(shots):
            raise RuntimeError("Timeline 分段数量与选中镜头数不一致")
        if not QiniuService.get_config().available:
            raise RuntimeError("Timeline 已生成，但七牛云存储未配置，无法写入各镜成片")
        split_urls: list[str] = []
        for shot, clip in zip(shots, clips):
            _, url = QiniuService.store_bytes(
                "video",
                f"beat-{shot.get('sequence')}-{payload.get('episode_id')}-{secrets.token_hex(4)}.mp4",
                clip,
            )
            split_urls.append(url)
            shot["video_url"] = url
            ProjectDetailService.update_episode_beat(
                project_id,
                episode_id,
                str(shot.get("beat_id")),
                {
                    "video_url": url,
                    "upscaled_video_url": None,
                    "render_status": "completed",
                    "status": "completed",
                },
            )
        payload["shot_video_urls"] = split_urls

    @classmethod
    def _write_episode_video(
        cls,
        project_id: str,
        episode_id: str,
        *,
        url: str,
        source: str,
        job_id: str,
    ) -> None:
        timestamp = now_str()
        with transaction_cursor() as cursor:
            cursor.execute(
                "SELECT data_json FROM ai_project_episodes WHERE id = %s AND project_id = %s FOR UPDATE",
                (episode_id, project_id),
            )
            episode_row = cursor.fetchone()
            if not episode_row:
                raise ValueError("分集不存在")
            try:
                data = json.loads(episode_row.get("data_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            data["episode_video_url"] = url
            data["episode_video_source"] = source
            data["episode_video_job_id"] = job_id
            cursor.execute(
                "UPDATE ai_project_episodes SET data_json = %s, updated_at = %s WHERE id = %s AND project_id = %s",
                (json.dumps(data, ensure_ascii=False), timestamp, episode_id, project_id),
            )

    @staticmethod
    def _merge_chunk_videos(comfy: ComfyVideoClient, outputs: list[dict[str, str]]) -> bytes:
        return concat_video_bytes([comfy.download_output(output) for output in outputs])

    @classmethod
    def _await_comfy(
        cls,
        job_id: str,
        payload: dict[str, Any],
        comfy: ComfyVideoClient,
        workflow: dict[str, Any],
        *,
        submission_index: int,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        def on_progress(value: int) -> None:
            cls._set_state(job_id, payload, "running", value)

        def on_submitted(submitted: dict[str, Any]) -> None:
            payload["comfy_submission_count"] = submission_index
            payload.update({
                "client_id": submitted["client_id"],
                "prompt_id": submitted["prompt_id"],
                "queue_number": submitted.get("number"),
                "node_errors": submitted.get("node_errors") or {},
            })
            cls._set_state(job_id, payload, "comfy_queued", 5)

        _submitted, history, output = comfy.submit_and_wait(
            workflow,
            progress=on_progress,
            on_submitted=on_submitted,
        )
        return history, output

    @staticmethod
    def _set_state(job_id: str, payload: dict[str, Any], status: str, progress: int) -> None:
        payload["runtime_stage"] = status
        execute_sql(
            "UPDATE ai_project_jobs SET status = %s, progress = %s, payload_json = %s, updated_at = %s WHERE id = %s",
            (status, progress, json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )

    @classmethod
    def _vsr_rejection_for_shot(
        cls,
        options: dict[str, Any],
        shot: dict[str, Any],
        workflow_id: str | None = None,
        *,
        comfy: ComfyVideoClient | None = None,
    ) -> str | None:
        duration = duration_seconds(shot, float(options.get("duration_per_beat") or cls.DEFAULTS["duration_per_beat"]))
        patched = dict(options)
        patched["duration"] = duration
        patched.pop("frames", None)
        patched.pop("length", None)
        mode = workflow_id or str(options.get("workflow_id") or options.get("workflow") or "")
        shape = source_video_shape(mode, patched)
        if shape is None:
            width = int(options.get("width") or 0)
            height = int(options.get("height") or 0)
            if width <= 0 or height <= 0:
                return None
            shape = (width, height, int(h3_length({"duration": duration})))
        vram_total = None
        device_name = ""
        client = comfy
        if client is None:
            try:
                client = ComfyVideoClient(ComfyService.get_config().base_url)
            except Exception:
                client = None
        if client is not None:
            try:
                vram_total = client.vram_total_bytes()
                device_name = client.vram_device_name()
            except Exception:
                vram_total = None
                device_name = ""
        return vsr_memory_rejection(*shape, vram_total=vram_total, device_name=device_name)

    @classmethod
    def _download_video_bytes(cls, url: str) -> bytes:
        response = requests.get(url, timeout=600)
        response.raise_for_status()
        if not response.content:
            raise RuntimeError("超分原片下载为空")
        return response.content

    @classmethod
    def _store_upscaled_video(cls, comfy: ComfyVideoClient, output: dict[str, str], job_id: str, beat_id: str) -> str:
        result_url = comfy.view_url(output)
        if QiniuService.get_config().available:
            content = comfy.download_output(output)
            _, result_url = QiniuService.store_bytes(
                "video",
                f"vsr-{beat_id or job_id}-{secrets.token_hex(4)}.mp4",
                content,
            )
        return result_url

    @classmethod
    def _upscale_source_url(
        cls,
        job_id: str,
        payload: dict[str, Any],
        comfy: ComfyVideoClient,
        source_url: str,
        shot: dict[str, Any],
    ) -> str:
        rejection = cls._vsr_rejection_for_shot(
            payload, shot, str(payload.get("workflow_id") or ""), comfy=comfy,
        )
        if rejection:
            raise RuntimeError(rejection)
        content = cls._download_video_bytes(source_url)
        cls._set_state(job_id, payload, "upscaling", 97)

        def on_progress(value: int) -> None:
            cls._set_state(job_id, payload, "upscaling", max(97, min(99, value)))

        def on_submitted(submitted: dict[str, Any]) -> None:
            payload.update({
                "vsr_client_id": submitted.get("client_id"),
                "vsr_prompt_id": submitted.get("prompt_id"),
            })
            cls._set_state(job_id, payload, "upscaling", 97)

        output = comfy.run_rtx_vsr(
            content,
            preferred_name=f"beat-{shot.get('sequence') or shot.get('beat_id') or 'shot'}.mp4",
            progress=on_progress,
            on_submitted=on_submitted,
            filename_prefix=f"video/{payload.get('project_id')}/{payload.get('episode_id')}/{job_id}/vsr",
        )
        return cls._store_upscaled_video(comfy, output, job_id, str(shot.get("beat_id") or ""))

    @classmethod
    def _auto_upscale_if_requested(
        cls,
        job_id: str,
        payload: dict[str, Any],
        comfy: ComfyVideoClient,
        shots: list[dict[str, Any]],
    ) -> None:
        if not should_auto_upscale(str(payload.get("render_scope") or ""), payload):
            return
        upscaled_urls: list[str] = []
        warnings: list[str] = []
        for shot in shots:
            source_url = str(shot.get("video_url") or "").strip()
            beat_id = str(shot.get("beat_id") or "")
            if not source_url or not beat_id:
                continue
            try:
                upscaled_url = cls._upscale_source_url(job_id, payload, comfy, source_url, shot)
                ProjectDetailService.update_episode_beat(
                    str(payload.get("project_id") or ""),
                    str(payload.get("episode_id") or ""),
                    beat_id,
                    {"upscaled_video_url": upscaled_url},
                )
                shot["upscaled_video_url"] = upscaled_url
                upscaled_urls.append(upscaled_url)
            except Exception as error:
                warnings.append(f"Beat {shot.get('sequence') or beat_id}: {error}")
        if upscaled_urls:
            payload["upscaled_video_url"] = upscaled_urls[0] if len(upscaled_urls) == 1 else None
            payload["upscaled_video_urls"] = upscaled_urls
            payload["source_video_url"] = str(shots[0].get("video_url") or payload.get("source_video_url") or "")
        if warnings:
            payload["upscale_warning"] = "；".join(warnings)

    @classmethod
    def _run_upscale_job(cls, job_id: str, payload: dict[str, Any]) -> None:
        cls._set_state(job_id, payload, "preparing", 10)
        comfy = ComfyVideoClient(payload["comfy_base_url"])
        comfy.ping()
        source_url = str(payload.get("source_video_url") or "").strip()
        shots = payload.get("source_shots") or []
        shot = shots[0] if shots else {"beat_id": payload.get("beat_id"), "sequence": 1, "duration_sec": payload.get("duration_per_beat")}
        if not source_url:
            source_url = str(shot.get("video_url") or "").strip()
        if not source_url:
            raise RuntimeError("超分任务缺少原片地址")
        payload["shots"] = [shot]
        upscaled_url = cls._upscale_source_url(job_id, payload, comfy, source_url, shot)
        beat_id = str(payload.get("beat_id") or shot.get("beat_id") or "")
        if beat_id:
            ProjectDetailService.update_episode_beat(
                str(payload.get("project_id") or ""),
                str(payload.get("episode_id") or ""),
                beat_id,
                {"upscaled_video_url": upscaled_url},
            )
        payload["upscaled_video_url"] = upscaled_url
        payload["upscaled_video_urls"] = [upscaled_url]
        payload["source_video_url"] = source_url
        payload["result_kind"] = "shot_upscale" if beat_id else "episode_upscale"
        payload["render_plan"] = payload.get("render_plan") or {}
        payload["render_plan"]["status"] = "succeeded"
        timestamp = now_str()
        execute_sql(
            """
            UPDATE ai_project_jobs SET status = 'completed', progress = 100, result_url = %s,
              payload_json = %s, error_message = NULL, completed_at = %s, updated_at = %s
            WHERE id = %s
            """,
            (upscaled_url, json.dumps(payload, ensure_ascii=False), timestamp, timestamp, job_id),
        )
        cls._mark_source_job_upscaled(str(payload.get("source_job_id") or ""), upscaled_url, source_url)

    @staticmethod
    def _director_report(outputs: dict[str, Any]) -> str:
        node = outputs.get("8") or {}
        values = node.get("text") or node.get("string") or []
        if isinstance(values, list):
            return "\n".join(str(value) for value in values)
        return str(values or "")
