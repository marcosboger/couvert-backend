"""Merge the Excel catalog with the Google Maps resolution, then upsert to Cosmos.

The three stages stay separate on purpose:
    ingest_excel        parse the curation workbook          (no network)
    resolve_google_maps resolve names → place_id, cached     (billed, capped)
    seed_restaurants    merge both and write to Cosmos       (this module)

Reads the Maps results straight from the on-disk cache, so re-seeding costs
nothing and never issues a Places call. Places the curation marked as closed are
left out of the catalog entirely.

São Paulo is the launch city; rows that resolve elsewhere are flagged `scope` and
kept, not deleted.

Usage:
    uv run python -m jobs.seed_restaurants preview          # counts only, no writes
    uv run python -m jobs.seed_restaurants merges           # dedupe decisions
    uv run python -m jobs.seed_restaurants flagged          # parked + unresolved rows
    uv run python -m jobs.seed_restaurants seed --dry-run   # show what would upsert
    uv run python -m jobs.seed_restaurants seed             # upsert into Cosmos
"""

import json
import re
from collections import Counter
from pathlib import Path

import typer

from core.config import get_settings
from core.models.restaurant import RestaurantDoc
from jobs.ingest_excel import DRY_RUN_OPTION, XLSX_OPTION, parse_workbook
from jobs.resolve_google_maps import resolution_from_cache, significant_tokens

app = typer.Typer(help="Excel + Maps → Cosmos restaurants")

# The city sits just before the two-letter state, separated by either a dash or a
# comma: "..., São Paulo - SP, 01123-030" and "..., Recife, PE, 50030-150".
_CITY_RE = re.compile(r"([^,\-]+?)\s*[-,]\s*([A-Z]{2}),")

# Resolutions good enough to carry Maps identity into the catalog.
TRUSTED_STATUSES = {"matched"}

# The launch city. Greater-SP towns are deliberately excluded — a separate call.
SAO_PAULO = "São Paulo"

# Unambiguous other-city place names. Needed because the search was biased to São
# Paulo, so 'Gero Rio' matched São Paulo's Gero: the resolved city says SP while
# the curated name says otherwise, and the name is the one to trust.
# Matched as whole words only — 'Empório' and 'Território' contain 'rio', and
# 'Aconchego Carioca' really is in São Paulo.
OTHER_CITY_TOKENS = {
    "botafogo", "brasilia", "copacabana", "curitiba", "florianopolis", "gloria",
    "horizonte", "ipanema", "leblon", "niteroi", "pampulha", "recife", "rio",
    "salvador", "savassi",
}


def city_from_address(address: str | None) -> str | None:
    match = _CITY_RE.search(address or "")
    return match.group(1).strip() if match else None


def scope_for(source_name: str, city: str | None) -> str:
    """'sp' | 'other_city' | 'unknown' — the curated name outranks the match."""
    if OTHER_CITY_TOKENS & set(significant_tokens(source_name)):
        return "other_city"
    if city is None:
        return "unknown"
    return "sp" if city == SAO_PAULO else "other_city"


def apply_resolution(doc: RestaurantDoc, res: dict | None) -> RestaurantDoc:
    """Stamp Maps identity onto a parsed doc. Coordinates and address only come
    along with a trusted match — a shaky guess must not look like known truth."""
    status = "uncached" if res is None else res["status"]
    identity: dict = {}
    city = None
    if res is not None and status in TRUSTED_STATUSES:
        city = city_from_address(res.get("address"))
        identity = {
            "place_id": res.get("place_id"),
            "maps_name": res.get("maps_name"),
            "maps_types": res.get("types", []),
            "address": res.get("address"),
            "city": city,
            "latitude": res.get("latitude"),
            "longitude": res.get("longitude"),
        }
    scope = scope_for(doc.source_name, city)
    if scope == "other_city" and city == SAO_PAULO:
        # The name says another city but the search — biased to São Paulo — found
        # a namesake here. That place belongs to the São Paulo restaurant, so
        # keeping it would merge two different venues into one.
        return doc.model_copy(update={"resolution_status": "wrong_city", "scope": scope})
    return doc.model_copy(update={"resolution_status": status, "scope": scope, **identity})


_UNION_LISTS = ("place_types", "occasions", "cuisines", "positionings", "specialties")


def _absorb(keeper: RestaurantDoc, other: RestaurantDoc) -> RestaurantDoc:
    """Fold a duplicate row into the surviving doc, losing no curated detail."""
    update: dict = {}
    for field in _UNION_LISTS:
        seen: dict[str, None] = {}
        for item in getattr(keeper, field) + getattr(other, field):
            seen.setdefault(item, None)
        update[field] = list(seen)
    for field in ("chef", "editorial_comment", "awards_mention"):
        if getattr(keeper, field) is None and getattr(other, field) is not None:
            update[field] = getattr(other, field)
    if not keeper.awards and other.awards:
        update["awards"] = other.awards
    update["merged_ids"] = [*keeper.merged_ids, other.id, *other.merged_ids]
    update["merged_names"] = [
        *keeper.merged_names,
        *({other.source_name, *other.merged_names} - {keeper.source_name}),
    ]
    return keeper.model_copy(update=update)


def dedupe_by_place(docs: list[RestaurantDoc]) -> tuple[list[RestaurantDoc], list[str]]:
    """One Google place = one restaurant. The earliest workbook row survives.

    Only trusted matches carry a place_id, so rejected and unresolved rows can
    never be merged together by accident.
    """
    by_key: dict[str, RestaurantDoc] = {}
    order: list[str] = []
    notes: list[str] = []
    for i, doc in enumerate(docs):
        # Unresolved rows stay separate: each gets a key nothing else can share.
        key = doc.place_id or f"row:{i}:{doc.id}"
        if key not in by_key:
            by_key[key] = doc
            order.append(key)
            continue
        by_key[key] = _absorb(by_key[key], doc)
        notes.append(
            f"merged {doc.source_name!r} ({doc.id}) into "
            f"{by_key[key].source_name!r} ({by_key[key].id}) — same place {doc.place_id}"
        )
    return [by_key[k] for k in order], notes


def build_catalog(xlsx: Path) -> tuple[list[RestaurantDoc], Counter, list[str]]:
    """Final docs to serve, a breakdown, and the merge decisions taken.

    Closed places are dropped; other-city rows are kept but flagged via `scope`.
    """
    docs, _ = parse_workbook(xlsx)
    resolved = [apply_resolution(d, resolution_from_cache(d.source_name)) for d in docs]
    counts: Counter = Counter()
    for doc in resolved:
        counts[doc.resolution_status] += 1
        counts[f"scope:{doc.scope}"] += 1
    live = [d for d in resolved if d.resolution_status != "closed"]
    catalog, notes = dedupe_by_place(live)
    return catalog, counts, notes


def _breakdown(catalog: list[RestaurantDoc]) -> str:
    sp = [d for d in catalog if d.scope == "sp"]
    return (
        f"{len(catalog)} docs — São Paulo {len(sp)}, "
        f"other city {sum(1 for d in catalog if d.scope == 'other_city')}, "
        f"unknown {sum(1 for d in catalog if d.scope == 'unknown')}"
    )


@app.command()
def preview(xlsx: Path = XLSX_OPTION) -> None:
    """Status breakdown and a sample doc. No writes, no network calls."""
    catalog, counts, notes = build_catalog(xlsx)
    typer.echo(f"catalog: {_breakdown(catalog)}")
    typer.echo(f"counts: {dict(counts)}")
    typer.echo(f"duplicate rows merged into another place: {len(notes)}")
    ready = [d for d in catalog if d.scope == "sp" and d.place_id]
    typer.echo(f"São Paulo docs with a Google place: {len(ready)}")
    typer.echo(f"  of those, with coordinates: {sum(1 for d in ready if d.latitude)}")
    typer.echo(json.dumps(ready[0].model_dump(), ensure_ascii=False, indent=1))


@app.command()
def merges(xlsx: Path = XLSX_OPTION) -> None:
    """Every dedupe decision taken. No writes, no network calls."""
    _, _, notes = build_catalog(xlsx)
    for note in notes:
        typer.echo(f"  {note}")
    typer.echo(f"{len(notes)} merge(s)")


@app.command()
def flagged(xlsx: Path = XLSX_OPTION) -> None:
    """Rows parked in another city, and rows whose city is still unknown.

    A doc only earns scope 'sp' by matching a São Paulo place, so everything
    still needing identity work lands in 'unknown'.
    """
    catalog, _, _ = build_catalog(xlsx)
    parked = [d for d in catalog if d.scope == "other_city"]
    typer.echo(f"--- another city, parked: {len(parked)}")
    for doc in sorted(parked, key=lambda d: (d.city or "~", d.source_name)):
        typer.echo(f"  {doc.source_name!r} → {doc.maps_name!r} | {doc.city}")
    todo = [d for d in catalog if d.scope == "unknown"]
    typer.echo(f"--- city unknown, needs identity: {len(todo)}")
    for doc in sorted(todo, key=lambda d: (d.resolution_status or "", d.source_name)):
        # Untrusted candidates are kept off the doc, so read them from the cache.
        res = resolution_from_cache(doc.source_name) or {}
        guess = ""
        if res.get("maps_name"):
            guess = f" → {res['maps_name']!r} (score {res.get('score')})"
        note = f" [{res['note']}]" if res.get("note") else ""
        typer.echo(f"  [{doc.resolution_status}] {doc.source_name!r}{guess}{note}")


@app.command()
def seed(
    xlsx: Path = XLSX_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Upsert the merged catalog into the Cosmos restaurants container."""
    catalog, counts, notes = build_catalog(xlsx)
    typer.echo(f"catalog: {_breakdown(catalog)}")
    typer.echo(f"counts: {dict(counts)}  merges: {len(notes)}")
    if dry_run:
        typer.echo(f"dry-run: would upsert {len(catalog)} docs")
        return

    from azure.cosmos import CosmosClient

    settings = get_settings()
    if not settings.cosmos_configured:
        typer.echo("COSMOS_ENDPOINT / COSMOS_KEY not set — configure .env first.", err=True)
        raise typer.Exit(code=1)
    client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
    container = client.get_database_client(settings.cosmos_database).get_container_client(
        settings.restaurants_container
    )
    for i, doc in enumerate(catalog, 1):
        container.upsert_item(doc.model_dump())
        if i % 100 == 0:
            typer.echo(f"  upserted {i}/{len(catalog)}")
    typer.echo(f"done — {len(catalog)} restaurants upserted.")


if __name__ == "__main__":
    app()
