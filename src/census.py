#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — U.S. Census Bureau provider

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import csv
import io
from typing import Any, Dict, Iterator, List, Tuple

import requests

from .api import AccuracyLevel, GeocodeResult, Provider, SourceRecord, grade_accuracy, register


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
    MAX_ACCURACY = AccuracyLevel.PARCEL

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

    def cache_key(self, record: SourceRecord) -> str:
        """
        Builds the key from the components Census is sent, plus the pinned dataset.

        Country is excluded because the addressbatch CSV has no country column, so
        two rows differing only in country resolve to the same request. The
        benchmark and vintage are included because they select which dataset
        answers the query, and moving off Census2020 would make stored responses
        answers to a different question.
        """
        parts = [record.address, record.city, record.stateprov, record.postalcode, self.BENCHMARK, self.VINTAGE]
        return "|".join(parts)

    def _fetch(self, records: List[SourceRecord]) -> Iterator[Tuple[SourceRecord, Dict[str, Any]]]:
        """
        Posts records in batches, yielding each record with its response row.

        Yielding per batch rather than per run means an interrupted job keeps
        every batch that already came back.

        Parameters
        ----------
        records : List[SourceRecord]
            The source rows to geocode.

        Return
        ----------
        Iterator[Tuple[SourceRecord, Dict[str, Any]]]
            Each record paired with its raw Census response row.
        """
        for start in range(0, len(records), self.BATCH_SIZE):
            yield from self._fetch_batch(records[start : start + self.BATCH_SIZE])

    def _fetch_batch(self, batch: List[SourceRecord]) -> Iterator[Tuple[SourceRecord, Dict[str, Any]]]:
        """Posts one CSV batch, verifies its row count, and matches rows back by internal key."""
        response = self._post_batch(batch)
        rows = [row for row in csv.reader(io.StringIO(response.text)) if row]
        if len(rows) != len(batch):
            raise ValueError(f"Census returned {len(rows)} rows for {len(batch)} submitted records; the service or benchmark may have changed")

        records_by_key = {record.internal_key: record for record in batch}
        for row in rows:
            record = records_by_key.get(int(row[0]))
            if record is not None:
                yield record, self._build_raw(row)

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

    def _build_raw(self, row: List[str]) -> Dict[str, Any]:
        """
        Names the positional fields of one response row, validating a match first.

        Reading the headerless response by position is only safe while the pinned
        layout holds, so a match row is checked here, where it arrives from the
        network, and never again. Everything downstream reads the named fields.

        The echoed id is dropped: it is this run's internal key, which carries no
        meaning once the response outlives the run that fetched it.
        """
        status = row[2] if len(row) > 2 else "No_Match"
        if status == "Match":
            self._check_layout(row)

        raw = dict(zip(self.RESPONSE_FIELDS, row))
        raw.pop("id", None)
        return raw

    def parse(self, raw: Dict[str, Any]) -> GeocodeResult:
        """
        Converts one Census response row into a normalized GeocodeResult.

        Accuracy is graded from the populated result fields rather than the
        Census match type, so it reflects how specific the returned location is.
        """
        result = self._build_result(raw)
        result.accuracy = grade_accuracy(result, self.MAX_ACCURACY)
        return result

    def _build_result(self, raw: Dict[str, Any]) -> GeocodeResult:
        """Maps a Census response row to a result without scoring its accuracy."""
        status = raw.get("match_status", "No_Match")

        if status == "Match":
            exact = raw.get("match_type", "").strip().lower() == "exact"
            address, city, stateprov, postalcode = self._split_address(raw.get("matched_address", ""))
            longitude, latitude = self._split_coordinates(raw.get("coordinates", ""))
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
                raw=raw,
            )

        if status == "Tie":
            return GeocodeResult(match_type="tie", match_notes="Tie", raw=raw)

        return GeocodeResult(match_notes="No match", raw=raw)

    def _check_layout(self, row: List[str]) -> None:
        """
        Fails loudly when a match row departs from the pinned Census2020 layout.

        The addressbatch response is headerless and read by fixed position, so a
        match must carry the full column set and a numeric ``lon,lat`` pair; a
        mismatch means the pinned layout shifted and positional reads can no
        longer be trusted.
        """
        if len(row) != len(self.RESPONSE_FIELDS):
            raise ValueError(
                f"Census match row has {len(row)} of {len(self.RESPONSE_FIELDS)} expected fields; pinned layout may have changed: {row!r}"
            )

        longitude, latitude = self._split_coordinates(row[5])
        try:
            float(longitude)
            float(latitude)
        except ValueError:
            raise ValueError(f"Census match coordinates {row[5]!r} are not a numeric lon,lat pair; pinned layout may have changed: {row!r}") from None

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
