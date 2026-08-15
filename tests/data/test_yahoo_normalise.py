"""Vendor normalisation, tested without the vendor.

yfinance's frame goes in, our schema comes out. These run offline because the
network call and the reshaping are separate functions.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qrt.conventions import TZ
from qrt.data.yahoo import _actions, _event_ts, _prices


def yahoo_frame() -> pd.DataFrame:
    """Shaped like what yfinance returns: midnight-stamped index, actions as
    columns that are zero on ordinary days."""
    index = pd.DatetimeIndex(
        pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
    ).tz_localize(TZ)
    return pd.DataFrame(
        {
            "Open": [10.0, 11.0, 12.0],
            "High": [10.5, 11.5, 12.5],
            "Low": [9.5, 10.5, 11.5],
            "Close": [10.2, 11.2, 12.2],
            "Adj Close": [9.9, 10.9, 11.9],
            "Volume": [1000.0, 2000.0, 3000.0],
            "Dividends": [0.0, 0.25, 0.0],
            "Stock Splits": [0.0, 0.0, 4.0],
        },
        index=index,
    )


def test_bars_are_stamped_at_the_close_not_midnight() -> None:
    """Yahoo dates a bar at 00:00. A bar is not knowable until the session
    ends, and rebalances happen at the close, so it moves to 16:00."""
    stamped = _event_ts(pd.DatetimeIndex(yahoo_frame().index))
    assert all(t.hour == 16 for t in stamped)
    assert str(stamped.iloc[0].tzinfo) == TZ


def test_a_first_observation_is_stamped_at_its_own_close() -> None:
    """Vendor rows arrive as first observations, published when the session
    ended. Ingestion re-stamps only what turns out to be a correction."""
    raw = yahoo_frame()
    out = _prices(raw, _event_ts(pd.DatetimeIndex(raw.index)), "AAPL")
    assert out["knowledge_ts"].tolist() == out["event_ts"].tolist()


def test_adjusted_close_is_not_stored() -> None:
    """Keeping it would invite using a number that Yahoo restates on every
    distribution, which is the reproducibility hole we are avoiding."""
    raw = yahoo_frame()
    out = _prices(raw, _event_ts(pd.DatetimeIndex(raw.index)), "AAPL")
    assert "adj_close" not in out.columns
    assert out["close"].tolist() == [10.2, 11.2, 12.2]


def test_volume_becomes_an_integer() -> None:
    raw = yahoo_frame()
    out = _prices(raw, _event_ts(pd.DatetimeIndex(raw.index)), "AAPL")
    assert out["volume"].dtype == "int64"


def test_actions_split_into_kinds_and_skip_ordinary_days() -> None:
    raw = yahoo_frame()
    out = _actions(raw, _event_ts(pd.DatetimeIndex(raw.index)), "AAPL")

    assert len(out) == 2
    by_kind = dict(zip(out["kind"], out["value"], strict=True))
    assert by_kind == {"dividend": 0.25, "split": 4.0}


def test_a_quiet_ticker_produces_no_action_rows() -> None:
    raw = yahoo_frame()
    raw[["Dividends", "Stock Splits"]] = 0.0
    out = _actions(raw, _event_ts(pd.DatetimeIndex(raw.index)), "AAPL")
    assert out.empty


@pytest.mark.parametrize("column", ["Dividends", "Stock Splits"])
def test_missing_action_columns_are_tolerated(column: str) -> None:
    """Not every yfinance response carries both."""
    raw = yahoo_frame().drop(columns=[column])
    out = _actions(raw, _event_ts(pd.DatetimeIndex(raw.index)), "AAPL")
    assert len(out) == 1
