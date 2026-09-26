from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.auth import AuthStore, csrf_token
from backend.app.llm_provider import LlmProviderService, model_supports_vision
from backend.app.main import app
from backend.app.models import UserRole
from backend.app.storage import JobStore
from backend.app.vision_capability import _CACHE, VisionProbeResult, probe_fields
from backend.app.llm_client import (
    OpenAICompatibleClient,
    generate_zhipu_jwt,
    looks_like_zhipu_api_key,
    normalize_api_key,
    resolve_openai_bearer_token,
)
from backend.app.vlm_provider import VLM_NOT_VISION_MESSAGE, VLM_UNAVAILABLE_MESSAGE, VlmProviderService


class ZhipuAuthTests(unittest.TestCase):
    def test_normalize_api_key_strips_bearer_prefix(self) -> None:
        self.assertEqual(normalize_api_key("  Bearer abc.def  "), "abc.def")

    def test_looks_like_zhipu_api_key(self) -> None:
        self.assertTrue(looks_like_zhipu_api_key("abc123.secret456"))
        self.assertFalse(looks_like_zhipu_api_key("sk-siliconflow"))
        self.assertFalse(looks_like_zhipu_api_key("a.b.c"))

    def test_generate_zhipu_jwt_has_three_segments(self) -> None:
        token = generate_zhipu_jwt("abc123.secret456")
        self.assertEqual(token.count("."), 2)

    def test_openai_client_uses_jwt_for_zhipu(self) -> None:
        client = OpenAICompatibleClient(
            base_url="https://open.bigmodel.cn/api/paas/v4",
            api_key="abc123.secret456",
        )
        bearer = client.headers["Authorization"].removeprefix("Bearer ")
        self.assertNotEqual(bearer, "abc123.secret456")
        self.assertEqual(bearer.count("."), 2)

    def test_resolve_openai_bearer_keeps_siliconflow_key(self) -> None:
        token = resolve_openai_bearer_token(
            base_url="https://api.siliconflow.cn/v1",
            api_key="sk-siliconflow-test-key",
        )
        self.assertEqual(token, "sk-siliconflow-test-key")


class VisionModelNameTests(unittest.TestCase):
    def test_glm46v_and_gemma4_count_as_vision(self) -> None:
        self.assertTrue(model_supports_vision("glm-4.6v-flash"))
        self.assertTrue(model_supports_vision("glm-4v-flash"))
        self.assertTrue(model_supports_vision("glm-4.1v-thinking-flash"))
        self.assertTrue(model_supports_vision("google/gemma-4-31b-it"))
        self.assertTrue(model_supports_vision("Qwen/Qwen3-VL-8B-Instruct"))
        self.assertFalse(model_supports_vision("Qwen/Qwen2.5-7B-Instruct"))
        self.assertFalse(model_supports_vision("THUDM/GLM-4-9B-0414"))


class VlmProviderEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        _CACHE.clear()
        self.addCleanup(_CACHE.clear)
        probe = patch("backend.app.vision_capability.probe_vision_capability", return_value=VisionProbeResult("supported", "mock verified"))
        self.probe = probe.start()
        self.addCleanup(probe.stop)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_vlm.db"
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        self.llm_provider = LlmProviderService(self.job_store, self.credential_key)
        self.vlm_provider = VlmProviderService(self.job_store, self.credential_key)
        app.state.auth_store = self.auth_store
        app.state.store = self.job_store
        app.state.llm_provider = self.llm_provider
        app.state.vlm_provider = self.vlm_provider
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

    def _admin_headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": csrf_token(self.admin_token)}

    def test_admin_vlm_permissions(self) -> None:
        res = self.client.get("/api/admin/providers/vlm")
        self.assertEqual(res.status_code, 401)
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        res = self.client.get("/api/admin/providers/vlm")
        self.assertEqual(res.status_code, 403)
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        res = self.client.get("/api/admin/providers/vlm")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["model"], "glm-4v-flash")
        self.assertFalse(res.json()["enabled"])

    def test_update_unknown_model_stays_unverified(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        res = self.client.put(
            "/api/admin/providers/vlm",
            headers=self._admin_headers(),
            json={
                "enabled": True,
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "api_key": "sk-dummy",
            },
        )
        # Name-based hard validation is removed: saving never raises on the model
        # name. The three-state capability is persisted (seeded by legacy guess)
        # and only the connection-test probe can prove or disprove vision.
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn(body["vision_capability"], ("unknown", "supported", "unsupported"))
        self.assertEqual(body["vision_capability"], "unknown")
        self.assertIsNone(body["vision_capability_source"])

    def test_update_accepts_glm46v(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        res = self.client.put(
            "/api/admin/providers/vlm",
            headers=self._admin_headers(),
            json={
                "enabled": True,
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "model": "glm-4.6v-flash",
                "api_key": "sk-dummy",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["model"], "glm-4.6v-flash")
        self.assertFalse(res.json()["supports_vision"])

    def test_vlm_profiles_restore_saved_key_and_reuse_setting(self) -> None:
        self.llm_provider.update({"enabled": True, "base_url": "https://llm.example/v1", "model": "writer", "api_key": "test-key"})
        self.vlm_provider.update({
            "profile_id": "siliconflow",
            "enabled": True,
            "use_llm_credentials": False,
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "Qwen/Qwen3-VL-8B-Instruct",
            "api_key": "sk-vlm-siliconflow-history",
        })
        self.vlm_provider.update({
            "profile_id": "custom",
            "enabled": True,
            "use_llm_credentials": True,
            "base_url": "https://custom-vlm.example/v1",
            "model": str(self.job_store.get_llm_settings().get("model") or "deepseek-ai/DeepSeek-V4-Flash-0731"),
        })

        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        response = self.client.get("/api/admin/providers/vlm/profiles")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["active_profile_id"], "siliconflow")
        self.assertNotIn("sk-vlm-siliconflow-history", response.text)
        profiles = {row["profile_id"]: row for row in body["profiles"]}
        self.assertTrue(profiles["siliconflow"]["has_api_key"])
        self.assertTrue(profiles["siliconflow"]["use_llm_credentials"])

        self.vlm_provider.update({
            "profile_id": "siliconflow",
            "enabled": True,
            "use_llm_credentials": False,
            "base_url": profiles["siliconflow"]["base_url"],
            "model": profiles["siliconflow"]["model"],
            "api_key": None,
        })
        self.assertEqual(self.vlm_provider.public_config()["profile_id"], "siliconflow")
        self.assertEqual(self.vlm_provider.api_key(), "sk-vlm-siliconflow-history")

    def test_update_can_reuse_llm_credentials(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://llm.example/v1",
            "model": "gpt-5.6-sol",
            "api_key": "sk-llm",
        })
        res = self.client.put(
            "/api/admin/providers/vlm",
            headers=self._admin_headers(),
            json={
                "enabled": True,
                "use_llm_credentials": True,
                "base_url": "https://old-vlm.example/v1",
                "model": "gpt-5.6-sol",
            },
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["use_llm_credentials"])
        self.assertEqual("https://llm.example/v1", body["base_url"])
        self.assertEqual("gpt-5.6-sol", body["model"])
        self.assertTrue(body["has_api_key"])
        self.assertEqual("llm", body["connection_source"])
        self.assertEqual(self.job_store.get_vlm_settings()["model"], body["independent_model"])
        self.assertEqual(self.job_store.get_vlm_settings()["base_url"], body["independent_base_url"])

    def test_test_empty_body_inherits_saved_reuse_and_updates_llm(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        self.llm_provider.update({"enabled": True, "base_url": "https://llm.example/v1",
                                  "model": "deepseek-v4.1-flash", "api_key": "sk-llm"})
        self.vlm_provider.update({"enabled": True, "use_llm_credentials": True})
        before = self.job_store.get_vlm_settings()
        with patch.object(self.vlm_provider.llm_connection, "test", return_value=self.llm_provider.public_config()) as test_llm:
            response = self.client.post("/api/admin/providers/vlm/test", headers=self._admin_headers(), json={})
        self.assertEqual(200, response.status_code)
        test_llm.assert_called_once_with()
        self.assertEqual("deepseek-v4.1-flash", response.json()["model"])
        self.assertEqual("llm", response.json()["connection_source"])
        self.assertEqual(before, self.job_store.get_vlm_settings())

    def test_update_reuse_rejects_unverified_llm(self) -> None:
        self.probe.return_value = VisionProbeResult("unsupported", "Model not exist")
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://llm.example/v1",
            "model": "gpt-5.6-sol",
            "api_key": "sk-llm",
        })
        res = self.client.put(
            "/api/admin/providers/vlm",
            headers=self._admin_headers(),
            json={
                "enabled": True,
                "use_llm_credentials": True,
                "base_url": "https://old-vlm.example/v1",
                "model": "glm-4.6v-flash",
            },
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("复用大模型连接尚未通过视觉验证", res.json()["detail"])

    def test_status_separates_authoring_and_analysis_vision(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "qwen2.5-vl-72b-instruct",
            "api_key": "sk-llm",
        })
        row = self.job_store.get_llm_settings()
        self.job_store.update_llm_settings(probe_fields(row, VisionProbeResult("supported", "mock verified")))
        res = self.client.get("/api/llm/status")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["available"])
        self.assertTrue(body["supports_vision"])
        self.assertEqual("llm", body["authoring_vision"]["source"])
        self.assertTrue(body["authoring_vision"]["attach_images"])
        self.assertEqual("llm", body["analysis_vision"]["source"])
        self.assertEqual("qwen2.5-vl-72b-instruct", body["model"])

        self.vlm_provider.update({
            "enabled": True,
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4v-flash",
            "api_key": "sk-vlm",
        })
        row = self.job_store.get_vlm_settings()
        self.job_store.update_vlm_settings(probe_fields(row, VisionProbeResult("supported", "mock verified")))
        res = self.client.get("/api/llm/status")
        body = res.json()
        self.assertTrue(body["supports_vision"])
        self.assertEqual("llm", body["authoring_vision"]["source"])
        self.assertEqual("vlm", body["analysis_vision"]["source"])
        vlm = self.client.get("/api/vlm/status")
        self.assertEqual(vlm.status_code, 200)
        self.assertTrue(vlm.json()["available"])
        self.assertEqual(vlm.json()["model"], "glm-4v-flash")

    def test_analyze_subject_requires_vlm_not_llm(self) -> None:
        self.probe.return_value = VisionProbeResult("unsupported", "mock text model")
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-dummy",
        })
        response = self.client.post(
            "/api/llm/analyze-subject",
            headers={"X-CSRF-Token": csrf_token(self.employee_token)},
            data={"kind": "character", "name": "主角"},
            files={"image": ("ref.png", b"fake-bytes", "image/png")},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("视觉", response.json()["detail"])
        self.assertIn("VLM", response.json()["detail"])

    def test_analyze_subject_uses_vlm_provider(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        self.vlm_provider.update({
            "enabled": True,
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4v-flash",
            "api_key": "sk-vlm",
        })
        with patch.object(self.vlm_provider, "analyze_subject", return_value="脏白背心，花白短寸") as mocked:
            response = self.client.post(
                "/api/llm/analyze-subject",
                headers={"X-CSRF-Token": csrf_token(self.employee_token)},
                data={"kind": "character", "name": "吴耐"},
                files={"image": ("ref.png", b"fake-bytes", "image/png")},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["description"], "脏白背心，花白短寸")
        mocked.assert_called_once()

    @patch("requests.Session.get")
    def test_catalog_keeps_all_candidates_without_name_authorization(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "Qwen/Qwen2.5-7B-Instruct"},
                {"id": "Qwen/Qwen3-VL-8B-Instruct"},
                {"id": "THUDM/GLM-4-9B-0414"},
            ]
        }
        mock_get.return_value = mock_response
        self.vlm_provider.update({
            "profile_id": "siliconflow",
            "enabled": True,
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "sk-siliconflow-test-key",
            "model": "Qwen/Qwen3-VL-8B-Instruct",
        })
        self.vlm_provider.update({
            "profile_id": "custom",
            "enabled": True,
            "base_url": "https://custom-vlm.example/v1",
            "api_key": "sk-current-vlm-custom",
            "model": "custom-vision-model",
        })
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        res = self.client.post(
            "/api/admin/providers/vlm/models",
            json={"profile_id": "siliconflow", "base_url": "https://api.siliconflow.cn/v1", "free_only": False},
            headers=self._admin_headers(),
        )
        self.assertEqual(res.status_code, 200)
        ids = [item["id"] for item in res.json()["models"]]
        self.assertEqual(set(ids), {"Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen3-VL-8B-Instruct", "THUDM/GLM-4-9B-0414"})
        auth_headers = [call.kwargs.get("headers", {}).get("Authorization") for call in mock_get.call_args_list]
        self.assertIn("Bearer sk-siliconflow-test-key", auth_headers)

    def test_unavailable_message_points_to_vlm_tab(self) -> None:
        self.assertIn("VLM 视觉模型", VLM_UNAVAILABLE_MESSAGE)
        self.assertIn("VL", VLM_NOT_VISION_MESSAGE)


class VlmRuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        _CACHE.clear()
        self.addCleanup(_CACHE.clear)
        for target, value in (("backend.app.media_studio.services.llm_service.llm_row", {}), ("backend.app.vision_capability.probe_vision_capability", VisionProbeResult("supported", "mock verified"))):
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    @patch("backend.app.media_studio.services.llm_service.vlm_row")
    def test_infer_requires_enabled_vlm(self, mock_row: MagicMock) -> None:
        from backend.app.media_studio.services.llm_service import LlmService

        mock_row.return_value = {"enabled": 0}
        with self.assertRaisesRegex(ValueError, "VLM 视觉模型"):
            LlmService._vlm_runtime_config()

    @patch("backend.app.media_studio.services.llm_service.credential_manager")
    @patch("backend.app.media_studio.services.llm_service.vlm_row")
    def test_infer_uses_vlm_row_not_llm(self, mock_row: MagicMock, mock_creds: MagicMock) -> None:
        from backend.app.media_studio.services.llm_service import LlmService

        mock_row.return_value = {
            "enabled": 1,
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4v-flash",
            "api_key_encrypted": "enc",
        }
        mock_creds.return_value.decrypt.return_value = "sk-vlm-only"
        base_url, model, api_key = LlmService._vlm_runtime_config()
        self.assertEqual(base_url, "https://open.bigmodel.cn/api/paas/v4")
        self.assertEqual(model, "glm-4v-flash")
        self.assertEqual(api_key, "sk-vlm-only")

