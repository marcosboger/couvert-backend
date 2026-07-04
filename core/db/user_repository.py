import contextlib
from typing import Protocol

from azure.cosmos import exceptions
from azure.cosmos.aio import ContainerProxy

from core.models.user import UserDoc


class UserRepository(Protocol):
    async def get(self, uid: str) -> UserDoc | None: ...

    async def upsert(self, user: UserDoc) -> UserDoc: ...

    async def delete(self, uid: str) -> None: ...

    async def username_taken(self, username: str, exclude_uid: str | None = None) -> bool: ...


class CosmosUserRepository:
    """Users container: documents keyed and partitioned by uid (id == uid == partition key)."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    async def get(self, uid: str) -> UserDoc | None:
        try:
            item = await self._container.read_item(item=uid, partition_key=uid)
        except exceptions.CosmosResourceNotFoundError:
            return None
        return UserDoc.model_validate(item)

    async def upsert(self, user: UserDoc) -> UserDoc:
        stored = await self._container.upsert_item(body=user.model_dump())
        return UserDoc.model_validate(stored)

    async def delete(self, uid: str) -> None:
        # idempotent: deleting an absent user is fine
        with contextlib.suppress(exceptions.CosmosResourceNotFoundError):
            await self._container.delete_item(item=uid, partition_key=uid)

    async def username_taken(self, username: str, exclude_uid: str | None = None) -> bool:
        query = "SELECT VALUE c.uid FROM c WHERE c.username = @username"
        params: list[dict[str, object]] = [{"name": "@username", "value": username}]
        results = self._container.query_items(query=query, parameters=params)
        async for uid in results:
            if uid != exclude_uid:
                return True
        return False
