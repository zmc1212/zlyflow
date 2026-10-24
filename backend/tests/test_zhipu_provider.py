from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.auth import AuthStore, csrf_token
from backend.app.llm_client import OpenAICompatibleClient, apply_plaza_free_ids, classify_model_free, parse_model_catalog
from backend.app.llm_provider import LlmProviderService
from backend.app.main import app
from backend.app.models import UserRole
from backend.app.storage import JobStore
from backend.app.vlm_provider import VlmProviderService
from backend.app.zhipu_catalog import ZHIPU_BASE_URL, is_zhipu_official_base_url, model_provider_presets, zhipu_model_free


class ZhipuPricingTests(unittest.TestCase):
    def test_known_prices_are_exact_and_scoped_to_official_endpoint(self) -> None:
        for model, expected in (("glm-4.7-flash", True), ("glm-4.7", False), ("glm-5.3", False),
                                ("glm-4.6v-flash", True), ("glm-4.6v", False), ("glm-4.6v-flashx", False),
                                ("unknown-flash", None), ("glm-4.7-flash-unknown", None)):
            with self.subTest(model=model):
                self.assertIs(zhipu_model_free(ZHIPU_BASE_URL + "/", model.upper()), expected)
                self.assertIsNone(zhipu_model_free("https://relay.example/api/paas/v4", model))
        for base_url in ("https://open.bigmodel.cn.example/api/paas/v4", "http://open.bigmodel.cn/api/paas/v4",
                         "https://api.z.ai/api/paas/v4", ZHIPU_BASE_URL + "/v1", ZHIPU_BASE_URL + "?relay=1"):
            with self.subTest(base_url=base_url):
                self.assertFalse(is_zhipu_official_base_url(base_url))

    def test_incomplete_or_cache_prices_never_imply_free_inference(self) -> None:
        cases = [
            ({"pricing": {"input": 0}}, None),
            ({"pricing": {"output": "0"}}, None),
            ({"pricing": {"input": 0, "output": 2}}, False),
            ({"pricing": {"input": 2, "output": 0}}, False),
            ({"pricing": {"prompt": "0", "completion": "0"}}, True),
            ({"pricing": {"input": 0, "output": 0}, "free": False}, False),
            ({"pricing": {"input": 1}, "free": True}, False),
            ({"free": "false"}, None),
            ({"pricing": {"cache": "免费"}}, None),
            ({"pricing": {"input": False, "output": 0}}, None),
            ({"pricing": {"input": "NaN", "output": 0}}, None),
            ({"pricing": {"input": -1, "output": 0}}, None),
        ]
        for row, expected in cases:
            with self.subTest(row=row):
                self.assertIs(classify_model_free({"id": "unknown-model", **row}, provider="custom"), expected)

    def test_catalog_uses_official_fallback_and_retains_explicit_paid_metadata(self) -> None:
        payload = {"data": [{"id": "glm-4.7-flash"}, {"id": "glm-4.7"}, {"id": "unknown"},
                            {"id": "glm-4.6v-flash", "pricing": {"input": 1, "output": 0}}]}
        rows = parse_model_catalog(payload, provider="zhipu", free_only=False, base_url=ZHIPU_BASE_URL)
        self.assertEqual({row["id"]: row["free"] for row in rows}, {
            "glm-4.7-flash": True, "glm-4.7": False, "unknown": None, "glm-4.6v-flash": False,
        })
        free_rows = parse_model_catalog(payload, provider="zhipu", free_only=True, base_url=ZHIPU_BASE_URL)
        self.assertEqual([row["id"] for row in free_rows], ["glm-4.7-flash"])
        self.assertEqual(apply_plaza_free_ids([{"id": "paid", "free": False}], {"paid"})[0]["free"], False)

    def test_preset_responses_do_not_mutate_registry(self) -> None:
        first = model_provider_presets()
        first["presets"][0]["chat_models"][0]["free"] = False
        self.assertTrue(model_provider_presets()["presets"][0]["chat_models"][0]["free"])


class ZhipuProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock()
        self.session.get.return_value.status_code = 200
        self.session.get.return_value.json.return_value = {"data": [{"id": "glm-4.7-flash"}]}
        self.session.post.return_value.status_code = 200
        self.session.post.return_value.json.return_value = {"choices": [{"message": {"content": "连接成功"}}]}
        self.client = OpenAICompatibleClient(ZHIPU_BASE_URL + "/", "synthetic.secret", session=self.session)

    def test_catalog_probe_and_business_chat_keep_v4_root(self) -> None:
        self.client.list_model_catalog()
        self.assertEqual(self.session.get.call_args.args[0], ZHIPU_BASE_URL + "/models")
        self.client.test_connection("glm-4.7-flash")
        probe = self.session.post.call_args
        self.assertEqual(probe.args[0], ZHIPU_BASE_URL + "/chat/completions")
        self.assertEqual(probe.kwargs["json"]["thinking"], {"type": "disabled"})
        self.client.chat_completion([{"role": "user", "content": "写一段剧本"}], model="glm-4.7-flash", temperature=0)
        runtime = self.session.post.call_args
        self.assertEqual(runtime.args[0], probe.args[0])
        self.assertNotIn("temperature", runtime.kwargs["json"])
        self.assertNotIn("enable_thinking", runtime.kwargs["json"])
        self.assertNotIn("thinking", runtime.kwargs["json"])

    def test_forced_thinking_models_are_never_disabled_or_limited_to_128_tokens(self) -> None:
        for model in ("glm-5.3", "glm-4.1v-thinking-flash"):
            with self.subTest(model=model):
                self.client.test_connection(model)
                payload = self.session.post.call_args.kwargs["json"]
                self.assertNotIn("thinking", payload)
                self.assertGreaterEqual(payload["max_tokens"], 4096)
                if model == "glm-5.3":
                    self.assertEqual(payload["reasoning_effort"], "low")

    def test_stream_separates_zhipu_reasoning_and_content(self) -> None:
        response = self.session.post.return_value
        response.headers = {"Content-Type": "text/event-stream"}
        response.iter_lines.return_value = [
            ("data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "思考"}}]})).encode(),
            ("data: " + json.dumps({"choices": [{"delta": {"content": "剧本正文"}}]})).encode(),
            b"data: [DONE]",
        ]
        deltas = []
        reply = self.client.chat_completion([{"role": "user", "content": "写剧本"}], model="glm-4.7-flash",
                                            stream=True, on_delta=lambda kind, text: deltas.append((kind, text)))
        self.assertEqual(reply, "剧本正文")
        self.assertIn(("reasoning", "思考"), deltas)
        self.assertIn(("content", "剧本正文"), deltas)

    def test_relay_keeps_its_own_parameters(self) -> None:
        client = OpenAICompatibleClient("https://relay.example/v1", "synthetic", session=self.session)
        client.chat_completion([], "glm-4.7-flash", temperature=0, thinking_enabled=False)
        payload = self.session.post.call_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0)
        self.assertNotIn("thinking", payload)


class ZhipuAdminIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "zhipu.db")
        self.auth = AuthStore(Path(self.temp_dir.name) / "zhipu.db")
        key = Fernet.generate_key().decode()
        self.llm = LlmProviderService(self.store, key)
        self.vlm = VlmProviderService(self.store, key)
        self.previous_state = {name: getattr(app.state, name, None) for name in ("auth_store", "store", "llm_provider", "vlm_provider")}
        app.state.auth_store, app.state.store = self.auth, self.store
        app.state.llm_provider, app.state.vlm_provider = self.llm, self.vlm
        admin = self.auth.create_user("synthetic-admin", "智谱测试", "test-password-1234", UserRole.SUPER_ADMIN, must_change_password=False)
        self.token, _ = self.auth.create_session(admin["id"])
        self.client = TestClient(app)
        self.client.cookies.set("zly_ai_video_studio_session", self.token)
        self.headers = {"X-CSRF-Token": csrf_token(self.token)}

    def tearDown(self) -> None:
        self.client.close()
        for name, value in self.previous_state.items():
            setattr(app.state, name, value)
        self.temp_dir.cleanup()

    def test_preset_metadata_is_available_without_vendor_key_and_requires_super_admin(self) -> None:
        response = self.client.get("/api/admin/providers/model-presets")
        self.assertEqual(response.status_code, 200, response.text)
        preset = response.json()["presets"][0]
        self.assertEqual(preset["label"], "智谱官方")
        self.assertEqual(preset["chat_models"][0]["id"], "glm-4.7-flash")
        self.assertEqual(preset["vision_models"][0]["id"], "glm-4.6v-flash")
        self.assertIn(False, [model["free"] for model in preset["chat_models"]])
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/admin/providers/model-presets").status_code, 401)
        employee = self.auth.create_user("synthetic-employee", "测试员工", "test-password-1234", UserRole.EMPLOYEE, must_change_password=False)
        token, _ = self.auth.create_session(employee["id"])
        self.client.cookies.set("zly_ai_video_studio_session", token)
        self.assertEqual(self.client.get("/api/admin/providers/model-presets").status_code, 403)

    def test_save_reload_and_key_encryption_for_both_purposes(self) -> None:
        for purpose, model in (("llm", "glm-4.7-flash"), ("vlm", "glm-4.6v-flash")):
            with self.subTest(purpose=purpose):
                response = self.client.put(f"/api/admin/providers/{purpose}", headers=self.headers, json={
                    "enabled": True, "base_url": ZHIPU_BASE_URL, "model": model, "api_key": "synthetic.secret",
                })
                self.assertEqual(response.status_code, 200, response.text)
                reloaded = self.client.get(f"/api/admin/providers/{purpose}").json()
                self.assertEqual(reloaded["base_url"], ZHIPU_BASE_URL)
                self.assertEqual(reloaded["model"], model)
                self.assertTrue(reloaded["has_api_key"])
                self.assertNotIn("synthetic.secret", json.dumps(reloaded))
                stored = self.store.get_llm_settings() if purpose == "llm" else self.store.get_vlm_settings()
                self.assertNotEqual(stored["api_key_encrypted"], "synthetic.secret")

    @patch("requests.Session.post")
    @patch("requests.Session.get")
    def test_saved_key_is_never_reused_for_another_endpoint(self, get: MagicMock, post: MagicMock) -> None:
        for service, model in ((self.llm, "glm-4.7-flash"), (self.vlm, "glm-4.6v-flash")):
            service.update({"enabled": True, "base_url": ZHIPU_BASE_URL, "model": model, "api_key": "synthetic.secret"})
            changed = {"base_url": "https://another-provider.example/v1", "model": model}
            for action in (service.list_catalog, service.test, service.update):
                with self.subTest(service=type(service).__name__, action=action.__name__):
                    with self.assertRaisesRegex((ValueError, RuntimeError), "API Key|Token"):
                        action(changed)
        get.assert_not_called()
        post.assert_not_called()

    @patch("requests.Session.get")
    def test_vision_free_only_excludes_paid_supplemental_models(self, get: MagicMock) -> None:
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"data": [{"id": "glm-4.7"}, {"id": "glm-4.6v"}]}
        response = self.client.post("/api/admin/providers/vlm/models", headers=self.headers, json={
            "base_url": ZHIPU_BASE_URL, "api_key": "synthetic.secret", "free_only": True,
        })
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()["models"]
        self.assertTrue(rows)
        self.assertTrue(all(row["free"] is True for row in rows))
        self.assertNotIn("glm-4.6v", [row["id"] for row in rows])

    @patch.object(OpenAICompatibleClient, "test_connection", return_value="隔离测试通过")
    def test_draft_probe_does_not_verify_the_saved_model_or_keep_an_old_success(self, probe: MagicMock) -> None:
        for service, model, other in ((self.llm, "glm-4.7-flash", "glm-4.7"), (self.vlm, "glm-4.6v-flash", "glm-4.6v")):
            with self.subTest(service=type(service).__name__):
                service.update({"enabled": True, "base_url": ZHIPU_BASE_URL, "model": model, "api_key": "synthetic.secret"})
                result = service.test({"model": other})
                self.assertEqual(result["last_test_status"], "成功")
                self.assertIsNone(service.public_config()["last_test_status"])
                service.test({"model": model})
                self.assertEqual(service.public_config()["last_test_status"], "成功")
                service.update({"enabled": True, "base_url": ZHIPU_BASE_URL, "model": other})
                self.assertIsNone(service.public_config()["last_test_status"])

    @patch.object(OpenAICompatibleClient, "list_model_catalog")
    def test_vision_reuse_uses_llm_endpoint_and_credential_even_with_a_draft_key(self, catalog: MagicMock) -> None:
        self.llm.update({"enabled": True, "base_url": ZHIPU_BASE_URL, "model": "glm-4.7-flash", "api_key": "synthetic.secret"})
        catalog.return_value = {"models": [], "provider": "zhipu", "message": None}
        with patch("backend.app.vlm_provider.OpenAICompatibleClient", wraps=OpenAICompatibleClient) as client:
            self.vlm.list_catalog({"use_llm_credentials": True, "base_url": "https://ignored.example/v1", "api_key": "wrong-draft-key"})
            client.assert_called_once_with(base_url=ZHIPU_BASE_URL, api_key="synthetic.secret")
        self.assertEqual(self.vlm.public_config()["llm_base_url"], ZHIPU_BASE_URL)

    @patch.object(OpenAICompatibleClient, "test_connection")
    def test_stale_probe_does_not_verify_a_connection_changed_while_waiting(self, probe: MagicMock) -> None:
        for service, model, other in ((self.llm, "glm-4.7-flash", "glm-4.7"), (self.vlm, "glm-4.6v-flash", "glm-4.6v")):
            service.update({"enabled": True, "base_url": ZHIPU_BASE_URL, "model": model, "api_key": "synthetic.secret"})

            def change_connection(*args: object, **kwargs: object) -> str:
                service.update({"enabled": True, "base_url": ZHIPU_BASE_URL, "model": other})
                return "旧测试已返回"

            probe.side_effect = change_connection
            service.test({"model": model})
            self.assertEqual(service.public_config()["model"], other)
            self.assertIsNone(service.public_config()["last_test_status"])

    def test_switching_reuse_mode_cannot_rebind_an_old_independent_key(self) -> None:
        self.llm.update({"enabled": True, "base_url": ZHIPU_BASE_URL, "model": "glm-4.7-flash", "api_key": "synthetic.llm"})
        self.vlm.update({"enabled": True, "base_url": "https://old-vision.example/v1", "model": "old-vision", "api_key": "old-independent-key"})
        self.vlm.update({"enabled": True, "use_llm_credentials": True, "base_url": ZHIPU_BASE_URL, "model": "glm-4.6v-flash"})
        self.assertIsNone(self.store.get_vlm_settings()["api_key_encrypted"])
        self.assertEqual(self.vlm.api_key(), "synthetic.llm")
        self.vlm.update({"enabled": True, "use_llm_credentials": False, "base_url": ZHIPU_BASE_URL, "model": "glm-4.6v-flash"})
        self.assertIsNone(self.vlm.api_key())
        with self.assertRaisesRegex(ValueError, "API Key"):
            self.vlm.test()

    @patch.object(OpenAICompatibleClient, "test_connection", return_value="隔离测试通过")
    @patch.object(OpenAICompatibleClient, "list_model_catalog", return_value={"models": [], "provider": "zhipu"})
    def test_empty_test_and_catalog_bodies_keep_saved_credential_reuse(self, catalog: MagicMock, probe: MagicMock) -> None:
        self.llm.update({"enabled": True, "base_url": ZHIPU_BASE_URL, "model": "glm-4.7-flash", "api_key": "synthetic.llm"})
        self.vlm.update({"enabled": True, "use_llm_credentials": True, "base_url": ZHIPU_BASE_URL, "model": "glm-4.6v-flash"})
        for suffix in ("test", "models"):
            with self.subTest(suffix=suffix):
                result = self.client.post(f"/api/admin/providers/vlm/{suffix}", headers=self.headers, json={})
                self.assertEqual(result.status_code, 200, result.text)
        probe.assert_called_once()
        catalog.assert_called_once()
