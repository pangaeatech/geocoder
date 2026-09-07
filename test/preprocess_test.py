#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder Pre-processing Tests

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import pytest

from src.api import SourceRecord
from src.preprocess import check_record, check_records, format_flags


def _record(**attributes):
    """Builds a source record with the given fields and sensible defaults."""
    defaults = {"address": "1 Main St", "city": "Anytown", "stateprov": "CA", "name": "Site", "postalcode": "90210", "country": "US"}
    defaults.update(attributes)
    return SourceRecord(internal_key=0, **defaults)


@pytest.mark.parametrize(
    "address",
    ["PO Box 12", "P.O. Box 12", "p o box 12", "Post Office Box 9", "PMB #4"],
)
def test_po_box_variants_flagged(address):
    """Every spelling of a post office box raises the PO_BOX flag."""
    assert "PO_BOX" in check_record(_record(address=address))


def test_street_address_not_flagged():
    """An ordinary street address raises no flags at all."""
    assert not check_record(_record())


def test_blank_fields_flagged_individually():
    """Each empty address-forming field raises its own flag."""
    flags = check_record(_record(city="", postalcode=""))
    assert "BLANK_CITY" in flags
    assert "BLANK_POSTALCODE" in flags
    assert "BLANK_ADDRESS" not in flags


def test_placeholder_address_flagged():
    """A stand-in address is reported with the offending text."""
    flags = check_record(_record(address="N/A"))
    assert flags["PLACEHOLDER"] == "N/A"


def test_rural_route_flagged():
    """A rural route box raises RURAL_ROUTE and suppresses NO_STREET_NUMBER."""
    flags = check_record(_record(address="RR 2 Box 15"))
    assert "RURAL_ROUTE" in flags
    assert "NO_STREET_NUMBER" not in flags


def test_intersection_flagged():
    """An address given as a crossing of two streets is flagged."""
    assert "INTERSECTION" in check_record(_record(address="Main St & 5th Ave"))
    assert "INTERSECTION" in check_record(_record(address="Corner of Main and 5th"))


@pytest.mark.parametrize(
    "address",
    [
        "NE1/4 of Section 12",
        "SEC 12, TWP 5 N, RGE 3 W",
        "T5N R3W",
        "Lot 4, Block 2, Sunrise Subdivision",
        "thence N 45 deg E 200 feet",
    ],
)
def test_legal_descriptions_flagged(address):
    """Survey calls, lot and block references, and bearings are flagged."""
    assert "LEGAL_DESCRIPTION" in check_record(_record(address=address))


def test_legal_description_in_name_flagged():
    """A legal description in the name field is flagged and attributed to it."""
    flags = check_record(_record(name="Parcel 7 of the SW1/4"))
    assert flags["LEGAL_DESCRIPTION"].startswith("name:")


def test_single_weak_legal_pattern_not_flagged():
    """One weak survey word alone is not enough to call it a legal description."""
    assert "LEGAL_DESCRIPTION" not in check_record(_record(address="100 Lot 5 Road"))


def test_address_range_flagged():
    """A street number written as a range is flagged."""
    assert "ADDRESS_RANGE" in check_record(_record(address="123-127 Main St"))


def test_missing_street_number_flagged():
    """An address with no number at all is flagged when nothing explains it."""
    assert "NO_STREET_NUMBER" in check_record(_record(address="Main Street"))


@pytest.mark.parametrize(
    "address",
    ["Av. Insurgentes Sur 1234", "Calle 5 de Mayo 21", "N82 W13118 Leon Rd", "123 Main St"],
)
def test_numbered_address_not_flagged_wherever_the_number_sits(address):
    """A number anywhere in the address counts, whatever the local convention."""
    assert "NO_STREET_NUMBER" not in check_record(_record(address=address))


def test_escaped_control_character_flagged():
    """A control character Excel stored as its literal escape is still caught."""
    assert "INVALID_CHARACTERS" in check_record(_record(city="Anytown_x000b_"))


def test_invalid_characters_flagged():
    """A replacement character left by a bad encoding is flagged with its field."""
    flags = check_record(_record(city="Montr�al"))
    assert flags["INVALID_CHARACTERS"] == "city"


@pytest.mark.parametrize(
    "postalcode,country,expected",
    [
        ("90210", "US", False),
        ("90210-1234", "USA", False),
        ("ABCDE", "US", True),
        ("M5V 2T6", "Canada", False),
        ("90210", "CA", True),
        ("06600", "MX", False),
        ("ABCDE", "France", False),
    ],
)
def test_postalcode_format_checked_per_country(postalcode, country, expected):
    """Postal codes are checked only against the countries with known formats."""
    flags = check_record(_record(postalcode=postalcode, country=country))
    assert ("INVALID_POSTALCODE" in flags) is expected


def test_postalcode_lost_leading_zero_flagged():
    """A short numeric US code is reported as one a spreadsheet stripped zeros from."""
    flags = check_record(_record(postalcode="1562", country="US"))
    assert flags["TRUNCATED_POSTALCODE"] == "1562 is missing its leading zero(s)"
    assert "INVALID_POSTALCODE" not in flags


def test_postalcode_missing_hyphen_flagged():
    """A nine-digit U.S. code is reported as a ZIP+4 that lost its hyphen."""
    flags = check_record(_record(postalcode="974029150", country="US"))
    assert flags["UNFORMATTED_POSTALCODE"] == "974029150 should be written 97402-9150"


def test_blank_fields_limited_to_named_columns():
    """Only the fields the sheet has a column for are checked for blank cells."""
    flags = check_record(_record(name="", country=""), blank_fields=["address", "city"])
    assert "BLANK_NAME" not in flags
    assert "BLANK_COUNTRY" not in flags


@pytest.mark.parametrize(
    "latitude,longitude,expected",
    [
        ("40.0", "-75.0", False),
        ("", "", False),
        ("40.0", "", True),
        ("abc", "-75.0", True),
        ("91.0", "-75.0", True),
        ("0", "0", True),
    ],
)
def test_source_coordinates_validated(latitude, longitude, expected):
    """Incomplete, unparseable, off-globe, and null island coordinates are flagged."""
    flags = check_record(_record(latitude=latitude, longitude=longitude))
    assert ("INVALID_COORDINATES" in flags) is expected


def test_duplicate_addresses_flagged_across_rows():
    """Rows sharing a normalized address are flagged with the number of siblings."""
    records = [
        SourceRecord(internal_key=0, address="1 Main St", city="Anytown", stateprov="CA"),
        SourceRecord(internal_key=1, address="1 MAIN ST.", city="anytown", stateprov="ca"),
        SourceRecord(internal_key=2, address="2 Other St", city="Anytown", stateprov="CA"),
    ]

    flags = check_records(records)
    assert flags[0]["DUPLICATE"] == "address is shared with 1 other row(s)"
    assert "DUPLICATE" in flags[1]
    assert "DUPLICATE" not in flags[2]


@pytest.mark.parametrize("address", ["", "N/A"])
def test_rows_without_an_address_are_not_duplicates(address):
    """Rows with nothing to match on are left out of the duplicate count."""
    records = [SourceRecord(internal_key=index, address=address, city="Anytown", stateprov="CA") for index in range(3)]

    for record_flags in check_records(records, ["address"]):
        assert "DUPLICATE" not in record_flags


def test_format_flags_renders_names_and_notes():
    """Flag names fill PRE_FLAGS and only the flags carrying notes fill PRE_NOTES."""
    cells = format_flags({"BLANK_CITY": "", "PO_BOX": "PO Box 12"})
    assert cells == ["BLANK_CITY, PO_BOX", "PO_BOX: PO Box 12"]
