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
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .config import settings

HYPIT_SCHEMA_VERSION = 1
HYPIT_JOB_STATUSES = ("idle", "running", "done", "failed")
HYPIT_LANGUAGES = ("zh", "en")
# Semantic canvas presets. Do not expose a raw MP number box; labels show pixels.
# 9:16 sizes match provider-comfy-h3 h3Dimensions (32-pixel grid).
HYPIT_H3_QUALITY_DEFAULT = "safe"
HYPIT_H3_QUALITIES: dict[str, dict[str, Any]] = {
    "safe": {"megapixels": 0.6, "width": 608, "height": 1056, "label": "16GB 稳妥"},
    "balanced": {"megapixels": 0.7, "width": 640, "height": 1152, "label": "均衡"},
    "official": {"megapixels": 0.98, "width": 768, "height": 1344, "label": "官方 768P"},
}
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


def normalize_h3_quality(value: Any) -> str:
    key = _text(value)
    return key if key in HYPIT_H3_QUALITIES else HYPIT_H3_QUALITY_DEFAULT


def hypit_h3_quality_preset(value: Any) -> dict[str, Any]:
    return HYPIT_H3_QUALITIES[normalize_h3_quality(value)]


def stamp_hypit_job_progress(
    job: dict[str, Any],
    *,
    progress: int | None = None,
    message: str | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Write live progress onto transcript/compile so a later page load can resume the bar."""
    if progress is not None:
        job["progress"] = max(0, min(100, int(progress)))
    if message is not None:
        job["message"] = _text(message) or None
    if operation_id is not None:
        job["operationId"] = _text(operation_id) or None
    return job


def empty_hypit_payload(*, title: str = "") -> dict[str, Any]:
    return {
        "kind": "hypit_replication",
        "schemaVersion": HYPIT_SCHEMA_VERSION,
        "title": title,
        "brief": "",
        "language": "zh",
        "h3Quality": HYPIT_H3_QUALITY_DEFAULT,
        "workspacePath": None,
        "sourceVideo": None,
        "transcript": {
            "status": "idle",
            "path": None,
            "url": None,
            "wordCount": 0,
            "durationSec": 0.0,
            "error": None,
            "operationId": None,
            "progress": 0,
            "message": None,
        },
        "compile": {
            "status": "idle",
            "buildId": None,
            "operationId": None,
            "error": None,
            "progress": 0,
            "message": None,
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
    base["h3Quality"] = normalize_h3_quality(raw.get("h3Quality"))
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
        "operationId": _text(transcript.get("operationId")) or None,
        "progress": max(0, min(100, int(_number(transcript.get("progress"), 0)))),
        "message": _text(transcript.get("message")) or None,
    }

    compile_info = _as_dict(raw.get("compile")) or base["compile"]
    c_status = _text(compile_info.get("status")) or "idle"
    base["compile"] = {
        "status": c_status if c_status in HYPIT_JOB_STATUSES else "idle",
        "buildId": _text(compile_info.get("buildId")) or None,
        "operationId": _text(compile_info.get("operationId")) or None,
        "error": _text(compile_info.get("error")) or None,
        "progress": max(0, min(100, int(_number(compile_info.get("progress"), 0)))),
        "message": _text(compile_info.get("message")) or None,
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


def classify_hypit_command(command: str) -> str | None:
    """Classify a process command line: build, execution-worker, pool-worker, or None."""
    text = command or ""
    if "hypit" not in text.lower():
        return None
    if "--execution-root" in text:
        return "execution-worker"
    if "_worker" in text:
        return "pool-worker"
    if re.search(r"hypit(?:\.cmd|\.mjs)?[\"']?\s+build\b", text, re.IGNORECASE):
        return "build"
    return None


def command_mentions_path(command: str, path: Path) -> bool:
    resolved = str(path)
    variants = (
        resolved.lower(),
        resolved.replace("\\", "/").lower(),
        resolved.replace("/", "\\").lower(),
    )
    hay = command.lower().replace("/", "\\")
    return any(item.replace("/", "\\") in hay for item in variants)


def pids_to_reap_for_workspace(
    processes: list[tuple[int, str]],
    workspace: Path,
    *,
    ignore_pids: set[int] | None = None,
) -> list[int]:
    """Leftover `hypit build` for this project, plus execution workers if no other build is live."""
    ignore = ignore_pids or set()
    builds_here: list[int] = []
    other_builds = False
    execution: list[int] = []
    for pid, command in processes:
        if pid in ignore:
            continue
        kind = classify_hypit_command(command)
        if kind == "build" and command_mentions_path(command, workspace):
            builds_here.append(pid)
        elif kind == "build":
            other_builds = True
        elif kind == "execution-worker":
            execution.append(pid)
    pids = list(builds_here)
    if not other_builds:
        pids.extend(execution)
    return sorted(set(pids))


def pids_of_unattached_execution_workers(
    processes: list[tuple[int, str]],
    *,
    ignore_build_pids: set[int] | None = None,
) -> list[int]:
    """Execution workers that are still polling after every `hypit build --follow` has died."""
    ignore = ignore_build_pids or set()
    if any(
        pid not in ignore and classify_hypit_command(command) == "build"
        for pid, command in processes
    ):
        return []
    return [
        pid
        for pid, command in processes
        if classify_hypit_command(command) == "execution-worker"
    ]


def list_os_processes() -> list[tuple[int, str]]:
    try:
        return _list_os_processes()
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []


def _list_os_processes() -> list[tuple[int, str]]:
    if os.name == "nt":
        completed = subprocess.run(
            ["wmic", "process", "get", "ProcessId,CommandLine", "/FORMAT:LIST"],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
        rows: list[tuple[int, str]] = []
        pid: int | None = None
        command = ""
        for raw in (completed.stdout or "").splitlines():
            line = raw.strip()
            if not line:
                if pid is not None:
                    rows.append((pid, command))
                pid = None
                command = ""
                continue
            if line.lower().startswith("commandline="):
                command = line.split("=", 1)[1]
            elif line.lower().startswith("processid="):
                try:
                    pid = int(line.split("=", 1)[1])
                except ValueError:
                    pid = None
        if pid is not None:
            rows.append((pid, command))
        return rows
    completed = subprocess.run(
        ["ps", "-ax", "-o", "pid=", "-o", "args="],
        capture_output=True,
        text=True,
        timeout=20,
        encoding="utf-8",
        errors="replace",
    )
    rows = []
    for raw in (completed.stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        pid_text, _, rest = line.partition(" ")
        try:
            rows.append((int(pid_text), rest.strip()))
        except ValueError:
            continue
    return rows


def kill_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return
    try:
        os.kill(pid, 15)
    except OSError:
        return


def reap_hypit_compile_orphans(
    workspace: Path,
    *,
    processes: list[tuple[int, str]] | None = None,
    ignore_pids: set[int] | None = None,
) -> list[int]:
    """Kill leftover Hypit build/executors that would block the next compile's H3 slot."""
    snapshot = list_os_processes() if processes is None else processes
    pids = pids_to_reap_for_workspace(snapshot, workspace, ignore_pids=ignore_pids)
    for pid in pids:
        kill_process_tree(pid)
    return pids


def reap_unattached_execution_workers(
    *,
    processes: list[tuple[int, str]] | None = None,
    ignore_build_pids: set[int] | None = None,
) -> list[int]:
    snapshot = list_os_processes() if processes is None else processes
    pids = pids_of_unattached_execution_workers(
        snapshot, ignore_build_pids=ignore_build_pids,
    )
    for pid in pids:
        kill_process_tree(pid)
    return pids


def write_hypit_compile_runtime(workspace: Path, *, megapixels: float) -> Path:
    """Copy the POC runtime and override H3 megapixels for this compile only."""
    source = hypit_runtime_path()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {"format": "hypit.runtime-local@1", "endpoints": {}, "bindings": {}}
    if not isinstance(payload, dict):
        payload = {"format": "hypit.runtime-local@1", "endpoints": {}, "bindings": {}}
    data_root = payload.get("dataRoot")
    if isinstance(data_root, str) and data_root.strip() and not Path(data_root).is_absolute():
        payload["dataRoot"] = str((hypit_poc_root() / data_root).resolve())
    endpoints = payload.get("endpoints")
    if not isinstance(endpoints, dict):
        endpoints = {}
        payload["endpoints"] = endpoints
    comfy = endpoints.get("comfy.h3")
    if not isinstance(comfy, dict):
        comfy = {"use": "@zly/provider-comfy-h3", "config": {}}
        endpoints["comfy.h3"] = comfy
    config = comfy.get("config")
    if not isinstance(config, dict):
        config = {}
        comfy["config"] = config
    config["megapixels"] = float(megapixels)
    dest = workspace / "notes" / "hypit.runtime.overlay.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def run_hypit(
    subcommand: str,
    extra: list[str],
    *,
    workspace: Path,
    timeout: int,
    on_output: Callable[[str], None] | None = None,
    extra_env: dict[str, str] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_pid: Callable[[int], None] | None = None,
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
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        shell=False,
    )
    if on_pid is not None:
        on_pid(proc.pid)
    chunks: list[str] = []

    def reader() -> None:
        stream = proc.stdout
        if stream is None:
            return
        for line in stream:
            chunks.append(line)
            if on_output is None:
                continue
            try:
                on_output("".join(chunks)[-800:])
            except Exception:
                continue

    thread = threading.Thread(target=reader, name=f"hypit-{subcommand}-stdout", daemon=True)
    thread.start()
    deadline = time.monotonic() + max(1, int(timeout))
    cancelled = False
    try:
        while proc.poll() is None:
            if cancel_check is not None and cancel_check():
                cancelled = True
                kill_process_tree(proc.pid)
                break
            if time.monotonic() > deadline:
                kill_process_tree(proc.pid)
                thread.join(timeout=5)
                raise HypitError(f"hypit {subcommand} 超时（{timeout}s），已结束后台进程")
            time.sleep(0.4)
        thread.join(timeout=8)
        combined = "".join(chunks).strip()
        if cancelled:
            reap_unattached_execution_workers(ignore_build_pids={proc.pid})
            raise HypitError("操作已取消，已结束后台 Hypit 进程")
        if proc.returncode not in (0, None):
            reap_unattached_execution_workers(ignore_build_pids={proc.pid})
            raise HypitError(combined[-1200:] or f"hypit {subcommand} 失败（exit {proc.returncode}）")
        if on_output and combined:
            on_output(combined[-800:])
        return combined
    finally:
        if proc.poll() is None:
            kill_process_tree(proc.pid)
            reap_unattached_execution_workers(ignore_build_pids={proc.pid})


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
