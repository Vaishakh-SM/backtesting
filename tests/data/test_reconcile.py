"""How a fetch becomes rows in the store.

The rule under test:

    not seen before   ->  knowledge_ts = event_ts   (published at the close)
    contradicts       ->  knowledge_ts = now        (we learned it just now)
    identical         ->  dropped                   (nothing new to record)

The failure this guards against is the quiet one: stamping a re-fetched,
split-adjusted 2020 price as though we had known it in 2020, which would make
a point-in-time backtest read the future through the knowledge axis.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from qrt.data import ingest as ingest_module
from qrt.data.dataset import DatasetRef
from qrt.data.ingest import ingest
from qrt.data.polars_reader import read_latest
from qrt.data.schema import ACTIONS, ACTIONS_KEY, PRICES, PRICES_KEY
from qrt.data.yahoo import Fetched
from tests.conftest import actions_table, prices_table, read_table, ts

BAR_1 = ts(2026, 1, 5)
BAR_2 = ts(2026, 1, 6)
RUN_1 = ts(2026, 1, 7, hour=6)
RUN_2 = ts(2026, 6, 20, hour=6)


def vendor_returns(
    monkeypatch: pytest.MonkeyPatch,
    prices: Sequence[tuple],
    actions: Sequence[tuple] = (),
) -> None:
    """Stand in for yfinance, stamping publication time as the real one does."""

    def fetch(tickers, start, end):  # type: ignore[no-untyped-def]
        return Fetched(
            # knowledge_ts = event_ts, matching what yahoo.fetch produces.
            prices=prices_table(prices, knowledge_ts=None),
            actions=actions_table(actions, knowledge_ts=None),
            failed={},
        )

    monkeypatch.setattr(ingest_module.yahoo, "fetch", fetch)


def run(store: DatasetRef, at) -> object:  # type: ignore[no-untyped-def]
    return ingest(store, ["AAPL"], ts(2026, 1, 1, hour=0), ts(2026, 1, 31), at)


def test_a_first_observation_is_stamped_when_it_was_published(
    store: DatasetRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bar was public at its own close. Stamping it there models publication
    rather than inventing it, and is what makes point-in-time backtests over
    backfilled history work at all."""
    vendor_returns(monkeypatch, [("AAPL", BAR_1, 100.0)])
    run(store, RUN_1)

    rows = read_table(store, PRICES)
    assert rows["knowledge_ts"].to_list() == [BAR_1]


def test_re_running_over_unchanged_data_writes_nothing(
    store: DatasetRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Genuinely idempotent, rather than appending duplicates and relying on
    reads to hide them."""
    vendor_returns(monkeypatch, [("AAPL", BAR_1, 100.0)])
    run(store, RUN_1)
    summary = run(store, RUN_2)

    assert read_table(store, PRICES).height == 1
    assert summary.first_observations[PRICES] == 0  # type: ignore[attr-defined]
    assert summary.restatements[PRICES] == 0  # type: ignore[attr-defined]


def test_a_changed_value_is_stamped_when_we_learned_it(
    store: DatasetRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half of the rule that keeps it honest. We did not know the corrected
    price on 2026-01-05; we learned it in June."""
    vendor_returns(monkeypatch, [("AAPL", BAR_1, 100.0)])
    run(store, RUN_1)

    vendor_returns(monkeypatch, [("AAPL", BAR_1, 25.0)])
    summary = run(store, RUN_2)

    rows = read_table(store, PRICES).sort("knowledge_ts")
    assert rows["knowledge_ts"].to_list() == [BAR_1, RUN_2]
    assert rows["close"].to_list() == [100.0, 25.0]
    assert summary.restatements[PRICES] == 1  # type: ignore[attr-defined]


def test_a_correction_arriving_the_next_day(
    store: DatasetRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary case for a price correction, and what the key is shaped for.

    The key is (ticker, event_ts) and deliberately excludes knowledge_ts, so
    the corrected bar and the original are recognised as the same fact asserted
    twice rather than as two separate bars. Which one a reader sees is decided
    by its knowledge cutoff, not by which arrived first on disk.
    """
    next_day = ts(2026, 1, 6, hour=6)

    vendor_returns(monkeypatch, [("AAPL", BAR_1, 100.0)])
    run(store, RUN_1)

    vendor_returns(monkeypatch, [("AAPL", BAR_1, 100.5)])
    run(store, next_day)

    from qrt.data.polars_reader import read_window

    def seen_at(cutoff):  # type: ignore[no-untyped-def]
        rows = read_window(
            store, PRICES, PRICES_KEY, ["AAPL"], ts(2026, 1, 1, hour=0), ts(2026, 1, 31), cutoff
        )
        return rows["close"].to_list()

    # Two rows stored, one bar. The cutoff picks which assertion applies.
    assert read_table(store, PRICES).height == 2
    assert seen_at(ts(2026, 1, 5, hour=20)) == [100.0]  # before the correction
    assert seen_at(ts(2026, 1, 6, hour=20)) == [100.5]  # after it


def test_a_backdated_correction_is_allowed(
    store: DatasetRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stamping a correction earlier than now is a real operation, not a bug.

    A vendor with a genuine point-in-time feed supplies real publication times,
    and a fix to our own normaliser may be a value that truly was available at
    the time. Nothing here forbids it; a reader simply resolves by cutoff.
    """
    vendor_returns(monkeypatch, [("AAPL", BAR_1, 100.0)])
    run(store, ts(2026, 3, 1, hour=6))

    vendor_returns(monkeypatch, [("AAPL", BAR_1, 100.5)])
    backdated = ts(2026, 1, 5, hour=18)
    run(store, backdated)

    stamps = read_table(store, PRICES).sort("knowledge_ts")["knowledge_ts"].to_list()
    assert stamps == [BAR_1, backdated]


def test_a_correction_on_the_same_instant_is_refused(
    store: DatasetRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one case with no defined answer.

    Two rows sharing a key and a knowledge_ts leave a reader picking
    arbitrarily, so this is rejected rather than written. The ambiguity is the
    bug — backdating on its own is fine, see the test above.
    """
    vendor_returns(monkeypatch, [("AAPL", BAR_1, 100.0)])
    run(store, RUN_1)

    vendor_returns(monkeypatch, [("AAPL", BAR_1, 100.5)])
    with pytest.raises(ValueError, match="same knowledge_ts"):
        run(store, BAR_1)  # exactly the stamp the original carries


def test_a_restatement_is_invisible_before_it_happened(
    store: DatasetRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property all of this exists for: a backtest run in March is
    unchanged by a correction made in June."""
    vendor_returns(monkeypatch, [("AAPL", BAR_1, 100.0)])
    run(store, RUN_1)
    vendor_returns(monkeypatch, [("AAPL", BAR_1, 25.0)])
    run(store, RUN_2)

    from qrt.data.polars_reader import read_window

    as_known_in_march = read_window(
        store, PRICES, PRICES_KEY, ["AAPL"], ts(2026, 1, 1, hour=0), ts(2026, 1, 31), ts(2026, 3, 1)
    )
    assert as_known_in_march["close"].to_list() == [100.0]


def test_new_bars_alongside_a_restatement_keep_their_own_stamps(
    store: DatasetRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that both corrects an old bar and brings a new one must not stamp
    them the same way."""
    vendor_returns(monkeypatch, [("AAPL", BAR_1, 100.0)])
    run(store, RUN_1)

    vendor_returns(monkeypatch, [("AAPL", BAR_1, 25.0), ("AAPL", BAR_2, 101.0)])
    summary = run(store, RUN_2)

    latest = read_latest(store, PRICES, PRICES_KEY).sort("event_ts")
    assert latest["knowledge_ts"].to_list() == [RUN_2, BAR_2]
    assert summary.first_observations[PRICES] == 1  # type: ignore[attr-defined]
    assert summary.restatements[PRICES] == 1  # type: ignore[attr-defined]


def test_a_dividend_and_a_split_on_one_day_are_two_facts(
    store: DatasetRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actions key on kind as well as date. Without that, a company paying a
    dividend on a split ex-date would have one of them silently swallowed as a
    restatement of the other."""
    vendor_returns(
        monkeypatch,
        [("AAPL", BAR_1, 100.0)],
        [("AAPL", BAR_1, "dividend", 0.25), ("AAPL", BAR_1, "split", 4.0)],
    )
    run(store, RUN_1)

    actions = read_latest(store, ACTIONS, ACTIONS_KEY)
    assert sorted(actions["kind"].to_list()) == ["dividend", "split"]
