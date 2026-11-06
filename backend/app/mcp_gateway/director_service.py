"""MCP-facing director studio: projects, scripts, assets, workshop shots and dubbing.

Every action delegates to the same service methods the workbench HTTP routes call, so the
gateway never owns a second copy of the workshop state machine or its readiness rules.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from ..media_studio.models import ProjectCreateRequest
from ..media_studio.services.dubbing_service import DubbingService
from ..media_studio.services.episode_video_service import ACCEPTED_FILL_STRATEGIES, EpisodeVideoService
from ..media_studio.services.project_detail_service import ProjectDetailService
from ..media_studio.services.project_service import ProjectService
from ..media_studio.services.tts_generation_job_service import TtsGenerationJobService
from ..workflow_registry import H3_STANDARD_OPTION_SCHEMA, workflow_for
from .config import McpConfig

MAX_SCRIPT_CHARS = 500_000
MAX_BEAT_IDS = 300
MAX_SUMMARY_CHARS = 600
ASSET_TARGET_BY_KIND = {"character": "avatar", "scene": "scene_master", "prop": "prop_reference"}
DOCUMENT_FIELDS = ("id", "project_id", "filename", "file_size", "input_mode", "status", "spine_template",
                   "visual_style", "asset_extraction_required", "locked_episode_nums", "episode_lock_reasons",
                   "shot_plan_job_id", "aspect_hint", "created_at", "updated_at")
BEAT_FIELDS = ("id", "kind", "heading", "speaker", "dialogue", "action", "camera", "time_of_day", "scene",
               "scene_id", "characters", "character_ids", "character_look_id", "character_look_ids",
               "props", "prop_ids", "visual_prompt", "sketch_prompt", "render_prompt", "triptych_prompt",
               "h3_prompt", "timestamped_zh_prompt", "video_prompt_zh", "sketch_url", "render_url",
               "triptych_url", "video_url", "upscaled_video_url", "status", "render_status", "triptych_status",
               "vision_status", "video_duration", "take_role", "story_shot", "parent_beat_id")
JOB_FIELDS = ("id", "project_id", "job_type", "title", "status", "progress", "result_url", "error_message",
              "created_at", "updated_at")
BEAT_PATCH_FIELDS = ("heading", "speaker", "dialogue", "action", "camera", "scene", "scene_id", "time_of_day",
                     "characters", "character_ids", "character_look_id", "character_look_ids", "props",
                     "prop_ids", "visual_prompt", "sketch_prompt", "render_prompt", "h3_prompt",
                     "video_prompt_zh", "timestamped_zh_prompt", "video_duration", "visible_text",
                     "dialogue_turns", "workshop_prompt_document", "story_shot")


def _present(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: row[key] for key in fields if key in row and row[key] is not None}


def _analysis_view(analysis: dict[str, Any]) -> dict[str, Any]:
    episodes = [item for item in (analysis.get("episodes") or []) if isinstance(item, dict)]
    counts = {kind: len(analysis.get(bucket) or []) for kind, bucket in
              (("character", "characters"), ("scene", "scenes"), ("prop", "props"))}
    return {
        "title": str(analysis.get("title") or ""),
        "summary": str(analysis.get("summary") or "")[:MAX_SUMMARY_CHARS],
        "episode_nums": [item.get("episode_num") for item in episodes if item.get("episode_num") is not None],
        "episodes": [{"episode_num": item.get("episode_num"), "title": str(item.get("title") or ""),
                      "shot_count": len(item.get("shots") or [])} for item in episodes],
        "asset_counts": counts,
        "assets_extracted_episode_nums": sorted({int(number) for number in
                                                 (analysis.get("assets_extracted_episode_nums") or [])}),
    }


def _document_view(row: dict[str, Any], *, include_script: bool) -> dict[str, Any]:
    data = _present(row, DOCUMENT_FIELDS)
    raw_text = str(row.get("raw_text") or "")
    analysis = row.get("analysis")
    data["analysis"] = _analysis_view(analysis) if isinstance(analysis, dict) else {}
    data["raw_chars"] = len(raw_text)
    if include_script:
        data["raw_text"] = raw_text
        # The workbench edit contract compares this baseline before writing; echo it for copy-free CAS.
        data["base_raw_text"] = raw_text
    return data


def _beats(detail: dict[str, Any]) -> list[dict[str, Any]]:
    return [beat for beat in (detail.get("beats") or []) if isinstance(beat, dict)]


def _beat_view(beat: dict[str, Any]) -> dict[str, Any]:
    data = _present(beat, BEAT_FIELDS)
    lines = [item for item in (beat.get("dubbing_lines") or []) if isinstance(item, dict)]
    if lines:
        data["dubbing"] = {"total": len(lines),
                           "ready": sum(1 for item in lines if item.get("status") == "ready" and item.get("audio_url")),
                           "failed": sum(1 for item in lines if item.get("status") == "failed")}
    return data


def _episode_view(row: dict[str, Any], *, beats: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    data = _present(row, ("id", "project_id", "episode_num", "title", "status", "shots_count", "created_at", "updated_at"))
    try:
        payload = json.loads(row.get("data_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    source = beats if beats is not None else [beat for beat in (payload.get("beats") or []) if isinstance(beat, dict)]
    data["beat_count"] = len(source)
    data["video_ready_beats"] = sum(1 for beat in source
                                    if str(beat.get("upscaled_video_url") or beat.get("video_url") or "").strip())
    data["episode_video_url"] = str(payload.get("episode_video_url") or "")
    if beats is not None:
        data["beats"] = [_beat_view(beat) for beat in source]
    return data


def _asset_view(row: dict[str, Any]) -> dict[str, Any]:
    data = _present(row, ("id", "kind", "name", "role", "description", "image_url", "voice_id", "status"))
    extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    identities = [item for item in (extra.get("identities") or []) if isinstance(item, dict)]
    if identities:
        data["looks"] = [{"id": str(item.get("id") or ""), "name": str(item.get("name") or ""),
                          "has_image": bool(str(item.get("image_url") or "").strip())} for item in identities]
    return data


def _job_view(row: dict[str, Any]) -> dict[str, Any]:
    data = _present(row, JOB_FIELDS)
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    for key in ("episode_id", "beat_id", "asset_id", "target_type", "render_scope", "workflow"):
        if payload.get(key):
            data[key] = payload[key]
    return data


class DirectorService:
    def __init__(self, app, config: McpConfig):
        self.app, self.config = app, config

    @staticmethod
    def _guard(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except (TypeError, KeyError, json.JSONDecodeError) as error:
            raise HTTPException(400, "参数格式不正确，请先查询项目与分集结构") from error

    @staticmethod
    def _text(value: Any, label: str, maximum: int) -> str:
        text = "" if value is None else str(value)
        if len(text) > maximum:
            raise HTTPException(422, f"{label}最长 {maximum} 字")
        return text

    @staticmethod
    def _ids(values: Any, label: str, maximum: int) -> list[str]:
        if values is None:
            return []
        if not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values):
            raise HTTPException(422, f"{label}必须是非空字符串数组")
        if len(values) > maximum:
            raise HTTPException(422, f"{label}一次最多 {maximum} 项")
        return list(dict.fromkeys(item.strip() for item in values))

    # --- 读取 ---
    def projects(self, limit: int, user: dict[str, Any]) -> dict[str, Any]:
        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise HTTPException(422, "limit 需在 1–100 之间")
        rows = self._guard(ProjectService.list_projects, user["id"])
        return {"projects": [{**_present(row.model_dump(), ("id", "name", "description", "cover_url", "status",
                                                            "created_at", "updated_at")),
                              "workspace_url": f"/director2/{row.id}"}
                             for row in rows[:limit]], "total": len(rows)}

    def project_detail(self, project_id: str) -> dict[str, Any]:
        project = self._guard(ProjectService.get_project, project_id)
        if not project:
            raise HTTPException(404, "项目不存在")
        documents = self._guard(ProjectDetailService.list_documents, project_id)
        assets = self._guard(ProjectDetailService.list_assets, project_id)
        episodes = self._guard(ProjectDetailService.list_episodes, project_id)
        return {"project": _present(project.model_dump(), ("id", "name", "description", "cover_url", "status",
                                                           "settings", "created_at", "updated_at")),
                "documents": [_document_view(row, include_script=False) for row in documents],
                "assets": [_asset_view(row) for row in assets[:200]],
                "assets_truncated": len(assets) > 200,
                "episodes": [_episode_view(row) for row in episodes]}

    def script(self, project_id: str, document_id: str) -> dict[str, Any]:
        documents = self._guard(ProjectDetailService.list_documents, project_id)
        row = next((item for item in documents if item.get("id") == document_id), None)
        if not row:
            raise HTTPException(404, "剧本文档不存在")
        return _document_view(row, include_script=True)

    def episode(self, project_id: str, episode_id: str) -> dict[str, Any]:
        detail = self._guard(ProjectDetailService.get_episode_detail, project_id, episode_id)
        data = _episode_view(detail, beats=_beats(detail))
        data["script_text"] = str(detail.get("script_text") or "")
        return data

    def dubbing(self, project_id: str, episode_id: str) -> dict[str, Any]:
        track = self._guard(DubbingService.get_track, project_id, episode_id)
        lines = [_present(item, ("id", "beat_id", "kind", "seq", "speaker", "character_id", "text", "status",
                                 "audio_url", "duration_sec", "emotion", "mix", "job_id", "error"))
                 for item in (track.get("lines") or []) if isinstance(item, dict)]
        return {"project_id": project_id, "episode_id": episode_id, "total": track.get("total"),
                "ready": track.get("ready"), "unbound_count": track.get("unbound_count"),
                "characters": [_present(item, ("id", "name", "bound", "voice_id"))
                               for item in (track.get("characters") or []) if isinstance(item, dict)],
                "lines": lines,
                "compose": _present(track, ("requires_narration", "compose_blocked", "compose_block_reason",
                                            "missing_narration"))}

    def jobs(self, project_id: str, job_id: str | None, limit: int) -> dict[str, Any]:
        if job_id:
            row = self._guard(ProjectDetailService.get_job, project_id, job_id)
            if not row:
                raise HTTPException(404, "任务不存在")
            return {"jobs": [_job_view(row)], "next_poll_seconds": self._poll_seconds([row])}
        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise HTTPException(422, "limit 需在 1–100 之间")
        rows = self._guard(ProjectDetailService.list_jobs, project_id)
        return {"jobs": [_job_view(row) for row in rows[:limit]], "total": len(rows),
                "next_poll_seconds": self._poll_seconds(rows)}

    @staticmethod
    def _poll_seconds(rows: list[dict[str, Any]]) -> int:
        return 2 if any(str(row.get("status") or "") in {"queued", "preparing", "running", "storing", "awaiting_refine"}
                        for row in rows) else 0

    # --- 项目与剧本 ---
    def create_project(self, name: str, description: str, user: dict[str, Any]) -> dict[str, Any]:
        name = name.strip()
        if not name or len(name) > 255:
            raise HTTPException(422, "项目名称需为 1–255 字")
        project = self._guard(ProjectService.create_project,
                              ProjectCreateRequest(name=name, description=description.strip() or None),
                              owner_user_id=user["id"])
        return {"project": _present(project.model_dump(), ("id", "name", "description", "status", "updated_at")),
                "workspace_url": f"/director2/{project.id}"}

    def save_script(self, user: dict, project_id: str, raw_text: str, document_id: str, base_raw_text: str,
                    filename: str, episode_num: int | None) -> dict[str, Any]:
        self._text(raw_text, "剧本正文", MAX_SCRIPT_CHARS)
        actions = getattr(getattr(self.app.state, "director_assistant", None), "actions", None)
        if episode_num is not None:
            if actions is None:
                raise HTTPException(503, "导演助手未启用")
            if not 1 <= episode_num <= 1000:
                raise HTTPException(422, "集数需为 1–1000")
            if not document_id:
                raise HTTPException(422, "按集编辑需要 document_id")
            result = self._guard(actions.edit_script_episode, str(user["id"]), project_id, document_id,
                                 int(episode_num), raw_text, base_raw_text)
            return {"document_id": document_id, "episode_num": episode_num, "result": result}
        if document_id:
            if not base_raw_text:
                raise HTTPException(422, "整篇改写需要 base_raw_text（编辑前的完整正文，来自 studio_get_script）")
            result = self._guard(ProjectDetailService.update_document, project_id, document_id, raw_text, base_raw_text)
        else:
            result = self._guard(ProjectDetailService.create_document, project_id, filename or "剧本文档", raw_text)
        return {"document": _document_view(result or {}, include_script=False)}

    def plan_script(self, project_id: str, document_id: str, aspect_ratio: str) -> dict[str, Any]:
        ratio = aspect_ratio.strip()
        if ratio and ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4"}:
            raise HTTPException(422, "aspect_ratio 需为 16:9、9:16、1:1、4:3 或 3:4")
        result = self._guard(ProjectDetailService.enqueue_document_shot_plan, project_id, document_id,
                             ratio or None)
        return {**result, "poll": "studio_list_project_jobs"}

    def extract_script_assets(self, project_id: str, document_id: str, mode: str) -> dict[str, Any]:
        if mode not in {"merge", "append"}:
            raise HTTPException(422, "mode 需为 merge 或 append")
        return self._guard(ProjectDetailService.transfer_assets_from_document, project_id, document_id, mode=mode)

    def apply_script_episodes(self, project_id: str, document_id: str, mode: str) -> dict[str, Any]:
        if mode not in {"overwrite", "append"}:
            raise HTTPException(422, "mode 需为 overwrite 或 append")
        return self._guard(ProjectDetailService.transfer_episodes_from_document, project_id, document_id, mode=mode)

    # --- 资产 ---
    def create_asset(self, project_id: str, name: str, kind: str, role: str, description: str,
                     visual_prompt: str) -> dict[str, Any]:
        if kind not in {"character", "scene", "prop"}:
            raise HTTPException(422, "kind 需为 character、scene 或 prop")
        if not name.strip():
            raise HTTPException(422, "资产名称不能为空")
        asset = self._guard(ProjectDetailService.create_asset, project_id, {
            "name": name.strip(), "kind": kind, "role": role.strip(), "description": description.strip(),
            "visual_prompt": visual_prompt.strip(),
        })
        return {"asset": _asset_view(asset or {})}

    def generate_asset_image(self, project_id: str, asset_id: str, target_type: str, prompt: str,
                             identity_id: str) -> dict[str, Any]:
        assets = self._guard(ProjectDetailService.list_assets, project_id)
        asset = next((item for item in assets if item.get("id") == asset_id), None)
        if not asset:
            raise HTTPException(404, "资产不存在")
        extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
        looks = [item for item in (extra.get("identities") or [])
                 if isinstance(item, dict) and str(item.get("id") or "").strip()]
        chosen = target_type.strip()
        if not chosen:
            # 出片参考图取角色造型卡与场景主图，头像只用于界面展示；角色缺省直接
            # 出造型卡，避免客户端按旧默认生成头像后仍卡在出片前置检查。
            chosen = "identity" if asset.get("kind") == "character" and looks \
                else str(ASSET_TARGET_BY_KIND.get(asset.get("kind")) or "asset")
        payload: dict[str, Any] = {"target_type": chosen}
        if chosen == "identity":
            if identity_id.strip():
                payload["identity_id"] = identity_id.strip()
            elif looks:
                # 不指定造型时取第一个还没有图的造型；都已出图则重生成第一个。
                pending = next((item for item in looks if not str(item.get("image_url") or "").strip()), looks[0])
                payload["identity_id"] = str(pending.get("id") or "")
        if prompt.strip():
            payload["prompt"] = prompt.strip()[:2000]
        result = self._guard(ProjectDetailService.generate_asset_image, project_id, asset_id, payload)
        note = "资产出图在服务端同步完成，返回即为最终结果"
        if chosen == "identity":
            note += "；造型卡是出片参考图，角色出片前置已就绪" if looks \
                else "；该角色还没有造型槽位，请先在工作台添加造型或改用 target_type=avatar"
        elif chosen == "scene_master":
            note += "；场景主图是出片参考图"
        elif chosen == "avatar":
            note += "；头像仅用于界面展示，出片需要造型卡（target_type=identity）"
        return {**result, "note": note}

    # --- 工坊 ---
    def update_beat(self, project_id: str, episode_id: str, beat_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict) or not patch:
            raise HTTPException(422, "patch 需要至少一个分镜字段")
        unknown = sorted(key for key in patch if key not in BEAT_PATCH_FIELDS)
        if unknown:
            raise HTTPException(422, "不支持修改的分镜字段：" + "、".join(unknown) +
                               "；可改字段：" + "、".join(BEAT_PATCH_FIELDS))
        return self._guard(ProjectDetailService.update_episode_beat, project_id, episode_id, beat_id, dict(patch))

    def generate_beat_prompt(self, project_id: str, episode_id: str, beat_id: str,
                             merge_as_one: bool) -> dict[str, Any]:
        return self._guard(ProjectDetailService.generate_beat_h3_prompt, project_id, episode_id, beat_id,
                           {"merge_as_one": bool(merge_as_one)})

    def generate_episode_video(self, project_id: str, episode_id: str, beat_ids: list[str] | None, force: bool,
                              workflow: str, strategy: str, options: dict[str, Any] | None) -> dict[str, Any]:
        if options is not None and not isinstance(options, dict):
            raise HTTPException(422, "options 需要是对象")
        chosen = self._ids(beat_ids, "beat_ids", MAX_BEAT_IDS) if beat_ids is not None else None
        chosen_workflow = workflow.strip()
        body: dict[str, Any] = dict(options or {})
        if chosen_workflow:
            body["workflow"] = chosen_workflow
        if chosen:
            body["beat_ids"] = chosen
        if force:
            body["force"] = True
        fill_strategy = str(strategy or "").strip().lower()
        if fill_strategy:
            if fill_strategy not in ACCEPTED_FILL_STRATEGIES:
                raise HTTPException(422, "strategy 仅支持 gap_fill 或 continue")
            body["strategy"] = fill_strategy
        self._reject_hidden_options(chosen_workflow or str(EpisodeVideoService.DEFAULTS["workflow"]), body)
        if "duration" in body:
            raise HTTPException(422, "工坊出片时长按镜头取，请改分镜的 video_duration，不要传整体 duration")
        result = self._guard(EpisodeVideoService.generate_episode_videos, project_id, episode_id, body)
        return {**result, "poll": "studio_list_project_jobs",
                "awaiting_refine_hint": "任务停在 awaiting_refine 时用 studio_confirm_project_refine 继续二采"}

    @staticmethod
    def _reject_hidden_options(workflow_id: str, body: dict[str, Any]) -> None:
        """ComfyUI 内部参数由注册表默认值托管，和 studio_create_video 一样拒绝显式传入。"""
        if not workflow_id:
            return
        try:
            definition = workflow_for(workflow_id)
        except KeyError:
            return
        schema = definition.option_schema
        if schema is None and definition.supports_h3_options:
            schema = H3_STANDARD_OPTION_SCHEMA
        properties = (schema or {}).get("properties") or {}
        blocked = sorted(key for key in body
                         if key in properties and properties[key].get("ui_group") == "internal")
        if blocked:
            raise HTTPException(422, "这些技术参数由工作台默认值托管，请勿指定：" + "、".join(blocked))

    def confirm_refine(self, project_id: str, job_id: str) -> dict[str, Any]:
        return self._guard(EpisodeVideoService.confirm_refine, project_id, job_id)

    def skip_refine(self, project_id: str, job_id: str) -> dict[str, Any]:
        return self._guard(EpisodeVideoService.skip_refine, project_id, job_id)

    def generate_dubbing(self, project_id: str, episode_id: str, line_ids: list[str]) -> dict[str, Any]:
        chosen = self._ids(line_ids, "line_ids", MAX_BEAT_IDS)
        return self._guard(TtsGenerationJobService.enqueue, project_id, episode_id,
                           line_ids=chosen or None)
