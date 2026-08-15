"""Turning a name into a strategy.

A config file or a queue message can only carry a string. The failure that
matters is a bad name or a bad parameter reaching a worker and dying eighty
rebalances into a run, so both are rejected when the reference is resolved.
"""

from __future__ import annotations

import pytest

from qrt.strategy import STRATEGIES, as_ref, available, load_strategy
from qrt.strategy.base import StrategyRef
from qrt.strategy.trailing_return import TrailingReturn


def test_a_named_strategy_resolves_to_an_object() -> None:
    strategy = load_strategy(
        StrategyRef("trailing_return", {"lookback_sessions": 30, "direction": -1})
    )
    assert isinstance(strategy, TrailingReturn)
    assert strategy.lookback_sessions == 30
    assert strategy.direction == -1


def test_defaults_apply_when_params_are_omitted() -> None:
    assert load_strategy(StrategyRef("trailing_return")).lookback_sessions == 60


def test_an_unknown_name_lists_what_is_available() -> None:
    """The error a typo in a config file produces, so it should say what the
    alternatives are rather than just refusing."""
    with pytest.raises(ValueError, match="trailing_retrun.*available: trailing_return"):
        load_strategy(StrategyRef("trailing_retrun"))


def test_an_unknown_parameter_is_rejected() -> None:
    with pytest.raises(ValueError, match="bad parameters"):
        load_strategy(StrategyRef("trailing_return", {"lookback_dayz": 60}))


def test_an_invalid_parameter_value_is_rejected_at_lookup() -> None:
    """The strategy's own validation runs here, not at the first rebalance."""
    with pytest.raises(ValueError, match="direction"):
        load_strategy(StrategyRef("trailing_return", {"direction": 2}))


def test_the_mapping_cannot_be_mutated() -> None:
    """Read-only, so what is available is whatever the file says. Nothing can
    add a strategy at import time and change the answer."""
    with pytest.raises(TypeError):
        STRATEGIES["sneaky"] = TrailingReturn  # type: ignore[index]


def test_available_lists_the_names() -> None:
    assert available() == ["trailing_return"]


def test_a_known_strategy_reports_its_name_and_parameters() -> None:
    """Round trip: an object built here can be described as a reference, and
    that reference rebuilds an equivalent object on another machine."""
    ref = as_ref(TrailingReturn(lookback_sessions=20, direction=-1))
    assert ref == StrategyRef(
        "trailing_return",
        {"lookback_sessions": 20, "direction": -1, "top_fraction": 0.2, "bottom_fraction": 0.2},
    )

    rebuilt = load_strategy(ref)
    assert rebuilt.lookback_sessions == 20
    assert rebuilt.direction == -1


def test_a_strategy_defined_outside_the_mapping_has_no_name() -> None:
    """A strategy written in a notebook runs locally but cannot be rebuilt from
    a description, so it reports no name rather than pretending to have one."""

    class AdHoc(TrailingReturn):
        pass

    assert as_ref(AdHoc()) is None
