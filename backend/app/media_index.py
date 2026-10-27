from __future__ import annotations

import threading
from typing import Any

from .storage import JobStore

_MAX_SCOPES = 32


class MediaOutputIndex:
    """Path to output lookup that survives between media requests.

    ``/api/media`` used to hydrate up to a thousand complete jobs per request
    just to find one file. The index is rebuilt from a narrow projection only
    after the job store reports new content, once per owner scope.
    """

    def __init__(self, store: JobStore) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._epoch: int | None = None
        self._scopes: dict[str | None, dict[str, dict[str, Any]]] = {}

    def lookup(self, user_id: str | None, path: str) -> dict[str, Any] | None:
        with self._lock:
            epoch = self._store.content_epoch()
            if epoch != self._epoch:
                self._scopes.clear()
                self._epoch = epoch
            index = self._scopes.get(user_id)
            if index is None:
                index = self._store.output_locations(user_id, 1000)
                if len(self._scopes) >= _MAX_SCOPES:
                    self._scopes.clear()
                self._scopes[user_id] = index
            return index.get(path)
