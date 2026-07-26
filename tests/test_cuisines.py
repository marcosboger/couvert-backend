"""The workbook spells cuisines both ways; one canonical label per cuisine."""

from core.cuisines import canonical_cuisine, canonical_cuisines


def test_feminine_variants_collapse_onto_the_catalog_label():
    """'Italiano' had 113 restaurants and 'Italiana' 2 — one cuisine, split in two."""
    assert canonical_cuisine("Italiana") == "Italiano"
    assert canonical_cuisine("Japonesa") == "Japonês"
    assert canonical_cuisine("Francesa") == "Francês"
    assert canonical_cuisine("Brasileira") == "Brasileiro"
    assert canonical_cuisine("Espanhola") == "Espanhol"
    assert canonical_cuisine("Vegetariana") == "Vegetariano"
    assert canonical_cuisine("Contemporânea") == "Contemporâneo"


def test_the_apps_chip_labels_resolve_even_without_a_workbook_twin():
    """preferences.fixture.ts uses these; the workbook only has the masculine form."""
    assert canonical_cuisine("Chinesa") == "Chinês"
    assert canonical_cuisine("Mexicana") == "Mexicano"
    assert canonical_cuisine("Peruana") == "Peruano"
    assert canonical_cuisine("Tailandesa") == "Tailandês"
    assert canonical_cuisine("Mediterrânea") == "Mediterrâneo"


def test_lookup_ignores_accents_case_and_padding():
    for variant in ("contemporanea", "CONTEMPORÂNEA", "  Contemporânea  ", "Contemporanea"):
        assert canonical_cuisine(variant) == "Contemporâneo"


def test_a_canonical_label_is_left_alone():
    assert canonical_cuisine("Italiano") == "Italiano"
    assert canonical_cuisine("Contemporâneo") == "Contemporâneo"


def test_an_uncatalogued_label_passes_through():
    """Unknown cuisines must still filter, not become empty."""
    assert canonical_cuisine("Carnes") == "Carnes"
    assert canonical_cuisine("Frutos do Mar") == "Frutos do Mar"


def test_a_list_is_canonicalised_and_deduped_in_order():
    assert canonical_cuisines(["Italiana", "Carnes", "Italiano", "Japonesa"]) == [
        "Italiano",
        "Carnes",
        "Japonês",
    ]


def test_blank_labels_are_dropped():
    assert canonical_cuisines(["", "  ", "Italiano"]) == ["Italiano"]
