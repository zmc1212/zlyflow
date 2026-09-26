from __future__ import annotations

import asyncio
import copy
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..db import execute_sql, now_str, query_all, query_one, transaction_cursor
from .script_development import VERSION, develop_story, digest, plan_story, validate_plan
from .script_parser import StandardScriptParser


class ScriptDevelopmentService:
    JOB_TYPE = "script_development"
    _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="script-development")
    _lock = threading.RLock()

    @staticmethod
    def document(project_id: str, doc_id: str) -> dict:
        row = query_one("SELECT * FROM ai_project_documents WHERE id=%s AND project_id=%s", (doc_id, project_id))
        if not row:
            raise ValueError("剧本文档不存在")
        return row

    @staticmethod
    def fingerprint(row: dict) -> str:
        analysis = json.loads(row.get("analysis_json") or "{}")
        return digest({"source": row.get("raw_text"), "adopted": analysis.get("script_development")})

    @classmethod
    def get(cls, project_id: str, doc_id: str, job_id: str | None = None) -> dict | None:
        cls.document(project_id, doc_id)
        rows = query_all("SELECT * FROM ai_project_jobs WHERE project_id=%s AND job_type=%s ORDER BY created_at DESC", (project_id, cls.JOB_TYPE))
        for row in rows:
            data = json.loads(row.get("payload_json") or "{}")
            if data.get("document_id") == doc_id and (not job_id or row["id"] == job_id):
                return {"job_id": row["id"], "status": row["status"], "error": row.get("error_message"), "data": data}
        if job_id:
            raise ValueError("剧本发展任务不存在")
        return None

    @classmethod
    def start(cls, project_id: str, doc_id: str, preferences: dict) -> dict:
        with cls._lock:
            row = cls.document(project_id, doc_id)
            existing = cls.get(project_id, doc_id)
            if existing and existing["status"] in {"queued", "running", "awaiting_review"}:
                return existing
            jid = f"job-{uuid.uuid4().hex[:12]}"
            analysis = json.loads(row.get("analysis_json") or "{}")
            accepted = analysis.get("script_development") or {}
            project = query_one("SELECT settings_json FROM ai_projects WHERE id=%s", (project_id,)) or {}
            settings = json.loads(project.get("settings_json") or "{}")
            settings = {**settings, **(settings.get("extra") or {})}
            defaults = {k: settings[k] for k in ("episode_count", "duration_seconds", "episode_duration", "target_duration") if settings.get(k) is not None}
            preferences = {**defaults, **{k: v for k, v in preferences.items() if v is not None}}
            data = {"version": VERSION, "document_id": doc_id, "source": accepted.get("script_text") or row["raw_text"],
                    "source_fingerprint": cls.fingerprint(row), "preferences": preferences, "phase": "planning",
                    "message": "正在诊断剧本并策划全剧"}
            execute_sql("INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,payload_json,created_at,updated_at) VALUES (%s,%s,%s,%s,'queued',0,%s,%s,%s)",
                        (jid, project_id, cls.JOB_TYPE, "剧本发展: " + row["filename"], json.dumps(data, ensure_ascii=False), now_str(), now_str()))
            cls._executor.submit(cls.run, project_id, doc_id, jid)
            return cls.get(project_id, doc_id, jid)

    @classmethod
    def save(cls, project_id: str, jid: str, data: dict, status: str = "running", error: str | None = None) -> None:
        execute_sql("UPDATE ai_project_jobs SET payload_json=%s,status=%s,error_message=%s,updated_at=%s WHERE id=%s AND project_id=%s",
                    (json.dumps(data, ensure_ascii=False), status, error, now_str(), jid, project_id))

    @classmethod
    def check_source(cls, project_id: str, doc_id: str, data: dict) -> None:
        if cls.fingerprint(cls.document(project_id, doc_id)) != data["source_fingerprint"]:
            raise ValueError("SOURCE_CONFLICT: 已采纳剧本或原稿发生变化，请重新策划")

    @classmethod
    def run(cls, project_id: str, doc_id: str, jid: str) -> None:
        # Atomic claim prevents duplicate workers, including retries and double clicks.
        if not execute_sql("UPDATE ai_project_jobs SET status='running' WHERE id=%s AND project_id=%s AND status='queued'", (jid, project_id)):
            return
        data = cls.get(project_id, doc_id, jid)["data"]
        try:
            cls.check_source(project_id, doc_id, data)
            if data["phase"] == "planning":
                data["plan"] = plan_story(data["source"], data.get("preferences"))
                data.update(phase="plan_review", message="请确认主线、分集钩子与时长，再开始扩写")
            else:
                develop_story(data, lambda s: cls.save(project_id, jid, s), check=lambda: cls.check_source(project_id, doc_id, data))
            cls.check_source(project_id, doc_id, data)
            cls.save(project_id, jid, data, "awaiting_review")
        except Exception as err:
            cls.save(project_id, jid, data, "failed", str(err))

    @classmethod
    def action(cls, project_id: str, doc_id: str, jid: str, body: dict) -> dict:
        with cls._lock:
            job = cls.get(project_id, doc_id, jid)
            data = copy.deepcopy(job["data"])
            action = body.get("action")
            if job["status"] in {"queued", "running"}:
                raise ValueError("创作正在进行，请等待当前步骤完成")
            if job["status"] == "succeeded":
                if action == "apply":
                    return job
                raise ValueError("该版本已经采纳，请开始新的策划")
            cls.check_source(project_id, doc_id, data)
            if body.get("revision") != digest(job["data"]):
                raise ValueError("VERSION_CONFLICT: 页面版本已变化，请刷新后再操作")
            if action == "confirm_plan" and data["phase"] == "plan_review":
                data.update(plan=validate_plan(body.get("plan") or data["plan"]), phase="writing")
                data["plan"]["scale_reason"] = "用户已确认以上集数与各集时长，扩写与审稿不得自行更改。"
                data["message"] = "已确认策划，正在准备逐集扩写"
            elif action == "revise" and data["phase"] == "script_review":
                targets = body.get("episode_numbers") or []
                if not targets or any(type(n) is not int or not 1 <= n <= len(data["episodes"]) for n in targets):
                    raise ValueError("请选择有效的待修订集")
                if not str(body.get("feedback") or "").strip():
                    raise ValueError("请填写修订要求")
                data.setdefault("draft_history", []).append({"episodes": copy.deepcopy(data["episodes"]), "reviews": data.get("reviews", [])})
                data.update(phase="writing", revision_episodes=targets, revised_episodes=[], feedback=body["feedback"],
                            review_complete=False, review_round=0, repair_done=[], reviews=[])
                data.pop("pending_review", None)
            elif action == "retry" and job["status"] == "failed":
                pass
            elif action == "apply" and data["phase"] == "script_review":
                cls.apply(project_id, doc_id, jid, data)
                return cls.get(project_id, doc_id, jid)
            elif action == "keep_original" and data["phase"] == "plan_review":
                data.update(script_text=data["source"], episodes=[], unresolved_issues=[], phase="script_review", kept_original=True)
                cls.apply(project_id, doc_id, jid, data)
                return cls.get(project_id, doc_id, jid)
            else:
                raise ValueError("当前步骤不支持此操作")
            cls.save(project_id, jid, data, "queued")
            cls._executor.submit(cls.run, project_id, doc_id, jid)
            return cls.get(project_id, doc_id, jid)

    @classmethod
    def apply(cls, project_id: str, doc_id: str, jid: str, data: dict) -> None:
        row = cls.document(project_id, doc_id)
        cls.check_source(project_id, doc_id, data)
        old = json.loads(row.get("analysis_json") or "{}")
        analysis = StandardScriptParser.parse(data["script_text"])
        for kind in ("characters", "scenes", "props"):
            merged = {x["name"]: x for x in analysis.get(kind, []) if isinstance(x, dict) and x.get("name")}
            for ep in data.get("episodes", []):
                for asset in (ep.get("assets") or {}).get(kind, []):
                    if isinstance(asset, dict) and asset.get("name"):
                        merged[str(asset["name"])] = asset
            analysis[kind] = list(merged.values())
        previous = old.get("script_development") or {}
        accepted = {"version": VERSION, "revision": int(previous.get("revision", 0)) + 1, "job_id": jid,
                    "script_text": data["script_text"], "plan": data["plan"], "unresolved_issues": data.get("unresolved_issues", []),
                    "history": [*previous.get("history", []), {k: v for k, v in previous.items() if k != "history"}] if previous else []}
        analysis["script_development"] = accepted
        for ep in analysis.get("episodes") or []:
            spec = next((s for s in data["plan"]["episodes"] if s["episode_num"] == ep.get("episode_num")), {})
            ep["dramatic_design"] = spec
        data.update(phase="adopted", message="已采纳剧本，进入剧集工坊规划镜头")
        with transaction_cursor() as cursor:
            cursor.execute("UPDATE ai_project_documents SET analysis_json=%s,status='awaiting_aspect',updated_at=%s WHERE id=%s AND project_id=%s AND raw_text=%s AND analysis_json=%s",
                           (json.dumps(analysis, ensure_ascii=False), now_str(), doc_id, project_id, row["raw_text"], row["analysis_json"]))
            if cursor.rowcount != 1:
                raise ValueError("SOURCE_CONFLICT: 文档已变化，请刷新")
            from .workshop_service import WorkshopService
            WorkshopService.bind_adopted(cursor, project_id, doc_id, analysis)
            cursor.execute("SELECT id,data_json FROM ai_project_episodes WHERE project_id=%s", (project_id,))
            for episode in cursor.fetchall():
                edata = json.loads(episode.get("data_json") or "{}")
                if edata.get("source_document_id") == doc_id and edata.get("script_revision") != accepted["revision"]:
                    edata["script_stale"] = {"document_id": doc_id, "revision": accepted["revision"]}
                    cursor.execute("UPDATE ai_project_episodes SET data_json=%s,updated_at=%s WHERE id=%s", (json.dumps(edata, ensure_ascii=False), now_str(), episode["id"]))
            cursor.execute("UPDATE ai_project_jobs SET status='succeeded',progress=100,payload_json=%s,updated_at=%s WHERE id=%s AND project_id=%s",
                           (json.dumps(data, ensure_ascii=False), now_str(), jid, project_id))

    @classmethod
    def public(cls, job: dict | None) -> dict | None:
        if not job:
            return None
        return {**job, "revision": digest(job["data"])}

    @classmethod
    async def stream(cls, job_id: str, project_id: str, request: Any, since: int = 0):
        last = ""
        while not await request.is_disconnected():
            row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s AND job_type=%s", (job_id, project_id, cls.JOB_TYPE))
            if not row:
                raise ValueError("剧本发展任务不存在")
            data = json.loads(row["payload_json"])
            stamp = digest({"data": data, "status": row["status"]})
            if stamp != last:
                terminal = row["status"] not in {"queued", "running"}
                yield {"event": "done" if terminal else "status", "terminal": terminal,
                       "data": {"status": row["status"], "message": data.get("message"), "phase": data["phase"]}}
                last = stamp
                if terminal:
                    return
            await asyncio.sleep(1)

    @classmethod
    def recover_interrupted_jobs(cls) -> None:
        execute_sql("UPDATE ai_project_jobs SET status='failed',error_message=%s WHERE job_type=%s AND status IN ('running','queued')",
                    ("服务重启，已保留完成的集与审稿检查点，请重试", cls.JOB_TYPE))
