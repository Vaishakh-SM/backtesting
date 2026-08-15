"""End to end over the committed fixture store.

Unit tests cannot see wiring bugs. This runs the real CLI against a tiny
dataset and checks a report lands on disk. No network.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="pipeline not implemented yet")
def test_backtest_command_writes_a_report() -> None: ...
