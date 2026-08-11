#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — provider base and shared types

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional, Type

import requests

KEY_ENV_VARS = {
    "geocodio": "GEOCODIO_API_KEY",
    "google": "GOOGLE_GEOCODING_API_KEY",
}


@dataclass
class SourceRecord:
    """A single input row, keyed by an internal sequential id for batch matching."""

    internal_key: int
    id: str = ""
    name: str = ""
    address: str = ""
    city: str = ""
    stateprov: str = ""
    postalcode: str = ""
    country: str = ""
    latitude: str = ""
    longitude: str = ""

    def address_string(self) -> str:
        """Joins the non-blank address components into a single query string."""
        parts = [self.address, self.city, self.stateprov, self.postalcode, self.country]
        return ", ".join(part for part in parts if part)


@dataclass
class GeocodeResult:
    """A normalized geocoding result; providers return one per SourceRecord."""

    result_id: str = ""
    result_name: str = ""
    result_address: str = ""
    result_city: str = ""
    result_stateprov: str = ""
    result_postalcode: str = ""
    result_country: str = ""
    latitude: str = ""
    longitude: str = ""
    match_type: str = "no_match"
    accuracy: int = 0
    location_type: str = ""
    match_notes: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


class AccuracyLevel(IntEnum):
    """
    Location precision tiers from an exact rooftop down to no match, each paired
    with the result field whose presence implies it, or blank for tiers no field
    maps to (reachable only as a provider cap).
    """

    ROOFTOP = (100, "result_address")
    PARCEL = (90, "")
    BLOCK = (80, "")
    STREET = (70, "")
    NEIGHBORHOOD = (60, "")
    POSTALCODE = (50, "result_postalcode")
    CITY = (40, "result_city")
    COUNTY = (30, "")
    STATE = (20, "result_stateprov")
    COUNTRY = (10, "result_country")
    NONE = (0, "")

    def __new__(cls, score, field_name):
        """Builds a member valued by its score and tagged with its source field."""
        member = int.__new__(cls, score)
        member._value_ = score
        member.field = field_name
        return member


def grade_accuracy(result: GeocodeResult, cap: Optional[int] = None) -> int:
    """
    Scores a result by how specific its populated location fields are.

    The score reflects the most specific field the provider returned, not how
    well the source matched, so a street-level result always outranks one that
    resolved only to a city or state. Fields are checked from most to least
    specific and the first populated one wins; a result with no location fields
    scores zero. Scores follow AccuracyLevel, mapped onto the location fields a
    result actually carries.

    The cap bounds the score to a provider's best achievable precision: a
    provider that never resolves finer than a street (e.g. Census, which
    interpolates a parcel rather than pinpointing a rooftop) passes the parcel
    level, while one that can pinpoint a rooftop leaves it unset.

    Parameters
    ----------
    result : GeocodeResult
        The result whose location fields are inspected.
    cap : Optional[int]
        The highest score the provider can achieve, or None for no limit.

    Return
    ----------
    int
        The accuracy score for the most specific populated field, bounded by cap.
    """
    for level in AccuracyLevel:
        if level.field and getattr(result, level.field):
            return level if cap is None else min(level, cap)
    return AccuracyLevel.NONE


PROVIDERS: Dict[str, Type["Provider"]] = {}


def register(name: str):
    """Class decorator that registers a Provider subclass under the given name."""

    def decorator(cls):
        cls.name = name
        PROVIDERS[name] = cls
        return cls

    return decorator


class Provider(ABC):
    """Base class for geocoding providers; subclasses self-register via @register."""

    name: str = ""
    requires_key: bool = False
    MAX_ATTEMPTS = 3
    RETRY_BACKOFF = 5
    MAX_ACCURACY = AccuracyLevel.ROOFTOP

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    @abstractmethod
    def geocode(self, records: List[SourceRecord]) -> List[GeocodeResult]:
        """Returns one GeocodeResult per input record, in the same order."""

    def _request_with_retry(self, send: Callable[[], requests.Response]) -> requests.Response:
        """
        Calls send(), retrying transient failures with a linear backoff.

        Each attempt runs send() and raises for an HTTP error status; any
        requests error is retried until MAX_ATTEMPTS is reached, sleeping
        RETRY_BACKOFF seconds times the attempt number between tries. The final
        failure is re-raised.

        Parameters
        ----------
        send : Callable[[], requests.Response]
            A zero-argument callable that performs one HTTP request.

        Return
        ----------
        requests.Response
            The first successful response.

        Raises
        ----------
        requests.RequestException
            If every attempt fails.
        """
        last_error = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                response = send()
                response.raise_for_status()
                return response
            except requests.RequestException as error:
                last_error = error
                if attempt < self.MAX_ATTEMPTS:
                    time.sleep(self.RETRY_BACKOFF * attempt)
        raise last_error


def resolve_api_key(api: str, cli_key: Optional[str]) -> Optional[str]:
    """
    Resolves an API key, preferring --apiKey over the provider's environment variable.

    Parameters
    ----------
    api : str
        The provider name whose environment variable is consulted.
    cli_key : Optional[str]
        The key supplied on the command line, if any.

    Return
    ----------
    Optional[str]
        The resolved key, or None when none is configured.
    """
    if cli_key:
        return cli_key

    env_var = KEY_ENV_VARS.get(api)
    return os.environ.get(env_var) if env_var else None
