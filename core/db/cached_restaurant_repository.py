"""Caching decorator over a RestaurantRepository.

Wraps any repository, so the Cosmos implementation stays free of caching concerns
and tests can wrap a fake one.

What is cached, and why only these:
- `cuisine_counts()` and `with_awards()` scan the catalog (22 and 44 RU) and back
  /cuisines, /awards, /discover and /home.
- `search()` **only when there is no search term** — the 12 cuisine-row queries on
  an unfiltered /restaurants are ~4.4 RU each and dominate that request's 78 RU.
  Free-text terms are user-driven and unbounded, so caching them would grow the
  key space without bound for little gain.
- `get()` is a 1.7 RU point read across 697 possible ids — not worth the memory.
"""

from core.cache import TtlCache
from core.db.restaurant_repository import RestaurantRepository
from core.models.restaurant import RestaurantDoc


class CachedRestaurantRepository:
    def __init__(self, inner: RestaurantRepository, ttl_seconds: float) -> None:
        self._inner = inner
        self._cache = TtlCache(ttl_seconds)

    async def get(self, restaurant_id: str) -> RestaurantDoc | None:
        return await self._inner.get(restaurant_id)

    async def search(
        self, *, cuisine: str | None = None, term: str | None = None, limit: int = 60
    ) -> list[RestaurantDoc]:
        if term:
            return await self._inner.search(cuisine=cuisine, term=term, limit=limit)
        # Copied on the way out: callers sort and slice these lists, and an
        # in-place sort would reorder the cached copy for everyone else.
        cached = await self._cache.get_or_load(
            f"search:{cuisine}:{limit}",
            lambda: self._inner.search(cuisine=cuisine, limit=limit),
        )
        return list(cached)

    async def cuisine_counts(self) -> list[tuple[str, int]]:
        cached = await self._cache.get_or_load("cuisine_counts", self._inner.cuisine_counts)
        return list(cached)

    async def with_awards(self) -> list[RestaurantDoc]:
        cached = await self._cache.get_or_load("with_awards", self._inner.with_awards)
        return list(cached)

    async def count(self, *, cuisine: str | None = None, term: str | None = None) -> int:
        if term:
            return await self._inner.count(cuisine=cuisine, term=term)
        return await self._cache.get_or_load(
            f"count:{cuisine}",
            lambda: self._inner.count(cuisine=cuisine),
        )

    def clear(self) -> None:
        self._cache.clear()
