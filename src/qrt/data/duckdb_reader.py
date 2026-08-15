"""Alternative reader. Same signature as polars_reader.read_window.

Researchers who prefer SQL can point the engine at this one. Kept in step with
the polars reader by tests that assert both return identical frames.
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
    """See polars_reader.read_window."""
    raise NotImplementedError
