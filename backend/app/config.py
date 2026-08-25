from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_DIR = Path(__file__).resolve().parents[2]
DATABASE_FILENAME = "zly-ai-video-studio.db"
LEGACY_DATABASE_FILENAME = "".join(("toon", "flow.db"))


@dataclass(frozen=True)
class Settings:
    workspace_dir: Path = WORKSPACE_DIR
    comfy_url: str = os.getenv("ZLY_AI_VIDEO_STUDIO_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
    public_api_prefix: str = os.getenv("ZLY_AI_VIDEO_STUDIO_PUBLIC_API_PREFIX", "/api").rstrip("/") or "/api"
    resource_provider: str = os.getenv("ZLY_AI_VIDEO_STUDIO_RESOURCE_PROVIDER", "browser-stream")
    secure_cookies: bool = os.getenv("ZLY_AI_VIDEO_STUDIO_SECURE_COOKIES", "false").lower() in {"1", "true", "yes"}
    data_dir_override: str | None = os.getenv("ZLY_AI_VIDEO_STUDIO_DATA_DIR")
    comfy_root_override: str | None = os.getenv("ZLY_AI_VIDEO_STUDIO_COMFY_ROOT")
    credential_key_override: str | None = os.getenv("ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY")
    grs_poll_interval_seconds: int = int(os.getenv("ZLY_AI_VIDEO_STUDIO_GRS_POLL_INTERVAL_SECONDS", "5"))
    grs_timeout_seconds: int = int(os.getenv("ZLY_AI_VIDEO_STUDIO_GRS_TIMEOUT_SECONDS", "43200"))
    grs_max_concurrency: int = int(os.getenv("ZLY_AI_VIDEO_STUDIO_GRS_MAX_CONCURRENCY", "4"))

    @property
    def credential_key(self) -> str | None:
        if self.credential_key_override:
            return self.credential_key_override
        key_path = self.data_dir / "credential.key"
        try:
            from .local_credential_key import ensure_local_credential_key
            return ensure_local_credential_key(key_path)
        except Exception:
            return None

    @property
    def results_dir(self) -> Path:
        return self.workspace_dir / "results"


    @property
    def data_dir(self) -> Path:
        return Path(self.data_dir_override).resolve() if self.data_dir_override else self.workspace_dir / "data"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def comfy_output_dir(self) -> Path:
        # The local ComfyUI bundle sits next to the workbench directory. This
        # must be derived from this settings instance so /app is also valid in Docker.
        root = (
            Path(self.comfy_root_override).resolve()
            if self.comfy_root_override
            else self.workspace_dir.parent / "整合包及模型" / "comfyui-integrate-v1.3" / "comfyui-integrate" / "Comfyui"
        )
        return root / "output"

    @property
    def database_path(self) -> Path:
        data_dir = self.data_dir
        database_path = data_dir / DATABASE_FILENAME
        legacy_path = data_dir / LEGACY_DATABASE_FILENAME
        if database_path.exists() or not legacy_path.exists():
            return database_path
        for suffix in ("", "-wal", "-shm"):
            source = legacy_path.with_name(f"{legacy_path.name}{suffix}")
            if source.exists():
                source.replace(database_path.with_name(f"{database_path.name}{suffix}"))
        return database_path

    @property
    def frontend_dist_dir(self) -> Path:
        return self.workspace_dir / "frontend" / "dist"


settings = Settings()
