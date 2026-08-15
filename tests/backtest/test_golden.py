"""A full run over four tickers with the answer worked out on paper.

Tedious to write and worth it: this is the only test that says the whole chain
produces the number a person computed independently. Everything else checks a
piece in isolation, and a backtest can be wrong while every piece is right.

The data is contrived so the arithmetic is doable by hand — prices move in
round numbers and nothing pays a dividend.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from qrt.backtest.engine import run_backtest
from qrt.backtest.spec import BacktestSpec
from qrt.data.dataset import DatasetRef
from qrt.data.schema import ACTIONS, PRICES
from qrt.data.writer import append
from qrt.strategy.trailing_return import TrailingReturn
from tests.conftest import actions_table, prices_table, ts

# Four names over March-May 2024. Prices are set only on the dates that matter;
# every session in between is filled by a straight line so the series exists.
#
#   AAPL rises 20% over the signal window, MSFT 10%, NVDA falls 10%, XOM 20%.
#
# With top/bottom 25% of four names, that is one long and one short.
SIGNAL_START = ts(2024, 3, 1)
SIGNAL_END = ts(2024, 4, 30)

ANCHORS = {
    "AAPL": (100.0, 120.0),
    "MSFT": (100.0, 110.0),
    "NVDA": (100.0, 90.0),
    "XOM": (100.0, 80.0),
}


def build_store(store: DatasetRef, sessions: list[datetime]) -> None:
    """Straight-line each name between its two anchor prices."""
    rows = []
    for ticker, (first, last) in ANCHORS.items():
        for i, session in enumerate(sessions):
            fraction = i / (len(sessions) - 1)
            rows.append((ticker, session, first + (last - first) * fraction))

    ingested = ts(2024, 1, 1, hour=0)
    append(store, PRICES, prices_table(rows, None), ingested)
    append(store, ACTIONS, actions_table([], None), ingested)


@pytest.fixture
def seeded(store: DatasetRef) -> DatasetRef:
    from qrt.backtest.calendar import trading_days

    build_store(store, trading_days(ts(2024, 1, 2), ts(2024, 6, 28)))
    return store


def spec_for(**overrides: object) -> BacktestSpec:
    defaults: dict[str, object] = {
        "universe": ("AAPL", "MSFT", "NVDA", "XOM"),
        "start": ts(2024, 4, 1),
        "end": ts(2024, 6, 28),
        "strategy": TrailingReturn(lookback_sessions=20, direction=1),
        "as_of_knowledge": ts(2026, 1, 1),
        "top_fraction": 0.25,
        "bottom_fraction": 0.25,
        "cost_bps": 0.0,
        "rebalance_frequency": "M",
    }
    return BacktestSpec(**(defaults | overrides))  # type: ignore[arg-type]


def test_the_book_is_the_best_and_worst_name(seeded: DatasetRef) -> None:
    """Prices rise monotonically for AAPL and fall for XOM throughout, so on
    every rebalance momentum is long AAPL and short XOM."""
    result = run_backtest(spec_for(), seeded)

    held = result.positions.filter(pl.col("weight") != 0)
    assert set(held.filter(pl.col("weight") > 0)["ticker"].unique()) == {"AAPL"}
    assert set(held.filter(pl.col("weight") < 0)["ticker"].unique()) == {"XOM"}


def test_weights_are_neutral_and_unlevered(seeded: DatasetRef) -> None:
    """One name each side, so +0.5 and -0.5."""
    result = run_backtest(spec_for(), seeded)

    by_rebalance = result.positions.group_by("rebalance_ts").agg(
        pl.col("weight").sum().alias("net"),
        pl.col("weight").abs().sum().alias("gross"),
    )
    assert by_rebalance["net"].abs().max() == pytest.approx(0.0, abs=1e-12)
    assert by_rebalance["gross"].to_list() == pytest.approx([1.0] * by_rebalance.height)


def test_reversal_is_momentum_with_the_book_flipped(seeded: DatasetRef) -> None:
    """Same data, direction=-1. The scores negate, so the buckets swap."""
    momentum = run_backtest(spec_for(), seeded)
    reversal = run_backtest(spec_for(strategy=TrailingReturn(20, -1)), seeded)

    long_leg = reversal.positions.filter(pl.col("weight") > 0)["ticker"].unique()
    assert set(long_leg) == {"XOM"}

    joined = momentum.scores.join(reversal.scores, on=["rebalance_ts", "ticker"])
    assert joined["score"].to_list() == pytest.approx([-s for s in joined["score_right"]])


def test_pnl_matches_the_hand_computed_return(seeded: DatasetRef) -> None:
    """Straight-line prices, so a holding period return is arithmetic.

    Long AAPL at +0.5 and short XOM at -0.5. Both legs move in our favour every
    period — AAPL up, XOM down — so gross return is positive throughout.
    """
    result = run_backtest(spec_for(), seeded)
    first = result.returns.row(0, named=True)

    prices = pl.scan_parquet(seeded.scan(PRICES), **seeded.as_polars()).collect()

    def close(ticker: str, when: datetime) -> float:
        row = prices.filter((pl.col("ticker") == ticker) & (pl.col("event_ts") == when))
        return float(row["close"][0])

    start, end = first["held_from"], first["held_to"]
    expected = 0.5 * (close("AAPL", end) / close("AAPL", start) - 1) - 0.5 * (
        close("XOM", end) / close("XOM", start) - 1
    )
    assert first["gross_return"] == pytest.approx(expected, abs=1e-12)


def test_equity_compounds_the_net_returns(seeded: DatasetRef) -> None:
    result = run_backtest(spec_for(cost_bps=25.0), seeded)

    compounded = 1.0
    for row in result.returns.iter_rows(named=True):
        compounded *= 1.0 + row["net_return"]
        assert row["equity"] == pytest.approx(compounded, abs=1e-12)


def test_costs_are_charged_and_reduce_the_return(seeded: DatasetRef) -> None:
    """The first rebalance turns over the whole book, so at 100bps it costs
    1% — you have to buy the book before you can hold it."""
    free = run_backtest(spec_for(cost_bps=0.0), seeded)
    charged = run_backtest(spec_for(cost_bps=100.0), seeded)

    assert free.returns["cost"].sum() == 0.0
    assert charged.returns.row(0, named=True)["turnover"] == pytest.approx(1.0)
    assert charged.returns.row(0, named=True)["cost"] == pytest.approx(0.01)
    assert charged.returns["equity"][-1] < free.returns["equity"][-1]


def test_holding_starts_the_session_after_the_signal(seeded: DatasetRef) -> None:
    """Decide on the close of t, hold from t+1. Executing at t would be reading
    the close that generated the signal."""
    result = run_backtest(spec_for(), seeded)

    for row in result.returns.iter_rows(named=True):
        assert row["held_from"] > row["rebalance_ts"]


def test_no_lag_executes_at_the_signal_close(seeded: DatasetRef) -> None:
    result = run_backtest(spec_for(execution_lag_sessions=0), seeded)

    for row in result.returns.iter_rows(named=True):
        assert row["held_from"] == row["rebalance_ts"]


def test_rebalances_without_enough_history_are_skipped(seeded: DatasetRef) -> None:
    """The store holds 124 sessions from 2 January. The April rebalance is
    session 83, so a strategy wanting 100 sessions of history cannot be scored
    there — and must not be scored on a short window as though it had been.
    """
    result = run_backtest(spec_for(strategy=TrailingReturn(100, 1)), seeded)

    assert result.scores["rebalance_ts"].min() > ts(2024, 4, 30)


def test_a_backtest_that_ends_before_it_can_be_marked_says_so(seeded: DatasetRef) -> None:
    """Only the final rebalance has enough history, and its position opens the
    session after the data ends. Nothing can be measured, and reporting an
    empty result would look like a strategy that simply did nothing.
    """
    with pytest.raises(ValueError, match="no holding period can be measured"):
        run_backtest(spec_for(strategy=TrailingReturn(120, 1)), seeded)


def test_a_universe_too_small_to_split_is_rejected(seeded: DatasetRef) -> None:
    """Three names at 90% each wants two long and two short, so a ticker would
    land on both sides. Better to refuse than to net a name against itself and
    report the result as market neutral."""
    with pytest.raises(ValueError, match="without overlapping"):
        run_backtest(
            spec_for(
                universe=("AAPL", "MSFT", "NVDA"),
                top_fraction=0.9,
                bottom_fraction=0.9,
            ),
            seeded,
        )
