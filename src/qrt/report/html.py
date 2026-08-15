"""One self-contained HTML file. No external assets, opens anywhere."""

from __future__ import annotations

from collections.abc import Sequence

from qrt.backtest.spec import BacktestResult


def render(
    results: Sequence[BacktestResult],
    output_path: str,
    display_notional: float = 1_000_000.0,
) -> str:
    """Write the report, return its path.

    Takes a sequence so a parameter sweep renders as one document.
    `display_notional` scales P&L into dollars for presentation only — it
    changes no metric, because a weight-based dollar-neutral backtest gives the
    same numbers at any size.
    """
    raise NotImplementedError
