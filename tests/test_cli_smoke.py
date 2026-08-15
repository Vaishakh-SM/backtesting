"""The whole pipeline, through the commands a user actually types.

Unit tests cannot see wiring: a config field renamed on one side, a command
that builds a spec the engine rejects, a report pointed at the wrong directory.
Every piece can be right while the thing does not run.

This walks ingest -> backtest -> report exactly as the README documents it, and
asserts a report lands on disk with real numbers in it. The vendor call is the
one thing substituted, so it runs offline; everything after it is real.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from backtester.cli import app
from backtester.data import ingest as ingest_module
from backtester.data.yahoo import Fetched
from backtester.engine.calendar import trading_days
from tests.conftest import actions_table, prices_table, ts

UNIVERSE = ("AAPL", "MSFT", "NVDA", "XOM", "KO", "JNJ")
FIRST, LAST = ts(2024, 1, 2), ts(2024, 6, 28)

runner = CliRunner()


@pytest.fixture(autouse=True)
def offline_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for yfinance. Each name drifts at its own rate so the ranking
    is unambiguous, and one pays a dividend so the actions table is exercised.
    """

    def fetch(tickers: Sequence[str], start: datetime, end: datetime) -> Fetched:
        sessions = trading_days(FIRST, LAST)
        rows = [
            (ticker, session, 100.0 + (i - 2.5) * 0.4 * step)
            for i, ticker in enumerate(UNIVERSE)
            for step, session in enumerate(sessions)
        ]
        return Fetched(
            prices=prices_table(rows, None),
            actions=actions_table([("KO", sessions[20], "dividend", 0.5)], None),
            failed={},
        )

    monkeypatch.setattr(ingest_module.yahoo, "fetch", fetch)


def write_configs(tmp_path: Path) -> tuple[Path, Path]:
    universe = tmp_path / "universe.yaml"
    universe.write_text("name: smoke\ntickers:\n" + "".join(f"  - {t}\n" for t in UNIVERSE))

    config = tmp_path / "momentum.yaml"
    config.write_text(
        "strategy:\n"
        "  name: trailing_return\n"
        "  params:\n"
        "    lookback_sessions: 20\n"
        "    direction: 1\n"
        "    top_fraction: 0.34\n"
        "    bottom_fraction: 0.34\n"
        "universe: smoke\n"
        "start: 2024-03-01\n"
        "end: 2024-06-28\n"
        "rebalance_frequency: M\n"
        "execution_lag_sessions: 1\n"
        "cost_bps: 10.0\n"
    )
    return universe, config


def run(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, (
        f"`backtester {' '.join(args)}` failed:\n{result.output}\n{result.exception}"
    )
    return result.output


def test_ingest_backtest_report(tmp_path: Path) -> None:
    """The documented path, start to finish."""
    universe, config = write_configs(tmp_path)
    store, out = tmp_path / "store", tmp_path / "out"

    run(
        "ingest",
        "--universe",
        str(universe),
        "--root",
        str(store),
        "--start",
        "2024-01-01",
        "--end",
        "2024-06-30",
    )
    assert (store / "prices").exists()
    assert (store / "actions").exists()

    backtest_output = run(
        "run",
        str(config),
        "--universe",
        str(universe),
        "--root",
        str(store),
        "--out",
        str(out),
    )
    run_directory = Path(backtest_output.split()[0])
    assert (run_directory / "spec.json").exists()
    assert {p.name for p in run_directory.glob("*.parquet")} == {
        "returns.parquet",
        "positions.parquet",
        "scores.parquet",
    }

    report = tmp_path / "report.html"
    run("report", str(run_directory), "--out", str(report))

    html = report.read_text()
    assert "Sharpe (net)" in html
    assert "<svg" in html
    assert re.findall(r'(?:src|href)="(?!#)[^"]+"', html) == [], "report is not self-contained"


def test_the_config_reaches_the_spec_unaltered(tmp_path: Path) -> None:
    """Every field a config carries has to survive into the recorded spec.

    A field dropped between the two is invisible: the run succeeds, writes a
    result, and quietly answers a different question. Losing the execution lag
    would execute at the very close that generated the signal — the textbook
    lookahead — and every other test in the suite still passed when that was
    deliberately broken, because they build specs themselves rather than going
    through the command.
    """
    universe, config = write_configs(tmp_path)
    store, out = tmp_path / "store", tmp_path / "out"

    run(
        "ingest",
        "--universe",
        str(universe),
        "--root",
        str(store),
        "--start",
        "2024-01-01",
        "--end",
        "2024-06-30",
    )
    directory = Path(
        run(
            "run",
            str(config),
            "--universe",
            str(universe),
            "--root",
            str(store),
            "--out",
            str(out),
        ).split()[0]
    )

    spec = json.loads((directory / "spec.json").read_text())
    assert spec["execution_lag_sessions"] == 1
    assert spec["rebalance_frequency"] == "M"
    assert spec["cost_bps"] == 10.0
    assert spec["point_in_time"] is True
    assert spec["universe"] == list(UNIVERSE)
    assert spec["start"].startswith("2024-03-01")
    assert spec["end"].startswith("2024-06-28")
    assert spec["strategy"] == {
        "name": "trailing_return",
        "params": {
            "lookback_sessions": 20,
            "direction": 1,
            "top_fraction": 0.34,
            "bottom_fraction": 0.34,
        },
    }
    assert spec["reproducible"] is True


def test_positions_are_held_from_the_session_after_the_signal(tmp_path: Path) -> None:
    """The same guarantee, checked in the output rather than in the config."""
    universe, config = write_configs(tmp_path)
    store, out = tmp_path / "store", tmp_path / "out"

    run(
        "ingest",
        "--universe",
        str(universe),
        "--root",
        str(store),
        "--start",
        "2024-01-01",
        "--end",
        "2024-06-30",
    )
    directory = Path(
        run(
            "run",
            str(config),
            "--universe",
            str(universe),
            "--root",
            str(store),
            "--out",
            str(out),
        ).split()[0]
    )

    returns = pl.read_parquet(directory / "returns.parquet")
    assert returns.height > 0
    assert (returns["held_from"] > returns["rebalance_ts"]).all()


def test_a_sweep_becomes_one_report(tmp_path: Path) -> None:
    """The reason results are files: several parameter sets, reported together
    without re-running any of them."""
    universe, config = write_configs(tmp_path)
    store, out = tmp_path / "store", tmp_path / "out"

    run(
        "ingest",
        "--universe",
        str(universe),
        "--root",
        str(store),
        "--start",
        "2024-01-01",
        "--end",
        "2024-06-30",
    )

    directories = []
    for lookback in (10, 20):
        variant = tmp_path / f"m{lookback}.yaml"
        variant.write_text(
            config.read_text().replace("lookback_sessions: 20", f"lookback_sessions: {lookback}")
        )
        directories.append(
            run(
                "run",
                str(variant),
                "--universe",
                str(universe),
                "--root",
                str(store),
                "--out",
                str(out),
            ).split()[0]
        )

    assert len(set(directories)) == 2, "different parameters must not share a directory"

    report = tmp_path / "sweep.html"
    run("report", *directories, "--out", str(report))

    html = report.read_text()
    assert "lookback 10" in html and "lookback 20" in html


def test_re_running_a_backtest_does_not_duplicate_it(tmp_path: Path) -> None:
    """Same spec, same output directory — what a queue that redelivers needs."""
    universe, config = write_configs(tmp_path)
    store, out = tmp_path / "store", tmp_path / "out"

    run(
        "ingest",
        "--universe",
        str(universe),
        "--root",
        str(store),
        "--start",
        "2024-01-01",
        "--end",
        "2024-06-30",
    )

    first = run(
        "run",
        str(config),
        "--universe",
        str(universe),
        "--root",
        str(store),
        "--out",
        str(out),
    ).split()[0]
    second = run(
        "run",
        str(config),
        "--universe",
        str(universe),
        "--root",
        str(store),
        "--out",
        str(out),
    ).split()[0]

    assert first == second
    assert len(list(out.iterdir())) == 1


def test_re_ingesting_unchanged_data_appends_nothing(tmp_path: Path) -> None:
    """Idempotent through the command line, not just through the function."""
    universe, _ = write_configs(tmp_path)
    store = tmp_path / "store"

    run(
        "ingest",
        "--universe",
        str(universe),
        "--root",
        str(store),
        "--start",
        "2024-01-01",
        "--end",
        "2024-06-30",
    )
    files_after_first = sorted(p.name for p in (store / "prices").rglob("*.parquet"))

    output = run(
        "ingest",
        "--universe",
        str(universe),
        "--root",
        str(store),
        "--start",
        "2024-01-01",
        "--end",
        "2024-06-30",
    )

    assert "prices=0" in output
    assert sorted(p.name for p in (store / "prices").rglob("*.parquet")) == files_after_first


def test_a_config_naming_the_wrong_universe_is_refused(tmp_path: Path) -> None:
    """Two files that have to agree, so the failure is worth catching at the
    boundary rather than as an empty backtest."""
    universe, config = write_configs(tmp_path)
    other = tmp_path / "other.yaml"
    other.write_text("name: something-else\ntickers:\n  - AAPL\n  - MSFT\n")

    result = runner.invoke(
        app, ["run", str(config), "--universe", str(other), "--root", str(tmp_path / "store")]
    )
    assert result.exit_code != 0
    assert "something-else" in result.output


def test_backtesting_an_empty_store_says_what_to_do(tmp_path: Path) -> None:
    _, config = write_configs(tmp_path)
    universe = tmp_path / "universe.yaml"

    result = runner.invoke(
        app,
        ["run", str(config), "--universe", str(universe), "--root", str(tmp_path / "nothing")],
    )
    assert result.exit_code != 0
    assert "backtester ingest" in str(result.exception) + result.output


def test_the_strategies_command_lists_what_a_config_can_name() -> None:
    assert "trailing_return" in run("strategies")
