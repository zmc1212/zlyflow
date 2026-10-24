"""MCP-facing smart editing backed by the director assistant's deterministic actions."""
from __future__ import annotations

import math
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..director_assistant.repository import AssistantConflict, AssistantNotFound, dumps
from ..media_studio.db import now_str
from ..media_studio.models import ProjectCreateRequest
from ..media_studio.services.project_detail_service import ProjectDetailService
from ..media_studio.services.project_service import ProjectService
from ..media_studio.services.smart_edit_document import timeline_duration, validate_document
from ..media_studio.services.smart_edit_service import EditConflict, create_export, get_export, import_local_media, save_document
from .config import McpConfig

TEXT_PRESETS = {
    "title": {"font_size": 110.0, "y": 0.0, "color": "#f5c451"},
    "subtitle": {"font_size": 56.0, "y": 36.0, "color": "#ffffff"},
}
MAX_TEXT_CHARS = 1000
PROPOSAL_FIELDS = (
    "id", "operation", "title", "status", "project_id", "sequence_id", "base_revision",
    "count", "items", "skipped_count", "missing_video_count", "append_at", "total_duration",
    "replaced_count", "inaudible_count", "dropped_count", "trimmed_count",
    "strategy", "strategy_title", "principle", "transcript", "understanding",
    "created_at", "updated_at",
)


def _number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label}必须是数字")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label}必须是数字") from error
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{label}需在 {minimum:g}–{maximum:g} 之间")
    return result


class EditingService:
    def __init__(self, app, config: McpConfig):
        self.app, self.config = app, config

    @property
    def assistant(self):
        value = getattr(self.app.state, "director_assistant", None)
        if value is None or getattr(value, "editing", None) is None:
            raise HTTPException(503, "智能剪辑助手未启用")
        return value

    @property
    def actions(self):
        return self.assistant.editing

    @property
    def transcription(self):
        value = getattr(self.actions, "transcription", None)
        if value is None:
            raise HTTPException(503, "音频转写能力未启用，请先在管理设置检查语音转写配置")
        return value

    def _guard(self, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except AssistantNotFound as error:
            raise HTTPException(404, str(error)) from error
        except (AssistantConflict, EditConflict) as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @staticmethod
    def _proposal(record: dict) -> dict[str, Any]:
        return {key: record[key] for key in PROPOSAL_FIELDS if key in record}

    def projects(self) -> dict[str, Any]:
        projects = []
        for project in ProjectService.list_projects():
            sequences = [{"sequence_id": "main", "episode_num": 0, "title": "自由剪辑", "status": "active"}]
            for episode in ProjectDetailService.list_episodes(project.id):
                sequences.append({"sequence_id": episode["id"], "episode_num": episode.get("episode_num"),
                                  "title": episode.get("title") or "", "status": episode.get("status") or "draft"})
            projects.append({"id": project.id, "name": project.name, "description": project.description,
                             "cover_url": project.cover_url, "status": project.status,
                             "updated_at": project.updated_at, "sequences": sequences})
        return {"projects": projects}

    def timeline(self, owner: str, project: str, sequence: str) -> dict[str, Any]:
        with self.actions.repo.store.connection() as conn:
            self.actions.target(conn, project, sequence)
            snapshot = self.actions.snapshot(conn, owner, project, sequence)
        analysis = self._guard(self.actions.read, owner, project, sequence).get("analysis") or {}
        document = snapshot["document"]
        return {"project_id": project, "sequence_id": sequence, "revision": snapshot["revision"],
                "name": document["name"], "settings": document["settings"],
                "duration": timeline_duration(document), "assets": document["assets"],
                "clips": document["clips"], "analysis": analysis}

    def prepare_episode(self, project_name: str, episode_code: str, *, title: str = "",
                        version: str = "v001", script_text: str = "") -> dict[str, Any]:
        return self._guard(self._prepare_episode, project_name, episode_code, title=title,
                           version=version, script_text=script_text)

    def _prepare_episode(self, project_name: str, episode_code: str, *, title: str,
                         version: str, script_text: str) -> dict[str, Any]:
        name = str(project_name or "").strip()
        match = re.fullmatch(r"S(\d{2,})E(\d{2,})", episode_code)
        if not name or len(name) > 255 or not match or not re.fullmatch(r"v\d{3,}", version):
            raise ValueError("需要准确剧名、S01E09 形式的集号和 v001 形式的版本")
        if len(script_text) > 200000 or len(title) > 120:
            raise ValueError("剧本或集名过长")
        matches = [p for p in ProjectService.list_projects() if p.name == name]
        if len(matches) > 1:
            raise ValueError("存在多个同名工程，请先在工作台消除歧义后再创建本地剪辑目标")
        created_project = not matches
        project = matches[0] if matches else ProjectService.create_project(ProjectCreateRequest(name=name))
        # A separate version target prevents an updated episode from replacing a manual cut.
        marker = f"{episode_code} {version}"
        matches = [e for e in ProjectDetailService.list_episodes(project.id)
                   if e.get("title", "") == marker or e.get("title", "").startswith(marker + " · ")]
        if len(matches) > 1:
            raise ValueError("同集同版本存在多个剪辑目标，请先在工作台确认目标")
        if matches:
            episode = matches[0]
            if script_text:
                detail = ProjectDetailService.get_episode_detail(project.id, episode["id"])
                existing = str(detail.get("script_text") or "")
                if existing.strip() and existing.strip() != script_text.strip():
                    raise ValueError("该剪辑目标的剧本已变化，请使用新版本，不覆盖原剧本")
        else:
            episode = ProjectDetailService.create_episode(project.id, {
                "episode_num": int(match.group(2)), "title": marker + (" · " + title.strip() if title.strip() else ""),
                "script_text": script_text, "status": "draft",
            })
        return {"project_id": project.id, "sequence_id": episode["id"], "project_name": name,
                "episode_code": episode_code, "version": version, "created_project": created_project,
                "created_sequence": not bool(matches)}

    def import_media(self, user: dict, project: str, sequence: str, *, paths: list[str],
                     revision: int, document_name: str = "") -> dict[str, Any]:
        return self._guard(self._import_media, user, project, sequence, paths=paths,
                           revision=revision, document_name=document_name)

    def _import_media(self, user: dict, project: str, sequence: str, *, paths: list[str],
                      revision: int, document_name: str) -> dict[str, Any]:
        if not paths or len(paths) > 200 or len(document_name) > 200:
            raise ValueError("一次需要 1–200 个明确的本机文件路径，剪辑名称最多 200 字")
        owner = str(user["id"])
        with self.actions.repo.store.connection() as conn:
            self.actions.target(conn, project, sequence)
            snapshot = self.actions.snapshot(conn, owner, project, sequence)
        if isinstance(revision, bool) or revision != snapshot["revision"]:
            raise AssistantConflict("时间线已变化，请先重新读取 revision 再导入")
        document = validate_document(snapshot["document"])
        by_url = {asset["url"]: asset for asset in document["assets"]}
        ordered, added = [], []
        for path in paths:
            result = import_local_media(path, False, user)
            if not Path(result["path"]).is_file() or result.get("skipped") or len(result["assets"]) != 1:
                raise ValueError("请传入可解码的单个文件路径；文件夹或失败素材不会部分写入时间线")
            asset = result["assets"][0]
            existing = by_url.get(asset["url"])
            if existing is None:
                document["assets"].append(asset)
                by_url[asset["url"]] = asset
                added.append(asset["id"])
            chosen = existing or asset
            if chosen["id"] in ordered:
                raise ValueError("本批包含重复文件，请先按单元清单去重")
            ordered.append(chosen["id"])
        changed_name = bool(document_name.strip() and document_name.strip() != document["name"])
        if changed_name:
            document["name"] = document_name.strip()
        if added or changed_name:
            saved = save_document(project, owner, sequence, revision, document)
            revision = saved["revision"]
        return {"project_id": project, "sequence_id": sequence, "revision": revision,
                "asset_ids": ordered, "added_count": len(added), "reused_count": len(ordered) - len(added),
                "clip_count": len(document["clips"])}

    def transcript(self, owner: str, project: str, sequence: str) -> dict[str, Any]:
        return self._guard(self.transcription.read, owner, project, sequence)

    def start_transcript(self, owner: str, project: str, sequence: str, *, force: bool = False) -> dict[str, Any]:
        return self._guard(self.transcription.start, owner, project, sequence, force=force)

    def preview(self, owner: str, project: str, sequence: str, *, operation: str, revision: int | None = None,
                asset_ids: list[str] | None = None, strategy: str | None = None) -> dict[str, Any]:
        record = self._guard(self.actions.preview, owner, project, sequence, revision=revision,
                             operation=operation, asset_ids=asset_ids, strategy=strategy)
        return self._proposal(record)

    def action(self, owner: str, project: str, sequence: str, action_id: str) -> dict[str, Any]:
        return self._proposal(self._guard(self.actions.get, owner, project, sequence, action_id))

    def reorder(self, owner: str, project: str, sequence: str, action_id: str,
                asset_ids: list[str]) -> dict[str, Any]:
        return self._proposal(self._guard(self.actions.reorder, owner, project, sequence, action_id, asset_ids))

    def confirm(self, owner: str, project: str, sequence: str, action_id: str) -> dict[str, Any]:
        record = self._guard(self.actions.confirm, owner, project, sequence, action_id)
        result = self._proposal(record)
        snapshot = record.get("snapshot") or {}
        if snapshot:
            result["revision"] = snapshot.get("revision")
            result["duration"] = timeline_duration(snapshot["document"])
        return result

    def _document(self, owner: str, project: str, sequence: str) -> dict[str, Any]:
        with self.actions.repo.store.connection() as conn:
            self.actions.target(conn, project, sequence)
            return self.actions.snapshot(conn, owner, project, sequence)["document"]

    def export(self, user: dict, project: str, sequence: str, *, output_dir: str | None = None,
               quality: int = 1080) -> dict[str, Any]:
        owner = str(user["id"])
        document = self._guard(self._document, owner, project, sequence)
        result = self._guard(create_export, project, owner, document, quality, output_dir, user)
        result["download_url"] = f"/api/projects/{project}/smart-edit/exports/{result['id']}/file"
        return result

    def export_status(self, owner: str, project: str, job_id: str) -> dict[str, Any]:
        result = self._guard(get_export, project, owner, job_id)
        result["download_url"] = f"/api/projects/{project}/smart-edit/exports/{job_id}/file"
        return result

    def add_text(self, owner: str, project: str, sequence: str, *, text: str, preset: str = "title",
                 start: float = 0.0, duration: float = 3.0, font_size: float | None = None,
                 color: str = "", x: float = 0.0, y: float | None = None) -> dict[str, Any]:
        return self._guard(self._add_text, owner, project, sequence, text=text, preset=preset,
                           start=start, duration=duration, font_size=font_size, color=color, x=x, y=y)

    def _add_text(self, owner: str, project: str, sequence: str, *, text: str, preset: str,
                  start: float, duration: float, font_size: float | None, color: str, x: float,
                  y: float | None) -> dict[str, Any]:
        value = str(text or "").strip()
        if not value or len(value) > MAX_TEXT_CHARS:
            raise ValueError(f"文字不能为空且不能超过 {MAX_TEXT_CHARS} 字")
        if preset not in TEXT_PRESETS:
            raise ValueError("preset 必须为 title 或 subtitle")
        style = TEXT_PRESETS[preset]
        size = _number(font_size if font_size is not None else style["font_size"], "字号", 16, 200)
        offset_x = _number(x, "横向位置", -100, 100)
        offset_y = _number(y if y is not None else style["y"], "纵向位置", -100, 100)
        tone = str(color or style["color"]).strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", tone):
            raise ValueError("文字颜色需为 #RRGGBB")
        with self.actions.repo.transaction() as conn:
            self.actions.target(conn, project, sequence)
            # Serialize first writes like proposal confirmation does.
            conn.execute("SELECT id FROM ai_projects WHERE id=?", (project,), for_update=True).fetchone()
            current = self.actions.snapshot(conn, owner, project, sequence, lock=True)
            document = validate_document(current["document"])
            fps = document["settings"]["fps"]
            begin = round(_number(start, "开始时间", 0, 1800) * fps) / fps
            length = max(1, round(_number(duration, "时长", 1 / fps, 1800) * fps)) / fps
            if begin + length > 1800 + .001:
                raise ValueError("文字片段超出 30 分钟时间线")
            occupied = sorted((clip["start"], clip["start"] + clip["duration"])
                              for clip in document["clips"] if clip["track"] == "text")
            for used_start, used_end in occupied:
                if begin < used_end - 1e-6 and begin + length > used_start + 1e-6:
                    raise ValueError(f"文字轨 {used_start:.2f}–{used_end:.2f} 秒已有内容，请换一个开始时间或先调整已有文字")
            clip = {"id": uuid.uuid4().hex, "track": "text", "start": begin, "duration": length,
                    "in_point": 0, "speed": 1, "volume": 1, "muted": False, "opacity": 1,
                    "scale": 1, "x": offset_x, "y": offset_y, "rotation": 0, "effect": "none",
                    "fade_in": 0, "fade_out": 0, "text": value, "color": tone,
                    "font_size": size, "origin": "manual"}
            document["clips"].append(clip)
            document = validate_document(document)
            revision, timestamp = current["revision"] + 1, now_str()
            if current["revision"]:
                updated = conn.execute(
                    "UPDATE ai_smart_edit_documents SET document_json=?,revision=?,updated_at=?"
                    " WHERE id=? AND owner_user_id=? AND revision=?",
                    (dumps(document), revision, timestamp, current["draft_key"], owner, current["revision"]))
                if updated.rowcount != 1:
                    raise AssistantConflict("时间线已变化，请重新读取后再添加文字")
            else:
                conn.execute(
                    "INSERT INTO ai_smart_edit_documents"
                    " (id,project_id,owner_user_id,sequence_id,revision,document_json,created_at,updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (current["draft_key"], project, owner, sequence, revision, dumps(document), timestamp, timestamp))
        return {"project_id": project, "sequence_id": sequence, "revision": revision,
                "clip": clip, "duration": timeline_duration(document), "clip_count": len(document["clips"])}
