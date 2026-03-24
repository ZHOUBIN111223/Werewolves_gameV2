from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from src.api.schemas.event import EventDTO


class MatchDTO(BaseModel):
    match_id: str
    status: str
    phase: str
    current_subphase: Optional[str] = None
    alive_players_count: int = 0
    total_players: int = 0
    current_speaker: Optional[str] = None
    focus_target: Optional[str] = None
    winner: Optional[str] = None
    game_ended: bool = False


class PlayerDTO(BaseModel):
    id: str
    seat_no: int
    name: str
    alive: bool
    role: Optional[str] = None
    camp: Optional[str] = None
    suspicion: float = 0.0
    vote_target: Optional[str] = None
    is_speaking: bool = False
    accent: Optional[str] = None


class MatchSnapshotResponse(BaseModel):
    match: MatchDTO
    players: List[PlayerDTO] = Field(default_factory=list)
    recent_events: List[EventDTO] = Field(default_factory=list)


class MatchListItem(BaseModel):
    match_id: str
    phase: str
    status: str
    winner: Optional[str] = None
    last_seq: int = 0


class MatchListResponse(BaseModel):
    items: List[MatchListItem] = Field(default_factory=list)
