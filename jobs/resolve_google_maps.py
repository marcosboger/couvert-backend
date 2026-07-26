"""Resolve Excel restaurant names → Google Maps canonical identity (place_id).

Cost model (deliberate):
- Text Search runs AT MOST ONCE per restaurant, ever: every response is cached on
  disk (data/maps_cache/) keyed by the source name, and cached names are never
  re-queried. Later enrichment (rating/hours/photos, Phase 3) must use Place
  Details by the stored place_id — never a new text search.
- Every run has a hard --max-calls budget (default 10). The full catalog run is an
  explicit, human-approved action.
- Field mask requests Pro-tier fields only (id, displayName, formattedAddress,
  location, types) — no rating/hours/phone, which bill on the pricier tier.

Manual verdicts live in data/maps_overrides.json (see mark-closed / mark-query)
and win over whatever the cached search says — a human reviewing a batch is the
final authority on identity.

Usage:
    uv run python -m jobs.resolve_google_maps plan               # 0 network calls
    uv run python -m jobs.resolve_google_maps resolve            # up to 10 calls
    uv run python -m jobs.resolve_google_maps resolve --max-calls 1000
    uv run python -m jobs.resolve_google_maps report             # match quality, 0 calls
    uv run python -m jobs.resolve_google_maps mark-closed "Bottega 21"   # 0 calls
    uv run python -m jobs.resolve_google_maps mark-query "X" "X Pizzaria, São Paulo"
    uv run python -m jobs.resolve_google_maps requery "X"        # 1 call, re-searches
    uv run python -m jobs.resolve_google_maps confirm "X"        # accept match, 0 calls
"""

import json
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import httpx
import typer

from core.config import get_settings
from core.models.restaurant import RestaurantDoc
from jobs.ingest_excel import XLSX_OPTION, parse_workbook

app = typer.Typer(help="Google Maps identity resolution (cached, call-capped)")

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "maps_cache"
OVERRIDES_PATH = Path(__file__).resolve().parents[2] / "data" / "maps_overrides.json"
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,places.types"
)
# São Paulo center; bias only (not restrict) so oddballs still resolve.
LOCATION_BIAS = {
    "circle": {"center": {"latitude": -23.5613, "longitude": -46.6565}, "radius": 30000.0}
}
SECONDS_BETWEEN_CALLS = 0.7  # stays under a 100-requests/minute quota
MATCH_THRESHOLD = 0.6
MAX_CALLS_OPTION = typer.Option(10, help="Hard budget of Text Search calls this run.")
NOTE_OPTION = typer.Option("permanently closed", help="Why this name was settled by hand.")
PLACE_ID_OPTION = typer.Option("", help="Confirm this exact candidate, not the top-scoring one.")
NO_MATCH_NOTE_OPTION = typer.Option("wrong venue", help="Why the cached match was rejected.")
# Geographic results (streets, districts) can outscore the actual venue on name
# similarity — only ever match real establishments.
GEO_TYPES = {"route", "street_address", "locality", "sublocality", "neighborhood", "postal_code"}

# Words that carry no identity: Maps routinely appends them ('Shiro' →
# 'Shiro Japanese cocktail bar'), so they must not weigh on the comparison.
GENERIC_TOKENS = {
    "and", "bar", "bares", "bistro", "bistrot", "brasil", "brazil", "cafe", "caffe",
    "cocktail", "cocktails", "coffee", "da", "das", "de", "do", "dos", "e",
    "gastrobar", "pub", "restaurant", "restaurante", "sao", "paulo", "speakeasy",
    "sp", "the",
}
# One name fully contained in the other is a match regardless of length gap.
CONTAINMENT_SCORE = 0.85
# Below this, a containment claim is too weak to trust ('S.' inside anything).
# Three admits real short names — Aiô, Roi — while still rejecting initials.
MIN_CONTAINMENT_CHARS = 3


def load_overrides() -> dict[str, dict]:
    """Human verdicts keyed by Excel source name."""
    if OVERRIDES_PATH.exists():
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    return {}


def save_overrides(overrides: dict[str, dict]) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )


def _cache_key(source_name: str) -> str:
    normalized = unicodedata.normalize("NFKD", source_name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "unnamed"


def cache_path(source_name: str) -> Path:
    return CACHE_DIR / f"{_cache_key(source_name)}.json"


def load_cached(source_name: str) -> dict | None:
    path = cache_path(source_name)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _ascii_lower(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()


def similarity(source_name: str, maps_name: str) -> float:
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9 ]+", " ", _ascii_lower(s)).strip()

    return SequenceMatcher(None, norm(source_name), norm(maps_name)).ratio()


def significant_tokens(name: str) -> list[str]:
    """Identity-carrying words only; falls back to all words if that empties it."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", _ascii_lower(name)) if t]
    return [t for t in tokens if t not in GENERIC_TOKENS] or tokens


def match_score(source_name: str, maps_name: str) -> tuple[float, str]:
    """Confidence that two names denote the same venue, plus how we decided.

    Plain fuzzy ratio punishes Maps' habit of appending descriptors, so a name
    whose significant words are a subset of the other's counts as a match.
    """
    ratio = similarity(source_name, maps_name)
    source = significant_tokens(source_name)
    maps = significant_tokens(maps_name)
    source_flat, maps_flat = "".join(source), "".join(maps)
    if min(len(source_flat), len(maps_flat)) >= MIN_CONTAINMENT_CHARS and (
        ratio < CONTAINMENT_SCORE
    ):
        # Word spacing is not identity: 'Mamma San' is 'Mammasan'.
        if source_flat == maps_flat:
            return CONTAINMENT_SCORE, "same letters"
        if set(source) <= set(maps) or set(maps) <= set(source):
            return CONTAINMENT_SCORE, "contained"
    return ratio, "fuzzy"


def cached_candidates(source_name: str) -> list[dict]:
    """Cached results that could be a venue — geographic hits are never candidates."""
    cached = load_cached(source_name) or {}
    places = cached.get("response", {}).get("places", [])
    return [p for p in places if p.get("types") and not (set(p["types"]) & GEO_TYPES)]


def resolution_from_cache(source_name: str) -> dict | None:
    """Interpret a cached search response → {place_id, maps_name, address, lat, lng,
    types, status} or status-only when nothing matched. None = never queried.

    A human override (closed / pinned place) outranks the cached search.
    """
    override = load_overrides().get(source_name, {})
    if override.get("status") == "closed":
        return {"status": "closed", "note": override.get("note")}
    if override.get("status") == "no_match":
        # A human judged the cached candidates to be other venues entirely.
        return {"status": "unresolved", "note": override.get("note")}
    if load_cached(source_name) is None:
        return None
    candidates = cached_candidates(source_name)
    if not candidates:
        return {"status": "unresolved"}

    confirmed_id = override.get("confirmed_place_id")
    pinned = next((p for p in candidates if p.get("id") == confirmed_id), None)
    if confirmed_id and pinned is None:
        # The cache moved on since the human signed off — resurface it.
        return {"status": "low_confidence", "reason": "confirmed place no longer returned"}
    if pinned is not None:
        score, reason = 1.0, "confirmed"
        top = pinned
    else:
        scored = [
            (match_score(source_name, p.get("displayName", {}).get("text", "")), p)
            for p in candidates
        ]
        (score, reason), top = max(scored, key=lambda pair: pair[0][0])
    return {
        "status": "matched" if score >= MATCH_THRESHOLD else "low_confidence",
        "score": round(score, 3),
        "reason": reason,
        "place_id": top.get("id"),
        "maps_name": top.get("displayName", {}).get("text", ""),
        "address": top.get("formattedAddress"),
        "latitude": top.get("location", {}).get("latitude"),
        "longitude": top.get("location", {}).get("longitude"),
        "types": top.get("types", []),
    }


def build_query(doc: RestaurantDoc, overrides: dict[str, dict] | None = None) -> str:
    """Curated place type disambiguates ('Guarita Bar' vs the street 'Rua Guariata').

    A hand-written override query replaces it outright, for the cases where the
    curated type sends the search to the wrong kind of venue.
    """
    override = (overrides or {}).get(doc.source_name, {})
    if override.get("query"):
        return override["query"]
    place_type = doc.place_types[0] if doc.place_types else ""
    if place_type and place_type.lower() not in doc.source_name.lower():
        return f"{doc.source_name} {place_type}, São Paulo"
    return f"{doc.source_name}, São Paulo"


def _unique_docs(xlsx: Path) -> list[RestaurantDoc]:
    docs, _ = parse_workbook(xlsx)
    seen: dict[str, RestaurantDoc] = {}
    for doc in docs:
        seen.setdefault(doc.source_name, doc)
    return list(seen.values())


def _pending_docs(xlsx: Path) -> list[RestaurantDoc]:
    """Names still needing a call: never queried and not settled by a human."""
    overrides = load_overrides()
    return [
        d
        for d in _unique_docs(xlsx)
        if load_cached(d.source_name) is None
        and overrides.get(d.source_name, {}).get("status") != "closed"
    ]


@app.command()
def plan(xlsx: Path = XLSX_OPTION) -> None:
    """How many uncached names a full resolve would query. Zero network calls."""
    pending = _pending_docs(xlsx)
    typer.echo(f"uncached names (= Text Search calls a full run would make): {len(pending)}")
    for doc in pending[:10]:
        typer.echo(f"  e.g. {build_query(doc)}")


def _require_api_key() -> str:
    key = get_settings().google_maps_api_key
    if not key:
        typer.echo("GOOGLE_MAPS_API_KEY not set in .env", err=True)
        raise typer.Exit(code=1)
    return key


def _search_and_cache(
    client: httpx.Client, headers: dict[str, str], doc: RestaurantDoc, query: str
) -> dict | None:
    """One billed Text Search → cache file. Aborts the run on any non-200 so a
    transient failure never lands in the cache as a permanent 'no match'."""
    body = {"textQuery": query, "pageSize": 3, "locationBias": LOCATION_BIAS}
    response = client.post(SEARCH_URL, headers=headers, json=body)
    if response.status_code != 200:
        typer.echo(
            f"  {doc.source_name}: HTTP {response.status_code} — {response.text[:200]}", err=True
        )
        typer.echo("aborting run (nothing cached for failed calls).", err=True)
        raise typer.Exit(code=1)
    cache_path(doc.source_name).write_text(
        json.dumps({"query": query, "response": response.json()}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return resolution_from_cache(doc.source_name)


def _summarize(res: dict | None) -> str:
    if not res:
        return "-"
    return f"{res.get('maps_name') or '-'} ({res['status']} {res.get('score', '')})".strip()


@app.command()
def resolve(
    xlsx: Path = XLSX_OPTION,
    max_calls: int = MAX_CALLS_OPTION,
) -> None:
    """Query uncached names, newest cache wins. Costs one call per name, capped."""
    api_key = _require_api_key()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    overrides = load_overrides()

    pending = _pending_docs(xlsx)
    typer.echo(f"pending: {len(pending)} — this run will call at most {max_calls}")
    calls = 0
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=15) as client:
        for doc in pending:
            if calls >= max_calls:
                typer.echo(f"call budget reached ({max_calls}) — stopping.")
                break
            calls += 1
            res = _search_and_cache(client, headers, doc, build_query(doc, overrides))
            typer.echo(f"  [{calls}] {doc.source_name} → {_summarize(res)}")
            time.sleep(SECONDS_BETWEEN_CALLS)
    typer.echo(f"done — {calls} calls made, {len(pending) - calls} still pending.")


@app.command()
def mark_closed(
    name: str,
    note: str = NOTE_OPTION,
) -> None:
    """Record that a curated place no longer exists. Zero network calls.

    Keeps it out of future resolve runs and out of the review list, rather than
    letting it settle on some unrelated venue's place_id.
    """
    overrides = load_overrides()
    overrides.setdefault(name, {}).update({"status": "closed", "note": note})
    save_overrides(overrides)
    typer.echo(f"marked closed: {name!r} ({note})")


@app.command()
def confirm(name: str, place_id: str = PLACE_ID_OPTION) -> None:
    """Accept a cached candidate as correct. Zero network calls.

    Pins its place_id, so a name the scorer can't credit ('Hotel Unique Sky Bar'
    → 'Skye') stops coming back for review — and resurfaces if the cache ever
    stops returning that place. Defaults to the top-scoring candidate; pass
    --place-id to pick a lower-ranked one the scorer got wrong.
    """
    candidates = cached_candidates(name)
    if not candidates:
        typer.echo(f"{name!r} has no cached candidate — run `requery` first.", err=True)
        raise typer.Exit(code=1)
    if place_id:
        chosen = next((p for p in candidates if p.get("id") == place_id), None)
        if chosen is None:
            ids = [p.get("id") for p in candidates]
            typer.echo(f"{place_id!r} is not a cached candidate for {name!r}: {ids}", err=True)
            raise typer.Exit(code=1)
    else:
        res = resolution_from_cache(name)
        chosen = next((p for p in candidates if p.get("id") == res.get("place_id")), None)
    overrides = load_overrides()
    overrides.setdefault(name, {})["confirmed_place_id"] = chosen["id"]
    save_overrides(overrides)
    typer.echo(
        f"confirmed: {name!r} → {chosen.get('displayName', {}).get('text')!r} ({chosen['id']})"
    )


@app.command()
def mark_no_match(
    name: str,
    note: str = NO_MATCH_NOTE_OPTION,
) -> None:
    """Reject the cached candidates as the wrong venue. Zero network calls.

    For the case where Maps confidently returned a different restaurant — left
    alone, that place_id would let two curated rows collapse into one venue.
    """
    overrides = load_overrides()
    overrides.setdefault(name, {}).update({"status": "no_match", "note": note})
    overrides[name].pop("confirmed_place_id", None)
    save_overrides(overrides)
    typer.echo(f"rejected match for {name!r} ({note})")


@app.command()
def mark_query(name: str, query: str) -> None:
    """Pin a hand-written search query for a name. Zero network calls by itself —
    run `requery <name>` afterwards to spend the one call it needs."""
    overrides = load_overrides()
    overrides.setdefault(name, {})["query"] = query
    save_overrides(overrides)
    typer.echo(f"query set for {name!r}: {query!r} — run `requery {name!r}` to apply.")


@app.command()
def requery(
    names: list[str],
    xlsx: Path = XLSX_OPTION,
) -> None:
    """Re-search specific names, overwriting their cache. One call per name."""
    api_key = _require_api_key()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    overrides = load_overrides()
    by_name = {d.source_name: d for d in _unique_docs(xlsx)}
    missing = [n for n in names if n not in by_name]
    if missing:
        typer.echo(f"not in the workbook: {missing}", err=True)
        raise typer.Exit(code=1)

    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    }
    typer.echo(f"re-searching {len(names)} name(s) — {len(names)} call(s)")
    with httpx.Client(timeout=15) as client:
        for name in names:
            doc = by_name[name]
            res = _search_and_cache(client, headers, doc, build_query(doc, overrides))
            typer.echo(f"  {name} → {_summarize(res)}")
            time.sleep(SECONDS_BETWEEN_CALLS)


@app.command()
def report(xlsx: Path = XLSX_OPTION) -> None:
    """Match-quality summary from cache only. Zero network calls."""
    counts = {
        "matched": 0,
        "low_confidence": 0,
        "unresolved": 0,
        "closed": 0,
        "uncached": 0,
    }
    review: list[str] = []
    for doc in _unique_docs(xlsx):
        res = resolution_from_cache(doc.source_name)
        if res is None:
            counts["uncached"] += 1
            continue
        counts[res["status"]] += 1
        if res["status"] in {"low_confidence", "unresolved"}:
            review.append(
                f"  {doc.source_name!r} → {res.get('maps_name')!r} "
                f"(score {res.get('score')}, {res.get('reason')}, {res['status']})"
            )
    typer.echo(f"totals: {counts}")
    if review:
        typer.echo("needs manual review:")
        for line in review:
            typer.echo(line)


if __name__ == "__main__":
    app()
