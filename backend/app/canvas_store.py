from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .storage import JobStore

EMPTY_CANVAS_CONTENT = json.dumps({"nodes": [], "edges": []}, ensure_ascii=False, separators=(",", ":"))
MAX_CONTENT_BYTES = 8 * 1024 * 1024
MAX_NODES = 3000
MAX_EDGES = 6000
MAX_VERSIONS = 200
MAX_TAGS = 8
MAX_TAG_LENGTH = 24
PREVIEW_MAX_ITEMS = 120
PREVIEW_MAX_LINKS = 80
PREVIEW_MAX_URLS = 12
PREVIEW_MAX_URL_LENGTH = 768
PREVIEW_MAX_BYTES = 48 * 1024
PREVIEW_MAX_COVERS = 3
PREVIEW_MAX_COVER_LENGTH = 64_000
PREVIEW_COVER_BUDGET = 36 * 1024
PREVIEW_COVER_PATTERN = re.compile(r"data:image/(?:jpeg|webp|png);base64,[A-Za-z0-9+/]+={0,2}")


class CanvasNotFoundError(LookupError):
    pass


class CanvasConflictError(RuntimeError):
    def __init__(self, current_version: int) -> None:
        super().__init__(f"画布已在其他窗口更新为版本 {current_version}")
        self.current_version = current_version


class CanvasValidationError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def normalize_canvas_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in tags:
        tag = str(raw).strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise CanvasValidationError(f"单个标签不能超过 {MAX_TAG_LENGTH} 个字符")
        if tag not in normalized:
            normalized.append(tag)
    if len(normalized) > MAX_TAGS:
        raise CanvasValidationError(f"标签不能超过 {MAX_TAGS} 个")
    return normalized


def decode_canvas_tags(raw: Any) -> list[str]:
    try:
        payload = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [
        tag.strip()
        for tag in payload[:MAX_TAGS]
        if isinstance(tag, str) and tag.strip() and len(tag.strip()) <= MAX_TAG_LENGTH
    ]


_PREVIEW_NODE_TYPES = {"text", "image", "video", "artboard", "generator", "unknown"}
_PREVIEW_FALLBACK_SIZES: dict[str, tuple[int, int]] = {
    "text": (260, 120),
    "image": (320, 200),
    "video": (360, 220),
    "artboard": (720, 480),
    "generator": (340, 240),
    "unknown": (260, 150),
}


def _preview_number(
    value: Any,
    *,
    minimum: float,
    maximum: float,
    fallback: float | None = None,
) -> float | None:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            number = float(value.strip())
        except ValueError:
            return fallback
    else:
        return fallback
    if not math.isfinite(number):
        return fallback
    return min(max(number, minimum), maximum)


def _preview_number_exact(
    value: Any,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    number = _preview_number(value, minimum=-math.inf, maximum=math.inf)
    if number is None or number < minimum or number > maximum:
        return None
    return number


def _preview_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or len(url) > PREVIEW_MAX_URL_LENGTH:
        return None
    if url.startswith("/") or url.lower().startswith(("http://", "https://")):
        return url
    return None


def _preview_node_type(node: dict[str, Any]) -> str:
    value = node.get("type")
    if isinstance(value, str) and value in _PREVIEW_NODE_TYPES:
        return value
    return "unknown"


def _preview_node_rect(node: dict[str, Any], node_type: str) -> tuple[float, float, float, float]:
    position = node.get("position") if isinstance(node.get("position"), dict) else {}
    x = _preview_number(position.get("x"), minimum=-1_000_000, maximum=1_000_000, fallback=0) or 0
    y = _preview_number(position.get("y"), minimum=-1_000_000, maximum=1_000_000, fallback=0) or 0
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    fallback_width, fallback_height = _PREVIEW_FALLBACK_SIZES[node_type]
    width = _preview_number(style.get("width"), minimum=1, maximum=20_000)
    if width is None:
        width = _preview_number(node.get("width"), minimum=1, maximum=20_000)
    height = _preview_number(style.get("height"), minimum=1, maximum=20_000)
    if height is None:
        height = _preview_number(node.get("height"), minimum=1, maximum=20_000)
    return x, y, width or fallback_width, height or fallback_height


def _preview_cover(node: dict[str, Any], node_type: str) -> str | None:
    if node_type != "video":
        return None
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    cover = data.get("cover")
    if not isinstance(cover, str):
        return None
    cover = cover.strip()
    if not cover or len(cover) > PREVIEW_MAX_COVER_LENGTH:
        return None
    url = _preview_url(data.get("url"))
    if not url or data.get("coverSource") != data.get("url"):
        return None
    return cover if PREVIEW_COVER_PATTERN.fullmatch(cover) else None


def _preview_node_url(node: dict[str, Any], node_type: str) -> str | None:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    if node_type == "image":
        return _preview_url(data.get("url"))
    if node_type == "generator" and data.get("resultKind") == "image":
        return _preview_url(data.get("resultUrl"))
    return None


def _preview_bytes(preview: dict[str, Any]) -> int:
    return len(json.dumps(preview, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _fit_canvas_preview(preview: dict[str, Any]) -> dict[str, Any]:
    if _preview_bytes(preview) <= PREVIEW_MAX_BYTES:
        return preview
    while _preview_bytes(preview) > PREVIEW_MAX_BYTES:
        covered = [item for item in preview["items"] if "cover" in item]
        if not covered:
            break
        covered[-1].pop("cover", None)
    if _preview_bytes(preview) <= PREVIEW_MAX_BYTES:
        return preview
    for item in preview["items"]:
        item.pop("url", None)
    if _preview_bytes(preview) <= PREVIEW_MAX_BYTES:
        return preview
    preview["links"] = []
    if _preview_bytes(preview) <= PREVIEW_MAX_BYTES:
        return preview
    for item_limit in (60, 30, 0):
        preview["items"] = preview["items"][:item_limit]
        preview["links"] = [
            [left, right]
            for left, right in preview["links"]
            if left < item_limit and right < item_limit
        ][:40]
        if _preview_bytes(preview) <= PREVIEW_MAX_BYTES:
            return preview
    return {
        "x": preview["x"],
        "y": preview["y"],
        "width": preview["width"],
        "height": preview["height"],
        "nodeCount": preview["nodeCount"],
        "items": [],
        "links": [],
    }


def build_canvas_preview(payload: dict[str, Any]) -> dict[str, Any]:
    raw_nodes = payload.get("nodes")
    raw_edges = payload.get("edges")
    nodes = [node for node in raw_nodes if isinstance(node, dict)] if isinstance(raw_nodes, list) else []
    edges = [edge for edge in raw_edges if isinstance(edge, dict)] if isinstance(raw_edges, list) else []
    shapes = [(node, _preview_node_type(node), _preview_node_rect(node, _preview_node_type(node))) for node in nodes]
    if shapes:
        min_x = min(rect[0] for _, _, rect in shapes)
        min_y = min(rect[1] for _, _, rect in shapes)
        max_x = max(rect[0] + rect[2] for _, _, rect in shapes)
        max_y = max(rect[1] + rect[3] for _, _, rect in shapes)
    else:
        min_x = min_y = max_x = max_y = 0

    step = max(1, math.ceil(len(shapes) / PREVIEW_MAX_ITEMS)) if shapes else 1
    selected = shapes[::step][:PREVIEW_MAX_ITEMS]
    items: list[dict[str, Any]] = []
    url_count = 0
    cover_count = 0
    cover_bytes = 0
    for node, node_type, (x, y, width, height) in selected:
        item: dict[str, Any] = {
            "type": node_type,
            "x": round(x),
            "y": round(y),
            "width": round(width),
            "height": round(height),
        }
        if url_count < PREVIEW_MAX_URLS:
            url = _preview_node_url(node, node_type)
            if url:
                item["url"] = url
                url_count += 1
        if cover_count < PREVIEW_MAX_COVERS:
            cover = _preview_cover(node, node_type)
            if cover and cover_bytes + len(cover) <= PREVIEW_COVER_BUDGET:
                item["cover"] = cover
                cover_count += 1
                cover_bytes += len(cover)
        items.append(item)

    index_by_node_id: dict[str, int] = {}
    for index, (node, _, _) in enumerate(selected):
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id:
            index_by_node_id.setdefault(node_id, index)

    links: list[list[int]] = []
    seen_links: set[tuple[int, int]] = set()
    for edge in edges:
        source = index_by_node_id.get(edge.get("source"))
        target = index_by_node_id.get(edge.get("target"))
        if source is None or target is None or source == target:
            continue
        pair = (source, target)
        if pair in seen_links:
            continue
        seen_links.add(pair)
        links.append([source, target])
        if len(links) >= PREVIEW_MAX_LINKS:
            break

    preview = {
        "x": round(min_x),
        "y": round(min_y),
        "width": round(max(0.0, max_x - min_x)),
        "height": round(max(0.0, max_y - min_y)),
        "nodeCount": len(nodes),
        "items": items,
        "links": links,
    }
    return _fit_canvas_preview(preview)


def decode_canvas_preview(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    x = _preview_number_exact(payload.get("x"), minimum=-1_000_000, maximum=1_000_000)
    y = _preview_number_exact(payload.get("y"), minimum=-1_000_000, maximum=1_000_000)
    width = _preview_number_exact(payload.get("width"), minimum=0, maximum=2_000_000)
    height = _preview_number_exact(payload.get("height"), minimum=0, maximum=2_000_000)
    raw_items = payload.get("items")
    if x is None or y is None or width is None or height is None or not isinstance(raw_items, list):
        return None
    items: list[dict[str, Any]] = []
    for raw_item in raw_items[:PREVIEW_MAX_ITEMS]:
        if not isinstance(raw_item, dict):
            return None
        item_type = raw_item.get("type")
        if not isinstance(item_type, str) or item_type not in _PREVIEW_NODE_TYPES:
            return None
        item_x = _preview_number_exact(raw_item.get("x"), minimum=-1_000_000, maximum=1_000_000)
        item_y = _preview_number_exact(raw_item.get("y"), minimum=-1_000_000, maximum=1_000_000)
        item_width = _preview_number_exact(raw_item.get("width"), minimum=1, maximum=20_000)
        item_height = _preview_number_exact(raw_item.get("height"), minimum=1, maximum=20_000)
        if item_x is None or item_y is None or item_width is None or item_height is None:
            return None
        item: dict[str, Any] = {
            "type": item_type,
            "x": round(item_x),
            "y": round(item_y),
            "width": round(item_width),
            "height": round(item_height),
        }
        url = _preview_url(raw_item.get("url"))
        if url:
            item["url"] = url
        cover = raw_item.get("cover")
        if item_type == "video" and isinstance(cover, str):
            cover = cover.strip()
            if cover and len(cover) <= PREVIEW_MAX_COVER_LENGTH and PREVIEW_COVER_PATTERN.fullmatch(cover):
                item["cover"] = cover
        items.append(item)
    links: list[list[int]] = []
    raw_links = payload.get("links")
    if isinstance(raw_links, list):
        for pair in raw_links[:PREVIEW_MAX_LINKS]:
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            if any(isinstance(value, bool) or not isinstance(value, int) for value in pair):
                continue
            left, right = pair
            if left == right or not (0 <= left < len(items) and 0 <= right < len(items)):
                continue
            links.append([left, right])
    node_count = payload.get("nodeCount")
    if isinstance(node_count, bool) or not isinstance(node_count, int) or node_count < 0:
        node_count = len(items)
    return {
        "x": round(x),
        "y": round(y),
        "width": round(width),
        "height": round(height),
        "nodeCount": min(node_count, 1_000_000),
        "items": items,
        "links": links,
    }


def _project_payload(row: Any) -> dict[str, Any]:
    project = dict(row)
    project["tags"] = decode_canvas_tags(project.pop("tags_json", None))
    project["is_favorite"] = bool(project.pop("is_favorite", 0))
    project["preview"] = decode_canvas_preview(project.pop("preview_json", None))
    return project


def parse_canvas_content(content: str) -> tuple[dict[str, Any], int]:
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise CanvasValidationError("画布内容超过 8MB 上限")
    try:
        payload = json.loads(content)
    except (TypeError, ValueError) as error:
        raise CanvasValidationError("画布内容不是合法 JSON") from error
    if not isinstance(payload, dict):
        raise CanvasValidationError("画布内容必须是 JSON 对象")
    if "nodes" not in payload or "edges" not in payload:
        raise CanvasValidationError("画布内容缺少 nodes 或 edges")
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise CanvasValidationError("画布节点和连线必须是数组")
    if len(nodes) > MAX_NODES or len(edges) > MAX_EDGES:
        raise CanvasValidationError("画布节点或连线数量超过上限")
    normalized = {**payload, "nodes": nodes, "edges": edges}
    return normalized, len(nodes)


def canvas_checksum(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


class CanvasStore:
    def __init__(self, store: JobStore) -> None:
        self._store = store

    def list_projects(self, owner_user_id: str, *, trashed: bool = False) -> list[dict[str, Any]]:
        deleted_filter = "p.deleted_at IS NOT NULL" if trashed else "p.deleted_at IS NULL"
        with self._store.connection() as connection:
            rows = connection.execute(
                f"""SELECT p.id, p.title, p.created_at, p.updated_at,
                           p.tags_json, p.is_favorite, p.deleted_at, p.preview_json,
                           d.version AS draft_version, d.node_count AS node_count,
                           d.updated_at AS draft_updated_at
                    FROM canvas_projects p
                    LEFT JOIN canvas_drafts d ON d.canvas_id = p.id
                    WHERE p.owner_user_id = ? AND {deleted_filter}
                    ORDER BY p.is_favorite DESC, COALESCE(d.updated_at, p.updated_at) DESC""",
                (owner_user_id,),
            ).fetchall()
        return [_project_payload(row) for row in rows]

    def create_project(self, owner_user_id: str, title: str) -> dict[str, Any]:
        title = title.strip() or "未命名画布"
        if len(title) > 120:
            raise CanvasValidationError("画布标题不能超过 120 个字符")
        now = _now()
        project_id = _new_id("canvas")
        node_count = 0
        version = 1
        checksum = canvas_checksum(EMPTY_CANVAS_CONTENT)
        preview_json = json.dumps(
            build_canvas_preview({"nodes": [], "edges": []}),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._store.connection() as connection:
            connection.execute(
                """INSERT INTO canvas_projects
                   (id, owner_user_id, title, preview_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (project_id, owner_user_id, title, preview_json, now, now),
            )
            connection.execute(
                """INSERT INTO canvas_drafts
                   (canvas_id, version, checksum, content, node_count, updated_by, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, version, checksum, EMPTY_CANVAS_CONTENT, node_count, owner_user_id, now),
            )
            connection.execute(
                """INSERT INTO canvas_draft_versions
                   (id, canvas_id, version, checksum, content, node_count, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (_new_id("canvasv"), project_id, version, checksum, EMPTY_CANVAS_CONTENT, node_count, owner_user_id, now),
            )
        return self.get_project(owner_user_id, project_id)

    def get_project(self, owner_user_id: str, project_id: str) -> dict[str, Any]:
        with self._store.connection() as connection:
            row = connection.execute(
                """SELECT p.id, p.title, p.created_at, p.updated_at,
                          p.tags_json, p.is_favorite, p.deleted_at, p.preview_json,
                          d.version, d.checksum, d.content, d.node_count, d.updated_at AS draft_updated_at
                   FROM canvas_projects p
                   LEFT JOIN canvas_drafts d ON d.canvas_id = p.id
                   WHERE p.id = ? AND p.owner_user_id = ? AND p.deleted_at IS NULL""",
                (project_id, owner_user_id),
            ).fetchone()
        if row is None:
            raise CanvasNotFoundError(project_id)
        project = _project_payload(row)
        project["version"] = int(project.pop("version") or 0)
        project["node_count"] = int(project.get("node_count") or 0)
        project["content"] = project.get("content") or EMPTY_CANVAS_CONTENT
        project["checksum"] = project.get("checksum") or canvas_checksum(project["content"])
        return project

    def update_project(
        self,
        owner_user_id: str,
        project_id: str,
        *,
        title: str | None = None,
        tags: list[str] | None = None,
        is_favorite: bool | None = None,
    ) -> dict[str, Any]:
        assignments: list[str] = []
        params: list[Any] = []
        if title is not None:
            title = title.strip()
            if not title:
                raise CanvasValidationError("请填写画布标题")
            if len(title) > 120:
                raise CanvasValidationError("画布标题不能超过 120 个字符")
            assignments.append("title = ?")
            params.append(title)
        if tags is not None:
            assignments.append("tags_json = ?")
            params.append(json.dumps(normalize_canvas_tags(tags), ensure_ascii=False, separators=(",", ":")))
        if is_favorite is not None:
            assignments.append("is_favorite = ?")
            params.append(1 if is_favorite else 0)
        if not assignments:
            raise CanvasValidationError("没有需要更新的字段")
        assignments.append("updated_at = ?")
        params.append(_now())
        params.extend([project_id, owner_user_id])
        with self._store.connection() as connection:
            cursor = connection.execute(
                f"UPDATE canvas_projects SET {', '.join(assignments)} "
                "WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL",
                tuple(params),
            )
            if cursor.rowcount == 0:
                raise CanvasNotFoundError(project_id)
        return self.get_project(owner_user_id, project_id)

    def rename_project(self, owner_user_id: str, project_id: str, title: str) -> dict[str, Any]:
        return self.update_project(owner_user_id, project_id, title=title)

    def trash_project(self, owner_user_id: str, project_id: str) -> dict[str, Any]:
        deleted_at = _now()
        with self._store.connection() as connection:
            cursor = connection.execute(
                """UPDATE canvas_projects SET deleted_at = ?
                   WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL""",
                (deleted_at, project_id, owner_user_id),
            )
            if cursor.rowcount == 0:
                raise CanvasNotFoundError(project_id)
        return {"id": project_id, "deleted_at": deleted_at}

    def restore_project(self, owner_user_id: str, project_id: str) -> dict[str, Any]:
        with self._store.connection() as connection:
            cursor = connection.execute(
                """UPDATE canvas_projects SET deleted_at = NULL
                   WHERE id = ? AND owner_user_id = ? AND deleted_at IS NOT NULL""",
                (project_id, owner_user_id),
            )
            if cursor.rowcount == 0:
                raise CanvasNotFoundError(project_id)
        return self.get_project(owner_user_id, project_id)

    def delete_project(self, owner_user_id: str, project_id: str) -> None:
        with self._store.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM canvas_projects WHERE id = ? AND owner_user_id = ?",
                (project_id, owner_user_id),
            )
            if cursor.rowcount == 0:
                raise CanvasNotFoundError(project_id)
            connection.execute("DELETE FROM canvas_draft_versions WHERE canvas_id = ?", (project_id,))
            connection.execute("DELETE FROM canvas_drafts WHERE canvas_id = ?", (project_id,))

    def save_draft(
        self,
        owner_user_id: str,
        project_id: str,
        base_version: int,
        content: str,
        checksum: str | None = None,
    ) -> dict[str, Any]:
        payload, node_count = parse_canvas_content(content)
        preview_json = json.dumps(build_canvas_preview(payload), ensure_ascii=False, separators=(",", ":"))
        actual_checksum = canvas_checksum(content)
        if checksum and checksum != actual_checksum:
            raise CanvasValidationError("画布内容校验失败，请重新加载后再保存")
        now = _now()
        with self._store.connection() as connection:
            row = connection.execute(
                """SELECT p.owner_user_id, d.version
                   FROM canvas_projects p
                   JOIN canvas_drafts d ON d.canvas_id = p.id
                   WHERE p.id = ? AND p.owner_user_id = ? AND p.deleted_at IS NULL""",
                (project_id, owner_user_id),
                for_update=True,
            ).fetchone()
            if row is None:
                raise CanvasNotFoundError(project_id)
            current_version = int(row["version"])
            if current_version != base_version:
                raise CanvasConflictError(current_version)
            next_version = current_version + 1
            connection.execute(
                "UPDATE canvas_drafts SET version = ?, checksum = ?, content = ?, node_count = ?, updated_by = ?, updated_at = ? WHERE canvas_id = ?",
                (next_version, actual_checksum, content, node_count, owner_user_id, now, project_id),
            )
            connection.execute(
                """INSERT INTO canvas_draft_versions
                   (id, canvas_id, version, checksum, content, node_count, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (_new_id("canvasv"), project_id, next_version, actual_checksum, content, node_count, owner_user_id, now),
            )
            connection.execute(
                "UPDATE canvas_projects SET updated_at = ?, preview_json = ? WHERE id = ?",
                (now, preview_json, project_id),
            )
            connection.execute(
                """DELETE FROM canvas_draft_versions
                   WHERE canvas_id = ? AND version <= ?""",
                (project_id, next_version - MAX_VERSIONS),
            )
        return {
            "id": project_id,
            "version": next_version,
            "checksum": actual_checksum,
            "node_count": node_count,
            "updated_at": now,
        }

    def list_versions(self, owner_user_id: str, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._store.connection() as connection:
            owner = connection.execute(
                "SELECT id FROM canvas_projects WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL",
                (project_id, owner_user_id),
            ).fetchone()
            if owner is None:
                raise CanvasNotFoundError(project_id)
            rows = connection.execute(
                """SELECT id, version, checksum, node_count, created_by, created_at
                   FROM canvas_draft_versions
                   WHERE canvas_id = ?
                   ORDER BY version DESC
                   LIMIT ?""",
                (project_id, max(1, min(limit, 200))),
            ).fetchall()
        return [dict(row) for row in rows]

    def restore_version(self, owner_user_id: str, project_id: str, version: int) -> dict[str, Any]:
        with self._store.connection() as connection:
            row = connection.execute(
                """SELECT v.content, d.version AS current_version
                   FROM canvas_draft_versions v
                   JOIN canvas_projects p ON p.id = v.canvas_id
                   JOIN canvas_drafts d ON d.canvas_id = v.canvas_id
                   WHERE v.canvas_id = ? AND v.version = ? AND p.owner_user_id = ? AND p.deleted_at IS NULL""",
                (project_id, version, owner_user_id),
            ).fetchone()
            if row is None:
                raise CanvasNotFoundError(f"{project_id}:{version}")
            content = row["content"]
            current_version = int(row["current_version"])
        return self.save_draft(owner_user_id, project_id, current_version, content)
