"""Results on disk.

Running and reporting are separate steps, so a result has to survive the trip
through a file. What matters is that a run can be found again, that two runs of
the same thing do not become two answers, and that a spec which cannot be
rebuilt says so rather than looking reproducible.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from qrt.backtest.spec import BacktestResult, BacktestSpec
from qrt.backtest.store import load_result, load_results, save_result
from qrt.strategy.base import StrategyRef
from qrt.strategy.trailing_return import TrailingReturn
from tests.conftest import ts


def spec_for(**overrides: object) -> BacktestSpec:
    defaults: dict[str, object] = {
        "universe": ("AAPL", "MSFT"),
        "start": ts(2024, 1, 2),
        "end": ts(2024, 6, 28),
        "strategy": StrategyRef("trailing_return", {"lookback_sessions": 20, "direction": 1}),
        "as_of_knowledge": ts(2026, 1, 1),
    }
    return BacktestSpec(**(defaults | overrides))  # type: ignore[arg-type]


def result_for(spec: BacktestSpec) -> BacktestResult:
    return BacktestResult(
        spec=spec,
        knowledge_ts=spec.as_of_knowledge,
        reproducible=spec.is_reproducible(),
        scores=pl.DataFrame({"rebalance_ts": [ts(2024, 3, 1)], "ticker": ["AAPL"], "score": [0.1]}),
        positions=pl.DataFrame(
            {"rebalance_ts": [ts(2024, 3, 1)], "ticker": ["AAPL"], "weight": [0.5]}
        ),
        returns=pl.DataFrame({"rebalance_ts": [ts(2024, 3, 1)], "equity": [1.02]}),
    )


def test_a_result_round_trips(tmp_path: Path) -> None:
    spec = spec_for()
    saved = save_result(result_for(spec), tmp_path)
    back = load_result(saved)

    assert back.spec == spec
    assert back.reproducible is True
    assert_frame_equal(back.returns, result_for(spec).returns)
    assert_frame_equal(back.positions, result_for(spec).positions)
    assert_frame_equal(back.scores, result_for(spec).scores)


def test_the_directory_is_named_for_the_spec(tmp_path: Path) -> None:
    spec = spec_for()
    assert save_result(result_for(spec), tmp_path).name == spec.content_id()


def test_the_same_spec_writes_the_same_place(tmp_path: Path) -> None:
    """A queue that delivers a job twice must not produce two answers."""
    spec = spec_for()
    first = save_result(result_for(spec), tmp_path)
    second = save_result(result_for(spec), tmp_path)

    assert first == second
    assert len(list(tmp_path.iterdir())) == 1


def test_different_parameters_write_different_places(tmp_path: Path) -> None:
    """The point of the sweep: five parameter sets, five directories."""
    for lookback in (20, 60, 120):
        spec = spec_for(
            strategy=StrategyRef("trailing_return", {"lookback_sessions": lookback, "direction": 1})
        )
        save_result(result_for(spec), tmp_path)

    assert len(list(tmp_path.iterdir())) == 3


def test_the_content_id_does_not_depend_on_field_order(tmp_path: Path) -> None:
    """Hashing the canonical form rather than the dictionary as built, so the
    same run does not land in two places because a key moved."""
    a = spec_for(strategy=StrategyRef("trailing_return", {"direction": 1, "lookback_sessions": 20}))
    b = spec_for(strategy=StrategyRef("trailing_return", {"lookback_sessions": 20, "direction": 1}))
    assert a.content_id() == b.content_id()


def test_a_live_strategy_object_is_named_where_it_can_be(tmp_path: Path) -> None:
    """A spec built in a notebook still files under its content id, because the
    strategy is one the package knows."""
    spec = spec_for(strategy=TrailingReturn(20, 1))
    saved = save_result(result_for(spec), tmp_path)

    raw = json.loads((saved / "spec.json").read_text())
    assert raw["strategy"]["name"] == "trailing_return"
    assert raw["content_id"] == saved.name


def test_an_unregistered_strategy_is_saved_but_not_named(tmp_path: Path) -> None:
    """Written, so the work is not lost — but filed under a timestamp, and the
    file says it cannot be rebuilt from its own description."""

    class AdHoc(TrailingReturn):
        pass

    result = result_for(spec_for(strategy=AdHoc()))
    saved = save_result(replace(result, reproducible=False), tmp_path)

    assert saved.name.startswith("adhoc-")
    assert json.loads((saved / "spec.json").read_text())["reproducible"] is False


def test_a_spec_holding_a_live_object_has_no_content_id() -> None:
    """Nothing can guarantee two machines would rebuild the same thing."""
    assert spec_for(strategy=TrailingReturn(20, 1)).content_id() is None


def test_several_runs_load_together(tmp_path: Path) -> None:
    """What a consolidated report reads."""
    directories = [
        save_result(
            result_for(
                spec_for(
                    strategy=StrategyRef(
                        "trailing_return", {"lookback_sessions": n, "direction": 1}
                    )
                )
            ),
            tmp_path,
        )
        for n in (20, 60)
    ]

    loaded = load_results(directories)
    assert len(loaded) == 2
    assert {r.spec.strategy.params["lookback_sessions"] for r in loaded} == {20, 60}  # type: ignore[union-attr]


def test_a_missing_run_says_which(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_result(tmp_path / "not-a-run")
