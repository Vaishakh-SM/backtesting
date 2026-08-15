"""Where a dataset lives, and how to describe it to a query engine."""

from __future__ import annotations

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

    The as_* methods return configuration, never live connections, so this type
    never imports an engine just to describe where files live. Supporting
    another engine means adding another as_* method.
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

    def as_polars(self) -> dict[str, Any]:
        """Keyword arguments for pl.scan_parquet."""
        opts: dict[str, Any] = {"hive_partitioning": True}
        if self.is_remote:
            opts["storage_options"] = dict(self.storage_options)
        return opts

    def as_duckdb(self) -> Sequence[str]:
        """SQL to run before querying. Empty for a local root."""
        if not self.is_remote:
            return []
        stmts = ["INSTALL httpfs", "LOAD httpfs"]
        if region := self.storage_options.get("region"):
            stmts.append(f"SET s3_region='{region}'")
        if endpoint := self.storage_options.get("endpoint"):
            stmts.append(f"SET s3_endpoint='{endpoint}'")
            stmts.append("SET s3_use_ssl=false")
            stmts.append("SET s3_url_style='path'")
        return stmts


class MissingData(ValueError):
    """A table has no files yet. Raised by every reader, so the message and the
    suggested fix live in one place."""

    def __init__(self, ref: DatasetRef, table: str) -> None:
        super().__init__(f"no {table} data at {ref.table(table)} — run `backtester ingest` first")
