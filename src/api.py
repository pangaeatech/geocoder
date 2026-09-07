#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — provider base and shared types

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import os
import re
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

LEGAL_SUBDIVISION = r"(?:[NS][EW]|\d{1,2})"
SURVEY_GRID = r"\d{1,2}[-\s]\d{1,3}[-\s]\d{1,2}"

DOMINION_LAND_SURVEY = rf"""
    (?:{LEGAL_SUBDIVISION}[-\s]){{1,2}}         # quarter section and legal subdivision
    {SURVEY_GRID}                               # section, township and range
    (?:[-\s]?[WE]\s?[1-6]?M?|[-\s][1-6]M?)      # meridian, however it is written
  | {SURVEY_GRID}                               # section, township and range, unqualified
    [-\s]?[WE]\s?[1-6]M?                        # meridian, which must then be lettered and numbered
"""

NATIONAL_TOPOGRAPHIC_SYSTEM = r"""
    [A-L]-\d{1,3}-[A-L]                         # unit, block and quarter of the map sheet
    [-\s/]{0,2}                                 # separator, written inconsistently or omitted
    \d{2,3}-[A-P]-\d{1,2}                       # map sheet, series and area
"""

LEGAL_LAND_DESCRIPTION = re.compile(
    rf"\b(?:{DOMINION_LAND_SURVEY}|{NATIONAL_TOPOGRAPHIC_SYSTEM})\b",
    re.IGNORECASE | re.VERBOSE,
)

LEGAL_LAND_NOTE = "Legal land description withheld from the provider"
NO_ADDRESS_NOTE = "No address to geocode"


def strip_legal_land_description(value: str) -> str:
    """
    Removes any Canadian legal land description from the given value.

    Legal land descriptions locate an oil rig on a survey grid rather than on a
    street, and no supported provider covers either grid: the prairie provinces
    use the Dominion Land Survey (``01-17-040-06w4``) and British Columbia the
    National Topographic System (``A-51-I/94-O-10``). Left in a query they are
    misread as a street address and drag the match onto an unrelated road, so
    the surrounding text is kept and the description itself is dropped.

    Both grids are written inconsistently: a Dominion meridian may be lettered
    (``06w4``), spelled out (``06-W4M``) or reduced to its number (``19-4``),
    and a Topographic map sheet may be separated by a slash, a space, or nothing
    at all.

    A meridian reduced to a bare number or a bare letter is only recognized when
    the quarter section or legal subdivision precedes it, because ``5-10-15-2``
    on its own is indistinguishable from an ordinary hyphenated street address
    such as a lot or box number. A meridian carrying both its letter and its
    number is distinctive enough to stand alone.

    Whatever is left is only kept when it still holds a letter, since the digits
    stranded by a well identifier such as ``200 /D-050-E/094-H-05/ 00`` name
    nothing a geocoder can find.

    Parameters
    ----------
    value : str
        The address or city text to clean.

    Return
    ----------
    str
        The value without its legal land description, or an empty string when
        nothing locatable was left behind.
    """
    remainder = LEGAL_LAND_DESCRIPTION.sub(" ", value)
    if remainder == value:
        return value

    remainder = " ".join(remainder.split()).strip(" ,-/")
    return remainder if any(character.isalpha() for character in remainder) else ""


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
        """
        Joins the non-blank address components into a single query string.

        Any legal land description is stripped from the street and city first, so
        a rig row is queried by the province it sits in rather than by a grid
        reference no provider can resolve.
        """
        street = strip_legal_land_description(self.address)
        city = strip_legal_land_description(self.city)
        parts = [street, city, self.stateprov, self.postalcode, self.country]
        return ", ".join(part for part in parts if part)

    def has_legal_land_description(self) -> bool:
        """Reports whether the street or city holds a legal land description."""
        return any(LEGAL_LAND_DESCRIPTION.search(part) for part in (self.address, self.city))


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


def apply_legal_land_limit(record: SourceRecord, result: GeocodeResult) -> GeocodeResult:
    """
    Bounds a result at the precision its source row could ever support.

    A row carrying a legal land description is queried with that description
    stripped out, so the provider only ever saw the surrounding province and the
    match it returned describes that province rather than the survey parcel. The
    score is capped there and the result annotated, so a coincidentally
    street-level answer is not mistaken for the rig's location.

    Parameters
    ----------
    record : SourceRecord
        The source row the result was produced for.
    result : GeocodeResult
        The result to bound, modified in place.

    Return
    ----------
    GeocodeResult
        The same result, capped and annotated when the row named a parcel.
    """
    if not record.has_legal_land_description():
        return result

    result.accuracy = min(result.accuracy, AccuracyLevel.STATE)
    result.match_notes = "; ".join(note for note in (result.match_notes, LEGAL_LAND_NOTE) if note)
    return result


ROUTE_FIRST_COUNTRIES = {"MX"}


def format_street_address(country: str, street: str, number: str = "", subpremise: str = "", sublocality: str = "") -> str:
    """
    Assembles a street line in the convention of the country it belongs to.

    Most countries lead with the street number, but those in
    ROUTE_FIRST_COUNTRIES place it after the street, hyphenate any subpremise
    onto it, and append the sublocality, because a street number there is only
    unique within its sublocality.

    A street with no number still yields an address, since the street name alone
    locates the row to that street; the caller's accuracy cap grades such a
    result no higher than street level.

    Parameters
    ----------
    country : str
        The country code of the match, which selects the convention to follow.
    street : str
        The street name; a match without one yields no address.
    number : str
        The house number, when the match carries one.
    subpremise : str
        The unit within the premise, when the match carries one.
    sublocality : str
        The neighbourhood the house number is unique within, when the provider
        reports one.

    Return
    ----------
    str
        The assembled street line, or an empty string without a street.
    """
    if not street:
        return ""

    if country not in ROUTE_FIRST_COUNTRIES:
        return f"{number} {street}" if number else street

    if number and subpremise:
        number = f"{number}-{subpremise}"

    address = f"{street} {number}" if number else street
    return f"{address}, {sublocality}" if sublocality else address


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

    @staticmethod
    def unqueryable_result() -> GeocodeResult:
        """Returns the no-match a record with nothing left to query resolves to."""
        return GeocodeResult(match_notes=NO_ADDRESS_NOTE)

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
