"""Structured agent action event."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic.config import ConfigDict

from .event import EventBase
from src.enums import ActionType


class Action(EventBase):
    """Structured action emitted by an agent and consumed by the controller."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    actor: str = Field("", description="The player performing the action")
    action_type: ActionType = Field(..., description="The action type")
    target: str = Field("", description="Target player id")
    reasoning_summary: str = Field("", description="Private reasoning summary")
    public_speech: str = Field("", description="Public speech content for speak actions")
    event_type: str = Field(default="action", description="Event type")

    @field_validator("actor", "action_type")
    @classmethod
    def validate_required_fields(cls, value):
        """确保关键字段不为空（Pydantic 字段校验）。"""
        if not value:
            raise ValueError("required action field cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_action_for_phase(self):
        """对 Action 与 phase 的组合进行额外约束校验。"""
        if "day" in str(self.phase).lower() and self.action_type == ActionType.SKIP:
            raise ValueError("day phase does not allow skip actions")
        return self

    def model_dump(self, *args, **kwargs) -> dict[str, Any]:
        """序列化为 dict，并确保枚举字段输出为字符串值。"""
        result = super().model_dump(*args, **kwargs)
        if "action_type" in result and hasattr(result["action_type"], "value"):
            result["action_type"] = result["action_type"].value
        return result
