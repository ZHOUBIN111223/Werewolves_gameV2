"""全局事件抽象定义。"""

from __future__ import annotations

from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator
from pydantic.config import ConfigDict
import json
import time
from threading import Lock

from src.enums import GamePhase

# 全局序列计数器锁，确保序列号生成的原子性
_global_sequence_lock = Lock()
_global_sequence_counter = 0


def generate_monotonic_timestamp():
    """
    生成单调递增的时间戳，确保严格排序
    使用纳秒级精度的时间戳，并结合全局序列计数器避免重复
    """
    global _global_sequence_counter

    # 获取纳秒级时间戳
    timestamp_ns = time.time_ns()

    # 加锁确保序列计数器的原子更新
    with _global_sequence_lock:
        if timestamp_ns <= _global_sequence_counter:
            # 如果当前时间戳不大于之前的计数器值，则递增计数器
            _global_sequence_counter += 1
        else:
            # 否则，将计数器重置为当前时间戳
            _global_sequence_counter = timestamp_ns

        return _global_sequence_counter


class EventBase(BaseModel):
    """基础事件模型，使用Pydantic提供严格类型验证"""

    # Configure Pydantic to serialize enums to their values
    model_config = ConfigDict(
        # Use alias generator to convert enum values during serialization
        arbitrary_types_allowed=True,
        json_encoders={datetime: lambda v: v.isoformat()}
    )

    game_id: str = Field(..., description="游戏ID")
    phase: GamePhase = Field(..., description="当前游戏阶段")
    visibility: List[str] = Field(..., description="可见性列表")
    payload: Dict[str, Any] = Field(default_factory=dict, description="事件载荷")
    event_type: str = Field(..., description="事件类型")
    event_id: str = Field(default_factory=lambda: str(uuid4()), description="事件唯一ID")
    timestamp: int = Field(default_factory=generate_monotonic_timestamp, description="单调时间戳，用于严格排序")
    sequence_num: int = Field(default_factory=lambda: int(time.time_ns()) % 1000000, description="序列号，用于打破时间戳平局")
    version: int = Field(1, description="版本号")

    @field_validator('game_id')
    def validate_game_id(cls, v: str) -> str:
        """校验 game_id 非空并去除首尾空白。"""
        if not v or not v.strip():
            raise ValueError('game_id 不能为空')
        return v.strip()

    @field_validator('visibility')
    def validate_visibility(cls, v: List[str]) -> List[str]:
        """校验 visibility 为字符串列表。"""
        if not isinstance(v, list):
            raise ValueError('visibility 必须是字符串列表')
        return v

    @field_validator('payload')
    def validate_payload(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """校验 payload 为字典结构。"""
        if not isinstance(v, dict):
            raise ValueError('payload 必须是字典')
        return v

    def model_dump(self, *args, **kwargs) -> dict[str, Any]:
        """Custom model_dump to properly serialize enums and datetime."""
        # Enable serialization of non-serializable types
        kwargs.setdefault("mode", "python")
        kwargs.setdefault("by_alias", True)
        result = super().model_dump(*args, **kwargs)

        # Ensure enums are serialized as their values
        if 'phase' in result and hasattr(result['phase'], 'value'):
            result['phase'] = result['phase'].value

        if 'action_type' in result and hasattr(result['action_type'], 'value'):
            result['action_type'] = result['action_type'].value

        # Ensure datetime is serialized as ISO string, but for our integer timestamp, we just keep the integer
        if 'timestamp' in result and isinstance(result['timestamp'], int):
            # Keep the integer timestamp as-is for monotonic sorting
            pass  # We don't need to convert the monotonic integer timestamp
        elif 'timestamp' in result and isinstance(result['timestamp'], datetime):
            result['timestamp'] = result['timestamp'].isoformat()

        return result
