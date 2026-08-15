"""The snapshot handed to a strategy.

Its job is small: hold already-filtered frames and hand them over in whichever
dataframe library the researcher works in.
"""

from __future__ import annotations

import pandas as pd
import polars as pl
import pyarrow as pa
import pytest

from backtester.data.schema import ACTIONS, PRICES
from backtester.data.view import MarketView, Snapshot
from tests.conftest import ts

AS_OF = ts(2026, 1, 8)


@pytest.fixture
def snapshot() -> Snapshot:
    return Snapshot(
        frames={PRICES: pl.DataFrame({"ticker": ["AAPL"], "close": [100.0]})},
        as_of_event=AS_OF,
        as_of_knowledge=AS_OF,
    )


def test_it_satisfies_the_protocol(snapshot: Snapshot) -> None:
    assert isinstance(snapshot, MarketView)


def test_polars_is_the_default(snapshot: Snapshot) -> None:
    assert isinstance(snapshot.read(PRICES), pl.DataFrame)


def test_pandas_and_arrow_are_one_call_away(snapshot: Snapshot) -> None:
    """Arrow is the common currency, so the researcher's choice of frame is
    independent of which engine fetched the window."""
    assert isinstance(snapshot.read(PRICES, "pandas"), pd.DataFrame)
    assert isinstance(snapshot.read(PRICES, "arrow"), pa.Table)


def test_values_survive_conversion(snapshot: Snapshot) -> None:
    assert snapshot.read(PRICES, "pandas")["close"].tolist() == [100.0]
    assert snapshot.read(PRICES, "arrow").column("close").to_pylist() == [100.0]


def test_bounds_are_readable_but_not_settable(snapshot: Snapshot) -> None:
    """A strategy can ask what instant it is deciding at. It cannot move it."""
    assert snapshot.as_of_event == AS_OF
    assert snapshot.as_of_knowledge == AS_OF
    with pytest.raises(AttributeError):
        snapshot.as_of_event = ts(2027, 1, 1)  # type: ignore[misc]


def test_asking_for_a_table_that_was_not_fetched_says_which_were(
    snapshot: Snapshot,
) -> None:
    """Better than a KeyError on a bare dict: a strategy reading `actions` when
    the engine only fetched `prices` should be told so."""
    with pytest.raises(KeyError, match=PRICES):
        snapshot.read(ACTIONS)


def test_unknown_format_is_rejected(snapshot: Snapshot) -> None:
    with pytest.raises(ValueError, match="polars, pandas or arrow"):
        snapshot.read(PRICES, "numpy")  # type: ignore[arg-type]
