from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class StoredResource:
    key: str
    local_path: Path | None
    source_info: dict | None = None


class ResourceStorage(Protocol):
    provider_id: str
    streams_outputs: bool
    retains_comfy_outputs: bool
    persistent_outputs: bool

    def store_bytes(self, prefix: str, source_filename: str, content: bytes) -> StoredResource: ...
    def create_reference(self, prefix: str, source_filename: str) -> StoredResource: ...
    def resolve(self, key: str) -> Path | None: ...
    def delete(self, key: str) -> bool: ...
    def download_url(self, key: str, expires_in_seconds: int = 300) -> str | None: ...
    def object_url(self, key: str) -> str | None: ...


class BrowserLocalStagingStorage:
    """Temporary server-side staging used until the browser confirms a local write."""

    provider_id = "browser-local"
    streams_outputs = False
    retains_comfy_outputs = False
    persistent_outputs = False

    def __init__(self, staging_dir: Path) -> None:
        self.staging_dir = staging_dir

    def store_bytes(self, prefix: str, source_filename: str, content: bytes) -> StoredResource:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(source_filename).suffix or ".bin"
        key = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}{suffix}"
        destination = self.staging_dir / key
        destination.write_bytes(content)
        return StoredResource(key=key, local_path=destination)

    def create_reference(self, prefix: str, source_filename: str) -> StoredResource:
        raise RuntimeError("browser-local provider does not support remote output references")

    def resolve(self, key: str) -> Path | None:
        if key != Path(key).name:
            return None
        candidate = (self.staging_dir / key).resolve()
        if candidate.parent != self.staging_dir.resolve() or not candidate.is_file():
            return None
        return candidate

    def delete(self, key: str) -> bool:
        path = self.resolve(key)
        if path is None:
            return False
        path.unlink(missing_ok=True)
        return True

    def download_url(self, key: str, expires_in_seconds: int = 300) -> str | None:
        return None

    def object_url(self, key: str) -> str | None:
        return None


class BrowserStreamStorage(BrowserLocalStagingStorage):
    """Keep completed output in ComfyUI and proxy it only while delivering to the employee."""

    provider_id = "browser-stream"
    streams_outputs = True
    retains_comfy_outputs = True

    def create_reference(self, prefix: str, source_filename: str) -> StoredResource:
        suffix = Path(source_filename).suffix or ".bin"
        key = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}{suffix}"
        return StoredResource(key=key, local_path=None)

    def delete(self, key: str) -> bool:
        # Intermediate files may still use staging; completed stream references have no local file to remove.
        if self.resolve(key) is not None:
            return super().delete(key)
        return key == Path(key).name


ResourceStorageFactory = Callable[[Path], ResourceStorage]
RESOURCE_STORAGE_PROVIDERS: dict[str, ResourceStorageFactory] = {
    BrowserLocalStagingStorage.provider_id: BrowserLocalStagingStorage,
    BrowserStreamStorage.provider_id: BrowserStreamStorage,
}


def register_resource_storage(provider_id: str, factory: ResourceStorageFactory) -> None:
    """Register an optional provider such as a Qiniu-backed implementation."""
    RESOURCE_STORAGE_PROVIDERS[provider_id] = factory


def resource_object_url(storage: Any | None, key: str | None) -> str | None:
    """Stable object URL for persistent providers; never a time-limited signed link."""
    if storage is None or not str(key or "").strip():
        return None
    getter = getattr(storage, "object_url", None)
    if not callable(getter):
        return None
    url = getter(str(key).strip())
    if not url:
        return None
    return str(url).strip() or None


def create_resource_storage(provider_id: str, staging_dir: Path) -> ResourceStorage:
    try:
        factory = RESOURCE_STORAGE_PROVIDERS[provider_id]
    except KeyError as error:
        available = ", ".join(sorted(RESOURCE_STORAGE_PROVIDERS))
        raise ValueError(f"未知资源存储 provider: {provider_id}；当前可用: {available}") from error
    return factory(staging_dir)
