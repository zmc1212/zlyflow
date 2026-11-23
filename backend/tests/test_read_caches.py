from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main as main_module
from backend.tests.app_state_guard import isolated_lifespan_state
from backend.app.config import Settings
from backend.app.models import JobMode, JobStatus, UserRole


class WorkerStub:
    def __init__(self, *_args) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def enqueue(self, _job_id: str) -> None:
        pass


def output(path: str, *, status: str = "cloud") -> dict:
    return {
        "kind": "video" if path.endswith(".mp4") else "image",
        "path": path,
        "label": "生成结果",
        "delivery_status": status,
        "cloud_url": f"https://cdn.example.com/{path}",
    }


class ReadCacheEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self._original_settings = main_module.settings
        self._original_worker = main_module.JobWorker
        root = Path(self._directory.name)
        main_module.settings = Settings(workspace_dir=root, data_dir_override=str(root / "data"))
        main_module.JobWorker = WorkerStub
        # lifespan 会重建全部 app.state（含积分服务），用快照守卫避免临时库泄漏到后续模块。
        self._lifespan_guard = isolated_lifespan_state(main_module.app)
        self._lifespan_guard.__enter__()
        self._client_context = TestClient(main_module.app)
        self.client = self._client_context.__enter__()
        self.store = main_module.app.state.store

    def tearDown(self) -> None:
        self._client_context.__exit__(None, None, None)
        self._lifespan_guard.__exit__(None, None, None)
        main_module.settings = self._original_settings
        main_module.JobWorker = self._original_worker
        self._directory.cleanup()

    def create_session(self, user_id: str, name: str, role: UserRole = UserRole.EMPLOYEE) -> tuple[str, str]:
        user = main_module.app.state.auth_store.create_user(
            user_id, name, "secure-pass-123", role, must_change_password=False,
        )
        token, _ = main_module.app.state.auth_store.create_session(user["id"])
        return user["id"], token

    def create_job_with_output(self, job_id: str, owner_id: str, path: str) -> None:
        job = self.store.create(
            job_id, JobMode.MINIMAX_H3_T2V, "提示词", "", None, [],
            owner_user_id=owner_id, title=f"任务 {job_id}",
        )
        item_id = job["rounds"][-1]["generation_items"][0]["id"]
        self.store.update_generation(
            item_id, status=JobStatus.SUCCEEDED, stage="生成完成", progress=100, outputs=[output(path)],
        )

    def test_health_reuses_cached_probe_per_comfy_url(self) -> None:
        probe_result = {"reachable": True, "url": "http://comfy.example", "error": None}
        with patch.object(main_module.ComfyService, "health", return_value=probe_result) as probe:
            first = self.client.get("/api/health")
            second = self.client.get("/api/health")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(first.json()["comfy"], probe_result)

        self.store.update_comfy_settings(base_url="http://comfy.example:28188")
        with patch.object(main_module.ComfyService, "health", return_value=probe_result) as other_probe:
            self.client.get("/api/health")
        self.assertEqual(other_probe.call_count, 1)

    def test_library_endpoints_share_one_derived_cache_per_content_epoch(self) -> None:
        owner_id, token = self.create_session("cache-owner", "缓存用户")
        cookies = {"zly_ai_video_studio_session": token}
        self.create_job_with_output("cache-job-a", owner_id, "cache-a.png")

        with patch.object(self.store, "list_library_sources", wraps=self.store.list_library_sources) as sources:
            listing = self.client.get("/api/library", cookies=cookies)
            paged = self.client.get("/api/library/query", cookies=cookies)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(paged.status_code, 200)
        self.assertEqual([item["path"] for item in listing.json()], ["cache-a.png"])
        self.assertEqual(paged.json()["total"], 1)
        self.assertEqual(sources.call_count, 1)

        self.create_job_with_output("cache-job-b", owner_id, "cache-b.png")
        with patch.object(self.store, "list_library_sources", wraps=self.store.list_library_sources) as refreshed:
            paged = self.client.get("/api/library/query", cookies=cookies)
        self.assertEqual(refreshed.call_count, 1)
        self.assertEqual(paged.json()["total"], 2)
        self.assertEqual(
            {item["path"] for item in paged.json()["items"]},
            {"cache-a.png", "cache-b.png"},
        )

    def test_media_route_accepts_output_paths_with_directories(self) -> None:
        """带目录的输出路径必须以媒体字节返回，不能掉进 SPA 兜底拿到 200 HTML。"""
        owner_id, token = self.create_session("media-nested", "目录媒体用户")
        cookies = {"zly_ai_video_studio_session": token}
        nested = "zly-ai-video-studio/minimax_h3_image/20261119/frame.png"
        self.create_job_with_output("media-job-nested", owner_id, nested)
        main_module.settings.results_dir.mkdir(parents=True, exist_ok=True)
        (main_module.settings.results_dir / "frame.png").write_bytes(b"\x89PNG\r\n\x1a\nnested")

        response = self.client.get("/api/media/zly-ai-video-studio%2Fminimax_h3_image%2F20261119%2Fframe.png", cookies=cookies)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"\x89PNG\r\n\x1a\nnested")
        self.assertNotIn("text/html", response.headers.get("content-type", ""))

        missing = self.client.get("/api/media/zly-ai-video-studio%2Fmissing%2Fframe.png", cookies=cookies)
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn("text/html", missing.headers.get("content-type", ""))

        self.assertEqual(self.client.get("/api/not-a-real-endpoint", cookies=cookies).status_code, 404)

    def test_media_lookup_uses_epoch_index_and_keeps_owner_scope(self) -> None:
        owner_id, token = self.create_session("media-owner", "媒体用户")
        other_id, other_token = self.create_session("media-other", "其他用户")
        cookies = {"zly_ai_video_studio_session": token}
        other_cookies = {"zly_ai_video_studio_session": other_token}
        self.create_job_with_output("media-job-a", owner_id, "media-a.png")
        main_module.settings.results_dir.mkdir(parents=True, exist_ok=True)
        (main_module.settings.results_dir / "media-a.png").write_bytes(b"\x89PNG\r\n\x1a\npayload")

        with patch.object(self.store, "output_locations", wraps=self.store.output_locations) as locations:
            first = self.client.get("/api/media/media-a.png", cookies=cookies)
            second = self.client.get("/api/media/media-a.png", cookies=cookies)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.content, b"\x89PNG\r\n\x1a\npayload")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(locations.call_count, 1)

        self.assertEqual(self.client.get("/api/media/media-a.png", cookies=other_cookies).status_code, 404)

        self.create_job_with_output("media-job-b", owner_id, "media-b.png")
        (main_module.settings.results_dir / "media-b.png").write_bytes(b"\x89PNG\r\n\x1a\npayload-b")
        with patch.object(self.store, "output_locations", wraps=self.store.output_locations) as rebuilt:
            refreshed = self.client.get("/api/media/media-b.png", cookies=cookies)
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(refreshed.content, b"\x89PNG\r\n\x1a\npayload-b")
        self.assertEqual(rebuilt.call_count, 1)
