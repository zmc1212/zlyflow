from __future__ import annotations

import asyncio
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError

from fastapi import HTTPException

from .director_export import DirectorExportError, SystemFfmpegRunner
from .director_jobs import materialize_job_output_file
from .xiaji_asset_api import _enqueue_queued_job
from .xiaji_episode_api import (
    RenderRequest,
    SketchRequest,
    VideoPromptRequest,
    VideoRequest,
    _beat_can_make_video,
    _episodes,
    _hydrate_episode,
    _submit_render,
    _submit_sketch,
    _submit_video,
    generate_beat_video_prompt,
    previous_video_beat,
    store_beat_in_frame,
)
from .xiaji_episode_run_store import episode_runs_store

STEPS = ("sketch", "render", "bridge", "prompt", "video")


class XiajiAutoRunCancelled(RuntimeError):
    pass


class XiajiAutoRunFailed(RuntimeError):
    pass


def extract_last_frame_png(video_path: Path, dest: Path) -> None:
    runner = SystemFfmpegRunner()
    dest.parent.mkdir(parents=True, exist_ok=True)
    runner.run(
        [
            "-hide_banner",
            "-loglevel",
            "error",
            "-sseof",
            "-0.08",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(dest),
        ]
    )
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise XiajiAutoRunFailed("无法从上一镜视频抽出衔接帧")


class XiajiAutoPipeline:
    def __init__(
        self,
        app: Any,
        *,
        poll_interval: float = 2.0,
        wait_timeout: float = 30 * 60,
        extract_frame: Callable[[Path, Path], None] | None = None,
    ) -> None:
        self.app = app
        self.poll_interval = poll_interval
        self.wait_timeout = wait_timeout
        self.extract_frame = extract_frame or extract_last_frame_png
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping = False

    def start(self, run_id: str) -> None:
        task = asyncio.create_task(self._run(run_id), name=f"xiaji-auto-run:{run_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def stop(self) -> None:
        self._stopping = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def interrupt_stale(self) -> None:
        store = episode_runs_store(self.app)
        if store is not None:
            store.interrupt_stale()

    def _runs(self) -> Any:
        store = episode_runs_store(self.app)
        if store is None:
            raise XiajiAutoRunFailed("自动生成任务存储未启动")
        return store

    def _check_cancelled(self, run_id: str) -> None:
        if self._stopping:
            raise XiajiAutoRunCancelled("操作已中断")
        row = self._runs().get(run_id)
        if row is None:
            raise XiajiAutoRunCancelled("自动生成任务不存在")
        if row.get("cancel_requested") or row.get("status") in {"cancelled", "interrupted"}:
            raise XiajiAutoRunCancelled("自动生成已取消")

    async def _run(self, run_id: str) -> None:
        store = self._runs()
        try:
            store.update(run_id, status="running", progress=1, update_error=True, error=None)
            await self._execute(run_id)
            store.update(run_id, status="succeeded", progress=100, update_error=True, error=None)
        except XiajiAutoRunCancelled as error:
            store.update(run_id, status="cancelled", error=str(error), update_error=True)
        except asyncio.CancelledError:
            try:
                store.update(
                    run_id,
                    status="interrupted",
                    error="服务停止，自动生成已中断；不会自动重试，请重新添加任务。",
                    update_error=True,
                )
            finally:
                raise
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, str) else str(error.detail)
            store.update(run_id, status="failed", error=detail, update_error=True)
        except Exception as error:
            store.update(run_id, status="failed", error=str(error), update_error=True)

    async def _execute(self, run_id: str) -> None:
        row = self._runs().get(run_id)
        if row is None:
            raise XiajiAutoRunFailed("自动生成任务不存在")
        owner = str(row["owner_user_id"])
        episode_id = str(row["episode_id"])
        params = dict(row.get("video_params") or {})
        episode = self._load_episode(episode_id, owner)
        beats = [item for item in (episode.get("beats") or []) if _beat_can_make_video(item)]
        if not beats:
            raise XiajiAutoRunFailed("请先生成脚本")
        total = max(1, len(beats) * len(STEPS))
        done = 0
        for index, beat in enumerate(beats):
            for step in STEPS:
                self._check_cancelled(run_id)
                self._runs().update(
                    run_id,
                    cursor={
                        "beat_id": beat["id"],
                        "sequence": beat.get("sequence"),
                        "step": step,
                        "index": index + 1,
                        "total": len(beats),
                    },
                    progress=int((done / total) * 100),
                )
                episode = await self._run_step(run_id, episode, beat["id"], step, params, owner)
                beat = next(item for item in episode.get("beats") or [] if item["id"] == beat["id"])
                done += 1
                self._runs().update(run_id, progress=int((done / total) * 100))

    def _load_episode(self, episode_id: str, owner: str) -> dict[str, Any]:
        return _hydrate_episode(self.app, _episodes(self.app).get_episode(episode_id, owner), owner)

    def _beat(self, episode: dict[str, Any], beat_id: str) -> dict[str, Any]:
        beat = next((item for item in episode.get("beats") or [] if item["id"] == beat_id), None)
        if beat is None:
            raise XiajiAutoRunFailed("镜头不存在")
        return beat

    async def _run_step(
        self,
        run_id: str,
        episode: dict[str, Any],
        beat_id: str,
        step: str,
        params: dict[str, Any],
        owner: str,
    ) -> dict[str, Any]:
        beat = self._beat(episode, beat_id)
        scene_view = str(params.get("scene_view") or "front")
        if scene_view not in {"front", "reverse"}:
            scene_view = "front"
        if step == "sketch":
            if str(beat.get("sketch_url") or "").strip():
                return episode
            updated, job = _submit_sketch(
                self.app, owner, episode, beat, SketchRequest(force=False, scene_view=scene_view)
            )
            await self._enqueue(job)
            return await self._wait_url(
                run_id,
                episode["id"],
                owner,
                beat_id,
                url_key="sketch_url",
                status_key="status",
                error_key="error",
                label="草图",
            )
        if step == "render":
            if str(beat.get("render_url") or "").strip():
                return episode
            if not str(beat.get("sketch_url") or "").strip():
                raise XiajiAutoRunFailed("草图尚未落库，不能精绘")
            updated, job = _submit_render(
                self.app, owner, episode, beat, RenderRequest(force=False, scene_view=scene_view)
            )
            await self._enqueue(job)
            return await self._wait_url(
                run_id,
                episode["id"],
                owner,
                beat_id,
                url_key="render_url",
                status_key="render_status",
                error_key="render_error",
                label="精绘",
            )
        if step == "bridge":
            return await asyncio.to_thread(self._ensure_bridge, episode, beat_id, owner)
        if step == "prompt":
            if str(beat.get("video_prompt") or "").strip() and str(beat.get("video_prompt_zh") or "").strip():
                return episode
            if not str(beat.get("render_url") or "").strip():
                raise XiajiAutoRunFailed("精绘尚未落库，不能生成提示词")
            episode = self._load_episode(episode["id"], owner)
            beat = self._beat(episode, beat_id)
            result = await asyncio.to_thread(
                generate_beat_video_prompt,
                self.app,
                owner,
                episode,
                beat,
                VideoPromptRequest(
                    force=False,
                    family=str(params.get("family") or "") or None,
                    duration=params.get("duration"),
                    scene_view=scene_view,
                ),
            )
            fresh = result.get("episode") or self._load_episode(episode["id"], owner)
            current = self._beat(fresh, beat_id)
            if not str(current.get("video_prompt") or "").strip() or not str(current.get("video_prompt_zh") or "").strip():
                raise XiajiAutoRunFailed("提示词未写入镜头")
            return fresh
        if step == "video":
            if str(beat.get("video_url") or "").strip() and str(beat.get("video_status") or "") != "failed":
                return episode
            if not str(beat.get("video_prompt") or "").strip() or not str(beat.get("video_prompt_zh") or "").strip():
                raise XiajiAutoRunFailed("提示词尚未落库，不能生成视频")
            episode = self._load_episode(episode["id"], owner)
            beat = self._beat(episode, beat_id)
            payload = VideoRequest(
                force=False,
                family=str(params.get("family") or "") or None,
                duration=params.get("duration"),
                quality=str(params.get("quality") or "") or None,
                aspect_ratio=str(params.get("aspect_ratio") or "") or None,
                speed=str(params.get("speed") or "") or None,
                custom_steps=params.get("custom_steps"),
                scene_view=scene_view,
            )
            _updated, job = _submit_video(self.app, owner, episode, beat, payload)
            await self._enqueue(job)
            return await self._wait_url(
                run_id,
                episode["id"],
                owner,
                beat_id,
                url_key="video_url",
                status_key="video_status",
                error_key="video_error",
                label="视频",
            )
        return episode

    async def _enqueue(self, job: dict[str, Any] | None) -> None:
        if job is None:
            return
        worker = getattr(self.app.state, "worker", None)
        if worker is None:
            raise XiajiAutoRunFailed("任务执行器未启动")
        await _enqueue_queued_job(worker, job)

    async def _wait_url(
        self,
        run_id: str,
        episode_id: str,
        owner: str,
        beat_id: str,
        *,
        url_key: str,
        status_key: str,
        error_key: str,
        label: str,
    ) -> dict[str, Any]:
        elapsed = 0.0
        while elapsed <= self.wait_timeout:
            self._check_cancelled(run_id)
            episode = self._load_episode(episode_id, owner)
            beat = self._beat(episode, beat_id)
            url = str(beat.get(url_key) or "").strip()
            status = str(beat.get(status_key) or "")
            if url:
                return episode
            if status == "failed":
                raise XiajiAutoRunFailed(str(beat.get(error_key) or f"{label}生成失败"))
            await asyncio.sleep(self.poll_interval)
            elapsed += self.poll_interval
        raise XiajiAutoRunFailed(f"等待{label}超时")

    def _ensure_bridge(self, episode: dict[str, Any], beat_id: str, owner: str) -> dict[str, Any]:
        episode = self._load_episode(episode["id"], owner)
        beat = self._beat(episode, beat_id)
        previous = previous_video_beat(episode, beat)
        if previous is None:
            return episode
        previous_url = str(previous.get("video_url") or "").strip()
        if not previous_url:
            raise XiajiAutoRunFailed("请先生成上一镜视频")
        source_job = str(previous.get("video_job_id") or "").strip()
        existing = str(beat.get("video_in_frame_url") or "").strip()
        existing_source = str(beat.get("video_in_source_job_id") or "").strip()
        if existing and (not source_job or existing_source == source_job):
            return episode
        content = self._last_frame_bytes(previous)
        updated = store_beat_in_frame(
            self.app,
            owner,
            beat_id,
            content=content,
            filename=f"{beat_id}-in-frame.png",
            source_job_id=source_job or None,
            sec=None,
            manual=False,
        )
        fresh = _hydrate_episode(self.app, updated, owner)
        current = self._beat(fresh, beat_id)
        if not str(current.get("video_in_frame_url") or "").strip():
            raise XiajiAutoRunFailed("衔接帧未写入镜头")
        return fresh

    def _last_frame_bytes(self, previous: dict[str, Any]) -> bytes:
        job_id = str(previous.get("video_job_id") or "").strip()
        video_path: Path | None = None
        if job_id:
            try:
                job = self.app.state.store.get(job_id)
            except Exception:
                job = None
            video_path = materialize_job_output_file(
                job, resource_storage=getattr(self.app.state, "resource_storage", None), kind="video"
            )
        url = str(previous.get("video_url") or "").strip()
        with tempfile.TemporaryDirectory(prefix="xiaji-bridge-") as raw:
            work = Path(raw)
            source = video_path
            if source is None or not source.is_file():
                if not url:
                    raise XiajiAutoRunFailed("无法读取上一镜视频")
                downloaded = work / "source.mp4"
                try:
                    with urllib.request.urlopen(url, timeout=120) as response:
                        downloaded.write_bytes(response.read())
                except (OSError, URLError, TimeoutError, ValueError) as error:
                    raise XiajiAutoRunFailed(f"下载上一镜视频失败：{error}") from error
                source = downloaded
            dest = work / "last-frame.png"
            try:
                self.extract_frame(source, dest)
            except DirectorExportError as error:
                raise XiajiAutoRunFailed(str(error) or "未找到 ffmpeg，无法抽取衔接帧") from error
            if not dest.is_file():
                raise XiajiAutoRunFailed("无法从上一镜视频抽出衔接帧")
            return dest.read_bytes()
