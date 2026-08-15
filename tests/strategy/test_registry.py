"""Strategies resolve by name, and bad ones fail when the spec is built."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="registry not implemented yet")
def test_shipped_strategy_resolves_by_name() -> None: ...


@pytest.mark.skip(reason="registry not implemented yet")
def test_unknown_name_fails_immediately() -> None: ...


@pytest.mark.skip(reason="registry not implemented yet")
def test_bad_params_fail_at_load_not_at_run() -> None: ...


@pytest.mark.skip(reason="registry not implemented yet")
def test_spec_with_live_object_reports_not_reproducible() -> None: ...
