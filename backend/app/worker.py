from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

from .comfy_service import ComfyQueuePrompt, ComfyService, ComfyUnavailable
from .config import settings
from .grs_client import FAILED_STATUSES, SUCCESS_STATUSES, GrsClient, GrsError, GrsTemporaryError
from .grs_provider import GrsProviderService
from .models import JobMode, JobStatus
from .resource_storage import ResourceStorage
from .storage import JobStore
from .workflow_registry import H3_WORKFLOWS, IMAGE_WORKFLOWS, grs_request_size


class JobWorker:
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
        self.task: asyncio.Task | None = None
        self.image_tasks: set[asyncio.Task] = set()
        self.image_semaphore = asyncio.Semaphore(max(1, min(4, settings.grs_max_concurrency)))

    async def start(self) -> None:
        recovered = await asyncio.to_thread(self.recover)
        self.task = asyncio.create_task(self.run(), name="zly-ai-video-studio-job-worker")
        for job_id in recovered:
            await self.enqueue(job_id)
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
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        for task in self.image_tasks:
            task.cancel()
        if self.image_tasks:
            await asyncio.gather(*self.image_tasks, return_exceptions=True)

    async def enqueue(self, job_id: str) -> None:
        job = self.store.get(job_id)
        items = job["rounds"][-1]["generation_items"]
        if items and items[0]["executor"] == "grs":
            for item in items:
                if item["status"] == JobStatus.QUEUED.value:
                    self.enqueue_generation(item["id"])
            return
        await self.queue.put(job_id)

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
            if JobMode(job["mode"]) in H3_WORKFLOWS
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

    def recover(self) -> list[str]:
        active_prompts = self.comfy.active_prompts()
        active_jobs = self.store.with_statuses(JobStatus.QUEUED, JobStatus.RUNNING)
        supported_jobs = []
        for job in active_jobs:
            if JobMode(job["mode"]) in H3_WORKFLOWS:
                supported_jobs.append(job)
                continue
            if JobMode(job["mode"]) in IMAGE_WORKFLOWS:
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
        for job in supported_jobs:
            if job["status"] == JobStatus.QUEUED:
                recovered.append(job["id"])
                continue
            prompt_id = job.get("comfy_prompt_id")
            if not prompt_id:
                self.store.update(job["id"], status=JobStatus.INTERRUPTED, stage="缺少 ComfyUI 任务标识，无法恢复")
                continue
            state, _ = self.comfy.prompt_state(prompt_id, active_prompt_ids)
            if state in {"active", "completed"}:
                self.store.update(job["id"], stage="正在恢复 ComfyUI 任务同步")
                recovered.append(job["id"])
            elif state == "failed":
                self.store.clear_comfy_execution(job["id"])
                self.store.update(job["id"], status=JobStatus.FAILED, stage="ComfyUI 推理失败", error="ComfyUI 已报告任务失败")
            elif state == "missing":
                self.store.clear_comfy_execution(job["id"])
                self.store.update(job["id"], status=JobStatus.INTERRUPTED, stage="ComfyUI 中未找到任务")
        return recovered

    async def run(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self.execute(job_id)
            finally:
                self.queue.task_done()

    async def execute(self, job_id: str) -> None:
        job = self.store.get(job_id, include_references=True)
        if job["status"] == JobStatus.QUEUED:
            self.store.update(job_id, status=JobStatus.RUNNING, stage="正在准备任务", progress=0)
            job = self.store.get(job_id, include_references=True)
        if job["status"] != JobStatus.RUNNING:
            return

        def update_stage(stage: str, progress: int | None = None) -> None:
            self.store.update(job_id, stage=stage, progress=progress)

        def on_submitted(prompt_id: str, client_id: str, phase: str) -> None:
            self.store.set_comfy_execution(job_id, prompt_id, client_id, phase)

        def save_partial_outputs(outputs: list[dict]) -> None:
            self.store.update(job_id, outputs=outputs)

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
                )
            self.store.clear_comfy_execution(job_id)
            self.store.update(job_id, status=JobStatus.SUCCEEDED, stage="生成完成", progress=100, outputs=outputs)
        except ComfyUnavailable as error:
            self.store.clear_comfy_execution(job_id)
            self.store.update(
                job_id,
                status=JobStatus.INTERRUPTED,
                stage="ComfyUI 连接中断，等待重新提交",
                error=str(error),
            )
        except Exception as error:
            self.store.clear_comfy_execution(job_id)
            self.store.update(job_id, status=JobStatus.FAILED, stage="生成失败", error=str(error))

    async def execute_image(self, generation_item_id: str) -> None:
        if self.grs_provider is None or self.resource_storage is None:
            self.store.update_generation(
                generation_item_id, status=JobStatus.FAILED, stage="GRS 执行器不可用", error="服务器未初始化 GRS 执行器。",
            )
            return
        async with self.image_semaphore:
            context = self.store.generation_context(generation_item_id)
            mode = JobMode(context["mode"])
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
                        self.store.update_generation(
                            generation_item_id, status=JobStatus.INTERRUPTED,
                            stage="GRS 提交结果不确定", error=f"{error}；为避免重复扣费，请确认后显式重试。",
                        )
                        return
                    self.store.update_generation(
                        generation_item_id, status=JobStatus.RUNNING, stage="GRS 已接单，等待生成",
                        progress=12, remote_task_id=remote_task_id, remote_status="submitted",
                    )
                await self._poll_image(client, generation_item_id, remote_task_id)
            except Exception as error:
                self.store.update_generation(
                    generation_item_id, status=JobStatus.FAILED, stage="图片生成失败", error=str(error),
                )

    async def _poll_image(self, client: GrsClient, generation_item_id: str, remote_task_id: str) -> None:
        started = time.monotonic()
        delay = max(5, settings.grs_poll_interval_seconds)
        while time.monotonic() - started < settings.grs_timeout_seconds:
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
            if status in FAILED_STATUSES:
                raise GrsError(message or f"GRS 任务失败：{status}")
            if status in SUCCESS_STATUSES:
                filename, content = await asyncio.to_thread(client.download_image, urls[0])
                stored = await asyncio.to_thread(self.resource_storage.store_bytes, "image", filename, content)
                output = {
                    "kind": "image", "path": stored.key, "label": "生成图片",
                    "delivery_status": "pending", "delivered_at": None,
                }
                self.store.update_generation(
                    generation_item_id, status=JobStatus.SUCCEEDED, stage="生成完成", progress=100,
                    outputs=[output], error="", remote_status=status,
                )
                return
            await asyncio.sleep(delay)
        raise GrsError("GRS 图片生成超过 30 分钟，已停止轮询。")
