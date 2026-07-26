"""Canonical restaurant document (Cosmos `restaurants` container, pk /id).

The id is the frontend's name slug (makeRestaurantId port in jobs.fixtures).
`place_id`/address/coords/rating stay None until the Google Maps resolve+enrich
jobs run (Phase 3) — Maps is the future source of truth for canonical identity,
so ids may be rewritten once, before Phase 4 introduces user-content references.
"""

from pydantic import BaseModel, Field


class AwardMention(BaseModel):
    """Best-effort parse of one entry in the Excel 'Menção em Premiações' column."""

    raw: str
    placement: str | None = None
    category: str | None = None
    award: str | None = None
    year: int | None = None


class RestaurantDoc(BaseModel):
    id: str
    name: str
    source_name: str
    source: str = "excel"
    source_row: int | None = None

    # Google Maps canonical identity (resolve job). resolution_status:
    # "matched" | "low_confidence" | "unresolved" | "closed" | "uncached" | None.
    place_id: str | None = None
    maps_name: str | None = None
    maps_types: list[str] = Field(default_factory=list)
    resolution_status: str | None = None

    # São Paulo is the launch city. The workbook also carries Rio, BH, Salvador
    # and others; those are flagged and parked rather than dropped.
    # "sp" | "other_city" | "unknown"
    scope: str = "sp"

    # Several workbook rows can turn out to be one Google place ('Arabia' /
    # 'Arábia'). The survivor keeps the ids and names it absorbed.
    merged_ids: list[str] = Field(default_factory=list)
    merged_names: list[str] = Field(default_factory=list)

    place_types: list[str] = Field(default_factory=list)
    cuisines: list[str] = Field(default_factory=list)
    occasions: list[str] = Field(default_factory=list)
    positionings: list[str] = Field(default_factory=list)
    specialties: list[str] = Field(default_factory=list)
    chef: str | None = None
    editorial_comment: str | None = None
    awards_mention: str | None = None
    awards: list[AwardMention] = Field(default_factory=list)

    # Filled by Maps enrichment (Phase 3); interim images resolve via bundled
    # image_key on the app side.
    rating: float | None = None
    address: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    image_url: str | None = None
    logo_url: str | None = None
    image_key: str | None = None
    logo_key: str | None = None

    @property
    def cuisine(self) -> str | None:
        """Primary cuisine — what the app's Restaurant DTO exposes."""
        return self.cuisines[0] if self.cuisines else None
