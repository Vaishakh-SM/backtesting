"""What a strategy hands back.

The invariants live on the type because they break silently: a book that has
stopped being neutral, or has quietly levered itself, still produces a
plausible equity curve.
"""

from __future__ import annotations

import pytest

from backtester.strategy.portfolio import Allocation, linear_cost, rank_weights, turnover


def test_a_neutral_unlevered_book_is_accepted() -> None:
    Allocation({"AAPL": 0.5, "XOM": -0.5})


def test_a_book_that_is_not_neutral_is_rejected() -> None:
    with pytest.raises(ValueError, match="not dollar neutral"):
        Allocation({"AAPL": 0.6, "XOM": -0.4})


def test_a_levered_book_is_rejected() -> None:
    with pytest.raises(ValueError, match="gross exposure"):
        Allocation({"AAPL": 1.0, "XOM": -1.0})


def test_an_empty_book_is_allowed() -> None:
    """A rebalance with nothing to hold is a legitimate answer."""
    assert Allocation({}).weights == {}


def test_scores_are_optional() -> None:
    """Not every strategy has a meaningful intermediate to expose."""
    assert Allocation({"AAPL": 0.5, "XOM": -0.5}).scores == {}


# --- rank_weights, a helper strategies may use -----------------------------


SCORES = {"A": 0.9, "B": 0.5, "C": 0.1, "D": -0.2, "E": -0.6, "F": -0.9}


def test_it_holds_the_ends_and_nothing_else() -> None:
    book = rank_weights(SCORES, 1 / 3, 1 / 3).weights
    assert set(book) == {"A", "B", "E", "F"}


def test_each_leg_carries_half_the_gross() -> None:
    book = rank_weights(SCORES, 1 / 3, 1 / 3).weights
    assert book["A"] == pytest.approx(0.25)
    assert book["F"] == pytest.approx(-0.25)


def test_only_the_ordering_matters() -> None:
    """A name up 90% and one up 50% are held identically. That is what
    equal-weighted means, and it is the information a conviction-weighted
    strategy would size on instead."""
    book = rank_weights(SCORES, 1 / 3, 1 / 3).weights
    assert book["A"] == book["B"]


def test_ties_break_by_ticker() -> None:
    """Otherwise the same data gives a different book on a rerun, for no reason
    a reader can see."""
    tied = {"ZZ": 1.0, "AA": 1.0, "MM": 1.0, "BB": -1.0}
    first = rank_weights(tied, 0.25, 0.25).weights
    for _ in range(5):
        assert rank_weights(tied, 0.25, 0.25).weights == first
    assert first["AA"] > 0  # alphabetically first among the tied winners


def test_the_scores_travel_with_the_book() -> None:
    assert rank_weights(SCORES, 1 / 3, 1 / 3).scores == SCORES


def test_overlapping_buckets_are_refused() -> None:
    with pytest.raises(ValueError, match="without overlapping"):
        rank_weights(SCORES, 0.9, 0.9)


def test_no_scores_gives_no_book() -> None:
    assert rank_weights({}).weights == {}


# --- turnover and costs ----------------------------------------------------


def test_the_first_rebalance_turns_over_the_whole_book() -> None:
    """You have to buy the book before you can hold it."""
    assert turnover(None, Allocation({"A": 0.5, "B": -0.5})) == pytest.approx(1.0)


def test_holding_the_same_book_costs_nothing() -> None:
    book = Allocation({"A": 0.5, "B": -0.5})
    assert turnover(book, book) == pytest.approx(0.0)
    assert linear_cost(book, book, bps=100) == pytest.approx(0.0)


def test_a_name_leaving_the_book_is_traded_out() -> None:
    before = Allocation({"A": 0.5, "B": -0.5})
    after = Allocation({"C": 0.5, "B": -0.5})
    assert turnover(before, after) == pytest.approx(1.0)  # sell A, buy C


def test_cost_is_turnover_times_the_rate() -> None:
    assert linear_cost(None, Allocation({"A": 0.5, "B": -0.5}), bps=25) == pytest.approx(0.0025)


# --- the point of the change: sizing is the strategy's choice ---------------


def test_a_strategy_can_size_however_it_likes() -> None:
    """Conviction weighting, which rank_weights cannot express. Nothing in the
    engine needs to know this exists."""
    scores = {"A": 3.0, "B": 1.0, "C": -1.0, "D": -3.0}

    longs = {t: s for t, s in scores.items() if s > 0}
    shorts = {t: s for t, s in scores.items() if s < 0}
    book = {t: 0.5 * s / sum(longs.values()) for t, s in longs.items()} | {
        t: -0.5 * s / sum(shorts.values()) for t, s in shorts.items()
    }

    allocation = Allocation(book, scores)
    assert allocation.weights["A"] == pytest.approx(0.375)  # 3x the conviction of B
    assert allocation.weights["B"] == pytest.approx(0.125)
