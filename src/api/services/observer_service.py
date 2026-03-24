from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from config import AppConfig
from src.api.schemas.event import EventDTO, EventListResponse
from src.api.schemas.match import (
    MatchDTO,
    MatchListItem,
    MatchListResponse,
    MatchSnapshotResponse,
    PlayerDTO,
)
from src.events.async_store import GlobalEventStore
from src.events.event import EventBase


class MatchNotFoundError(Exception):
    pass


class ObserverService:
    """Read-only adapter from stored events to frontend-facing DTOs."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        base_path = Path(db_path) if db_path is not None else Path(AppConfig.STORE_PATH) / "global_events.db"
        self._store = GlobalEventStore(base_path)

    async def list_matches(self) -> MatchListResponse:
        items: List[MatchListItem] = []
        for game_id in await self._store.list_game_ids():
            events = await self._store.get_events_by_game_id(game_id)
            if not events:
                continue
            match = self._build_match_dto(game_id, events)
            items.append(
                MatchListItem(
                    match_id=match.match_id,
                    phase=match.phase,
                    status=match.status,
                    winner=match.winner,
                    last_seq=events[-1].timestamp,
                )
            )
        return MatchListResponse(items=items)

    async def get_match_snapshot(self, match_id: str, recent_limit: int = 20) -> MatchSnapshotResponse:
        events = await self._store.get_events_by_game_id(match_id)
        if not events:
            raise MatchNotFoundError(match_id)

        match = self._build_match_dto(match_id, events)
        players = self._build_players(events)
        recent_events = [self._to_event_dto(event) for event in events[-recent_limit:]]
        return MatchSnapshotResponse(match=match, players=players, recent_events=recent_events)

    async def get_timeline(self, match_id: str) -> List[EventDTO]:
        events = await self._store.get_events_by_game_id(match_id)
        if not events:
            raise MatchNotFoundError(match_id)
        return [self._to_event_dto(event) for event in events]

    async def get_events_after(self, match_id: str, after_seq: int, limit: int = 100) -> EventListResponse:
        events = await self._store.get_events_after_timestamp(match_id, after_seq, limit=limit + 1)
        if not events:
            all_events = await self._store.get_events_by_game_id(match_id)
            if not all_events:
                raise MatchNotFoundError(match_id)
        has_more = len(events) > limit
        sliced = events[:limit]
        next_seq = sliced[-1].timestamp if sliced else after_seq
        return EventListResponse(
            match_id=match_id,
            next_seq=next_seq,
            has_more=has_more,
            events=[self._to_event_dto(event) for event in sliced],
        )

    def _build_match_dto(self, match_id: str, events: Iterable[EventBase]) -> MatchDTO:
        events = list(events)
        last_event = events[-1]
        payloads = [event.payload for event in events if isinstance(event.payload, dict)]

        game_ended = any(self._is_system(event, "game_ended") for event in events)
        winner = self._find_winner(events)
        current_speaker = self._find_last_payload_value(events, "speaker")
        focus_target = self._find_focus_target(events)
        current_subphase = self._find_last_payload_value(events, "subphase")
        alive_players = self._find_last_alive_players(events)
        total_players = len(self._find_player_order(events))

        return MatchDTO(
            match_id=match_id,
            status="finished" if game_ended else "running",
            phase=str(getattr(last_event.phase, "value", last_event.phase)),
            current_subphase=current_subphase,
            alive_players_count=len(alive_players),
            total_players=total_players,
            current_speaker=current_speaker,
            focus_target=focus_target,
            winner=winner,
            game_ended=game_ended,
        )

    def _build_players(self, events: Iterable[EventBase]) -> List[PlayerDTO]:
        event_list = list(events)
        player_order = self._find_player_order(event_list)
        alive_players = set(self._find_last_alive_players(event_list))
        vote_targets = self._find_vote_targets(event_list)
        current_speaker = self._find_last_payload_value(event_list, "speaker")

        players: List[PlayerDTO] = []
        for index, player_id in enumerate(player_order, start=1):
            players.append(
                PlayerDTO(
                    id=player_id,
                    seat_no=index,
                    name=player_id,
                    alive=player_id in alive_players,
                    vote_target=vote_targets.get(player_id),
                    is_speaking=player_id == current_speaker,
                )
            )
        return players

    def _find_player_order(self, events: Iterable[EventBase]) -> List[str]:
        for event in events:
            if self._is_system(event, "game_started"):
                players = event.payload.get("players", [])
                if isinstance(players, list):
                    return [str(player_id) for player_id in players]
        return []

    def _find_last_alive_players(self, events: Iterable[EventBase]) -> List[str]:
        player_order = self._find_player_order(events)
        alive = list(player_order)
        for event in events:
            if self._is_system(event, "player_eliminated"):
                eliminated = event.payload.get("eliminated_player")
                if eliminated in alive:
                    alive.remove(eliminated)
        return alive

    def _find_vote_targets(self, events: Iterable[EventBase]) -> Dict[str, str]:
        vote_targets: Dict[str, str] = {}
        for event in events:
            if self._is_system(event, "vote_recorded"):
                voter = event.payload.get("voter")
                target = event.payload.get("target")
                if voter and target:
                    vote_targets[str(voter)] = str(target)
            elif self._is_system(event, "phase_advanced"):
                previous_phase = str(event.payload.get("previous_phase", ""))
                if previous_phase.startswith("day_"):
                    vote_targets = {}
        return vote_targets

    def _find_focus_target(self, events: Iterable[EventBase]) -> Optional[str]:
        for event in reversed(list(events)):
            if self._is_system(event, "vote_recorded"):
                target = event.payload.get("target")
                if target:
                    return str(target)
            if self._is_system(event, "player_eliminated"):
                target = event.payload.get("eliminated_player")
                if target:
                    return str(target)
        return None

    def _find_winner(self, events: Iterable[EventBase]) -> Optional[str]:
        for event in reversed(list(events)):
            if self._is_system(event, "game_ended"):
                winner = event.payload.get("winner")
                if winner:
                    return str(winner)
        return None

    def _find_last_payload_value(self, events: Iterable[EventBase], key: str) -> Optional[str]:
        for event in reversed(list(events)):
            value = event.payload.get(key) if isinstance(event.payload, dict) else None
            if value not in (None, ""):
                return str(value)
        return None

    def _is_system(self, event: EventBase, system_name: str) -> bool:
        return event.event_type == "system" and event.payload is not None and getattr(event, "system_name", None) == system_name

    def _to_event_dto(self, event: EventBase) -> EventDTO:
        data: Dict[str, Any] = event.model_dump()
        return EventDTO(
            event_id=str(data["event_id"]),
            match_id=str(data["game_id"]),
            seq=int(data["timestamp"]),
            type=str(data["event_type"]),
            phase=str(data["phase"]),
            visibility=[str(item) for item in data.get("visibility", [])],
            ts=int(data["timestamp"]),
            payload=data.get("payload", {}) or {},
            actor=data.get("actor"),
            action_type=data.get("action_type"),
            system_name=data.get("system_name"),
        )
