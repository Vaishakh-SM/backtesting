"""Alternative reader, for researchers who would rather write SQL.

Same signature as polars_reader.read_window; a test asserts the two return
identical frames.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import duckdb
import polars as pl

from qrt.data.dataset import DatasetRef, MissingData
from qrt.data.schema import PARTITION_COL, TZ

# QUALIFY filters after the window function, so the restatement collapse and
# the time bounds stay in one statement.
_SQL = """
SELECT * EXCLUDE ({partition_col})
FROM read_parquet($path, hive_partitioning = true)
WHERE event_ts > $since
  AND event_ts <= $as_of_event
  AND knowledge_ts <= $as_of_knowledge
  AND ($universe IS NULL OR list_contains($universe, ticker))
QUALIFY row_number() OVER (
    PARTITION BY {key} ORDER BY knowledge_ts DESC
) = 1
ORDER BY {key}
"""


def read_window(
    ref: DatasetRef,
    table: str,
    key: Sequence[str],
    universe: Sequence[str] | None,
    since: datetime,
    as_of_event: datetime,
    as_of_knowledge: datetime,
) -> pl.DataFrame:
    """See polars_reader.read_window."""
    sql = _SQL.format(partition_col=PARTITION_COL, key=", ".join(key))
    conn = duckdb.connect()
    try:
        # DuckDB renders TIMESTAMPTZ in the session timezone, which defaults to
        # the host's. Without this the same window comes back stamped
        # differently on different machines.
        conn.execute(f"SET TimeZone = '{TZ}'")
        for statement in ref.as_duckdb():
            conn.execute(statement)

        return conn.execute(
            sql,
            {
                "path": ref.scan(table),
                "since": since,
                "as_of_event": as_of_event,
                "as_of_knowledge": as_of_knowledge,
                "universe": list(universe) if universe is not None else None,
            },
        ).pl()
    except duckdb.IOException as exc:
        raise MissingData(ref, table) from exc
    finally:
        conn.close()
