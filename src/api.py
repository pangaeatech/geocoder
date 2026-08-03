#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — geocoding providers

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import csv
import io
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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


@register("census")
class CensusProvider(Provider):
    """
    Batch geocoder backed by the free U.S. Census Bureau addressbatch service.

    Records are submitted as CSV batches and matched back by their internal key.
    The service covers U.S. addresses only and requires no API key.
    """

    requires_key = False

    ENDPOINT = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
    BENCHMARK = "Public_AR_Current"
    VINTAGE = "Current_Current"
    BATCH_SIZE = 10000
    TIMEOUT = 300

    RESPONSE_FIELDS = [
        "id",
        "input_address",
        "match_status",
        "match_type",
        "matched_address",
        "coordinates",
        "tigerline_id",
        "side",
        "state_fips",
        "county_fips",
        "tract",
        "block",
    ]

    def geocode(self, records: List[SourceRecord]) -> List[GeocodeResult]:
        """
        Geocodes records in batches and returns one result per record, in order.

        Parameters
        ----------
        records : List[SourceRecord]
            The source rows to geocode.

        Return
        ----------
        List[GeocodeResult]
            One result per input record, aligned by position.
        """
        results_by_key: Dict[int, GeocodeResult] = {}
        for start in range(0, len(records), self.BATCH_SIZE):
            self._geocode_batch(records[start : start + self.BATCH_SIZE], results_by_key)

        return [results_by_key.get(record.internal_key, GeocodeResult(match_notes="No match")) for record in records]

    def _geocode_batch(self, batch: List[SourceRecord], results_by_key: Dict[int, GeocodeResult]) -> None:
        """Posts one CSV batch and stores each parsed result by its internal key."""
        response = self._post_batch(batch)
        for row in csv.reader(io.StringIO(response.text)):
            if row:
                results_by_key[int(row[0])] = self._parse_row(row)

    def _post_batch(self, batch: List[SourceRecord]) -> requests.Response:
        """Posts one CSV batch through the retrying request helper."""
        csv_input = self._build_csv(batch)
        return self._request_with_retry(
            lambda: requests.post(
                self.ENDPOINT,
                data={"benchmark": self.BENCHMARK, "vintage": self.VINTAGE},
                files={"addressFile": ("addresses.csv", csv_input)},
                timeout=self.TIMEOUT,
            )
        )

    @staticmethod
    def _build_csv(batch: List[SourceRecord]) -> str:
        """Serializes a batch into the Census addressbatch CSV input format."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for record in batch:
            writer.writerow(
                [
                    record.internal_key,
                    record.address,
                    record.city,
                    record.stateprov,
                    record.postalcode,
                ]
            )
        return buffer.getvalue()

    def _parse_row(self, row: List[str]) -> GeocodeResult:
        """Converts one Census response row into a normalized GeocodeResult."""
        raw = dict(zip(self.RESPONSE_FIELDS, row))
        status = row[2] if len(row) > 2 else "No_Match"

        if status == "Match" and len(row) > 5:
            exact = row[3].strip().lower() == "exact"
            address, city, stateprov, postalcode = self._split_address(row[4])
            longitude, latitude = self._split_coordinates(row[5])
            return GeocodeResult(
                result_address=address,
                result_city=city,
                result_stateprov=stateprov,
                result_postalcode=postalcode,
                latitude=latitude,
                longitude=longitude,
                match_type="exact" if exact else "non-exact",
                accuracy=100 if exact else 70,
                raw=raw,
            )

        if status == "Tie":
            return GeocodeResult(match_type="tie", accuracy=30, match_notes="Tie", raw=raw)

        return GeocodeResult(match_notes="No match", raw=raw)

    @staticmethod
    def _split_address(matched_address: str) -> List[str]:
        """Splits a Census matched-address into street, city, state, and zip."""
        parts = [part.strip() for part in matched_address.split(",")]
        parts += [""] * (4 - len(parts))
        return parts[:4]

    @staticmethod
    def _split_coordinates(coordinates: str) -> List[str]:
        """Splits a Census 'longitude,latitude' pair into separate strings."""
        parts = [part.strip() for part in coordinates.split(",")]
        return parts if len(parts) == 2 else ["", ""]
