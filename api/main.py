import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.cache_headers import CacheHeadersMiddleware
from api.routers import couvert, user
from core.config import get_settings
from core.db.cached_restaurant_repository import CachedRestaurantRepository
from core.db.cosmos import create_client, get_container
from core.db.restaurant_repository import CosmosRestaurantRepository
from core.db.user_repository import CosmosUserRepository

logger = logging.getLogger("couvert.startup")


async def _warm_cache(repo: CachedRestaurantRepository) -> None:
    """Preload the catalog so the first real request doesn't pay for it.

    A cold browse costs ~14 round trips to Cosmos (seconds, from outside Azure),
    and with scale-to-zero hosting some user always lands on a cold container.
    Failures are swallowed: a warm cache is an optimisation, and every endpoint
    works without it.
    """
    with contextlib.suppress(Exception):
        await couvert.warm_catalog(repo)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.cosmos_configured:
        logger.warning(
            "COSMOS_ENDPOINT/COSMOS_KEY unset — every /couvert and /user route will 503."
        )
    if not settings.firebase_configured:
        # Not fatal: /couvert/* is public. But /user/* would accept a request and
        # then fail deep inside firebase_admin, which is a confusing way to learn
        # about a missing secret.
        logger.warning(
            "Neither FIREBASE_CREDENTIALS_JSON nor FIREBASE_CREDENTIALS_PATH is set — "
            "public content will serve, but every authenticated /user route will fail."
        )
    client = None
    warmup: asyncio.Task | None = None
    if settings.cosmos_configured:
        client = create_client(settings)
        app.state.user_repository = CosmosUserRepository(
            get_container(client, settings, settings.users_container)
        )
        app.state.restaurant_repository = CachedRestaurantRepository(
            CosmosRestaurantRepository(
                get_container(client, settings, settings.restaurants_container)
            ),
            ttl_seconds=settings.content_cache_seconds,
        )
        # Backgrounded so readiness isn't held up by the warm-up.
        warmup = asyncio.create_task(_warm_cache(app.state.restaurant_repository))
    yield
    if warmup is not None and not warmup.done():
        warmup.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await warmup
    if client is not None:
        await client.close()


app = FastAPI(title="Couvert API", version="0.1.0", lifespan=lifespan)
# Lets iOS/Android cache content responses on the device and revalidate with a 304.
app.add_middleware(CacheHeadersMiddleware, max_age=get_settings().content_cache_seconds)
# Expo web (browser) calls the API cross-origin; native apps send no Origin header.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=get_settings().cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(user.router)
app.include_router(couvert.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
