from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .db import Database, open_database
from .storage import now
from .xiaji_asset_prompts import VOICE_SLOTS

ASSET_KINDS = ("character", "scene", "prop", "voice")

SQLITE_ASSET_SCHEMA = """
CREATE TABLE IF NOT EXISTS xiaji_assets (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    source_document_id TEXT,
    definition_json TEXT NOT NULL,
    image_job_id TEXT,
    image_object_key TEXT,
    image_url TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, kind, name)
);
CREATE INDEX IF NOT EXISTS idx_xiaji_assets_owner_kind
    ON xiaji_assets(owner_user_id, kind, updated_at);
CREATE TABLE IF NOT EXISTS xiaji_asset_media (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES xiaji_assets(id) ON DELETE CASCADE,
    media_kind TEXT NOT NULL,
    slot TEXT NOT NULL DEFAULT '',
    job_id TEXT,
    object_key TEXT,
    url TEXT,
    prompt TEXT,
    model TEXT,
    is_official INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xiaji_asset_media_asset
    ON xiaji_asset_media(asset_id, media_kind, created_at);
"""


def _parse_json(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        parsed = json.loads(raw or ("{}" if isinstance(fallback, dict) else "[]"))
    except json.JSONDecodeError:
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def empty_voice_profile() -> dict[str, str]:
    return {
        "language": "",
        "timbre": "",
        "pitch": "",
        "speaking_style": "",
        "sample_line": "",
        "tts_voice": "",
        "prompt": "",
    }


def default_look() -> dict[str, str]:
    return {
        "id": f"look-{uuid.uuid4().hex[:10]}",
        "name": "基础造型",
        "appearance_details": "",
        "image_url": "",
        "job_id": "",
    }


class XiajiAssetStore:
    def __init__(self, database: Database | Path) -> None:
        self._db = database if isinstance(database, Database) else open_database(database)
        self.initialize()

    def initialize(self) -> None:
        with self._db.connection() as connection:
            if self._db.dialect == "mysql":
                self._db.apply_mysql_schema(connection)
            else:
                connection.executescript(SQLITE_ASSET_SCHEMA)

    def _media_for(self, connection: Any, asset_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM xiaji_asset_media WHERE asset_id = ? ORDER BY created_at DESC",
            (asset_id,),
        ).fetchall()
        items = []
        for row in rows:
            items.append(
                {
                    "id": row["id"],
                    "media_kind": row["media_kind"],
                    "slot": row["slot"] or "",
                    "job_id": row["job_id"],
                    "object_key": row["object_key"],
                    "url": row["url"],
                    "prompt": row["prompt"],
                    "model": row["model"],
                    "is_official": bool(row["is_official"]),
                    "created_at": row["created_at"],
                }
            )
        return items

    def _from_row(self, row: dict[str, Any], media: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        definition = _parse_json(row["definition_json"], {})
        record = {
            "id": row["id"],
            "owner_user_id": row["owner_user_id"],
            "project_id": row["project_id"],
            "kind": row["kind"],
            "name": row["name"],
            "status": row["status"],
            "source_document_id": row["source_document_id"],
            "definition": definition,
            "image_job_id": row["image_job_id"],
            "image_object_key": row["image_object_key"],
            "image_url": row["image_url"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "media": media if media is not None else [],
        }
        if record["kind"] == "character":
            record["voice_slots"] = self._voice_slots(record["media"])
        elif record["kind"] == "voice":
            record["voice_slots"] = self._voice_slots(record["media"])
        return record

    def _voice_slots(self, media: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for item in media:
            if item.get("media_kind") != "voice_sample":
                continue
            slot = str(item.get("slot") or "default")
            if slot not in latest:
                latest[slot] = item
        slots = []
        fallback = latest.get("default")
        for slot in VOICE_SLOTS:
            current = latest.get(slot)
            inherited = current is None and fallback is not None and slot != "default"
            source = current or (fallback if inherited else None)
            slots.append(
                {
                    "slot": slot,
                    "url": (source or {}).get("url") or "",
                    "inherited_from_default": inherited,
                    "media_id": (source or {}).get("id"),
                }
            )
        return slots

    def list_assets(self, owner_user_id: str, project_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        with self._db.connection() as connection:
            if kind:
                rows = connection.execute(
                    """SELECT * FROM xiaji_assets WHERE owner_user_id = ? AND project_id = ? AND kind = ?
                    ORDER BY updated_at DESC""",
                    (owner_user_id, project_id, kind),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM xiaji_assets WHERE owner_user_id = ? AND project_id = ?
                    ORDER BY kind, updated_at DESC""",
                    (owner_user_id, project_id),
                ).fetchall()
            items = []
            for row in rows:
                media = self._media_for(connection, row["id"])
                items.append(self._from_row(dict(row), media))
            return items

    def get_asset(self, asset_id: str, owner_user_id: str) -> dict[str, Any]:
        with self._db.connection() as connection:
            row = connection.execute(
                "SELECT * FROM xiaji_assets WHERE id = ? AND owner_user_id = ?",
                (asset_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise KeyError(asset_id)
            media = self._media_for(connection, asset_id)
        return self._from_row(dict(row), media)

    def create_asset(
        self,
        owner_user_id: str,
        *,
        project_id: str,
        kind: str,
        name: str,
        definition: dict[str, Any] | None = None,
        source_document_id: str | None = None,
    ) -> dict[str, Any]:
        kind = kind.strip()
        name = name.strip()
        project_id = (project_id or "").strip()
        if not project_id:
            raise ValueError("请选择项目")
        if kind not in ASSET_KINDS:
            raise ValueError("资产类型无效")
        if not name:
            raise ValueError("请填写名称")
        payload = dict(definition or {})
        if kind == "character" and not payload.get("looks"):
            payload["looks"] = [default_look()]
        if kind in {"character", "voice"} and not payload.get("voice_profile"):
            payload["voice_profile"] = empty_voice_profile()
        asset_id = f"ast-{uuid.uuid4().hex[:16]}"
        timestamp = now()
        with self._db.connection() as connection:
            existing = connection.execute(
                "SELECT id FROM xiaji_assets WHERE project_id = ? AND kind = ? AND name = ?",
                (project_id, kind, name[:255]),
            ).fetchone()
            if existing is not None:
                raise ValueError("已存在同名资产")
            connection.execute(
                """INSERT INTO xiaji_assets (
                    id, owner_user_id, project_id, kind, name, status, source_document_id, definition_json,
                    image_job_id, image_object_key, image_url, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, NULL, NULL, NULL, NULL, ?, ?)""",
                (
                    asset_id,
                    owner_user_id,
                    project_id,
                    kind,
                    name[:255],
                    source_document_id,
                    json.dumps(payload, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_asset(asset_id, owner_user_id)

    def update_asset(
        self,
        asset_id: str,
        owner_user_id: str,
        *,
        name: str | None = None,
        definition: dict[str, Any] | None = None,
        status: str | None = None,
        image_job_id: str | None = None,
        image_object_key: str | None = None,
        image_url: str | None = None,
        error: str | None = None,
        clear_error: bool = False,
    ) -> dict[str, Any]:
        current = self.get_asset(asset_id, owner_user_id)
        next_name = (name or current["name"]).strip()[:255]
        if not next_name:
            raise ValueError("请填写名称")
        payload = dict(current["definition"])
        if definition is not None:
            payload.update(definition)
        if current["kind"] == "character":
            looks = payload.get("looks")
            if isinstance(looks, list):
                normalized_looks = []
                for look in looks:
                    if not isinstance(look, dict):
                        continue
                    if not str(look.get("id") or "").strip():
                        look["id"] = default_look()["id"]
                    look["name"] = str(look.get("name") or "造型").strip()[:64] or "造型"
                    look["appearance_details"] = str(look.get("appearance_details") or "")
                    normalized_looks.append(look)
                payload["looks"] = normalized_looks
            if not payload.get("voice_profile"):
                payload["voice_profile"] = empty_voice_profile()
        timestamp = now()
        with self._db.connection() as connection:
            if next_name != current["name"]:
                clash = connection.execute(
                    "SELECT id FROM xiaji_assets WHERE project_id = ? AND kind = ? AND name = ? AND id != ?",
                    (current["project_id"], current["kind"], next_name, asset_id),
                ).fetchone()
                if clash is not None:
                    raise ValueError("已存在同名资产")
            connection.execute(
                """UPDATE xiaji_assets SET name = ?, definition_json = ?, status = ?,
                    image_job_id = ?, image_object_key = ?, image_url = ?, error = ?, updated_at = ?
                    WHERE id = ? AND owner_user_id = ?""",
                (
                    next_name,
                    json.dumps(payload, ensure_ascii=False),
                    status or current["status"],
                    image_job_id if image_job_id is not None else current["image_job_id"],
                    image_object_key if image_object_key is not None else current["image_object_key"],
                    image_url if image_url is not None else current["image_url"],
                    None if clear_error else (error if error is not None else current["error"]),
                    timestamp,
                    asset_id,
                    owner_user_id,
                ),
            )
        return self.get_asset(asset_id, owner_user_id)

    def delete_asset(self, asset_id: str, owner_user_id: str) -> None:
        with self._db.connection() as connection:
            row = connection.execute(
                "SELECT id FROM xiaji_assets WHERE id = ? AND owner_user_id = ?",
                (asset_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise KeyError(asset_id)
            connection.execute("DELETE FROM xiaji_asset_media WHERE asset_id = ?", (asset_id,))
            connection.execute("DELETE FROM xiaji_assets WHERE id = ?", (asset_id,))

    def add_media(
        self,
        asset_id: str,
        owner_user_id: str,
        *,
        media_kind: str,
        slot: str = "",
        job_id: str | None = None,
        object_key: str | None = None,
        url: str | None = None,
        prompt: str | None = None,
        model: str | None = None,
        official: bool = True,
    ) -> dict[str, Any]:
        self.get_asset(asset_id, owner_user_id)
        media_id = f"med-{uuid.uuid4().hex[:16]}"
        timestamp = now()
        with self._db.connection() as connection:
            connection.execute(
                """INSERT INTO xiaji_asset_media (
                    id, asset_id, media_kind, slot, job_id, object_key, url, prompt, model, is_official, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    media_id,
                    asset_id,
                    media_kind[:32],
                    (slot or "")[:64],
                    job_id,
                    object_key,
                    url,
                    prompt,
                    (model or "")[:255] if model else None,
                    1 if official else 0,
                    timestamp,
                ),
            )
        return self.get_asset(asset_id, owner_user_id)

    def latest_analysis(self, owner_user_id: str, project_id: str, document_id: str | None = None) -> tuple[str | None, dict[str, Any] | None]:
        with self._db.connection() as connection:
            if document_id:
                row = connection.execute(
                    """SELECT d.id, a.analysis_json FROM xiaji_documents d
                    JOIN xiaji_document_analyses a ON a.document_id = d.id
                    WHERE d.owner_user_id = ? AND d.project_id = ? AND d.id = ?""",
                    (owner_user_id, project_id, document_id),
                ).fetchone()
            else:
                row = connection.execute(
                    """SELECT d.id, a.analysis_json FROM xiaji_documents d
                    JOIN xiaji_document_analyses a ON a.document_id = d.id
                    WHERE d.owner_user_id = ? AND d.project_id = ?
                    ORDER BY d.updated_at DESC LIMIT 1""",
                    (owner_user_id, project_id),
                ).fetchone()
        if row is None:
            return None, None
        payload = _parse_json(row["analysis_json"], {})
        return row["id"], payload

    def list_analyses(self, owner_user_id: str, project_id: str) -> list[tuple[str, dict[str, Any]]]:
        with self._db.connection() as connection:
            rows = connection.execute(
                """SELECT d.id, a.analysis_json FROM xiaji_documents d
                JOIN xiaji_document_analyses a ON a.document_id = d.id
                WHERE d.owner_user_id = ? AND d.project_id = ?
                ORDER BY d.updated_at ASC""",
                (owner_user_id, project_id),
            ).fetchall()
        items: list[tuple[str, dict[str, Any]]] = []
        for row in rows:
            payload = _parse_json(row["analysis_json"], {})
            if isinstance(payload, dict):
                items.append((row["id"], payload))
        return items

    def sync_from_analysis(
        self,
        owner_user_id: str,
        analysis: dict[str, Any],
        *,
        project_id: str,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        if not (project_id or "").strip():
            raise ValueError("请选择项目")
        settings = analysis.get("ingest_settings") if isinstance(analysis.get("ingest_settings"), dict) else {}
        visual_style = str(settings.get("visual_style") or "")
        ethnicity = str(settings.get("ethnicity") or "Chinese")
        created = 0
        character_count = 0
        scene_count = 0
        prop_count = 0
        for item in analysis.get("characters") or []:
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            created += self._upsert_character(owner_user_id, project_id, item, document_id, visual_style, ethnicity)
            character_count += 1
        for item in analysis.get("scenes") or []:
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            created += self._upsert_named(
                owner_user_id,
                project_id,
                "scene",
                str(item["name"]).strip(),
                {
                    "scene_type": str(item.get("scene_type") or "interior"),
                    "description": str(item.get("description") or ""),
                    "environment_prompt": str(item.get("environment_prompt") or item.get("description") or ""),
                    "time_of_day": str(item.get("time_of_day") or ""),
                    "visual_style": visual_style,
                    "ethnicity": ethnicity,
                    "aliases": list(item.get("aliases") or []),
                },
                document_id,
            )
            scene_count += 1
        for item in analysis.get("props") or []:
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            created += self._upsert_named(
                owner_user_id,
                project_id,
                "prop",
                str(item["name"]).strip(),
                {
                    "aliases": list(item.get("aliases") or []),
                    "prop_type": str(item.get("prop_type") or "object"),
                    "visual_prompt": str(item.get("visual_prompt") or ""),
                    "description": str(item.get("description") or ""),
                    "owner": str(item.get("owner") or ""),
                    "visual_style": visual_style,
                    "ethnicity": ethnicity,
                },
                document_id,
            )
            prop_count += 1
        self._upsert_named(
            owner_user_id,
            project_id,
            "voice",
            "解说",
            {
                "role": "narrator",
                "visual_style": visual_style,
                "voice_profile": empty_voice_profile(),
            },
            document_id,
        )
        return {
            "created": created,
            "transferred": {
                "characters": character_count,
                "scenes": scene_count,
                "props": prop_count,
            },
            "assets": self.list_assets(owner_user_id, project_id),
        }

    def _find(self, project_id: str, kind: str, name: str) -> dict[str, Any] | None:
        with self._db.connection() as connection:
            row = connection.execute(
                "SELECT * FROM xiaji_assets WHERE project_id = ? AND kind = ? AND name = ?",
                (project_id, kind, name),
            ).fetchone()
        if row is None:
            return None
        return self.get_asset(row["id"], row["owner_user_id"])

    def _upsert_character(
        self,
        owner_user_id: str,
        project_id: str,
        item: dict[str, Any],
        document_id: str | None,
        visual_style: str,
        ethnicity: str = "Chinese",
    ) -> int:
        name = str(item["name"]).strip()
        incoming = {
            "aliases": list(item.get("aliases") or []),
            "role": str(item.get("role") or ""),
            "is_main": bool(item.get("is_main")),
            "gender": str(item.get("gender") or ""),
            "age_group": str(item.get("age_group") or ""),
            "body_type": str(item.get("body_type") or ""),
            "description": str(item.get("description") or ""),
            "face_prompt": str(item.get("face_prompt") or ""),
            "visual_style": visual_style,
            "ethnicity": ethnicity or "Chinese",
        }
        existing = self._find(project_id, "character", name)
        if existing is None:
            look = default_look()
            look["appearance_details"] = incoming["description"]
            incoming["looks"] = [look]
            incoming["voice_profile"] = empty_voice_profile()
            self.create_asset(
                owner_user_id,
                project_id=project_id,
                kind="character",
                name=name,
                definition=incoming,
                source_document_id=document_id,
            )
            return 1
        merged = dict(existing["definition"])
        merged["aliases"] = list(dict.fromkeys([*incoming["aliases"], *(merged.get("aliases") or [])]))
        for key in ("role", "gender", "age_group", "body_type", "description", "face_prompt", "visual_style", "ethnicity"):
            if incoming.get(key):
                merged[key] = incoming[key]
        merged["is_main"] = incoming["is_main"] or bool(merged.get("is_main"))
        if not merged.get("looks"):
            look = default_look()
            look["appearance_details"] = merged.get("description") or ""
            merged["looks"] = [look]
        if not merged.get("voice_profile"):
            merged["voice_profile"] = empty_voice_profile()
        self.update_asset(existing["id"], owner_user_id, definition=merged)
        return 0

    def _upsert_named(
        self,
        owner_user_id: str,
        project_id: str,
        kind: str,
        name: str,
        definition: dict[str, Any],
        document_id: str | None,
    ) -> int:
        existing = self._find(project_id, kind, name)
        if existing is None:
            self.create_asset(
                owner_user_id,
                project_id=project_id,
                kind=kind,
                name=name,
                definition=definition,
                source_document_id=document_id,
            )
            return 1
        merged = dict(existing["definition"])
        aliases = list(dict.fromkeys([*(merged.get("aliases") or []), *(definition.get("aliases") or [])]))
        if aliases:
            merged["aliases"] = aliases
        for key, value in definition.items():
            if key == "aliases":
                continue
            if key == "voice_profile" and merged.get("voice_profile"):
                continue
            if value:
                merged[key] = value
        if kind == "voice" and not merged.get("voice_profile"):
            merged["voice_profile"] = empty_voice_profile()
        self.update_asset(existing["id"], owner_user_id, definition=merged)
        return 0
