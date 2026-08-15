"""Lookahead, tested where it would actually hurt.

tests/data/test_bounds.py checks that a window cannot reach past its cutoff.
This checks the thing that follows from it and is what anyone actually cares
about: data arriving later does not change a position that was already taken.

A lookahead bug does not raise. It returns a better equity curve, which is why
it survives review — the output looks like success.
"""

from __future__ import annotations

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from qrt.backtest.calendar import trading_days
from qrt.backtest.engine import run_backtest
from qrt.backtest.spec import BacktestSpec
from qrt.data.dataset import DatasetRef
from qrt.data.schema import ACTIONS, PRICES
from qrt.data.writer import append
from qrt.strategy.trailing_return import TrailingReturn
from tests.conftest import actions_table, prices_table, ts

UNIVERSE = ("AAPL", "MSFT", "NVDA", "XOM")
DRIFT = {"AAPL": 1.0, "MSFT": 0.4, "NVDA": -0.3, "XOM": -0.8}

INGESTED = ts(2024, 1, 1, hour=0)
LATER = ts(2026, 6, 1, hour=6)


@pytest.fixture
def seeded(store: DatasetRef) -> DatasetRef:
    """Each name drifts at its own steady rate, so the ranking is unambiguous
    and any change to it is a real change."""
    sessions = trading_days(ts(2024, 1, 2), ts(2024, 6, 28))
    rows = [
        (ticker, session, 100.0 + drift * i)
        for ticker, drift in DRIFT.items()
        for i, session in enumerate(sessions)
    ]
    append(store, PRICES, prices_table(rows, None), INGESTED)
    append(store, ACTIONS, actions_table([], None), INGESTED)
    return store


def spec() -> BacktestSpec:
    return BacktestSpec(
        universe=UNIVERSE,
        start=ts(2024, 3, 1),
        end=ts(2024, 5, 31),
        strategy=TrailingReturn(
            lookback_sessions=20, direction=1, top_fraction=0.25, bottom_fraction=0.25
        ),
        as_of_knowledge=ts(2026, 12, 31),
    )


def decisions(store: DatasetRef) -> tuple[pl.DataFrame, pl.DataFrame]:
    result = run_backtest(spec(), store)
    return result.scores.sort("rebalance_ts", "ticker"), result.positions.sort(
        "rebalance_ts", "ticker"
    )


def test_prices_after_the_backtest_do_not_change_its_decisions(seeded: DatasetRef) -> None:
    """The most direct form of the test. Six months of history arrive after the
    run ends; every score and every position must be identical."""
    scores_before, positions_before = decisions(seeded)

    later_sessions = trading_days(ts(2024, 7, 1), ts(2024, 12, 31))
    shock = [
        (ticker, session, 1000.0 if ticker == "XOM" else 1.0)
        for ticker in UNIVERSE
        for session in later_sessions
    ]
    append(seeded, PRICES, prices_table(shock, None), LATER)

    scores_after, positions_after = decisions(seeded)
    assert_frame_equal(scores_before, scores_after)
    assert_frame_equal(positions_before, positions_after)


def test_a_restatement_of_history_does_not_change_past_decisions(
    seeded: DatasetRef,
) -> None:
    """Harder to catch than a future bar: the corrected value is for a date the
    strategy legitimately saw, so only the knowledge cutoff keeps it out.

    Run point-in-time, a correction learned in 2026 is invisible to a decision
    made in 2024.
    """
    scores_before, positions_before = decisions(seeded)

    sessions = trading_days(ts(2024, 1, 2), ts(2024, 6, 28))
    restated = [("XOM", session, 9_999.0) for session in sessions]
    append(seeded, PRICES, prices_table(restated, LATER), LATER)

    scores_after, positions_after = decisions(seeded)
    assert_frame_equal(scores_before, scores_after)
    assert_frame_equal(positions_before, positions_after)


def test_the_same_restatement_does_change_a_non_point_in_time_run(
    seeded: DatasetRef,
) -> None:
    """The counterpart. Pinning every read to one late cutoff is how an old run
    is reproduced or how the effect of restated data is measured — so it must
    actually see the correction. Without this, the test above could pass
    because nothing is being read at all.
    """
    sessions = trading_days(ts(2024, 1, 2), ts(2024, 6, 28))
    append(seeded, PRICES, prices_table([("XOM", s, 9_999.0) for s in sessions], LATER), LATER)

    point_in_time = run_backtest(spec(), seeded)

    from dataclasses import replace

    latest = run_backtest(replace(spec(), point_in_time=False), seeded)

    assert not point_in_time.scores.equals(latest.scores)


def test_the_universe_growing_later_does_not_change_past_decisions(
    seeded: DatasetRef,
) -> None:
    """Coverage of a name we did not hold arrives afterwards. Nothing about an
    earlier decision should move."""
    scores_before, positions_before = decisions(seeded)

    sessions = trading_days(ts(2024, 1, 2), ts(2024, 6, 28))
    append(seeded, PRICES, prices_table([("KO", s, 50.0) for s in sessions], LATER), LATER)

    scores_after, positions_after = decisions(seeded)
    assert_frame_equal(scores_before, scores_after)
    assert_frame_equal(positions_before, positions_after)


def test_the_decisions_are_not_empty(seeded: DatasetRef) -> None:
    """Two empty frames compare equal, so every test above would pass on a
    backtest that did nothing at all."""
    scores, positions = decisions(seeded)
    assert scores.height > 0
    assert positions.height > 0
    assert positions["rebalance_ts"].n_unique() >= 2
