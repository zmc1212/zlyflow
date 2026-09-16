from __future__ import annotations

import asyncio
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ...dialogue_timing import resolve_shot_duration_sec
from ...director_recipe import empty_recipe_payload, flatten_recipe_shots, normalize_recipe_payload
from ...director_stream import DirectorOperationEventBus, terminal_event_for_status
from ..db import execute_sql, now_str, query_all, query_one, transaction_cursor
from ..services.project_detail_service import (
    ProjectDetailService,
    asset_name_id_map,
    match_named_asset_ids,
    resolve_shot_scene,
)
from .script_parser import StandardScriptParser


class AiOperationCancelled(RuntimeError):
    pass


class AiGenerationService:
    """Director2 project-level AI pipeline.

    The durable record lives in ai_project_jobs so the existing Director2 task
    center can display it. The event bus follows the Director operation SSE
    contract, while the result adapter writes only Director2 entities.
    """

    # Worker-active statuses: a background worker is running or queued to run.
    # awaiting_review is intentionally excluded — the operation is paused waiting
    # for the user to confirm the current step, so no worker is occupied and the
    # user is free to think. revising DOES occupy a worker (streaming the clarify
    # questions for the current step), so it counts as active.
    ACTIVE = {"queued", "running", "clarifying", "revising"}
    # Statuses that still hold the project's single AI operation slot. Adds the
    # paused awaiting_review state so create() rejects a second operation while a
    # user is reviewing a step, and get_active() re-attaches to it on reload.
    OCCUPYING = ACTIVE | {"awaiting_review"}
    STAGES = ("script", "assets", "episodes", "storyboard")
    AGENTS = ("script", "characters", "locations", "episodes", "storyboard")
    # Per-step confirmation legs: each stage runs only its own agents, then pauses
    # at awaiting_review until the user adopts it (advance) or asks to revise.
    STAGE_AGENTS: dict[str, list[str]] = {
        "script": ["script"],
        "assets": ["characters", "locations"],
        "episodes": ["episodes"],
        "storyboard": ["storyboard"],
    }
    # Progress reached when a leg finishes and pauses for review.
    STAGE_END_PROGRESS = {"script": 25, "assets": 50, "episodes": 72, "storyboard": 95}
    # Statuses that can retry a named completed/failed stage (not a live worker).
    STAGE_RETRY_ALLOWED = {"failed", "cancelled", "awaiting_review", "succeeded"}
    _STAGE_REVIEW_MESSAGE = {
        "script": "剧本已生成，请确认或提出调整",
        "assets": "角色·场景·道具已生成，请确认或提出调整",
        "episodes": "分集结构已生成，请确认或提出调整",
        "storyboard": "分镜已生成，请确认或提出调整",
    }
    _RECIPE_CLEAR_FROM = {
        "clarify": ("script", "characters", "props", "locations", "episodes", "scenes"),
        "script": ("script", "characters", "props", "locations", "episodes", "scenes"),
        "assets": ("characters", "props", "locations", "episodes", "scenes"),
        "episodes": ("episodes", "scenes"),
        "storyboard": ("scenes",),
    }
    _AGENT_CLEAR_FROM = {
        "clarify": ("script", "characters", "locations", "episodes", "storyboard"),
        "script": ("script", "characters", "locations", "episodes", "storyboard"),
        "assets": ("characters", "locations", "episodes", "storyboard"),
        "episodes": ("episodes", "storyboard"),
        "storyboard": ("storyboard",),
    }
    _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="director2-ai")

    @classmethod
    def recover_orphaned_jobs(cls) -> None:
        """Do not resume paid LLM calls after a process restart; expose retry instead."""
        try:
            rows = query_all("SELECT id, payload_json FROM ai_project_jobs WHERE job_type='ai_pipeline' AND status IN ('queued','running','clarifying','revising')")
        except Exception:
            # Older deployments may not have the optional AI Media Studio table
            # yet; recovery must never prevent the main API from starting.
            return
        for row in rows:
            try:
                payload = json.loads(row.get("payload_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            message = "服务进程重启，AI 任务已中断，请重新提交或重试。"
            payload["recovery"] = message
            execute_sql("UPDATE ai_project_jobs SET status='failed', progress=0, error_message=%s, payload_json=%s, updated_at=%s WHERE id=%s", (message, json.dumps(payload, ensure_ascii=False), now_str(), row["id"]))

    def __init__(self, llm_provider: Any):
        self.llm_provider = llm_provider
        self.events = DirectorOperationEventBus()
        self._futures: set[Any] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _payload(row: dict[str, Any]) -> dict[str, Any]:
        try:
            return json.loads(row.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}

    @classmethod
    def _public(cls, row: dict[str, Any]) -> dict[str, Any]:
        payload = cls._payload(row)
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        # 失败/取消后仍需把已经写入的 Recipe 快照带回前端，抽屉才能在刷新
        # 或重新接管任务后继续查看已生成内容。运行中不回传快照，避免每次轮询
        # 携带完整剧本和分镜造成不必要的网络开销。
        # 待确认/调整阶段同样需要回传 Recipe 快照：卡点确认卡要展示该阶段刚生成
        # 的内容，刷新或重新接管后也能立即看到，不必等 SSE 重放。
        if row.get("status") in {"failed", "cancelled", "succeeded", "awaiting_review", "revising"} and isinstance(payload.get("recipe"), dict):
            result = {**result, "recipe": payload["recipe"]}
        request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        # Director2 used to persist the legacy beat-count question. Normalize
        # it on read so a restarted browser immediately shows the episode and
        # per-episode shot questions instead of replaying stale clarification state.
        opening_questions = (
            payload.get("kind") == "clarify"
            or payload.get("current_stage") == "clarify"
            or payload.get("revise_stage") == "clarify"
        )
        if opening_questions and isinstance(result.get("questions"), list):
            from ...llm_minimax_skills import ensure_director2_opening_questions

            result = {**result, "questions": ensure_director2_opening_questions(result["questions"])}
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "kind": payload.get("kind") or "pipeline",
            "status": row.get("status") or "queued",
            "progress": int(row.get("progress") or 0),
            "current_stage": payload.get("current_stage"),
            "awaiting_stage": payload.get("awaiting_stage"),
            "stage_plan": payload.get("stage_plan") or list(cls.STAGES),
            "request": request,
            "stage_clarifications": cls._public_stage_clarifications(payload),
            "result": result,
            "error": row.get("error_message"),
            "cancel_requested": bool(payload.get("cancel_requested")),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    @staticmethod
    def _public_stage_clarifications(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """Expose per-stage revise answers for the completed-step choice chips.

        Assets copy the same Q&A onto every agent; the frontend helper
        dedupes. Missing/malformed stores become `{}` so old tasks stay safe.
        """
        store = payload.get("stage_clarifications")
        if not isinstance(store, dict):
            return {}
        public: dict[str, list[dict[str, Any]]] = {}
        for key, items in store.items():
            if not isinstance(items, list):
                continue
            public[str(key)] = [item for item in items if isinstance(item, dict)]
        return public

    def _emit(self, operation_id: str, event: dict[str, Any]) -> None:
        self.events.emit(operation_id, event)

    def _read(self, operation_id: str, project_id: str | None = None) -> dict[str, Any]:
        row = query_one("SELECT * FROM ai_project_jobs WHERE id = %s" + (" AND project_id = %s" if project_id else ""), (operation_id, project_id) if project_id else (operation_id,))
        if not row or row.get("job_type") != "ai_pipeline":
            raise ValueError("AI 生成任务不存在")
        return row

    def create(self, project_id: str, request: dict[str, Any]) -> dict[str, Any]:
        kind = str(request.get("kind") or "pipeline")
        if kind not in {"clarify", "pipeline"}:
            raise ValueError("不支持的 AI 操作类型")
        goal = str(request.get("goal") or "").strip()
        if not goal:
            raise ValueError("请输入创意简报")
        active = query_one(
            "SELECT id FROM ai_project_jobs WHERE project_id = %s AND job_type = 'ai_pipeline' AND status IN ('queued','running','clarifying','revising','awaiting_review') ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        )
        if active:
            raise ValueError(f"该项目已有进行中的 AI 任务：{active['id']}")
        operation_id = f"aiop-{uuid.uuid4().hex[:12]}"
        payload = {
            "kind": kind,
            "request": request,
            "current_stage": "clarify" if kind == "clarify" else "script",
            "completed_stages": [],
            "stage_plan": list(self.STAGES),
            "awaiting_stage": None,
            "stage_clarifications": {},
            "result": {},
            "cancel_requested": False,
            "attempt": 0,
            "run_action": "clarify" if kind == "clarify" else "leg",
            "run_stage": None if kind == "clarify" else "script",
        }
        ts = now_str()
        status = "clarifying" if kind == "clarify" else "queued"
        execute_sql(
            "INSERT INTO ai_project_jobs (id, project_id, job_type, title, status, progress, result_url, payload_json, created_at, updated_at) VALUES (%s,%s,'ai_pipeline',%s,%s,0,NULL,%s,%s,%s)",
            (operation_id, project_id, "AI 生成：" + goal[:60], status, json.dumps(payload, ensure_ascii=False), ts, ts),
        )
        self.start(operation_id)
        return self._public(self._read(operation_id, project_id))

    def start(self, operation_id: str) -> None:
        future = self._executor.submit(self._run_sync, operation_id)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(lambda item: self._futures.discard(item))

    def get(self, operation_id: str, project_id: str) -> dict[str, Any]:
        return self._public(self._read(operation_id, project_id))

    def get_active(self, project_id: str) -> dict[str, Any] | None:
        row = query_one(
            "SELECT * FROM ai_project_jobs WHERE project_id = %s AND job_type = 'ai_pipeline' AND status IN ('queued','running','clarifying','revising','awaiting_review') ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        )
        return self._public(row) if row else None

    def cancel(self, operation_id: str, project_id: str) -> dict[str, Any]:
        row = self._read(operation_id, project_id)
        status = row.get("status")
        if status not in self.OCCUPYING:
            raise ValueError("该 AI 任务已结束，不能取消")
        payload = self._payload(row)
        payload["cancel_requested"] = True
        if status == "awaiting_review":
            # 待确认阶段没有正在运行的 worker 来观察取消标记，直接把任务落为已取消，
            # 并保留当前阶段作为可续跑的位置。
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            payload["result"] = {**result, "failed_stage": payload.get("awaiting_stage") or payload.get("current_stage")}
            self._update(operation_id, status="cancelled", error="已取消当前生成", payload=payload)
            operation = self.get(operation_id, project_id)
            self._emit(operation_id, terminal_event_for_status("cancelled", message="已取消当前生成"))
            return operation
        execute_sql("UPDATE ai_project_jobs SET payload_json=%s, updated_at=%s WHERE id=%s AND project_id=%s", (json.dumps(payload, ensure_ascii=False), now_str(), operation_id, project_id))
        operation = self.get(operation_id, project_id)
        self._emit(operation_id, {
            "event": "status",
            "data": {
                "status": operation["status"],
                "progress": operation["progress"],
                "stage": operation["current_stage"],
                "completed_stages": operation["result"].get("completed_stages") or [],
                "cancel_requested": True,
                "message": "正在停止当前生成…",
            },
        })
        return operation

    def retry(self, operation_id: str, project_id: str, stage: str | None = None) -> dict[str, Any]:
        row = self._read(operation_id, project_id)
        requested = str(stage or "").strip() or None
        status = row.get("status")
        # 重试请求可能因双击或网络重放而到达两次。第一次请求已把任务置为
        # queued/running 时，直接返回同一个操作并让前端重新订阅，不能再创建
        # 第二个 worker，也不应误报“只有失败或已取消的任务可以重试”。
        if status in self.ACTIVE:
            payload = self._payload(row)
            current = payload.get("run_stage") or payload.get("revise_stage") or payload.get("current_stage")
            if requested and requested != current:
                raise ValueError("生成进行中，请等待完成或取消后再重试其他阶段")
            return self.get(operation_id, project_id)
        payload = self._payload(row)
        is_clarify_kind = payload.get("kind") == "clarify"
        if requested:
            if status not in self.STAGE_RETRY_ALLOWED:
                raise ValueError("当前状态不能重试指定阶段")
            if requested != "clarify" and requested not in self.STAGE_AGENTS:
                raise ValueError(f"未知的生成阶段：{requested}")
            if is_clarify_kind and requested != "clarify":
                raise ValueError("创意确认尚未完成，请先回答问题后再生成")
        elif status not in {"failed", "cancelled"}:
            raise ValueError("只有失败或已取消的 AI 任务可以重试")
        if not is_clarify_kind:
            payload["kind"] = "pipeline"
        payload["cancel_requested"] = False
        payload["attempt"] = int(payload.get("attempt") or 0) + 1
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        if is_clarify_kind:
            self._update(operation_id, status="queued", progress=0, payload=payload)
        else:
            retry_stage = requested or payload.get("awaiting_stage") or payload.get("current_stage") or result.get("failed_stage") or "script"
            if retry_stage == "clarify":
                self._queue_opening_clarify(payload)
                self._update(operation_id, status="revising", progress=0, payload=payload)
            else:
                if retry_stage not in self.STAGE_AGENTS:
                    retry_stage = "script"
                if requested:
                    self._invalidate_from(payload, retry_stage)
                payload["run_action"] = "leg"
                payload["run_stage"] = retry_stage
                payload["awaiting_stage"] = None
                payload["current_stage"] = retry_stage
                payload.pop("revise_stage", None)
                payload.pop("revise_feedback", None)
                payload["result"] = {"completed_stages": list(payload.get("completed_stages") or result.get("completed_stages") or [])}
                self._update(operation_id, status="queued", progress=self._stage_start_progress(retry_stage), payload=payload)
        execute_sql("UPDATE ai_project_jobs SET error_message=NULL, updated_at=%s WHERE id=%s AND project_id=%s", (now_str(), operation_id, project_id))
        self.start(operation_id)
        return self.get(operation_id, project_id)

    def _completed_before(self, stage: str) -> list[str]:
        stages = list(self.STAGES)
        if stage not in stages:
            return []
        return stages[:stages.index(stage)]

    def _invalidate_from(self, payload: dict[str, Any], stage: str) -> None:
        """Drop later completed stages and their recipe / clarification snapshots."""
        keep = set(self._completed_before(stage))
        payload["completed_stages"] = [
            item for item in (payload.get("completed_stages") or [])
            if isinstance(item, str) and item in keep
        ]
        store = payload.get("stage_clarifications") if isinstance(payload.get("stage_clarifications"), dict) else {}
        drop = ["clarify", *self.STAGES] if stage == "clarify" else list(self.STAGES)[list(self.STAGES).index(stage):]
        for key in drop:
            store.pop(key, None)
        payload["stage_clarifications"] = store
        recipe = payload.get("recipe")
        if not isinstance(recipe, dict):
            return
        goal = str((payload.get("request") or {}).get("goal") or "").strip()
        for field in self._RECIPE_CLEAR_FROM.get(stage, ()):
            if field == "script":
                recipe["script"] = {"title": goal[:40], "summary": "", "fullStory": goal}
            else:
                recipe[field] = []
        agents = set(self._AGENT_CLEAR_FROM.get(stage, ()))
        statuses = recipe.get("agentStatus")
        if isinstance(statuses, list):
            for item in statuses:
                if isinstance(item, dict) and item.get("id") in agents:
                    item["status"] = "pending"
                    item["error"] = None
                    item["message"] = None
        payload["recipe"] = recipe

    def _queue_opening_clarify(self, payload: dict[str, Any]) -> None:
        self._invalidate_from(payload, "clarify")
        request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        request["clarifications"] = []
        payload["request"] = request
        payload["kind"] = "pipeline"
        payload["run_action"] = "opening_clarify"
        payload["run_stage"] = None
        payload["revise_stage"] = "clarify"
        payload["awaiting_stage"] = None
        payload["current_stage"] = "clarify"
        payload.pop("revise_feedback", None)
        payload["result"] = {"completed_stages": []}

    def _check_cancelled(self, operation_id: str) -> None:
        row = self._read(operation_id)
        if self._payload(row).get("cancel_requested"):
            raise AiOperationCancelled("AI 生成已取消")

    def _update(self, operation_id: str, *, status: str | None = None, progress: int | None = None, payload: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
        row = self._read(operation_id)
        data = payload if payload is not None else self._payload(row)
        persisted = self._payload(row)
        # Keep an in-flight cancel so a stale worker payload cannot clear it.
        # Retry / advance / revise start a new attempt from a terminal or paused
        # status and must be allowed to reset the flag; otherwise the new worker
        # immediately sees cancel_requested and stops again.
        next_status = status if status is not None else row.get("status")
        if (
            persisted.get("cancel_requested")
            and not data.get("cancel_requested")
            and row.get("status") in self.ACTIVE
            and next_status in self.ACTIVE
        ):
            data = {**data, "cancel_requested": True}
        updates: list[str] = ["payload_json=%s", "updated_at=%s"]
        values: list[Any] = [json.dumps(data, ensure_ascii=False), now_str()]
        if status is not None:
            updates.append("status=%s")
            values.append(status)
        if progress is not None:
            updates.append("progress=%s")
            values.append(max(0, min(100, int(progress))))
        if error is not None:
            updates.append("error_message=%s")
            values.append(error)
        elif status == "running":
            # A surviving worker can flip status back to running after restart
            # recovery wrote a stale error_message; never show that as a live failure.
            updates.append("error_message=%s")
            values.append(None)
        values.append(operation_id)
        execute_sql(f"UPDATE ai_project_jobs SET {', '.join(updates)} WHERE id=%s", tuple(values))
        return self._read(operation_id)

    def _run_sync(self, operation_id: str) -> None:
        try:
            row = self._read(operation_id)
            payload = self._payload(row)
            request = payload.get("request") or {}
            kind = payload.get("kind")
            action = str(payload.get("run_action") or ("clarify" if kind == "clarify" else "leg"))
            if kind == "clarify":
                self._update(operation_id, status="running", progress=max(1, int(row.get("progress") or 0)), payload=payload)
                self._emit(operation_id, {"event": "status", "data": {"status": "running", "progress": 1}})
                self._run_clarify(operation_id, payload, request)
            elif action == "opening_clarify":
                self._run_opening_clarify(operation_id, payload, request)
            elif action == "revise":
                # 生成该阶段的澄清问题：保持 revising 状态（占用 worker），不切回 running。
                self._run_revise(operation_id, payload, request)
            else:
                self._update(operation_id, status="running", progress=max(1, int(row.get("progress") or 0)), payload=payload)
                self._emit(operation_id, {"event": "status", "data": {"status": "running", "progress": 1}})
                self._run_stage_leg(operation_id, payload, request, str(payload.get("run_stage") or "script"))
        except AiOperationCancelled as error:
            message = str(error)
            current = self._read(operation_id)
            payload = self._payload(current)
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            result = {**result, "failed_stage": payload.get("current_stage")}
            payload["result"] = result
            self._update(operation_id, status="cancelled", error=message, payload=payload)
            self._emit(operation_id, terminal_event_for_status("cancelled", message=message))
        except Exception as error:
            message = str(error)
            current = self._read(operation_id)
            payload = self._payload(current)
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            result = {**result, "failed_stage": payload.get("current_stage")}
            payload["result"] = result
            self._update(operation_id, status="failed", error=message, payload=payload)
            self._emit(operation_id, terminal_event_for_status("failed", message=message))

    def _collect_opening_questions(self, operation_id: str, request: dict[str, Any]) -> list[dict[str, Any]]:
        def on_stream(event: dict[str, Any]) -> None:
            self._check_cancelled(operation_id)
            self._emit(operation_id, event)

        is_director2 = str(request.get("surface") or "") == "director2"
        questions = self.llm_provider.run_director_clarify(
            str(request.get("goal") or ""),
            recipe=None,
            on_stream=on_stream,
            include_beat_count=not is_director2,
            include_shots_per_episode=is_director2,
        )
        if is_director2:
            from ...llm_minimax_skills import ensure_director2_opening_questions

            questions = ensure_director2_opening_questions(questions)
        return questions

    def _run_clarify(self, operation_id: str, payload: dict[str, Any], request: dict[str, Any]) -> None:
        self._check_cancelled(operation_id)
        questions = self._collect_opening_questions(operation_id, request)
        self._check_cancelled(operation_id)
        payload["result"] = {"questions": questions, "completed_stages": []}
        payload["current_stage"] = "clarify"
        self._check_cancelled(operation_id)
        self._update(operation_id, status="succeeded", progress=100, payload=payload)
        self._emit(operation_id, terminal_event_for_status("succeeded", result=payload["result"]))

    def _run_opening_clarify(self, operation_id: str, payload: dict[str, Any], request: dict[str, Any]) -> None:
        """Re-ask opening questions on an existing pipeline without ending the operation."""
        self._check_cancelled(operation_id)
        questions = self._collect_opening_questions(operation_id, {**request, "surface": "director2"})
        self._check_cancelled(operation_id)
        payload["kind"] = "pipeline"
        payload["revise_stage"] = "clarify"
        payload["current_stage"] = "clarify"
        payload["awaiting_stage"] = None
        payload["completed_stages"] = []
        payload.pop("run_action", None)
        payload["result"] = {"questions": questions, "completed_stages": [], "revise_stage": "clarify"}
        self._update(operation_id, status="revising", progress=0, payload=payload)
        self._emit(operation_id, {"event": "status", "data": {
            "status": "revising",
            "stage": "clarify",
            "questions_ready": True,
            "questions": questions,
            "completed_stages": [],
        }})

    # ------------------------------------------------------------------
    # 逐 leg 状态机：script / assets / episodes / storyboard 各自独立成一步，
    # 跑完暂停在 awaiting_review 等用户确认；采纳(advance)进入下一步，不满意
    # (revise)出该阶段澄清卡、作答(rerun_stage)后只重跑当前步。已完成的更早阶段
    # 可通过 retry(stage=…) 单独重跑，该阶段之后从 completed_stages 作废。
    # ------------------------------------------------------------------
    def _next_stage(self, stage: str) -> str | None:
        stages = list(self.STAGES)
        if stage not in stages:
            return None
        idx = stages.index(stage)
        return stages[idx + 1] if idx + 1 < len(stages) else None

    def _stage_start_progress(self, stage: str) -> int:
        stages = list(self.STAGES)
        if stage not in stages:
            return 1
        idx = stages.index(stage)
        return 5 if idx == 0 else int(self.STAGE_END_PROGRESS.get(stages[idx - 1], 5))

    def _stage_clarifications(self, payload: dict[str, Any], stage: str) -> list[dict[str, Any]]:
        store = payload.get("stage_clarifications")
        if not isinstance(store, dict):
            return []
        items = store.get(stage)
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def _stage_run_clarifications(self, stage: str, answers: Any, feedback: str) -> list[dict[str, Any]]:
        """Shape the user's revise answers + free-text feedback into clarification
        items the recipe agents can consume. The script step injects untagged
        items (see _clarified_goal_text); every other step tags each item with the
        consuming agent id so _clarified_stage_text picks it up for that agent."""
        agent_ids = list(self.STAGE_AGENTS.get(stage, [stage]))
        result: list[dict[str, Any]] = []

        def emit(question: str, answer: str, qid: Any = None, label: Any = None) -> None:
            question = str(question or "").strip()
            answer = str(answer or "").strip()
            if not (question and answer):
                return
            item: dict[str, Any] = {"id": qid, "question": question, "answer": answer}
            text = str(label or "").strip()
            if text:
                item["label"] = text
            if stage == "script":
                result.append(item)
            else:
                for aid in agent_ids:
                    result.append({**item, "agent": aid})

        if isinstance(answers, list):
            for item in answers:
                if isinstance(item, dict):
                    emit(item.get("question"), item.get("answer") or item.get("value"), item.get("id"), item.get("label"))
        if str(feedback or "").strip():
            emit("本轮调整诉求", feedback, "revise_feedback")
        return result

    def _run_stage_leg(self, operation_id: str, payload: dict[str, Any], request: dict[str, Any], stage: str) -> None:
        self._check_cancelled(operation_id)
        if stage not in self.STAGE_AGENTS:
            raise ValueError(f"未知的生成阶段：{stage}")
        goal = str(request.get("goal") or "").strip()
        recipe = normalize_recipe_payload(payload.get("recipe") or empty_recipe_payload(title=goal[:40], full_story=goal))
        agents = list(self.STAGE_AGENTS[stage])
        # 初始 clarify 的答案（如集数、每集镜头数）随 request 走，逐步调整的答案存 stage_clarifications。
        clarifications = list(request.get("clarifications") or [])
        stage_extra = self._stage_clarifications(payload, stage)
        if stage_extra:
            clarifications = clarifications + stage_extra
        payload["current_stage"] = stage
        payload["awaiting_stage"] = None
        payload.pop("run_action", None)
        stage_start = self._stage_start_progress(stage)
        stage_end = int(self.STAGE_END_PROGRESS.get(stage, 90))

        def leg_progress(statuses: dict[str, str]) -> int:
            done = sum(1 for aid in agents if statuses.get(aid) == "completed")
            if done >= len(agents):
                return max(stage_start + 1, stage_end - 1)
            frac = done / max(1, len(agents))
            return max(stage_start + 1, min(stage_end - 1, int(stage_start + (stage_end - stage_start) * frac)))

        def on_progress(current: dict[str, Any]) -> None:
            self._check_cancelled(operation_id)
            normalized = normalize_recipe_payload(current)
            payload["recipe"] = normalized
            statuses = {str(item.get("id")): str(item.get("status")) for item in normalized.get("agentStatus") or [] if isinstance(item, dict)}
            agent_messages = {str(item.get("id")): str(item.get("message") or "") for item in normalized.get("agentStatus") or [] if isinstance(item, dict)}
            running_agent = next((aid for aid in agents if statuses.get(aid) == "running"), None)
            running_message = agent_messages.get(running_agent, "") if running_agent else ""
            payload["result"] = self._running_result(payload, running_message)
            progress = leg_progress(statuses)
            self._update(operation_id, status="running", progress=progress, payload=payload)
            status_data: dict[str, Any] = {
                "status": "running",
                "progress": progress,
                "stage": stage,
                "completed_stages": payload.get("completed_stages") or [],
            }
            if running_message:
                status_data["message"] = running_message
            self._emit(operation_id, {"event": "status", "data": status_data})

        def on_stream(event: dict[str, Any]) -> None:
            self._check_cancelled(operation_id)
            self._emit(operation_id, event)

        updated = self.llm_provider.run_director_recipe(
            recipe, goal=goal, agents=agents, skip_research=True,
            on_progress=on_progress, on_stream=on_stream, clarifications=clarifications, resume=False,
        )
        self._check_cancelled(operation_id)
        normalized = normalize_recipe_payload(updated)
        payload["recipe"] = normalized
        project_id = str((payload.get("request") or {}).get("project_id") or request.get("project_id") or "")
        self._adapt_recipe(project_id, normalized, stage)
        self._check_cancelled(operation_id)
        # 该 leg 结束：暂停等确认。stage 未加入 completed_stages（那是 advance 的职责），
        # 只标记为 awaiting_stage，并发 status 事件（非 terminal），SSE 保持连接。
        payload["awaiting_stage"] = stage
        payload["current_stage"] = stage
        payload.pop("run_action", None)
        payload["result"] = self._awaiting_result(payload, stage)
        self._update(operation_id, status="awaiting_review", progress=stage_end, payload=payload)
        self._emit(operation_id, {"event": "status", "data": {
            "status": "awaiting_review",
            "progress": stage_end,
            "stage": stage,
            "awaiting_stage": stage,
            "completed_stages": payload.get("completed_stages") or [],
            "message": payload["result"].get("message"),
        }})

    def _run_revise(self, operation_id: str, payload: dict[str, Any], request: dict[str, Any]) -> None:
        self._check_cancelled(operation_id)
        stage = str(payload.get("revise_stage") or payload.get("awaiting_stage") or "").strip()
        if stage not in self.STAGE_AGENTS:
            raise ValueError(f"未知的生成阶段：{stage}")
        feedback = str(payload.get("revise_feedback") or "").strip()
        goal = str(request.get("goal") or "").strip()
        recipe = payload.get("recipe") if isinstance(payload.get("recipe"), dict) else None

        def on_stream(event: dict[str, Any]) -> None:
            self._check_cancelled(operation_id)
            self._emit(operation_id, event)

        questions = self.llm_provider.run_director_clarify(
            goal, recipe=recipe, agent=stage, feedback=feedback, on_stream=on_stream,
        )
        self._check_cancelled(operation_id)
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        payload["result"] = {
            **result,
            "questions": questions,
            "revise_stage": stage,
            "revise_feedback": feedback,
            "completed_stages": list(payload.get("completed_stages") or []),
        }
        payload["current_stage"] = stage
        payload.pop("run_action", None)
        # 停在 revising：澄清卡已就绪，等用户作答后由 rerun_stage 只重跑当前步。
        self._update(operation_id, status="revising", progress=self._stage_start_progress(stage), payload=payload)
        self._emit(operation_id, {"event": "status", "data": {
            "status": "revising",
            "stage": stage,
            "awaiting_stage": stage,
            "questions_ready": True,
            "completed_stages": payload.get("completed_stages") or [],
        }})

    @staticmethod
    def _awaiting_result(payload: dict[str, Any], stage: str) -> dict[str, Any]:
        return {
            "completed_stages": list(payload.get("completed_stages") or []),
            "awaiting_stage": stage,
            "message": AiGenerationService._STAGE_REVIEW_MESSAGE.get(stage, "该阶段已生成，请确认"),
        }

    def advance(self, operation_id: str, project_id: str) -> dict[str, Any]:
        """采纳当前 leg，进入下一步；已是最后一步则整体完成。"""
        row = self._read(operation_id, project_id)
        if row.get("status") != "awaiting_review":
            raise ValueError("当前不在待确认状态，无法进入下一步")
        payload = self._payload(row)
        stage = str(payload.get("awaiting_stage") or "")
        if stage not in self.STAGE_AGENTS:
            raise ValueError("没有待确认的生成阶段")
        completed = [s for s in (payload.get("completed_stages") or []) if isinstance(s, str)]
        if stage not in completed:
            completed.append(stage)
        payload["completed_stages"] = completed
        payload["awaiting_stage"] = None
        # 采纳后清理上一轮调整遗留，避免带入下一步。
        payload.pop("revise_stage", None)
        payload.pop("revise_feedback", None)
        payload["cancel_requested"] = False
        next_stage = self._next_stage(stage)
        if next_stage is None:
            payload["current_stage"] = None
            payload["result"] = {"completed_stages": completed, "message": "剧本、角色·场景·道具、分集与分镜已生成"}
            self._update(operation_id, status="succeeded", progress=100, payload=payload)
            self._emit(operation_id, terminal_event_for_status("succeeded", result=payload["result"]))
            return self.get(operation_id, project_id)
        payload["run_action"] = "leg"
        payload["run_stage"] = next_stage
        payload["current_stage"] = next_stage
        payload["result"] = self._running_result(payload)
        self._update(operation_id, status="queued", progress=self._stage_start_progress(next_stage), payload=payload)
        self.start(operation_id)
        return self.get(operation_id, project_id)

    def revise(self, operation_id: str, project_id: str, feedback: str) -> dict[str, Any]:
        """对当前 leg 提出对话反馈，AI 据此生成该阶段的澄清问题。"""
        row = self._read(operation_id, project_id)
        if row.get("status") != "awaiting_review":
            raise ValueError("当前不在待确认状态，无法调整")
        text = str(feedback or "").strip()
        if not text:
            raise ValueError("请描述你想怎么调整")
        payload = self._payload(row)
        stage = str(payload.get("awaiting_stage") or "")
        if stage not in self.STAGE_AGENTS:
            raise ValueError("没有待确认的生成阶段")
        payload["run_action"] = "revise"
        payload["revise_stage"] = stage
        payload["revise_feedback"] = text
        payload["cancel_requested"] = False
        payload["current_stage"] = stage
        self._update(operation_id, status="revising", progress=self._stage_start_progress(stage), payload=payload)
        self.start(operation_id)
        return self.get(operation_id, project_id)

    def rerun_stage(self, operation_id: str, project_id: str, clarifications: Any) -> dict[str, Any]:
        """提交该阶段澄清卡答案，合并反馈后只重跑当前 leg。"""
        row = self._read(operation_id, project_id)
        if row.get("status") not in {"revising", "awaiting_review"}:
            raise ValueError("当前无法重跑该阶段")
        payload = self._payload(row)
        stage = str(payload.get("revise_stage") or payload.get("awaiting_stage") or payload.get("current_stage") or "")
        answers = clarifications if isinstance(clarifications, list) else []
        if stage == "clarify":
            request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
            request["clarifications"] = answers
            payload["request"] = request
            self._invalidate_from(payload, "clarify")
            payload["kind"] = "pipeline"
            payload["run_action"] = "leg"
            payload["run_stage"] = "script"
            payload["awaiting_stage"] = None
            payload["current_stage"] = "script"
            payload["cancel_requested"] = False
            payload.pop("revise_stage", None)
            payload.pop("revise_feedback", None)
            payload["result"] = self._running_result(payload)
            self._update(operation_id, status="queued", progress=self._stage_start_progress("script"), payload=payload)
            self.start(operation_id)
            return self.get(operation_id, project_id)
        if stage not in self.STAGE_AGENTS:
            raise ValueError("没有需要重跑的生成阶段")
        feedback = str(payload.get("revise_feedback") or "").strip()
        merged = self._stage_run_clarifications(stage, answers, feedback)
        store = payload.get("stage_clarifications") if isinstance(payload.get("stage_clarifications"), dict) else {}
        store[stage] = merged
        payload["stage_clarifications"] = store
        payload["run_action"] = "leg"
        payload["run_stage"] = stage
        payload["awaiting_stage"] = None
        payload["current_stage"] = stage
        payload["cancel_requested"] = False
        payload.pop("revise_stage", None)
        payload.pop("revise_feedback", None)
        # 清掉澄清卡，重新进入运行态。
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        result.pop("questions", None)
        payload["result"] = self._running_result(payload)
        self._update(operation_id, status="queued", progress=self._stage_start_progress(stage), payload=payload)
        self.start(operation_id)
        return self.get(operation_id, project_id)

    @staticmethod
    def _running_result(payload: dict[str, Any], message: str = "") -> dict[str, Any]:
        result: dict[str, Any] = {"completed_stages": list(payload.get("completed_stages") or [])}
        text = str(message or "").strip() or str((payload.get("result") or {}).get("message") or "").strip()
        if text:
            result["message"] = text
        return result

    @staticmethod
    def _format_shot_camera(camera: Any) -> str:
        if isinstance(camera, dict):
            return " ".join(
                str(camera.get(key) or "").strip()
                for key in ("scale", "movement", "angle", "speed")
                if str(camera.get(key) or "").strip()
            )
        return str(camera or "").strip()

    @classmethod
    def _format_name_list(cls, value: Any) -> str:
        if isinstance(value, list):
            names: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                else:
                    name = str(item or "").strip()
                if name:
                    names.append(name)
            return "、".join(names)
        return str(value or "").strip()

    @staticmethod
    def _text_has_shot_cards(text: str) -> bool:
        return bool(re.search(r"#{1,3}\s*镜头", str(text or "")))

    @staticmethod
    def _shot_duration_seconds(shot: dict[str, Any], default: int = 8) -> int:
        return resolve_shot_duration_sec(shot, default=default)

    @classmethod
    def _shot_visual_prompt(cls, shot: dict[str, Any]) -> str:
        return str(
            shot.get("promptText")
            or shot.get("prompt")
            or shot.get("visualPrompt")
            or shot.get("visual_prompt")
            or ""
        ).strip()

    @classmethod
    def _recipe_shot_lines(cls, shot: dict[str, Any], index: int) -> list[str]:
        title = str(shot.get("title") or shot.get("heading") or "分镜").strip() or "分镜"
        lines = ["", f"### 镜头 {index}｜{title}"]
        action = str(shot.get("description") or shot.get("action") or "").strip()
        camera = cls._format_shot_camera(shot.get("camera"))
        dialogue = str(shot.get("dialogue") or "").strip()
        audio = str(shot.get("soundscape") or shot.get("audio") or "").strip()
        fields = [
            ("人物", cls._format_name_list(shot.get("characterNames") or shot.get("characters"))),
            ("场景", str(shot.get("locationName") or shot.get("scene") or "").strip()),
            ("道具", cls._format_name_list(shot.get("propNames") or shot.get("props"))),
            ("时长", f"{cls._shot_duration_seconds(shot)}秒"),
            ("动作", action),
            ("运镜", camera),
            ("台词", dialogue),
            ("音效", audio),
            ("提示词", cls._shot_visual_prompt(shot)),
        ]
        for label, value in fields:
            if value:
                lines.append(f"- {label}：{value}")
        return lines

    @staticmethod
    def _split_names(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value or "").strip()
        if not text:
            return []
        return [part.strip() for part in re.split(r"[、,，;；/|]+", text) if part.strip()]

    @staticmethod
    def _named_items(items: Any) -> list[dict[str, Any]]:
        return [item for item in (items or []) if isinstance(item, dict) and str(item.get("name") or "").strip()]

    @classmethod
    def _asset_markdown(cls, recipe: dict[str, Any]) -> list[str]:
        characters = cls._named_items(recipe.get("characters"))
        locations = cls._named_items(recipe.get("locations"))
        if not characters and not locations:
            return []
        lines: list[str] = []
        prompts: list[tuple[str, str]] = []
        if characters:
            lines.extend(["", "# 一、主要人物固定设定", ""])
            for character in characters:
                name = str(character.get("name")).strip()
                role = str(character.get("role") or character.get("type") or "主要角色").strip() or "主要角色"
                spec = character.get("identitySpec") if isinstance(character.get("identitySpec"), dict) else {}
                age = str(spec.get("ageRange") or character.get("age") or "").strip()
                description = str(character.get("description") or "").strip()
                accessories = cls._split_names(spec.get("immutableAccessories") or character.get("fixed_props") or character.get("fixedProps"))
                lines.append(f"### {name} —— {role}")
                if age and description:
                    lines.append(f"{age}。{description}")
                elif age:
                    lines.append(age)
                elif description:
                    lines.append(description)
                if accessories:
                    lines.append(f"固定道具：{'、'.join(accessories)}")
                lines.append("")
                prompt = str(character.get("promptText") or character.get("visualPrompt") or character.get("visual_prompt") or "").strip()
                if prompt:
                    prompts.append((name, prompt))
        if prompts:
            lines.extend(["# 四、人物一致性提示词", ""])
            for name, prompt in prompts:
                lines.append(f"{name}：{prompt}")
            lines.append("")
        if locations:
            lines.extend(["# 三、固定场景库", ""])
            for location in locations:
                name = str(location.get("name")).strip()
                description = str(location.get("description") or "").strip()
                prompt = str(location.get("promptText") or location.get("visualPrompt") or location.get("visual_prompt") or "").strip()
                lines.append(f"## {name}")
                if description:
                    lines.append(description)
                if prompt:
                    lines.append(prompt)
                lines.append("")
        return lines

    @classmethod
    def merge_recipe_assets_into_analysis(cls, analysis: dict[str, Any] | None, recipe: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(analysis or {})
        recipe = recipe if isinstance(recipe, dict) else {}

        characters = {str(item.get("name") or "").strip(): dict(item) for item in merged.get("characters") or [] if isinstance(item, dict) and str(item.get("name") or "").strip()}
        for item in cls._named_items(recipe.get("characters")):
            name = str(item.get("name")).strip()
            spec = item.get("identitySpec") if isinstance(item.get("identitySpec"), dict) else {}
            current = characters.get(name) or {"name": name, "shots_count": 0}
            current["role"] = str(item.get("role") or item.get("type") or current.get("role") or "主要角色").strip() or "主要角色"
            gender = str(item.get("gender") or "").strip()
            if gender:
                current["gender"] = gender
            age = str(spec.get("ageRange") or item.get("age") or "").strip()
            if age:
                current["age"] = age
            description = str(item.get("description") or "").strip()
            if description:
                current["description"] = description
            accessories = cls._split_names(spec.get("immutableAccessories") or item.get("fixed_props") or item.get("fixedProps") or current.get("fixed_props"))
            if accessories:
                current["fixed_props"] = accessories
            prompt = str(item.get("promptText") or item.get("visualPrompt") or item.get("visual_prompt") or current.get("visual_prompt") or "").strip()
            if prompt:
                current["visual_prompt"] = prompt
            characters[name] = current
        merged["characters"] = list(characters.values())

        scenes = {str(item.get("name") or "").strip(): dict(item) for item in merged.get("scenes") or [] if isinstance(item, dict) and str(item.get("name") or "").strip()}
        for item in cls._named_items(recipe.get("locations")):
            name = str(item.get("name")).strip()
            current = scenes.get(name) or {"name": name, "type": "固定场景", "elements": [], "shots_count": 0}
            current["type"] = str(item.get("type") or current.get("type") or "固定场景").strip() or "固定场景"
            description = str(item.get("description") or "").strip()
            if description:
                current["description"] = description
            prompt = str(item.get("promptText") or item.get("visualPrompt") or item.get("visual_prompt") or current.get("visual_prompt") or "").strip()
            if prompt:
                current["visual_prompt"] = prompt
            scenes[name] = current
        merged["scenes"] = list(scenes.values())

        props = {str(item.get("name") or "").strip(): dict(item) for item in merged.get("props") or [] if isinstance(item, dict) and str(item.get("name") or "").strip()}
        for character in merged.get("characters") or []:
            if not isinstance(character, dict):
                continue
            related = str(character.get("name") or "").strip()
            for name in cls._split_names(character.get("fixed_props")):
                current = props.get(name) or {"name": name, "kind": "人物固定道具", "count": 1}
                current["kind"] = current.get("kind") or "人物固定道具"
                current["related_character"] = current.get("related_character") or related
                current["count"] = current.get("count") or 1
                props[name] = current
        for item in cls._named_items(recipe.get("props")):
            name = str(item.get("name")).strip()
            current = props.get(name) or {"name": name, "count": 1}
            description = str(item.get("description") or "").strip()
            if description:
                current["description"] = description
            kind = str(item.get("kind") or item.get("type") or current.get("kind") or "").strip()
            if kind:
                current["kind"] = kind
            related = str(item.get("related_character") or item.get("relatedCharacter") or current.get("related_character") or "").strip()
            if related:
                current["related_character"] = related
            current["count"] = current.get("count") or 1
            props[name] = current
        merged["props"] = list(props.values())
        episodes = [item for item in (merged.get("episodes") or []) if isinstance(item, dict)]
        total_shots = sum(int(item.get("shots_count") or len(item.get("shots") or [])) for item in episodes)
        merged["summary"] = (
            f"共解析出 {len(episodes)} 集剧情、{total_shots} 个分镜头；"
            f"识别到 {len(merged.get('characters') or [])} 位主要人物、{len(merged.get('scenes') or [])} 处拍摄场景、{len(merged.get('props') or [])} 件核心道具。"
        )
        return merged

    @staticmethod
    def _recipe_text(recipe: dict[str, Any]) -> str:
        script = recipe.get("script") or {}
        full_story = str(script.get("fullStory") or "")
        shots = [shot for shot in flatten_recipe_shots(recipe) if isinstance(shot, dict)]
        lines = [f"# {script.get('title') or '未命名剧本'}", "", str(script.get("summary") or "")]
        lines.extend(AiGenerationService._asset_markdown(recipe))
        if not shots:
            body = full_story.strip()
            # 剧本阶段可能已把「### 镜头」写进正文，但还没有结构化 shots；
            # 补上「# 第1集」以免内容库解析器抽不出分集。
            has_shots = "###" in body and "镜头" in body
            has_episode = "第" in body and "集" in body and any(
                line.lstrip().startswith("#") and "第" in line and "集" in line
                for line in body.splitlines()
            )
            if has_shots and not has_episode:
                lines.extend(["", f"# 第1集 {script.get('title') or '第 1 集'}", "", body])
            else:
                lines.extend(["", body])
            return "\n".join(lines).strip()
        # 按已确认的分集大纲把 fullStory 切回各集文本，与镜头一起按集落进文档。
        # 优先消费 episodes agent 写入的 recipe["episodes"]，避免文档与分镜各切一遍。
        from ...director_agents import _episodes_for_storyboard

        story_episodes = _episodes_for_storyboard(recipe, full_story)
        story_by_num = {ep["num"]: ep for ep in story_episodes}
        grouped: dict[int, list[dict[str, Any]]] = {}
        for shot in shots:
            try:
                ep_num = int(shot.get("episodeNumber") or shot.get("episode") or 1)
            except (TypeError, ValueError):
                ep_num = 1
            grouped.setdefault(ep_num, []).append(shot)
        shot_index = {id(shot): number for number, shot in enumerate(shots, 1)}
        all_nums = sorted(set(story_by_num) | set(grouped)) or [1]
        for ep_num in all_nums:
            episode = story_by_num.get(ep_num) or {}
            title = str(episode.get("title") or (shots[0].get("episodeTitle") if grouped.get(ep_num) else "") or f"第 {ep_num} 集")
            lines.extend(["", f"# 第{ep_num}集 {title}"])
            episode_text = str(episode.get("text") or "").strip()
            if episode_text and not AiGenerationService._text_has_shot_cards(episode_text):
                lines.extend(["", episode_text])
            for shot in grouped.get(ep_num) or []:
                index = shot_index.get(id(shot), 0)
                lines.extend(AiGenerationService._recipe_shot_lines(shot, index))
        return "\n".join(lines).strip()

    @classmethod
    def persist_recipe_assets(cls, project_id: str, recipe: dict[str, Any] | None) -> int:
        recipe = recipe if isinstance(recipe, dict) else {}
        ts = now_str()
        written = 0
        for kind, items in (
            ("character", recipe.get("characters") or []),
            ("scene", recipe.get("locations") or []),
            ("prop", recipe.get("props") or []),
        ):
            for item in cls._named_items(items):
                name = str(item.get("name")).strip()
                existing = query_one("SELECT id,description,visual_prompt FROM ai_project_assets WHERE project_id=%s AND kind=%s AND name=%s LIMIT 1", (project_id, kind, name))
                spec = item.get("identitySpec") if isinstance(item.get("identitySpec"), dict) else {}
                description = str(item.get("description") or item.get("appearance") or item.get("details") or "").strip()
                prompt = str(item.get("visualPrompt") or item.get("visual_prompt") or item.get("promptText") or item.get("prompt_text") or description).strip()
                role = str(item.get("role") or item.get("type") or spec.get("ageRange") or "").strip()
                if existing:
                    execute_sql("UPDATE ai_project_assets SET role=COALESCE(NULLIF(role,''),%s),description=COALESCE(NULLIF(description,''),%s),visual_prompt=COALESCE(NULLIF(visual_prompt,''),%s),updated_at=%s WHERE id=%s", (role, description, prompt, ts, existing["id"]))
                else:
                    ProjectDetailService.create_asset(project_id, {"kind": kind, "name": name, "role": role, "description": description, "visual_prompt": prompt})
                written += 1
        return written

    def _adapt_recipe(self, project_id: str | None, recipe: dict[str, Any], stage: str) -> None:
        if not project_id:
            return
        script = recipe.get("script") or {}
        raw_text = self._recipe_text(recipe)
        analysis = self.merge_recipe_assets_into_analysis(StandardScriptParser.parse(raw_text), recipe)
        existing_doc = query_one("SELECT id FROM ai_project_documents WHERE project_id=%s AND input_mode='ai_pipeline' ORDER BY updated_at DESC LIMIT 1", (project_id,))
        ts = now_str()
        if existing_doc:
            execute_sql("UPDATE ai_project_documents SET filename=%s,file_size=%s,raw_text=%s,analysis_json=%s,visual_style=%s,updated_at=%s WHERE id=%s", (script.get("title") or "AI 生成剧本", len(raw_text.encode("utf-8")), raw_text, json.dumps(analysis, ensure_ascii=False), str((recipe.get("artStyle") or {}).get("name_zh") or ""), ts, existing_doc["id"]))
        else:
            execute_sql("INSERT INTO ai_project_documents (id,project_id,filename,file_size,input_mode,status,spine_template,visual_style,raw_text,analysis_json,created_at,updated_at) VALUES (%s,%s,%s,%s,'ai_pipeline','ready','drama',%s,%s,%s,%s,%s)", (f"doc-{uuid.uuid4().hex[:12]}", project_id, script.get("title") or "AI 生成剧本", len(raw_text.encode("utf-8")), str((recipe.get("artStyle") or {}).get("name_zh") or ""), raw_text, json.dumps(analysis, ensure_ascii=False), ts, ts))

        self.persist_recipe_assets(project_id, recipe)
        if stage in {"episodes", "storyboard"}:
            asset_rows = query_all(
                "SELECT id, kind, name, image_url, extra_json FROM ai_project_assets WHERE project_id=%s",
                (project_id,),
            )
            char_map = asset_name_id_map(asset_rows, "character")
            scene_map = asset_name_id_map(asset_rows, "scene")
            prop_map = asset_name_id_map(asset_rows, "prop")
            grouped: dict[int, list[dict[str, Any]]] = {}
            for shot in flatten_recipe_shots(recipe):
                if not isinstance(shot, dict):
                    continue
                ep_num = int(shot.get("episodeNumber") or shot.get("episode") or 1)
                grouped.setdefault(ep_num, []).append(shot)
            outline_by_num: dict[int, dict[str, Any]] = {}
            for item in recipe.get("episodes") or []:
                if not isinstance(item, dict):
                    continue
                try:
                    num = int(item.get("num") or 0)
                except (TypeError, ValueError):
                    continue
                if num > 0:
                    outline_by_num[num] = item
            for ep_num in sorted(set(grouped) | set(outline_by_num)):
                shots = grouped.get(ep_num) or []
                outline = outline_by_num.get(ep_num) or {}
                episode = query_one("SELECT id FROM ai_project_episodes WHERE project_id=%s AND episode_num=%s LIMIT 1", (project_id, ep_num))
                title = str(outline.get("title") or (shots[0].get("episodeTitle") if shots else "") or f"第 {ep_num} 集")
                script_text = str(outline.get("text") or outline.get("summary") or "")
                if shots:
                    inherited_scene_name = ""
                    inherited_scene_id = None
                    beats = []
                    for i, shot in enumerate(shots):
                        beat = self._beat_payload(
                            shot,
                            i + 1,
                            project_id,
                            char_map=char_map,
                            scene_map=scene_map,
                            prop_map=prop_map,
                            inherited_scene_name=inherited_scene_name,
                            inherited_scene_id=inherited_scene_id,
                        )
                        if str(shot.get("locationName") or shot.get("scene") or "").strip():
                            inherited_scene_name = str(beat.get("scene") or "")
                            inherited_scene_id = beat.get("scene_id")
                        beats.append(beat)
                    data = {
                        "beats": beats,
                        "summary": str(outline.get("summary") or ""),
                        "targetShots": outline.get("targetShots") or 0,
                    }
                    if not script_text:
                        script_text = "\n".join(str(shot.get("description") or shot.get("action") or "") for shot in shots)
                    shots_count = len(shots)
                else:
                    data = {
                        "beats": [],
                        "summary": str(outline.get("summary") or ""),
                        "targetShots": outline.get("targetShots") or 0,
                    }
                    shots_count = 0
                if episode:
                    execute_sql(
                        "UPDATE ai_project_episodes SET title=COALESCE(NULLIF(title,''),%s),status='script_ready',script_text=%s,shots_count=%s,data_json=%s,updated_at=%s WHERE id=%s",
                        (title, script_text, shots_count, json.dumps(data, ensure_ascii=False), ts, episode["id"]),
                    )
                else:
                    eid = f"ep-{uuid.uuid4().hex[:12]}"
                    execute_sql(
                        "INSERT INTO ai_project_episodes (id,project_id,episode_num,title,status,script_text,shots_count,data_json,created_at,updated_at) VALUES (%s,%s,%s,%s,'script_ready',%s,%s,%s,%s,%s)",
                        (eid, project_id, ep_num, title, script_text, shots_count, json.dumps(data, ensure_ascii=False), ts, ts),
                    )

    @staticmethod
    def _beat_payload(
        shot: dict[str, Any],
        sequence: int,
        project_id: str,
        *,
        char_map: dict[str, str] | None = None,
        scene_map: dict[str, str] | None = None,
        prop_map: dict[str, str] | None = None,
        inherited_scene_name: str = "",
        inherited_scene_id: str | None = None,
    ) -> dict[str, Any]:
        chars = shot.get("characterNames") or shot.get("characters") or []
        props = shot.get("propNames") or shot.get("props") or []
        action = str(shot.get("description") or shot.get("action") or "").strip()
        dialogue = str(shot.get("dialogue") or "").strip()
        prompt = AiGenerationService._shot_visual_prompt(shot)
        camera = AiGenerationService._format_shot_camera(shot.get("camera")) or "中景"
        audio = str(shot.get("soundscape") or shot.get("audio") or "").strip()
        explicit_scene = str(shot.get("locationName") or shot.get("scene") or "").strip()
        scene_name, scene_id = resolve_shot_scene(
            explicit_scene, scene_map or {}, inherited_scene_name, inherited_scene_id
        )
        video_prompt_zh = " ".join(
            part for part in (
                action,
                f"运镜：{camera}" if camera else "",
                f"声音：{audio}" if audio else "",
            ) if part
        ) or dialogue or prompt
        return {
            "id": f"beat-{uuid.uuid4().hex[:12]}",
            "sequence": sequence,
            "kind": "dialogue" if dialogue else "action",
            "heading": str(shot.get("title") or shot.get("heading") or f"分镜 {sequence}"),
            "speaker": str(shot.get("speaker") or (chars[0] if chars else "")),
            "dialogue": dialogue,
            "action": action,
            "camera": camera,
            "audio": audio,
            "characters": chars,
            "character_ids": match_named_asset_ids(chars, char_map or {}),
            "scene": scene_name,
            "scene_id": scene_id,
            "props": props,
            "prop_ids": match_named_asset_ids(props, prop_map or {}),
            "visual_prompt": prompt,
            "sketch_prompt": prompt,
            "video_prompt_zh": video_prompt_zh,
            "video_duration": str(AiGenerationService._shot_duration_seconds(shot)),
            "status": "draft",
        }

    async def stream(self, operation_id: str, project_id: str, request: Any, since: int = 0):
        queue, replay = self.events.subscribe(operation_id, since=max(0, since))
        try:
            for event in replay:
                yield event
                if event.get("terminal"):
                    return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    current = self._public(self._read(operation_id, project_id))
                    if current["status"] in {"succeeded", "failed", "cancelled"}:
                        yield terminal_event_for_status(current["status"], result=current.get("result"), message=current.get("error"))
                        return
                    yield {"event": "keep-alive", "data": {}}
                    continue
                if event is None:
                    return
                yield event
                if event.get("terminal"):
                    return
        finally:
            self.events.unsubscribe(operation_id, queue)
