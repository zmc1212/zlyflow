from __future__ import annotations

import json
import uuid
from typing import Any

from ..db import execute_sql, now_str, query_all, query_one
from ..models import ProjectCreateRequest, ProjectItem, ProjectUpdateRequest


class ProjectService:
    @staticmethod
    def _to_project_item(row: dict[str, Any]) -> ProjectItem:
        settings = None
        if row.get("settings_json"):
            try:
                settings = json.loads(row["settings_json"])
            except Exception:
                settings = None

        return ProjectItem(
            id=row["id"],
            name=row["name"],
            description=row.get("description") or "",
            cover_url=row.get("cover_url"),
            status=row.get("status") or "active",
            settings=settings,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @classmethod
    def list_projects(cls) -> list[ProjectItem]:
        rows = query_all("SELECT * FROM ai_projects ORDER BY updated_at DESC")
        return [cls._to_project_item(r) for r in rows]

    @classmethod
    def get_project(cls, project_id: str) -> ProjectItem | None:
        row = query_one("SELECT * FROM ai_projects WHERE id = %s", (project_id,))
        if not row:
            return None
        return cls._to_project_item(row)

    @classmethod
    def create_project(cls, payload: ProjectCreateRequest) -> ProjectItem:
        name = payload.name.strip()
        if not name:
            raise ValueError("项目名称不能为空")

        project_id = f"proj-{uuid.uuid4().hex[:16]}"
        timestamp = now_str()
        settings_str = json.dumps(payload.settings, ensure_ascii=False) if payload.settings else "{}"

        execute_sql(
            """
            INSERT INTO ai_projects (id, name, description, cover_url, status, settings_json, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'active', %s, %s, %s)
            """,
            (
                project_id,
                name,
                payload.description.strip() if payload.description else "",
                payload.cover_url.strip() if payload.cover_url else None,
                settings_str,
                timestamp,
                timestamp,
            ),
        )
        created = cls.get_project(project_id)
        if not created:
            raise RuntimeError("项目创建失败")
        return created

    @classmethod
    def update_project(cls, project_id: str, payload: ProjectUpdateRequest) -> ProjectItem:
        current = cls.get_project(project_id)
        if not current:
            raise ValueError(f"未找到 ID 为 {project_id} 的项目")

        name = payload.name.strip() if payload.name is not None else current.name
        if not name:
            raise ValueError("项目名称不能为空")

        description = payload.description if payload.description is not None else current.description
        cover_url = payload.cover_url if payload.cover_url is not None else current.cover_url
        status = payload.status if payload.status is not None else current.status
        timestamp = now_str()

        settings_str = None
        if payload.settings is not None:
            settings_str = json.dumps(payload.settings, ensure_ascii=False)

        if settings_str is not None:
            execute_sql(
                """
                UPDATE ai_projects
                SET name = %s, description = %s, cover_url = %s, status = %s, settings_json = %s, updated_at = %s
                WHERE id = %s
                """,
                (name, description, cover_url, status, settings_str, timestamp, project_id),
            )
        else:
            execute_sql(
                """
                UPDATE ai_projects
                SET name = %s, description = %s, cover_url = %s, status = %s, updated_at = %s
                WHERE id = %s
                """,
                (name, description, cover_url, status, timestamp, project_id),
            )

        updated = cls.get_project(project_id)
        if not updated:
            raise RuntimeError("更新项目失败")
        return updated

    @classmethod
    def delete_project(cls, project_id: str) -> bool:
        affected = execute_sql("DELETE FROM ai_projects WHERE id = %s", (project_id,))
        return affected > 0
