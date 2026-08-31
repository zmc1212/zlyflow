from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .config import settings
from .director_recipe import (
    _normalize_character,
    _normalize_location,
    _text,
    normalize_recipe_payload,
)


LIBRARY_KINDS = ("character", "scene", "prop")
LIBRARY_KIND_ALIASES = {
    "character": "character",
    "char": "character",
    "人物": "character",
    "角色": "character",
    "scene": "scene",
    "location": "scene",
    "loc": "scene",
    "场景": "scene",
    "prop": "prop",
    "object": "prop",
    "道具": "prop",
}
LIBRARY_GENDERS = ("", "male", "female", "nonbinary", "unspecified")
_LIBRARY_IMAGE_URL = re.compile(r"/api/director/library-assets/([^/]+)/image")


class DirectorLibraryError(ValueError):
    """Invalid employee library asset."""


def new_library_asset_id() -> str:
    return f"lib-{uuid.uuid4().hex[:16]}"


def normalize_library_kind(value: Any) -> str:
    raw = str(value or "").strip()
    kind = LIBRARY_KIND_ALIASES.get(raw, LIBRARY_KIND_ALIASES.get(raw.lower(), ""))
    if kind not in LIBRARY_KINDS:
        raise DirectorLibraryError("资产类型必须是人物、场景或道具")
    return kind


def library_image_url(asset_id: str) -> str:
    return f"/api/director/library-assets/{asset_id}/image"


def library_asset_dir(owner_user_id: str, asset_id: str) -> Path:
    return settings.uploads_dir / owner_user_id / "library" / asset_id


def find_library_asset_file(owner_user_id: str, asset_id: str, image_path: str | None = None) -> Path | None:
    if image_path:
        candidate = Path(image_path)
        if candidate.is_file():
            return candidate
    directory = library_asset_dir(owner_user_id, asset_id)
    if not directory.is_dir():
        return None
    matches = sorted(path for path in directory.glob("image.*") if path.is_file())
    return matches[0] if matches else None


def parse_library_asset_id_from_url(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    match = _LIBRARY_IMAGE_URL.search(text)
    return match.group(1) if match else None


def public_library_asset(record: dict[str, Any]) -> dict[str, Any]:
    asset_id = str(record.get("id") or "")
    image_path = record.get("image_path")
    owner = str(record.get("owner_user_id") or "")
    has_file = bool(find_library_asset_file(owner, asset_id, image_path if isinstance(image_path, str) else None))
    image_url = library_image_url(asset_id) if has_file else (_text(record.get("image_url")) or None)
    return {
        "id": asset_id,
        "kind": record.get("kind") or "character",
        "name": record.get("name") or "",
        "description": record.get("description") or "",
        "promptText": record.get("prompt_text") or "",
        "gender": record.get("gender") or "",
        "imageUrl": image_url,
        "imageJobId": record.get("image_job_id") or None,
        "sourceProjectId": record.get("source_project_id") or None,
        "created_at": record.get("created_at") or "",
        "updated_at": record.get("updated_at") or "",
    }


def normalize_library_asset_fields(raw: dict[str, Any] | None, *, partial: bool = False) -> dict[str, Any]:
    item = raw if isinstance(raw, dict) else {}
    fields: dict[str, Any] = {}
    if not partial or "kind" in item:
        fields["kind"] = normalize_library_kind(item.get("kind"))
    if not partial or "name" in item:
        name = _text(item.get("name"))
        if not name:
            raise DirectorLibraryError("请填写资产名称")
        fields["name"] = name
    if not partial or "description" in item:
        fields["description"] = _text(item.get("description"))
    if not partial or "promptText" in item or "prompt_text" in item:
        fields["prompt_text"] = _text(item.get("promptText"), item.get("prompt_text") or "")
    if not partial or "gender" in item:
        gender = _text(item.get("gender"))
        fields["gender"] = gender if gender in LIBRARY_GENDERS else ""
    if "imageUrl" in item or "image_url" in item:
        fields["image_url"] = _text(item.get("imageUrl"), item.get("image_url") or "") or None
    if "imageJobId" in item or "image_job_id" in item:
        fields["image_job_id"] = _text(item.get("imageJobId"), item.get("image_job_id") or "") or None
    if "sourceProjectId" in item or "source_project_id" in item:
        fields["source_project_id"] = _text(item.get("sourceProjectId"), item.get("source_project_id") or "") or None
    return fields


def save_library_asset_image(*, owner_user_id: str, asset_id: str, source: Path) -> Path:
    dest_dir = library_asset_dir(owner_user_id, asset_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower() if source.suffix else ".png"
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        suffix = ".png"
    dest = dest_dir / f"image{suffix}"
    for leftover in dest_dir.glob("image.*"):
        leftover.unlink(missing_ok=True)
    shutil.copy2(source, dest)
    return dest


def delete_library_asset_files(owner_user_id: str, asset_id: str) -> None:
    directory = library_asset_dir(owner_user_id, asset_id)
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)


def recipe_items_for_library(
    recipe: dict[str, Any],
    *,
    character_ids: list[str] | None = None,
    location_ids: list[str] | None = None,
    prop_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    payload = normalize_recipe_payload(recipe)
    wanted_chars = {item for item in (character_ids or []) if item}
    wanted_locs = {item for item in (location_ids or []) if item}
    wanted_props = {item for item in (prop_ids or []) if item}
    take_all = not wanted_chars and not wanted_locs and not wanted_props
    items: list[dict[str, Any]] = []
    for character in payload.get("characters") or []:
        if not take_all and character.get("id") not in wanted_chars:
            continue
        kind = "prop" if str(character.get("type") or "") == "object" else "character"
        approved_look = next((look for look in character.get("looks") or [] if isinstance(look, dict) and look.get("status") == "approved"), None)
        approved_sheet = (approved_look or {}).get("sheet") if isinstance(approved_look, dict) else None
        approved_version = next((version for version in (approved_sheet or {}).get("versions") or [] if isinstance(version, dict) and version.get("id") == (approved_sheet or {}).get("approvedVersionId")), None)
        if approved_version is None:
            portrait = character.get("portrait") if isinstance(character.get("portrait"), dict) else {}
            approved_version = next((version for version in portrait.get("versions") or [] if isinstance(version, dict) and version.get("id") == portrait.get("approvedVersionId")), None)
        image_url = approved_version.get("imageUrl") if approved_version else None
        image_job_id = approved_version.get("jobId") if approved_version else None
        if not image_url and not (str(character.get("type") or "") == "object" and not character.get("portrait", {}).get("versions")):
            continue
        items.append({
            "kind": kind,
            "name": character.get("name") or "",
            "description": character.get("description") or "",
            "prompt_text": character.get("promptText") or character.get("prompt_text") or "",
            "gender": character.get("gender") or "",
            "image_url": image_url,
            "image_job_id": image_job_id,
            "source_project_id": None,
        })
    for location in payload.get("locations") or []:
        if not take_all and location.get("id") not in wanted_locs:
            continue
        plate = location.get("plate") if isinstance(location.get("plate"), dict) else {}
        if not location.get("imageUrl") and plate.get("versions"):
            continue
        items.append({
            "kind": "scene",
            "name": location.get("name") or "",
            "description": location.get("description") or "",
            "prompt_text": location.get("promptText") or location.get("prompt_text") or "",
            "gender": "",
            "image_url": location.get("imageUrl") or location.get("image_url") or None,
            "image_job_id": location.get("imageJobId") or location.get("image_job_id") or None,
            "source_project_id": None,
        })
    for prop in payload.get("props") or []:
        if not isinstance(prop, dict):
            continue
        if not take_all and prop.get("id") not in wanted_props:
            continue
        if not prop.get("imageUrl"):
            continue
        items.append({
            "kind": "prop",
            "name": prop.get("name") or "",
            "description": prop.get("description") or "",
            "prompt_text": prop.get("promptText") or prop.get("prompt_text") or "",
            "gender": "",
            "image_url": prop.get("imageUrl") or prop.get("image_url") or None,
            "image_job_id": prop.get("imageJobId") or prop.get("image_job_id") or None,
            "source_project_id": None,
        })
    if not items:
        raise DirectorLibraryError("没有可存入资产库的人物、场景或道具")
    return items


def _library_to_character(asset: dict[str, Any], index: int) -> dict[str, Any]:
    public = public_library_asset(asset) if "prompt_text" in asset or "owner_user_id" in asset else asset
    kind = public.get("kind") or asset.get("kind")
    char_type = "object" if kind == "prop" else "character"
    image_url = public.get("imageUrl") or asset.get("image_url") or asset.get("imageUrl")
    if find_library_asset_file(str(asset.get("owner_user_id") or ""), str(asset.get("id") or ""), asset.get("image_path")):
        image_url = library_image_url(str(asset.get("id") or ""))
    return _normalize_character({
        "name": public.get("name") or asset.get("name"),
        "description": public.get("description") or asset.get("description"),
        "promptText": public.get("promptText") or asset.get("prompt_text") or asset.get("promptText"),
        "gender": public.get("gender") or asset.get("gender") or "",
        "type": char_type,
        "imageUrl": image_url,
        "imageJobId": public.get("imageJobId") or asset.get("image_job_id") or asset.get("imageJobId"),
        "libraryAssetId": asset.get("id"),
    }, index)


def _library_to_location(asset: dict[str, Any], index: int) -> dict[str, Any]:
    public = public_library_asset(asset) if "prompt_text" in asset or "owner_user_id" in asset else asset
    image_url = public.get("imageUrl") or asset.get("image_url") or asset.get("imageUrl")
    if find_library_asset_file(str(asset.get("owner_user_id") or ""), str(asset.get("id") or ""), asset.get("image_path")):
        image_url = library_image_url(str(asset.get("id") or ""))
    return _normalize_location({
        "name": public.get("name") or asset.get("name"),
        "description": public.get("description") or asset.get("description"),
        "promptText": public.get("promptText") or asset.get("prompt_text") or asset.get("promptText"),
        "imageUrl": image_url,
        "imageJobId": public.get("imageJobId") or asset.get("image_job_id") or asset.get("imageJobId"),
        "libraryAssetId": asset.get("id"),
    }, index)


def insert_library_assets_into_recipe(recipe: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    if not assets:
        raise DirectorLibraryError("请选择要插入的资产")
    payload = normalize_recipe_payload(recipe)
    characters = list(payload.get("characters") or [])
    locations = list(payload.get("locations") or [])
    for asset in assets:
        kind = asset.get("kind") if asset.get("kind") in LIBRARY_KINDS else normalize_library_kind(asset.get("kind"))
        if kind == "scene":
            locations.append(_library_to_location(asset, len(locations)))
        else:
            characters.append(_library_to_character({**asset, "kind": kind}, len(characters)))
    payload["characters"] = [_normalize_character(item, index) for index, item in enumerate(characters)]
    payload["locations"] = [_normalize_location(item, index) for index, item in enumerate(locations)]
    return payload
