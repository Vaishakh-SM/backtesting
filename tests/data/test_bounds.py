"""Causality. The test that matters most in a backtester.

A lookahead bug does not crash — it returns a beautiful equity curve. The only
way to catch it is to change data the strategy must not have seen and assert
nothing moves.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="reader not implemented yet")
def test_future_events_do_not_change_scores() -> None:
    """Mutate rows with event_ts after the rebalance; scores stay identical."""


@pytest.mark.skip(reason="reader not implemented yet")
def test_later_restatements_do_not_change_scores() -> None:
    """Append a restatement with a later knowledge_ts; a point-in-time run is
    unaffected, because that correction did not exist when the decision was
    made."""


@pytest.mark.skip(reason="reader not implemented yet")
def test_window_excludes_rows_older_than_lookback() -> None: ...
