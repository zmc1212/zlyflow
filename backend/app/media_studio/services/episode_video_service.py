from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import requests

from ..db import execute_sql, now_str, query_all, query_one, transaction_cursor

_VIDEO_LEASE = threading.local()


def _video_write(sql, params):
    owner = getattr(_VIDEO_LEASE, "owner", None)
    if owner:
        sql += " AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.execution_lease.owner'))=%s"
        params = (*params, owner)
    changed = execute_sql(sql, params)
    if owner and changed != 1:
        raise RuntimeError("视频任务执行租约已转移")
    return changed

from .comfy_service import ComfyService
from .comfy_video_client import ComfyVideoClient
from .character_looks import apply_resolved_looks_to_beat, missing_look_message, select_character_look
from .episode_image_prompts import resolve_scene_asset, scene_master_url
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
from ...rtx_vsr_workflow import should_auto_upscale, source_video_shape, vsr_memory_rejection, vsr_scale_from_options, vsr_scale_label
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
_SUCCEEDED_VIDEO_STATUSES = ("completed", "succeeded")
_SHOT_TAKE_SCOPES = frozenset({"shot", "selection"})
_EXCLUDED_TAKE_SCOPES = frozenset({"episode", "compose", "upscale"})


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
            "seed": normalized.get("seed", 0) if workflow_id == "minimax-h3-director-confirm-accel-r2v" else secrets.randbelow(2**31 - 2) + 1,
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

    @staticmethod
    def _requested_segment_ids(options: dict[str, Any] | None) -> list[str] | None:
        if not options or "segment_ids" not in options:
            return None
        raw = options.get("segment_ids")
        if not isinstance(raw, list):
            raise ValueError("segment_ids 必须是 Director 段 ID 列表")
        return list(dict.fromkeys(str(item or "").strip() for item in raw if str(item or "").strip()))

    @classmethod
    def _director_plan_shots(
        cls,
        detail: dict[str, Any],
        options: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
        authoring = detail.get("prompt_authoring") if isinstance(detail.get("prompt_authoring"), dict) else {}
        plan = authoring.get("director_plan") if isinstance(authoring.get("director_plan"), dict) else None
        if not plan:
            raise ValueError("请先使用“连续剧情（导演台）”生成并保存 Director 出片方案")
        if (
            int(plan.get("schema_version") or 0) not in {3, 4, 5, 6}
            or str(plan.get("planning_strategy") or "") != "atomic_units"
            or str(plan.get("validation_status") or "") != "valid"
            or not isinstance(plan.get("source_facts"), dict)
            or not plan.get("source_facts")
            or any(not isinstance(segment.get("source_units"), list) or not segment.get("source_units")
                   for part in plan.get("parts") or [] for segment in part.get("segments") or [])
        ):
            raise ValueError("Director 方案结构已升级，请重新生成")
        if str(plan.get("status") or "") != "current":
            raise ValueError("Director 出片方案已过期，请根据当前剧本和资产重新生成")
        from .director_plan_quality import assert_ready_for_video
        if plan.get("schema_version") in {5, 6}:
            from .director_reliable import assert_routes
            assert_routes(plan)
        requested_revision = options.get("director_plan_revision")
        if requested_revision not in (None, "") and int(requested_revision) != int(plan.get("revision") or 0):
            raise ValueError("Director 出片方案版本已变化，请刷新页面后重试")

        render_scope = str(options.get("render_scope") or "episode")
        if render_scope not in {"episode", "selection"}:
            raise ValueError("Director 工作流只支持整集或 Director 段选区生成")
        parts = plan.get("parts") if isinstance(plan.get("parts"), list) else []
        selected_segments: list[tuple[dict[str, Any], dict[str, Any]]] = []
        if render_scope == "selection":
            part_id = str(options.get("part_id") or "").strip()
            segment_ids = cls._requested_segment_ids(options)
            if not part_id or not segment_ids:
                raise ValueError("局部生成必须选择同一 Part 内的 Director 段")
            part = next((item for item in parts if str(item.get("id") or "") == part_id), None)
            if not part:
                raise ValueError("指定的 Director Part 不存在")
            assert_ready_for_video(plan, str(part.get("source_group_id") or part_id))
            segments = part.get("segments") if isinstance(part.get("segments"), list) else []
            index_by_id = {str(item.get("id") or ""): index for index, item in enumerate(segments)}
            if any(segment_id not in index_by_id for segment_id in segment_ids):
                raise ValueError("选中的 Director 段不存在或不属于同一 Part")
            indexes = sorted(index_by_id[segment_id] for segment_id in segment_ids)
            if indexes != list(range(indexes[0], indexes[-1] + 1)):
                raise ValueError("局部生成只允许选择同一 Part 内连续的 Director 段")
            selected_segments = [(part, segments[index]) for index in indexes]
        else:
            assert_ready_for_video(plan)
            for part in parts:
                for segment in part.get("segments") or []:
                    selected_segments.append((part, segment))
        if not selected_segments:
            raise ValueError("Director 出片方案没有可生成的段")

        reference_urls = [
            str(item.get("image_url") or "").strip()
            for item in plan.get("reference_slots") or []
            if str(item.get("image_url") or "").strip()
        ]
        shots: list[dict[str, Any]] = []
        from .h3_prompt_builder import H3PromptBuilder
        common_prompt = str((plan.get("common_prompt") or (plan.get("common_setting") or {}).get("prompt_text")
                            or (plan.get("common_setting") or {}).get("subject_definitions") or "")).strip()
        previous_part_id = ""
        for sequence, (part, segment) in enumerate(selected_segments, start=1):
            part_id = str(part.get("id") or "")
            part_boundary = bool(previous_part_id and part_id != previous_part_id)
            segment_prompt = str(segment.get("h3_prompt") or segment.get("prompt_text") or "").strip()
            compiled = H3PromptBuilder.compile_director_segment_prompt(
                common_prompt, segment_prompt, language=str(plan.get("language") or "zh-CN"),
            )
            shots.append({
                "group_render_mode": part.get("render_mode", "director"),
                "group_workflow_id": part.get("workflow_id") or plan.get("workflow_id"),
                "group_options": part.get("execution_options") or {},
                "beat_id": str(segment.get("id") or f"director-segment-{sequence}"),
                "sequence": sequence,
                "heading": str(segment.get("title") or f"Director 段 {sequence}"),
                "prompt": compiled["segment_prompt"],
                "h3_prompt": compiled["segment_prompt"],
                "global_prompt": compiled["global_prompt"],
                "h3_prompt_source": "prompt_master_director",
                "reference_urls": [str(slot.get("image_url") or "").strip()
                                   for slot in part.get("reference_slots", plan.get("reference_slots") or [])
                                   if str(slot.get("image_url") or "").strip()] if plan.get("schema_version") in {5, 6} else reference_urls,
                "duration_sec": float(segment.get("duration_seconds") or 8),
                "duration_seconds": float(segment.get("duration_seconds") or 8),
                "frame_count": int(segment.get("frame_count") or 192),
                "planned_frame_count": int(segment["frame_count"]) if plan.get("schema_version") in {5, 6} else None,
                "continuity": {"partId": part_id, "segmentId": segment.get("id")},
                "continuity_from_prev": sequence > 1 and not part_boundary and render_scope == "episode",
                "part_boundary": part_boundary,
                "director_part_id": part_id,
                "source_beat_ids": segment.get("source_beat_ids") or [],
            })
            if part.get("render_mode") == "shot":
                # Isolated shot routes need the shared subject definition in
                # the segment itself; continuous Director routes send it as
                # global_prompt and keep the H3 body independent.
                prefix = "subject_definitions" if plan.get("language") == "en" else "主体定义"
                shots[-1]["prompt"] = f"{prefix}: {common_prompt}\n\n" + shots[-1]["prompt"]
                shots[-1]["h3_prompt"] = shots[-1]["prompt"]
            previous_part_id = part_id
        if render_scope == "selection":
            shots[0]["continuity_from_prev"] = False
            for index in range(1, len(shots)):
                shots[index]["continuity_from_prev"] = True
        return shots, plan, render_scope

    @classmethod
    def generate_episode_videos(
        cls,
        project_id: str,
        episode_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        incoming = dict(options or {})
        from . import workshop_contract as workshop
        unified_detail = ProjectDetailService.get_episode_detail(project_id, episode_id) if "expected_revision" in incoming else {}
        if workshop.unified(unified_detail):
            plan = workshop.plan_of(unified_detail)
            from .workshop_references import assert_reference_snapshot
            assert_reference_snapshot(plan, incoming)
            if incoming.get("expected_revision") != plan["revision"]:
                raise ValueError("VERSION_CONFLICT: 提示词或规划已变化，请刷新")
            requested = incoming.get("beat_ids")
            groups = [[bid] for bid in requested] if requested and len(requested) == 1 else [
                g["beat_ids"] for g in plan["groups"] if not requested or set(g["beat_ids"]).issubset(set(requested))]
            if requested and set(requested) != {bid for ids in groups for bid in ids}:
                raise ValueError("请选择完整镜头组或单镜头")
            from .production_state import summary
            adopted = summary(unified_detail)["adopted"]
            jobs, blocked, skipped = [], [], 0
            for ids in groups:
                if not requested and not incoming.get("force") and all(b in adopted for b in ids):
                    skipped += 1
                    continue
                try:
                    created = cls.create_job(project_id, episode_id, beat_ids=ids, render_scope="selection",
                        options={**incoming, "workflow": plan["workflow_id"], "render_scope": "selection"})
                    jobs.append(created["job_id"])
                except ValueError as err:
                    blocked.append({"beat_ids": ids, "reason": str(err)})
            if not jobs and blocked:
                reasons = {}
                for item in blocked:
                    reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
                raise ValueError("没有可提交的镜头组：" + "；".join(f"{count} 组：{reason}" for reason, count in reasons.items()))
            return {"job_ids": jobs, "job_id": jobs[0] if jobs else "", "submitted": len(jobs), "skipped": skipped, "blocked": blocked, "status": "queued" if jobs else "completed"}
        beat_ids = cls._requested_beat_ids(incoming)
        force = bool(incoming.pop("force", False)) or bool(beat_ids)
        incoming.pop("beat_ids", None)
        settings = cls.resolve_generation_options(incoming)
        workflow_id = str(settings.get("workflow") or cls.DEFAULTS["workflow"])
        definition = workflow_for(workflow_id)
        if definition.prompt_profile == "director_segments":
            if beat_ids is not None:
                raise ValueError("Director 工作流不再按原 Beat 选择，请选择 Director 出片方案中的段")
            render_scope = str(incoming.get("render_scope") or "episode")
            detail = ProjectDetailService.get_episode_detail(project_id, episode_id) if render_scope == "episode" else None
            plan = ((detail or {}).get("prompt_authoring") or {}).get("director_plan") or {}
            if render_scope == "episode" and int(plan.get("schema_version") or 0) == 5:
                from .production_state import summary as production_summary
                from .director_plan_quality import assert_ready_for_video
                if plan.get("status") != "current":
                    raise ValueError("Director 出片方案已过期，请更新制作方案")
                state = production_summary(detail, mode="director")
                adopted = state["adopted"]
                materials = {m["id"]: m for m in state["materials"] if m.get("verified")}
                active_parts = {str(cls._job_payload(row).get("part_id") or "")
                                for row in cls._active_video_jobs(project_id, episode_id)}
                job_ids, skipped, blocked = [], 0, []
                for part in plan.get("parts") or []:
                    segment_ids = [s["id"] for s in part.get("segments") or []]
                    if (part["id"] in active_parts or segment_ids and all(adopted.get(sid) in materials for sid in segment_ids)):
                        skipped += 1
                        continue
                    try:
                        assert_ready_for_video(plan, str(part.get("source_group_id") or part["id"]))
                        created = cls.create_job(project_id, episode_id, render_scope="selection",
                            options={**incoming, "render_scope": "selection", "part_id": part["id"],
                                     "segment_ids": segment_ids, "director_plan_revision": plan.get("revision")})
                        job_ids.append(created["job_id"])
                    except ValueError as err:
                        blocked.append({"part_id": part["id"], "reason": str(err)})
                if not job_ids:
                    if blocked:
                        raise ValueError("没有可提交的生成组：" + "；".join(f"{item['part_id']} {item['reason']}" for item in blocked))
                    raise ValueError("全部生成组已完成或正在队列中；可在方案内单独重做指定组")
                return {"job_id": job_ids[0], "job_ids": job_ids, "status": "queued",
                        "render_scope": "episode", "render_mode": "episode",
                        "submitted": len(job_ids), "skipped": skipped, "blocked": blocked,
                        "shot_count": sum(len(p.get("segments") or []) for p in plan.get("parts") or [])}
            created = cls.create_job(
                project_id,
                episode_id,
                render_scope=render_scope,
                options=incoming,
            )
            return {
                **created,
                "render_mode": "episode",
                "job_ids": [created["job_id"]],
                "submitted": 1,
                "shot_count": created.get("shot_count") or 1,
                "skipped": 0,
            }
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
        cls._persist_shot_looks(project_id, episode_id, shots)
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
        from .production_state import summary as production_summary
        adopted = production_summary(detail, mode="shot")["adopted"]
        for shot in shots:
            beat_id = str(shot.get("beat_id") or "")
            beat = beats_by_id.get(beat_id) or {}
            if skip_existing and beat_id in adopted:
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
        try:
            scale = vsr_scale_from_options(incoming)
        except ValueError as err:
            raise ValueError(str(err)) from err
        incoming.pop("scale", None)
        incoming.pop("upscale_scale", None)
        settings = {**cls.DEFAULTS, **cls.resolve_generation_options(incoming)}
        settings["upscale_scale"] = scale
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
        scale_label = vsr_scale_label(scale)
        payload = {
            **settings,
            "model": f"RTX {scale_label} 超分",
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
            "upscale_scale": scale,
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
                f"{scale_label} 超分：第 {detail.get('number')} 集 Beat {sequence}",
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
            definition = workflow_for(workflow_id)
            model_name = definition.name
        except KeyError:
            definition = None
            model_name = "MiniMax H3"
        director_prompt_profile = bool(definition and definition.prompt_profile == "director_segments")

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

        if director_prompt_profile:
            render_scope = str((options or {}).get("render_scope") or render_scope or "episode")
        elif selected_ids:
            render_scope = "shot" if len(selected_ids) == 1 else "selection"
        elif render_mode == "shot":
            raise ValueError("逐镜工作流必须指定 Beat，请使用一键生成或「生成本镜」")
        else:
            render_scope = "episode"

        comfy_config = ComfyService.get_config()
        comfy = ComfyVideoClient(comfy_config.base_url)
        cls._assert_can_enqueue(
            project_id,
            episode_id,
            render_scope,
            beat_id=selected_ids[0] if len(selected_ids) == 1 else None,
            beat_ids=selected_ids or None,
        )

        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        assets = ProjectDetailService.list_assets(project_id)
        director_plan = None
        from . import workshop_contract as workshop
        if workshop.unified(detail):
            from .workshop_service import WorkshopService
            from .workshop_references import assert_reference_snapshot
            assert_reference_snapshot(workshop.plan_of(detail), options or {})
            if workflow_id != workshop.plan_of(detail)["workflow_id"]:
                raise ValueError("视频工作流与确认规划不一致，请先调整规划")
            current_source = WorkshopService.view(project_id, episode_id)
            if current_source["source_changed"]:
                raise ValueError("采纳剧本已更新，请先调整镜头规划")
            if (options or {}).get("expected_revision") != workshop.plan_of(detail)["revision"]:
                raise ValueError("VERSION_CONFLICT: 提示词版本已变化")
            shots, director_plan = workshop.execution_shots(detail, selected_ids or None)
            selected = {s["beat_id"] for s in shots}
            for active in cls._active_video_jobs(project_id, episode_id):
                snapshot = cls._job_payload(active)
                if selected.intersection(str(s.get("beat_id")) for s in snapshot.get("source_shots") or snapshot.get("shots") or []):
                    raise ValueError(f"所选镜头已有进行中的视频任务：{active['id']}")
            if len(director_plan["parts"]) != 1:
                raise ValueError("一次任务只提交一个镜头组，请使用本集批量入口")
            render_scope = "selection"
        elif director_prompt_profile:
            shots, director_plan, render_scope = cls._director_plan_shots(detail, options or {})
            if render_scope == "selection":
                requested_segments = {str(s.get("beat_id") or "") for s in shots}
                for row in cls._active_video_jobs(project_id, episode_id):
                    active_payload = cls._job_payload(row)
                    if (active_payload.get("director_plan_id") == director_plan.get("id")
                            and requested_segments.intersection(active_payload.get("segment_ids") or [])):
                        raise ValueError(f"该生成组已有进行中的视频任务：{row['id']}")
        else:
            shots = cls._prepare_shots(detail, assets, beat_ids=selected_ids or None)
            cls._persist_shot_looks(project_id, episode_id, shots)
            if cls._workshop_prompts_usable(shots) is None:
                raise ValueError("视频生成前置检查失败：存在缺失或过期的 H3 提示词，请先使用六段式模板生成并保存")
        if selected_ids and not shots:
            raise ValueError("指定的 Beat 不存在或无法生成视频")
        task_type = comfy.preflight(require_director=uses_director_timeline(workflow_id)
            and any(s.get("group_render_mode", "director") == "director" for s in shots))
        if options:
            settings["render_pass"] = str(options.get("render_pass") or "final")
        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        if director_prompt_profile and render_scope == "selection":
            scope_label = f"Director 选中 {len(shots)} 段"
        elif render_scope == "shot":
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
            "comfy_base_url": comfy_config.base_url,
            "task_type": task_type,
            "source_shots": shots,
            "shots": [],
            "render_plan": {"status": "queued", "chunks": [], "assembly": None},
        }
        if director_plan:
            payload.update({
                "pipeline_version": director_plan.get("schema_version", 4),
                "prompt_profile": "director_segments",
                "director_plan_id": director_plan.get("id"),
                "director_plan_revision": director_plan.get("revision"),
                "part_id": (options or {}).get("part_id"),
                "segment_ids": (options or {}).get("segment_ids") or [],
                "global_prompt": shots[0].get("global_prompt") or (director_plan.get("common_setting") or {}).get("subject_definitions") or "",
                "continuity_enabled": True,
                "prompt_source": "prompt_master_director",
            })
        from .production_service import ProductionService
        # Persist the exact source/plan identity before dispatch; workers never infer it later.
        if not director_prompt_profile:
            detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        payload["production_context"] = ProductionService.generation_context(
            detail, "director" if director_prompt_profile else "shot",
        )
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
        if options and "expected_revision" in options:
            return cls._create_production_export(project_id, episode_id, options)
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
    def _create_production_export(cls, project_id: str, episode_id: str, options: dict) -> dict:
        from .production_service import ProductionService
        cls._assert_can_enqueue(project_id, episode_id, "compose")
        snapshot = ProductionService.export_snapshot(project_id, episode_id, options)
        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        payload = {"project_id": project_id, "episode_id": episode_id, "render_scope": "compose",
                   "render_mode": "production", "target_type": "episode_video", "model": "ffmpeg production",
                   "production_snapshot": snapshot, "render_plan": {"status": "queued"}}
        execute_sql(
            "INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at) "
            "VALUES (%s,%s,'video_generation',%s,'queued',0,NULL,%s,%s,%s)",
            (jid, project_id, "导出本集采用版成片", json.dumps(payload, ensure_ascii=False), timestamp, timestamp),
        )
        _EXECUTOR.submit(cls._run_job, jid)
        return {"job_id": jid, "status": "queued", "render_scope": "compose", "render_mode": "production"}

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
    def _mark_source_job_upscaled(cls, source_job_id: str, upscaled_url: str, original_url: str, scale: int | None = None) -> None:
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
        if scale:
            payload["upscale_scale"] = int(scale)
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
        for shot in payload.get("shots") or []:
            if isinstance(shot, dict):
                beat_id = str(shot.get("beat_id") or "").strip()
                if beat_id:
                    ids.add(beat_id)
        return ids

    @staticmethod
    def _make_video_take_id(job_id: str = "", url: str = "", beat_id: str = "") -> str:
        job = str(job_id or "").strip()
        beat = str(beat_id or "").strip()
        if job and beat:
            return f"take-{job}-{beat}"
        if job:
            return f"take-{job}"
        digest = hashlib.sha1(f"{beat}|{url}".encode("utf-8")).hexdigest()[:12]
        return f"take-local-{digest}"

    @classmethod
    def _normalize_video_takes(cls, raw: Any) -> list[dict[str, Any]]:
        items = raw if isinstance(raw, list) else []
        takes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            scope = str(item.get("scope") or "shot").strip() or "shot"
            if scope not in _SHOT_TAKE_SCOPES:
                continue
            seen.add(url)
            take: dict[str, Any] = {
                "id": str(item.get("id") or "").strip() or cls._make_video_take_id(
                    str(item.get("job_id") or ""), url, str(item.get("beat_id") or ""),
                ),
                "job_id": str(item.get("job_id") or "").strip(),
                "url": url,
                "created_at": str(item.get("created_at") or "").strip(),
                "scope": scope,
            }
            upscaled = str(item.get("upscaled_url") or "").strip()
            if upscaled:
                take["upscaled_url"] = upscaled
            takes.append(take)
        return takes

    @classmethod
    def _archive_and_adopt_beat_video(
        cls,
        beat: dict[str, Any] | None,
        *,
        url: str,
        job_id: str = "",
        scope: str = "shot",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        url = str(url or "").strip()
        if not url:
            raise ValueError("成片地址为空")
        beat = beat if isinstance(beat, dict) else {}
        beat_id = str(beat.get("id") or beat.get("beat_id") or "").strip()
        takes = cls._normalize_video_takes(beat.get("video_takes"))
        old_url = str(beat.get("video_url") or "").strip()
        old_upscaled = str(beat.get("upscaled_video_url") or "").strip()
        existing_urls = {str(item.get("url") or "") for item in takes}
        take_scope = scope if scope in _SHOT_TAKE_SCOPES else "shot"
        if old_url and old_url not in existing_urls:
            archived = {
                "id": str(beat.get("video_take_id") or "").strip() or cls._make_video_take_id("", old_url, beat_id),
                "job_id": "",
                "url": old_url,
                "created_at": "",
                "scope": "shot",
            }
            if old_upscaled:
                archived["upscaled_url"] = old_upscaled
            takes.append(archived)
            existing_urls.add(old_url)
        take_id = cls._make_video_take_id(job_id, url, beat_id)
        if url not in existing_urls:
            takes.append({
                "id": take_id,
                "job_id": str(job_id or "").strip(),
                "url": url,
                "created_at": created_at or now_str(),
                "scope": take_scope,
            })
        else:
            for item in takes:
                if item.get("url") != url:
                    continue
                take_id = str(item.get("id") or take_id)
                if job_id and not item.get("job_id"):
                    item["job_id"] = str(job_id)
                if not item.get("created_at") and created_at:
                    item["created_at"] = created_at
                break
        return {
            "video_url": url,
            "upscaled_video_url": None,
            "video_take_id": take_id,
            "video_takes": takes,
            "render_status": "completed",
            "status": "completed",
        }

    @classmethod
    def _attach_upscaled_to_adopted_take(cls, beat: dict[str, Any] | None, upscaled_url: str, scale: int | None = None) -> dict[str, Any]:
        upscaled_url = str(upscaled_url or "").strip()
        beat = beat if isinstance(beat, dict) else {}
        takes = cls._normalize_video_takes(beat.get("video_takes"))
        adopted = str(beat.get("video_url") or "").strip()
        beat_id = str(beat.get("id") or beat.get("beat_id") or "").strip()
        if adopted:
            found = False
            for item in takes:
                if item.get("url") == adopted:
                    item["upscaled_url"] = upscaled_url
                    found = True
                    break
            if not found:
                take: dict[str, Any] = {
                    "id": str(beat.get("video_take_id") or "").strip() or cls._make_video_take_id("", adopted, beat_id),
                    "job_id": "",
                    "url": adopted,
                    "created_at": "",
                    "scope": "shot",
                }
                if upscaled_url:
                    take["upscaled_url"] = upscaled_url
                takes.append(take)
        return {
            "upscaled_video_url": upscaled_url,
            "video_takes": takes,
            **({"upscale_scale": int(scale)} if scale else {}),
        }

    @classmethod
    def _adopt_take_updates(cls, beat: dict[str, Any] | None, url: str, *, take_id: str = "") -> dict[str, Any]:
        url = str(url or "").strip()
        if not url:
            raise ValueError("成片地址为空")
        beat = beat if isinstance(beat, dict) else {}
        takes = cls._normalize_video_takes(beat.get("video_takes"))
        target = next((item for item in takes if item.get("url") == url), None)
        if target is None:
            target = {
                "id": str(take_id or beat.get("video_take_id") or "").strip()
                or cls._make_video_take_id("", url, str(beat.get("id") or "")),
                "job_id": "",
                "url": url,
                "created_at": "",
                "scope": "shot",
            }
            takes.append(target)
        elif take_id and not target.get("id"):
            target["id"] = take_id
        return {
            "video_url": url,
            "video_take_id": str(target.get("id") or take_id or ""),
            "upscaled_video_url": str(target.get("upscaled_url") or "").strip() or None,
            "video_takes": takes,
        }

    @classmethod
    def _shot_video_url_from_job(cls, row: dict[str, Any] | None, payload: dict[str, Any], beat_id: str) -> str:
        scope = str(payload.get("render_scope") or "")
        if scope in _EXCLUDED_TAKE_SCOPES:
            return ""
        wanted = str(beat_id or "").strip()
        if not wanted or wanted not in cls._job_beat_ids(payload):
            return ""
        shots = [item for item in (payload.get("shots") or []) if isinstance(item, dict)]
        for shot in shots:
            if str(shot.get("beat_id") or "") == wanted:
                url = str(shot.get("video_url") or "").strip()
                if url:
                    return url
        split = payload.get("shot_video_urls")
        if isinstance(split, list) and split:
            order: list[str] = []
            for key in ("shots", "source_shots"):
                ids = [
                    str(item.get("beat_id") or "").strip()
                    for item in (payload.get(key) or [])
                    if isinstance(item, dict) and str(item.get("beat_id") or "").strip()
                ]
                if wanted in ids:
                    order = ids
                    break
            if not order:
                order = [str(item).strip() for item in (payload.get("beat_ids") or []) if str(item or "").strip()]
            if wanted in order:
                index = order.index(wanted)
                if index < len(split):
                    return str(split[index] or "").strip()
        if len(cls._job_beat_ids(payload)) <= 1:
            return cls._original_video_url_from_job(row, payload)
        return ""

    @classmethod
    def _list_completed_video_jobs(cls, project_id: str) -> list[dict[str, Any]]:
        try:
            return query_all(
                """
                SELECT id, result_url, payload_json, created_at, updated_at, status
                FROM ai_project_jobs
                WHERE project_id = %s AND job_type = 'video_generation'
                  AND status IN ('completed', 'succeeded')
                ORDER BY created_at ASC
                LIMIT 200
                """,
                (project_id,),
            ) or []
        except Exception:
            return []

    @classmethod
    def collect_beat_video_takes(
        cls,
        beat: dict[str, Any] | None,
        jobs: list[dict[str, Any]] | None,
        episode_id: str,
    ) -> list[dict[str, Any]]:
        beat = beat if isinstance(beat, dict) else {}
        beat_id = str(beat.get("id") or beat.get("beat_id") or "").strip()
        episode = str(episode_id or "").strip()
        merged: dict[str, dict[str, Any]] = {}

        def upsert(take: dict[str, Any]) -> None:
            url = str(take.get("url") or "").strip()
            if not url:
                return
            current = merged.get(url)
            if current is None:
                merged[url] = take
                return
            created = str(take.get("created_at") or "")
            prev_created = str(current.get("created_at") or "")
            if created and (not prev_created or created < prev_created):
                current["created_at"] = created
            if take.get("job_id") and not current.get("job_id"):
                current["job_id"] = take.get("job_id")
            if take.get("id") and not current.get("id"):
                current["id"] = take.get("id")
            if take.get("upscaled_url"):
                current["upscaled_url"] = take.get("upscaled_url")
            if take.get("scope") and not current.get("scope"):
                current["scope"] = take.get("scope")

        for item in cls._normalize_video_takes(beat.get("video_takes")):
            upsert(item)
        adopted = str(beat.get("video_url") or "").strip()
        if adopted:
            upsert({
                "id": str(beat.get("video_take_id") or "").strip() or cls._make_video_take_id("", adopted, beat_id),
                "job_id": "",
                "url": adopted,
                "created_at": "",
                "scope": "shot",
                **({"upscaled_url": str(beat.get("upscaled_video_url") or "").strip()}
                   if str(beat.get("upscaled_video_url") or "").strip() else {}),
            })
        for row in jobs or []:
            payload = cls._job_payload(row)
            if str(payload.get("episode_id") or "") != episode:
                continue
            scope = str(payload.get("render_scope") or "")
            if scope == "upscale":
                source = str(payload.get("source_video_url") or "").strip()
                upscaled = str(payload.get("upscaled_video_url") or row.get("result_url") or "").strip()
                if source and upscaled and source in merged:
                    merged[source]["upscaled_url"] = upscaled
                continue
            if str(row.get("status") or "") not in _SUCCEEDED_VIDEO_STATUSES:
                continue
            if str(row.get("job_type") or "video_generation") != "video_generation":
                continue
            url = cls._shot_video_url_from_job(row, payload, beat_id)
            if not url:
                continue
            upsert({
                "id": cls._make_video_take_id(str(row.get("id") or ""), url, beat_id),
                "job_id": str(row.get("id") or ""),
                "url": url,
                "created_at": str(row.get("created_at") or ""),
                "scope": scope if scope in _SHOT_TAKE_SCOPES else "shot",
            })
        adopted_upscaled = str(beat.get("upscaled_video_url") or "").strip()
        if adopted and adopted_upscaled and adopted in merged and not merged[adopted].get("upscaled_url"):
            merged[adopted]["upscaled_url"] = adopted_upscaled
        takes = list(merged.values())
        takes.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("url") or "")))
        return takes

    @classmethod
    def _persist_shot_original_video(
        cls,
        project_id: str,
        episode_id: str,
        beat_id: str,
        url: str,
        *,
        job_id: str = "",
        scope: str = "shot",
        beat: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = dict(beat or {})
        if not snapshot:
            try:
                detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
                snapshot = next(
                    (item for item in (detail.get("beats") or []) if str(item.get("id") or "") == str(beat_id)),
                    {},
                ) or {}
            except Exception:
                snapshot = {}
        if "id" not in snapshot:
            snapshot["id"] = beat_id
        updates = cls._archive_and_adopt_beat_video(
            snapshot, url=url, job_id=job_id, scope=scope,
        )
        ProjectDetailService.update_episode_beat(project_id, episode_id, beat_id, updates)
        return updates

    @classmethod
    def adopt_beat_video_take(
        cls,
        project_id: str,
        episode_id: str,
        beat_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        url = str(body.get("url") or "").strip()
        job_id = str(body.get("job_id") or "").strip()
        if not url and not job_id:
            raise ValueError("请提供要采用的成片地址或任务 ID")
        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        beat = next((item for item in (detail.get("beats") or []) if str(item.get("id") or "") == str(beat_id)), None)
        if not beat:
            raise ValueError("分镜不存在")
        jobs = cls._list_completed_video_jobs(project_id)
        if job_id:
            row = next((item for item in jobs if str(item.get("id") or "") == job_id), None)
            if row is None:
                row = query_one(
                    """
                    SELECT id, result_url, payload_json, created_at, updated_at, status, job_type
                    FROM ai_project_jobs WHERE id = %s AND project_id = %s
                    """,
                    (job_id, project_id),
                )
            job_payload = cls._job_payload(row)
            if not row or str(row.get("job_type") or "video_generation") != "video_generation":
                raise ValueError("该任务没有本镜成功成片")
            if str(row.get("status") or "") not in _SUCCEEDED_VIDEO_STATUSES:
                raise ValueError("该任务没有本镜成功成片")
            if str(job_payload.get("episode_id") or "") != str(episode_id):
                raise ValueError("该成片不属于本镜的成功抽卡结果")
            resolved = cls._shot_video_url_from_job(row, job_payload, beat_id)
            if not resolved:
                raise ValueError("该任务没有本镜成功成片")
            if url and url != resolved:
                raise ValueError("该成片不属于本镜的成功抽卡结果")
            url = resolved
        candidates = cls.collect_beat_video_takes(beat, jobs, episode_id)
        target = next((item for item in candidates if item.get("url") == url), None)
        if target is None:
            raise ValueError("该成片不属于本镜的成功抽卡结果")
        updates = cls._adopt_take_updates(
            {**beat, "video_takes": candidates},
            url,
            take_id=str(target.get("id") or ""),
        )
        return ProjectDetailService.update_episode_beat(project_id, episode_id, beat_id, updates)

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
        episode = query_one("SELECT data_json FROM ai_project_episodes WHERE id=%s AND project_id=%s", (episode_id, project_id)) or {}
        episode_data = json.loads(episode.get("data_json") or "{}")
        if episode_data.get("script_stale"):
            raise ValueError("已采纳新剧本，请先重新规划镜头并同步至工坊")
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
        if row.get("status") not in {"failed", "completed", "succeeded", "cancelled"}:
            raise ValueError("只有失败或已完成的视频任务可以重试")
        payload = json.loads(row.get("payload_json") or "{}")
        if float((payload.get("execution_lease") or {}).get("expires_at") or 0) > time.time():
            raise ValueError("原视频执行器仍持有运行租约，请等待其完成或租约过期再重试")
        if payload.get("h3_confirmation") and row.get("status") in {"completed", "succeeded"}:
            raise ValueError("已完成的确认任务请新建预览或选择另一画质，不覆盖已有结果")
        frozen_shots = payload.get("shots")
        for key in (
            "shots", "llm_attempts", "prompt_generation_progress", "timeline", "workflow_request",
            "prompt_id", "client_id", "queue_number", "node_errors", "comfy_output",
            "director_report", "storage_warning", "failure_stage", "comfy_submission_count",
        ):
            payload.pop(key, None)
        payload["shots"] = []
        if payload.get("h3_confirmation", {}).get("stage") == "refine_only":
            payload["shots"] = frozen_shots or payload.get("source_shots") or []
            payload["confirmation_cancel_requested"] = False
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
              AND COALESCE(JSON_EXTRACT(payload_json,'$.execution_lease.expires_at'),0) <= %s
            """,
            (timestamp, time.time()),
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
        for beat in beats:
            apply_resolved_looks_to_beat(beat, assets)
        protagonist = cls._episode_protagonist(all_beats, assets)
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
            beat_characters = [
                by_id[str(asset_id)] for asset_id in (beat.get("character_ids") or [])
                if str(asset_id) in by_id and by_id[str(asset_id)].get("kind") == "character"
            ]
            character_references: list[dict[str, str]] = []
            for character in beat_characters:
                look = cls._select_character_look(character, beat)
                selected_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
                selected_look_id = str(selected_ids.get(str(character.get("id") or "")) or "").strip()
                if not look:
                    missing.append(missing_look_message(
                        character, beat, sequence, selected_look_id=selected_look_id,
                    ))
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
            prompt_authoring = detail.get("prompt_authoring") if isinstance(detail.get("prompt_authoring"), dict) else {}
            prompt_records = prompt_authoring.get("full_reference") if isinstance(prompt_authoring.get("full_reference"), dict) else {}
            prompt_record = prompt_records.get(str(beat.get("id") or ""))
            ref_images: list[dict[str, Any]] = []
            if isinstance(prompt_record, dict):
                for slot in prompt_record.get("reference_slots") or []:
                    url = str(slot.get("image_url") or "").strip()
                    if url:
                        ref_images.append({
                            "index": int(slot.get("index") or len(ref_images) + 1),
                            "url": url,
                            "name": str(slot.get("name") or "参考图"),
                            "asset_id": str(slot.get("asset_id") or ""),
                        })
                reference_state = str(prompt_record.get("status") or "stale")
                reference_reason = "六段式提示词已过期，请重新生成" if reference_state != "current" else ""
            else:
                fallback_refs: list[tuple[str, str, str]] = [
                    (item["url"], item["character_name"], item["character_id"])
                    for item in character_references if item.get("url")
                ]
                if scene_url:
                    fallback_refs.append((scene_url, str((scene or {}).get("name") or "场景"), str((scene or {}).get("id") or "")))
                for prop_id in beat.get("prop_ids") or []:
                    prop = by_id.get(str(prop_id)) or {}
                    extra = prop.get("extra") if isinstance(prop.get("extra"), dict) else {}
                    url = str(extra.get("reference_url") or extra.get("master_url") or prop.get("image_url") or "").strip()
                    if url:
                        fallback_refs.append((url, str(prop.get("name") or "道具"), str(prop.get("id") or "")))
                for index, (url, name, asset_id) in enumerate(fallback_refs[:9], start=1):
                    ref_images.append({"index": index, "url": url, "name": name, "asset_id": asset_id})
                explicit_state = str(beat.get("h3_prompt_reference_state") or "").strip()
                prompt_source = str(beat.get("h3_prompt_source") or "").strip()
                if explicit_state:
                    reference_state = explicit_state
                elif str(beat.get("h3_prompt") or "").strip() and prompt_source in {"generated", "legacy_generated"}:
                    reference_state = "legacy_stale"
                else:
                    reference_state = "manual" if beat.get("h3_prompt") else "missing"
                reference_reason = str(beat.get("h3_prompt_reference_reason") or "")
            reference_urls = [str(item.get("url") or "") for item in ref_images if item.get("url")]
            if str(beat.get("h3_prompt") or "").strip() and reference_state in {"stale", "legacy_stale", "invalid"}:
                missing.append(f"Beat {sequence} {reference_reason or '提示词已过期，请重新生成'}")
            if str(beat.get("h3_prompt") or "").strip() and reference_state == "manual":
                used_pictures = {
                    int(value)
                    for value in re.findall(r"<Picture\s+(\d+)>", str(beat.get("h3_prompt") or ""), flags=re.I)
                }
                invalid_pictures = sorted(value for value in used_pictures if value < 1 or value > len(reference_urls))
                if invalid_pictures:
                    missing.append(
                        f"Beat {sequence} 手写提示词引用了不存在的参考图：{invalid_pictures}"
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
                "skill_pack_id": "",
                "narration": str(beat.get("narration") or beat.get("voiceover") or "").strip(),
                "speaker": str(beat.get("speaker") or "").strip(),
                "characters": [item["character_name"] for item in character_references],
                "props": beat.get("props") or [],
                "scene": str(beat.get("scene") or (scene or {}).get("name") or ""),
                "scene_id": str((scene or {}).get("id") or beat.get("scene_id") or ""),
                "scene_description": str((scene or {}).get("description") or (scene or {}).get("visual_prompt") or ""),
                "character_id": str((protagonist or {}).get("id") or ""),
                "character_name": str((protagonist or {}).get("name") or ""),
                "character_look_id": next(
                    (item["look_id"] for item in character_references if item["character_id"] == str((protagonist or {}).get("id") or "")),
                    "",
                ),
                "character_description": next(
                    (item["description"] for item in character_references if item["character_id"] == str((protagonist or {}).get("id") or "")),
                    "",
                ),
                "visual_prompt": str(beat.get("visual_prompt") or "").strip(),
                "audio": str(beat.get("audio") or beat.get("soundscape") or "").strip(),
                "video_prompt_zh": str(beat.get("video_prompt_zh") or beat.get("timestamped_zh_prompt") or "").strip(),
                "timestamped_zh_prompt": str(beat.get("timestamped_zh_prompt") or "").strip(),
                "character_references": character_references,
                "scene_picture_index": None,
                "reference_urls": reference_urls,
                "ref_images": ref_images,
                "h3_reference_policy": "prompt_master_slots" if isinstance(prompt_record, dict) else "manual_fallback",
                "h3_prompt_context_fingerprint": (prompt_record or {}).get("source_fingerprint") or beat.get("h3_prompt_context_fingerprint") or "",
                "h3_prompt_reference_state": reference_state,
                "duration_sec": duration_seconds(beat),
                "duration_seconds": duration_seconds(beat),
                "frame_count": frame_count(beat),
                "continuity": {"sceneId": str((scene or {}).get("id") or beat.get("scene_id") or ""), "sequence": sequence},
            }
            shots.append(shot)
        if missing:
            raise ValueError("视频生成前置检查失败：\n" + "\n".join(f"- {item}" for item in missing))
        return shots

    @classmethod
    def _persist_shot_looks(cls, project_id: str, episode_id: str, shots: list[dict[str, Any]]) -> None:
        for shot in shots:
            look_ids = {
                str(item.get("character_id") or ""): str(item.get("look_id") or "")
                for item in (shot.get("character_references") or [])
                if str(item.get("character_id") or "") and str(item.get("look_id") or "")
            }
            beat_id = str(shot.get("beat_id") or "")
            if look_ids and beat_id:
                ProjectDetailService._update_episode_beat_atomic(
                    project_id,
                    episode_id,
                    beat_id,
                    {"character_look_ids": look_ids},
                )

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
        return select_character_look(character, beat)

    @classmethod
    def _workshop_prompt_for_shot(cls, shot: dict[str, Any]) -> str | None:
        saved = str(shot.get("h3_prompt") or "").strip()
        if not saved:
            return None
        if str(shot.get("h3_prompt_reference_state") or "") in {"stale", "legacy_stale", "invalid"}:
            return None
        return saved

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
        stopped = threading.Event()
        _VIDEO_LEASE.owner = None
        try:
            row = query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}
            payload = json.loads(row.get("payload_json") or "{}")
            if payload.get("pipeline_version") == 5 or payload.get("workflow_id") == "minimax-h3-director-confirm-accel-r2v":
                owner = uuid.uuid4().hex
                payload["execution_lease"] = {"owner": owner, "expires_at": time.time() + 120}
                if execute_sql("UPDATE ai_project_jobs SET status='preparing',payload_json=%s WHERE id=%s AND status='queued'",
                               (json.dumps(payload, ensure_ascii=False), job_id)) != 1:
                    return
                _VIDEO_LEASE.owner = owner
                def heartbeat():
                    while not stopped.wait(30):
                        try:
                            execute_sql("UPDATE ai_project_jobs SET payload_json=JSON_SET(payload_json,'$.execution_lease.expires_at',%s) "
                                "WHERE id=%s AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.execution_lease.owner'))=%s",
                                (time.time() + 120, job_id, owner))
                        except Exception:
                            continue
                threading.Thread(target=heartbeat, name=f"video-heartbeat-{job_id}", daemon=True).start()
            if str(payload.get("render_scope") or "") == "compose":
                cls._run_compose_job(job_id, payload)
                return
            gpu_cm = occupy_gpu("comfy")
            gpu_cm.__enter__()
            if payload.get("h3_confirmation", {}).get("stage") == "refine_only":
                from .h3_confirmation_service import run_refinement
                run_refinement(cls, job_id, payload)
                return
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
            source_shots = payload.get("source_shots") or []
            task_type = comfy.preflight(require_director=timeline_job
                and any(s.get("group_render_mode", "director") == "director" for s in source_shots))

            payload["prompt_generation_progress"] = {"completed": 0, "total": len(source_shots)}
            saved_prompts = cls._workshop_prompts_usable(source_shots)
            if saved_prompts is None:
                raise ValueError("视频任务不会自动调用大模型：请先在工坊生成并保存有效提示词")
            prompts = saved_prompts
            payload["prompt_source"] = payload.get("prompt_source") or "workshop_material"
            payload["prompt_generation_progress"]["completed"] = len(source_shots)

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
            if payload.get("production_context"):
                cls._auto_upscale_if_requested(job_id, payload, comfy, generated_shots)
                if payload.get("render_scope") == "episode":
                    from .production_service import ProductionService
                    ProductionService.record_export(payload, job_id, result_url, direct=True)
            elif payload.get("prompt_profile") == "director_segments" and payload.get("render_scope") == "selection":
                try:
                    cls._write_director_selection_result(payload, result_url, job_id)
                except Exception as selection_update_error:
                    payload["director_selection_update_warning"] = str(selection_update_error)
            elif payload.get("render_scope") in {"shot", "selection"} and generated_shots:
                try:
                    cls._write_selected_beat_videos(payload, generated_shots, result_url, job_id=job_id)
                except Exception as beat_update_error:
                    payload["beat_update_warning"] = str(beat_update_error)
                cls._auto_upscale_if_requested(job_id, payload, comfy, generated_shots)
            if payload.get("render_scope") == "episode" and not payload.get("production_context"):
                try:
                    cls._write_episode_video(
                        payload["project_id"],
                        payload["episode_id"],
                        url=result_url,
                        source="director_plan" if payload.get("prompt_profile") == "director_segments" else "director_direct",
                        job_id=job_id,
                    )
                except Exception as episode_update_error:
                    payload["episode_update_warning"] = str(episode_update_error)
            timestamp = now_str()
            payload.pop("execution_lease", None)
            _video_write(
                """
                UPDATE ai_project_jobs SET status = 'completed', progress = 100, result_url = %s,
                  payload_json = %s, error_message = NULL, completed_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (result_url, json.dumps(payload, ensure_ascii=False), timestamp, timestamp, job_id),
            )
        except Exception as err:
            timestamp = now_str()
            if str(err).startswith("H3_CONFIRMATION_CANCELLED:"):
                _video_write("UPDATE ai_project_jobs SET status='cancelled',error_message=%s,updated_at=%s,"
                    "payload_json=JSON_REMOVE(payload_json,'$.execution_lease') WHERE id=%s",
                    (str(err), timestamp, job_id))
                return
            try:
                row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}
                failed_payload = json.loads(row.get("payload_json") or "{}")
                failed_payload["failure_stage"] = failed_payload.get("runtime_stage") or "unknown"
                if isinstance(failed_payload.get("render_plan"), dict):
                    failed_payload["render_plan"]["status"] = "failed"
                failed_payload.pop("execution_lease", None)
                _video_write(
                    """
                    UPDATE ai_project_jobs SET status = 'failed', progress = 0, error_message = %s,
                      payload_json = %s, updated_at = %s WHERE id = %s
                    """,
                    (str(err)[:4000], json.dumps(failed_payload, ensure_ascii=False), timestamp, job_id),
                )
            except Exception:
                _video_write(
                    "UPDATE ai_project_jobs SET status = 'failed', progress = 0, error_message = %s, updated_at = %s WHERE id = %s",
                    (str(err)[:4000], timestamp, job_id),
                )
        finally:
            stopped.set()
            _VIDEO_LEASE.owner = None
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
                } | ({k: v for k, v in previous_chunks[tuple(str(shot.get("beat_id")) for shot in chunk)].items()
                      if k in {"output", "production_recorded", "timeline", "director_report", "render_request", "workflow_snapshot", "execution_parameters", "workflow_id", "render_mode"}}
                     if tuple(str(shot.get("beat_id")) for shot in chunk) in previous_chunks
                     and previous_chunks[tuple(str(shot.get("beat_id")) for shot in chunk)].get("output") else {})
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
            if chunk[0].get("group_render_mode") == "shot":
                shot = chunk[0]
                if len(chunk) != 1:
                    raise ValueError("逐镜生成组必须只包含一个段")
                route = shot["group_workflow_id"]
                workflow = comfy.build_shot_workflow(route, shot["prompt"], shot.get("uploaded_refs") or [],
                    f"video/{payload['project_id']}/{payload['episode_id']}/{job_id}/group-{index + 1}",
                    options={**payload, **shot.get("group_options", {}), "duration": shot["duration_sec"]})
                timeline = None
                render_request = {"workflowId": route, "renderMode": "shot"}
            else:
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
                    options={**payload, **chunk[0].get("group_options", {})},
                    workflow_id=str(chunk[0].get("group_workflow_id") or resolved_workflow_id),
                )
            payload["render_plan"]["chunks"][index]["timeline"] = timeline
            route = chunk[0].get("group_workflow_id") or resolved_workflow_id
            route_definition = workflow_for(route)
            properties = ((route_definition.option_schema or H3_STANDARD_OPTION_SCHEMA).get("properties") or {})
            effective = {**payload, **chunk[0].get("group_options", {}), "duration": chunk[0]["duration_sec"]}
            payload["render_plan"]["chunks"][index].update({
                "workflow_id": route, "render_mode": chunk[0].get("group_render_mode", "director"),
                "workflow_snapshot": workflow,
                "execution_parameters": normalize_options(route, {k: v for k, v in effective.items() if k in properties}),
            })
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
            if payload.get("production_context") and payload.get("render_scope") != "selection":
                cls._record_production_output(payload, job_id, chunk, output, comfy)
                payload["render_plan"]["chunks"][index]["production_recorded"] = True
                cls._set_state(job_id, payload, "running", 95)

        if payload.get("production_context") and payload.get("render_scope") != "selection":
            for index, (chunk, output) in enumerate(zip(chunks, chunk_outputs)):
                if not payload["render_plan"]["chunks"][index].get("production_recorded"):
                    cls._record_production_output(payload, job_id, chunk, output, comfy)
                    payload["render_plan"]["chunks"][index]["production_recorded"] = True
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
        if payload.get("production_context") and payload.get("render_scope") == "selection":
            # A continuous selection is one candidate, even when the renderer used several chunks.
            cls._record_production_output(payload, job_id, generated_shots, chunk_outputs[0], comfy,
                                          url=result_url, content=merged if len(chunk_outputs) > 1 else None)
        if payload.get("h3_confirmation"):
            from .production_media import measure
            payload["output_media_info"] = measure(merged, []) if len(chunk_outputs) > 1 else payload["h3_confirmation"]["groups"][0].get("media_info")
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
            if payload.get("production_context"):
                shot["video_url"] = result_url
                cls._record_production_output(payload, job_id, [shot], output, comfy, url=result_url)
            elif len(generated_shots) > 1:
                try:
                    updates = cls._persist_shot_original_video(
                        payload["project_id"],
                        payload["episode_id"],
                        str(shot.get("beat_id")),
                        result_url,
                        job_id=job_id,
                        scope=str(payload.get("render_scope") or "shot"),
                    )
                    shot["video_url"] = result_url
                    shot["video_takes"] = updates.get("video_takes")
                    shot["video_take_id"] = updates.get("video_take_id")
                except Exception as beat_update_error:
                    payload["beat_update_warning"] = str(beat_update_error)
            cls._set_state(job_id, payload, "running", 95)
        return result_url

    @classmethod
    def _run_compose_job(cls, job_id: str, payload: dict[str, Any]) -> None:
        if payload.get("production_snapshot"):
            cls._run_production_export(job_id, payload)
            return
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
    def _record_production_output(cls, payload, job_id, shots, output, comfy, url=None, content=None):
        from .production_service import ProductionService
        from .production_media import measure
        content = content if content is not None else comfy.download_output(output)
        # Match the frame counts actually submitted by the timeline compiler, not draft durations.
        submitted = {}
        reports = []
        for chunk in (payload.get("render_plan") or {}).get("chunks", []):
            for segment in (chunk.get("timeline") or {}).get("segments", []):
                submitted[str(segment.get("shotId") or "")] = int(segment.get("frameCount") or 0)
            if chunk.get("director_report"):
                reports.append(chunk["director_report"])
        for checkpoint in payload.get("confirmation_checkpoints", {}).values():
            graph = checkpoint.get("graph") or {}
            timeline = json.loads(graph.get("12", {}).get("inputs", {}).get("timeline_data") or "{}")
            for segment, count in zip(timeline.get("segments") or [], checkpoint.get("frame_counts") or []):
                if segment.get("shotId"):
                    submitted[str(segment["shotId"])] = int(count)
        measured = measure(content, [{**s, "frame_count": submitted.get(str(s["beat_id"]), s.get("frame_count"))} for s in shots])
        measured["submitted_frames"] = [submitted.get(str(s["beat_id"]), s.get("frame_count")) for s in shots]
        measured["director_report"] = "\n".join(reports)
        if not url:
            if QiniuService.get_config().available:
                _, url = QiniuService.store_bytes("video", output["filename"], content)
            else:
                url = comfy.view_url(output)
        ProductionService.record_output(payload, job_id, shots, url, measured)

    @classmethod
    def _run_production_export(cls, job_id, payload):
        from .production_media import assemble
        from .production_service import ProductionService
        cls._set_state(job_id, payload, "assembling", 10)
        content = assemble(payload["production_snapshot"], cls._fetch_mix_audio, cls._fetch_mix_audio,
                           lambda done, total: cls._set_state(job_id, payload, "assembling", 10 + done * 75 // total))
        if not QiniuService.get_config().available:
            raise RuntimeError("请配置七牛云后导出成片")
        _, url = QiniuService.store_bytes("video", f"production-{job_id}.mp4", content)
        ProductionService.record_export(payload, job_id, url)
        payload["render_plan"] = {"status": "succeeded", "assembly": {"status": "succeeded"}}
        payload["result_kind"] = "episode_video"
        timestamp = now_str()
        execute_sql("UPDATE ai_project_jobs SET status='completed',progress=100,result_url=%s,payload_json=%s,"
                    "error_message=NULL,completed_at=%s,updated_at=%s WHERE id=%s",
                    (url, json.dumps(payload, ensure_ascii=False), timestamp, timestamp, job_id))

    @classmethod
    def _write_selected_beat_videos(
        cls,
        payload: dict[str, Any],
        shots: list[dict[str, Any]],
        result_url: str,
        job_id: str = "",
    ) -> None:
        project_id = str(payload.get("project_id") or "")
        episode_id = str(payload.get("episode_id") or "")
        scope = str(payload.get("render_scope") or "shot")
        if not shots:
            return
        beats_by_id: dict[str, dict[str, Any]] = {}
        try:
            detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
            beats_by_id = {
                str(item.get("id") or ""): item
                for item in (detail.get("beats") or [])
                if isinstance(item, dict) and item.get("id")
            }
        except Exception:
            beats_by_id = {}

        def persist(shot: dict[str, Any], url: str) -> None:
            beat_id = str(shot.get("beat_id") or "")
            updates = cls._persist_shot_original_video(
                project_id,
                episode_id,
                beat_id,
                url,
                job_id=job_id,
                scope=scope,
                beat=beats_by_id.get(beat_id),
            )
            shot["video_url"] = url
            shot["video_takes"] = updates.get("video_takes")
            shot["video_take_id"] = updates.get("video_take_id")
            current = beats_by_id.get(beat_id)
            if current is not None:
                current.update(updates)

        if len(shots) == 1:
            persist(shots[0], result_url)
            return
        if all(str(shot.get("video_url") or "").strip() for shot in shots):
            split_urls = [str(shot.get("video_url") or "").strip() for shot in shots]
            for shot, url in zip(shots, split_urls):
                persist(shot, url)
            payload["shot_video_urls"] = split_urls
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
            persist(shot, url)
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

    @classmethod
    def _write_director_selection_result(
        cls,
        payload: dict[str, Any],
        result_url: str,
        job_id: str,
    ) -> None:
        project_id = str(payload.get("project_id") or "")
        episode_id = str(payload.get("episode_id") or "")
        revision = int(payload.get("director_plan_revision") or 0)
        part_id = str(payload.get("part_id") or "")
        segment_ids = [str(item) for item in payload.get("segment_ids") or []]
        timestamp = now_str()
        with transaction_cursor() as cursor:
            cursor.execute(
                "SELECT data_json FROM ai_project_episodes WHERE id=%s AND project_id=%s FOR UPDATE",
                (episode_id, project_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("分集不存在")
            try:
                data = json.loads(row.get("data_json") or "{}")
            except (TypeError, json.JSONDecodeError) as err:
                raise ValueError("分集数据格式无效") from err
            authoring = data.get("prompt_authoring") if isinstance(data.get("prompt_authoring"), dict) else {}
            plan = authoring.get("director_plan") if isinstance(authoring.get("director_plan"), dict) else None
            if not plan or int(plan.get("revision") or 0) != revision:
                raise ValueError("Director 方案已更新，当前局部生成结果未自动绑定")
            part = next((item for item in plan.get("parts") or [] if str(item.get("id") or "") == part_id), None)
            if not part:
                raise ValueError("Director Part 不存在")
            renders = part.get("renders") if isinstance(part.get("renders"), list) else []
            renders.append({"job_id": job_id, "segment_ids": segment_ids, "url": result_url, "created_at": timestamp})
            part["renders"] = renders[-20:]
            if len(segment_ids) == 1:
                segment = next((item for item in part.get("segments") or [] if str(item.get("id") or "") == segment_ids[0]), None)
                if segment:
                    segment["video_url"] = result_url
                    segment["video_job_id"] = job_id
            cursor.execute(
                "UPDATE ai_project_episodes SET data_json=%s,updated_at=%s WHERE id=%s AND project_id=%s",
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
        from ...minimax_h3_confirm_workflow import is_confirmation_graph, execution_report, confirmation_state
        confirming = is_confirmation_graph(workflow)
        if confirming:
            from ..provider_bridge import comfy_row
            if comfy.base_url.rstrip("/") != str(comfy_row()["base_url"]).rstrip("/"):
                raise ValueError("ComfyUI 实例已切换，请恢复原实例")
            checkpoints = payload.setdefault("confirmation_checkpoints", {})
            prior = checkpoints.get(str(submission_index))
            if prior:
                workflow = prior["graph"]
                if prior.get("output") and prior.get("report"):
                    history = {"outputs": {"12": {"zly_h3_confirmation": [prior["report"]]},
                                           "7": {"images": [prior["output"]]}}}
                    execution_report(workflow, history)
                    if not prior.get("media_info"):
                        from .production_media import measure
                        prior["media_info"] = measure(comfy.download_output(prior["output"]), [])
                    if prior["report"]["stage"] == "preview_only":
                        groups = [v for _, v in sorted(checkpoints.items(), key=lambda x: int(x[0])) if v.get("report")]
                        payload["h3_confirmation"] = confirmation_state(groups, comfy.base_url)
                        payload["output_media_info"] = prior["media_info"]
                    cls._set_state(job_id, payload, "running", 95)
                    return history, prior["output"]
            else:
                checkpoints[str(submission_index)] = {"graph": workflow}
            cls._set_state(job_id, payload, "preparing", 0)

        def on_progress(value: int) -> None:
            cls._set_state(job_id, payload, "running", value)

        def on_submitted(submitted: dict[str, Any]) -> None:
            if confirming:
                payload["confirmation_checkpoints"][str(submission_index)]["submitted"] = submitted
            payload["comfy_submission_count"] = submission_index
            payload.update({
                "client_id": submitted["client_id"],
                "prompt_id": submitted["prompt_id"],
                "queue_number": submitted.get("number"),
                "node_errors": submitted.get("node_errors") or {},
            })
            cls._set_state(job_id, payload, "comfy_queued", 5)

        def cancelled():
            row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
            return bool(json.loads(row.get("payload_json") or "{}").get("confirmation_cancel_requested"))

        cancellation = {"is_cancelled": cancelled} if payload.get("h3_confirmation", {}).get("stage") == "refine_only" else {}
        submitted = payload.get("confirmation_checkpoints", {}).get(str(submission_index), {}).get("submitted") if confirming else None
        if submitted:
            response = comfy.session.get(f"{comfy.base_url}/history/{submitted['prompt_id']}", timeout=comfy.timeout)
            response.raise_for_status()
            previous = response.json().get(submitted["prompt_id"])
            if previous and (previous.get("status") or {}).get("status_str") in {"error", "failed"}:
                submitted = None
            elif not previous:
                response = comfy.session.get(f"{comfy.base_url}/queue", timeout=comfy.timeout)
                response.raise_for_status()
                active = [r[1] for kind in ("queue_running", "queue_pending") for r in response.json().get(kind, [])]
                if submitted["prompt_id"] not in active:
                    raise ValueError("远端执行记录已丢失；原片保留，请重新生成一采预览")
        if submitted:
            # Recover the exact prompt after a backend restart; no new GPU submission.
            history, output = comfy.wait_for_result(submitted["prompt_id"], client_id=submitted["client_id"],
                workflow=workflow, progress=on_progress, **cancellation)
        else:
            _submitted, history, output = comfy.submit_and_wait(
                workflow, progress=on_progress, on_submitted=on_submitted, **cancellation)
        if confirming:
            report = execution_report(workflow, history)
            output = comfy._find_video((history.get("outputs") or {}).get("7", {}))
            if not output:
                raise ValueError("确认工作流缺少保存的视频")
            checkpoint = payload["confirmation_checkpoints"][str(submission_index)]
            checkpoint.update(report=report, output=output)
            from ...minimax_h3_confirm_workflow import executed_segment_frames
            checkpoint["frame_counts"] = executed_segment_frames(history, report["segment_count"])
            # Save stage evidence before media inspection so a storage failure is recoverable.
            cls._set_state(job_id, payload, "running", 94)
            from .production_media import measure
            checkpoint["media_info"] = measure(comfy.download_output(output), [])
            if report["stage"] == "preview_only":
                groups = [v for _, v in sorted(payload["confirmation_checkpoints"].items(), key=lambda x: int(x[0])) if v.get("report")]
                payload["h3_confirmation"] = confirmation_state(groups, comfy.base_url)
                payload["output_media_info"] = checkpoint["media_info"]
            cls._set_state(job_id, payload, "running", 95)
        from ...minimax_h3_director_refine_workflow import is_refine_graph, RECIPE_VERSION
        if is_refine_graph(workflow):
            payload["recipe_version"] = RECIPE_VERSION
            payload["workflow_request"] = workflow
            # Node identity, never history order, determines the adopted output.
            output = comfy._find_video((history.get("outputs") or {}).get("7", {}))
            if not output:
                raise RuntimeError("二采工作流缺少主输出节点 7")
            variants = []
            for node, label in [("7", "二采成片" if "38" in workflow else "一采原片"), ("20", "一采原片")]:
                if node not in workflow:
                    continue
                media = comfy._find_video((history.get("outputs") or {}).get(node, {}))
                if not media:
                    raise RuntimeError(f"二采工作流缺少输出节点 {node}")
                url = comfy.view_url(media)
                from .production_media import measure
                content = comfy.download_output(media)
                measured = measure(content, [])
                if QiniuService.get_config().available:
                    _, url = QiniuService.store_bytes("video", media["filename"], content)
                variants.append({"node_id": node, "label": label, "url": url, "comfy_output": media,
                                 "submission_index": submission_index, "media_info": measured})
                if node == "7":
                    payload["output_media_info"] = measured
            payload["refine_outputs"] = [item for item in payload.get("refine_outputs", [])
                if item.get("submission_index") != submission_index] + variants
        return history, output

    @staticmethod
    def _set_state(job_id: str, payload: dict[str, Any], status: str, progress: int) -> None:
        payload["runtime_stage"] = status
        if getattr(_VIDEO_LEASE, "owner", None):
            payload["execution_lease"] = {"owner": _VIDEO_LEASE.owner, "expires_at": time.time() + 120}
        payload_sql = ("JSON_SET(%s,'$.confirmation_cancel_requested',"
                       "CASE WHEN JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.confirmation_cancel_requested')) "
                       "IN ('true','1') THEN 1 ELSE 0 END)"
                       if payload.get("h3_confirmation", {}).get("stage") == "refine_only" else "%s")
        _video_write(
            f"UPDATE ai_project_jobs SET status = %s, progress = %s, payload_json = {payload_sql}, updated_at = %s WHERE id = %s",
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
        return vsr_memory_rejection(
            *shape,
            scale=vsr_scale_from_options(options),
            vram_total=vram_total,
            device_name=device_name,
        )

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
            scale=vsr_scale_from_options(payload),
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
                if payload.get("production_context"):
                    from .production_media import measure
                    from .production_service import ProductionService
                    scale = vsr_scale_from_options(payload)
                    measured = measure(cls._fetch_mix_audio(upscaled_url), [shot])
                    measured.update(variant=f"vsr-{scale}", title=f"{scale}x 超分候选")
                    ProductionService.record_output(payload, job_id, [shot], upscaled_url, measured)
                    shot["upscaled_video_url"] = upscaled_url
                    upscaled_urls.append(upscaled_url)
                    continue
                beat_like = {
                    "id": beat_id,
                    "video_url": source_url,
                    "video_takes": shot.get("video_takes") or [],
                    "video_take_id": shot.get("video_take_id"),
                }
                scale = vsr_scale_from_options(payload)
                updates = cls._attach_upscaled_to_adopted_take(beat_like, upscaled_url, scale)
                ProjectDetailService.update_episode_beat(
                    str(payload.get("project_id") or ""),
                    str(payload.get("episode_id") or ""),
                    beat_id,
                    updates,
                )
                shot["upscaled_video_url"] = upscaled_url
                shot["video_takes"] = updates.get("video_takes")
                upscaled_urls.append(upscaled_url)
            except Exception as error:
                warnings.append(f"Beat {shot.get('sequence') or beat_id}: {error}")
        if upscaled_urls:
            payload["upscaled_video_url"] = upscaled_urls[0] if len(upscaled_urls) == 1 else None
            payload["upscaled_video_urls"] = upscaled_urls
            payload["source_video_url"] = str(shots[0].get("video_url") or payload.get("source_video_url") or "")
            payload["upscale_scale"] = vsr_scale_from_options(payload)
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
            beat_like: dict[str, Any] = {
                "id": beat_id,
                "video_url": source_url,
                "video_takes": shot.get("video_takes") or [],
                "video_take_id": shot.get("video_take_id"),
            }
            try:
                detail = ProjectDetailService.get_episode_detail(
                    str(payload.get("project_id") or ""),
                    str(payload.get("episode_id") or ""),
                )
                live = next(
                    (item for item in (detail.get("beats") or []) if str(item.get("id") or "") == beat_id),
                    None,
                )
                if isinstance(live, dict):
                    beat_like = live
                    if not beat_like.get("video_url"):
                        beat_like = {**live, "video_url": source_url}
            except Exception:
                pass
            updates = cls._attach_upscaled_to_adopted_take(beat_like, upscaled_url, vsr_scale_from_options(payload))
            ProjectDetailService.update_episode_beat(
                str(payload.get("project_id") or ""),
                str(payload.get("episode_id") or ""),
                beat_id,
                updates,
            )
        payload["upscaled_video_url"] = upscaled_url
        payload["upscaled_video_urls"] = [upscaled_url]
        payload["source_video_url"] = source_url
        payload["upscale_scale"] = vsr_scale_from_options(payload)
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
        cls._mark_source_job_upscaled(
            str(payload.get("source_job_id") or ""),
            upscaled_url,
            source_url,
            vsr_scale_from_options(payload),
        )

    @staticmethod
    def _director_report(outputs: dict[str, Any]) -> str:
        node = outputs.get("8") or {}
        values = node.get("text") or node.get("string") or []
        if isinstance(values, list):
            return "\n".join(str(value) for value in values)
        return str(values or "")
