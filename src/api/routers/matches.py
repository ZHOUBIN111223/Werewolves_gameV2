from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.schemas.event import EventDTO, EventListResponse
from src.api.schemas.match import MatchListResponse, MatchSnapshotResponse
from src.api.services.observer_service import MatchNotFoundError, ObserverService

router = APIRouter(prefix="/api/matches", tags=["matches"])

_observer_service = ObserverService()


def get_observer_service() -> ObserverService:
    return _observer_service


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
        raise HTTPException(status_code=404, detail=f"match not found: {exc}") from exc


@router.get("/{match_id}/timeline", response_model=list[EventDTO])
async def get_match_timeline(
    match_id: str,
    service: ObserverService = Depends(get_observer_service),
) -> list[EventDTO]:
    try:
        return await service.get_timeline(match_id)
    except MatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"match not found: {exc}") from exc


@router.get("/{match_id}/events", response_model=EventListResponse)
async def get_match_events(
    match_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: ObserverService = Depends(get_observer_service),
) -> EventListResponse:
    try:
        return await service.get_events_after(match_id, after_seq=after_seq, limit=limit)
    except MatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"match not found: {exc}") from exc
