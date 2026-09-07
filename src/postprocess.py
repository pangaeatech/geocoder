#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — result post-processing

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import math
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from .api import GeocodeResult, SourceRecord
from .regions import COUNTRY_CODE_NAMES, SUBDIVISION_NAMES

COMPARE_FIELDS = ["NAME", "ADDRESS", "CITY", "STATEPROV", "POSTALCODE", "COUNTRY"]

DISTANCE_HEADERS = ["MATCH_LATITUDE_M", "MATCH_LONGITUDE_M", "MATCH_DISTANCE_M"]

MATCH_HEADERS = [f"MATCH_{field_name}" for field_name in COMPARE_FIELDS] + DISTANCE_HEADERS

EARTH_RADIUS_M = 6371008.8

MAX_ABBREVIATION_LENGTH = 4

FIELD_CODE_NAMES = {"STATEPROV": SUBDIVISION_NAMES, "COUNTRY": COUNTRY_CODE_NAMES}

ABBREVIATIONS = {
    "apt": "apartment",
    "av": "avenue",
    "ave": "avenue",
    "bldg": "building",
    "blvd": "boulevard",
    "cir": "circle",
    "ct": "court",
    "dr": "drive",
    "e": "east",
    "fl": "floor",
    "ft": "fort",
    "hts": "heights",
    "hwy": "highway",
    "ln": "lane",
    "mt": "mount",
    "n": "north",
    "ne": "northeast",
    "nw": "northwest",
    "pkwy": "parkway",
    "rd": "road",
    "rm": "room",
    "s": "south",
    "se": "southeast",
    "sq": "square",
    "st": "street",
    "ste": "suite",
    "sw": "southwest",
    "trl": "trail",
    "w": "west",
}


def _tokenize(value: str) -> List[str]:
    """Folds a value to accent-free lowercase words, dropping punctuation."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    unaccented = "".join(character for character in decomposed if not unicodedata.combining(character))
    return re.sub(r"[^0-9a-z]+", " ", unaccented).split()


def _tokens_match(left: str, right: str) -> bool:
    """
    Reports whether two words are the same word, one of them abbreviated.

    Numbers never abbreviate one another: a street number is the part of an
    address a comparison most needs to hold to the letter, so 1 and 1234 are
    different addresses rather than a shortened spelling of one.
    """
    if ABBREVIATIONS.get(left, left) == ABBREVIATIONS.get(right, right):
        return True

    short, long = sorted([left, right], key=len)
    return not short.isdigit() and len(short) <= MAX_ABBREVIATION_LENGTH and long.startswith(short)


def _is_subsequence(part: List[str], whole: List[str]) -> bool:
    """Reports whether part appears within whole in order, with words missing."""
    if len(part) >= len(whole):
        return False

    remaining = iter(whole)
    return all(any(_tokens_match(word, candidate) for candidate in remaining) for word in part)


def _overlaps(left: List[str], right: List[str]) -> bool:
    """Reports whether at least half of the shorter value's words are shared."""
    shared = sum(1 for word in left if any(_tokens_match(word, candidate) for candidate in right))
    return shared * 2 >= min(len(left), len(right))


def _expand_code(tokens: List[str], code_names: Optional[Dict[str, str]]) -> List[str]:
    """Replaces a known region code with the words of the name it stands for."""
    name = code_names.get(tokens[0].upper()) if code_names and len(tokens) == 1 else None
    return _tokenize(name) if name else tokens


def _compare_tokens(source_tokens: List[str], result_tokens: List[str]) -> str:
    """Grades two folded word lists, from identical wording down to unrelated."""
    if not source_tokens or not result_tokens:
        return "DIFFERENT"
    if source_tokens == result_tokens:
        return "FORMATTING"
    if len(source_tokens) == len(result_tokens) and all(_tokens_match(*pair) for pair in zip(source_tokens, result_tokens)):
        return "ABBREVIATED"
    if _is_subsequence(source_tokens, result_tokens):
        return "TRUNCATED"
    if _is_subsequence(result_tokens, source_tokens):
        return "EXTRA"
    return "PARTIAL" if _overlaps(source_tokens, result_tokens) else "DIFFERENT"


def compare_values(source: str, result: str, code_names: Optional[Dict[str, str]] = None) -> str:
    """
    Grades how closely a source cell matches the result the provider returned.

    The grades run from an identical string down to unrelated text: EXACT,
    FORMATTING (case, spacing, or punctuation only), ABBREVIATED (the same words
    with one side shortened, e.g. "St" for "Street"), TRUNCATED (the source is
    missing whole parts the result carries), EXTRA (the result dropped parts the
    source carried), PARTIAL (they share words), and DIFFERENT. A blank on one
    side is reported as ADDED or MISSING, and a blank on both as BLANK.

    Providers answer with codes where the source often spells the name out, so a
    field with a known set of codes is compared with both sides expanded.

    Parameters
    ----------
    source : str
        The value taken from the input workbook.
    result : str
        The corresponding value returned by the provider.
    code_names : Optional[Dict[str, str]]
        The codes this field may be written in, mapped to the names they stand
        for, so that a code and its spelled-out name grade as ABBREVIATED.

    Return
    ----------
    str
        The grade describing the relationship between the two values.
    """
    if not source and not result:
        return "BLANK"
    if not source:
        return "ADDED"
    if not result:
        return "MISSING"
    if source == result:
        return "EXACT"

    source_tokens = _tokenize(source)
    result_tokens = _tokenize(result)
    if source_tokens != result_tokens and _expand_code(source_tokens, code_names) == _expand_code(result_tokens, code_names):
        return "ABBREVIATED"
    return _compare_tokens(source_tokens, result_tokens)


def _coordinates(latitude: str, longitude: str) -> Optional[Tuple[float, float]]:
    """Parses a latitude and longitude pair, or None when either is unusable."""
    try:
        return float(latitude), float(longitude)
    except ValueError:
        return None


def compare_coordinates(record: SourceRecord, result: GeocodeResult) -> List:
    """
    Measures how far the result moved from the source coordinates, in meters.

    The offsets are signed and reported as the result relative to the source, so
    a positive latitude offset means the result sits north of the source. The
    latitude and longitude offsets give the direction of the shift and the
    great-circle distance gives its true magnitude; the longitude offset narrows
    with latitude, since a degree of longitude does. All three cells are left
    blank when either side lacks usable coordinates.

    Parameters
    ----------
    record : SourceRecord
        The source row, which may carry no coordinates at all.
    result : GeocodeResult
        The geocoded result for that row.

    Return
    ----------
    List
        The north-south offset, east-west offset, and great-circle distance.
    """
    source = _coordinates(record.latitude, record.longitude)
    matched = _coordinates(result.latitude, result.longitude)
    if source is None or matched is None:
        return ["", "", ""]

    source_latitude, source_longitude = (math.radians(value) for value in source)
    result_latitude, result_longitude = (math.radians(value) for value in matched)
    latitude_delta = result_latitude - source_latitude
    longitude_delta = result_longitude - source_longitude

    northing = EARTH_RADIUS_M * latitude_delta
    easting = EARTH_RADIUS_M * longitude_delta * math.cos((source_latitude + result_latitude) / 2)

    haversine = math.sin(latitude_delta / 2) ** 2 + math.cos(source_latitude) * math.cos(result_latitude) * math.sin(longitude_delta / 2) ** 2
    distance = 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(haversine)))

    return [round(northing, 1), round(easting, 1), round(distance, 1)]


def compare_record(record: SourceRecord, result: GeocodeResult) -> List:
    """
    Builds the MATCH_ cells comparing one source row against its result.

    Parameters
    ----------
    record : SourceRecord
        The source row to compare.
    result : GeocodeResult
        The geocoded result for that row.

    Return
    ----------
    List
        One grade per compared field, followed by the coordinate offsets.
    """
    grades = [
        compare_values(getattr(record, name.lower()), getattr(result, f"result_{name.lower()}"), FIELD_CODE_NAMES.get(name))
        for name in COMPARE_FIELDS
    ]
    return grades + compare_coordinates(record, result)
