"""DatasetRef path and engine-config translation."""

from __future__ import annotations

from qrt.data.dataset import DatasetRef
from qrt.data.schema import PRICES


def test_local_root_needs_no_duckdb_setup() -> None:
    assert DatasetRef("/data/us-equities").as_duckdb() == []


def test_remote_root_loads_httpfs_and_sets_region() -> None:
    stmts = DatasetRef("s3://research/us-equities", {"region": "us-east-1"}).as_duckdb()
    assert "LOAD httpfs" in stmts
    assert "SET s3_region='us-east-1'" in stmts


def test_storage_options_only_travel_for_remote_roots() -> None:
    assert "storage_options" not in DatasetRef("/data/x").as_polars()
    assert "storage_options" in DatasetRef("s3://b/x", {"region": "eu-west-1"}).as_polars()


def test_table_and_scan_paths() -> None:
    ref = DatasetRef("/data/us-equities")
    assert ref.table(PRICES) == "/data/us-equities/prices"
    assert ref.scan(PRICES) == "/data/us-equities/prices/**/*.parquet"


def test_trailing_slash_in_root_does_not_double_up() -> None:
    assert DatasetRef("/data/us-equities/").table(PRICES) == "/data/us-equities/prices"
