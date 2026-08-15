"""The periodic ingestion job.

Runs on a schedule in deployment; invoked from the CLI here. Backtests never
fetch — they read what this has already landed, which is what keeps them
offline, reproducible, and independent of vendor uptime.

Every fetched row is reconciled against what the store already holds:

    not seen before   ->  knowledge_ts = event_ts   (published at the close)
    contradicts       ->  knowledge_ts = now        (we learned it just now)
    identical         ->  dropped                   (nothing new to record)

Exchange prices publish at the close with no revision lag, so stamping a first
observation at its event time models publication rather than inventing it. The
lie we are avoiding is the other one: stamping a re-fetched, split-adjusted
2020 price as though we had known it in 2020. That is what the second rule is
for, and why the comparison has to happen at write time.

Dropping identical rows makes a re-run genuinely idempotent, and leaves the log
holding exactly the first observations plus the real corrections.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
import polars as pl
import pyarrow as pa

from qrt.data import yahoo
from qrt.data.dataset import DatasetRef
from qrt.data.polars_reader import read_latest
from qrt.data.schema import (
    ACTIONS,
    ACTIONS_KEY,
    ACTIONS_VALUES,
    PRICES,
    PRICES_KEY,
    PRICES_VALUES,
    TZ,
    UNIVERSE,
    UNIVERSE_KEY,
    UNIVERSE_SCHEMA,
    UNIVERSE_VALUES,
)
from qrt.data.writer import append


@dataclass(frozen=True)
class IngestionSummary:
    ingested_at: datetime
    first_observations: Mapping[str, int]
    restatements: Mapping[str, int]
    failed: Mapping[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        parts = []
        for table in sorted(self.first_observations):
            new = self.first_observations[table]
            fixed = self.restatements.get(table, 0)
            parts.append(f"{table}={new}" + (f" (+{fixed} restated)" if fixed else ""))
        line = f"ingested_at={self.ingested_at.isoformat()}  " + ", ".join(parts)
        if self.failed:
            line += f"\nfailed: {', '.join(sorted(self.failed))}"
        return line


def ingest(
    ref: DatasetRef,
    tickers: Sequence[str],
    start: datetime,
    end: datetime,
    ingested_at: datetime,
) -> IngestionSummary:
    """Fetch, reconcile against the store, append what is actually new.

    `ingested_at` is passed in rather than read from the clock, so the job is
    deterministic under test and a backfill can be stamped with the time it
    represents.

    Full history is re-fetched for every ticker on every run, not just the new
    tail. Yahoo restates prices when a split occurs, so a batch covering only
    recent bars would leave the store mixing pre- and post-split conventions.
    Reconciliation then means only the rows that genuinely changed are written.
    """
    fetched = yahoo.fetch(tickers, start, end)

    first: dict[str, int] = {}
    restated: dict[str, int] = {}

    for table, rows, key, values in (
        (PRICES, fetched.prices, PRICES_KEY, PRICES_VALUES),
        (ACTIONS, fetched.actions, ACTIONS_KEY, ACTIONS_VALUES),
        (
            UNIVERSE,
            _universe_rows(tickers, fetched.failed, start),
            UNIVERSE_KEY,
            UNIVERSE_VALUES,
        ),
    ):
        new_rows, corrections = _what_changed(ref, table, rows, key, values, ingested_at)
        append(ref, table, new_rows, ingested_at)
        first[table] = new_rows.num_rows - corrections
        restated[table] = corrections

    return IngestionSummary(
        ingested_at=ingested_at,
        first_observations=first,
        restatements=restated,
        failed=fetched.failed,
    )


def _what_changed(
    ref: DatasetRef,
    table: str,
    fetched: pa.Table,
    key: Sequence[str],
    values: Sequence[str],
    ingested_at: datetime,
) -> tuple[pa.Table, int]:
    """Which fetched rows are worth writing, and how they should be stamped.

    Returns the rows to write, and how many of them are corrections rather
    than first observations.
    """
    if fetched.num_rows == 0:
        return fetched, 0

    stored = _stored_values(ref, table, key, values)
    if stored is None:
        return fetched, 0  # first ever run: everything is a first observation

    frame = pl.from_arrow(fetched)
    assert isinstance(frame, pl.DataFrame)

    joined = frame.join(stored, on=list(key), how="left", suffix="__stored")

    seen = pl.col(f"{values[0]}__stored").is_not_null()
    unchanged = pl.all_horizontal([pl.col(v) == pl.col(f"{v}__stored") for v in values])

    # Exact comparison, not a tolerance. A tolerance would silently swallow
    # small genuine corrections, and parquet round-trips f64 exactly, so an
    # unchanged value compares equal.
    changed = (
        joined.filter(seen & ~unchanged)
        .with_columns(
            pl.lit(ingested_at).cast(pl.Datetime("us", TZ)).alias("knowledge_ts"),
        )
        .select([*frame.columns, "knowledge_ts__stored"])
    )

    _reject_ties(changed, table, key)

    brand_new = joined.filter(~seen).select(frame.columns)
    changed = changed.select(frame.columns)

    return pl.concat([brand_new, changed]).to_arrow().cast(fetched.schema), changed.height


def _reject_ties(changed: pl.DataFrame, table: str, key: Sequence[str]) -> None:
    """Refuse a correction that would land on the same instant as the row it
    corrects.

    Backdating is deliberately allowed — a vendor's real publication times, or
    a fix to our own normaliser where the correct value genuinely was available
    at the time. What is not allowed is a tie, because two rows sharing a key
    and a knowledge_ts have no defined winner and a reader would pick one
    arbitrarily. The ambiguity is the bug, not the direction.
    """
    ties = changed.filter(pl.col("knowledge_ts") == pl.col("knowledge_ts__stored"))
    if ties.is_empty():
        return
    example = ties.select(key).row(0)
    raise ValueError(
        f"{table}: correction for {dict(zip(key, example, strict=True))} carries the same "
        f"knowledge_ts as the row it corrects, so which one a reader sees would be "
        f"arbitrary. Use a distinct timestamp."
    )


def _stored_values(
    ref: DatasetRef,
    table: str,
    key: Sequence[str],
    values: Sequence[str],
) -> pl.DataFrame | None:
    """What the store currently says, keyed for joining against a fetch.

    None if the table has never been written.
    """
    try:
        return (
            read_latest(ref, table, key)
            .select([*key, *values, "knowledge_ts"])
            .rename({v: f"{v}__stored" for v in [*values, "knowledge_ts"]})
        )
    except ValueError:
        return None


def _universe_rows(
    tickers: Sequence[str],
    failed: Mapping[str, str],
    start: datetime,
) -> pa.Table:
    """Membership as a step function: one row per ticker saying it was in the
    universe from `start` onwards.

    A static list, so this carries no real point-in-time information — it is
    where the survivorship bias in docs/ASSUMPTIONS.md lives. The table shape
    is here so that dated membership can replace it without a migration.
    """
    live = [t for t in tickers if t not in failed]
    if not live:
        return UNIVERSE_SCHEMA.empty_table()

    frame = pd.DataFrame(
        {
            "ticker": live,
            "event_ts": start,
            "in_universe": True,
            "knowledge_ts": start,
            "event_year": start.year,
        }
    )
    return pa.Table.from_pandas(frame, schema=UNIVERSE_SCHEMA, preserve_index=False)
