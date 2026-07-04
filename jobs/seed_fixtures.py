"""Seed Cosmos with the app's fixture restaurant catalog. Idempotent — safe to re-run.

Usage:
    uv run python -m jobs.seed_fixtures init-db   # create database + containers (one-time)
    uv run python -m jobs.seed_fixtures seed      # upsert the ~25 fixture restaurants
"""

import typer
from azure.cosmos import CosmosClient, PartitionKey

from core.config import get_settings
from jobs.fixtures import restaurant_docs

app = typer.Typer(help="Couvert Cosmos seeding jobs")

CONTAINERS: list[tuple[str, str]] = [
    ("users", "/uid"),
    ("restaurants", "/id"),
    ("user_content", "/uid"),
    ("content", "/type"),
]

# Free tier grants 1000 RU/s account-wide. The legacy FoodApp database in this account
# already holds 600 RU/s shared, so CouvertApp gets the 400 minimum: 600 + 400 = 1000 → $0.
SHARED_THROUGHPUT_RU = 400


def _client() -> CosmosClient:
    settings = get_settings()
    if not settings.cosmos_configured:
        typer.echo("COSMOS_ENDPOINT / COSMOS_KEY not set — configure .env first.", err=True)
        raise typer.Exit(code=1)
    return CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)


@app.command()
def init_db() -> None:
    """Create the database and the four containers with their partition keys."""
    settings = get_settings()
    client = _client()
    database = client.create_database_if_not_exists(
        id=settings.cosmos_database, offer_throughput=SHARED_THROUGHPUT_RU
    )
    for name, pk in CONTAINERS:
        database.create_container_if_not_exists(id=name, partition_key=PartitionKey(path=pk))
        typer.echo(f"container ok: {name} (pk {pk})")
    typer.echo(f"database '{settings.cosmos_database}' ready.")


@app.command()
def seed() -> None:
    """Upsert the fixture restaurant catalog into the restaurants container."""
    settings = get_settings()
    client = _client()
    container = client.get_database_client(settings.cosmos_database).get_container_client(
        settings.restaurants_container
    )
    docs = restaurant_docs()
    for doc in docs:
        container.upsert_item(doc)
        typer.echo(f"upserted: {doc['id']}")
    typer.echo(f"done — {len(docs)} restaurants.")


if __name__ == "__main__":
    app()
