from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.auth import AuthStore, csrf_token
from backend.app.main import SESSION_COOKIE, app
from backend.app.models import UserRole
from backend.app.profile_avatar import MAX_PROFILE_AVATAR_BYTES
from backend.app.resource_storage import StoredResource
from backend.tests.app_state_guard import restore_app_state, snapshot_app_state


class FakeAvatarStorage:
    provider_id = "qiniu"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads = 0

    def store_bytes(self, prefix: str, filename: str, content: bytes) -> StoredResource:
        self.uploads += 1
        key = f"{prefix}/{self.uploads}_{filename}"
        self.objects[key] = content
        return StoredResource(key=key, local_path=None)

    def download_url(self, key: str) -> str:
        return f"https://cdn.example.test/{key}?e=123&token=signed"

    def delete(self, key: str) -> bool:
        self.objects.pop(key)
        return True


def profile_picture() -> bytes:
    with BytesIO() as buffer:
        Image.new("RGBA", (520, 360), (65, 90, 140, 180)).save(buffer, format="PNG")
        return buffer.getvalue()


class ProfileAvatarTests(TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        snapshot = snapshot_app_state(app, "auth_store", "resource_storage")
        self.addCleanup(restore_app_state, app, snapshot)
        self.auth = AuthStore(Path(directory.name) / "accounts.db")
        self.storage = FakeAvatarStorage()
        app.state.auth_store = self.auth
        app.state.resource_storage = self.storage
        self.client = TestClient(app, follow_redirects=False)
        self.addCleanup(self.client.close)
        self.user = self.auth.create_user("creator", "创作者", "profile-test-pass", UserRole.EMPLOYEE, must_change_password=False)
        self.token, _ = self.auth.create_session(self.user["id"])

    def upload(self, data: bytes, token: str | None = None):
        return self.client.post(
            "/api/auth/avatar",
            headers={"X-CSRF-Token": csrf_token(token)} if token else {},
            files={"file": ("picture.png", data, "image/png")},
        )

    def test_upload_replaces_and_persists_current_accounts_avatar(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, self.token)
        self.assertIsNone(self.client.get("/api/auth/status").json()["user"]["avatar_url"])

        response = self.upload(profile_picture(), self.token)
        self.assertEqual(response.status_code, 200, response.text)
        avatar_url = response.json()["user"]["avatar_url"]
        key = self.auth.get_avatar_key(self.user["id"])
        self.assertEqual(self.client.get("/api/auth/status").json()["user"]["avatar_url"], avatar_url)
        self.assertNotIn("avatar_key", response.json()["user"])
        with Image.open(BytesIO(self.storage.objects[key])) as image:
            self.assertEqual((image.format, image.size, image.mode), ("WEBP", (256, 256), "RGBA"))
        preview = self.client.get(avatar_url)
        self.assertEqual(preview.status_code, 307)
        self.assertEqual(preview.headers["location"], self.storage.download_url(key))
        self.assertEqual(preview.headers["cache-control"], "private, no-store")

        replacement = self.upload(profile_picture(), self.token)
        self.assertEqual(replacement.status_code, 200, replacement.text)
        new_url = replacement.json()["user"]["avatar_url"]
        self.assertNotEqual(new_url, avatar_url)
        self.assertNotIn(key, self.storage.objects)
        self.assertEqual(self.client.get(avatar_url).status_code, 404)
        self.assertEqual(self.client.get(new_url).status_code, 307)

    def test_avatar_is_self_only_and_upload_requires_csrf(self) -> None:
        self.assertEqual(self.upload(profile_picture()).status_code, 401)
        self.client.cookies.set(SESSION_COOKIE, self.token)
        self.assertEqual(self.upload(profile_picture()).status_code, 403)
        avatar_url = self.upload(profile_picture(), self.token).json()["user"]["avatar_url"]

        other = self.auth.create_user("other", "其他账号", "profile-test-pass", UserRole.EMPLOYEE)
        other_token, _ = self.auth.create_session(other["id"])
        self.client.cookies.set(SESSION_COOKIE, other_token)
        self.assertEqual(self.client.get(avatar_url).status_code, 404)
        self.assertEqual(self.upload(profile_picture(), other_token).status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(avatar_url).status_code, 401)

    def test_invalid_images_and_failed_writes_keep_current_avatar(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, self.token)
        response = self.upload(profile_picture(), self.token)
        self.assertEqual(response.status_code, 200)
        initial_key = self.auth.get_avatar_key(self.user["id"])

        malformed = self.client.post(
            "/api/auth/avatar", headers={"X-CSRF-Token": csrf_token(self.token)},
            files={"file": (None, "not a file")},
        )
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(self.upload(b"not a PNG", self.token).status_code, 422)
        self.assertEqual(self.upload(b"\0" * (MAX_PROFILE_AVATAR_BYTES + 1), self.token).status_code, 413)
        with patch.object(self.storage, "store_bytes", side_effect=RuntimeError("storage offline")):
            self.assertEqual(self.upload(profile_picture(), self.token).status_code, 502)
        with patch.object(self.auth, "replace_avatar", side_effect=KeyError(self.user["id"])):
            self.assertEqual(self.upload(profile_picture(), self.token).status_code, 409)

        self.assertEqual(self.auth.get_avatar_key(self.user["id"]), initial_key)
        self.assertEqual(list(self.storage.objects), [initial_key])
