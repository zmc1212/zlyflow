# -*- coding: utf-8 -*-
"""Hypit 复刻（hypit_replication）payload、工程目录与本机 CLI 封装。

与 shot_replication（VACE 锁运镜转绘）并列，不混 payload。工程文件落在
data/hypit/{user}/{project}，子进程调用本机 Hypit CLI（默认 D:\\zlyun\\hypit-poc），
禁止把 Hypit monorepo vendoring 进 backend/app。
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .config import settings

HYPIT_SCHEMA_VERSION = 1
HYPIT_JOB_STATUSES = ("idle", "running", "done", "failed")
HYPIT_LANGUAGES = ("zh", "en")
_MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
_ALLOWED_SOURCE_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v"}
_BUILD_ID_RE = re.compile(r"bld_[A-Za-z0-9_]+", re.IGNORECASE)
_DEFAULT_POC_ROOT = Path(r"D:\zlyun\hypit-poc")


class HypitError(ValueError):
    """Hypit payload 校验、文件或 CLI 失败。"""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def empty_hypit_payload(*, title: str = "") -> dict[str, Any]:
    return {
        "kind": "hypit_replication",
        "schemaVersion": HYPIT_SCHEMA_VERSION,
        "title": title,
        "brief": "",
        "language": "zh",
        "workspacePath": None,
        "sourceVideo": None,
        "transcript": {
            "status": "idle",
            "path": None,
            "url": None,
            "wordCount": 0,
            "durationSec": 0.0,
            "error": None,
        },
        "compile": {
            "status": "idle",
            "buildId": None,
            "error": None,
        },
        "result": {
            "path": None,
            "url": None,
            "buildId": None,
        },
    }


def normalize_hypit_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = _as_dict(payload)
    base = empty_hypit_payload(title=_text(raw.get("title")))
    if not raw:
        return base
    language = _text(raw.get("language")) or "zh"
    base["brief"] = _text(raw.get("brief"))
    base["language"] = language if language in HYPIT_LANGUAGES else "zh"
    base["workspacePath"] = _text(raw.get("workspacePath")) or None

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

    transcript = _as_dict(raw.get("transcript")) or base["transcript"]
    t_status = _text(transcript.get("status")) or "idle"
    base["transcript"] = {
        "status": t_status if t_status in HYPIT_JOB_STATUSES else "idle",
        "path": _text(transcript.get("path")) or None,
        "url": _text(transcript.get("url")) or None,
        "wordCount": int(_number(transcript.get("wordCount"), 0)),
        "durationSec": round(_number(transcript.get("durationSec"), 0), 3),
        "error": _text(transcript.get("error")) or None,
    }

    compile_info = _as_dict(raw.get("compile")) or base["compile"]
    c_status = _text(compile_info.get("status")) or "idle"
    base["compile"] = {
        "status": c_status if c_status in HYPIT_JOB_STATUSES else "idle",
        "buildId": _text(compile_info.get("buildId")) or None,
        "error": _text(compile_info.get("error")) or None,
    }

    result = _as_dict(raw.get("result")) or base["result"]
    base["result"] = {
        "path": _text(result.get("path")) or None,
        "url": _text(result.get("url")) or None,
        "buildId": _text(result.get("buildId")) or None,
    }
    return base


def validate_hypit_source_video(filename: str, size: int | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in _ALLOWED_SOURCE_SUFFIXES:
        allowed = "、".join(sorted(_ALLOWED_SOURCE_SUFFIXES))
        raise HypitError(f"仅支持以下视频格式：{allowed}")
    if size is not None and size > _MAX_SOURCE_BYTES:
        raise HypitError("参考片不能超过 2GB。")
    return suffix


def hypit_poc_root() -> Path:
    raw = os.getenv("ZLY_HYPIT_POC_ROOT", str(_DEFAULT_POC_ROOT))
    return Path(raw).expanduser().resolve()


def hypit_runtime_path() -> Path:
    override = os.getenv("ZLY_HYPIT_RUNTIME")
    if override:
        return Path(override).expanduser().resolve()
    return hypit_poc_root() / "hypit.runtime.json"


_DEFAULT_HYPIT_COMFY_URL = "http://192.168.10.54:8188"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def hypit_comfy_url() -> str:
    """H3 A-roll ComfyUI origin. Env override, else hypit.runtime.json comfy.h3, else LAN default."""
    override = os.getenv("ZLY_HYPIT_COMFY_URL", "").strip()
    if override:
        return override.rstrip("/")
    try:
        payload = json.loads(hypit_runtime_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _DEFAULT_HYPIT_COMFY_URL
    endpoints = payload.get("endpoints") if isinstance(payload, dict) else None
    comfy = endpoints.get("comfy.h3") if isinstance(endpoints, dict) else None
    config = comfy.get("config") if isinstance(comfy, dict) else None
    url = config.get("comfyUrl") if isinstance(config, dict) else None
    if isinstance(url, str) and url.strip():
        return url.strip().rstrip("/")
    return _DEFAULT_HYPIT_COMFY_URL


def hypit_comfy_is_local() -> bool:
    from urllib.parse import urlparse

    host = (urlparse(hypit_comfy_url()).hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def hypit_workspace(owner_user_id: str, project_id: str) -> Path:
    return Path(settings.data_dir) / "hypit" / owner_user_id / project_id


def ensure_hypit_workspace(owner_user_id: str, project_id: str) -> Path:
    root = hypit_workspace(owner_user_id, project_id)
    for name in ("samples", "notes", "authors", "runs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def save_hypit_source(
    owner_user_id: str,
    project_id: str,
    *,
    source: Path,
    original_name: str,
) -> tuple[Path, str]:
    root = ensure_hypit_workspace(owner_user_id, project_id)
    dest_dir = root / "samples"
    dest = dest_dir / f"source{source.suffix.lower() or '.mp4'}"
    pending = dest.with_name(f".{dest.name}.{secrets.token_hex(4)}.tmp")
    try:
        shutil.copy2(source, pending)
        pending.replace(dest)
    finally:
        pending.unlink(missing_ok=True)
    for leftover in dest_dir.glob("source.*"):
        if leftover != dest:
            leftover.unlink(missing_ok=True)
    url = f"/api/director/hypit/{project_id}/source"
    return dest, url


def find_hypit_source_file(owner_user_id: str, project_id: str) -> Path | None:
    directory = hypit_workspace(owner_user_id, project_id) / "samples"
    if not directory.is_dir():
        return None
    matches = sorted(path for path in directory.glob("source.*") if path.is_file())
    return matches[0] if matches else None


def find_hypit_transcript_file(owner_user_id: str, project_id: str) -> Path | None:
    path = hypit_workspace(owner_user_id, project_id) / "notes" / "transcript.json"
    return path if path.is_file() else None


def find_hypit_result_file(owner_user_id: str, project_id: str) -> Path | None:
    path = hypit_workspace(owner_user_id, project_id) / "notes" / "final.mp4"
    return path if path.is_file() else None


def find_hypit_svrun(workspace: Path) -> Path | None:
    runs = workspace / "runs"
    if not runs.is_dir():
        return None
    matches = sorted(path for path in runs.glob("*.svrun") if path.is_file())
    return matches[0] if matches else None


def svrun_output_name(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'output="([^"]+)"', text)
    return match.group(1) if match else "final.video"


def hypit_argv(*args: str) -> list[str]:
    override = os.getenv("ZLY_HYPIT_BIN")
    if override:
        return [override, *args]
    root = hypit_poc_root()
    local = root / "node_modules" / ".bin" / ("hypit.cmd" if os.name == "nt" else "hypit")
    if local.is_file():
        return [str(local), *args]
    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx") or shutil.which("npx")
    if not npx:
        raise HypitError("未找到本机 Hypit CLI（npx / node_modules/.bin/hypit）。请先在 D:\\zlyun\\hypit-poc 安装 POC。")
    return [npx, "--no", "--", "hypit", *args]


def run_hypit(
    subcommand: str,
    extra: list[str],
    *,
    workspace: Path,
    timeout: int,
    on_output: Callable[[str], None] | None = None,
) -> str:
    argv = hypit_argv(subcommand, *extra)
    if "--workspace" not in argv:
        argv.extend(["--workspace", str(workspace)])
    if subcommand in {"transcribe", "plan", "build", "pricing", "doctor"} and "--runtime" not in extra:
        argv.extend(["--runtime", str(hypit_runtime_path())])
    cwd = workspace if workspace.is_dir() else hypit_poc_root()
    if os.name == "nt" and str(argv[0]).lower().endswith((".cmd", ".bat")):
        argv = ["cmd.exe", "/c", *argv]
    env = os.environ.copy()
    env.setdefault("HF_HUB_DISABLE_XET", "1")
    completed = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        shell=False,
    )
    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if on_output and combined:
        on_output(combined[-800:])
    if completed.returncode != 0:
        raise HypitError(combined[-1200:] or f"hypit {subcommand} 失败（exit {completed.returncode}）")
    return combined


def summarize_transcript(path: Path) -> tuple[int, float]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, 0.0
    data = payload.get("data") if isinstance(payload, dict) else None
    body = data if isinstance(data, dict) else payload if isinstance(payload, dict) else {}
    words = body.get("words") if isinstance(body, dict) else None
    passages = body.get("passages") if isinstance(body, dict) else None
    word_count = len(words) if isinstance(words, list) else 0
    if word_count == 0 and isinstance(passages, list):
        word_count = sum(
            len(item.get("words") or [])
            for item in passages
            if isinstance(item, dict)
        )
    duration = 0.0
    if isinstance(passages, list) and passages:
        last = passages[-1] if isinstance(passages[-1], dict) else {}
        duration = _number(
            last.get("end") or last.get("end_seconds") or last.get("duration"),
            0.0,
        )
    if duration <= 0 and isinstance(body, dict):
        duration = _number(body.get("audio_seconds") or body.get("duration"), 0.0)
    return word_count, duration


def parse_build_id(text: str) -> str | None:
    matches = _BUILD_ID_RE.findall(text or "")
    return matches[-1] if matches else None


def reveal_hypit_workspace(owner_user_id: str, project_id: str) -> Path:
    root = ensure_hypit_workspace(owner_user_id, project_id)
    if sys.platform == "win32":
        os.startfile(root)  # noqa: S606 — local workbench folder reveal
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(root)])
    else:
        subprocess.Popen(["xdg-open", str(root)])
    return root
