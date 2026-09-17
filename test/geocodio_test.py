#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder Geocodio Provider Tests

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

from test.helpers import FakeResponse, assert_white_house

import pytest

from src import geocodio
from src.api import LEGAL_LAND_NOTE, NO_ADDRESS_NOTE, PROVIDERS, SourceRecord


def _candidate(accuracy_type, components, **overrides):
    """Builds a single Geocodio result candidate."""
    candidate = {
        "formatted_address": "candidate",
        "location": {"lat": 38.898754, "lng": -77.03535},
        "accuracy": 1,
        "accuracy_type": accuracy_type,
        "source": "City of Washington",
        "address_components": components,
    }
    candidate.update(overrides)
    return candidate


def _batch(*candidate_lists):
    """Wraps ordered per-record candidate lists in the Geocodio batch envelope."""
    return {"results": [{"response": {"results": candidates}} for candidates in candidate_lists]}


ROOFTOP_COMPONENTS = {
    "number": "1600",
    "formatted_street": "Pennsylvania Ave NW",
    "city": "Washington",
    "state": "DC",
    "zip": "20500",
    "country": "US",
}

PLACE_COMPONENTS = {
    "city": "Pendleton",
    "state": "SC",
    "country": "US",
}

PROVINCE_COMPONENTS = {
    "state": "AB",
    "country": "CA",
}

MEXICO_COMPONENTS = {
    "number": "489",
    "street": "Avenida Paseo De La Reforma",
    "formatted_street": "Avenida Paseo De La Reforma",
    "city": "Ciudad De Mexico",
    "state": "CMX",
    "zip": "06500",
    "country": "MX",
}

MEXICO_SUBPREMISE_COMPONENTS = {
    "number": "7",
    "street": "Gral. Pedro Hinojosa",
    "secondarynumber": "17",
    "formatted_street": "Gral. Pedro Hinojosa",
    "city": "Heroica Matamoros",
    "state": "TAM",
    "zip": "87499",
    "country": "MX",
}


def _patch_response(monkeypatch, payload, captured=None):
    """Routes requests.post to a canned payload, optionally capturing the call args."""

    def fake_post(url, params=None, json=None, timeout=None):
        if captured is not None:
            captured.update(url=url, params=params, json=json, timeout=timeout)
        return FakeResponse(payload)

    monkeypatch.setattr(geocodio.requests, "post", fake_post)


def test_geocodio_registered():
    """@register("geocodio") wires GeocodioProvider into the registry."""
    assert PROVIDERS["geocodio"] is geocodio.GeocodioProvider


def test_geocodio_requires_key():
    """Geocodio is a keyed provider so the CLI enforces an API key."""
    assert geocodio.GeocodioProvider.requires_key is True


def test_geocodio_parses_rooftop(monkeypatch):
    """A rooftop match keeps its street address and grades to full accuracy."""
    captured = {}
    _patch_response(monkeypatch, _batch([_candidate("rooftop", ROOFTOP_COMPONENTS)]), captured)

    record = SourceRecord(internal_key=0, address="1600 Pennsylvania Ave NW", city="Washington", stateprov="DC", postalcode="20500")
    result = geocodio.GeocodioProvider("key").geocode([record])[0]

    assert captured["url"] == geocodio.GeocodioProvider.ENDPOINT
    assert captured["params"]["api_key"] == "key"
    assert captured["json"] == [record.address_string()]
    assert result.match_type == "exact"
    assert result.location_type == "rooftop"
    assert_white_house(result)
    assert result.accuracy == 100


def test_geocodio_caps_interpolated_below_rooftop(monkeypatch):
    """An interpolated match echoes a street address but is capped at block level."""
    _patch_response(monkeypatch, _batch([_candidate("range_interpolation", ROOFTOP_COMPONENTS)]))

    result = geocodio.GeocodioProvider("key").geocode([SourceRecord(internal_key=0, address="1024 Chester Rd")])[0]

    assert result.match_type == "non-exact"
    assert result.result_address == "1600 Pennsylvania Ave NW"
    assert result.accuracy == 80


def test_geocodio_caps_place_at_city(monkeypatch):
    """A place centroid drops the missing street address and grades to city."""
    _patch_response(monkeypatch, _batch([_candidate("place", PLACE_COMPONENTS)]))

    result = geocodio.GeocodioProvider("key").geocode([SourceRecord(internal_key=0, address="PO Box 1019", city="Pendleton", stateprov="SC")])[0]

    assert result.result_address == ""
    assert result.result_city == "Pendleton"
    assert result.accuracy == 40


def test_geocodio_street_without_number_keeps_street_name(monkeypatch):
    """A street without a house number is still returned, graded down to street level."""
    components = {key: value for key, value in ROOFTOP_COMPONENTS.items() if key != "number"}
    _patch_response(monkeypatch, _batch([_candidate("street_center", components)]))

    result = geocodio.GeocodioProvider("key").geocode([SourceRecord(internal_key=0, address="Stornoway St")])[0]

    assert result.result_address == "Pennsylvania Ave NW"
    assert result.accuracy == 70


def test_geocodio_caps_numberless_rooftop_at_street(monkeypatch):
    """A rooftop accuracy_type cannot outrank street level without a house number."""
    components = {key: value for key, value in ROOFTOP_COMPONENTS.items() if key != "number"}
    _patch_response(monkeypatch, _batch([_candidate("rooftop", components)]))

    result = geocodio.GeocodioProvider("key").geocode([SourceRecord(internal_key=0, address="Stornoway St")])[0]

    assert result.accuracy == 70


def test_geocodio_mexican_address_trails_the_house_number(monkeypatch):
    """A Mexican street line carries the house number after the street."""
    _patch_response(monkeypatch, _batch([_candidate("rooftop", MEXICO_COMPONENTS)]))

    record = SourceRecord(internal_key=0, address="Avenida Paseo De La Reforma 489", city="Ciudad De Mexico", stateprov="CMX", country="Mexico")
    result = geocodio.GeocodioProvider("key").geocode([record])[0]

    assert result.result_address == "Avenida Paseo De La Reforma 489"
    assert result.result_city == "Ciudad De Mexico"
    assert result.result_stateprov == "CMX"
    assert result.result_country == "MX"
    assert result.accuracy == 100


def test_geocodio_mexican_address_hyphenates_subpremise(monkeypatch):
    """A Mexican subpremise is hyphenated onto the house number that follows the street."""
    _patch_response(monkeypatch, _batch([_candidate("rooftop", MEXICO_SUBPREMISE_COMPONENTS)]))

    record = SourceRecord(internal_key=0, address="Calle Poniente 2 Pedro Hinojosa Y Norte 7, 17", city="Heroica Matamoros", stateprov="Tamaulipas")
    result = geocodio.GeocodioProvider("key").geocode([record])[0]

    assert result.result_address == "Gral. Pedro Hinojosa 7-17"
    assert result.result_city == "Heroica Matamoros"
    assert result.result_stateprov == "TAM"


def test_geocodio_mexican_street_without_number_keeps_the_street(monkeypatch):
    """A Mexican street with no house number returns the street alone, graded down to street level."""
    components = {key: value for key, value in MEXICO_COMPONENTS.items() if key != "number"}
    _patch_response(monkeypatch, _batch([_candidate("street_center", components)]))

    result = geocodio.GeocodioProvider("key").geocode([SourceRecord(internal_key=0, address="Avenida Paseo De La Reforma")])[0]

    assert result.result_address == "Avenida Paseo De La Reforma"
    assert result.accuracy == 70


def test_geocodio_ignores_us_ordered_address_lines(monkeypatch):
    """Geocodio writes address_lines house number first for every country, so they are not used."""
    candidate = _candidate("rooftop", MEXICO_COMPONENTS, address_lines=["489 Avenida Paseo De La Reforma", "", "06500 Ciudad De Mexico, CMX"])
    _patch_response(monkeypatch, _batch([candidate]))

    result = geocodio.GeocodioProvider("key").geocode([SourceRecord(internal_key=0, address="Reforma 489")])[0]

    assert result.result_address == "Avenida Paseo De La Reforma 489"


def test_geocodio_empty_candidates_is_no_match(monkeypatch):
    """An entry with no candidates yields a no-match result rather than an error."""
    _patch_response(monkeypatch, _batch([]))

    result = geocodio.GeocodioProvider("key").geocode([SourceRecord(internal_key=0, address="Nowhere St")])[0]

    assert result.match_type == "no_match"
    assert result.accuracy == 0
    assert result.match_notes == "No match"


def test_geocodio_aligns_entries_by_position(monkeypatch):
    """Ordered response entries are matched back to records by position."""
    payload = _batch(
        [_candidate("rooftop", ROOFTOP_COMPONENTS)],
        [],
        [_candidate("place", PLACE_COMPONENTS)],
    )
    _patch_response(monkeypatch, payload)

    records = [
        SourceRecord(internal_key=0, address="1600 Pennsylvania Ave NW"),
        SourceRecord(internal_key=1, address="Nowhere St"),
        SourceRecord(internal_key=2, address="Pendleton, SC"),
    ]
    results = geocodio.GeocodioProvider("key").geocode(records)

    assert results[0].location_type == "rooftop"
    assert results[0].accuracy == 100
    assert results[1].match_type == "no_match"
    assert results[1].match_notes == "No match"
    assert results[2].location_type == "place"
    assert results[2].accuracy == 40


def test_geocodio_raises_on_entry_count_mismatch(monkeypatch):
    """A response short of one entry per record fails loudly instead of misaligning."""
    _patch_response(monkeypatch, _batch([_candidate("rooftop", ROOFTOP_COMPONENTS)]))

    records = [
        SourceRecord(internal_key=0, address="1600 Pennsylvania Ave NW"),
        SourceRecord(internal_key=1, address="Nowhere St"),
    ]
    with pytest.raises(ValueError):
        geocodio.GeocodioProvider("key").geocode(records)


def test_geocodio_withholds_legal_land_description(monkeypatch):
    """A rig row asks Geocodio only for its province and is capped there."""
    captured = {}
    _patch_response(monkeypatch, _batch([_candidate("state", PROVINCE_COMPONENTS)]), captured)

    record = SourceRecord(internal_key=0, address="02-16-066-15w5", stateprov="Alberta", country="Canada")
    result = geocodio.GeocodioProvider("key").geocode([record])[0]

    assert captured["json"] == ["Alberta, Canada"]
    assert result.result_stateprov == "AB"
    assert result.accuracy == 20


def test_geocodio_caps_legal_land_description_at_the_province(monkeypatch):
    """A rooftop answer for a rig row is still capped at the province."""
    _patch_response(monkeypatch, _batch([_candidate("rooftop", ROOFTOP_COMPONENTS)]))

    record = SourceRecord(internal_key=0, address="01-17-040-06w4", city="02-16-066-15w5", stateprov="Alberta")
    result = geocodio.GeocodioProvider("key").geocode([record])[0]

    assert result.accuracy == 20
    assert result.match_notes == LEGAL_LAND_NOTE


def test_geocodio_keeps_a_row_left_with_no_address_out_of_the_batch(monkeypatch):
    """A row that is nothing but a grid reference is dropped from the batch, not misaligned."""
    captured = {}
    _patch_response(monkeypatch, _batch([_candidate("rooftop", ROOFTOP_COMPONENTS)]), captured)

    records = [
        SourceRecord(internal_key=0, address="01-17-040-06w4"),
        SourceRecord(internal_key=1, address="1600 Pennsylvania Ave NW"),
    ]
    results = geocodio.GeocodioProvider("key").geocode(records)

    assert captured["json"] == ["1600 Pennsylvania Ave NW"]
    assert results[0].match_notes == f"{NO_ADDRESS_NOTE}; {LEGAL_LAND_NOTE}"
    assert results[0].accuracy == 0
    assert results[1].accuracy == 100
