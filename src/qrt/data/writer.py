"""Append-only parquet writes.

The ingestion job is the only caller. Nothing else in the system writes, which
is what makes append-only cheap to hold: no locking, no coordination between
writers, no reconciliation.

Each call adds files under <table>/event_year=YYYY/<batch>-<n>.parquet.
Existing files are never touched, so a reader mid-scan is unaffected and a
restatement is simply another file.
"""

from __future__ import annotations

from datetime import datetime

import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.parquet as pq

from qrt.data.dataset import DatasetRef
from qrt.data.schema import PARTITION_COL


def batch_id(knowledge_ts: datetime) -> str:
    """Names the files a single ingestion produced, so a batch stays traceable
    on disk. Re-running with the same stamp rewrites that batch rather than
    silently doubling it."""
    return knowledge_ts.strftime("%Y%m%dT%H%M%S%z")


def _filesystem(ref: DatasetRef, path: str) -> tuple[pafs.FileSystem, str]:
    if ref.is_remote:
        return pafs.FileSystem.from_uri(path)
    return pafs.LocalFileSystem(), path


def append(ref: DatasetRef, table: str, rows: pa.Table, knowledge_ts: datetime) -> int:
    """Write `rows` as a new partitioned batch. Returns the row count."""
    if rows.num_rows == 0:
        return 0

    fs, path = _filesystem(ref, ref.table(table))

    pq.write_to_dataset(
        rows,
        root_path=path,
        filesystem=fs,
        partition_cols=[PARTITION_COL],
        basename_template=f"{batch_id(knowledge_ts)}-{{i}}.parquet",
        # Only touches files this batch names. Other batches in the same
        # partition directory are left alone, which is what keeps the log
        # append-only.
        existing_data_behavior="overwrite_or_ignore",
    )
    return rows.num_rows
