"""Short-lived memos for the git probes that run on every engine build.

Why this exists (audit 2026-09-13): building an engine spawned SIX `git` subprocesses —
four in `environment.py`, one in `projects.py`, one in `session_facts.py` — ~180 ms of a
~220 ms build on Windows. The draft re-target path rebuilds the engine on every coworker
and folder pick, so the user paid that repeatedly for answers that cannot have changed in
the second between two clicks.

The memo is deliberately SHORT-LIVED rather than process-lifetime: every value here is a
snapshot of a working tree the user is actively editing, and a stale one is a lie the agent
is told about its own workspace. Ten seconds is long enough to cover a burst of rebuilds
(the picker) and short enough that nobody can act on a stale reading. Where staleness has a
security dimension — `session_facts` freezes the "known world" so an agent that adds its own
remote cannot make its destination look familiar — staleness errs on the safe side: a remote
added seconds ago reads as unknown, never as known.

Thread-safety: Wave 2 moves the engine build onto a worker thread, so every cache here is
guarded by its own lock. The value is computed OUTSIDE the lock — two threads racing on a
cold key may both spawn git (exactly today's cost, no worse), whereas computing under the
lock would let one workspace's 5-second git timeout stall every other workspace's build.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Hashable

# Long enough to collapse a burst of engine builds, short enough that no one can act on a
# stale reading of their own working tree.
TTL_SECONDS = 10.0

# A running process sees one state dir and a handful of workspaces; a cap keeps a
# long-lived server from accumulating entries for folders the user visited once.
_MAX_ENTRIES = 64

_ALL: "list[TTLCache]" = []
_ALL_LOCK = threading.Lock()


class TTLCache:
    """Keyed memo with a wall-clock TTL. Thread-safe; misses compute outside the lock."""

    def __init__(self, ttl: float = TTL_SECONDS) -> None:
        self._ttl = ttl
        self._lock = threading.Lock()
        self._entries: dict[Hashable, tuple[float, Any]] = {}
        with _ALL_LOCK:
            _ALL.append(self)

    def get(self, key: Hashable, compute: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and now - hit[0] < self._ttl:
                return hit[1]
        value = compute()
        stamp = time.monotonic()
        with self._lock:
            if len(self._entries) >= _MAX_ENTRIES:
                cutoff = stamp - self._ttl
                self._entries = {
                    k: v for k, v in self._entries.items() if v[0] >= cutoff
                }
                if len(self._entries) >= _MAX_ENTRIES:
                    self._entries.clear()
            self._entries[key] = (stamp, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def clear_all() -> None:
    """Drop every memo. For tests that change a working tree and re-probe it inside the
    TTL — real callers want the memo, so nothing in production calls this."""
    with _ALL_LOCK:
        caches = list(_ALL)
    for cache in caches:
        cache.clear()
