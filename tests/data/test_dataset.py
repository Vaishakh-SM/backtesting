"""DatasetRef path and engine-config translation."""

from __future__ import annotations

import pytest

from backtester.data.dataset import DatasetRef
from backtester.data.schema import PRICES


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


# --- object storage --------------------------------------------------------
# Verified against MinIO by hand; these lock in what that exercise found.


def test_duckdb_is_given_the_endpoint_without_its_scheme() -> None:
    """duckdb prepends the scheme itself, so passing one produces a request to
    http://http://host and an unresolvable hostname."""
    stmts = DatasetRef("s3://b/x", {"endpoint": "http://localhost:9000"}).as_duckdb()

    assert "SET s3_endpoint='localhost:9000'" in stmts
    assert not any("http://localhost" in s for s in stmts)


def test_ssl_follows_the_endpoint_scheme() -> None:
    https = DatasetRef("s3://b/x", {"endpoint": "https://s3.example.com"}).as_duckdb()
    http = DatasetRef("s3://b/x", {"endpoint": "http://localhost:9000"}).as_duckdb()

    assert "SET s3_use_ssl=true" in https
    assert "SET s3_use_ssl=false" in http


def test_credentials_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """polars and pyarrow read AWS_* themselves; duckdb does not, so they are
    passed explicitly. Never from a spec or a config file — those get committed,
    and a spec travels through a queue."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")

    stmts = DatasetRef("s3://b/x", {"region": "us-east-1"}).as_duckdb()
    assert "SET s3_access_key_id='key'" in stmts
    assert "SET s3_secret_access_key='secret'" in stmts


def test_no_credentials_in_the_environment_means_none_are_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An instance profile or a mounted role supplies them elsewhere."""
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(var, raising=False)

    assert not any("access_key" in s for s in DatasetRef("s3://b/x").as_duckdb())


def test_a_quote_in_a_secret_does_not_break_the_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ke'y")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")

    assert "SET s3_access_key_id='ke''y'" in DatasetRef("s3://b/x").as_duckdb()


def test_a_local_root_needs_none_of_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")

    assert DatasetRef("/data/us-equities").as_duckdb() == []
