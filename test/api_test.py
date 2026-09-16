#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder API Tests

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import pytest

from src import api
from src.api import (
    LEGAL_LAND_NOTE,
    GeocodeResult,
    Provider,
    SourceRecord,
    apply_legal_land_limit,
    format_street_address,
    grade_accuracy,
    register,
    resolve_api_key,
    strip_legal_land_description,
)


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


def test_strip_legal_land_description_removes_the_grid_reference():
    """A legal land description is dropped in each of the forms the data carries."""
    assert strip_legal_land_description("01-17-040-06w4") == ""
    assert strip_legal_land_description("02-16-066-15w5") == ""
    assert strip_legal_land_description("16-066-15w5") == ""
    assert strip_legal_land_description("NE-16-066-15-W5M") == ""
    assert strip_legal_land_description("SW 4 30 5 W4") == ""
    assert strip_legal_land_description("09-03-084-01 W6m") == ""
    assert strip_legal_land_description("2-9-15-37-8w4") == ""


def test_strip_legal_land_description_removes_a_numbered_meridian():
    """A meridian reduced to its number is dropped like a lettered one."""
    assert strip_legal_land_description("04-11-36-19-4") == ""
    assert strip_legal_land_description("7-35-43-18-4") == ""
    assert strip_legal_land_description("11-30-51-25-5") == ""


def test_strip_legal_land_description_removes_an_unnumbered_meridian():
    """A meridian written as a bare letter is dropped like a numbered one."""
    assert strip_legal_land_description("Nw-02-033-26w") == ""


def test_strip_legal_land_description_removes_a_topographic_reference():
    """A British Columbia map sheet reference is dropped however its separator is written."""
    assert strip_legal_land_description("A-51-I/94-O-10") == ""
    assert strip_legal_land_description("B-009-C/094-A-16") == ""
    assert strip_legal_land_description("D-95-I94-A-15") == ""
    assert strip_legal_land_description("B-33-G 93-P-3 B-033-G/093-P-03") == ""


def test_strip_legal_land_description_drops_stranded_identifier_digits():
    """The digits a well identifier wraps around a reference locate nothing on their own."""
    assert strip_legal_land_description("200 /D-050-E/094-H-05/ 00") == ""


def test_strip_legal_land_description_keeps_a_street_address_beside_a_reference():
    """A row carrying both a reference and a real street keeps the street."""
    assert strip_legal_land_description("C-40-G/94-J-09 5012 - 48th Ave") == "5012 - 48th Ave"


def test_strip_legal_land_description_keeps_the_surrounding_text():
    """Only the grid reference is removed; anything else in the field survives."""
    assert strip_legal_land_description("LSD 01-17-040-06w4 Access Rd") == "LSD Access Rd"


def test_strip_legal_land_description_leaves_street_addresses_alone():
    """An ordinary street address carries no grid reference to remove."""
    assert strip_legal_land_description("1600 Pennsylvania Ave NW") == "1600 Pennsylvania Ave NW"
    assert strip_legal_land_description("100 W 5th Ave") == "100 W 5th Ave"
    assert strip_legal_land_description("Avenida Paseo De La Reforma 489") == "Avenida Paseo De La Reforma 489"
    assert strip_legal_land_description("Bay 5-3830 19 St NE") == "Bay 5-3830 19 St NE"


def test_strip_legal_land_description_leaves_hyphenated_numbers_alone():
    """A run of hyphenated numbers is not a grid reference without a qualified meridian."""
    assert strip_legal_land_description("PO Box 1-2-3-4") == "PO Box 1-2-3-4"
    assert strip_legal_land_description("Lot 4-11-36-2") == "Lot 4-11-36-2"
    assert strip_legal_land_description("Hwy 2-16-66-5") == "Hwy 2-16-66-5"
    assert strip_legal_land_description("1-800-555-1212") == "1-800-555-1212"


def test_strip_legal_land_description_leaves_a_bare_direction_alone():
    """A trailing direction is not a meridian without the qualifying subdivision."""
    assert strip_legal_land_description("Range Rd 5-10-15 W") == "Range Rd 5-10-15 W"


def test_strip_legal_land_description_leaves_spaced_letters_and_numbers_alone():
    """A map sheet reference is written with hyphens, so spaced tokens are left alone."""
    assert strip_legal_land_description("Bldg C 5 D 100 A 2") == "Bldg C 5 D 100 A 2"


def test_address_string_withholds_a_legal_land_description():
    """A rig row is queried by its province alone rather than by its grid reference."""
    record = SourceRecord(internal_key=0, address="02-16-066-15w5", stateprov="Alberta", country="Canada")

    assert record.address_string() == "Alberta, Canada"
    assert record.has_legal_land_description() is True


def test_address_string_withholds_a_legal_land_description_in_the_city():
    """A grid reference filed under city is withheld just as one filed under address is."""
    record = SourceRecord(internal_key=0, address="01-17-040-06w4", city="16-066-15w5", stateprov="AB", country="Canada")

    assert record.address_string() == "AB, Canada"
    assert record.has_legal_land_description() is True


def test_address_string_withholds_the_postal_code_of_a_legal_land_row():
    """A rig row keeps the town it names but not the postal code filed beside the grid reference."""
    record = SourceRecord(internal_key=0, address="7-24-35-2 W5m", city="Spruce View", stateprov="Alberta", postalcode="T0M1V0", country="Canada")

    assert record.address_string() == "Spruce View, Alberta, Canada"


def test_address_string_keeps_an_ordinary_address():
    """A row without a grid reference is queried exactly as it was entered."""
    record = SourceRecord(internal_key=0, address="1600 Pennsylvania Ave NW", city="Washington", stateprov="DC", postalcode="20500")

    assert record.address_string() == "1600 Pennsylvania Ave NW, Washington, DC, 20500"
    assert record.has_legal_land_description() is False


def test_apply_legal_land_limit_caps_at_the_province():
    """A rig row cannot claim a match finer than the province that was queried."""
    result = GeocodeResult(result_address="2 AB-16", result_city="Spruce Grove", result_stateprov="AB", accuracy=100)
    record = SourceRecord(internal_key=0, address="02-16-066-15w5", stateprov="Alberta", country="Canada")

    assert apply_legal_land_limit(record, result).accuracy == 20
    assert result.match_notes == LEGAL_LAND_NOTE


def test_apply_legal_land_limit_keeps_a_coarser_score():
    """A match already coarser than the province is left where it stands."""
    result = GeocodeResult(result_country="CA", accuracy=10, match_notes="No match")
    record = SourceRecord(internal_key=0, address="02-16-066-15w5", country="Canada")

    assert apply_legal_land_limit(record, result).accuracy == 10
    assert result.match_notes == f"No match; {LEGAL_LAND_NOTE}"


def test_apply_legal_land_limit_leaves_ordinary_rows_untouched():
    """A row without a grid reference keeps its full score and notes."""
    result = GeocodeResult(result_address="1600 Pennsylvania Ave NW", accuracy=100)
    record = SourceRecord(internal_key=0, address="1600 Pennsylvania Ave NW")

    assert apply_legal_land_limit(record, result).accuracy == 100
    assert result.match_notes == ""


class _FakeResponse:
    """Stands in for a requests.Response so provider tests avoid the network."""

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        """Mimics a successful response by never raising."""


class _RetryProvider(Provider):
    """Routes a single retried request through geocode for the retry tests."""

    def __init__(self, send):
        super().__init__()
        self.send = send

    def geocode(self, records):
        """Returns the response from one retried request, ignoring records."""
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

    response = _RetryProvider(send).geocode([])

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
        _RetryProvider(send).geocode([])
    assert attempts["count"] == Provider.MAX_ATTEMPTS
