"""Restaurant id slugs — the app-facing key.

Byte-identical to makeRestaurantId() in
couvert-app/src/data/couvert/fixtures/restaurants.fixture.ts. Both fold accents by
stripping Unicode category Mn from the NFD form, so 'Íz' → 'iz', never 'z'.
Changing one side means changing the other; test-locked in tests/test_fixtures.py.
"""

import re
import unicodedata


def make_restaurant_id(name: str) -> str:
    decomposed = unicodedata.normalize("NFD", name)
    # Category Mn = nonspacing marks, the same set the frontend strips.
    folded = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
