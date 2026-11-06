from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.grs_catalog import GRS_PROFILE_GPT_IMAGE_2_5, GRS_PROFILE_NANO_BANANA_2
from backend.app.grs_client import GrsClient, GrsError
from backend.app.grs_provider import GrsProviderService
from backend.app.models import ModeResponse
from backend.app.storage import JobStore

MODEL_LIST_PAYLOAD = {
    "code": 0,
    "data": {
        "list": [
            {"name": "gpt-image-2.5", "type": "image", "cost": 8},
            {"name": "gpt-image-2.5-flare", "type": "image", "cost": "16.0"},
            {"name": "nano-banana-2", "type": "image", "cost": 0},
            {"name": "gemini-3-pro-image", "type": "image", "cost": None},
            {"name": "gpt-2.6", "type": "image"},
            {"name": "minimax-h3", "type": "video", "cost": 120},
            {"name": "deepseek-v3", "type": "text", "costType": 1, "cost": 2},
        ]
    },
}


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

    def post(self, url: str, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


class FakePlatformClient:
    def __init__(self, models: list[str], costs: dict[str, int] | None = None, *, fail_costs: bool = False) -> None:
        self.models = models
        self.costs = dict(costs or {})
        self.fail_costs = fail_costs
        self.cost_calls = 0

    def list_models(self) -> list[str]:
        return list(self.models)

    def model_costs(self) -> dict[str, int]:
        self.cost_calls += 1
        if self.fail_costs:
            raise GrsError("GRS 模型价格查询失败")
        return dict(self.costs)


def provider_with_store(directory: str) -> tuple[GrsProviderService, JobStore]:
    store = JobStore(Path(directory) / "test.db")
    return GrsProviderService(store, Fernet.generate_key().decode()), store


class GrsClientModelCostsTests(unittest.TestCase):
    def test_keeps_only_priced_image_models(self) -> None:
        session = FakeSession([FakeResponse(MODEL_LIST_PAYLOAD)])
        client = GrsClient("https://grs.example.com", "key-1", session=session)  # type: ignore[arg-type]

        self.assertEqual(client.model_costs(), {"gpt-image-2.5": 8, "gpt-image-2.5-flare": 16})
        method, url, kwargs = session.calls[0]
        self.assertEqual((method, url), ("POST", "https://grs.example.com/client/openapi/getModelList"))
        self.assertEqual(kwargs["json"], {"apiKey": "key-1"})

    def test_rejects_a_payload_without_the_model_list(self) -> None:
        client = GrsClient("https://grs.example.com", "key-1", session=FakeSession([FakeResponse({"code": 0, "data": {}})]))  # type: ignore[arg-type]
        with self.assertRaises(GrsError):
            client.model_costs()

    def test_surfaces_an_upstream_error_code(self) -> None:
        client = GrsClient(
            "https://grs.example.com", "key-1",
            session=FakeSession([FakeResponse({"code": 500, "msg": "价格表暂不可用"})]),  # type: ignore[arg-type]
        )
        with self.assertRaises(GrsError):
            client.model_costs()


class CatalogCostStorageTests(unittest.TestCase):
    def test_updates_known_models_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _provider, store = provider_with_store(directory)
            store.add_grs_image_model({
                "provider_model": "gpt-image-2.6", "display_name": "GPT Image 2.6",
                "profile": GRS_PROFILE_GPT_IMAGE_2_5, "enabled": True,
            })

            updated = store.set_grs_image_model_costs({
                "gpt-image-2.6": 12, "nano-banana-9": 30, "gpt-image-2.5": "0", "unknown": 5,
            })

            self.assertEqual(updated, 1)
            rows = {item["provider_model"]: item for item in store.list_grs_image_models()}
            self.assertEqual(rows["gpt-image-2.6"]["credit_cost"], 12)
            self.assertIsNone(rows["gpt-image-2.5"]["credit_cost"])

    def test_keeps_the_cost_when_the_administrator_reorders_the_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, store = provider_with_store(directory)
            store.set_grs_image_model_costs({"gpt-image-2.5": 8})
            models = store.list_grs_image_models()
            priced = next(item for item in models if item["provider_model"] == "gpt-image-2.5")

            store.update_grs_image_models([
                {
                    "workflow_id": item["workflow_id"], "display_name": item["display_name"],
                    "enabled": item["enabled"], "sort_order": index + 1,
                    "is_default": item["workflow_id"] == priced["workflow_id"],
                }
                for index, item in enumerate(models)
            ])

            rows = {item["workflow_id"]: item for item in provider.catalog_payload()["models"]}
            self.assertEqual(rows[priced["workflow_id"]]["credit_cost"], 8)
            self.assertTrue(rows[priced["workflow_id"]]["is_default"])


class ProviderCostRefreshTests(unittest.TestCase):
    def test_refresh_writes_costs_and_repeats_are_rate_limited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, store = provider_with_store(directory)
            client = FakePlatformClient(["gpt-image-2.5"], {"gpt-image-2.5": 8})
            provider.client = lambda **_kwargs: client  # type: ignore[method-assign]

            self.assertEqual(provider.refresh_model_costs(), 1)
            self.assertEqual(store.list_grs_image_models()[0]["credit_cost"], 8)
            self.assertEqual(provider.refresh_model_costs(), 0)
            self.assertEqual(client.cost_calls, 1)
            self.assertEqual(provider.refresh_model_costs(force=True), 1)
            self.assertEqual(client.cost_calls, 2)

    def test_upstream_failure_keeps_the_previous_costs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, store = provider_with_store(directory)
            provider.client = lambda **_kwargs: FakePlatformClient([], {"gpt-image-2.5": 8})  # type: ignore[method-assign]
            provider.refresh_model_costs(force=True)
            provider._costs_refresh_deadline = 0.0
            provider.client = lambda **_kwargs: FakePlatformClient([], fail_costs=True)  # type: ignore[method-assign]

            self.assertEqual(provider.refresh_model_costs(force=True), 0)
            self.assertEqual(store.list_grs_image_models()[0]["credit_cost"], 8)

    def test_fetch_reports_costs_and_descriptions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, _store = provider_with_store(directory)
            provider.client = lambda **_kwargs: FakePlatformClient(  # type: ignore[method-assign]
                ["gpt-image-2.5", "nano-banana-2"], {"gpt-image-2.5": 8, "nano-banana-2": 6},
            )

            listed = {item["provider_model"]: item for item in provider.fetch_platform_models()["models"]}

            self.assertEqual(listed["gpt-image-2.5"]["credit_cost"], 8)
            self.assertEqual(listed["nano-banana-2"]["credit_cost"], 6)
            self.assertTrue(listed["gpt-image-2.5"]["description"])

    def test_fetch_survives_a_failed_price_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, _store = provider_with_store(directory)
            provider.client = lambda **_kwargs: FakePlatformClient(  # type: ignore[method-assign]
                ["gpt-image-2.5"], fail_costs=True,
            )

            listed = provider.fetch_platform_models()["models"][0]

            self.assertIsNone(listed["credit_cost"])

    def test_import_stores_the_description_and_priced_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, store = provider_with_store(directory)
            provider.client = lambda **_kwargs: FakePlatformClient([], {"gpt-image-2.6": 10})  # type: ignore[method-assign]

            provider.import_platform_models([
                {"provider_model": "gpt-image-2.6", "display_name": "", "profile": None, "enabled": True},
            ])

            saved = {item["provider_model"]: item for item in store.list_grs_image_models()}["gpt-image-2.6"]
            self.assertEqual(saved["credit_cost"], 10)
            self.assertTrue(saved["description"])


class WorkflowCostExposureTests(unittest.TestCase):
    def test_modes_payload_carries_the_catalog_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, store = provider_with_store(directory)
            store.set_grs_image_model_costs({"gpt-image-2.5": 8})

            workflows = provider.enabled_image_workflows()
            priced = next(item for item in workflows if item.credit_cost)

            self.assertEqual(priced.credit_cost, 8)
            self.assertTrue(priced.description)

            payload = ModeResponse(**{**priced.payload(), "available": True, "unavailable_reason": None})
            self.assertEqual(payload.credit_cost, 8)

    def test_workflows_without_a_price_stay_null(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, store = provider_with_store(directory)
            store.add_grs_image_model({
                "provider_model": "nano-banana-2-lite", "display_name": "Nano Banana 2 Lite",
                "profile": GRS_PROFILE_NANO_BANANA_2, "enabled": True,
            })

            unpriced = {item.id for item in provider.enabled_image_workflows() if item.credit_cost is None}

            self.assertIn("grs-nano-banana-2-lite", unpriced)


if __name__ == "__main__":
    unittest.main()
