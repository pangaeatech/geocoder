#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — text folding shared by the checks, the lookups, and the comparisons

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import re
import unicodedata
from typing import List


def unaccent(value: str) -> str:
    """Folds a value to lowercase and strips the accents from its letters."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def words(value: str) -> List[str]:
    """Splits a value into accent-free lowercase words, dropping punctuation."""
    return re.sub(r"[^0-9a-z]+", " ", unaccent(value)).split()


def key(value: str) -> str:
    """Reduces a value to the bare letters and digits a lookup is keyed by."""
    return "".join(words(value))
