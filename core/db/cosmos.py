"""Async Cosmos client factory for the API (jobs use the sync client directly)."""

from azure.cosmos.aio import ContainerProxy, CosmosClient

from core.config import Settings


def create_client(settings: Settings) -> CosmosClient:
    return CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)


def get_container(client: CosmosClient, settings: Settings, container_name: str) -> ContainerProxy:
    database = client.get_database_client(settings.cosmos_database)
    return database.get_container_client(container_name)
