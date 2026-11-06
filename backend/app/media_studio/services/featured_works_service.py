from __future__ import annotations

import json
import uuid
from typing import Any

from ..db import execute_sql, now_str, query_all, query_one
from ..models import ProjectCreateRequest
from .project_service import ProjectService

FEATURED_STATUS = "published"
FEATURED_SNAPSHOT_VERSION = 2
MAX_MEDIA_URL_LENGTH = 2048
MAX_DOCUMENT_CHARS = 200_000
MAX_PROMPT_CHARS = 4_000
DISPLAY_BEAT_FIELDS = (
    "heading",
    "speaker",
    "dialogue",
    "action",
    "camera",
    "scene",
    "time_of_day",
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _media_url(value: Any) -> str:
    text = _clean_text(value)
    if not text or len(text) > MAX_MEDIA_URL_LENGTH:
        return ""
    if text.startswith(("http://", "https://", "/")):
        return text
    return ""


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _display_beat(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    beat = {key: _clean_text(raw.get(key)) for key in DISPLAY_BEAT_FIELDS}
    beat["id"] = _clean_text(raw.get("id"))
    beat["image_url"] = _media_url(raw.get("render_url") or raw.get("sketch_url") or raw.get("triptych_url"))
    beat["video_url"] = _media_url(raw.get("video_url") or raw.get("upscaled_video_url"))
    try:
        beat["duration"] = int(float(raw.get("video_duration") or 0))
    except (TypeError, ValueError):
        beat["duration"] = 0
    # 视频生成提示词：优先最终送生成的 h3_prompt，回退到中文拼接与视觉描述。
    beat["prompt"] = _clean_text(raw.get("h3_prompt") or raw.get("video_prompt_zh") or raw.get("visual_prompt"))[:MAX_PROMPT_CHARS]
    if not any(beat.get(key) for key in ("heading", "speaker", "dialogue", "action", "image_url", "video_url", "prompt")):
        return None
    return beat


def _display_asset(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _clean_text(raw.get("id")),
        "kind": _clean_text(raw.get("kind")) or "character",
        "name": _clean_text(raw.get("name")),
        "role": _clean_text(raw.get("role")),
        "description": _clean_text(raw.get("description")),
        "visual_prompt": _clean_text(raw.get("visual_prompt"))[:MAX_PROMPT_CHARS],
        "image_url": _media_url(raw.get("image_url")),
    }


def _display_document(raw: dict[str, Any]) -> dict[str, Any] | None:
    raw_text = str(raw.get("raw_text") or "")
    if not raw_text.strip():
        return None
    return {"filename": _clean_text(raw.get("filename")) or "剧本文档", "raw_text": raw_text[:MAX_DOCUMENT_CHARS]}


def _storage_beat(raw: Any) -> dict[str, Any] | None:
    """把展示 beat 还原成剧集工坊 data_json 里的 beat 存储结构。"""
    if not isinstance(raw, dict):
        return None
    beat = {key: _clean_text(raw.get(key)) for key in DISPLAY_BEAT_FIELDS}
    beat["id"] = _clean_text(raw.get("id")) or f"beat-{uuid.uuid4().hex[:10]}"
    if raw.get("image_url"):
        beat["render_url"] = _media_url(raw.get("image_url"))
    if raw.get("video_url"):
        beat["video_url"] = _media_url(raw.get("video_url"))
    try:
        duration = int(float(raw.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0
    if duration > 0:
        beat["video_duration"] = duration
    if raw.get("prompt"):
        beat["h3_prompt"] = _clean_text(raw.get("prompt"))[:MAX_PROMPT_CHARS]
    return beat


def _remap_canvas_asset_ids(canvas: dict[str, Any], asset_id_map: dict[str, str]) -> dict[str, Any]:
    """画布资产投影节点引用的是原项目资产 ID，复制后要换成新项目的资产 ID。"""
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    edges = canvas.get("edges") if isinstance(canvas.get("edges"), list) else []
    viewport = canvas.get("viewport") if isinstance(canvas.get("viewport"), dict) else None
    if not asset_id_map:
        return {"nodes": nodes, "edges": edges, "viewport": viewport}
    remapped: list[Any] = []
    for node in nodes:
        if isinstance(node, dict):
            data = node.get("data")
            if isinstance(data, dict) and data.get("assetId") in asset_id_map:
                node = {**node, "data": {**data, "assetId": asset_id_map[data["assetId"]]}}
        remapped.append(node)
    return {"nodes": remapped, "edges": edges, "viewport": viewport}


def _clean_canvas_content(content: Any) -> dict[str, Any] | None:
    """提取绑定画布草稿的只读内容；画布为空或结构异常时返回 None。"""
    data = content if isinstance(content, dict) else _json_dict(content)
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None
    return {
        "nodes": nodes[:3000],
        "edges": data.get("edges") if isinstance(data.get("edges"), list) else [],
        "viewport": data.get("viewport") if isinstance(data.get("viewport"), dict) else None,
    }


def build_featured_snapshot(
    project: dict[str, Any],
    documents: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    canvas_content: Any = None,
) -> dict[str, Any]:
    """只保留展示需要的字段，发布后不再依赖原项目的实时编辑状态。"""
    asset_items = [_display_asset(item) for item in assets]
    episode_items: list[dict[str, Any]] = []
    for raw in sorted(episodes, key=lambda item: int(item.get("episode_num") or 0)):
        data = _json_dict(raw.get("data_json"))
        beats = [beat for beat in (_display_beat(item) for item in data.get("beats") or []) if beat]
        episode_items.append({
            "id": _clean_text(raw.get("id")),
            "number": int(raw.get("episode_num") or len(episode_items) + 1),
            "title": _clean_text(raw.get("title")) or f"第 {len(episode_items) + 1} 集",
            "status": _clean_text(raw.get("status")),
            "script_text": str(raw.get("script_text") or ""),
            "summary": _clean_text(data.get("summary")),
            "episode_video_url": _media_url(data.get("episode_video_url")),
            "beats": beats,
        })

    cover_url = _media_url(project.get("cover_url"))
    if not cover_url:
        for kind in ("character", "scene", "prop"):
            cover_url = next((item["image_url"] for item in asset_items if item["kind"] == kind and item["image_url"]), "")
            if cover_url:
                break
    if not cover_url:
        cover_url = next((beat["image_url"] for episode in episode_items for beat in episode["beats"] if beat["image_url"]), "")

    document_items = [item for item in (_display_document(raw) for raw in documents) if item]
    snapshot: dict[str, Any] = {
        "version": FEATURED_SNAPSHOT_VERSION,
        "project": {
            "id": _clean_text(project.get("id")),
            "name": _clean_text(project.get("name")),
            "description": _clean_text(project.get("description")),
            "cover_url": cover_url,
        },
        "documents": document_items,
        "episodes": episode_items,
        "assets": [item for item in asset_items if item["name"]],
    }
    canvas = _clean_canvas_content(canvas_content)
    if canvas:
        snapshot["canvas"] = canvas
    return snapshot


class FeaturedWorksService:
    @staticmethod
    def list_published() -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in query_all(
                """SELECT id, project_id, title, summary, cover_url, episode_count, shot_count,
                          sort_order, published_at, updated_at
                FROM ai_featured_works
                WHERE status = %s
                ORDER BY sort_order ASC, published_at DESC""",
                (FEATURED_STATUS,),
            )
        ]

    @staticmethod
    def get_published(featured_id: str) -> dict[str, Any] | None:
        row = query_one(
            "SELECT * FROM ai_featured_works WHERE id = %s AND status = %s",
            (featured_id, FEATURED_STATUS),
        )
        if not row:
            return None
        item = dict(row)
        snapshot = _json_dict(item.pop("snapshot_json", None))
        item["snapshot"] = snapshot
        return item

    @staticmethod
    def publish(payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        project_id = _clean_text(payload.get("project_id"))
        if not project_id:
            raise ValueError("请选择要发布的短剧")
        project = query_one(
            "SELECT id, name, description, cover_url FROM ai_projects WHERE id = %s",
            (project_id,),
        )
        if not project:
            raise ValueError("短剧不存在或已被删除")

        documents = query_all(
            "SELECT filename, raw_text FROM ai_project_documents WHERE project_id = %s ORDER BY updated_at ASC",
            (project_id,),
        )
        episodes = query_all(
            "SELECT * FROM ai_project_episodes WHERE project_id = %s ORDER BY episode_num ASC",
            (project_id,),
        )
        assets = query_all(
            "SELECT id, kind, name, role, description, visual_prompt, image_url FROM ai_project_assets WHERE project_id = %s ORDER BY updated_at DESC",
            (project_id,),
        )
        # 创作过程画布：取绑定本项目的画布草稿快照（存在即整份带出，画布为空则省略）。
        canvas_content: Any = None
        canvas_row = query_one(
            "SELECT id FROM canvas_projects WHERE linked_director_project_id = %s AND deleted_at IS NULL LIMIT 1",
            (project_id,),
        )
        if canvas_row:
            draft_row = query_one("SELECT content FROM canvas_drafts WHERE canvas_id = %s", (canvas_row["id"],))
            canvas_content = _json_dict(draft_row.get("content")) if draft_row else {}
        snapshot = build_featured_snapshot(project, documents, episodes, assets, canvas_content=canvas_content)
        has_script = any(item["raw_text"].strip() for item in snapshot["documents"]) or any(
            episode["script_text"].strip() or episode["beats"] for episode in snapshot["episodes"]
        )
        if not has_script:
            raise ValueError("该短剧还没有可展示的剧本内容")

        title = _clean_text(payload.get("title")) or _clean_text(project.get("name")) or "未命名短剧"
        summary = _clean_text(payload.get("summary")) if "summary" in payload else _clean_text(project.get("description"))
        cover_url = _media_url(payload.get("cover_url")) or snapshot["project"]["cover_url"]
        sort_order = payload.get("sort_order")
        try:
            sort_order = int(sort_order or 0)
        except (TypeError, ValueError):
            sort_order = 0
        sort_order = max(0, min(sort_order, 999))

        shot_count = sum(len(episode["beats"]) for episode in snapshot["episodes"])
        episode_count = len(snapshot["episodes"])
        snapshot["project"].update({"name": title, "description": summary, "cover_url": cover_url})

        now = now_str()
        existing = query_one("SELECT id, published_at FROM ai_featured_works WHERE project_id = %s", (project_id,))
        if existing:
            featured_id = str(existing["id"])
            published_at = str(existing.get("published_at") or now)
            execute_sql(
                """UPDATE ai_featured_works
                SET title = %s, summary = %s, cover_url = %s, snapshot_json = %s,
                    episode_count = %s, shot_count = %s, sort_order = %s,
                    status = %s, published_by = %s, published_at = %s, updated_at = %s
                WHERE id = %s""",
                (title, summary, cover_url, json.dumps(snapshot, ensure_ascii=False), episode_count,
                 shot_count, sort_order, FEATURED_STATUS, actor_user_id, published_at, now, featured_id),
            )
        else:
            featured_id = f"featured-{uuid.uuid4().hex[:16]}"
            execute_sql(
                """INSERT INTO ai_featured_works
                (id, project_id, title, summary, cover_url, snapshot_json, episode_count, shot_count,
                 sort_order, status, published_by, published_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (featured_id, project_id, title, summary, cover_url, json.dumps(snapshot, ensure_ascii=False),
                 episode_count, shot_count, sort_order, FEATURED_STATUS, actor_user_id, now, now),
            )
        created = FeaturedWorksService.get_published(featured_id)
        if not created:
            raise ValueError("精选作品发布失败")
        return created

    @staticmethod
    def unpublish(featured_id: str) -> bool:
        return execute_sql("DELETE FROM ai_featured_works WHERE id = %s", (featured_id,)) > 0

    @staticmethod
    def copy_to_user(featured_id: str, owner_user_id: str, canvas_store: Any = None) -> dict[str, Any]:
        """把精选作品快照复制成当前用户自己的可编辑短剧项目。"""
        work = FeaturedWorksService.get_published(featured_id)
        if not work:
            raise ValueError("精选作品不存在或已下架")
        snapshot = work["snapshot"] or {}
        episodes = [item for item in snapshot.get("episodes") or [] if isinstance(item, dict)]
        assets = [item for item in snapshot.get("assets") or [] if isinstance(item, dict)]
        documents = [item for item in snapshot.get("documents") or [] if isinstance(item, dict)]
        if not documents and not any(item.get("script_text") or item.get("beats") for item in episodes):
            raise ValueError("该精选作品还没有可复制的内容")

        source_name = _clean_text(work.get("title")) or _clean_text((snapshot.get("project") or {}).get("name")) or "未命名短剧"
        copy_name = f"{source_name}（副本）"[:255]
        created = ProjectService.create_project(
            ProjectCreateRequest(
                name=copy_name,
                description=_clean_text(work.get("summary")) or _clean_text((snapshot.get("project") or {}).get("description")),
                cover_url=_media_url(work.get("cover_url")) or None,
            ),
            owner_user_id=owner_user_id,
        )
        project_id = created.id
        now = now_str()

        asset_id_map: dict[str, str] = {}
        asset_count = 0
        for item in assets:
            name = _clean_text(item.get("name"))[:128]
            if not name:
                continue
            asset_id = f"ast-{uuid.uuid4().hex[:12]}"
            asset_count += 1
            if _clean_text(item.get("id")):
                asset_id_map[_clean_text(item.get("id"))] = asset_id
            execute_sql(
                """INSERT INTO ai_project_assets
                (id, project_id, kind, name, role, description, visual_prompt, image_url, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (asset_id, project_id, _clean_text(item.get("kind")) or "character", name,
                 _clean_text(item.get("role")), _clean_text(item.get("description")),
                 _clean_text(item.get("visual_prompt")), _media_url(item.get("image_url")) or None, now, now),
            )

        beat_count = 0
        for index, item in enumerate(episodes):
            beats = [beat for beat in (_storage_beat(raw) for raw in item.get("beats") or []) if beat]
            beat_count += len(beats)
            try:
                number = int(item.get("number") or index + 1)
            except (TypeError, ValueError):
                number = index + 1
            data_json = {
                "summary": _clean_text(item.get("summary")),
                "episode_video_url": _media_url(item.get("episode_video_url")),
                "beats": beats,
            }
            execute_sql(
                """INSERT INTO ai_project_episodes
                (id, project_id, episode_num, title, status, script_text, shots_count, data_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'script_ready', %s, %s, %s, %s, %s)""",
                (f"ep-{uuid.uuid4().hex[:12]}", project_id, number,
                 (_clean_text(item.get("title")) or f"第 {number} 集")[:255], str(item.get("script_text") or ""),
                 len(beats), json.dumps(data_json, ensure_ascii=False), now, now),
            )

        for item in documents:
            raw_text = str(item.get("raw_text") or "")
            if not raw_text.strip():
                continue
            execute_sql(
                """INSERT INTO ai_project_documents
                (id, project_id, filename, file_size, input_mode, status, spine_template, visual_style, raw_text, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'paste', 'ready', 'drama', 'chinese_period_drama', %s, %s, %s)""",
                (f"doc-{uuid.uuid4().hex[:12]}", project_id, (_clean_text(item.get("filename")) or "剧本文档")[:255],
                 len(raw_text.encode("utf-8")), raw_text, now, now),
            )

        canvas = snapshot.get("canvas") if isinstance(snapshot.get("canvas"), dict) else None
        canvas_nodes = canvas.get("nodes") if canvas else None
        if canvas_store and isinstance(canvas_nodes, list) and canvas_nodes:
            try:
                linked = canvas_store.get_or_create_linked(owner_user_id, project_id, f"资产画布 · {copy_name}")
                remapped = _remap_canvas_asset_ids(canvas, asset_id_map)
                canvas_store.save_draft(
                    owner_user_id, linked["id"], 0,
                    json.dumps({"schemaVersion": 2, **remapped}, ensure_ascii=False),
                )
            except Exception:  # 画布复制失败不影响项目本身
                pass

        return {
            "project_id": project_id,
            "name": copy_name,
            "episode_count": len(episodes),
            "shot_count": beat_count,
            "asset_count": asset_count,
        }
