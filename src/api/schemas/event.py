"""Observer API 的事件数据模型（DTO）。

该文件定义了 API 返回给前端/调用方的事件结构（与内部 EventBase 结构保持兼容，
但字段命名与类型更偏向序列化与展示）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EventDTO(BaseModel):
    """单条事件（对外展示用）。"""

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
    """增量事件查询响应。"""

    match_id: str
    next_seq: int
    has_more: bool
    events: List[EventDTO] = Field(default_factory=list)
