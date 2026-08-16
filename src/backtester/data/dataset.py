"""Where a dataset lives, and how to describe it to a query engine."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DatasetRef:
    """Points at a dataset root and describes it to a query engine.

    The root already says whether this is local or remote, so there is one
    type rather than two:

        DatasetRef("/data/us-equities")
        DatasetRef("s3://research/us-equities", {"region": "us-east-1"})

    The per-engine methods return configuration, never live connections, so
    this type never imports an engine just to describe where files live.
    Supporting another engine means adding another such method. Each is named
    for what it returns rather than for the engine alone, because what an
    engine needs differs: polars takes keyword arguments, duckdb takes
    statements to execute.
    """

    root: str
    storage_options: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_remote(self) -> bool:
        return "://" in self.root

    def table(self, name: str) -> str:
        """Directory for one table. What the writer appends into."""
        return f"{self.root.rstrip('/')}/{name}"

    def scan(self, name: str) -> str:
        """Glob for one table. What a reader scans."""
        return f"{self.table(name)}/**/*.parquet"

    def polars_options(self) -> dict[str, Any]:
        """Keyword arguments for pl.scan_parquet."""
        opts: dict[str, Any] = {"hive_partitioning": True}
        if self.is_remote:
            opts["storage_options"] = dict(self.storage_options)
        return opts

    def duckdb_setup(self) -> Sequence[str]:
        """SQL to run before querying. Empty for a local root.

        Credentials come from the environment, never from a spec or a config
        file — those get committed, and a backtest spec travels through a
        queue. polars and pyarrow read AWS_* themselves; duckdb does not, so
        they are passed explicitly here.
        """
        if not self.is_remote:
            return []

        stmts = ["INSTALL httpfs", "LOAD httpfs"]
        if region := self.storage_options.get("region"):
            stmts.append(f"SET s3_region='{_sql(region)}'")

        # polars and pyarrow both honour AWS_ENDPOINT_URL, so duckdb does too.
        # Otherwise pointing at MinIO or any non-AWS S3 works for two of the
        # three libraries and fails for the third.
        endpoint = self.storage_options.get("endpoint") or os.environ.get("AWS_ENDPOINT_URL")
        if endpoint:
            # duckdb adds the scheme itself. Passing one produces a request to
            # http://http://host, which fails as an unresolvable hostname.
            scheme, _, host = endpoint.rpartition("//")
            stmts.append(f"SET s3_endpoint='{_sql(host)}'")
            stmts.append(f"SET s3_use_ssl={'true' if scheme.startswith('https') else 'false'}")
            stmts.append("SET s3_url_style='path'")

        key, secret = os.environ.get("AWS_ACCESS_KEY_ID"), os.environ.get("AWS_SECRET_ACCESS_KEY")
        if key and secret:
            stmts.append(f"SET s3_access_key_id='{_sql(key)}'")
            stmts.append(f"SET s3_secret_access_key='{_sql(secret)}'")
        if token := os.environ.get("AWS_SESSION_TOKEN"):
            stmts.append(f"SET s3_session_token='{_sql(token)}'")
        return stmts


class MissingData(ValueError):
    """A table has no files yet. Raised by every reader, so the message and the
    suggested fix live in one place."""

    def __init__(self, ref: DatasetRef, table: str) -> None:
        super().__init__(f"no {table} data at {ref.table(table)} — run `backtester ingest` first")


def _sql(value: str) -> str:
    """Escape a value for a duckdb SET statement. These are configuration
    strings rather than user input, but a secret containing a quote would
    otherwise produce a confusing syntax error."""
    return value.replace("'", "''")
