"""Default reader. Lazy scan over parquet, filters pushed down.

Same signature as duckdb_reader.read_window, deliberately. There is no reader
interface: the two modules are the seam, and switching engines means calling
the other function.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import polars as pl

from qrt.data.dataset import DatasetRef


def read_window(
    ref: DatasetRef,
    table: str,
    universe: Sequence[str],
    since: datetime,
    as_of_event: datetime,
    as_of_knowledge: datetime,
) -> pl.DataFrame:
    """Rows for one table in (since, as_of_event], as known at as_of_knowledge.

    Deduplicates restatements: at most one row per (ticker, event_ts), the one
    with the newest knowledge_ts at or before the cutoff.
    """
    raise NotImplementedError
