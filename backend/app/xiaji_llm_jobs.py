from __future__ import annotations

import json
import uuid
from typing import Any

from .llm_client import LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS, llm_error_raw
from .storage import now

KIND_LABELS = {
    "ingest": "内容导入",
    "script": "生成脚本",
    "voice": "声线定义",
    "video_prompt": "镜头视频提示词",
    "compose": "合成成片",
}

PARAMETER_LABELS = {
    "kind": "任务类型",
    "model": "模型",
    "base_url": "接口地址",
    "temperature": "temperature",
    "max_tokens": "max_tokens",
    "timeout_seconds": "timeout_seconds",
    "system_prompt": "系统提示词",
    "user_prompt": "用户提示词",
    "messages": "完整 messages",
    "response": "模型输出",
    "document_id": "文档 ID",
    "filename": "文件名",
    "source_format": "源格式",
    "char_count": "字数",
    "chapter_count": "章节数",
    "target_episodes": "目标集数",
    "spine_template": "项目类型",
    "visual_style": "视觉风格",
    "art_style_id": "画风",
    "narration_style": "解说人称",
    "ethnicity": "人物族裔",
    "episode_id": "剧集 ID",
    "episode_number": "集数",
    "title": "标题",
    "summary": "摘要",
    "original_lines": "原文行",
    "line_count": "原文行数",
    "script_mode": "脚本模式",
    "characters": "角色名单",
    "scenes": "场景名单",
    "props": "道具名单",
    "name_to_asset": "名称到资产映射",
    "prompt_version": "提示词版本",
    "asset_id": "资产 ID",
    "asset_kind": "资产类型",
    "beat_id": "镜头 ID",
    "duration": "时长",
    "route": "视频路由",
    "family": "工作流",
    "pictures": "参考图职责",
    "prompt_zh": "中文提示词",
    "prompt_en": "英文提示词",
    "name": "名称",
    "role": "定位",
    "gender": "性别",
    "age_group": "年龄段",
    "description": "外貌与性格",
    "purpose": "用途",
    "resolution": "分辨率",
    "add_subtitles": "烧录字幕",
    "clip_count": "拼接镜头数",
    "compose_url": "成片地址",
    "compose_filename": "成片文件名",
    "compose_duration_sec": "成片时长",
}

SQLITE_LLM_JOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS xiaji_llm_jobs (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    prompt TEXT NOT NULL,
    system_prompt TEXT,
    messages_json TEXT,
    parameters_json TEXT NOT NULL,
    response_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xiaji_llm_jobs_project
    ON xiaji_llm_jobs(project_id, created_at);
"""


def _parse_json(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    text = "" if raw is None else str(raw)
    if not text.strip():
        return fallback
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return raw if fallback is None else fallback
    if fallback is None:
        return parsed
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def llm_failure_response(error: Exception | None) -> dict[str, str] | None:
    raw = llm_error_raw(error)
    if not raw:
        return None
    return {"raw": raw}


def llm_runtime_snapshot(app: Any, *, temperature: float, max_tokens: int) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout_seconds": LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
        "model": "",
        "base_url": "",
    }
    provider = getattr(app.state, "llm_provider", None)
    store = getattr(provider, "store", None) if provider is not None else None
    getter = getattr(store, "get_llm_settings", None) if store is not None else None
    if callable(getter):
        try:
            config = getter() or {}
        except Exception:
            config = {}
        snapshot["model"] = str(config.get("model") or "")
        snapshot["base_url"] = str(config.get("base_url") or "")
        snapshot["enabled"] = bool(config.get("enabled"))
    return snapshot


def _messages_prompt(messages: list[dict[str, str]]) -> tuple[str, str]:
    system = ""
    user_parts: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role == "system" and not system:
            system = content
        elif role == "user":
            user_parts.append(content)
    return system, "\n\n".join(user_parts)


def flatten_parameters(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for name, value in payload.items():
        items.append(
            {
                "name": name,
                "label": PARAMETER_LABELS.get(name, name),
                "value": value,
            }
        )
    return items


class XiajiLlmJobStore:
    def __init__(self, database: Any) -> None:
        from .db import Database, open_database

        self._db = database if isinstance(database, Database) else open_database(database)
        self.initialize()

    def initialize(self) -> None:
        with self._db.connection() as connection:
            if self._db.dialect == "mysql":
                self._db.apply_mysql_schema(connection)
            else:
                connection.executescript(SQLITE_LLM_JOB_SCHEMA)

    def create(
        self,
        *,
        owner_user_id: str,
        project_id: str,
        kind: str,
        target: str,
        title: str,
        prompt: str,
        system_prompt: str = "",
        messages: list[dict[str, str]] | None = None,
        parameters: dict[str, Any] | None = None,
        model: str = "",
        status: str = "running",
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:16]
        timestamp = now()
        payload = dict(parameters or {})
        payload.setdefault("kind", kind)
        if model:
            payload.setdefault("model", model)
        if system_prompt:
            payload.setdefault("system_prompt", system_prompt)
        if prompt:
            payload.setdefault("user_prompt", prompt)
        if messages is not None:
            payload.setdefault("messages", messages)
        with self._db.connection() as connection:
            connection.execute(
                """INSERT INTO xiaji_llm_jobs (
                    id, owner_user_id, project_id, kind, target, title, status, progress,
                    model, prompt, system_prompt, messages_json, parameters_json,
                    response_json, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)""",
                (
                    job_id,
                    owner_user_id,
                    project_id,
                    kind,
                    target[:512],
                    title[:255],
                    status,
                    10 if status == "running" else 0,
                    model,
                    prompt,
                    system_prompt,
                    _dump(messages or []),
                    _dump(payload),
                    timestamp,
                    timestamp,
                ),
            )
        return self.get(job_id)

    def set_progress(self, job_id: str, progress: int, *, message: str | None = None) -> dict[str, Any] | None:
        row = self.get(job_id)
        if row is None:
            return None
        parameters = dict(row.get("options") or {})
        if message:
            parameters["progress_message"] = message
        timestamp = now()
        clamped = max(0, min(99, int(progress)))
        with self._db.connection() as connection:
            connection.execute(
                """UPDATE xiaji_llm_jobs SET progress = ?, parameters_json = ?, updated_at = ?
                   WHERE id = ?""",
                (clamped, _dump(parameters), timestamp, job_id),
            )
        return self.get(job_id)

    def finish(
        self,
        job_id: str,
        *,
        status: str,
        response: Any = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        row = self.get(job_id)
        if row is None:
            return None
        parameters = dict(row.get("options") or {})
        if response is not None:
            parameters["response"] = response
        timestamp = now()
        progress = 100 if status == "succeeded" else row.get("progress") or 0
        with self._db.connection() as connection:
            connection.execute(
                """UPDATE xiaji_llm_jobs SET status = ?, progress = ?, parameters_json = ?,
                    response_json = ?, error = ?, updated_at = ? WHERE id = ?""",
                (
                    status,
                    progress,
                    _dump(parameters),
                    _dump(response) if response is not None else row.get("response_json"),
                    error,
                    timestamp,
                    job_id,
                ),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._db.connection() as connection:
            row = connection.execute("SELECT * FROM xiaji_llm_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._from_row(row) if row else None

    def list_project_jobs(self, owner_user_id: str, project_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM xiaji_llm_jobs
                   WHERE owner_user_id = ? AND project_id = ?
                   ORDER BY created_at DESC""",
                (owner_user_id, project_id),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def _from_row(self, row: Any) -> dict[str, Any]:
        parameters = _parse_json(row["parameters_json"], {})
        messages = _parse_json(row["messages_json"], [])
        response = _parse_json(row["response_json"], None) if row["response_json"] else None
        if response is None and "response" in parameters:
            response = parameters.get("response")
        compose_url = ""
        if isinstance(response, dict):
            compose_url = str(response.get("compose_url") or "").strip()
        if not compose_url:
            compose_url = str(parameters.get("compose_url") or "").strip()
        outputs = []
        if compose_url:
            outputs = [{"kind": "video", "cloud_url": compose_url, "download_url": compose_url}]
        kind = row["kind"]
        return {
            "id": row["id"],
            "job_id": row["id"],
            "owner_user_id": row["owner_user_id"],
            "project_id": row["project_id"],
            "kind": kind,
            "source": "llm",
            "target": row["target"],
            "slot": kind,
            "slot_label": KIND_LABELS.get(kind, kind),
            "title": row["title"],
            "status": row["status"],
            "progress": row["progress"] or 0,
            "mode": "xiaji-compose" if kind == "compose" else "xiaji-llm",
            "model": row["model"] or "",
            "prompt": row["prompt"] or "",
            "system_prompt": row["system_prompt"] or "",
            "messages": messages,
            "parameters": flatten_parameters(parameters),
            "options": parameters,
            "response": response,
            "llm_output": response if kind != "compose" else None,
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "job_created_at": row["created_at"],
            "job_updated_at": row["updated_at"],
            "bound_url": compose_url,
            "preview_url": compose_url,
            "outputs": outputs,
            "reference_count": 0,
            "references": [],
            "negative_prompt": "",
            "image_size": None,
            "missing": False,
        }


def llm_jobs_store(app: Any) -> XiajiLlmJobStore | None:
    store = getattr(app.state, "xiaji_llm_job_store", None)
    return store if isinstance(store, XiajiLlmJobStore) else None


def start_xiaji_llm_job(
    app: Any,
    *,
    owner_user_id: str,
    project_id: str,
    kind: str,
    target: str,
    title: str,
    messages: list[dict[str, str]],
    parameters: dict[str, Any],
    temperature: float,
    max_tokens: int,
) -> str | None:
    store = llm_jobs_store(app)
    if store is None:
        return None
    runtime = llm_runtime_snapshot(app, temperature=temperature, max_tokens=max_tokens)
    system_prompt, user_prompt = _messages_prompt(messages)
    payload = {**runtime, **parameters, "kind": kind, "messages": messages}
    if system_prompt:
        payload["system_prompt"] = system_prompt
    if user_prompt:
        payload["user_prompt"] = user_prompt
    created = store.create(
        owner_user_id=owner_user_id,
        project_id=project_id,
        kind=kind,
        target=target,
        title=title,
        prompt=user_prompt,
        system_prompt=system_prompt,
        messages=messages,
        parameters=payload,
        model=str(runtime.get("model") or ""),
        status="running",
    )
    return str(created["id"])


def start_xiaji_tracked_job(
    app: Any,
    *,
    owner_user_id: str,
    project_id: str,
    kind: str,
    target: str,
    title: str,
    prompt: str = "",
    parameters: dict[str, Any] | None = None,
) -> str | None:
    store = llm_jobs_store(app)
    if store is None:
        return None
    payload = dict(parameters or {})
    payload["kind"] = kind
    created = store.create(
        owner_user_id=owner_user_id,
        project_id=project_id,
        kind=kind,
        target=target,
        title=title,
        prompt=prompt,
        system_prompt="",
        messages=[],
        parameters=payload,
        model="",
        status="running",
    )
    return str(created["id"])


def set_xiaji_job_progress(app: Any, job_id: str | None, progress: int, *, message: str | None = None) -> None:
    if not job_id:
        return
    store = llm_jobs_store(app)
    if store is None:
        return
    store.set_progress(job_id, progress, message=message)


def finish_xiaji_llm_job(
    app: Any,
    job_id: str | None,
    *,
    status: str,
    response: Any = None,
    error: str | None = None,
) -> None:
    if not job_id:
        return
    store = llm_jobs_store(app)
    if store is None:
        return
    store.finish(job_id, status=status, response=response, error=error)
