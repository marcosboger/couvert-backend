"""Catalog caching: the in-process TTL cache and the client cache headers."""

import asyncio

from fastapi.testclient import TestClient

from api.deps import get_restaurant_repository
from api.main import app
from core.cache import TtlCache
from core.db.cached_restaurant_repository import CachedRestaurantRepository
from core.models.restaurant import AwardMention, RestaurantDoc
from tests.test_couvert_api import CATALOG, FakeRestaurantRepository


class CountingRepository(FakeRestaurantRepository):
    """Records how often each expensive read reaches the database."""

    def __init__(self, docs: list[RestaurantDoc]) -> None:
        super().__init__(docs)
        self.calls: dict[str, int] = {}

    def _tally(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    async def cuisine_counts(self):
        self._tally("cuisine_counts")
        return await super().cuisine_counts()

    async def with_awards(self):
        self._tally("with_awards")
        return await super().with_awards()

    async def search(self, *, cuisine=None, term=None, limit=60):
        self._tally("search")
        return await super().search(cuisine=cuisine, term=term, limit=limit)

    async def get(self, restaurant_id: str):
        self._tally("get")
        return await super().get(restaurant_id)


def _cached(ttl: float = 60) -> tuple[CachedRestaurantRepository, CountingRepository]:
    inner = CountingRepository(CATALOG)
    return CachedRestaurantRepository(inner, ttl_seconds=ttl), inner


def test_repeated_scans_hit_the_database_once():
    repo, inner = _cached()

    async def go():
        for _ in range(5):
            await repo.cuisine_counts()
            await repo.with_awards()

    asyncio.run(go())
    assert inner.calls["cuisine_counts"] == 1
    assert inner.calls["with_awards"] == 1


def test_an_expired_entry_is_reloaded():
    repo, inner = _cached(ttl=0)

    async def go():
        await repo.cuisine_counts()
        await repo.cuisine_counts()

    asyncio.run(go())
    assert inner.calls["cuisine_counts"] == 2


def test_cuisine_listings_are_cached_but_free_text_searches_are_not():
    """Row queries repeat with fixed arguments; search terms are unbounded."""
    repo, inner = _cached()

    async def go():
        await repo.search(cuisine="Italiano", limit=12)
        await repo.search(cuisine="Italiano", limit=12)
        await repo.search(term="nino")
        await repo.search(term="nino")

    asyncio.run(go())
    assert inner.calls["search"] == 3  # one cached listing + two live term searches


def test_point_reads_are_never_cached():
    repo, inner = _cached()

    async def go():
        await repo.get("nino-cucina")
        await repo.get("nino-cucina")

    asyncio.run(go())
    assert inner.calls["get"] == 2


def test_callers_cannot_reorder_the_cached_list():
    """The routers sort what they get back; that must not touch the cache."""
    repo, _ = _cached()

    async def go():
        first = await repo.with_awards()
        first.sort(key=lambda d: d.name, reverse=True)
        return await repo.with_awards()

    second = asyncio.run(go())
    assert [d.name for d in second] == [d.name for d in CATALOG if d.awards]


def test_concurrent_misses_load_only_once():
    """A traffic burst on a cold cache must not become N identical queries."""
    repo, inner = _cached()

    async def go():
        await asyncio.gather(*(repo.cuisine_counts() for _ in range(10)))

    asyncio.run(go())
    assert inner.calls["cuisine_counts"] == 1


def test_ttl_cache_returns_the_loaded_value():
    cache = TtlCache(ttl_seconds=60)

    async def go():
        return await cache.get_or_load("k", lambda: _answer())

    async def _answer():
        return 42

    assert asyncio.run(go()) == 42


# --- client cache headers ---------------------------------------------------


def _client() -> TestClient:
    repo = CachedRestaurantRepository(FakeRestaurantRepository(CATALOG), ttl_seconds=60)
    app.dependency_overrides[get_restaurant_repository] = lambda: repo
    return TestClient(app)


def test_content_responses_carry_cache_control_and_etag():
    with _client() as client:
        response = client.get("/couvert/cuisines")
    assert response.status_code == 200
    assert "max-age=" in response.headers["cache-control"]
    assert response.headers["cache-control"].startswith("public")
    assert response.headers["etag"]
    app.dependency_overrides.clear()


def test_a_matching_etag_gets_a_304_with_no_body():
    with _client() as client:
        first = client.get("/couvert/restaurants")
        etag = first.headers["etag"]
        second = client.get("/couvert/restaurants", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
    app.dependency_overrides.clear()


def test_a_stale_etag_gets_the_full_body():
    with _client() as client:
        response = client.get("/couvert/cuisines", headers={"If-None-Match": '"nonsense"'})
    assert response.status_code == 200
    assert response.json()
    app.dependency_overrides.clear()


def test_etags_differ_between_endpoints():
    with _client() as client:
        a = client.get("/couvert/cuisines").headers["etag"]
        b = client.get("/couvert/awards").headers["etag"]
    assert a != b
    app.dependency_overrides.clear()


def test_user_endpoints_are_never_marked_cacheable():
    """Per-user authenticated data must not be cached by a device or a proxy."""
    with TestClient(app) as client:
        response = client.get("/user/me")
    assert "cache-control" not in {k.lower() for k in response.headers}


def test_health_is_not_cached():
    with TestClient(app) as client:
        response = client.get("/health")
    assert "cache-control" not in {k.lower() for k in response.headers}


def test_award_detail_is_cacheable_too():
    doc = next(d for d in CATALOG if d.awards)
    assert isinstance(doc.awards[0], AwardMention)
    with _client() as client:
        response = client.get("/couvert/awards/guia-michelin")
    assert response.status_code == 200
    assert response.headers["etag"]
    app.dependency_overrides.clear()
