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

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    api TEXT NOT NULL,
    query TEXT NOT NULL,
    original_query TEXT NOT NULL,
    response TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (api, query)
)
"""


def normalize_query(query: str) -> str:
    """
    Canonicalizes a provider query into the key its response is stored under.

    Letter case and runs of whitespace are folded so equivalent queries share one
    cached response; nothing else is altered, since punctuation and abbreviations
    can change what a geocoder returns.

    Parameters
    ----------
    query : str
        The query text a provider would send for a record.

    Return
    ----------
    str
        The canonical key for that query.
    """
    return " ".join(query.split()).casefold()


class Cache:
    """
    A SQLite-backed store of raw provider responses keyed by the query that produced them.

    It is never a source of truth: deleting a cache file changes nothing but how
    many API calls a run costs, and one table serves every provider.
    """

    COMMIT_INTERVAL = 250
    LOOKUP_CHUNK = 500

    def __init__(self, path: Optional[str] = None, read_paths: Sequence[str] = ()):
        self._writer = self._open_writer(path) if path else None
        self._readers = [self._open_reader(read_path) for read_path in read_paths]
        self._uncommitted = 0

    @staticmethod
    def _open_writer(path: str) -> sqlite3.Connection:
        """
        Opens the read-write cache, creating the file and table when absent.

        Parameters
        ----------
        path : str
            The path of the cache file to open or create.

        Return
        ----------
        sqlite3.Connection
            A connection with the cache table in place.

        Raises
        ----------
        ValueError
            If the path names an existing file that is not a SQLite database.
        """
        connection = sqlite3.connect(path)
        try:
            connection.execute(SCHEMA)
            connection.commit()
        except sqlite3.DatabaseError as error:
            connection.close()
            raise ValueError(f"'{path}' cannot be used as a cache: {error}") from error
        return connection

    @staticmethod
    def _open_reader(path: str) -> sqlite3.Connection:
        """
        Opens a cache file read-only and confirms it carries the cache table.

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
            If the file is not a SQLite database or holds no cache table.
        """
        connection = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
        try:
            found = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'cache'").fetchone()
        except sqlite3.DatabaseError as error:
            connection.close()
            raise ValueError(f"'{path}' is not a readable SQLite database: {error}") from error

        if found is None:
            connection.close()
            raise ValueError(f"'{path}' is not a geocoder cache (it has no 'cache' table)")
        return connection

    def _connections(self) -> Iterator[sqlite3.Connection]:
        """Yields the writable cache first, then each read-only cache in the order given."""
        if self._writer is not None:
            yield self._writer
        yield from self._readers

    def lookup(self, api: str, keys: Iterable[str]) -> Dict[str, Any]:
        """
        Fetches the stored responses for the given keys, writable cache first.

        The first file holding a key wins, and keys with no stored response are
        absent from the result.

        Parameters
        ----------
        api : str
            The provider name whose entries are searched.
        keys : Iterable[str]
            The normalized query keys to look for.

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
                rows = connection.execute(f"SELECT query, response FROM cache WHERE api = ? AND query IN ({placeholders})", [api, *chunk])
                for key, response in rows:
                    found[key] = json.loads(response)
            outstanding = [key for key in outstanding if key not in found]

        return found

    def store(self, api: str, key: str, query: str, response: Any) -> None:
        """
        Records one provider response, committing once a batch has accumulated.

        Committing as the run proceeds means a crash costs only the calls made
        since the last commit.

        Parameters
        ----------
        api : str
            The provider name the response came from.
        key : str
            The normalized query key to store the response under.
        query : str
            The query text as the provider composed it, kept for manual review.
        response : Any
            The raw provider response, stored as JSON.
        """
        if self._writer is None:
            return

        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._writer.execute(
            "INSERT OR REPLACE INTO cache (api, query, original_query, response, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (api, key, query, json.dumps(response, ensure_ascii=False), fetched_at),
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
