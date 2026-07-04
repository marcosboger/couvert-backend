"""Restaurant seed catalog, ported from the app's mock fixtures.

Source of truth: couvert-app/src/data/couvert/fixtures/restaurants.fixture.ts
(RESTAURANT_CATALOG). IDs must stay byte-identical to the frontend's makeRestaurantId().
image_key/logo_key are the app's bundled-asset keys; real image_url/logo_url arrive with
the Google Maps enrichment job (Phase 3).
"""

import re
from typing import Any


def make_restaurant_id(name: str) -> str:
    """Python port of makeRestaurantId(): lowercase, non-[a-z0-9] runs → '-', trim '-'."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# (name, cuisine, rating, image_key, extras)
_CATALOG: list[tuple[str, str, int, str, dict[str, Any]]] = [
    (
        "Spot — JK",
        "Contemporânea",
        5,
        "imgRestaurant",
        {
            "logo_key": "logoSpot",
            "address": "Alameda Min. Rocha Azevedo, 72 — Bela Vista, São Paulo - SP",
            "latitude": -23.5615,
            "longitude": -46.6558,
        },
    ),
    (
        "Casa Tucupi",
        "Amazônica",
        5,
        "imgCocktails",
        {"city": "Pinheiros", "latitude": -23.5677, "longitude": -46.6934},
    ),
    ("Notiê", "Autoral", 4, "imgRestaurant", {"city": "República"}),
    ("Nelita", "Contemporânea", 5, "imgCocktails", {"city": "Jardins"}),
    (
        "Cantina 1900",
        "Italiana",
        5,
        "imgRestaurant",
        {
            "address": "Alameda Min. Rocha Azevedo, 72 — Bela Vista, São Paulo - SP",
            "latitude": -23.5615,
            "longitude": -46.6558,
        },
    ),
    ("La Tavola", "Italiana", 4, "imgCocktails", {}),
    ("Forneria", "Pizza", 5, "imgRestaurant", {}),
    ("Osteria", "Italiana", 4, "imgCocktails", {}),
    ("Ceviche Bar", "Peruana", 5, "imgRestaurant", {}),
    ("Lima", "Peruana", 4, "imgCocktails", {}),
    ("Pisco", "Peruana", 5, "imgRestaurant", {}),
    ("Inca", "Peruana", 4, "imgCocktails", {}),
    ("Poke House", "Poke", 5, "imgRestaurant", {}),
    ("Aloha", "Poke", 4, "imgCocktails", {}),
    ("Maki", "Poke", 5, "imgRestaurant", {}),
    ("Bowl", "Poke", 4, "imgCocktails", {}),
    (
        "Jun Sakamoto",
        "Japonesa",
        5,
        "imgRestaurant",
        {
            "logo_key": "logoJunSakamoto",
            "address": "R. Lisboa, 55 — Pinheiros, São Paulo - SP",
            "latitude": -23.5672,
            "longitude": -46.6918,
        },
    ),
    ("Aizomê", "Japonesa", 5, "imgCocktails", {}),
    ("Sa Pa", "Asiática", 4, "imgRestaurant", {}),
    ("Shin", "Japonesa", 4, "imgCocktails", {}),
    ("SPOT", "Contemporânea", 5, "imgRestaurant", {"logo_key": "logoSpot"}),
    ("Subastor", "Autoral", 4, "imgCocktails", {"logo_key": "logoSubastor"}),
    ("Nino", "Italiana", 5, "imgRestaurant", {"logo_key": "logoNino"}),
    ("Bar do Cofre", "Coquetelaria", 5, "imgCocktails", {"city": "Centro"}),
    (
        "Spot — JK Iguatemi",
        "Contemporânea",
        5,
        "imgRestaurant",
        {
            "logo_key": "logoSpot",
            "address": "Av. Pres. Juscelino Kubitschek, 2041 — Vila Olímpia, São Paulo - SP",
            "latitude": -23.5912,
            "longitude": -46.6874,
        },
    ),
]


def restaurant_docs() -> list[dict[str, Any]]:
    docs = []
    for name, cuisine, rating, image_key, extras in _CATALOG:
        doc: dict[str, Any] = {
            "id": make_restaurant_id(name),
            "name": name,
            "cuisine": cuisine,
            "rating": rating,
            "image_key": image_key,
            "image_url": None,
            "logo_key": extras.get("logo_key"),
            "logo_url": None,
            "city": extras.get("city"),
            "address": extras.get("address"),
            "latitude": extras.get("latitude"),
            "longitude": extras.get("longitude"),
            "source": "fixture",
        }
        docs.append(doc)
    return docs
