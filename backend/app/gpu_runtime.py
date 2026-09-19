from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar

import requests

from .tts_provider import INDEXTTS_DEFAULT_BASE_URL, detect_tts_provider, free_indextts_sidecar

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_OWNER = ""
T = TypeVar("T")


def gpu_owner() -> str:
    return _OWNER


def free_comfy() -> bool:
    try:
        from .media_studio.services.comfy_service import ComfyService

        url = str(ComfyService.get_config().base_url or "").rstrip("/")
        if not url:
            return False
        response = requests.post(
            f"{url}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=8,
        )
        return bool(response.ok)
    except Exception:
        logger.debug("ComfyUI /free skipped", exc_info=True)
        return False


def free_indextts() -> bool:
    try:
        from .media_studio.provider_bridge import tts_row
        from .tts_provider import sidecar_origin

        row = tts_row() or {}
        base_url = str(row.get("base_url") or INDEXTTS_DEFAULT_BASE_URL)
        model = str(row.get("model") or "")
        if detect_tts_provider(base_url=base_url, model=model) != "indextts":
            return False
        return free_indextts_sidecar(base_url or sidecar_origin(base_url))
    except Exception:
        logger.debug("IndexTTS /free skipped", exc_info=True)
        return False


@contextmanager
def occupy_gpu(owner: str) -> Iterator[None]:
    """Serialize H3 (ComfyUI) and IndexTTS on the same card.

    TTS jobs free ComfyUI before cloning. Comfy / worker H3 jobs free IndexTTS
    before submitting a prompt. The lock is held for the whole inference so the
    two engines cannot share a 4090.
    """
    global _OWNER
    with _LOCK:
        previous = _OWNER
        if owner == "tts":
            free_comfy()
        elif owner == "comfy":
            free_indextts()
        _OWNER = owner
        try:
            yield
        finally:
            _OWNER = previous


def idle_run(callback: Callable[[], T]) -> T | None:
    """Run a GPU-idle side effect (Comfy `/free`) only when H3/TTS are not occupying the card."""
    if not _LOCK.acquire(blocking=False):
        return None
    try:
        if _OWNER:
            return None
        return callback()
    finally:
        _LOCK.release()
