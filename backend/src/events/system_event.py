"""系统事件定义。"""

from __future__ import annotations

from pydantic import Field

from .event import EventBase


class SystemEvent(EventBase):
    """表示 Controller 侧的系统状态事件。"""

    system_name: str = Field("controller", description="系统组件名称")

    # Override the event_type to "system"
    event_type: str = Field(default="system", description="事件类型")
