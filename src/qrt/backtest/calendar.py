"""Trading days and rebalance timestamps.

Business logic, so a function rather than part of any interface. Month-end
means the last day the exchange was open, not the 31st.
"""

from __future__ import annotations

from datetime import datetime


def trading_days(start: datetime, end: datetime) -> list[datetime]:
    """NYSE sessions in [start, end], as timezone-aware closes."""
    raise NotImplementedError


def rebalance_timestamps(
    start: datetime,
    end: datetime,
    frequency: str,
) -> list[datetime]:
    """Rebalance instants for a frequency: "M", "W" or "D".

    Each one is an exchange close, because that is when a signal is computed.
    """
    raise NotImplementedError
