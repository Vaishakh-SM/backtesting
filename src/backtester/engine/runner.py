"""Walking a strategy over history."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime

import polars as pl

from backtester.conventions import TZ
from backtester.data.dataset import DatasetRef, MissingData
from backtester.data.polars_reader import earliest_knowledge_ts, read_window
from backtester.data.schema import (
    ACTIONS,
    ACTIONS_KEY,
    ACTIONS_SCHEMA,
    PARTITION_COL,
    PRICES,
    PRICES_KEY,
)
from backtester.data.view import Snapshot
from backtester.engine.calendar import next_session, rebalance_timestamps, sessions_before
from backtester.engine.spec import BacktestResult, BacktestSpec
from backtester.strategy import Strategy, load_strategy
from backtester.strategy.portfolio import Allocation, linear_cost, turnover

logger = logging.getLogger(__name__)


def run_backtest(spec: BacktestSpec, ref: DatasetRef) -> BacktestResult:
    """Run a spec against a store. Knows nothing about scheduling.

    One query per rebalance for the signal window, plus one for the holding
    period prices. Consecutive signal windows overlap so rows are read more
    than once; "The engine" in docs/DESIGN_DECISIONS.md has the arithmetic and
    the point at which the other approach wins.
    """
    strategy = (
        spec.strategy if isinstance(spec.strategy, Strategy) else load_strategy(spec.strategy)
    )

    rebalances = rebalance_timestamps(spec.start, spec.end, spec.rebalance_frequency)
    if not rebalances:
        raise ValueError(f"no trading sessions between {spec.start} and {spec.end}")

    _check_knowledge_covers(ref, rebalances[0], spec)

    logger.info(
        "%d rebalances, %s to %s, %d names, knowledge capped at %s",
        len(rebalances),
        spec.start.date(),
        spec.end.date(),
        len(spec.universe),
        spec.as_of_knowledge.date(),
    )

    scores: list[dict[str, object]] = []
    positions: list[dict[str, object]] = []
    book: list[tuple[datetime, Allocation]] = []

    for rebalance_ts in rebalances:
        window = _signal_window(ref, spec, strategy, rebalance_ts)
        if window is None:
            # Debug rather than info: on a long backtest the leading rebalances
            # are routinely skipped while the lookback fills, and warning about
            # each would train the reader to ignore the log.
            logger.debug(
                "%s skipped: fewer than %d sessions behind it",
                rebalance_ts.date(),
                strategy.lookback_sessions,
            )
            continue

        allocation = strategy.allocate(window)
        if not allocation.weights:
            logger.debug("%s: strategy held nothing", rebalance_ts.date())
            continue

        logger.debug("%s: %d positions", rebalance_ts.date(), len(allocation.weights))

        scores += [
            {"rebalance_ts": rebalance_ts, "ticker": t, "score": s}
            for t, s in allocation.scores.items()
        ]
        positions += [
            {"rebalance_ts": rebalance_ts, "ticker": t, "weight": w}
            for t, w in allocation.weights.items()
        ]
        book.append((rebalance_ts, allocation))

    if not book:
        raise ValueError(
            "every rebalance was skipped for want of history — check the store covers "
            f"{strategy.lookback_sessions} sessions before {spec.start.date()}"
        )

    returns = _holding_returns(ref, spec, strategy, book)

    return BacktestResult(
        spec=spec,
        knowledge_ts=spec.as_of_knowledge,
        reproducible=spec.is_reproducible(),
        scores=pl.DataFrame(scores, schema=_SCORE_SCHEMA),
        positions=pl.DataFrame(positions),
        returns=returns,
    )


# Spelled out so a strategy that exposes no scores still yields a typed frame
# rather than an untyped empty one the report has to special-case.
_SCORE_SCHEMA: Mapping[str, pl.DataType] = {
    "rebalance_ts": pl.Datetime("us", TZ),
    "ticker": pl.String(),
    "score": pl.Float64(),
}


def _knowledge_cutoff(spec: BacktestSpec, rebalance_ts: datetime) -> datetime:
    """What the strategy is allowed to have known.

    Point-in-time caps knowledge at the decision itself, so a correction made
    later cannot leak backwards. Otherwise every read pins to one cutoff, which
    is how an old run is reproduced exactly.
    """
    if not spec.point_in_time:
        return spec.as_of_knowledge
    return min(rebalance_ts, spec.as_of_knowledge)


def _signal_window(
    ref: DatasetRef, spec: BacktestSpec, strategy: Strategy, rebalance_ts: datetime
) -> Snapshot | None:
    """The bounded view for one decision, or None if history is too short.

    `lookback_sessions` sessions of history plus the current one, so a
    sixty-session strategy sees sixty-one bars and computes a sixty-session
    return.
    """
    since = sessions_before(rebalance_ts, strategy.lookback_sessions + 1)
    cutoff = _knowledge_cutoff(spec, rebalance_ts)

    prices = read_window(ref, PRICES, PRICES_KEY, spec.universe, since, rebalance_ts, cutoff)
    sessions = prices["event_ts"].n_unique() if prices.height else 0
    if sessions <= strategy.lookback_sessions:
        return None

    return Snapshot(
        {PRICES: prices, ACTIONS: _actions(ref, spec, since, rebalance_ts, cutoff)},
        rebalance_ts,
        cutoff,
    )


def _actions(
    ref: DatasetRef, spec: BacktestSpec, since: datetime, until: datetime, cutoff: datetime
) -> pl.DataFrame:
    """Corporate actions for the window, or an empty frame if there are none.

    A universe that has never paid a dividend or split is a legitimate state,
    and ingestion writes no file when it has nothing to write. That must read
    as "no actions" rather than as a missing store.
    """
    try:
        return read_window(ref, ACTIONS, ACTIONS_KEY, spec.universe, since, until, cutoff)
    except MissingData:
        empty = pl.from_arrow(ACTIONS_SCHEMA.empty_table())
        assert isinstance(empty, pl.DataFrame)
        return empty.drop(PARTITION_COL, strict=False)


def _check_knowledge_covers(ref: DatasetRef, first: datetime, spec: BacktestSpec) -> None:
    """Refuse a point-in-time run the store cannot answer.

    A store backfilled in one go and stamped with the wall clock knows nothing
    about any date before the backfill ran, so every window would come back
    empty and the run would report no positions rather than failing. Silence is
    the worst outcome here, so this is an error.
    """
    if not spec.point_in_time:
        return

    oldest = earliest_knowledge_ts(ref)
    if oldest <= first:
        return

    raise ValueError(
        f"point-in-time run starting {first.date()}, but the store's earliest observation "
        f"is only known as of {oldest.date()} — every window would be empty. Either set "
        "point_in_time=False to pin every read to as_of_knowledge, or re-ingest so that "
        "first observations carry their publication time."
    )


def _holding_returns(
    ref: DatasetRef,
    spec: BacktestSpec,
    strategy: Strategy,
    book: list[tuple[datetime, Allocation]],
) -> pl.DataFrame:
    """P&L of each held position, from one execution to the next.

    Signals are point-in-time; P&L is not, and should not be. A decision is
    judged on what we now believe actually happened, so these read at the run's
    knowledge cutoff rather than at each rebalance's.
    """
    executions = [next_session(ts, spec.execution_lag_sessions) for ts, _ in book]

    prices = read_window(
        ref,
        PRICES,
        PRICES_KEY,
        spec.universe,
        sessions_before(executions[0], 1),
        max(executions[-1], spec.end),
        spec.as_of_knowledge,
    ).pivot(on="ticker", index="event_ts", values="close")

    if prices.is_empty():
        raise ValueError(
            f"the first position is taken on {executions[0].date()}, after the last session in "
            "the store, so no holding period can be measured. Either extend the data or start "
            "the backtest earlier."
        )

    # A position is marked at the last session we actually have. Without this
    # the final rebalance's execution can land past the end of the data and a
    # period would be scored against prices that do not exist — which showed up
    # as a return of exactly zero rather than as an error.
    last_available = prices["event_ts"].max()
    assert isinstance(last_available, datetime)

    rows = []
    equity = 1.0
    previous: Allocation | None = None

    for i, (rebalance_ts, weights) in enumerate(book):
        start = executions[i]
        end = min(executions[i + 1] if i + 1 < len(book) else last_available, last_available)
        if start >= last_available or end <= start:
            continue  # still open at the end of the data; nothing to measure

        long_pnl, short_pnl = _leg_returns(prices, weights, start, end)
        gross = long_pnl + short_pnl
        cost = linear_cost(previous, weights, spec.cost_bps)
        net = gross - cost
        equity *= 1.0 + net

        rows.append(
            {
                "rebalance_ts": rebalance_ts,
                "held_from": start,
                "held_to": end,
                "turnover": turnover(previous, weights),
                "long_pnl": long_pnl,
                "short_pnl": short_pnl,
                "gross_return": gross,
                "cost": cost,
                "net_return": net,
                "equity": equity,
            }
        )
        previous = weights

    return pl.DataFrame(rows)


def _leg_returns(
    prices: pl.DataFrame, weights: Allocation, start: datetime, end: datetime
) -> tuple[float, float]:
    """What each side of the book earned over the holding period.

    Split rather than summed, because "did both legs contribute" is a question
    a PM asks of anything calling itself market neutral, and it cannot be
    recovered from the total afterwards.

    Missing prices raise rather than contributing zero. A held name with no
    price is either a data gap or a delisting, and both would otherwise show up
    as a position that simply did not move — which reads as a real result.
    Delistings are out of scope (docs/ASSUMPTIONS.md); this is how that shows.
    """
    first = prices.filter(pl.col("event_ts") == start)
    last = prices.filter(pl.col("event_ts") == end)
    if first.is_empty() or last.is_empty():
        raise ValueError(f"no prices at {start} or {end} to mark the book against")

    long_pnl = short_pnl = 0.0
    for ticker, weight in weights.weights.items():
        if ticker not in prices.columns or first[ticker][0] is None or last[ticker][0] is None:
            raise ValueError(
                f"{ticker} is held from {start.date()} to {end.date()} but has no price at "
                "one end — a gap or a delisting, neither of which is modelled"
            )
        a, b = first[ticker][0], last[ticker][0]
        contribution = weight * (b / a - 1.0)
        if weight > 0:
            long_pnl += contribution
        else:
            short_pnl += contribution
    return long_pnl, short_pnl


__all__ = ["run_backtest"]
