from __future__ import annotations

import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parent / "data" / "logs"
LOG_FILE = LOG_DIR / "server.log"
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT: dict[str, tuple[str, float]] = {}
_HEARTBEAT_STARTED = False


def setup_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if getattr(root, "_ai_media_configured", False):
        return LOG_FILE
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s %(threadName)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=8,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    root._ai_media_configured = True  # type: ignore[attr-defined]
    logging.getLogger("server").info("file log -> %s pid=%s", LOG_FILE, os.getpid())
    return LOG_FILE


def track_request_start(request_id: str, path: str) -> None:
    with _INFLIGHT_LOCK:
        _INFLIGHT[request_id] = (path, time.monotonic())


def track_request_end(request_id: str) -> None:
    with _INFLIGHT_LOCK:
        _INFLIGHT.pop(request_id, None)


def inflight_snapshot() -> list[tuple[str, int]]:
    now = time.monotonic()
    with _INFLIGHT_LOCK:
        return [(path, int(now - started)) for path, started in _INFLIGHT.values()]


def start_heartbeat() -> None:
    global _HEARTBEAT_STARTED
    if _HEARTBEAT_STARTED:
        return
    _HEARTBEAT_STARTED = True
    logger = logging.getLogger("server.heartbeat")

    def _loop() -> None:
        while True:
            time.sleep(15)
            items = inflight_snapshot()
            hung = [f"{path} {age}s" for path, age in items if age >= 8]
            logger.info("alive pid=%s inflight=%s hung=%s", os.getpid(), len(items), hung or "-")

    thread = threading.Thread(target=_loop, name="heartbeat", daemon=True)
    thread.start()


def debugger_hint() -> dict[str, Any]:
    return {
        "debugpy": "debugpy" in sys.modules or "pydevd" in sys.modules,
        "pid": os.getpid(),
        "ppid": os.getppid(),
    }
