"""Seed catalog must stay in lockstep with the frontend fixtures."""

from jobs.fixtures import make_restaurant_id, restaurant_docs


def test_make_restaurant_id_matches_frontend_algorithm():
    # Expected values derived from makeRestaurantId() in restaurants.fixture.ts
    assert make_restaurant_id("Spot — JK") == "spot-jk"
    assert make_restaurant_id("Casa Tucupi") == "casa-tucupi"
    assert make_restaurant_id("Cantina 1900") == "cantina-1900"
    assert make_restaurant_id("Spot — JK Iguatemi") == "spot-jk-iguatemi"
    assert make_restaurant_id("Sa Pa") == "sa-pa"


def test_make_restaurant_id_folds_accents_instead_of_dropping_them():
    """Both sides strip Unicode category Mn from the NFD form, so an accented
    letter keeps its base letter: 'Íz' is 'iz', never 'z'."""
    assert make_restaurant_id("Notiê") == "notie"
    assert make_restaurant_id("Aizomê") == "aizome"
    assert make_restaurant_id("Íz") == "iz"
    assert make_restaurant_id("Arábia") == "arabia"
    assert make_restaurant_id("Totò") == "toto"
    assert make_restaurant_id("Caledônia") == "caledonia"
    assert make_restaurant_id("Aiô") == "aio"
    assert make_restaurant_id("Jesuíno Brilhante") == "jesuino-brilhante"


def test_make_restaurant_id_folds_the_cedilla():
    assert make_restaurant_id("Açaí") == "acai"


def test_make_restaurant_id_still_collapses_other_punctuation():
    assert make_restaurant_id("De*Primeira") == "de-primeira"
    assert make_restaurant_id("Bocada’s") == "bocada-s"
    assert make_restaurant_id("  Fel.sp  ") == "fel-sp"


def test_catalog_size_and_unique_ids():
    docs = restaurant_docs()
    assert len(docs) == 25
    ids = [doc["id"] for doc in docs]
    assert len(ids) == len(set(ids))


def test_docs_have_required_fields():
    for doc in restaurant_docs():
        assert doc["id"] and doc["name"] and doc["cuisine"]
        assert doc["rating"] in (4, 5)
        assert doc["image_key"] in ("imgRestaurant", "imgCocktails")
