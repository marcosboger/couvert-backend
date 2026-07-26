"""Repository-level guards that the fake repo in the API tests can't express."""

import asyncio

from core.db.restaurant_repository import CosmosRestaurantRepository


class _StubContainer:
    """Minimal stand-in for an async Cosmos ContainerProxy."""

    def __init__(self, item: dict) -> None:
        self._item = item
        self.reads: list[str] = []

    async def read_item(self, item: str, partition_key: str) -> dict:
        self.reads.append(item)
        return self._item


def _get(item: dict, restaurant_id: str):
    repo = CosmosRestaurantRepository(_StubContainer(item))
    return asyncio.run(repo.get(restaurant_id))


def test_a_legacy_fixture_document_reads_as_not_found():
    """The Phase 1 fixture docs still in the container have no source_name, so
    validating them would raise a 500 where the caller expects a 404."""
    legacy = {
        "id": "aizom",
        "name": "Aizomê",
        "cuisine": "Japonesa",
        "rating": 5,
        "source": "fixture",
    }
    assert _get(legacy, "aizom") is None


def test_a_restaurant_in_another_city_reads_as_not_found():
    other = {
        "id": "sushi-leblon",
        "name": "Sushi Leblon",
        "source_name": "Sushi Leblon",
        "scope": "other_city",
    }
    assert _get(other, "sushi-leblon") is None


def test_a_sao_paulo_restaurant_is_returned():
    doc = _get(
        {
            "id": "a-casa-do-porco",
            "name": "A Casa do Porco",
            "source_name": "A Casa do Porco",
            "scope": "sp",
            "cuisines": ["Brasileiro"],
            "city": "São Paulo",
        },
        "a-casa-do-porco",
    )
    assert doc is not None
    assert doc.cuisine == "Brasileiro"
