#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — U.S. Census Bureau provider

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import csv
import io
from typing import Dict, List

import requests

from .api import GeocodeResult, Provider, SourceRecord, register


@register("census")
class CensusProvider(Provider):
    """
    Batch geocoder backed by the free U.S. Census Bureau addressbatch service.

    Records are submitted as CSV batches and matched back by their internal key.
    The service covers U.S. addresses only and requires no API key.

    The benchmark and vintage are pinned to the frozen Census2020 dataset so the
    positional response layout stays stable; the addressbatch endpoint returns
    headerless CSV, so columns can only be read by their fixed position.
    """

    requires_key = False

    ENDPOINT = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
    BENCHMARK = "Public_AR_Census2020"
    VINTAGE = "Census2020_Census2020"
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
                result_id=raw.get("tigerline_id", ""),
                result_address=address,
                result_city=city,
                result_stateprov=stateprov,
                result_postalcode=postalcode,
                result_country="US",
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
