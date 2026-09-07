#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — source record pre-processing

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import re
from typing import Callable, Dict, List, Optional

from .api import SourceRecord
from .regions import COUNTRY_ALIASES

PRE_HEADERS = ["PRE_FLAGS", "PRE_NOTES"]

BLANK_CHECKED_FIELDS = ["name", "address", "city", "stateprov", "postalcode", "country"]

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

ADDRESS_RANGE_RE = re.compile(r"^\d+\s*[-–]\s*\d+\s+\S")

ADDRESS_DIGIT_RE = re.compile(r"\d")

INVALID_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\ufffd]|_x[0-9A-Fa-f]{4}_")

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

LOST_ZERO_COUNTRIES = {"US", "MX"}

LOST_ZERO_RE = re.compile(r"^\d{3,4}$")

ZIP_PLUS_FOUR_RE = re.compile(r"^(\d{5})(\d{4})$")

DUPLICATE_FLAG = "DUPLICATE"
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
    """Flags an address whose text is a stand-in rather than a real location."""
    normalized = re.sub(r"[^0-9a-z]+", " ", record.address.casefold()).strip()
    if normalized and normalized in PLACEHOLDER_VALUES:
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


def _check_invalid_characters(record: SourceRecord) -> Dict[str, str]:
    """
    Flags replacement or control characters left behind by a bad encoding.

    A worksheet cannot hold a raw control character, since the XML it is stored
    as forbids one, so Excel writes it as the literal escape ``_x000b_``; both
    that escape and a character that survived intact are reported.
    """
    for field_name in BLANK_CHECKED_FIELDS:
        if INVALID_CHARACTER_RE.search(getattr(record, field_name)):
            return {"INVALID_CHARACTERS": field_name}
    return {}


def _check_postalcode(record: SourceRecord) -> Dict[str, str]:
    """
    Flags a postal code that does not fit the format of its country.

    Two shapes are reported separately from an unusable code, because both are
    the right digits written the wrong way and are mechanical to repair: a short
    all-digit code in a country whose codes are fixed-length digits has had its
    leading zeros eaten by a spreadsheet storing the column as numbers, and a
    nine-digit U.S. code is a ZIP+4 that lost its hyphen.
    """
    country = COUNTRY_ALIASES.get(record.country.casefold().strip("."))
    pattern = POSTALCODE_PATTERNS.get(country)
    if not record.postalcode or not pattern or pattern.match(record.postalcode):
        return {}

    if country in LOST_ZERO_COUNTRIES and LOST_ZERO_RE.match(record.postalcode):
        return {"TRUNCATED_POSTALCODE": f"{record.postalcode} is missing its leading zero(s)"}

    plus_four = ZIP_PLUS_FOUR_RE.match(record.postalcode) if country == "US" else None
    if plus_four:
        return {"UNFORMATTED_POSTALCODE": f"{record.postalcode} should be written {plus_four[1]}-{plus_four[2]}"}
    return {"INVALID_POSTALCODE": f"{record.postalcode} is not a {country} postal code"}


def _check_coordinates(record: SourceRecord) -> Dict[str, str]:
    """Flags source coordinates that are incomplete, unparseable, or off-globe."""
    if not record.latitude and not record.longitude:
        return {}
    if not record.latitude or not record.longitude:
        return {"INVALID_COORDINATES": "only one of latitude and longitude is set"}

    try:
        latitude = float(record.latitude)
        longitude = float(record.longitude)
    except ValueError:
        return {"INVALID_COORDINATES": f"{record.latitude}, {record.longitude} are not numeric"}

    if abs(latitude) > 90 or abs(longitude) > 180:
        return {"INVALID_COORDINATES": f"{latitude}, {longitude} is outside the globe"}
    if latitude == 0 and longitude == 0:
        return {"INVALID_COORDINATES": "null island"}
    return {}


CHECKS: List[Callable[[SourceRecord], Dict[str, str]]] = [
    _check_placeholder,
    _check_po_box,
    _check_rural_route,
    _check_intersection,
    _check_legal_description,
    _check_address_range,
    _check_street_number,
    _check_invalid_characters,
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


def _duplicate_key(record: SourceRecord) -> str:
    """Builds the normalized address key two rows must share to be duplicates."""
    parts = [record.address, record.city, record.stateprov, record.postalcode, record.country]
    return re.sub(r"[^0-9a-z]+", " ", " ".join(parts).casefold()).strip()


def check_records(records: List[SourceRecord], blank_fields: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """
    Checks every record in a worksheet and adds the checks that span rows.

    A row whose address is blank or a placeholder is left out of the duplicate
    count: it has nothing to be a duplicate of, and its own flags already say so.

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
    keys = ["" if record_flags.keys() & UNUSABLE_ADDRESS_FLAGS else _duplicate_key(record) for record, record_flags in zip(records, flags)]

    counts: Dict[str, int] = {}
    for key in filter(None, keys):
        counts[key] = counts.get(key, 0) + 1

    for key, record_flags in zip(keys, flags):
        others = counts.get(key, 0) - 1
        if others > 0:
            record_flags[DUPLICATE_FLAG] = f"address is shared with {others} other row(s)"
    return flags


def format_flags(flags: Dict[str, str]) -> List[str]:
    """
    Renders one record's flags as the PRE_FLAGS and PRE_NOTES cell values.

    Parameters
    ----------
    flags : Dict[str, str]
        The flags raised for a record, mapped to their notes.

    Return
    ----------
    cells : List[str]
        The comma-joined flag names and the notes of the flags that carry one.
    """
    return [
        ", ".join(flags),
        "; ".join(f"{name}: {note}" for name, note in flags.items() if note),
    ]
