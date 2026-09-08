#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — Google Geocoding API provider

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

from typing import Dict, List

import requests

from .api import AccuracyLevel, GeocodeResult, Provider, SourceRecord, format_street_address, grade_accuracy, register


@register("google")
class GoogleProvider(Provider):
    """
    Geocoder backed by the Google Geocoding API.

    Google exposes no batch endpoint for forward geocoding, so records are
    queried one at a time and returned in the order received. Requests require an
    API key, resolved from --apiKey or the GOOGLE_GEOCODING_API_KEY environment
    variable.

    Accuracy is driven by the response ``location_type`` rather than the returned
    address fields: Google echoes a full formatted address even when it only
    interpolated a point or fell back to an area centroid, so grading the fields
    alone would report those coarser matches as rooftop precision. Each
    location_type therefore caps the graded score at the precision it actually
    represents, and a match resolved to a route with no street number is capped
    lower still.

    Street addresses are assembled from the response components in the
    convention of the country they belong to, since Mexican addresses order and
    punctuate their parts differently from North American ones.
    """

    requires_key = True

    ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
    TIMEOUT = 30

    LOCATION_TYPE_ACCURACY = {
        "ROOFTOP": AccuracyLevel.ROOFTOP,
        "RANGE_INTERPOLATED": AccuracyLevel.BLOCK,
        "GEOMETRIC_CENTER": AccuracyLevel.STREET,
        "APPROXIMATE": AccuracyLevel.CITY,
    }

    COMPONENT_FIELDS = {
        "street_number": "street_number",
        "subpremise": "subpremise",
        "route": "route",
        "sublocality_level_1": "sublocality",
        "locality": "result_city",
        "administrative_area_level_1": "result_stateprov",
        "postal_code": "result_postalcode",
        "country": "result_country",
    }

    def geocode(self, records: List[SourceRecord]) -> List[GeocodeResult]:
        """
        Geocodes each record with a single request and returns results in order.

        Parameters
        ----------
        records : List[SourceRecord]
            The source rows to geocode.

        Return
        ----------
        List[GeocodeResult]
            One result per input record, aligned by position.
        """
        return [self._geocode_one(record) for record in records]

    def _geocode_one(self, record: SourceRecord) -> GeocodeResult:
        """Queries one address and grades the parsed response by its location_type."""
        payload = self._request(record.address_string())
        status = payload.get("status", "UNKNOWN")

        if status == "OK":
            return self._parse_result(payload["results"][0])
        if status == "ZERO_RESULTS":
            return GeocodeResult(match_notes="No match", raw=payload)
        raise ValueError(f"Google geocoding failed with status {status!r}: {payload.get('error_message', '')}".strip())

    def _request(self, address: str) -> Dict:
        """Sends one geocoding request through the retrying request helper."""
        response = self._request_with_retry(
            lambda: requests.get(
                self.ENDPOINT,
                params={"address": address, "key": self.api_key},
                timeout=self.TIMEOUT,
            )
        )
        return response.json()

    def _parse_result(self, match: Dict) -> GeocodeResult:
        """
        Converts one Google result into a normalized GeocodeResult.

        The graded accuracy is capped at the tier implied by ``location_type`` so
        an interpolated or centroid match cannot report rooftop precision on the
        strength of the echoed address fields.
        """
        components = self._extract_components(match)
        result = self._build_result(match, components)
        result.accuracy = grade_accuracy(result, self._accuracy_cap(result, components))
        return result

    def _accuracy_cap(self, result: GeocodeResult, components: Dict[str, str]) -> AccuracyLevel:
        """
        Returns the highest accuracy the match can claim.

        The ``location_type`` sets the ceiling, and an address without a street
        number lowers it to street level: the route alone resolves no finer than
        the geographic centre of the whole street.
        """
        cap = self.LOCATION_TYPE_ACCURACY.get(result.location_type, AccuracyLevel.NONE)
        if components.get("street_number"):
            return cap
        return min(cap, AccuracyLevel.STREET)

    def _build_result(self, match: Dict, components: Dict[str, str]) -> GeocodeResult:
        """Maps a Google result to a GeocodeResult without scoring its accuracy."""
        geometry = match.get("geometry", {})
        location = geometry.get("location", {})

        return GeocodeResult(
            result_id=match.get("place_id", ""),
            result_address=self._street_address(components),
            result_city=components.get("result_city", ""),
            result_stateprov=components.get("result_stateprov", ""),
            result_postalcode=components.get("result_postalcode", ""),
            result_country=components.get("result_country", ""),
            latitude=str(location.get("lat", "")),
            longitude=str(location.get("lng", "")),
            match_type="partial" if match.get("partial_match") else "exact",
            location_type=geometry.get("location_type", ""),
            raw=match,
        )

    def _extract_components(self, match: Dict) -> Dict[str, str]:
        """Reduces Google address_components to the result fields the codebase tracks."""
        extracted: Dict[str, str] = {}
        for component in match.get("address_components", []):
            for component_type in component.get("types", []):
                field_name = self.COMPONENT_FIELDS.get(component_type)
                if field_name and field_name not in extracted:
                    extracted[field_name] = component.get("short_name", "")
        return extracted

    @staticmethod
    def _street_address(components: Dict[str, str]) -> str:
        """Assembles the street address from the response components in the convention of the result's country."""
        return format_street_address(
            components.get("result_country", ""),
            components.get("route", ""),
            components.get("street_number", ""),
            components.get("subpremise", ""),
            components.get("sublocality", ""),
        )
