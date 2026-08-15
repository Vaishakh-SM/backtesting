"""Ingestion is append-only, and a restatement adds rather than replaces.

These target the way a bitemporal store goes silently wrong: a rewrite that
loses the previous observation, or a re-run that quietly drops data. Both leave
a store that looks fine and answers a past question differently than it did
before.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from qrt.data.dataset import DatasetRef
from qrt.data.ingest import ingest, latest_knowledge_ts
from qrt.data.schema import PRICES, UNIVERSE
from qrt.data.writer import append
from qrt.data.yahoo import Fetched
from tests.conftest import actions_table, prices_table, ts

BATCH_1 = ts(2026, 1, 10, hour=6)
BATCH_2 = ts(2026, 6, 20, hour=6)


def read(ref: DatasetRef, table: str) -> pl.DataFrame:
    return pl.scan_parquet(ref.scan(table), **ref.as_polars()).collect()


def test_reingesting_same_period_keeps_both_observations(store: DatasetRef) -> None:
    """The same bar fetched twice is two observations, not one overwritten."""
    bar = [("AAPL", ts(2026, 1, 5), 100.0)]

    append(store, PRICES, prices_table(bar, BATCH_1), BATCH_1)
    append(store, PRICES, prices_table(bar, BATCH_2), BATCH_2)

    rows = read(store, PRICES)
    assert rows.height == 2
    assert sorted(rows["knowledge_ts"].to_list()) == [BATCH_1, BATCH_2]


def test_restatement_keeps_the_superseded_value(store: DatasetRef) -> None:
    """A corrected price does not erase what we previously believed.

    This is the whole reason for the knowledge axis: a backtest run before the
    correction must stay reproducible afterwards.
    """
    append(store, PRICES, prices_table([("AAPL", ts(2026, 1, 5), 100.0)], BATCH_1), BATCH_1)
    append(store, PRICES, prices_table([("AAPL", ts(2026, 1, 5), 25.0)], BATCH_2), BATCH_2)

    rows = read(store, PRICES).sort("knowledge_ts")
    assert rows["close"].to_list() == [100.0, 25.0]


def test_existing_files_are_never_modified(store: DatasetRef) -> None:
    """A second batch adds files. It does not touch the first batch's bytes."""
    append(store, PRICES, prices_table([("AAPL", ts(2026, 1, 5), 100.0)], BATCH_1), BATCH_1)

    written = sorted(Path(store.table(PRICES)).rglob("*.parquet"))
    before = {p: p.read_bytes() for p in written}

    append(store, PRICES, prices_table([("AAPL", ts(2026, 1, 5), 25.0)], BATCH_2), BATCH_2)

    for path, content in before.items():
        assert path.read_bytes() == content, f"{path.name} was rewritten"

    after = sorted(Path(store.table(PRICES)).rglob("*.parquet"))
    assert len(after) == len(written) + 1


def test_batches_are_traceable_on_disk(store: DatasetRef) -> None:
    """File names carry the batch stamp, so a row can be tied to the run that
    produced it without opening anything."""
    append(store, PRICES, prices_table([("AAPL", ts(2026, 1, 5), 100.0)], BATCH_1), BATCH_1)

    names = [p.name for p in Path(store.table(PRICES)).rglob("*.parquet")]
    assert all(n.startswith("20260110T060000") for n in names)


def test_empty_fetch_writes_nothing(store: DatasetRef) -> None:
    from qrt.data.schema import PRICES_SCHEMA

    assert append(store, PRICES, PRICES_SCHEMA.empty_table(), BATCH_1) == 0
    assert not Path(store.table(PRICES)).exists()


def test_rows_land_in_partitions_by_event_year(store: DatasetRef) -> None:
    rows = [("AAPL", ts(2024, 6, 3), 10.0), ("AAPL", ts(2026, 6, 3), 20.0)]
    append(store, PRICES, prices_table(rows, BATCH_1), BATCH_1)

    partitions = {p.name for p in Path(store.table(PRICES)).iterdir()}
    assert partitions == {"event_year=2024", "event_year=2026"}


# --- the job itself, with the vendor call substituted -----------------------


@pytest.fixture
def fake_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for yfinance. Everything downstream of it stays real."""
    from qrt.data import ingest as ingest_module

    def fetch(tickers, start, end, knowledge_ts):  # type: ignore[no-untyped-def]
        return Fetched(
            prices=prices_table([("AAPL", ts(2026, 1, 5), 100.0)], knowledge_ts),
            actions=actions_table([("AAPL", ts(2026, 1, 5), "split", 4.0)], knowledge_ts),
            failed={"BADTICKER": "no rows returned"},
        )

    monkeypatch.setattr(ingest_module.yahoo, "fetch", fetch)


@pytest.mark.usefixtures("fake_vendor")
def test_failed_tickers_are_reported_and_left_out_of_the_universe(
    store: DatasetRef,
) -> None:
    """A symbol that could not be fetched must not silently appear as a name we
    hold data for."""
    summary = ingest(
        ref=store,
        tickers=["AAPL", "BADTICKER"],
        start=ts(2026, 1, 1, hour=0),
        end=ts(2026, 1, 31),
        knowledge_ts=BATCH_1,
    )

    assert "BADTICKER" in summary.failed
    assert read(store, UNIVERSE)["ticker"].to_list() == ["AAPL"]


@pytest.mark.usefixtures("fake_vendor")
def test_knowledge_ts_comes_from_the_caller_not_the_clock(store: DatasetRef) -> None:
    """Injected rather than read from wall time, so the job is deterministic
    and a backfill can be stamped with the time it represents."""
    ingest(
        ref=store,
        tickers=["AAPL"],
        start=ts(2026, 1, 1, hour=0),
        end=ts(2026, 1, 31),
        knowledge_ts=BATCH_1,
    )

    assert read(store, PRICES)["knowledge_ts"].unique().to_list() == [BATCH_1]
    assert latest_knowledge_ts(store) == BATCH_1


def test_latest_knowledge_ts_on_an_empty_store_says_so(store: DatasetRef) -> None:
    with pytest.raises(Exception, match="qrt ingest"):
        latest_knowledge_ts(store)
