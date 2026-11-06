from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.grs_catalog import (
    GRS_PROFILE_GPT_IMAGE_2_5, GRS_PROFILE_GPT_IMAGE_2_5_VIP, GRS_PROFILE_NANO_BANANA,
    GRS_PROFILE_NANO_BANANA_2, guess_profile, is_image_model_id, platform_entry,
)
from backend.app.grs_client import GrsClient, GrsError
from backend.app.grs_provider import GrsProviderService
from backend.app.storage import JobStore


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)


PLATFORM_MODELS = {
    "data": [
        {"id": "gemini-2.5-flash", "owned_by": "google"},
        {"id": "gpt-6-astra", "owned_by": "openai"},
        {"id": "gpt-image-2.5", "owned_by": "openai"},
        {"id": "gpt-image-2.6", "owned_by": "openai"},
        {"id": "nano-banana-2-lite", "owned_by": "google"},
        {"id": "nano-banana-pro-vip", "owned_by": "google"},
    ]
}


def provider_with_store(directory: str) -> tuple[GrsProviderService, JobStore]:
    store = JobStore(Path(directory) / "test.db")
    return GrsProviderService(store, Fernet.generate_key().decode()), store


class GrsClientListModelsTests(unittest.TestCase):
    def test_list_models_reads_the_openai_compatible_payload(self) -> None:
        session = FakeSession([FakeResponse(PLATFORM_MODELS)])
        client = GrsClient("https://grs.example.com", "key-1", session=session)

        self.assertEqual(client.list_models(), [
            "gemini-2.5-flash", "gpt-6-astra", "gpt-image-2.5", "gpt-image-2.6",
            "nano-banana-2-lite", "nano-banana-pro-vip",
        ])
        method, url, kwargs = session.calls[0]
        self.assertEqual((method, url), ("GET", "https://grs.example.com/v1/models"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer key-1")

    def test_list_models_rejects_a_payload_without_the_model_list(self) -> None:
        client = GrsClient("https://grs.example.com", "key-1", session=FakeSession([FakeResponse({"detail": "nope"})]))
        with self.assertRaises(GrsError):
            client.list_models()

    def test_list_models_surfaces_upstream_client_errors(self) -> None:
        client = GrsClient("https://grs.example.com", "key-1", session=FakeSession([FakeResponse({"detail": "x"}, 404)]))
        with self.assertRaises(GrsError):
            client.list_models()


class PlatformModelClassificationTests(unittest.TestCase):
    def test_chat_models_are_filtered_out(self) -> None:
        for value in ("gemini-2.5-flash", "gpt-6-astra", "gpt-5.6-sol", "", None):
            self.assertFalse(is_image_model_id(value), value)
        for value in ("gpt-image-2.6", "nano-banana-2-lite", "nano-banana-pro-vip", "gemini-3-pro-image"):
            self.assertTrue(is_image_model_id(value), value)

    def test_profile_guess_follows_the_model_family(self) -> None:
        self.assertEqual(guess_profile("gpt-image-2.6"), GRS_PROFILE_GPT_IMAGE_2_5)
        self.assertEqual(guess_profile("gpt-image-2.7-vip"), GRS_PROFILE_GPT_IMAGE_2_5_VIP)
        self.assertEqual(guess_profile("nano-banana-2.1"), GRS_PROFILE_NANO_BANANA_2)
        self.assertEqual(guess_profile("nano-banana-pro-max"), GRS_PROFILE_NANO_BANANA)
        self.assertEqual(guess_profile("flux-2-kontext"), GRS_PROFILE_NANO_BANANA)

    def test_builtin_entry_keeps_the_documented_parameters(self) -> None:
        entry = platform_entry("nano-banana-2-4k-cl")
        self.assertEqual(entry["profile"], GRS_PROFILE_NANO_BANANA_2)
        self.assertEqual(entry["resolutions"], ["4K"])
        self.assertEqual(entry["profile_source"], "builtin")

    def test_unknown_entry_gets_a_generated_display_name(self) -> None:
        entry = platform_entry("gpt-image-2.6")
        self.assertEqual(entry["display_name"], "GPT Image 2.6")
        self.assertEqual(entry["profile"], GRS_PROFILE_GPT_IMAGE_2_5)
        self.assertEqual(entry["profile_source"], "guess")
        self.assertFalse(entry["builtin"])


class FetchPlatformModelsTests(unittest.TestCase):
    def test_aligns_the_platform_list_with_the_local_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, store = provider_with_store(directory)
            provider.client = lambda **_kwargs: FakeListClient(PLATFORM_MODELS["data"])  # type: ignore[method-assign]
            store.add_grs_image_model({
                "provider_model": "nano-banana-2-lite", "display_name": "平台新模型",
                "profile": GRS_PROFILE_NANO_BANANA_2, "enabled": True,
            })

            result = provider.fetch_platform_models()

            self.assertEqual(result["total"], 6)
            listed = {item["provider_model"]: item for item in result["models"]}
            self.assertEqual(
                sorted(listed), ["gpt-image-2.5", "gpt-image-2.6", "nano-banana-2-lite", "nano-banana-pro-vip"],
            )
            self.assertTrue(listed["nano-banana-2-lite"]["in_catalog"])
            self.assertTrue(listed["nano-banana-2-lite"]["enabled"])
            self.assertEqual(listed["nano-banana-2-lite"]["display_name"], "平台新模型")
            self.assertFalse(listed["gpt-image-2.6"]["in_catalog"])
            self.assertEqual(listed["gpt-image-2.6"]["profile_source"], "guess")
            self.assertEqual(result["models"][0]["provider_model"], "gpt-image-2.6")
            off = {item["provider_model"] for item in result["off_platform"]}
            self.assertIn("nano-banana-pro-vt", off)
            self.assertNotIn("gpt-image-2.5", off)
            self.assertIsNone(result["message"])

    def test_reports_when_the_platform_has_no_image_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, _store = provider_with_store(directory)
            provider.client = lambda **_kwargs: FakeListClient([{"id": "gemini-2.5-flash"}])  # type: ignore[method-assign]

            result = provider.fetch_platform_models()

            self.assertEqual(result["models"], [])
            self.assertIn("没有识别出生图模型", result["message"])


class FakeListClient:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def list_models(self) -> list[str]:
        return [str(item["id"]) for item in self.rows]


class ImportPlatformModelsTests(unittest.TestCase):
    def test_import_creates_selected_models_and_skips_existing_ones(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, store = provider_with_store(directory)

            result = provider.import_platform_models([
                {"provider_model": "gpt-image-2.6", "display_name": "GPT Image 2.6", "profile": None, "enabled": True},
                {"provider_model": "gpt-image-2.5", "display_name": "已存在", "profile": None, "enabled": True},
            ])

            self.assertEqual(result["created"], ["grs-gpt-image-2.6"])
            self.assertEqual(result["skipped"], ["gpt-image-2.5"])
            saved = {item["provider_model"]: item for item in store.list_grs_image_models()}
            self.assertEqual(saved["gpt-image-2.6"]["profile"], GRS_PROFILE_GPT_IMAGE_2_5)
            self.assertEqual(saved["gpt-image-2.6"]["display_name"], "GPT Image 2.6")
            self.assertTrue(saved["gpt-image-2.6"]["enabled"])
            self.assertFalse(saved["gpt-image-2.6"]["builtin"])
            self.assertNotEqual(saved["gpt-image-2.5"]["display_name"], "已存在")

    def test_import_honours_the_administrator_profile_and_disabled_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, store = provider_with_store(directory)

            provider.import_platform_models([
                {"provider_model": "nano-banana-3", "display_name": "", "profile": GRS_PROFILE_NANO_BANANA, "enabled": False},
            ])

            saved = {item["provider_model"]: item for item in store.list_grs_image_models()}["nano-banana-3"]
            self.assertEqual(saved["profile"], GRS_PROFILE_NANO_BANANA)
            self.assertEqual(saved["display_name"], "Nano Banana 3")
            self.assertFalse(saved["enabled"])

    def test_import_rejects_an_unknown_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, _store = provider_with_store(directory)
            with self.assertRaises(ValueError):
                provider.import_platform_models([
                    {"provider_model": "nano-banana-9", "display_name": "X", "profile": "sora", "enabled": True},
                ])


if __name__ == "__main__":
    unittest.main()
