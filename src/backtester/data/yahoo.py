"""The vendor bit, isolated.

Everything yfinance-specific lives here: its column names, its timestamps, its
quirks. Swapping vendors means writing another module like this one and
changing nothing else.

Two things about Yahoo that shape the rest of the design:

1. Its unadjusted "Close" is already split-adjusted. AAPL's close on
   2020-08-28 comes back as 124.81, not the ~499 that actually traded, with
   the 4.0 split flagged on the 2020-08-31 ex-date. So a new split silently
   restates that ticker's entire history.

   That is why ingestion re-fetches full history per ticker rather than only
   the new tail: a window straddling a split would otherwise mix pre-split and
   post-split rows from different batches. Each batch is internally
   consistent, and the append-only log keeps the older version intact.

2. Dividends are *not* folded into Close (124.81 raw against 120.97 adjusted),
   so dividend adjustment is still ours to derive. We deliberately do not store
   Yahoo's "Adj Close" — keeping it would invite using a number that is
   restated on every distribution.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

import pandas as pd
import pyarrow as pa
import yfinance as yf
from yfinance import exceptions as yfe

from backtester.conventions import CLOSE_HOUR, TZ
from backtester.data.schema import ACTIONS_SCHEMA, PRICES_SCHEMA

SOURCE = "yfinance"

ATTEMPTS = 3
BACKOFF_SECONDS = 1.0

# Nothing about the request will change on a second try, so retrying only
# spends time and rate limit. Anything else — a rate limit, a dropped
# connection, a 5xx — is worth another go.
PERMANENT = (
    yfe.YFTickerMissingError,
    yfe.YFTzMissingError,
    yfe.YFPricesMissingError,
    yfe.YFInvalidPeriodError,
)

# Indirection so tests do not actually wait.
_sleep = time.sleep

F = TypeVar("F", bound=Callable[..., Any])


def retry(fn: F) -> F:
    """Retry transient vendor failures with exponential backoff.

    A public API we do not control is the one place in this system that fails
    for reasons unrelated to our inputs, so it is the one place a retry earns
    its keep.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                return fn(*args, **kwargs)
            except PERMANENT:
                raise
            except Exception:
                if attempt == ATTEMPTS:
                    raise
                _sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    return wrapper  # type: ignore[return-value]


@retry
def _history(ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
    return yf.Ticker(ticker).history(
        start=start.date(),
        end=end.date(),
        auto_adjust=False,
        actions=True,
        raise_errors=True,
    )


@dataclass(frozen=True)
class Fetched:
    prices: pa.Table
    actions: pa.Table
    failed: dict[str, str]


def fetch(tickers: Sequence[str], start: datetime, end: datetime) -> Fetched:
    """Fetch raw OHLCV and corporate actions, normalised to our schemas.

    Rows come back stamped with `knowledge_ts = event_ts`, i.e. as first
    observations published at the close. Ingestion re-stamps anything that
    turns out to contradict what the store already holds — see "Time, and what
    we knew when" in docs/DESIGN_DECISIONS.md.

    One request per ticker rather than a batched download, so a single bad
    symbol degrades to a recorded failure instead of taking the batch with it.
    """
    price_frames: list[pd.DataFrame] = []
    action_frames: list[pd.DataFrame] = []
    failed: dict[str, str] = {}

    for ticker in tickers:
        try:
            raw = _history(ticker, start, end)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the batch
            failed[ticker] = f"{type(exc).__name__}: {exc}"
            continue

        if raw.empty:
            failed[ticker] = "no rows returned"
            continue

        event_ts = _event_ts(pd.DatetimeIndex(raw.index))
        price_frames.append(_prices(raw, event_ts, ticker))
        action_frames.append(_actions(raw, event_ts, ticker))

    return Fetched(
        prices=_to_arrow(price_frames, PRICES_SCHEMA),
        actions=_to_arrow(action_frames, ACTIONS_SCHEMA),
        failed=failed,
    )


def _event_ts(index: pd.DatetimeIndex) -> pd.Series:
    """Bar date at the exchange close, timezone-aware.

    Yahoo dates a bar at local midnight, but a bar is not knowable until the
    session ends. Every session is treated as full-length, early closes
    included — the calendar makes the same assumption, so the two agree.
    """
    local = index.tz_convert(TZ) if index.tz is not None else index.tz_localize(TZ)
    return pd.Series(local.normalize() + pd.Timedelta(hours=CLOSE_HOUR), index=index)


def _prices(raw: pd.DataFrame, event_ts: pd.Series, ticker: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ticker,
            "event_ts": event_ts.to_numpy(),
            "open": raw["Open"].astype("float64").to_numpy(),
            "high": raw["High"].astype("float64").to_numpy(),
            "low": raw["Low"].astype("float64").to_numpy(),
            "close": raw["Close"].astype("float64").to_numpy(),
            # Yahoo occasionally reports volume as float; int64 is the contract.
            "volume": raw["Volume"].fillna(0).astype("int64").to_numpy(),
            "knowledge_ts": event_ts.to_numpy(),
            "source": SOURCE,
            "event_year": event_ts.dt.year.astype("int32").to_numpy(),
        }
    )


def _actions(raw: pd.DataFrame, event_ts: pd.Series, ticker: str) -> pd.DataFrame:
    parts = []

    for column, kind in (("Dividends", "dividend"), ("Stock Splits", "split")):
        if column not in raw.columns:
            continue
        mask = raw[column].fillna(0) != 0
        if not mask.any():
            continue
        parts.append(
            pd.DataFrame(
                {
                    "ticker": ticker,
                    "event_ts": event_ts[mask].to_numpy(),
                    "kind": kind,
                    "value": raw.loc[mask, column].astype("float64").to_numpy(),
                    "knowledge_ts": event_ts[mask].to_numpy(),
                    "source": SOURCE,
                    "event_year": event_ts[mask].dt.year.astype("int32").to_numpy(),
                }
            )
        )

    if not parts:
        return pd.DataFrame(columns=ACTIONS_SCHEMA.names)
    return pd.concat(parts, ignore_index=True)


def _to_arrow(frames: list[pd.DataFrame], schema: pa.Schema) -> pa.Table:
    frames = [f for f in frames if not f.empty]
    if not frames:
        return schema.empty_table()
    combined = pd.concat(frames, ignore_index=True)
    return pa.Table.from_pandas(combined, schema=schema, preserve_index=False)
