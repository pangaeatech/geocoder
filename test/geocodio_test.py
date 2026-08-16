#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder Geocodio Provider Tests

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import pytest

from src import geocodio
from src.api import PROVIDERS, SourceRecord


class _FakeResponse:
    """Stands in for a requests.Response so provider tests avoid the network."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        """Mimics a successful response by never raising."""

    def json(self):
        """Returns the canned decoded payload."""
        return self._payload


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


def _patch_response(monkeypatch, payload, captured=None):
    """Routes requests.post to a canned payload, optionally capturing the call args."""

    def fake_post(url, params=None, json=None, timeout=None):
        if captured is not None:
            captured.update(url=url, params=params, json=json, timeout=timeout)
        return _FakeResponse(payload)

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
    assert result.result_address == "1600 Pennsylvania Ave NW"
    assert result.result_city == "Washington"
    assert result.result_stateprov == "DC"
    assert result.result_postalcode == "20500"
    assert result.result_country == "US"
    assert result.latitude == "38.898754"
    assert result.longitude == "-77.03535"
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


def test_geocodio_street_without_number_is_not_rooftop(monkeypatch):
    """A street without a house number leaves the address blank so grading stays coarse."""
    components = {key: value for key, value in ROOFTOP_COMPONENTS.items() if key != "number"}
    _patch_response(monkeypatch, _batch([_candidate("street_center", components)]))

    result = geocodio.GeocodioProvider("key").geocode([SourceRecord(internal_key=0, address="Stornoway St")])[0]

    assert result.result_address == ""
    assert result.accuracy == 50


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
