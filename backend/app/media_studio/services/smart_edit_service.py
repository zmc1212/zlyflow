from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import requests

from ...config import settings
from ...local_media import LOCAL_MEDIA_EXTENSIONS, is_local_url, path_for_url, url_for_path, ensure_export_allowed, ensure_import_allowed
from ..db import execute_sql, now_str, query_all, query_one
from .project_detail_service import ProjectDetailService
from .project_service import ProjectService
from .qiniu_service import QiniuService
from .smart_edit_document import empty_document, media_url, validate_document
from .smart_edit_render import export_jianying, export_otio, export_xml, probe, render_document

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smart-edit-export")
_ACTIVE: set[str] = set()
_LOCK = threading.Lock()
MAX_FILE_BYTES = 512 * 1024 * 1024


class EditConflict(ValueError):
    pass


def document_id(project_id: str, owner: str, sequence: str) -> str:
    return hashlib.sha256(json.dumps([project_id, owner, sequence]).encode()).hexdigest()


def project_or_error(project_id: str):
    project = ProjectService.get_project(project_id)
    if not project:
        raise ValueError("工程不存在")
    return project


def read_document(project_id: str, owner: str, sequence: str) -> dict:
    project = project_or_error(project_id)
    row = query_one("SELECT * FROM ai_smart_edit_documents WHERE id = %s AND owner_user_id = %s", (document_id(project_id, owner, sequence), owner))
    if not row:
        return {"revision": 0, "document": empty_document(f"{project.name} · 剪辑"), "updated_at": None, "draft_key": document_id(project_id, owner, sequence)}
    return {"revision": row["revision"], "document": json.loads(row["document_json"]), "updated_at": str(row["updated_at"]), "draft_key": document_id(project_id, owner, sequence)}


def save_document(project_id: str, owner: str, sequence: str, revision: int, document: dict) -> dict:
    project_or_error(project_id)
    if not sequence or len(sequence) > 160:
        raise ValueError("剪辑序列 ID 无效")
    doc = validate_document(document)
    did, timestamp = document_id(project_id, owner, sequence), now_str()
    content = json.dumps(doc, ensure_ascii=False, allow_nan=False)
    if len(content.encode()) > 2 * 1024 * 1024:
        raise ValueError("工程过大，请减少素材或片段")
    if revision == 0:
        try:
            execute_sql("INSERT INTO ai_smart_edit_documents (id, project_id, owner_user_id, sequence_id, revision, document_json, created_at, updated_at) VALUES (%s, %s, %s, %s, 1, %s, %s, %s)", (did, project_id, owner, sequence, content, timestamp, timestamp))
        except Exception as error:
            if query_one("SELECT id FROM ai_smart_edit_documents WHERE id = %s", (did,)):
                raise EditConflict("该剪辑已在其他窗口保存。请先下载当前 JSON 备份，再重新加载云端版本。") from error
            raise
    else:
        changed = execute_sql("UPDATE ai_smart_edit_documents SET document_json = %s, revision = revision + 1, updated_at = %s WHERE id = %s AND owner_user_id = %s AND revision = %s", (content, timestamp, did, owner, revision))
        if not changed:
            raise EditConflict("该剪辑已在其他窗口更新。请先下载当前 JSON 备份，再重新加载云端版本。")
    return {"revision": revision + 1, "document": doc, "updated_at": timestamp, "draft_key": did}


def project_sources(project_id: str, sequence: str, owner: str | None = None) -> list[dict]:
    project_or_error(project_id)
    assets: list[dict] = []
    if sequence != "main":
        detail = ProjectDetailService.get_episode_detail(project_id, sequence)
        beats = sorted(detail.get("beats") or [], key=lambda beat: int(beat.get("sequence") or 0))
        for beat in beats:
            duration = float(beat.get("duration_sec") or beat.get("video_duration") or 8)
            video = beat.get("upscaled_video_url") or beat.get("video_url")
            thumb = beat.get("render_url") or beat.get("sketch_url")
            if video:
                assets.append({"id": f"beat-{beat['id']}-{hashlib.sha256(video.encode()).hexdigest()[:8]}", "name": f"镜头 {beat.get('sequence') or len(assets)+1} · {beat.get('heading') or '成片'}", "url": video, "kind": "video", "duration": duration, "thumbnail": thumb, "beat_id": beat["id"]})
            elif thumb:
                assets.append({"id": f"beat-{beat['id']}-{hashlib.sha256(thumb.encode()).hexdigest()[:8]}", "name": f"镜头 {beat.get('sequence') or len(assets)+1} · 分镜图", "url": thumb, "kind": "image", "duration": duration, "thumbnail": thumb, "beat_id": beat["id"]})
            for line in beat.get("dubbing_lines") or []:
                url = line.get("audio_url") or line.get("result_url")
                if url:
                    assets.append({"id": f"voice-{line.get('id') or beat['id']}-{hashlib.sha256(url.encode()).hexdigest()[:8]}", "name": f"配音 · {str(line.get('text') or '')[:30]}", "kind": "audio", "url": url, "duration": float(line.get('duration_sec') or line.get('duration') or 5), "beat_id": beat["id"]})
    for asset in ProjectDetailService.list_assets(project_id):
        item = asset if isinstance(asset, dict) else asset.model_dump()
        if item.get("image_url"):
            assets.append({"id": f"asset-{item['id']}", "name": item.get("name") or "项目图片", "url": item["image_url"], "kind": "image", "duration": 5, "thumbnail": item["image_url"]})
    # Music generated in the workbench becomes BGM material; scoped to the
    # current account so one user never sees another's soundtracks.
    if owner:
        rows = query_all("SELECT id, title, result_url, duration_seconds FROM music_jobs "
                         "WHERE owner_user_id = %s AND status = 'succeeded' AND result_url IS NOT NULL "
                         "ORDER BY created_at DESC, id DESC LIMIT 20", (owner,))
        assets.extend({"id": f"music-{row['id']}", "name": f"音乐 · {(row.get('title') or '未命名')[:30]}",
                       "kind": "audio", "url": row["result_url"],
                       "duration": float(row.get("duration_seconds") or 0) or 5} for row in rows)
    return assets


def import_local_media(path_value: str, recursive: bool, user: dict) -> dict:
    raw = str(path_value or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("请输入本机文件或文件夹路径")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("请输入本机绝对路径，例如 G:\\工作区\\S01E09")
    try:
        path = ensure_import_allowed(path, user)
    except PermissionError as error:
        raise ValueError(str(error)) from error
    if not path.exists():
        raise ValueError("路径不存在，请检查后重试")
    if path.is_file():
        if path.suffix.lower() not in LOCAL_MEDIA_EXTENSIONS:
            raise ValueError("支持 MP4/MOV/WebM/MKV、PNG/JPG/WebP 和 MP3/WAV/M4A/OGG/FLAC")
        files = [path]
    elif path.is_dir():
        candidates = path.rglob("*") if recursive else path.iterdir()
        files = sorted(
            (item for item in candidates if item.is_file() and item.suffix.lower() in LOCAL_MEDIA_EXTENSIONS),
            key=lambda item: [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(item))],
        )
    else:
        raise ValueError("路径既不是文件也不是文件夹")
    if not files:
        raise ValueError("该路径下没有支持的视频、图片或音频文件")
    if len(files) > 200:
        raise ValueError("一次最多导入 200 个素材，请选择更具体的文件夹")
    assets, skipped = [], []
    for file in files:
        kind = LOCAL_MEDIA_EXTENSIONS[file.suffix.lower()]
        try:
            info = probe(file)
        except (ValueError, RuntimeError) as error:
            skipped.append({"name": file.name, "error": str(error)})
            continue
        if kind == "audio" and not info["has_audio"]:
            skipped.append({"name": file.name, "error": "文件没有音轨"})
            continue
        if kind != "audio" and not info["has_video"]:
            skipped.append({"name": file.name, "error": "文件没有画面"})
            continue
        if kind == "image":
            info["duration"] = 5
        url = url_for_path(file)
        assets.append({
            "id": "local-" + uuid.uuid4().hex[:20], "name": file.name or "本机素材", "kind": kind,
            "url": url, "thumbnail": url if kind == "image" else None, "local_path": str(file), **info,
        })
    return {"path": str(path), "assets": assets, "skipped": skipped}


def download_asset(asset: dict, destination: Path) -> Path:
    """Local references stay in place; remote assets may only come from configured storage."""
    url = media_url(asset.get("url"))
    if is_local_url(url):
        return path_for_url(url)
    config = QiniuService.get_config()
    trusted = urlsplit(config.domain if "://" in config.domain else "https://" + config.domain)
    actual = urlsplit(url)
    if not trusted.hostname or (actual.hostname, actual.port) != (trusted.hostname, trusted.port):
        raise ValueError("素材地址不属于当前配置的媒体存储，请通过「导入素材」重新上传后导出")
    suffix = Path(urlsplit(url).path).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ".png" if asset["kind"] == "image" else ".mp4" if asset["kind"] == "video" else ".wav"
    destination = destination.with_suffix(suffix)
    with requests.get(url, stream=True, timeout=(15, 60), allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("素材地址发生跳转或不可下载，请重新导入")
        total = 0
        with destination.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                total += len(chunk)
                if total > MAX_FILE_BYTES:
                    raise ValueError("单个素材不能超过 512 MB")
                output.write(chunk)
    if not total:
        raise ValueError("素材文件为空，请重新导入")
    return destination


def _export_filename(document: dict, jid: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", str(document.get("name") or "智能剪辑"))
    name = (name.strip(" .") or "智能剪辑")[:60].rstrip(" .")
    return f"{name}-{time.strftime('%Y%m%d-%H%M%S')}-{jid[-6:]}.mp4"


def create_export(project_id: str, owner: str, document: dict, quality: int,
                  output_dir: str | None = None, user: dict | None = None) -> dict:
    project_or_error(project_id)
    doc = validate_document(document)
    if quality not in {720, 1080}:
        raise ValueError("请选择 720P 或 1080P")
    if not doc["clips"]:
        raise ValueError("时间线为空，请先添加素材")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ValueError("服务器需要安装 FFmpeg 和 ffprobe 才能导出成片")
    requested = str(output_dir or "").strip().strip('"').strip("'")
    if requested:
        if user is None:
            raise ValueError("指定导出目录需要当前账号信息")
        path = Path(requested).expanduser()
        if not path.is_absolute():
            raise ValueError("导出目录必须是本机绝对路径")
        try:
            directory = ensure_export_allowed(path, user)
        except PermissionError as error:
            raise ValueError(str(error)) from error
    else:
        directory = settings.exports_dir / "smart-edit"
    with _LOCK:
        if len(_ACTIVE) >= 4:
            raise ValueError("导出队列已满，请等待当前任务完成")
        active = query_one("SELECT id FROM ai_project_jobs WHERE project_id = %s AND job_type = 'smart_edit_export' AND status IN ('queued', 'running')", (project_id,))
        if active and active["id"] in _ACTIVE:
            raise ValueError("该工程正在导出，请等待完成后再试")
        jid, timestamp = f"edit-{uuid.uuid4().hex[:20]}", now_str()
        snapshot_sequence = f"export:{jid}"
        save_document(project_id, owner, snapshot_sequence, 0, doc)
        target = directory / f"{jid}.mp4" if not requested else directory / _export_filename(doc, jid)
        # Existing generic job-detail routes must not expose another account's document.
        payload = {"owner_user_id": owner, "project_id": project_id, "quality": quality, "source": "smart_edit", "name": doc["name"], "fps": doc["settings"]["fps"], "aspect_ratio": doc["settings"]["ratio"], "clip_count": len(doc["clips"]), "document_sequence": snapshot_sequence, "output_path": str(target)}
        execute_sql("INSERT INTO ai_project_jobs (id, project_id, job_type, title, status, progress, payload_json, created_at, updated_at) VALUES (%s, %s, 'smart_edit_export', %s, 'queued', 0, %s, %s, %s)", (jid, project_id, f"智能剪辑 · {doc['name']}", json.dumps(payload, ensure_ascii=False), timestamp, timestamp))
        _ACTIVE.add(jid)
    _EXECUTOR.submit(_run_export, jid, {**payload, "document": doc})
    return {"id": jid, "status": "queued", "progress": 0, "output_path": str(target)}


def _run_export(jid: str, payload: dict) -> None:
    try:
        def progress(value):
            execute_sql("UPDATE ai_project_jobs SET status = 'running', progress = %s, updated_at = %s WHERE id = %s", (value, now_str(), jid))
        target = Path(payload.get("output_path") or settings.exports_dir / "smart-edit" / f"{jid}.mp4")
        with tempfile.TemporaryDirectory(prefix="zly-smart-edit-") as directory:
            output = render_document(payload["document"], Path(directory), download_asset, progress, payload["quality"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(output), target)
        url = f"/api/projects/{payload['project_id']}/smart-edit/exports/{jid}/file"
        execute_sql("UPDATE ai_project_jobs SET status = 'completed', progress = 100, result_url = %s, completed_at = %s, updated_at = %s WHERE id = %s", (url, now_str(), now_str(), jid))
    except Exception as error:
        execute_sql("UPDATE ai_project_jobs SET status = 'failed', error_message = %s, completed_at = %s, updated_at = %s WHERE id = %s", (str(error)[:2000], now_str(), now_str(), jid))
    finally:
        with _LOCK:
            _ACTIVE.discard(jid)


def get_export(project_id: str, owner: str, jid: str) -> dict:
    row = query_one("SELECT * FROM ai_project_jobs WHERE id = %s AND project_id = %s AND job_type = 'smart_edit_export'", (jid, project_id))
    payload = json.loads(row.get("payload_json") or "{}") if row else {}
    if not row or payload.get("owner_user_id") != owner:
        raise ValueError("导出任务不存在")
    with _LOCK:
        interrupted = row["status"] in {"queued", "running"} and jid not in _ACTIVE
    if interrupted:
        execute_sql("UPDATE ai_project_jobs SET status = 'failed', error_message = %s, updated_at = %s WHERE id = %s AND status IN ('queued', 'running')", ("服务重启导致导出中断，请重新导出", now_str(), jid))
        row.update(status="failed", error_message="服务重启导致导出中断，请重新导出")
    result = {key: row.get(key) for key in ("id", "status", "progress", "result_url", "error_message")}
    result["output_path"] = payload.get("output_path")
    return result


def export_file_path(project_id: str, owner: str, jid: str) -> Path:
    if not re.fullmatch(r"edit-[0-9a-f]{20}", jid):
        raise ValueError("导出任务不存在")
    job = get_export(project_id, owner, jid)
    if job["status"] != "completed":
        raise ValueError("导出尚未完成")
    path = Path(job.get("output_path") or settings.exports_dir / "smart-edit" / f"{jid}.mp4")
    if not path.is_absolute():
        raise ValueError("导出文件路径无效，请重新导出")
    if not path.is_file():
        raise ValueError("导出文件已被移动或清理，请重新导出")
    return path


def write_bundle(document: dict, format_name: str, include_media: bool, root: Path) -> Path:
    doc = validate_document(document)
    names = {}
    output = root / "project.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        if include_media:
            ids = {c["asset_id"] for c in doc["clips"] if c["track"] != "text"}
            total = 0
            for index, asset in enumerate(a for a in doc["assets"] if a["id"] in ids):
                path = download_asset(asset, root / f"media-{index}")
                total += path.stat().st_size
                if total > 2 * 1024**3:
                    raise ValueError("素材总量超过 2 GB，请分批导出或关闭「打包素材」")
                name = f"media/{index+1:03d}{path.suffix}"
                archive.write(path, name)
                names[asset["id"]] = name
        # Always include the lossless document alongside interchange files.
        archive.writestr("project.zly.json", json.dumps(doc, ensure_ascii=False, indent=2))
        if format_name == "xml":
            archive.writestr("timeline.xml", export_xml(doc, names))
        elif format_name == "otio":
            archive.writestr("timeline.otio", json.dumps(export_otio(doc, names), ensure_ascii=False, indent=2))
        elif format_name == "jianying":
            meta, content = export_jianying(doc, names)
            archive.writestr("draft_meta_info.json", json.dumps(meta, ensure_ascii=False, indent=2))
            archive.writestr("draft_content.json", json.dumps(content, ensure_ascii=False, indent=2))
        archive.writestr("使用说明.txt", "project.zly.json 可在导演台智能剪辑中完整恢复。\nXML / OTIO 交换剪辑点、轨道和速度，文字、调色及画面变换由目标软件重新调整；完整效果以 MP4 和 JSON 工程为准。\n剪映基础草稿沿用本工作台既有草稿结构，保留画面/音频剪辑点、速度、音量和变换；文字、特效与淡入淡出需在剪映重建。兼容性取决于电脑版版本，未在剪映客户端实机验收。\n剪映草稿文件夹可复制到 %LOCALAPPDATA%/JianyingPro/User Data/Projects/com.lveditor.draft/，如提示素材丢失请重新定位 media。\n打包素材后请保持 media 目录与工程文件同级，目标软件如提示缺失可重连到 media。\nJSON 原始地址需仍然可访问；打包素材可供外部后期软件离线重连。\n")
    return output
