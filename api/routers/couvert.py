"""Couvert content API — read side.

Public on purpose: the app's guest tabs show restaurants before sign-in, so these
endpoints take no token. User-specific content (diary, lists, points) lives
elsewhere and stays authenticated.
"""

import asyncio
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_restaurant_repository
from core.db.restaurant_repository import RestaurantRepository
from core.models.couvert import (
    AwardDetailWire,
    AwardWire,
    CuisineRowWire,
    CuisineWire,
    HomeFeedWire,
    RestaurantListWire,
    RestaurantWire,
    make_award_id,
)
from core.models.restaurant import RestaurantDoc

router = APIRouter(prefix="/couvert", tags=["couvert"])

# Rows are for browsing, not exhaustive listing — the app links through to a
# cuisine query for the rest.
ROW_CUISINES = 12
ROW_SIZE = 12


HOME_RECOMMENDATIONS = 12


def _most_awarded(docs: list[RestaurantDoc]) -> list[RestaurantDoc]:
    """Never sort in place — the repository may hand back a cached list."""
    return sorted(docs, key=lambda d: (-len(d.awards), d.name))


async def _build_rows(
    repo: RestaurantRepository,
) -> tuple[list[CuisineRowWire], dict[str, RestaurantDoc]]:
    """The browse rows. Fetched concurrently: twelve serial round trips to Cosmos
    cost several seconds on a cold cache, and they don't depend on each other."""
    counts = await repo.cuisine_counts()
    wanted = [name for name, _ in counts[:ROW_CUISINES]]
    results = await asyncio.gather(
        *(repo.search(cuisine=name, limit=ROW_SIZE) for name in wanted)
    )
    rows: list[CuisineRowWire] = []
    by_id: dict[str, RestaurantDoc] = {}
    for name, docs in zip(wanted, results, strict=True):
        if not docs:
            continue
        rows.append(CuisineRowWire(cuisine=name, restaurant_ids=[d.id for d in docs]))
        by_id.update({d.id: d for d in docs})
    return rows, by_id


async def warm_catalog(repo: RestaurantRepository) -> None:
    """Preload everything an unfiltered browse and the home feed need, so the
    first request after a cold start doesn't pay for it."""
    await asyncio.gather(_build_rows(repo), repo.with_awards(), repo.count())


@router.get("/home", response_model=HomeFeedWire)
async def home_feed(
    repo: RestaurantRepository = Depends(get_restaurant_repository),
) -> HomeFeedWire:
    """The home screen's three sections, two of which are empty for now.

    `news` needs an editorial source that doesn't exist yet, and `activity`
    needs friendships (Phase 6). Both return `[]` rather than placeholder
    content, so the app can hide the section and show nothing invented.
    """
    awarded = _most_awarded(await repo.with_awards())
    return HomeFeedWire(
        news=[],
        recommendations=[RestaurantWire.from_doc(d) for d in awarded[:HOME_RECOMMENDATIONS]],
        activity=[],
    )


@router.get("/cuisines", response_model=list[CuisineWire])
async def list_cuisines(
    repo: RestaurantRepository = Depends(get_restaurant_repository),
) -> list[CuisineWire]:
    counts = await repo.cuisine_counts()
    return [CuisineWire(name=name, restaurant_count=n) for name, n in counts]


@router.get("/restaurants", response_model=RestaurantListWire)
async def list_restaurants(
    cuisine: str | None = Query(default=None, description="Exact cuisine label"),
    search: str | None = Query(default=None, min_length=2, description="Name fragment"),
    limit: int = Query(default=60, ge=1, le=200),
    repo: RestaurantRepository = Depends(get_restaurant_repository),
) -> RestaurantListWire:
    """Filtered list, or cuisine-grouped rows when nothing is filtered."""
    if cuisine or search:
        docs = await repo.search(cuisine=cuisine, term=search, limit=limit)
        return RestaurantListWire(
            restaurants=[RestaurantWire.from_doc(d) for d in docs],
            rows=[],
            # Everything matching the filter, not just this page.
            total=await repo.count(cuisine=cuisine, term=search),
        )

    rows, by_id = await _build_rows(repo)
    return RestaurantListWire(
        restaurants=[RestaurantWire.from_doc(d) for d in by_id.values()],
        rows=rows,
        total=await repo.count(),
    )


@router.get("/restaurants/{restaurant_id}", response_model=RestaurantWire)
async def get_restaurant(
    restaurant_id: str,
    repo: RestaurantRepository = Depends(get_restaurant_repository),
) -> RestaurantWire:
    doc = await repo.get(restaurant_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Restaurante não encontrado")
    return RestaurantWire.from_doc(doc)


@router.get("/discover", response_model=list[RestaurantWire])
async def discover_deck(
    limit: int = Query(default=20, ge=1, le=60),
    repo: RestaurantRepository = Depends(get_restaurant_repository),
) -> list[RestaurantWire]:
    """Onboarding swipe deck. Award-carrying places first — a stronger first
    impression than alphabetical order, and stable between requests."""
    deck = _most_awarded(await repo.with_awards())[:limit]
    if len(deck) < limit:
        seen = {d.id for d in deck}
        filler = await repo.search(limit=limit)
        deck += [d for d in filler if d.id not in seen][: limit - len(deck)]
    return [RestaurantWire.from_doc(d) for d in deck]


async def _award_index(repo: RestaurantRepository) -> dict[str, dict]:
    """Awards live inline on each restaurant, so the index is built by scanning
    the awarded ones and grouping their mentions."""
    index: dict[str, dict] = defaultdict(
        lambda: {"label": "", "years": set(), "docs": {}}
    )
    for doc in await repo.with_awards():
        for mention in doc.awards:
            label = (mention.award or mention.raw).strip()
            if not label:
                continue
            entry = index[make_award_id(label)]
            entry["label"] = label
            if mention.year:
                entry["years"].add(mention.year)
            entry["docs"][doc.id] = doc
    return index


@router.get("/awards", response_model=list[AwardWire])
async def list_awards(
    repo: RestaurantRepository = Depends(get_restaurant_repository),
) -> list[AwardWire]:
    index = await _award_index(repo)
    awards = [
        AwardWire(
            id=award_id,
            label=entry["label"],
            years=sorted(entry["years"]),
            restaurant_count=len(entry["docs"]),
        )
        for award_id, entry in index.items()
    ]
    awards.sort(key=lambda a: (-a.restaurant_count, a.label))
    return awards


@router.get("/awards/{award_id}", response_model=AwardDetailWire)
async def get_award(
    award_id: str,
    repo: RestaurantRepository = Depends(get_restaurant_repository),
) -> AwardDetailWire:
    entry = (await _award_index(repo)).get(award_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Premiação não encontrada")
    docs = sorted(entry["docs"].values(), key=lambda d: d.name)
    return AwardDetailWire(
        id=award_id,
        label=entry["label"],
        years=sorted(entry["years"]),
        restaurant_count=len(docs),
        restaurant_ids=[d.id for d in docs],
        restaurants=[RestaurantWire.from_doc(d) for d in docs],
    )
