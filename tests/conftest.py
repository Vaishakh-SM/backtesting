"""Shared fixtures.

Tests never touch the network. The vendor call is the one thing that would, so
it is substituted; everything downstream of it runs for real against a
temporary store.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pytest

from qrt.data.dataset import DatasetRef
from qrt.data.schema import ACTIONS_SCHEMA, PRICES_SCHEMA, TZ

NY = ZoneInfo(TZ)


def ts(y: int, m: int, d: int, hour: int = 16) -> datetime:
    """An exchange close, which is when a signal is computed."""
    return datetime(y, m, d, hour, tzinfo=NY)


def prices_table(
    rows: Sequence[tuple[str, datetime, float]],
    knowledge_ts: datetime,
    source: str = "test",
) -> pa.Table:
    """Build a prices table from (ticker, event_ts, close) triples.

    OHLC are all set to `close`: these tests are about the bitemporal
    machinery, not about candles.
    """
    frame = pd.DataFrame(
        {
            "ticker": [r[0] for r in rows],
            "event_ts": [r[1] for r in rows],
            "open": [r[2] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[2] for r in rows],
            "volume": [1_000 for _ in rows],
            "knowledge_ts": knowledge_ts,
            "source": source,
            "event_year": [r[1].year for r in rows],
        }
    )
    return pa.Table.from_pandas(frame, schema=PRICES_SCHEMA, preserve_index=False)


def actions_table(
    rows: Sequence[tuple[str, datetime, str, float]],
    knowledge_ts: datetime,
) -> pa.Table:
    """Build an actions table from (ticker, event_ts, kind, value) tuples."""
    frame = pd.DataFrame(
        {
            "ticker": [r[0] for r in rows],
            "event_ts": [r[1] for r in rows],
            "kind": [r[2] for r in rows],
            "value": [r[3] for r in rows],
            "knowledge_ts": knowledge_ts,
            "source": "test",
            "event_year": [r[1].year for r in rows],
        }
    )
    return pa.Table.from_pandas(frame, schema=ACTIONS_SCHEMA, preserve_index=False)


@pytest.fixture
def store(tmp_path: Path) -> DatasetRef:
    """An empty dataset root for a single test."""
    return DatasetRef(str(tmp_path / "us-equities"))
