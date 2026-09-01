#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — Google Geocoding API provider

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

from typing import Any, Dict, Iterator, List, Tuple

import requests

from .api import AccuracyLevel, GeocodeResult, Provider, SourceRecord, grade_accuracy, register


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
    represents.
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
        "route": "route",
        "locality": "result_city",
        "administrative_area_level_1": "result_stateprov",
        "postal_code": "result_postalcode",
        "country": "result_country",
    }

    def _fetch(self, records: List[SourceRecord]) -> Iterator[Tuple[SourceRecord, Dict[str, Any]]]:
        """
        Queries one address per request, yielding each response as it arrives.

        A status other than a match or an empty result means the request itself
        failed — a rejected key or an exhausted quota — so it is raised here rather
        than yielded, keeping a failure out of the cache and off the output.

        Parameters
        ----------
        records : List[SourceRecord]
            The source rows to geocode.

        Return
        ----------
        Iterator[Tuple[SourceRecord, Dict[str, Any]]]
            Each record paired with its raw Google response.

        Raises
        ----------
        ValueError
            If Google reports a status other than OK or ZERO_RESULTS.
        """
        for record in records:
            payload = self._request(record.address_string())
            status = payload.get("status", "UNKNOWN")
            if status not in ("OK", "ZERO_RESULTS"):
                raise ValueError(f"Google geocoding failed with status {status!r}: {payload.get('error_message', '')}".strip())
            yield record, payload

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

    def parse(self, raw: Dict[str, Any]) -> GeocodeResult:
        """
        Converts one Google response into a normalized GeocodeResult.

        The graded accuracy is capped at the tier implied by ``location_type`` so
        an interpolated or centroid match cannot report rooftop precision on the
        strength of the echoed address fields.
        """
        if raw.get("status") != "OK":
            return GeocodeResult(match_notes="No match", raw=raw)

        result = self._build_result(raw)
        cap = self.LOCATION_TYPE_ACCURACY.get(result.location_type, AccuracyLevel.NONE)
        result.accuracy = grade_accuracy(result, cap)
        return result

    def _build_result(self, raw: Dict[str, Any]) -> GeocodeResult:
        """
        Maps the best Google match to a GeocodeResult without scoring its accuracy.

        The whole response envelope is kept as the raw value rather than the single
        match it was read from, so what is cached and reported is what Google
        actually said.
        """
        match = raw["results"][0]
        components = self._extract_components(match)
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
            raw=raw,
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
        """
        Joins street number and route into a street address, or blank without a number.

        A route without a street number is only street-level, so leaving the
        address blank lets grade_accuracy fall through to the coarser field the
        result actually resolved.
        """
        number = components.get("street_number", "")
        route = components.get("route", "")
        if number and route:
            return f"{number} {route}"
        return ""
