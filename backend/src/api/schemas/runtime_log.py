"""Schemas for frontend runtime log ingestion and inspection."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FrontendLogIn(BaseModel):
    """Payload sent by the frontend runtime logger."""

    level: str = Field(min_length=1, max_length=16)
    scope: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    session_id: str = Field(min_length=1, max_length=80)
    href: str | None = Field(default=None, max_length=1000)
    user_agent: str | None = Field(default=None, max_length=1000)
    client_time: datetime | None = None
    context: Any = Field(default_factory=dict)


class FrontendLogRecord(FrontendLogIn):
    """Stored runtime log record."""

    id: str
    server_time: datetime


class FrontendLogWriteResponse(BaseModel):
    """Result returned after writing one runtime log."""

    ok: bool = True
    id: str
    path: str


class FrontendLogTailResponse(BaseModel):
    """Tail response for recently stored runtime logs."""

    path: str
    items: list[FrontendLogRecord] = Field(default_factory=list)
