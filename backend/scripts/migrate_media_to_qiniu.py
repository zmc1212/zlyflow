from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import settings
from backend.app.db import MysqlDatabase, mysql_settings_from_env_or_docs
from backend.app.storage import now


URL_KEYS = {
    "path", "image_path", "imageUrl", "image_url", "firstFrameUrl", "endFrameUrl",
    "outputVideoUrl", "videoUrl", "ttsUrl", "voicePreviewUrl", "audioUrl", "url",
    "coverUrl", "fileUrl",
}


def looks_like_object_key(value: str, prefix: str) -> bool:
    stripped = value.lstrip("/")
    return bool(prefix) and stripped.startswith(prefix.rstrip("/") + "/")


def looks_like_http(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://") or value.startswith("/api/")


_FILE_INDEX: dict[str, Path] | None = None


def media_file_index() -> dict[str, Path]:
    global _FILE_INDEX
    if _FILE_INDEX is not None:
        return _FILE_INDEX
    index: dict[str, Path] = {}
    for root in (settings.results_dir, settings.uploads_dir, settings.staging_dir):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                index.setdefault(path.name, path)
                try:
                    index.setdefault(str(path.resolve()), path)
                except OSError:
                    pass
    _FILE_INDEX = index
    return index


def find_local_file(value: str) -> Path | None:
    raw = Path(value)
    index = media_file_index()
    if raw.is_absolute() and raw.is_file():
        return raw
    resolved = (settings.workspace_dir / raw).resolve()
    if resolved.is_file():
        return resolved
    by_name = index.get(raw.name)
    if by_name is not None:
        return by_name
    return index.get(str(raw)) or index.get(value)


def upload_file(storage, local_path: Path, prefix: str) -> tuple[str, str | None]:
    stored = storage.store_bytes(prefix, local_path.name, local_path.read_bytes())
    return stored.key, storage.object_url(stored.key)


def looks_like_media_path(value: str) -> bool:
    if looks_like_http(value) or value.startswith("data:"):
        return False
    lower = value.lower()
    suffixes = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".mp4", ".webm", ".mov", ".mkv", ".mp3", ".wav", ".m4a", ".aac")
    if any(lower.split("?", 1)[0].endswith(suffix) for suffix in suffixes):
        return True
    return ("/" in value or "\\" in value) and find_local_file(value) is not None


def rewrite_string(value: str, storage, prefix: str, cache: dict[str, tuple[str, str | None]], stats: dict[str, int]) -> str:
    object_prefix = str(storage.config.get("object_prefix") or "")
    if looks_like_http(value) or looks_like_object_key(value, object_prefix) or not looks_like_media_path(value):
        stats["skipped"] += 1
        return value
    if value in cache:
        key, _cloud = cache[value]
        stats["reused"] += 1
        return key
    local = find_local_file(value)
    if local is None:
        stats["missing"] += 1
        return value
    resolved = str(local.resolve())
    if resolved in cache:
        key, cloud_url = cache[resolved]
        cache[value] = (key, cloud_url)
        stats["reused"] += 1
        return key
    key, cloud_url = upload_file(storage, local, prefix)
    cache[value] = (key, cloud_url)
    cache[resolved] = (key, cloud_url)
    stats["uploaded"] += 1
    print(f"  uploaded {local} -> {key}", flush=True)
    return key


def rewrite_value(value: Any, storage, prefix: str, cache: dict[str, tuple[str, str | None]], stats: dict[str, int]) -> Any:
    if isinstance(value, str):
        return rewrite_string(value, storage, prefix, cache, stats)
    if isinstance(value, list):
        return [rewrite_value(item, storage, prefix, cache, stats) for item in value]
    if isinstance(value, dict):
        updated = dict(value)
        for key, item in list(updated.items()):
            if key in URL_KEYS and isinstance(item, str) and item:
                new_value = rewrite_string(item, storage, prefix, cache, stats)
                updated[key] = new_value
                if key == "path" and new_value != item:
                    cloud = cache.get(item, (new_value, None))[1] or storage.object_url(new_value)
                    updated["delivery_status"] = "cloud"
                    if cloud:
                        updated["cloud_url"] = cloud
            else:
                updated[key] = rewrite_value(item, storage, prefix, cache, stats)
        return updated
    return value


def load_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def rewrite_json_column(db: MysqlDatabase, table: str, column: str, pk: str, storage, prefix: str, cache, stats) -> None:
    with db.connection() as connection:
        connection.execute("SET SESSION innodb_lock_wait_timeout = 5")
        rows = [{"id": row[pk], "payload": row[column]} for row in connection.execute(f"SELECT {pk}, {column} FROM {table}").fetchall()]
    for row in rows:
        parsed = load_json(row["payload"], [] if column.endswith("json") and "options" not in column else {})
        rewritten = rewrite_value(parsed, storage, prefix, cache, stats)
        if rewritten == parsed:
            continue
        with db.connection() as connection:
            connection.execute("SET SESSION innodb_lock_wait_timeout = 120")
            connection.execute(
                f"UPDATE {table} SET {column} = ? WHERE {pk} = ?",
                (dump_json(rewritten), row["id"]),
            )


def main() -> int:
    from backend.app.grs_provider import CredentialManager
    from backend.app.qiniu_storage import QiniuStorage

    mysql = MysqlDatabase(mysql_settings_from_env_or_docs())
    credentials = CredentialManager(settings.credential_key)
    with mysql.connection() as connection:
        row = connection.execute("SELECT * FROM qiniu_provider_settings WHERE id = 1").fetchone()
    if not row:
        print("七牛云配置不存在。跳过媒体迁移。")
        return 1
    access_key = credentials.decrypt(row.get("access_key_encrypted"))
    secret_key = credentials.decrypt(row.get("secret_key_encrypted"))
    if not (access_key and secret_key and row.get("bucket") and row.get("domain")):
        print("七牛云配置不完整（管理设置中需有 AK/SK/Bucket/域名）。跳过媒体迁移，未启用七牛。")
        return 1
    if not credentials.ready:
        print(f"无法解密七牛凭证: {credentials.error}。请保持本机 data/credential.key 不变。")
        return 1
    storage = QiniuStorage({
        "enabled": True,
        "access_key": access_key,
        "secret_key": secret_key,
        "bucket": row["bucket"],
        "region": row.get("region") or "z0",
        "domain": row["domain"],
        "object_prefix": row.get("object_prefix") or "zly-ai-video-studio/",
    })
    cache: dict[str, tuple[str, str | None]] = {}
    stats = {"uploaded": 0, "reused": 0, "skipped": 0, "missing": 0}
    rewrite_json_column(mysql, "generation_items", "outputs_json", "id", storage, "migrated-output", cache, stats)
    rewrite_json_column(mysql, "jobs", "outputs_json", "id", storage, "migrated-output", cache, stats)
    rewrite_json_column(mysql, "jobs", "references_json", "id", storage, "migrated-upload", cache, stats)
    rewrite_json_column(mysql, "job_rounds", "references_json", "id", storage, "migrated-upload", cache, stats)
    rewrite_json_column(mysql, "director_projects", "payload_json", "id", storage, "migrated-director", cache, stats)
    with mysql.connection() as connection:
        assets = connection.execute("SELECT id, image_path, image_url FROM director_library_assets").fetchall()
    for asset in assets:
        updates: dict[str, str] = {}
        if asset.get("image_path"):
            updates["image_path"] = rewrite_string(asset["image_path"], storage, "migrated-library", cache, stats)
        if asset.get("image_url") and not looks_like_http(str(asset.get("image_url") or "")):
            updates["image_url"] = rewrite_string(asset["image_url"], storage, "migrated-library", cache, stats)
        if updates:
            assignment = ", ".join(f"{key} = ?" for key in updates)
            with mysql.connection() as connection:
                connection.execute(
                    f"UPDATE director_library_assets SET {assignment} WHERE id = ?",
                    (*updates.values(), asset["id"]),
                )
    with mysql.connection() as connection:
        connection.execute(
            "UPDATE qiniu_provider_settings SET enabled = 1, updated_at = ? WHERE id = 1",
            (now(),),
        )
    print(
        "媒体迁移完成: "
        f"uploaded={stats['uploaded']} reused={stats['reused']} "
        f"skipped={stats['skipped']} missing={stats['missing']}"
    )
    print("已启用七牛云。本地 results/uploads 文件未删除。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
