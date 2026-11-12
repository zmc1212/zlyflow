from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from ..db import db_cursor, execute_sql, now_str, query_all, query_one, transaction_cursor
from .job_payload import (
    JOB_LIST_COLUMNS,
    collect_infer_asset_ids,
    parse_job_payload,
    serialize_job_row,
)
from .asset_image_prompts import (
    IDENTITY_SHEET_ASPECT_RATIO,
    IDENTITY_SHEET_IMAGE_SIZE,
    build_identity_generation,
    character_portrait_prompt,
    identity_sheet_dimensions,
    prop_view_prompt,
    safe_scene_master_prompt,
    scene_view_prompt,
)
from .asset_prompt_inference import (
    apply_inferred_prompts,
    reference_urls_to_data_uris,
    source_urls_for_inference,
)
from .asset_source_references import (
    MAX_SOURCE_REFERENCE_BYTES,
    apply_source_references_to_generation,
    append_source_reference,
    normalize_source_references,
    remove_source_reference,
    sniff_image_suffix,
    source_reference_urls,
)
from .grs_client import GrsClient, GrsError
from .workshop_prompt import normalize_workshop_prompt, invalidate_changed_prompt
from .episode_shot_planner import document_needs_shot_plan
from ...skill_packs.aspect import document_aspect_hint, persist_workshop_aspect_ratio
from ...workflow_registry import GRS_VIP_SIZES
from .llm_service import LlmService
from ..provider_bridge import credential_manager, grs_row
from .qiniu_service import QiniuService
from .script_parser import StandardScriptParser
from .script_asset_extraction import ASSET_EXTRACTION_REVISION, asset_source_hash, merge_extracted_assets, script_asset_extraction_required
from .voice_profile import (
    MAX_VOICE_AUDIO_BYTES,
    clone_voice_id,
    merge_voice,
    normalize_voice_profile,
    sniff_audio_suffix,
    voice_of,
)

# GPT Image 2.5 系列的能力档：线上协议不接受 "1:1" 等比例字符串，必须传像素值或 auto，
# 映射表与主注册表 grs_request_size 共用（workflow_registry 是能力映射的唯一来源）。
GPT_IMAGE_25_PROFILES = ("gpt_image_2_5", "gpt_image_2_5_vip")
# 导演台资产生图默认走 GPT Image 2.5 基础版（1K，图片服务国内节点最便宜档 600 积分/张）。
ASSET_IMAGE_DEFAULT_MODEL = "gpt-image-2.5"
ASSET_IMAGE_DEFAULT_PROFILE = "gpt_image_2_5"


def grs_wire_aspect_ratio(profile: str | None, aspect_ratio: str, image_size: str | None) -> str:
    """把注册表口径的比例/分辨率映射成图片服务线上协议的 aspectRatio 值。"""
    if profile not in GPT_IMAGE_25_PROFILES or aspect_ratio == "auto":
        return aspect_ratio
    sizes = GRS_VIP_SIZES.get(aspect_ratio) or {}
    pixel = sizes.get(image_size or "1K") or next(iter(sizes.values()), None)
    return pixel or aspect_ratio


def resolve_shot_scene(
    scene_name: str,
    scene_map: dict[str, str],
    inherited_name: str = "",
    inherited_id: str | None = None,
) -> tuple[str, str | None]:
    """Resolve an explicit scene, or inherit the last explicit scene for continuation shots."""
    scene_name = str(scene_name or "").strip()
    if not scene_name:
        return inherited_name, inherited_id
    for asset_name, asset_id in scene_map.items():
        if asset_name in scene_name or scene_name in asset_name:
            return scene_name, asset_id
    return scene_name, None


def asset_name_id_map(rows: list[dict[str, Any]], kind: str) -> dict[str, str]:
    """Map asset names to IDs, preferring rows that already have an image."""
    mapping: dict[str, str] = {}
    ranked: list[tuple[str, bool, str]] = []
    for row in rows:
        if row.get("kind") != kind or not row.get("id"):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        if not extra and row.get("extra_json"):
            try:
                extra = json.loads(row["extra_json"]) if isinstance(row["extra_json"], str) else (row["extra_json"] or {})
            except Exception:
                extra = {}
        has_image = bool(str(
            row.get("image_url")
            or extra.get("master_url")
            or extra.get("avatar_url")
            or extra.get("reference_url")
            or ""
        ).strip())
        ranked.append((name, has_image, str(row["id"])))
    ranked.sort(key=lambda item: item[1])
    for name, _has_image, asset_id in ranked:
        mapping[name] = asset_id
    return mapping


def match_named_asset_ids(names: list[Any], name_map: dict[str, str]) -> list[str]:
    matched: list[str] = []
    for raw in names or []:
        name = str(raw or "").strip()
        if not name:
            continue
        for key, asset_id in name_map.items():
            if key in name or name in key:
                if asset_id not in matched:
                    matched.append(asset_id)
    return matched


def _document_asset_match_key(kind: str, name: str) -> tuple[str, str]:
    normalized = str(name or "").strip()
    if kind == "scene":
        normalized = re.sub(r"(?:\s*[/／|｜·]\s*(?:白天|夜晚|清晨|傍晚|黄昏|内景|外景|日|夜|内|外))+\s*$", "", normalized).strip() or normalized
    return kind, normalized


def _legacy_scene_title(title: Any) -> bool:
    return bool(re.match(r"\s*\**\s*场景\s*\**\s*[：:]", str(title or "")))


def _has_analysis_content(value: Any) -> bool:
    """解析结果里的「这一节有没有内容」：列表看元素，字典看任意非空字段，字符串看去空白。"""
    if isinstance(value, dict):
        return any(_has_analysis_content(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_analysis_content(item) for item in value)
    return bool(str(value or "").strip())


_ASSET_IMAGE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="asset-image")
_ASSET_IMAGE_ACTIVE_STATUSES = ("queued", "running", "preparing", "storing")

# 镜头生图目标已全部下线（草图/渲染/三联关键帧）。保留标记只为让历史任务在任务中心
# 仍可分类与回显，重试时给出明确提示而不是误入资产图或视频重试分支。
RETIRED_BEAT_IMAGE_TARGETS = {"beat_sketch", "beat_render", "beat_triptych"}
RETIRED_BEAT_IMAGE_MESSAGE = "镜头生图（草图 / 渲染图 / 三联关键帧）已下线，请直接为本镜生成 H3 提示词后用角色卡与场景卡出片。"


class BeatInputChangedError(ValueError):
    """A generated draft no longer matches the editable beat it was based on."""


class ProjectDetailService:
    # --- 1. 内容库 Documents ---
    @classmethod
    def _analysis_for_document_row(cls, row: dict[str, Any], *, persist: bool = False) -> dict[str, Any] | None:
        analysis = None
        raw_json = row.get("analysis_json")
        if raw_json:
            try:
                analysis = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            except Exception:
                analysis = None
        raw_text = str(row.get("raw_text") or "")
        stale = not analysis or not (analysis.get("episodes") or [])
        if stale and raw_text.strip():
            parsed = StandardScriptParser.parse(raw_text)
            if parsed.get("episodes"):
                recovered = dict(analysis or {})
                for key, value in parsed.items():
                    if key in {"episodes", "summary", "logs", "model"} or not _has_analysis_content(recovered.get(key)):
                        recovered[key] = value
                analysis = recovered
                if persist and row.get("id"):
                    execute_sql(
                        "UPDATE ai_project_documents SET analysis_json = %s WHERE id = %s AND COALESCE(raw_text, '') = %s AND COALESCE(analysis_json, '') = %s",
                        (json.dumps(analysis, ensure_ascii=False), row["id"], raw_text, raw_json or ""),
                    )
            elif analysis is None:
                analysis = parsed
        analysis = cls._recover_scene_analysis(row, analysis, persist=persist)
        analysis = cls._recover_analysis_sections(row, analysis, persist=persist)
        merged = cls._merge_pipeline_recipe_assets(row, analysis, persist=persist)
        if merged:
            summary = merged.get("summary")
            cls._refresh_analysis_shot_summary(merged)
            if persist and row.get("id") and merged.get("summary") != summary:
                execute_sql(
                    "UPDATE ai_project_documents SET analysis_json = %s WHERE id = %s",
                    (json.dumps(merged, ensure_ascii=False), row["id"]),
                )
        return merged

    @classmethod
    def _recover_scene_analysis(cls, row: dict[str, Any], analysis: dict[str, Any] | None, *, persist: bool) -> dict[str, Any] | None:
        # 旧解析器会把镜头标题后的首个场景标签当作标题，已落库文档的 scenes 为空；无 LLM 规划时按原文重解析。
        if not analysis:
            return analysis
        stored_shots = [
            shot
            for episode in (analysis.get("episodes") or [])
            if isinstance(episode, dict)
            for shot in (episode.get("shots") or [])
            if isinstance(shot, dict)
        ]
        broken_titles = any(_legacy_scene_title(shot.get("title")) for shot in stored_shots)
        if (analysis.get("scenes") or analysis.get("scene_analysis_revision")) and not broken_titles:
            return analysis
        raw_text = str(row.get("raw_text") or "")
        if not re.search(r"(?m)^\s*(?:[-*+]\s*)?(?:\*\*)?场景(?:\*\*)?\s*[：:]", raw_text):
            return analysis
        episodes = [item for item in (analysis.get("episodes") or []) if isinstance(item, dict)]
        if any(str(item.get("shots_source") or "").lower() == "llm" for item in episodes):
            return analysis
        parsed = StandardScriptParser.parse(raw_text)
        scenes = parsed.get("scenes") or []
        parsed_episodes = {
            item.get("episode_num"): item
            for item in (parsed.get("episodes") or [])
            if isinstance(item, dict)
        }
        episodes = []
        for episode in analysis.get("episodes") or []:
            if not isinstance(episode, dict):
                episodes.append(episode)
                continue
            parsed_shots = {
                shot.get("shot_num"): shot
                for shot in ((parsed_episodes.get(episode.get("episode_num")) or {}).get("shots") or [])
                if isinstance(shot, dict)
            }
            shots = []
            for shot in episode.get("shots") or []:
                if not isinstance(shot, dict):
                    shots.append(shot)
                    continue
                parsed_shot = parsed_shots.get(shot.get("shot_num")) or {}
                patch: dict[str, Any] = {}
                if not shot.get("scene") and parsed_shot.get("scene"):
                    patch["scene"] = parsed_shot["scene"]
                if _legacy_scene_title(shot.get("title")) and parsed_shot.get("title"):
                    patch["title"] = parsed_shot["title"]
                shots.append({**shot, **patch} if patch else shot)
            episodes.append({**episode, "shots": shots})
        recovered = {**analysis, "episodes": episodes, "scenes": scenes, "scene_analysis_revision": 2}
        cls._refresh_analysis_shot_summary(recovered)
        if persist and row.get("id"):
            execute_sql(
                "UPDATE ai_project_documents SET analysis_json = %s WHERE id = %s",
                (json.dumps(recovered, ensure_ascii=False), row["id"]),
            )
        return recovered

    @classmethod
    def _recover_analysis_sections(
        cls, row: dict[str, Any], analysis: dict[str, Any] | None, *, persist: bool
    ) -> dict[str, Any] | None:
        # 旧文档存的是当时那版解析器的结果：裸标题「主要人物」认不出、章节名写成
        # 「故事定位」时整节定位直接丢失。按原文补解析一次，只填空位，
        # 已有值一律不覆盖（镜头可能是 LLM 规划结果，道具本来就没写）。
        if not analysis or analysis.get("analysis_sections_revision"):
            return analysis
        pending = [key for key in ("characters", "positioning", "visual_style", "production_advice")
                   if not _has_analysis_content(analysis.get(key))]
        if not pending:
            return analysis
        raw_text = str(row.get("raw_text") or "")
        if not raw_text.strip():
            return analysis
        parsed = StandardScriptParser.parse(raw_text)
        filled = False
        for key in pending:
            value = parsed.get(key)
            if _has_analysis_content(value):
                analysis[key] = value
                filled = True
        # 剧本本来就没写这些章节时不盖章也不回写，免得每次读内容库都多一条 UPDATE；
        # 重解析的代价只是几次正则，远小于把旧文档永久标成「已处理」的风险。
        if not filled:
            return analysis
        analysis["analysis_sections_revision"] = 1
        cls._refresh_analysis_shot_summary(analysis)
        if persist and row.get("id"):
            execute_sql(
                "UPDATE ai_project_documents SET analysis_json = %s WHERE id = %s",
                (json.dumps(analysis, ensure_ascii=False), row["id"]),
            )
        return analysis

    @classmethod
    def _latest_pipeline_recipe(cls, project_id: str | None) -> dict[str, Any] | None:
        if not project_id:
            return None
        job = query_one(
            "SELECT payload_json FROM ai_project_jobs WHERE project_id = %s AND job_type = 'ai_pipeline' ORDER BY updated_at DESC LIMIT 1",
            (project_id,),
        )
        if not job:
            return None
        try:
            payload = json.loads(job.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            return None
        recipe = payload.get("recipe")
        return recipe if isinstance(recipe, dict) else None

    @classmethod
    def _merge_pipeline_recipe_assets(cls, row: dict[str, Any], analysis: dict[str, Any] | None, *, persist: bool = False) -> dict[str, Any] | None:
        if str(row.get("input_mode") or "") != "ai_pipeline":
            return analysis
        recipe = cls._latest_pipeline_recipe(row.get("project_id"))
        if not recipe:
            return analysis
        from .ai_generation_service import AiGenerationService

        merged = AiGenerationService.merge_recipe_assets_into_analysis(analysis or {}, recipe)
        before = json.dumps(analysis or {}, ensure_ascii=False, sort_keys=True)
        after = json.dumps(merged, ensure_ascii=False, sort_keys=True)
        if persist and row.get("id") and after != before:
            execute_sql(
                "UPDATE ai_project_documents SET analysis_json = %s WHERE id = %s",
                (json.dumps(merged, ensure_ascii=False), row["id"]),
            )
        if persist and row.get("project_id") and (merged.get("characters") or merged.get("scenes") or merged.get("props")):
            AiGenerationService.persist_recipe_assets(str(row.get("project_id") or ""), recipe)
        return merged

    @classmethod
    def list_documents(cls, project_id: str) -> list[dict[str, Any]]:
        rows = query_all(
            "SELECT * FROM ai_project_documents WHERE project_id = %s AND COALESCE(status,'') <> 'merged' ORDER BY updated_at DESC",
            (project_id,),
        )
        from .asset_extraction_job_service import AssetExtractionJobService
        from .shot_plan_job_service import ShotPlanJobService
        from ...skill_packs.binding import load_project, skill_pack_id_of
        from ...skill_packs.recipe import get_pack

        job_ids = ShotPlanJobService.active_job_ids_by_document(project_id)
        extraction_job_ids = AssetExtractionJobService.active_job_ids_by_document(project_id)
        from ...director_assistant.script_documents import episode_locks
        production_rows = query_all("SELECT episode_num,status,data_json FROM ai_project_episodes WHERE project_id = %s", (project_id,)) if rows else []
        project = None
        recipe = None
        try:
            project = load_project(project_id)
            recipe = get_pack(skill_pack_id_of(project))
        except Exception:
            project, recipe = None, None
        items = []
        for r in rows:
            analysis = cls._analysis_for_document_row(r, persist=True)
            locks = episode_locks({**r, "analysis_json": analysis or {}}, production_rows)
            items.append({
                "id": r["id"],
                "project_id": r["project_id"],
                "filename": r["filename"],
                "file_size": r["file_size"],
                "input_mode": r["input_mode"],
                "status": r["status"],
                "spine_template": r["spine_template"],
                "visual_style": r["visual_style"],
                "raw_text": r["raw_text"],
                "analysis": analysis,
                "asset_extraction_required": script_asset_extraction_required(str(r.get("raw_text") or ""), analysis),
                "locked_episode_nums": sorted(locks),
                "episode_lock_reasons": {str(number): reason for number, reason in locks.items()},
                "shot_plan_job_id": job_ids.get(r["id"]),
                "asset_extraction_job_id": extraction_job_ids.get(r["id"]),
                "aspect_hint": document_aspect_hint(
                    str(r.get("raw_text") or ""),
                    project=project,
                    recipe=recipe,
                ),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            })
        return items

    @classmethod
    def create_document(
        cls,
        project_id: str,
        filename: str,
        raw_text: str,
        spine_template: str = "drama",
        visual_style: str = "chinese_period_drama",
        input_mode: str = "paste",
    ) -> dict[str, Any]:
        doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        file_size = len(raw_text.encode("utf-8"))

        # 只跑解析器立刻落库；粘贴/文件导入先确认成片画幅，再入队 shot_plan。
        analysis = StandardScriptParser.parse(raw_text)
        should_plan = document_needs_shot_plan(analysis, input_mode=input_mode)
        doc_status = "awaiting_aspect" if should_plan else "ready"

        # 若未提供文件名或为默认名称，自动优先采用解析出的剧目主标题
        if (not filename or filename.startswith("未命名") or filename == "新建剧本文档") and analysis.get("title"):
            filename = analysis["title"]

        execute_sql(
            """
            INSERT INTO ai_project_documents
            (id, project_id, filename, file_size, input_mode, status, spine_template, visual_style, raw_text, analysis_json, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                doc_id,
                project_id,
                filename,
                file_size,
                input_mode,
                doc_status,
                spine_template,
                visual_style,
                raw_text,
                json.dumps(analysis, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )

        return {
            "id": doc_id,
            "project_id": project_id,
            "filename": filename,
            "file_size": file_size,
            "input_mode": input_mode,
            "status": doc_status,
            "spine_template": spine_template,
            "visual_style": visual_style,
            "raw_text": raw_text,
            "analysis": analysis,
            "shot_plan_job_id": None,
            "aspect_hint": document_aspect_hint(raw_text, project_id=project_id),
            "needs_shot_plan": should_plan,
            "created_at": timestamp,
            "updated_at": timestamp,
        }

    @classmethod
    def update_document(cls, project_id: str, doc_id: str, raw_text: str, base_raw_text: str) -> dict[str, Any]:
        """Save the same script without changing production assets or episodes."""
        from .shot_plan_job_service import ShotPlanJobService

        row = query_one("SELECT * FROM ai_project_documents WHERE id = %s AND project_id = %s", (doc_id, project_id))
        if not row:
            raise ValueError("文档不存在")
        if not raw_text.strip():
            raise ValueError("剧本正文不能为空")
        if len(raw_text) > 500_000:
            raise ValueError("剧本正文最多 500000 个字符")
        if str(row.get("raw_text") or "") != base_raw_text:
            raise ValueError("文档已更新，请重新加载后再保存")
        if ShotPlanJobService.active_job_ids_by_document(project_id).get(doc_id):
            raise ValueError("镜头规划正在进行，请完成后再编辑剧本")
        if raw_text == base_raw_text:
            return {**row, "analysis": cls._analysis_for_document_row(row), "shot_plan_job_id": None}

        analysis = StandardScriptParser.parse(raw_text)
        from ...director_assistant.script_documents import document_analysis, parsed_script
        previous = document_analysis(row)
        if previous.get("primary_script"):
            parsed = parsed_script(raw_text)
            for key in ("story_setting_text", "story_setting_fields"):
                if previous.get(key):
                    parsed[key] = previous[key]
            original = {ep["episode_num"]: ep for ep in parsed_script(base_raw_text).get("episodes", [])}
            saved = {ep["episode_num"]: ep for ep in previous.get("episodes", [])}
            changed = [ep["episode_num"] for ep in parsed.get("episodes", []) if ep.get("body") != original.get(ep["episode_num"], {}).get("body")]
            parsed["episodes"] = [saved.get(ep["episode_num"], ep) if ep["episode_num"] not in changed else ep for ep in parsed.get("episodes", [])]
            analysis = {**previous, **parsed, "script_changes": {"section": "body", "episode_nums": changed, "assets_need_review": bool(changed)}}
        from ...director_assistant.script_documents import episode_locks, ensure_locked_bodies_unchanged
        productions = query_all("SELECT episode_num,status,data_json FROM ai_project_episodes WHERE project_id = %s", (project_id,))
        ensure_locked_bodies_unchanged(row, {"raw_text": raw_text, "analysis_json": analysis}, episode_locks(row, productions))
        status = "awaiting_aspect" if document_needs_shot_plan(analysis, input_mode=str(row.get("input_mode") or "paste")) else "ready"
        timestamp = now_str()
        size = len(raw_text.encode("utf-8"))
        changed = execute_sql(
            "UPDATE ai_project_documents SET raw_text = %s, file_size = %s, analysis_json = %s, status = %s, updated_at = %s "
            "WHERE id = %s AND project_id = %s AND COALESCE(analysis_json, '') = %s AND COALESCE(raw_text, '') = %s",
            (raw_text, size, json.dumps(analysis, ensure_ascii=False), status, timestamp, doc_id, project_id, row.get("analysis_json") or "", base_raw_text),
        )
        if not changed:
            raise ValueError("文档已更新，请重新加载后再保存")
        return {**row, "raw_text": raw_text, "file_size": size, "analysis": analysis, "status": status,
                "updated_at": timestamp, "shot_plan_job_id": None}

    @classmethod
    def enqueue_document_shot_plan(
        cls,
        project_id: str,
        doc_id: str,
        aspect_ratio: str | None = None,
    ) -> dict[str, Any]:
        from .shot_plan_job_service import ShotPlanJobService

        if aspect_ratio:
            persist_workshop_aspect_ratio(project_id, aspect_ratio)
            return ShotPlanJobService.enqueue(project_id, doc_id, aspect_ratio=aspect_ratio)
        return ShotPlanJobService.enqueue(project_id, doc_id)

    @classmethod
    def persist_shot_plan_episode(
        cls,
        project_id: str,
        doc_id: str,
        *,
        episode_num: Any,
        episode_index: int,
        updated_episode: dict[str, Any],
        log_line: str | None = None,
    ) -> dict[str, Any]:
        row = query_one(
            "SELECT id, analysis_json FROM ai_project_documents WHERE id = %s AND project_id = %s",
            (doc_id, project_id),
        )
        if not row:
            raise ValueError("文档不存在")
        raw_json = row.get("analysis_json")
        if isinstance(raw_json, dict):
            analysis = dict(raw_json)
        else:
            try:
                parsed = json.loads(raw_json or "{}")
            except json.JSONDecodeError:
                parsed = {}
            analysis = parsed if isinstance(parsed, dict) else {}
        episodes = list(analysis.get("episodes") or [])
        target_index = None
        if episode_num is not None:
            for index, item in enumerate(episodes):
                if isinstance(item, dict) and item.get("episode_num") == episode_num:
                    target_index = index
                    break
        if target_index is None and 0 <= int(episode_index) < len(episodes):
            target_index = int(episode_index)
        if target_index is None:
            raise ValueError("未找到要写入的分集")
        episodes[target_index] = updated_episode
        analysis["episodes"] = episodes
        if log_line:
            logs = list(analysis.get("logs") or [])
            logs.append(log_line)
            analysis["logs"] = logs
        cls._refresh_analysis_shot_summary(analysis)
        execute_sql(
            "UPDATE ai_project_documents SET analysis_json = %s, updated_at = %s WHERE id = %s AND project_id = %s",
            (json.dumps(analysis, ensure_ascii=False), now_str(), doc_id, project_id),
        )
        return analysis

    @staticmethod
    def _refresh_analysis_shot_summary(analysis: dict[str, Any]) -> None:
        episodes = [item for item in (analysis.get("episodes") or []) if isinstance(item, dict)]
        total_shots = sum(len(item.get("shots") or []) for item in episodes)
        summary = str(analysis.get("summary") or "")
        updated = re.sub(
            r"共解析出 \d+ 集剧情、\d+ 个分镜头",
            f"共解析出 {len(episodes)} 集剧情、{total_shots} 个分镜头",
            summary,
            count=1,
        )
        if any(key in analysis for key in ("characters", "scenes", "props")):
            updated = re.sub(
                r"识别到 \d+ 位主要人物、\d+ 处拍摄场景、\d+ 件核心道具",
                f"识别到 {len(analysis.get('characters') or [])} 位主要人物、"
                f"{len(analysis.get('scenes') or [])} 处拍摄场景、"
                f"{len(analysis.get('props') or [])} 件核心道具",
                updated,
                count=1,
            )
        if updated != summary:
            analysis["summary"] = updated

    @classmethod
    def delete_document(cls, project_id: str, doc_id: str) -> bool:
        aff = execute_sql("DELETE FROM ai_project_documents WHERE id = %s AND project_id = %s", (doc_id, project_id))
        return aff > 0

    @classmethod
    def transfer_assets_from_document(
        cls,
        project_id: str,
        doc_id: str,
        *,
        mode: str = "merge",
        on_phase: Callable[[str, bool], None] | None = None,
    ) -> dict[str, Any]:
        if mode not in {"merge", "append"}:
            raise ValueError("资产同步方式无效")
        row = query_one("SELECT id, analysis_json, raw_text FROM ai_project_documents WHERE id = %s AND project_id = %s", (doc_id, project_id))
        if not row:
            raise ValueError("文档不存在或尚未完成分析")
        analysis = cls._analysis_for_document_row(row, persist=True) or {}
        if script_asset_extraction_required(str(row.get("raw_text") or ""), analysis):
            analysis = cls._extract_prose_document_assets(project_id, row, on_phase=on_phase)
        ts = now_str()
        chars = analysis.get("characters") or []
        scenes = analysis.get("scenes") or []
        props = analysis.get("props") or []
        if not any(item.get("name", "").strip() for item in [*chars, *scenes, *props]):
            raise ValueError("未识别到制作资产，请在剧本中补充角色、场景或道具后重试拆解")

        # 查询已有资产以做平滑更新或去重
        existing_rows = query_all("SELECT id, kind, name FROM ai_project_assets WHERE project_id = %s", (project_id,))
        existing_map = {(r["kind"], r["name"]): r["id"] for r in existing_rows}
        append_names = {_document_asset_match_key(r["kind"], r["name"]) for r in existing_rows}

        c_count = 0
        s_count = 0
        p_count = 0

        # 1. 角色转入（保存角色名、定位、外观与一致性 Prompt）
        for c in chars:
            c_name = c.get("name", "").strip()
            if not c_name:
                continue
            role = c.get("role") or "主要角色"
            desc = c.get("description") or f"{c.get('gender', '')} 角色设定"
            prompt = c.get("visual_prompt") or ""
            key = ("character", c_name)
            if mode == "append" and _document_asset_match_key(*key) in append_names:
                continue
            if key in existing_map:
                execute_sql(
                    "UPDATE ai_project_assets SET role = %s, description = %s, visual_prompt = %s, updated_at = %s WHERE id = %s",
                    (role, desc, prompt, ts, existing_map[key]),
                )
            else:
                aid = f"ast-{uuid.uuid4().hex[:12]}"
                execute_sql(
                    """
                    INSERT INTO ai_project_assets (id, project_id, kind, name, role, description, visual_prompt, created_at, updated_at)
                    VALUES (%s, %s, 'character', %s, %s, %s, %s, %s, %s)
                    """,
                    (aid, project_id, c_name, role, desc, prompt, ts, ts),
                )
            c_count += 1
            append_names.add(_document_asset_match_key(*key))

        # 2. 场景转入（保存场景名、氛围与描述）
        for s in scenes:
            s_name = s.get("name", "").strip()
            if not s_name:
                continue
            role = s.get("type") or "固定场景"
            desc = s.get("description") or f"规划场景: {s_name}"
            key = ("scene", s_name)
            if mode == "append" and _document_asset_match_key(*key) in append_names:
                continue
            if key in existing_map:
                execute_sql(
                    "UPDATE ai_project_assets SET role = %s, description = %s, updated_at = %s WHERE id = %s",
                    (role, desc, ts, existing_map[key]),
                )
            else:
                aid = f"ast-{uuid.uuid4().hex[:12]}"
                execute_sql(
                    """
                    INSERT INTO ai_project_assets (id, project_id, kind, name, role, description, created_at, updated_at)
                    VALUES (%s, %s, 'scene', %s, %s, %s, %s, %s)
                    """,
                    (aid, project_id, s_name, role, desc, ts, ts),
                )
            s_count += 1
            append_names.add(_document_asset_match_key(*key))

        # 3. 道具转入（保存道具名、重要性与关联角色）
        for p in props:
            p_name = p.get("name", "").strip()
            if not p_name:
                continue
            role = p.get("kind") or "核心道具"
            rel_char = p.get("related_character") or "场景公用"
            desc = p.get("description") or f"类型: {role}，关联角色/场景: {rel_char}"
            key = ("prop", p_name)
            if mode == "append" and _document_asset_match_key(*key) in append_names:
                continue
            if key in existing_map:
                execute_sql(
                    "UPDATE ai_project_assets SET role = %s, description = %s, updated_at = %s WHERE id = %s",
                    (role, desc, ts, existing_map[key]),
                )
            else:
                aid = f"ast-{uuid.uuid4().hex[:12]}"
                execute_sql(
                    """
                    INSERT INTO ai_project_assets (id, project_id, kind, name, role, description, created_at, updated_at)
                    VALUES (%s, %s, 'prop', %s, %s, %s, %s, %s)
                    """,
                    (aid, project_id, p_name, role, desc, ts, ts),
                )
            p_count += 1
            append_names.add(_document_asset_match_key(*key))

        extracted_numbers = sorted({int(number) for number in analysis.get("assets_extracted_episode_nums", [])} | {int(ep["episode_num"]) for ep in analysis.get("episodes", [])})
        placeholders = ",".join("%s" for _ in extracted_numbers)
        marked = execute_sql(
            "UPDATE ai_project_documents SET analysis_json=JSON_SET(COALESCE(analysis_json,'{}'),'$.assets_extracted_episode_nums',JSON_ARRAY(" + placeholders + ")),updated_at=%s WHERE id=%s AND project_id=%s AND COALESCE(raw_text,'')=%s",
            (*extracted_numbers, ts, doc_id, project_id, str(row.get("raw_text") or "")),
        )
        if marked == 0:
            current = query_one("SELECT raw_text FROM ai_project_documents WHERE id=%s AND project_id=%s", (doc_id, project_id))
            if not current or str(current.get("raw_text") or "") != str(row.get("raw_text") or ""):
                raise ValueError("剧本已更新，已提取的资产保留，请重新核对分集后操作")
        receipt = analysis.get("script_asset_extraction")
        receipt = receipt if isinstance(receipt, dict) else {}
        skipped = receipt.get("skipped") if isinstance(receipt.get("skipped"), list) else []
        return {
            "transferred": {
                "characters": c_count,
                "scenes": s_count,
                "props": p_count,
            },
            "total": c_count + s_count + p_count,
            "skipped": skipped,
            "skipped_count": len(skipped),
        }

    @classmethod
    def _extract_prose_document_assets(
        cls,
        project_id: str,
        row: dict[str, Any],
        *,
        on_phase: Callable[[str, bool], None] | None = None,
    ) -> dict[str, Any]:
        # LLM requests run only after an explicit extraction action, never while
        # listing documents. Refresh after any deterministic read recovery.
        current = query_one("SELECT id,raw_text,analysis_json FROM ai_project_documents WHERE id=%s AND project_id=%s", (row["id"], project_id))
        if not current or str(current.get("raw_text") or "") != str(row.get("raw_text") or ""):
            raise ValueError("剧本已更新，请重新加载后拆解资产")
        analysis = cls._analysis_for_document_row(current, persist=False) or {}
        text = str(current.get("raw_text") or "")
        if not script_asset_extraction_required(text, analysis):
            return analysis
        extracted = LlmService.extract_script_assets(text, analysis, on_phase=on_phase)
        skipped = list(getattr(extracted, "skipped", []))
        merged = merge_extracted_assets(analysis, extracted)
        merged["script_asset_extraction"] = {"revision": ASSET_EXTRACTION_REVISION,
                                               "source_hash": asset_source_hash(text, analysis), "created_at": now_str(),
                                               "skipped": skipped[:50], "skipped_count": len(skipped)}
        cls._refresh_analysis_shot_summary(merged)
        if on_phase:
            on_phase("正在写入制作资产", False)
        changed = execute_sql(
            "UPDATE ai_project_documents SET analysis_json=%s WHERE id=%s AND project_id=%s AND COALESCE(raw_text,'')=%s AND COALESCE(analysis_json,'')=%s",
            (json.dumps(merged, ensure_ascii=False), row["id"], project_id, text, current.get("analysis_json") or ""),
        )
        if changed == 0:
            raise ValueError("剧本在拆解期间已更新，结果尚未写入资产库，请重新加载后重试")
        return merged

    @classmethod
    @staticmethod
    def _episode_script_text(ep_num: int, title: str, summary: str, shots: list[dict[str, Any]]) -> str:
        script_lines = [f"第 {ep_num} 集：{title}"]
        if summary:
            script_lines.append(f"【剧情概要】{summary}\n")
        for shot in shots:
            script_lines.append(f"### 镜头 {shot.get('shot_num', 1)}｜{shot.get('title', '')}")
            if shot.get("characters"):
                script_lines.append(f"- 人物：{', '.join(shot['characters'])}")
            if shot.get("scene"):
                script_lines.append(f"- 场景：{shot['scene']}")
            if shot.get("props"):
                script_lines.append(f"- 道具：{', '.join(shot['props'])}")
            if shot.get("camera"):
                script_lines.append(f"- 运镜：{shot['camera']}")
            if shot.get("action"):
                script_lines.append(f"- 动作：{shot['action']}")
            if shot.get("dialogue"):
                script_lines.append(f"- 台词：{shot['dialogue']}")
            if shot.get("audio"):
                script_lines.append(f"- 音效：{shot['audio']}")
            if shot.get("visual_prompt"):
                script_lines.append(f"- 提示词：{shot['visual_prompt']}")
            script_lines.append("")
        return "\n".join(script_lines).strip()

    @classmethod
    def _beats_from_document_shots(
        cls,
        episode_id: str,
        shots: list[dict[str, Any]],
        char_map: dict[str, str],
        scene_map: dict[str, str],
        prop_map: dict[str, str],
    ) -> list[dict[str, Any]]:
        beats: list[dict[str, Any]] = []
        inherited_scene_name = ""
        inherited_scene_id = None
        for shot in shots:
            s_num = int(shot.get("shot_num") or (len(beats) + 1))
            s_title = shot.get("title") or f"镜头 {s_num}"
            s_scene = shot.get("scene") or ""
            s_camera = shot.get("camera") or "中景"
            s_action = shot.get("action") or ""
            s_dialogue = shot.get("dialogue") or ""
            s_prompt = shot.get("visual_prompt") or ""
            s_audio = shot.get("audio") or ""
            s_chars = shot.get("characters") or []
            s_props = shot.get("props") or []
            speaker = next((name for name in s_chars if re.match(rf"^[*_`\s]*{re.escape(name)}[*_`\s]*[：:]", s_dialogue)), s_chars[0] if s_chars else "")
            matched_char_ids = match_named_asset_ids(s_chars, char_map)
            explicit_scene = bool(str(s_scene or "").strip())
            s_scene, matched_scene_id = resolve_shot_scene(
                s_scene, scene_map, inherited_scene_name, inherited_scene_id
            )
            if explicit_scene:
                inherited_scene_name = s_scene
                inherited_scene_id = matched_scene_id
            matched_prop_ids = match_named_asset_ids(s_props, prop_map)
            heading = f"{s_title} · {s_scene} · {s_camera}" if s_scene else s_title
            beat = {
                "id": f"beat-{uuid.uuid4().hex[:12]}",
                "sequence": s_num,
                "kind": "dialogue" if s_dialogue else "action",
                "heading": heading,
                "speaker": speaker,
                "dialogue": s_dialogue,
                "action": s_action,
                "camera": s_camera,
                "audio": s_audio,
                "characters": s_chars,
                "character_ids": matched_char_ids,
                "scene": s_scene,
                "scene_id": matched_scene_id,
                "props": s_props,
                "prop_ids": matched_prop_ids,
                "visual_prompt": s_prompt,
                "sketch_prompt": s_prompt,
                "sketch_url": None,
                "render_url": None,
                "video_url": None,
                "upscaled_video_url": None,
                "video_prompt_zh": " ".join(
                    part for part in (s_action, f"运镜：{s_camera}" if s_camera else "", f"声音：{s_audio}" if s_audio else "") if part
                ) or s_dialogue or s_prompt,
                "video_duration": str(cls._resolved_beat_duration({
                    "dialogue": s_dialogue,
                    "action": s_action,
                    "visual_prompt": s_prompt,
                    "duration_sec": shot.get("duration_sec"),
                    "video_duration": shot.get("video_duration"),
                    "durationSec": shot.get("durationSec") or shot.get("duration"),
                })),
                "status": "draft",
                "story_shot": s_num,
                "source_episode_id": episode_id,
            }
            cls._apply_resolved_beat_duration(beat)
            beats.append(beat)
        return beats

    @classmethod
    def transfer_episodes_from_document(
        cls,
        project_id: str,
        doc_id: str,
        mode: str = "overwrite",
    ) -> dict[str, Any]:
        """将解析出的分集与镜头同步到剧集工坊。

        overwrite：按本剧本重写已有集的镜头（含 data_json.beats），并删除剧本里没有的旧集。
        append：已有集号保持不动，只创建工坊还没有的集。
        """
        sync_mode = str(mode or "overwrite").strip().lower()
        if sync_mode not in {"overwrite", "append"}:
            raise ValueError("同步方式只能是覆盖已有集或只补新集")

        row = query_one(
            "SELECT id, analysis_json, raw_text, input_mode, project_id FROM ai_project_documents WHERE id = %s AND project_id = %s",
            (doc_id, project_id),
        )
        if not row:
            raise ValueError("文档不存在或尚未完成分析")
        analysis = cls._analysis_for_document_row(row, persist=True) or {}
        ts = now_str()
        # 同步只拷贝内容库已有出片镜。规划走 shot_plan 后台任务，不在同步请求里补跑。
        episodes = analysis.get("episodes") or []
        if not episodes:
            raise ValueError("该剧本中未识别到分集或分镜头信息")

        existing_rows = query_all("SELECT id, episode_num FROM ai_project_episodes WHERE project_id = %s", (project_id,))
        existing_map = {int(r["episode_num"]): r["id"] for r in existing_rows}
        assets_rows = query_all("SELECT id, kind, name, image_url, extra_json FROM ai_project_assets WHERE project_id = %s", (project_id,))
        char_map = asset_name_id_map(assets_rows, "character")
        scene_map = asset_name_id_map(assets_rows, "scene")
        prop_map = asset_name_id_map(assets_rows, "prop")

        incoming_nums: set[int] = set()
        created = 0
        replaced = 0
        skipped = 0
        transferred_shots = 0

        for ep in episodes:
            try:
                ep_num = int(ep.get("episode_num") or 1)
            except (TypeError, ValueError):
                ep_num = 1
            incoming_nums.add(ep_num)
            title = ep.get("title") or f"第 {ep_num} 集"
            shots = ep.get("shots") or []
            script_text = cls._episode_script_text(ep_num, title, str(ep.get("summary") or ""), shots)

            if ep_num in existing_map:
                if sync_mode == "append":
                    skipped += 1
                    continue
                eid = existing_map[ep_num]
                beats = cls._beats_from_document_shots(eid, shots, char_map, scene_map, prop_map)
                data = {
                    "beats": beats,
                    "summary": ep.get("summary") or "",
                    "source_document_id": doc_id,
                }
                execute_sql(
                    """
                    UPDATE ai_project_episodes
                    SET title = %s, script_text = %s, shots_count = %s, status = 'script_ready', data_json = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (title, script_text, len(beats), json.dumps(data, ensure_ascii=False), ts, eid),
                )
                replaced += 1
                transferred_shots += len(beats)
                continue

            eid = f"ep-{uuid.uuid4().hex[:12]}"
            beats = cls._beats_from_document_shots(eid, shots, char_map, scene_map, prop_map)
            data = {
                "beats": beats,
                "summary": ep.get("summary") or "",
                "source_document_id": doc_id,
            }
            execute_sql(
                """
                INSERT INTO ai_project_episodes
                (id, project_id, episode_num, title, status, script_text, shots_count, data_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'script_ready', %s, %s, %s, %s, %s)
                """,
                (eid, project_id, ep_num, title, script_text, len(beats), json.dumps(data, ensure_ascii=False), ts, ts),
            )
            created += 1
            transferred_shots += len(beats)

        deleted = 0
        if sync_mode == "overwrite":
            for num, eid in list(existing_map.items()):
                if num not in incoming_nums:
                    execute_sql("DELETE FROM ai_project_episodes WHERE id = %s AND project_id = %s", (eid, project_id))
                    deleted += 1

        return {
            "mode": sync_mode,
            "transferred_episodes": created + replaced,
            "created_episodes": created,
            "replaced_episodes": replaced,
            "skipped_episodes": skipped,
            "deleted_episodes": deleted,
            "transferred_shots": transferred_shots,
        }

    # --- 2. 资产库 Assets ---
    @classmethod
    def _hydrate_asset(cls, row: dict[str, Any]) -> dict[str, Any]:
        """填充资产的 extra 数据结构（角色多造型、场景主反打机位、道具特写归属）"""
        extra: dict[str, Any] = {}
        if row.get("extra_json"):
            try:
                extra = json.loads(row["extra_json"])
            except Exception:
                extra = {}
        
        kind = row.get("kind")
        # 1. 角色类型
        if kind == "character":
            if not extra.get("avatar_url"):
                extra["avatar_url"] = row.get("image_url") or ""
            if not extra.get("avatar_prompt"):
                extra["avatar_prompt"] = f"{row['name']}，面部肖像，五官特写，眼神清亮坚毅，写实电影级光影，8k"
            
            identities = extra.get("identities")
            if not identities or not isinstance(identities, list):
                base_desc = row.get("description") or "日常基础造型"
                base_prompt = row.get("visual_prompt") or f"{row['name']} 半身立绘，{base_desc}，电影级质感，8k"
                identities = [
                    {
                        "id": f"ident-{row['id'][-6:] if len(row['id']) >= 6 else 'default'}",
                        "name": f"{row['name']} (日常/初始造型)",
                        "description": base_desc,
                        "visual_prompt": base_prompt,
                        "image_url": row.get("image_url") or "",
                    }
                ]
                extra["identities"] = identities
            extra["voice"] = normalize_voice_profile(extra.get("voice"))

        # 2. 场景类型 (参考 source2: Master主视角 + Reverse背面反打视角 + Pano 360全景图)
        elif kind == "scene":
            if not extra.get("master_url"):
                extra["master_url"] = row.get("image_url") or ""
            if not extra.get("reverse_url"):
                extra["reverse_url"] = ""
            if not extra.get("pano_url"):
                extra["pano_url"] = ""
            if not extra.get("scene_type"):
                is_interior = any(w in (row.get("name") or "") for w in ["堂", "房", "斋", "室内", "舍", "阁", "楼", "院内", "私塾"])
                extra["scene_type"] = "interior" if is_interior else "exterior"
            if not extra.get("environment_prompt"):
                extra["environment_prompt"] = row.get("visual_prompt") or row.get("description") or f"{row['name']}，电影级空镜空间全景，忠于剧本的时代与环境设定，自然光影"
            if not extra.get("reverse_prompt"):
                extra["reverse_prompt"] = f"{row['name']}，对立反打机位视角，180度反向景深透视，影视级空间镜头，8k"
            if not extra.get("pano_prompt"):
                extra["pano_prompt"] = f"{row['name']}，360度球形等距柱状全景图，忠于剧本的时代与环境设定，无缝环视"

        # 3. 道具类型 (严格参考 source2: 参考图 + 转面图三视图 + 细节特写 + 归属人物 + 道具类别)
        elif kind == "prop":
            if not extra.get("reference_url"):
                extra["reference_url"] = row.get("image_url") or ""
            if not extra.get("turnaround_url"):
                extra["turnaround_url"] = ""
            if not extra.get("detail_url"):
                extra["detail_url"] = ""
            if not extra.get("owner"):
                extra["owner"] = row.get("role") or ""
            if not extra.get("prop_type"):
                name_str = row.get("name") or ""
                if any(w in name_str for w in ["剑", "刀", "枪", "弓", "匕首", "兵器", "扇"]):
                    extra["prop_type"] = "weapon"       # 武器
                elif any(w in name_str for w in ["佩", "戒", "镯", "簪", "冠", "饰"]):
                    extra["prop_type"] = "accessory"    # 饰品
                elif any(w in name_str for w in ["印", "鼎", "镜", "符", "法器", "圣物"]):
                    extra["prop_type"] = "artifact"     # 神器/法器
                elif any(w in name_str for w in ["书", "信", "折", "图", "册", "文书", "密信"]):
                    extra["prop_type"] = "document"     # 文书
                elif any(w in name_str for w in ["桌", "椅", "案", "床", "屏风", "箱", "榻"]):
                    extra["prop_type"] = "furniture"    # 家具
                else:
                    extra["prop_type"] = "object"       # 其他物件
            if not extra.get("visual_prompt"):
                extra["visual_prompt"] = row.get("visual_prompt") or f"{row['name']}，影视道具概念设计参考图，高清质感，8k"
            if not extra.get("turnaround_prompt"):
                extra["turnaround_prompt"] = f"{row['name']}，道具三视图转面图设计，正视、侧视、俯视/背视三面图，干净纯色背景，工业造型设计图纸，8k"
            if not extra.get("detail_prompt"):
                extra["detail_prompt"] = f"{row['name']}，静物微距细节特写摄影，局部材质纹理、开刃做旧与磨损雕花，微距镜头光影，8k"

        extra["source_references"] = normalize_source_references(extra)
        row["extra"] = extra
        return row

    @classmethod
    def list_assets(cls, project_id: str, kind: Optional[str] = None) -> list[dict[str, Any]]:
        if kind:
            rows = query_all(
                "SELECT * FROM ai_project_assets WHERE project_id = %s AND kind = %s ORDER BY updated_at DESC",
                (project_id, kind),
            )
        else:
            rows = query_all(
                "SELECT * FROM ai_project_assets WHERE project_id = %s ORDER BY updated_at DESC",
                (project_id,),
            )
        return [cls._hydrate_asset(r) for r in rows]

    @classmethod
    def create_asset(cls, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        aid = f"ast-{uuid.uuid4().hex[:12]}"
        ts = now_str()
        name = payload.get("name", "").strip()
        if not name:
            raise ValueError("资产名称不能为空")

        kind = payload.get("kind", "character")
        extra = payload.get("extra") or {}
        if not extra and payload.get("extra_json"):
            try:
                extra = json.loads(payload["extra_json"])
            except Exception:
                extra = {}

        if kind == "character" and not extra.get("identities"):
            base_desc = payload.get("description") or "日常基础造型"
            extra["avatar_url"] = payload.get("image_url") or ""
            extra["avatar_prompt"] = f"{name}，面部肖像，五官特写，超写实电影质感，8k"
            extra["identities"] = [
                {
                    "id": f"ident-{aid[-6:]}",
                    "name": f"{name} (日常造型)",
                    "description": base_desc,
                    "visual_prompt": payload.get("visual_prompt") or f"{name} 全身立绘，{base_desc}",
                    "image_url": payload.get("image_url") or "",
                }
            ]
        elif kind == "scene":
            extra["master_url"] = payload.get("image_url") or ""
            extra["environment_prompt"] = payload.get("visual_prompt") or f"{name}，电影级实景空间，8k"
        elif kind == "prop":
            extra["reference_url"] = payload.get("image_url") or ""
            extra["owner"] = payload.get("role") or ""

        extra_json = json.dumps(extra, ensure_ascii=False) if extra else None

        execute_sql(
            """
            INSERT INTO ai_project_assets
            (id, project_id, kind, name, role, description, visual_prompt, image_url, voice_id, extra_json, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                aid,
                project_id,
                kind,
                name,
                payload.get("role", ""),
                payload.get("description", ""),
                payload.get("visual_prompt", ""),
                payload.get("image_url", ""),
                payload.get("voice_id", ""),
                extra_json,
                ts,
                ts,
            ),
        )
        row = query_one("SELECT * FROM ai_project_assets WHERE id = %s", (aid,))
        return cls._hydrate_asset(row) if row else {}

    @classmethod
    def update_asset(cls, project_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        ts = now_str()
        current = query_one("SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s", (asset_id, project_id))
        if not current:
            raise ValueError("资产不存在")

        extra_val = current.get("extra_json")
        if "extra" in payload:
            extra_val = json.dumps(payload["extra"], ensure_ascii=False)
        elif "extra_json" in payload:
            extra_val = payload["extra_json"]

        img_url = payload.get("image_url", current.get("image_url", ""))
        # 角色联动 avatar_url，场景联动 master_url，道具联动 reference_url
        if "extra" in payload and isinstance(payload["extra"], dict):
            if payload["extra"].get("avatar_url"):
                img_url = payload["extra"]["avatar_url"]
            elif payload["extra"].get("master_url"):
                img_url = payload["extra"]["master_url"]
            elif payload["extra"].get("reference_url"):
                img_url = payload["extra"]["reference_url"]

        execute_sql(
            """
            UPDATE ai_project_assets
            SET name = %s, role = %s, description = %s, visual_prompt = %s, image_url = %s, voice_id = %s, extra_json = %s, updated_at = %s
            WHERE id = %s AND project_id = %s
            """,
            (
                payload.get("name", current.get("name")),
                payload.get("role", current.get("role")),
                payload.get("description", current.get("description")),
                payload.get("visual_prompt", current.get("visual_prompt")),
                img_url,
                payload.get("voice_id", current.get("voice_id")),
                extra_val,
                ts,
                asset_id,
                project_id,
            ),
        )
        row = query_one("SELECT * FROM ai_project_assets WHERE id = %s", (asset_id,))
        return cls._hydrate_asset(row) if row else {}

    @classmethod
    def delete_asset(cls, project_id: str, asset_id: str) -> bool:
        aff = execute_sql("DELETE FROM ai_project_assets WHERE id = %s AND project_id = %s", (asset_id, project_id))
        return aff > 0

    @classmethod
    def generate_asset_image(cls, project_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raw_row = query_one("SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s", (asset_id, project_id))
        if not raw_row:
            raise ValueError("资产不存在")

        row = cls._hydrate_asset(raw_row)
        target_type = payload.get("target_type") or "asset"  # 'avatar' | 'identity' | 'scene_master' | 'scene_reverse' | 'scene_pano' | 'prop_reference' | 'asset'
        target_kind = "character" if target_type in {"avatar", "identity"} else "scene" if target_type.startswith("scene_") else "prop" if target_type.startswith("prop_") else None
        if target_kind and row.get("kind") != target_kind:
            raise ValueError("生图目标与资产类型不匹配，请重新打开对应资产后生成")
        identity_id = payload.get("identity_id")
        prompt = (payload.get("prompt") or "").strip()
        # 解析请求的模型参数，默认为 GPT Image 2.5（1K 基础档）
        requested_model = (payload.get("model") or "").strip() or ASSET_IMAGE_DEFAULT_MODEL
        # 查找匹配的模型（按 provider_model, display_name 或 workflow_id）
        model_row = query_one(
            """
            SELECT provider_model, display_name, profile FROM grs_image_models
            WHERE (provider_model = %s OR display_name = %s OR workflow_id = %s) AND enabled = 1
            ORDER BY is_default DESC LIMIT 1
            """,
            (requested_model, requested_model, requested_model),
        )
        if not model_row:
            model_row = query_one(
                "SELECT provider_model, display_name, profile FROM grs_image_models WHERE is_default = 1 AND enabled = 1 LIMIT 1"
            )
        grs_model = (model_row["provider_model"] if model_row else None) or ASSET_IMAGE_DEFAULT_MODEL
        grs_profile = (model_row["profile"] if model_row else None) or ASSET_IMAGE_DEFAULT_PROFILE
        model_display = (model_row["display_name"] if model_row else None) or grs_model
        extra = row.get("extra") or {}
        extra["source_references"] = normalize_source_references(extra)
        follow_source_photos = bool(source_reference_urls(extra))
        for key in ("ethnicity", "visual_style", "art_style_id", "body_type", "gender", "face_prompt"):
            value = payload.get(key)
            if value not in (None, ""):
                extra[key] = value
        char_ethnicity = str(payload.get("ethnicity") or extra.get("ethnicity") or "Chinese").strip() or "Chinese"

        reference_images: list[str] = []
        reference_urls: list[str] = []
        visual_style = str(payload.get("visual_style") or extra.get("visual_style") or "").strip()
        art_style_id = str(payload.get("art_style_id") or extra.get("art_style_id") or "").strip()

        if target_type == "avatar":
            aspect_ratio = payload.get("aspect_ratio") or "1:1"
            clean_prompt = character_portrait_prompt(
                row,
                extra,
                style=art_style_id,
                visual_style=visual_style,
                ethnicity=char_ethnicity,
                face_prompt="" if follow_source_photos else prompt,
                follow_source_photos=follow_source_photos,
            )
            job_title = f"生成角色头像: {row['name']} ({grs_model})"
        elif target_type == "identity":
            ident_item = next((it for it in extra.get("identities", []) if it.get("id") == identity_id), None)
            if ident_item is None:
                raise ValueError("找不到该造型")
            # 设定板默认 16:9；画布 Prompt Bar 可传其他比例，注册表不支持的值回退 16:9。
            requested_aspect = str(payload.get("aspect_ratio") or IDENTITY_SHEET_ASPECT_RATIO)
            if requested_aspect not in GRS_VIP_SIZES:
                requested_aspect = IDENTITY_SHEET_ASPECT_RATIO
            spec = build_identity_generation(
                row,
                ident_item,
                extra,
                prompt=prompt,
                follow_source_photos=follow_source_photos,
                style=art_style_id,
                visual_style=visual_style,
                ethnicity=char_ethnicity,
                aspect_ratio=requested_aspect,
            )
            aspect_ratio = spec["aspect_ratio"]
            reference_urls = list(spec["reference_urls"])
            clean_prompt = spec["clean_prompt"]
            prompt = spec["costume"]
            job_title = f"生成造型形象: {row['name']} - {spec['ident_name']} ({grs_model})"
        elif target_type == "scene_master":
            aspect_ratio = payload.get("aspect_ratio") or "16:9"
            if follow_source_photos:
                clean_prompt = (
                    "master wide shot cinematic scene matching the source photos exactly, "
                    "establishing shot, architectural environment, 8k resolution. "
                    "Do not add furniture, signage, or objects that are not in the photos."
                )
            else:
                if not prompt:
                    prompt = extra.get("environment_prompt") or row.get("visual_prompt") or row.get("name")
                prompt = safe_scene_master_prompt(prompt, str(row.get("name") or ""))
                clean_prompt = f"{prompt}, master wide shot cinematic scene, establishing shot, architectural environment, 8k resolution"
            job_title = f"生成场景主视角: {row['name']} ({grs_model})"
        elif target_type == "scene_reverse":
            aspect_ratio = payload.get("aspect_ratio") or "16:9"
            master_url = (extra.get("master_url") or row.get("image_url") or "").strip()
            if not master_url:
                raise ValueError("请先生成或上传正面源图，背面图需要把它作为 REFERENCE 1 传入")
            reference_urls = [master_url]
            clean_prompt = scene_view_prompt(
                row,
                "reverse",
                extra,
                style=art_style_id,
                visual_style=visual_style,
                has_master_reference=True,
            )
            job_title = f"生成场景反打视角: {row['name']} ({grs_model})"
        elif target_type == "scene_pano":
            aspect_ratio = payload.get("aspect_ratio") or "2:1"
            master_url = (extra.get("master_url") or row.get("image_url") or "").strip()
            if not master_url:
                raise ValueError("请先生成或上传正面源图，360全景需要把它作为 REFERENCE 1 传入")
            reverse_url = (extra.get("reverse_url") or "").strip()
            reference_urls = [master_url]
            if reverse_url:
                reference_urls.append(reverse_url)
            clean_prompt = scene_view_prompt(
                row,
                "panorama",
                extra,
                style=art_style_id,
                visual_style=visual_style,
                has_master_reference=True,
                has_reverse_reference=bool(reverse_url),
            )
            job_title = f"生成场景360全景图: {row['name']} ({grs_model})"
        elif target_type == "prop_reference":
            aspect_ratio = payload.get("aspect_ratio") or "16:9"
            clean_prompt = prop_view_prompt(
                row, "master", extra, style=art_style_id, visual_style=visual_style
            )
            job_title = f"生成道具参考图: {row['name']} ({grs_model})"
        elif target_type == "prop_turnaround":
            aspect_ratio = payload.get("aspect_ratio") or "16:9"
            master_url = (extra.get("reference_url") or row.get("image_url") or "").strip()
            if not master_url:
                raise ValueError("请先生成或上传主视图，转面三视图需要把它作为 REFERENCE 1 传入")
            reference_urls = [master_url]
            clean_prompt = prop_view_prompt(
                row,
                "turnaround",
                extra,
                style=art_style_id,
                visual_style=visual_style,
                has_master_reference=True,
            )
            job_title = f"生成道具转面三视图: {row['name']} ({grs_model})"
        elif target_type == "prop_detail":
            aspect_ratio = payload.get("aspect_ratio") or "16:9"
            master_url = (extra.get("reference_url") or row.get("image_url") or "").strip()
            if not master_url:
                raise ValueError("请先生成或上传主视图，细节特写需要把它作为 REFERENCE 1 传入")
            reference_urls = [master_url]
            clean_prompt = prop_view_prompt(
                row,
                "detail",
                extra,
                style=art_style_id,
                visual_style=visual_style,
                has_master_reference=True,
            )
            job_title = f"生成道具细节特写: {row['name']} ({grs_model})"
        else:
            aspect_ratio = payload.get("aspect_ratio") or ("1:1" if row.get("kind") == "character" else "16:9")
            if not prompt:
                prompt = row.get("visual_prompt") or row.get("description") or row.get("name")
            clean_prompt = f"{prompt}, cinematic lighting, ultra-detailed, 8k resolution, photorealistic"
            job_title = f"生成资产形象: {row['name']} ({grs_model})"

        extra["source_references"] = normalize_source_references(extra)
        reference_urls, clean_prompt = apply_source_references_to_generation(
            kind=str(row.get("kind") or ""),
            extra=extra,
            payload=payload,
            target_type=target_type,
            reference_urls=reference_urls,
            clean_prompt=clean_prompt,
        )

        dim_map = {
            "1:1": (1024, 1024),
            "3:4": (896, 1152),
            "9:16": (768, 1344),
            "16:9": (1344, 768),
            "2:1": (2048, 1024),
            "4:3": (1152, 896),
        }
        if target_type == "identity":
            # 设定板默认 16:9 / 2K；画布 Prompt Bar 可传其他比例，非法值回退 16:9。
            supported_ratios = set(GRS_VIP_SIZES) | set(dim_map)
            if aspect_ratio not in supported_ratios:
                aspect_ratio = IDENTITY_SHEET_ASPECT_RATIO
            image_size = IDENTITY_SHEET_IMAGE_SIZE
            w, h = identity_sheet_dimensions(aspect_ratio)
        else:
            image_size = "1K"
            w, h = dim_map.get(aspect_ratio, (1024, 1024))

        # GPT Image 2.5 系列线上协议要求像素值或 auto（与主注册表 grs_request_size 同一映射）。
        wire_aspect_ratio = grs_wire_aspect_ratio(grs_profile, aspect_ratio, image_size)

        # -------- 严格调用图片服务极速生图供应商 (对齐 source1) --------
        grs_row_data = grs_row()
        grs_base_url = grs_row_data.get("base_url") or "https://grsai.dakka.com.cn"
        encrypted_key = grs_row_data.get("api_key_encrypted")

        cred = credential_manager()
        api_key = cred.decrypt(encrypted_key) if encrypted_key else None
        if not api_key:
            raise ValueError("图片服务供应商 API Key 未配置，请前往「系统设置 - 图片服务供应商」配置有效 API Key。")

        ts = now_str()
        jid = f"job-{uuid.uuid4().hex[:12]}"
        job_payload = {
            "model": grs_model,
            "api_endpoint": f"{grs_base_url}/v1/api/generate",
            "image_size": image_size,
            "target_type": target_type,
            "prompt": prompt,
            "clean_prompt": clean_prompt,
            "aspect_ratio": aspect_ratio,
            "width": w,
            "height": h,
            "asset_id": asset_id,
            "asset_name": row.get("name", ""),
            "identity_id": identity_id,
            "identity_anchor": target_type == "identity",
            "visual_style": visual_style,
            "art_style_id": art_style_id,
            "ethnicity": char_ethnicity,
            "body_type": extra.get("body_type") or "",
            "gender": extra.get("gender") or "",
            "reply_type": "async",
            "source_reference_count": len(source_reference_urls(extra)),
            "reference_urls": reference_urls,
            "request_body": {
                "model": grs_model,
                "prompt": clean_prompt,
                "images": reference_urls,
                "aspectRatio": wire_aspect_ratio,
                "imageSize": image_size,
                "replyType": "async",
            },
        }
        execute_sql(
            """
            INSERT INTO ai_project_jobs
            (id, project_id, job_type, title, status, progress, result_url, payload_json, created_at, updated_at)
            VALUES (%s, %s, 'image_generation', %s, 'running', 10, NULL, %s, %s, %s)
            """,
            (jid, project_id, job_title, json.dumps(job_payload, ensure_ascii=False), ts, ts),
        )

        client = GrsClient(base_url=grs_base_url, api_key=api_key)
        try:
            if reference_urls:
                reference_images = []
                for ref_url in reference_urls:
                    ref_name, ref_bytes = client.download_image(ref_url)
                    reference_images.append(GrsClient.data_uri_from_bytes(ref_bytes, ref_name))
            grs_url = client.generate_sync(
                model=grs_model,
                prompt=clean_prompt,
                aspect_ratio=wire_aspect_ratio,
                images=reference_images,
                image_size=image_size,
            )
            filename, content = client.download_image(grs_url)
            object_key, image_url = QiniuService.store_bytes("image", filename, content)
        except (GrsError, RuntimeError, Exception) as e:
            fail_ts = now_str()
            err_text = str(e)
            if isinstance(e, GrsError):
                err_text = f"图片服务生图失败: {e}"
            execute_sql(
                """
                UPDATE ai_project_jobs
                SET status = 'failed', progress = 0, error_message = %s, updated_at = %s
                WHERE id = %s
                """,
                (err_text[:4000], fail_ts, jid),
            )
            if isinstance(e, GrsError):
                raise ValueError(err_text) from e
            if isinstance(e, RuntimeError):
                raise ValueError(err_text) from e
            raise
        # -------- 图片服务调用结束 --------

        ts = now_str()
        generation_extra = extra
        latest_asset_row = query_one("SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s", (asset_id, project_id))
        if latest_asset_row:
            # Generation may take minutes. Bind only its media to the current asset,
            # retaining node positions, references and text saved in the meantime.
            extra = cls._hydrate_asset(latest_asset_row).get("extra") or {}

        # 根据 target_type 更新对应字段
        if target_type == "avatar":
            extra["avatar_url"] = image_url
            extra["avatar_object_key"] = object_key
            if prompt and extra.get("avatar_prompt") == generation_extra.get("avatar_prompt"):
                extra["avatar_prompt"] = prompt
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET image_url = %s, extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (image_url, extra_json, ts, asset_id, project_id),
            )
        elif target_type == "identity":
            identities = extra.get("identities", [])
            found = False
            for it in identities:
                if it.get("id") == identity_id:
                    it["image_url"] = image_url
                    it["object_key"] = object_key
                    found = True
                    break
            if not found and identity_id:
                identities.append({
                    "id": identity_id,
                    "name": "新造型",
                    "description": "",
                    "visual_prompt": prompt,
                    "image_url": image_url,
                    "object_key": object_key,
                })
            extra["identities"] = identities
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (extra_json, ts, asset_id, project_id),
            )
        elif target_type == "scene_master":
            extra["master_url"] = image_url
            if prompt and extra.get("environment_prompt") == generation_extra.get("environment_prompt"):
                extra["environment_prompt"] = prompt
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET image_url = %s, extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (image_url, extra_json, ts, asset_id, project_id),
            )
        elif target_type == "scene_reverse":
            extra["reverse_url"] = image_url
            extra["reverse_object_key"] = object_key
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (extra_json, ts, asset_id, project_id),
            )
        elif target_type == "scene_pano":
            extra["pano_url"] = image_url
            extra["pano_object_key"] = object_key
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (extra_json, ts, asset_id, project_id),
            )
        elif target_type == "prop_reference":
            extra["reference_url"] = image_url
            extra["reference_object_key"] = object_key
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET image_url = %s, extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (image_url, extra_json, ts, asset_id, project_id),
            )
        elif target_type == "prop_turnaround":
            extra["turnaround_url"] = image_url
            extra["turnaround_object_key"] = object_key
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (extra_json, ts, asset_id, project_id),
            )
        elif target_type == "prop_detail":
            extra["detail_url"] = image_url
            extra["detail_object_key"] = object_key
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (extra_json, ts, asset_id, project_id),
            )
        else:
            execute_sql(
                """
                UPDATE ai_project_assets
                SET image_url = %s, visual_prompt = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (image_url, prompt, ts, asset_id, project_id),
            )


        job_payload["api_url"] = image_url
        job_payload["grs_url"] = grs_url
        job_payload["object_key"] = object_key
        execute_sql(
            """
            UPDATE ai_project_jobs
            SET status = 'completed', progress = 100, result_url = %s, payload_json = %s,
                error_message = NULL, completed_at = %s, updated_at = %s
            WHERE id = %s
            """,
            (image_url, json.dumps(job_payload, ensure_ascii=False), ts, ts, jid),
        )


        updated_row = query_one("SELECT * FROM ai_project_assets WHERE id = %s", (asset_id,))
        hydrated = cls._hydrate_asset(updated_row) if updated_row else {}
        return {
            "status": "success",
            "image_url": image_url,
            "job_id": jid,
            "target_type": target_type,
            "identity_id": identity_id,
            "source_reference_count": job_payload["source_reference_count"],
            "asset": hydrated,
        }

    @classmethod
    def _persist_asset_extra(cls, project_id: str, asset_id: str, extra: dict[str, Any]) -> dict[str, Any]:
        extra_json = json.dumps(extra, ensure_ascii=False)
        ts = now_str()
        execute_sql(
            """
            UPDATE ai_project_assets
            SET extra_json = %s, updated_at = %s
            WHERE id = %s AND project_id = %s
            """,
            (extra_json, ts, asset_id, project_id),
        )
        updated_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not updated_row:
            raise ValueError("资产不存在")
        return cls._hydrate_asset(updated_row)

    @classmethod
    def upload_asset_image(
        cls, project_id: str, asset_id: str, *, target_type: str, identity_id: str = "",
        filename: str, content: bytes, content_type: str = "",
    ) -> dict[str, Any]:
        """Bind an uploaded image to a production slot without adding a source reference."""
        targets = {
            "identity": ("character", None), "scene_master": ("scene", "master_url"),
            "scene_reverse": ("scene", "reverse_url"), "scene_pano": ("scene", "pano_url"),
            "prop_reference": ("prop", "reference_url"), "prop_turnaround": ("prop", "turnaround_url"),
            "prop_detail": ("prop", "detail_url"),
        }
        row = query_one("SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s", (asset_id, project_id))
        if not row:
            raise ValueError("资产不存在")
        target = targets.get(target_type)
        if not target or row.get("kind") != target[0]:
            raise ValueError("图片目标与资产类型不匹配")
        asset = cls._hydrate_asset(row)
        if target_type == "identity" and (not identity_id or not any(str(item.get("id") or "") == identity_id for item in asset["extra"].get("identities", []))):
            raise ValueError("找不到该造型")
        if not content or len(content) > MAX_SOURCE_REFERENCE_BYTES:
            raise ValueError("图片不能为空且不能超过 10 MB")
        from io import BytesIO
        from PIL import Image
        try:
            with Image.open(BytesIO(content)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                    raise ValueError("不支持的图片格式")
                image.verify()
        except Exception as err:
            raise ValueError("图片无法读取，请上传有效的 JPG / PNG / WebP / GIF") from err
        suffix = sniff_image_suffix(content, filename, content_type)
        object_key, image_url = QiniuService.store_bytes("asset-image", filename or f"image{suffix}", content)
        # Re-read after storage so text/layout changes made during upload are retained.
        latest = query_one("SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s", (asset_id, project_id))
        if not latest:
            raise ValueError("资产不存在")
        current = cls._hydrate_asset(latest)
        extra = current.get("extra") or {}
        image = current.get("image_url") or ""
        if target_type == "identity":
            found = False
            identities = []
            for item in extra.get("identities", []):
                if str(item.get("id") or "") == identity_id:
                    item = {**item, "image_url": image_url, "object_key": object_key}
                    found = True
                identities.append(item)
            if not found:
                raise ValueError("造型已移除，请重新选择上传目标")
            extra["identities"] = identities
            if not image or (identities and str(identities[0].get("id") or "") == identity_id):
                image = image_url
        else:
            field = target[1]
            extra[field] = image_url
            extra[field.removesuffix("_url") + "_object_key"] = object_key
            if target_type in {"scene_master", "prop_reference"}:
                image = image_url
        execute_sql(
            "UPDATE ai_project_assets SET image_url = %s, extra_json = %s, updated_at = %s WHERE id = %s AND project_id = %s",
            (image, json.dumps(extra, ensure_ascii=False), now_str(), asset_id, project_id),
        )
        saved = query_one("SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s", (asset_id, project_id))
        if not saved:
            raise ValueError("资产不存在")
        return cls._hydrate_asset(saved)

    @classmethod
    def add_asset_source_reference(
        cls,
        project_id: str,
        asset_id: str,
        *,
        filename: str,
        content: bytes,
        content_type: str = "",
    ) -> dict[str, Any]:
        raw_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not raw_row:
            raise ValueError("资产不存在")
        if not content:
            raise ValueError("文件为空")
        if len(content) > MAX_SOURCE_REFERENCE_BYTES:
            raise ValueError("参考图不能超过 10 MB")
        suffix = sniff_image_suffix(content, filename, content_type)
        safe_name = (filename or f"source{suffix}").strip() or f"source{suffix}"
        _object_key, image_url = QiniuService.store_bytes("asset-ref", safe_name, content)
        extra = cls._hydrate_asset(raw_row).get("extra") or {}
        extra["source_references"] = append_source_reference(
            extra,
            url=image_url,
            filename=filename or safe_name,
        )
        extra.pop("source_reference_urls", None)
        return cls._persist_asset_extra(project_id, asset_id, extra)

    @classmethod
    def delete_asset_source_reference(cls, project_id: str, asset_id: str, ref_id: str) -> dict[str, Any]:
        raw_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not raw_row:
            raise ValueError("资产不存在")
        extra = cls._hydrate_asset(raw_row).get("extra") or {}
        before = normalize_source_references(extra)
        extra["source_references"] = remove_source_reference(extra, ref_id)
        if len(extra["source_references"]) == len(before):
            raise ValueError("参考图不存在")
        return cls._persist_asset_extra(project_id, asset_id, extra)

    @classmethod
    def upload_asset_voice(
        cls,
        project_id: str,
        asset_id: str,
        *,
        filename: str,
        content: bytes,
        content_type: str = "",
    ) -> dict[str, Any]:
        raw_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not raw_row:
            raise ValueError("资产不存在")
        if str(raw_row.get("kind") or "") != "character":
            raise ValueError("只有角色可以绑定参考音")
        if not content:
            raise ValueError("文件为空")
        if len(content) > MAX_VOICE_AUDIO_BYTES:
            raise ValueError("参考音不能超过 20 MB")
        suffix = sniff_audio_suffix(content, filename, content_type)
        safe_name = (filename or f"voice{suffix}").strip() or f"voice{suffix}"
        _key, audio_url = QiniuService.store_bytes("asset-voice", safe_name, content)
        extra = cls._hydrate_asset(raw_row).get("extra") or {}
        extra = merge_voice(extra, {"preset_id": "", "ref_audio_url": audio_url, "preview_url": "", "source": None})
        hydrated = cls._persist_asset_extra(project_id, asset_id, extra)
        voice_id = clone_voice_id(hydrated.get("voice_id") or raw_row.get("voice_id"))
        execute_sql(
            "UPDATE ai_project_assets SET voice_id = %s, extra_json = %s, updated_at = %s WHERE id = %s AND project_id = %s",
            (voice_id, json.dumps(hydrated.get("extra") or extra, ensure_ascii=False), now_str(), asset_id, project_id),
        )
        hydrated["voice_id"] = voice_id
        return hydrated

    @classmethod
    def delete_asset_voice(cls, project_id: str, asset_id: str) -> dict[str, Any]:
        raw_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not raw_row:
            raise ValueError("资产不存在")
        extra = cls._hydrate_asset(raw_row).get("extra") or {}
        extra = merge_voice(extra, {"preset_id": "", "ref_audio_url": "", "preview_url": "", "source": None})
        return cls._persist_asset_extra(project_id, asset_id, extra)

    @classmethod
    def apply_asset_voice_preset(cls, project_id: str, asset_id: str, preset_id: str) -> dict[str, Any]:
        from ...voice_bank import VoiceBankError, get_voice_preset, public_audio_url, read_voice_prompt

        raw_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not raw_row:
            raise ValueError("资产不存在")
        if str(raw_row.get("kind") or "") != "character":
            raise ValueError("只有角色可以绑定参考音")
        found = get_voice_preset(preset_id)
        if found is None:
            raise ValueError("内置声线不存在")
        try:
            read_voice_prompt(found["id"])
        except VoiceBankError as error:
            raise ValueError(str(error)) from error
        extra = cls._hydrate_asset(raw_row).get("extra") or {}
        extra = merge_voice(extra, {
            "preset_id": found["id"],
            "ref_audio_url": public_audio_url(found["id"]),
            "preview_url": "",
            "default_emotion": found.get("default_emotion") or "calm",
            "source": None,
        })
        hydrated = cls._persist_asset_extra(project_id, asset_id, extra)
        voice_id = clone_voice_id(hydrated.get("voice_id") or raw_row.get("voice_id"))
        execute_sql(
            "UPDATE ai_project_assets SET voice_id = %s, extra_json = %s, updated_at = %s WHERE id = %s AND project_id = %s",
            (voice_id, json.dumps(hydrated.get("extra") or extra, ensure_ascii=False), now_str(), asset_id, project_id),
        )
        hydrated["voice_id"] = voice_id
        return hydrated

    @classmethod
    def preview_asset_voice(cls, project_id: str, asset_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from .dubbing_service import prompt_audio_bytes, tts_provider_service
        from .dubbing_lines import estimate_duration_sec

        raw_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not raw_row:
            raise ValueError("资产不存在")
        hydrated = cls._hydrate_asset(raw_row)
        extra = dict(hydrated.get("extra") or {})
        voice = voice_of(extra)
        body = payload or {}
        if body.get("default_emotion") or body.get("emo_alpha") is not None or body.get("duration_factor") is not None:
            extra = merge_voice(extra, {
                "default_emotion": body.get("default_emotion", voice.get("default_emotion")),
                "emo_alpha": body.get("emo_alpha", voice.get("emo_alpha")),
                "duration_factor": body.get("duration_factor", voice.get("duration_factor")),
            })
            voice = voice_of(extra)
        text = str(body.get("text") or "").strip() or f"你好，我是{hydrated.get('name') or '角色'}。"
        tts = tts_provider_service()
        spk_audio = prompt_audio_bytes(voice) or None
        if not spk_audio:
            raise ValueError("请先绑定角色参考音")
        from ...gpu_runtime import occupy_gpu

        with occupy_gpu("tts"):
            audio = tts.synthesize(
                text,
                voice=hydrated.get("voice_id"),
                spk_audio=spk_audio,
                spk_filename="ref.wav",
                emotion=voice.get("default_emotion"),
                emo_alpha=voice.get("emo_alpha"),
                duration_factor=voice.get("duration_factor"),
            )
        suffix = ".wav" if audio.startswith(b"RIFF") else ".mp3"
        _key, preview_url = QiniuService.store_bytes("asset-voice-preview", f"{asset_id}{suffix}", audio)
        extra = merge_voice(extra, {"preview_url": preview_url})
        saved = cls._persist_asset_extra(project_id, asset_id, extra)
        return {
            "asset": saved,
            "preview_url": preview_url,
            "duration_sec": estimate_duration_sec(audio, text),
        }

    @classmethod
    def list_voice_extract_sources(cls, project_id: str, asset_id: str) -> dict[str, Any]:
        from .voice_extract import list_voice_extract_sources

        return {"sources": list_voice_extract_sources(project_id, asset_id)}

    @classmethod
    def extract_asset_voice_from_shot(
        cls,
        project_id: str,
        asset_id: str,
        *,
        episode_id: str,
        beat_id: str,
        start_sec: Any,
        end_sec: Any,
    ) -> dict[str, Any]:
        from .voice_extract import extract_asset_voice_from_shot

        return extract_asset_voice_from_shot(
            project_id,
            asset_id,
            episode_id=episode_id,
            beat_id=beat_id,
            start_sec=start_sec,
            end_sec=end_sec,
        )

    @classmethod
    def infer_asset_prompts(cls, project_id: str, asset_id: str) -> dict[str, Any]:
        raw_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not raw_row:
            raise ValueError("资产不存在")
        row = cls._hydrate_asset(raw_row)
        extra = dict(row.get("extra") or {})
        urls = source_urls_for_inference(extra)
        images = reference_urls_to_data_uris(urls)
        inferred = LlmService.infer_asset_prompts_from_images(
            kind=str(row.get("kind") or "character"),
            name=str(row.get("name") or ""),
            role=str(row.get("role") or extra.get("role_position") or ""),
            images=images,
        )
        extra, description, visual_prompt = apply_inferred_prompts(
            kind=str(row.get("kind") or "character"),
            extra=extra,
            inferred=inferred,
            name=str(row.get("name") or ""),
            current_description=str(row.get("description") or extra.get("description") or ""),
            current_visual_prompt=str(row.get("visual_prompt") or extra.get("visual_prompt") or extra.get("environment_prompt") or ""),
        )
        return cls.update_asset(
            project_id,
            asset_id,
            {
                "name": row.get("name") or "",
                "role": row.get("role") or "",
                "description": description,
                "visual_prompt": visual_prompt,
                "image_url": row.get("image_url") or "",
                "voice_id": row.get("voice_id") or "",
                "extra": extra,
            },
        )

    # --- 3. 剧集工坊 Episodes ---
    @classmethod
    def list_episodes(cls, project_id: str) -> list[dict[str, Any]]:
        return query_all(
            "SELECT * FROM ai_project_episodes WHERE project_id = %s ORDER BY episode_num ASC",
            (project_id,),
        )

    @classmethod
    def create_episode(cls, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        eid = f"ep-{uuid.uuid4().hex[:12]}"
        ts = now_str()
        num = payload.get("episode_num", 1)
        title = payload.get("title") or f"第 {num} 集"
        execute_sql(
            """
            INSERT INTO ai_project_episodes (id, project_id, episode_num, title, status, script_text, shots_count, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                eid,
                project_id,
                num,
                title,
                payload.get("status", "draft"),
                payload.get("script_text", ""),
                payload.get("shots_count", 0),
                ts,
                ts,
            ),
        )
        return query_one("SELECT * FROM ai_project_episodes WHERE id = %s", (eid,))

    @classmethod
    def update_episode(cls, project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        ts = now_str()
        execute_sql(
            """
            UPDATE ai_project_episodes
            SET title = %s, status = %s, script_text = %s, shots_count = %s, updated_at = %s
            WHERE id = %s AND project_id = %s
            """,
            (
                payload.get("title", ""),
                payload.get("status", "draft"),
                payload.get("script_text", ""),
                payload.get("shots_count", 0),
                ts,
                episode_id,
                project_id,
            ),
        )
        return query_one("SELECT * FROM ai_project_episodes WHERE id = %s", (episode_id,))

    @classmethod
    def delete_episode(cls, project_id: str, episode_id: str) -> bool:
        aff = execute_sql("DELETE FROM ai_project_episodes WHERE id = %s AND project_id = %s", (episode_id, project_id))
        return aff > 0

    @staticmethod
    def _resolved_beat_duration(beat: dict[str, Any]) -> int:
        from ...dialogue_timing import resolve_shot_duration_sec
        return resolve_shot_duration_sec(beat)

    @classmethod
    def _apply_resolved_beat_duration(cls, beat: dict[str, Any]) -> bool:
        if not isinstance(beat, dict):
            return False
        resolved = cls._resolved_beat_duration(beat)
        raw = str(beat.get("video_duration") or "").strip()
        try:
            stored = int(float(raw)) if raw else 0
        except (TypeError, ValueError):
            stored = 0
        if stored >= resolved and stored >= 2:
            return False
        beat["video_duration"] = str(resolved)
        return True

    @classmethod
    def get_episode_detail(cls, project_id: str, episode_id: str) -> dict[str, Any]:
        """获取分集详细数据（含结构化分镜 beats、关联资产 links 等，对齐 source1 XiajiEpisode）"""
        ep_row = query_one("SELECT * FROM ai_project_episodes WHERE id = %s AND project_id = %s", (episode_id, project_id))
        if not ep_row:
            raise ValueError("分集不存在")

        ep = dict(ep_row)
        data = {}
        if ep.get("data_json"):
            try:
                data = json.loads(ep["data_json"])
            except Exception:
                data = {}

        beats = data.get("beats") or []

        # 获取项目资产供反查关联
        assets_rows = query_all("SELECT id, kind, name, image_url, extra_json FROM ai_project_assets WHERE project_id = %s", (project_id,))
        char_map = asset_name_id_map(assets_rows, "character")
        scene_map = asset_name_id_map(assets_rows, "scene")
        prop_map = asset_name_id_map(assets_rows, "prop")

        # 如果 beats 为空，从关联剧本文档解析出的分析结果抽取或生成初始分镜
        if not beats:
            doc_row = query_one(
                "SELECT analysis_json FROM ai_project_documents WHERE project_id = %s ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            )
            doc_analysis = json.loads(doc_row["analysis_json"]) if (doc_row and doc_row.get("analysis_json")) else {}
            episodes_list = doc_analysis.get("episodes") or []
            target_ep = next((e for e in episodes_list if e.get("episode_num") == ep["episode_num"]), None)

            shots = (target_ep.get("shots") if target_ep else []) or []
            # 如果依然没有，从 script_text 简单解析行
            if not shots and ep.get("script_text"):
                lines = [l.strip() for l in ep["script_text"].split("\n") if l.strip()]
                for idx, line in enumerate(lines):
                    shots.append({
                        "shot_num": idx + 1,
                        "title": f"分镜 {idx + 1}",
                        "action": line,
                        "visual_prompt": f"{ep['title']}，分镜{idx + 1}，{line}，电影级画面，8k",
                    })

            beats = cls._beats_from_document_shots(episode_id, shots, char_map, scene_map, prop_map)
            data["beats"] = beats
            execute_sql(
                "UPDATE ai_project_episodes SET data_json = %s, shots_count = %s WHERE id = %s",
                (json.dumps(data, ensure_ascii=False), len(beats), episode_id),
            )

        duration_changed = False
        for beat in beats:
            if cls._apply_resolved_beat_duration(beat):
                duration_changed = True
        if duration_changed:
            data["beats"] = beats
            execute_sql(
                "UPDATE ai_project_episodes SET data_json = %s, shots_count = %s WHERE id = %s",
                (json.dumps(data, ensure_ascii=False), len(beats), episode_id),
            )

        links = []
        for a in assets_rows:
            links.append({
                "id": f"link-{a['id']}",
                "asset_id": a["id"],
                "kind": a["kind"],
                "name": a["name"],
                "image_url": a.get("image_url") or "",
            })

        original_lines = [l for l in (ep.get("script_text") or "").split("\n") if l.strip()]

        return {
            "id": ep["id"],
            "project_id": ep["project_id"],
            "number": ep["episode_num"],
            "title": ep["title"],
            "status": ep["status"],
            "script_text": ep.get("script_text") or "",
            "content_summary": data.get("summary") or (ep.get("script_text")[:120] if ep.get("script_text") else ""),
            "shots_count": len(beats),
            "beat_count": len(beats),
            "character_count": len([l for l in links if l["kind"] == "character"]),
            "scene_count": len([l for l in links if l["kind"] == "scene"]),
            "prop_count": len([l for l in links if l["kind"] == "prop"]),
            "line_count": len(original_lines),
            "original_lines": original_lines,
            "beats": beats,
            "links": links,
            "data": data,
            "episode_video_url": data.get("episode_video_url") or "",
            "episode_video_source": data.get("episode_video_source") or "",
            "episode_video_job_id": data.get("episode_video_job_id") or "",
        }

    @classmethod
    def update_episode_beat(cls, project_id: str, episode_id: str, beat_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """更新单个分镜的数据（文案、提示词、绑定资产、草图与视频等）"""
        detail = cls.get_episode_detail(project_id, episode_id)
        beats = detail.get("beats") or []
        allowed_fields = [
            "heading", "speaker", "dialogue", "action", "camera", "scene", "scene_id", "time_of_day",
            "characters", "character_ids", "character_look_id", "character_look_ids", "props", "prop_ids", "visual_prompt", "sketch_prompt",
            "sketch_url", "sketch_job_id", "render_url", "render_prompt",
            "render_job_id", "render_status", "video_url", "upscaled_video_url", "video_take_id", "video_takes",
            "video_prompt_zh", "video_duration", "status", "workshop_prompt_document",
            "h3_prompt", "h3_prompt_source", "dialogue_turns", "visible_text",
            "parent_beat_id", "take_role", "story_shot", "merge_as_one", "take_source",
            "triptych_url", "triptych_panels", "triptych_job_id", "triptych_prompt", "triptych_status",
            "timestamped_zh_prompt",
            "vision_status", "vision_model", "vision_image_count", "vision_source",
            "authored_en_valid",
        ]
        updates = {key: payload[key] for key in allowed_fields if key in payload}
        if updates.get("workshop_prompt_document") is not None:
            updates.update(normalize_workshop_prompt(updates["workshop_prompt_document"], cls.list_assets(project_id)))
        target = cls._update_episode_beat_atomic(
            project_id,
            episode_id,
            beat_id,
            updates,
            initial_beats=beats,
        )
        return {"status": "ok", "beat": target}

    @classmethod
    def _update_episode_beat_atomic(
        cls,
        project_id: str,
        episode_id: str,
        beat_id: str,
        updates: dict[str, Any],
        *,
        initial_beats: list[dict[str, Any]] | None = None,
        completed_job: dict[str, Any] | None = None,
        expected_job_id: str | None = None,
        expected_job_field: str | None = None,
        expected_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Lock the episode briefly and merge only one beat into the latest JSON."""
        ts = now_str()
        with transaction_cursor() as cursor:
            cursor.execute(
                "SELECT data_json FROM ai_project_episodes WHERE id = %s AND project_id = %s FOR UPDATE",
                (episode_id, project_id),
            )
            episode_row = cursor.fetchone()
            if not episode_row:
                raise ValueError("分集不存在")

            try:
                data = json.loads(episode_row.get("data_json") or "{}")
            except (TypeError, json.JSONDecodeError) as err:
                raise ValueError("分集数据格式无效，无法安全回填生成结果") from err

            beats = data.get("beats") or initial_beats or []
            target = next((beat for beat in beats if beat.get("id") == beat_id), None)
            if not target:
                raise ValueError("分镜不存在")
            if expected_job_id and expected_job_field and target.get(expected_job_field) != expected_job_id:
                raise ValueError("任务结果已过期，较新的生成任务已替代该任务")
            if expected_fields is not None and any(target.get(key) != value for key, value in expected_fields.items()):
                raise BeatInputChangedError("片段已修改，保留当前正文与提示词")
            target.update(invalidate_changed_prompt(target, updates))
            data["beats"] = beats

            cursor.execute(
                "UPDATE ai_project_episodes SET data_json = %s, updated_at = %s WHERE id = %s AND project_id = %s",
                (json.dumps(data, ensure_ascii=False), ts, episode_id, project_id),
            )
            if completed_job:
                cursor.execute(
                    """
                    UPDATE ai_project_jobs
                    SET status = 'completed', progress = 100, result_url = %s, payload_json = %s,
                        error_message = NULL, completed_at = %s, updated_at = %s
                    WHERE id = %s AND project_id = %s
                    """,
                    (
                        completed_job["result_url"],
                        json.dumps(completed_job["payload"], ensure_ascii=False),
                        ts,
                        ts,
                        completed_job["id"],
                        project_id,
                    ),
                )
            return dict(target)

    @classmethod
    def delete_episode_beats(cls, project_id: str, episode_id: str, beat_ids: list[str]) -> dict[str, Any]:
        if not isinstance(beat_ids, list) or not beat_ids or any(not isinstance(item, str) or not item.strip() for item in beat_ids):
            raise ValueError("请选择要删除的片段")
        requested = {item.strip() for item in beat_ids}
        from .episode_video_service import EpisodeVideoService

        with transaction_cursor() as cursor:
            cursor.execute("SELECT data_json FROM ai_project_episodes WHERE id = %s AND project_id = %s FOR UPDATE", (episode_id, project_id))
            row = cursor.fetchone()
            if not row:
                raise ValueError("分集不存在")
            try:
                data = json.loads(row.get("data_json") or "{}")
            except (TypeError, json.JSONDecodeError) as err:
                raise ValueError("分集数据格式无效，无法安全删除片段") from err
            if not isinstance(data, dict) or not isinstance(data.get("beats"), list) or any(not isinstance(beat, dict) for beat in data["beats"]):
                raise ValueError("分集数据格式无效，无法安全删除片段")
            beats = data["beats"]
            available = {str(beat.get("id") or "") for beat in beats}
            if not requested <= available:
                raise ValueError("片段列表已变化，请刷新后重新选择")
            if len(requested) >= len(beats):
                raise ValueError("至少保留 1 个片段")

            cursor.execute("SELECT job_type, payload_json FROM ai_project_jobs WHERE project_id = %s AND status NOT IN ('completed', 'succeeded', 'failed', 'cancelled', 'canceled')", (project_id,))
            for job in cursor.fetchall() or []:
                payload = parse_job_payload(job.get("payload_json"))
                if str(payload.get("episode_id") or "") != episode_id:
                    continue
                affected = EpisodeVideoService._job_beat_ids(payload)
                if not affected or requested & affected or payload.get("render_scope") in {"episode", "compose"}:
                    raise RuntimeError("选中片段或本集正在生成，请完成后再删除")

            remaining = [beat for beat in beats if beat.get("id") not in requested]
            data["beats"] = remaining
            # The prior whole-episode result no longer represents this cut; its job and cloud file remain.
            for key in ("episode_video_url", "episode_video_source", "episode_video_job_id"):
                data.pop(key, None)
            cursor.execute("UPDATE ai_project_episodes SET data_json = %s, shots_count = %s, updated_at = %s WHERE id = %s AND project_id = %s", (json.dumps(data, ensure_ascii=False), len(remaining), now_str(), episode_id, project_id))
            return {"status": "ok", "deleted_beat_ids": [beat["id"] for beat in beats if beat.get("id") in requested], "beats": remaining}

    @classmethod
    def replace_episode_beats(
        cls,
        project_id: str,
        episode_id: str,
        beats: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ts = now_str()
        with transaction_cursor() as cursor:
            cursor.execute(
                "SELECT data_json FROM ai_project_episodes WHERE id = %s AND project_id = %s FOR UPDATE",
                (episode_id, project_id),
            )
            episode_row = cursor.fetchone()
            if not episode_row:
                raise ValueError("分集不存在")
            try:
                data = json.loads(episode_row.get("data_json") or "{}")
            except (TypeError, json.JSONDecodeError) as err:
                raise ValueError("分集数据格式无效，无法安全回填生成结果") from err
            data["beats"] = beats
            cursor.execute(
                "UPDATE ai_project_episodes SET data_json = %s, shots_count = %s, updated_at = %s "
                "WHERE id = %s AND project_id = %s",
                (json.dumps(data, ensure_ascii=False), len(beats), ts, episode_id, project_id),
            )
            return beats

    @classmethod
    def _project_visual_settings(cls, project_id: str, payload: dict[str, Any]) -> dict[str, str]:
        visual_style = str(payload.get("visual_style") or "").strip()
        ethnicity = str(payload.get("ethnicity") or "").strip()
        art_style_id = str(payload.get("art_style_id") or "").strip()
        if not visual_style:
            doc = query_one(
                "SELECT visual_style FROM ai_project_documents WHERE project_id = %s ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            )
            visual_style = str((doc or {}).get("visual_style") or "").strip()
        return {
            "visual_style": visual_style or "chinese_period_drama",
            "ethnicity": ethnicity or "Chinese",
            "art_style_id": art_style_id,
        }

    @classmethod
    def _resolve_grs_model(cls, requested_model: str) -> tuple[str, str]:
        requested = (requested_model or "").strip() or ASSET_IMAGE_DEFAULT_MODEL
        model_row = query_one(
            """
            SELECT provider_model, display_name FROM grs_image_models
            WHERE (provider_model = %s OR display_name = %s OR workflow_id = %s) AND enabled = 1
            ORDER BY is_default DESC LIMIT 1
            """,
            (requested, requested, requested),
        )
        if not model_row:
            model_row = query_one(
                "SELECT provider_model, display_name FROM grs_image_models WHERE is_default = 1 AND enabled = 1 LIMIT 1"
            )
        grs_model = (model_row["provider_model"] if model_row else None) or ASSET_IMAGE_DEFAULT_MODEL
        model_display = (model_row["display_name"] if model_row else None) or grs_model
        return grs_model, model_display

    @classmethod
    def generate_beat_h3_prompt(cls, project_id: str, episode_id: str, beat_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from .h3_prompt_job_service import H3PromptJobService
        from .h3_take_split import merge_episode_beats

        req = payload or {}
        detail = cls.get_episode_detail(project_id, episode_id)
        beats = list(detail.get("beats") or [])
        beat = next((item for item in beats if item.get("id") == beat_id), None)
        if not beat:
            raise ValueError("分镜不存在")
        target_id = beat_id
        take_ids = [beat_id]
        if req.get("merge_as_one"):
            beats, target_id = merge_episode_beats(beats, beat_id)
            cls.replace_episode_beats(project_id, episode_id, beats)
            take_ids = [target_id]
        jobs = [
            H3PromptJobService.enqueue(project_id, episode_id, take_id, req)
            for take_id in take_ids
        ]
        first = jobs[0] if jobs else {}
        result = dict(first)
        result["beat_id"] = target_id
        result["beat_ids"] = take_ids
        result["job_ids"] = [str(item.get("job_id") or "") for item in jobs if item.get("job_id")]
        result["split"] = False
        result["merged"] = bool(req.get("merge_as_one"))
        return result

    # --- 4. 全部任务 Jobs ---
    @classmethod
    def list_jobs(cls, project_id: str) -> list[dict[str, Any]]:
        with db_cursor() as cursor:
            cursor.execute(
                f"SELECT {JOB_LIST_COLUMNS} FROM ai_project_jobs WHERE project_id = %s ORDER BY updated_at DESC",
                (project_id,),
            )
            rows = list(cursor.fetchall() or [])
            payloads = [parse_job_payload(row.get("payload_json")) for row in rows]
            asset_ids = collect_infer_asset_ids(payloads)
            assets_by_id: dict[str, dict[str, Any]] = {}
            if asset_ids:
                placeholders = ",".join(["%s"] * len(asset_ids))
                cursor.execute(
                    f"SELECT id, image_url, extra_json FROM ai_project_assets WHERE id IN ({placeholders})",
                    tuple(asset_ids),
                )
                for asset in cursor.fetchall() or []:
                    assets_by_id[str(asset["id"])] = asset
        return [serialize_job_row(row, slim=True, assets_by_id=assets_by_id) for row in rows]

    @classmethod
    def get_job(cls, project_id: str, job_id: str) -> dict[str, Any] | None:
        row = query_one(
            f"SELECT {JOB_LIST_COLUMNS} FROM ai_project_jobs WHERE id = %s AND project_id = %s",
            (job_id, project_id),
        )
        if not row:
            return None
        payload = parse_job_payload(row.get("payload_json"))
        asset_ids = collect_infer_asset_ids([payload])
        assets_by_id: dict[str, dict[str, Any]] = {}
        if asset_ids:
            placeholders = ",".join(["%s"] * len(asset_ids))
            for asset in query_all(
                f"SELECT id, image_url, extra_json FROM ai_project_assets WHERE id IN ({placeholders})",
                tuple(asset_ids),
            ):
                assets_by_id[str(asset["id"])] = asset
        return serialize_job_row(row, slim=False, assets_by_id=assets_by_id)

    @classmethod
    def create_job(cls, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        jid = f"job-{uuid.uuid4().hex[:12]}"
        ts = now_str()
        execute_sql(
            """
            INSERT INTO ai_project_jobs (id, project_id, job_type, title, status, progress, result_url, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                jid,
                project_id,
                payload.get("job_type", "image_generation"),
                payload.get("title", "生成任务"),
                payload.get("status", "running"),
                payload.get("progress", 0),
                payload.get("result_url", ""),
                ts,
                ts,
            ),
        )
        return query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (jid,))

    @classmethod
    def recover_interrupted_image_jobs(cls) -> None:
        """资产形象图在请求线程内同步调图片服务：进程重启后任务行不会再有结果，
        留在 running 会一直触发助手媒体提案的 409 保护。
        已下线的镜头生图行（含三联关键帧）没有执行器，按同一条原因收口。"""
        placeholders = ", ".join("%s" for _ in _ASSET_IMAGE_ACTIVE_STATUSES)
        rows = query_all(
            f"SELECT id, payload_json FROM ai_project_jobs WHERE job_type = 'image_generation' AND status IN ({placeholders})",
            tuple(_ASSET_IMAGE_ACTIVE_STATUSES),
        )
        for row in rows:
            try:
                payload = json.loads(row.get("payload_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            message = (
                RETIRED_BEAT_IMAGE_MESSAGE
                if payload.get("target_type") in RETIRED_BEAT_IMAGE_TARGETS
                else "服务重启时生图任务已中断，请在任务中心重试。"
            )
            execute_sql(
                "UPDATE ai_project_jobs SET status = 'failed', progress = 0, error_message = %s, updated_at = %s WHERE id = %s",
                (message, now_str(), row["id"]),
            )

    @classmethod
    def _retry_asset_image(cls, project_id: str, row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        if row.get("status") in _ASSET_IMAGE_ACTIVE_STATUSES:
            raise ValueError("该生图任务仍在进行中，请等待完成后再重试")
        asset_id = str(payload.get("asset_id") or "")
        if not query_one(
            "SELECT id FROM ai_project_assets WHERE id = %s AND project_id = %s", (asset_id, project_id)
        ):
            raise ValueError("资产已不存在，请在资产库重新发起生图")
        future = _ASSET_IMAGE_EXECUTOR.submit(cls.generate_asset_image, project_id, asset_id, dict(payload))
        # 生图失败已由新任务行的 error_message 承载，取回异常只为不在子线程里静默丢弃。
        future.add_done_callback(lambda item: item.exception())
        return query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (row["id"],))

    @classmethod
    def retry_job(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one(
            "SELECT id, job_type, status, payload_json FROM ai_project_jobs WHERE id = %s AND project_id = %s",
            (job_id, project_id),
        )
        if row and row.get("job_type") == "video_generation":
            from .episode_video_service import EpisodeVideoService
            return EpisodeVideoService.retry_job(project_id, job_id)
        if row and row.get("job_type") == "h3_prompt":
            from .h3_prompt_job_service import H3PromptJobService
            return H3PromptJobService.retry(project_id, job_id)
        if row and row.get("job_type") == "shot_plan":
            from .shot_plan_job_service import ShotPlanJobService
            return ShotPlanJobService.retry(project_id, job_id)
        if row and row.get("job_type") == "tts_generation":
            from .tts_generation_job_service import TtsGenerationJobService
            return TtsGenerationJobService.retry(project_id, job_id)
        payload = json.loads((row or {}).get("payload_json") or "{}")
        if payload.get("target_type") in RETIRED_BEAT_IMAGE_TARGETS:
            raise ValueError(RETIRED_BEAT_IMAGE_MESSAGE)
        if payload.get("asset_id"):
            return cls._retry_asset_image(project_id, row or {}, payload)
        ts = now_str()
        execute_sql(
            "UPDATE ai_project_jobs SET status = 'running', progress = 10, error_message = NULL, updated_at = %s WHERE id = %s AND project_id = %s",
            (ts, job_id, project_id),
        )
        return query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (job_id,))
