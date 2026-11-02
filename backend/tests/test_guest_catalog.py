from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.auth import AuthStore
from backend.app.main import app
from backend.app.models import UserRole
from backend.app.workflow_registry import WORKFLOWS


class GuestCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.previous_store = getattr(app.state, "auth_store", None)
        self.store = AuthStore(Path(self.temp.name) / "auth.db")
        app.state.auth_store = self.store
        self.user = self.store.create_user("guesttest", "测试员工", "password123456", UserRole.EMPLOYEE, must_change_password=False)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.state.auth_store = self.previous_store
        self.client.close()
        self.temp.cleanup()

    def test_guest_catalog_contains_only_creative_options_and_does_not_mutate_registry(self) -> None:
        before = copy.deepcopy([item.payload() for item in WORKFLOWS])
        with patch("backend.app.main.listed_workflows", return_value=WORKFLOWS), patch("backend.app.main.mode_payload", side_effect=AssertionError("guest must not read provider availability")):
            response = self.client.get("/api/modes")
        self.assertEqual(response.status_code, 200)
        modes = response.json()["modes"]
        self.assertTrue(modes)
        self.assertTrue(any(parameter.get("schema", {}).get("properties") for mode in modes for parameter in mode["parameters"] if parameter.get("schema")))
        for mode in modes:
            self.assertIsNone(mode["unavailable_reason"])
            for parameter in mode["parameters"]:
                schema = parameter.get("schema") or {}
                self.assertNotIn("default", schema)
                for option in schema.get("properties", {}).values():
                    self.assertIn(option["ui_group"], {"primary", "advanced"})
        self.assertEqual(before, [item.payload() for item in WORKFLOWS])

    def test_private_reads_and_generation_still_require_login(self) -> None:
        for path in ["/api/jobs", "/api/library", "/api/admin/users", "/api/providers/grs/balance", f"/api/modes/{WORKFLOWS[0].id}"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        response = self.client.post("/api/jobs", data={"mode": WORKFLOWS[0].id, "prompt": "测试画面"})
        self.assertEqual(response.status_code, 401)

    def test_account_password_login_keeps_session_and_full_catalog(self) -> None:
        response = self.client.post("/api/auth/login", json={"username": "guesttest", "password": "password123456"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])
        self.assertTrue(response.json()["csrf_token"])
        self.assertTrue(self.client.get("/api/auth/status").json()["authenticated"])
        with patch("backend.app.main.listed_workflows", return_value=WORKFLOWS):
            modes = self.client.get("/api/modes").json()["modes"]
        self.assertTrue(any(option.get("ui_group") == "internal" for mode in modes for parameter in mode["parameters"] for option in (parameter.get("schema") or {}).get("properties", {}).values()))


if __name__ == "__main__":
    unittest.main()
