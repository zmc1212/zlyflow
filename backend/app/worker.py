from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

from .comfy_service import ComfyCancelled, ComfyQueuePrompt, ComfyService, ComfyUnavailable
from .config import settings
from .grs_client import FAILED_STATUSES, SUCCESS_STATUSES, GrsClient, GrsError, GrsTemporaryError
from .grs_provider import GrsProviderService
from .models import JobMode, JobStatus
from .resource_storage import ResourceStorage
from .storage import JobStore
from .workflow_registry import grs_request_size, is_h3_workflow, is_image_workflow


class JobWorker:
    MAX_AUTO_RETRIES = 3
    WATCH_INTERVAL_SECONDS = 8
    STOP_TIMEOUT_SECONDS = 3

    def __init__(
        self, store: JobStore, comfy: ComfyService,
        grs_provider: GrsProviderService | None = None,
        resource_storage: ResourceStorage | None = None,
    ) -> None:
        self.store = store
        self.comfy = comfy
        self.grs_provider = grs_provider
        self.resource_storage = resource_storage
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.queued_job_ids: set[str] = set()
        self._auto_retries: dict[str, int] = {}
        self.task: asyncio.Task | None = None
        self.watch_task: asyncio.Task | None = None
        self.image_tasks: set[asyncio.Task] = set()
        self.image_semaphore = asyncio.Semaphore(max(1, min(4, settings.grs_max_concurrency)))

    async def start(self) -> None:
        recovered = await asyncio.to_thread(self.recover)
        self.task = asyncio.create_task(self.run(), name="zly-ai-video-studio-job-worker")
        self.watch_task = asyncio.create_task(self.watch_comfy(), name="zly-ai-video-studio-comfy-watch")
        for job_id in recovered:
            await self.enqueue(job_id)
        await self.release_comfy_resources_if_idle()
        if self.grs_provider is not None:
            for item in self.store.recoverable_generation_items("grs"):
                if item["status"] == JobStatus.RUNNING.value and not item.get("remote_task_id"):
                    self.store.update_generation(
                        item["id"], status=JobStatus.INTERRUPTED,
                        stage="提交后中断，需显式重试", error="未持久化 GRS 远端任务 ID；为避免重复扣费不会自动重提。",
                    )
                    continue
                self.enqueue_generation(item["id"])

    async def stop(self) -> None:
        tasks = [task for task in (self.watch_task, self.task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=self.STOP_TIMEOUT_SECONDS)
        image_tasks = list(self.image_tasks)
        for task in image_tasks:
            task.cancel()
        if image_tasks:
            await asyncio.wait(image_tasks, timeout=self.STOP_TIMEOUT_SECONDS)

    async def enqueue(self, job_id: str) -> None:
        job = self.store.get(job_id)
        items = job["rounds"][-1]["generation_items"]
        if items and items[0]["executor"] == "grs":
            for item in items:
                if item["status"] == JobStatus.QUEUED.value:
                    self.enqueue_generation(item["id"])
            return
        if job_id in self.queued_job_ids:
            return
        self.queued_job_ids.add(job_id)
        await self.queue.put(job_id)

    async def watch_comfy(self) -> None:
        while True:
            await asyncio.sleep(self.WATCH_INTERVAL_SECONDS)
            try:
                if not any(is_h3_workflow(job["mode"]) for job in self.store.with_statuses(
                    JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.INTERRUPTED,
                )):
                    continue
                recovered = await asyncio.to_thread(self.recover)
                for job_id in recovered:
                    await self.enqueue(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    def enqueue_generation(self, generation_item_id: str) -> None:
        task = asyncio.create_task(self.execute_image(generation_item_id), name=f"grs-image-{generation_item_id}")
        self.image_tasks.add(task)
        task.add_done_callback(self.image_tasks.discard)

    @staticmethod
    def created_at(job: dict) -> datetime | None:
        try:
            return datetime.fromisoformat(job["created_at"]).astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError):
            return None

    def reconnect_legacy_jobs(self, active_prompts: list[ComfyQueuePrompt]) -> None:
        candidates = [
            job for job in self.store.with_statuses(JobStatus.INTERRUPTED)
            if is_h3_workflow(job["mode"])
            and job.get("stage") == "应用已重启" and not job.get("comfy_prompt_id")
        ]
        prompts = [item for item in active_prompts if item.prompt and item.created_at]
        while candidates and prompts:
            matches = [
                (abs((created - prompt.created_at).total_seconds()), prompt, job)
                for prompt in prompts
                for job in candidates
                if job.get("prompt") == prompt.prompt
                and (created := self.created_at(job)) is not None
                and abs((created - prompt.created_at).total_seconds()) <= 15 * 60
            ]
            if not matches:
                return
            _, prompt, job = min(matches, key=lambda item: item[0])
            self.store.set_comfy_execution(job["id"], prompt.prompt_id, prompt.client_id, "generation")
            self.store.update(job["id"], stage="已重新连接 ComfyUI 队列")
            candidates.remove(job)
            prompts.remove(prompt)

    def _auto_requeue_lost_job(self, job_id: str) -> bool:
        count = self._auto_retries.get(job_id, 0)
        if count >= self.MAX_AUTO_RETRIES:
            self.store.update(
                job_id, status=JobStatus.INTERRUPTED,
                stage=f"已自动重试 {self.MAX_AUTO_RETRIES} 次仍未完成，请检查 ComfyUI 后手动重新提交",
            )
            return False
        self.store.update(job_id, status=JobStatus.INTERRUPTED, stage="ComfyUI 任务已丢失，正在自动重新提交")
        if not self.store.retry_terminal(job_id):
            return False
        self._auto_retries[job_id] = count + 1
        self.store.update(job_id, stage=f"ComfyUI 已恢复，正在自动重新提交（第 {count + 1} 次）")
        return True

    def recover(self) -> list[str]:
        active_prompts = self.comfy.active_prompts()
        active_jobs = self.store.with_statuses(JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.INTERRUPTED)
        supported_jobs = []
        for job in active_jobs:
            if is_h3_workflow(job["mode"]):
                supported_jobs.append(job)
                continue
            if is_image_workflow(job["mode"]):
                continue
            self.store.clear_comfy_execution(job["id"])
            self.store.update(
                job["id"], status=JobStatus.FAILED,
                stage="工作流已从当前工作台移除",
                error="该任务使用的旧工作流已下线，无法继续执行。",
            )
        if active_prompts is None:
            return [job["id"] for job in supported_jobs if job["status"] == JobStatus.QUEUED]

        self.reconnect_legacy_jobs(active_prompts)
        active_prompt_ids = {item.prompt_id for item in active_prompts}
        recovered: list[str] = []
        for snapshot in supported_jobs:
            job = self.store.get(snapshot["id"], include_references=True)
            if self.store.is_cancelled(job["id"]):
                continue
            if job["status"] == JobStatus.QUEUED:
                recovered.append(job["id"])
                continue
            if job["status"] not in {JobStatus.RUNNING.value, JobStatus.INTERRUPTED.value}:
                continue
            prompt_id = job.get("comfy_prompt_id")
            if not prompt_id:
                preparing = job["status"] == JobStatus.RUNNING.value and job["id"] in self.queued_job_ids
                if not preparing and self._auto_requeue_lost_job(job["id"]):
                    recovered.append(job["id"])
                continue
            state, _ = self.comfy.prompt_state(prompt_id, active_prompt_ids)
            if state in {"active", "completed"}:
                if job["status"] == JobStatus.INTERRUPTED.value:
                    self.store.update(job["id"], status=JobStatus.RUNNING, stage="正在恢复 ComfyUI 任务同步")
                recovered.append(job["id"])
            elif state == "failed":
                self.store.clear_comfy_execution(job["id"])
                self.store.update(job["id"], status=JobStatus.FAILED, stage="ComfyUI 推理失败", error="ComfyUI 已报告任务失败")
            elif state == "missing":
                self.store.clear_comfy_execution(job["id"])
                if self._auto_requeue_lost_job(job["id"]):
                    recovered.append(job["id"])
        return recovered

    async def run(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self.execute(job_id)
            finally:
                self.queued_job_ids.discard(job_id)
                self.queue.task_done()
                await self.release_comfy_resources_if_idle()

    async def release_comfy_resources_if_idle(self) -> None:
        """Ask ComfyUI to unload models after the last local video job.

        Consecutive queued H3 jobs keep models loaded. Image/GRS jobs do not
        occupy ComfyUI VRAM and are ignored here.
        """
        if not self.queue.empty() or self.queued_job_ids:
            return
        if any(is_h3_workflow(job["mode"]) for job in self.store.with_statuses(
            JobStatus.QUEUED, JobStatus.RUNNING,
        )):
            return
        free = getattr(self.comfy, "free_resources", None)
        if not callable(free):
            return
        try:
            await asyncio.to_thread(free)
        except Exception:
            return

    async def execute(self, job_id: str) -> None:
        job = self.store.get(job_id, include_references=True)
        if self.store.is_cancelled(job_id):
            return
        if job["status"] == JobStatus.QUEUED:
            self.store.update(job_id, status=JobStatus.RUNNING, stage="正在准备任务", progress=0)
            job = self.store.get(job_id, include_references=True)
        elif job["status"] == JobStatus.INTERRUPTED and job.get("comfy_prompt_id"):
            self.store.update(job_id, status=JobStatus.RUNNING, stage="正在恢复 ComfyUI 任务同步")
            job = self.store.get(job_id, include_references=True)
        if job["status"] != JobStatus.RUNNING:
            return

        def update_stage(stage: str, progress: int | None = None) -> None:
            self.store.update(job_id, stage=stage, progress=progress)

        def on_submitted(prompt_id: str, client_id: str, phase: str) -> None:
            self.store.set_comfy_execution(job_id, prompt_id, client_id, phase)
            if self.store.is_cancelled(job_id):
                self.comfy.stop_prompt(prompt_id)
                self.store.clear_comfy_execution(job_id)

        def save_partial_outputs(outputs: list[dict]) -> None:
            self.store.update(job_id, outputs=outputs)

        def is_cancelled() -> bool:
            return self.store.is_cancelled(job_id)

        try:
            if job.get("comfy_prompt_id"):
                outputs = await asyncio.to_thread(
                    self.comfy.resume,
                    JobMode(job["mode"]),
                    job["prompt"],
                    job["comfy_prompt_id"],
                    job.get("comfy_client_id"),
                    job.get("comfy_phase") or "generation",
                    job["outputs"],
                    update_stage,
                    on_submitted,
                    save_partial_outputs,
                    is_cancelled=is_cancelled,
                )
            else:
                outputs = await asyncio.to_thread(
                    self.comfy.run,
                    JobMode(job["mode"]),
                    job["references"],
                    job["prompt"],
                    job["negative_prompt"],
                    job["image_size"],
                    job["options"],
                    update_stage,
                    on_submitted,
                    save_partial_outputs,
                    is_cancelled=is_cancelled,
                )
            if self.store.is_cancelled(job_id):
                return
            self.store.clear_comfy_execution(job_id)
            self._auto_retries.pop(job_id, None)
            self.store.update(
                job_id, status=JobStatus.SUCCEEDED, stage="生成完成", progress=100, outputs=outputs,
                execution_elapsed_ms=self.comfy.last_execution_elapsed_ms,
            )
        except ComfyCancelled:
            if not self.store.is_cancelled(job_id):
                self.store.mark_cancelled(job_id)
            self.store.clear_comfy_execution(job_id)
        except ComfyUnavailable as error:
            if self.store.is_cancelled(job_id):
                self.store.clear_comfy_execution(job_id)
                return
            self.store.update(
                job_id,
                status=JobStatus.INTERRUPTED,
                stage="ComfyUI 连接中断，恢复后将自动重新提交",
                error=str(error),
            )
        except Exception as error:
            if self.store.is_cancelled(job_id):
                self.store.clear_comfy_execution(job_id)
                return
            self.store.clear_comfy_execution(job_id)
            self.store.update(job_id, status=JobStatus.FAILED, stage="生成失败", error=str(error), execution_elapsed_ms=self.comfy.last_execution_elapsed_ms)

    async def execute_image(self, generation_item_id: str) -> None:
        if self._generation_cancelled(generation_item_id):
            return
        if self.grs_provider is None or self.resource_storage is None:
            self.store.update_generation(
                generation_item_id, status=JobStatus.FAILED, stage="GRS 执行器不可用", error="服务器未初始化 GRS 执行器。",
            )
            return
        async with self.image_semaphore:
            if self._generation_cancelled(generation_item_id):
                return
            context = self.store.generation_context(generation_item_id)
            mode = context["mode"]
            available, reason = self.grs_provider.availability(mode)
            if not available:
                self.store.update_generation(
                    generation_item_id, status=JobStatus.FAILED, stage="GRS 配置不可用", error=reason or "GRS 不可用",
                )
                return
            client = self.grs_provider.client()
            remote_task_id = context.get("remote_task_id")
            try:
                if not remote_task_id:
                    self.store.update_generation(
                        generation_item_id, status=JobStatus.RUNNING, stage="正在提交 GRS", progress=5,
                    )
                    def reference_data_uris() -> list[str]:
                        uploads_root = settings.uploads_dir.resolve()
                        images: list[str] = []
                        for name in context["references"]:
                            path = Path(name).resolve()
                            if uploads_root not in path.parents or not path.is_file():
                                raise GrsError(f"参考图片不存在或超出上传目录: {path.name}")
                            images.append(GrsClient.data_uri(path))
                        return images

                    images = await asyncio.to_thread(reference_data_uris)
                    aspect_ratio, image_size = grs_request_size(mode, context["options"])
                    try:
                        remote_task_id = await asyncio.to_thread(
                            client.submit,
                            model=context["options"]["provider_model"], prompt=context["prompt"], images=images,
                            aspect_ratio=aspect_ratio, image_size=image_size,
                        )
                    except Exception as error:
                        if self._generation_cancelled(generation_item_id):
                            return
                        self.store.update_generation(
                            generation_item_id, status=JobStatus.INTERRUPTED,
                            stage="GRS 提交结果不确定", error=f"{error}；为避免重复扣费，请确认后显式重试。",
                        )
                        return
                    if self._generation_cancelled(generation_item_id):
                        return
                    self.store.update_generation(
                        generation_item_id, status=JobStatus.RUNNING, stage="GRS 已接单，等待生成",
                        progress=12, remote_task_id=remote_task_id, remote_status="submitted",
                    )
                await self._poll_image(client, generation_item_id, remote_task_id)
            except Exception as error:
                if self._generation_cancelled(generation_item_id) or self._generation_has_output(generation_item_id):
                    return
                self.store.update_generation(
                    generation_item_id, status=JobStatus.FAILED, stage="图片生成失败", error=str(error),
                )

    def _generation_cancelled(self, generation_item_id: str) -> bool:
        try:
            item = self.store.get_generation(generation_item_id)
        except KeyError:
            return True
        return item["status"] == JobStatus.CANCELLED.value or bool(item.get("cancel_requested"))

    def _generation_has_output(self, generation_item_id: str) -> bool:
        try:
            item = self.store.get_generation(generation_item_id)
        except KeyError:
            return False
        return item.get("status") == JobStatus.SUCCEEDED.value or bool(item.get("outputs"))

    async def _ingest_image(
        self, client: GrsClient, generation_item_id: str, urls: list[str], remote_status: str,
    ) -> None:
        if self.resource_storage is None:
            raise GrsError("服务器未初始化资源存储。")
        last_error: Exception | None = None
        for url in urls:
            try:
                filename, content = await asyncio.to_thread(client.download_image, url)
            except Exception as error:
                last_error = error
                continue
            stored = await asyncio.to_thread(self.resource_storage.store_bytes, "image", filename, content)
            output = {
                "kind": "image", "path": stored.key, "label": "生成图片",
                "delivery_status": "cloud" if self.resource_storage.persistent_outputs else "pending",
                "delivered_at": None,
            }
            self.store.update_generation(
                generation_item_id, status=JobStatus.SUCCEEDED, stage="生成完成", progress=100,
                outputs=[output], error="", remote_status=remote_status,
            )
            asyncio.create_task(self._refresh_grs_balance(), name="grs-balance-refresh")
            return
        if last_error is not None:
            raise last_error
        raise GrsError("GRS 未返回可下载的图片")

    async def _poll_image(self, client: GrsClient, generation_item_id: str, remote_task_id: str) -> None:
        started = time.monotonic()
        delay = max(5, settings.grs_poll_interval_seconds)
        while time.monotonic() - started < settings.grs_timeout_seconds:
            if self._generation_cancelled(generation_item_id):
                return
            try:
                status, urls, message = await asyncio.to_thread(client.result, remote_task_id)
                delay = max(5, settings.grs_poll_interval_seconds)
            except GrsTemporaryError as error:
                delay = min(30, max(5, delay * 2))
                self.store.update_generation(
                    generation_item_id, stage=f"GRS 暂时不可用，{delay} 秒后重试", remote_status="temporary_error", error=str(error),
                )
                await asyncio.sleep(delay)
                continue
            elapsed = time.monotonic() - started
            progress = min(90, 12 + int(78 * elapsed / max(1, settings.grs_timeout_seconds)))
            self.store.update_generation(
                generation_item_id, stage="GRS 正在生成图片", progress=progress, remote_status=status,
            )
            terminal = status in SUCCESS_STATUSES or status in FAILED_STATUSES
            if terminal and urls:
                if self._generation_cancelled(generation_item_id):
                    return
                try:
                    await self._ingest_image(client, generation_item_id, urls, status)
                    return
                except GrsTemporaryError as error:
                    delay = min(30, max(5, delay * 2))
                    self.store.update_generation(
                        generation_item_id, stage=f"GRS 图片下载暂时失败，{delay} 秒后重试",
                        remote_status="temporary_error", error=str(error),
                    )
                    await asyncio.sleep(delay)
                    continue
                except Exception:
                    if self._generation_has_output(generation_item_id):
                        return
                    if status in FAILED_STATUSES:
                        raise GrsError(GrsClient.format_failure(status, message))
                    raise
            if status in FAILED_STATUSES:
                raise GrsError(GrsClient.format_failure(status, message))
            if status in SUCCESS_STATUSES:
                self.store.update_generation(
                    generation_item_id, stage="GRS 已完成，等待结果地址", progress=progress, remote_status=status,
                )
            await asyncio.sleep(delay)
        raise GrsError("GRS 图片生成超过 30 分钟，已停止轮询。")

    async def _refresh_grs_balance(self) -> None:
        if self.grs_provider is None:
            return
        try:
            await asyncio.to_thread(self.grs_provider.refresh_balance_snapshot)
        except Exception:
            return
