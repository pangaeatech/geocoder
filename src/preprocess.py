#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — source record pre-processing

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import math
import re
from typing import Callable, Dict, List, Optional

from .api import SourceRecord
from .regions import COUNTRY_NAMES, COUNTRY_SUBDIVISIONS, country_code, subdivision_code, within_country
from .text import words

PRE_HEADERS = ["PRE_FLAGS"]

QUERY_FIELDS = ["address", "city", "stateprov", "postalcode", "country"]

BLANK_CHECKED_FIELDS = ["name"] + QUERY_FIELDS

PLACEHOLDER_VALUES = {
    "-",
    ".",
    "n a",
    "na",
    "no address",
    "none",
    "not applicable",
    "not available",
    "null",
    "same",
    "same as above",
    "tbd",
    "unk",
    "unknown",
    "x",
}

PO_BOX_RE = re.compile(r"\b(?:p\.?\s*o\.?\s*box|post\s+office\s+box|postal\s+box|pmb\s*#?\s*\d|box\s+#?\s*\d)", re.IGNORECASE)

RURAL_ROUTE_RE = re.compile(r"\b(?:r\.?\s*r\.?|rural\s+route|h\.?\s*c\.?\s*r?|highway\s+contract)\s*#?\s*\d+\b", re.IGNORECASE)

INTERSECTION_RE = re.compile(r"\bcorner\s+(?:of|at)\b|\bintersection\s+of\b|\s&\s|\s/\s", re.IGNORECASE)

ADDRESS_RANGE_RE = re.compile(r"^\d+\s*[-–]\s*\d+(?=\s+\S)")

ADDRESS_DIGIT_RE = re.compile(r"\d")

INVALID_CHARACTER_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f\ufffd]|_x[0-9A-Fa-f]{4}_")

EMBEDDED_WHITESPACE_RE = re.compile(r"[\t\n\v\f\r]")

MOJIBAKE_RE = re.compile("[\u00c3\u00c2\u00e2][\u0080-\u00ff\u2013-\u20ac]")

FIELD_PATTERNS = [
    ("INVALID_CHARACTERS", INVALID_CHARACTER_RE),
    ("EMBEDDED_WHITESPACE", EMBEDDED_WHITESPACE_RE),
    ("MOJIBAKE", MOJIBAKE_RE),
]

CARE_OF_RE = re.compile(r"\b(?:c\s*[/\\]\s*o|care\s+of|attn|attention|dba|d\s*/\s*b\s*/\s*a)\b", re.IGNORECASE)

LEGAL_STRONG_PATTERNS = [
    re.compile(r"\b[ns][ew]\s*(?:1/4|¼|qtr|quarter)", re.IGNORECASE),
    re.compile(r"\b(?:sec|section)\.?\s*\d{1,2}\b[^,;]{0,40}\b(?:twp|township|t)\.?\s*\d{1,3}\s*[ns]\b", re.IGNORECASE),
    re.compile(r"\b(?:twp|township|t)\.?\s*\d{1,3}\s*[ns]\b[^,;]{0,40}\b(?:rge|range|r)\.?\s*\d{1,3}\s*[ew]\b", re.IGNORECASE),
    re.compile(r"\bprincipal\s+meridian\b|\b\d+(?:st|nd|rd|th)\s+p\.?\s*m\.?\b", re.IGNORECASE),
    re.compile(r"\bmetes\s+and\s+bounds\b|\bthence\b", re.IGNORECASE),
]

LEGAL_WEAK_PATTERNS = [
    re.compile(r"\blot\s*#?\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bbl(?:oc)?k\.?\s*\d+\b", re.IGNORECASE),
    re.compile(r"\b(?:parcel|tract)\s*#?\s*[\w-]+\b", re.IGNORECASE),
    re.compile(r"\b(?:subdivision|plat|abstract)\b", re.IGNORECASE),
    re.compile(r"\b(?:sec|section)\.?\s*\d{1,2}\b", re.IGNORECASE),
    re.compile(r"\b(?:twp|township)\.?\s*\d{1,3}\b", re.IGNORECASE),
    re.compile(r"\b(?:rge|range)\.?\s*\d{1,3}\s*[ew]\b", re.IGNORECASE),
    re.compile(r"\b[ns]\s*\d{1,3}\s*(?:°|deg\b)", re.IGNORECASE),
]

POSTALCODE_PATTERNS = {
    "US": re.compile(r"^\d{5}(?:-\d{4})?$"),
    "CA": re.compile(r"^[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d$"),
    "MX": re.compile(r"^\d{5}$"),
}

LOCALITY_FIELDS = ["city", "stateprov", "postalcode"]

MIN_REPEATED_LOCALITY = 2

LOST_ZERO_COUNTRIES = {"US", "MX"}

LOST_ZERO_RE = re.compile(r"^\d{3,4}$")

ZIP_PLUS_FOUR_RE = re.compile(r"^(\d{5})(\d{4})$")

DUPLICATE_FLAG = "DUPLICATE"
SHARED_ADDRESS_FLAG = "SHARED_ADDRESS"
NO_STREET_NUMBER_FLAG = "NO_STREET_NUMBER"

UNUSABLE_ADDRESS_FLAGS = {"BLANK_ADDRESS", "PLACEHOLDER"}

STREET_NUMBER_EXEMPT_FLAGS = {
    "PO_BOX",
    "RURAL_ROUTE",
    "INTERSECTION",
    "LEGAL_DESCRIPTION",
    "PLACEHOLDER",
    "BLANK_ADDRESS",
}


def _check_placeholder(record: SourceRecord) -> Dict[str, str]:
    """
    Flags an address whose text is a stand-in rather than a real location.

    Folding the text down to bare words is what lets "N/A" and "n a" read as
    the one stand-in, but it empties an address written as a single mark, so a
    value that folds away to nothing is matched as it was typed instead.
    """
    normalized = " ".join(words(record.address)) or record.address.strip()
    if normalized in PLACEHOLDER_VALUES:
        return {"PLACEHOLDER": record.address}
    return {}


def _check_po_box(record: SourceRecord) -> Dict[str, str]:
    """Flags a post office box, which locates a mail drop rather than a site."""
    match = PO_BOX_RE.search(record.address)
    return {"PO_BOX": match.group(0)} if match else {}


def _check_rural_route(record: SourceRecord) -> Dict[str, str]:
    """Flags a rural route or highway contract box, which has no street number."""
    match = RURAL_ROUTE_RE.search(record.address)
    return {"RURAL_ROUTE": match.group(0)} if match else {}


def _check_intersection(record: SourceRecord) -> Dict[str, str]:
    """Flags an address given as a street intersection rather than a number."""
    match = INTERSECTION_RE.search(record.address)
    return {"INTERSECTION": match.group(0).strip()} if match else {}


def _check_legal_description(record: SourceRecord) -> Dict[str, str]:
    """
    Flags a legal land description in the name or address field.

    Such descriptions (public land survey calls, lot and block references, metes
    and bounds) identify a parcel on a plat rather than a mailing address, so no
    geocoder can resolve them. A single unambiguous survey pattern is enough to
    flag; the weaker patterns each appear in ordinary addresses too, so two of
    them must agree before the field is called a legal description.
    """
    for field_name in ["address", "name"]:
        value = getattr(record, field_name)
        if not value:
            continue

        strong = next((match for match in (pattern.search(value) for pattern in LEGAL_STRONG_PATTERNS) if match), None)
        if strong:
            return {"LEGAL_DESCRIPTION": f"{field_name}: {strong.group(0).strip()}"}

        weak = [match.group(0).strip() for match in (pattern.search(value) for pattern in LEGAL_WEAK_PATTERNS) if match]
        if len(weak) > 1:
            return {"LEGAL_DESCRIPTION": f"{field_name}: {', '.join(weak)}"}
    return {}


def _check_address_range(record: SourceRecord) -> Dict[str, str]:
    """Flags a street number given as a range, which resolves to one endpoint."""
    match = ADDRESS_RANGE_RE.search(record.address)
    return {"ADDRESS_RANGE": match.group(0).strip()} if match else {}


def _check_street_number(record: SourceRecord) -> Dict[str, str]:
    """
    Flags an address that carries no number at all.

    Where the number sits is a matter of local convention — it leads in the
    United States and Canada and trails in Mexico, and grid addresses put
    letters around it — so only its total absence is worth reporting.
    """
    if record.address and not ADDRESS_DIGIT_RE.search(record.address):
        return {NO_STREET_NUMBER_FLAG: ""}
    return {}


def _check_care_of(record: SourceRecord) -> Dict[str, str]:
    """Flags a routing instruction the provider will read as part of the street."""
    match = CARE_OF_RE.search(record.address)
    return {"CARE_OF": match.group(0)} if match else {}


def _contains(haystack: List[str], needle: List[str]) -> bool:
    """Reports whether one word list appears whole and in order inside another."""
    return bool(needle) and any(haystack[start : start + len(needle)] == needle for start in range(len(haystack) - len(needle) + 1))


def _check_redundant_address(record: SourceRecord) -> Dict[str, str]:
    """
    Flags an address that repeats the city, state, or postal code columns.

    One repeated field proves nothing, since a street may be named after the
    town it leads to; two mean the address was pasted whole from a single-column
    source and will reach the provider with its tail said twice.
    """
    address = words(record.address)
    repeated = [name for name in LOCALITY_FIELDS if _contains(address, words(getattr(record, name)))]
    if len(repeated) < MIN_REPEATED_LOCALITY:
        return {}
    return {"REDUNDANT_ADDRESS": f"address repeats {', '.join(repeated)}"}


def _check_field_text(record: SourceRecord) -> Dict[str, str]:
    """
    Flags the text damage a bad export leaves in the address-forming fields.

    Each kind is reported once, naming the first field it appears in. A
    worksheet cannot hold a raw control character, since the XML it is stored as
    forbids one, so Excel writes it as the literal escape ``_x000b_``; both that
    escape and a character that survived intact are reported. A line break or a
    tab is legal in a cell but reaches the provider inside the value, and the
    doubled accents a UTF-8 file re-read as Latin-1 leaves behind corrupt it.
    """
    flags = {}
    for flag, pattern in FIELD_PATTERNS:
        field_name = next((name for name in BLANK_CHECKED_FIELDS if pattern.search(getattr(record, name))), None)
        if field_name:
            flags[flag] = field_name
    return flags


def _check_country(record: SourceRecord) -> Dict[str, str]:
    """Flags a country outside the set this tool's providers can geocode."""
    if record.country and not country_code(record.country):
        return {"UNSUPPORTED_COUNTRY": f"{record.country} is not one of {', '.join(COUNTRY_NAMES.values())}"}
    return {}


def _check_stateprov(record: SourceRecord) -> Dict[str, str]:
    """
    Flags a state or province the row's country does not have.

    Only a country with a subdivision table is checked, so a Mexican state and
    a country outside this tool's reach both pass without comment.
    """
    country = country_code(record.country)
    if not record.stateprov or country not in COUNTRY_SUBDIVISIONS or subdivision_code(country, record.stateprov):
        return {}
    return {"INVALID_STATEPROV": f"{record.stateprov} is not a {COUNTRY_NAMES[country]} state or province"}


def _check_postalcode(record: SourceRecord) -> Dict[str, str]:
    """
    Flags a postal code that does not fit the format of its country.

    Two shapes are reported separately from an unusable code, because both are
    the right digits written the wrong way and are mechanical to repair: a short
    all-digit code in a country whose codes are fixed-length digits has had its
    leading zeros eaten by a spreadsheet storing the column as numbers, and a
    nine-digit U.S. code is a ZIP+4 that lost its hyphen.
    """
    country = country_code(record.country)
    pattern = POSTALCODE_PATTERNS.get(country or "")
    if not record.postalcode or not pattern or pattern.match(record.postalcode):
        return {}

    if country in LOST_ZERO_COUNTRIES and LOST_ZERO_RE.match(record.postalcode):
        return {"TRUNCATED_POSTALCODE": f"{record.postalcode} is missing its leading zero(s)"}

    plus_four = ZIP_PLUS_FOUR_RE.match(record.postalcode) if country == "US" else None
    if plus_four:
        return {"UNFORMATTED_POSTALCODE": f"{record.postalcode} should be written {plus_four[1]}-{plus_four[2]}"}
    return {"INVALID_POSTALCODE": f"{record.postalcode} is not a {country} postal code"}


def _coordinate_problem(latitude: float, longitude: float) -> str:
    """Names what is wrong with a parsed coordinate pair, or a blank when nothing is."""
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return f"{latitude}, {longitude} is not a finite coordinate"
    if abs(latitude) > 90 or abs(longitude) > 180:
        return f"{latitude}, {longitude} is outside the globe"
    return "null island" if latitude == 0 and longitude == 0 else ""


def _check_coordinates(record: SourceRecord) -> Dict[str, str]:
    """
    Flags source coordinates that are incomplete, unparseable, or in the wrong place.

    A pair that is a valid point on the globe is measured once more against the
    extent of the country the row claims, which is what catches a latitude and
    longitude entered the wrong way round or with a sign dropped.
    """
    if not record.latitude and not record.longitude:
        return {}
    if not record.latitude or not record.longitude:
        return {"INVALID_COORDINATES": "only one of latitude and longitude is set"}

    try:
        latitude = float(record.latitude)
        longitude = float(record.longitude)
    except ValueError:
        return {"INVALID_COORDINATES": f"{record.latitude}, {record.longitude} are not numeric"}

    problem = _coordinate_problem(latitude, longitude)
    if problem:
        return {"INVALID_COORDINATES": problem}

    country = country_code(record.country)
    if not within_country(country, latitude, longitude):
        return {"COORDINATES_OUTSIDE_COUNTRY": f"{latitude}, {longitude} is not in {COUNTRY_NAMES[country or '']}"}
    return {}


CHECKS: List[Callable[[SourceRecord], Dict[str, str]]] = [
    _check_placeholder,
    _check_po_box,
    _check_rural_route,
    _check_intersection,
    _check_legal_description,
    _check_address_range,
    _check_street_number,
    _check_care_of,
    _check_redundant_address,
    _check_field_text,
    _check_country,
    _check_stateprov,
    _check_postalcode,
    _check_coordinates,
]


def check_record(record: SourceRecord, blank_fields: Optional[List[str]] = None) -> Dict[str, str]:
    """
    Runs every single-record check and returns the problems it found.

    A missing street number is only worth reporting when nothing else already
    explains it, so the flag is dropped when the address is a box, a route, an
    intersection, or a legal description.

    Parameters
    ----------
    record : SourceRecord
        The source row to inspect.
    blank_fields : Optional[List[str]]
        The fields whose empty cells are worth flagging; defaults to every
        address-forming field.

    Return
    ----------
    flags : Dict[str, str]
        Each flag raised, mapped to an explanatory note or a blank string.
    """
    if blank_fields is None:
        blank_fields = BLANK_CHECKED_FIELDS

    flags: Dict[str, str] = {f"BLANK_{name.upper()}": "" for name in blank_fields if not getattr(record, name)}
    for check in CHECKS:
        flags.update(check(record))

    if flags.keys() & STREET_NUMBER_EXEMPT_FLAGS:
        flags.pop(NO_STREET_NUMBER_FLAG, None)
    return flags


def _address_key(record: SourceRecord) -> str:
    """Builds the normalized address key two rows must share to sit together."""
    return " ".join(words(" ".join([record.address, record.city, record.stateprov, record.postalcode, record.country])))


def _count_keys(keys: List[str]) -> Dict[str, int]:
    """Counts how many rows carry each non-blank key."""
    counts: Dict[str, int] = {}
    for value in filter(None, keys):
        counts[value] = counts.get(value, 0) + 1
    return counts


def check_records(records: List[SourceRecord], blank_fields: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """
    Checks every record in a worksheet and adds the checks that span rows.

    Two rows at one address are only a duplicate when they are also the same
    place: several tenants of one building legitimately share an address, and
    that is worth knowing without being called a repeated row. A row whose
    address is blank or a placeholder is counted as neither: it has nothing to
    be a duplicate of, and its own flags already say so. A row that carries no
    name is the same case seen from the other side — nothing establishes it as
    the same place as its neighbour — so it can only be said to share.

    Parameters
    ----------
    records : List[SourceRecord]
        The source rows of a single worksheet, in reading order.
    blank_fields : Optional[List[str]]
        The fields whose empty cells are worth flagging; defaults to every
        address-forming field.

    Return
    ----------
    flags : List[Dict[str, str]]
        One flag mapping per record, aligned with records.
    """
    flags = [check_record(record, blank_fields) for record in records]
    usable = [not record_flags.keys() & UNUSABLE_ADDRESS_FLAGS for record_flags in flags]
    addresses = [_address_key(record) if keep else "" for record, keep in zip(records, usable)]
    names = [" ".join(words(record.name)) for record in records]
    rows = [f"{name}|{address}" if name and address else "" for name, address in zip(names, addresses)]

    address_counts = _count_keys(addresses)
    row_counts = _count_keys(rows)

    for address, row, record_flags in zip(addresses, rows, flags):
        repeats = row_counts.get(row, 0) - 1
        shared = address_counts.get(address, 0) - 1
        if repeats > 0:
            record_flags[DUPLICATE_FLAG] = f"name and address repeat on {repeats} other row(s)"
        elif shared > 0:
            record_flags[SHARED_ADDRESS_FLAG] = f"address is shared with {shared} other row(s)"
    return flags
