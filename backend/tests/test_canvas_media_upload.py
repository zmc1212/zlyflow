from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from backend.app.main import app, canvas_media_file, canvas_media_upload


def _request() -> SimpleNamespace:
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))


def _upload(filename: str, content: bytes = b"fixture", content_type: str = "application/octet-stream") -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content), headers=Headers({"content-type": content_type}))


class CanvasMediaUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self._sentinel = object()
        self._original_auth = getattr(app.state, "auth_store", self._sentinel)
        self._patch_settings = patch(
            "backend.app.main.settings",
            SimpleNamespace(uploads_dir=Path(self._directory.name)),
        )
        self._patch_settings.start()
        self.addCleanup(self._patch_settings.stop)
        app.state.auth_store = SimpleNamespace(audit=Mock())
        self.addCleanup(self._restore_auth)

    def _restore_auth(self) -> None:
        if self._original_auth is self._sentinel:
            if hasattr(app.state, "auth_store"):
                delattr(app.state, "auth_store")
        else:
            app.state.auth_store = self._original_auth

    def test_rejects_files_that_are_neither_image_nor_video(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(canvas_media_upload(_upload("notes.txt"), _request(), {"id": "alice"}))
        self.assertEqual(raised.exception.status_code, 422)
        app.state.auth_store.audit.assert_not_called()

    def test_upload_returns_site_url_and_audits(self) -> None:
        result = asyncio.run(canvas_media_upload(
            _upload("开场镜头.PNG", b"png-bytes", "image/png"), _request(), {"id": "alice"},
        ))
        self.assertEqual("image", result["kind"])
        self.assertEqual("开场镜头", result["label"])
        self.assertTrue(result["url"].startswith("/api/canvas/media/files/"))
        name = result["url"].rsplit("/", 1)[-1]
        self.assertTrue((Path(self._directory.name) / "alice" / "canvas-media" / name).is_file())
        self.assertEqual("canvas_media_upload", app.state.auth_store.audit.call_args.args[0])

    def test_video_suffix_is_normalized_and_served(self) -> None:
        result = asyncio.run(canvas_media_upload(
            _upload("clip.MOV", b"mov-bytes", "video/quicktime"), _request(), {"id": "alice"},
        ))
        self.assertEqual("video", result["kind"])
        name = result["url"].rsplit("/", 1)[-1]
        self.assertTrue(name.endswith(".mov"))
        response = canvas_media_file(name, {"id": "alice"})
        self.assertEqual("video/quicktime", response.media_type)

    def test_other_users_and_path_traversal_cannot_read_the_file(self) -> None:
        result = asyncio.run(canvas_media_upload(
            _upload("cat.png", b"png-bytes", "image/png"), _request(), {"id": "alice"},
        ))
        name = result["url"].rsplit("/", 1)[-1]
        for candidate, user in ((name, {"id": "bob"}), ("../alice/canvas-media/" + name, {"id": "alice"})):
            with self.subTest(candidate=candidate):
                with self.assertRaises(HTTPException) as raised:
                    canvas_media_file(candidate, user)
                self.assertEqual(raised.exception.status_code, 404)

    def test_size_limit_cleans_up_partial_file(self) -> None:
        with patch("backend.app.main.MAX_UPLOAD_BYTES", 3):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(canvas_media_upload(
                    _upload("big.png", b"more-than-three-bytes", "image/png"), _request(), {"id": "alice"},
                ))
        self.assertEqual(raised.exception.status_code, 413)
        directory = Path(self._directory.name) / "alice" / "canvas-media"
        self.assertEqual([], list(directory.glob("*")))


if __name__ == "__main__":
    unittest.main()
