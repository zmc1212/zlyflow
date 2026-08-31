from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import requests
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import main as main_module
from backend.app.auth import csrf_token
from backend.app.config import Settings
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


class GrsCatalogTests(unittest.TestCase):
    def test_store_seeds_builtin_catalog_with_legacy_models_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            models = {item["provider_model"]: item for item in store.list_grs_image_models()}
            self.assertEqual(models["gpt-image-2"]["workflow_id"], "grs-gpt-image-2")
            self.assertTrue(models["gpt-image-2"]["enabled"])
            self.assertTrue(models["gpt-image-2-vip"]["enabled"])
            self.assertTrue(models["gpt-image-2"]["is_default"])
            self.assertFalse(models["nano-banana-2"]["enabled"])
            self.assertEqual(models["nano-banana-2-2k-cl"]["resolutions"], ["2K"])
            enabled_ids = [item.id for item in GrsProviderService(store, Fernet.generate_key().decode()).enabled_image_workflows()]
            self.assertEqual(enabled_ids[0], "grs-gpt-image-2")
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
            enabled_ids = [item.id for item in GrsProviderService(store, Fernet.generate_key().decode()).enabled_image_workflows()]
            self.assertEqual(enabled_ids[0], "grs-my-custom-model")
            self.assertIn("grs-gpt-image-2", enabled_ids)
            self.assertNotIn("grs-gpt-image-2-vip", enabled_ids)


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
        untrusted = GrsClient(
            "https://grs.example.com", "secret", session=FakeSession([]),
            resolver=lambda _host: ["198.18.1.176"],
        )
        with self.assertRaises(GrsError):
            untrusted.download_image("https://cdn.example.com/a.png")

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
                with TestClient(main_module.app) as client:
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
                with TestClient(main_module.app) as client:
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
                with TestClient(main_module.app) as client:
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
            (dist / "index.html").write_text("<!doctype html><html><body>spa-shell</body></html>", encoding="utf-8")
            (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
            main_module.settings = Settings(workspace_dir=root, data_dir_override=str(root / "data"))
            main_module.JobWorker = WorkerStub
            try:
                with TestClient(main_module.app) as client:
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
            finally:
                main_module.settings = original_settings
                main_module.JobWorker = original_worker


if __name__ == "__main__":
    unittest.main()
