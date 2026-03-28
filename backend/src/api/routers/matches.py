"""HTTP routes for observer-facing match queries."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.schemas.event import EventDTO, EventListResponse
from src.api.schemas.match import MatchListResponse, MatchSnapshotResponse, MatchStatsResponse
from src.api.services.observer_service import MatchNotFoundError, ObserverService


router = APIRouter(prefix="/api/matches", tags=["matches"])
_observer_service = ObserverService()


def get_observer_service() -> ObserverService:
    return _observer_service


def _raise_not_found(exc: MatchNotFoundError) -> None:
    raise HTTPException(status_code=404, detail=f"match not found: {exc}") from exc


@router.get("", response_model=MatchListResponse)
async def list_matches(service: ObserverService = Depends(get_observer_service)) -> MatchListResponse:
    return await service.list_matches()


@router.get("/{match_id}", response_model=MatchSnapshotResponse)
async def get_match_snapshot(
    match_id: str,
    recent_limit: int = Query(default=20, ge=1, le=100),
    service: ObserverService = Depends(get_observer_service),
) -> MatchSnapshotResponse:
    try:
        return await service.get_match_snapshot(match_id, recent_limit=recent_limit)
    except MatchNotFoundError as exc:
        _raise_not_found(exc)


@router.get("/{match_id}/timeline", response_model=list[EventDTO])
async def get_match_timeline(
    match_id: str,
    event_type: str | None = Query(default=None),
    phase: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    system_name: str | None = Query(default=None),
    visible_to: str | None = Query(default=None),
    service: ObserverService = Depends(get_observer_service),
) -> list[EventDTO]:
    """Return a match timeline, optionally filtered by common event fields."""
    try:
        return await service.get_timeline(
            match_id,
            event_type=event_type,
            phase=phase,
            actor=actor,
            system_name=system_name,
            visible_to=visible_to,
        )
    except MatchNotFoundError as exc:
        _raise_not_found(exc)


@router.get("/{match_id}/events", response_model=EventListResponse)
async def get_match_events(
    match_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    event_type: str | None = Query(default=None),
    phase: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    system_name: str | None = Query(default=None),
    visible_to: str | None = Query(default=None),
    service: ObserverService = Depends(get_observer_service),
) -> EventListResponse:
    """Return incremental match events with optional server-side filters."""
    try:
        return await service.get_events_after(
            match_id,
            after_seq=after_seq,
            limit=limit,
            event_type=event_type,
            phase=phase,
            actor=actor,
            system_name=system_name,
            visible_to=visible_to,
        )
    except MatchNotFoundError as exc:
        _raise_not_found(exc)


@router.get("/{match_id}/stats", response_model=MatchStatsResponse)
async def get_match_stats(
    match_id: str,
    visible_to: str | None = Query(default=None),
    service: ObserverService = Depends(get_observer_service),
) -> MatchStatsResponse:
    """Return aggregate event statistics for one match."""
    try:
        return await service.get_match_stats(match_id, visible_to=visible_to)
    except MatchNotFoundError as exc:
        _raise_not_found(exc)
