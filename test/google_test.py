#!/usr/bin/python3
# -.- coding: utf-8 -.-

"""
Geocoder Google Provider Tests
"""

from test.helpers import FakeResponse, assert_white_house

import pytest

from src import google
from src.api import LEGAL_LAND_NOTE, NO_ADDRESS_NOTE, PROVIDERS, SourceRecord, cache_key
from src.cache import Cache


def _result(location_type, components, **overrides):
    """Builds a minimal Google result body for a single-address response."""
    match = {
        "place_id": "PLACE",
        "partial_match": False,
        "geometry": {"location": {"lat": 38.898754, "lng": -77.03535}, "location_type": location_type},
        "address_components": components,
        "types": ["street_address"],
    }
    match.update(overrides)
    return {"status": "OK", "results": [match]}


ROOFTOP_COMPONENTS = [
    {"short_name": "1600", "types": ["street_number"]},
    {"short_name": "Pennsylvania Ave NW", "types": ["route"]},
    {"short_name": "Washington", "types": ["locality"]},
    {"short_name": "DC", "types": ["administrative_area_level_1"]},
    {"short_name": "20500", "types": ["postal_code"]},
    {"short_name": "US", "types": ["country"]},
]

CITY_COMPONENTS = [
    {"short_name": "Pendleton", "types": ["locality"]},
    {"short_name": "SC", "types": ["administrative_area_level_1"]},
    {"short_name": "US", "types": ["country"]},
]

PROVINCE_COMPONENTS = [
    {"short_name": "AB", "types": ["administrative_area_level_1", "political"]},
    {"short_name": "CA", "types": ["country", "political"]},
]

MEXICO_COMPONENTS = [
    {"short_name": "76", "types": ["street_number"]},
    {"short_name": "C. 49", "types": ["route"]},
    {"short_name": "Santa Margarita", "types": ["sublocality_level_1", "sublocality", "political"]},
    {"short_name": "Cdad. del Carmen", "types": ["locality", "political"]},
    {"short_name": "Camp.", "types": ["administrative_area_level_1", "political"]},
    {"short_name": "24120", "types": ["postal_code"]},
    {"short_name": "MX", "types": ["country", "political"]},
]

MEXICO_SUBPREMISE_COMPONENTS = [
    {"short_name": "17", "types": ["subpremise"]},
    {"short_name": "7", "types": ["street_number"]},
    {"short_name": "Gral. Pedro Hinojosa", "types": ["route"]},
    {"short_name": "Cd Industrial", "types": ["sublocality_level_1", "sublocality", "political"]},
    {"short_name": "Heroica Matamoros", "types": ["locality", "political"]},
    {"short_name": "Tamps.", "types": ["administrative_area_level_1", "political"]},
    {"short_name": "87499", "types": ["postal_code"]},
    {"short_name": "MX", "types": ["country", "political"]},
]


def _patch_response(monkeypatch, payload, captured=None):
    """Routes requests.get to a canned payload, optionally capturing the call args."""

    def fake_get(url, params=None, timeout=None):
        if captured is not None:
            captured.update(url=url, params=params, timeout=timeout)
        return FakeResponse(payload)

    monkeypatch.setattr(google.requests, "get", fake_get)


def test_google_registered():
    """@register("google") wires GoogleProvider into the registry."""
    assert PROVIDERS["google"] is google.GoogleProvider


def test_google_requires_key():
    """Google is a keyed provider so the CLI enforces an API key."""
    assert google.GoogleProvider.requires_key is True


def test_google_parses_rooftop(monkeypatch):
    """A rooftop match keeps its street address and grades to full accuracy."""
    captured = {}
    _patch_response(monkeypatch, _result("ROOFTOP", ROOFTOP_COMPONENTS), captured)

    record = SourceRecord(internal_key=0, address="1600 Pennsylvania Ave NW", city="Washington", stateprov="DC", postalcode="20500")
    result = google.GoogleProvider("key").geocode([record])[0]

    assert captured["url"] == google.GoogleProvider.ENDPOINT
    assert captured["params"]["key"] == "key"
    assert captured["params"]["address"] == record.address_string()
    assert result.match_type == "exact"
    assert result.location_type == "ROOFTOP"
    assert_white_house(result)
    assert result.result_id == "PLACE"
    assert result.accuracy == 100


def test_google_caps_interpolated_below_rooftop(monkeypatch):
    """An interpolated match echoes a street address but is capped at block level."""
    _patch_response(monkeypatch, _result("RANGE_INTERPOLATED", ROOFTOP_COMPONENTS))

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="1024 Chester Rd")])[0]

    assert result.result_address == "1600 Pennsylvania Ave NW"
    assert result.accuracy == 80


def test_google_caps_approximate_at_city(monkeypatch):
    """An approximate centroid drops the missing street address and grades to city."""
    _patch_response(monkeypatch, _result("APPROXIMATE", CITY_COMPONENTS))

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="PO Box 1019", city="Pendleton", stateprov="SC")])[0]

    assert result.result_address == ""
    assert result.result_city == "Pendleton"
    assert result.accuracy == 40


def test_google_route_without_number_keeps_street_name(monkeypatch):
    """A route without a street number is still returned, graded down to street level."""
    components = [component for component in ROOFTOP_COMPONENTS if component["types"] != ["street_number"]]
    _patch_response(monkeypatch, _result("GEOMETRIC_CENTER", components))

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="Stornoway St")])[0]

    assert result.result_address == "Pennsylvania Ave NW"
    assert result.accuracy == 70


def test_google_caps_numberless_rooftop_at_street(monkeypatch):
    """A rooftop location_type cannot outrank street level without a street number."""
    components = [component for component in ROOFTOP_COMPONENTS if component["types"] != ["street_number"]]
    _patch_response(monkeypatch, _result("ROOFTOP", components))

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="Stornoway St")])[0]

    assert result.accuracy == 70


def test_google_mexican_address_orders_number_after_route(monkeypatch):
    """A Mexican address trails the street number and carries its sublocality."""
    _patch_response(monkeypatch, _result("ROOFTOP", MEXICO_COMPONENTS))

    record = SourceRecord(internal_key=0, address="76 Calle 49", city="Ciudad Del Carmen", stateprov="Campeche", postalcode="24166")
    result = google.GoogleProvider("key").geocode([record])[0]

    assert result.result_address == "C. 49 76, Santa Margarita"
    assert result.result_city == "Cdad. del Carmen"
    assert result.result_stateprov == "Camp."
    assert result.result_postalcode == "24120"
    assert result.accuracy == 100


def test_google_mexican_address_hyphenates_subpremise(monkeypatch):
    """A Mexican subpremise is hyphenated onto the street number."""
    _patch_response(monkeypatch, _result("ROOFTOP", MEXICO_SUBPREMISE_COMPONENTS))

    record = SourceRecord(internal_key=0, address="Calle Poniente 2 Pedro Hinojosa Y Norte 7, 17", city="Heroica Matamoros", stateprov="Tamaulipas")
    result = google.GoogleProvider("key").geocode([record])[0]

    assert result.result_address == "Gral. Pedro Hinojosa 7-17, Cd Industrial"
    assert result.result_city == "Heroica Matamoros"
    assert result.result_stateprov == "Tamps."


def test_google_mexican_route_without_number_keeps_sublocality(monkeypatch):
    """A Mexican route with no street number still carries its sublocality."""
    components = [component for component in MEXICO_COMPONENTS if component["types"] != ["street_number"]]
    _patch_response(monkeypatch, _result("GEOMETRIC_CENTER", components))

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="Calle Mike Allen")])[0]

    assert result.result_address == "C. 49, Santa Margarita"
    assert result.accuracy == 70


def test_google_prefers_named_sublocality_over_numeric_code(monkeypatch):
    """A numeric sublocality_level_3 never displaces the colonia in sublocality_level_1."""
    components = [{"short_name": "015", "types": ["political", "sublocality", "sublocality_level_3"]}] + MEXICO_COMPONENTS
    _patch_response(monkeypatch, _result("ROOFTOP", components))

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="76 Calle 49")])[0]

    assert result.result_address == "C. 49 76, Santa Margarita"


def test_google_sublocality_stays_out_of_us_address(monkeypatch):
    """A U.S. address leads with its street number and omits any sublocality."""
    components = ROOFTOP_COMPONENTS + [{"short_name": "Brooklyn", "types": ["sublocality_level_1", "sublocality", "political"]}]
    _patch_response(monkeypatch, _result("ROOFTOP", components))

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="1600 Pennsylvania Ave NW")])[0]

    assert result.result_address == "1600 Pennsylvania Ave NW"


def test_google_flags_partial_match(monkeypatch):
    """The partial_match flag is surfaced as a partial match_type."""
    _patch_response(monkeypatch, _result("ROOFTOP", ROOFTOP_COMPONENTS, partial_match=True))

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="109 SEAPINE Ln")])[0]

    assert result.match_type == "partial"


def test_google_zero_results_is_no_match(monkeypatch):
    """A ZERO_RESULTS status yields a no-match result rather than an error."""
    _patch_response(monkeypatch, {"status": "ZERO_RESULTS", "results": []})

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="Nowhere St")])[0]

    assert result.match_type == "no_match"
    assert result.accuracy == 0
    assert result.match_notes == "No match"


def test_google_raises_on_error_status(monkeypatch):
    """A REQUEST_DENIED status fails loudly instead of masking a misconfiguration."""
    _patch_response(monkeypatch, {"status": "REQUEST_DENIED", "error_message": "The provided API key is invalid."})

    with pytest.raises(ValueError):
        google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="1 Main St")])


def test_google_raw_is_the_whole_response(monkeypatch):
    """The stored raw value is the full envelope, not just the match read from it."""
    _patch_response(monkeypatch, _result("ROOFTOP", ROOFTOP_COMPONENTS))

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="1600 Pennsylvania Ave NW")])[0]

    assert result.raw["status"] == "OK"
    assert result.raw["results"][0]["place_id"] == "PLACE"


def test_google_requests_each_distinct_address_once(monkeypatch):
    """Records sharing an address cost one request and all receive the result."""
    requested = []

    def fake_get(_url, params=None, **_kwargs):
        requested.append(params["address"])
        return FakeResponse(_result("ROOFTOP", ROOFTOP_COMPONENTS))

    monkeypatch.setattr(google.requests, "get", fake_get)

    records = [
        SourceRecord(internal_key=0, address="1 Main St", city="Town", stateprov="CA"),
        SourceRecord(internal_key=1, address="1  MAIN  ST", city="Town", stateprov="CA"),
        SourceRecord(internal_key=2, address="2 Oak St", city="Town", stateprov="CA"),
    ]
    results = google.GoogleProvider("key").geocode(records)

    assert len(requested) == 2
    assert len(results) == 3
    assert all(result.accuracy == 100 for result in results)


def test_google_error_status_is_never_cached(monkeypatch, tmp_path):
    """A failed request leaves nothing behind, so a later run retries it."""
    path = str(tmp_path / "cache.sqlite")
    version = google.GoogleProvider.CACHE_VERSION
    _patch_response(monkeypatch, {"status": "OVER_QUERY_LIMIT", "error_message": "quota exceeded"})

    record = SourceRecord(internal_key=0, address="1 Main St")
    with Cache("google", version, path) as cache:
        with pytest.raises(ValueError):
            google.GoogleProvider("key", cache).geocode([record])

    with Cache("google", version, path) as cache:
        assert not cache.lookup([cache_key(record)])


def test_google_withholds_legal_land_description(monkeypatch):
    """A rig row asks Google only for its province and is capped there."""
    captured = {}
    _patch_response(monkeypatch, _result("APPROXIMATE", PROVINCE_COMPONENTS), captured)

    record = SourceRecord(internal_key=0, address="02-16-066-15w5", stateprov="Alberta", country="Canada")
    result = google.GoogleProvider("key").geocode([record])[0]

    assert captured["params"]["address"] == "Alberta, Canada"
    assert result.result_stateprov == "AB"
    assert result.accuracy == 20


def test_google_caps_legal_land_description_at_the_province(monkeypatch):
    """A street-level answer for a rig row is still capped at the province."""
    _patch_response(monkeypatch, _result("ROOFTOP", ROOFTOP_COMPONENTS))

    record = SourceRecord(internal_key=0, address="01-17-040-06w4", city="02-16-066-15w5", stateprov="Alberta")
    result = google.GoogleProvider("key").geocode([record])[0]

    assert result.accuracy == 20
    assert result.match_notes == LEGAL_LAND_NOTE


def test_google_skips_a_row_left_with_no_address(monkeypatch):
    """A row that is nothing but a grid reference is never sent to Google."""

    def fake_get(*args, **kwargs):
        raise AssertionError("Google was queried for a row left with no address")

    monkeypatch.setattr(google.requests, "get", fake_get)

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="01-17-040-06w4")])[0]

    assert result.match_type == "no_match"
    assert result.accuracy == 0
    assert result.match_notes == f"{NO_ADDRESS_NOTE}; {LEGAL_LAND_NOTE}"
