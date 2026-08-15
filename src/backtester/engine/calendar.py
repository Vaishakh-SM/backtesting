"""When decisions get made.

Month-end means the last day the exchange was open, not the 31st. December 2022
ended on a Saturday; the December rebalance is the 30th. Getting this from a
maintained calendar rather than from the data means a ticker with a gap cannot
quietly move a rebalance.

Every session is treated as a full day ending at 16:00, early closes included.
NYSE shuts at 13:00 on about four days a year, but ingestion stamps every bar
at 16:00, so a rebalance stamped at the true 13:00 close would exclude that
day's own bar from its window. Same convention on both sides, no gap.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from backtester.conventions import CLOSE_HOUR, TZ

EXCHANGE = "XNYS"

_FREQUENCIES = {
    "D": lambda d: (d.year, d.month, d.day),
    "W": lambda d: d.isocalendar()[:2],
    "M": lambda d: (d.year, d.month),
}


@lru_cache(maxsize=1)
def _calendar() -> xcals.ExchangeCalendar:
    """Cached: building one takes long enough to notice in a sweep."""
    return xcals.get_calendar(EXCHANGE)


def _close(session: pd.Timestamp) -> datetime:
    return datetime(session.year, session.month, session.day, CLOSE_HOUR, tzinfo=ZoneInfo(TZ))


def trading_days(start: datetime, end: datetime) -> list[datetime]:
    """Sessions in [start, end], as closes."""
    if start > end:
        return []
    return [_close(s) for s in _calendar().sessions_in_range(start.date(), end.date())]


def rebalance_timestamps(start: datetime, end: datetime, frequency: str) -> list[datetime]:
    """Instants at which a signal is computed: "M", "W" or "D".

    The last session of each period. A trailing partial period still yields a
    rebalance — the engine decides whether a position with no subsequent data
    is worth keeping.
    """
    if frequency not in _FREQUENCIES:
        raise ValueError(f"unknown rebalance frequency {frequency!r}: expected M, W or D")

    period = _FREQUENCIES[frequency]
    days = trading_days(start, end)
    return [d for i, d in enumerate(days) if i + 1 == len(days) or period(days[i + 1]) != period(d)]


def next_session(after: datetime, count: int = 1) -> datetime:
    """The close `count` sessions after `after`, which must itself be a session.

    This is the execution lag: decide on the close of t, hold from t+1. `count`
    of 0 means executing at the same close the signal was computed on, which
    is the most common way a backtest reports impossible performance.
    """
    return _shift(after, count)


def sessions_before(before: datetime, count: int) -> datetime:
    """The close `count` sessions before `before`, which must itself be a session.

    The guarantee, which is what a window bound needs: exactly `count` sessions
    fall strictly after the returned instant, up to and including `before`.
    Readers bound windows as (since, as_of], so this drops straight in.

    Counting sessions rather than calendar time is the point. Sixty calendar
    days is about forty-one sessions, so a strategy asking in calendar time
    would quietly receive two thirds of the history it meant.
    """
    return _shift(before, -count)


def _shift(from_: datetime, sessions: int) -> datetime:
    calendar = _calendar()
    step = calendar.next_session if sessions > 0 else calendar.previous_session

    day = pd.Timestamp(from_.date())
    for _ in range(abs(sessions)):
        day = step(day)
    return _close(day)
