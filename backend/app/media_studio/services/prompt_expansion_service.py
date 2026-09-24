from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import threading
import time
import unicodedata
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from ...dialogue_timing import resolve_shot_duration_sec
from ...director_stream import DirectorOperationEventBus
from ...llm_client import LlmStreamHook, emit_llm_stream_status
from ...workflow_registry import WorkflowDefinition, workflow_for
from ..db import execute_sql, now_str, query_all, query_one, transaction_cursor
from .llm_service import LlmService
from . import director_reliable
from .director_plan_quality import content_digest, improve_plan, preflight
from .prompt_templates import (
    DIRECTOR_TEMPLATE_VERSION,
    DIRECTOR_UNIT_PLANNER_VERSION,
    FULL_REFERENCE_TEMPLATE_VERSION,
    PromptTemplateError,
    build_director_prompts,
    build_director_unit_planning_prompts,
    build_full_reference_prompts,
    normalize_language,
    parse_director_creative_output,
    parse_director_output,
    parse_director_unit_plan,
    parse_full_reference,
)


JOB_TYPE = "prompt_expansion"
_FPS = 24
_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="prompt-expansion")
_DISPATCH_LOCK = threading.Lock()
_ACTIVE: set[str] = set()
_ACTIVE_LOCK = threading.Lock()
_EVENTS = DirectorOperationEventBus()
_STREAM_LOCK = threading.Lock()
_STREAM_STATE: dict[str, dict[str, Any]] = {}
_STREAM_FLUSH_AT: dict[str, float] = {}
_STREAM_FLUSH_INTERVAL = 0.45
_DIRECTOR_PLAN_SCHEMA_VERSION = 4
_DIRECTOR_REPLAY_TERMS = (
    "再次", "重新", "回响", "时间回响", "感知回响", "回放", "倒放", "重演", "重新醒来", "再次醒来", "再次说", "再次重复",
    "time echo", "sensory echo", "replay", "rewind", "relive", "again wakes", "repeat the dialogue",
)


class PromptPipelineError(PromptTemplateError):
    """A recoverable Director pipeline failure with a stable public envelope."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        stage: str,
        part_id: str = "",
        segment_ids: list[str] | None = None,
        attempt: int = 0,
        retryable: bool = True,
        user_message: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.part_id = part_id
        self.segment_ids = segment_ids or []
        self.attempt = attempt
        self.retryable = retryable
        self.user_message = user_message or message

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "part_id": self.part_id or None,
            "segment_ids": self.segment_ids,
            "attempt": self.attempt,
            "retryable": self.retryable,
            "message": self.user_message,
            "detail": str(self),
        }


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("payload_json")
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _shot_number(value: Any, fallback: int) -> int:
    match = re.search(r"\d+", _clean(value))
    return int(match.group(0)) if match else fallback


class PromptExpansionService:
    """Preview-first Prompt Master authoring for the director workshop."""

    @classmethod
    def enqueue(cls, project_id: str, episode_id: str, request: dict[str, Any] | None = None) -> dict[str, Any]:
        req = dict(request or {})
        source = cls._load_source(project_id, episode_id)
        from .script_parser import StandardScriptParser
        if StandardScriptParser.is_line_fallback(source["episode"].get("script_text") or "", source["beats"]):
            raise ValueError("当前镜头由旧版按剧本文本行初始化，请先在镜头页按剧本结构恢复镜头，再优化提示词")
        workflow_id = _clean(req.get("workflow_id"))
        if not workflow_id:
            raise ValueError("请选择视频工作流")
        definition = workflow_for(workflow_id)
        profile = str(definition.prompt_profile or "none")
        target = req.get("target") if isinstance(req.get("target"), dict) else {}
        target_kind = _clean(target.get("kind"))
        if profile == "full_reference" and target_kind != "beat":
            raise ValueError("当前工作流只能针对单个分镜生成六段式提示词")
        if profile == "director_segments" and target_kind != "director_episode":
            raise ValueError("当前 Director 工作流必须生成整集 Director 出片方案")
        if profile not in {"full_reference", "director_segments"}:
            raise ValueError("当前工作流未启用 H3 提示词模板")

        beat_id = _clean(target.get("beat_id"))
        if target_kind == "beat" and not any(_clean(item.get("id")) == beat_id for item in source["beats"]):
            raise ValueError("分镜不存在")
        language = normalize_language(req.get("language"))
        rewrite_mode = _clean(req.get("rewrite_mode")) or ("strict" if profile == "full_reference" else "expand")
        if rewrite_mode not in {"strict", "expand"}:
            raise ValueError("改写模式必须是 strict 或 expand")
        aspect_ratio = _clean(req.get("aspect_ratio")) or "16:9"
        slots = cls._normalize_reference_slots(
            req.get("reference_slots"), source["assets"], definition,
            target_kind=target_kind, beat_id=beat_id, beats=source["beats"],
        )
        target_segment_count = None
        planned_parts: list[dict[str, Any]] = []
        source_facts: dict[str, dict[str, list[dict[str, str]]]] = {}
        if profile == "director_segments":
            raw_count = req.get("target_segment_count")
            target_segment_count = int(raw_count) if raw_count not in (None, "") else None
            if not source["beats"]:
                raise ValueError("当前分集没有可规划的分镜")
            source_facts = cls._build_source_facts(source["beats"])
            conflicts = preflight(source["beats"], source_facts, definition)
            if director_reliable.enabled():
                conflicts = [c for c in conflicts if c["code"] != "SINGLE_UNIT_SCENE"]
            if conflicts:
                raise PromptPipelineError(
                    "\n".join(f"{x['beat_id']}：{x['evidence']} {x['suggestion']}" for x in conflicts),
                    code="DIRECTOR_PREFLIGHT_CONFLICT", stage="preflight", retryable=False,
                    user_message="当前分镜无法满足 Director 要求，请先调整分镜或改用逐镜生成。",
                )

        normalized_request = {
            "pipeline_version": 5 if profile == "director_segments" and director_reliable.enabled() else 4,
            "story_design": profile == "director_segments",
            "workflow_id": workflow_id,
            "prompt_profile": profile,
            "template_version": FULL_REFERENCE_TEMPLATE_VERSION if profile == "full_reference" else DIRECTOR_TEMPLATE_VERSION,
            "unit_planner_version": DIRECTOR_UNIT_PLANNER_VERSION if profile == "director_segments" else None,
            "target": {"kind": target_kind, **({"beat_id": beat_id} if beat_id else {})},
            "language": language,
            "rewrite_mode": rewrite_mode,
            "aspect_ratio": aspect_ratio,
            "target_segment_count": target_segment_count,
            "reference_slots": slots,
        }
        fingerprint = cls.source_fingerprint(source, normalized_request)
        for row in query_all(
            "SELECT id,status,payload_json FROM ai_project_jobs WHERE project_id=%s AND job_type=%s "
            "AND status IN ('queued','preparing','running') ORDER BY created_at DESC",
            (project_id, JOB_TYPE),
        ):
            existing = _payload(row)
            if existing.get("episode_id") == episode_id and existing.get("source_fingerprint") == fingerprint and not existing.get("revision_request"):
                return {"job_id": row["id"], "status": row["status"], "duplicate": True}

        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        title_prefix = "六段式提示词预览" if profile == "full_reference" else "Director 出片方案预览"
        job_payload = {
            "target_type": "prompt_preview",
            "project_id": project_id,
            "episode_id": episode_id,
            "beat_id": beat_id or None,
            "prompt_profile": profile,
            "template_version": normalized_request["template_version"],
            "source_fingerprint": fingerprint,
            "reference_urls": [item["image_url"] for item in slots if item.get("image_url")],
            "request": normalized_request,
            "source_snapshot": cls._source_snapshot(source, target_kind, beat_id),
            "source_facts": source_facts,
            "planned_parts": planned_parts,
            "checkpoints": {},
            "validation_status": "pending",
        }
        execute_sql(
            "INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,'queued',0,NULL,%s,%s,%s)",
            (
                jid, project_id, JOB_TYPE,
                f"{title_prefix} · {source['episode'].get('title') or episode_id}",
                json.dumps(job_payload, ensure_ascii=False), timestamp, timestamp,
            ),
        )
        cls.kick()
        return {
            "job_id": jid,
            "status": "queued",
            "source_fingerprint": fingerprint,
            "prompt_profile": profile,
            "recommended_segment_count": target_segment_count,
        }

    @classmethod
    def revise(cls, project_id: str, episode_id: str, request: dict[str, Any]) -> dict[str, Any]:
        """Create a preview revision from a server-owned plan, never overwrite it."""
        source = cls._load_source(project_id, episode_id)
        saved = ((source.get("data") or {}).get("prompt_authoring") or {}).get("director_plan")
        base_job_id = _clean(request.get("base_job_id"))
        if base_job_id:
            row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (base_job_id, project_id)) or {}
            old = _payload(row)
            if row.get("job_type") != JOB_TYPE or row.get("status") not in {"completed", "succeeded"} or old.get("episode_id") != episode_id:
                raise ValueError("返修来源不是本集已完成的方案预览")
            plan = old.get("preview")
        else:
            plan = saved
        if not isinstance(plan, dict) or plan.get("kind") != "director_segments" or not plan.get("director_design"):
            raise ValueError("请先生成新版 Director 方案再返修")
        if request.get("expected_plan_id") != plan.get("id") or int(request.get("expected_revision") or 0) != int(plan.get("revision") or 0):
            raise RuntimeError("REVISION_CONFLICT: 返修来源版本已变化，请刷新方案")
        cls.validate_director_plan(plan)
        feedback = _clean(request.get("feedback"))
        if len(feedback) > 4000:
            raise ValueError("修改意见不能超过 4000 字")
        ids = [s["id"] for p in plan["parts"] for s in p["segments"]]
        targets = request.get("segment_ids")
        if not isinstance(targets, list) or any(not isinstance(x, str) or x not in ids for x in targets) or len(targets) != len(set(targets)):
            raise ValueError("返修段落选择无效")
        if feedback and not targets:
            raise ValueError("请指定需要返修的段落")
        req = {k: plan.get(k) for k in ("workflow_id", "template_version", "unit_planner_version", "language", "rewrite_mode", "aspect_ratio", "target_segment_count", "reference_slots")}
        req.update(story_design=True, prompt_profile="director_segments", target={"kind": "director_episode"})
        fingerprint = cls.source_fingerprint(source, req)
        if fingerprint != plan.get("source_fingerprint"):
            raise RuntimeError("SOURCE_CHANGED: 剧本、分镜或资产已变化，请重新生成方案")
        revision_request = {"feedback": feedback, "segment_ids": targets, "base_plan_digest": content_digest(plan),
                            "base_job_id": base_job_id, "saved_base_digest": content_digest(saved)}
        for row in query_all("SELECT id,status,payload_json FROM ai_project_jobs WHERE project_id=%s AND job_type=%s AND status IN ('queued','preparing','running')", (project_id, JOB_TYPE)):
            active = _payload(row)
            if active.get("episode_id") == episode_id and active.get("revision_request") == revision_request and active.get("source_fingerprint") == fingerprint:
                return {"job_id": row["id"], "status": row["status"], "duplicate": True}
        jid, timestamp = f"job-{uuid.uuid4().hex[:12]}", now_str()
        payload = {"target_type": "prompt_preview", "project_id": project_id, "episode_id": episode_id,
                   "prompt_profile": "director_segments", "template_version": req["template_version"], "request": req,
                   "source_fingerprint": fingerprint, "source_snapshot": cls._source_snapshot(source, "director_episode", ""),
                   "revision_request": revision_request, "revision_base": plan, "checkpoints": {}, "validation_status": "pending"}
        execute_sql("INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at) VALUES (%s,%s,%s,%s,'queued',0,NULL,%s,%s,%s)",
                    (jid, project_id, JOB_TYPE, "Director 方案返修" if feedback else "Director 方案重新审稿", json.dumps(payload, ensure_ascii=False), timestamp, timestamp))
        cls.kick()
        return {"job_id": jid, "status": "queued"}

    @classmethod
    def _load_source(cls, project_id: str, episode_id: str) -> dict[str, Any]:
        from .project_detail_service import ProjectDetailService

        row = query_one("SELECT * FROM ai_project_episodes WHERE id=%s AND project_id=%s", (episode_id, project_id))
        if not row:
            raise ValueError("分集不存在")
        data = _json_dict(row.get("data_json"))
        if data.get("script_stale"):
            raise ValueError("已采纳新剧本，请先重新规划镜头并同步至工坊")
        beats = data.get("beats") if isinstance(data.get("beats"), list) else []
        if not beats:
            detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
            row = query_one("SELECT * FROM ai_project_episodes WHERE id=%s AND project_id=%s", (episode_id, project_id)) or row
            data = _json_dict(row.get("data_json"))
            beats = detail.get("beats") if isinstance(detail.get("beats"), list) else []
        return {
            "episode": dict(row),
            "data": data,
            "beats": beats,
            "assets": ProjectDetailService.list_assets(project_id),
            "adjacent_episodes": query_all("SELECT episode_num,title,script_text FROM ai_project_episodes WHERE project_id=%s AND episode_num IN (%s,%s)",
                                           (project_id, int(row.get("episode_num") or 1) - 1, int(row.get("episode_num") or 1) + 1)),
        }

    @staticmethod
    def _asset_image_url(asset: dict[str, Any], look_id: str = "") -> str:
        extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else _json_dict(asset.get("extra_json"))
        if look_id:
            for look in (extra.get("identities") or extra.get("looks") or []):
                if isinstance(look, dict) and _clean(look.get("id")) == look_id:
                    return _clean(look.get("image_url") or look.get("url"))
        return _clean(
            extra.get("master_url") or extra.get("reference_url") or extra.get("image_url")
            or extra.get("avatar_url") or asset.get("image_url")
        )

    @classmethod
    def _default_asset_order(
        cls,
        assets: list[dict[str, Any]],
        *,
        target_kind: str,
        beat_id: str,
        beats: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        target_beats = beats if target_kind == "director_episode" else [
            item for item in beats if _clean(item.get("id")) == beat_id
        ]
        linked: list[str] = []
        for beat in target_beats:
            linked.extend(_clean(value) for value in beat.get("character_ids") or [])
            if beat.get("scene_id"):
                linked.append(_clean(beat.get("scene_id")))
            linked.extend(_clean(value) for value in beat.get("prop_ids") or [])
        linked_rank = {value: idx for idx, value in enumerate(dict.fromkeys(value for value in linked if value))}
        kind_rank = {"character": 0, "scene": 1, "prop": 2}
        return sorted(
            assets,
            key=lambda item: (
                0 if _clean(item.get("id")) in linked_rank else 1,
                linked_rank.get(_clean(item.get("id")), 9999),
                kind_rank.get(_clean(item.get("kind")), 9),
                _clean(item.get("name")),
            ),
        )

    @classmethod
    def _normalize_reference_slots(
        cls,
        raw_slots: Any,
        assets: list[dict[str, Any]],
        definition: WorkflowDefinition,
        *,
        target_kind: str,
        beat_id: str,
        beats: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        assets_by_id = {_clean(item.get("id")): item for item in assets if item.get("id")}
        candidates = raw_slots if isinstance(raw_slots, list) else []
        if not candidates:
            candidates = [
                {"asset_id": item.get("id")}
                for item in cls._default_asset_order(
                    assets, target_kind=target_kind, beat_id=beat_id, beats=beats,
                )
                if cls._asset_image_url(item)
            ][: int(definition.max_references or 0)]
        if len(candidates) > int(definition.max_references or 0):
            raise ValueError(f"参考图最多允许 {definition.max_references} 张")
        slots: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for idx, item in enumerate(candidates, start=1):
            if not isinstance(item, dict):
                raise ValueError("参考图槽位格式无效")
            asset_id = _clean(item.get("asset_id"))
            look_id = _clean(item.get("look_id"))
            asset = assets_by_id.get(asset_id)
            if not asset:
                raise ValueError(f"参考资产不存在或不属于当前项目：{asset_id}")
            if (asset_id, look_id) in seen:
                raise ValueError("同一个参考资产造型不能重复绑定")
            seen.add((asset_id, look_id))
            image_url = cls._asset_image_url(asset, look_id)
            if not image_url:
                raise ValueError(f"资产“{asset.get('name') or asset_id}”没有可用参考图")
            token = _clean(item.get("token")) or f"<Picture {idx}>"
            if token.lower() not in {f"<picture {idx}>", f"<subject {idx}>"}:
                raise ValueError("参考槽位 token 必须与当前排序序号一致")
            slots.append({
                "index": idx,
                "token": token,
                "asset_id": asset_id,
                "look_id": look_id or None,
                "image_url": image_url,
                "kind": _clean(asset.get("kind")) or "asset",
                "name": _clean(item.get("name") or asset.get("name")) or f"参考图 {idx}",
            })
        if len(slots) < int(definition.min_references or 0):
            raise ValueError(f"当前工作流至少需要 {definition.min_references} 张参考图")
        return slots

    @staticmethod
    def _source_snapshot(source: dict[str, Any], target_kind: str, beat_id: str) -> dict[str, Any]:
        episode = source["episode"]
        selected = source["beats"] if target_kind == "director_episode" else [
            item for item in source["beats"] if _clean(item.get("id")) == beat_id
        ]
        beat_fields = (
            "id", "sequence", "story_shot", "heading", "scene", "action", "camera", "dialogue",
            "speaker", "visual_prompt", "audio", "video_duration", "character_ids", "scene_id", "prop_ids",
            "opening_state", "closing_state", "transition_note",
        )
        return {
            "episode": {"id": episode.get("id"), "title": episode.get("title"), "script_text": episode.get("script_text") or "",
                        "dramatic_design": (source.get("data") or {}).get("dramatic_design"), "script_revision": (source.get("data") or {}).get("script_revision")},
            "adjacent_episodes": sorted(source.get("adjacent_episodes") or [], key=lambda item: int(item.get("episode_num") or 0)) if target_kind == "director_episode" else [],
            "beats": [{key: beat.get(key) for key in beat_fields} for beat in selected],
            "assets": [
                {
                    "id": item.get("id"), "kind": item.get("kind"), "name": item.get("name"),
                    "description": item.get("description"), "visual_prompt": item.get("visual_prompt"),
                    "image_url": item.get("image_url"),
                    "extra": {key: value for key, value in (item.get("extra") or _json_dict(item.get("extra_json"))).items()
                              if key not in {"voice", "voice_id"}},
                }
                for item in sorted(source["assets"], key=lambda asset: str(asset.get("id") or ""))
            ],
        }

    @classmethod
    def source_fingerprint(cls, source: dict[str, Any], request: dict[str, Any]) -> str:
        target = request.get("target") if isinstance(request.get("target"), dict) else {}
        body = {
            "template_version": request.get("template_version"),
            "unit_planner_version": request.get("unit_planner_version"),
            "workflow_id": request.get("workflow_id"),
            "language": request.get("language"), "rewrite_mode": request.get("rewrite_mode"),
            "aspect_ratio": request.get("aspect_ratio"), "target_segment_count": request.get("target_segment_count"),
            "reference_slots": request.get("reference_slots") or [],
            "source": cls._source_snapshot(source, _clean(target.get("kind")), _clean(target.get("beat_id"))),
        }
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def recommended_segment_count(cls, beats: list[dict[str, Any]], definition: WorkflowDefinition) -> int:
        max_segments = int(definition.max_segments or 6)
        max_frames = int(definition.max_total_frames or 1152)
        preferred = max(1, max_frames // max_segments)
        total_frames = sum(max(1, round(resolve_shot_duration_sec(item) * _FPS)) for item in beats) or preferred * 2
        return max(2, math.ceil(total_frames / preferred))

    @classmethod
    def plan_director_parts(
        cls,
        beats: list[dict[str, Any]],
        definition: WorkflowDefinition,
        requested_count: int | None,
    ) -> list[dict[str, Any]]:
        if not beats:
            raise ValueError("当前分集没有可用于连续剧情的分镜")
        max_segments = int(definition.max_segments or 6)
        max_frames = int(definition.max_total_frames or 1152)
        preferred = max(1, max_frames // max_segments)
        total_frames = sum(max(1, round(resolve_shot_duration_sec(item) * _FPS)) for item in beats)
        count = int(requested_count or cls.recommended_segment_count(beats, definition))
        if count < 2:
            raise ValueError("Director 方案至少需要 2 段")
        part_count = max(math.ceil(count / max_segments), math.ceil(total_frames / max_frames), 1)
        count = max(count, part_count * 2)
        part_count = max(part_count, math.ceil(count / max_segments))

        units: list[dict[str, Any]] = []
        generated_shot_number = 1
        for seq, beat in enumerate(beats, start=1):
            frames = max(1, round(resolve_shot_duration_sec(beat) * _FPS))
            split_count = max(1, math.ceil(frames / preferred))
            base, remainder = divmod(frames, split_count)
            start_frame = 0
            source_shot_number = _shot_number(beat.get("story_shot") or beat.get("sequence"), seq)
            for chunk in range(split_count):
                chunk_frames = base + (1 if chunk < remainder else 0)
                units.append({
                    "id": f"unit-{seq}-{chunk + 1}",
                    "source_beat_id": _clean(beat.get("id")),
                    "source_shot_number": source_shot_number,
                    "generated_shot_number": generated_shot_number,
                    "chunk_index": chunk,
                    "chunk_count": split_count,
                    "start_frame": start_frame,
                    "end_frame": start_frame + chunk_frames,
                    "frames": chunk_frames,
                })
                generated_shot_number += 1
                start_frame += chunk_frames
        while len(units) < count:
            pos = max(range(len(units)), key=lambda index: units[index]["frames"])
            item = units[pos]
            if item["frames"] < 2:
                raise ValueError("Director 目标段数超过可安全拆分的动作单元数量")
            left = max(1, item["frames"] // 2)
            right = item["frames"] - left
            units[pos:pos + 1] = [
                {
                    **item,
                    "id": f"{item['id']}-a",
                    "end_frame": item["start_frame"] + left,
                    "frames": left,
                },
                {
                    **item,
                    "id": f"{item['id']}-b",
                    "start_frame": item["start_frame"] + left,
                    "end_frame": item["end_frame"],
                    "frames": right,
                },
            ]

        by_beat: dict[str, list[dict[str, Any]]] = {}
        for generated_number, item in enumerate(units, start=1):
            item["generated_shot_number"] = generated_number
            by_beat.setdefault(item["source_beat_id"], []).append(item)
        for beat_units in by_beat.values():
            beat_units.sort(key=lambda item: (item["start_frame"], item["end_frame"], item["id"]))
            for chunk_index, item in enumerate(beat_units):
                item["chunk_index"] = chunk_index
                item["chunk_count"] = len(beat_units)
                item["unit_id"] = item["id"]

        segment_units: list[list[dict[str, Any]]] = []
        offset = 0
        remaining_frames = sum(item["frames"] for item in units)
        for segment_index in range(count):
            remaining_segments = count - segment_index
            remaining_units = len(units) - offset
            take = 1
            target_frames = remaining_frames / remaining_segments
            current = units[offset]["frames"]
            while take < remaining_units - (remaining_segments - 1):
                next_frames = units[offset + take]["frames"]
                if current + next_frames > target_frames:
                    break
                current += next_frames
                take += 1
            selected = units[offset:offset + take]
            segment_units.append(selected)
            remaining_frames -= sum(item["frames"] for item in selected)
            offset += take

        base_count, remainder = divmod(count, part_count)
        part_counts = [base_count + (1 if index < remainder else 0) for index in range(part_count)]
        if any(value < 2 or value > max_segments for value in part_counts):
            raise ValueError("无法在当前工作流能力内生成合法的 Director Part")
        parts: list[dict[str, Any]] = []
        cursor = 0
        for part_index, segment_count in enumerate(part_counts, start=1):
            segments = []
            for local_index in range(segment_count):
                selected = segment_units[cursor]
                frame_count = sum(item["frames"] for item in selected)
                source_ids = list(dict.fromkeys(item["source_beat_id"] for item in selected if item.get("source_beat_id")))
                source_units = []
                for item in selected:
                    source_units.append({
                        "id": item["id"],
                        "source_beat_id": item["source_beat_id"],
                        "source_shot_number": item["source_shot_number"],
                        "generated_shot_number": item["generated_shot_number"],
                        "chunk_index": item["chunk_index"],
                        "chunk_count": item["chunk_count"],
                        "start_sec": round(item["start_frame"] / _FPS, 3),
                        "end_sec": round(item["end_frame"] / _FPS, 3),
                        "duration_seconds": round(item["frames"] / _FPS, 3),
                        "event_ids": [],
                        "dialogue_ids": [],
                        "event_refs": [],
                        "dialogue_refs": [],
                        "required_events": [],
                        "dialogue_owner": [],
                        "start_state": "",
                        "handoff_state": "",
                    })
                segments.append({
                    "id": f"segment-{uuid.uuid4().hex[:12]}", "index": local_index + 1,
                    "title": f"Part {part_index} · 段 {local_index + 1}", "frame_count": frame_count,
                    "duration_seconds": round(frame_count / _FPS, 3), "source_beat_ids": source_ids,
                    "source_units": source_units,
                })
                cursor += 1
            frame_count = sum(item["frame_count"] for item in segments)
            if frame_count > max_frames:
                raise ValueError("建议段数过少，单个 Director Part 超过工作流总帧上限")
            parts.append({
                "id": f"part-{uuid.uuid4().hex[:12]}", "index": part_index,
                "frame_count": frame_count, "segments": segments,
            })
        return parts

    @classmethod
    def bind_loop(cls) -> None:
        try:
            _EVENTS.bind_loop()
        except RuntimeError:
            pass

    @classmethod
    async def stream(cls, job_id: str, project_id: str, request: Any, since: int = 0):
        cls.bind_loop()
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (job_id, project_id)) or {}
        if not row or row.get("job_type") != JOB_TYPE:
            raise ValueError("提示词预览任务不存在")
        queue, replay = _EVENTS.subscribe(job_id, since=max(0, since))
        try:
            if not replay:
                snapshot = cls._public_stream_snapshot(row)
                if snapshot:
                    yield snapshot
                    if snapshot.get("terminal"):
                        return
            for event in replay:
                yield event
                if event.get("terminal"):
                    return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    current = query_one(
                        "SELECT status,error_message,payload_json FROM ai_project_jobs WHERE id=%s AND project_id=%s",
                        (job_id, project_id),
                    ) or {}
                    if current.get("status") in {"completed", "succeeded", "failed"}:
                        yield cls._terminal_from_row(current)
                        return
                    yield {"event": "keep-alive", "data": {}}
                    continue
                if event is None:
                    return
                yield event
                if event.get("terminal"):
                    return
        finally:
            _EVENTS.unsubscribe(job_id, queue)

    @classmethod
    def _public_stream_snapshot(cls, row: dict[str, Any]) -> dict[str, Any]:
        if row.get("status") in {"completed", "succeeded", "failed"}:
            return cls._terminal_from_row(row)
        stream = _payload(row).get("stream")
        stream = stream if isinstance(stream, dict) else {}
        return {
            "event": "status",
            "data": {
                "phase": stream.get("phase") or "write",
                "message": stream.get("message") or "正在生成提示词预览",
                "reset": False,
                "reasoning": stream.get("reasoning") or "",
                "text": stream.get("text") or "",
            },
        }

    @staticmethod
    def _terminal_from_row(row: dict[str, Any]) -> dict[str, Any]:
        if row.get("status") == "failed":
            failure = _payload(row).get("failure")
            if not isinstance(failure, dict):
                failure = {
                    "code": "PROMPT_PREVIEW_FAILED",
                    "stage": "generation",
                    "part_id": None,
                    "segment_ids": [],
                    "attempt": 0,
                    "retryable": True,
                    "message": _clean(row.get("error_message")) or "提示词预览生成失败，可重试",
                }
            return {"event": "error", "terminal": True, "data": {"status": "failed", **failure}}
        return {
            "event": "done", "terminal": True,
            "data": {"status": "succeeded", "preview": _payload(row).get("preview")},
        }

    @classmethod
    def _patch_stream(cls, job_id: str, updates: dict[str, Any], *, force: bool = False) -> None:
        with _STREAM_LOCK:
            state = _STREAM_STATE.setdefault(
                job_id,
                {"phase": "write", "message": "正在生成提示词预览", "reasoning": "", "text": ""},
            )
            if updates.get("reset"):
                state["reasoning"] = ""
                state["text"] = ""
            for key in ("code", "phase", "stage", "part_id", "segment_ids", "attempt", "retryable", "message", "reasoning", "text"):
                if key in updates and updates[key] is not None:
                    state[key] = updates[key]
            current_time = time.monotonic()
            if not force and current_time - (_STREAM_FLUSH_AT.get(job_id) or 0.0) < _STREAM_FLUSH_INTERVAL:
                return
            _STREAM_FLUSH_AT[job_id] = current_time
            snapshot = dict(state)
        row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        payload = _payload(row)
        payload["stream"] = snapshot
        execute_sql(
            "UPDATE ai_project_jobs SET payload_json=%s,updated_at=%s WHERE id=%s",
            (json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )

    @classmethod
    def kick(cls) -> None:
        if not _DISPATCH_LOCK.acquire(blocking=False):
            return
        try:
            with _ACTIVE_LOCK:
                capacity = max(0, 3 - len(_ACTIVE))
            if not capacity:
                return
            rows = query_all(
                "SELECT id FROM ai_project_jobs WHERE job_type=%s AND status='queued' ORDER BY created_at ASC LIMIT 20",
                (JOB_TYPE,),
            )
            for row in rows:
                if capacity <= 0:
                    break
                job_id = row["id"]
                if execute_sql(
                    "UPDATE ai_project_jobs SET status='preparing',progress=10,updated_at=%s WHERE id=%s AND status='queued'",
                    (now_str(), job_id),
                ) != 1:
                    continue
                with _ACTIVE_LOCK:
                    _ACTIVE.add(job_id)
                _EXECUTOR.submit(cls._run, job_id)
                capacity -= 1
        finally:
            _DISPATCH_LOCK.release()

    @classmethod
    def recover_interrupted_jobs(cls) -> None:
        for row in query_all(
            "SELECT id,status,payload_json FROM ai_project_jobs WHERE job_type=%s AND status IN ('queued','preparing','running')",
            (JOB_TYPE,),
        ):
            if row.get("status") == "queued":
                continue
            payload = _payload(row)
            request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
            stage = "generation"
            part_id = None
            segment_ids: list[str] = []
            if request.get("prompt_profile") == "director_segments":
                checkpoints = payload.get("checkpoints") if isinstance(payload.get("checkpoints"), dict) else {}
                planning = checkpoints.get("fact_planning") if isinstance(checkpoints.get("fact_planning"), dict) else {}
                if planning.get("status") != "completed":
                    stage = "fact_planning"
                else:
                    completed = checkpoints.get("part_generation") if isinstance(checkpoints.get("part_generation"), dict) else {}
                    parts = planning.get("planned_parts") if isinstance(planning.get("planned_parts"), list) else []
                    next_part = next((part for part in parts if (completed.get(part.get("id")) or {}).get("status") != "completed"), None)
                    if next_part:
                        stage = "part_generation"
                        part_id = str(next_part.get("id") or "") or None
                        segment_ids = [str(item.get("id") or "") for item in next_part.get("segments") or []]
                    else:
                        stage = "final_validation"
            payload["failure"] = {
                "code": "PROMPT_PREVIEW_INTERRUPTED",
                "stage": stage,
                "part_id": part_id,
                "segment_ids": segment_ids,
                "attempt": 0,
                "retryable": True,
                "message": "服务重启中断了预览，可重试失败部分。" if request.get("prompt_profile") == "director_segments" else "服务重启中断了预览，请重试。",
                "detail": "服务重启时提示词预览任务已中断",
            }
            payload["validation_status"] = "invalid"
            payload.pop("stream", None)
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,payload_json=%s,updated_at=%s WHERE id=%s",
                ("服务重启时提示词预览任务已中断，请重试。", json.dumps(payload, ensure_ascii=False), now_str(), row["id"]),
            )
        cls.kick()

    @classmethod
    def retry(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (job_id, project_id)) or {}
        if not row or row.get("job_type") != JOB_TYPE:
            raise ValueError("提示词预览任务不存在")
        if row.get("status") not in {"failed", "completed", "succeeded"}:
            raise ValueError("只有失败或已完成的任务可以重试")
        payload = _payload(row)
        if (payload.get("failure") or {}).get("retryable") is False:
            raise ValueError("该问题不能通过重复尝试解决，请按问题说明调整后重新生成")
        request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        if request.get("prompt_profile") != "director_segments" or not payload.get("failure"):
            return cls.enqueue(project_id, payload["episode_id"], request)
        source = cls._load_source(project_id, payload["episode_id"])
        current_fingerprint = cls.source_fingerprint(source, request)
        if current_fingerprint != payload.get("source_fingerprint"):
            raise RuntimeError("SOURCE_CHANGED: 剧本、分镜、资产或工作流已变化，请重新生成全部")

        old_checkpoints = payload.get("checkpoints") if isinstance(payload.get("checkpoints"), dict) else {}
        reusable: dict[str, Any] = {}
        if old_checkpoints.get("quality_revision"):
            reusable["quality_revision"] = old_checkpoints["quality_revision"]
        planning = old_checkpoints.get("fact_planning") if isinstance(old_checkpoints.get("fact_planning"), dict) else None
        if planning and planning.get("status") == "completed":
            reusable["fact_planning"] = planning
        part_rows = old_checkpoints.get("part_generation") if isinstance(old_checkpoints.get("part_generation"), dict) else {}
        failed_part_id = _clean((payload.get("failure") or {}).get("part_id")) if isinstance(payload.get("failure"), dict) else ""
        reusable_parts = {
            key: value for key, value in part_rows.items()
            if isinstance(value, dict) and value.get("status") == "completed" and key != failed_part_id
        }
        if reusable_parts:
            reusable["part_generation"] = reusable_parts

        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        new_payload = {
            **payload,
            "source_snapshot": cls._source_snapshot(source, "director_episode", ""),
            "checkpoints": reusable,
            "failure": None,
            "validation_status": "pending",
            "resumed_from_job_id": job_id,
        }
        for key in ("preview", "stream", "applied_at"):
            new_payload.pop(key, None)
        execute_sql(
            "INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,'queued',0,NULL,%s,%s,%s)",
            (
                jid, project_id, JOB_TYPE, row.get("title") or "Director 出片方案预览",
                json.dumps(new_payload, ensure_ascii=False), timestamp, timestamp,
            ),
        )
        cls.kick()
        return {"job_id": jid, "status": "queued", "resumed_from_job_id": job_id, "resumed": True}

    @classmethod
    def _save_checkpoint(
        cls,
        job_id: str,
        payload: dict[str, Any],
        stage: str,
        value: Any,
    ) -> None:
        checkpoints = payload.setdefault("checkpoints", {})
        checkpoints[stage] = value
        if not job_id:
            return
        latest = _payload(query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {})
        stream = latest.get("stream")
        merged = {**latest, **payload}
        if stream and "stream" not in payload:
            merged["stream"] = stream
        payload.clear()
        payload.update(merged)
        execute_sql(
            "UPDATE ai_project_jobs SET payload_json=%s,updated_at=%s WHERE id=%s",
            (json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )

    @classmethod
    def _generate_with_one_retry(
        cls,
        system_prompt: str,
        user_prompt: str,
        parser: Callable[[str], dict[str, Any]],
        retry_instruction: str = "仍使用同一模板完整重写一次；不要解释错误。",
        *,
        stream_phase: str = "write",
        stream_message: str = "正在生成提示词预览",
        retry_message: str | None = None,
        max_repairs: int = 1,
        status_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str, bool]:
        prompt = user_prompt
        last_output = ""
        errors: list[str] = []
        for attempt in range(max(0, int(max_repairs)) + 1):
            emit_llm_stream_status(
                stream_phase if attempt == 0 else f"{stream_phase}_retry",
                stream_message if attempt == 0 else (retry_message or f"输出未通过校验，正在进行第 {attempt} 次修复"),
                reset=True,
                attempt=attempt,
                retryable=True,
                **(status_context or {}),
            )
            last_output = LlmService.chat_text(
                system_prompt,
                prompt,
                max_tokens=16000,
                temperature=0.25 if attempt == 0 else 0.2,
                timeout=300,
            )
            try:
                return parser(last_output), last_output, attempt > 0
            except PromptTemplateError as err:
                detail = str(err)
                if detail in errors and max_repairs > 1:
                    ctx = status_context or {}
                    raise PromptPipelineError(detail, code="DIRECTOR_NO_PROGRESS", stage=ctx.get("stage") or stream_phase,
                        part_id=ctx.get("part_id") or "", segment_ids=ctx.get("segment_ids"),
                        retryable=False, attempt=attempt,
                        user_message=f"同一问题重复出现，已停止自动重写：{detail}") from err
                errors.append(detail)
                if attempt >= max_repairs:
                    raise
                prompt = (
                    f"{user_prompt}\n\n必须修复本次错误：{err}。此前问题一并复核，禁止回归：{'；'.join(errors)}\n"
                    f"{retry_instruction}\n不要解释错误。\n\n上一次输出：\n"
                    f"{last_output}"
                )
        raise PromptTemplateError("提示词生成未返回可解析结果")

    @classmethod
    def _run(cls, job_id: str) -> None:
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
        payload = _payload(row)
        try:
            execute_sql(
                "UPDATE ai_project_jobs SET status='running',progress=30,updated_at=%s WHERE id=%s",
                (now_str(), job_id),
            )
            request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
            source = payload.get("source_snapshot") if isinstance(payload.get("source_snapshot"), dict) else {}

            def on_delta(kind: str, piece: str) -> None:
                with _STREAM_LOCK:
                    state = _STREAM_STATE.setdefault(
                        job_id,
                        {"phase": "write", "message": "正在生成提示词预览", "reasoning": "", "text": ""},
                    )
                    key = "reasoning" if kind == "reasoning" else "text"
                    if key == "text" and str(state.get("phase") or "").startswith("director_plan"):
                        return
                    state[key] = str(state.get(key) or "") + piece
                    snapshot = state[key]
                _EVENTS.emit(job_id, {"event": "reasoning" if key == "reasoning" else "delta", "data": {"text": snapshot}})
                cls._patch_stream(job_id, {})

            def on_status(info: dict[str, Any]) -> None:
                update = {
                    "code": info.get("code") or "PROMPT_PROGRESS",
                    "phase": info.get("phase") or "write",
                    "stage": info.get("stage") or info.get("phase") or "write",
                    "message": info.get("message") or "正在生成提示词预览",
                    "reset": bool(info.get("reset")),
                    "part_id": info.get("part_id"),
                    "segment_ids": info.get("segment_ids") or [],
                    "attempt": int(info.get("attempt") or 0),
                    "retryable": bool(info.get("retryable", True)),
                }
                _EVENTS.emit(job_id, {"event": "status", "data": update})
                cls._patch_stream(job_id, update, force=True)

            with LlmStreamHook(on_delta=on_delta, on_status=on_status):
                if request.get("prompt_profile") == "full_reference":
                    beat = (source.get("beats") or [{}])[0]
                    episode = source.get("episode") if isinstance(source.get("episode"), dict) else {}
                    system, user = build_full_reference_prompts(
                        language=request.get("language"),
                        rewrite_mode=request.get("rewrite_mode"),
                        aspect_ratio=request.get("aspect_ratio"),
                        duration_seconds=resolve_shot_duration_sec(beat),
                        source_text=cls._beat_source_text(episode, beat, cls._assets_text(source.get("assets") or [])),
                        reference_slots=request.get("reference_slots") or [],
                    )
                    parsed, raw, retried = cls._generate_with_one_retry(
                        system, user,
                        lambda value: parse_full_reference(value, request.get("language"), request.get("reference_slots") or []),
                        stream_phase="full_reference",
                        stream_message="正在生成六段式提示词",
                    )
                    preview = {
                        "kind": "full_reference", "template_version": request.get("template_version"),
                        "language": request.get("language"), "source_fingerprint": payload.get("source_fingerprint"),
                        "reference_slots": request.get("reference_slots") or [],
                        "beat_id": request.get("target", {}).get("beat_id"),
                        "sections": parsed["sections"], "prompt_text": parsed["prompt_text"],
                        "raw_output": raw, "retried": retried,
                    }
                elif request.get("prompt_profile") == "director_segments":
                    if payload.get("revision_base"):
                        import copy
                        preview = copy.deepcopy(payload["revision_base"])
                        preview["id"] = f"director-plan-{uuid.uuid4().hex[:12]}"
                        preview["revision"] = int(preview.get("revision") or 0) + 1
                        preview["revision_parent"] = {"id": payload["revision_base"]["id"], "revision": payload["revision_base"]["revision"]}
                        revision_request = payload["revision_request"]
                        preview = cls._improve_director_plan(preview, payload, job_id,
                            feedback=revision_request["feedback"], targets=revision_request["segment_ids"] or None)
                    else:
                        preview = cls._generate_director_preview(payload, request, job_id=job_id)
                else:
                    raise ValueError("提示词任务类型无效")

            latest = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
            completed = _payload(latest) or payload
            completed["preview"] = preview
            completed["validation_status"] = "valid"
            completed["failure"] = None
            completed.pop("stream", None)
            timestamp = now_str()
            execute_sql(
                "UPDATE ai_project_jobs SET status='completed',progress=100,payload_json=%s,error_message=NULL,completed_at=%s,updated_at=%s WHERE id=%s",
                (json.dumps(completed, ensure_ascii=False), timestamp, timestamp, job_id),
            )
            _EVENTS.emit(job_id, {"event": "done", "terminal": True, "data": {"status": "succeeded", "preview": preview}})
        except Exception as err:
            latest = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
            failed = _payload(latest) or payload
            # Keep the last streamed draft for diagnosis and recovery after refresh.
            failure = err.as_dict() if isinstance(err, PromptPipelineError) else {
                "code": "PROMPT_PREVIEW_FAILED",
                "stage": "generation",
                "part_id": None,
                "segment_ids": [],
                "attempt": 0,
                "retryable": True,
                "message": "提示词预览生成失败，可重试失败部分",
                "detail": str(err),
            }
            failed["failure"] = failure
            failed["validation_status"] = "invalid"
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,payload_json=%s,updated_at=%s WHERE id=%s",
                (str(err)[:1000], json.dumps(failed, ensure_ascii=False), now_str(), job_id),
            )
            _EVENTS.emit(job_id, {"event": "error", "terminal": True, "data": {"status": "failed", **failure}})
        finally:
            with _STREAM_LOCK:
                _STREAM_STATE.pop(job_id, None)
                _STREAM_FLUSH_AT.pop(job_id, None)
            with _ACTIVE_LOCK:
                _ACTIVE.discard(job_id)
            cls.kick()

    @staticmethod
    def _assets_text(assets: list[dict[str, Any]]) -> str:
        return "\n".join(
            f"- {item.get('kind') or 'asset'}｜{item.get('name') or '未命名'}：{item.get('description') or item.get('visual_prompt') or ''}"
            for item in assets
        )

    @staticmethod
    def _beat_source_text(episode: dict[str, Any], beat: dict[str, Any], assets_text: str) -> str:
        return (
            f"分集：{episode.get('title') or ''}\n原剧本：\n{episode.get('script_text') or ''}\n\n"
            f"当前分镜：{beat.get('heading') or beat.get('scene') or ''}\n"
            f"动作：{beat.get('action') or beat.get('visual_prompt') or ''}\n机位：{beat.get('camera') or ''}\n"
            f"对白：{beat.get('dialogue') or ''}\n声音：{beat.get('audio') or ''}\n\n"
            f"项目资产文字设定：\n{assets_text}"
        )

    @staticmethod
    def _director_unit_specs(planned_parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            unit
            for part in planned_parts
            for segment in part.get("segments") or []
            for unit in segment.get("source_units") or []
        ]

    @classmethod
    def _build_source_facts(
        cls,
        beats: list[dict[str, Any]],
    ) -> dict[str, dict[str, list[dict[str, str]]]]:
        """Create stable fact ids without asking the model to rewrite source text."""
        result: dict[str, dict[str, list[dict[str, str]]]] = {}
        for beat_index, beat in enumerate(beats, start=1):
            beat_id = _clean(beat.get("id")) or f"beat-{beat_index}"
            action = _clean(beat.get("action") or beat.get("visual_prompt"))
            event_texts = [
                chunk.strip()
                for chunk in re.split(r"(?<=[。！？!?；;])|[\r\n]+", action)
                if chunk.strip()
            ]
            if action and not event_texts:
                event_texts = [action]
            dialogues = cls._dialogue_lines(beat.get("dialogue"))
            result[beat_id] = {
                "events": [
                    {"id": f"{beat_id}:event:{index}", "text": text}
                    for index, text in enumerate(event_texts, start=1)
                ],
                "dialogues": [
                    {"id": f"{beat_id}:dialogue:{index}", "text": text}
                    for index, text in enumerate(dialogues, start=1)
                ],
                "persistent_states": [text for text in event_texts if re.match(r"^(?:开场|收束|空间|光线|造型锁定|环境|站位|服装)[：:]", text)],
                "camera_requirements": _clean(beat.get("camera")),
            }
            result[beat_id]["events"] = [ref for ref in result[beat_id]["events"] if ref["text"] not in result[beat_id]["persistent_states"]]
        return result

    @staticmethod
    def _normalized_match_text(value: Any) -> str:
        text = str(value or "").lower()
        text = re.sub(r"\[shot\s+\d+\]", "", text, flags=re.I)
        text = re.sub(r"\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?", "", text)
        text = re.sub(r"\s+", "", text)
        return text

    @staticmethod
    def _dialogue_lines(value: Any) -> list[str]:
        return [line.strip() for line in str(value or "").splitlines() if line.strip()]

    @staticmethod
    def _dialogue_match_key(value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or ""))
        text = re.sub(r"\s+", "", text)
        return text.translate(str.maketrans("", "", "\"'“”‘’「」『』"))

    @classmethod
    def _validate_atomic_unit_allocation(
        cls,
        parsed: dict[str, dict[str, Any]],
        units: list[dict[str, Any]],
        beats: list[dict[str, Any]],
        source_facts: dict[str, dict[str, list[dict[str, str]]]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        by_id = {str(item.get("id") or ""): item for item in units}
        beat_by_id = {str(item.get("id") or ""): item for item in beats}
        if set(parsed) != set(by_id):
            raise PromptTemplateError("动作单元规划与计划单元不一致")
        facts = source_facts or cls._build_source_facts(beats)
        fact_maps: dict[str, dict[str, dict[str, str]]] = {}
        expected_ids: dict[str, dict[str, set[str]]] = {}
        for beat_id, rows in facts.items():
            events = {str(item.get("id") or ""): item for item in rows.get("events") or []}
            dialogues = {str(item.get("id") or ""): item for item in rows.get("dialogues") or []}
            fact_maps[beat_id] = {**events, **dialogues}
            expected_ids[beat_id] = {"events": set(events), "dialogues": set(dialogues)}

        event_owners: Counter[str] = Counter()
        dialogue_owners: Counter[str] = Counter()
        for unit_id, allocation in parsed.items():
            source_beat_id = str(by_id[unit_id].get("source_beat_id") or "")
            if source_beat_id not in beat_by_id:
                raise PromptTemplateError(f"动作单元 {unit_id} 引用了未知 Beat")
            event_ids = [str(value or "").strip() for value in allocation.get("event_ids") or [] if str(value or "").strip()]
            dialogue_ids = [str(value or "").strip() for value in allocation.get("dialogue_ids") or [] if str(value or "").strip()]
            if len(event_ids) != len(set(event_ids)) or len(dialogue_ids) != len(set(dialogue_ids)):
                raise PromptTemplateError(f"动作单元 {unit_id} 包含重复事实 ID")
            unknown_events = set(event_ids) - expected_ids.get(source_beat_id, {}).get("events", set())
            unknown_dialogues = set(dialogue_ids) - expected_ids.get(source_beat_id, {}).get("dialogues", set())
            if unknown_events or unknown_dialogues:
                unknown = sorted(unknown_events | unknown_dialogues)
                raise PromptTemplateError(f"动作单元 {unit_id} 引用了未知事实 ID：{unknown}")
            event_refs = [dict(fact_maps[source_beat_id][fact_id]) for fact_id in event_ids]
            dialogue_refs = [dict(fact_maps[source_beat_id][fact_id]) for fact_id in dialogue_ids]
            allocation.update({
                "event_ids": event_ids,
                "dialogue_ids": dialogue_ids,
                "event_refs": event_refs,
                "dialogue_refs": dialogue_refs,
                "required_events": [item["text"] for item in event_refs],
                "dialogue_owner": [item["text"] for item in dialogue_refs],
            })
            event_owners.update(event_ids)
            dialogue_owners.update(dialogue_ids)

        all_event_ids = {fact_id for rows in expected_ids.values() for fact_id in rows["events"]}
        all_dialogue_ids = {fact_id for rows in expected_ids.values() for fact_id in rows["dialogues"]}
        invalid_events = sorted(fact_id for fact_id in all_event_ids if event_owners[fact_id] != 1)
        invalid_dialogues = sorted(fact_id for fact_id in all_dialogue_ids if dialogue_owners[fact_id] != 1)
        if invalid_events:
            raise PromptTemplateError(f"动作事实必须且只能分配一次：{invalid_events}")
        if invalid_dialogues:
            raise PromptTemplateError(f"对白事实必须且只能分配一次：{invalid_dialogues}")

        units_by_beat: dict[str, list[dict[str, Any]]] = {}
        for unit in units:
            units_by_beat.setdefault(str(unit.get("source_beat_id") or ""), []).append(unit)
        for beat_id, beat_units in units_by_beat.items():
            ordered = sorted(beat_units, key=lambda item: (float(item.get("start_sec") or 0), str(item.get("id") or "")))
            previous_state = ""
            for index, unit in enumerate(ordered):
                allocation = parsed[unit["id"]]
                if index == 0:
                    start_state = _clean(allocation.get("start_state")) or f"{beat_by_id.get(beat_id, {}).get('heading') or '当前场景'}的起始可见状态"
                else:
                    start_state = previous_state
                handoff_state = _clean(allocation.get("handoff_state"))
                if not handoff_state:
                    event_text = "；".join(allocation.get("required_events") or [])
                    handoff_state = f"{event_text or '当前动作'}完成后的稳定可见状态"
                allocation["start_state"] = start_state
                allocation["handoff_state"] = handoff_state
                previous_state = handoff_state
        return parsed

    @classmethod
    def _compile_director_groups(
        cls,
        planned_segments: list[dict[str, Any]],
        groups: list[dict[str, Any]],
        language: str,
        *,
        previous_segment_count: int = 0,
    ) -> list[dict[str, Any]]:
        """Inject immutable source facts and structural markers into creative prose."""
        if len(planned_segments) != len(groups):
            raise PromptTemplateError("Director 段数量与创意扩写不一致")
        lang = normalize_language(language)
        labels = {
            "summary": "summary" if lang == "en" else "摘要",
            "retention_analysis": "retention_analysis" if lang == "en" else "保留分析",
            "detailed_description": "detailed_description" if lang == "en" else "详细描述",
            "overall_soundscape": "overall_soundscape" if lang == "en" else "整体声景",
            "non_diegetic_music": "non_diegetic_music" if lang == "en" else "非叙事配乐",
        }
        continuity = "No hard cut. Immediately following the previous section." if lang == "en" else "无硬切。紧接上一段。"
        all_fact_texts = [
            _clean(ref.get("text"))
            for segment in planned_segments
            for unit in segment.get("source_units") or []
            for ref in (unit.get("event_refs") or []) + (unit.get("dialogue_refs") or [])
            if _clean(ref.get("text"))
        ]
        compiled: list[dict[str, Any]] = []
        for index, (segment, group) in enumerate(zip(planned_segments, groups)):
            sections = dict(group.get("sections") or {})
            creative = _clean(sections.get("detailed_description"))
            creative = re.sub(r"\[Shot\s+\d+]", "", creative, flags=re.I)
            creative = creative.replace(continuity, "").strip()
            for fact_text in sorted(all_fact_texts, key=len, reverse=True):
                creative = creative.replace(fact_text, "")
            creative = re.sub(r"\n{3,}", "\n\n", creative).strip(" \n，,。")
            normalized_creative = cls._dialogue_match_key(creative)
            for planned in planned_segments:
                for unit in planned.get("source_units") or []:
                    for ref in unit.get("dialogue_refs") or []:
                        dialogue_key = cls._dialogue_match_key(ref.get("text"))
                        if len(dialogue_key) >= 4 and dialogue_key in normalized_creative:
                            raise PromptTemplateError("创意扩写重复了原始对白，请只描述表演，不复写台词")

            continuous = segment.get("continuity_from_prev", previous_segment_count + index > 0)
            detail_rows: list[str] = [continuity] if continuous else []
            shot_numbers: list[int] = []
            segment_elapsed = 0.0
            for unit in segment.get("source_units") or []:
                shot_number = int(unit.get("generated_shot_number") or 0)
                shot_numbers.append(shot_number)
                shot_end = segment_elapsed + float(unit.get("duration_seconds") or 0)
                detail_rows.append(
                    f"[Shot {shot_number}] "
                    f"{int(segment_elapsed // 60):02d}:{segment_elapsed % 60:05.2f}–"
                    f"{int(shot_end // 60):02d}:{shot_end % 60:05.2f}"
                )
                segment_elapsed = shot_end
                if unit.get("purpose"):
                    detail_rows.append(f"{unit.get('shot_size')}，{unit.get('camera')}，{unit.get('movement')}。{unit.get('performance')}。{unit.get('dialogue_timing')}")
                events = [_clean(item.get("text")) for item in unit.get("event_refs") or [] if _clean(item.get("text"))]
                dialogues = [_clean(item.get("text")) for item in unit.get("dialogue_refs") or [] if _clean(item.get("text"))]
                if events:
                    detail_rows.append(("Source actions: " if lang == "en" else "动作事实：") + "；".join(events))
                if dialogues:
                    detail_rows.append(("Verbatim dialogue: " if lang == "en" else "对白原文：") + "；".join(dialogues))
                detail_rows.append(
                    ("Visible continuity: " if lang == "en" else "可见状态：")
                    + f"{_clean(unit.get('start_state'))} → {_clean(unit.get('handoff_state'))}"
                )
            if creative:
                detail_rows.append(creative if segment.get("story_designed") else ("Creative direction: " if lang == "en" else "运镜与表演扩写：") + creative)
            if lang != "en" and not any("不要乱说话" in row for row in detail_rows):
                detail_rows.append("不要乱说话。")
            sections["detailed_description"] = "\n".join(row for row in detail_rows if row)
            prompt_text = "\n\n".join(f"{labels[key]}: {sections[key]}" for key in labels)
            compiled.append({"sections": sections, "prompt_text": prompt_text, "shot_numbers": shot_numbers})
        return compiled

    @classmethod
    def _validate_director_groups(
        cls,
        planned_segments: list[dict[str, Any]],
        groups: list[dict[str, Any]],
        language: str = "zh",
    ) -> None:
        if len(planned_segments) != len(groups):
            raise PromptTemplateError("Director 段数量与模型输出不一致")
        all_shot_numbers: list[int] = []
        unit_ids: set[str] = set()
        event_ids: set[str] = set()
        dialogue_ids: set[str] = set()
        for segment_index, (segment, group) in enumerate(zip(planned_segments, groups), start=1):
            prompt_text = str(group.get("prompt_text") or "")
            detail = str((group.get("sections") or {}).get("detailed_description") or "")
            continuity = (
                "No hard cut. Immediately following the previous section."
                if normalize_language(language) == "en"
                else "无硬切。紧接上一段。"
            )
            if segment.get("continuity_from_prev", segment_index > 1) and not detail.startswith(continuity):
                raise PromptTemplateError(f"第 {segment_index} 段缺少程序编译的连续性开头")
            actual_shots = [int(value) for value in re.findall(r"\[Shot\s+(\d+)]", prompt_text, flags=re.I)]
            expected_shots = [int(unit.get("generated_shot_number") or 0) for unit in segment.get("source_units") or []]
            if actual_shots != expected_shots:
                raise PromptTemplateError(f"第 {segment_index} 段的程序编译镜头编号无效")
            all_shot_numbers.extend(actual_shots)
            for unit in segment.get("source_units") or []:
                unit_id = str(unit.get("id") or "")
                if not unit_id or unit_id in unit_ids:
                    raise PromptTemplateError("Director source_unit_id 为空或重复")
                unit_ids.add(unit_id)
                unit_event_ids = [str(value or "") for value in unit.get("event_ids") or []]
                unit_dialogue_ids = [str(value or "") for value in unit.get("dialogue_ids") or []]
                if len(unit_event_ids) != len(set(unit_event_ids)) or len(unit_dialogue_ids) != len(set(unit_dialogue_ids)):
                    raise PromptTemplateError("Director Unit 包含重复事实 ID")
                for ref in (unit.get("event_refs") or []) + (unit.get("dialogue_refs") or []):
                    if _clean(ref.get("text")) not in detail:
                        raise PromptTemplateError(f"第 {segment_index} 段遗漏原始动作或对白事实")
                if event_ids.intersection(unit_event_ids):
                    raise PromptTemplateError("动作事实 ID 跨 Director 段重复")
                if dialogue_ids.intersection(unit_dialogue_ids):
                    raise PromptTemplateError("对白事实 ID 跨 Director 段重复")
                event_ids.update(unit_event_ids)
                dialogue_ids.update(unit_dialogue_ids)
            if segment_index > 1 and any(term.lower() in prompt_text.lower() for term in _DIRECTOR_REPLAY_TERMS):
                raise PromptTemplateError(f"第 {segment_index} 段包含禁止的重播语义")
        if len(all_shot_numbers) != len(set(all_shot_numbers)):
            raise PromptTemplateError("generated_shot_number 在 Director 方案中重复")

        # A high overlap in adjacent summaries for the same source Beat is a
        # useful local signal for replayed prose without blocking normal
        # continuity language shared by all segments.
        for index in range(1, len(planned_segments)):
            previous = planned_segments[index - 1]
            current = planned_segments[index]
            previous_beats = {str(item.get("source_beat_id") or "") for item in previous.get("source_units") or []}
            current_beats = {str(item.get("source_beat_id") or "") for item in current.get("source_units") or []}
            if not previous_beats.intersection(current_beats):
                continue
            left = cls._normalized_match_text(groups[index - 1].get("sections", {}).get("summary"))
            right = cls._normalized_match_text(groups[index].get("sections", {}).get("summary"))
            if len(left) >= 12 and len(right) >= 12:
                left_pairs = {left[pos:pos + 2] for pos in range(len(left) - 1)}
                right_pairs = {right[pos:pos + 2] for pos in range(len(right) - 1)}
                overlap = len(left_pairs & right_pairs) / max(1, min(len(left_pairs), len(right_pairs)))
                if overlap >= 0.82:
                    raise PromptTemplateError(f"相邻 Director 段摘要高度重复（{overlap * 100:.0f}%），疑似重演动作")

    @classmethod
    def _populate_director_atomic_units(
        cls,
        payload: dict[str, Any],
        request: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], bool]:
        planned_parts = payload.get("planned_parts") if isinstance(payload.get("planned_parts"), list) else []
        source = payload.get("source_snapshot") if isinstance(payload.get("source_snapshot"), dict) else {}
        beats = [dict(item) for item in source.get("beats") or [] if isinstance(item, dict)]
        source_facts = payload.get("source_facts") if isinstance(payload.get("source_facts"), dict) else cls._build_source_facts(beats)
        payload["source_facts"] = source_facts
        units = cls._director_unit_specs(planned_parts)
        if not units:
            raise PromptTemplateError("Director 方案没有可规划的动作单元")
        for beat in beats:
            beat["source_shot_number"] = _shot_number(beat.get("story_shot") or beat.get("sequence"), beat.get("sequence") or 1)
        system, user = build_director_unit_planning_prompts(
            language=request.get("language"), beats=beats, units=units, source_facts=source_facts,
        )
        parsed, _raw, retried = cls._generate_with_one_retry(
            system,
            user,
            lambda value: cls._validate_atomic_unit_allocation(
                parse_director_unit_plan(value, units), units, beats, source_facts,
            ),
            retry_instruction="只修复动作单元归属 JSON；保持 unit_id、时间范围和原始对白不变，不增加事件。",
            stream_phase="director_plan",
            stream_message="正在整理剧情事实",
            retry_message="剧情事实未通过校验，正在自动修复",
            max_repairs=2,
            status_context={
                "code": "DIRECTOR_FACT_PLANNING",
                "stage": "fact_planning",
                "segment_ids": [str(item.get("id") or "") for part in planned_parts for item in part.get("segments") or []],
            },
        )
        for unit in units:
            unit.update(parsed[unit["id"]])
        return planned_parts, retried

    @classmethod
    def _parse_and_validate_director_output(
        cls,
        value: str,
        request: dict[str, Any],
        segments: list[dict[str, Any]],
        expected_shots: list[list[int]],
        expected_groups: int,
        previous_segments: list[dict[str, Any]] | None = None,
        previous_groups: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        parsed = parse_director_creative_output(
            value,
            request.get("language"),
            request.get("reference_slots") or [],
            segments,
            locked_common_setting=request.get("locked_common_setting"),
        )
        parsed["groups"] = cls._compile_director_groups(
            segments,
            parsed["groups"],
            request.get("language") or "zh",
            previous_segment_count=len(previous_segments or []),
        )
        cls._validate_director_groups(
            [*(previous_segments or []), *segments],
            [*(previous_groups or []), *parsed["groups"]],
            request.get("language") or "zh",
        )
        return parsed

    @classmethod
    def _generate_director_preview(
        cls,
        payload: dict[str, Any],
        request: dict[str, Any],
        *,
        job_id: str = "",
    ) -> dict[str, Any]:
        checkpoints = payload.setdefault("checkpoints", {})
        if request.get("story_design") and not checkpoints.get("fact_planning"):
            from .director_story_design import design_prompts, pack_design, reference_common_setting
            from .llm_service import LlmService
            source = payload.get("source_snapshot") or {}
            facts = payload.get("source_facts") or cls._build_source_facts(source.get("beats") or [])
            definition = workflow_for(request["workflow_id"])
            locked_setting = reference_common_setting(source, request)
            if locked_setting:
                request = {**request, "locked_common_setting": locked_setting}
            system, user = design_prompts(source, facts, request, definition)
            def parse_design(raw: str) -> dict:
                try:
                    design = LlmService._parse_json_object(raw)
                except ValueError as err:
                    raise PromptTemplateError(f"导演设计 JSON 无法解析：{err}") from err
                if locked_setting:
                    design["common_setting"] = locked_setting
                design["planned_parts"] = pack_design(design, source.get("beats") or [], facts, definition, _FPS)
                return design
            design, _, repaired = cls._generate_with_one_retry(system, user, parse_design,
                stream_phase="director_design", stream_message="正在设计本集戏剧节奏与镜头",
                retry_instruction="依据具体校验错误修复导演设计；禁止填充无剧情动作，不要改变事实和总时长。", max_repairs=2)
            payload["director_design"] = {k: v for k, v in design.items() if k != "planned_parts"}
            payload["source_facts"] = facts
            payload["planned_parts"] = design["planned_parts"]
            cls._save_checkpoint(job_id, payload, "fact_planning", {"status": "completed", "planned_parts": design["planned_parts"], "retried": repaired})
        planning_checkpoint = checkpoints.get("fact_planning") if isinstance(checkpoints.get("fact_planning"), dict) else {}
        if planning_checkpoint.get("status") == "completed" and isinstance(planning_checkpoint.get("planned_parts"), list):
            planned_parts = planning_checkpoint["planned_parts"]
            planning_retried = bool(planning_checkpoint.get("retried"))
        else:
            try:
                planned_parts, planning_retried = cls._populate_director_atomic_units(payload, request)
            except PromptTemplateError as err:
                raise PromptPipelineError(
                    str(err),
                    code="DIRECTOR_FACT_PLANNING_INVALID",
                    stage="fact_planning",
                    attempt=2,
                    retryable=True,
                    user_message="剧情事实分配仍有冲突，请重试失败部分。",
                ) from err
            cls._save_checkpoint(job_id, payload, "fact_planning", {
                "status": "completed",
                "planned_parts": planned_parts,
                "retried": planning_retried,
            })

        parts: list[dict[str, Any]] = []
        common_setting: dict[str, Any] | None = (payload.get("director_design") or {}).get("common_setting")
        if common_setting:
            from .director_story_design import normalize_common_setting
            common_setting = normalize_common_setting(common_setting)
            payload["director_design"]["common_setting"] = common_setting
            request = {**request, "locked_common_setting": common_setting}
        previous_handoff: dict[str, Any] | str = ""
        retried = planning_retried
        raw_outputs: list[str] = []
        all_planned_segments: list[dict[str, Any]] = []
        all_groups: list[dict[str, Any]] = []
        part_checkpoints = checkpoints.get("part_generation") if isinstance(checkpoints.get("part_generation"), dict) else {}
        part_total = len(planned_parts)
        for part_index, part in enumerate(planned_parts, start=1):
            part_id = str(part.get("id") or f"part-{part_index}")
            cached = part_checkpoints.get(part_id) if isinstance(part_checkpoints.get(part_id), dict) else {}
            if cached.get("status") == "completed" and isinstance(cached.get("part"), dict):
                completed_part = cached["part"]
                completed_segments = [item for item in completed_part.get("segments") or [] if isinstance(item, dict)]
                parts.append(completed_part)
                all_planned_segments.extend(completed_segments)
                all_groups.extend({
                    "sections": segment.get("sections") or {},
                    "prompt_text": segment.get("prompt_text") or "",
                    "shot_numbers": [int(shot.get("shot_number") or 0) for shot in segment.get("shots") or []],
                } for segment in completed_segments)
                common_setting = common_setting or (cached.get("common_setting") if isinstance(cached.get("common_setting"), dict) else None)
                raw_outputs.append(str(cached.get("raw_output") or ""))
                retried = retried or bool(cached.get("retried"))
                if completed_segments:
                    last_segment = completed_segments[-1]
                    previous_handoff = {
                        "segment_id": last_segment.get("id"),
                        "state": ((last_segment.get("source_units") or [{}])[-1].get("handoff_state") or ""),
                        "description_tail": str((last_segment.get("sections") or {}).get("detailed_description") or "")[-240:],
                    }
                continue

            part_handoff = previous_handoff
            if part.get("transition_type") == "cut":
                previous_handoff = {"transition_type": "cut", "message": "新场景或时间跳跃，重新建立起幅，不强制连续动作"}
            system, user = build_director_prompts(
                language=request.get("language"), rewrite_mode=request.get("rewrite_mode"),
                aspect_ratio=request.get("aspect_ratio"), segment_sources=part.get("segments") or [],
                reference_slots=request.get("reference_slots") or [], previous_handoff=previous_handoff,
                director_context={"design": payload.get("director_design"), "episode": (payload.get("source_snapshot") or {}).get("episode")} if request.get("story_design") else None,
                common_setting=common_setting if request.get("story_design") else None,
            )
            expected_shots = [
                [int(unit.get("generated_shot_number")) for unit in segment.get("source_units") or []]
                for segment in part.get("segments") or []
            ]
            try:
                parsed, raw, part_retried = cls._generate_with_one_retry(
                    system, user,
                    lambda value, expected=len(part.get("segments") or []): cls._parse_and_validate_director_output(
                        value,
                        request,
                        part.get("segments") or [],
                        expected_shots,
                        expected,
                        all_planned_segments,
                        all_groups,
                    ),
                    retry_instruction=(
                        "完整重写当前 Part 的创意扩写；章节标题、Shot 编号、连续性语句、动作和对白均由程序写入，"
                        "模型不要输出这些固定内容。"
                    ),
                    stream_phase=f"director_part_{part_index}",
                    stream_message=f"正在生成 Director Part {part_index}/{part_total}",
                    retry_message=f"Director Part {part_index} 未通过校验，正在自动修复",
                    max_repairs=2,
                    status_context={
                        "code": "DIRECTOR_PART_GENERATION",
                        "stage": "part_generation",
                        "part_id": part_id,
                        "segment_ids": [str(item.get("id") or "") for item in part.get("segments") or []],
                    },
                )
            except PromptTemplateError as err:
                if isinstance(err, PromptPipelineError):
                    raise
                raise PromptPipelineError(
                    str(err),
                    code="DIRECTOR_PART_INVALID",
                    stage="part_generation",
                    part_id=part_id,
                    segment_ids=[str(item.get("id") or "") for item in part.get("segments") or []],
                    attempt=2,
                    retryable=True,
                    user_message=f"Part {part_index}/{part_total} 自动修复两次后仍未通过，可只重试失败部分。",
                ) from err
            retried = retried or part_retried
            raw_outputs.append(raw)
            all_planned_segments.extend(part.get("segments") or [])
            all_groups.extend(parsed["groups"])
            if common_setting is None or request.get("story_design"):
                common_setting = parsed["common_setting"]
            segments = []
            for idx, (planned, group) in enumerate(zip(part.get("segments") or [], parsed["groups"]), start=1):
                source_ids = list(planned.get("source_beat_ids") or [])
                units_by_shot = {
                    int(unit.get("generated_shot_number")): str(unit.get("source_beat_id") or "") or None
                    for unit in planned.get("source_units") or []
                }
                segments.append({
                    "id": planned["id"], "index": idx, "title": planned.get("title") or f"段 {idx}",
                    "frame_count": planned.get("frame_count"), "duration_seconds": planned.get("duration_seconds"),
                    "source_beat_ids": source_ids,
                    "source_units": planned.get("source_units") or [],
                    "shots": [
                        {"shot_number": number, "source_beat_id": units_by_shot.get(number)}
                        for number in group.get("shot_numbers") or []
                    ],
                    "sections": group["sections"], "prompt_text": group["prompt_text"],
                    "continuity_from_prev": planned.get("continuity_from_prev", part_index > 1 or idx > 1),
                    "story_designed": planned.get("story_designed", False),
                })
            previous_handoff = {
                "segment_id": segments[-1]["id"],
                "state": (segments[-1].get("source_units") or [{}])[-1].get("handoff_state") or "",
                "description_tail": segments[-1]["sections"]["detailed_description"][-240:],
            }
            completed_part = {
                "transition_type": part.get("transition_type", "continuous"),
                "id": part["id"], "index": part["index"], "frame_count": part["frame_count"],
                "segments": segments,
                "handoff_from_previous_part": part_handoff if isinstance(part_handoff, dict) else {},
            }
            parts.append(completed_part)
            part_checkpoints[part_id] = {
                "status": "completed",
                "part": completed_part,
                "common_setting": parsed["common_setting"],
                "raw_output": raw,
                "retried": part_retried,
            }
            cls._save_checkpoint(job_id, payload, "part_generation", part_checkpoints)

        emit_llm_stream_status(
            "director_final_validation",
            "正在进行最终校验",
            reset=False,
            code="DIRECTOR_FINAL_VALIDATION",
            stage="final_validation",
            segment_ids=[str(item.get("id") or "") for item in all_planned_segments],
            attempt=0,
            retryable=True,
        )
        preview = {
            "director_design": payload.get("director_design"),
            "requested_segment_count": request.get("target_segment_count"),
            "quality_status": "awaiting_review" if request.get("story_design") else "not_reviewed",
            "kind": "director_segments", "id": f"director-plan-{uuid.uuid4().hex[:12]}", "revision": 1,
            "schema_version": _DIRECTOR_PLAN_SCHEMA_VERSION,
            "planning_strategy": "atomic_units",
            "unit_planner_version": DIRECTOR_UNIT_PLANNER_VERSION,
            "template_version": request.get("template_version"), "workflow_id": request.get("workflow_id"),
            "language": request.get("language"), "rewrite_mode": request.get("rewrite_mode"),
            "aspect_ratio": request.get("aspect_ratio"),
            "target_segment_count": request.get("target_segment_count"),
            "actual_segment_count": sum(len(part["segments"]) for part in parts),
            "source_fingerprint": payload.get("source_fingerprint"),
            "source_facts": payload.get("source_facts") or {},
            "reference_slots": request.get("reference_slots") or [], "common_setting": common_setting or {},
            "parts": parts, "raw_outputs": raw_outputs, "retried": retried,
            "validation_status": "valid", "status": "current",
        }
        try:
            cls._validate_director_groups(all_planned_segments, all_groups, request.get("language") or "zh")
            cls.validate_director_plan(preview)
        except (PromptTemplateError, ValueError) as err:
            affected_part = parts[-1] if parts else {}
            raise PromptPipelineError(
                str(err),
                code="DIRECTOR_FINAL_VALIDATION_FAILED",
                stage="final_validation",
                part_id=str(affected_part.get("id") or "") or None,
                segment_ids=[str(item.get("id") or "") for item in affected_part.get("segments") or []],
                attempt=0,
                retryable=True,
                user_message="最终校验发现事实归属冲突，请重试失败部分。",
            ) from err
        if request.get("story_design"):
            preview = cls._improve_director_plan(preview, payload, job_id)
        cls._save_checkpoint(job_id, payload, "final_validation", {
            "status": "completed",
            "validated_at": now_str(),
        })
        return preview

    @classmethod
    def _improve_director_plan(cls, preview, payload, job_id, *, feedback="", targets=None):
        return improve_plan(preview, payload.get("source_snapshot") or {}, feedback=feedback, targets=targets,
            state=(payload.get("checkpoints") or {}).get("quality_revision"),
            save=lambda state: cls._save_checkpoint(job_id, payload, "quality_revision", state))

    @classmethod
    def apply_preview(
        cls,
        project_id: str,
        episode_id: str,
        job_id: str,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        req = request or {}
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (job_id, project_id)) or {}
        payload = _payload(row)
        preview = payload.get("preview") if isinstance(payload.get("preview"), dict) else None
        if not row or row.get("job_type") != JOB_TYPE or row.get("status") not in {"completed", "succeeded"} or not preview:
            raise ValueError("提示词预览尚未完成")
        if payload.get("validation_status") != "valid" or preview.get("validation_status") == "invalid":
            raise ValueError("提示词预览尚未通过最终校验，不能保存或用于出片")
        if payload.get("episode_id") != episode_id:
            raise ValueError("提示词预览不属于当前分集")
        expected = _clean(req.get("expected_source_fingerprint"))
        if expected and expected != _clean(payload.get("source_fingerprint")):
            raise RuntimeError("SOURCE_CONFLICT: 预览来源指纹不匹配")
        timestamp = now_str()
        with transaction_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM ai_project_episodes WHERE id=%s AND project_id=%s FOR UPDATE",
                (episode_id, project_id),
            )
            episode_row = cursor.fetchone()
            if not episode_row:
                raise ValueError("分集不存在")
            data = _json_dict(episode_row.get("data_json"))
            beats = data.get("beats") if isinstance(data.get("beats"), list) else []
            cursor.execute(
                "SELECT * FROM ai_project_assets WHERE project_id=%s ORDER BY updated_at DESC FOR UPDATE",
                (project_id,),
            )
            asset_rows = cursor.fetchall() or []
            locked_source = {
                "episode": dict(episode_row),
                "data": data,
                "beats": beats,
                "assets": [dict(item) for item in asset_rows],
            }
            if (payload.get("request") or {}).get("story_design"):
                number = int(episode_row.get("episode_num") or 1)
                cursor.execute(
                    "SELECT episode_num,title,script_text FROM ai_project_episodes "
                    "WHERE project_id=%s AND episode_num IN (%s,%s) ORDER BY episode_num FOR UPDATE",
                    (project_id, number - 1, number + 1),
                )
                locked_source["adjacent_episodes"] = [dict(item) for item in (cursor.fetchall() or [])]
            current = cls.source_fingerprint(locked_source, payload.get("request") or {})
            if current != payload.get("source_fingerprint"):
                raise RuntimeError("SOURCE_CONFLICT: 剧本、分镜、资产或工作流已变化，请重新生成预览")
            authoring = data.get("prompt_authoring") if isinstance(data.get("prompt_authoring"), dict) else {}
            authoring["schema_version"] = _DIRECTOR_PLAN_SCHEMA_VERSION if preview.get("kind") == "director_segments" else max(
                1, int(authoring.get("schema_version") or 1)
            )
            if preview.get("kind") == "full_reference":
                beat_id = _clean(preview.get("beat_id"))
                beat = next((item for item in beats if _clean(item.get("id")) == beat_id), None)
                if not beat:
                    raise ValueError("分镜不存在")
                existing_prompt = _clean(beat.get("h3_prompt"))
                existing_source = _clean(beat.get("h3_prompt_source"))
                manual = bool(existing_prompt and existing_source not in {"generated", "prompt_master_full_reference"})
                if manual and not bool(req.get("overwrite_manual")):
                    raise RuntimeError("MANUAL_CONFLICT: 当前分镜包含手写提示词，请确认覆盖")
                records = authoring.get("full_reference") if isinstance(authoring.get("full_reference"), dict) else {}
                record = {
                    **preview,
                    "status": "current", "origin": "prompt_master",
                    "workflow_id": payload.get("request", {}).get("workflow_id"),
                    "rewrite_mode": payload.get("request", {}).get("rewrite_mode"),
                    "aspect_ratio": payload.get("request", {}).get("aspect_ratio"),
                    "applied_from_job_id": job_id, "updated_at": timestamp,
                }
                record.pop("raw_output", None)
                records[beat_id] = record
                authoring["full_reference"] = records
                beat.update({
                    "h3_prompt": preview["prompt_text"],
                    "h3_prompt_source": "prompt_master_full_reference",
                    "h3_prompt_template_version": preview.get("template_version"),
                    "h3_prompt_context_fingerprint": preview.get("source_fingerprint"),
                })
                data["beats"] = beats
            else:
                revision_request = payload.get("revision_request")
                if revision_request and content_digest(authoring.get("director_plan")) != revision_request.get("saved_base_digest"):
                    raise RuntimeError("REVISION_CONFLICT: 返修期间已保存的方案发生变化，请基于新版本返修")
                plan = dict(preview)
                plan.pop("raw_outputs", None)
                if plan.get("target_segment_count") in (None, ""):
                    plan["target_segment_count"] = (payload.get("request") or {}).get("target_segment_count")
                plan.update({
                    "status": "current", "origin": "prompt_master",
                    "applied_from_job_id": job_id, "updated_at": timestamp,
                })
                cls.validate_director_plan(plan)
                authoring["director_plan"] = plan
            data["prompt_authoring"] = authoring
            cursor.execute(
                "UPDATE ai_project_episodes SET data_json=%s,updated_at=%s WHERE id=%s AND project_id=%s",
                (json.dumps(data, ensure_ascii=False), timestamp, episode_id, project_id),
            )
            payload["applied_at"] = timestamp
            cursor.execute(
                "UPDATE ai_project_jobs SET payload_json=%s,updated_at=%s WHERE id=%s AND project_id=%s",
                (json.dumps(payload, ensure_ascii=False), timestamp, job_id, project_id),
            )
        return {"status": "applied", "prompt_authoring": authoring}

    @classmethod
    def patch_director_plan(
        cls,
        project_id: str,
        episode_id: str,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        req = request or {}
        expected_revision = int(req.get("expected_revision") or 0)
        with transaction_cursor() as cursor:
            cursor.execute(
                "SELECT data_json FROM ai_project_episodes WHERE id=%s AND project_id=%s FOR UPDATE",
                (episode_id, project_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("分集不存在")
            data = _json_dict(row.get("data_json"))
            authoring = data.get("prompt_authoring") if isinstance(data.get("prompt_authoring"), dict) else {}
            current = authoring.get("director_plan") if isinstance(authoring.get("director_plan"), dict) else None
            if not current:
                raise ValueError("当前分集还没有 Director 出片方案")
            if int(current.get("revision") or 0) != expected_revision:
                raise RuntimeError("REVISION_CONFLICT: Director 方案已被其他操作更新")
            plan = dict(current)
            for key in ("common_setting", "parts", "reference_slots"):
                if key in req:
                    plan[key] = req[key]
            cls.validate_director_plan(plan)
            plan["revision"] = expected_revision + 1
            plan["origin"] = "manual_edit"
            plan["creative_review"] = None
            plan["quality_status"] = "not_reviewed"
            plan["updated_at"] = now_str()
            authoring["director_plan"] = plan
            data["prompt_authoring"] = authoring
            cursor.execute(
                "UPDATE ai_project_episodes SET data_json=%s,updated_at=%s WHERE id=%s AND project_id=%s",
                (json.dumps(data, ensure_ascii=False), plan["updated_at"], episode_id, project_id),
            )
        return plan

    @staticmethod
    def validate_director_plan(plan: dict[str, Any]) -> None:
        definition = workflow_for(_clean(plan.get("workflow_id")))
        if int(plan.get("schema_version") or 0) not in {4, 5}:
            raise ValueError("Director 方案结构已升级，请重新生成")
        if _clean(plan.get("planning_strategy")) != "atomic_units":
            raise ValueError("Director 方案缺少动作单元规划，请重新生成")
        max_segments = int(definition.max_segments or 6)
        max_frames = int(definition.max_total_frames or 1152)
        common = plan.get("common_setting") if isinstance(plan.get("common_setting"), dict) else {}
        if not _clean(common.get("subject_definitions")):
            raise ValueError("Director 公共设定不能为空")
        reference_slots = plan.get("reference_slots") if isinstance(plan.get("reference_slots"), list) else []
        if len(reference_slots) > int(definition.max_references or 0):
            raise ValueError("Director 参考图数量超过当前工作流容量")
        if [int(item.get("index") or 0) for item in reference_slots] != list(range(1, len(reference_slots) + 1)):
            raise ValueError("Director 参考图编号必须从 1 连续递增")
        source_facts = plan.get("source_facts") if isinstance(plan.get("source_facts"), dict) else {}
        if not source_facts:
            raise ValueError("Director 方案缺少 source_facts，请重新生成")
        fact_maps: dict[str, dict[str, dict[str, str]]] = {}
        expected_event_ids: set[str] = set()
        expected_dialogue_ids: set[str] = set()
        for beat_id, rows in source_facts.items():
            if not isinstance(rows, dict):
                raise ValueError("Director source_facts 格式无效")
            events = {
                _clean(item.get("id")): item
                for item in rows.get("events") or []
                if isinstance(item, dict) and _clean(item.get("id"))
            }
            dialogues = {
                _clean(item.get("id")): item
                for item in rows.get("dialogues") or []
                if isinstance(item, dict) and _clean(item.get("id"))
            }
            if any(not _clean(item.get("text")) for item in [*events.values(), *dialogues.values()]):
                raise ValueError("Director source_facts 包含空原文")
            fact_maps[_clean(beat_id)] = {**events, **dialogues}
            expected_event_ids.update(events)
            expected_dialogue_ids.update(dialogues)
        language = normalize_language(plan.get("language"))
        public_label = "subject_definitions" if language == "en" else "主体定义"
        public_prompt = _clean(common.get("prompt_text")) or f"{public_label}: {_clean(common.get('subject_definitions'))}"
        parts = plan.get("parts") if isinstance(plan.get("parts"), list) else []
        if not parts:
            raise ValueError("Director 方案至少需要一个 Part")
        part_ids: set[str] = set()
        segment_ids: set[str] = set()
        unit_ids: set[str] = set()
        generated_shots: set[int] = set()
        owned_event_ids: set[str] = set()
        owned_dialogue_ids: set[str] = set()
        units_by_beat: dict[str, list[dict[str, Any]]] = {}
        all_segments: list[dict[str, Any]] = []
        all_groups: list[dict[str, Any]] = []
        for part in parts:
            part_id = _clean(part.get("id"))
            if not part_id or part_id in part_ids:
                raise ValueError("Director Part ID 为空或重复")
            part_ids.add(part_id)
            segments = part.get("segments") if isinstance(part.get("segments"), list) else []
            single = plan.get("schema_version") == 5 and part.get("render_mode") == "shot"
            if (single and len(segments) != 1) or (not single and (len(segments) < 2 or len(segments) > max_segments)):
                raise ValueError(f"每个 Director Part 必须包含 2–{max_segments} 段")
            frame_total = 0
            group_prompts: list[str] = []
            expected_shots: list[list[int]] = []
            for segment in segments:
                segment_id = _clean(segment.get("id"))
                if not segment_id or segment_id in segment_ids:
                    raise ValueError("Director 段 ID 为空或重复")
                segment_ids.add(segment_id)
                frames = int(segment.get("frame_count") or round(float(segment.get("duration_seconds") or 0) * _FPS))
                if frames <= 0:
                    raise ValueError("Director 段时长必须大于 0")
                frame_total += frames
                source_units = segment.get("source_units") if isinstance(segment.get("source_units"), list) else []
                if not source_units:
                    raise ValueError("Director 段缺少 source_units，请重新生成")
                for unit in source_units:
                    unit_id = _clean(unit.get("id"))
                    if not unit_id or unit_id in unit_ids:
                        raise ValueError("Director source_unit_id 为空或重复")
                    unit_ids.add(unit_id)
                    source_beat_id = _clean(unit.get("source_beat_id"))
                    generated_shot = int(unit.get("generated_shot_number") or 0)
                    start_sec = float(unit.get("start_sec") or 0)
                    end_sec = float(unit.get("end_sec") or 0)
                    if not source_beat_id or generated_shot <= 0 or end_sec <= start_sec:
                        raise ValueError("Director source_units 的来源、镜头号或时间范围无效")
                    if generated_shot in generated_shots:
                        raise ValueError("Director generated_shot_number 重复")
                    generated_shots.add(generated_shot)
                    event_ids = [_clean(value) for value in unit.get("event_ids") or [] if _clean(value)]
                    dialogue_ids = [_clean(value) for value in unit.get("dialogue_ids") or [] if _clean(value)]
                    if owned_event_ids.intersection(event_ids) or owned_dialogue_ids.intersection(dialogue_ids):
                        raise ValueError("Director 事实 ID 跨 Unit 重复")
                    if any(value not in expected_event_ids for value in event_ids):
                        raise ValueError("Director Unit 引用了未知动作事实 ID")
                    if any(value not in expected_dialogue_ids for value in dialogue_ids):
                        raise ValueError("Director Unit 引用了未知对白事实 ID")
                    if any(value not in fact_maps.get(source_beat_id, {}) for value in [*event_ids, *dialogue_ids]):
                        raise ValueError("Director Unit 引用了其他 Beat 的事实 ID")
                    event_refs = unit.get("event_refs") if isinstance(unit.get("event_refs"), list) else []
                    dialogue_refs = unit.get("dialogue_refs") if isinstance(unit.get("dialogue_refs"), list) else []
                    if [(_clean(item.get("id")), _clean(item.get("text"))) for item in event_refs if isinstance(item, dict)] != [
                        (value, _clean(fact_maps[source_beat_id][value].get("text"))) for value in event_ids
                    ]:
                        raise ValueError("Director 动作事实引用与原文不一致")
                    if [(_clean(item.get("id")), _clean(item.get("text"))) for item in dialogue_refs if isinstance(item, dict)] != [
                        (value, _clean(fact_maps[source_beat_id][value].get("text"))) for value in dialogue_ids
                    ]:
                        raise ValueError("Director 对白事实引用与原文不一致")
                    owned_event_ids.update(event_ids)
                    owned_dialogue_ids.update(dialogue_ids)
                    units_by_beat.setdefault(source_beat_id, []).append(unit)
                sections = segment.get("sections") if isinstance(segment.get("sections"), dict) else {}
                for key in ("summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music"):
                    if not _clean(sections.get(key)):
                        raise ValueError(f"Director 段缺少 {key}")
                prompt_text = _clean(segment.get("prompt_text"))
                if not prompt_text:
                    raise ValueError("Director 段提示词不能为空")
                group_prompts.append(prompt_text)
                expected_shots.append([
                    int(item.get("generated_shot_number"))
                    for item in source_units
                ])
            if frame_total > max_frames:
                raise ValueError(f"单个 Director Part 不能超过 {max_frames} 帧")
            public_separator = "===== Public Settings =====" if language == "en" else "===== 公共设定 ====="
            group_name = "Prompt Group" if language == "en" else "提示词组"
            combined = [public_separator, public_prompt]
            for index, prompt_text in enumerate(group_prompts, start=1):
                combined.extend([f"===== {group_name} {index} =====", prompt_text])
            parsed = parse_director_output(
                "\n".join(combined),
                language,
                reference_slots,
                expected_groups=len(segments),
                allow_single=single,
            )
            for segment, group in zip(segments, parsed["groups"]):
                stored = segment.get("sections") if isinstance(segment.get("sections"), dict) else {}
                if any(_clean(stored.get(key)) != _clean(group["sections"].get(key)) for key in group["sections"]):
                    raise ValueError("Director 段结构化正文与提示词不一致")
            all_segments.extend(segments)
            all_groups.extend(parsed["groups"])
        if owned_event_ids != expected_event_ids:
            raise ValueError("Director 动作事实未完整且唯一归属")
        if owned_dialogue_ids != expected_dialogue_ids:
            raise ValueError("Director 对白事实未完整且唯一归属")
        for source_beat_id, items in units_by_beat.items():
            ordered = sorted(items, key=lambda item: float(item.get("start_sec") or 0))
            previous_end = 0.0
            for index, item in enumerate(ordered):
                start_sec = float(item.get("start_sec") or 0)
                end_sec = float(item.get("end_sec") or 0)
                duration_seconds = float(item.get("duration_seconds") or 0)
                if abs(duration_seconds - (end_sec - start_sec)) > 0.02:
                    raise ValueError(f"Beat {source_beat_id} 的 source_unit 时长与时间范围不一致")
                if index == 0 and abs(start_sec) > 0.01:
                    raise ValueError(f"Beat {source_beat_id} 的 source_units 未从 0 秒开始")
                if index and start_sec < previous_end - 0.01:
                    raise ValueError(f"Beat {source_beat_id} 的 source_units 时间范围重叠")
                if index and abs(start_sec - previous_end) > 0.01:
                    raise ValueError(f"Beat {source_beat_id} 的 source_units 时间范围存在缺口")
                if index and _clean(item.get("start_state")) != _clean(ordered[index - 1].get("handoff_state")):
                    raise ValueError(f"Beat {source_beat_id} 的 source_units 状态交接不一致")
                previous_end = max(previous_end, end_sec)
        try:
            PromptExpansionService._validate_director_groups(all_segments, all_groups, plan.get("language") or "zh")
        except PromptTemplateError as err:
            raise ValueError(str(err)) from err

    @classmethod
    def hydrated_authoring_state(
        cls,
        project_id: str,
        episode: dict[str, Any],
        data: dict[str, Any],
        beats: list[dict[str, Any]],
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        state = json.loads(json.dumps(data.get("prompt_authoring") or {}, ensure_ascii=False))
        source = {"episode": episode, "data": data, "beats": beats, "assets": assets}
        if (state.get("director_plan") or {}).get("director_design"):
            number = int(episode.get("episode_num") or 1)
            source["adjacent_episodes"] = query_all("SELECT episode_num,title,script_text FROM ai_project_episodes WHERE project_id=%s AND episode_num IN (%s,%s)",
                                                  (project_id, number - 1, number + 1))
        def source_matches(record: dict, request: dict) -> bool:
            if data.get("script_stale"):
                return False
            current = cls.source_fingerprint(source, request)
            if current == record.get("source_fingerprint"):
                return True
            # Pre-production previews hashed voice settings and database sort order. Compare
            # their immutable source snapshot canonically; never guess from today's assets.
            job_id = _clean(record.get("applied_from_job_id"))
            if not job_id:
                return False
            original = _payload(query_one(
                "SELECT payload_json FROM ai_project_jobs WHERE id=%s AND project_id=%s AND job_type=%s",
                (job_id, project_id, JOB_TYPE),
            ) or {})
            snapshot = original.get("source_snapshot")
            if original.get("source_fingerprint") != record.get("source_fingerprint") or not isinstance(snapshot, dict):
                return False
            old_source = {"episode": snapshot.get("episode") or {}, "beats": snapshot.get("beats") or [],
                          "assets": snapshot.get("assets") or [], "data": {}}
            return cls.source_fingerprint(old_source, request) == current
        records = state.get("full_reference") if isinstance(state.get("full_reference"), dict) else {}
        for beat_id, record in records.items():
            if not isinstance(record, dict):
                continue
            request = {
                "template_version": record.get("template_version"), "workflow_id": record.get("workflow_id"),
                "language": record.get("language"), "rewrite_mode": record.get("rewrite_mode"),
                "aspect_ratio": record.get("aspect_ratio"), "target_segment_count": None,
                "reference_slots": record.get("reference_slots") or [],
                "target": {"kind": "beat", "beat_id": beat_id},
            }
            record["status"] = "current" if source_matches(record, request) else "stale"
        plan = state.get("director_plan") if isinstance(state.get("director_plan"), dict) else None
        if plan:
            missing_units = any(
                not isinstance(segment.get("source_units"), list) or not segment.get("source_units")
                for part in plan.get("parts") or []
                for segment in part.get("segments") or []
            )
            if (
                int(plan.get("schema_version") or 0) not in {4, 5}
                or _clean(plan.get("planning_strategy")) != "atomic_units"
                or missing_units
                or not isinstance(plan.get("source_facts"), dict)
                or not plan.get("source_facts")
            ):
                plan["status"] = "stale"
                plan["invalid_reason"] = "DIRECTOR_PLAN_SCHEMA_OUTDATED"
                return state
            actual_segment_count = sum(len(part.get("segments") or []) for part in plan.get("parts") or [])
            target_segment_count = plan.get("target_segment_count")
            if target_segment_count in (None, ""):
                applied_job_id = _clean(plan.get("applied_from_job_id"))
                if applied_job_id:
                    job = query_one(
                        "SELECT payload_json FROM ai_project_jobs WHERE id=%s AND project_id=%s AND job_type=%s",
                        (applied_job_id, project_id, JOB_TYPE),
                    ) or {}
                    job_request = _payload(job).get("request")
                    if isinstance(job_request, dict):
                        target_segment_count = job_request.get("target_segment_count")
            try:
                target_segment_count = int(target_segment_count)
            except (TypeError, ValueError):
                target_segment_count = actual_segment_count
            if target_segment_count <= 0:
                target_segment_count = actual_segment_count
            plan["target_segment_count"] = target_segment_count
            if plan.get("director_design"):
                target_segment_count = plan.get("requested_segment_count")
                plan["target_segment_count"] = target_segment_count
            request = {
                "template_version": plan.get("template_version"), "workflow_id": plan.get("workflow_id"),
                "unit_planner_version": plan.get("unit_planner_version") or DIRECTOR_UNIT_PLANNER_VERSION,
                "language": plan.get("language"), "rewrite_mode": plan.get("rewrite_mode") or "expand",
                "aspect_ratio": plan.get("aspect_ratio") or "16:9",
                "target_segment_count": target_segment_count,
                "reference_slots": plan.get("reference_slots") or [], "target": {"kind": "director_episode"},
            }
            plan["status"] = "current" if source_matches(plan, request) else "stale"
            if plan["status"] == "stale":
                plan["invalid_reason"] = "SOURCE_CHANGED"
            else:
                plan.pop("invalid_reason", None)
        return state
