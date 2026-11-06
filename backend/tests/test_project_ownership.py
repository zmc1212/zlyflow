from __future__ import annotations

import asyncio
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.media_studio.models import ProjectCreateRequest
from backend.app.media_studio.routers.project_router import ProjectAccessMiddleware
from backend.app.media_studio.services.project_service import ProjectService


MODULE = "backend.app.media_studio.services.project_service"


class ProjectOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE ai_projects (
            id TEXT PRIMARY KEY, name TEXT, description TEXT, cover_url TEXT,
            status TEXT, settings_json TEXT, owner_user_id TEXT, created_at TEXT, updated_at TEXT)""")
        self.addCleanup(self.db.close)
        patch(MODULE + ".query_one", side_effect=self.query_one).start()
        patch(MODULE + ".query_all", side_effect=self.query_all).start()
        patch(MODULE + ".execute_sql", side_effect=self.execute_sql).start()
        self.addCleanup(patch.stopall)

    def query_one(self, sql, params=()):
        row = self.db.execute(sql.replace("%s", "?"), params).fetchone()
        return dict(row) if row else None

    def query_all(self, sql, params=()):
        rows = self.db.execute(sql.replace("%s", "?"), params).fetchall()
        return [dict(row) for row in rows]

    def execute_sql(self, sql, params=()):
        return self.db.execute(sql.replace("%s", "?"), params).rowcount

    def test_create_records_owner_and_list_only_returns_own_projects(self):
        project = ProjectService.create_project(ProjectCreateRequest(name="爱丽丝的剧"), owner_user_id="alice")
        ProjectService.create_project(ProjectCreateRequest(name="鲍勃的剧"), owner_user_id="bob")
        self.assertEqual([p.name for p in ProjectService.list_projects("alice")], ["爱丽丝的剧"])
        self.assertEqual([p.name for p in ProjectService.list_projects("bob")], ["鲍勃的剧"])
        self.assertEqual(ProjectService.list_projects("carol"), [])
        self.assertNotIn("owner_user_id", project.model_dump())

    def test_allows_user_denies_cross_account_and_missing_projects(self):
        project = ProjectService.create_project(ProjectCreateRequest(name="爱丽丝的剧"), owner_user_id="alice")
        self.assertTrue(ProjectService.allows_user(project.id, "alice"))
        self.assertFalse(ProjectService.allows_user(project.id, "bob"))
        self.assertFalse(ProjectService.allows_user("missing-project", "alice"))

    def test_unowned_legacy_project_stays_accessible(self):
        self.db.execute(
            "INSERT INTO ai_projects VALUES ('legacy', '历史工程', '', NULL, 'active', '{}', NULL, 'now', 'now')")
        self.assertTrue(ProjectService.allows_user("legacy", "alice"))


async def _downstream(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


class ProjectAccessMiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE ai_projects (
            id TEXT PRIMARY KEY, name TEXT, description TEXT, cover_url TEXT,
            status TEXT, settings_json TEXT, owner_user_id TEXT, created_at TEXT, updated_at TEXT)""")
        self.db.execute(
            "INSERT INTO ai_projects VALUES ('p1', '爱丽丝的剧', '', NULL, 'active', '{}', 'alice', 'now', 'now')")
        self.addCleanup(self.db.close)
        patch(MODULE + ".query_one", side_effect=self.query_one).start()
        self.addCleanup(patch.stopall)
        users = {"alice-token": {"id": "alice"}, "bob-token": {"id": "bob"}}
        auth_store = SimpleNamespace(user_for_session=lambda token: users.get(token))
        self.middleware = ProjectAccessMiddleware(
            _downstream, state=SimpleNamespace(auth_store=auth_store), session_cookie="zly_ai_video_studio_session")

    def query_one(self, sql, params=()):
        row = self.db.execute(sql.replace("%s", "?"), params).fetchone()
        return dict(row) if row else None

    def call(self, path, token=""):
        sent = []
        scope = {"type": "http", "method": "GET", "path": path,
                 "headers": [(b"cookie", f"zly_ai_video_studio_session={token}".encode())]}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        asyncio.run(self.middleware(scope, receive, send))
        return sent[0]["status"]

    def test_owner_reaches_project_subresources(self):
        self.assertEqual(self.call("/api/projects/p1/episodes", "alice-token"), 200)

    def test_other_account_gets_not_found_for_project_subresources(self):
        self.assertEqual(self.call("/api/projects/p1/episodes", "bob-token"), 404)
        self.assertEqual(self.call("/api/projects/p1", "bob-token"), 404)

    def test_unrelated_paths_and_anonymous_requests_pass_through(self):
        self.assertEqual(self.call("/api/projects", "bob-token"), 200)
        self.assertEqual(self.call("/api/jobs/j1", "bob-token"), 200)
        self.assertEqual(self.call("/api/projects/p1/episodes", ""), 200)


if __name__ == "__main__":
    unittest.main()
