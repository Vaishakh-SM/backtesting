"""Table names and column schemas.

Schemas are only needed when writing — readers get them back from the parquet
footer — so they live next to the ingestion code rather than in a shared
module. Named constants, so a typo fails at import instead of at runtime.

Every table is append-only and carries two timestamps:

    event_ts      what the row is about
    knowledge_ts  when we learned it

A restatement is a new row with the same event_ts and a later knowledge_ts.
Nothing is ever updated or deleted.
"""

from __future__ import annotations

import pyarrow as pa

from backtester.conventions import TZ

_TS = pa.timestamp("us", tz=TZ)

PRICES = "prices"
ACTIONS = "actions"
UNIVERSE = "universe"

# Files are laid out as <table>/event_year=YYYY/<batch>.parquet. Year is coarse
# enough to keep file counts sane and fine enough to prune most of a scan.
PARTITION_COL = "event_year"


PRICES_SCHEMA = pa.schema(
    [
        ("ticker", pa.string()),
        ("event_ts", _TS),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("volume", pa.int64()),
        ("knowledge_ts", _TS),
        ("source", pa.string()),
        (PARTITION_COL, pa.int32()),
    ]
)

# kind is "split" or "dividend".
#   split     value = ratio, e.g. 4.0 for a 4-for-1
#   dividend  value = cash amount per share, in the listing currency
ACTIONS_SCHEMA = pa.schema(
    [
        ("ticker", pa.string()),
        ("event_ts", _TS),
        ("kind", pa.string()),
        ("value", pa.float64()),
        ("knowledge_ts", _TS),
        ("source", pa.string()),
        (PARTITION_COL, pa.int32()),
    ]
)

# Membership over time. Populated with a constant list today, which is where
# the survivorship bias in docs/ASSUMPTIONS.md comes from. The shape is here so
# point-in-time membership can be added without a migration.
UNIVERSE_SCHEMA = pa.schema(
    [
        ("ticker", pa.string()),
        ("event_ts", _TS),
        ("in_universe", pa.bool_()),
        ("knowledge_ts", _TS),
        (PARTITION_COL, pa.int32()),
    ]
)

# What identifies an observation, and what counts as its content.
#
# The key is what a restatement restates: two rows sharing a key are the same
# fact asserted twice, and only the newest is read. Note that actions key on
# `kind` as well — a dividend and a split can share an ex-date, and they are
# two facts about that day rather than one correcting the other.
#
# The value columns are what "changed" means when deciding whether a re-fetch
# has told us anything new.

PRICES_KEY = ("ticker", "event_ts")
PRICES_VALUES = ("open", "high", "low", "close", "volume")

ACTIONS_KEY = ("ticker", "event_ts", "kind")
ACTIONS_VALUES = ("value",)

UNIVERSE_KEY = ("ticker", "event_ts")
UNIVERSE_VALUES = ("in_universe",)

# Deliberately no name -> schema dictionary. Callers reference the constant
# they mean, so a typo is an import error rather than a KeyError at runtime.
