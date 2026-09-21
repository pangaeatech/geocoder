#!/usr/bin/python3
# -.- coding: utf-8 -.-
# -.- dependencies: Python 3.8+ -.-

"""
Geocoder — provider response cache

Copyright (c) 2026 Pangaea Information Technologies, Ltd.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

DEFAULT_CACHE_FILE = "geocoder-cache.sqlite"

REQUIRED_COLUMNS = ("query", "version", "response")

SCHEMA = """
CREATE TABLE IF NOT EXISTS {table} (
    query TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    response TEXT NOT NULL,
    fetched_at TEXT NOT NULL
)
"""


class Cache:
    """
    A SQLite-backed store of raw provider responses keyed by the query that produced them.

    The key is the address a run asks about, and nothing else: how the provider
    was called is held apart from it, as the version tag every row carries.
    Lookups are filtered to the version the run is calling now, so entries
    written under an earlier one are never served, and re-fetching a query
    overwrites its row rather than leaving an obsolete one behind for good.

    Each provider owns a table named for it, so a lookup reads only the entries
    that could answer it and the tables of providers never called cost nothing.

    A cache is never a source of truth: deleting a cache file changes nothing
    but how many API calls a run costs.
    """

    COMMIT_INTERVAL = 250
    LOOKUP_CHUNK = 500

    def __init__(self, api: str, version: str, path: Optional[str] = None, read_paths: Sequence[str] = ()):
        self._api = api
        self._version = version
        self._writer = self._open_writer(path) if path else None
        self._readers = [self._open_reader(read_path) for read_path in read_paths]
        self._uncommitted = 0

    @property
    def _table(self) -> str:
        """Returns this provider's table name, quoted for use in a statement."""
        escaped = self._api.replace('"', '""')
        return f'"{escaped}"'

    def _open_writer(self, path: str) -> sqlite3.Connection:
        """
        Opens the read-write cache, creating the file and this provider's table when absent.

        Parameters
        ----------
        path : str
            The path of the cache file to open or create.

        Return
        ----------
        sqlite3.Connection
            A connection with this provider's table in place.

        Raises
        ----------
        ValueError
            If the path names an existing file that is not a SQLite database.
        """
        connection = sqlite3.connect(path)
        try:
            connection.execute(SCHEMA.format(table=self._table))
            connection.commit()
        except sqlite3.DatabaseError as error:
            connection.close()
            raise ValueError(f"'{path}' cannot be used as a cache: {error}") from error
        return connection

    def _open_reader(self, path: str) -> sqlite3.Connection:
        """
        Opens a cache file read-only and confirms it can answer this provider's lookups.

        A file named as a read-only cache is one the run expects to save calls,
        so a file holding nothing for this provider is refused here rather than
        quietly costing the calls it was meant to spare. The columns lookups
        read are checked as well as the table itself, so a foreign database that
        happens to hold a table of that name is refused too.

        Parameters
        ----------
        path : str
            The path of an existing cache file.

        Return
        ----------
        sqlite3.Connection
            A connection that cannot modify the file.

        Raises
        ----------
        ValueError
            If the file is not a SQLite database, or holds no usable table for
            this provider.
        """
        connection = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
        try:
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({self._table})")}
        except sqlite3.DatabaseError as error:
            connection.close()
            raise ValueError(f"'{path}' is not a readable SQLite database: {error}") from error

        if not columns:
            connection.close()
            raise ValueError(f"'{path}' holds no cached '{self._api}' responses")

        missing = [column for column in REQUIRED_COLUMNS if column not in columns]
        if missing:
            connection.close()
            raise ValueError(f"'{path}' is not a geocoder cache (its '{self._api}' table is missing {', '.join(missing)})")
        return connection

    def _connections(self) -> Iterator[sqlite3.Connection]:
        """Yields the writable cache first, then each read-only cache in the order given."""
        if self._writer is not None:
            yield self._writer
        yield from self._readers

    def lookup(self, keys: Iterable[str]) -> Dict[str, Any]:
        """
        Fetches the stored responses for the given keys, writable cache first.

        The first file holding a key under the current version wins; keys with
        no such response are absent from the result, whether they were never
        stored or were stored under a version this run no longer calls.

        Parameters
        ----------
        keys : Iterable[str]
            The query keys to look for.

        Return
        ----------
        Dict[str, Any]
            Each found key mapped to its decoded response.
        """
        found: Dict[str, Any] = {}
        outstanding = list(dict.fromkeys(keys))

        for connection in self._connections():
            if not outstanding:
                break
            for start in range(0, len(outstanding), self.LOOKUP_CHUNK):
                chunk = outstanding[start : start + self.LOOKUP_CHUNK]
                placeholders = ",".join("?" * len(chunk))
                rows = connection.execute(
                    f"SELECT query, response FROM {self._table} WHERE version = ? AND query IN ({placeholders})",
                    [self._version, *chunk],
                )
                for key, response in rows:
                    found[key] = json.loads(response)
            outstanding = [key for key in outstanding if key not in found]

        return found

    def store(self, key: str, response: Any) -> None:
        """
        Records one provider response, committing once a batch has accumulated.

        The response is tagged with the version that produced it, replacing any
        entry the query already had, so an obsolete response is retired by the
        call that supersedes it.

        Committing as the run proceeds means a crash costs only the calls made
        since the last commit.

        Parameters
        ----------
        key : str
            The query key to store the response under.
        response : Any
            The raw provider response, stored as JSON.
        """
        if self._writer is None:
            return

        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._writer.execute(
            f"INSERT OR REPLACE INTO {self._table} (query, version, response, fetched_at) VALUES (?, ?, ?, ?)",
            (key, self._version, json.dumps(response, ensure_ascii=False), fetched_at),
        )

        self._uncommitted += 1
        if self._uncommitted >= self.COMMIT_INTERVAL:
            self.commit()

    def commit(self) -> None:
        """Flushes any stored responses that have not yet been committed."""
        if self._writer is not None and self._uncommitted:
            self._writer.commit()
            self._uncommitted = 0

    def close(self) -> None:
        """Commits outstanding writes and closes every open cache file."""
        self.commit()
        for connection in self._connections():
            connection.close()
        self._writer = None
        self._readers = []

    def __enter__(self) -> "Cache":
        """Returns the cache so it can be used as a context manager."""
        return self

    def __exit__(self, *_exception) -> None:
        """Closes the cache when the context exits."""
        self.close()


def missing_files(paths: Sequence[str]) -> List[str]:
    """Returns the subset of the given paths that are not existing files."""
    return [path for path in paths if not Path(path).is_file()]
