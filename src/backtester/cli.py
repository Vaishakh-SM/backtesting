"""Command line entry point.

Ingestion and backtesting are separate commands on purpose. Ingestion touches
the network and writes; backtests do neither. Running them together would make
every backtest depend on vendor uptime.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer

from backtester import __version__
from backtester.config import load_backtest, load_universe
from backtester.conventions import CLOSE_HOUR, TZ
from backtester.data.dataset import DatasetRef

app = typer.Typer(add_completion=False, help="Backtesting platform.")

logger = logging.getLogger(__name__)

NY = ZoneInfo(TZ)

RootOpt = Annotated[str, typer.Option(help="Dataset root: a local path or s3://...")]

# On each command rather than on the app, so they can be typed where a person
# naturally types them: `backtester run --debug config.yaml`. As app-level
# options they would only be accepted before the command name, which is a
# distinction nobody should have to know.
QuietOpt = Annotated[bool, typer.Option("--quiet", "-q", help="Errors only.")]
DebugOpt = Annotated[bool, typer.Option("--debug", help="Every read and rebalance.")]


def _configure(quiet: bool, debug: bool) -> None:
    """Set logging up for one command.

    Progress goes to stderr and results go to stdout, so `backtester run ... >
    ids.txt` still collects only the directories while a person or a scheduler
    watches the rest.

    The library never configures logging itself. It only ever asks for a logger,
    so importing it into a notebook or a service leaves that program's own
    logging setup alone.
    """
    logging.basicConfig(
        level=logging.ERROR if quiet else logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
        force=True,  # tests invoke several commands in one process
    )


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
    quiet: QuietOpt = False,
    debug: DebugOpt = False,
) -> None:
    """Fetch and append market data. Run periodically; the only writer."""
    from backtester.data.ingest import ingest as run_ingest

    _configure(quiet, debug)

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
def run(
    config: Annotated[Path, typer.Argument(help="Backtest config.")],
    universe: Annotated[Path, typer.Option(help="Universe config.")] = Path(
        "configs/universe.yaml"
    ),
    root: RootOpt = "./data/us-equities",
    out: Annotated[Path, typer.Option(help="Where to write the result.")] = Path("out"),
    region: Annotated[str, typer.Option(help="For s3:// roots.")] = "us-east-1",
    quiet: QuietOpt = False,
    debug: DebugOpt = False,
) -> None:
    """Run the backtests a config file describes, and write each result.

    A file listing several backtests runs them in sequence, one directory each,
    so a single report can cover the lot.

    Writes rather than prints, so a report can be produced later without
    re-running anything.
    """
    from backtester.data.polars_reader import latest_knowledge_ts
    from backtester.engine.runner import run_backtest
    from backtester.engine.spec import BacktestSpec
    from backtester.engine.store import save_result
    from backtester.strategy import load_strategy
    from backtester.strategy.base import StrategyRef

    _configure(quiet, debug)

    configs = load_backtest(config)
    names = load_universe(universe)
    for cfg in configs:
        if cfg.universe != names.name:
            raise typer.BadParameter(
                f"config wants universe {cfg.universe!r}, {universe} is {names.name!r}"
            )

    ref = DatasetRef(root, {"region": region} if "://" in root else {})

    strategies = [StrategyRef(cfg.strategy.name, cfg.strategy.params) for cfg in configs]
    for strategy in strategies:  # fail on a bad name or params before running any
        load_strategy(strategy)

    # Resolved once for the file, so runs meant to be compared cannot end up
    # reading the store as of different moments.
    cutoff = latest_knowledge_ts(ref)

    for position, (cfg, strategy) in enumerate(zip(configs, strategies, strict=True), start=1):
        if len(configs) > 1:
            logger.info("run %d of %d: %s", position, len(configs), dict(strategy.params))

        spec = BacktestSpec(
            universe=tuple(names.tickers),
            start=_at_close(cfg.start),
            end=_at_close(cfg.end),
            strategy=strategy,
            as_of_knowledge=cutoff,
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
    runs: Annotated[list[Path], typer.Argument(help="Result directories from `backtester run`.")],
    out: Annotated[Path, typer.Option()] = Path("out/report.html"),
    quiet: QuietOpt = False,
    debug: DebugOpt = False,
) -> None:
    """Render one report over one or more runs.

    Reads what `backtester run` wrote, so a sweep of parameter sets becomes one
    document without re-running anything.
    """
    from backtester.engine.store import load_results
    from backtester.report.html import render

    _configure(quiet, debug)

    results = load_results(runs)
    written = render(results, out)
    typer.echo(f"{written}  {len(results)} run(s)")


@app.command()
def strategies() -> None:
    """List the strategies a config file can name."""
    from backtester.strategy import STRATEGIES

    for name, cls in sorted(STRATEGIES.items()):
        typer.echo(f"{name:20} {cls.__module__}.{cls.__qualname__}")


if __name__ == "__main__":
    app()
