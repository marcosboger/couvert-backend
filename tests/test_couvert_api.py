"""Contract tests for the Couvert content API. No Cosmos, no Firebase."""

import pytest
from fastapi.testclient import TestClient

from api.deps import get_restaurant_repository
from api.main import app
from core.models.restaurant import AwardMention, RestaurantDoc


def _doc(name: str, cuisines: list[str], **extra) -> RestaurantDoc:
    from core.slug import make_restaurant_id

    base = dict(
        id=make_restaurant_id(name),
        name=name,
        source_name=name,
        cuisines=cuisines,
        scope="sp",
        city="São Paulo",
        resolution_status="matched",
    )
    base.update(extra)
    return RestaurantDoc(**base)


CATALOG = [
    _doc("Nino Cucina", ["Italiano"], latitude=-23.56, longitude=-46.65),
    _doc("Picchi", ["Italiano"], awards=[AwardMention(raw="x", award="Guia Michelin", year=2025)]),
    _doc("Íz", ["Contemporâneo"], awards=[AwardMention(raw="y", award="Guia Michelin", year=2024)]),
    _doc("Jun Sakamoto", ["Japonês"], image_key="imgRestaurant"),
    _doc("Arábia", ["Árabe"]),
]
# Out of scope: must never surface. Mirrors the leftover fixture docs in Cosmos.
OUT_OF_SCOPE = _doc("Sushi Leblon", ["Japonês"], scope="other_city", city="Rio de Janeiro")


class FakeRestaurantRepository:
    def __init__(self, docs: list[RestaurantDoc]) -> None:
        self.docs = [d for d in docs if d.scope == "sp"]

    async def get(self, restaurant_id: str) -> RestaurantDoc | None:
        return next((d for d in self.docs if d.id == restaurant_id), None)

    async def search(self, *, cuisine=None, term=None, limit=60) -> list[RestaurantDoc]:
        found = self.docs
        if cuisine:
            found = [d for d in found if cuisine in d.cuisines]
        if term:
            from core.slug import make_restaurant_id

            needle, slug = term.lower(), make_restaurant_id(term)
            found = [d for d in found if needle in d.name.lower() or slug in d.id]
        return sorted(found, key=lambda d: d.name)[:limit]

    async def cuisine_counts(self) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for doc in self.docs:
            for cuisine in doc.cuisines:
                counts[cuisine] = counts.get(cuisine, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    async def with_awards(self) -> list[RestaurantDoc]:
        return [d for d in self.docs if d.awards]

    async def count(self) -> int:
        return len(self.docs)


@pytest.fixture
def client():
    repo = FakeRestaurantRepository([*CATALOG, OUT_OF_SCOPE])
    app.dependency_overrides[get_restaurant_repository] = lambda: repo
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_cuisines_are_ranked_by_restaurant_count(client):
    body = client.get("/couvert/cuisines").json()
    assert body[0] == {"name": "Italiano", "restaurant_count": 2}
    assert {c["name"] for c in body} == {"Italiano", "Contemporâneo", "Japonês", "Árabe"}


def test_cuisines_exclude_restaurants_outside_sao_paulo(client):
    """'Sushi Leblon' is Japonês but in Rio — it must not inflate the count."""
    body = client.get("/couvert/cuisines").json()
    japanese = next(c for c in body if c["name"] == "Japonês")
    assert japanese["restaurant_count"] == 1


def test_unfiltered_list_returns_cuisine_rows(client):
    body = client.get("/couvert/restaurants").json()
    assert body["total"] == len(CATALOG)
    rows = {row["cuisine"]: row["restaurant_ids"] for row in body["rows"]}
    assert rows["Italiano"] == ["nino-cucina", "picchi"]
    ids = {r["id"] for r in body["restaurants"]}
    assert ids == {"nino-cucina", "picchi", "iz", "jun-sakamoto", "arabia"}


def test_filtering_by_cuisine_drops_the_grouping(client):
    body = client.get("/couvert/restaurants", params={"cuisine": "Italiano"}).json()
    assert body["rows"] == []
    assert [r["name"] for r in body["restaurants"]] == ["Nino Cucina", "Picchi"]
    assert body["total"] == 2


def test_search_is_accent_insensitive_through_the_slug(client):
    """Ids are accent-folded, so 'arabia' finds 'Arábia' without a folded index."""
    body = client.get("/couvert/restaurants", params={"search": "arabia"}).json()
    assert [r["name"] for r in body["restaurants"]] == ["Arábia"]


def test_search_requires_a_couple_of_characters(client):
    assert client.get("/couvert/restaurants", params={"search": "a"}).status_code == 422


def test_restaurant_detail_returns_the_wire_shape(client):
    body = client.get("/couvert/restaurants/nino-cucina").json()
    assert body["name"] == "Nino Cucina"
    assert body["cuisine"] == "Italiano"
    assert body["city"] == "São Paulo"
    assert body["latitude"] == -23.56
    # No rating anywhere in the pipeline yet — null, never a zero-star lie.
    assert body["rating"] is None


def test_missing_restaurant_is_a_404(client):
    response = client.get("/couvert/restaurants/nao-existe")
    assert response.status_code == 404
    assert response.json()["detail"] == "Restaurante não encontrado"


def test_a_restaurant_outside_sao_paulo_is_not_served(client):
    assert client.get("/couvert/restaurants/sushi-leblon").status_code == 404


def test_image_key_falls_back_to_a_bundled_asset(client):
    """Cards must render even though we have no photo URLs yet."""
    body = client.get("/couvert/restaurants/arabia").json()
    assert body["image_key"] in ("imgRestaurant", "imgCocktails")


def test_image_key_prefers_a_real_one_when_present(client):
    body = client.get("/couvert/restaurants/jun-sakamoto").json()
    assert body["image_key"] == "imgRestaurant"


def test_image_key_is_stable_across_requests(client):
    first = client.get("/couvert/restaurants/arabia").json()["image_key"]
    second = client.get("/couvert/restaurants/arabia").json()["image_key"]
    assert first == second


def test_discover_deck_leads_with_awarded_restaurants(client):
    body = client.get("/couvert/discover", params={"limit": 3}).json()
    # Both carry one award, so name order decides; 'Í' sorts after 'P' by code point.
    assert [r["id"] for r in body[:2]] == ["picchi", "iz"]
    assert len(body) == 3


def test_awards_are_derived_from_restaurant_mentions(client):
    body = client.get("/couvert/awards").json()
    [michelin] = body
    assert michelin["id"] == "guia-michelin"
    assert michelin["label"] == "Guia Michelin"
    assert michelin["years"] == [2024, 2025]
    assert michelin["restaurant_count"] == 2


def test_award_detail_lists_its_restaurants(client):
    body = client.get("/couvert/awards/guia-michelin").json()
    # 'Íz' folds to the id 'iz' — lower() alone would leave the accent.
    assert body["restaurant_ids"] == ["picchi", "iz"]
    assert [r["name"] for r in body["restaurants"]] == ["Picchi", "Íz"]


def test_missing_award_is_a_404(client):
    assert client.get("/couvert/awards/nao-existe").status_code == 404


def test_content_endpoints_need_no_token(client):
    """Guest tabs browse restaurants before sign-in."""
    for path in ("/couvert/cuisines", "/couvert/restaurants", "/couvert/awards"):
        assert client.get(path).status_code == 200
