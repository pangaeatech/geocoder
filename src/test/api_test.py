#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder API Tests

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import pytest

import api
from api import Provider, SourceRecord, register, resolve_api_key


def test_register_adds_to_registry():
    """@register adds the subclass to PROVIDERS and sets its name."""

    @register("temp_provider")
    class _Temp(Provider):
        def geocode(self, records):
            """Returns no results; the class only exercises registration."""
            return []

    try:
        assert api.PROVIDERS["temp_provider"] is _Temp
        assert _Temp.name == "temp_provider"
    finally:
        del api.PROVIDERS["temp_provider"]


def test_resolve_api_key_cli_wins(monkeypatch):
    """A command-line key takes precedence over the environment variable."""
    monkeypatch.setenv("GEOCODIO_API_KEY", "from_env")
    assert resolve_api_key("geocodio", "from_cli") == "from_cli"


def test_resolve_api_key_env_fallback(monkeypatch):
    """The environment variable is used when no command-line key is given."""
    monkeypatch.setenv("GEOCODIO_API_KEY", "from_env")
    assert resolve_api_key("geocodio", None) == "from_env"


def test_resolve_api_key_none_for_keyless_provider():
    """A provider without a configured env var resolves to no key."""
    assert resolve_api_key("census", None) is None


class _FakeResponse:
    """Stands in for a requests.Response so provider tests avoid the network."""

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        """Mimics a successful response by never raising."""


CENSUS_RESPONSE = (
    '"2","1 Main St, Anytown, CA","Tie"\r\n'
    '"0","1600 Pennsylvania Ave NW, Washington, DC, 20500","Match","Exact",'
    '"1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500","-77.03535,38.898754",'
    '"76225813","L","11","001","980000","1034"\r\n'
    '"1","Nowhere St, Nowhere, ZZ","No_Match"\r\n'
)


def test_census_registered():
    """@register("census") wires CensusProvider into the registry."""
    assert api.PROVIDERS["census"] is api.CensusProvider


def test_census_parses_batch(monkeypatch):
    """A batch response is parsed and aligned to records by internal key."""
    captured = {}

    def fake_post(url, data=None, files=None, timeout=None):
        captured.update(url=url, data=data, files=files, timeout=timeout)
        return _FakeResponse(CENSUS_RESPONSE)

    monkeypatch.setattr(api.requests, "post", fake_post)

    records = [
        SourceRecord(
            internal_key=0,
            address="1600 Pennsylvania Ave NW",
            city="Washington",
            stateprov="DC",
            postalcode="20500",
        ),
        SourceRecord(
            internal_key=1, address="Nowhere St", city="Nowhere", stateprov="ZZ"
        ),
        SourceRecord(
            internal_key=2, address="1 Main St", city="Anytown", stateprov="CA"
        ),
    ]

    results = api.CensusProvider().geocode(records)

    assert captured["url"] == api.CensusProvider.ENDPOINT
    assert captured["data"]["benchmark"] == "Public_AR_Current"
    assert captured["data"]["vintage"] == "Current_Current"

    exact = results[0]
    assert exact.match_type == "exact"
    assert exact.accuracy == 100
    assert exact.result_address == "1600 PENNSYLVANIA AVE NW"
    assert exact.result_city == "WASHINGTON"
    assert exact.result_stateprov == "DC"
    assert exact.result_postalcode == "20500"
    assert exact.longitude == "-77.03535"
    assert exact.latitude == "38.898754"
    assert exact.location_type == ""
    assert exact.result_id == ""

    assert results[1].match_type == "no_match"
    assert results[1].accuracy == 0
    assert results[1].match_notes == "No match"

    assert results[2].match_type == "tie"
    assert results[2].accuracy == 30
    assert results[2].match_notes == "Tie"


def test_census_builds_csv_input(monkeypatch):
    """The posted CSV carries the internal key and address components."""
    captured = {}

    def fake_post(url, data=None, files=None, timeout=None):
        captured["csv"] = files["addressFile"][1]
        return _FakeResponse('"0","1 Main St, Town, CA","No_Match"\r\n')

    monkeypatch.setattr(api.requests, "post", fake_post)

    records = [
        SourceRecord(
            internal_key=0,
            address="1 Main St",
            city="Town",
            stateprov="CA",
            postalcode="90210",
        )
    ]
    api.CensusProvider().geocode(records)

    assert captured["csv"].startswith("0,")
    assert "1 Main St" in captured["csv"]
    assert "90210" in captured["csv"]


def test_census_retries_transient_failure(monkeypatch):
    """A transient connection error is retried until the request succeeds."""
    attempts = {"count": 0}

    def fake_post(url, data=None, files=None, timeout=None):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise api.requests.ConnectionError("connection reset")
        return _FakeResponse('"0","1 Main St, Town, CA","No_Match"\r\n')

    monkeypatch.setattr(api.requests, "post", fake_post)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: None)

    records = [SourceRecord(internal_key=0, address="1 Main St", stateprov="CA")]
    results = api.CensusProvider().geocode(records)

    assert attempts["count"] == 3
    assert results[0].match_type == "no_match"


def test_census_reraises_after_exhausting_retries(monkeypatch):
    """Retries stop at MAX_ATTEMPTS and the final failure propagates."""
    attempts = {"count": 0}

    def fake_post(url, data=None, files=None, timeout=None):
        attempts["count"] += 1
        raise api.requests.ConnectionError("connection reset")

    monkeypatch.setattr(api.requests, "post", fake_post)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: None)

    records = [SourceRecord(internal_key=0, address="1 Main St", stateprov="CA")]
    with pytest.raises(api.requests.ConnectionError):
        api.CensusProvider().geocode(records)
    assert attempts["count"] == api.CensusProvider.MAX_ATTEMPTS
