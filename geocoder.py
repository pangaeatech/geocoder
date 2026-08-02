#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import argparse
import csv
import io
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

import requests
from openpyxl import Workbook, load_workbook


CANONICAL_FIELDS = [
    "ID",
    "NAME",
    "ADDRESS",
    "CITY",
    "STATEPROV",
    "POSTALCODE",
    "COUNTRY",
    "LATITUDE",
    "LONGITUDE",
]

COLUMN_SYNONYMS = {
    "ID": ["id", "facility id", "locationid", "location id"],
    "NAME": ["name", "facility name"],
    "ADDRESS": ["address", "street address"],
    "CITY": ["city"],
    "STATEPROV": [
        "state",
        "province",
        "state/province",
        "stateprovince",
        "state province",
    ],
    "POSTALCODE": ["zipcode", "zip code", "postal code", "postalcode"],
    "COUNTRY": ["country"],
    "LATITUDE": ["lat", "latitude"],
    "LONGITUDE": ["lng", "longitude"],
}

REQUIRED_FIELDS = ["ADDRESS", "CITY", "STATEPROV"]

SOURCE_HEADERS = [f"SOURCE_{field_name}" for field_name in CANONICAL_FIELDS]
RESULT_HEADERS = [f"RESULT_{field_name}" for field_name in CANONICAL_FIELDS]
META_HEADERS = [
    "GEOCODER_API",
    "MATCH_TYPE",
    "ACCURACY",
    "LOCATION_TYPE",
    "MATCH_NOTES",
]
DEBUG_HEADER = "RAW_MATCH"

KEY_ENV_VARS = {
    "geocodio": "GEOCODIO_API_KEY",
    "google": "GOOGLE_GEOCODING_API_KEY",
}


def load_dotenv(path: str = ".env") -> None:
    """
    Loads KEY=VALUE pairs from a .env file into the environment.

    Existing environment variables are left untouched, and a missing file is ignored.

    Parameters
    ----------
    path : str
        The path of the .env file to read.
    """
    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class SourceRecord:
    """A single input row, keyed by an internal sequential id for batch matching."""

    internal_key: int
    id: str = ""
    name: str = ""
    address: str = ""
    city: str = ""
    stateprov: str = ""
    postalcode: str = ""
    country: str = ""
    latitude: str = ""
    longitude: str = ""

    def address_string(self) -> str:
        """Joins the non-blank address components into a single query string."""
        parts = [self.address, self.city, self.stateprov, self.postalcode, self.country]
        return ", ".join(part for part in parts if part)


@dataclass
class GeocodeResult:
    """A normalized geocoding result; providers return one per SourceRecord."""

    result_id: str = ""
    result_name: str = ""
    result_address: str = ""
    result_city: str = ""
    result_stateprov: str = ""
    result_postalcode: str = ""
    result_country: str = ""
    latitude: str = ""
    longitude: str = ""
    match_type: str = "no_match"
    accuracy: int = 0
    location_type: str = ""
    match_notes: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


PROVIDERS: Dict[str, Type["Provider"]] = {}


def register(name: str):
    """Class decorator that registers a Provider subclass under the given name."""

    def decorator(cls):
        cls.name = name
        PROVIDERS[name] = cls
        return cls

    return decorator


class Provider(ABC):
    """Base class for geocoding providers; subclasses self-register via @register."""

    name: str = ""
    requires_key: bool = False

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    @abstractmethod
    def geocode(self, records: List[SourceRecord]) -> List[GeocodeResult]:
        """Returns one GeocodeResult per input record, in the same order."""


def resolve_api_key(api: str, cli_key: Optional[str]) -> Optional[str]:
    """
    Resolves an API key, preferring --apiKey over the provider's environment variable.

    Parameters
    ----------
    api : str
        The provider name whose environment variable is consulted.
    cli_key : Optional[str]
        The key supplied on the command line, if any.

    Return
    ----------
    Optional[str]
        The resolved key, or None when none is configured.
    """
    if cli_key:
        return cli_key

    env_var = KEY_ENV_VARS.get(api)
    return os.environ.get(env_var) if env_var else None


@register("census")
class CensusProvider(Provider):
    """
    Batch geocoder backed by the free U.S. Census Bureau addressbatch service.

    Records are submitted as CSV batches and matched back by their internal key.
    The service covers U.S. addresses only and requires no API key.
    """

    requires_key = False

    ENDPOINT = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
    BENCHMARK = "Public_AR_Current"
    VINTAGE = "Current_Current"
    BATCH_SIZE = 10000
    TIMEOUT = 300

    RESPONSE_FIELDS = [
        "id",
        "input_address",
        "match_status",
        "match_type",
        "matched_address",
        "coordinates",
        "tigerline_id",
        "side",
        "state_fips",
        "county_fips",
        "tract",
        "block",
    ]

    def geocode(self, records: List[SourceRecord]) -> List[GeocodeResult]:
        """
        Geocodes records in batches and returns one result per record, in order.

        Parameters
        ----------
        records : List[SourceRecord]
            The source rows to geocode.

        Return
        ----------
        List[GeocodeResult]
            One result per input record, aligned by position.
        """
        results_by_key: Dict[int, GeocodeResult] = {}
        for start in range(0, len(records), self.BATCH_SIZE):
            self._geocode_batch(
                records[start : start + self.BATCH_SIZE], results_by_key
            )

        return [
            results_by_key.get(
                record.internal_key, GeocodeResult(match_notes="No match")
            )
            for record in records
        ]

    def _geocode_batch(
        self, batch: List[SourceRecord], results_by_key: Dict[int, GeocodeResult]
    ) -> None:
        """Posts one CSV batch and stores each parsed result by its internal key."""
        response = requests.post(
            self.ENDPOINT,
            data={"benchmark": self.BENCHMARK, "vintage": self.VINTAGE},
            files={"addressFile": ("addresses.csv", self._build_csv(batch))},
            timeout=self.TIMEOUT,
        )
        response.raise_for_status()

        for row in csv.reader(io.StringIO(response.text)):
            if row:
                results_by_key[int(row[0])] = self._parse_row(row)

    @staticmethod
    def _build_csv(batch: List[SourceRecord]) -> str:
        """Serializes a batch into the Census addressbatch CSV input format."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for record in batch:
            writer.writerow(
                [
                    record.internal_key,
                    record.address,
                    record.city,
                    record.stateprov,
                    record.postalcode,
                ]
            )
        return buffer.getvalue()

    def _parse_row(self, row: List[str]) -> GeocodeResult:
        """Converts one Census response row into a normalized GeocodeResult."""
        raw = dict(zip(self.RESPONSE_FIELDS, row))
        status = row[2] if len(row) > 2 else "No_Match"

        if status == "Match" and len(row) > 5:
            exact = row[3].strip().lower() == "exact"
            address, city, stateprov, postalcode = self._split_address(row[4])
            longitude, latitude = self._split_coordinates(row[5])
            return GeocodeResult(
                result_address=address,
                result_city=city,
                result_stateprov=stateprov,
                result_postalcode=postalcode,
                latitude=latitude,
                longitude=longitude,
                match_type="exact" if exact else "non-exact",
                accuracy=100 if exact else 70,
                raw=raw,
            )

        if status == "Tie":
            return GeocodeResult(
                match_type="tie", accuracy=30, match_notes="Tie", raw=raw
            )

        return GeocodeResult(match_notes="No match", raw=raw)

    @staticmethod
    def _split_address(matched_address: str) -> List[str]:
        """Splits a Census matched-address into street, city, state, and zip."""
        parts = [part.strip() for part in matched_address.split(",")]
        parts += [""] * (4 - len(parts))
        return parts[:4]

    @staticmethod
    def _split_coordinates(coordinates: str) -> List[str]:
        """Splits a Census 'longitude,latitude' pair into separate strings."""
        parts = [part.strip() for part in coordinates.split(",")]
        return parts if len(parts) == 2 else ["", ""]


def clean_cell(value) -> str:
    """Converts the specified cell value into a trimmed string."""
    if value is None:
        return ""

    return str(value).strip()


def detect_columns(header_cells) -> Dict[str, int]:
    """
    Maps canonical field names to their 0-based column index in the header row.

    Matching is case-insensitive and uses COLUMN_SYNONYMS; when a field has more
    than one matching column, the first one wins.

    Parameters
    ----------
    header_cells
        The header row values to search through.

    Return
    ----------
    mapping : Dict[str, int]
        Each canonical field name mapped to its column index in the row.
    """
    synonym_to_field = {
        synonym: field_name
        for field_name, synonyms in COLUMN_SYNONYMS.items()
        for synonym in synonyms
    }

    mapping = {}
    for index, value in enumerate(header_cells):
        if value is None:
            continue
        field_name = synonym_to_field.get(str(value).strip().lower())
        if field_name and field_name not in mapping:
            mapping[field_name] = index
    return mapping


def read_sheet_records(
    rows, column_map: Dict[str, int], sheet_name: str, country_per_sheet: bool
) -> List[SourceRecord]:
    """
    Builds SourceRecords from the data rows of a worksheet.

    The header row must already be consumed before calling this. Fully blank rows
    are skipped, and each kept record is assigned a sequential internal key.

    Parameters
    ----------
    rows
        An iterable of data rows (tuples of cell values), with the header excluded.
    column_map : Dict[str, int]
        Each canonical field name mapped to its column index.
    sheet_name : str
        The worksheet name, used as COUNTRY when country_per_sheet is set.
    country_per_sheet : bool
        When True, blank country cells are filled with sheet_name.

    Return
    ----------
    records : List[SourceRecord]
        One record per non-blank data row.
    """
    records = []
    for row in rows:
        values = {}
        for field_name in CANONICAL_FIELDS:
            index = column_map.get(field_name)
            values[field_name] = (
                clean_cell(row[index]) if index is not None and index < len(row) else ""
            )

        if not any(values.values()):
            continue

        if country_per_sheet and not values["COUNTRY"]:
            values["COUNTRY"] = sheet_name

        attributes = {name.lower(): value for name, value in values.items()}
        records.append(SourceRecord(internal_key=len(records), **attributes))
    return records


def write_output_sheet(
    workbook: Workbook,
    sheet_name: str,
    records: List[SourceRecord],
    results: List[GeocodeResult],
    api_name: str,
    debug: bool,
) -> None:
    """
    Writes the source, result, and match-metadata columns for one worksheet.

    Parameters
    ----------
    workbook : Workbook
        The destination workbook a new sheet is added to.
    sheet_name : str
        The name of the sheet to create.
    records : List[SourceRecord]
        The source rows, in output order.
    results : List[GeocodeResult]
        The geocoding results, aligned with records.
    api_name : str
        The provider name recorded in the GEOCODER_API column.
    debug : bool
        When True, append a RAW_MATCH column holding the raw provider JSON.

    Raises
    ----------
    ValueError
        If the provider did not return exactly one result per input record.
    """
    if len(results) != len(records):
        raise ValueError(
            f"provider '{api_name}' returned {len(results)} results "
            f"for {len(records)} records"
        )

    worksheet = workbook.create_sheet(title=sheet_name)

    headers = SOURCE_HEADERS + RESULT_HEADERS + META_HEADERS
    if debug:
        headers = headers + [DEBUG_HEADER]
    worksheet.append(headers)

    for record, result in zip(records, results):
        row = [getattr(record, field_name.lower()) for field_name in CANONICAL_FIELDS]
        row += [
            result.result_id,
            result.result_name,
            result.result_address,
            result.result_city,
            result.result_stateprov,
            result.result_postalcode,
            result.result_country,
            result.latitude,
            result.longitude,
            api_name,
            result.match_type,
            result.accuracy,
            result.location_type,
            result.match_notes,
        ]
        if debug:
            row.append(json.dumps(result.raw, ensure_ascii=False) if result.raw else "")
        worksheet.append(row)


def process_workbook(
    infile: str,
    outfile: str,
    provider: Provider,
    worksheet: Optional[str] = None,
    country_per_sheet: bool = False,
    debug: bool = False,
) -> None:
    """
    Reads an input workbook, geocodes each qualifying sheet, and writes the output.

    Every worksheet is processed unless a single worksheet is named. Sheets missing
    any required column are skipped with a message written to stdout.

    Parameters
    ----------
    infile : str
        The path of the workbook to read.
    outfile : str
        The path of the workbook to create.
    provider : Provider
        The geocoding provider used to resolve records.
    worksheet : Optional[str]
        A single worksheet to process; when None, all sheets are processed.
    country_per_sheet : bool
        When True, blank country cells are filled with the sheet name.
    debug : bool
        When True, include the RAW_MATCH column in the output.

    Raises
    ----------
    SystemExit
        If the named worksheet is missing, or no sheet had the required columns.
    """
    source = load_workbook(infile, read_only=True, data_only=True)
    try:
        if worksheet is not None and worksheet not in source.sheetnames:
            raise SystemExit(f"error: worksheet '{worksheet}' not found in {infile}")

        sheet_names = [worksheet] if worksheet else source.sheetnames

        output = Workbook()
        output.remove(output.active)

        processed = 0
        for name in sheet_names:
            rows = source[name].iter_rows(values_only=True)
            header = next(rows, None)
            if header is None:
                continue

            column_map = detect_columns(header)
            if not all(field_name in column_map for field_name in REQUIRED_FIELDS):
                print(
                    f"skipping sheet '{name}': missing required columns "
                    f"(need {', '.join(REQUIRED_FIELDS)})"
                )
                continue

            records = read_sheet_records(rows, column_map, name, country_per_sheet)
            results = provider.geocode(records)
            write_output_sheet(output, name, records, results, provider.name, debug)
            processed += 1
    finally:
        source.close()

    if processed == 0:
        raise SystemExit(
            "error: no worksheets had the required columns; nothing written"
        )

    output.save(outfile)


def parse_args(argv: Optional[List[str]] = None):
    """Takes and parses the command-line arguments given by the user."""
    parser = argparse.ArgumentParser(
        description="Geocode address rows in an Excel workbook."
    )

    parser.add_argument("infile", help="Excel file to read (must exist)")
    parser.add_argument("outfile", help="Excel file to create (must not exist)")
    parser.add_argument(
        "worksheet",
        nargs="?",
        default=None,
        help="optional single worksheet to process",
    )
    parser.add_argument(
        "--api",
        default="census",
        metavar="{census|geocodio|google}",
        help="geocoding provider (default: census)",
    )
    parser.add_argument(
        "--apiKey",
        dest="api_key",
        default=None,
        help="API key; falls back to .env / environment",
    )
    parser.add_argument(
        "--countryPerSheet",
        dest="country_per_sheet",
        action="store_true",
        help="use the worksheet name as COUNTRY when a row's country is blank",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="add a RAW_MATCH column populated with raw provider JSON",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    """
    Runs the geocoder: validates arguments, selects a provider, and writes the output.

    Parameters
    ----------
    argv : Optional[List[str]]
        The argument list to parse; defaults to sys.argv when None.

    Raises
    ----------
    SystemExit
        If the input file is missing, the output file already exists, the api is
        unknown, or a required API key is not configured.
    """
    load_dotenv()
    args = parse_args(argv)

    if not os.path.isfile(args.infile):
        raise SystemExit(f"error: input file '{args.infile}' does not exist")
    if os.path.exists(args.outfile):
        raise SystemExit(f"error: output file '{args.outfile}' already exists")

    provider_cls = PROVIDERS.get(args.api)
    if provider_cls is None:
        available = ", ".join(sorted(PROVIDERS)) or "none"
        raise SystemExit(f"error: unknown api '{args.api}' (available: {available})")

    api_key = None
    if provider_cls.requires_key:
        api_key = resolve_api_key(args.api, args.api_key)
        if not api_key:
            raise SystemExit(
                f"error: api '{args.api}' requires an API key "
                f"(pass --apiKey or set {KEY_ENV_VARS[args.api]})"
            )

    provider = provider_cls(api_key)
    process_workbook(
        args.infile,
        args.outfile,
        provider,
        worksheet=args.worksheet,
        country_per_sheet=args.country_per_sheet,
        debug=args.debug,
    )
    print(f"wrote {args.outfile}")


if __name__ == "__main__":
    main()
