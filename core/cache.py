"""Tiny in-process TTL cache for catalog reads.

The restaurant catalog only changes when a data job runs, so serving it from
memory for a few minutes is safe and takes the expensive queries off Cosmos —
`/couvert/restaurants` cost ~78 RU of a 400 RU/s shared budget, about five
requests per second before throttling.

Deliberately in-process: with scale-to-zero hosting there is no shared cache to
talk to, and a per-container copy of a read-only catalog is correct anyway. It
also means the cache dies with the container, which is fine — it refills from one
query.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any


class TtlCache:
    """Async-safe cache with a single loader per key.

    Concurrent misses on the same key wait on one load instead of all hitting the
    database — the stampede is the case worth protecting against, since it's
    exactly what a burst of traffic causes.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _fresh(self, key: str) -> tuple[bool, Any]:
        entry = self._entries.get(key)
        if entry is None:
            return False, None
        stored_at, value = entry
        if time.monotonic() - stored_at > self._ttl:
            return False, None
        return True, value

    async def get_or_load(self, key: str, loader: Callable[[], Awaitable[Any]]) -> Any:
        hit, value = self._fresh(key)
        if hit:
            return value
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Another waiter may have loaded it while we queued.
            hit, value = self._fresh(key)
            if hit:
                return value
            value = await loader()
            self._entries[key] = (time.monotonic(), value)
            return value

    def clear(self) -> None:
        self._entries.clear()
