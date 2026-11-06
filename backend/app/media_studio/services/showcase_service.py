"""「灵感」示例库：把一条真实出片冻结成可复用的创作配方，供所有用户浏览并一键回填创作台。

与 ai_featured_works（整部短剧的项目快照）不同，这里的一行 = 一张示例卡 = 一次可复现的生成请求，
所以必须原样带上 mode / prompt / options / references，才能在工作台重建同一个任务。
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from ..db import execute_sql, now_str, query_all, query_one

SHOWCASE_STATUS = "published"
MAX_MEDIA_URL_LENGTH = 2048
MAX_CATEGORIES = 24
LIST_COLUMNS = """id, slug, category, title, blurb, origin, mode, prompt, display_prompt,
    negative_prompt, image_size, options_json, references_json, tags_json, cover_url, media_url,
    media_type, duration_seconds, source_job_id, sort_order, published_at, updated_at"""

# 画廊里的素材必须对任何用户都可取：公开地址直接用，本机上传件改走同源预览路由。
SAFE_MEDIA_RE = re.compile(r"^(https://|/)", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"^(?:[a-zA-Z]:[\\/]|\\\\)")
SLUG_RE = re.compile(r"[^\w\u4e00-\u9fff-]+")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _media_url(value: Any) -> str:
    text = _clean_text(value)
    if not text or len(text) > MAX_MEDIA_URL_LENGTH or not SAFE_MEDIA_RE.match(text):
        return ""
    return text


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _slugify(text: str, fallback: str) -> str:
    slug = SLUG_RE.sub("-", text.lower()).strip("-")
    return (slug or fallback)[:120]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _references(value: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw in _json_value(value, []):
        if isinstance(raw, dict):
            url = _media_url(raw.get("url") or raw.get("cloud_url"))
            if not url:
                continue
            items.append({"url": url, "name": _clean_text(raw.get("name")) or f"参考 {len(items) + 1}"})
        else:
            url = _media_url(raw)
            if url:
                items.append({"url": url, "name": f"参考 {len(items) + 1}"})
    return items


def _tags(value: Any) -> list[str]:
    tags = [
        _clean_text(item)
        for item in _json_value(value, [])
        if _clean_text(item)
    ]
    return tags[:MAX_CATEGORIES]


def to_public(row: dict[str, Any]) -> dict[str, Any]:
    """行 → 前端示例卡。options/references/tags 一律反序列化成对象，前端不再解析字符串。"""
    item = dict(row)
    options = _json_value(item.pop("options_json", None), {})
    references = _references(item.pop("references_json", None))
    tags = _tags(item.pop("tags_json", None))
    media_url = _media_url(item.get("media_url"))
    cover_url = _media_url(item.get("cover_url"))
    item.update(
        {
            "category": _clean_text(item.get("category")) or "general",
            "title": _clean_text(item.get("title")),
            "blurb": _clean_text(item.get("blurb")),
            "origin": _clean_text(item.get("origin")) or "local",
            "mode": _clean_text(item.get("mode")),
            "prompt": str(item.get("prompt") or ""),
            "display_prompt": _clean_text(item.get("display_prompt")),
            "negative_prompt": str(item.get("negative_prompt") or ""),
            "image_size": _clean_text(item.get("image_size")),
            "media_url": media_url,
            "cover_url": cover_url,
            "media_type": _clean_text(item.get("media_type")) or "video",
            "duration_seconds": _as_int(item.get("duration_seconds")),
            "sort_order": _as_int(item.get("sort_order")),
            "options": options,
            "references": references,
            "tags": tags,
        }
    )
    return item


class ShowcaseService:
    @staticmethod
    def list_published(category: str = "") -> list[dict[str, Any]]:
        clause = "WHERE status = %s"
        params: list[Any] = [SHOWCASE_STATUS]
        wanted = _clean_text(category)
        if wanted and wanted != "all":
            clause += " AND category = %s"
            params.append(wanted)
        rows = query_all(
            f"""SELECT {LIST_COLUMNS} FROM ai_showcase_items
            {clause} ORDER BY sort_order ASC, published_at DESC""",
            tuple(params),
        )
        return [to_public(row) for row in rows]

    @staticmethod
    def list_categories() -> list[dict[str, Any]]:
        rows = query_all(
            """SELECT category, COUNT(*) AS total FROM ai_showcase_items
            WHERE status = %s GROUP BY category ORDER BY MIN(sort_order) ASC""",
            (SHOWCASE_STATUS,),
        )
        return [
            {"category": _clean_text(row.get("category")) or "general", "total": _as_int(row.get("total"))}
            for row in rows
        ]

    @staticmethod
    def get(item_id: str) -> dict[str, Any] | None:
        row = query_one(
            f"SELECT {LIST_COLUMNS} FROM ai_showcase_items WHERE id = %s AND status = %s",
            (item_id, SHOWCASE_STATUS),
        )
        return to_public(row) if row else None

    @staticmethod
    def validate_mode(mode: str) -> str:
        from ...workflow_registry import workflow_for

        cleaned = _clean_text(mode)
        if not cleaned:
            raise ValueError("请选择示例使用的工作流")
        try:
            definition = workflow_for(cleaned)
        except KeyError as error:
            raise ValueError(f"工作流不存在：{cleaned}") from error
        return str(getattr(definition, "mode", cleaned) or cleaned)

    @staticmethod
    def normalize(payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        title = _clean_text(payload.get("title"))
        if not title:
            raise ValueError("请填写示例标题")
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("请填写示例提示词")
        media_url = _media_url(payload.get("media_url"))
        cover_url = _media_url(payload.get("cover_url"))
        if not media_url and not cover_url:
            raise ValueError("示例需要一条可播放的成品素材或封面")
        mode = ShowcaseService.validate_mode(payload.get("mode"))
        category = _clean_text(payload.get("category")) or "general"
        origin = _clean_text(payload.get("origin")) or "local"
        media_type = _clean_text(payload.get("media_type")) or "video"
        return {
            "slug": _slugify(_clean_text(payload.get("slug")) or title, f"showcase-{uuid.uuid4().hex[:8]}"),
            "category": category[:32],
            "title": title[:255],
            "blurb": _clean_text(payload.get("blurb")),
            "origin": origin[:32],
            "mode": mode[:64],
            "prompt": prompt,
            "display_prompt": _clean_text(payload.get("display_prompt")),
            "negative_prompt": str(payload.get("negative_prompt") or "").strip(),
            "image_size": _clean_text(payload.get("image_size"))[:32],
            "options_json": _dump(payload.get("options") if isinstance(payload.get("options"), dict) else {}),
            "references_json": _dump(_references(payload.get("references"))),
            "tags_json": _dump(_tags(payload.get("tags"))),
            "cover_url": cover_url,
            "media_url": media_url,
            "media_type": "image" if media_type == "image" else "video",
            "duration_seconds": max(0, min(_as_int(payload.get("duration_seconds")), 3600)),
            "source_job_id": _clean_text(payload.get("source_job_id"))[:64],
            "sort_order": max(0, min(_as_int(payload.get("sort_order")), 999)),
            "published_by": _clean_text(actor_user_id)[:64],
        }

    @staticmethod
    def publish(payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        fields = ShowcaseService.normalize(payload, actor_user_id)
        now = now_str()
        existing = query_one(
            "SELECT id, published_at FROM ai_showcase_items WHERE slug = %s",
            (fields["slug"],),
        )
        if existing:
            item_id = str(existing["id"])
            columns = [key for key in fields if key not in ("slug", "published_by")]
            assignments = ", ".join(f"{key} = %s" for key in columns)
            execute_sql(
                f"""UPDATE ai_showcase_items
                SET {assignments}, status = %s, published_by = %s, updated_at = %s WHERE id = %s""",
                tuple(
                    [fields[key] for key in columns]
                    + [SHOWCASE_STATUS, fields["published_by"], now, item_id]
                ),
            )
        else:
            item_id = f"showcase-{uuid.uuid4().hex[:16]}"
            columns = list(fields)
            placeholders = ", ".join(["%s"] * (len(columns) + 3))
            execute_sql(
                f"""INSERT INTO ai_showcase_items
                (id, {", ".join(columns)}, status, published_at, updated_at)
                VALUES (%s, {placeholders})""",
                tuple([item_id] + [fields[key] for key in columns] + [SHOWCASE_STATUS, now, now]),
            )
        created = ShowcaseService.get(item_id)
        if not created:
            raise ValueError("示例发布失败")
        return created

    @staticmethod
    def publish_from_job(job_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        """从一条已成功的任务冻结示例配方，保证画廊里的 prompt/参数就是出片时真正用的那份。"""
        job = query_one("SELECT * FROM jobs WHERE id = %s", (_clean_text(job_id),))
        if not job:
            raise ValueError("任务不存在")
        if _clean_text(job.get("status")) != "succeeded":
            raise ValueError("只能把成功的任务登记为示例")
        outputs = _json_value(job.get("outputs_json"), [])
        first = outputs[0] if outputs and isinstance(outputs[0], dict) else {}
        media_url = _media_url(first.get("cloud_url")) or f"/api/jobs/{job_id}/outputs/0/download"
        merged = {
            "mode": job.get("mode"),
            "prompt": job.get("prompt"),
            "negative_prompt": job.get("negative_prompt"),
            "image_size": job.get("image_size"),
            "options": _json_value(job.get("options_json"), {}),
            "references": first.get("references") or _references_from_job(job),
            "media_url": media_url,
            "media_type": "image" if _clean_text(job.get("media_type")) == "image" else "video",
            "duration_seconds": _as_int(first.get("duration")) or _options_duration(job),
            "source_job_id": job_id,
            **{key: value for key, value in (payload or {}).items() if value not in (None, "")},
        }
        merged.setdefault("title", _clean_text(job.get("title")) or f"示例 {job_id}")
        return ShowcaseService.publish(merged, actor_user_id)

    @staticmethod
    def unpublish(item_id: str) -> bool:
        return execute_sql("DELETE FROM ai_showcase_items WHERE id = %s", (item_id,)) > 0


def _references_from_job(job: dict[str, Any]) -> list[dict[str, str]]:
    """任务的参考素材：已经是公开地址的直接用；本机上传件走同源预览路由，索引从 1 开始。"""
    stored = _json_value(job.get("references_json"), [])
    job_id = _clean_text(job.get("id"))
    items: list[dict[str, str]] = []
    for index, raw in enumerate(stored, 1):
        if isinstance(raw, dict):
            text = _clean_text(raw.get("url") or raw.get("cloud_url") or raw.get("path"))
        else:
            text = _clean_text(raw)
        url = _media_url(text)
        if not url and job_id and LOCAL_PATH_RE.match(text):
            url = f"/api/jobs/{job_id}/references/{index}"
        if url:
            items.append({"url": url, "name": f"参考 {index}"})
    return items


def _options_duration(job: dict[str, Any]) -> int:
    options = _json_value(job.get("options_json"), {})
    return _as_int(options.get("duration"))
