"""Both readers, tested as one thing.

The two are a seam, not an abstraction: nothing forces them to agree. So the
first test asserts they return identical frames, and every behavioural test
below runs against both. A divergence is a bug in whichever one is wrong, and
this is the only thing that would catch it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from qrt.data.dataset import DatasetRef
from qrt.data.duckdb_reader import read_window as duckdb_read
from qrt.data.polars_reader import read_window as polars_read
from qrt.data.schema import PRICES, PRICES_KEY
from qrt.data.writer import append
from tests.conftest import READERS, Reader, prices_table, ts

BATCH_1 = ts(2026, 1, 10, hour=6)
BATCH_2 = ts(2026, 6, 20, hour=6)

WINDOW_START = ts(2026, 1, 1, hour=0)
WINDOW_END = ts(2026, 1, 8)
KNOWN_AT = ts(2026, 12, 31)


def seed(
    store: DatasetRef,
    rows: Sequence[tuple[str, datetime, float]],
    knowledge_ts: datetime = BATCH_1,
) -> None:
    append(store, PRICES, prices_table(rows, knowledge_ts), knowledge_ts)


def window(
    read: Reader,
    store: DatasetRef,
    universe: Sequence[str] | None = ("AAPL", "MSFT"),
    since: datetime = WINDOW_START,
    as_of_event: datetime = WINDOW_END,
    as_of_knowledge: datetime = KNOWN_AT,
) -> pl.DataFrame:
    return read(store, PRICES, PRICES_KEY, universe, since, as_of_event, as_of_knowledge)


def test_both_readers_agree(store: DatasetRef) -> None:
    """The property that lets us offer a choice of engine at all."""
    seed(
        store,
        [
            ("AAPL", ts(2026, 1, 5), 100.0),
            ("AAPL", ts(2026, 1, 6), 101.0),
            ("MSFT", ts(2026, 1, 5), 200.0),
            ("NVDA", ts(2026, 1, 5), 300.0),
        ],
    )
    # And a restatement, so the comparison covers the interesting path.
    seed(store, [("AAPL", ts(2026, 1, 5), 111.0)], knowledge_ts=BATCH_2)

    assert_frame_equal(
        window(polars_read, store),
        window(duckdb_read, store),
        check_column_order=False,
    )


@READERS
def test_restatement_collapses_to_the_newest_observation(read: Reader, store: DatasetRef) -> None:
    """Both versions are stored. Only one is read."""
    seed(store, [("AAPL", ts(2026, 1, 5), 100.0)], knowledge_ts=BATCH_1)
    seed(store, [("AAPL", ts(2026, 1, 5), 111.0)], knowledge_ts=BATCH_2)

    rows = window(read, store)
    assert rows.height == 1
    assert rows["close"].to_list() == [111.0]


@READERS
def test_a_cutoff_before_the_correction_sees_the_original(read: Reader, store: DatasetRef) -> None:
    """The point of the knowledge axis: an earlier run stays reproducible after
    the data is corrected."""
    seed(store, [("AAPL", ts(2026, 1, 5), 100.0)], knowledge_ts=BATCH_1)
    seed(store, [("AAPL", ts(2026, 1, 5), 111.0)], knowledge_ts=BATCH_2)

    rows = window(read, store, as_of_knowledge=ts(2026, 3, 1))
    assert rows["close"].to_list() == [100.0]


@READERS
def test_events_after_the_cutoff_are_unreachable(read: Reader, store: DatasetRef) -> None:
    seed(
        store,
        [
            ("AAPL", ts(2026, 1, 5), 100.0),
            ("AAPL", ts(2026, 1, 20), 999.0),  # beyond as_of_event
        ],
    )
    assert window(read, store)["close"].to_list() == [100.0]


@READERS
def test_events_before_the_lookback_are_excluded(read: Reader, store: DatasetRef) -> None:
    seed(
        store,
        [
            ("AAPL", ts(2025, 12, 20), 50.0),  # before `since`
            ("AAPL", ts(2026, 1, 5), 100.0),
        ],
    )
    assert window(read, store)["close"].to_list() == [100.0]


@READERS
def test_tickers_outside_the_universe_are_excluded(read: Reader, store: DatasetRef) -> None:
    seed(store, [("AAPL", ts(2026, 1, 5), 100.0), ("NVDA", ts(2026, 1, 5), 300.0)])
    assert window(read, store, universe=["AAPL"])["ticker"].to_list() == ["AAPL"]


@READERS
def test_no_universe_reads_every_ticker(read: Reader, store: DatasetRef) -> None:
    seed(store, [("AAPL", ts(2026, 1, 5), 100.0), ("NVDA", ts(2026, 1, 5), 300.0)])
    assert window(read, store, universe=None)["ticker"].to_list() == ["AAPL", "NVDA"]


@READERS
def test_partition_key_is_not_exposed(read: Reader, store: DatasetRef) -> None:
    """event_year is how bytes are laid out, not a fact about the market."""
    seed(store, [("AAPL", ts(2026, 1, 5), 100.0)])
    assert "event_year" not in window(read, store).columns


@READERS
def test_rows_come_back_ordered(read: Reader, store: DatasetRef) -> None:
    """So a strategy taking .last() gets the latest bar without sorting."""
    seed(
        store,
        [
            ("MSFT", ts(2026, 1, 6), 201.0),
            ("AAPL", ts(2026, 1, 6), 101.0),
            ("AAPL", ts(2026, 1, 5), 100.0),
        ],
    )
    rows = window(read, store)
    assert rows["ticker"].to_list() == ["AAPL", "AAPL", "MSFT"]
    assert rows["close"].to_list() == [100.0, 101.0, 201.0]


@READERS
def test_empty_window_is_not_an_error(read: Reader, store: DatasetRef) -> None:
    """A rebalance before any history exists yields nothing, not a crash."""
    seed(store, [("AAPL", ts(2026, 1, 5), 100.0)])
    assert window(read, store, as_of_event=ts(2026, 1, 2)).height == 0


@READERS
def test_missing_table_says_what_to_do(read: Reader, store: DatasetRef) -> None:
    with pytest.raises(ValueError, match="qrt ingest"):
        window(read, store)
