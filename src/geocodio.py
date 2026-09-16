#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — Geocodio provider

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

from typing import Any, Dict, Iterator, List, Tuple

import requests

from .api import AccuracyLevel, GeocodeResult, Provider, SourceRecord, format_street_address, grade_accuracy, register


@register("geocodio")
class GeocodioProvider(Provider):
    """
    Batch geocoder backed by the Geocodio API.

    Records are submitted as a JSON array of address strings; Geocodio returns
    one result entry per input in the same order, so entries are matched back to
    records by position and the batch is rejected if the counts differ. Requests
    require an API key, resolved from --apiKey or the GEOCODIO_API_KEY
    environment variable, and cover U.S., Canadian, Mexican, and U.K. addresses.

    Accuracy is driven by the response ``accuracy_type`` rather than the returned
    address fields: Geocodio echoes a full formatted address even when it only
    interpolated a point along a street range or fell back to a place centroid,
    so grading the fields alone would report those coarser matches as rooftop
    precision. Each accuracy_type therefore caps the graded score at the
    precision it actually represents, and a match resolved to a street with no
    house number is capped lower still.

    Street addresses are assembled from the response components in the
    convention of the country they belong to. Geocodio's own ``address_lines``
    are not used: it writes that line house number first for every country,
    which is the wrong order for Mexican addresses.
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

    def _fetch(self, records: List[SourceRecord]) -> Iterator[Tuple[SourceRecord, Dict[str, Any]]]:
        """
        Posts records in batches, yielding each record with its response entry.

        Yielding per batch rather than per run means an interrupted job keeps
        every batch that already came back.

        Parameters
        ----------
        records : List[SourceRecord]
            The source rows to geocode.

        Return
        ----------
        Iterator[Tuple[SourceRecord, Dict[str, Any]]]
            Each record paired with its raw Geocodio response entry.
        """
        for start in range(0, len(records), self.BATCH_SIZE):
            yield from self._fetch_batch(records[start : start + self.BATCH_SIZE])

    def _fetch_batch(self, batch: List[SourceRecord]) -> Iterator[Tuple[SourceRecord, Dict[str, Any]]]:
        """Posts one batch, verifies its entry count, and matches entries back by position."""
        entries = self._post_batch(batch)
        if len(entries) != len(batch):
            raise ValueError(f"Geocodio returned {len(entries)} entries for {len(batch)} submitted records; the batch response may have changed")
        yield from zip(batch, entries)

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

    def parse(self, raw: Dict[str, Any]) -> GeocodeResult:
        """
        Converts one Geocodio response entry into a normalized GeocodeResult.

        The graded accuracy is capped at the tier implied by ``accuracy_type`` so
        an interpolated or centroid match cannot report rooftop precision on the
        strength of the echoed address fields.

        Parameters
        ----------
        raw : Dict[str, Any]
            One Geocodio response entry.

        Return
        ----------
        GeocodeResult
            The normalized, graded result that entry describes.
        """
        matches = raw.get("response", {}).get("results", [])
        if not matches:
            return GeocodeResult(match_notes="No match", raw=raw)

        components = matches[0].get("address_components", {})
        result = self._build_result(raw, components)
        result.accuracy = grade_accuracy(result, self._accuracy_cap(result, components))
        return result

    def _accuracy_cap(self, result: GeocodeResult, components: Dict[str, str]) -> AccuracyLevel:
        """
        Returns the highest accuracy the match can claim.

        The ``accuracy_type`` sets the ceiling, and an address without a house
        number lowers it to street level: the street alone resolves no finer
        than the geographic centre of the whole street.
        """
        cap = self.ACCURACY_TYPE_LEVELS.get(result.location_type, AccuracyLevel.NONE)
        if components.get("number"):
            return cap
        return min(cap, AccuracyLevel.STREET)

    def _build_result(self, raw: Dict[str, Any], components: Dict[str, str]) -> GeocodeResult:
        """
        Maps the best Geocodio candidate to a GeocodeResult without scoring its accuracy.

        The whole response entry is kept as the raw value rather than the single
        candidate it was read from, so what is cached and reported is what
        Geocodio actually said.
        """
        match = raw["response"]["results"][0]
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
            raw=raw,
        )

    @staticmethod
    def _street_address(components: Dict[str, str]) -> str:
        """
        Assembles the street address from the response components in the convention of the match's country.

        Geocodio reports no sublocality of its own, so a Mexican address carries
        only the street, house number and any subpremise.
        """
        return format_street_address(
            components.get("country", ""),
            components.get("formatted_street", ""),
            components.get("number", ""),
            components.get("secondarynumber", ""),
        )
