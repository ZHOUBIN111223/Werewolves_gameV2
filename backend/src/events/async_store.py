"""Async SQLite-backed event storage."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from src.enums import ActionType, GamePhase

from .action import Action
from .event import EventBase
from .observation import Observation
from .system_event import SystemEvent


_EVENT_TYPE_MAP = {
    "action": Action,
    "observation": Observation,
    "system": SystemEvent,
}

_GROUPABLE_FIELDS = {"event_type", "phase", "system_name", "actor"}

_INSERT_EVENT_SQL = """
INSERT INTO events
(event_id, game_id, event_type, phase, visibility, actor, action_type, system_name, payload, timestamp, sequence_num, version)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


@dataclass(slots=True)
class EventQuery:
    """Structured query options for reading stored events."""

    game_id: str | None = None
    after_timestamp: int | None = None
    event_type: str | None = None
    phase: str | None = None
    actor: str | None = None
    system_name: str | None = None
    visibility_scope: str | None = None
    limit: int | None = None


@dataclass(slots=True)
class GameEventStats:
    """Aggregate statistics for one stored game."""

    game_id: str
    total_events: int = 0
    first_seq: int = 0
    last_seq: int = 0
    counts_by_type: dict[str, int] = field(default_factory=dict)
    counts_by_phase: dict[str, int] = field(default_factory=dict)
    counts_by_system_name: dict[str, int] = field(default_factory=dict)
    counts_by_actor: dict[str, int] = field(default_factory=dict)


class AsyncEventStore:
    """Asynchronous event store backed by SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self) -> None:
        """Create tables and indexes on first use."""
        if self._initialized:
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.execute("PRAGMA cache_size=1000")
            await db.execute("PRAGMA temp_store=memory")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    game_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    actor TEXT,
                    action_type TEXT,
                    system_name TEXT,
                    payload TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    sequence_num INTEGER DEFAULT 0,
                    version INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cursor = await db.execute("PRAGMA table_info(events)")
            columns = [column[1] for column in await cursor.fetchall()]
            if "sequence_num" not in columns:
                await db.execute("ALTER TABLE events ADD COLUMN sequence_num INTEGER DEFAULT 0")

            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_game_id ON events(game_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_phase ON events(phase)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_sequence ON events(sequence_num)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_event_id ON events(event_id)")
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_game_timeline
                ON events(game_id, timestamp, sequence_num, id)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_game_system
                ON events(game_id, system_name)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_game_actor
                ON events(game_id, actor)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_game_phase
                ON events(game_id, phase)
                """
            )
            await db.commit()

        self._initialized = True

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None

    async def append(self, event: EventBase) -> None:
        """Append one event."""
        await self.initialize()
        serialized_event = self._serialize_event(event)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(_INSERT_EVENT_SQL, self._event_insert_params(serialized_event))
            await db.commit()

    async def append_many(self, events: Iterable[EventBase]) -> None:
        """Append multiple events in a single transaction."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                for event in events:
                    serialized_event = self._serialize_event(event)
                    await db.execute(_INSERT_EVENT_SQL, self._event_insert_params(serialized_event))
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def read_all(self) -> list[EventBase]:
        """Read all stored events."""
        return await self.query_events()

    async def filter_by_visibility(self, audience: str) -> list[EventBase]:
        """Read all events visible to the given audience."""
        return await self.query_events(EventQuery(visibility_scope=audience))

    async def query_events(self, query: EventQuery | None = None) -> list[EventBase]:
        """Read events matching the provided filters."""
        await self.initialize()
        query = query or EventQuery()
        where_sql, params = self._build_where_clause(query)

        sql = f"""
            SELECT *
            FROM events
            {where_sql}
            ORDER BY timestamp ASC, sequence_num ASC, id ASC
        """
        if query.limit is not None:
            sql += "\nLIMIT ?"
            params.append(query.limit)

        rows = await self._fetch_rows(sql, params)
        return [self._deserialize_event(self._row_to_dict(row)) for row in rows]

    async def count_grouped_by(self, field: str, query: EventQuery | None = None) -> dict[str, int]:
        """Count events grouped by a known column."""
        if field not in _GROUPABLE_FIELDS:
            raise ValueError(f"unsupported group field: {field}")

        await self.initialize()
        query = query or EventQuery()
        where_sql, params = self._build_where_clause(query)
        group_where = f"{where_sql} AND {field} IS NOT NULL" if where_sql else f"WHERE {field} IS NOT NULL"
        sql = f"""
            SELECT {field} AS group_key, COUNT(*) AS total
            FROM events
            {group_where}
            GROUP BY {field}
            ORDER BY total DESC, group_key ASC
        """

        rows = await self._fetch_rows(sql, params)
        return {
            str(row["group_key"]): int(row["total"])
            for row in rows
            if row["group_key"] not in (None, "")
        }

    async def count_events(self, query: EventQuery | None = None) -> int:
        """Count events matching the provided filters."""
        await self.initialize()
        query = query or EventQuery()
        where_sql, params = self._build_where_clause(query)
        sql = f"SELECT COUNT(*) AS total FROM events {where_sql}"
        rows = await self._fetch_rows(sql, params)
        return int(rows[0]["total"]) if rows else 0

    def _event_insert_params(self, data: dict[str, Any]) -> tuple[Any, ...]:
        return (
            data["event_id"],
            data["game_id"],
            data["event_type"],
            data["phase"],
            json.dumps(data["visibility"], ensure_ascii=False),
            data.get("actor"),
            data.get("action_type"),
            data.get("system_name"),
            json.dumps(data["payload"], ensure_ascii=False),
            data["timestamp"],
            data.get("sequence_num", 0),
            data["version"],
        )

    def _build_where_clause(self, query: EventQuery) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if query.game_id is not None:
            clauses.append("game_id = ?")
            params.append(query.game_id)
        if query.after_timestamp is not None:
            clauses.append("timestamp > ?")
            params.append(query.after_timestamp)
        if query.event_type is not None:
            clauses.append("event_type = ?")
            params.append(query.event_type)
        if query.phase is not None:
            clauses.append("phase = ?")
            params.append(query.phase)
        if query.actor is not None:
            clauses.append("actor = ?")
            params.append(query.actor)
        if query.system_name is not None:
            clauses.append("system_name = ?")
            params.append(query.system_name)
        if query.visibility_scope is not None:
            clauses.append(
                """
                (
                    'all' IN (SELECT value FROM json_each(visibility))
                    OR ? IN (SELECT value FROM json_each(visibility))
                )
                """.strip()
            )
            params.append(query.visibility_scope)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where_sql, params

    async def _fetch_rows(self, sql: str, params: list[Any] | tuple[Any, ...]) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            return await cursor.fetchall()

    def _serialize_event(self, event: EventBase) -> dict[str, Any]:
        data = event.model_dump()

        if hasattr(event, "phase") and hasattr(event.phase, "value"):
            data["phase"] = event.phase.value

        if hasattr(event, "action_type") and hasattr(event.action_type, "value"):
            data["action_type"] = event.action_type.value

        return data

    def _deserialize_event(self, data: dict[str, Any]) -> EventBase:
        event_type = str(data.get("event_type", ""))
        event_cls = _EVENT_TYPE_MAP.get(event_type, EventBase)

        if "phase" in data and isinstance(data["phase"], str):
            try:
                data["phase"] = GamePhase(data["phase"])
            except ValueError:
                pass

        if "action_type" in data and isinstance(data["action_type"], str):
            try:
                data["action_type"] = ActionType(data["action_type"])
            except ValueError:
                pass

        return event_cls.model_validate(data)

    def _row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        row_dict = dict(row)
        visibility = row_dict.get("visibility")
        payload = row_dict.get("payload")
        row_dict["visibility"] = json.loads(visibility) if visibility else []
        row_dict["payload"] = json.loads(payload) if payload else {}
        return row_dict


class GlobalEventStore(AsyncEventStore):
    """Game-wide event store with game-oriented query helpers."""

    async def get_events_by_game_id(self, game_id: str) -> list[EventBase]:
        return await self.query_events(EventQuery(game_id=game_id))

    async def get_events_by_type(self, event_type: str) -> list[EventBase]:
        return await self.query_events(EventQuery(event_type=event_type))

    async def get_events_by_phase(self, game_phase: str) -> list[EventBase]:
        return await self.query_events(EventQuery(phase=game_phase))

    async def list_game_ids(self) -> list[str]:
        """Return known game ids ordered by latest activity first."""
        await self.initialize()
        rows = await self._fetch_rows(
            """
            SELECT game_id
            FROM events
            GROUP BY game_id
            ORDER BY MAX(timestamp) DESC, MAX(sequence_num) DESC, MAX(id) DESC
            """,
            [],
        )
        return [str(row["game_id"]) for row in rows]

    async def has_game(self, game_id: str) -> bool:
        """Return whether the store contains the given game id."""
        return await self.count_events(EventQuery(game_id=game_id, limit=None)) > 0

    async def query_game_events(
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
        """Query one game's events with optional filters."""
        return await self.query_events(
            EventQuery(
                game_id=game_id,
                after_timestamp=after_timestamp,
                event_type=event_type,
                phase=phase,
                actor=actor,
                system_name=system_name,
                visibility_scope=visibility_scope,
                limit=limit,
            )
        )

    async def get_events_after_timestamp(
        self,
        game_id: str,
        after_timestamp: int,
        limit: int = 100,
        *,
        event_type: str | None = None,
        phase: str | None = None,
        actor: str | None = None,
        system_name: str | None = None,
        visibility_scope: str | None = None,
    ) -> list[EventBase]:
        """Return later events for a single game."""
        return await self.query_game_events(
            game_id,
            after_timestamp=after_timestamp,
            event_type=event_type,
            phase=phase,
            actor=actor,
            system_name=system_name,
            visibility_scope=visibility_scope,
            limit=limit,
        )

    async def get_game_statistics(
        self,
        game_id: str,
        *,
        visibility_scope: str | None = None,
    ) -> GameEventStats:
        """Return aggregate statistics for one game."""
        base_query = EventQuery(game_id=game_id, visibility_scope=visibility_scope)
        total_events = await self.count_events(base_query)
        if total_events == 0:
            return GameEventStats(game_id=game_id)

        where_sql, params = self._build_where_clause(base_query)
        range_rows = await self._fetch_rows(
            f"""
            SELECT
                MIN(timestamp) AS first_seq,
                MAX(timestamp) AS last_seq
            FROM events
            {where_sql}
            """,
            params,
        )
        first_seq = int(range_rows[0]["first_seq"] or 0)
        last_seq = int(range_rows[0]["last_seq"] or 0)

        return GameEventStats(
            game_id=game_id,
            total_events=total_events,
            first_seq=first_seq,
            last_seq=last_seq,
            counts_by_type=await self.count_grouped_by("event_type", base_query),
            counts_by_phase=await self.count_grouped_by("phase", base_query),
            counts_by_system_name=await self.count_grouped_by("system_name", base_query),
            counts_by_actor=await self.count_grouped_by("actor", base_query),
        )


__all__ = ["AsyncEventStore", "EventQuery", "GameEventStats", "GlobalEventStore"]
