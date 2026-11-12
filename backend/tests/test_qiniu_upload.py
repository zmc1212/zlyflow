from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock
import sys
import qiniu
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.media_studio.services import qiniu_service as qiniu_service_module
from backend.app.media_studio.services.qiniu_service import (
    LARGE_UPLOAD_BYTES,
    UPLOAD_ATTEMPTS,
    UPLOAD_PART_BYTES,
    QiniuService,
)

from backend.app import qiniu_storage as qiniu_storage_module
from backend.app.qiniu_storage import (
    QiniuStorage,
    QINIU_UPLOAD_BACKUP_HOSTS,
    UPLOAD_ATTEMPTS as STORAGE_UPLOAD_ATTEMPTS,
    UPLOAD_PART_BYTES as STORAGE_UPLOAD_PART_BYTES,
)

CONFIG = {
    "access_key": "ak",
    "secret_key": "sk",
    "bucket": "bucket",
    "domain": "https://cdn.example.com",
    "object_prefix": "studio/",
    "region": "z0",
}


class _Info:
    def __init__(self, status_code: int = 200, error: object = None) -> None:
        self.status_code = status_code
        self.error = error
        self.exception = None

    def ok(self) -> bool:
        return self.status_code == 200


SUCCESS = _Info()
SERVER_ERROR = _Info(503, "server busy")


def _writer(store: list[dict]):
    def upload(*args, **kwargs):
        store.append({"args": args, "kwargs": kwargs})
        key = args[1]
        return {"key": key}, SUCCESS

    return upload


class QiniuUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(QiniuService, "_runtime_config", return_value=dict(CONFIG))
        patcher.start()
        self.addCleanup(patcher.stop)
        sleep_patcher = mock.patch.object(qiniu_service_module.time, "sleep", return_value=None)
        self.sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def test_real_sdk_form_uploader_uses_https_despite_its_http_default(self) -> None:
        sdk = qiniu_service_module.qiniu
        token = sdk.Auth("synthetic-ak", "synthetic-sk").upload_token("bucket", "key", 3600)
        with mock.patch("qiniu.services.storage.uploader.FormUploader") as uploader:
            uploader.return_value.upload.return_value = ({"key": "key"}, SUCCESS)
            sdk.put_data(token, "key", b"small", check_crc=True, regions=[sdk.Region(up_host="up-z0.qiniup.com", scheme="https")])
        self.assertEqual("https", uploader.call_args.kwargs["preferred_scheme"])

    def test_real_sdk_passes_separate_connection_and_read_deadlines_to_requests(self) -> None:
        sdk = qiniu_service_module.qiniu
        token = sdk.Auth("synthetic-ak", "synthetic-sk").upload_token("bucket", "key", 3600)
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"key":"key","hash":"synthetic"}'
        with mock.patch("qiniu.http.client.requests.Session.send", return_value=response) as send:
            result, info = sdk.put_data(token, "key", b"small", regions=[sdk.Region(up_host="up-z0.qiniup.com", scheme="https")])
        self.assertTrue(info.ok())
        self.assertEqual("key", result["key"])
        self.assertEqual((15, 180), send.call_args.kwargs["timeout"])
        self.assertTrue(send.call_args.args[0].url.startswith("https://up-z0.qiniup.com/"))

    def test_large_payload_uses_resumable_chunked_upload(self) -> None:
        calls: list[dict] = []
        content = b"x" * (LARGE_UPLOAD_BYTES + 1)
        with mock.patch.object(
            qiniu_service_module.qiniu, "put_stream_v2", side_effect=_writer(calls), create=True
        ) as stream, mock.patch.object(
            qiniu_service_module.qiniu, "put_data"
        ) as put_data:
            key, url = QiniuService.store_bytes("video", "episode.mp4", content)
        stream.assert_called_once()
        put_data.assert_not_called()
        kwargs = calls[0]["kwargs"]
        self.assertEqual(kwargs["part_size"], UPLOAD_PART_BYTES)
        self.assertLessEqual(kwargs["part_size"], 1024 * 1024)
        self.assertEqual(kwargs["bucket_name"], "bucket")
        self.assertEqual(kwargs["mime_type"], "video/mp4")
        self.assertEqual(calls[0]["args"][4], len(content))
        self.assertTrue(key.startswith("studio/video/"))
        self.assertEqual(url, f"https://cdn.example.com/{key}")

    def test_large_payload_falls_back_to_put_stream_v2_flag(self) -> None:
        calls: list[dict] = []
        content = b"x" * (LARGE_UPLOAD_BYTES + 1)
        with mock.patch.object(
            qiniu_service_module.qiniu, "put_stream_v2", None, create=True
        ), mock.patch.object(
            qiniu_service_module.qiniu, "put_stream", side_effect=_writer(calls)
        ) as stream:
            QiniuService.store_bytes("video", "episode.mp4", content)
        stream.assert_called_once()
        self.assertEqual(calls[0]["kwargs"]["version"], "v2")
        self.assertEqual(calls[0]["kwargs"]["part_size"], UPLOAD_PART_BYTES)

    def test_small_payload_uses_put_data(self) -> None:
        calls: list[dict] = []
        with mock.patch.object(
            qiniu_service_module.qiniu, "put_data", side_effect=_writer(calls)
        ) as put_data, mock.patch.object(
            qiniu_service_module.qiniu, "put_stream", create=True
        ) as stream:
            QiniuService.store_bytes("image", "cover.png", b"small")
        put_data.assert_called_once()
        stream.assert_not_called()
        self.assertEqual(calls[0]["kwargs"]["mime_type"], "image/png")

    def test_transient_failure_retries_then_succeeds(self) -> None:
        content = b"small"
        responses = [({"key": None}, SERVER_ERROR), ({"key": "ok"}, SUCCESS)]

        def upload(token, key, *args, **kwargs):
            result, info = responses.pop(0)
            return ({"key": key} if result else result), info

        with mock.patch.object(
            qiniu_service_module.qiniu, "put_data", side_effect=upload
        ) as put_data:
            key, _url = QiniuService.store_bytes("image", "cover.png", content)
        self.assertEqual(put_data.call_count, 2)
        self.assertEqual(self.sleep.call_count, 1)
        self.assertTrue(key.endswith(".png"))

    def test_timeout_exception_retries_then_fails(self) -> None:
        with mock.patch.object(
            qiniu_service_module.qiniu, "put_data", side_effect=TimeoutError("read timed out")
        ) as put_data:
            with self.assertRaises(RuntimeError) as raised:
                QiniuService.store_bytes("image", "cover.png", b"small")
        self.assertEqual(put_data.call_count, UPLOAD_ATTEMPTS)
        self.assertIn("read timed out", str(raised.exception))

    def test_client_error_is_not_retried(self) -> None:
        with mock.patch.object(
            qiniu_service_module.qiniu, "put_data", return_value=(None, _Info(400, "bad token"))
        ) as put_data:
            with self.assertRaises(RuntimeError):
                QiniuService.store_bytes("image", "cover.png", b"small")
        self.assertEqual(put_data.call_count, 1)
        self.sleep.assert_not_called()

    def test_region_declares_backup_upload_host(self) -> None:
        calls: list[dict] = []
        with mock.patch.object(
            qiniu_service_module.qiniu, "put_data", side_effect=_writer(calls)
        ):
            QiniuService.store_bytes("image", "cover.png", b"small")
        regions = calls[0]["kwargs"]["regions"]
        self.assertEqual(regions[0].up_host, "up-z0.qiniup.com")
        self.assertEqual(regions[0].up_host_backup, "upload-z0.qiniup.com")

    def test_retry_classification(self) -> None:
        self.assertTrue(QiniuService._retryable_upload(_Info(503)))
        self.assertTrue(QiniuService._retryable_upload(_Info(-1)))
        self.assertTrue(QiniuService._retryable_upload(TimeoutError("timed out")))
        self.assertTrue(QiniuService._retryable_upload(
            _Info(0, "HTTPConnectionPool: Read timed out. (read timeout=30)")
        ))
        self.assertFalse(QiniuService._retryable_upload(_Info(400, "invalid argument")))
        self.assertFalse(QiniuService._retryable_upload(_Info(614, "file exists")))


class QiniuStorageUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_timeout = qiniu.config.get_default("connection_timeout")
        self.addCleanup(
            qiniu.set_default,
            connection_timeout=self.previous_timeout,
        )
        sleep_patcher = mock.patch.object(qiniu_storage_module.time, "sleep", return_value=None)
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)
        self.storage = QiniuStorage(dict(CONFIG))

    def test_large_music_upload_uses_one_mib_parts_and_backup_host(self) -> None:
        calls: list[dict] = []
        content = b"x" * (9 * 1024 * 1024)
        with mock.patch.object(
            qiniu, "put_stream_v2", side_effect=_writer(calls), create=True
        ):
            stored = self.storage.store_bytes("music/audio", "song.flac", content)
        self.assertTrue(stored.key.startswith("studio/music/audio/"))
        kwargs = calls[0]["kwargs"]
        self.assertEqual(kwargs["part_size"], STORAGE_UPLOAD_PART_BYTES)
        self.assertLessEqual(kwargs["part_size"], 1024 * 1024)
        region = kwargs["regions"][0]
        self.assertEqual(region.up_host, "up-z0.qiniup.com")
        self.assertEqual(region.up_host_backup, QINIU_UPLOAD_BACKUP_HOSTS["z0"])

    def test_write_timeout_retried_and_reported_with_payload_size(self) -> None:
        content = b"x" * (9 * 1024 * 1024)
        with mock.patch.object(
            qiniu,
            "put_stream_v2",
            side_effect=TimeoutError("The write operation timed out"),
            create=True,
        ) as upload:
            with self.assertRaises(RuntimeError) as raised:
                self.storage.store_bytes("music/audio", "song.flac", content)
        self.assertEqual(upload.call_count, STORAGE_UPLOAD_ATTEMPTS)
        message = str(raised.exception)
        self.assertIn("七牛云上传失败", message)
        self.assertIn("9.0 MiB", message)
        self.assertIn("The write operation timed out", message)


if __name__ == "__main__":
    unittest.main()