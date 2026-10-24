from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.canvas_store import (
    PREVIEW_MAX_BYTES,
    PREVIEW_MAX_COVERS,
    CanvasConflictError,
    CanvasNotFoundError,
    CanvasStore,
    CanvasValidationError,
    _fit_canvas_preview,
    build_canvas_preview,
    canvas_checksum,
    decode_canvas_preview,
)
from backend.app.storage import JobStore


def canvas_content(nodes: list[dict] | None = None, edges: list[dict] | None = None) -> str:
    return json.dumps({"nodes": nodes or [], "edges": edges or []}, ensure_ascii=False)


class CanvasStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "canvas.db")
        self.canvas = CanvasStore(self.store)
        self.user_id = "user_canvas_test"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_project_seeds_empty_draft(self) -> None:
        project = self.canvas.create_project(self.user_id, "  分镜画布  ")
        self.assertEqual(project["title"], "分镜画布")
        self.assertEqual(project["version"], 1)
        self.assertEqual(project["node_count"], 0)
        self.assertEqual(json.loads(project["content"]), {"nodes": [], "edges": []})
        listed = self.canvas.list_projects(self.user_id)
        self.assertEqual([item["id"] for item in listed], [project["id"]])
        self.assertEqual(listed[0]["draft_version"], 1)

    def test_save_draft_increments_version_and_keeps_history(self) -> None:
        project = self.canvas.create_project(self.user_id, "画布")
        content = canvas_content([{"id": "n1", "type": "text", "position": {"x": 10, "y": 20}, "data": {"label": "开场"}}])
        saved = self.canvas.save_draft(
            self.user_id, project["id"], 1, content, canvas_checksum(content),
        )
        self.assertEqual(saved["version"], 2)
        self.assertEqual(saved["node_count"], 1)
        loaded = self.canvas.get_project(self.user_id, project["id"])
        self.assertEqual(loaded["version"], 2)
        self.assertEqual(loaded["content"], content)
        versions = self.canvas.list_versions(self.user_id, project["id"])
        self.assertEqual([item["version"] for item in versions], [2, 1])

    def test_stale_base_version_is_rejected(self) -> None:
        project = self.canvas.create_project(self.user_id, "画布")
        content = canvas_content()
        self.canvas.save_draft(self.user_id, project["id"], 1, content)
        with self.assertRaises(CanvasConflictError) as raised:
            self.canvas.save_draft(self.user_id, project["id"], 1, content)
        self.assertEqual(raised.exception.current_version, 2)

    def test_checksum_mismatch_and_invalid_payload_are_rejected(self) -> None:
        project = self.canvas.create_project(self.user_id, "画布")
        with self.assertRaises(CanvasValidationError):
            self.canvas.save_draft(self.user_id, project["id"], 1, canvas_content(), "bad-checksum")
        with self.assertRaises(CanvasValidationError):
            self.canvas.save_draft(self.user_id, project["id"], 1, "{}")
        with self.assertRaises(CanvasValidationError):
            self.canvas.save_draft(self.user_id, project["id"], 1, "not-json")

    def test_restore_version_writes_new_head(self) -> None:
        project = self.canvas.create_project(self.user_id, "画布")
        first = json.loads(project["content"])
        first["nodes"].append({"id": "n1", "type": "text", "position": {"x": 0, "y": 0}, "data": {"label": "第一版"}})
        first_content = canvas_content(first["nodes"], first["edges"])
        self.canvas.save_draft(self.user_id, project["id"], 1, first_content)
        second_content = canvas_content([], [])
        self.canvas.save_draft(self.user_id, project["id"], 2, second_content)
        restored = self.canvas.restore_version(self.user_id, project["id"], 2)
        self.assertEqual(restored["version"], 4)
        loaded = self.canvas.get_project(self.user_id, project["id"])
        self.assertEqual(loaded["content"], first_content)
        self.assertEqual(loaded["node_count"], 1)

    def test_projects_are_scoped_to_owner_and_deletable(self) -> None:
        project = self.canvas.create_project(self.user_id, "我的画布")
        with self.assertRaises(CanvasNotFoundError):
            self.canvas.get_project("someone_else", project["id"])
        self.canvas.delete_project(self.user_id, project["id"])
        with self.assertRaises(CanvasNotFoundError):
            self.canvas.get_project(self.user_id, project["id"])

    def test_rename_project(self) -> None:
        project = self.canvas.create_project(self.user_id, "旧标题")
        renamed = self.canvas.rename_project(self.user_id, project["id"], "新标题")
        self.assertEqual(renamed["title"], "新标题")
        with self.assertRaises(CanvasValidationError):
            self.canvas.rename_project(self.user_id, project["id"], "   ")

    def test_tags_and_favorite_are_normalized_and_persisted(self) -> None:
        project = self.canvas.create_project(self.user_id, "画布")
        self.assertEqual(project["tags"], [])
        self.assertFalse(project["is_favorite"])
        updated = self.canvas.update_project(
            self.user_id,
            project["id"],
            tags=[" 分镜 ", "雨夜", "分镜", "  "],
            is_favorite=True,
        )
        self.assertEqual(updated["tags"], ["分镜", "雨夜"])
        self.assertTrue(updated["is_favorite"])
        listed = self.canvas.list_projects(self.user_id)
        self.assertEqual(listed[0]["tags"], ["分镜", "雨夜"])
        self.assertTrue(listed[0]["is_favorite"])
        with self.assertRaises(CanvasValidationError):
            self.canvas.update_project(self.user_id, project["id"], tags=[f"标签{index}" for index in range(9)])
        with self.assertRaises(CanvasValidationError):
            self.canvas.update_project(self.user_id, project["id"], tags=["长" * 25])
        with self.assertRaises(CanvasValidationError):
            self.canvas.update_project(self.user_id, project["id"])

    def test_trash_filters_projects_and_restore(self) -> None:
        kept = self.canvas.create_project(self.user_id, "保留")
        trashed = self.canvas.create_project(self.user_id, "回收")
        self.canvas.trash_project(self.user_id, trashed["id"])
        active = self.canvas.list_projects(self.user_id)
        self.assertEqual([item["id"] for item in active], [kept["id"]])
        trash = self.canvas.list_projects(self.user_id, trashed=True)
        self.assertEqual([item["id"] for item in trash], [trashed["id"]])
        self.assertTrue(trash[0]["deleted_at"])
        with self.assertRaises(CanvasNotFoundError):
            self.canvas.get_project(self.user_id, trashed["id"])
        with self.assertRaises(CanvasNotFoundError):
            self.canvas.save_draft(self.user_id, trashed["id"], 1, canvas_content())
        with self.assertRaises(CanvasNotFoundError):
            self.canvas.list_versions(self.user_id, trashed["id"])
        with self.assertRaises(CanvasNotFoundError):
            self.canvas.update_project(self.user_id, trashed["id"], is_favorite=True)
        with self.assertRaises(CanvasNotFoundError):
            self.canvas.trash_project("someone_else", trashed["id"])
        with self.assertRaises(CanvasNotFoundError):
            self.canvas.restore_project("someone_else", trashed["id"])
        restored = self.canvas.restore_project(self.user_id, trashed["id"])
        self.assertIsNone(restored["deleted_at"])
        self.assertEqual(
            sorted(item["id"] for item in self.canvas.list_projects(self.user_id)),
            sorted([kept["id"], trashed["id"]]),
        )
        self.assertEqual(self.canvas.list_projects(self.user_id, trashed=True), [])

    def test_permanent_delete_after_trash(self) -> None:
        project = self.canvas.create_project(self.user_id, "待删除")
        self.canvas.trash_project(self.user_id, project["id"])
        self.canvas.delete_project(self.user_id, project["id"])
        self.assertEqual(self.canvas.list_projects(self.user_id), [])
        self.assertEqual(self.canvas.list_projects(self.user_id, trashed=True), [])
        with self.assertRaises(CanvasNotFoundError):
            self.canvas.get_project(self.user_id, project["id"])

    def test_preview_summary_tracks_bounds_nodes_links_and_safe_media(self) -> None:
        project = self.canvas.create_project(self.user_id, "缩略图")
        self.assertEqual(project["preview"]["items"], [])
        self.assertEqual(project["preview"]["nodeCount"], 0)
        nodes = [
            {
                "id": "artboard",
                "type": "artboard",
                "position": {"x": 100, "y": 100},
                "data": {"label": "画板"},
                "style": {"width": 800, "height": 600},
            },
            {
                "id": "image",
                "type": "image",
                "position": {"x": -50, "y": 20},
                "data": {"url": "/api/media/first.png"},
                "style": {"width": 320, "height": 200},
            },
            {
                "id": "generator",
                "type": "generator",
                "position": {"x": 900, "y": 30},
                "data": {"resultKind": "image", "resultUrl": "https://cdn.example/result.png"},
                "style": {"width": 340, "height": 240},
            },
            {
                "id": "text",
                "type": "text",
                "position": {"x": 0, "y": 800},
                "data": {"text": "开场"},
            },
            {
                "id": "unsafe",
                "type": "image",
                "position": {"x": 0, "y": 0},
                "data": {"url": "javascript:alert(1)"},
            },
            {
                "id": "inline",
                "type": "image",
                "position": {"x": 300, "y": 0},
                "data": {"url": "data:image/png;base64,AAAA"},
            },
        ]
        edges = [
            {"id": "e1", "source": "artboard", "target": "image"},
            {"id": "e2", "source": "image", "target": "generator"},
            {"id": "e3", "source": "generator", "target": "missing"},
        ]
        content = canvas_content(nodes, edges)
        self.canvas.save_draft(self.user_id, project["id"], 1, content)
        preview = self.canvas.list_projects(self.user_id)[0]["preview"]
        self.assertEqual(preview["x"], -50)
        self.assertEqual(preview["y"], 0)
        self.assertEqual(preview["width"], 1290)
        self.assertEqual(preview["height"], 920)
        self.assertEqual(preview["nodeCount"], 6)
        self.assertEqual(len(preview["items"]), 6)
        self.assertEqual(preview["links"], [[0, 1], [1, 2]])
        media_urls = [item["url"] for item in preview["items"] if item.get("url")]
        self.assertEqual(media_urls, ["/api/media/first.png", "https://cdn.example/result.png"])
        self.assertNotIn("javascript", json.dumps(preview))
        self.assertNotIn("data:image", json.dumps(preview))

    def test_preview_caps_items_links_and_payload_size(self) -> None:
        nodes = [
            {
                "id": f"node-{index}",
                "type": "image",
                "position": {"x": index * 80, "y": (index % 10) * 60},
                "data": {"url": "/api/media/" + ("a" * 700)},
            }
            for index in range(300)
        ]
        edges = [
            {"id": f"edge-{index}", "source": f"node-{index}", "target": f"node-{index + 1}"}
            for index in range(299)
        ]
        preview = build_canvas_preview({"nodes": nodes, "edges": edges})
        self.assertEqual(preview["nodeCount"], 300)
        self.assertLessEqual(len(preview["items"]), 120)
        self.assertLessEqual(len(preview["links"]), 80)
        self.assertLessEqual(
            len(json.dumps(preview, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            PREVIEW_MAX_BYTES,
        )
        self.assertGreater(preview["items"][-1]["x"], preview["items"][0]["x"])

    def test_preview_includes_only_matching_video_covers(self) -> None:
        cover = "data:image/jpeg;base64," + "A" * 4000
        nodes = [
            {
                "id": "valid",
                "type": "video",
                "position": {"x": 0, "y": 0},
                "data": {"url": "/api/media/a.mp4", "cover": cover, "coverSource": "/api/media/a.mp4"},
            },
            {
                "id": "stale",
                "type": "video",
                "position": {"x": 400, "y": 0},
                "data": {"url": "/api/media/b.mp4", "cover": cover, "coverSource": "/api/media/old.mp4"},
            },
            {
                "id": "unsafe",
                "type": "video",
                "position": {"x": 800, "y": 0},
                "data": {"url": "/api/media/c.mp4", "cover": "data:image/svg+xml;base64,AAAA", "coverSource": "/api/media/c.mp4"},
            },
            {
                "id": "image",
                "type": "image",
                "position": {"x": 1200, "y": 0},
                "data": {"url": "/api/media/d.png", "cover": cover, "coverSource": "/api/media/d.png"},
            },
        ]
        preview = build_canvas_preview({"nodes": nodes, "edges": []})
        self.assertEqual(preview["items"][0]["cover"], cover)
        self.assertNotIn("cover", preview["items"][1])
        self.assertNotIn("cover", preview["items"][2])
        self.assertNotIn("cover", preview["items"][3])

    def test_preview_caps_video_covers(self) -> None:
        cover = "data:image/png;base64," + "A" * 10_000
        nodes = [
            {
                "id": f"video-{index}",
                "type": "video",
                "position": {"x": index * 400, "y": 0},
                "data": {"url": f"/api/media/{index}.mp4", "cover": cover, "coverSource": f"/api/media/{index}.mp4"},
            }
            for index in range(PREVIEW_MAX_COVERS + 1)
        ]
        preview = build_canvas_preview({"nodes": nodes, "edges": []})
        covers = [item.get("cover") for item in preview["items"]]
        self.assertEqual(covers[:PREVIEW_MAX_COVERS], [cover] * PREVIEW_MAX_COVERS)
        self.assertIsNone(covers[PREVIEW_MAX_COVERS])
        self.assertLessEqual(
            len(json.dumps(preview, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            PREVIEW_MAX_BYTES,
        )

    def test_preview_fit_drops_covers_before_urls(self) -> None:
        cover = "data:image/jpeg;base64," + "A" * 50_000
        preview = {
            "x": 0,
            "y": 0,
            "width": 320,
            "height": 200,
            "nodeCount": 1,
            "items": [{
                "type": "video",
                "x": 0,
                "y": 0,
                "width": 320,
                "height": 200,
                "url": "/api/media/a.mp4",
                "cover": cover,
            }],
            "links": [],
        }
        fitted = _fit_canvas_preview(preview)
        self.assertNotIn("cover", fitted["items"][0])
        self.assertEqual(fitted["items"][0]["url"], "/api/media/a.mp4")
        self.assertLessEqual(
            len(json.dumps(fitted, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            PREVIEW_MAX_BYTES,
        )

    def test_preview_decode_filters_covers(self) -> None:
        cover = "data:image/webp;base64," + "A" * 1000
        decoded = decode_canvas_preview(json.dumps({
            "x": 0,
            "y": 0,
            "width": 400,
            "height": 200,
            "items": [
                {"type": "video", "x": 0, "y": 0, "width": 100, "height": 60, "cover": cover},
                {"type": "image", "x": 100, "y": 0, "width": 100, "height": 60, "cover": cover},
                {"type": "video", "x": 200, "y": 0, "width": 100, "height": 60, "cover": "javascript:alert(1)"},
                {"type": "video", "x": 300, "y": 0, "width": 100, "height": 60, "cover": "data:image/jpeg;base64," + "A" * 70_000},
            ],
            "links": [],
        }))
        self.assertEqual(decoded["items"][0]["cover"], cover)
        self.assertNotIn("cover", decoded["items"][1])
        self.assertNotIn("cover", decoded["items"][2])
        self.assertNotIn("cover", decoded["items"][3])

    def test_preview_decode_rejects_invalid_payloads(self) -> None:
        self.assertIsNone(decode_canvas_preview(None))
        self.assertIsNone(decode_canvas_preview("not-json"))
        self.assertIsNone(decode_canvas_preview(json.dumps({"items": []})))
        self.assertIsNone(decode_canvas_preview(json.dumps({
            "x": 0,
            "y": 0,
            "width": 100,
            "height": 100,
            "items": [{"type": "image", "x": 0, "y": 0, "width": 0, "height": 10}],
            "links": [],
        })))
        decoded = decode_canvas_preview(json.dumps({
            "x": -10,
            "y": -20,
            "width": 200,
            "height": 120,
            "nodeCount": 2,
            "items": [
                {"type": "image", "x": -10, "y": -20, "width": 80, "height": 60, "url": "/api/media/a.png"},
                {"type": "text", "x": 20, "y": 10, "width": 100, "height": 60, "url": "javascript:alert(1)"},
            ],
            "links": [[0, 1], [1, 1], [0, 5]],
        }))
        self.assertEqual(decoded["links"], [[0, 1]])
        self.assertNotIn("url", decoded["items"][1])

    def test_list_response_model_keeps_preview(self) -> None:
        from backend.app.models import CanvasProjectListItem

        project = self.canvas.create_project(self.user_id, "缩略图")
        content = canvas_content([{
            "id": "image",
            "type": "image",
            "position": {"x": 0, "y": 0},
            "data": {"url": "/api/media/a.png"},
            "style": {"width": 320, "height": 200},
        }])
        self.canvas.save_draft(self.user_id, project["id"], 1, content)
        listed = self.canvas.list_projects(self.user_id)[0]
        validated = CanvasProjectListItem.model_validate(listed)
        self.assertIsNotNone(validated.preview)
        self.assertEqual(validated.preview.nodeCount, 1)
        self.assertEqual(validated.preview.items[0].url, "/api/media/a.png")
        self.assertEqual(validated.model_dump()["preview"]["x"], 0)
