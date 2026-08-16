#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — Geocodio provider

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

from typing import Dict, List

import requests

from .api import AccuracyLevel, GeocodeResult, Provider, SourceRecord, grade_accuracy, register


@register("geocodio")
class GeocodioProvider(Provider):
    """
    Batch geocoder backed by the Geocodio API.

    Records are submitted as a JSON array of address strings; Geocodio returns
    one result entry per input in the same order, so entries are matched back to
    records by position and the batch is rejected if the counts differ. Requests
    require an API key, resolved from --apiKey or the GEOCODIO_API_KEY
    environment variable, and cover U.S. and Canadian addresses only.

    Accuracy is driven by the response ``accuracy_type`` rather than the returned
    address fields: Geocodio echoes a full formatted address even when it only
    interpolated a point along a street range or fell back to a place centroid,
    so grading the fields alone would report those coarser matches as rooftop
    precision. Each accuracy_type therefore caps the graded score at the
    precision it actually represents.
    """

    requires_key = True

    ENDPOINT = "https://api.geocod.io/v1.7/geocode"
    BATCH_SIZE = 10000
    TIMEOUT = 600

    ACCURACY_TYPE_LEVELS = {
        "rooftop": AccuracyLevel.ROOFTOP,
        "point": AccuracyLevel.ROOFTOP,
        "range_interpolation": AccuracyLevel.BLOCK,
        "nearest_rooftop_match": AccuracyLevel.BLOCK,
        "street_center": AccuracyLevel.STREET,
        "intersection": AccuracyLevel.STREET,
        "place": AccuracyLevel.CITY,
        "county": AccuracyLevel.COUNTY,
        "state": AccuracyLevel.STATE,
    }

    EXACT_TYPES = {"rooftop", "point"}

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
        """Posts one batch, verifies its entry count, and stores each result by internal key."""
        entries = self._post_batch(batch)
        if len(entries) != len(batch):
            raise ValueError(f"Geocodio returned {len(entries)} entries for {len(batch)} submitted records; the batch response may have changed")
        for record, entry in zip(batch, entries):
            results_by_key[record.internal_key] = self._parse_entry(entry)

    def _post_batch(self, batch: List[SourceRecord]) -> List[Dict]:
        """Posts one batch through the retrying request helper and returns the ordered result entries."""
        payload = [record.address_string() for record in batch]
        response = self._request_with_retry(
            lambda: requests.post(
                self.ENDPOINT,
                params={"api_key": self.api_key},
                json=payload,
                timeout=self.TIMEOUT,
            )
        )
        return response.json().get("results", [])

    def _parse_entry(self, entry: Dict) -> GeocodeResult:
        """Grades the best candidate for one input, or returns a no-match when none was found."""
        matches = entry.get("response", {}).get("results", [])
        if not matches:
            return GeocodeResult(match_notes="No match", raw=entry)
        return self._parse_result(matches[0])

    def _parse_result(self, match: Dict) -> GeocodeResult:
        """
        Converts one Geocodio candidate into a normalized GeocodeResult.

        The graded accuracy is capped at the tier implied by ``accuracy_type`` so
        an interpolated or centroid match cannot report rooftop precision on the
        strength of the echoed address fields.
        """
        result = self._build_result(match)
        cap = self.ACCURACY_TYPE_LEVELS.get(result.location_type, AccuracyLevel.NONE)
        result.accuracy = grade_accuracy(result, cap)
        return result

    def _build_result(self, match: Dict) -> GeocodeResult:
        """Maps a Geocodio candidate to a GeocodeResult without scoring its accuracy."""
        components = match.get("address_components", {})
        location = match.get("location", {})
        accuracy_type = match.get("accuracy_type", "")

        return GeocodeResult(
            result_address=self._street_address(components),
            result_city=components.get("city", ""),
            result_stateprov=components.get("state", ""),
            result_postalcode=components.get("zip", ""),
            result_country=components.get("country", ""),
            latitude=str(location.get("lat", "")),
            longitude=str(location.get("lng", "")),
            match_type="exact" if accuracy_type in self.EXACT_TYPES else "non-exact",
            location_type=accuracy_type,
            raw=match,
        )

    @staticmethod
    def _street_address(components: Dict[str, str]) -> str:
        """
        Joins house number and street into a street address, or blank without a number.

        A street without a house number is only street-level, so leaving the
        address blank lets grade_accuracy fall through to the coarser field the
        result actually resolved.
        """
        number = components.get("number", "")
        street = components.get("formatted_street", "")
        if number and street:
            return f"{number} {street}"
        return ""
