#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — the flag cell shared by the pre-checks and the comparisons

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

from typing import Dict


def format_flags(flags: Dict[str, str]) -> str:
    """
    Renders one record's flags as a single cell.

    Each flag is written on its own, followed by its note where it has one, so
    that the whole of what a check found stays in one place: a reader scanning
    the column sees the flag names, and searching for one finds its detail
    alongside rather than in a second column that is blank as often as not.
    Flags are parted by a semicolon, because a note is free to hold a comma and
    several of them do.

    Parameters
    ----------
    flags : Dict[str, str]
        The flags raised for a record, mapped to their notes.

    Return
    ----------
    str
        Every flag and the notes it carries, or a blank for an unflagged record.
    """
    return "; ".join(f"{name}: {note}" if note else name for name, note in flags.items())
