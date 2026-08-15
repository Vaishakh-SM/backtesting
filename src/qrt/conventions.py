"""Market conventions.

Facts about the venue we trade, not about how we store data. Ingestion, the
calendar and the readers all have to agree on these, so they are defined once.
"""

from __future__ import annotations

# Every instrument is NYSE-listed for now, so all timestamps are timezone-aware
# in New York time.
TZ = "America/New_York"

# Every session is treated as a full day ending here, early closes included.
# NYSE shuts at 13:00 on about four days a year; we ignore that so that
# ingestion and the calendar stamp the same instant. If these two ever
# disagreed, a rebalance would exclude its own day's bar. See
# docs/ASSUMPTIONS.md.
CLOSE_HOUR = 16
