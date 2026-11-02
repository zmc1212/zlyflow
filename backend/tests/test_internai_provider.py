from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.auth import AuthStore, csrf_token
from backend.app.internai_catalog import (
    INTERNAI_BASE_URL,
    INTERNAI_FREE_MODELS,
    INTERNAI_METERED_MODELS,
    is_internai_official_base_url,
    internai_model_free,
    internai_provider_preset,
)
from backend.app.llm_capabilities import STRUCTURED_NONE, STRUCTURED_OBJECT, detect_capabilities
from backend.app.llm_client import catalog_provider_key, classify_model_free, parse_model_catalog
from backend.app.llm_provider import LlmProviderService, model_supports_vision
from backend.app.main import app
from backend.app.models import UserRole
from backend.app.storage import JobStore
from backend.app.zhipu_catalog import model_provider_presets


class InternaiEndpointTests(unittest.TestCase):
    def test_official_endpoint_match_is_strict(self) -> None:
        for base_url in ("https://discovery-api.intern-ai.org.cn", "https://discovery-api.intern-ai.org.cn/v1",
                         "https://discovery-api.intern-ai.org.cn/v1/"):
            with self.subTest(base_url=base_url):
                self.assertTrue(is_internai_official_base_url(base_url))
        for base_url in ("http://discovery-api.intern-ai.org.cn/v1", "https://discovery-api.intern-ai.org.cn.invalid/v1",
                         "https://discovery-api.intern-ai.org.cn/other", "https://user:secret@discovery-api.intern-ai.org.cn/v1",
                         "https://discovery-api.intern-ai.org.cn/v1?key=secret", "https://discovery-api.intern-ai.org.cn:8443/v1",
                         "https://chat.intern-ai.org.cn/api/v1/"):
            with self.subTest(base_url=base_url):
                self.assertFalse(is_internai_official_base_url(base_url))

    def test_provider_key_maps_discovery_gateway_only(self) -> None:
        self.assertEqual(catalog_provider_key(INTERNAI_BASE_URL), "internai")
        self.assertEqual(catalog_provider_key("https://discovery-api.intern-ai.org.cn/v1/"), "internai")
        # 旧平台与仿冒后缀域名不得借用端砚能力口径。
        self.assertEqual(catalog_provider_key("https://chat.intern-ai.org.cn/api/v1/"), "custom")
        self.assertEqual(catalog_provider_key("https://discovery-api.intern-ai.org.cn.evil.com/v1"), "custom")


class InternaiPricingTests(unittest.TestCase):
    def test_free_models_are_true_only_on_official_endpoint(self) -> None:
        for model in INTERNAI_FREE_MODELS:
            with self.subTest(model=model):
                self.assertIs(internai_model_free(INTERNAI_BASE_URL, model), True)
                self.assertIs(internai_model_free(INTERNAI_BASE_URL, model.upper()), True)
                self.assertIsNone(internai_model_free("https://relay.example/v1", model))

    def test_metered_models_are_false_and_unknown_stay_unknown(self) -> None:
        for model in INTERNAI_METERED_MODELS:
            with self.subTest(model=model):
                self.assertIs(internai_model_free(INTERNAI_BASE_URL, model), False)
        self.assertIsNone(internai_model_free(INTERNAI_BASE_URL, "some-new-model"))
        self.assertIsNone(internai_model_free(INTERNAI_BASE_URL, ""))

    def test_catalog_marks_known_models_and_upstream_metadata_wins(self) -> None:
        payload = {"data": [{"id": model} for model in (*INTERNAI_FREE_MODELS, *INTERNAI_METERED_MODELS)]
                           + [{"id": "brand-new-model"}]}
        rows = parse_model_catalog(payload, provider="internai", free_only=False, base_url=INTERNAI_BASE_URL)
        self.assertEqual({row["id"]: row["free"] for row in rows}, {
            **{model: True for model in INTERNAI_FREE_MODELS},
            **{model: False for model in INTERNAI_METERED_MODELS},
            "brand-new-model": None,
        })
        free_rows = parse_model_catalog(payload, provider="internai", free_only=True, base_url=INTERNAI_BASE_URL)
        self.assertEqual(sorted(row["id"] for row in free_rows), sorted(INTERNAI_FREE_MODELS))
        # 上游显式付费元数据仍然优先于端砚测试期提示。
        paid = classify_model_free({"id": "intern-s2", "free": False}, provider="internai", base_url=INTERNAI_BASE_URL)
        self.assertIs(paid, False)

    def test_vision_marker_covers_flash_vision(self) -> None:
        self.assertTrue(model_supports_vision("deepseek-v4-flash-vision"))
        self.assertFalse(model_supports_vision("deepseek-v4-flash-0731"))


class InternaiCapabilityTests(unittest.TestCase):
    def test_gateway_stays_conservative_like_modelscope(self) -> None:
        for model in ("intern-s2", "agents-a1", "atria-dawn-preview", "kimi-k2.6", "minimax-m3"):
            with self.subTest(model=model):
                caps = detect_capabilities(INTERNAI_BASE_URL, model)
                self.assertEqual(caps.provider, "internai")
                self.assertFalse(caps.native_tools)
                self.assertIsNone(caps.structured_output)
                self.assertIsNone(caps.prompt_cache)
                self.assertFalse(caps.web_search)
        for model in ("deepseek-v4-flash-0731", "glm-5.3", "qwen3.8-27b"):
            with self.subTest(model=model):
                caps = detect_capabilities(INTERNAI_BASE_URL, model)
                self.assertFalse(caps.native_tools)
                self.assertEqual(caps.structured_output, STRUCTURED_OBJECT)
        self.assertEqual(detect_capabilities(INTERNAI_BASE_URL, "deepseek-v4-flash-vision").structured_output, STRUCTURED_NONE)


class InternaiPresetTests(unittest.TestCase):
    def test_preset_is_registered_with_chat_and_vision_models(self) -> None:
        presets = model_provider_presets()["presets"]
        internai = next((row for row in presets if row["key"] == "internai"), None)
        self.assertIsNotNone(internai)
        self.assertEqual(internai["base_url"], INTERNAI_BASE_URL)
        self.assertEqual(internai["pricing_verified_at"], "2026-11-01")
        chat_ids = [row["id"] for row in internai["chat_models"]]
        self.assertEqual(len(chat_ids), len(INTERNAI_FREE_MODELS) + len(INTERNAI_METERED_MODELS))
        self.assertEqual(sorted(chat_ids), sorted([*INTERNAI_FREE_MODELS, *INTERNAI_METERED_MODELS]))
        self.assertEqual([row["free"] for row in internai["chat_models"] if row["id"] in INTERNAI_FREE_MODELS], [True] * len(INTERNAI_FREE_MODELS))
        self.assertEqual([row["id"] for row in internai["vision_models"]], ["deepseek-v4-flash-vision"])

    def test_preset_catalog_payloads_are_independent_copies(self) -> None:
        first = internai_provider_preset()
        second = internai_provider_preset()
        first["chat_models"][0]["free"] = False
        self.assertIs(second["chat_models"][0]["free"], True)


class InternaiAdminIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "internai.db")
        self.auth = AuthStore(Path(self.temp_dir.name) / "internai.db")
        key = Fernet.generate_key().decode()
        self.llm = LlmProviderService(self.store, key)
        self.previous_state = {name: getattr(app.state, name, None) for name in ("auth_store", "store", "llm_provider")}
        app.state.auth_store, app.state.store = self.auth, self.store
        app.state.llm_provider = self.llm
        admin = self.auth.create_user("synthetic-admin", "端砚测试", "test-password-1234", UserRole.SUPER_ADMIN, must_change_password=False)
        self.token, _ = self.auth.create_session(admin["id"])
        self.client = TestClient(app)
        self.client.cookies.set("zly_ai_video_studio_session", self.token)
        self.headers = {"X-CSRF-Token": csrf_token(self.token)}

    def tearDown(self) -> None:
        self.client.close()
        for name, value in self.previous_state.items():
            setattr(app.state, name, value)
        self.temp_dir.cleanup()

    def test_preset_endpoint_lists_internai_after_zhipu_and_qiniu(self) -> None:
        response = self.client.get("/api/admin/providers/model-presets")
        self.assertEqual(response.status_code, 200, response.text)
        keys = [row["key"] for row in response.json()["presets"]]
        self.assertEqual(keys, ["zhipu", "qiniu", "internai"])
        internai = response.json()["presets"][-1]
        self.assertEqual(internai["base_url"], INTERNAI_BASE_URL)
        self.assertTrue(any(row["free"] for row in internai["chat_models"]))


if __name__ == "__main__":
    unittest.main()
