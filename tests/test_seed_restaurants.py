from core.models.restaurant import RestaurantDoc
from jobs.seed_restaurants import (
    apply_resolution,
    city_from_address,
    dedupe_by_place,
    scope_for,
)

MATCHED = {
    "status": "matched",
    "place_id": "ChIJskye",
    "maps_name": "Skye",
    "address": "Av. Brigadeiro Luís Antônio, 4700 - Jardim Paulista, São Paulo - SP, 01402-002",
    "latitude": -23.5701,
    "longitude": -46.6531,
    "types": ["bar", "restaurant"],
}


def _doc() -> RestaurantDoc:
    return RestaurantDoc(id="skye", name="Skye", source_name="Hotel Unique Sky Bar")


def test_city_parsed_from_a_brazilian_formatted_address():
    assert city_from_address(MATCHED["address"]) == "São Paulo"


def test_city_parsed_when_a_comma_precedes_the_state():
    """Not every Google address uses a dash: '..., Recife, PE, 50030-150'."""
    assert city_from_address("Av. Alfredo Lisboa, 04 - Recife, PE, 50030-150, Brazil") == "Recife"
    assert city_from_address("BA-142 - Mucugê, BA, 46750-000, Brazil") == "Mucugê"


def test_city_is_none_when_the_address_has_no_state():
    assert city_from_address("somewhere") is None
    assert city_from_address(None) is None


def test_matched_resolution_populates_identity_and_location():
    doc = apply_resolution(_doc(), MATCHED)
    assert doc.resolution_status == "matched"
    assert doc.place_id == "ChIJskye"
    assert doc.maps_name == "Skye"
    assert doc.maps_types == ["bar", "restaurant"]
    assert doc.city == "São Paulo"
    assert doc.latitude == -23.5701


def test_low_confidence_resolution_records_status_but_no_location():
    """A shaky guess must not masquerade as known truth."""
    doc = apply_resolution(_doc(), {**MATCHED, "status": "low_confidence"})
    assert doc.resolution_status == "low_confidence"
    assert doc.place_id is None
    assert doc.address is None
    assert doc.latitude is None


def test_closed_resolution_is_flagged_for_the_caller_to_drop():
    doc = apply_resolution(_doc(), {"status": "closed", "note": "fechado"})
    assert doc.resolution_status == "closed"
    assert doc.place_id is None


def test_never_queried_name_is_marked_uncached():
    doc = apply_resolution(_doc(), None)
    assert doc.resolution_status == "uncached"
    assert doc.place_id is None


def test_a_rio_name_matching_a_sao_paulo_place_keeps_no_identity():
    """Otherwise 'Gero Rio' and 'GERO' would collapse into one restaurant."""
    doc = RestaurantDoc(id="gero-rio", name="Gero Rio", source_name="Gero Rio")
    resolved = apply_resolution(doc, {**MATCHED, "maps_name": "Gero Restaurant"})
    assert resolved.resolution_status == "wrong_city"
    assert resolved.scope == "other_city"
    assert resolved.place_id is None


def test_a_rio_name_matching_a_rio_place_keeps_its_identity():
    doc = RestaurantDoc(id="sushi-leblon", name="Sushi Leblon", source_name="Sushi Leblon")
    address = "Rua Dias Ferreira, 256 - Leblon, Rio de Janeiro - RJ, 22431-050"
    resolved = apply_resolution(doc, {**MATCHED, "address": address})
    assert resolved.resolution_status == "matched"
    assert resolved.scope == "other_city"
    assert resolved.city == "Rio de Janeiro"
    assert resolved.place_id == "ChIJskye"


def test_scope_follows_the_resolved_city():
    assert scope_for("Guarita", "São Paulo") == "sp"
    assert scope_for("Sushi Leblon", "Rio de Janeiro") == "other_city"
    assert scope_for("Tiara", None) == "unknown"


def test_scope_trusts_the_curated_name_over_a_sao_paulo_match():
    """'Gero Rio' matched São Paulo's Gero — the name is the honest signal."""
    assert scope_for("Gero Rio", "São Paulo") == "other_city"
    assert scope_for("Rubaiyat Rio", "São Paulo") == "other_city"


def test_scope_does_not_read_city_names_inside_other_words():
    """'Empório' and 'Território' contain 'rio'; Aconchego Carioca is in SP."""
    assert scope_for("Empório Jardim", "São Paulo") == "sp"
    assert scope_for("Território Ristorante", "São Paulo") == "sp"
    assert scope_for("Aconchego Carioca", "São Paulo") == "sp"


def _row(id_: str, name: str, place_id: str | None, **extra) -> RestaurantDoc:
    return RestaurantDoc(id=id_, name=name, source_name=name, place_id=place_id, **extra)


def test_rows_sharing_a_place_merge_into_the_first_one():
    docs, notes = dedupe_by_place(
        [
            _row("arabia", "Arabia", "place-1", cuisines=["Árabe"]),
            _row("ar-bia", "Arábia", "place-1", chef="Chef A", occasions=["Jantar"]),
        ]
    )
    assert len(docs) == 1
    keeper = docs[0]
    assert keeper.id == "arabia"
    assert keeper.chef == "Chef A"
    assert keeper.cuisines == ["Árabe"]
    assert keeper.occasions == ["Jantar"]
    assert keeper.merged_ids == ["ar-bia"]
    assert keeper.merged_names == ["Arábia"]
    assert len(notes) == 1


def test_rows_without_a_place_are_never_merged_together():
    """Two unresolved rows are not evidence of being the same restaurant."""
    docs, notes = dedupe_by_place(
        [_row("tiara", "Tiara", None), _row("didier", "Didier", None)]
    )
    assert len(docs) == 2
    assert notes == []


def test_distinct_places_are_left_alone():
    docs, _ = dedupe_by_place(
        [_row("a", "A", "place-1"), _row("b", "B", "place-2")]
    )
    assert len(docs) == 2
