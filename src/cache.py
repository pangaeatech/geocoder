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

READ_COLUMNS = ("query", "version", "response")
WRITE_COLUMNS = READ_COLUMNS + ("fetched_at",)

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
        self._writer: Optional[sqlite3.Connection] = None
        self._readers: List[sqlite3.Connection] = []
        self._uncommitted = 0
        try:
            for read_path in read_paths:
                self._readers.append(self._open_reader(read_path))
            if path:
                self._writer = self._open_writer(path)
        except BaseException:
            self.close()
            raise

    @property
    def _table(self) -> str:
        """Returns this provider's table name, quoted for use in a statement."""
        escaped = self._api.replace('"', '""')
        return f'"{escaped}"'

    def _open_writer(self, path: str) -> sqlite3.Connection:
        """
        Opens the read-write cache, creating the file and this provider's table when absent.

        A table of this provider's name already in the file is checked for every
        column lookups and writes use, so an incompatible one is refused before
        any work is done rather than failing on its first lookup.

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
            If the file cannot be opened, is not a SQLite database, or holds a
            table for this provider without the columns a cache needs.
        """
        return self._open(path, read_only=False)

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
            If the file cannot be opened, is not a SQLite database, or holds no
            usable table for this provider.
        """
        return self._open(path, read_only=True)

    def _open(self, path: str, read_only: bool) -> sqlite3.Connection:
        """
        Connects to a cache file, closing it again if it cannot serve this provider.

        A read-only file is opened through a URI so SQLite refuses every write;
        a writable one is opened by its literal path and gains this provider's
        table when it lacks one.

        Parameters
        ----------
        path : str
            The path of the cache file.
        read_only : bool
            Whether to open the file read-only rather than read-write.

        Return
        ----------
        sqlite3.Connection
            A connection whose provider table carries every required column.

        Raises
        ----------
        ValueError
            If the file cannot be opened or cannot serve this provider.
        """
        try:
            if read_only:
                connection = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
            else:
                connection = sqlite3.connect(path)
        except sqlite3.Error as error:
            raise ValueError(f"'{path}' cannot be opened as a cache: {error}") from error

        try:
            self._check_table(connection, path, READ_COLUMNS if read_only else WRITE_COLUMNS, create=not read_only)
        except BaseException:
            connection.close()
            raise
        return connection

    def _check_table(self, connection: sqlite3.Connection, path: str, required: Sequence[str], create: bool) -> None:
        """
        Confirms this provider's table exists and carries the given columns.

        Parameters
        ----------
        connection : sqlite3.Connection
            The open cache file.
        path : str
            The cache file's path as the user gave it, used in error messages.
        required : Sequence[str]
            The columns the table must carry.
        create : bool
            Whether to create the table when the file lacks it.

        Raises
        ----------
        ValueError
            If the file is not a SQLite database, or its table is absent or
            lacks any of the required columns.
        """
        try:
            if create:
                connection.execute(SCHEMA.format(table=self._table))
                connection.commit()
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({self._table})")}
        except sqlite3.DatabaseError as error:
            raise ValueError(f"'{path}' is not a usable SQLite database: {error}") from error

        if not columns:
            raise ValueError(f"'{path}' holds no cached '{self._api}' responses")

        missing = [column for column in required if column not in columns]
        if missing:
            raise ValueError(f"'{path}' is not a geocoder cache (its '{self._api}' table is missing {', '.join(missing)})")

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
        stored, were stored under a version this run no longer calls, or hold
        a response that is not valid JSON. A corrupt entry is treated like any
        other miss, so a later file or the provider answers in its place.

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
                    try:
                        found[key] = json.loads(response)
                    except (TypeError, ValueError):
                        continue
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

    def __exit__(self, *_exception: object) -> None:
        """Closes the cache when the context exits."""
        self.close()


def missing_files(paths: Sequence[str]) -> List[str]:
    """Returns the subset of the given paths that are not existing files."""
    return [path for path in paths if not Path(path).is_file()]
