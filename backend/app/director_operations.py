from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .director_catalog import find_art_style
from .director_jobs import create_queued_job, render_recipe_shots, revert_orphaned_shot_submissions
from .director_project_service import persist_recipe_execution
from .director_recipe import (
    AGENT_IDS,
    PAYLOAD_KIND_RECIPE,
    PAYLOAD_KIND_REPLICATION,
    normalize_recipe_payload,
    payload_kind,
)
from .director_replication import (
    find_replication_shot,
    new_replication_shot_id,
    normalize_replication_payload,
    save_replication_artifact,
    save_replication_depth,
)
from .director_stream import DirectorOperationEventBus, terminal_event_for_status
from .llm_client import LlmError
from .storage import DirectorProjectConflictError, JobStore


class DirectorOperationCancelled(RuntimeError):
    pass


class DirectorOperationService:
    """Durable coordinator for long LLM preparation work.

    ComfyUI jobs remain owned by JobWorker; this service only makes the LLM
    preparation lifecycle durable and observable.
    """

    def __init__(
        self,
        store: JobStore,
        *,
        llm_provider: Any,
        worker: Any,
        resource_storage: Any | None,
    ) -> None:
        self.store = store
        self.llm_provider = llm_provider
        self.worker = worker
        self.resource_storage = resource_storage
        self.events = DirectorOperationEventBus()
        self._agent_snapshots: dict[str, dict[str, tuple[str, str]]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping = False

    def start(self, operation_id: str) -> None:
        task = asyncio.create_task(self._run(operation_id), name=f"director-operation:{operation_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def stop(self) -> None:
        self._stopping = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.events.close()

    def _emit(self, operation_id: str, event: dict[str, Any]) -> None:
        self.events.emit(operation_id, event)

    def _emit_status(self, operation_id: str, status: str, progress: int | None = None) -> None:
        data: dict[str, Any] = {"status": status}
        if progress is not None:
            data["progress"] = progress
        self._emit(operation_id, {"event": "status", "data": data})

    def _emit_agent_events(self, operation_id: str, current: dict[str, Any]) -> None:
        """Diff agentStatus against the last snapshot and emit changes."""
        snapshot = self._agent_snapshots.get(operation_id) or {}
        latest: dict[str, tuple[str, str]] = {}
        for item in current.get("agentStatus") or []:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("id") or "")
            if not agent_id:
                continue
            status = str(item.get("status") or "")
            message = str(item.get("message") or item.get("error") or "")
            latest[agent_id] = (status, message)
            if snapshot.get(agent_id) == (status, message):
                continue
            self._emit(operation_id, {
                "event": "agent",
                "data": {"id": agent_id, "status": status, "message": message},
            })
        if latest or operation_id in self._agent_snapshots:
            self._agent_snapshots[operation_id] = latest

    def _check_cancelled(self, operation_id: str) -> None:
        operation = self.store.get_director_operation(operation_id)
        if self._stopping or operation.get("cancel_requested") or operation.get("status") in {
            "cancelled", "interrupted", "failed", "succeeded",
        }:
            raise DirectorOperationCancelled("操作已由用户取消")

    async def _run(self, operation_id: str) -> None:
        operation: dict[str, Any] | None = None
        try:
            operation = self.store.update_director_operation(
                operation_id, status="running", progress=1, error=None, update_error=True,
            )
            self._emit_status(operation_id, "running", 1)
            self._check_cancelled(operation_id)
            if operation["kind"] == "plan_pipeline":
                result = await self._run_plan(operation)
            elif operation["kind"] == "plan_clarify":
                result = await self._run_clarify(operation)
            elif operation["kind"] == "shot_render_prepare":
                result = await self._run_render(operation)
            elif operation["kind"] == "analyze_reference_video":
                result = await self._run_analyze_reference(operation)
            elif operation["kind"] == "replicate_shots":
                result = await self._run_replicate(operation)
            else:
                raise ValueError(f"不支持的导演操作：{operation['kind']}")
            self._check_cancelled(operation_id)
            self.store.update_director_operation(
                operation_id,
                status="succeeded",
                progress=100,
                result=result,
                error=None,
                update_error=True,
            )
            self._emit(operation_id, terminal_event_for_status("succeeded", result=result))
        except DirectorOperationCancelled as error:
            if operation is not None:
                self._revert_orphaned_render_submissions(operation)
            self.store.update_director_operation(
                operation_id, status="cancelled", error=str(error), update_error=True,
            )
            self._emit(operation_id, terminal_event_for_status("cancelled", message=str(error)))
        except asyncio.CancelledError:
            try:
                if operation is not None:
                    self._revert_orphaned_render_submissions(operation)
                self.store.update_director_operation(
                    operation_id,
                    status="interrupted",
                    error="服务停止，操作已中断；不会自动重试，以避免重复计费，请手动重试。",
                    update_error=True,
                )
            finally:
                self._emit(
                    operation_id,
                    terminal_event_for_status("interrupted", message="服务停止，操作已中断"),
                )
                raise
        except Exception as error:
            if operation is not None:
                self._revert_orphaned_render_submissions(operation)
            self.store.update_director_operation(
                operation_id, status="failed", error=str(error), update_error=True,
            )
            self._emit(operation_id, terminal_event_for_status("failed", message=str(error)))
        finally:
            self._agent_snapshots.pop(operation_id, None)

    def _revert_orphaned_render_submissions(self, operation: dict[str, Any]) -> None:
        if operation.get("kind") != "shot_render_prepare":
            return
        request = operation.get("request") or {}
        shot_ids = [str(item) for item in (request.get("shot_ids") or []) if str(item)]
        record = self.store.get_director_project(operation["project_id"])
        recipe = revert_orphaned_shot_submissions(record["payload"], shot_ids=shot_ids or None)
        persist_recipe_execution(
            self.store,
            operation["project_id"],
            recipe,
            scope="render",
            shot_ids=shot_ids or None,
        )

    async def _run_clarify(self, operation: dict[str, Any]) -> dict[str, Any]:
        operation_id = operation["id"]
        request = operation.get("request") or {}
        goal = str(request.get("goal") or "").strip()
        if not goal:
            raise ValueError("请先填写创意简报")

        def stream_event(event: dict[str, Any]) -> None:
            self._emit(operation_id, event)

        questions = await asyncio.to_thread(
            self.llm_provider.run_director_clarify, goal, on_stream=stream_event,
        )
        return {"questions": questions}

    async def _run_plan(self, operation: dict[str, Any]) -> dict[str, Any]:
        operation_id = operation["id"]
        request = operation.get("request") or {}
        record = self.store.get_director_project(operation["project_id"])
        if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
            raise ValueError("只有 Recipe 工程可以生成创作方案")
        goal = str(
            request.get("goal")
            or record.get("source_script")
            or ((record.get("payload") or {}).get("script") or {}).get("fullStory")
            or record.get("title")
            or ""
        ).strip()
        if not goal:
            raise ValueError("请先填写创作目标或完整故事")
        art_style_id = request.get("art_style_id")
        if art_style_id and find_art_style(str(art_style_id)) is None:
            raise ValueError("画风必须选自目录")
        requested_agents = request.get("agents")
        agents = None
        if isinstance(requested_agents, list) and requested_agents:
            unknown = [str(item) for item in requested_agents if str(item) not in AGENT_IDS]
            if unknown:
                raise ValueError(f"未知 Agent：{', '.join(unknown)}")
            agents = [str(item) for item in requested_agents]

        recipe = normalize_recipe_payload(record["payload"])
        expected_content_revision = int(record["content_revision"])
        total = max(1, len(agents or AGENT_IDS))

        def persist(current: dict[str, Any]) -> None:
            nonlocal expected_content_revision
            self._check_cancelled(operation_id)
            statuses = current.get("agentStatus") or []
            completed = sum(
                1 for item in statuses
                if isinstance(item, dict)
                and item.get("id") in (agents or AGENT_IDS)
                and item.get("status") in {"completed", "failed"}
            )
            saved = self.store.update_director_project(
                record["id"],
                title=((current.get("script") or {}).get("title") or record["title"]),
                summary=((current.get("script") or {}).get("summary") or record["summary"]),
                source_script=goal,
                payload=current,
                expected_content_revision=expected_content_revision,
                content_update=True,
            )
            expected_content_revision = int(saved["content_revision"])
            progress = min(95, 5 + int(completed / total * 90))
            self.store.update_director_operation(
                operation_id,
                progress=progress,
                result={"project_revision": saved["revision"]},
            )
            self._emit_status(operation_id, "running", progress)
            self._emit_agent_events(operation_id, current)

        def stream_event(event: dict[str, Any]) -> None:
            self._emit(operation_id, event)

        updated = await asyncio.to_thread(
            self.llm_provider.run_director_recipe,
            recipe,
            goal=goal,
            art_style_id=art_style_id,
            agents=agents,
            skip_research=request.get("skip_research"),
            on_progress=persist,
            on_stream=stream_event,
            clarifications=request.get("clarifications"),
        )
        persist(updated)
        saved = self.store.get_director_project(record["id"])
        selected_agents = agents or list(AGENT_IDS)
        failed_agents = [
            str(item.get("id"))
            for item in (updated.get("agentStatus") or [])
            if isinstance(item, dict)
            and item.get("id") in selected_agents
            and item.get("status") == "failed"
        ]
        return {
            "project_revision": saved["revision"],
            "content_revision": saved["content_revision"],
            "failed_agents": failed_agents,
        }

    async def _run_render(self, operation: dict[str, Any]) -> dict[str, Any]:
        operation_id = operation["id"]
        request = operation.get("request") or {}
        record = self.store.get_director_project(operation["project_id"])
        if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
            raise ValueError("只有 Recipe 工程可以提交分镜")
        shot_ids = [str(item) for item in (request.get("shot_ids") or []) if str(item)]
        render_pass = "preview" if request.get("render_pass") == "preview" else "final"
        polish_prompt = request.get("polish_prompt", True) is not False
        llm_available, llm_reason = self.llm_provider.availability() if polish_prompt else (False, "已关闭提示词润色")
        if polish_prompt and not llm_available:
            raise LlmError(f"提示词润色不可用：{llm_reason}。请配置大模型服务，或关闭提示词润色后重试。")

        latest_revision = record["revision"]

        def persist(current: dict[str, Any]) -> None:
            nonlocal latest_revision
            self._check_cancelled(operation_id)
            saved = persist_recipe_execution(
                self.store,
                record["id"],
                current,
                scope="render",
                shot_ids=shot_ids,
            )
            latest_revision = saved["revision"]
            self.store.update_director_operation(
                operation_id,
                progress=20,
                result={"project_revision": latest_revision},
            )
            self._emit_status(operation_id, "running", 20)
            self._emit_agent_events(operation_id, current)

        def persist_message(message: str) -> None:
            self._check_cancelled(operation_id)
            self.store.update_director_operation(
                operation_id,
                result={"project_revision": latest_revision, "message": message},
            )
            self._emit(operation_id, {"event": "status", "data": {"status": "running", "message": message}})

        recipe, job_ids = await asyncio.to_thread(
            render_recipe_shots,
            self.store,
            owner_user_id=operation["owner_user_id"],
            recipe=record["payload"],
            shot_ids=shot_ids,
            render_pass=render_pass,
            resource_storage=self.resource_storage,
            h3_prompt_refiner=(
                self.llm_provider.polish_director_h3_prompt
                if polish_prompt and llm_available
                else None
            ),
            on_progress=persist,
            on_message=persist_message,
        )
        saved = persist_recipe_execution(
            self.store, record["id"], recipe, scope="render", shot_ids=shot_ids,
        )
        for job_id in job_ids:
            self._check_cancelled(operation_id)
            await self.worker.enqueue(job_id)
        return {"job_ids": job_ids, "project_revision": saved["revision"]}

    def _cancel_requested(self, operation_id: str) -> bool:
        try:
            operation = self.store.get_director_operation(operation_id)
        except KeyError:
            return True
        return self._stopping or bool(operation.get("cancel_requested")) or operation.get("status") in {
            "cancelled", "interrupted", "failed", "succeeded",
        }

    async def _run_analyze_reference(self, operation: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._analyze_reference_thread, operation)

    def _analyze_reference_thread(self, operation: dict[str, Any]) -> dict[str, Any]:
        """拉片分析：分镜切分 → 全片深度提取 → 逐镜切段/关键帧/视觉反推。"""
        import base64
        import math
        import secrets
        import tempfile
        from datetime import datetime, timezone

        from .video_analysis import (
            VideoAnalysisError,
            cut_segment,
            detect_scenes,
            extract_keyframes,
            fixed_segments,
            probe_video,
        )

        operation_id = operation["id"]
        request = operation.get("request") or {}
        record = self.store.get_director_project(operation["project_id"])
        if payload_kind(record.get("payload")) != PAYLOAD_KIND_REPLICATION:
            raise ValueError("只有复刻工程可以执行拉片分析")
        payload = normalize_replication_payload(record["payload"])
        owner_user_id = operation["owner_user_id"]
        project_id = operation["project_id"]
        content_revision = int(record["content_revision"])
        comfy = getattr(self.worker, "comfy", None)
        if comfy is None:
            raise ValueError("ComfyUI 服务未就绪，无法提取深度视频")

        def persist(current: dict[str, Any], *, progress: int | None = None, message: str | None = None) -> None:
            nonlocal content_revision
            self._check_cancelled(operation_id)
            saved = self.store.update_director_project(
                project_id, payload=current,
                expected_content_revision=content_revision, content_update=True,
            )
            content_revision = int(saved["content_revision"])
            if progress is not None:
                self.store.update_director_operation(operation_id, progress=progress)
                data: dict[str, Any] = {"status": "running", "progress": progress}
                if message:
                    data["message"] = message
                self._emit(operation_id, {"event": "status", "data": data})

        analysis = payload["analysis"]
        mode = "fixed" if str(request.get("analysis_mode") or "") == "fixed" else "smart"
        segment_seconds = float(request.get("segment_seconds") or analysis.get("segmentSeconds") or 15)
        threshold = float(request.get("scene_threshold") or analysis.get("sceneThreshold") or 0.35)
        art_style = str((payload.get("renderSettings") or {}).get("artStyle") or "")
        vision_model = self.llm_provider.vision_model_name() if hasattr(self.llm_provider, "vision_model_name") else None

        source_info = payload.get("sourceVideo") or {}
        source_path = Path(str(source_info.get("path") or ""))
        if not source_path.is_file():
            from .director_replication import find_replication_source_file

            fallback = find_replication_source_file(owner_user_id, project_id)
            if fallback is None:
                raise ValueError("请先上传参考片再开始拉片分析")
            source_path = fallback

        analysis.update({"status": "running", "mode": mode, "error": None, "visionModel": vision_model})
        payload["shots"] = []
        payload["subjects"] = []
        persist(payload, progress=3, message="正在读取参考片")

        probe = probe_video(source_path)
        payload["sourceVideo"] = {
            "path": str(source_path),
            "url": f"/api/director/replications/{project_id}/source",
            "name": str(source_info.get("name") or source_path.name),
            "width": probe.width,
            "height": probe.height,
            "fps": round(probe.fps, 3),
            "durationSec": round(probe.duration, 3),
        }
        persist(payload, progress=6, message=f"参考片 {probe.width}×{probe.height}，{probe.duration:.1f} 秒")

        if mode == "fixed":
            segments = fixed_segments(probe.duration, segment_seconds)
        else:
            try:
                segments = detect_scenes(
                    source_path, threshold=threshold, min_duration=1.0, max_duration=20.0,
                )
            except VideoAnalysisError:
                segments = fixed_segments(probe.duration, segment_seconds)
        if not segments:
            raise ValueError("未能从参考片中切分出任何镜头")
        persist(payload, progress=10, message=f"检测到 {len(segments)} 个镜头")

        analysis["depthStatus"] = "running"
        persist(payload, progress=12, message="正在提取全片深度视频")
        fps = 16
        frame_cap = int(math.ceil(probe.duration * fps)) + 2
        try:
            depth_resource = comfy.run_depth_extraction(
                str(source_path), fps=fps, frame_cap=frame_cap,
                update_stage=lambda stage, _progress: self._emit(
                    operation_id, {"event": "status", "data": {"status": "running", "message": stage}},
                ),
                is_cancelled=lambda: self._cancel_requested(operation_id),
            )
        except Exception as error:
            from .comfy_service import ComfyCancelled

            if isinstance(error, ComfyCancelled):
                raise DirectorOperationCancelled("操作已由用户取消") from error
            analysis["depthStatus"] = "failed"
            persist(payload)
            raise ValueError(f"深度视频提取失败：{error}") from error
        depth_path, depth_url = save_replication_depth(
            owner_user_id, project_id, source=Path(depth_resource.local_path),
        )
        analysis["depthStatus"] = "done"
        analysis["depthPath"] = str(depth_path)
        analysis["depthUrl"] = depth_url
        persist(payload, progress=40, message="深度视频已就绪")

        subjects: dict[str, dict[str, Any]] = {}
        shots: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="zly-replication-") as workdir:
            workdir_path = Path(workdir)
            for index, segment in enumerate(segments, 1):
                self._check_cancelled(operation_id)
                shot_id = new_replication_shot_id()
                message = f"正在分析第 {index}/{len(segments)} 镜"
                persist(payload, progress=40 + int(index / len(segments) * 50), message=message)

                segment_cut = cut_segment(
                    source_path, start=segment.start, end=segment.end,
                    dest=workdir_path / f"{shot_id}_segment.mp4",
                )
                segment_path, segment_url = save_replication_artifact(
                    owner_user_id, project_id, shot_id, "segment", source=segment_cut,
                )
                depth_cut = cut_segment(
                    depth_path, start=segment.start, end=segment.end,
                    dest=workdir_path / f"{shot_id}_depth.mp4",
                )
                shot_depth_path, shot_depth_url = save_replication_artifact(
                    owner_user_id, project_id, shot_id, "depth", source=depth_cut,
                )
                keyframe_times = [segment.start, segment.start + segment.duration * 0.5]
                keyframe_files = extract_keyframes(
                    source_path, times=keyframe_times, dest_dir=workdir_path, stem=f"{shot_id}_key",
                )
                keyframe_paths: list[str] = []
                keyframe_urls: list[str] = []
                for slot_index, keyframe in enumerate(keyframe_files[:2]):
                    slot = "key0" if slot_index == 0 else "key1"
                    saved_path, saved_url = save_replication_artifact(
                        owner_user_id, project_id, shot_id, slot, source=keyframe,
                    )
                    keyframe_paths.append(str(saved_path))
                    keyframe_urls.append(saved_url)

                note = None
                analysis_result: dict[str, Any] | None = None
                if vision_model:
                    frames = []
                    for path in keyframe_paths:
                        raw = Path(path).read_bytes()
                        frames.append("data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii"))
                    try:
                        analysis_result = self.llm_provider.analyze_video_shot(
                            frames=frames, shot_number=index,
                            duration_sec=segment.duration, art_style=art_style,
                        )
                    except LlmError as error:
                        note = f"AI 反推失败：{error}"
                else:
                    note = "未配置视觉模型，请手动填写提示词"

                prompt_text = ""
                description = ""
                camera_note = None
                if analysis_result:
                    prompt_text = str(analysis_result.get("promptText") or "").strip()
                    description = str(analysis_result.get("description") or "").strip()
                    camera_note = str(analysis_result.get("camera") or "").strip() or None
                    for item in analysis_result.get("subjects") or []:
                        if not isinstance(item, dict):
                            continue
                        name = str(item.get("name") or "").strip()
                        if not name:
                            continue
                        existing = subjects.get(name)
                        if existing is None:
                            existing = {
                                "id": f"rsub_{secrets.token_hex(4)}",
                                "name": name,
                                "type": str(item.get("type") or "prop"),
                                "description": str(item.get("description") or "").strip(),
                                "refPath": None,
                                "refUrl": None,
                                "shotIds": [shot_id],
                                "hidden": False,
                            }
                            subjects[name] = existing
                        else:
                            if shot_id not in existing["shotIds"]:
                                existing["shotIds"].append(shot_id)
                            if not existing.get("description") and item.get("description"):
                                existing["description"] = str(item.get("description")).strip()

                shots.append({
                    "id": shot_id,
                    "shotNumber": index,
                    "timeStart": round(segment.start, 3),
                    "timeEnd": round(segment.end, 3),
                    "durationSec": round(segment.duration, 3),
                    "segmentPath": str(segment_path),
                    "segmentUrl": segment_url,
                    "keyframePaths": keyframe_paths,
                    "keyframeUrls": keyframe_urls,
                    "depthPath": str(shot_depth_path),
                    "depthUrl": shot_depth_url,
                    "promptText": prompt_text,
                    "compiledPrompt": "",
                    "negativePrompt": "",
                    "subjectBindings": [],
                    "keepFirstFrame": bool((payload.get("renderSettings") or {}).get("keepFirstFrame", True)),
                    "status": "ready",
                    "jobId": None,
                    "progress": 0,
                    "error": None,
                    "analysisNote": description or note,
                    "cameraNote": camera_note,
                    "takes": [],
                })
                payload["shots"] = shots
                payload["subjects"] = list(subjects.values())
                del segment_cut, depth_cut

        analysis["status"] = "done"
        analysis["finishedAt"] = datetime.now(timezone.utc).isoformat()
        persist(payload, progress=96, message=f"拉片完成，共 {len(shots)} 个镜头")
        try:
            comfy.free_resources()
        except Exception:
            pass
        return {"shot_count": len(shots), "subject_count": len(payload["subjects"]), "depth_url": depth_url}

    async def _run_replicate(self, operation: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._replicate_thread, operation)

    def _replicate_thread(self, operation: dict[str, Any]) -> dict[str, Any]:
        """按镜头提交 Wan VACE 深度复刻任务（走既有排队/串行执行链路）。"""
        operation_id = operation["id"]
        request = operation.get("request") or {}
        record = self.store.get_director_project(operation["project_id"])
        if payload_kind(record.get("payload")) != PAYLOAD_KIND_REPLICATION:
            raise ValueError("只有复刻工程可以提交转绘任务")
        payload = normalize_replication_payload(record["payload"])
        owner_user_id = operation["owner_user_id"]
        project_id = operation["project_id"]
        content_revision = int(record["content_revision"])
        settings = payload.get("renderSettings") or {}
        engine = str(settings.get("engine") or "vace_depth")
        if engine != "vace_depth":
            raise ValueError(f"暂不支持的转绘引擎：{engine}")
        workflow_id = "wan21-vace-depth-v2v"
        source_video = payload.get("sourceVideo") or {}
        base_width = int(source_video.get("width") or 832)
        base_height = int(source_video.get("height") or 480)

        requested_ids = {str(item) for item in (request.get("shot_ids") or []) if str(item)}
        selected = [
            shot for shot in payload.get("shots") or []
            if (not requested_ids or shot.get("id") in requested_ids)
            and str(shot.get("promptText") or "").strip()
        ]
        if not selected:
            raise ValueError("没有可提交的镜头：请先填写镜头提示词")

        def persist(current: dict[str, Any], *, progress: int | None = None) -> None:
            nonlocal content_revision
            self._check_cancelled(operation_id)
            saved = self.store.update_director_project(
                project_id, payload=current,
                expected_content_revision=content_revision, content_update=True,
            )
            content_revision = int(saved["content_revision"])
            if progress is not None:
                self.store.update_director_operation(operation_id, progress=progress)
                self._emit_status(operation_id, "running", progress)

        job_ids: list[str] = []
        shots = payload.get("shots") or []
        for index, shot in enumerate(shots):
            if requested_ids and shot.get("id") not in requested_ids:
                continue
            if not str(shot.get("promptText") or "").strip():
                continue
            self._check_cancelled(operation_id)
            depth_path = shot.get("depthPath")
            if not depth_path or not Path(depth_path).is_file():
                raise ValueError(f"镜头 {shot.get('shotNumber')} 缺少深度视频，请重新执行拉片分析")
            references = [str(depth_path)]
            if shot.get("keepFirstFrame", True) and shot.get("keyframePaths"):
                references.append(str(shot["keyframePaths"][0]))
            art_style = str(settings.get("artStyle") or "").strip()
            prompt = str(shot.get("promptText")).strip()
            compiled = f"{art_style}. {prompt}" if art_style else prompt
            duration_sec = float(shot.get("durationSec") or 0)
            frames = min(81, max(5, int(round(duration_sec * 16)) + 1))
            job = create_queued_job(
                self.store,
                owner_user_id=owner_user_id,
                mode=workflow_id,
                prompt=compiled,
                options={
                    "vace_strength": float(settings.get("vaceStrength") or 1.0),
                    "keep_first_frame": bool(shot.get("keepFirstFrame", True)),
                    "steps": int(settings.get("steps") or 30),
                    "seed": int(settings.get("seed") or 0),
                    "width": base_width,
                    "height": base_height,
                    "length": frames,
                    "fps": 16,
                },
                references=references,
                title=f"复刻镜头 {shot.get('shotNumber')}",
            )
            shot["jobId"] = job["id"]
            shot["compiledPrompt"] = compiled
            shot["status"] = "queued"
            shot["progress"] = 0
            shot["error"] = None
            takes = [take for take in (shot.get("takes") or []) if isinstance(take, dict)]
            takes.append({
                "id": job["id"],
                "takeNumber": len(takes) + 1,
                "jobId": job["id"],
                "status": "queued",
                "progress": 0,
                "workflowId": workflow_id,
                "videoWorkflowFamily": "vace_depth",
                "promptSnapshot": compiled,
                "createdAt": operation.get("created_at"),
            })
            shot["takes"] = takes
            job_ids.append(job["id"])
            persist(payload, progress=10 + int((index + 1) / max(1, len(shots)) * 80))
        return {"job_ids": job_ids, "project_revision": record["revision"]}
