#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder API Tests

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import pytest

from src import api
from src.api import GeocodeResult, Provider, format_street_address, grade_accuracy, register, resolve_api_key


def test_register_adds_to_registry():
    """@register adds the subclass to PROVIDERS and sets its name."""

    @register("temp_provider")
    class _Temp(Provider):
        def _fetch(self, records):
            """Yields nothing; the class only exercises registration."""
            return iter(())

        def parse(self, raw):
            """Returns an empty result; the class only exercises registration."""
            return GeocodeResult(raw=raw)

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


def test_grade_accuracy_uses_most_specific_field():
    """Each populated field grades to its tier, most specific field winning."""
    assert grade_accuracy(GeocodeResult(result_address="1 Main St", result_city="Town")) == 100
    assert grade_accuracy(GeocodeResult(result_postalcode="90210", result_city="Town")) == 50
    assert grade_accuracy(GeocodeResult(result_city="Town", result_stateprov="CA")) == 40
    assert grade_accuracy(GeocodeResult(result_stateprov="CA", result_country="US")) == 20
    assert grade_accuracy(GeocodeResult(result_country="US")) == 10


def test_grade_accuracy_zero_without_location_fields():
    """A result with no location fields scores zero regardless of other data."""
    assert grade_accuracy(GeocodeResult(match_type="tie")) == 0


def test_grade_accuracy_cap_limits_top_tier():
    """A provider cap lowers the top tier but leaves coarser tiers untouched."""
    assert grade_accuracy(GeocodeResult(result_address="1 Main St"), cap=90) == 90
    assert grade_accuracy(GeocodeResult(result_postalcode="90210"), cap=90) == 50


def test_format_street_address_leads_with_the_number():
    """Countries outside ROUTE_FIRST_COUNTRIES put the house number before the street."""
    assert format_street_address("US", "Pennsylvania Ave NW", "1600") == "1600 Pennsylvania Ave NW"
    assert format_street_address("CA", "Stornoway Dr", "42") == "42 Stornoway Dr"


def test_format_street_address_trails_the_number_in_mexico():
    """A Mexican street line carries the number after the street, with the sublocality appended."""
    assert format_street_address("MX", "C. 49", "76", sublocality="Santa Margarita") == "C. 49 76, Santa Margarita"
    assert format_street_address("MX", "Gral. Pedro Hinojosa", "7", "17", "Cd Industrial") == "Gral. Pedro Hinojosa 7-17, Cd Industrial"


def test_format_street_address_without_a_number_keeps_the_street():
    """A street with no house number still yields an address in either convention."""
    assert format_street_address("US", "Pennsylvania Ave NW") == "Pennsylvania Ave NW"
    assert format_street_address("MX", "C. 49", sublocality="Santa Margarita") == "C. 49, Santa Margarita"


def test_format_street_address_without_a_street_is_blank():
    """A match with no street has no address to report, whatever else it carries."""
    assert format_street_address("US", "", "1600") == ""
    assert format_street_address("MX", "", "76", "17", "Santa Margarita") == ""


class _FakeResponse:
    """Stands in for a requests.Response so provider tests avoid the network."""

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        """Mimics a successful response by never raising."""


class _RetryProvider(Provider):
    """Routes a single retried request through the provider for the retry tests."""

    def __init__(self, send):
        super().__init__()
        self.send = send

    def _fetch(self, records):
        """Yields nothing; the class only exercises the retry helper."""
        return iter(())

    def parse(self, raw):
        """Returns an empty result; the class only exercises the retry helper."""
        return GeocodeResult(raw=raw)

    def send_once(self):
        """Returns the response from one retried request."""
        return self._request_with_retry(self.send)


def test_request_with_retry_succeeds_after_transient_error(monkeypatch):
    """A transient connection error is retried until the request succeeds."""
    monkeypatch.setattr(api.time, "sleep", lambda seconds: None)
    attempts = {"count": 0}

    def send():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise api.requests.ConnectionError("connection reset")
        return _FakeResponse("ok")

    response = _RetryProvider(send).send_once()

    assert attempts["count"] == 3
    assert response.text == "ok"


def test_request_with_retry_reraises_after_exhausting_attempts(monkeypatch):
    """Retries stop at MAX_ATTEMPTS and the final failure propagates."""
    monkeypatch.setattr(api.time, "sleep", lambda seconds: None)
    attempts = {"count": 0}

    def send():
        attempts["count"] += 1
        raise api.requests.ConnectionError("connection reset")

    with pytest.raises(api.requests.ConnectionError):
        _RetryProvider(send).send_once()
    assert attempts["count"] == Provider.MAX_ATTEMPTS
