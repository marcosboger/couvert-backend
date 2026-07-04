from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routers import user
from core.config import get_settings
from core.db.cosmos import create_client, get_container
from core.db.user_repository import CosmosUserRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = None
    if settings.cosmos_configured:
        client = create_client(settings)
        container = get_container(client, settings, settings.users_container)
        app.state.user_repository = CosmosUserRepository(container)
    yield
    if client is not None:
        await client.close()


app = FastAPI(title="Couvert API", version="0.1.0", lifespan=lifespan)
app.include_router(user.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
