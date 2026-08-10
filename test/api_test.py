#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder API Tests

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import pytest

from src import api
from src.api import Provider, register, resolve_api_key


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
