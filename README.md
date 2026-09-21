# Geocoder

Geocoder reads address records from an Excel workbook, submits them to a selected
geocoding provider, and writes a new workbook containing the original fields,
normalized location results, match metadata, and optional raw provider responses.
Repeated queries are deduplicated within a run and can be stored in a local SQLite
cache to avoid paying for the same lookup again.

## Requirements

- Python `>=3.10,<3.15`
- [Poetry](https://python-poetry.org/) for the supported installation workflow

## Installation

Install the runtime dependencies:

```bash
poetry install --only main
```

For development, testing, linting, and documentation tools, install the `dev`
group as well:

```bash
poetry install
```

Run the command from the project root:

```bash
poetry run geocoder --help
```

## Input Workbook

The input must be an `.xlsx` workbook. Each worksheet to process needs these
columns (matching is case-insensitive):

- `ADDRESS`
- `CITY`
- `STATEPROV`

The following columns are optional: `ID`, `NAME`, `POSTALCODE`, `COUNTRY`,
`LATITUDE`, and `LONGITUDE`. Common names such as `street address`, `state`,
`province`, `zip code`, and `postal code` are recognized.

For example:

| ID | ADDRESS | CITY | STATEPROV | POSTALCODE | COUNTRY |
| --- | --- | --- | --- | --- | --- |
| 1 | 1600 Pennsylvania Ave NW | Washington | DC | 20500 | US |
| 2 | 111 Richmond St W | Toronto | ON | M5H 2G4 | CA |

All worksheets are processed by default. Pass a worksheet name as the third
positional argument to process just one sheet.

## Basic Usage

Use the free Census provider to geocode a U.S. workbook:

```bash
poetry run geocoder input.xlsx output.xlsx --api census
```

Process only the `Facilities` worksheet:

```bash
poetry run geocoder input.xlsx output.xlsx Facilities --api census
```

Use the worksheet name as `COUNTRY` when a row does not provide that column:

```bash
poetry run geocoder input.xlsx output.xlsx --api geocodio --countryPerSheet
```

Add the provider's raw JSON response to the output workbook for troubleshooting:

```bash
poetry run geocoder input.xlsx output.xlsx --api google --debug
```

By default, requests are cached in `geocoder-cache.sqlite` in the current
directory. Choose a cache location, reuse one or more read-only caches, or disable
persistent caching:

```bash
poetry run geocoder input.xlsx output.xlsx --api census --cache data/geocoder.sqlite
poetry run geocoder input.xlsx output.xlsx --api census --cacheRead archive.sqlite
poetry run geocoder input.xlsx output.xlsx --api census --noCache
```

`--noCache` opens no cache file at all, so `--cache` and `--cacheRead` are
ignored when it is given; repeated addresses within a run still cost one call.
A `--cacheRead` file must hold entries for the provider being run, and is
rejected if it does not.

Each provider's responses are stored in a table of their own, tagged with the
version of the API that produced them: entries written by an earlier version are
never served, and are replaced as their addresses are looked up again.

## Providers

| Provider | `--api` value | Coverage | API key |
| --- | --- | --- | --- |
| U.S. Census Bureau address batch service | `census` | U.S. addresses | Not required |
| Geocodio | `geocodio` | U.S., Canada, Mexico, and U.K. addresses | Required |
| Google Geocoding API | `google` | Coverage depends on Google Geocoding API availability | Required |

`census` is the default provider. It sends records in batches of up to 10,000.
Geocodio also submits batches, while Google is queried one address at a time.

## API Keys

The Geocodio and Google providers require a key. Supply it directly with
`--apiKey`, set the corresponding environment variable, or put the variable in a
`.env` file in the working directory. Environment variables take precedence over
values in `.env`.

```bash
# Geocodio
export GEOCODIO_API_KEY="your-key"
poetry run geocoder input.xlsx output.xlsx --api geocodio

# Google
export GOOGLE_GEOCODING_API_KEY="your-key"
poetry run geocoder input.xlsx output.xlsx --api google

# One-off key
poetry run geocoder input.xlsx output.xlsx --api geocodio --apiKey "your-key"
```

An equivalent `.env` file is:

```dotenv
GEOCODIO_API_KEY=your-geocodio-key
GOOGLE_GEOCODING_API_KEY=your-google-key
```

Do not commit `.env` files or API keys. `.env` is ignored by this repository.

## Output

The output workbook retains the source fields as `SOURCE_*` columns and adds
`RESULT_*` columns for normalized provider results. It also includes:

- `GEOCODER_API`: the provider used for the row.
- `MATCH_TYPE`: whether the provider reported an exact, partial, or no match.
- `ACCURACY`: the normalized precision score.
- `LOCATION_TYPE`: provider precision metadata.
- `MATCH_NOTES`: any notes returned while processing the record.
