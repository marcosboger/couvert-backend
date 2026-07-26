import json

from core.models.restaurant import RestaurantDoc
from jobs import resolve_google_maps as rgm


def _doc(name: str, place_types: list[str] | None = None) -> RestaurantDoc:
    return RestaurantDoc(
        id=name.lower(), name=name, source_name=name, place_types=place_types or []
    )


def test_significant_tokens_drops_generic_words():
    assert rgm.significant_tokens("Seen São Paulo") == ["seen"]
    assert rgm.significant_tokens("Shiro Japanese cocktail bar") == ["shiro", "japanese"]


def test_significant_tokens_keeps_all_when_every_word_is_generic():
    assert rgm.significant_tokens("The Bar") == ["the", "bar"]


def test_match_score_accepts_maps_appended_descriptor():
    """Maps routinely returns a longer name for the same venue."""
    score, reason = rgm.match_score("Shiro", "Shiro Japanese cocktail bar")
    assert reason == "contained"
    assert score >= rgm.MATCH_THRESHOLD


def test_match_score_accepts_curated_name_with_city_suffix():
    score, _ = rgm.match_score("Seen São Paulo", "Seen - Restaurant & Bar")
    assert score >= rgm.MATCH_THRESHOLD


def test_match_score_ignores_word_spacing():
    score, reason = rgm.match_score("Mamma San", "Restaurante Mammasan")
    assert reason == "same letters"
    assert score >= rgm.MATCH_THRESHOLD


def test_match_score_accepts_a_three_letter_name():
    """'Aiô' and 'Roi' are real names, not initials."""
    assert rgm.match_score("Aiô", "AIÔ restaurante")[0] >= rgm.MATCH_THRESHOLD
    assert rgm.match_score("Roi", "Roi Méditerranée")[0] >= rgm.MATCH_THRESHOLD


def test_match_score_rejects_a_near_miss_short_name():
    """'Bai' is not 'Baio' — one letter is the whole identity at this length."""
    score, reason = rgm.match_score("Bai", "Baio Cozinha Sulista")
    assert reason == "fuzzy"
    assert score < rgm.MATCH_THRESHOLD


def test_match_score_rejects_unrelated_venue():
    score, reason = rgm.match_score("Bottega 21", "APERITIVO BAR")
    assert reason == "fuzzy"
    assert score < rgm.MATCH_THRESHOLD


def test_match_score_ignores_containment_of_a_too_short_name():
    """'S' inside anything is not evidence of identity."""
    score, reason = rgm.match_score("The S.", "Sushi Leblon")
    assert reason == "fuzzy"
    assert score < rgm.MATCH_THRESHOLD


def test_build_query_appends_curated_place_type():
    assert rgm.build_query(_doc("Guarita", ["Bar"])) == "Guarita Bar, São Paulo"


def test_build_query_skips_place_type_already_in_the_name():
    assert rgm.build_query(_doc("Balsa Bar", ["Bar"])) == "Balsa Bar, São Paulo"


def test_build_query_prefers_a_pinned_override():
    overrides = {"Bottega 21": {"query": "Bottega 21 Pizzaria, São Paulo"}}
    assert rgm.build_query(_doc("Bottega 21", ["Bar"]), overrides) == (
        "Bottega 21 Pizzaria, São Paulo"
    )


def test_closed_override_wins_over_a_cached_match(tmp_path, monkeypatch):
    monkeypatch.setattr(rgm, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(rgm, "OVERRIDES_PATH", tmp_path / "overrides.json")
    rgm.CACHE_DIR.mkdir()
    rgm.cache_path("Bottega 21").write_text(
        json.dumps(
            {
                "query": "irrelevant",
                "response": {
                    "places": [
                        {
                            "id": "wrong-place",
                            "displayName": {"text": "Bottega 21"},
                            "types": ["bar", "establishment"],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    assert rgm.resolution_from_cache("Bottega 21")["status"] == "matched"

    rgm.save_overrides({"Bottega 21": {"status": "closed", "note": "fechado"}})
    res = rgm.resolution_from_cache("Bottega 21")
    assert res == {"status": "closed", "note": "fechado"}


def _write_cache(name: str, places: list[dict]) -> None:
    rgm.cache_path(name).write_text(
        json.dumps({"query": "q", "response": {"places": places}}), encoding="utf-8"
    )


def test_confirmed_place_id_overrides_a_low_score(tmp_path, monkeypatch):
    """'Hotel Unique Sky Bar' → 'Skye' is right, but no scorer can know that."""
    monkeypatch.setattr(rgm, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(rgm, "OVERRIDES_PATH", tmp_path / "overrides.json")
    rgm.CACHE_DIR.mkdir()
    _write_cache(
        "Hotel Unique Sky Bar",
        [{"id": "skye", "displayName": {"text": "Skye"}, "types": ["bar"]}],
    )
    assert rgm.resolution_from_cache("Hotel Unique Sky Bar")["status"] == "low_confidence"

    rgm.save_overrides({"Hotel Unique Sky Bar": {"confirmed_place_id": "skye"}})
    res = rgm.resolution_from_cache("Hotel Unique Sky Bar")
    assert res["status"] == "matched"
    assert res["reason"] == "confirmed"
    assert res["place_id"] == "skye"


def test_confirmation_resurfaces_when_the_cache_no_longer_returns_that_place(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(rgm, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(rgm, "OVERRIDES_PATH", tmp_path / "overrides.json")
    rgm.CACHE_DIR.mkdir()
    _write_cache(
        "Hotel Unique Sky Bar",
        [{"id": "something-else", "displayName": {"text": "Skye"}, "types": ["bar"]}],
    )
    rgm.save_overrides({"Hotel Unique Sky Bar": {"confirmed_place_id": "skye"}})
    res = rgm.resolution_from_cache("Hotel Unique Sky Bar")
    assert res["status"] == "low_confidence"
    assert "no longer returned" in res["reason"]


def test_geographic_results_are_never_matched(tmp_path, monkeypatch):
    monkeypatch.setattr(rgm, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(rgm, "OVERRIDES_PATH", tmp_path / "overrides.json")
    rgm.CACHE_DIR.mkdir()
    rgm.cache_path("Guarita").write_text(
        json.dumps(
            {
                "query": "Guarita, São Paulo",
                "response": {
                    "places": [
                        {
                            "id": "street",
                            "displayName": {"text": "Rua Guariata"},
                            "types": ["route"],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    assert rgm.resolution_from_cache("Guarita") == {"status": "unresolved"}
