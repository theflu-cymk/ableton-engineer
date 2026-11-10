"""The snapshot cache (spec §7).

One read of the Set, reused by every report, invalidated by any write Enableton performs. The
cache is deliberately dumb: it knows how old the data is and what it cost, nothing about Live.
That keeps the invalidation rule in one place instead of scattered through the report code.

The age limit is a backstop, not the main mechanism — mutations through this server invalidate
eagerly. It exists because the user can drag a clip in Live while a model is thinking.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

SNAPSHOT_TIMEOUT_MS = 6000


class SnapshotCache(object):
    def __init__(self, adapter, max_age_s: float = 30.0, clock: Callable[[], float] = None):
        self._adapter = adapter
        self._max_age_s = max_age_s
        self._clock = clock or time.monotonic
        self._data = None  # type: Optional[Dict[str, Any]]
        self._taken = 0.0
        self._epoch = 0
        self._lock = threading.Lock()
        self.trace = []  # type: List[Dict[str, Any]]

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def stale(self) -> bool:
        return self._data is None or (self._clock() - self._taken) > self._max_age_s

    def get(self, refresh: bool = False) -> Dict[str, Any]:
        """Return the snapshot, reading Live at most once per invalidation."""
        with self._lock:
            if refresh or self.stale:
                self._fetch()
            return self._data

    def invalidate(self) -> None:
        """Forget the snapshot. Called after every write this server performs."""
        with self._lock:
            self._data = None
            self._epoch += 1

    def _fetch(self) -> None:
        started = self._clock()
        data = self._adapter.call("snapshot.get", {}, timeout_ms=SNAPSHOT_TIMEOUT_MS)
        if not isinstance(data, dict):
            raise TypeError("snapshot.get returned %r" % (type(data).__name__,))

        self._data = data
        self._taken = self._clock()

        counts = data.get("counts") or {}
        self.trace.append(
            {
                "cmd": "snapshot.get",
                "ms": round((self._taken - started) * 1000.0, 1),
                "tracks": counts.get("tracks"),
                "clips": (counts.get("arrangement_clips") or 0)
                + (counts.get("session_clips") or 0),
                "epoch": self._epoch,
            }
        )
