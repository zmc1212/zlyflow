from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from fastapi import Depends, File, HTTPException, Path as ApiPath, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ...local_media import LocalMediaError, path_for_token
from ..services.qiniu_service import QiniuService
from ..services.smart_edit_document import validate_document
from ..services.smart_edit_render import probe
from ..services import smart_edit_service as service


class SaveEditRequest(BaseModel):
    revision: int = Field(ge=0, description="读取工程时得到的版本号；首次保存为 0，过期版本返回 409。")
    document: dict = Field(description="版本为 1 的完整剪辑工程，含设置、素材和按输出秒计时的三轨片段。")


class EditActionRequest(BaseModel):
    operation: str = Field(default="video_arrange", description="剪辑动作：video_arrange 智能铺轨、subtitle_arrange 自动字幕（按分集对白）、audio_subtitle 音轨字幕（按已完成的音轨转写）、subtitle_translate 字幕翻译（把文字轨已有字幕翻成简体中文，只改文本）、dialogue_cut 对白精剪、quick_cut 成片速剪、highlight_cut 高光合集、hook_cut 引流剪辑。")
    revision: int = Field(ge=0, description="已保存的剪辑版本；版本过期需重新预览。")
    session_id: str | None = Field(default=None, max_length=96, description="可选的当前分集剪辑助手会话，用于保存动作消息。")
    asset_ids: list[str] | None = Field(default=None, max_length=200, description="可选：按给定顺序铺轨的视频素材 ID，仅用于 video_arrange。")
    strategy: str | None = Field(default=None, max_length=32, description="引流剪辑策略：conflict_3s、climax_only、quote_open、ending_hook、trailer；仅用于 hook_cut。")


class ReorderEditRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=200, description="按目标顺序排列的视频素材 ID。")


class ReapplyEditRequest(BaseModel):
    revision: int = Field(ge=0, description="已保存的剪辑版本；版本过期需重新应用。")
    session_id: str | None = Field(default=None, max_length=96, description="可选的当前分集剪辑助手会话，用于保存动作消息。")


class UnderstandingRequest(BaseModel):
    force: bool = Field(default=False, description="是否忽略已有成功结果并重新抽取关键帧理解；进行中的任务不会重复启动。")


class TranscriptionRequest(BaseModel):
    force: bool = Field(default=False, description="是否忽略已有转写结果并重新下载音轨；进行中的任务不会重复启动。")


class ExportEditRequest(BaseModel):
    document: dict = Field(description="本次导出的完整有效工程快照，导出过程不修改原片。")
    quality: int = Field(default=1080, description="导出清晰度：720 或 1080；按工程比例等比缩放。")
    output_dir: str | None = Field(default=None, max_length=4096, description="可选：本机绝对文件夹路径。留空保存到服务器 data/exports/smart-edit；员工只能写入管理员配置的允许目录。")


class ImportLocalRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096, description="本机绝对路径：单个视频/图片/音频文件，或包含素材的文件夹。仅引用原文件，不复制、不上传。")
    recursive: bool = Field(default=False, description="路径为文件夹时是否包含子目录中的素材。")


class BundleEditRequest(BaseModel):
    document: dict = Field(description="需要打包的剪辑工程；ZIP 总会附带完整 JSON 备份。")
    format: str = Field(default="json", description="工程格式：json、xml、otio 或 jianying（基础草稿）。")
    include_media: bool = Field(default=False, description="是否将时间线已使用的原始素材打包到 media 目录。")


def register_smart_edit_routes(app, *, current_user: Callable, mutating_user: Callable) -> None:
    prefix = "/api/projects/{project_id}/smart-edit"

    def call(function, *args):
        try:
            return function(*args)
        except service.EditConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    def editing_call(method, *args, **kwargs):
        from ...director_assistant.repository import AssistantConflict, AssistantNotFound
        try:
            return getattr(app.state.director_assistant.editing, method)(*args, **kwargs)
        except AssistantNotFound as error:
            raise HTTPException(404, str(error)) from error
        except AssistantConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    def understanding_call(method, *args, **kwargs):
        from ...director_assistant.repository import AssistantConflict, AssistantNotFound
        try:
            return getattr(app.state.director_assistant.understanding, method)(*args, **kwargs)
        except AssistantNotFound as error:
            raise HTTPException(404, str(error)) from error
        except AssistantConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    def transcription_call(method, *args, **kwargs):
        from ...director_assistant.repository import AssistantConflict, AssistantNotFound
        try:
            return getattr(app.state.director_assistant.transcription, method)(*args, **kwargs)
        except AssistantNotFound as error:
            raise HTTPException(404, str(error)) from error
        except AssistantConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.get(prefix + "/{sequence_id}/understanding", tags=["智能剪辑"], summary="读取当前账号的视频画面理解结果")
    def read_understanding(project_id: str, sequence_id: str, user: dict = Depends(current_user)):
        return understanding_call("read", str(user["id"]), project_id, sequence_id)

    @app.post(prefix + "/{sequence_id}/understanding", tags=["智能剪辑"], summary="抽取镜头关键帧并启动视频画面理解")
    def start_understanding(project_id: str, sequence_id: str, body: UnderstandingRequest, user: dict = Depends(mutating_user)):
        return understanding_call("start", str(user["id"]), project_id, sequence_id, force=body.force)

    @app.get(prefix + "/{sequence_id}/transcript", tags=["智能剪辑"], summary="读取当前账号的音轨转写结果")
    def read_transcript(project_id: str, sequence_id: str, user: dict = Depends(current_user)):
        return transcription_call("read", str(user["id"]), project_id, sequence_id)

    @app.post(prefix + "/{sequence_id}/transcript", tags=["智能剪辑"], summary="下载时间线有声素材、提取音轨并启动语音转写")
    def start_transcript(project_id: str, sequence_id: str, body: TranscriptionRequest, user: dict = Depends(mutating_user)):
        return transcription_call("start", str(user["id"]), project_id, sequence_id, force=body.force)

    @app.post(prefix + "/{sequence_id}/actions/preview", tags=["智能剪辑"], summary="预览智能铺轨清单，不修改时间线")
    def preview_action(project_id: str, sequence_id: str, body: EditActionRequest, user: dict = Depends(mutating_user)):
        return editing_call("preview", str(user["id"]), project_id, sequence_id, **body.model_dump())

    @app.get(prefix + "/{sequence_id}/actions/{action_id}", tags=["智能剪辑"], summary="查询当前账号的铺轨清单与真实执行结果")
    def read_action(project_id: str, sequence_id: str, action_id: str, user: dict = Depends(current_user)):
        return editing_call("get", str(user["id"]), project_id, sequence_id, action_id)

    @app.post(prefix + "/{sequence_id}/actions/{action_id}/reorder", tags=["智能剪辑"], summary="按用户调整后的顺序重新生成待确认的铺轨清单")
    def reorder_action(project_id: str, sequence_id: str, action_id: str, body: ReorderEditRequest, user: dict = Depends(mutating_user)):
        return editing_call("reorder", str(user["id"]), project_id, sequence_id, action_id, body.asset_ids)

    @app.post(prefix + "/{sequence_id}/actions/{action_id}/reapply", tags=["智能剪辑"], summary="按已执行的字幕翻译记录对当前时间线重新生成待确认清单")
    def reapply_action(project_id: str, sequence_id: str, action_id: str, body: ReapplyEditRequest, user: dict = Depends(mutating_user)):
        return editing_call("reapply", str(user["id"]), project_id, sequence_id, action_id, revision=body.revision, session_id=body.session_id)

    @app.post(prefix + "/{sequence_id}/actions/{action_id}/confirm", tags=["智能剪辑"], summary="确认并幂等执行剪辑方案，原子保存剪辑文档与执行结果")
    def confirm_action(project_id: str, sequence_id: str, action_id: str, user: dict = Depends(mutating_user)):
        return editing_call("confirm", str(user["id"]), project_id, sequence_id, action_id)

    @app.get(prefix + "/{sequence_id}", tags=["智能剪辑"], summary="读取账号隔离的分集剪辑工程")
    def read_edit(project_id: str, sequence_id: str, user: dict = Depends(current_user)):
        return call(service.read_document, project_id, str(user["id"]), sequence_id)

    @app.put(prefix + "/{sequence_id}", tags=["智能剪辑"], summary="按版本保存剪辑工程，防止多窗口覆盖")
    def save_edit(project_id: str, sequence_id: str, body: SaveEditRequest, user: dict = Depends(mutating_user)):
        return call(service.save_document, project_id, str(user["id"]), sequence_id, body.revision, body.document)

    @app.get(prefix + "/{sequence_id}/sources", tags=["智能剪辑"], summary="获取分集成片、分镜图、配音与项目图片")
    def sources(project_id: str, sequence_id: str, user: dict = Depends(current_user)):
        return call(service.project_sources, project_id, sequence_id)

    @app.get("/api/local-media/{token}", tags=["智能剪辑"], summary="按签名地址播放本机引用的素材")
    def local_media(token: str = ApiPath(description="本机素材签名 token，由「引用本机」导入结果返回；只读且校验签名。"),
                    user: dict = Depends(current_user)):
        try:
            path = path_for_token(token)
        except LocalMediaError as error:
            raise HTTPException(404, str(error)) from error
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    @app.post(prefix + "/{sequence_id}/import-local", tags=["智能剪辑"], summary="直接引用本机文件或文件夹，不复制、不上传")
    def import_local(project_id: str, sequence_id: str, body: ImportLocalRequest, user: dict = Depends(mutating_user)):
        call(service.project_or_error, project_id)
        return call(service.import_local_media, body.path, body.recursive, user)

    @app.post(prefix + "/{sequence_id}/upload", tags=["智能剪辑"], summary="导入媒体并探测实际时长")
    def upload(project_id: str, sequence_id: str, file: UploadFile = File(...), user: dict = Depends(mutating_user)):
        call(service.project_or_error, project_id)
        extension = Path(file.filename or "").suffix.lower()
        kinds = {".mp4": "video", ".mov": "video", ".webm": "video", ".mkv": "video", ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".ogg": "audio", ".flac": "audio"}
        if extension not in kinds:
            raise HTTPException(400, "支持 MP4/MOV/WebM、PNG/JPG/WebP 和 MP3/WAV/M4A/OGG/FLAC")
        if not QiniuService.get_config().available:
            raise HTTPException(400, "请先在管理设置中启用七牛云媒体存储")
        with tempfile.TemporaryDirectory(prefix="zly-edit-import-") as directory:
            path = Path(directory) / ("upload" + extension)
            total = 0
            with path.open("wb") as output:
                while chunk := file.file.read(1024 * 1024):
                    total += len(chunk)
                    if total > service.MAX_FILE_BYTES:
                        raise HTTPException(413, "单个素材不能超过 512 MB")
                    output.write(chunk)
            info = call(probe, path)
            kind = kinds[extension]
            if kind in {"video", "image"} and not info["has_video"] or kind == "audio" and not info["has_audio"]:
                raise HTTPException(400, "素材实际类型与扩展名不符，请重新选择文件")
            if kind == "image":
                info["duration"] = 5
            _, url = QiniuService.store_bytes("smart-edit", file.filename or path.name, path.read_bytes())
        return {"id": "import-" + service.uuid.uuid4().hex[:20], "name": file.filename or "导入素材", "kind": kind, "url": url, "thumbnail": url if kind == "image" else None, **info}

    @app.post(prefix + "/exports/mp4", status_code=202, tags=["智能剪辑"], summary="按当前时间线导出真实 MP4，可指定本机输出目录")
    def export_video(project_id: str, body: ExportEditRequest, user: dict = Depends(mutating_user)):
        if body.quality not in {720, 1080}:
            raise HTTPException(400, "请选择 720P 或 1080P")
        return call(service.create_export, project_id, str(user["id"]), body.document, body.quality,
                    body.output_dir, user)

    @app.get(prefix + "/exports/{job_id}", tags=["智能剪辑"], summary="查询当前账号的剪辑导出任务")
    def export_status(project_id: str, job_id: str, user: dict = Depends(current_user)):
        return call(service.get_export, project_id, str(user["id"]), job_id)

    @app.get(prefix + "/exports/{job_id}/file", tags=["智能剪辑"], summary="下载本机导出的 MP4 成片")
    def export_file(project_id: str, job_id: str, user: dict = Depends(current_user)):
        path = call(service.export_file_path, project_id, str(user["id"]), job_id)
        return FileResponse(path, media_type="video/mp4", filename=f"{job_id}.mp4", content_disposition_type="attachment")

    @app.post(prefix + "/exports/bundle", tags=["智能剪辑"], summary="导出 JSON/XML/OTIO 工程及可选素材包")
    def bundle(project_id: str, body: BundleEditRequest, user: dict = Depends(mutating_user)):
        call(service.project_or_error, project_id)
        if body.format not in {"json", "xml", "otio", "jianying"}:
            raise HTTPException(400, "不支持的工程格式")
        call(validate_document, body.document)
        directory = tempfile.TemporaryDirectory(prefix="zly-edit-bundle-")
        try:
            result = call(service.write_bundle, body.document, body.format, body.include_media, Path(directory.name))
        except Exception:
            directory.cleanup()
            raise
        return FileResponse(result, media_type="application/zip", filename="smart-edit-project.zip", background=BackgroundTask(directory.cleanup))
