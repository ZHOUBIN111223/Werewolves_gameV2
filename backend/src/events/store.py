"""Synchronous wrappers around the async SQLite event store."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable

from .async_store import (
    AsyncEventStore as BaseAsyncEventStore,
    EventQuery,
    GameEventStats,
    GlobalEventStore as BaseGlobalEventStore,
)
from .event import EventBase


def get_async_store(db_path: str | Path) -> BaseGlobalEventStore:
    """Return the async game-level event store."""
    return BaseGlobalEventStore(db_path)


class SyncEventStoreWrapper:
    """Compatibility wrapper for code that still needs sync access."""

    def __init__(self, file_path: str | Path) -> None:
        db_path = Path(file_path).with_suffix(".db")
        self._async_store = BaseAsyncEventStore(db_path)
        asyncio.run(self._async_store.initialize())

    def append(self, event: EventBase) -> None:
        asyncio.run(self._async_store.append(event))

    def append_many(self, events: Iterable[EventBase]) -> None:
        asyncio.run(self._async_store.append_many(events))

    def read_all(self) -> list[EventBase]:
        return asyncio.run(self._async_store.read_all())

    def filter_by_visibility(self, audience: str) -> list[EventBase]:
        return asyncio.run(self._async_store.filter_by_visibility(audience))

    def query_events(self, query: EventQuery | None = None) -> list[EventBase]:
        return asyncio.run(self._async_store.query_events(query))


class EventStore(SyncEventStoreWrapper):
    """Backward-compatible sync event store."""


class GlobalEventStore(SyncEventStoreWrapper):
    """Backward-compatible sync wrapper for game-scoped queries."""

    def __init__(self, file_path: str | Path) -> None:
        db_path = Path(file_path).with_suffix(".db")
        self._async_store = BaseGlobalEventStore(db_path)
        asyncio.run(self._async_store.initialize())

    def get_events_by_game_id(self, game_id: str) -> list[EventBase]:
        return asyncio.run(self._async_store.get_events_by_game_id(game_id))

    def get_events_by_type(self, event_type: str) -> list[EventBase]:
        return asyncio.run(self._async_store.get_events_by_type(event_type))

    def get_events_by_phase(self, game_phase: str) -> list[EventBase]:
        return asyncio.run(self._async_store.get_events_by_phase(game_phase))

    def has_game(self, game_id: str) -> bool:
        return asyncio.run(self._async_store.has_game(game_id))

    def query_game_events(
        self,
        game_id: str,
        *,
        after_timestamp: int | None = None,
        event_type: str | None = None,
        phase: str | None = None,
        actor: str | None = None,
        system_name: str | None = None,
        visibility_scope: str | None = None,
        limit: int | None = None,
    ) -> list[EventBase]:
        return asyncio.run(
            self._async_store.query_game_events(
                game_id,
                after_timestamp=after_timestamp,
                event_type=event_type,
                phase=phase,
                actor=actor,
                system_name=system_name,
                visibility_scope=visibility_scope,
                limit=limit,
            )
        )

    def get_game_statistics(
        self,
        game_id: str,
        *,
        visibility_scope: str | None = None,
    ) -> GameEventStats:
        return asyncio.run(
            self._async_store.get_game_statistics(
                game_id,
                visibility_scope=visibility_scope,
            )
        )


__all__ = [
    "EventQuery",
    "GameEventStats",
    "get_async_store",
    "EventStore",
    "SyncEventStoreWrapper",
    "GlobalEventStore",
    "BaseAsyncEventStore",
    "BaseGlobalEventStore",
]
