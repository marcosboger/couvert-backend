"""Seed catalog must stay in lockstep with the frontend fixtures."""

from jobs.fixtures import make_restaurant_id, restaurant_docs


def test_make_restaurant_id_matches_frontend_algorithm():
    # Expected values derived from makeRestaurantId() in restaurants.fixture.ts
    assert make_restaurant_id("Spot — JK") == "spot-jk"
    assert make_restaurant_id("Casa Tucupi") == "casa-tucupi"
    assert make_restaurant_id("Notiê") == "noti"  # accents are non-[a-z0-9] → stripped at edge
    assert make_restaurant_id("Aizomê") == "aizom"
    assert make_restaurant_id("Cantina 1900") == "cantina-1900"
    assert make_restaurant_id("Spot — JK Iguatemi") == "spot-jk-iguatemi"
    assert make_restaurant_id("Sa Pa") == "sa-pa"


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
