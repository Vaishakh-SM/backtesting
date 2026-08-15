"""Shared fixtures.

Tests never touch the network. The vendor call is the one thing that would, so
it is substituted; everything downstream of it runs for real against a
temporary store.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import polars as pl
import pyarrow as pa
import pytest

from backtester.conventions import TZ
from backtester.data.dataset import DatasetRef
from backtester.data.duckdb_reader import read_window as duckdb_read
from backtester.data.polars_reader import read_window as polars_read
from backtester.data.schema import ACTIONS_SCHEMA, PRICES_SCHEMA

NY = ZoneInfo(TZ)


def ts(y: int, m: int, d: int, hour: int = 16) -> datetime:
    """An exchange close, which is when a signal is computed."""
    return datetime(y, m, d, hour, tzinfo=NY)


def prices_table(
    rows: Sequence[tuple[str, datetime, float]],
    knowledge_ts: datetime | None,
    source: str = "test",
) -> pa.Table:
    """Build a prices table from (ticker, event_ts, close) triples.

    OHLC are all set to `close`: these tests are about the bitemporal
    machinery, not about candles.

    `knowledge_ts=None` stamps each row at its own event_ts, which is what a
    vendor fetch looks like before ingestion reconciles it.
    """
    if not rows:
        return PRICES_SCHEMA.empty_table()
    frame = pd.DataFrame(
        {
            "ticker": [r[0] for r in rows],
            "event_ts": [r[1] for r in rows],
            "open": [r[2] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[2] for r in rows],
            "volume": [1_000 for _ in rows],
            "knowledge_ts": [knowledge_ts or r[1] for r in rows],
            "source": source,
            "event_year": [r[1].year for r in rows],
        }
    )
    return pa.Table.from_pandas(frame, schema=PRICES_SCHEMA, preserve_index=False)


def actions_table(
    rows: Sequence[tuple[str, datetime, str, float]],
    knowledge_ts: datetime | None,
) -> pa.Table:
    """Build an actions table from (ticker, event_ts, kind, value) tuples."""
    if not rows:
        return ACTIONS_SCHEMA.empty_table()
    frame = pd.DataFrame(
        {
            "ticker": [r[0] for r in rows],
            "event_ts": [r[1] for r in rows],
            "kind": [r[2] for r in rows],
            "value": [r[3] for r in rows],
            "knowledge_ts": [knowledge_ts or r[1] for r in rows],
            "source": "test",
            "event_year": [r[1].year for r in rows],
        }
    )
    return pa.Table.from_pandas(frame, schema=ACTIONS_SCHEMA, preserve_index=False)


def read_table(ref: DatasetRef, table: str) -> pl.DataFrame:
    """Everything in a table, restatements and all.

    Deliberately not the reader under test: assertions about what was *stored*
    should not depend on the deduplication being correct.
    """
    return pl.scan_parquet(ref.scan(table), **ref.as_polars()).collect()


# Every reader test runs against both engines. Nothing forces the two to agree,
# so the parametrisation is the thing keeping them in step.
Reader = Callable[..., pl.DataFrame]
READERS = pytest.mark.parametrize("read", [polars_read, duckdb_read], ids=["polars", "duckdb"])


@pytest.fixture
def store(tmp_path: Path) -> DatasetRef:
    """An empty dataset root for a single test."""
    return DatasetRef(str(tmp_path / "us-equities"))
