from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import requests
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import main as main_module
from backend.app.auth import csrf_token
from backend.app.config import Settings
from backend.app.db import DbConnection
from backend.app.director_jobs import default_image_workflow_id
from backend.app.grs_client import (
    GRS_INTERNATIONAL_BASE_URL, GRS_SUBMIT_TIMEOUT, GrsClient, GrsConnectionError, GrsError,
    GrsUncertainSubmitError, with_grs_billing_caution,
)
from backend.app.local_credential_key import ensure_local_credential_key
from backend.app.grs_provider import CredentialManager, GrsProviderService
from backend.app.models import JobMode, JobStatus, UserRole
from backend.app.qiniu_provider import QiniuProviderService
from backend.app.qiniu_storage import QiniuStorage, qiniu_upload_host
from backend.app.storage import JobStore
from backend.app.workflow_registry import (
    IMAGE_WORKFLOWS, grs_request_size, is_image_workflow, normalize_options, validate_references, workflow_for,
)
from backend.tests.app_state_guard import isolated_lifespan_state


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, headers: dict | None = None, content: bytes = b"") -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content

    def json(self):
        return self.payload

    def iter_content(self, _size: int):
        yield self._content

    def close(self):
        return None


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []

    def post(self, url: str, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    def get(self, url: str, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)


class RegistryTests(unittest.TestCase):
    def test_image_workflows_are_registry_driven(self) -> None:
        self.assertEqual(IMAGE_WORKFLOWS, {JobMode.GRS_GPT_IMAGE_2, JobMode.GRS_GPT_IMAGE_2_VIP})
        standard = workflow_for(JobMode.GRS_GPT_IMAGE_2)
        self.assertEqual(standard.media_type, "image")
        self.assertEqual(standard.executor, "grs")
        self.assertEqual(standard.max_references, 10)
        properties = standard.option_schema["properties"]
        self.assertEqual(properties["count"]["ui_group"], "primary")
        self.assertEqual(properties["aspect_ratio"]["ui_companions"], ["resolution", "count"])
        vip_properties = workflow_for(JobMode.GRS_GPT_IMAGE_2_VIP).option_schema["properties"]
        self.assertEqual(vip_properties["aspect_ratio"]["ui_companions"], ["resolution", "count", "custom_width", "custom_height"])
        self.assertEqual(properties["provider_model"]["ui_group"], "internal")
        self.assertEqual(properties["provider_model"]["default"], "gpt-image-2")

    def test_nano_banana_profiles_use_direct_size_mapping(self) -> None:
        banana = workflow_for("grs-nano-banana-2")
        ratios = banana.option_schema["properties"]["aspect_ratio"]["enum"]
        self.assertIn("1:8", ratios)
        self.assertEqual(banana.option_schema["properties"]["resolution"]["enum"], ["1K", "2K", "4K"])
        options = normalize_options("grs-nano-banana-2", {"aspect_ratio": "1:8", "resolution": "2K"})
        self.assertEqual(options["provider_model"], "nano-banana-2")
        self.assertEqual(grs_request_size("grs-nano-banana-2", options), ("1:8", "2K"))
        locked = workflow_for("grs-nano-banana-2-2k-cl")
        self.assertEqual(locked.option_schema["properties"]["resolution"]["enum"], ["2K"])
        self.assertTrue(is_image_workflow("grs-nano-banana-pro"))

    def test_standard_and_vip_option_matrix(self) -> None:
        standard = normalize_options(JobMode.GRS_GPT_IMAGE_2, {"aspect_ratio": "16:9", "count": 4})
        self.assertEqual(grs_request_size(JobMode.GRS_GPT_IMAGE_2, standard), ("16:9", "1K"))
        vip = normalize_options(JobMode.GRS_GPT_IMAGE_2_VIP, {"aspect_ratio": "21:9", "resolution": "4K"})
        self.assertEqual(grs_request_size(JobMode.GRS_GPT_IMAGE_2_VIP, vip), ("3840x1648", "4K"))
        custom = normalize_options(JobMode.GRS_GPT_IMAGE_2_VIP, {
            "resolution": "CUSTOM", "custom_width": 1600, "custom_height": 800,
        })
        self.assertEqual(grs_request_size(JobMode.GRS_GPT_IMAGE_2_VIP, custom), ("1600x800", None))
        with self.assertRaises(ValueError):
            normalize_options(JobMode.GRS_GPT_IMAGE_2_VIP, {
                "resolution": "CUSTOM", "custom_width": 1025, "custom_height": 1024,
            })
        with self.assertRaises(ValueError):
            normalize_options(JobMode.GRS_GPT_IMAGE_2_VIP, {"aspect_ratio": "1:3", "resolution": "1K"})

    def test_image_reference_limit(self) -> None:
        validate_references(JobMode.GRS_GPT_IMAGE_2, [object()] * 10)
        with self.assertRaises(ValueError):
            validate_references(JobMode.GRS_GPT_IMAGE_2, [object()] * 11)


class GptImage25RegistryTests(unittest.TestCase):
    def test_gpt_image_25_base_profile_is_1k_without_quality(self) -> None:
        base = workflow_for("grs-gpt-image-2.5")
        self.assertEqual(base.media_type, "image")
        self.assertEqual(base.executor, "grs")
        self.assertEqual(base.max_references, 10)
        properties = base.option_schema["properties"]
        self.assertEqual(properties["provider_model"]["default"], "gpt-image-2.5")
        self.assertEqual(properties["provider_model"]["ui_group"], "internal")
        self.assertEqual(properties["aspect_ratio"]["ui_group"], "primary")
        self.assertEqual(properties["aspect_ratio"]["ui_companions"], ["resolution", "count"])
        self.assertEqual(properties["resolution"]["enum"], ["1K"])
        self.assertNotIn("quality", properties)
        options = normalize_options("grs-gpt-image-2.5", {"aspect_ratio": "16:9"})
        self.assertEqual(grs_request_size("grs-gpt-image-2.5", options), ("1280x720", "1K"))
        auto = normalize_options("grs-gpt-image-2.5", {"aspect_ratio": "auto"})
        self.assertEqual(grs_request_size("grs-gpt-image-2.5", auto), ("auto", "1K"))

    def test_gpt_image_25_vip_quality_is_advanced_and_model_scoped(self) -> None:
        flare = workflow_for("grs-gpt-image-2.5-flare").option_schema["properties"]
        self.assertEqual(flare["quality"]["ui_group"], "advanced")
        self.assertEqual(flare["quality"]["enum"], ["low", "medium", "high"])
        self.assertEqual(flare["quality"]["default"], "medium")
        self.assertEqual(flare["resolution"]["enum"], ["1K", "2K", "4K"])
        sunburst = workflow_for("grs-gpt-image-2.5-sunburst").option_schema["properties"]
        self.assertEqual(sunburst["quality"]["enum"], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(sunburst["quality"]["default"], "high")
        options = normalize_options(
            "grs-gpt-image-2.5-flare",
            {"aspect_ratio": "21:9", "resolution": "2K", "quality": "high"},
        )
        self.assertEqual(options["quality"], "high")
        self.assertEqual(grs_request_size("grs-gpt-image-2.5-flare", options), ("2912x1248", "2K"))

    def test_gpt_image_25_rejects_unsupported_ratio_resolution_pair(self) -> None:
        with self.assertRaises(ValueError):
            normalize_options("grs-gpt-image-2.5-flare", {"aspect_ratio": "1:3", "resolution": "1K"})


class GrsCatalogTests(unittest.TestCase):
    def test_store_seeds_builtin_catalog_with_legacy_models_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            models = {item["provider_model"]: item for item in store.list_grs_image_models()}
            self.assertEqual(models["gpt-image-2"]["workflow_id"], "grs-gpt-image-2")
            self.assertTrue(models["gpt-image-2"]["enabled"])
            self.assertTrue(models["gpt-image-2-vip"]["enabled"])
            self.assertFalse(models["gpt-image-2"]["is_default"])
            self.assertTrue(models["gpt-image-2.5"]["is_default"])
            self.assertFalse(models["nano-banana-2"]["enabled"])
            self.assertEqual(models["nano-banana-2-2k-cl"]["resolutions"], ["2K"])
            enabled_ids = [item.id for item in GrsProviderService(store, Fernet.generate_key().decode()).enabled_image_workflows()]
            self.assertEqual(enabled_ids[0], "grs-gpt-image-2.5")
            self.assertIn("grs-gpt-image-2-vip", enabled_ids)
            self.assertNotIn("grs-nano-banana-2", enabled_ids)

    def test_store_migrates_extra_comma_separated_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
                connection.execute(
                    """CREATE TABLE grs_provider_settings (
                        id INTEGER PRIMARY KEY CHECK(id = 1),
                        enabled INTEGER NOT NULL DEFAULT 0,
                        base_url TEXT NOT NULL,
                        api_key_encrypted TEXT,
                        gpt_image_2_enabled INTEGER NOT NULL DEFAULT 1,
                        gpt_image_2_vip_enabled INTEGER NOT NULL DEFAULT 1,
                        models TEXT NOT NULL DEFAULT 'gpt-image-2',
                        vip_models TEXT NOT NULL DEFAULT 'gpt-image-2-vip',
                        last_test_status TEXT, last_test_message TEXT, last_test_at TEXT,
                        last_balance REAL, last_balance_at TEXT, updated_at TEXT NOT NULL
                    )"""
                )
                connection.execute(
                    """INSERT INTO grs_provider_settings
                    (id, enabled, base_url, gpt_image_2_enabled, gpt_image_2_vip_enabled, models, vip_models, updated_at)
                    VALUES (1, 1, 'https://grsai.dakka.com.cn', 1, 1, 'gpt-image-2,nano-banana-2', 'gpt-image-2-vip,custom-vip', ?)""",
                    ("2026-08-25T00:00:00+00:00",),
                )
                connection.commit()
            finally:
                connection.close()
            store = JobStore(path)
            models = {item["provider_model"]: item for item in store.list_grs_image_models()}
            self.assertTrue(models["nano-banana-2"]["enabled"])
            self.assertEqual(models["nano-banana-2"]["profile"], "nano_banana_2")
            self.assertTrue(models["custom-vip"]["enabled"])
            self.assertEqual(models["custom-vip"]["profile"], "gpt_image_2_vip")
            self.assertFalse(models["custom-vip"]["builtin"])

    def test_catalog_add_and_disable_controls_enabled_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            added = store.add_grs_image_model({
                "provider_model": "my-custom-model",
                "display_name": "自定义模型",
                "profile": "nano_banana",
                "enabled": True,
            })
            self.assertEqual(added["workflow_id"], "grs-my-custom-model")
            items = store.list_grs_image_models()
            for item in items:
                item["enabled"] = item["workflow_id"] in {"grs-gpt-image-2", "grs-my-custom-model"}
                item["is_default"] = item["workflow_id"] == "grs-my-custom-model"
            store.update_grs_image_models(items)
            service = GrsProviderService(store, Fernet.generate_key().decode())
            enabled_ids = [item.id for item in service.enabled_image_workflows()]
            self.assertIn("grs-gpt-image-2", enabled_ids)
            self.assertNotIn("grs-gpt-image-2-vip", enabled_ids)
            # 默认模型不再被钉在首位：未重排时仍按目录 sort_order 显示。
            self.assertEqual(enabled_ids[0], "grs-gpt-image-2")
            self.assertEqual(default_image_workflow_id(service), "grs-my-custom-model")

    def test_catalog_sort_order_is_independent_from_the_default_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            service = GrsProviderService(store, Fernet.generate_key().decode())
            visible = {"grs-nano-banana-2": 10, "grs-gpt-image-2": 20, "grs-gpt-image-2.5": 30}
            items = store.list_grs_image_models()
            for item in items:
                item["enabled"] = item["workflow_id"] in visible
                if item["workflow_id"] in visible:
                    item["sort_order"] = visible[item["workflow_id"]]
            store.update_grs_image_models(items)

            workflows = service.enabled_image_workflows()
            self.assertEqual([item.id for item in workflows], [
                "grs-nano-banana-2", "grs-gpt-image-2", "grs-gpt-image-2.5",
            ])
            self.assertEqual([item.is_default for item in workflows], [False, False, True])
            self.assertTrue(workflows[2].payload()["is_default"])
            # 导演台自动出图与复合工作流回落都认默认标记，不受显示顺序影响。
            self.assertEqual(default_image_workflow_id(service), "grs-gpt-image-2.5")
            self.assertEqual(service.resolve_composite_model("gpt-image-2-vip"), "gpt-image-2.5")

    def test_new_grs_image_model_appends_after_the_custom_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            items = store.list_grs_image_models()
            for index, item in enumerate(items):
                item["sort_order"] = (index + 1) * 10
            store.update_grs_image_models(items)
            added = store.add_grs_image_model({
                "provider_model": "brand-new-model", "display_name": "新导入模型",
                "profile": "nano_banana", "enabled": True,
            })
            self.assertEqual(added["sort_order"], len(items) * 10 + 10)
            self.assertEqual(store.list_grs_image_models()[-1]["provider_model"], "brand-new-model")

    def test_store_seeds_gpt_image_25_series_enabled_with_quality_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            models = {item["provider_model"]: item for item in store.list_grs_image_models()}
            for provider_model in ("gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"):
                self.assertTrue(models[provider_model]["enabled"], provider_model)
                self.assertTrue(models[provider_model]["builtin"], provider_model)
                self.assertEqual(models[provider_model]["profile"], "gpt_image_2_5_vip" if provider_model != "gpt-image-2.5" else "gpt_image_2_5")
            self.assertEqual(models["gpt-image-2.5-flare"]["quality_options"], ["low", "medium", "high"])
            self.assertEqual(models["gpt-image-2.5-flare"]["default_quality"], "medium")
            self.assertEqual(models["gpt-image-2.5-sunburst"]["quality_options"], ["low", "medium", "high", "xhigh", "max"])
            self.assertEqual(models["gpt-image-2.5-sunburst"]["default_quality"], "high")
            service = GrsProviderService(store, Fernet.generate_key().decode())
            self.assertEqual([item.id for item in service.enabled_image_workflows()][0], "grs-gpt-image-2.5")

    def test_legacy_catalog_migrates_gpt_image_25_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-catalog.db"
            timestamp = "2026-09-01T00:00:00+00:00"
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
                connection.execute(
                    """CREATE TABLE grs_image_models (
                        workflow_id TEXT PRIMARY KEY,
                        provider_model TEXT NOT NULL UNIQUE,
                        display_name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        profile TEXT NOT NULL,
                        resolutions_json TEXT,
                        enabled INTEGER NOT NULL DEFAULT 0,
                        sort_order INTEGER NOT NULL DEFAULT 100,
                        is_default INTEGER NOT NULL DEFAULT 0,
                        builtin INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )"""
                )
                for workflow_id, provider_model, profile, enabled, sort_order, is_default in (
                    ("grs-gpt-image-2", "gpt-image-2", "gpt_image_2", 1, 10, 1),
                    ("grs-gpt-image-2-vip", "gpt-image-2-vip", "gpt_image_2_vip", 1, 20, 0),
                    ("grs-nano-banana", "nano-banana", "nano_banana", 0, 30, 0),
                ):
                    connection.execute(
                        """INSERT INTO grs_image_models
                        (workflow_id, provider_model, display_name, description, profile, resolutions_json,
                         enabled, sort_order, is_default, builtin, created_at, updated_at)
                        VALUES (?, ?, ?, '', ?, NULL, ?, ?, ?, 1, ?, ?)""",
                        (workflow_id, provider_model, provider_model, profile, enabled, sort_order, is_default, timestamp, timestamp),
                    )
                connection.execute(
                    "INSERT INTO schema_migrations (name, applied_at) VALUES ('2026-08-25-grs-image-models-v1', ?)",
                    (timestamp,),
                )
                connection.execute(
                    """CREATE TABLE grs_provider_settings (
                        id INTEGER PRIMARY KEY CHECK(id = 1),
                        enabled INTEGER NOT NULL DEFAULT 0,
                        base_url TEXT NOT NULL,
                        api_key_encrypted TEXT,
                        gpt_image_2_enabled INTEGER NOT NULL DEFAULT 1,
                        gpt_image_2_vip_enabled INTEGER NOT NULL DEFAULT 1,
                        models TEXT NOT NULL DEFAULT 'gpt-image-2',
                        vip_models TEXT NOT NULL DEFAULT 'gpt-image-2-vip',
                        last_test_status TEXT, last_test_message TEXT, last_test_at TEXT,
                        last_balance REAL, last_balance_at TEXT, updated_at TEXT NOT NULL
                    )"""
                )
                connection.execute(
                    "INSERT INTO grs_provider_settings (id, enabled, base_url, updated_at) VALUES (1, 1, 'https://grsai.dakka.com.cn', ?)",
                    (timestamp,),
                )
                connection.commit()
            finally:
                connection.close()
            store = JobStore(path)
            models = {item["provider_model"]: item for item in store.list_grs_image_models()}
            self.assertEqual(len(models), 6)
            for provider_model in ("gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"):
                self.assertTrue(models[provider_model]["enabled"], provider_model)
                self.assertTrue(models[provider_model]["builtin"], provider_model)
            self.assertTrue(models["gpt-image-2.5"]["is_default"])
            self.assertTrue(models["gpt-image-2"]["enabled"])
            self.assertFalse(models["gpt-image-2"]["is_default"])
            self.assertFalse(models["nano-banana"]["enabled"])
            self.assertEqual(models["gpt-image-2.5-flare"]["quality_options"], ["low", "medium", "high"])
            service = GrsProviderService(store, Fernet.generate_key().decode())
            self.assertEqual([item.id for item in service.enabled_image_workflows()][0], "grs-gpt-image-2.5")


class GrsClientTests(unittest.TestCase):
    def test_submit_and_result_response_variants(self) -> None:
        session = FakeSession([
            FakeResponse({"data": {"taskId": "remote-1"}}),
            FakeResponse({"data": {"status": "completed", "result": {"image_url": "https://cdn.example.com/a.png"}}}),
        ])
        client = GrsClient("https://grs.example.com", "secret", session=session)
        remote_id = client.submit(model="gpt-image-2", prompt="test", images=[], aspect_ratio="1:1", image_size="1K")
        self.assertEqual(remote_id, "remote-1")
        status, urls, _ = client.result(remote_id)
        self.assertEqual(status, "completed")
        self.assertEqual(urls, ["https://cdn.example.com/a.png"])
        self.assertNotIn("secret", str(session.calls[0][2]["json"]))

    def test_result_accepts_succeeded_results_url(self) -> None:
        session = FakeSession([
            FakeResponse({"status": "succeeded", "results": [{"url": "https://file1.aitohumanize.com/a.png"}]}),
        ])
        client = GrsClient("https://grs.example.com", "secret", session=session)

        status, urls, message = client.result("remote-1")

        self.assertEqual(status, "succeeded")
        self.assertEqual(urls, ["https://file1.aitohumanize.com/a.png"])
        self.assertIsNone(message)

    def test_submit_forwards_quality_only_when_present(self) -> None:
        session = FakeSession([FakeResponse({"id": "remote-quality"})])
        client = GrsClient("https://grs.example.com", "secret", session=session)
        remote_id = client.submit(
            model="gpt-image-2.5-flare", prompt="test", images=[],
            aspect_ratio="1024x1024", image_size="1K", quality="low",
        )
        self.assertEqual(remote_id, "remote-quality")
        body = session.calls[0][2]["json"]
        self.assertEqual(body["quality"], "low")
        self.assertEqual(body["aspectRatio"], "1024x1024")
        self.assertEqual(body["imageSize"], "1K")
        plain_session = FakeSession([FakeResponse({"id": "remote-plain"})])
        plain_client = GrsClient("https://grs.example.com", "secret", session=plain_session)
        plain_client.submit(model="gpt-image-2", prompt="test", images=[], aspect_ratio="1:1", image_size="1K")
        self.assertNotIn("quality", plain_session.calls[0][2]["json"])

    def test_result_parses_http_400_violation_and_keeps_urls(self) -> None:
        session = FakeSession([
            FakeResponse(
                {
                    "id": "remote-1",
                    "status": "violation",
                    "error": "contains a photorealistic person",
                    "results": [{"url": "https://file1.aitohumanize.com/kept.png"}],
                },
                status_code=400,
            ),
        ])
        client = GrsClient("https://grs.example.com", "secret", session=session)

        status, urls, message = client.result("remote-1")

        self.assertEqual(status, "violation")
        self.assertEqual(urls, ["https://file1.aitohumanize.com/kept.png"])
        self.assertEqual(message, "contains a photorealistic person")
        self.assertIn("真人", client.format_failure(status, message))

    def test_result_http_400_without_urls_uses_body_error(self) -> None:
        session = FakeSession([
            FakeResponse({"status": "failed", "error": "generate failed"}, status_code=400),
        ])
        client = GrsClient("https://grs.example.com", "secret", session=session)

        status, urls, message = client.result("remote-1")

        self.assertEqual(status, "failed")
        self.assertEqual(urls, [])
        self.assertEqual(message, "generate failed")

    def test_result_succeeded_without_urls_keeps_polling(self) -> None:
        session = FakeSession([FakeResponse({"status": "succeeded", "results": []})])
        client = GrsClient("https://grs.example.com", "secret", session=session)

        status, urls, message = client.result("remote-1")

        self.assertEqual(status, "succeeded")
        self.assertEqual(urls, [])
        self.assertIsNone(message)

    def test_result_accepts_results_string_and_images_list(self) -> None:
        session = FakeSession([
            FakeResponse({"status": "succeeded", "results": "https://cdn.example.com/direct.png"}),
            FakeResponse({"status": "completed", "images": ["https://cdn.example.com/list.png"]}),
        ])
        client = GrsClient("https://grs.example.com", "secret", session=session)

        status, urls, _ = client.result("remote-1")
        self.assertEqual(status, "succeeded")
        self.assertEqual(urls, ["https://cdn.example.com/direct.png"])
        status, urls, _ = client.result("remote-2")
        self.assertEqual(status, "completed")
        self.assertEqual(urls, ["https://cdn.example.com/list.png"])

    def test_download_rejects_http_private_and_invalid_signature(self) -> None:
        client = GrsClient("https://grs.example.com", "secret", session=FakeSession([]), resolver=lambda _host: ["8.8.8.8"])
        with self.assertRaises(GrsError):
            client.download_image("http://cdn.example.com/a.png")
        private = GrsClient("https://grs.example.com", "secret", session=FakeSession([]), resolver=lambda _host: ["127.0.0.1"])
        with self.assertRaises(GrsError):
            private.download_image("https://cdn.example.com/a.png")
        invalid_session = FakeSession([FakeResponse({}, headers={"Content-Type": "image/png"}, content=b"not-an-image")])
        invalid = GrsClient("https://grs.example.com", "secret", session=invalid_session, resolver=lambda _host: ["8.8.8.8"])
        with self.assertRaises(GrsError):
            invalid.download_image("https://cdn.example.com/a.png")

    def test_download_allows_grs_benchmark_cdn_only(self) -> None:
        image = b"\x89PNG\r\n\x1a\ncontent"
        trusted_session = FakeSession([FakeResponse({}, headers={"Content-Type": "image/png"}, content=image)])
        trusted = GrsClient(
            "https://grs.example.com", "secret", session=trusted_session,
            resolver=lambda _host: ["198.18.1.176"],
        )

        filename, content = trusted.download_image("https://file1.aitohumanize.com/a.png")

        self.assertEqual(filename, "grs-result.png")
        self.assertEqual(content, image)
        file8_session = FakeSession([FakeResponse({}, headers={"Content-Type": "image/png"}, content=image)])
        file8 = GrsClient(
            "https://grs.example.com", "secret", session=file8_session,
            resolver=lambda _host: ["198.18.0.5"],
        )
        filename, content = file8.download_image("https://file8.aitohumanize.com/a.png")
        self.assertEqual(filename, "grs-result.png")
        self.assertEqual(content, image)
        proxy_v6_session = FakeSession([FakeResponse({}, headers={"Content-Type": "image/png"}, content=image)])
        proxy_v6 = GrsClient(
            "https://grs.example.com", "secret", session=proxy_v6_session,
            resolver=lambda _host: ["198.18.1.48", "fdfe:dcba:9876::15f"],
        )
        filename, content = proxy_v6.download_image("https://file5.aitohumanize.com/a.png")
        self.assertEqual(filename, "grs-result.png")
        self.assertEqual(content, image)
        translated_v6_session = FakeSession([FakeResponse({}, headers={"Content-Type": "image/png"}, content=image)])
        translated_v6 = GrsClient(
            "https://grs.example.com", "secret", session=translated_v6_session,
            resolver=lambda _host: ["198.18.6.105", "2001:2::64d"],
        )
        filename, content = translated_v6.download_image("https://file3.aitohumanize.com/a.png")
        self.assertEqual(filename, "grs-result.png")
        self.assertEqual(content, image)
        untrusted = GrsClient(
            "https://grs.example.com", "secret", session=FakeSession([]),
            resolver=lambda _host: ["198.18.1.176"],
        )
        with self.assertRaises(GrsError):
            untrusted.download_image("https://cdn.example.com/a.png")
        untrusted_v6 = GrsClient(
            "https://grs.example.com", "secret", session=FakeSession([]),
            resolver=lambda _host: ["fdfe:dcba:9876::15f"],
        )
        with self.assertRaises(GrsError):
            untrusted_v6.download_image("https://cdn.example.com/a.png")
        translated_untrusted = GrsClient(
            "https://grs.example.com", "secret", session=FakeSession([]),
            resolver=lambda _host: ["2001:2::64d"],
        )
        with self.assertRaises(GrsError):
            translated_untrusted.download_image("https://cdn.example.com/a.png")

    def test_format_failure_translates_upstream_generate_image_failed(self) -> None:
        self.assertEqual(GrsClient.format_failure("failed", "generate image failed"), "上游生图失败，请重新生成")

    def test_submit_retries_connect_timeout_then_succeeds(self) -> None:
        class FlakySession:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def post(self, url: str, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) == 1:
                    raise requests.exceptions.ConnectTimeout("connect timed out")
                return FakeResponse({"data": {"id": "remote-ok"}})

        session = FlakySession()
        client = GrsClient("https://grsai.dakka.com.cn", "secret", session=session)
        client._connect_retry_delay = 0

        remote_id = client.submit(model="gpt-image-2", prompt="test", images=[], aspect_ratio="1:1")

        self.assertEqual(remote_id, "remote-ok")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0]["timeout"], GRS_SUBMIT_TIMEOUT)

    def test_submit_connect_timeout_is_safe_to_retry(self) -> None:
        class DeadSession:
            def post(self, url: str, **kwargs):
                raise requests.exceptions.ConnectTimeout("connect timed out")

        client = GrsClient("https://grsai.dakka.com.cn", "secret", session=DeadSession())
        client._connect_retry_delay = 0

        with self.assertRaises(GrsConnectionError) as ctx:
            client.submit(model="gpt-image-2", prompt="test", images=[], aspect_ratio="1:1")

        message = str(ctx.exception)
        self.assertIn("不会扣费", message)
        self.assertIn(GRS_INTERNATIONAL_BASE_URL, message)
        self.assertNotIn("Max retries exceeded", message)
        self.assertNotIn("HTTPSConnectionPool", message)

    def test_submit_read_timeout_is_uncertain_and_does_not_duplicate_caution(self) -> None:
        class SlowSession:
            def post(self, url: str, **kwargs):
                raise requests.exceptions.ReadTimeout("read timed out")

        client = GrsClient("https://grs.example.com", "secret", session=SlowSession())

        with self.assertRaises(GrsUncertainSubmitError) as ctx:
            client.submit(model="gpt-image-2", prompt="test", images=[], aspect_ratio="1:1")

        message = str(ctx.exception)
        self.assertIn("等待响应超时", message)
        self.assertEqual(message.count("为避免重复扣费"), 1)
        self.assertEqual(with_grs_billing_caution(message), message)

    def test_balance_matches_smart_floor_planner_request_contract(self) -> None:
        session = FakeSession([FakeResponse({"code": 0, "data": {"credits": 321}})])
        client = GrsClient("https://grs.example.com", "secret", session=session)

        self.assertEqual(client.balance(), 321)
        method, url, request = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://grs.example.com/client/openapi/getAPIKeyCredits")
        self.assertEqual(request["json"], {"apiKey": "secret"})
        self.assertEqual(request["headers"], {"Content-Type": "application/json", "Accept": "application/json"})


class QiniuStorageTests(unittest.TestCase):
    def test_delete_accepts_sdk_success_and_612_as_idempotent_success(self) -> None:
        storage = object.__new__(QiniuStorage)
        storage.config = {"bucket": "test-bucket", "domain": "https://media.example.com", "object_prefix": "studio/"}
        storage._bucket_manager = Mock()
        for status in (200, 612):
            with self.subTest(status=status):
                info = SimpleNamespace(status_code=status, ok=lambda: status == 200)
                storage._bucket_manager.delete.reset_mock()
                storage._bucket_manager.delete.return_value = (None, info)
                self.assertTrue(storage.delete("studio/image/deleted.png"))
                storage._bucket_manager.delete.assert_called_once_with("test-bucket", "studio/image/deleted.png")

    def test_delete_does_not_treat_other_sdk_errors_as_missing_objects(self) -> None:
        storage = object.__new__(QiniuStorage)
        storage.config = {"bucket": "test-bucket"}
        storage._bucket_manager = Mock()
        for status in (401, 404, 500):
            with self.subTest(status=status):
                storage._bucket_manager.delete.return_value = (
                    None, SimpleNamespace(status_code=status, ok=lambda: False),
                )
                with self.assertRaisesRegex(RuntimeError, "七牛云删除失败"):
                    storage.delete("studio/image/result.png")

    def test_upload_host_matches_configured_region(self) -> None:
        self.assertEqual(qiniu_upload_host("cn-east-2"), "up-cn-east-2.qiniup.com")
        self.assertEqual(qiniu_upload_host("z0"), "up-z0.qiniup.com")

    def test_store_bytes_retries_transient_remote_disconnect(self) -> None:
        class Info:
            def __init__(self, status_code: int, exception: object | None = None) -> None:
                self.status_code = status_code
                self.exception = exception

            def ok(self) -> bool:
                return self.status_code == 200

            def __str__(self) -> str:
                return "remote upload response"

        class AuthStub:
            def upload_token(self, bucket: str, key: str, expires: int) -> str:
                return f"token:{bucket}:{key}:{expires}"

        class QiniuStub:
            def __init__(self) -> None:
                self.calls = 0

            def put_data(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    from http.client import RemoteDisconnected
                    return None, Info(-1, RemoteDisconnected("Remote end closed connection without response"))
                return {"key": _args[1]}, Info(200)

        storage = object.__new__(QiniuStorage)
        storage.config = {"bucket": "bucket", "object_prefix": "studio/"}
        storage._auth = AuthStub()
        storage._qiniu = QiniuStub()
        storage._upload_regions = []

        stored = storage.store_bytes("video", "result.mp4", b"video-bytes")
        self.assertEqual(stored.local_path, None)
        self.assertEqual(storage._qiniu.calls, 2)

    def test_object_url_is_canonical_https_path_not_signed(self) -> None:
        storage = object.__new__(QiniuStorage)
        storage.config = {"domain": "https://media.example.com/", "bucket": "bucket"}
        self.assertEqual(
            storage.object_url("studio/image/look.png"),
            "https://media.example.com/studio/image/look.png",
        )
        self.assertIsNone(storage.object_url(""))
        self.assertEqual(
            storage.object_url("studio/image/镜头 01.png"),
            "https://media.example.com/studio/image/%E9%95%9C%E5%A4%B4%2001.png",
        )


class JobEndpointTests(unittest.TestCase):
    def test_delete_terminal_job_returns_json_and_removes_the_record(self) -> None:
        class WorkerStub:
            def __init__(self, *_args) -> None:
                pass

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            original_worker = main_module.JobWorker
            root = Path(directory)
            main_module.settings = Settings(workspace_dir=root, data_dir_override=str(root / "data"))
            main_module.JobWorker = WorkerStub
            try:
                with isolated_lifespan_state(main_module.app), TestClient(main_module.app) as client:
                    user = main_module.app.state.auth_store.create_user(
                        "delete-test", "删除测试", "secure-pass-123", UserRole.SUPER_ADMIN, must_change_password=False,
                    )
                    token, _ = main_module.app.state.auth_store.create_session(user["id"])
                    main_module.app.state.store.create(
                        "delete-test-job", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [], owner_user_id=user["id"],
                    )
                    main_module.app.state.store.update("delete-test-job", status=JobStatus.SUCCEEDED)

                    response = client.delete(
                        "/api/jobs/delete-test-job",
                        headers={"X-CSRF-Token": csrf_token(token)},
                        cookies={"zly_ai_video_studio_session": token},
                    )

                    self.assertEqual(response.status_code, 200)
                    self.assertIn("application/json", response.headers["content-type"])
                    self.assertEqual(response.json(), {"id": "delete-test-job"})
                    with self.assertRaises(KeyError):
                        main_module.app.state.store.get("delete-test-job")
            finally:
                main_module.settings = original_settings
                main_module.JobWorker = original_worker

    def test_cancel_queued_job_marks_cancelled_and_rejects_terminal_cancel(self) -> None:
        class WorkerStub:
            def __init__(self, store, comfy, *_args) -> None:
                self.store = store
                self.comfy = comfy
                self.comfy.stopped = []
                def capture(prompt_id: str) -> None:
                    self.comfy.stopped.append(prompt_id)

                self.comfy.stop_prompt = capture

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            original_worker = main_module.JobWorker
            root = Path(directory)
            main_module.settings = Settings(workspace_dir=root, data_dir_override=str(root / "data"))
            main_module.JobWorker = WorkerStub
            try:
                with isolated_lifespan_state(main_module.app), TestClient(main_module.app) as client:
                    user = main_module.app.state.auth_store.create_user(
                        "cancel-test", "停止测试", "secure-pass-123", UserRole.SUPER_ADMIN, must_change_password=False,
                    )
                    token, _ = main_module.app.state.auth_store.create_session(user["id"])
                    headers = {"X-CSRF-Token": csrf_token(token)}
                    cookies = {"zly_ai_video_studio_session": token}
                    main_module.app.state.store.create(
                        "cancel-queued", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [], owner_user_id=user["id"],
                    )
                    main_module.app.state.store.create(
                        "cancel-running", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [], owner_user_id=user["id"],
                    )
                    main_module.app.state.store.set_comfy_execution("cancel-running", "prompt-9", "client-9", "generation")
                    main_module.app.state.store.create(
                        "cancel-done", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [], owner_user_id=user["id"],
                    )
                    main_module.app.state.store.update("cancel-done", status=JobStatus.SUCCEEDED)

                    queued = client.post("/api/jobs/cancel-queued/cancel", headers=headers, cookies=cookies)
                    self.assertEqual(queued.status_code, 200)
                    self.assertEqual(queued.json()["status"], "cancelled")
                    self.assertEqual(queued.json()["stage"], "已停止生成")

                    running = client.post("/api/jobs/cancel-running/cancel", headers=headers, cookies=cookies)
                    self.assertEqual(running.status_code, 200)
                    self.assertEqual(running.json()["status"], "cancelled")
                    self.assertIn("prompt-9", main_module.app.state.worker.comfy.stopped)

                    done = client.post("/api/jobs/cancel-done/cancel", headers=headers, cookies=cookies)
                    self.assertEqual(done.status_code, 409)
            finally:
                main_module.settings = original_settings
                main_module.JobWorker = original_worker

    def test_admin_can_filter_jobs_by_user_id_and_employee_cannot(self) -> None:
        class WorkerStub:
            def __init__(self, *_args) -> None:
                pass

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            original_worker = main_module.JobWorker
            root = Path(directory)
            main_module.settings = Settings(workspace_dir=root, data_dir_override=str(root / "data"))
            main_module.JobWorker = WorkerStub
            try:
                with isolated_lifespan_state(main_module.app), TestClient(main_module.app) as client:
                    admin = main_module.app.state.auth_store.create_user(
                        "filter-admin", "筛选管理员", "secure-pass-123", UserRole.SUPER_ADMIN, must_change_password=False,
                    )
                    employee = main_module.app.state.auth_store.create_user(
                        "filter-staff", "筛选员工", "secure-pass-123", UserRole.EMPLOYEE, must_change_password=False,
                    )
                    admin_token, _ = main_module.app.state.auth_store.create_session(admin["id"])
                    employee_token, _ = main_module.app.state.auth_store.create_session(employee["id"])
                    store = main_module.app.state.store
                    store.create(
                        "admin-job", JobMode.MINIMAX_H3_T2V, "admin prompt", "", None, [], owner_user_id=admin["id"],
                    )
                    store.create(
                        "staff-job", JobMode.MINIMAX_H3_T2V, "staff prompt", "", None, [], owner_user_id=employee["id"],
                    )
                    admin_cookies = {"zly_ai_video_studio_session": admin_token}
                    employee_cookies = {"zly_ai_video_studio_session": employee_token}

                    own = client.get("/api/jobs", cookies=admin_cookies)
                    self.assertEqual(own.status_code, 200)
                    self.assertEqual([job["id"] for job in own.json()], ["admin-job"])

                    staff = client.get(f"/api/jobs?user_id={employee['id']}", cookies=admin_cookies)
                    self.assertEqual(staff.status_code, 200)
                    self.assertEqual([job["id"] for job in staff.json()], ["staff-job"])

                    everyone = client.get("/api/jobs?user_id=all", cookies=admin_cookies)
                    self.assertEqual(everyone.status_code, 200)
                    self.assertEqual({job["id"] for job in everyone.json()}, {"admin-job", "staff-job"})

                    ignored = client.get(f"/api/jobs?user_id={admin['id']}", cookies=employee_cookies)
                    self.assertEqual(ignored.status_code, 200)
                    self.assertEqual([job["id"] for job in ignored.json()], ["staff-job"])

                    ignored_all = client.get("/api/jobs?user_id=all", cookies=employee_cookies)
                    self.assertEqual(ignored_all.status_code, 200)
                    self.assertEqual([job["id"] for job in ignored_all.json()], ["staff-job"])
            finally:
                main_module.settings = original_settings
                main_module.JobWorker = original_worker

    def test_round_reference_preview_uses_image_content_type_without_extension(self) -> None:
        class WorkerStub:
            def __init__(self, *_args) -> None:
                pass

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            original_worker = main_module.JobWorker
            root = Path(directory)
            main_module.settings = Settings(workspace_dir=root, data_dir_override=str(root / "data"))
            main_module.JobWorker = WorkerStub
            try:
                with isolated_lifespan_state(main_module.app), TestClient(main_module.app) as client:
                    user = main_module.app.state.auth_store.create_user(
                        "ref-preview", "参考图预览", "secure-pass-123", UserRole.SUPER_ADMIN, must_change_password=False,
                    )
                    token, _ = main_module.app.state.auth_store.create_session(user["id"])
                    uploads = main_module.settings.uploads_dir / user["id"] / "ref-job"
                    uploads.mkdir(parents=True, exist_ok=True)
                    image_path = uploads / "1_upload"
                    image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
                    job = main_module.app.state.store.create(
                        "ref-job", JobMode.MINIMAX_H3_I2V, "prompt", "", None, [str(image_path)], owner_user_id=user["id"],
                    )
                    round_id = job["rounds"][0]["id"]
                    cookies = {"zly_ai_video_studio_session": token}

                    listed = client.get("/api/jobs", cookies=cookies)
                    self.assertEqual(listed.status_code, 200)
                    payload = next(item for item in listed.json() if item["id"] == "ref-job")
                    self.assertEqual(payload["rounds"][0]["references"][0]["url"], f"/api/jobs/ref-job/rounds/{round_id}/references/1")

                    preview = client.get(payload["rounds"][0]["references"][0]["url"], cookies=cookies)
                    self.assertEqual(preview.status_code, 200)
                    self.assertIn("image/png", preview.headers.get("content-type", ""))
                    self.assertTrue(preview.content.startswith(b"\x89PNG"))
            finally:
                main_module.settings = original_settings
                main_module.JobWorker = original_worker


class JobCloudDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        class WorkerStub:
            def __init__(self, *_args) -> None:
                pass

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(main_module, "settings", Settings(
            workspace_dir=self.root, data_dir_override=str(self.root / "data"),
            resource_provider="browser-stream", secure_cookies=False,
        )))
        self.stack.enter_context(patch.object(main_module, "JobWorker", WorkerStub))
        self.stack.enter_context(patch(
            "backend.app.db._pymysql_connect", side_effect=AssertionError("测试不得连接 MySQL"),
        ))
        self.stack.enter_context(patch(
            "requests.sessions.Session.request", side_effect=AssertionError("测试不得发送真实网络请求"),
        ))
        self.client = self.stack.enter_context(TestClient(main_module.app))
        self.store = main_module.app.state.store
        self.assertEqual(self.store._db.dialect, "sqlite")
        auth_store = main_module.app.state.auth_store
        self.user = auth_store.create_user(
            "cloud-delete", "云端删除测试", "secure-pass-123", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.other = auth_store.create_user(
            "cloud-other", "其他员工", "secure-pass-123", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.token, _ = auth_store.create_session(self.user["id"])
        self.client.cookies.set("zly_ai_video_studio_session", self.token)
        self.headers = {"X-CSRF-Token": csrf_token(self.token)}
        self.cloud = object.__new__(QiniuStorage)
        self.cloud.config = {
            "domain": "https://media.example.com", "bucket": "test-bucket", "object_prefix": "studio/",
        }
        self.cloud._bucket_manager = Mock()
        self.cloud._bucket_manager.delete.return_value = self._sdk_result(200)
        self.cloud_delete = self.cloud._bucket_manager.delete
        self.stack.enter_context(patch.object(main_module.app.state, "resource_storage", self.cloud))

    def tearDown(self) -> None:
        self.stack.close()

    @staticmethod
    def _sdk_result(status: int) -> tuple:
        return None, SimpleNamespace(status_code=status, ok=lambda: status == 200)

    def _output(self, key: str, **overrides) -> dict:
        return {
            "kind": "image", "label": "生成图片", "path": key,
            "cloud_url": self.cloud.object_url(key), "delivery_status": "cloud", **overrides,
        }

    def _create_job(
        self, job_id: str = "cloud-job", *, outputs: list[dict] | None = None,
        references: list[str] | None = None, count: int = 1,
        owner_user_id: str | None = None, source: dict | None = None,
    ) -> dict:
        job = self.store.create(
            job_id, JobMode.GRS_GPT_IMAGE_2, "prompt", "", None, references or [], {"count": count},
            owner_user_id=owner_user_id or self.user["id"], source=source,
        )
        for index, item in enumerate(job["rounds"][0]["generation_items"]):
            self.store.update_generation(
                item["id"], status=JobStatus.SUCCEEDED, outputs=(outputs or []) if index == 0 else [],
            )
        return self.store.get(job_id, include_references=True)

    def _delete(self, job_id: str):
        return self.client.delete(f"/api/jobs/{job_id}", headers=self.headers)

    def _assert_blocked(self, job_id: str, status: int = 409) -> None:
        before = self.store.get(job_id, include_references=True)
        epoch = self.store.content_epoch()
        response = self._delete(job_id)
        self.assertEqual(response.status_code, status, response.text)
        self.assertTrue(response.json()["detail"])
        self.cloud_delete.assert_not_called()
        self.assertEqual(self.store.get(job_id, include_references=True), before)
        self.assertEqual(self.store.content_epoch(), epoch)

    def _assert_deleted(self, job: dict) -> None:
        with self.assertRaises(KeyError):
            self.store.get(job["id"])
        with self.store.connection() as connection:
            for round_data in job["rounds"]:
                self.assertIsNone(connection.execute(
                    "SELECT id FROM job_rounds WHERE id = ?", (round_data["id"],),
                ).fetchone())
                for item in round_data["generation_items"]:
                    self.assertIsNone(connection.execute(
                        "SELECT id FROM generation_items WHERE id = ?", (item["id"],),
                    ).fetchone())

    def test_deletes_all_rounds_items_legacy_mirror_and_previews_once_before_commit(self) -> None:
        upload = main_module.settings.uploads_dir / "reference.png"
        local = main_module.settings.staging_dir / "local.png"
        upload.write_bytes(b"uploaded-reference")
        local.write_bytes(b"local-output")
        reference_key = "studio/uploads/reference.png"
        shared = self._output("studio/image/shared.png")
        old = self._output("studio/image/old.png")
        second = self._output("studio/image/second.png")
        latest = self._output("studio/image/latest.png")
        unicode_output = self._output("studio/image/镜头 01.png", delivery_status="pending")
        unicode_output["cloud_url"] += "?e=123&token=test#preview"
        preview = self._output("studio/image/preview-only.png")
        mirror = self._output("studio/image/mirror-only.png")
        local_output = {"kind": "image", "label": "本地产物", "path": str(local), "delivery_status": "local"}
        job = self._create_job(
            outputs=[shared, old], count=2, references=[str(upload), self.cloud.object_url(reference_key)],
        )
        first_items = job["rounds"][0]["generation_items"]
        self.store.update_generation(first_items[1]["id"], outputs=[second])
        self.store.update_generation(first_items[0]["id"], refine_state={"preview_outputs": [preview, shared]})
        job = self.store.create_round(job["id"], prompt="next round", options={"count": 2})
        last_items = job["rounds"][-1]["generation_items"]
        self.store.update_generation(last_items[0]["id"], status=JobStatus.SUCCEEDED, outputs=[latest, shared, local_output])
        self.store.update_generation(last_items[1]["id"], status=JobStatus.SUCCEEDED, outputs=[unicode_output])
        # 历史镜像可能独有产物，不能只用最近一轮回填后的 outputs。
        with self.store.connection() as connection:
            connection.execute("UPDATE jobs SET outputs_json = ? WHERE id = ?", (
                json.dumps([mirror, shared, local_output]), job["id"],
            ))
        before = self.store.get(job["id"], include_references=True)
        keys = sorted(output["path"] for output in [shared, old, second, latest, unicode_output, preview, mirror])
        remaining = set(keys) | {reference_key}

        def delete_cloud(bucket, key):
            self.assertEqual(bucket, "test-bucket")
            self.assertEqual(self.store.get(job["id"], include_references=True), before)
            remaining.remove(key)
            return self._sdk_result(200)

        self.cloud_delete.side_effect = delete_cloud
        response = self._delete(job["id"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("application/json", response.headers["content-type"])
        self.assertEqual(response.json(), {"id": job["id"]})
        self.assertEqual(self.cloud_delete.call_args_list, [call("test-bucket", key) for key in keys])
        self._assert_deleted(before)
        self.assertEqual(remaining, {reference_key})
        self.assertEqual(upload.read_bytes(), b"uploaded-reference")
        self.assertEqual(local.read_bytes(), b"local-output")

    def test_local_outputs_and_uploaded_references_do_not_require_qiniu(self) -> None:
        upload = main_module.settings.uploads_dir / "keep-reference.png"
        local = main_module.settings.staging_dir / "keep-result.png"
        upload.write_bytes(b"reference")
        local.write_bytes(b"result")
        with patch.object(self.cloud, "provider_id", "browser-stream"):
            for index, outputs in enumerate(([], [{
                "kind": "image", "label": "本地结果", "path": str(local), "delivery_status": "local",
            }])):
                with self.subTest(outputs=outputs):
                    job = self._create_job(
                        f"local-{index}", outputs=outputs,
                        references=[str(upload), "https://media.example.com/studio/uploads/keep.png"],
                    )
                    response = self._delete(job["id"])
                    self.assertEqual(response.status_code, 200, response.text)
                    self._assert_deleted(job)
        self.cloud_delete.assert_not_called()
        self.assertEqual(upload.read_bytes(), b"reference")
        self.assertEqual(local.read_bytes(), b"result")

    def test_awaiting_refine_can_delete_preview_only_outputs(self) -> None:
        job = self._create_job()
        preview = self._output("studio/image/awaiting-preview.png")
        self.store.update_generation(
            job["rounds"][0]["generation_items"][0]["id"], status=JobStatus.AWAITING_REFINE,
            refine_state={"status": "awaiting", "preview_outputs": [preview]},
        )
        self.assertEqual(self.store.get(job["id"])["status"], JobStatus.AWAITING_REFINE.value)
        response = self._delete(job["id"])
        self.assertEqual(response.status_code, 200, response.text)
        self.cloud_delete.assert_called_once_with("test-bucket", preview["path"])
        self._assert_deleted(job)

    def test_second_key_failure_keeps_database_and_retry_accepts_sdk_612(self) -> None:
        keys = ["studio/image/a.png", "studio/image/b.png", "studio/image/c.png"]
        before = self._create_job(outputs=[self._output(key) for key in reversed(keys)])
        epoch = self.store.content_epoch()
        self.cloud_delete.side_effect = [
            self._sdk_result(200), self._sdk_result(500),
            self._sdk_result(612), self._sdk_result(200), self._sdk_result(200),
        ]
        response = self._delete(before["id"])
        self.assertEqual(response.status_code, 502, response.text)
        self.assertIn("任务记录已保留", response.json()["detail"])
        self.assertEqual(self.cloud_delete.call_args_list, [call("test-bucket", key) for key in keys[:2]])
        self.assertEqual(self.store.get(before["id"], include_references=True), before)
        self.assertEqual(self.store.content_epoch(), epoch)
        retry = self._delete(before["id"])
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json(), {"id": before["id"]})
        self.assertEqual(self.cloud_delete.call_args_list, [call("test-bucket", key) for key in keys[:2] + keys])
        self._assert_deleted(before)
        self.assertEqual(self.store.content_epoch(), epoch + 1)

    def test_storage_false_or_exception_returns_502_without_database_deletion(self) -> None:
        for index, failure in enumerate((False, TimeoutError("mock delete timeout"))):
            with self.subTest(failure=repr(failure)):
                keys = [f"studio/image/{index}-a.png", f"studio/image/{index}-b.png", f"studio/image/{index}-c.png"]
                before = self._create_job(f"failed-{index}", outputs=[self._output(key) for key in keys])
                with patch.object(self.cloud, "delete", side_effect=[True, failure]) as delete:
                    response = self._delete(before["id"])
                self.assertEqual(response.status_code, 502, response.text)
                self.assertEqual(delete.call_args_list, [call(key) for key in keys[:2]])
                self.assertEqual(self.store.get(before["id"], include_references=True), before)
        self.cloud_delete.assert_not_called()

    def test_auth_csrf_ownership_and_missing_job_never_call_cloud_delete(self) -> None:
        own = self._create_job(outputs=[self._output("studio/image/own.png")])
        foreign = self._create_job(
            "foreign-job", outputs=[self._output("studio/image/foreign.png")], owner_user_id=self.other["id"],
        )
        cases = (
            ("unauthenticated", None, self.headers, own["id"], 401),
            ("invalid-session", "invalid-session", self.headers, own["id"], 401),
            ("missing-csrf", self.token, {}, own["id"], 403),
            ("wrong-csrf", self.token, {"X-CSRF-Token": "wrong"}, own["id"], 403),
            ("foreign-owner", self.token, self.headers, foreign["id"], 404),
            ("missing-job", self.token, self.headers, "does-not-exist", 404),
        )
        for name, token, headers, job_id, expected in cases:
            with self.subTest(case=name):
                self.client.cookies.clear()
                if token:
                    self.client.cookies.set("zly_ai_video_studio_session", token)
                response = self.client.delete(f"/api/jobs/{job_id}", headers=headers)
                self.assertEqual(response.status_code, expected, response.text)
                self.cloud_delete.assert_not_called()
                self.assertEqual(self.store.get(own["id"], include_references=True), own)
                self.assertEqual(self.store.get(foreign["id"], include_references=True), foreign)

    def test_queued_or_running_parent_or_any_round_item_prevents_cleanup(self) -> None:
        for status in (JobStatus.QUEUED, JobStatus.RUNNING):
            for location in ("parent", "earlier-item", "latest-item"):
                with self.subTest(status=status.value, location=location):
                    job_id = f"busy-{status.value}-{location}"
                    job = self._create_job(job_id, outputs=[self._output(f"studio/image/{job_id}.png")], count=2)
                    job = self.store.create_round(job_id, prompt="latest", options={"count": 2})
                    for item in job["rounds"][-1]["generation_items"]:
                        self.store.update_generation(item["id"], status=JobStatus.SUCCEEDED)
                    # 保留主任务成功镜像，单独构造早轮/非首项仍在运行的快照。
                    with self.store.connection() as connection:
                        if location == "parent":
                            connection.execute("UPDATE jobs SET status = ? WHERE id = ?", (status.value, job_id))
                        else:
                            round_index = 0 if location == "earlier-item" else -1
                            item_id = job["rounds"][round_index]["generation_items"][1]["id"]
                            connection.execute("UPDATE generation_items SET status = ? WHERE id = ?", (status.value, item_id))
                    self._assert_blocked(job_id)

    def test_all_cloud_outputs_are_validated_before_deleting_even_duplicate_keys(self) -> None:
        good = self._output("studio/image/a-good.png")
        bad = self._output("studio/image/z-bad.png")
        cases = (
            ("provider-changed", [good], "local", "https://media.example.com"),
            ("domain-changed", [good], "qiniu", "https://new.example.com"),
            ("no-current-domain", [good], "qiniu", ""),
            ("missing-url", [good, {**bad, "cloud_url": None}], "qiniu", "https://media.example.com"),
            ("empty-url", [good, {**bad, "cloud_url": ""}], "qiniu", "https://media.example.com"),
            ("missing-key", [good, {**bad, "path": ""}], "qiniu", "https://media.example.com"),
            ("mixed-domain", [good, {**bad, "cloud_url": "https://other.example.com/studio/image/z-bad.png"}], "qiniu", "https://media.example.com"),
            ("mixed-path", [good, {**bad, "cloud_url": good["cloud_url"]}], "qiniu", "https://media.example.com"),
            ("mixed-scheme", [good, {**bad, "cloud_url": bad["cloud_url"].replace("https:", "http:")}], "qiniu", "https://media.example.com"),
            ("duplicate-conflict", [good, {**good, "cloud_url": "https://other.example.com/studio/image/a-good.png"}], "qiniu", "https://media.example.com"),
            ("url-with-local-status", [good, {**bad, "delivery_status": "local", "cloud_url": good["cloud_url"]}], "qiniu", "https://media.example.com"),
        )
        for name, outputs, provider, domain in cases:
            with self.subTest(case=name):
                job = self._create_job(name, outputs=outputs)
                with patch.object(self.cloud, "provider_id", provider), patch.dict(self.cloud.config, domain=domain):
                    self._assert_blocked(job["id"])

    def test_other_owner_job_outputs_references_sources_and_api_links_are_protected(self) -> None:
        cases = ("job-output", "item-output", "preview", "job-reference", "round-reference", "source", "api-link")
        for index, location in enumerate(cases):
            with self.subTest(location=location):
                keys = [f"studio/image/shared-{index}-a.png", f"studio/image/shared-{index}-z.png"]
                job = self._create_job(f"source-{index}", outputs=[self._output(key) for key in keys])
                other = self._create_job(f"consumer-{index}", owner_user_id=self.other["id"])
                round_id = other["rounds"][0]["id"]
                item_id = other["rounds"][0]["generation_items"][0]["id"]
                reference_url = self.cloud.object_url(keys[-1]) + "?e=456&token=other#ref"
                table, column, row_id, value = {
                    "job-output": ("jobs", "outputs_json", other["id"], json.dumps([self._output(keys[-1])])),
                    "item-output": ("generation_items", "outputs_json", item_id, json.dumps([self._output(keys[-1])])),
                    "preview": ("generation_items", "refine_state_json", item_id, json.dumps({"preview_outputs": [self._output(keys[-1])]})),
                    "job-reference": ("jobs", "references_json", other["id"], json.dumps([reference_url])),
                    "round-reference": ("job_rounds", "references_json", round_id, json.dumps([reference_url])),
                    "source": ("jobs", "source_job_id", other["id"], job["id"]),
                    "api-link": ("job_rounds", "options_json", round_id, json.dumps({"source": f"/api/jobs/{job['id']}/generations/old/outputs/0/download"})),
                }[location]
                with self.store.connection() as connection:
                    connection.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?", (value, row_id))
                other_before = self.store.get(other["id"], include_references=True)
                self._assert_blocked(job["id"])
                self.assertEqual(self.store.get(other["id"], include_references=True), other_before)
                # 解除引用后可删除，排除被上一 subTest 的数据偶然挡住。
                self.assertTrue(self.store.delete(other["id"]))
                response = self._delete(job["id"])
                self.assertEqual(response.status_code, 200, response.text)
                self._assert_deleted(job)
                self.cloud_delete.reset_mock()

    def test_canvas_smart_edit_featured_showcase_and_asset_references_are_protected(self) -> None:
        timestamp = "2026-11-06T00:00:00+00:00"
        # Media Studio 的表在 SQLite lifespan 不初始化；只在当前临时库补扫描所需列。
        with self.store.connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS ai_smart_edit_documents (id TEXT PRIMARY KEY, document_json TEXT)")
            connection.execute("CREATE TABLE IF NOT EXISTS ai_project_assets (id TEXT PRIMARY KEY, image_url TEXT, extra_json TEXT)")
            connection.execute(
                "INSERT INTO canvas_projects (id, owner_user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("reference-canvas", self.other["id"], "other owner's canvas", timestamp, timestamp),
            )
        defaults = {
            "canvas_projects": {"owner_user_id": self.other["id"], "title": "preview", "created_at": timestamp, "updated_at": timestamp},
            "canvas_drafts": {"canvas_id": "reference-canvas", "updated_at": timestamp},
            "canvas_draft_versions": {"canvas_id": "reference-canvas", "version": 1, "created_at": timestamp},
            "ai_smart_edit_documents": {},
            "ai_project_assets": {},
            "director_library_assets": {"owner_user_id": self.other["id"], "kind": "character", "name": "persistent asset", "created_at": timestamp, "updated_at": timestamp},
            "ai_featured_works": {"project_id": "foreign-project", "title": "featured", "snapshot_json": "{}", "published_at": timestamp, "updated_at": timestamp},
            "ai_showcase_items": {"slug": "test-showcase", "title": "showcase", "mode": "grs-gpt-image-2", "prompt": "example", "published_at": timestamp, "updated_at": timestamp},
        }
        cases = (
            ("canvas_projects", "preview_json", "url-json"),
            ("canvas_drafts", "content", "api-link"),
            ("canvas_draft_versions", "content", "escaped-url-json"),
            ("ai_smart_edit_documents", "document_json", "url-json"),
            ("ai_featured_works", "cover_url", "url"),
            ("ai_featured_works", "snapshot_json", "unicode-key-json"),
            ("ai_showcase_items", "source_job_id", "job-id"),
            ("ai_showcase_items", "cover_url", "url"),
            ("ai_showcase_items", "media_url", "url"),
            ("ai_showcase_items", "references_json", "url-json"),
            ("ai_showcase_items", "options_json", "api-link"),
            ("ai_project_assets", "image_url", "url"),
            ("ai_project_assets", "extra_json", "url-json"),
            ("director_library_assets", "image_job_id", "job-id"),
            ("director_library_assets", "image_path", "key"),
            ("director_library_assets", "image_url", "url"),
        )
        for index, (table, column, representation) in enumerate(cases):
            with self.subTest(table=table, column=column, representation=representation):
                keys = [f"studio/image/persistent-{index}-a.png", f"studio/image/persistent-{index}-镜头 01.png"]
                job = self._create_job(f"persistent-{index}", outputs=[self._output(key) for key in keys])
                url = self.cloud.object_url(keys[-1]) + "?e=789&token=other#asset"
                value = {
                    "url": url,
                    "key": keys[-1],
                    "job-id": job["id"],
                    "url-json": json.dumps({"nodes": [{"data": {"url": url}}]}),
                    "escaped-url-json": json.dumps({"media": [url]}).replace("/", "\\/"),
                    "unicode-key-json": json.dumps({"outputs": [{"path": keys[-1]}]}, ensure_ascii=True),
                    "api-link": json.dumps({"url": f"/api/jobs/{job['id']}/outputs/0/download"}),
                }[representation]
                row = {"id": f"ref-{index}", **defaults[table], column: value}
                if table == "canvas_drafts":
                    row.pop("id")
                id_column = "canvas_id" if table == "canvas_drafts" else "id"
                with self.store.connection() as connection:
                    connection.execute(
                        f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values()),
                    )
                    stored = dict(connection.execute(f"SELECT * FROM {table} WHERE {id_column} = ?", (row[id_column],)).fetchone())
                self._assert_blocked(job["id"])
                with self.store.connection() as connection:
                    self.assertEqual(dict(connection.execute(
                        f"SELECT * FROM {table} WHERE {id_column} = ?", (row[id_column],),
                    ).fetchone()), stored)
                    connection.execute(f"DELETE FROM {table} WHERE {id_column} = ?", (row[id_column],))
                response = self._delete(job["id"])
                self.assertEqual(response.status_code, 200, response.text)
                self._assert_deleted(job)
                self.cloud_delete.reset_mock()

    def test_deletion_rechecks_generation_status_after_initial_access_snapshot(self) -> None:
        job = self._create_job(outputs=[self._output("studio/image/race.png")], count=2)
        item_id = job["rounds"][0]["generation_items"][1]["id"]
        original = main_module.job_or_404

        def access_then_start(*args, **kwargs):
            stale = original(*args, **kwargs)
            self.store.update_generation(item_id, status=JobStatus.RUNNING)
            return stale

        with patch.object(main_module, "job_or_404", side_effect=access_then_start):
            response = self._delete(job["id"])
        self.assertEqual(response.status_code, 409, response.text)
        self.cloud_delete.assert_not_called()
        self.assertEqual(self.store.get_generation(item_id)["status"], JobStatus.RUNNING.value)
        self.assertEqual(len(self.store.get(job["id"])["rounds"][0]["generation_items"]), 2)

    def test_cascade_lock_failure_never_reaches_cloud_cleanup(self) -> None:
        job = self._create_job(outputs=[self._output("studio/image/lock-conflict.png")])
        epoch = self.store.content_epoch()
        execute = DbConnection.execute

        def fail_cascade(connection, sql, parameters=None, **kwargs):
            if sql.startswith("DELETE FROM jobs"):
                raise sqlite3.OperationalError("simulated cascade lock conflict")
            return execute(connection, sql, parameters, **kwargs)

        with patch.object(DbConnection, "execute", fail_cascade):
            with self.assertRaisesRegex(sqlite3.OperationalError, "cascade lock conflict"):
                self._delete(job["id"])
        self.cloud_delete.assert_not_called()
        self.assertEqual(self.store.get(job["id"], include_references=True), job)
        self.assertEqual(self.store.content_epoch(), epoch)

    def test_cleanup_uses_same_sqlite_transaction_and_holds_write_lock(self) -> None:
        job = self._create_job(outputs=[self._output("studio/image/locked.png")])
        original_scan = self.store.job_media_in_use
        connections = []

        def scan(job_id, keys, connection):
            self.assertTrue(connection._raw.in_transaction)
            connections.append(connection)
            return original_scan(job_id, keys, connection)

        def delete_cloud(_bucket, _key):
            self.assertEqual(len(connections), 1)
            self.assertTrue(connections[0]._raw.in_transaction)
            self.assertIsNone(connections[0].execute("SELECT id FROM jobs WHERE id = ?", (job["id"],)).fetchone())
            self.assertIsNone(connections[0].execute(
                "SELECT id FROM job_rounds WHERE job_id = ?", (job["id"],),
            ).fetchone())
            self.assertIsNone(connections[0].execute(
                "SELECT id FROM generation_items WHERE id = ?", (job["rounds"][0]["generation_items"][0]["id"],),
            ).fetchone())
            self.assertEqual(self.store.get(job["id"], include_references=True), job)
            competing = sqlite3.connect(main_module.settings.database_path, timeout=0)
            try:
                with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                    competing.execute("UPDATE jobs SET title = 'concurrent write' WHERE id = ?", (job["id"],))
            finally:
                competing.close()
            return self._sdk_result(200)

        self.cloud_delete.side_effect = delete_cloud
        with patch.object(self.store, "job_media_in_use", side_effect=scan) as checked:
            response = self._delete(job["id"])
        self.assertEqual(response.status_code, 200, response.text)
        checked.assert_called_once()
        self.cloud_delete.assert_called_once_with("test-bucket", "studio/image/locked.png")
        self._assert_deleted(job)


class StorageAndCredentialTests(unittest.TestCase):
    def test_job_metadata_can_be_pinned_renamed_and_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("metadata-job", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [], owner_user_id="user-a")

            updated = store.update_metadata("metadata-job", title="自定义标题", pinned=True, update_title=True)
            self.assertEqual(updated["title"], "自定义标题")
            self.assertTrue(updated["pinned"])
            self.assertEqual(store.list_jobs("user-a")[0]["id"], "metadata-job")

            self.assertTrue(store.delete("metadata-job"))
            with self.assertRaises(KeyError):
                store.get("metadata-job")

    def test_local_credential_key_is_created_once_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential.key"
            first = ensure_local_credential_key(path)
            second = ensure_local_credential_key(path)

            self.assertEqual(first, second)
            self.assertTrue(CredentialManager(first).ready)

    def test_migration_is_idempotent_and_preserves_job_id_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            store = JobStore(path)
            store.create("legacy-video", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.update("legacy-video", status=JobStatus.SUCCEEDED, outputs=[{"kind": "video", "path": "result.mp4", "label": "结果"}])
            reopened = JobStore(path)
            job = reopened.get("legacy-video")
            self.assertEqual(job["id"], "legacy-video")
            self.assertEqual(len(job["rounds"]), 1)
            self.assertEqual(job["outputs"][0]["path"], "result.mp4")
            self.assertTrue(path.with_name(f"{path.name}.pre-ai-studio-migration.bak").exists())

    def test_image_round_aggregates_partial_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            options = normalize_options(JobMode.GRS_GPT_IMAGE_2, {"count": 2})
            job = store.create("image-job", JobMode.GRS_GPT_IMAGE_2, "prompt", "", None, [], options)
            first, second = job["rounds"][0]["generation_items"]
            store.update_generation(first["id"], status=JobStatus.SUCCEEDED, progress=100, outputs=[{"kind": "image", "path": "a.png", "label": "A"}])
            store.update_generation(second["id"], status=JobStatus.FAILED, error="upstream failed")
            updated = store.get("image-job")
            self.assertEqual(updated["status"], JobStatus.PARTIAL.value)
            self.assertEqual(len(updated["outputs"]), 1)

    def test_image_round_failed_item_with_outputs_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            job = store.create("image-job", JobMode.GRS_GPT_IMAGE_2, "prompt", "", None, [])
            item = job["rounds"][0]["generation_items"][0]
            store.update_generation(
                item["id"], status=JobStatus.FAILED, error="later overwrite",
                outputs=[{"kind": "image", "path": "kept.png", "label": "生成图片"}],
            )
            updated = store.get("image-job")
            self.assertEqual(updated["status"], JobStatus.PARTIAL.value)
            self.assertEqual(updated["outputs"][0]["path"], "kept.png")

    def test_credentials_are_encrypted_masked_and_wrong_key_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            key = Fernet.generate_key().decode()
            provider = GrsProviderService(store, key)
            config = provider.update({
                "enabled": True, "base_url": "https://grs.example.com", "api_key": "top-secret-key",
                "gpt_image_2_enabled": True, "gpt_image_2_vip_enabled": True,
            })
            self.assertNotEqual(store.get_grs_settings()["api_key_encrypted"], "top-secret-key")
            self.assertNotIn("top-secret-key", config["api_key_masked"])
            wrong = GrsProviderService(store, Fernet.generate_key().decode())
            self.assertFalse(wrong.public_config()["available"])
            missing = CredentialManager(None)
            self.assertFalse(missing.ready)
            with self.assertRaises(ValueError):
                provider.update({"base_url": "http://grs.example.com", "api_key": None})

    def test_connection_can_use_an_unsaved_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            provider = GrsProviderService(store, Fernet.generate_key().decode())

            class FakeClient:
                def balance(self) -> float:
                    return 88

            captured: dict[str, str | None] = {}

            def client(*, base_url: str | None = None, api_key: str | None = None) -> FakeClient:
                captured.update(base_url=base_url, api_key=api_key)
                return FakeClient()

            provider.client = client  # type: ignore[method-assign]
            result = provider.test_connection(base_url="https://grs.example.com", api_key="unsaved-key")

            self.assertEqual(captured, {"base_url": "https://grs.example.com", "api_key": "unsaved-key"})
            self.assertEqual(result["last_test_status"], "success")
            self.assertEqual(result["last_balance"], 88)

    def test_balance_snapshot_returns_only_the_last_successful_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            provider = GrsProviderService(store, Fernet.generate_key().decode())
            store.update_grs_settings(last_balance=123.45, last_balance_at="2026-08-14T09:30:00+00:00")

            self.assertEqual(provider.balance_snapshot(), {
                "credits": 123.45,
                "queried_at": "2026-08-14T09:30:00+00:00",
            })

    def test_balance_refresh_is_rate_limited_and_updates_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            provider = GrsProviderService(store, Fernet.generate_key().decode())
            provider.update({
                "enabled": True, "base_url": "https://grs.example.com", "api_key": "top-secret-key",
                "gpt_image_2_enabled": True, "gpt_image_2_vip_enabled": True,
            })

            class FakeClient:
                calls = 0

                def balance(self) -> float:
                    self.calls += 1
                    return 98.5

            client = FakeClient()
            provider.client = lambda: client  # type: ignore[method-assign]

            self.assertEqual(provider.refresh_balance_snapshot(), {"credits": 98.5, "queried_at": store.get_grs_settings()["last_balance_at"]})
            self.assertEqual(provider.refresh_balance_snapshot(), {"credits": 98.5, "queried_at": store.get_grs_settings()["last_balance_at"]})
            self.assertEqual(client.calls, 1)

    def test_qiniu_settings_encrypt_credentials_and_require_complete_enablement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            provider = QiniuProviderService(store, Fernet.generate_key().decode())
            with self.assertRaises(ValueError):
                provider.update({"enabled": True})
            config = provider.update({
                "enabled": True, "access_key": "qiniu-access", "secret_key": "qiniu-secret",
                "bucket": "media-bucket", "region": "z0", "domain": "https://media.example.com",
                "object_prefix": "studio/",
            })
            saved = store.get_qiniu_settings()
            self.assertTrue(config["available"])
            self.assertTrue(config["has_access_key"])
            self.assertNotEqual(saved["access_key_encrypted"], "qiniu-access")
            self.assertNotEqual(saved["secret_key_encrypted"], "qiniu-secret")
            self.assertEqual(saved["object_prefix"], "studio/")
            wrong = QiniuProviderService(store, Fernet.generate_key().decode())
            self.assertFalse(wrong.public_config()["available"])

    def test_cloud_delivery_status_is_retained_in_job_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            job = store.create("cloud-video", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            item = job["rounds"][0]["generation_items"][0]
            store.update_generation(item["id"], status=JobStatus.SUCCEEDED, outputs=[{
                "kind": "video", "path": "video/key.mp4", "label": "视频",
            }])
            updated = store.mark_output_delivered("cloud-video", 0, "2026-08-14T00:00:00+00:00", "cloud")
            self.assertEqual(updated["outputs"][0]["delivery_status"], "cloud")


class FrontendSpaFallbackTests(unittest.TestCase):
    def test_generate_video_without_session_returns_index_and_does_not_capture_api(self) -> None:
        class WorkerStub:
            def __init__(self, *_args) -> None:
                pass

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            original_worker = main_module.JobWorker
            root = Path(directory)
            dist = root / "frontend" / "dist"
            (dist / "assets").mkdir(parents=True)
            (dist / "generation-home").mkdir(parents=True)
            (dist / "index.html").write_text("<!doctype html><html><body>spa-shell</body></html>", encoding="utf-8")
            (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
            (dist / "generation-home" / "director-coast.png").write_bytes(b"\x89PNG-fake")
            (root / "outside-dist.txt").write_text("OUTSIDE-DIST", encoding="utf-8")
            main_module.settings = Settings(workspace_dir=root, data_dir_override=str(root / "data"))
            main_module.JobWorker = WorkerStub
            try:
                with isolated_lifespan_state(main_module.app), TestClient(main_module.app) as client:
                    spa = client.get("/generate/video")
                    self.assertEqual(spa.status_code, 200)
                    self.assertIn("text/html", spa.headers.get("content-type", ""))
                    self.assertIn("spa-shell", spa.text)

                    assets_page = client.get("/assets")
                    self.assertEqual(assets_page.status_code, 200)
                    self.assertIn("spa-shell", assets_page.text)

                    director = client.get("/director/example-project")
                    self.assertEqual(director.status_code, 200)
                    self.assertIn("spa-shell", director.text)

                    status = client.get("/api/auth/status")
                    self.assertEqual(status.status_code, 200)
                    self.assertIn("application/json", status.headers.get("content-type", ""))
                    payload = status.json()
                    self.assertIn("authenticated", payload)
                    self.assertFalse(payload["authenticated"])

                    health = client.get("/api/health")
                    self.assertEqual(health.status_code, 200)
                    self.assertIn("application/json", health.headers.get("content-type", ""))

                    asset = client.get("/assets/app.js")
                    self.assertEqual(asset.status_code, 200)
                    self.assertIn("javascript", asset.headers.get("content-type", ""))
                    self.assertIn("console.log('ok')", asset.text)

                    cover = client.get("/generation-home/director-coast.png")
                    self.assertEqual(cover.status_code, 200)
                    self.assertEqual(cover.headers.get("content-type"), "image/png")
                    self.assertEqual(cover.content, b"\x89PNG-fake")

                    escape = client.get("/generation-home/%2e%2e%2f%2e%2e%2f%2e%2e%2foutside-dist.txt")
                    self.assertNotIn("OUTSIDE-DIST", escape.text)
                    if escape.status_code == 200:
                        self.assertIn("spa-shell", escape.text)
            finally:
                main_module.settings = original_settings
                main_module.JobWorker = original_worker


if __name__ == "__main__":
    unittest.main()
