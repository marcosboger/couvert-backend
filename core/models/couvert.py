"""Wire models for the Couvert content API.

Shapes mirror the app's DTOs in couvert-app/src/data/couvert/types.ts, in
snake_case per the wire convention. The app's mapper layer
(mappers/restaurantMapper.ts) turns these into domain types.

Two honest gaps against RestaurantDto, both deliberate:
- `rating` is null. Google ratings are an Enterprise-tier field and we only pay
  for Pro; curation has no rating column either. Null rather than 0 so the app
  can show "no rating" instead of a zero-star lie.
- `image_key` falls back to a bundled asset key. Real photo URLs need Place
  Photos (also billed), so until then cards render a stock image.
"""

from pydantic import BaseModel

from core.models.restaurant import RestaurantDoc
from core.slug import make_restaurant_id

# Bundled asset keys that exist in the app (CouvertImageKey).
FALLBACK_IMAGE_KEYS = ("imgRestaurant", "imgCocktails")


def fallback_image_key(restaurant_id: str) -> str:
    """Stable per restaurant, so a card doesn't change image between requests."""
    return FALLBACK_IMAGE_KEYS[sum(restaurant_id.encode()) % len(FALLBACK_IMAGE_KEYS)]


class RestaurantWire(BaseModel):
    id: str
    name: str
    cuisine: str | None = None
    rating: float | None = None
    image_key: str
    city: str | None = None
    logo_key: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    @classmethod
    def from_doc(cls, doc: RestaurantDoc) -> "RestaurantWire":
        return cls(
            id=doc.id,
            name=doc.name,
            cuisine=doc.cuisine,
            rating=doc.rating,
            image_key=doc.image_key or fallback_image_key(doc.id),
            city=doc.city,
            logo_key=doc.logo_key,
            address=doc.address,
            latitude=doc.latitude,
            longitude=doc.longitude,
        )


class CuisineRowWire(BaseModel):
    """One catalog row: a cuisine and the restaurants filed under it."""

    cuisine: str
    restaurant_ids: list[str]


class RestaurantListWire(BaseModel):
    """`rows` is empty for filtered queries — a search result has no grouping.

    `total` is every restaurant matching the request, which can exceed
    `len(restaurants)` when `limit` truncates the page.
    """

    restaurants: list[RestaurantWire]
    rows: list[CuisineRowWire] = []
    total: int


class CuisineWire(BaseModel):
    name: str
    restaurant_count: int


class NewsItemWire(BaseModel):
    """Editorial item on the home feed.

    Declared but never populated yet — `/couvert/home` returns `news: []` because
    there is no editorial source wired up. The shape is fixed now so filling it
    later is a data change, not another frontend contract change. `title` carries
    real text, unlike the fixtures' i18n `titleKey`.
    """

    id: str
    source: str  # "paladar" | "veja-comer-beber" | "nossa-uol"
    title: str
    image_key: str
    award_id: str | None = None
    restaurant_id: str | None = None


class ActivityItemWire(BaseModel):
    """A friend's action. Empty until Phase 6 brings friendships."""

    id: str
    who: str
    color: str
    type: str  # "rated" | "quero" | "fui" | "fav"
    restaurant_id: str
    restaurant_name: str
    rating: float | None = None


class HomeFeedWire(BaseModel):
    """Mirrors the app's `HomeFeed`. Two of the three sections are empty by
    design; the app hides a section rather than rendering a placeholder."""

    news: list[NewsItemWire] = []
    recommendations: list[RestaurantWire] = []
    activity: list[ActivityItemWire] = []


class AwardWire(BaseModel):
    id: str
    label: str
    years: list[int]
    restaurant_count: int


class AwardDetailWire(AwardWire):
    restaurant_ids: list[str]
    restaurants: list[RestaurantWire]


def make_award_id(label: str) -> str:
    """Awards are addressed by slug, same convention as restaurants."""
    return make_restaurant_id(label)
