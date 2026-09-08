#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder Shared Provider Test Helpers

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""


class FakeResponse:
    """Stands in for a requests.Response so provider tests avoid the network."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        """Mimics a successful response by never raising."""

    def json(self):
        """Returns the canned decoded payload."""
        return self._payload


def assert_white_house(result):
    """
    Asserts a provider normalized the shared White House rooftop fixture.

    Each provider reads that address out of a different response shape, so the
    normalized fields they are all expected to agree on are asserted here once
    rather than restated in every provider's tests.
    """
    assert result.result_address == "1600 Pennsylvania Ave NW"
    assert result.result_city == "Washington"
    assert result.result_stateprov == "DC"
    assert result.result_postalcode == "20500"
    assert result.result_country == "US"
    assert result.latitude == "38.898754"
    assert result.longitude == "-77.03535"
