"""Command line entry point.

Ingestion and backtesting are separate commands on purpose. Ingestion touches
the network and writes; backtests do neither. Running them together would make
every backtest depend on vendor uptime.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer

from qrt.config import load_universe
from qrt.conventions import TZ
from qrt.data.dataset import DatasetRef

app = typer.Typer(add_completion=False, help="Backtesting platform.")

NY = ZoneInfo(TZ)

RootOpt = Annotated[str, typer.Option(help="Dataset root: a local path or s3://...")]


def _parse_day(value: str, hour: int) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(hour=hour, tzinfo=NY)


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
    root: RootOpt = "./data/us-equities",
    out: Annotated[Path, typer.Option()] = Path("out"),
) -> None:
    """Run a backtest over data already in the store."""
    raise NotImplementedError


@app.command()
def strategies() -> None:
    """List the strategies a config file can name."""
    from qrt.strategy import STRATEGIES

    for name, cls in sorted(STRATEGIES.items()):
        typer.echo(f"{name:20} {cls.__module__}.{cls.__qualname__}")


if __name__ == "__main__":
    app()
