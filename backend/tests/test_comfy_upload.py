from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

import local_video_studio as legacy
from backend.app.comfy_service import ComfyService, ComfyUnavailable
from backend.app.config import Settings


class ComfyUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "reference.png"
        self.content = b"reference-image-content"
        self.source.write_bytes(self.content)
        self.service = ComfyService(
            Settings(workspace_dir=self.root),
            url_resolver=lambda: "http://configured-comfy:18188",
        )
        self.response = MagicMock(ok=True, status_code=200)
        self.response.json.return_value = {"name": "saved.png", "subfolder": "references"}

    def test_upload_allows_slow_body_send_and_preserves_remote_path(self) -> None:
        def post(url, **kwargs):
            self.assertEqual(url, "http://configured-comfy:18188/upload/image")
            self.assertEqual(kwargs["timeout"], (120, 180))
            self.assertEqual(kwargs["data"], {"overwrite": "true"})
            filename, stream, mime = kwargs["files"]["image"]
            self.assertTrue(filename.startswith("h3_reference_6_"))
            self.assertEqual(mime, "image/png")
            self.assertEqual(stream.read(), self.content)
            return self.response

        with patch("backend.app.comfy_service.requests.post", side_effect=post) as upload:
            result = self.service.upload_image(str(self.source), "h3_reference_6")

        self.assertEqual(result, "references/saved.png")
        upload.assert_called_once()
        self.assertTrue(upload.call_args.kwargs["files"]["image"][1].closed)

    def test_network_retry_reopens_from_start_and_reuses_remote_name(self) -> None:
        attempts: list[tuple[str, int, bytes]] = []

        def post(url, **kwargs):
            filename, stream, _ = kwargs["files"]["image"]
            attempts.append((filename, stream.tell(), stream.read()))
            if len(attempts) == 1:
                raise requests.ConnectionError(TimeoutError("timed out"))
            return self.response

        with (
            patch("backend.app.comfy_service.requests.post", side_effect=post),
            patch("backend.app.comfy_service.time.sleep") as sleep,
            self.assertLogs("backend.app.comfy_service", level="WARNING") as logs,
        ):
            result = self.service.upload_image(str(self.source), "h3_reference_6")

        self.assertEqual(result, "references/saved.png")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(attempts[1][1:], (0, self.content))
        sleep.assert_called_once_with(1)
        self.assertIn("ConnectionError", logs.output[0])
        self.assertIsNotNone(logs.records[0].exc_info)

    def test_exhausted_retries_preserve_original_failure_and_log_details(self) -> None:
        error = requests.ConnectionError(TimeoutError("timed out"))
        with (
            patch("backend.app.comfy_service.requests.post", side_effect=error) as upload,
            patch("backend.app.comfy_service.time.sleep") as sleep,
            self.assertLogs("backend.app.comfy_service", level="WARNING") as logs,
            self.assertRaises(ComfyUnavailable) as raised,
        ):
            self.service.upload_image(str(self.source), "h3_reference_6")

        self.assertEqual(upload.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
        self.assertIs(raised.exception.__cause__, error)
        for text in (self.source.name, "MB", "ConnectionError", "timed out", "任务尚未提交"):
            self.assertIn(text, str(raised.exception))
        self.assertEqual(len(logs.records), 3)
        self.assertIn("attempt=3/3", logs.output[-1])
        self.assertIn("elapsed=", logs.output[-1])
        self.assertIsNotNone(logs.records[-1].exc_info)

    def test_invalid_request_does_not_retry(self) -> None:
        with (
            patch("backend.app.comfy_service.requests.post", side_effect=requests.exceptions.InvalidURL("bad URL")) as upload,
            patch("backend.app.comfy_service.time.sleep") as sleep,
            self.assertLogs("backend.app.comfy_service", level="WARNING"),
            self.assertRaises(ComfyUnavailable),
        ):
            self.service.upload_image(str(self.source), "reference")

        upload.assert_called_once()
        sleep.assert_not_called()

    def test_rejected_upload_does_not_repeat_invalid_request(self) -> None:
        self.response.ok = False
        self.response.status_code = 400
        self.response.text = "invalid upload"
        with (
            patch("backend.app.comfy_service.requests.post", return_value=self.response) as upload,
            patch("backend.app.comfy_service.time.sleep") as sleep,
            self.assertRaisesRegex(legacy.ComfyError, "invalid upload"),
        ):
            self.service.upload_image(str(self.source), "reference")

        upload.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
