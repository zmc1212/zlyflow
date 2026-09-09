from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, File, Form, HTTPException, Path as FastApiPath, Query, UploadFile
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from .llm_client import LlmError, llm_error_raw
from .xiaji_analyze import build_ingest_messages
from .xiaji_art_style import art_style_hint, first_art_style_id
from .xiaji_visual_styles import (
    DEFAULT_VISUAL_STYLE,
    normalize_visual_style,
    visual_style_contract,
    visual_style_label,
)
from .xiaji_llm_jobs import finish_xiaji_llm_job, llm_failure_response, start_xiaji_llm_job
from .xiaji_parser import ALLOWED_EXTENSIONS, MAX_INGEST_BYTES, episode_count_for_text, load_source_text
from .xiaji_project_api import require_xiaji_project
from .xiaji_store import XiajiIngestStore


class XiajiPasteRequest(BaseModel):
    text: str = Field(default="", max_length=8 * 1024 * 1024)
    title: str = Field(default="", max_length=255)
    spine_template: str = Field(default="drama", max_length=32)
    visual_style: str = Field(default="", max_length=64)
    art_style_id: str = Field(default="", max_length=64)
    narration_style: str = Field(default="", max_length=64)
    ethnicity: str = Field(default="", max_length=32)
    replace: bool = False


class XiajiChapterWrite(BaseModel):
    id: str | None = None
    title: str = Field(default="", max_length=512)
    content: str = Field(default="")


class XiajiChaptersReplaceRequest(BaseModel):
    chapters: list[XiajiChapterWrite] = Field(min_length=1, max_length=2000)


def _store(app: Any) -> XiajiIngestStore:
    return app.state.xiaji_store


def _document_or_404(store: XiajiIngestStore, document_id: str, owner_user_id: str) -> dict[str, Any]:
    try:
        return store.get_document(document_id, owner_user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="文档不存在") from error


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _replace_project_content(app: Any, owner_user_id: str, project_id: str) -> None:
    store = getattr(app.state, "xiaji_project_store", None)
    if store is None:
        return
    store.clear_project_content(project_id, owner_user_id)


def _ingest_plain_text(
    store: XiajiIngestStore,
    owner_user_id: str,
    *,
    project_id: str,
    title: str,
    original_text: str,
    filename: str,
    source_format: str,
) -> dict[str, Any]:
    text = original_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise HTTPException(status_code=422, detail="没有可解析的正文")
    if len(text.encode("utf-8")) > MAX_INGEST_BYTES:
        raise HTTPException(status_code=413, detail="文本不能超过 8 MB")
    stem = Path(filename).stem
    if stem.lower() in {"paste", "untitled"}:
        stem = ""
    display_title = title.strip() or stem or text.split("\n", 1)[0].strip()[:40] or "未命名文稿"
    return store.create_from_text(
        owner_user_id,
        project_id=project_id,
        filename=filename[:255],
        title=display_title[:255],
        source_format=source_format,
        original_text=text,
    )


def _run_llm_analysis(
    app: Any,
    document: dict[str, Any],
    owner_user_id: str,
    *,
    spine_template: str,
    visual_style: str,
    narration_style: str,
    ethnicity: str,
    art_style_id: str = "",
) -> dict[str, Any]:
    store = _store(app)
    original_text = str(document.get("original_text") or "")
    target_episodes = episode_count_for_text(original_text)
    resolved_art = first_art_style_id(art_style_id)
    resolved_visual = normalize_visual_style(visual_style) or DEFAULT_VISUAL_STYLE
    style_hint = "；".join(
        part
        for part in (
            f"{visual_style_label(resolved_visual)}。{visual_style_contract(resolved_visual)}".strip("。"),
            art_style_hint(resolved_art),
        )
        if part
    )
    ingest_settings = {
        "spine_template": spine_template,
        "art_style_id": resolved_art,
        "visual_style": resolved_visual,
        "narration_style": narration_style,
        "ethnicity": ethnicity,
    }
    messages = build_ingest_messages(
        original_text,
        spine_template=spine_template,
        visual_style=style_hint,
        narration_style=narration_style,
        ethnicity=ethnicity,
        target_episodes=target_episodes,
    )
    job_id = start_xiaji_llm_job(
        app,
        owner_user_id=owner_user_id,
        project_id=str(document.get("project_id") or ""),
        kind="ingest",
        target=str(document.get("title") or "内容导入"),
        title=f"内容导入 · {document.get('title') or '未命名文稿'}",
        messages=messages,
        parameters={
            "document_id": document["id"],
            "filename": document.get("filename") or "",
            "source_format": document.get("source_format") or "",
            "char_count": document.get("char_count") or 0,
            "chapter_count": document.get("chapter_count") or 0,
            "target_episodes": target_episodes,
            "spine_template": spine_template,
            "art_style_id": resolved_art,
            "visual_style": resolved_visual,
            "narration_style": narration_style,
            "ethnicity": ethnicity,
            "original_text": original_text,
        },
        temperature=0.3,
        max_tokens=4096,
    )
    logs = [
        f"解析原文：{document['char_count']} 字",
        f"规则识别章节：{document['chapter_count']} 章",
        "调用已配置大模型分析角色、场景、道具和剧集规划",
    ]
    try:
        analysis = app.state.llm_provider.analyze_xiaji_ingest(
            document["original_text"],
            spine_template=spine_template,
            visual_style=style_hint,
            narration_style=narration_style,
            ethnicity=ethnicity,
            target_episodes=target_episodes,
        )
    except LlmError as error:
        logs.append(f"分析失败：{error}")
        raw = llm_error_raw(error)
        if raw:
            logs.append("模型返回原文：")
            logs.append(raw[:8000])
        finish_xiaji_llm_job(
            app,
            job_id,
            status="failed",
            error=str(error),
            response=llm_failure_response(error),
        )
        return store.save_analysis(
            document["id"],
            owner_user_id,
            {
                "summary": "",
                "characters": [],
                "scenes": [],
                "props": [],
                "episodes": [],
                "ingest_settings": ingest_settings,
            },
            logs=logs,
            model="",
            status="failed",
            error=str(error),
        )
    logs.append(
        "分析完成："
        f"{len(analysis.get('characters') or [])} 个角色，"
        f"{len(analysis.get('scenes') or [])} 个场景，"
        f"{len(analysis.get('props') or [])} 个道具，"
        f"{len(analysis.get('episodes') or [])} 集规划"
    )
    analysis["ingest_settings"] = ingest_settings
    status = "review_required" if document["chapter_count"] <= 1 else "indexed"
    asset_store = getattr(app.state, "xiaji_asset_store", None)
    if asset_store is not None:
        try:
            transferred = asset_store.sync_from_analysis(
                owner_user_id,
                analysis,
                project_id=document["project_id"],
                document_id=document["id"],
            )
            counts = transferred.get("transferred") or {}
            logs.append(
                "已转入资产库："
                f"{counts.get('characters') or 0} 个角色，"
                f"{counts.get('scenes') or 0} 个场景，"
                f"{counts.get('props') or 0} 个道具"
            )
        except Exception as error:
            logs.append(f"资产库转入未完成：{error}")
    saved = store.save_analysis(
        document["id"],
        owner_user_id,
        analysis,
        logs=logs,
        model=str(analysis.get("model") or ""),
        status=status,
    )
    finish_xiaji_llm_job(app, job_id, status="succeeded", response=analysis)
    return saved


def register_xiaji_routes(app: Any, *, current_user: Callable, mutating_user: Callable) -> None:
    router = APIRouter(prefix="/api/xiaji", tags=["导台2"])

    # Depends 必须写在默认值上。本模块有 from __future__ import annotations，
    # 嵌套路由里 Annotated[..., Depends(闭包参数)] 在求值时找不到 mutating_user/current_user，
    # FastAPI 会把 user 误判成必填 query，粘贴导入就会 422。
    @router.get("/documents", summary="列出当前项目的内容库文档")
    def list_documents(
        project_id: str = Query(..., description="导台2 项目 ID"),
        user: dict = Depends(current_user),
    ) -> list[dict]:
        require_xiaji_project(app, project_id, user["id"])
        return _store(app).list_documents(user["id"], project_id)

    @router.post("/documents/paste", status_code=201, summary="粘贴文本并解析章节")
    def paste_document(
        payload: XiajiPasteRequest,
        project_id: str = Query(..., description="导台2 项目 ID"),
        user: dict = Depends(mutating_user),
    ) -> dict:
        require_xiaji_project(app, project_id, user["id"])
        text = (payload.text or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="请先粘贴或输入正文")
        if payload.replace:
            _replace_project_content(app, user["id"], project_id)
        document = _ingest_plain_text(
            _store(app),
            user["id"],
            project_id=project_id,
            title=payload.title,
            original_text=text,
            filename="paste.txt",
            source_format="txt",
        )
        return _run_llm_analysis(
            app,
            document,
            user["id"],
            spine_template=payload.spine_template,
            visual_style=payload.visual_style,
            art_style_id=payload.art_style_id,
            narration_style=payload.narration_style,
            ethnicity=payload.ethnicity,
        )

    @router.get("/documents/{document_id}", summary="读取文档原文与章节")
    def get_document(
        document_id: str = FastApiPath(..., description="导台2 内容库文档 ID"),
        user: dict = Depends(current_user),
    ) -> dict:
        return _document_or_404(_store(app), document_id, user["id"])

    @router.post("/documents", status_code=201, summary="上传文本并解析章节")
    async def upload_document(
        file: UploadFile = File(description="TXT / Markdown / DOCX"),
        project_id: str = Query(..., description="导台2 项目 ID"),
        user: dict = Depends(mutating_user),
        title: str | None = Form(None),
        spine_template: str = Form("drama"),
        visual_style: str = Form(""),
        art_style_id: str = Form(""),
        narration_style: str = Form(""),
        ethnicity: str = Form(""),
        replace: str = Form("false"),
    ) -> dict:
        require_xiaji_project(app, project_id, user["id"])
        filename = Path(file.filename or "untitled.txt").name
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=422, detail="仅支持 TXT、Markdown 和 DOCX")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=422, detail="文件是空的")
        if len(content) > MAX_INGEST_BYTES:
            raise HTTPException(status_code=413, detail="文本文件不能超过 8 MB")
        try:
            original_text, source_format = load_source_text(filename, content)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not original_text.strip():
            raise HTTPException(status_code=422, detail="没有可解析的正文")
        if _as_bool(replace):
            _replace_project_content(app, user["id"], project_id)
        document = _ingest_plain_text(
            _store(app),
            user["id"],
            project_id=project_id,
            title=(title or "").strip(),
            original_text=original_text,
            filename=filename,
            source_format=source_format,
        )
        return _run_llm_analysis(
            app,
            document,
            user["id"],
            spine_template=spine_template,
            visual_style=visual_style,
            art_style_id=art_style_id,
            narration_style=narration_style,
            ethnicity=ethnicity,
        )

    @router.put("/documents/{document_id}/chapters", summary="保存章节校对结果")
    def replace_chapters(
        payload: XiajiChaptersReplaceRequest,
        document_id: str = FastApiPath(..., description="导台2 内容库文档 ID"),
        user: dict = Depends(mutating_user),
    ) -> dict:
        store = _store(app)
        _document_or_404(store, document_id, user["id"])
        try:
            return store.replace_chapters(
                document_id,
                user["id"],
                [item.model_dump() for item in payload.chapters],
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.delete("/documents/{document_id}", summary="删除内容库文档")
    def delete_document(
        document_id: str = FastApiPath(..., description="导台2 内容库文档 ID"),
        user: dict = Depends(mutating_user),
    ) -> dict:
        try:
            _store(app).delete_document(document_id, user["id"])
        except KeyError as error:
            raise HTTPException(status_code=404, detail="文档不存在") from error
        return {"ok": True}

    app.include_router(router)
