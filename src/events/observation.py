"""Agent 可见观察事件定义。"""

from __future__ import annotations

from typing import Any
from pydantic import Field

from .event import EventBase


class Observation(EventBase):
    """表示 Controller 裁剪后发给 Agent 的观察事件。"""

    observer: str = Field("", description="观察者")
    source_event_id: str = Field("", description="源事件ID")

    # Override the event_type to "observation"
    event_type: str = Field(default="observation", description="事件类型")

    @classmethod
    def from_event(cls, event: EventBase, observer: str, payload: dict[str, Any] | None = None) -> "Observation":
        """基于全局事件派生指定 Agent 可见的观察事件。"""
        return cls(
            game_id=event.game_id,
            phase=event.phase,
            visibility=[observer],
            payload=payload or dict(event.payload),
            observer=observer,
            source_event_id=event.event_id,
        )
