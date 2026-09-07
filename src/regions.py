#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — country and subdivision reference data

The subdivision codes cover the United States and Canada, whose two-letter codes
share no letters with the names they stand for and so can only be recognized by
lookup. Mexican states are absent by design: they are abbreviated by prefix
("Jal." for Jalisco, "Q.R." for Quintana Roo), which needs no table.

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

from typing import Dict, List, Optional, Tuple

from .text import key

COUNTRY_NAMES = {
    "US": "United States",
    "CA": "Canada",
    "MX": "Mexico",
}

COUNTRY_ALIASES = {
    **{name.casefold(): code for code, name in COUNTRY_NAMES.items()},
    **{code.casefold(): code for code in COUNTRY_NAMES},
    "usa": "US",
    "united states of america": "US",
    "can": "CA",
    "mex": "MX",
    "méxico": "MX",
}

COUNTRY_CODE_NAMES = {alias.upper(): COUNTRY_NAMES[code] for alias, code in COUNTRY_ALIASES.items()}

US_SUBDIVISION_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "PR": "Puerto Rico",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

CA_SUBDIVISION_NAMES = {
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YT": "Yukon",
}

COUNTRY_SUBDIVISIONS = {"US": US_SUBDIVISION_NAMES, "CA": CA_SUBDIVISION_NAMES}

SUBDIVISION_NAMES = {**US_SUBDIVISION_NAMES, **CA_SUBDIVISION_NAMES}

EXTRA_SUBDIVISION_ALIASES = {
    "US": {"washington dc": "DC", "washington d.c.": "DC"},
    "CA": {"newfoundland": "NL", "labrador": "NL", "yukon territory": "YT", "pq": "QC"},
}

COUNTRY_BOUNDS: Dict[str, List[Tuple[float, float, float, float]]] = {
    "US": [
        (24.4, -125.1, 49.4, -66.9),
        (51.0, -180.0, 71.5, -129.9),
        (51.2, 172.4, 53.1, 180.0),
        (18.8, -160.3, 22.3, -154.7),
        (17.6, -67.3, 18.6, -64.5),
    ],
    "CA": [(41.6, -141.1, 83.2, -52.5)],
    "MX": [(14.5, -118.5, 32.8, -86.6)],
}


COUNTRY_KEYS = {key(alias): code for alias, code in COUNTRY_ALIASES.items()}

SUBDIVISION_KEYS = {
    country: {
        **{key(code): code for code in names},
        **{key(name): code for code, name in names.items()},
        **{key(alias): code for alias, code in EXTRA_SUBDIVISION_ALIASES.get(country, {}).items()},
    }
    for country, names in COUNTRY_SUBDIVISIONS.items()
}


def country_code(value: str) -> Optional[str]:
    """
    Resolves a country written as a code, a name, or a common alias.

    Parameters
    ----------
    value : str
        The country cell as it was written, in any case or punctuation.

    Return
    ----------
    Optional[str]
        The two-letter code, or None when the country is not one covered here.
    """
    return COUNTRY_KEYS.get(key(value))


def subdivision_code(country: Optional[str], value: str) -> Optional[str]:
    """
    Resolves a state or province to its code, within the country it belongs to.

    Parameters
    ----------
    country : Optional[str]
        The two-letter country code whose subdivisions are searched.
    value : str
        The state or province cell as it was written, as a code or a name.

    Return
    ----------
    Optional[str]
        The subdivision code, or None when the country has no table here or the
        value is not one of its subdivisions.
    """
    return SUBDIVISION_KEYS.get(country or "", {}).get(key(value))


def within_country(country: Optional[str], latitude: float, longitude: float) -> bool:
    """
    Reports whether a coordinate pair falls inside a country's bounding boxes.

    A country whose extent is not recorded here accepts every coordinate. One
    box per landmass keeps the test tight: a single box around the United States
    would stretch from Alaska to Puerto Rico and swallow most of the continent.

    Parameters
    ----------
    country : Optional[str]
        The two-letter country code whose extent is checked.
    latitude : float
        The latitude to test, in degrees.
    longitude : float
        The longitude to test, in degrees.

    Return
    ----------
    bool
        True when the point lies in one of the country's boxes, or none is known.
    """
    boxes = COUNTRY_BOUNDS.get(country or "")
    if not boxes:
        return True
    return any(south <= latitude <= north and west <= longitude <= east for south, west, north, east in boxes)
