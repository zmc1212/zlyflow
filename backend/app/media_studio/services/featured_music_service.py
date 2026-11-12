"""
音乐页「精选音乐」：管理员把生成成功的歌曲冻结成只读快照，所有登录成员可浏览与试听。

与导演台「精选作品」同构：发布时复制展示所需字段到独立表 ``ai_featured_music``，
之后原任务被删除或改名都不影响已发布内容；再次发布同一首歌曲时原地更新，
下架即删除展示行，不触碰音乐任务本身。
"""
from __future__ import annotations

import uuid
from typing import Any

from ..db import execute_sql, now_str, query_all, query_one

FEATURED_MUSIC_STATUS = "published"
MAX_URL_LENGTH = 1024
MAX_TITLE_LENGTH = 255
MAX_SUMMARY_LENGTH = 500
MAX_STYLE_LENGTH = 2_000
MAX_LYRICS_LENGTH = 8_000
MAX_FORMAT_LENGTH = 16


def _clean_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _media_url(value: Any) -> str:
    text = _clean_text(value, MAX_URL_LENGTH)
    if not text:
        return ""
    if text.startswith(("http://", "https://", "/")):
        return text
    return ""


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _sort_order(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return max(0, min(parsed, 999))


class FeaturedMusicService:
    @staticmethod
    def list_published() -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in query_all(
                """SELECT id, job_id, owner_user_id, title, summary, style, lyrics, result_url,
                          cover_url, duration_seconds, result_format, sort_order, published_at, updated_at
                FROM ai_featured_music
                WHERE status = %s
                ORDER BY sort_order ASC, published_at DESC""",
                (FEATURED_MUSIC_STATUS,),
            )
        ]

    @staticmethod
    def get_published(featured_id: str) -> dict[str, Any] | None:
        row = query_one(
            "SELECT * FROM ai_featured_music WHERE id = %s AND status = %s",
            (featured_id, FEATURED_MUSIC_STATUS),
        )
        return dict(row) if row else None

    @staticmethod
    def publish(payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        job_id = _clean_text(payload.get("job_id"), 64)
        if not job_id:
            raise ValueError("请选择要发布的歌曲")
        job = query_one(
            """SELECT id, owner_user_id, title, style, lyrics, status, result_url, result_format,
                      cover_url, duration_seconds
            FROM music_jobs WHERE id = %s""",
            (job_id,),
        )
        if not job:
            raise ValueError("歌曲不存在或已被删除")
        result_url = _media_url(job.get("result_url"))
        if str(job.get("status") or "") != "succeeded" or not result_url:
            raise ValueError("只有生成成功的歌曲才能发布为精选")

        title = _clean_text(payload.get("title"), MAX_TITLE_LENGTH) or _clean_text(job.get("title"), MAX_TITLE_LENGTH) or "未命名歌曲"
        summary = _clean_text(payload.get("summary"), MAX_SUMMARY_LENGTH) if "summary" in payload else ""
        cover_url = _media_url(payload.get("cover_url")) or _media_url(job.get("cover_url"))
        style = _clean_text(job.get("style"), MAX_STYLE_LENGTH)
        lyrics = _clean_text(job.get("lyrics"), MAX_LYRICS_LENGTH)
        duration_seconds = _positive_int(job.get("duration_seconds"))
        result_format = _clean_text(job.get("result_format"), MAX_FORMAT_LENGTH) or None
        sort_order = _sort_order(payload.get("sort_order"))

        now = now_str()
        existing = query_one("SELECT id, published_at FROM ai_featured_music WHERE job_id = %s", (job_id,))
        if existing:
            featured_id = str(existing["id"])
            published_at = str(existing.get("published_at") or now)
            execute_sql(
                """UPDATE ai_featured_music
                SET title = %s, summary = %s, style = %s, lyrics = %s, result_url = %s, cover_url = %s,
                    duration_seconds = %s, result_format = %s, sort_order = %s,
                    status = %s, published_by = %s, published_at = %s, updated_at = %s
                WHERE id = %s""",
                (title, summary, style, lyrics, result_url, cover_url or None, duration_seconds, result_format,
                 sort_order, FEATURED_MUSIC_STATUS, actor_user_id, published_at, now, featured_id),
            )
        else:
            featured_id = f"featured-music-{uuid.uuid4().hex[:16]}"
            execute_sql(
                """INSERT INTO ai_featured_music
                (id, job_id, owner_user_id, title, summary, style, lyrics, result_url, cover_url,
                 duration_seconds, result_format, sort_order, status, published_by, published_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (featured_id, job_id, _clean_text(job.get("owner_user_id"), 64) or None, title, summary, style,
                 lyrics, result_url, cover_url or None, duration_seconds, result_format, sort_order,
                 FEATURED_MUSIC_STATUS, actor_user_id, now, now),
            )
        created = FeaturedMusicService.get_published(featured_id)
        if not created:
            raise ValueError("精选音乐发布失败")
        return created

    @staticmethod
    def unpublish(featured_id: str) -> bool:
        return execute_sql(
            "DELETE FROM ai_featured_music WHERE id = %s AND status = %s",
            (featured_id, FEATURED_MUSIC_STATUS),
        ) > 0
