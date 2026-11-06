"""出片镜头的参考图装配，对齐 source1/app/xiaji_episode_prompts.py 的参考图顺序。"""
from __future__ import annotations

from typing import Any


def scene_master_url(scene: dict[str, Any] | None) -> str:
    if not scene:
        return ""
    extra = scene.get("extra") if isinstance(scene.get("extra"), dict) else {}
    for value in (extra.get("master_url"), scene.get("image_url")):
        url = str(value or "").strip()
        if url.startswith(("http://", "https://")):
            return url
    return ""


def _scene_name_matches(asset_name: str, scene_name: str) -> bool:
    asset_name = str(asset_name or "").strip()
    scene_name = str(scene_name or "").strip()
    if not asset_name or not scene_name:
        return False
    return asset_name == scene_name or asset_name in scene_name or scene_name in asset_name


def resolve_scene_asset(beat: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick a scene asset for a beat, preferring one that already has a master view."""
    by_id = {str(item.get("id")): item for item in assets if item.get("id")}
    bound = by_id.get(str(beat.get("scene_id") or ""))
    if bound and bound.get("kind") not in (None, "", "scene"):
        bound = None
    if scene_master_url(bound):
        return bound
    scenes = [item for item in assets if item.get("kind") == "scene"]
    scene_name = str(beat.get("scene") or (bound or {}).get("name") or "").strip()
    matches = [item for item in scenes if _scene_name_matches(str(item.get("name") or ""), scene_name)] if scene_name else []
    with_url = next((item for item in matches if scene_master_url(item)), None)
    if with_url:
        return with_url
    return bound or (matches[0] if matches else None)


def _append_https(urls: list[str], value: Any) -> None:
    url = str(value or "").strip()
    if url.startswith(("http://", "https://")) and url not in urls:
        urls.append(url)


def beat_reference_urls(
    beat: dict[str, Any],
    assets: list[dict[str, Any]],
    *,
    scene_view: str = "front",
) -> list[str]:
    """镜头参考图顺序：出场角色的选定造型（缺造型时回退形象图）、场景主图/反面图。"""
    by_id = {item["id"]: item for item in assets if item.get("id")}
    urls: list[str] = []
    scene = resolve_scene_asset(beat, assets)
    character_ids = [str(item) for item in (beat.get("character_ids") or [])]
    selected_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
    legacy_look_id = str(beat.get("character_look_id") or "").strip()
    for asset_id in character_ids:
        asset = by_id.get(asset_id)
        extra = asset.get("extra") if isinstance((asset or {}).get("extra"), dict) else {}
        identities = extra.get("identities") or []
        selected_look_id = str(selected_ids.get(asset_id) or "").strip()
        if not selected_look_id and legacy_look_id:
            if any(str((look or {}).get("id") or "") == legacy_look_id for look in identities):
                selected_look_id = legacy_look_id
        selected_look = next(
            (
                look for look in identities
                if isinstance(look, dict) and str(look.get("id") or "") == selected_look_id
            ),
            None,
        )
        look_url = (selected_look or {}).get("image_url")
        _append_https(urls, look_url)
        if not str(look_url or "").strip():
            _append_https(urls, extra.get("avatar_url") or (asset or {}).get("image_url"))
    if scene:
        extra = scene.get("extra") if isinstance(scene.get("extra"), dict) else {}
        if scene_view == "reverse":
            _append_https(urls, extra.get("reverse_url"))
        _append_https(urls, extra.get("master_url") or scene.get("image_url"))
    return urls[:9]
