"""剧本工作台聚合视图（只读派生）。

把一集的资产 / 镜头 / 成片派生成「节点图 + 进度关卡」，
供前端工作台（/director/projects/:id/workbench）一次性渲染。
业务权威数据仍在 ai_project_* 各表，本模块不写库、不新增表；
布局坐标由前端本地保存，不进入该接口。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from ..db import query_all, query_one
from .project_detail_service import ProjectDetailService

# 逐镜 chunk 状态 → 工作台节点状态的收敛映射（对齐 job_payload._CHUNK_SHOT_STATUS）
_CHUNK_STATUS_ALIASES = {
    "succeeded": "succeeded",
    "awaiting_refine": "awaiting_refine",
    "submitted": "running",
    "running": "running",
}


def parse_extra(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def character_looks(asset: dict[str, Any]) -> list[dict[str, Any]]:
    """与前端 canvasIdentities 对齐：造型缺失时回退为单张默认形象。"""
    extra = parse_extra(asset.get("extra_json"))
    looks = extra.get("identities")
    if isinstance(looks, list) and looks:
        return [item for item in looks if isinstance(item, dict)]
    return [{"id": "look-default", "name": "初始造型", "image_url": asset.get("image_url") or ""}]


def asset_ready_state(asset: dict[str, Any]) -> tuple[bool, int, int, str]:
    """返回 (是否齐备, 已就绪数, 总数, 文案)，口径与前端 assetReadiness 一致。"""
    kind = str(asset.get("kind") or "")
    if kind == "character":
        looks = character_looks(asset)
        total = len(looks)
        ready = sum(1 for look in looks if str(look.get("image_url") or "").strip())
        label = f"{total} 套造型已就绪" if ready == total and total else "待完善造型"
        return ready >= max(1, total), ready, max(1, total), label
    extra = parse_extra(asset.get("extra_json"))
    if kind == "scene":
        ready = bool(str(extra.get("master_url") or asset.get("image_url") or "").strip())
        return ready, 1 if ready else 0, 1, "主视角已就绪" if ready else "缺场景设定图"
    ready = bool(str(extra.get("reference_url") or asset.get("image_url") or "").strip())
    return ready, 1 if ready else 0, 1, "参考图已就绪" if ready else "缺道具设定图"


def _beat_text(beat: dict[str, Any]) -> str:
    dialogue = str(beat.get("dialogue") or "").strip()
    action = str(beat.get("action") or "").strip()
    text = dialogue or action
    return text[:80]


def beat_view(beat: dict[str, Any]) -> dict[str, Any]:
    sequence = beat.get("sequence") or beat.get("shot_num") or 0
    heading = str(beat.get("heading") or "").strip()
    video_url = str(beat.get("upscaled_video_url") or beat.get("video_url") or "").strip()
    h3_prompt = str(beat.get("h3_prompt") or "").strip()
    characters = [str(item) for item in (beat.get("character_ids") or []) if str(item).strip()]
    props = [str(item) for item in (beat.get("prop_ids") or []) if str(item).strip()]
    scene_id = str(beat.get("scene_id") or "").strip()
    return {
        "id": str(beat.get("id") or ""),
        "sequence": int(sequence) if sequence else 0,
        "kind": str(beat.get("kind") or "action"),
        "heading": heading,
        "title": heading or f"分镜 {sequence}",
        "text": _beat_text(beat),
        "speaker": str(beat.get("speaker") or "").strip(),
        "dialogue": str(beat.get("dialogue") or "").strip(),
        "character_ids": characters,
        "scene_id": scene_id,
        "prop_ids": props,
        "has_prompt": bool(h3_prompt),
        "has_video": bool(video_url),
        "video_url": video_url,
        "video_duration": str(beat.get("video_duration") or "").strip(),
        "awaiting_refine": False,
        "task_status": "idle",
    }


def referenced_asset_ids(beats: Iterable[dict[str, Any]], assets: list[dict[str, Any]]) -> set[str]:
    """收集本集镜头实际引用的资产 id；旧数据只有名字时按名字回退匹配。"""
    referenced: set[str] = set()
    name_to_id: dict[str, str] = {}
    for asset in assets:
        name = str(asset.get("name") or "").strip()
        if name:
            name_to_id.setdefault(name, str(asset.get("id") or ""))
    for beat in beats:
        view = beat if "has_prompt" in beat else beat_view(beat)
        referenced.update(item for item in view.get("character_ids") or [] if item)
        referenced.update(item for item in view.get("prop_ids") or [] if item)
        if view.get("scene_id"):
            referenced.add(str(view["scene_id"]))
        for name in [beat.get("scene")] if isinstance(beat, dict) else []:
            if name and str(name).strip() in name_to_id:
                referenced.add(name_to_id[str(name).strip()])
    return {item for item in referenced if item}


def beat_reference_ids(view: dict[str, Any]) -> set[str]:
    return {
        *(str(item) for item in (view.get("character_ids") or []) if str(item).strip()),
        *(str(item) for item in (view.get("prop_ids") or []) if str(item).strip()),
        *( [str(view.get("scene_id"))] if str(view.get("scene_id") or "").strip() else [] ),
    }


def derive_edges(beat_views: list[dict[str, Any]], referenced_ids: set[str]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    ordered = sorted(beat_views, key=lambda item: item.get("sequence") or 0)
    previous: Optional[str] = None
    for view in ordered:
        beat_id = view["id"]
        for asset_id in sorted(beat_reference_ids(view) & set(referenced_ids)):
            edges.append({
                "id": f"e-ref-{asset_id}-{beat_id}",
                "source": f"asset-{asset_id}",
                "target": f"beat-{beat_id}",
                "kind": "reference",
            })
        if previous:
            edges.append({"id": f"e-seq-{previous}-{beat_id}", "source": f"beat-{previous}", "target": f"beat-{beat_id}", "kind": "sequence"})
        edges.append({"id": f"e-out-{beat_id}", "source": f"beat-{beat_id}", "target": "episode-video", "kind": "output"})
        previous = beat_id
    return edges


def job_shot_statuses(job_rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    """从 video_generation 任务里提取每个 beat 的最新状态（调用方按 created_at 倒序传入）。

    最新提到某 beat 的任务决定其状态；整任务失败（status=failed 且 render_plan.status=failed）
    时，其中未出片、也非二采待确认的镜标为 failed，让工作台「待修复」灯真实可用；
    已 succeeded 的镜优先按 succeeded 展示（beat 本身有成片时由调用方覆盖）。
    """
    statuses: dict[str, str] = {}
    for row in job_rows:
        payload = parse_extra(row.get("payload_json"))
        if not payload:
            continue
        plan = payload.get("render_plan")
        plan_failed = str(row.get("status") or "") == "failed" and isinstance(plan, dict) and plan.get("status") == "failed"
        raw_chunks = plan.get("chunks") if isinstance(plan, dict) else None
        if not isinstance(raw_chunks, list):
            continue
        chunk_stages: dict[str, str] = {}
        for chunk in raw_chunks:
            if not isinstance(chunk, dict):
                continue
            stage = _CHUNK_STATUS_ALIASES.get(str(chunk.get("status") or ""), "queued")
            for beat_id in chunk.get("shot_ids") or []:
                key = str(beat_id or "").strip()
                if key:
                    chunk_stages[key] = stage
        for beat_id, stage in chunk_stages.items():
            if beat_id in statuses:
                continue
            if stage == "succeeded":
                statuses[beat_id] = "succeeded"
            elif plan_failed and stage != "awaiting_refine":
                statuses[beat_id] = "failed"
            else:
                statuses[beat_id] = stage
    return statuses


def compute_progress(
    beats: list[dict[str, Any]],
    asset_states: list[dict[str, Any]],
    has_script: bool,
) -> dict[str, Any]:
    total = len(beats)
    prompts_done = sum(1 for item in beats if item.get("has_prompt"))
    shots_done = sum(1 for item in beats if item.get("has_video"))
    assets_done = sum(1 for item in asset_states if item.get("ready"))
    assets_total = len(asset_states)

    def stage(done: int, stage_total: int, *, locked: bool = False) -> dict[str, Any]:
        if locked:
            return {"done": 0, "total": 0, "ratio": 0.0, "status": "locked"}
        ratio = (done / stage_total) if stage_total else 0.0
        status = "done" if stage_total and done >= stage_total else ("active" if stage_total else "empty")
        return {"done": done, "total": stage_total, "ratio": round(ratio, 4), "status": status}

    script_stage = stage(1 if total else 0, 1)
    if not total:
        script_stage["status"] = "active" if has_script else "empty"
    assets_stage = stage(assets_done, assets_total, locked=total == 0)
    prompts_stage = stage(prompts_done, total, locked=total == 0)
    shots_stage = stage(shots_done, total, locked=total == 0)
    stages = {"script": script_stage, "assets": assets_stage, "prompts": prompts_stage, "shots": shots_stage}
    ratios = [script_stage["ratio"], assets_stage["ratio"] if assets_total else None, prompts_stage["ratio"] if total else None, shots_stage["ratio"] if total else None]
    values = [item for item in ratios if item is not None]
    overall = round(sum(values) / len(values), 4) if values else 0.0
    return {
        "stages": stages,
        "overall_pct": int(overall * 100),
        "beats_total": total,
        "prompts_done": prompts_done,
        "shots_done": shots_done,
        "assets_total": assets_total,
        "assets_ready": assets_done,
    }


def compute_next_action(
    beats: list[dict[str, Any]],
    asset_states: list[dict[str, Any]],
    progress: dict[str, Any],
) -> dict[str, Any]:
    if not beats:
        return {"kind": "go-script", "label": "本集还没有分镜，先回剧本阶段完成拆解", "target": "content"}
    stages = progress.get("stages") or {}
    # 提示词先行：缺指令的镜最先补（生成指令不依赖素材图片）。
    if (stages.get("prompts") or {}).get("status") == "active":
        pending = next((item for item in beats if not item.get("has_prompt")), None)
        if pending:
            return {
                "kind": "make-prompt",
                "label": f"第 {pending.get('sequence')} 镜还差生成指令，先生成 H3 提示词",
                "beat_id": pending.get("id"),
                "target": "workbench",
            }
    shots_stage = (stages.get("shots") or {}).get("status")
    if shots_stage == "active":
        running = next((item for item in beats if item.get("task_status") in {"running", "queued"}), None)
        if running:
            remaining = sum(1 for item in beats if not item.get("has_video"))
            return {
                "kind": "wait",
                "label": f"正在生成，还差 {remaining} 镜出片",
                "beat_id": running.get("id"),
                "target": "workbench",
            }
        awaiting = next((item for item in beats if item.get("task_status") == "awaiting_refine"), None)
        if awaiting:
            return {
                "kind": "confirm",
                "label": f"第 {awaiting.get('sequence')} 镜有一采预览待确认，去工坊确认后继续",
                "beat_id": awaiting.get("id"),
                "target": "workshop",
            }
        # 仅在「有引用资产但未齐备」时先去补素材；本集不引用任何资产（empty/locked）不构成阻塞。
        if (stages.get("assets") or {}).get("status") == "active":
            missing = [item for item in asset_states if not item.get("ready")]
            names = "、".join(str(item.get("name") or "") for item in missing[:2])
            more = f" 等 {len(missing)} 项" if len(missing) > 2 else ""
            return {"kind": "fix-assets", "label": f"「{names}」{more}还缺出片素材，先补齐", "target": "assets"}
        pending = next((item for item in beats if not item.get("has_video")), None)
        if pending:
            remaining = sum(1 for item in beats if not item.get("has_video"))
            return {
                "kind": "render",
                "label": f"还差 {remaining} 镜出片，从第 {pending.get('sequence')} 镜开始",
                "beat_id": pending.get("id"),
                "target": "workbench",
            }
    return {"kind": "compose", "label": "本集全部出片，去智能剪辑合成整集", "target": "edit"}


class WorkbenchService:
    """聚合一集的工作台视图。"""

    @classmethod
    def get_workbench(cls, project_id: str, episode_id: Optional[str] = None) -> dict[str, Any]:
        project = query_one("SELECT id, name, description, cover_url FROM ai_projects WHERE id = %s", (project_id,))
        if not project:
            raise ValueError("项目不存在")

        if episode_id:
            episode = query_one(
                "SELECT id FROM ai_project_episodes WHERE id = %s AND project_id = %s",
                (episode_id, project_id),
            )
            if not episode:
                raise ValueError("分集不存在")
        else:
            episode = query_one(
                "SELECT id FROM ai_project_episodes WHERE project_id = %s ORDER BY episode_num ASC, created_at ASC LIMIT 1",
                (project_id,),
            )
            if not episode:
                raise ValueError("该项目还没有分集，请先在剧本阶段完成拆解")

        detail = ProjectDetailService.get_episode_detail(project_id, episode["id"])
        asset_rows = query_all(
            "SELECT id, kind, name, image_url, extra_json FROM ai_project_assets WHERE project_id = %s ORDER BY created_at ASC, id ASC",
            (project_id,),
        )
        raw_beats = [item for item in (detail.get("beats") or []) if isinstance(item, dict)]
        beat_views = [item for item in (beat_view(beat) for beat in raw_beats) if item["id"]]
        beat_views.sort(key=lambda item: item.get("sequence") or 0)

        referenced_ids = referenced_asset_ids(raw_beats, asset_rows)
        asset_nodes: list[dict[str, Any]] = []
        asset_states: list[dict[str, Any]] = []
        for asset in asset_rows:
            asset_id = str(asset.get("id") or "")
            if asset_id not in referenced_ids:
                continue
            ready, done, total, label = asset_ready_state(asset)
            asset_states.append({"id": asset_id, "kind": asset.get("kind"), "name": asset.get("name"), "ready": ready})
            asset_nodes.append({
                "id": asset_id,
                "kind": str(asset.get("kind") or "prop"),
                "name": str(asset.get("name") or ""),
                "image_url": str(asset.get("image_url") or ""),
                "ready": ready,
                "ready_label": label,
                "looks_total": total,
                "looks_ready": done,
                "ref_beats": sum(1 for view in beat_views if asset_id in beat_reference_ids(view)),
            })

        # 任务实时状态：只看本集的 video_generation 任务，最近优先。
        job_rows = query_all(
            "SELECT status, payload_json FROM ai_project_jobs WHERE project_id = %s AND job_type = 'video_generation' ORDER BY created_at DESC, id DESC LIMIT 40",
            (project_id,),
        )
        episode_id_value = episode["id"]
        live_statuses: dict[str, str] = {}
        for row in job_rows:
            payload = parse_extra(row.get("payload_json"))
            if not payload:
                continue
            if str(payload.get("episode_id") or "") != str(episode_id_value):
                continue
            for beat_id, stage in job_shot_statuses([row]).items():
                live_statuses[beat_id] = stage
        for view in beat_views:
            if view.get("has_video"):
                view["task_status"] = "succeeded"
                continue
            stage = live_statuses.get(view["id"])
            if stage:
                view["task_status"] = stage
                if stage == "awaiting_refine":
                    view["awaiting_refine"] = True

        progress = compute_progress(beat_views, asset_states, has_script=bool(str(detail.get("script_text") or "").strip()))
        next_action = compute_next_action(beat_views, asset_states, progress)

        return {
            "project": {
                "id": project["id"],
                "name": project["name"],
                "cover_url": project.get("cover_url") or "",
            },
            "episode": {
                "id": detail["id"],
                "number": detail["number"],
                "title": detail["title"],
                "status": detail["status"],
                "script_text": detail.get("script_text") or "",
                "summary": detail.get("content_summary") or "",
                "episode_video_url": detail.get("episode_video_url") or "",
                "episode_video_job_id": detail.get("episode_video_job_id") or "",
            },
            "assets": asset_nodes,
            "beats": beat_views,
            "edges": derive_edges(beat_views, referenced_ids),
            "progress": progress,
            "next_action": next_action,
        }

    @classmethod
    def list_episode_options(cls, project_id: str) -> list[dict[str, Any]]:
        rows = query_all(
            "SELECT id, episode_num, title, shots_count, status FROM ai_project_episodes WHERE project_id = %s ORDER BY episode_num ASC",
            (project_id,),
        )
        return [
            {
                "id": row["id"],
                "number": row["episode_num"],
                "title": row["title"],
                "shots_count": row.get("shots_count") or 0,
                "status": row.get("status") or "draft",
            }
            for row in rows
        ]

    @classmethod
    def project_overview(cls, project_id: str) -> dict[str, Any]:
        """项目级总览：全部集的四关进度聚合，供工作台「全部集」模式。

        只读轻量：直接读 ai_project_episodes.data_json 的 beats 计数，
        不触发 get_episode_detail 的兜底拆解写库；任务活跃状态只看最近 40 条视频任务。
        """
        project = query_one("SELECT id, name, description, cover_url FROM ai_projects WHERE id = %s", (project_id,))
        if not project:
            raise ValueError("项目不存在")
        episode_rows = query_all(
            "SELECT id, episode_num, title, status, data_json FROM ai_project_episodes WHERE project_id = %s ORDER BY episode_num ASC, created_at ASC",
            (project_id,),
        )
        job_rows = query_all(
            "SELECT status, payload_json FROM ai_project_jobs WHERE project_id = %s AND job_type = 'video_generation' ORDER BY created_at DESC, id DESC LIMIT 40",
            (project_id,),
        )
        live_by_episode: dict[str, dict[str, str]] = {}
        for row in job_rows:
            payload = parse_extra(row.get("payload_json"))
            if not payload:
                continue
            episode_key = str(payload.get("episode_id") or "")
            if not episode_key:
                continue
            statuses = live_by_episode.setdefault(episode_key, {})
            for beat_id, stage in job_shot_statuses([row]).items():
                priority = {"failed": 4, "awaiting_refine": 3, "running": 2, "queued": 1}
                current = statuses.get(beat_id)
                if current is None or priority.get(stage, 0) >= priority.get(current, 0):
                    statuses[beat_id] = stage

        episodes: list[dict[str, Any]] = []
        totals = {"beats": 0, "prompts": 0, "shots": 0}
        for row in episode_rows:
            data = parse_extra(row.get("data_json"))
            raw_beats = [item for item in (data.get("beats") or []) if isinstance(item, dict)]
            views = [beat_view(item) for item in raw_beats if str(item.get("id") or "").strip()]
            views.sort(key=lambda item: item.get("sequence") or 0)
            live = live_by_episode.get(str(row["id"]) or "", {})
            for view in views:
                if view.get("has_video"):
                    view["task_status"] = "succeeded"
                elif view["id"] in live:
                    view["task_status"] = live[view["id"]]
            beats_total = len(views)
            prompts_done = sum(1 for item in views if item.get("has_prompt"))
            shots_done = sum(1 for item in views if item.get("has_video"))
            running = any(item.get("task_status") in {"running", "queued"} for item in views)
            awaiting = any(item.get("task_status") == "awaiting_refine" for item in views)
            failed = any(item.get("task_status") == "failed" for item in views)
            overall = round(((prompts_done + shots_done) / (beats_total * 2)) if beats_total else 0.0, 4)
            totals["beats"] += beats_total
            totals["prompts"] += prompts_done
            totals["shots"] += shots_done
            episodes.append({
                "id": row["id"],
                "number": row["episode_num"],
                "title": row["title"],
                "status": row.get("status") or "draft",
                "beats_total": beats_total,
                "prompts_done": prompts_done,
                "shots_done": shots_done,
                "overall_pct": int(overall * 100),
                "running": running,
                "awaiting_refine": awaiting,
                "failed": failed,
                "episode_video_url": str(data.get("episode_video_url") or ""),
            })

        project_total = len(episodes)
        project_overall = round(((totals["prompts"] + totals["shots"]) / (totals["beats"] * 2)) if totals["beats"] else 0.0, 4)
        next_action = cls._overview_next_action(episodes)
        return {
            "project": {
                "id": project["id"],
                "name": project["name"],
                "cover_url": project.get("cover_url") or "",
            },
            "episodes": episodes,
            "project_progress": {
                "episodes_total": project_total,
                "beats_total": totals["beats"],
                "prompts_done": totals["prompts"],
                "shots_done": totals["shots"],
                "overall_pct": int(project_overall * 100),
            },
            "next_action": next_action,
        }

    @classmethod
    def _overview_next_action(cls, episodes: list[dict[str, Any]]) -> dict[str, Any]:
        if not episodes:
            return {"kind": "go-script", "label": "还没有分集，先回剧本阶段完成拆解并同步分镜", "target": "content"}
        for episode in episodes:
            if episode.get("running"):
                return {
                    "kind": "wait",
                    "label": f"第 {episode['number']} 集正在出片，等待完成",
                    "episode_id": episode["id"],
                    "target": "workbench",
                }
        for episode in episodes:
            if episode.get("awaiting_refine"):
                return {
                    "kind": "confirm",
                    "label": f"第 {episode['number']} 集有一采预览待确认",
                    "episode_id": episode["id"],
                    "target": "workshop",
                }
        for episode in episodes:
            beats_total = episode.get("beats_total") or 0
            if not beats_total:
                return {
                    "kind": "go-episode",
                    "label": f"第 {episode['number']} 集还没有分镜，先完成拆解",
                    "episode_id": episode["id"],
                    "target": "workbench",
                }
            if episode.get("failed"):
                return {
                    "kind": "go-episode",
                    "label": f"第 {episode['number']} 集有镜头出片失败，去重拍",
                    "episode_id": episode["id"],
                    "target": "workbench",
                }
            if (episode.get("prompts_done") or 0) < beats_total:
                return {
                    "kind": "go-episode",
                    "label": f"第 {episode['number']} 集还差 {beats_total - (episode.get('prompts_done') or 0)} 镜生成指令，继续制作",
                    "episode_id": episode["id"],
                    "target": "workbench",
                }
            if (episode.get("shots_done") or 0) < beats_total:
                remaining = beats_total - (episode.get("shots_done") or 0)
                return {
                    "kind": "go-episode",
                    "label": f"第 {episode['number']} 集还差 {remaining} 镜出片，继续制作",
                    "episode_id": episode["id"],
                    "target": "workbench",
                }
        return {"kind": "compose", "label": "全部集镜头已出片，去智能剪辑逐集合成", "target": "edit"}
