"""Default reader: lazy scan over parquet, filters pushed down.

Same signature as duckdb_reader.read_window, deliberately. The two modules are
a seam rather than an abstraction — switching engines means calling the other
function — and a test asserts they return identical frames.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import polars as pl

from backtester.data.dataset import DatasetRef, MissingData
from backtester.data.schema import PARTITION_COL, PRICES


def read_window(
    ref: DatasetRef,
    table: str,
    key: Sequence[str],
    universe: Sequence[str] | None,
    since: datetime,
    as_of_event: datetime,
    as_of_knowledge: datetime,
) -> pl.DataFrame:
    """Rows in (since, as_of_event], as known at as_of_knowledge.

    Applying both bounds here, rather than trusting the caller, is what makes
    lookahead unavailable to a strategy.

    Restatements collapse to one row per `key`. Without that, a corrected price
    would sit alongside the value it corrected and any aggregate over the
    window would count the day twice.

    `key` has no default on purpose: defaulting it to the prices key would let
    a caller reading actions silently treat a dividend and a split sharing an
    ex-date as one restating the other. `universe=None` reads every ticker.
    """
    predicates = [
        pl.col("event_ts") > since,
        pl.col("event_ts") <= as_of_event,
        pl.col("knowledge_ts") <= as_of_knowledge,
    ]
    if universe is not None:
        predicates.insert(0, pl.col("ticker").is_in(list(universe)))

    return _collect(_latest(_scan(ref, table).filter(*predicates), key), ref, table)


def read_latest(ref: DatasetRef, table: str, key: Sequence[str]) -> pl.DataFrame:
    """What we currently believe about every row in a table.

    No time bounds: this is the writer's question, not a strategy's. Ingestion
    uses it to tell a new observation from a restatement of one it holds.
    """
    return _collect(_latest(_scan(ref, table), key), ref, table)


def latest_knowledge_ts(ref: DatasetRef) -> datetime:
    """Newest observation in the store.

    Called when a spec is built, so a fan-out pins one cutoff instead of every
    worker resolving "latest" separately and getting a different answer.
    """
    newest = _collect(_scan(ref, PRICES).select(pl.col("knowledge_ts").max()), ref, PRICES).item()
    if newest is None:
        raise MissingData(ref, PRICES)
    return newest


def earliest_knowledge_ts(ref: DatasetRef) -> datetime:
    """Oldest observation in the store.

    The engine compares this against the first rebalance. A store backfilled in
    one go, stamped with the wall clock, knows nothing about any date before
    the backfill ran — so a point-in-time run over it would return empty
    windows at every rebalance and report no positions rather than failing.
    """
    oldest = _collect(_scan(ref, PRICES).select(pl.col("knowledge_ts").min()), ref, PRICES).item()
    if oldest is None:
        raise MissingData(ref, PRICES)
    return oldest


def _scan(ref: DatasetRef, table: str) -> pl.LazyFrame:
    return pl.scan_parquet(ref.scan(table), **ref.polars_options())


def _latest(frame: pl.LazyFrame, key: Sequence[str]) -> pl.LazyFrame:
    return (
        # Sorted inside each group rather than relying on scan order, so the
        # answer does not depend on which file a row landed in.
        frame.group_by(*key)
        .agg(pl.all().sort_by("knowledge_ts").last())
        .sort(*key)
        # event_year is a partition key, not a fact about the market.
        .drop(PARTITION_COL, strict=False)
    )


def _collect(frame: pl.LazyFrame, ref: DatasetRef, table: str) -> pl.DataFrame:
    try:
        return frame.collect()
    except pl.exceptions.ComputeError as exc:
        # The scan is lazy, so an unmatched glob surfaces here, not earlier.
        if "expanded paths were empty" not in str(exc):
            raise
        raise MissingData(ref, table) from exc
