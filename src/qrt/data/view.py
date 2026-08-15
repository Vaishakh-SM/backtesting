"""The bounded snapshot a strategy is handed."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

Format = Literal["polars", "pandas", "arrow"]


@runtime_checkable
class MarketView(Protocol):
    """One rebalance's worth of data, already filtered.

    Holds rows with event_ts <= as_of_event and knowledge_ts <=
    as_of_knowledge, reaching back as far as the strategy's lookback. Nothing
    outside that is reachable.

    A strategy reads this and returns scores. It does not fetch data, does not
    know where data is stored, and does not write time filters itself.

    Prices here are raw. Adjusting for splits and dividends is done in the
    strategy with adjust(), so that logic stays testable on its own.
    """

    @property
    def as_of_event(self) -> datetime: ...

    @property
    def as_of_knowledge(self) -> datetime: ...

    def read(self, table: str, fmt: Format = "polars") -> Any:
        """One table's rows for this window.

        A window is a few thousand rows, so strategies do ordinary dataframe
        work on it rather than pushing logic back down into the engine.
        """
        ...


class Snapshot:
    """MarketView backed by frames the engine has already fetched."""

    def __init__(
        self,
        frames: dict[str, Any],
        as_of_event: datetime,
        as_of_knowledge: datetime,
    ) -> None:
        self._frames = frames
        self._as_of_event = as_of_event
        self._as_of_knowledge = as_of_knowledge

    @property
    def as_of_event(self) -> datetime:
        return self._as_of_event

    @property
    def as_of_knowledge(self) -> datetime:
        return self._as_of_knowledge

    def read(self, table: str, fmt: Format = "polars") -> Any:
        raise NotImplementedError
