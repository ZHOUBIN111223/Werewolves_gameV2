"""Observer API 的对局数据模型（DTO）。"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from src.api.schemas.event import EventDTO


class MatchDTO(BaseModel):
    """对局元信息（状态、阶段等）。"""

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
    """玩家视图（用于观战展示）。"""

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
    """对局快照：对局信息 + 玩家列表 + 最近事件。"""

    match: MatchDTO
    players: List[PlayerDTO] = Field(default_factory=list)
    recent_events: List[EventDTO] = Field(default_factory=list)


class MatchListItem(BaseModel):
    """对局列表中的单条记录（轻量）。"""

    match_id: str
    phase: str
    status: str
    winner: Optional[str] = None
    last_seq: int = 0


class MatchListResponse(BaseModel):
    """对局列表响应。"""

    items: List[MatchListItem] = Field(default_factory=list)
