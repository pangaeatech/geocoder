#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder Post-processing Tests

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import pytest

from src.api import GeocodeResult, SourceRecord
from src.postprocess import FIELD_CODE_NAMES, compare_coordinates, compare_record, compare_values, flag_result, summarize_grades


@pytest.mark.parametrize(
    "source,result,expected",
    [
        ("", "", "BLANK"),
        ("", "Anytown", "ADDED"),
        ("Anytown", "", "MISSING"),
        ("Anytown", "Anytown", "EXACT"),
        ("Apt #G", "APT G", "FORMATTING"),
        ("Montréal", "MONTREAL", "FORMATTING"),
        ("123 Main St", "123 Main Street", "ABBREVIATED"),
        ("CA", "California", "ABBREVIATED"),
        ("123 Main St", "123 N Main St Apt 4", "TRUNCATED"),
        ("20500", "20500-0003", "TRUNCATED"),
        ("123 N Main St Apt 4", "123 Main St", "EXTRA"),
        ("1 Main St", "1234 Main St", "PARTIAL"),
        ("100 Main St", "10 Main St", "PARTIAL"),
        ("123 Main St", "123 Main Ave", "PARTIAL"),
        ("123 N 1st Ave", "123 North First Avenue", "ABBREVIATED"),
        ("St Louis", "Stanley Louis", "PARTIAL"),
        ("St Louis", "Saint Louis", "ABBREVIATED"),
        ("123 Main St", "987 Elm Boulevard", "DIFFERENT"),
        ("北京", "Beijing", "DIFFERENT"),
    ],
)
def test_compare_values_grades(source, result, expected):
    """Each pair of values is graded by how far the result moved from the source."""
    assert compare_values(source, result) == expected


@pytest.mark.parametrize(
    "field,source,result,expected",
    [
        ("STATEPROV", "Texas", "TX", "ABBREVIATED"),
        ("STATEPROV", "New Jersey", "NJ", "ABBREVIATED"),
        ("STATEPROV", "Québec", "QC", "ABBREVIATED"),
        ("STATEPROV", "Jalisco", "Jal.", "ABBREVIATED"),
        ("STATEPROV", "Missouri", "MT", "DIFFERENT"),
        ("COUNTRY", "United States", "US", "ABBREVIATED"),
        ("COUNTRY", "USA", "US", "ABBREVIATED"),
        ("COUNTRY", "Canada", "CA", "ABBREVIATED"),
    ],
)
def test_region_codes_grade_as_abbreviations(field, source, result, expected):
    """A code and the name it stands for are the same value, differently written."""
    assert compare_values(source, result, FIELD_CODE_NAMES[field]) == expected


def test_compare_coordinates_blank_without_both_sides():
    """A row with no source coordinates leaves all three distance cells blank."""
    record = SourceRecord(internal_key=0)
    result = GeocodeResult(latitude="40.0", longitude="-75.0")
    assert compare_coordinates(record, result) == ["", "", ""]


def test_compare_coordinates_measures_signed_offsets():
    """A result north and east of the source reports positive offsets in meters."""
    record = SourceRecord(internal_key=0, latitude="40.0", longitude="-75.0")
    result = GeocodeResult(latitude="40.001", longitude="-74.999")

    northing, easting, distance = compare_coordinates(record, result)
    assert northing == pytest.approx(111.2, abs=0.5)
    assert easting == pytest.approx(85.2, abs=0.5)
    assert distance == pytest.approx(140.0, abs=1.0)


def test_compare_coordinates_ignores_unparseable_values():
    """Coordinates that are not numbers leave the distance cells blank."""
    record = SourceRecord(internal_key=0, latitude="unknown", longitude="-75.0")
    result = GeocodeResult(latitude="40.0", longitude="-75.0")
    assert compare_coordinates(record, result) == ["", "", ""]


def test_compare_record_grades_every_field():
    """One row yields a grade per compared field followed by the three offsets."""
    record = SourceRecord(
        internal_key=0,
        name="Site A",
        address="123 Main St",
        city="Anytown",
        stateprov="CA",
        postalcode="90210",
        country="US",
        latitude="40.0",
        longitude="-75.0",
    )
    result = GeocodeResult(
        result_name="Site A",
        result_address="123 Main Street",
        result_city="ANYTOWN",
        result_stateprov="California",
        result_postalcode="90210-0003",
        result_country="",
        latitude="40.0",
        longitude="-75.0",
    )

    assert compare_record(record, result) == [
        "EXACT",
        "ABBREVIATED",
        "FORMATTING",
        "ABBREVIATED",
        "TRUNCATED",
        "MISSING",
        "EXACT",
        0.0,
        0.0,
        0.0,
        "MISSING",
        "COUNTRY_CHANGED",
    ]


@pytest.mark.parametrize(
    "source,result,expected",
    [
        ("123 Main St", "123 Main Street", "EXACT"),
        ("123 Main St", "125 Main St", "DIFFERENT"),
        ("Av. Insurgentes Sur 1234", "Avenida Insurgentes Sur 1234", "EXACT"),
        ("Main Street", "1 Main Street", "ADDED"),
        ("123rd Ave", "123rd Avenue", "BLANK"),
    ],
)
def test_street_number_graded_separately(source, result, expected):
    """The house number is graded on its own, wherever the country puts it."""
    record = SourceRecord(internal_key=0, address=source)
    assert compare_record(record, GeocodeResult(result_address=result))[6] == expected


def test_summarize_grades_reports_the_worst():
    """A row is summarized by the grade that most needs a person to look at it."""
    assert summarize_grades(["EXACT", "ABBREVIATED", "DIFFERENT", "BLANK"]) == "DIFFERENT"
    assert summarize_grades(["BLANK", "BLANK"]) == "BLANK"


def test_flag_result_reports_no_match_alone():
    """A result with no coordinates is flagged as unmatched and nothing else."""
    result = GeocodeResult(match_notes="no candidates")
    assert flag_result(result, {"CITY": "DIFFERENT"}, "") == {"NO_MATCH": "no candidates"}


def test_flag_result_names_the_rewritten_fields():
    """A field the provider rewrote rather than reformatted is called out by name."""
    result = GeocodeResult(latitude="40.0", longitude="-75.0", accuracy=100)
    flags = flag_result(result, {"CITY": "FORMATTING", "STATEPROV": "DIFFERENT"}, 20.0)
    assert flags == {"STATE_CHANGED": ""}


def test_flag_result_reports_distant_and_coarse_results():
    """A coarse result far from the source coordinates raises both flags."""
    result = GeocodeResult(latitude="40.0", longitude="-75.0", accuracy=40)
    flags = flag_result(result, {}, 4200.0)
    assert flags["LOW_ACCURACY"] == "resolved no finer than city"
    assert flags["FAR_FROM_SOURCE"] == "4.2 km from the source coordinates"


def test_compare_record_expands_codes_per_field():
    """Each field is compared against the codes that field is written in."""
    record = SourceRecord(internal_key=0, stateprov="Texas", country="United States")
    result = GeocodeResult(result_stateprov="TX", result_country="US")

    grades = compare_record(record, result)
    assert grades[3] == "ABBREVIATED"
    assert grades[5] == "ABBREVIATED"
