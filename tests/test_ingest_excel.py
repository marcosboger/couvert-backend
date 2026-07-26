from core.models.restaurant import RestaurantDoc
from jobs.ingest_excel import (
    dedupe,
    normalize_cuisines,
    parse_awards_mention,
    row_to_doc,
    split_multi,
)


def test_split_multi_dedupes_and_strips():
    assert split_multi("Happy Hour; Bom pra Date ; Happy Hour;") == [
        "Happy Hour",
        "Bom pra Date",
    ]
    assert split_multi(None) == []


def test_normalize_cuisines_maps_gender_variant():
    assert normalize_cuisines(["Contemporânea", "Italiano", "Contemporâneo"]) == [
        "Contemporâneo",
        "Italiano",
    ]


def test_parse_awards_mention_structured_entry():
    [m] = parse_awards_mention("12º Colocado | Melhor Bar - Prêmio Paladar 2025")
    assert m.placement == "12º Colocado"
    assert m.category == "Melhor Bar"
    assert m.award == "Prêmio Paladar 2025"
    assert m.year == 2025


def test_parse_awards_mention_without_category_separator():
    [m] = parse_awards_mention("88º Colocado | Exame – 100 Melhores do Brasil 2026")
    assert m.placement == "88º Colocado"
    assert m.category is None
    assert m.award == "Exame – 100 Melhores do Brasil 2026"
    assert m.year == 2026


def test_row_to_doc_maps_columns():
    row = (None, "1", "Guarita", "Bar", "Happy Hour; Com amigos", "Contemporâneo",
           "Coquetelaria", None, None, None, None)
    doc = row_to_doc(row)
    assert doc.id == "guarita"
    assert doc.place_types == ["Bar"]
    assert doc.occasions == ["Happy Hour", "Com amigos"]
    assert doc.cuisine == "Contemporâneo"


def _doc(**overrides) -> RestaurantDoc:
    base = dict(id="toto", name="Toto", source_name="Toto")
    base.update(overrides)
    return RestaurantDoc(**base)


def test_dedupe_merges_complementary_rows():
    a = _doc(chef=None, awards_mention="1º | X - Y 2025", cuisines=["Contemporâneo"])
    b = _doc(chef="Chef A", awards_mention=None, cuisines=["Padaria artesanal"])
    docs, notes = dedupe([a, b])
    assert len(docs) == 1
    assert docs[0].chef == "Chef A"
    assert docs[0].awards_mention == "1º | X - Y 2025"
    assert docs[0].cuisines == ["Contemporâneo", "Padaria artesanal"]
    assert any("merged" in n for n in notes)


def test_dedupe_keeps_conflicting_rows_distinct():
    a = _doc(awards_mention="Boa Cozinha | Guia Michelin 2024")
    b = _doc(awards_mention="88º Colocado | Exame 2026", chef="Thomas Troisgros")
    docs, notes = dedupe([a, b])
    assert {d.id for d in docs} == {"toto", "toto-2"}
    assert any("CONFLICT" in n for n in notes)
