from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app import main as main_module
from backend.app.auth import csrf_token
from backend.app.config import Settings
from backend.app.grs_client import GrsClient, GrsError
from backend.app.local_credential_key import ensure_local_credential_key
from backend.app.grs_provider import CredentialManager, GrsProviderService
from backend.app.models import JobMode, JobStatus, UserRole
from backend.app.qiniu_provider import QiniuProviderService
from backend.app.qiniu_storage import QiniuStorage, qiniu_upload_host
from backend.app.storage import JobStore
from backend.app.workflow_registry import (
    IMAGE_WORKFLOWS, grs_request_size, normalize_options, validate_references, workflow_for,
)


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
        untrusted = GrsClient(
            "https://grs.example.com", "secret", session=FakeSession([]),
            resolver=lambda _host: ["198.18.1.176"],
        )
        with self.assertRaises(GrsError):
            untrusted.download_image("https://cdn.example.com/a.png")

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
                with TestClient(main_module.app) as client:
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


class StorageAndCredentialTests(unittest.TestCase):
    def test_job_metadata_can_be_pinned_renamed_and_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("metadata-job", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [], owner_user_id="user-a")

            updated = store.update_metadata("metadata-job", title="自定义标题", pinned=True, update_title=True)
            self.assertEqual(updated["title"], "自定义标题")
            self.assertTrue(updated["pinned"])
            self.assertEqual(store.list_for_user("user-a")[0]["id"], "metadata-job")

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


if __name__ == "__main__":
    unittest.main()
