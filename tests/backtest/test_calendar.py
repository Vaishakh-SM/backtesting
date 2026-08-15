"""Rebalance dates land on days the exchange was actually open.

A rebalance on a closed day produces an empty window, which a backtest reports
as "no position" rather than as an error. These use real NYSE history, since
the whole point is deferring to a maintained calendar rather than to arithmetic
on dates.
"""

from __future__ import annotations

import pytest

from qrt.backtest.calendar import (
    next_session,
    rebalance_timestamps,
    sessions_before,
    trading_days,
)
from tests.conftest import ts


def days(start: tuple[int, int, int], end: tuple[int, int, int], freq: str) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in rebalance_timestamps(ts(*start), ts(*end), freq)]


def test_month_end_falls_on_a_trading_day() -> None:
    """31 Dec 2022 was a Saturday, so December's rebalance is the 30th."""
    assert days((2022, 11, 1), (2023, 1, 10), "M") == ["2022-11-30", "2022-12-30", "2023-01-10"]


def test_holidays_are_not_sessions() -> None:
    """Thanksgiving 2024, and Good Friday 2024 — a closure with no fixed date."""
    november = [d.strftime("%Y-%m-%d") for d in trading_days(ts(2024, 11, 27), ts(2024, 11, 29))]
    assert november == ["2024-11-27", "2024-11-29"]

    march = [d.strftime("%Y-%m-%d") for d in trading_days(ts(2024, 3, 28), ts(2024, 4, 1))]
    assert march == ["2024-03-28", "2024-04-01"]


def test_an_unscheduled_closure_is_respected() -> None:
    """Hurricane Sandy shut the exchange on 29 and 30 October 2012. No rule
    derives this; it has to come from a calendar that records it."""
    sandy = [d.strftime("%Y-%m-%d") for d in trading_days(ts(2012, 10, 26), ts(2012, 10, 31))]
    assert sandy == ["2012-10-26", "2012-10-31"]


def test_early_closes_are_still_sessions_at_sixteen_hundred() -> None:
    """NYSE closed at 13:00 on 29 Nov 2024. We stamp 16:00 anyway, matching how
    ingestion stamps bars — otherwise a rebalance there would exclude its own
    day's bar from the window.
    """
    half_day = trading_days(ts(2024, 11, 29), ts(2024, 11, 29))
    assert len(half_day) == 1
    assert half_day[0].hour == 16


def test_daily_frequency_is_every_session() -> None:
    assert days((2024, 7, 1), (2024, 7, 8), "D") == [
        "2024-07-01",
        "2024-07-02",
        "2024-07-03",
        # 4 July, closed
        "2024-07-05",
        "2024-07-08",
    ]


def test_weekly_frequency_takes_the_last_session_of_each_week() -> None:
    """Independence Day fell on the Thursday, so that week ends on Friday the
    5th rather than being skipped."""
    assert days((2024, 7, 1), (2024, 7, 19), "W") == ["2024-07-05", "2024-07-12", "2024-07-19"]


def test_a_week_shortened_by_a_holiday_still_rebalances() -> None:
    """Good Friday 2024 was 29 March, so that week ends on Thursday the 28th."""
    assert "2024-03-28" in days((2024, 3, 25), (2024, 4, 5), "W")


def test_execution_lag_moves_to_the_next_session() -> None:
    """Decide on the close of t, hold from t+1. Friday's signal is held from
    Monday, not Saturday."""
    friday = ts(2024, 7, 12)
    assert next_session(friday).strftime("%Y-%m-%d") == "2024-07-15"


def test_execution_lag_skips_a_holiday() -> None:
    """3 July 2024's signal is held from the 5th; the 4th was closed."""
    assert next_session(ts(2024, 7, 3)).strftime("%Y-%m-%d") == "2024-07-05"


def test_no_lag_means_the_same_close() -> None:
    """Available, and the single most common way a backtest reports impossible
    performance."""
    assert next_session(ts(2024, 7, 3), count=0) == ts(2024, 7, 3)


def test_a_longer_lag_compounds() -> None:
    assert next_session(ts(2024, 7, 3), count=2).strftime("%Y-%m-%d") == "2024-07-08"


def test_the_window_bound_leaves_exactly_that_many_sessions() -> None:
    """The contract the engine relies on. Readers bound windows as
    (since, as_of], so `count` sessions must fall strictly after the returned
    instant — counted here rather than asserted as a date, because a
    hand-guessed date proves nothing about the invariant.
    """
    end = ts(2024, 6, 28)
    for count in (1, 5, 60, 252):
        since = sessions_before(end, count)
        in_window = [d for d in trading_days(since, end) if d > since]
        assert len(in_window) == count


def test_sessions_are_not_calendar_days() -> None:
    """Sixty sessions back from 28 June 2024 spans 86 calendar days. A strategy
    asking for a 60-day window in calendar time would have received about
    forty-one sessions, and nothing would have looked wrong."""
    end = ts(2024, 6, 28)
    assert (end - sessions_before(end, 60)).days == 86


def test_stepping_back_skips_weekends_and_holidays() -> None:
    """One session before Monday 8 July is Friday the 5th; one before the 5th
    is the 3rd, since the 4th was Independence Day."""
    assert sessions_before(ts(2024, 7, 8), 1).strftime("%Y-%m-%d") == "2024-07-05"
    assert sessions_before(ts(2024, 7, 5), 1).strftime("%Y-%m-%d") == "2024-07-03"


def test_stepping_back_and_forward_are_inverses() -> None:
    start = ts(2024, 6, 28)
    assert next_session(sessions_before(start, 10), 10) == start


def test_an_unknown_frequency_is_rejected() -> None:
    with pytest.raises(ValueError, match="expected M, W or D"):
        days((2024, 1, 1), (2024, 2, 1), "Q")


def test_an_empty_range_is_empty() -> None:
    assert trading_days(ts(2024, 7, 10), ts(2024, 7, 1)) == []
