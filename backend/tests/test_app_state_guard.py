"""backend/tests/app_state_guard.py 的行为测试。"""
from __future__ import annotations

import unittest

from fastapi import FastAPI

from backend.app.cloud_video_service import CloudVideoService
from backend.app.music_job_service import MusicJobService
from backend.tests.app_state_guard import (
    isolated_lifespan_state,
    restore_app_state,
    snapshot_app_state,
)


class _SentinelStore:
    """占位对象，模拟被替换的 store 实例。"""


class AppStateSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.state.store = "original"
        self._singletons = (
            CloudVideoService._instance,
            MusicJobService._store,
            MusicJobService._credentials,
            MusicJobService._resource_storage,
        )

    def tearDown(self) -> None:
        CloudVideoService._instance = self._singletons[0]
        MusicJobService._store = self._singletons[1]
        MusicJobService._credentials = self._singletons[2]
        MusicJobService._resource_storage = self._singletons[3]

    def test_snapshot_captures_present_and_missing_attrs(self) -> None:
        snapshot = snapshot_app_state(self.app, "store", "not_set_yet")
        self.assertEqual(snapshot["state:store"], (True, "original"))
        self.assertEqual(snapshot["state:not_set_yet"], (False, None))

    def test_restore_puts_values_back_and_deletes_missing(self) -> None:
        snapshot = snapshot_app_state(self.app, "store", "not_set_yet")
        self.app.state.store = "swapped"
        self.app.state.not_set_yet = "leaked"
        restore_app_state(self.app, snapshot)
        self.assertEqual(self.app.state.store, "original")
        self.assertFalse(hasattr(self.app.state, "not_set_yet"))

    def test_restore_reverts_class_singletons(self) -> None:
        original = CloudVideoService._instance
        snapshot = snapshot_app_state(self.app, "store")
        try:
            CloudVideoService._instance = _SentinelStore()
            MusicJobService._store = _SentinelStore()
            restore_app_state(self.app, snapshot)
            self.assertIs(CloudVideoService._instance, original)
            self.assertIs(MusicJobService._store, self._singletons[1])
        finally:
            CloudVideoService._instance = original
            MusicJobService._store = self._singletons[1]

    def test_isolated_lifespan_state_restores_after_block(self) -> None:
        sentinel = _SentinelStore()
        with isolated_lifespan_state(self.app):
            self.app.state.store = sentinel
            CloudVideoService._instance = sentinel
        self.assertEqual(self.app.state.store, "original")
        self.assertIs(CloudVideoService._instance, self._singletons[0])

    def test_isolated_lifespan_state_restores_after_exception(self) -> None:
        sentinel = _SentinelStore()
        with self.assertRaises(RuntimeError):
            with isolated_lifespan_state(self.app):
                self.app.state.store = sentinel
                raise RuntimeError("lifespan 失败")
        self.assertEqual(self.app.state.store, "original")


if __name__ == "__main__":
    unittest.main()
