#!/usr/bin/python3
# -.- coding: utf-8 -.-

"""
Geocoder Census Provider Tests
"""

import pytest

from src import census
from src.api import PROVIDERS, SourceRecord


class _FakeResponse:
    """Stands in for a requests.Response so provider tests avoid the network."""

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        """Mimics a successful response by never raising."""


CENSUS_RESPONSE = (
    '"2","1 Main St, Anytown, CA","Tie"\r\n'
    '"0","1600 Pennsylvania Ave NW, Washington, DC, 20500","Match","Exact",'
    '"1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500","-77.03535,38.898754",'
    '"76225813","L","11","001","980000","1034"\r\n'
    '"1","Nowhere St, Nowhere, ZZ","No_Match"\r\n'
    '"3","500 W Madison St, Chicago, IL","Match","Non_Exact",'
    '"500 W MADISON ST, CHICAGO, IL, 60661","-87.63960,41.88187",'
    '"112042099","L","17","031","839100","1000"\r\n'
)


def test_census_registered():
    """@register("census") wires CensusProvider into the registry."""
    assert PROVIDERS["census"] is census.CensusProvider


def test_census_parses_batch(monkeypatch):
    """A batch response is parsed and aligned to records by internal key."""
    captured = {}

    def fake_post(url, data=None, files=None, timeout=None):
        captured.update(url=url, data=data, files=files, timeout=timeout)
        return _FakeResponse(CENSUS_RESPONSE)

    monkeypatch.setattr(census.requests, "post", fake_post)

    records = [
        SourceRecord(
            internal_key=0,
            address="1600 Pennsylvania Ave NW",
            city="Washington",
            stateprov="DC",
            postalcode="20500",
        ),
        SourceRecord(internal_key=1, address="Nowhere St", city="Nowhere", stateprov="ZZ"),
        SourceRecord(internal_key=2, address="1 Main St", city="Anytown", stateprov="CA"),
        SourceRecord(internal_key=3, address="500 W Madison St", city="Chicago", stateprov="IL"),
    ]

    results = census.CensusProvider().geocode(records)

    assert captured["url"] == census.CensusProvider.ENDPOINT
    assert captured["data"]["benchmark"] == "Public_AR_Census2020"
    assert captured["data"]["vintage"] == "Census2020_Census2020"

    exact = results[0]
    assert exact.match_type == "exact"
    assert exact.accuracy == 90
    assert exact.result_address == "1600 PENNSYLVANIA AVE NW"
    assert exact.result_city == "WASHINGTON"
    assert exact.result_stateprov == "DC"
    assert exact.result_postalcode == "20500"
    assert exact.longitude == "-77.03535"
    assert exact.latitude == "38.898754"
    assert exact.location_type == ""
    assert exact.result_id == "76225813"
    assert exact.result_country == "US"

    assert results[1].match_type == "no_match"
    assert results[1].accuracy == 0
    assert results[1].match_notes == "No match"

    assert results[2].match_type == "tie"
    assert results[2].accuracy == 0
    assert results[2].match_notes == "Tie"

    non_exact = results[3]
    assert non_exact.match_type == "non-exact"
    assert non_exact.accuracy == 90
    assert non_exact.result_id == "112042099"
    assert non_exact.result_country == "US"


def test_census_builds_csv_input(monkeypatch):
    """The posted CSV carries the internal key and address components."""
    captured = {}

    def fake_post(_url, files=None, **_kwargs):
        captured["csv"] = files["addressFile"][1]
        return _FakeResponse('"0","1 Main St, Town, CA","No_Match"\r\n')

    monkeypatch.setattr(census.requests, "post", fake_post)

    records = [
        SourceRecord(
            internal_key=0,
            address="1 Main St",
            city="Town",
            stateprov="CA",
            postalcode="90210",
        )
    ]
    census.CensusProvider().geocode(records)

    assert captured["csv"].startswith("0,")
    assert "1 Main St" in captured["csv"]
    assert "90210" in captured["csv"]


def test_census_raises_on_truncated_match_row(monkeypatch):
    """A match row missing pinned columns fails loudly instead of misparsing."""

    def fake_post(*_args, **_kwargs):
        return _FakeResponse('"0","1 Main St, Town, CA","Match","Exact","1 MAIN ST, TOWN, CA, 90210","-118.0,34.0"\r\n')

    monkeypatch.setattr(census.requests, "post", fake_post)

    with pytest.raises(ValueError):
        census.CensusProvider().geocode([SourceRecord(internal_key=0, address="1 Main St", city="Town", stateprov="CA")])


def test_census_raises_on_shifted_coordinates(monkeypatch):
    """A match whose coordinate slot is not a lon,lat pair signals layout drift and fails."""

    def fake_post(*_args, **_kwargs):
        return _FakeResponse('"0","1 Main St","Match","Exact","1 MAIN ST, TOWN, CA, 90210","L","76225813","11","001","980000","1034","EXTRA"\r\n')

    monkeypatch.setattr(census.requests, "post", fake_post)

    with pytest.raises(ValueError):
        census.CensusProvider().geocode([SourceRecord(internal_key=0, address="1 Main St", city="Town", stateprov="CA")])


def test_census_raises_on_row_count_mismatch(monkeypatch):
    """A response short of one row per record (retired benchmark, error body) fails loudly."""

    def fake_post(*_args, **_kwargs):
        return _FakeResponse('"0","1 Main St, Town, CA","No_Match"\r\n')

    monkeypatch.setattr(census.requests, "post", fake_post)

    records = [
        SourceRecord(internal_key=0, address="1 Main St", city="Town", stateprov="CA"),
        SourceRecord(internal_key=1, address="2 Oak St", city="Town", stateprov="CA"),
    ]
    with pytest.raises(ValueError):
        census.CensusProvider().geocode(records)


def test_census_cache_version_pins_the_dataset():
    """Cached entries are tagged with the dataset that answered them."""
    assert census.CensusProvider.BENCHMARK in census.CensusProvider.CACHE_VERSION
    assert census.CensusProvider.VINTAGE in census.CensusProvider.CACHE_VERSION


def test_census_posts_each_distinct_address_once(monkeypatch):
    """Repeated addresses are collapsed so the posted CSV carries one row each."""
    posted = []

    def fake_post(_url, files=None, **_kwargs):
        posted.append(files["addressFile"][1])
        keys = [line.split(",")[0] for line in files["addressFile"][1].splitlines() if line]
        return _FakeResponse("".join(f'"{key}","q","No_Match"\r\n' for key in keys))

    monkeypatch.setattr(census.requests, "post", fake_post)

    records = [
        SourceRecord(internal_key=0, address="1 Main St", city="Town", stateprov="CA"),
        SourceRecord(internal_key=1, address="1 MAIN  ST", city="Town", stateprov="CA"),
        SourceRecord(internal_key=2, address="2 Oak St", city="Town", stateprov="CA"),
    ]
    results = census.CensusProvider().geocode(records)

    assert len(posted) == 1
    assert len([line for line in posted[0].splitlines() if line]) == 2
    assert len(results) == 3


def test_census_raw_drops_the_run_local_id(monkeypatch):
    """The echoed internal key is not kept, since it means nothing outside its run."""

    def fake_post(*_args, **_kwargs):
        return _FakeResponse('"0","1 Main St, Town, CA","Match","Exact","1 MAIN ST, TOWN, CA, 90210","-118.0,34.0","1","L","06","037","1","1"\r\n')

    monkeypatch.setattr(census.requests, "post", fake_post)

    result = census.CensusProvider().geocode([SourceRecord(internal_key=0, address="1 Main St", city="Town", stateprov="CA")])[0]

    assert "id" not in result.raw
    assert result.raw["match_status"] == "Match"
