# -*- coding: utf-8 -*-
"""复刻台（shot_replication）payload 模型与文件助手。

参考片 → 拉片分析（分镜/提示词/深度视频/主体清单）→ VACE 深度控制转绘。
payload 存于 director_projects.payload_json，kind = "shot_replication"，
与 recipe/batch 并列，互不影响。
"""
from __future__ import annotations

import secrets
import shutil
from pathlib import Path
from typing import Any

from .config import settings

REPLICATION_SCHEMA_VERSION = 1
REPLICATION_SHOT_STATUSES = ("idle", "ready", "queued", "running", "succeeded", "failed")
REPLICATION_ANALYSIS_STATUSES = ("idle", "running", "done", "failed")
REPLICATION_ENGINES = ("vace_depth", "h3_r2v")
REPLICATION_ARTIFACT_SLOTS = ("segment", "depth", "key0", "key1")

_MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
_ALLOWED_SOURCE_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v"}


class ReplicationError(ValueError):
    """复刻 payload 校验或文件操作失败。"""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _flag(value: Any, default: bool) -> bool:
    return bool(value) if isinstance(value, bool) else default


def new_replication_shot_id() -> str:
    return f"rshot_{secrets.token_hex(4)}"


def empty_replication_payload(*, title: str = "") -> dict[str, Any]:
    return {
        "kind": "shot_replication",
        "schemaVersion": REPLICATION_SCHEMA_VERSION,
        "title": title,
        "sourceVideo": None,
        "analysis": {
            "status": "idle",
            "mode": "smart",
            "segmentSeconds": 15,
            "sceneThreshold": 0.35,
            "depthStatus": "idle",
            "depthPath": None,
            "depthUrl": None,
            "visionModel": None,
            "error": None,
            "startedAt": None,
            "finishedAt": None,
        },
        "renderSettings": {
            "engine": "vace_depth",
            "keepFirstFrame": True,
            "artStyle": "",
            "vaceStrength": 1.0,
            "steps": 30,
            "seed": None,
        },
        "subjects": [],
        "shots": [],
    }


def normalize_replication_take(raw: Any, index: int) -> dict[str, Any]:
    source = _as_dict(raw)
    status = _text(source.get("status")) or "queued"
    return {
        "id": _text(source.get("id")) or f"take_{index + 1}_{secrets.token_hex(3)}",
        "takeNumber": int(_number(source.get("takeNumber"), index + 1)),
        "jobId": _text(source.get("jobId")) or None,
        "videoUrl": _text(source.get("videoUrl")) or None,
        "outputPath": _text(source.get("outputPath")) or None,
        "status": status,
        "progress": int(_number(source.get("progress"), 0)),
        "error": _text(source.get("error")) or None,
        "createdAt": _text(source.get("createdAt")) or None,
        "promptSnapshot": _text(source.get("promptSnapshot")) or None,
        "workflowId": _text(source.get("workflowId")) or None,
        "videoWorkflowFamily": _text(source.get("videoWorkflowFamily")) or None,
        "options": _as_dict(source.get("options")),
    }


def normalize_replication_shot(raw: Any, index: int) -> dict[str, Any]:
    source = _as_dict(raw)
    shot_id = _text(source.get("id")) or new_replication_shot_id()
    time_start = _number(source.get("timeStart"), 0.0)
    time_end = _number(source.get("timeEnd"), 0.0)
    if time_end < time_start:
        time_start, time_end = time_end, time_start
    status = _text(source.get("status")) or "idle"
    if status not in REPLICATION_SHOT_STATUSES:
        status = "idle"
    takes = [
        normalize_replication_take(item, take_index)
        for take_index, item in enumerate(_as_list(source.get("takes")))
    ]
    bindings = [
        _text(item) for item in _as_list(source.get("subjectBindings")) if _text(item)
    ]
    return {
        "id": shot_id,
        "shotNumber": int(_number(source.get("shotNumber"), index + 1)),
        "timeStart": round(time_start, 3),
        "timeEnd": round(time_end, 3),
        "durationSec": round(max(0.0, time_end - time_start), 3),
        "segmentPath": _text(source.get("segmentPath")) or None,
        "segmentUrl": _text(source.get("segmentUrl")) or None,
        "keyframePaths": [
            _text(item) for item in _as_list(source.get("keyframePaths")) if _text(item)
        ],
        "keyframeUrls": [
            _text(item) for item in _as_list(source.get("keyframeUrls")) if _text(item)
        ],
        "depthPath": _text(source.get("depthPath")) or None,
        "depthUrl": _text(source.get("depthUrl")) or None,
        "promptText": _text(source.get("promptText")),
        "compiledPrompt": _text(source.get("compiledPrompt")),
        "negativePrompt": _text(source.get("negativePrompt")),
        "subjectBindings": bindings,
        "keepFirstFrame": _flag(source.get("keepFirstFrame"), True),
        "status": status,
        "jobId": _text(source.get("jobId")) or None,
        "progress": int(_number(source.get("progress"), 0)),
        "error": _text(source.get("error")) or None,
        "analysisNote": _text(source.get("analysisNote")) or None,
        "cameraNote": _text(source.get("cameraNote")) or None,
        "takes": takes,
    }


def normalize_replication_subject(raw: Any, index: int) -> dict[str, Any]:
    source = _as_dict(raw)
    subject_type = _text(source.get("type")) or "character"
    if subject_type not in {"character", "scene", "prop"}:
        subject_type = "prop"
    return {
        "id": _text(source.get("id")) or f"rsub_{secrets.token_hex(4)}",
        "name": _text(source.get("name")) or f"主体 {index + 1}",
        "type": subject_type,
        "description": _text(source.get("description")),
        "refPath": _text(source.get("refPath")) or None,
        "refUrl": _text(source.get("refUrl")) or None,
        "shotIds": [
            _text(item) for item in _as_list(source.get("shotIds")) if _text(item)
        ],
        "hidden": _flag(source.get("hidden"), False),
    }


def normalize_replication_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = _as_dict(payload)
    base = empty_replication_payload(title=_text(raw.get("title")))
    if not raw:
        return base

    source_video = _as_dict(raw.get("sourceVideo"))
    base["sourceVideo"] = {
        "path": _text(source_video.get("path")) or None,
        "url": _text(source_video.get("url")) or None,
        "name": _text(source_video.get("name")) or None,
        "width": int(_number(source_video.get("width"), 0)),
        "height": int(_number(source_video.get("height"), 0)),
        "fps": round(_number(source_video.get("fps"), 0), 3),
        "durationSec": round(_number(source_video.get("durationSec"), 0), 3),
    } if source_video else None

    analysis = _as_dict(raw.get("analysis")) or base["analysis"]
    status = _text(analysis.get("status")) or "idle"
    base["analysis"] = {
        "status": status if status in REPLICATION_ANALYSIS_STATUSES else "idle",
        "mode": "fixed" if _text(analysis.get("mode")) == "fixed" else "smart",
        "segmentSeconds": max(3.0, min(30.0, _number(analysis.get("segmentSeconds"), 15))),
        "sceneThreshold": max(0.05, min(0.95, _number(analysis.get("sceneThreshold"), 0.35))),
        "depthStatus": (
            _text(analysis.get("depthStatus"))
            if _text(analysis.get("depthStatus")) in REPLICATION_ANALYSIS_STATUSES
            else "idle"
        ),
        "depthPath": _text(analysis.get("depthPath")) or None,
        "depthUrl": _text(analysis.get("depthUrl")) or None,
        "visionModel": _text(analysis.get("visionModel")) or None,
        "error": _text(analysis.get("error")) or None,
        "startedAt": _text(analysis.get("startedAt")) or None,
        "finishedAt": _text(analysis.get("finishedAt")) or None,
    }

    settings = _as_dict(raw.get("renderSettings")) or base["renderSettings"]
    engine = _text(settings.get("engine")) or "vace_depth"
    base["renderSettings"] = {
        "engine": engine if engine in REPLICATION_ENGINES else "vace_depth",
        "keepFirstFrame": _flag(settings.get("keepFirstFrame"), True),
        "artStyle": _text(settings.get("artStyle")),
        "vaceStrength": max(0.05, min(1.0, _number(settings.get("vaceStrength"), 1.0))),
        "steps": int(max(4, min(60, _number(settings.get("steps"), 30)))),
        "seed": (
            int(_number(settings.get("seed"), 0))
            if settings.get("seed") is not None
            else None
        ),
    }

    base["subjects"] = [
        normalize_replication_subject(item, index)
        for index, item in enumerate(_as_list(raw.get("subjects")))
    ]
    base["shots"] = [
        normalize_replication_shot(item, index)
        for index, item in enumerate(_as_list(raw.get("shots")))
    ]
    return base


def flatten_replication_shots(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [shot for shot in _as_list(_as_dict(payload).get("shots")) if isinstance(shot, dict)]


def find_replication_shot(payload: dict[str, Any], shot_id: str) -> dict[str, Any] | None:
    for shot in flatten_replication_shots(payload):
        if _text(shot.get("id")) == shot_id:
            return shot
    return None


def find_replication_subject(payload: dict[str, Any], subject_id: str) -> dict[str, Any] | None:
    for subject in _as_list(_as_dict(payload).get("subjects")):
        if isinstance(subject, dict) and _text(subject.get("id")) == subject_id:
            return subject
    return None


def validate_source_video(filename: str, size: int | None) -> str:
    """校验上传的参考片文件名与大小，返回安全后缀。"""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in _ALLOWED_SOURCE_SUFFIXES:
        allowed = "、".join(sorted(_ALLOWED_SOURCE_SUFFIXES))
        raise ReplicationError(f"仅支持以下视频格式：{allowed}")
    if size is not None and size > _MAX_SOURCE_BYTES:
        raise ReplicationError("参考片不能超过 2GB。")
    return suffix


def replication_root(owner_user_id: str, project_id: str) -> Path:
    return Path(settings.uploads_dir) / owner_user_id / project_id / "replication"


def save_replication_source(
    owner_user_id: str,
    project_id: str,
    *,
    source: Path,
    original_name: str,
) -> tuple[Path, str]:
    """保存参考片源文件（原子替换），返回 (绝对路径, 同源 URL)。"""
    dest_dir = Path(settings.uploads_dir) / owner_user_id / project_id / "source"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"reference{source.suffix.lower() or '.mp4'}"
    pending = dest.with_name(f".{dest.name}.{secrets.token_hex(4)}.tmp")
    try:
        shutil.copy2(source, pending)
        pending.replace(dest)
    finally:
        pending.unlink(missing_ok=True)
    for leftover in dest_dir.glob("reference.*"):
        if leftover != dest:
            leftover.unlink(missing_ok=True)
    url = f"/api/director/replications/{project_id}/source"
    return dest, url


def save_replication_artifact(
    owner_user_id: str,
    project_id: str,
    shot_id: str,
    slot: str,
    *,
    source: Path,
) -> tuple[Path, str]:
    """保存某个分镜的拉片产物（片段/深度/关键帧），返回 (绝对路径, 同源 URL)。"""
    if slot not in REPLICATION_ARTIFACT_SLOTS:
        raise ReplicationError(f"未知的产品槽位：{slot}")
    root = replication_root(owner_user_id, project_id)
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{shot_id}_{slot}{source.suffix.lower() or '.mp4'}"
    pending = dest.with_name(f".{dest.name}.{secrets.token_hex(4)}.tmp")
    try:
        shutil.copy2(source, pending)
        pending.replace(dest)
    finally:
        pending.unlink(missing_ok=True)
    for leftover in root.glob(f"{shot_id}_{slot}.*"):
        if leftover != dest:
            leftover.unlink(missing_ok=True)
    url = f"/api/director/replications/{project_id}/shots/{shot_id}/{slot}"
    return dest, url


def save_replication_depth(
    owner_user_id: str,
    project_id: str,
    *,
    source: Path,
) -> tuple[Path, str]:
    """保存全片深度视频，返回 (绝对路径, 同源 URL)。"""
    root = replication_root(owner_user_id, project_id)
    root.mkdir(parents=True, exist_ok=True)
    dest = root / "depth_full.mp4"
    pending = dest.with_name(f".{dest.name}.{secrets.token_hex(4)}.tmp")
    try:
        shutil.copy2(source, pending)
        pending.replace(dest)
    finally:
        pending.unlink(missing_ok=True)
    url = f"/api/director/replications/{project_id}/depth"
    return dest, url


def find_replication_artifact_file(
    *,
    owner_user_id: str,
    project_id: str,
    shot_id: str,
    slot: str,
) -> Path | None:
    if slot not in REPLICATION_ARTIFACT_SLOTS:
        return None
    root = replication_root(owner_user_id, project_id)
    if not root.is_dir():
        return None
    matches = sorted(path for path in root.glob(f"{shot_id}_{slot}.*") if path.is_file())
    return matches[0] if matches else None


def find_replication_source_file(owner_user_id: str, project_id: str) -> Path | None:
    directory = Path(settings.uploads_dir) / owner_user_id / project_id / "source"
    if not directory.is_dir():
        return None
    matches = sorted(path for path in directory.glob("reference.*") if path.is_file())
    return matches[0] if matches else None


def find_replication_depth_file(owner_user_id: str, project_id: str) -> Path | None:
    path = replication_root(owner_user_id, project_id) / "depth_full.mp4"
    return path if path.is_file() else None
