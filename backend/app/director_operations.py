from __future__ import annotations

import asyncio
from typing import Any

from .director_catalog import find_art_style
from .director_jobs import render_recipe_shots, revert_orphaned_shot_submissions
from .director_project_service import persist_recipe_execution
from .director_recipe import AGENT_IDS, PAYLOAD_KIND_RECIPE, normalize_recipe_payload, payload_kind
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
            self._check_cancelled(operation_id)
            if operation["kind"] == "plan_pipeline":
                result = await self._run_plan(operation)
            elif operation["kind"] == "shot_render_prepare":
                result = await self._run_render(operation)
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
        except DirectorOperationCancelled as error:
            if operation is not None:
                self._revert_orphaned_render_submissions(operation)
            self.store.update_director_operation(
                operation_id, status="cancelled", error=str(error), update_error=True,
            )
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
                raise
        except Exception as error:
            if operation is not None:
                self._revert_orphaned_render_submissions(operation)
            self.store.update_director_operation(
                operation_id, status="failed", error=str(error), update_error=True,
            )

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
            self.store.update_director_operation(
                operation_id,
                progress=min(95, 5 + int(completed / total * 90)),
                result={"project_revision": saved["revision"]},
            )

        updated = await asyncio.to_thread(
            self.llm_provider.run_director_recipe,
            recipe,
            goal=goal,
            art_style_id=art_style_id,
            agents=agents,
            skip_research=request.get("skip_research"),
            on_progress=persist,
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
        llm_available, _ = self.llm_provider.availability()

        def persist(current: dict[str, Any]) -> None:
            self._check_cancelled(operation_id)
            saved = persist_recipe_execution(
                self.store,
                record["id"],
                current,
                scope="render",
                shot_ids=shot_ids,
            )
            self.store.update_director_operation(
                operation_id,
                progress=20,
                result={"project_revision": saved["revision"]},
            )

        recipe, job_ids = await asyncio.to_thread(
            render_recipe_shots,
            self.store,
            owner_user_id=operation["owner_user_id"],
            recipe=record["payload"],
            shot_ids=shot_ids,
            render_pass=render_pass,
            resource_storage=self.resource_storage,
            h3_prompt_refiner=self.llm_provider.polish_director_h3_prompt if llm_available else None,
            on_progress=persist,
        )
        saved = persist_recipe_execution(
            self.store, record["id"], recipe, scope="render", shot_ids=shot_ids,
        )
        for job_id in job_ids:
            self._check_cancelled(operation_id)
            await self.worker.enqueue(job_id)
        return {"job_ids": job_ids, "project_revision": saved["revision"]}
