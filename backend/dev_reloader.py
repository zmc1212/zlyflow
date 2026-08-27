"""Windows-safe local supervisor for the FastAPI workbench.

Uvicorn ``--reload`` on Windows uses StatReload in the same console group. A
file-change restart sends ``CTRL_C_EVENT`` to every process attached to that
console, so the supervisor exits with the worker instead of spawning a new one.
Closing the console is then stuck on ``Waiting for application shutdown`` while
non-daemon ComfyUI worker threads refuse to finish.

This process runs uvicorn *without* ``--reload``, detached from the console
control events, watches ``backend/app`` Python sources, force-kills the child
tree on shutdown, and restarts on code changes or crashes. Docker and production
still start uvicorn directly.
"""

from __future__ import annotations

import argparse
import atexit
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


WORKSPACE_DIR = Path(__file__).resolve().parents[1]
WATCH_DIR = WORKSPACE_DIR / "backend" / "app"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 7865
POLL_INTERVAL_SECONDS = 0.5
CHANGE_DEBOUNCE_SECONDS = 0.8
KILL_WAIT_SECONDS = 3
PORT_RELEASE_SECONDS = 0.5
MAX_CRASH_DELAY_SECONDS = 10

_active_reloader: DevReloader | None = None
_console_handler_ref = None


def enable_windows_ansi() -> None:
    prepare_windows_console()


def prepare_windows_console() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        stdout = kernel32.GetStdHandle(-11)
        stdin = kernel32.GetStdHandle(-10)
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(stdout, ctypes.byref(mode)):
            kernel32.SetConsoleMode(stdout, mode.value | 0x0004)
        if kernel32.GetConsoleMode(stdin, ctypes.byref(mode)):
            # Keep the window running when clicked; QuickEdit otherwise pauses the process.
            kernel32.SetConsoleMode(stdin, (mode.value | 0x0080) & ~0x0040)
    except Exception:
        return


def log(message: str) -> None:
    print(f"[reloader] {message}", flush=True)


def is_python_source(path: Path) -> bool:
    return path.suffix == ".py" and "__pycache__" not in path.parts


def snapshot_sources(root: Path) -> dict[str, int]:
    snapshot: dict[str, int] = {}
    if not root.is_dir():
        return snapshot
    for path in root.rglob("*.py"):
        if not is_python_source(path):
            continue
        try:
            snapshot[str(path)] = path.stat().st_mtime_ns
        except OSError:
            continue
    return snapshot


def restart_delay(crash_count: int) -> float:
    return float(min(MAX_CRASH_DELAY_SECONDS, 2 ** max(crash_count, 1)))


def creation_flags() -> int:
    if sys.platform != "win32":
        return 0
    return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW


def kill_process_tree(pid: int, wait: bool = True) -> None:
    if pid <= 0:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=KILL_WAIT_SECONDS,
            )
            return
        os.kill(pid, signal.SIGTERM)
        if not wait:
            return
        deadline = time.monotonic() + KILL_WAIT_SECONDS
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.05)
        os.kill(pid, signal.SIGKILL)
    except Exception:
        return


def _console_ctrl_handler(ctrl_type: int) -> int:
    reloader = _active_reloader
    if reloader is not None:
        try:
            reloader.shutdown_now()
        except Exception:
            pass
    os._exit(0)
    return 1


def install_windows_console_handler() -> None:
    global _console_handler_ref
    if sys.platform != "win32":
        return
    import ctypes

    handler = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)(_console_ctrl_handler)
    if ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True):
        _console_handler_ref = handler


class DevReloader:
    def __init__(self, host: str, port: int, extra_args: list[str]) -> None:
        self.host = host
        self.port = port
        self.extra_args = extra_args
        self._stop = threading.Event()
        self._restart = threading.Event()
        self._child: subprocess.Popen[bytes] | None = None
        self._crash_count = 0

    def run(self) -> int:
        global _active_reloader
        _active_reloader = self
        atexit.register(self.shutdown_now)
        install_windows_console_handler()
        watcher = threading.Thread(target=self._watch, name="backend-source-watch", daemon=True)
        watcher.start()
        log(f"watching {WATCH_DIR} ; restart on .py changes or unexpected exit")
        log("close this window or press Ctrl+C to stop")
        try:
            while not self._stop.is_set():
                self._start()
                self._wait_until_restart()
        except KeyboardInterrupt:
            log("stopping")
            self._stop.set()
        finally:
            self.shutdown_now()
            _active_reloader = None
        return 0

    def shutdown_now(self) -> None:
        try:
            self._stop.set()
            self._restart.set()
            self._kill(wait=False)
        except Exception:
            return

    def _watch(self) -> None:
        try:
            self._watch_with_watchfiles()
        except ImportError:
            log("watchfiles is not installed, falling back to mtime polling")
            self._watch_by_polling()
        except Exception as error:
            log(f"watchfiles failed ({error}), falling back to mtime polling")
            self._watch_by_polling()

    def _watch_with_watchfiles(self) -> None:
        from watchfiles import PythonFilter, watch

        for _ in watch(
            WATCH_DIR,
            watch_filter=PythonFilter(),
            debounce=int(CHANGE_DEBOUNCE_SECONDS * 1000),
            stop_event=self._stop,
        ):
            if self._stop.is_set():
                return
            self._restart.set()

    def _watch_by_polling(self) -> None:
        previous = snapshot_sources(WATCH_DIR)
        while not self._stop.wait(POLL_INTERVAL_SECONDS):
            current = snapshot_sources(WATCH_DIR)
            if current != previous:
                previous = current
                self._restart.set()

    def _start(self) -> None:
        if self._stop.is_set():
            return
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--app-dir",
            str(WORKSPACE_DIR),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--timeout-graceful-shutdown",
            "5",
            *self.extra_args,
        ]
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        self._child = subprocess.Popen(
            command,
            cwd=str(WORKSPACE_DIR),
            env=env,
            creationflags=creation_flags(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        if self._child.stdout is not None:
            threading.Thread(
                target=self._pump_output,
                args=(self._child.stdout,),
                name="uvicorn-log-pump",
                daemon=True,
            ).start()
        log(f"started uvicorn pid {self._child.pid} on {self.host}:{self.port}")

    def _pump_output(self, stream) -> None:
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                sys.stdout.buffer.write(chunk)
                sys.stdout.flush()
        except Exception:
            return

    def _wait_until_restart(self) -> None:
        while not self._stop.is_set():
            child = self._child
            if child is None:
                return
            code = child.poll()
            if code is not None:
                if self._stop.is_set():
                    return
                self._crash_count += 1
                delay = restart_delay(self._crash_count)
                log(f"uvicorn exited with {code}; restarting in {delay:.0f}s")
                self._child = None
                if self._stop.wait(delay):
                    return
                return
            if self._restart.wait(timeout=0.3):
                self._restart.clear()
                if self._stop.is_set():
                    return
                self._crash_count = 0
                log("detected backend Python change; restarting")
                time.sleep(CHANGE_DEBOUNCE_SECONDS)
                self._restart.clear()
                self._kill(wait=True)
                time.sleep(PORT_RELEASE_SECONDS)
                return

    def _kill(self, wait: bool) -> None:
        child = self._child
        self._child = None
        if child is None:
            return
        pid = child.pid
        if pid:
            kill_process_tree(pid, wait=wait)
        if not wait:
            return
        try:
            child.wait(timeout=KILL_WAIT_SECONDS)
        except Exception:
            try:
                child.kill()
            except OSError:
                return


def main(argv: list[str] | None = None) -> int:
    enable_windows_ansi()
    parser = argparse.ArgumentParser(description="Local FastAPI supervisor with Windows-safe reload")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args, extra = parser.parse_known_args(argv)
    if not WATCH_DIR.is_dir():
        log(f"watch directory is missing: {WATCH_DIR}")
        return 1
    return DevReloader(args.host, args.port, extra).run()


if __name__ == "__main__":
    sys.exit(main())
