"""Canonical cuisine vocabulary — one label per cuisine.

The curation workbook spells the same cuisine both ways, which split one cuisine
into two filters: 'Italiano' had 113 restaurants while 'Italiana' had 2, so a
query for 'Italiana' looked almost empty. Ingestion now collapses every known
variant onto one canonical label.

The API also runs incoming `?cuisine=` through here, so a caller using a variant
still finds the restaurants. That matters because the app's onboarding chips
(`CUISINES` in couvert-app/src/data/couvert/fixtures/preferences.fixture.ts) are
written in the feminine form — 'Italiana', 'Francesa', 'Chinesa' — and would
otherwise match the stragglers instead of the real catalog.

Only unambiguous variants of the *same word* live here. Grouping distinct labels
(Peixes vs Frutos do Mar, Sushi/Ramen/Omakase under Japonês) is a curation
decision, not a spelling fix, and is deliberately left alone.
"""

import re
import unicodedata

# variant → canonical. Keys are matched accent- and case-insensitively.
CUISINE_VARIANTS = {
    # Both spellings appear in the workbook and split the cuisine in two.
    "Italiana": "Italiano",
    "Japonesa": "Japonês",
    "Francesa": "Francês",
    "Brasileira": "Brasileiro",
    "Espanhola": "Espanhol",
    "Vegetariana": "Vegetariano",
    "Contemporânea": "Contemporâneo",
    # Only the masculine form is in the workbook, but the app's chips use these.
    "Mexicana": "Mexicano",
    "Peruana": "Peruano",
    "Tailandesa": "Tailandês",
    "Chinesa": "Chinês",
    "Mediterrânea": "Mediterrâneo",
    "Asiática": "Asiático",
    "Argentina": "Argentino",
    "Portuguesa": "Português",
    "Coreana": "Coreano",
    "Europeia": "Europeu",
    "Grega": "Grego",
    "Vegana": "Vegano",
}


def _key(label: str) -> str:
    decomposed = unicodedata.normalize("NFD", label)
    folded = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", folded).strip().lower()


_BY_KEY = {_key(variant): canonical for variant, canonical in CUISINE_VARIANTS.items()}


def canonical_cuisine(label: str) -> str:
    """One canonical spelling. Unknown labels pass through unchanged, so a cuisine
    we have not catalogued still filters correctly."""
    stripped = label.strip()
    return _BY_KEY.get(_key(stripped), stripped)


def canonical_cuisines(labels: list[str]) -> list[str]:
    """Canonicalise and de-duplicate, preserving first-seen order."""
    seen: dict[str, None] = {}
    for label in labels:
        canonical = canonical_cuisine(label)
        if canonical:
            seen.setdefault(canonical, None)
    return list(seen)
