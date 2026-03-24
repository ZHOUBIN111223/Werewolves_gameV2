from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EventDTO(BaseModel):
    event_id: str
    match_id: str
    seq: int
    type: str
    phase: str
    visibility: List[str] = Field(default_factory=list)
    ts: int
    payload: Dict[str, Any] = Field(default_factory=dict)
    actor: Optional[str] = None
    action_type: Optional[str] = None
    system_name: Optional[str] = None


class EventListResponse(BaseModel):
    match_id: str
    next_seq: int
    has_more: bool
    events: List[EventDTO] = Field(default_factory=list)
