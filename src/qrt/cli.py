"""Command line entry point.

Ingestion and backtesting are separate commands on purpose. Ingestion touches
the network and writes; backtests do neither. Running them together would make
every backtest depend on vendor uptime.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer

from qrt import __version__
from qrt.config import load_backtest, load_universe
from qrt.conventions import CLOSE_HOUR, TZ
from qrt.data.dataset import DatasetRef

app = typer.Typer(add_completion=False, help="Backtesting platform.")

NY = ZoneInfo(TZ)

RootOpt = Annotated[str, typer.Option(help="Dataset root: a local path or s3://...")]


def _parse_day(value: str, hour: int) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(hour=hour, tzinfo=NY)


def _at_close(day: date) -> datetime:
    """Config carries dates; the engine works in exchange closes."""
    return datetime(day.year, day.month, day.day, CLOSE_HOUR, tzinfo=NY)


@app.command()
def ingest(
    universe: Annotated[Path, typer.Option(help="Universe config.")] = Path(
        "configs/universe.yaml"
    ),
    root: RootOpt = "./data/us-equities",
    start: Annotated[str, typer.Option(help="First event date, YYYY-MM-DD.")] = "2015-01-01",
    end: Annotated[str, typer.Option(help="Last event date, YYYY-MM-DD. Defaults to today.")] = "",
    region: Annotated[str, typer.Option(help="For s3:// roots.")] = "us-east-1",
) -> None:
    """Fetch and append market data. Run periodically; the only writer."""
    from qrt.data.ingest import ingest as run_ingest

    cfg = load_universe(universe)
    ref = DatasetRef(root, {"region": region} if "://" in root else {})

    now = datetime.now(NY)
    summary = run_ingest(
        ref=ref,
        tickers=cfg.tickers,
        start=_parse_day(start, hour=0),
        end=_parse_day(end, hour=23) if end else now,
        # Only used to stamp restatements and name the batch: first observations
        # are stamped at the bar close, when they were published.
        ingested_at=now,
    )

    typer.echo(summary)
    if summary.failed:
        for ticker, reason in sorted(summary.failed.items()):
            typer.echo(f"  {ticker}: {reason}", err=True)
        raise typer.Exit(code=1)


@app.command()
def backtest(
    config: Annotated[Path, typer.Argument(help="Backtest config.")],
    universe: Annotated[Path, typer.Option(help="Universe config.")] = Path(
        "configs/universe.yaml"
    ),
    root: RootOpt = "./data/us-equities",
    out: Annotated[Path, typer.Option(help="Where to write the result.")] = Path("out"),
    region: Annotated[str, typer.Option(help="For s3:// roots.")] = "us-east-1",
) -> None:
    """Run a backtest over data already in the store, and write the result.

    Writes rather than prints, so a report can be produced later — and so a
    sweep leaves one directory per parameter set to report over together.
    """
    from qrt.backtest.engine import run_backtest
    from qrt.backtest.spec import BacktestSpec
    from qrt.backtest.store import save_result
    from qrt.data.polars_reader import latest_knowledge_ts
    from qrt.strategy import load_strategy
    from qrt.strategy.base import StrategyRef

    cfg = load_backtest(config)
    names = load_universe(universe)
    if cfg.universe != names.name:
        raise typer.BadParameter(
            f"config wants universe {cfg.universe!r}, {universe} is {names.name!r}"
        )

    ref = DatasetRef(root, {"region": region} if "://" in root else {})
    strategy = StrategyRef(cfg.strategy.name, cfg.strategy.params)
    load_strategy(strategy)  # fail here on a bad name or bad params, not mid-run

    spec = BacktestSpec(
        universe=tuple(names.tickers),
        start=_at_close(cfg.start),
        end=_at_close(cfg.end),
        strategy=strategy,
        # Resolved once, here, so a fan-out cannot see different cutoffs.
        as_of_knowledge=latest_knowledge_ts(ref),
        point_in_time=cfg.point_in_time,
        rebalance_frequency=cfg.rebalance_frequency,
        execution_lag_sessions=cfg.execution_lag_sessions,
        cost_bps=cfg.cost_bps,
        code_version=__version__,
    )

    result = run_backtest(spec, ref)
    directory = save_result(result, out)

    final = result.returns["equity"][-1]
    typer.echo(f"{directory}  {result.returns.height} periods  final equity {final:.4f}")


@app.command()
def report(
    runs: Annotated[list[Path], typer.Argument(help="Result directories from `qrt backtest`.")],
    out: Annotated[Path, typer.Option()] = Path("out/report.html"),
) -> None:
    """Render one report over one or more runs.

    Reads what `qrt backtest` wrote, so a sweep of parameter sets becomes one
    document without re-running anything.
    """
    from qrt.backtest.store import load_results
    from qrt.report.html import render

    written = render(load_results(runs), out)
    typer.echo(f"{written}  {len(runs)} run(s)")


@app.command()
def strategies() -> None:
    """List the strategies a config file can name."""
    from qrt.strategy import STRATEGIES

    for name, cls in sorted(STRATEGIES.items()):
        typer.echo(f"{name:20} {cls.__module__}.{cls.__qualname__}")


if __name__ == "__main__":
    app()
