#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder Cache Tests

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import sqlite3

import pytest

from src.api import GeocodeResult, Provider, SourceRecord
from src.cache import Cache, missing_files, normalize_query


class _CountingProvider(Provider):
    """Counts the records it is asked to fetch so cache hits can be observed."""

    name = "counting"

    def __init__(self, cache=None):
        super().__init__(cache=cache)
        self.fetched = []

    def _fetch(self, records):
        """Yields a response per record and records which records were requested."""
        for record in records:
            self.fetched.append(record.address_string())
            yield record, {"echo": record.address_string()}

    def parse(self, raw):
        """Returns a result carrying the echoed query so hits can be identified."""
        return GeocodeResult(result_address=raw["echo"], raw=raw)


def _record(key, address, city="Town", stateprov="CA"):
    """Builds a SourceRecord with the given internal key and address."""
    return SourceRecord(internal_key=key, address=address, city=city, stateprov=stateprov)


def test_normalize_query_folds_case_and_whitespace():
    """Case and runs of whitespace collapse so equivalent queries share one key."""
    assert normalize_query("123  Main   St") == normalize_query("123 MAIN ST")
    assert normalize_query("  1 A St\t") == "1 a st"


def test_normalize_query_keeps_distinct_addresses_distinct():
    """Normalization does not merge addresses that differ in substance."""
    assert normalize_query("1 Main St") != normalize_query("1 Main Ave")


def test_duplicates_collapse_to_one_call_without_a_cache_file():
    """Repeated addresses in one run cost a single call even with no cache configured."""
    provider = _CountingProvider()
    records = [
        _record(0, "1 Main St"),
        _record(1, "1 MAIN  ST"),
        _record(2, "2 Oak St"),
        _record(3, "1 Main St"),
    ]

    results = provider.geocode(records)

    assert len(provider.fetched) == 2
    assert len(results) == 4
    assert results[0].result_address == results[1].result_address == results[3].result_address
    assert results[2].result_address == "2 Oak St, Town, CA"


def test_cache_hit_across_runs_skips_the_api(tmp_path):
    """A second run over an overlapping list only calls the API for the new addresses."""
    path = str(tmp_path / "cache.sqlite")

    with Cache(path) as cache:
        first = _CountingProvider(cache)
        first.geocode([_record(0, "1 Main St"), _record(1, "2 Oak St")])
    assert len(first.fetched) == 2

    with Cache(path) as cache:
        second = _CountingProvider(cache)
        results = second.geocode([_record(0, "1 Main St"), _record(1, "3 Elm St")])

    assert second.fetched == ["3 Elm St, Town, CA"]
    assert results[0].result_address == "1 Main St, Town, CA"
    assert results[1].result_address == "3 Elm St, Town, CA"


def test_cache_is_scoped_per_api(tmp_path):
    """One provider's stored response is never served to another provider."""
    path = str(tmp_path / "cache.sqlite")

    with Cache(path) as cache:
        _CountingProvider(cache).geocode([_record(0, "1 Main St")])

    with Cache(path) as cache:
        other = _CountingProvider(cache)
        other.name = "different"
        other.geocode([_record(0, "1 Main St")])

    assert other.fetched == ["1 Main St, Town, CA"]


def test_read_only_cache_is_used_but_not_written(tmp_path):
    """A --cacheRead file answers lookups and is left untouched by the run."""
    shared = tmp_path / "shared.sqlite"
    with Cache(str(shared)) as cache:
        _CountingProvider(cache).geocode([_record(0, "1 Main St")])

    before = shared.read_bytes()

    with Cache(str(tmp_path / "own.sqlite"), [str(shared)]) as cache:
        provider = _CountingProvider(cache)
        provider.geocode([_record(0, "1 Main St"), _record(1, "2 Oak St")])

    assert provider.fetched == ["2 Oak St, Town, CA"]
    assert shared.read_bytes() == before


def test_writable_cache_wins_over_read_only(tmp_path):
    """The writable cache answers first when both files hold the same key."""
    stale = str(tmp_path / "stale.sqlite")
    fresh = str(tmp_path / "fresh.sqlite")
    key = normalize_query("1 Main St, Town, CA")

    with Cache(stale) as cache:
        cache.store("counting", key, "1 Main St, Town, CA", {"echo": "from stale"})
    with Cache(fresh) as cache:
        cache.store("counting", key, "1 Main St, Town, CA", {"echo": "from fresh"})

    with Cache(fresh, [stale]) as cache:
        result = _CountingProvider(cache).geocode([_record(0, "1 Main St")])[0]

    assert result.result_address == "from fresh"


def test_store_commits_in_batches_for_crash_safety(tmp_path):
    """Responses reach disk before the run ends so a crash keeps completed calls."""
    path = str(tmp_path / "cache.sqlite")
    cache = Cache(path)
    for index in range(Cache.COMMIT_INTERVAL):
        cache.store("counting", f"key {index}", f"key {index}", {"echo": index})

    committed = sqlite3.connect(path).execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    cache.close()

    assert committed == Cache.COMMIT_INTERVAL


def test_stored_row_keeps_the_original_query(tmp_path):
    """The un-normalized query is retained alongside its key for manual review."""
    path = str(tmp_path / "cache.sqlite")
    with Cache(path) as cache:
        _CountingProvider(cache).geocode([_record(0, "1  MAIN  St")])

    row = sqlite3.connect(path).execute("SELECT query, original_query FROM cache").fetchone()
    assert row[0] == "1 main st, town, ca"
    assert row[1] == "1  MAIN  St, Town, CA"


def test_read_only_cache_rejects_a_foreign_database(tmp_path):
    """A SQLite file without a cache table is refused instead of failing later."""
    path = str(tmp_path / "other.sqlite")
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE unrelated (id INTEGER)")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError):
        Cache(None, [path])


def test_read_only_cache_rejects_a_differently_shaped_cache_table(tmp_path):
    """A 'cache' table without the columns lookups read is refused up front."""
    path = str(tmp_path / "other.sqlite")
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE cache (key TEXT, value TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError):
        Cache(None, [path])


def test_read_only_cache_rejects_a_non_database(tmp_path):
    """A file that is not a SQLite database is refused with a clear error."""
    path = tmp_path / "notes.txt"
    path.write_text("not a database")

    with pytest.raises(ValueError):
        Cache(None, [str(path)])


def test_writable_cache_rejects_a_non_database(tmp_path):
    """Pointing --cache at an existing non-database file is refused, not overwritten."""
    path = tmp_path / "addresses.xlsx"
    path.write_text("not a database")

    with pytest.raises(ValueError):
        Cache(str(path))

    assert path.read_text() == "not a database"


def test_missing_files_reports_only_absent_paths(tmp_path):
    """Existing paths are dropped and absent ones are reported in order."""
    present = tmp_path / "here.sqlite"
    present.write_text("")
    absent = str(tmp_path / "gone.sqlite")

    assert missing_files([str(present), absent]) == [absent]
