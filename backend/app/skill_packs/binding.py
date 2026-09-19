from __future__ import annotations

from typing import Any

from .recipe import UnknownSkillPackError, get_pack


def canonicalize_skill_pack_extra(extra: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(extra or {})
    has_key = "skill_pack_id" in data or "skillPackId" in data
    pack_id = str(data.get("skill_pack_id") or data.get("skillPackId") or "").strip()
    data.pop("skillPackId", None)
    if pack_id:
        data["skill_pack_id"] = pack_id
    elif has_key:
        data.pop("skill_pack_id", None)
    return data


def extra_mapping(source: Any) -> dict[str, Any]:
    if source is None:
        return {}
    if hasattr(source, "model_dump"):
        try:
            source = source.model_dump()
        except Exception:
            source = dict(getattr(source, "__dict__", {}) or {})
    if not isinstance(source, dict):
        extra = getattr(source, "extra", None)
        settings = getattr(source, "settings", None)
        if isinstance(extra, dict):
            return dict(extra)
        if isinstance(settings, dict) and isinstance(settings.get("extra"), dict):
            return dict(settings["extra"])
        return {}
    extra = source.get("extra")
    if isinstance(extra, dict):
        return dict(extra)
    settings = source.get("settings")
    if isinstance(settings, dict) and isinstance(settings.get("extra"), dict):
        return dict(settings["extra"])
    return {}


def skill_pack_id_of(source: Any) -> str:
    if source is None:
        return ""
    extra = extra_mapping(source)
    for key in ("skill_pack_id", "skillPackId"):
        value = str(extra.get(key) or "").strip()
        if value:
            return value
    if isinstance(source, dict):
        value = str(source.get("skill_pack_id") or source.get("skillPackId") or "").strip()
        if value:
            return value
        settings = source.get("settings")
        if isinstance(settings, dict):
            value = str(settings.get("skill_pack_id") or "").strip()
            if value:
                return value
    else:
        value = str(getattr(source, "skill_pack_id", "") or "").strip()
        if value:
            return value
    return ""


def resolve_skill_pack_id(
    *,
    payload: Any = None,
    beat: Any = None,
    episode: Any = None,
    project: Any = None,
    project_id: str | None = None,
) -> str:
    for source in (payload, beat, episode, project):
        pack_id = skill_pack_id_of(source)
        if pack_id:
            return pack_id
    if project_id and project is None:
        pack_id = skill_pack_id_of(load_project(project_id))
        if pack_id:
            return pack_id
    return ""


def load_project(project_id: str) -> dict[str, Any] | None:
    from ..media_studio.services.project_service import ProjectService

    item = ProjectService.get_project(project_id)
    if item is None:
        return None
    return item.model_dump()


def merge_project_extra(settings: dict[str, Any] | None, extra: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(settings or {})
    incoming = canonicalize_skill_pack_extra(extra) if extra is not None else {}
    existing = canonicalize_skill_pack_extra(
        merged.get("extra") if isinstance(merged.get("extra"), dict) else {}
    )
    combined = {**existing, **incoming}
    if combined:
        merged["extra"] = combined
    else:
        merged.pop("extra", None)
    return merged


def persist_project_settings(
    settings: dict[str, Any] | None,
    extra: dict[str, Any] | None,
    *,
    current_settings: dict[str, Any] | None = None,
    current_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if settings is not None:
        merged = dict(settings)
    else:
        merged = dict(current_settings or {})
    existing_extra = merged.get("extra") if isinstance(merged.get("extra"), dict) else None
    if existing_extra is None:
        existing_extra = dict(current_extra or {}) if current_extra else {}
    else:
        existing_extra = canonicalize_skill_pack_extra(existing_extra)
    if extra is not None:
        incoming = canonicalize_skill_pack_extra(extra)
        combined = {**existing_extra, **incoming}
        clearing = (
            ("skill_pack_id" in extra and not str(extra.get("skill_pack_id") or "").strip())
            or ("skillPackId" in extra and not str(extra.get("skillPackId") or "").strip())
        )
        if clearing:
            combined.pop("skill_pack_id", None)
    else:
        combined = existing_extra
    if combined:
        merged["extra"] = combined
    else:
        merged.pop("extra", None)
    pack_id = skill_pack_id_of({"settings": merged, "extra": merged.get("extra")})
    if pack_id:
        validate_skill_pack_id(pack_id)
    return merged


def validate_skill_pack_id(pack_id: str | None) -> str:
    normalized = str(pack_id or "").strip()
    if not normalized:
        return ""
    get_pack(normalized)
    return normalized


def project_extra_skill_pack_id(settings: dict[str, Any] | None, extra: dict[str, Any] | None = None) -> str:
    pack_id = skill_pack_id_of({"extra": extra or {}, "settings": settings or {}})
    if not pack_id:
        return ""
    try:
        return validate_skill_pack_id(pack_id)
    except UnknownSkillPackError:
        raise
