from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.auth import AuthStore, csrf_token
from backend.app.main import app
from backend.app.models import UserRole
from backend.app.music_job_service import MusicJobService, MusicServiceError
from backend.app.music_lyrics import align_lyric_words, apply_lrc, lyric_text_lines
from backend.app.music_yue2_client import YuE2Client, YuE2Error
from backend.app.resource_storage import StoredResource
from backend.app.storage import JobStore


def _fernet_key() -> str:
    return Fernet.generate_key().decode("ascii")


class MusicStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_music_settings_default_and_update(self) -> None:
        settings = self.store.get_music_settings()
        self.assertEqual(settings["base_url"], "http://192.168.10.54:8791")
        self.assertIsNone(settings["access_key_encrypted"])
        self.store.update_music_settings(base_url="http://192.168.10.55:8791", access_key_encrypted="cipher")
        updated = self.store.get_music_settings()
        self.assertEqual(updated["base_url"], "http://192.168.10.55:8791")
        self.assertEqual(updated["access_key_encrypted"], "cipher")

    def test_music_job_crud_roundtrip(self) -> None:
        record = self.store.create_music_job({
            "id": "music-abc123",
            "owner_user_id": "user-1",
            "title": "测试歌",
            "style": "Mandarin, pop, 88 BPM",
            "lyrics": "[Verse 1]\n你好",
            "status": "queued",
            "params": {"duration_seconds": 30, "output_format": "flac"},
            "created_at": "2026-11-07T00:00:00+00:00",
            "updated_at": "2026-11-07T00:00:00+00:00",
        })
        self.assertEqual(record["status"], "queued")
        self.assertEqual(record["params"]["duration_seconds"], 30)
        fetched = self.store.get_music_job("music-abc123", owner_user_id="user-1")
        self.assertIsNotNone(fetched)
        self.assertIsNone(self.store.get_music_job("music-abc123", owner_user_id="user-2"))
        self.store.update_music_job("music-abc123", status="succeeded", progress=100, result_url="https://cdn/x.flac")
        updated = self.store.get_music_job("music-abc123")
        self.assertEqual(updated["status"], "succeeded")
        self.assertEqual(updated["result_url"], "https://cdn/x.flac")
        rows = self.store.list_music_jobs("user-1")
        self.assertEqual([row["id"] for row in rows], ["music-abc123"])
        self.assertTrue(self.store.delete_music_job("music-abc123", "user-1"))
        self.assertFalse(self.store.delete_music_job("music-abc123", "user-1"))

    def test_lyrics_claim_expiration_and_delete(self) -> None:
        self.store.create_music_job({
            "id": "music-claim", "owner_user_id": "user-1", "status": "succeeded", "result_url": "https://cdn/x.flac",
            "created_at": "2026-11-07T00:00:00+00:00", "updated_at": "2026-11-07T00:00:00+00:00",
        })
        self.assertTrue(self.store.claim_music_lyrics("music-claim", "first", 10, 20))
        self.assertFalse(self.store.claim_music_lyrics("music-claim", "duplicate", 19, 30))
        self.assertTrue(self.store.claim_music_lyrics("music-claim", "replacement", 20, 30))
        self.store.finish_music_lyrics("music-claim", "first", "failed", {})
        self.assertEqual(self.store.get_music_lyrics("music-claim")["status"], "aligning")
        self.store.finish_music_lyrics("music-claim", "replacement", "ready", {"lines": []})
        self.assertFalse(self.store.claim_music_lyrics("music-claim", "late", 31, 40))
        self.assertTrue(self.store.delete_music_job("music-claim", "user-1"))
        self.assertIsNone(self.store.get_music_lyrics("music-claim"))
        self.assertFalse(self.store.claim_music_lyrics("music-claim", "deleted", 40, 50))


class MusicLyricsAlignmentTests(unittest.TestCase):
    def test_enhanced_lrc_keeps_original_text_and_repeated_lines(self) -> None:
        lyrics = lyric_text_lines("[Intro]\r\n风吹过，麦田。\r\n[Chorus]\r\n回家的路\n风吹过，麦田。")
        lrc = "[00:04.80]<00:04.80>风吹过 <00:05.20>麦田\n[00:12.00]回家的路\n[01:28.25]风吹过麦田"
        result = apply_lrc(lyrics, lrc)
        self.assertEqual([line.text for line in result], lyrics)
        self.assertEqual([line.start_seconds for line in result], [4.8, 12, 88.25])

    def test_local_alignment_uses_audio_times_and_leaves_unmatched_lyrics_readable(self) -> None:
        lyrics = ["星星低垂", "麦浪沙沙", "Go home!", "星星低垂"]
        words = [("哼", 1.0, 2.0), ("星星", 8.0, 8.7), ("低垂", 8.8, 9.6),
                 ("go", 25.0, 25.6), ("home", 25.8, 26.5), ("星星低垂", 41.0, 43.0)]
        result = align_lyric_words(lyrics, words)
        self.assertEqual([line.text for line in result], lyrics)
        self.assertEqual([(line.start_seconds, line.end_seconds) for line in result],
                         [(8, 9.6), (None, None), (25, 26.5), (41, 43)])

    def test_mandarin_alignment_matches_traditional_and_homophones(self) -> None:
        lyrics = ["德令哈的夜 星星低垂", "海子 海子 麦子又熟了"]
        words = [("得靈哈的夜", 21.72, 24), ("星星地追", 24, 26.6), ("孩子孩子", 78.46, 80), ("買自由手了", 80, 83.58)]
        result = align_lyric_words(lyrics, words, language="zh")
        self.assertEqual([line.text for line in result], lyrics)
        self.assertEqual([line.start_seconds for line in result], [21.72, 78.46])


class YuE2ClientTests(unittest.TestCase):
    def test_adapter_catalog_returns_selectable_installed_adapters(self) -> None:
        client = YuE2Client("http://studio.test", "key")
        installed = {"id": "folk", "name": {"en": "Folk", "zh": "民谣"}, "scales": {"nar": 0.8}, "error": None}
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "installed": [installed, {"id": "broken", "name": "Broken", "error": "invalid weights"}],
            "catalog": [{"id": "missing", "name": "Missing"}],
        }
        with patch.object(client._session, "get", return_value=response):
            self.assertEqual(client.list_adapters(), [{**installed, "name": "民谣"}])
            legacy = [{"id": "jazz", "name": "Jazz"}]
            response.json.return_value = legacy
            self.assertEqual(client.list_adapters(), legacy)


class FakeYuE2Client:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.fail = False
        self.song_id = "song-1"

    def create_song(self, **kwargs):
        if self.fail:
            raise YuE2Error("引擎不可用")
        self.created.append(kwargs)
        return {"id": "remote-job-1", "status": "queued"}

    def wait_for_job(self, job_id: str, **kwargs):
        if self.fail:
            raise YuE2Error("引擎不可用")
        return {"id": job_id, "status": "completed", "song": {"id": self.song_id, "audio_url": "/v1/library/media/song-1"}}

    def download_media(self, song_id: str) -> bytes:
        return b"AUDIO"

    def download_cover(self, song_id: str) -> bytes | None:
        return None


class MusicJobServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")
        self.storage = MagicMock()
        self.storage.store_bytes.return_value = StoredResource(key="music/audio/x.flac", local_path=None)
        self.storage.object_url.return_value = "https://cdn.example.com/music/audio/x.flac"
        self.credential_key = _fernet_key()
        MusicJobService.configure(self.store, self.credential_key, self.storage)
        self.fake_client = FakeYuE2Client()

    def tearDown(self) -> None:
        MusicJobService.configure(None, None, None)
        self.temp_dir.cleanup()

    def test_client_requires_configuration(self) -> None:
        with self.assertRaises(MusicServiceError):
            MusicJobService.client()

    def test_provider_config_encrypts_and_hides_key(self) -> None:
        config = MusicJobService.update_provider("http://192.168.10.54:8791", "secret-key-123")
        self.assertTrue(config["has_access_key"])
        self.assertTrue(config["configured"])
        self.assertNotIn("secret-key-123", config["base_url"])
        raw = self.store.get_music_settings()["access_key_encrypted"]
        self.assertNotIn("secret-key-123", str(raw))
        client = MusicJobService.client()
        self.assertEqual(client.access_key, "secret-key-123")

    def test_enqueue_validates_parameters(self) -> None:
        with patch.object(MusicJobService, "client", return_value=self.fake_client):
            with self.assertRaises(ValueError):
                MusicJobService.enqueue("user-1", title="", style="", lyrics="")
            with self.assertRaises(ValueError):
                MusicJobService.enqueue("user-1", title="", style="pop", lyrics="", duration_seconds=5)
            with self.assertRaises(ValueError):
                MusicJobService.enqueue("user-1", title="", style="pop", lyrics="", output_format="ogg")

    def test_enqueue_creates_queued_job(self) -> None:
        with patch.object(MusicJobService, "client", return_value=self.fake_client), \
             patch.object(MusicJobService, "kick", lambda *args, **kwargs: None):
            record = MusicJobService.enqueue(
                "user-1", title="测试歌", style="Mandarin, pop, 88 BPM", lyrics="[Verse 1]\n你好",
                duration_seconds=30, output_format="flac", seed=1, lm_seed=2,
                adapters=[{"id": "lora-1", "scales": {"作曲": 1.0}}, {"id": ""}],
            )
        self.assertEqual(record["status"], "queued")
        self.assertEqual(record["params"]["adapters"], [{"id": "lora-1", "scales": {"作曲": 1.0}}])

    def test_run_succeeds_and_uploads(self) -> None:
        with patch.object(MusicJobService, "client", return_value=self.fake_client), \
             patch.object(MusicJobService, "kick", lambda *args, **kwargs: None):
            record = MusicJobService.enqueue(
                "user-1", title="测试歌", style="Mandarin, pop, 88 BPM", lyrics="",
                duration_seconds=30, output_format="flac",
            )
            MusicJobService._run(record["id"])
        final = self.store.get_music_job(record["id"])
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["remote_song_id"], "song-1")
        self.assertEqual(final["result_url"], "https://cdn.example.com/music/audio/x.flac")
        self.assertEqual(final["remote_job_id"], "remote-job-1")
        self.storage.store_bytes.assert_called_once()
        self.assertEqual(self.storage.store_bytes.call_args.args[1].endswith(".flac"), True)

    def test_run_marks_failed_on_remote_error(self) -> None:
        self.fake_client.fail = True
        with patch.object(MusicJobService, "client", return_value=self.fake_client), \
             patch.object(MusicJobService, "kick", lambda *args, **kwargs: None):
            record = MusicJobService.enqueue(
                "user-1", title="测试歌", style="pop", lyrics="", duration_seconds=30,
            )
            MusicJobService._run(record["id"])
        final = self.store.get_music_job(record["id"])
        self.assertEqual(final["status"], "failed")
        self.assertIn("引擎不可用", final["error_message"])

    def test_recover_marks_active_jobs_failed(self) -> None:
        with patch.object(MusicJobService, "client", return_value=self.fake_client), \
             patch.object(MusicJobService, "kick", lambda *args, **kwargs: None):
            record = MusicJobService.enqueue(
                "user-1", title="测试歌", style="pop", lyrics="", duration_seconds=30,
            )
        self.store.update_music_job(record["id"], status="running")
        with patch.object(MusicJobService, "kick", lambda *args, **kwargs: None):
            MusicJobService.recover_interrupted_jobs()
        final = self.store.get_music_job(record["id"])
        self.assertEqual(final["status"], "failed")


class FakeLlmProvider:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload or {
            "title": "写给海子的歌",
            "style": "Mandarin, gentle acoustic folk ballad, warm male vocals, fingerpicked acoustic guitar, nostalgic tender melody, 82 BPM",
            "lyrics": "[Verse 1]\n今夜我在德令哈\n",
        }
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def chat_json(self, system_prompt: str, user_content: str, **kwargs):
        self.calls.append((system_prompt, user_content))
        if self.error:
            raise self.error
        return self.payload


class MusicVibeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")
        MusicJobService.configure(self.store, _fernet_key(), MagicMock())

    def tearDown(self) -> None:
        MusicJobService.configure(None, None, None)
        self.temp_dir.cleanup()

    def test_vibe_expands_description_and_enqueues(self) -> None:
        llm = FakeLlmProvider()
        with patch.object(MusicJobService, "client", return_value=FakeYuE2Client()), \
             patch.object(MusicJobService, "kick", lambda *args, **kwargs: None):
            record = MusicJobService.create_from_vibe(
                "user-1", description="写给海子的一首民谣，男声，木吉他", duration_seconds=60, llm_provider=llm,
            )
        self.assertEqual(record["status"], "queued")
        self.assertEqual(record["title"], "写给海子的歌")
        self.assertIn("Mandarin", record["style"])
        # 扩写提示词里带上了用户的描述与目标时长
        self.assertIn("写给海子的一首民谣", llm.calls[0][1])
        self.assertIn("60 秒", llm.calls[0][1])

    def test_vibe_instrumental_clears_lyrics(self) -> None:
        llm = FakeLlmProvider()
        with patch.object(MusicJobService, "client", return_value=FakeYuE2Client()), \
             patch.object(MusicJobService, "kick", lambda *args, **kwargs: None):
            record = MusicJobService.create_from_vibe(
                "user-1", description="一段压抑的工业摇滚配乐", instrumental=True, llm_provider=llm,
            )
        self.assertEqual(record["lyrics"], "")

    def test_vibe_rejects_empty_description(self) -> None:
        with self.assertRaises(ValueError):
            MusicJobService.create_from_vibe("user-1", description="  ", llm_provider=FakeLlmProvider())

    def test_vibe_propagates_llm_failure(self) -> None:
        from backend.app.llm_client import LlmError
        llm = FakeLlmProvider(error=LlmError("上游超时"))
        with self.assertRaises(LlmError):
            MusicJobService.create_from_vibe("user-1", description="一首摇滚", llm_provider=llm)


class MusicEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        MusicJobService.configure(self.job_store, _fernet_key(), MagicMock())
        app.state.auth_store = self.auth_store
        app.state.store = self.job_store
        app.state.music_jobs = MusicJobService
        self.admin = self.auth_store.create_user(
            "superadmin", "Super Admin", "password123456", UserRole.SUPER_ADMIN, must_change_password=False,
        )
        self.admin_token, _ = self.auth_store.create_session(self.admin["id"])
        self.employee = self.auth_store.create_user(
            "worker", "Worker", "password123456", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.employee_token, _ = self.auth_store.create_session(self.employee["id"])
        self.client = TestClient(app)

    def tearDown(self) -> None:
        MusicJobService.configure(None, None, None)
        self.temp_dir.cleanup()

    def test_admin_provider_permissions(self) -> None:
        res = self.client.get("/api/admin/providers/music")
        self.assertEqual(res.status_code, 401)
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        res = self.client.get("/api/admin/providers/music")
        self.assertEqual(res.status_code, 403)
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        res = self.client.get("/api/admin/providers/music")
        self.assertEqual(res.status_code, 200)
        self.assertIn("base_url", res.json())

    def test_admin_can_save_and_mask_key(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        res = self.client.put(
            "/api/admin/providers/music",
            json={"base_url": "http://192.168.10.54:8791", "access_key": "k" * 32},
            headers={"X-CSRF-Token": csrf_token(self.admin_token)},
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["has_access_key"])
        self.assertNotIn("k" * 32, res.text)
        raw = self.job_store.get_music_settings()["access_key_encrypted"]
        self.assertNotIn("k" * 32, str(raw))

    def test_test_endpoint_reports_available_flag(self) -> None:
        """回归：测试连接接口必须回传 available / unavailable_reason。

        响应模型 MusicProviderResponse 缺这两个字段时，FastAPI 会把它们过滤掉，
        前端读不到 available 就会把「探活成功」也显示成「连接失败：未知原因」。
        """
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        url = "/api/admin/providers/music/test"
        headers = {"X-CSRF-Token": csrf_token(self.admin_token)}
        payload = {"base_url": "http://127.0.0.1:18080", "access_key": "k" * 32}

        ok_client = MagicMock()
        ok_client.ping.return_value = {"status": "ok"}
        with patch("backend.app.music_job_service.YuE2Client", return_value=ok_client):
            res = self.client.post(url, json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("available", body)
        self.assertIs(body["available"], True)
        self.assertIsNone(body["unavailable_reason"])

        bad_client = MagicMock()
        bad_client.ping.side_effect = YuE2Error("YuE2 服务不可达: 连接超时")
        with patch("backend.app.music_job_service.YuE2Client", return_value=bad_client):
            res = self.client.post(url, json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIs(body["available"], False)
        self.assertIn("服务不可达", body["unavailable_reason"] or "")

    def test_music_jobs_require_login_and_isolate_owner(self) -> None:
        res = self.client.get("/api/music/jobs")
        self.assertEqual(res.status_code, 401)
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        res = self.client.get("/api/music/jobs")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), [])

    def test_create_music_job_returns_queued(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        fake_client = FakeYuE2Client()
        with patch.object(MusicJobService, "client", return_value=fake_client), \
             patch.object(MusicJobService, "kick", lambda *args, **kwargs: None):
            res = self.client.post(
                "/api/music/jobs",
                json={"title": "测试歌", "style": "Mandarin, pop, 88 BPM", "lyrics": "", "duration_seconds": 30},
                headers={"X-CSRF-Token": csrf_token(self.employee_token)},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "queued")
        job_id = res.json()["id"]
        detail = self.client.get(f"/api/music/jobs/{job_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["owner_user_id"], self.employee["id"])

    def test_create_rejects_invalid_payload(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        res = self.client.post(
            "/api/music/jobs",
            json={"title": "", "style": "", "duration_seconds": 9999},
            headers={"X-CSRF-Token": csrf_token(self.employee_token)},
        )
        self.assertEqual(res.status_code, 422)

    def test_vibe_endpoint_enqueues_with_llm_payload(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        llm = FakeLlmProvider()
        with patch.object(MusicJobService, "client", return_value=FakeYuE2Client()), \
             patch.object(MusicJobService, "kick", lambda *args, **kwargs: None), \
             patch.object(app.state, "llm_provider", llm, create=True):
            res = self.client.post(
                "/api/music/vibe",
                json={"description": "写给海子的一首民谣，男声，木吉他", "duration_seconds": 60},
                headers={"X-CSRF-Token": csrf_token(self.employee_token)},
            )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["title"], "写给海子的歌")

    def test_vibe_endpoint_maps_llm_failure_to_502(self) -> None:
        from backend.app.llm_client import LlmError
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        llm = FakeLlmProvider(error=LlmError("上游超时"))
        with patch.object(app.state, "llm_provider", llm, create=True):
            res = self.client.post(
                "/api/music/vibe",
                json={"description": "一首摇滚"},
                headers={"X-CSRF-Token": csrf_token(self.employee_token)},
            )
        self.assertEqual(res.status_code, 502)

    def test_delete_other_users_job_not_allowed(self) -> None:
        record = self.job_store.create_music_job({
            "id": "music-owner-1", "owner_user_id": self.admin["id"], "title": "t", "style": "s",
            "lyrics": "", "status": "succeeded", "result_url": "https://cdn/x.flac",
            "created_at": "2026-11-07T00:00:00+00:00", "updated_at": "2026-11-07T00:00:00+00:00",
        })
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        res = self.client.delete(
            f"/api/music/jobs/{record['id']}",
            headers={"X-CSRF-Token": csrf_token(self.employee_token)},
        )
        self.assertEqual(res.status_code, 404)

    def test_music_lyrics_owner_csrf_and_saved_timing(self) -> None:
        record = self.job_store.create_music_job({
            "id": "music-lyrics", "owner_user_id": self.employee["id"], "status": "succeeded",
            "lyrics": "[Verse]\n回家的路", "result_url": "https://cdn/x.flac", "remote_song_id": "song-1",
            "created_at": "2026-11-07T00:00:00+00:00", "updated_at": "2026-11-07T00:00:00+00:00",
        })
        url = "/api/music/jobs/" + record["id"] + "/lyrics"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, headers={"X-CSRF-Token": csrf_token(self.admin_token)}).status_code, 404)
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        self.assertEqual(self.client.get(url).json()["status"], "idle")
        self.assertEqual(self.client.post(url).status_code, 403)

        fake_client = MagicMock()
        fake_client.get_song_lrc.return_value = "[00:17.40]<00:17.40>回家 <00:18.00>的路"
        with patch.object(MusicJobService, "client", return_value=fake_client), \
             patch("backend.app.music_lyrics._EXECUTOR.submit", side_effect=lambda fn, *args: fn(*args)):
            response = self.client.post(url, headers={"X-CSRF-Token": csrf_token(self.employee_token)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "yue2")
        self.assertEqual(response.json()["lines"], [{"text": "回家的路", "start_seconds": 17.4, "end_seconds": None}])
        self.assertEqual(self.client.get(url).json(), response.json())


if __name__ == "__main__":
    unittest.main()
