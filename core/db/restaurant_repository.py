"""Read access to the seeded restaurant catalog.

Every query is scoped to `scope = 'sp'`. That is both the product rule (São Paulo
is the launch city) and a safety net: the 20 leftover Phase 1 fixture documents
carry no `scope` field, so they can never leak into a response.
"""

from typing import Protocol

from azure.cosmos import exceptions
from azure.cosmos.aio import ContainerProxy

from core.models.restaurant import RestaurantDoc
from core.slug import make_restaurant_id

# Cosmos has no accent-insensitive comparison, but ids are already accent-folded
# slugs, so matching the folded term against the id gives it to us for free.
_FIELDS = (
    "c.id, c.name, c.source_name, c.cuisines, c.rating, c.city, c.address, "
    "c.latitude, c.longitude, c.image_key, c.logo_key, c.awards, c.place_types, "
    "c.occasions, c.specialties, c.chef, c.editorial_comment"
)
IN_SCOPE = "c.scope = 'sp'"
MAX_LIMIT = 200


class RestaurantRepository(Protocol):
    async def get(self, restaurant_id: str) -> RestaurantDoc | None: ...

    async def search(
        self, *, cuisine: str | None = None, term: str | None = None, limit: int = 60
    ) -> list[RestaurantDoc]: ...

    async def cuisine_counts(self) -> list[tuple[str, int]]: ...

    async def with_awards(self) -> list[RestaurantDoc]: ...

    async def count(self) -> int: ...


class CosmosRestaurantRepository:
    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    async def _query(self, query: str, params: list[dict]) -> list[RestaurantDoc]:
        items = self._container.query_items(query=query, parameters=params)
        return [RestaurantDoc.model_validate(item) async for item in items]

    async def get(self, restaurant_id: str) -> RestaurantDoc | None:
        try:
            item = await self._container.read_item(item=restaurant_id, partition_key=restaurant_id)
        except exceptions.CosmosResourceNotFoundError:
            return None
        # Scope is checked on the raw document, before validation: the leftover
        # Phase 1 fixture docs have no source_name and would raise instead of 404.
        if item.get("scope") != "sp":
            return None
        return RestaurantDoc.model_validate(item)

    async def search(
        self, *, cuisine: str | None = None, term: str | None = None, limit: int = 60
    ) -> list[RestaurantDoc]:
        where = [IN_SCOPE]
        params: list[dict] = [{"name": "@limit", "value": min(max(limit, 1), MAX_LIMIT)}]
        if cuisine:
            where.append("ARRAY_CONTAINS(c.cuisines, @cuisine)")
            params.append({"name": "@cuisine", "value": cuisine})
        if term:
            where.append("(CONTAINS(LOWER(c.name), @term) OR CONTAINS(c.id, @slug))")
            params.append({"name": "@term", "value": term.lower()})
            params.append({"name": "@slug", "value": make_restaurant_id(term)})
        query = (
            f"SELECT {_FIELDS} FROM c WHERE {' AND '.join(where)} "
            "ORDER BY c.name OFFSET 0 LIMIT @limit"
        )
        return await self._query(query, params)

    async def cuisine_counts(self) -> list[tuple[str, int]]:
        """Cosmos can't GROUP BY over an array, so the counting happens here."""
        query = f"SELECT c.cuisines FROM c WHERE {IN_SCOPE}"
        counts: dict[str, int] = {}
        async for item in self._container.query_items(query=query):
            for cuisine in item.get("cuisines") or []:
                counts[cuisine] = counts.get(cuisine, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    async def with_awards(self) -> list[RestaurantDoc]:
        query = (
            f"SELECT {_FIELDS} FROM c "
            f"WHERE {IN_SCOPE} AND IS_DEFINED(c.awards) AND ARRAY_LENGTH(c.awards) > 0"
        )
        return await self._query(query, [])

    async def count(self) -> int:
        query = f"SELECT VALUE COUNT(1) FROM c WHERE {IN_SCOPE}"
        async for total in self._container.query_items(query=query):
            return int(total)
        return 0
