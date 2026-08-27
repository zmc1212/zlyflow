from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app.auth import AuthStore, csrf_token
from backend.app.comfy_provider import ComfyProviderError, ComfyProviderService, validate_comfy_base_url
from backend.app.comfy_service import ComfyService
from backend.app.config import Settings
from backend.app.main import app
from backend.app.models import UserRole
from backend.app.storage import JobStore


class ComfyUrlValidationTests(unittest.TestCase):
    def test_accepts_loopback_http(self) -> None:
        self.assertEqual(validate_comfy_base_url("http://127.0.0.1:8188/"), "http://127.0.0.1:8188")

    def test_rejects_missing_host_and_credentials(self) -> None:
        with self.assertRaises(ValueError):
            validate_comfy_base_url("not-a-url")
        with self.assertRaises(ValueError):
            validate_comfy_base_url("http://user:pass@127.0.0.1:8188")
        with self.assertRaises(ValueError):
            validate_comfy_base_url("http://127.0.0.1:8188/?x=1")


class ComfyProviderServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")
        self.provider = ComfyProviderService(self.store, "http://127.0.0.1:8188")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_seeds_env_default_and_saves_override(self) -> None:
        self.assertEqual(self.provider.current_url(), "http://127.0.0.1:8188")
        result = self.provider.update({"base_url": "http://127.0.0.1:18188"})
        self.assertEqual(result["base_url"], "http://127.0.0.1:18188")
        self.assertEqual(self.provider.current_url(), "http://127.0.0.1:18188")
        self.assertEqual(result["env_default"], "http://127.0.0.1:8188")

    def test_test_uses_unsaved_url_without_persisting_it(self) -> None:
        mock_response = MagicMock()
        mock_response.ok = True
        with patch("backend.app.comfy_provider.requests.get", return_value=mock_response) as mock_get:
            result = self.provider.test({"base_url": "http://127.0.0.1:18188"})
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.args[0], "http://127.0.0.1:18188/system_stats")
        self.assertEqual(result["last_test_status"], "success")
        self.assertEqual(self.provider.current_url(), "http://127.0.0.1:8188")

    def test_failed_test_records_status(self) -> None:
        with patch("backend.app.comfy_provider.requests.get", side_effect=ConnectionError("refused")):
            with self.assertRaises(ComfyProviderError):
                self.provider.test({"base_url": "http://127.0.0.1:8188"})
        self.assertEqual(self.store.get_comfy_settings()["last_test_status"], "failed")


class ComfyServiceResolverTests(unittest.TestCase):
    def test_stop_prompt_uses_resolved_url(self) -> None:
        class FakeResponse:
            ok = True

            def json(self):
                return {"queue_running": [[0, "run-1", {}, {}, []]], "queue_pending": []}

        posts: list[str] = []

        class FakeRequests:
            @staticmethod
            def get(url, **kwargs):
                return FakeResponse()

            @staticmethod
            def post(url, **kwargs):
                posts.append(url)
                return FakeResponse()

        with patch("backend.app.comfy_service.requests", FakeRequests):
            service = ComfyService(Settings(), url_resolver=lambda: "http://127.0.0.1:18188")
            service.stop_prompt("run-1")
        self.assertEqual(posts, ["http://127.0.0.1:18188/interrupt"])


class ComfyProviderEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        self.provider = ComfyProviderService(self.job_store, "http://127.0.0.1:8188")
        app.state.auth_store = self.auth_store
        app.state.store = self.job_store
        app.state.comfy_provider = self.provider
        self.admin = self.auth_store.create_user(
            "superadmin", "Super Admin", "password123456", UserRole.SUPER_ADMIN, must_change_password=False,
        )
        self.admin_token, _ = self.auth_store.create_session(self.admin["id"])
        self.employee = self.auth_store.create_user(
            "worker", "Worker", "password123456", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.employee_token, _ = self.auth_store.create_session(self.employee["id"])
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_admin_config_permissions(self) -> None:
        res = self.client.get("/api/admin/providers/comfy")
        self.assertEqual(res.status_code, 401)
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        res = self.client.get("/api/admin/providers/comfy")
        self.assertEqual(res.status_code, 403)
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        res = self.client.get("/api/admin/providers/comfy")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["base_url"], "http://127.0.0.1:8188")

    def test_admin_can_save_url(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        res = self.client.put(
            "/api/admin/providers/comfy",
            json={"base_url": "http://127.0.0.1:18188"},
            headers={"X-CSRF-Token": csrf_token(self.admin_token)},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["base_url"], "http://127.0.0.1:18188")
        self.assertEqual(self.provider.current_url(), "http://127.0.0.1:18188")
