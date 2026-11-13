"""Shared helpers for tests that temporarily replace dependencies on app.state.

Several test classes swap services (store, auth_store, providers, ...) directly
onto ``app.state`` in ``setUp``, and a few drive the full lifespan via
``with TestClient(main_module.app)``. Without restoring afterwards, the swapped
instances keep pointing at already-deleted temp databases and leak into later
tests in the same process (full-suite ordering failures). Use these helpers to
snapshot the previous values and put them back afterwards.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from backend.app.cloud_video_service import CloudVideoService
from backend.app.music_job_service import MusicJobService

# Every app.state dependency any test (or the lifespan) swaps out.
APP_STATE_ATTRS = (
    "auth_store",
    "store",
    "llm_provider",
    "vlm_provider",
    "tts_provider",
    "director_assistant",
    "worker",
    "music_jobs",
    "grs_provider",
    "comfy_provider",
    "resource_storage",
    "ffmpeg_runner",
    "cloud_video",
)

# Class-level singletons configured by the lifespan and by some tests directly.
_SINGLETON_ATTRS = {
    CloudVideoService: ("_instance",),
    MusicJobService: ("_store", "_credentials", "_resource_storage"),
}


def snapshot_app_state(app: Any, *names: str) -> dict[str, Any]:
    """Capture app.state attributes plus the configured service singletons."""
    snapshot: dict[str, Any] = {
        f"state:{name}": (hasattr(app.state, name), getattr(app.state, name, None))
        for name in (names or APP_STATE_ATTRS)
    }
    for cls, attrs in _SINGLETON_ATTRS.items():
        for attr in attrs:
            snapshot[f"cls:{cls.__name__}.{attr}"] = getattr(cls, attr, None)
    return snapshot


def restore_app_state(app: Any, snapshot: dict[str, Any]) -> None:
    """Put previously captured attributes and singletons back in place."""
    for key, value in snapshot.items():
        if key.startswith("state:"):
            name = key[len("state:") :]
            existed, previous = value
            if existed:
                setattr(app.state, name, previous)
            elif hasattr(app.state, name):
                delattr(app.state, name)
        elif key.startswith("cls:"):
            owner_name, attr = key[len("cls:") :].rsplit(".", 1)
            for cls, _attrs in _SINGLETON_ATTRS.items():
                if cls.__name__ == owner_name:
                    setattr(cls, attr, value)
                    break


@contextmanager
def isolated_lifespan_state(app: Any) -> Iterator[None]:
    """Guard for ``with TestClient(app)`` blocks that run the full lifespan.

    The lifespan replaces every app.state dependency and reconfigures the
    CloudVideoService / MusicJobService singletons with the settings active at
    that moment (often a temp workspace in tests). Snapshot everything before
    entering and put it back on exit so later tests are unaffected.
    """
    snapshot = snapshot_app_state(app)
    try:
        yield
    finally:
        restore_app_state(app, snapshot)
