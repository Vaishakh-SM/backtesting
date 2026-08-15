"""Retrying the vendor call.

A public API we do not control is the one place in this system that fails for
reasons unrelated to our inputs. The distinction that matters is transient
versus permanent: retrying a symbol that does not exist just spends time and
rate limit three times over.
"""

from __future__ import annotations

import pytest
from yfinance import exceptions as yfe

from backtester.data import yahoo


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record the backoff instead of serving it."""
    waited: list[float] = []
    monkeypatch.setattr(yahoo, "_sleep", waited.append)
    return waited


def flaky(failures: int, error: Exception) -> object:
    """Fails `failures` times, then succeeds. Counts its own calls."""

    calls = {"n": 0}

    @yahoo.retry
    def call() -> str:
        calls["n"] += 1
        if calls["n"] <= failures:
            raise error
        return "ok"

    call.calls = calls  # type: ignore[attr-defined]
    return call


def test_a_transient_failure_is_retried() -> None:
    call = flaky(1, yfe.YFRateLimitError())
    assert call() == "ok"  # type: ignore[operator]
    assert call.calls["n"] == 2  # type: ignore[attr-defined]


def test_it_gives_up_after_the_attempt_limit() -> None:
    call = flaky(99, ConnectionError("network down"))
    with pytest.raises(ConnectionError):
        call()  # type: ignore[operator]
    assert call.calls["n"] == yahoo.ATTEMPTS  # type: ignore[attr-defined]


def test_backoff_grows(no_waiting: list[float]) -> None:
    """Doubling rather than a fixed pause, so a rate limit gets time to clear
    instead of being hammered on a fixed cadence."""
    call = flaky(99, yfe.YFRateLimitError())
    with pytest.raises(yfe.YFRateLimitError):
        call()  # type: ignore[operator]
    assert no_waiting == [yahoo.BACKOFF_SECONDS, yahoo.BACKOFF_SECONDS * 2]


@pytest.mark.parametrize(
    "error",
    [
        yfe.YFTickerMissingError("BAD", ""),
        yfe.YFTzMissingError("BAD"),
        yfe.YFPricesMissingError("BAD", ""),
    ],
    ids=["ticker-missing", "tz-missing", "prices-missing"],
)
def test_a_bad_symbol_is_not_retried(error: Exception, no_waiting: list[float]) -> None:
    """Nothing about the request will change on a second try. With thirty
    tickers, retrying each bad one three times with backoff is pure delay."""
    call = flaky(99, error)
    with pytest.raises(type(error)):
        call()  # type: ignore[operator]
    assert call.calls["n"] == 1  # type: ignore[attr-defined]
    assert no_waiting == []


def test_success_first_time_does_not_wait(no_waiting: list[float]) -> None:
    call = flaky(0, ConnectionError())
    assert call() == "ok"  # type: ignore[operator]
    assert no_waiting == []
