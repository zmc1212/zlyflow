from __future__ import annotations

import os
from pathlib import Path


SIDECAR_HOST = os.getenv("ZLY_AI_VIDEO_STUDIO_INDEXTTS_HOST", "127.0.0.1").strip() or "127.0.0.1"
SIDECAR_PORT = int(os.getenv("ZLY_AI_VIDEO_STUDIO_INDEXTTS_PORT", "7866") or "7866")
DEFAULT_ORIGIN = f"http://{SIDECAR_HOST}:{SIDECAR_PORT}"


def workbench_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def default_index_tts_root() -> Path:
    override = (os.getenv("ZLY_AI_VIDEO_STUDIO_INDEXTTS_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (workbench_dir().parent / "整合包及模型" / "index-tts").resolve()


def checkpoints_dir(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else default_index_tts_root()
    if (base / "config.yaml").is_file():
        return base
    nested = base / "checkpoints"
    if nested.is_dir() or not base.is_dir():
        return nested
    return base


def config_path(root: Path | None = None) -> Path:
    directory = checkpoints_dir(root)
    named = directory / "config.yaml"
    if named.is_file():
        return named
    return directory / "config.yaml"


def default_speaker_prompt(root: Path | None = None) -> Path | None:
    override = (os.getenv("ZLY_AI_VIDEO_STUDIO_INDEXTTS_DEFAULT_PROMPT") or "").strip()
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    base = Path(root) if root is not None else default_index_tts_root()
    candidates.extend(
        [
            base / "examples" / "voice_01.wav",
            base / "examples" / "voice_01.mp3",
            checkpoints_dir(base).parent / "examples" / "voice_01.wav",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def checkpoints_ready(root: Path | None = None) -> bool:
    directory = checkpoints_dir(root)
    return directory.is_dir() and config_path(root).is_file()
