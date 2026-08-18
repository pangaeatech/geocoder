#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder Google Provider Tests

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import pytest

from src import google
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


def _patch_response(monkeypatch, payload, captured=None):
    """Routes requests.get to a canned payload, optionally capturing the call args."""

    def fake_get(url, params=None, timeout=None):
        if captured is not None:
            captured.update(url=url, params=params, timeout=timeout)
        return _FakeResponse(payload)

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
    assert result.result_address == "1600 Pennsylvania Ave NW"
    assert result.result_city == "Washington"
    assert result.result_stateprov == "DC"
    assert result.result_postalcode == "20500"
    assert result.result_country == "US"
    assert result.latitude == "38.898754"
    assert result.longitude == "-77.03535"
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


def test_google_route_without_number_is_not_rooftop(monkeypatch):
    """A route without a street number leaves the address blank so grading stays coarse."""
    components = [component for component in ROOFTOP_COMPONENTS if component["types"] != ["street_number"]]
    _patch_response(monkeypatch, _result("GEOMETRIC_CENTER", components))

    result = google.GoogleProvider("key").geocode([SourceRecord(internal_key=0, address="Stornoway St")])[0]

    assert result.result_address == ""
    assert result.accuracy == 50


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
