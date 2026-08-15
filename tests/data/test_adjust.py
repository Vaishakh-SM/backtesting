"""Dividend adjustment, against numbers worked out by hand.

Getting this wrong is silent: prices still look like prices, returns still look
like returns, and the strategy just quietly dislikes anything that pays a
dividend.
"""

from __future__ import annotations

import polars as pl
import pytest

from qrt.data.adjust import adjust
from qrt.data.schema import TZ
from tests.conftest import ts


def prices(*rows: tuple[str, int, float]) -> pl.DataFrame:
    """(ticker, day-of-January, close)."""
    return pl.DataFrame(
        {
            "ticker": [r[0] for r in rows],
            "event_ts": [ts(2026, 1, r[1]) for r in rows],
            "close": [r[2] for r in rows],
        }
    )


def actions(*rows: tuple[str, int, str, float]) -> pl.DataFrame:
    """(ticker, day-of-January, kind, value)."""
    return pl.DataFrame(
        {
            "ticker": [r[0] for r in rows],
            "event_ts": [ts(2026, 1, r[1]) for r in rows],
            "kind": [r[2] for r in rows],
            "value": [r[3] for r in rows],
        },
        # Spelled out so the empty case still carries the right dtypes; a naive
        # timestamp here would fail to join against tz-aware prices.
        schema={
            "ticker": pl.String,
            "event_ts": pl.Datetime("us", TZ),
            "kind": pl.String,
            "value": pl.Float64,
        },
    )


def test_no_actions_leaves_prices_untouched() -> None:
    out = adjust(prices(("AAPL", 5, 100.0), ("AAPL", 6, 101.0)), actions())
    assert out["adj_close"].to_list() == [100.0, 101.0]


def test_a_dividend_scales_earlier_bars_only() -> None:
    """Hand-computed. $1 on a $100 stock gives a factor of 0.99, applied to
    every bar before the ex-date. The ex-date bar itself keeps its close.
    """
    out = adjust(
        prices(("AAPL", 5, 100.0), ("AAPL", 6, 100.0), ("AAPL", 7, 100.0)),
        actions(("AAPL", 7, "dividend", 1.0)),
    )
    assert out["adj_close"].to_list() == [99.0, 99.0, 100.0]


def test_the_return_across_an_ex_date_is_what_a_holder_earned() -> None:
    """The whole point. Raw closes say the stock went nowhere; the holder is up
    by the dividend."""
    raw = prices(("AAPL", 5, 100.0), ("AAPL", 6, 100.0))
    out = adjust(raw, actions(("AAPL", 6, "dividend", 1.0)))

    a, b = out["adj_close"].to_list()
    assert b / a - 1 == pytest.approx(0.010101, abs=1e-6)
    assert raw["close"][1] / raw["close"][0] - 1 == 0.0  # what it looks like unadjusted


def test_several_dividends_compound() -> None:
    """0.99 * 0.98 on the earliest bar, 0.98 on the middle one."""
    out = adjust(
        prices(("AAPL", 5, 100.0), ("AAPL", 6, 100.0), ("AAPL", 7, 100.0)),
        actions(("AAPL", 6, "dividend", 1.0), ("AAPL", 7, "dividend", 2.0)),
    )
    assert out["adj_close"].to_list() == pytest.approx([97.02, 98.0, 100.0])


def test_splits_are_ignored() -> None:
    """Yahoo has already back-adjusted for them. Applying the ratio here would
    divide the history a second time."""
    out = adjust(
        prices(("AAPL", 5, 100.0), ("AAPL", 6, 25.0)),
        actions(("AAPL", 6, "split", 4.0)),
    )
    assert out["adj_close"].to_list() == [100.0, 25.0]


def test_a_dividend_on_the_first_bar_has_nothing_to_adjust() -> None:
    """No earlier bar in the window to scale, and no prior close to reference.
    Must not produce nulls."""
    out = adjust(
        prices(("AAPL", 5, 100.0), ("AAPL", 6, 101.0)),
        actions(("AAPL", 5, "dividend", 1.0)),
    )
    assert out["adj_close"].to_list() == [100.0, 101.0]


def test_tickers_are_adjusted_independently() -> None:
    """A dividend from one name must not touch another's history."""
    out = adjust(
        prices(("AAPL", 5, 100.0), ("AAPL", 6, 100.0), ("MSFT", 5, 50.0), ("MSFT", 6, 50.0)),
        actions(("AAPL", 6, "dividend", 1.0)),
    )
    by_ticker = {t: g["adj_close"].to_list() for t, g in out.group_by("ticker")}
    assert by_ticker[("AAPL",)] == [99.0, 100.0]
    assert by_ticker[("MSFT",)] == [50.0, 50.0]


def test_other_columns_survive() -> None:
    frame = prices(("AAPL", 5, 100.0)).with_columns(volume=pl.lit(1000))
    out = adjust(frame, actions())
    assert set(out.columns) == {"ticker", "event_ts", "close", "volume", "adj_close"}
