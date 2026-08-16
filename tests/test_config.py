"""Loading a config file.

A file names the backtests to run. What matters is that what comes back is
exactly what the file says: no run invented, none dropped, and a file that is
wrong rejected here rather than eighty rebalances into a run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backtester.config import load_backtest

ONE = """
strategy:
  name: trailing_return
  params: {lookback_sessions: 60}
universe: us-liquid-30
start: 2020-01-01
end: 2024-12-31
"""

THREE = """
- &base
  strategy:
    name: trailing_return
    params: {lookback_sessions: 20, direction: 1}
  universe: us-liquid-30
  start: 2020-01-01
  end: 2024-12-31
  cost_bps: 5.0

- <<: *base
  strategy:
    name: trailing_return
    params: {lookback_sessions: 60, direction: 1}

- <<: *base
  strategy:
    name: trailing_return
    params: {lookback_sessions: 60, direction: -1}
  cost_bps: 20.0
"""


def written(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return path


def test_a_single_backtest_need_not_be_a_list(tmp_path: Path) -> None:
    """The common case is one run, and making it a one-item list would be
    ceremony for nothing."""
    configs = load_backtest(written(tmp_path, ONE))

    assert len(configs) == 1
    assert configs[0].strategy.params == {"lookback_sessions": 60}


def test_a_list_is_one_backtest_per_entry(tmp_path: Path) -> None:
    configs = load_backtest(written(tmp_path, THREE))

    assert [c.strategy.params for c in configs] == [
        {"lookback_sessions": 20, "direction": 1},
        {"lookback_sessions": 60, "direction": 1},
        {"lookback_sessions": 60, "direction": -1},
    ]


def test_an_anchor_shares_settings_and_an_entry_can_still_override(tmp_path: Path) -> None:
    """Anchors are how a file avoids repeating itself. Nothing in the loader
    implements them, which is the point of using YAML's own feature."""
    configs = load_backtest(written(tmp_path, THREE))

    assert [c.universe for c in configs] == ["us-liquid-30"] * 3
    assert [c.cost_bps for c in configs] == [5.0, 5.0, 20.0]


def test_an_empty_file_is_refused(tmp_path: Path) -> None:
    """Running nothing at all looks exactly like a run that produced nothing."""
    with pytest.raises(ValueError, match="no backtests"):
        load_backtest(written(tmp_path, "[]\n"))


def test_a_bad_entry_names_itself(tmp_path: Path) -> None:
    """One wrong entry among several must say which field, not just fail."""
    with pytest.raises(ValidationError, match="end"):
        load_backtest(written(tmp_path, THREE.replace("end: 2024-12-31", "end: 2019-01-01", 1)))
