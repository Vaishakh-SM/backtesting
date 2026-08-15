"""The periodic ingestion job.

Runs on a schedule in deployment; invoked from the CLI here. Backtests never
fetch — they read what this has already landed, which is what keeps them
offline, reproducible, and independent of vendor uptime.
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
from qrt.data.schema import ACTIONS, PRICES, UNIVERSE, UNIVERSE_SCHEMA
from qrt.data.writer import append


@dataclass(frozen=True)
class IngestionSummary:
    knowledge_ts: datetime
    rows_appended: Mapping[str, int]
    failed: Mapping[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        counts = ", ".join(f"{t}={n}" for t, n in self.rows_appended.items())
        line = f"knowledge_ts={self.knowledge_ts.isoformat()}  {counts}"
        if self.failed:
            line += f"\nfailed: {', '.join(sorted(self.failed))}"
        return line


def ingest(
    ref: DatasetRef,
    tickers: Sequence[str],
    start: datetime,
    end: datetime,
    knowledge_ts: datetime,
) -> IngestionSummary:
    """Fetch, normalise, stamp, append.

    `knowledge_ts` is passed in rather than read from the clock, so the job is
    deterministic under test and a backfill can be stamped with the time it
    represents rather than the time it happened to run.

    Full history is re-fetched for every ticker on every run, not just the new
    tail. Yahoo restates prices when a split occurs, so a batch that only
    covered recent bars would leave the store mixing pre- and post-split
    conventions. Each batch is internally consistent instead, and the older
    batch stays readable.

    Re-running over a period already covered appends fresh observations rather
    than failing. Under append-only semantics that is correct, and reads
    deduplicate by (ticker, event_ts) anyway.
    """
    fetched = yahoo.fetch(tickers, start, end, knowledge_ts)

    appended = {
        PRICES: append(ref, PRICES, fetched.prices, knowledge_ts),
        ACTIONS: append(ref, ACTIONS, fetched.actions, knowledge_ts),
        UNIVERSE: append(
            ref,
            UNIVERSE,
            _universe_rows(tickers, fetched.failed, start, knowledge_ts),
            knowledge_ts,
        ),
    }

    return IngestionSummary(
        knowledge_ts=knowledge_ts,
        rows_appended=appended,
        failed=fetched.failed,
    )


def _universe_rows(
    tickers: Sequence[str],
    failed: Mapping[str, str],
    start: datetime,
    knowledge_ts: datetime,
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
            "knowledge_ts": knowledge_ts,
            "event_year": start.year,
        }
    )
    return pa.Table.from_pandas(frame, schema=UNIVERSE_SCHEMA, preserve_index=False)


def latest_knowledge_ts(ref: DatasetRef) -> datetime:
    """Newest observation in the store.

    Called when a spec is built so a fan-out pins one cutoff, instead of every
    worker resolving "latest" independently and getting a different answer.
    """
    empty = f"no data at {ref.table(PRICES)} — run `qrt ingest` first"
    try:
        newest = (
            pl.scan_parquet(ref.scan(PRICES), **ref.as_polars())
            .select(pl.col("knowledge_ts").max())
            .collect()
            .item()
        )
    except Exception as exc:  # polars raises on an unmatched glob
        raise ValueError(empty) from exc
    if newest is None:
        raise ValueError(empty)
    return newest
