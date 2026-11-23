from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.library_query import build_library_entries, query_library_entries
from backend.tests.app_state_guard import isolated_lifespan_state


def output(
    *,
    kind: str = "image",
    path: str = "image.png",
    label: str = "生成图片",
    status: str = "cloud",
) -> dict:
    return {
        "kind": kind,
        "path": path,
        "label": label,
        "delivery_status": status,
        "cloud_url": f"https://cdn.example.com/{path}",
        "delivered_at": None,
    }


def job(
    job_id: str,
    title: str,
    prompt: str,
    created_at: str,
    *,
    items: list[tuple[str, list[dict]]] | None = None,
) -> dict:
    return {
        "id": job_id,
        "title": title,
        "prompt": prompt,
        "rounds": [{
            "created_at": created_at,
            "generation_items": [
                {"id": item_id, "outputs": outputs}
                for item_id, outputs in (items or [(f"{job_id}-item", [output()])])
            ],
        }],
    }


JOBS = [
    job(
        "job_old", "雨夜分镜", "霓虹街道开场", "2026-10-20T10:00:00+00:00",
        items=[("old-item", [output(path="old.png")])],
    ),
    job(
        "job_new", "室内对话", "午后窗边的两个人", "2026-10-22T10:00:00+00:00",
        items=[
            ("new-item-a", [output(path="new-a.png"), output(path="new-b.png", status="pending")]),
            ("new-item-b", [output(path="new-video.mp4", kind="video", label="生成视频")]),
        ],
    ),
    job(
        "job_local", "已交付到本机", "本机素材", "2026-10-23T10:00:00+00:00",
        items=[("local-item", [output(path="local.png", status="local")])],
    ),
    job(
        "job_expired", "已过期素材", "过期内容", "2026-10-23T11:00:00+00:00",
        items=[("expired-item", [output(path="expired.png", status="expired")])],
    ),
]


class LibraryEntryTests(unittest.TestCase):
    def test_build_entries_maps_source_and_download_url(self) -> None:
        entries = build_library_entries(JOBS)
        combined = [entry for entry in entries if entry["job_id"] == "job_new"]
        self.assertEqual([entry["path"] for entry in combined], ["new-a.png", "new-b.png", "new-video.mp4"])
        first = combined[0]
        self.assertEqual(first["job_title"], "室内对话")
        self.assertEqual(first["generation_item_id"], "new-item-a")
        self.assertEqual(first["output_index"], 0)
        self.assertEqual(first["created_at"], "2026-10-22T10:00:00+00:00")
        self.assertEqual(
            first["download_url"],
            "/api/jobs/job_new/generations/new-item-a/outputs/0/download",
        )
        self.assertEqual(combined[2]["output_index"], 0)
        self.assertEqual(combined[2]["kind"], "video")

    def test_build_entries_honors_api_prefix_and_skips_local_downloads_and_empty_paths(self) -> None:
        jobs = [job(
            "job_prefix", "前缀", "", "2026-10-22T12:00:00+00:00",
            items=[("prefix-item", [output(path="ok.png"), output(path=""), output(status="local")])],
        )]
        entries = build_library_entries(jobs, api_prefix="/studio/api/")
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            entries[0]["download_url"],
            "/studio/api/jobs/job_prefix/generations/prefix-item/outputs/0/download",
        )
        self.assertIsNone(entries[1]["download_url"])


class LibraryQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = build_library_entries(JOBS)

    def test_excludes_unavailable_and_sorts_newest_first(self) -> None:
        result = query_library_entries(self.entries, limit=100)
        paths = [entry["path"] for entry in result["items"]]
        self.assertEqual(paths, ["new-a.png", "new-b.png", "new-video.mp4", "old.png"])
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["counts"], {"image": 3, "video": 1})
        self.assertFalse(result["has_more"])

    def test_paginates_with_offset_and_reports_has_more(self) -> None:
        first = query_library_entries(self.entries, limit=3, offset=0)
        second = query_library_entries(self.entries, limit=3, offset=3)
        self.assertEqual([entry["path"] for entry in first["items"]], ["new-a.png", "new-b.png", "new-video.mp4"])
        self.assertTrue(first["has_more"])
        self.assertEqual([entry["path"] for entry in second["items"]], ["old.png"])
        self.assertFalse(second["has_more"])
        self.assertEqual(second["offset"], 3)

    def test_kind_filter_does_not_change_counts(self) -> None:
        result = query_library_entries(self.entries, kind="video")
        self.assertEqual([entry["path"] for entry in result["items"]], ["new-video.mp4"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["counts"], {"image": 3, "video": 1})
        empty = query_library_entries(self.entries, kind="image", offset=10)
        self.assertEqual(empty["items"], [])
        self.assertFalse(empty["has_more"])
        self.assertEqual(empty["counts"], {"image": 3, "video": 1})

    def test_search_matches_title_prompt_label_path_and_ids_case_insensitively(self) -> None:
        self.assertEqual(
            [entry["path"] for entry in query_library_entries(self.entries, q=" 室内 ")["items"]],
            ["new-a.png", "new-b.png", "new-video.mp4"],
        )
        self.assertEqual(
            [entry["path"] for entry in query_library_entries(self.entries, q="午后")["items"]],
            ["new-a.png", "new-b.png", "new-video.mp4"],
        )
        self.assertEqual(
            [entry["path"] for entry in query_library_entries(self.entries, q="生成视频")["items"]],
            ["new-video.mp4"],
        )
        self.assertEqual(
            [entry["path"] for entry in query_library_entries(self.entries, q="OLD.PNG")["items"]],
            ["old.png"],
        )
        self.assertEqual(
            [entry["path"] for entry in query_library_entries(self.entries, q="new-item-b")["items"]],
            ["new-video.mp4"],
        )
        self.assertEqual(query_library_entries(self.entries, q="不存在的素材")["items"], [])

    def test_search_ignores_unavailable_entries(self) -> None:
        result = query_library_entries(self.entries, q="已过期")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["counts"], {"image": 0, "video": 0})

    def test_exact_filters_target_insert_request(self) -> None:
        result = query_library_entries(
            self.entries, job_id="job_new", generation_item_id="new-item-a", output_index=1,
        )
        self.assertEqual([entry["path"] for entry in result["items"]], ["new-b.png"])
        self.assertEqual(result["total"], 1)
        by_job = query_library_entries(self.entries, job_id="job_new")
        self.assertEqual(len(by_job["items"]), 3)
        self.assertEqual(query_library_entries(self.entries, job_id="job_new", output_index=0)["total"], 2)
        self.assertEqual(
            query_library_entries(self.entries, job_id="job_new", generation_item_id="missing")["items"],
            [],
        )

    def test_clamps_limits_and_strips_internal_fields(self) -> None:
        clamped = query_library_entries(self.entries, limit=500, offset=-5)
        self.assertEqual(clamped["limit"], 100)
        self.assertEqual(clamped["offset"], 0)
        self.assertEqual(len(clamped["items"]), 4)
        self.assertTrue(all("_search_text" not in entry for entry in clamped["items"]))
        self.assertNotIn("job_prompt", clamped["items"][0])


class LibraryEndpointTests(unittest.TestCase):
    def test_endpoint_scopes_to_current_user_and_returns_page(self) -> None:
        from fastapi.testclient import TestClient

        from backend.app import main as main_module
        from backend.app.config import Settings
        from backend.app.models import JobMode, JobStatus, UserRole
        from backend.app.storage import JobStore

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
                # lifespan 会重建全部 app.state（含积分服务），用快照守卫避免临时库泄漏到后续模块。
                with isolated_lifespan_state(main_module.app), TestClient(main_module.app) as client:
                    store = main_module.app.state.store
                    owner = main_module.app.state.auth_store.create_user(
                        "library-owner", "作品库用户", "secure-pass-123", UserRole.EMPLOYEE, must_change_password=False,
                    )
                    other = main_module.app.state.auth_store.create_user(
                        "library-other", "其他用户", "secure-pass-123", UserRole.EMPLOYEE, must_change_password=False,
                    )
                    owner_token, _ = main_module.app.state.auth_store.create_session(owner["id"])
                    own_job = store.create(
                        "library-own-job", JobMode.MINIMAX_H3_T2V, "雨夜霓虹", "", None, [],
                        owner_user_id=owner["id"], title="雨夜分镜",
                    )
                    own_item = own_job["rounds"][-1]["generation_items"][0]["id"]
                    store.update_generation(
                        own_item, status=JobStatus.SUCCEEDED, stage="生成完成", progress=100,
                        outputs=[output(path="own.png")],
                    )
                    other_job = store.create(
                        "library-other-job", JobMode.MINIMAX_H3_T2V, "别的提示词", "", None, [],
                        owner_user_id=other["id"], title="别人的分镜",
                    )
                    other_item = other_job["rounds"][-1]["generation_items"][0]["id"]
                    store.update_generation(
                        other_item, status=JobStatus.SUCCEEDED, stage="生成完成", progress=100,
                        outputs=[output(path="other.png")],
                    )
                    cookies = {"zly_ai_video_studio_session": owner_token}
                    response = client.get(
                        "/api/library/query",
                        params={"q": "雨夜", "limit": 5},
                        cookies=cookies,
                    )
                    self.assertEqual(response.status_code, 200)
                    payload = response.json()
                    self.assertEqual(payload["total"], 1)
                    self.assertEqual(payload["items"][0]["path"], "own.png")
                    self.assertEqual(payload["items"][0]["job_title"], "雨夜分镜")
                    self.assertEqual(payload["counts"], {"image": 1, "video": 0})
                    self.assertEqual(payload["limit"], 5)
                    self.assertFalse(payload["has_more"])
                    exact = client.get(
                        f"/api/library/query?job_id={own_job['id']}&output_index=0",
                        cookies=cookies,
                    )
                    self.assertEqual([item["path"] for item in exact.json()["items"]], ["own.png"])
                    self.assertEqual(
                        client.get("/api/library/query?kind=audio", cookies=cookies).status_code, 422,
                    )
                    self.assertEqual(
                        client.get("/api/library/query?limit=101", cookies=cookies).status_code, 422,
                    )
            finally:
                main_module.settings = original_settings
                main_module.JobWorker = original_worker
