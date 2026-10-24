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

    @patch.object(OpenAICompatibleClient, "list_models", return_value=["Qwen/Qwen3-VL-30B-A3B-Thinking"])
    @patch("requests.Session.post")
    def test_thinking_vision_connection_omits_unsupported_switch(self, mock_post: MagicMock, _models: MagicMock) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        self.vlm_provider.update({
            "enabled": True, "base_url": "https://api.siliconflow.cn/v1",
            "model": "Qwen/Qwen3-VL-30B-A3B-Thinking", "api_key": "sk-test",
        })

        def upstream(_url: str, **kwargs: object) -> MagicMock:
            response = MagicMock()
            if "enable_thinking" in kwargs["json"]:
                response.status_code = 400
                response.json.return_value = {"error": {"message": "current model does not support parameter `enable_thinking`."}}
            else:
                response.status_code = 200
                response.json.return_value = {"choices": [{"message": {
                    "reasoning_content": "先分析问题", "content": "你好，我是视觉模型，可以正常中文对话。",
                }}]}
            return response

        mock_post.side_effect = upstream
        response = self.client.post("/api/admin/providers/vlm/test", headers=self._admin_headers(), json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["last_test_status"], "成功")
        self.assertIn("可以正常中文对话", response.json()["last_test_message"])
        self.assertNotIn("先分析问题", response.json()["last_test_message"])
        mock_post.assert_called_once()

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

    def test_update_rejects_text_model(self) -> None:
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
        self.assertEqual(res.status_code, 422)
        self.assertIn("视觉", res.json()["detail"])

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
        self.assertTrue(res.json()["supports_vision"])

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
                "model": "glm-4.6v-flash",
            },
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["use_llm_credentials"])
        self.assertEqual("https://llm.example/v1", body["base_url"])
        self.assertEqual("glm-4.6v-flash", body["model"])
        self.assertTrue(body["has_api_key"])

    def test_status_separates_authoring_and_analysis_vision(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "qwen2.5-vl-72b-instruct",
            "api_key": "sk-llm",
        })
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
    def test_catalog_keeps_vision_and_drops_text(self, mock_get: MagicMock) -> None:
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
            "enabled": True,
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "sk-siliconflow-test-key",
            "model": "Qwen/Qwen3-VL-8B-Instruct",
        })
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        res = self.client.post(
            "/api/admin/providers/vlm/models",
            json={"base_url": "https://api.siliconflow.cn/v1", "free_only": False},
            headers=self._admin_headers(),
        )
        self.assertEqual(res.status_code, 200)
        ids = [item["id"] for item in res.json()["models"]]
        self.assertEqual(ids, ["Qwen/Qwen3-VL-8B-Instruct"])

    def test_unavailable_message_points_to_vlm_tab(self) -> None:
        self.assertIn("VLM 视觉模型", VLM_UNAVAILABLE_MESSAGE)
        self.assertIn("VL", VLM_NOT_VISION_MESSAGE)


class VlmRuntimeConfigTests(unittest.TestCase):
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

