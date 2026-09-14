import sys

with open("backend/app/main.py", "r", encoding="utf-8") as f:
    content = f.read()

new_routes = """

@app.post(
    "/api/director/recipes/{project_id}/asset-image",
    response_model=DirectorProjectResponse,
    tags=["导演台"],
    summary="上传素材图片",
)
async def upload_director_recipe_asset_image(
    project_id: str,
    request: Request,
    user: Annotated[dict, Depends(mutating_user)],
    kind: Annotated[str, Form(description="素材类型: character, location, prop")],
    asset_id: Annotated[str, Form(description="素材 ID")],
    file: Annotated[UploadFile, File(description="素材图片")],
    look_id: Annotated[str | None, Form(description="造型 ID，如果是角色定妆板")] = None,
    expected_content_revision: Annotated[
        int | None,
        Form(ge=1, description="客户端最后读取的创作内容版本；不匹配时返回 409。"),
    ] = None,
) -> dict:
    from .director_jobs import save_recipe_asset_image
    import secrets
    from pathlib import Path
    
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=422, detail="只有 Recipe 工程可以上传素材图片")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="必须为图片")
    owner_user_id = str(record.get("owner_user_id") or user["id"])
    suffix = Path(file.filename or "image.png").suffix or ".png"
    staging = settings.staging_dir / f"director-asset-{secrets.token_urlsafe(6)}{suffix}"
    staging.parent.mkdir(parents=True, exist_ok=True)
    await save_upload(file, staging)
    try:
        saved = app.state.store.mutate_director_project_payload(
            project_id,
            lambda latest: save_recipe_asset_image(
                latest,
                owner_user_id=owner_user_id,
                project_id=project_id,
                kind=kind,
                asset_id=asset_id,
                look_id=look_id,
                source=staging,
            ),
            content_update=True,
            expected_content_revision=expected_content_revision,
        )
    except DirectorProjectConflictError as error:
        raise director_content_conflict_http(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        staging.unlink(missing_ok=True)
    app.state.auth_store.audit(
        "upload_director_asset_image", "director", actor_user_id=user["id"], target_id=project_id,
        detail=f"{kind}:{asset_id}", ip_address=client_ip(request),
    )
    return public_director_project(saved)


@app.get(
    "/api/director/recipes/{project_id}/asset-image/{kind}/{asset_id}",
    tags=["导演台"],
    summary="读取素材图片",
)
def download_director_recipe_asset_image(
    project_id: str,
    kind: str,
    asset_id: str,
    user: Annotated[dict, Depends(current_user)],
    look_id: str | None = None,
) -> FileResponse:
    from .director_jobs import find_recipe_asset_image_file
    record = director_project_or_404(app.state.store, project_id, user)
    if payload_kind(record.get("payload")) != PAYLOAD_KIND_RECIPE:
        raise HTTPException(status_code=404, detail="图片不存在")
    owner_user_id = str(record.get("owner_user_id") or user["id"])
    file_path = find_recipe_asset_image_file(
        owner_user_id=owner_user_id,
        project_id=project_id,
        kind=kind,
        asset_id=asset_id,
        look_id=look_id,
    )
    if file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail="图片未找到")
    return FileResponse(file_path, headers={"Cache-Control": "public, max-age=31536000"})
"""

if "def upload_director_recipe_asset_image(" not in content:
    content = content.replace("async def upload_director_recipe_frame(", new_routes + "\nasync def upload_director_recipe_frame(")
    with open("backend/app/main.py", "w", encoding="utf-8") as f:
        f.write(content)
