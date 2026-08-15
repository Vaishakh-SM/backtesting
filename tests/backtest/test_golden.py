"""A full run over four tickers with returns worked out on paper.

Tedious to write, disproportionately convincing: it is the only test that says
the whole chain produces the number a person computed independently.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="engine not implemented yet")
def test_scores_match_hand_computed_values() -> None: ...


@pytest.mark.skip(reason="engine not implemented yet")
def test_reversal_is_momentum_negated() -> None:
    """Same data, direction=-1, scores are the exact negation."""


@pytest.mark.skip(reason="engine not implemented yet")
def test_rebalances_without_enough_history_are_skipped() -> None: ...
