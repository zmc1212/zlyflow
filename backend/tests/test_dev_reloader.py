from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.dev_reloader import (
    DevReloader,
    creation_flags,
    is_python_source,
    kill_process_tree,
    restart_delay,
    snapshot_sources,
)
from backend.app.worker import JobWorker


class DevReloaderHelperTests(unittest.TestCase):
    def test_python_source_ignores_bytecode(self) -> None:
        self.assertTrue(is_python_source(Path("backend/app/main.py")))
        self.assertFalse(is_python_source(Path("backend/app/__pycache__/main.cpython-310.pyc")))
        self.assertFalse(is_python_source(Path("backend/app/main.pyi")))

    def test_snapshot_only_includes_python_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "worker.py").write_text("value = 1\n", encoding="utf-8")
            cached = root / "__pycache__"
            cached.mkdir()
            (cached / "worker.cpython-310.pyc").write_bytes(b"x")
            (root / "notes.txt").write_text("ignore\n", encoding="utf-8")
            snapshot = snapshot_sources(root)
            self.assertEqual(len(snapshot), 1)
            self.assertTrue(any(path.endswith("worker.py") for path in snapshot))

    def test_crash_delay_backs_off_and_caps(self) -> None:
        self.assertEqual(restart_delay(1), 2)
        self.assertEqual(restart_delay(3), 8)
        self.assertEqual(restart_delay(9), 10)

    def test_workspace_dir_contains_backend_app(self) -> None:
        from backend.dev_reloader import WATCH_DIR, WORKSPACE_DIR

        self.assertTrue((WORKSPACE_DIR / "backend" / "dev_reloader.py").is_file())
        self.assertEqual(WATCH_DIR, WORKSPACE_DIR / "backend" / "app")

    def test_kill_process_tree_ignores_invalid_pid(self) -> None:
        kill_process_tree(0)
        kill_process_tree(-1)

    def test_windows_child_is_detached_from_console_control(self) -> None:
        if sys.platform != "win32":
            self.assertEqual(creation_flags(), 0)
            return
        import subprocess

        flags = creation_flags()
        self.assertTrue(flags & subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(flags & subprocess.CREATE_NO_WINDOW)


class VideoJobRestartGuardTests(unittest.TestCase):
    def _reloader(self) -> DevReloader:
        return DevReloader("127.0.0.1", 1, [])

    def test_restart_waits_until_active_video_jobs_finish(self) -> None:
        reloader = self._reloader()
        child = mock.Mock()
        child.poll.return_value = None
        with mock.patch(
            "backend.dev_reloader.count_active_video_jobs",
            side_effect=[2, 1, 0],
        ) as probe, mock.patch(
            "backend.dev_reloader.VIDEO_JOB_POLL_SECONDS", 0.01
        ):
            self.assertTrue(reloader._wait_for_active_video_jobs(child))
        self.assertEqual(probe.call_count, 3)

    def test_restart_proceeds_when_no_video_job_is_active(self) -> None:
        reloader = self._reloader()
        with mock.patch(
            "backend.dev_reloader.count_active_video_jobs", return_value=0
        ) as probe:
            self.assertTrue(reloader._wait_for_active_video_jobs(None))
        self.assertEqual(probe.call_count, 1)

    def test_restart_proceeds_when_job_store_is_unreachable(self) -> None:
        reloader = self._reloader()
        with mock.patch(
            "backend.dev_reloader.count_active_video_jobs", return_value=None
        ):
            self.assertTrue(reloader._wait_for_active_video_jobs(None))

    def test_restart_proceeds_after_child_exits_while_waiting(self) -> None:
        reloader = self._reloader()
        child = mock.Mock()
        child.poll.side_effect = [None, 0]
        with mock.patch(
            "backend.dev_reloader.count_active_video_jobs", return_value=3
        ) as probe, mock.patch(
            "backend.dev_reloader.VIDEO_JOB_POLL_SECONDS", 0.01
        ):
            self.assertTrue(reloader._wait_for_active_video_jobs(child))
        self.assertEqual(probe.call_count, 1)

    def test_shutdown_abandons_deferred_restart(self) -> None:
        reloader = self._reloader()
        reloader._stop.set()
        with mock.patch(
            "backend.dev_reloader.count_active_video_jobs", return_value=1
        ) as probe:
            self.assertFalse(reloader._wait_for_active_video_jobs(mock.Mock()))
        probe.assert_not_called()


class WorkerStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_does_not_wait_forever_for_blocking_tasks(self) -> None:
        worker = JobWorker.__new__(JobWorker)
        worker.STOP_TIMEOUT_SECONDS = 0.2
        worker.image_tasks = set()
        worker.cloud_video_tasks = set()
        worker.background_tasks = set()
        worker.watch_task = None

        async def hang() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    return

        worker.task = asyncio.create_task(hang())
        started = time.monotonic()
        await worker.stop()
        self.assertLess(time.monotonic() - started, 2)
        worker.task.cancel()
        await asyncio.wait({worker.task}, timeout=1)
        self.assertTrue(worker.task.done())


if __name__ == "__main__":
    unittest.main()
