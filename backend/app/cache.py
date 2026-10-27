from __future__ import annotations

import threading
import time
from typing import Any, Callable, Hashable, TypeVar

T = TypeVar("T")


class TTLCache:
    """In-process cache for expensive read-only probes of external services."""

    def __init__(self, ttl_seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[Hashable, tuple[float, Any]] = {}

    def get_or_create(self, key: Hashable, factory: Callable[[], T]) -> T:
        now = self._clock()
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]
        value = factory()
        with self._lock:
            self._entries[key] = (self._clock() + self._ttl_seconds, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class EpochCache:
    """Derived read models invalidated by a monotonically increasing content epoch."""

    def __init__(self, max_entries: int = 16) -> None:
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: dict[Hashable, tuple[int, Any]] = {}

    def get_or_build(self, key: Hashable, epoch: int, builder: Callable[[], T]) -> T:
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None and cached[0] == epoch:
                return cached[1]
        value = builder()
        with self._lock:
            if len(self._entries) >= self._max_entries and key not in self._entries:
                self._entries.pop(next(iter(self._entries)))
            self._entries[key] = (epoch, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
