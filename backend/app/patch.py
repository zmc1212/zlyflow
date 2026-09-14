import sys
import re

with open("backend/app/director_jobs.py", "r", encoding="utf-8") as f:
    content = f.read()

new_funcs = """

def recipe_asset_image_file(
    *,
    owner_user_id: str,
    project_id: str,
    kind: str,
    asset_id: str,
    look_id: str | None,
    suffix: str = ".png",
) -> Path:
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    prefix = f"{kind}_{asset_id}"
    if look_id:
        prefix += f"_{look_id}"
    return settings.uploads_dir / owner_user_id / project_id / f"{prefix}{safe_suffix}"


def find_recipe_asset_image_file(
    *,
    owner_user_id: str,
    project_id: str,
    kind: str,
    asset_id: str,
    look_id: str | None,
) -> Path | None:
    directory = settings.uploads_dir / owner_user_id / project_id
    if not directory.is_dir():
        return None
    prefix = f"{kind}_{asset_id}"
    if look_id:
        prefix += f"_{look_id}"
    matches = sorted(path for path in directory.glob(f"{prefix}.*") if path.is_file())
    return matches[0] if matches else None


def save_recipe_asset_image(
    recipe: dict[str, Any],
    *,
    owner_user_id: str,
    project_id: str,
    kind: str,
    asset_id: str,
    look_id: str | None,
    source: Path,
) -> dict[str, Any]:
    normalized = normalize_recipe_payload(recipe)
    
    asset = None
    if kind == "character":
        for c in normalized.get("characters", []):
            if c.get("id") == asset_id:
                asset = c
                break
    elif kind == "location":
        for l in normalized.get("locations", []):
            if l.get("id") == asset_id:
                asset = l
                break
    elif kind == "prop":
        for p in normalized.get("props", []):
            if p.get("id") == asset_id:
                asset = p
                break
                
    if not asset:
        raise ValueError("指定的素材不存在")
        
    suffix = source.suffix.lower() or ".png"
    dest = recipe_asset_image_file(
        owner_user_id=owner_user_id,
        project_id=project_id,
        kind=kind,
        asset_id=asset_id,
        look_id=look_id,
        suffix=suffix,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    pending = dest.with_name(f".{dest.name}.{secrets.token_hex(4)}.tmp")
    try:
        shutil.copy2(source, pending)
        pending.replace(dest)
    finally:
        pending.unlink(missing_ok=True)
        
    prefix = f"{kind}_{asset_id}"
    if look_id:
        prefix += f"_{look_id}"
    for leftover in dest.parent.glob(f"{prefix}.*"):
        if leftover != dest:
            leftover.unlink(missing_ok=True)
            
    query = f"?look_id={look_id}" if look_id else ""
    public_url = f"/api/director/recipes/{project_id}/asset-image/{kind}/{asset_id}{query}"
    version_id = f"manual_{int(datetime.now().timestamp())}"
    
    version = {
        "id": version_id,
        "status": "succeeded",
        "imageUrl": public_url,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }
    
    if kind == "character":
        if look_id:
            for look in asset.get("looks", []):
                if look.get("id") == look_id:
                    rendition = look.get("sheet")
                    if not rendition:
                        look["sheet"] = {"versions": []}
                        rendition = look["sheet"]
                    rendition.setdefault("versions", []).append(version)
                    rendition["approvedVersionId"] = version_id
                    break
        else:
            rendition = asset.get("portrait")
            if not rendition:
                asset["portrait"] = {"versions": []}
                rendition = asset["portrait"]
            rendition.setdefault("versions", []).append(version)
            rendition["approvedVersionId"] = version_id
    elif kind == "location":
        rendition = asset.get("plate")
        if not rendition:
            asset["plate"] = {"versions": []}
            rendition = asset["plate"]
        rendition.setdefault("versions", []).append(version)
        rendition["approvedVersionId"] = version_id
    elif kind == "prop":
        rendition = asset.get("turnaround")
        if not rendition:
            asset["turnaround"] = {"versions": []}
            rendition = asset["turnaround"]
        rendition.setdefault("versions", []).append(version)
        rendition["approvedVersionId"] = version_id
        
    return normalized
"""

if "def save_recipe_asset_image(" not in content:
    content = content.replace("def copy_recipe_script_cover(", new_funcs + "\n\ndef copy_recipe_script_cover(")
    with open("backend/app/director_jobs.py", "w", encoding="utf-8") as f:
        f.write(content)
