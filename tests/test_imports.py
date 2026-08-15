"""Every module has to import on its own.

A circular import between two packages only shows up when one of them is
imported first. Under pytest something always gets there first in an order that
happens to work, so the whole suite can pass while `import qrt.strategy` in a
fresh interpreter raises — which is exactly what happened, and only surfaced
when `qrt strategies` ran inside the container.

Each import runs in its own subprocess, because once a module is in
sys.modules the cycle is no longer reachable.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

MODULES = [
    "qrt",
    "qrt.conventions",
    "qrt.config",
    "qrt.cli",
    "qrt.data",
    "qrt.data.dataset",
    "qrt.data.ingest",
    "qrt.data.polars_reader",
    "qrt.data.duckdb_reader",
    "qrt.data.dividends",
    "qrt.strategy",
    "qrt.strategy.base",
    "qrt.strategy.portfolio",
    "qrt.strategy.trailing_return",
    "qrt.backtest",
    "qrt.backtest.engine",
    "qrt.backtest.calendar",
    "qrt.backtest.store",
    "qrt.report.metrics",
    "qrt.report.html",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_standalone(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"], capture_output=True, text=True
    )
    assert result.returncode == 0, f"import {module} failed:\n{result.stderr}"


def test_the_dependency_direction_holds() -> None:
    """report -> backtest -> strategy -> data, one way only.

    The cycle that got through was strategy importing from backtest. Stating
    the rule as a test means the next one fails here rather than in a
    container.
    """
    import pathlib

    forbidden = {
        "qrt/data": ("qrt.strategy", "qrt.backtest", "qrt.report"),
        "qrt/strategy": ("qrt.backtest", "qrt.report"),
        "qrt/backtest": ("qrt.report",),
    }

    for package, banned in forbidden.items():
        for path in pathlib.Path("src", package).rglob("*.py"):
            source = path.read_text()
            for module in banned:
                assert f"from {module}" not in source and f"import {module}" not in source, (
                    f"{path} imports {module}, which reverses the dependency direction"
                )
