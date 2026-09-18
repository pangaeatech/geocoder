#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder Flag Rendering Tests

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

from src.flags import format_flags


def test_format_flags_renders_names_and_notes():
    """Every flag reaches the one cell, each with its note where it has one."""
    assert format_flags({"BLANK_CITY": "", "PO_BOX": "PO Box 12"}) == "BLANK_CITY; PO_BOX: PO Box 12"


def test_format_flags_parts_notes_that_hold_commas():
    """A note free to hold a comma stays readable beside the flag that follows it."""
    rendered = format_flags({"LEGAL_DESCRIPTION": "address: Lot 5, Block 2", "NO_MATCH": ""})
    assert rendered == "LEGAL_DESCRIPTION: address: Lot 5, Block 2; NO_MATCH"


def test_format_flags_of_a_clean_row_is_blank():
    """A row with nothing wrong with it leaves the column empty."""
    assert format_flags({}) == ""
