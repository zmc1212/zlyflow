from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

from backend.app.auth import AuthStore, csrf_token
from backend.app.main import SESSION_COOKIE, app
from backend.app.models import UserRole


class AccountNameEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.auth_store = AuthStore(Path(self.temp_dir.name) / "accounts.db")
        app.state.auth_store = self.auth_store
        self.super_admin = self.auth_store.create_user(
            "root", "超管", "password123456", UserRole.SUPER_ADMIN, must_change_password=False,
        )
        self.admin = self.auth_store.create_user(
            "manager", "管理员", "password123456", UserRole.ADMIN, must_change_password=False,
        )
        self.employee = self.auth_store.create_user(
            "worker", "员工", "password123456", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.admin_token, _ = self.auth_store.create_session(self.admin["id"])
        self.employee_token, _ = self.auth_store.create_session(self.employee["id"])
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def login_as(self, token: str) -> None:
        self.client.cookies.set(SESSION_COOKIE, token)

    def test_employee_renames_self(self) -> None:
        self.login_as(self.employee_token)
        res = self.client.patch(
            "/api/auth/profile", json={"display_name": "  李四  "},
            headers={"X-CSRF-Token": csrf_token(self.employee_token)},
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["authenticated"])
        self.assertEqual(body["user"]["display_name"], "李四")
        self.assertEqual(self.auth_store.get_user(self.employee["id"])["display_name"], "李四")

    def test_profile_rename_requires_csrf_and_rejects_blank_name(self) -> None:
        self.login_as(self.employee_token)
        res = self.client.patch("/api/auth/profile", json={"display_name": "李四"})
        self.assertEqual(res.status_code, 403)

        res = self.client.patch(
            "/api/auth/profile", json={"display_name": "   "},
            headers={"X-CSRF-Token": csrf_token(self.employee_token)},
        )
        self.assertEqual(res.status_code, 422)
        self.assertEqual(self.auth_store.get_user(self.employee["id"])["display_name"], "员工")

    def test_admin_renames_any_account_but_role_changes_stay_restricted(self) -> None:
        self.login_as(self.admin_token)
        headers = {"X-CSRF-Token": csrf_token(self.admin_token)}
        for target in (self.employee, self.admin, self.super_admin):
            res = self.client.patch(
                f"/api/admin/users/{target['id']}",
                json={"display_name": f"{target['display_name']}·改名"},
                headers=headers,
            )
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["display_name"], f"{target['display_name']}·改名")

        res = self.client.patch(
            f"/api/admin/users/{self.super_admin['id']}", json={"role": "employee"}, headers=headers,
        )
        self.assertEqual(res.status_code, 403)
        res = self.client.patch(
            f"/api/admin/users/{self.super_admin['id']}", json={"is_active": False}, headers=headers,
        )
        self.assertEqual(res.status_code, 403)

    def test_employee_cannot_use_admin_rename(self) -> None:
        self.login_as(self.employee_token)
        res = self.client.patch(
            f"/api/admin/users/{self.employee['id']}", json={"display_name": "张三"},
            headers={"X-CSRF-Token": csrf_token(self.employee_token)},
        )
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()
