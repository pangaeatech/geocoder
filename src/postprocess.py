#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — result post-processing

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import math
import re
from typing import Dict, List, Optional, Set, Tuple, Union

from .api import AccuracyLevel, GeocodeResult, SourceRecord
from .flags import format_flags
from .regions import COUNTRY_CODE_NAMES, SUBDIVISION_NAMES
from .text import words

COMPARE_FIELDS = ["NAME", "ADDRESS", "CITY", "STATEPROV", "POSTALCODE", "COUNTRY"]

STREET_NUMBER_HEADER = "MATCH_STREET_NUMBER"

DISTANCE_HEADERS = ["MATCH_LATITUDE_M", "MATCH_LONGITUDE_M", "MATCH_DISTANCE_M"]

SUMMARY_HEADERS = ["MATCH_SUMMARY", "POST_FLAGS"]

MATCH_HEADERS = [f"MATCH_{field_name}" for field_name in COMPARE_FIELDS] + [STREET_NUMBER_HEADER] + DISTANCE_HEADERS + SUMMARY_HEADERS

EARTH_RADIUS_M = 6371008.8

MAX_ABBREVIATION_LENGTH = 4

FAR_DISTANCE_M = 1000

LOW_ACCURACY = AccuracyLevel.STREET

FIELD_CODE_NAMES = {"STATEPROV": SUBDIVISION_NAMES, "COUNTRY": COUNTRY_CODE_NAMES}

GRADE_SEVERITY = {
    "BLANK": 0,
    "EXACT": 1,
    "FORMATTING": 2,
    "ABBREVIATED": 3,
    "TRUNCATED": 4,
    "ADDED": 5,
    "MISSING": 6,
    "EXTRA": 7,
    "PARTIAL": 8,
    "DIFFERENT": 9,
}

CHANGED_GRADES = {"PARTIAL", "MISSING", "DIFFERENT"}

CHANGE_FLAGS = {"CITY": "CITY_CHANGED", "STATEPROV": "STATE_CHANGED", "POSTALCODE": "POSTALCODE_CHANGED", "COUNTRY": "COUNTRY_CHANGED"}

STREET_NUMBER_RES = [re.compile(r"^\s*(\d+[a-z]?)\b", re.IGNORECASE), re.compile(r"\b(\d+[a-z]?)\s*$", re.IGNORECASE)]

ABBREVIATIONS = {
    "apt": ("apartment",),
    "av": ("avenue", "avenida"),
    "ave": ("avenue", "avenida"),
    "bldg": ("building",),
    "blvd": ("boulevard", "bulevar"),
    "cir": ("circle",),
    "col": ("colonia",),
    "ct": ("court",),
    "dr": ("drive",),
    "e": ("east",),
    "fl": ("floor",),
    "ft": ("fort",),
    "hts": ("heights",),
    "hwy": ("highway",),
    "ln": ("lane",),
    "mt": ("mount",),
    "n": ("north",),
    "ne": ("northeast",),
    "nw": ("northwest",),
    "pkwy": ("parkway",),
    "rd": ("road",),
    "rm": ("room",),
    "s": ("south",),
    "se": ("southeast",),
    "sq": ("square",),
    "st": ("street", "saint"),
    "ste": ("suite",),
    "sw": ("southwest",),
    "trl": ("trail",),
    "w": ("west",),
    "1st": ("first",),
    "2nd": ("second",),
    "3rd": ("third",),
    "4th": ("fourth",),
    "5th": ("fifth",),
    "6th": ("sixth",),
    "7th": ("seventh",),
    "8th": ("eighth",),
    "9th": ("ninth",),
    "10th": ("tenth",),
    "11th": ("eleventh",),
    "12th": ("twelfth",),
}


def _expansions(token: str) -> Set[str]:
    """Returns a word together with every word it is a known shorthand for."""
    return {token, *ABBREVIATIONS.get(token, ())}


def _tokens_match(left: str, right: str) -> bool:
    """
    Reports whether two words are the same word, one of them abbreviated.

    A word the table knows means what the table says it means, so "St" is a
    street or a saint but never Stanley; only a word with no listed expansion
    falls back to matching by prefix, which is how Mexican states abbreviate.
    Numbers never abbreviate one another: a street number is the part of an
    address a comparison most needs to hold to the letter, so 1 and 1234 are
    different addresses rather than a shortened spelling of one.
    """
    if _expansions(left) & _expansions(right):
        return True
    if left in ABBREVIATIONS or right in ABBREVIATIONS:
        return False

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
    return words(name) if name else tokens


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

    source_tokens = words(source)
    result_tokens = words(result)
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


def _street_number(address: str) -> str:
    """
    Pulls the house number off an address, wherever the country puts it.

    A leading number wins over a trailing one, so a United States or Canadian
    address is read correctly and a Mexican one falls back to the number its
    convention trails with. Both sides of a comparison are read the same way, so
    a Mexican address whose street name itself opens with a number still grades
    against the like part of the result.

    Parameters
    ----------
    address : str
        The address to read the number from.

    Return
    ----------
    str
        The house number, or a blank when the address carries none.
    """
    for pattern in STREET_NUMBER_RES:
        match = pattern.search(address)
        if match:
            return match[1]
    return ""


def summarize_grades(grades: List[str]) -> str:
    """
    Reduces one row's grades to the worst of them, for sorting and filtering.

    A field the provider answered differently outranks one it did not answer at
    all, since most providers return no name and a row would otherwise summarize
    as MISSING however well its address matched. Severity follows GRADE_SEVERITY.

    Parameters
    ----------
    grades : List[str]
        Every grade the row was given.

    Return
    ----------
    str
        The grade that most needs a human to look at it, or BLANK for a row
        with nothing to compare.
    """
    return max(grades, key=lambda grade: GRADE_SEVERITY.get(grade, 0), default="BLANK")


def flag_result(result: GeocodeResult, grades: Dict[str, str], distance: Union[float, str]) -> Dict[str, str]:
    """
    Flags the results whose own metadata says they are worth a second look.

    A field the provider rewrote rather than merely reformatted is called out by
    name, because a changed city, state, country, or postal code almost always
    means the query landed somewhere else entirely rather than that the source
    was untidy. The coordinate flag fires only when the source had coordinates
    of its own to disagree with.

    Parameters
    ----------
    result : GeocodeResult
        The geocoded result for one row.
    grades : Dict[str, str]
        Each compared field name mapped to the grade it was given.
    distance
        The great-circle distance from the source coordinates, or a blank.

    Return
    ----------
    flags : Dict[str, str]
        Each flag raised, mapped to an explanatory note or a blank string.
    """
    if not result.latitude and not result.longitude:
        return {"NO_MATCH": result.match_notes}

    flags = {}
    if result.accuracy and result.accuracy < LOW_ACCURACY:
        level = next((candidate for candidate in AccuracyLevel if candidate == result.accuracy), AccuracyLevel.NONE)
        flags["LOW_ACCURACY"] = f"resolved no finer than {level.name.lower()}"
    flags.update({flag: "" for field_name, flag in CHANGE_FLAGS.items() if grades.get(field_name) in CHANGED_GRADES})
    if isinstance(distance, float) and distance > FAR_DISTANCE_M:
        flags["FAR_FROM_SOURCE"] = f"{round(distance / 1000, 1)} km from the source coordinates"
    return flags


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
        One grade per compared field, the house-number grade, the coordinate
        offsets, the worst grade of the row, and the flags the result raised,
        each with the note explaining it.
    """
    grades = {
        name: compare_values(getattr(record, name.lower()), getattr(result, f"result_{name.lower()}"), FIELD_CODE_NAMES.get(name))
        for name in COMPARE_FIELDS
    }
    grades[STREET_NUMBER_HEADER] = compare_values(_street_number(record.address), _street_number(result.result_address))

    offsets = compare_coordinates(record, result)
    flags = flag_result(result, grades, offsets[-1])
    return list(grades.values()) + offsets + [summarize_grades(list(grades.values())), format_flags(flags)]
