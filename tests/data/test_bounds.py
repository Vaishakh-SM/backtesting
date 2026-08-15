"""Causality. The test that matters most in a backtester.

A lookahead bug does not crash — it returns a beautiful equity curve. Filter
tests in test_readers.py check that the bounds are applied; these check the
stronger property, which is that data arriving *later* cannot change an answer
already given.

The shape is: read a window, append rows the window must not have seen, read
the same window again, and assert nothing moved. A backtester that fails this
is not wrong by a little.
"""

from __future__ import annotations

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from backtester.data.dataset import DatasetRef
from backtester.data.schema import PRICES, PRICES_KEY
from backtester.data.writer import append
from tests.conftest import READERS, Reader, prices_table, ts

# Ingested the evening after the last bar, which is what a nightly job does.
# It has to precede the decision: data stamped as learned *after* a rebalance
# is correctly invisible to it, and a fixture that got this wrong would make
# every test below pass on an empty frame.
INGESTED = ts(2026, 1, 6, hour=18)
LATER = ts(2026, 9, 1, hour=6)

DECISION_AT = ts(2026, 1, 8)
HISTORY = [
    ("AAPL", ts(2026, 1, 5), 100.0),
    ("AAPL", ts(2026, 1, 6), 101.0),
    ("MSFT", ts(2026, 1, 5), 200.0),
    ("MSFT", ts(2026, 1, 6), 202.0),
]


def decision_window(read: Reader, store: DatasetRef) -> pl.DataFrame:
    """What a strategy deciding on 2026-01-08 is allowed to see.

    Asserts non-empty on the way out. Every test here compares a window before
    and after new data arrives, and two empty frames compare equal — so without
    this a broken bound would look like a passing causality test.
    """
    rows = read(
        store,
        PRICES,
        PRICES_KEY,
        ("AAPL", "MSFT"),
        ts(2026, 1, 1, hour=0),
        DECISION_AT,
        DECISION_AT,
    )
    assert rows.height == len(HISTORY), "window is empty; the test would pass vacuously"
    return rows


@pytest.fixture
def seeded(store: DatasetRef) -> DatasetRef:
    append(store, PRICES, prices_table(HISTORY, INGESTED), INGESTED)
    return store


@READERS
def test_future_bars_do_not_change_a_past_window(read: Reader, seeded: DatasetRef) -> None:
    """The next three weeks of history arrive. The decision made on the 8th is
    exactly what it was."""
    before = decision_window(read, seeded)

    append(
        seeded,
        PRICES,
        prices_table(
            [
                ("AAPL", ts(2026, 1, 9), 500.0),
                ("AAPL", ts(2026, 1, 20), 900.0),
                ("MSFT", ts(2026, 1, 9), 1.0),
            ],
            LATER,
        ),
        LATER,
    )

    assert_frame_equal(before, decision_window(read, seeded))


@READERS
def test_a_later_restatement_does_not_change_a_past_window(
    read: Reader, seeded: DatasetRef
) -> None:
    """The vendor corrects a price we already traded on. A point-in-time run is
    unaffected, because that correction did not exist when the decision was
    made.

    This is the axis a single-snapshot store cannot express: without
    knowledge_ts, the corrected value silently replaces what we believed and
    the old backtest becomes unreproducible.
    """
    before = decision_window(read, seeded)

    append(
        seeded,
        PRICES,
        prices_table([("AAPL", ts(2026, 1, 5), 42.0)], LATER),
        LATER,
    )

    after = decision_window(read, seeded)
    assert_frame_equal(before, after)
    assert after.filter(pl.col("ticker") == "AAPL")["close"].to_list() == [100.0, 101.0]


@READERS
def test_the_correction_is_visible_once_knowledge_catches_up(
    read: Reader, seeded: DatasetRef
) -> None:
    """The counterpart to the test above: the guarantee is that late data does
    not leak backwards, not that it is thrown away."""
    append(seeded, PRICES, prices_table([("AAPL", ts(2026, 1, 5), 42.0)], LATER), LATER)

    rows = read(
        seeded, PRICES, PRICES_KEY, ("AAPL",), ts(2026, 1, 1, hour=0), DECISION_AT, ts(2026, 12, 31)
    )
    assert rows["close"].to_list() == [42.0, 101.0]


@READERS
def test_a_window_is_unaffected_by_names_outside_the_universe(
    read: Reader, seeded: DatasetRef
) -> None:
    """Adding coverage of new tickers does not perturb an existing result."""
    before = decision_window(read, seeded)

    append(seeded, PRICES, prices_table([("NVDA", ts(2026, 1, 6), 300.0)], LATER), LATER)

    assert_frame_equal(before, decision_window(read, seeded))
