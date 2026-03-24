"""事件存储实现。提供同步和异步存储选项。"""
import asyncio
import warnings
from pathlib import Path
from typing import Iterable, List

from .action import Action
from .event import EventBase
from .observation import Observation
from .system_event import SystemEvent

# 导入异步版本的存储类
from .async_store import AsyncEventStore as BaseAsyncEventStore, GlobalEventStore as BaseGlobalEventStore


def get_async_store(db_path: str | Path) -> BaseGlobalEventStore:
    """获取异步事件存储实例，推荐在多智能体高并发场景下使用"""
    return BaseGlobalEventStore(db_path)


class SyncEventStoreWrapper:
    """同步事件存储包装器，使用 asyncio.run 来包装异步存储操作以实现向后兼容。"""

    def __init__(self, file_path: str | Path) -> None:
        # 将旧的 JSON 文件路径改为新的数据库路径
        db_path = Path(file_path).with_suffix('.db')
        self._async_store = BaseAsyncEventStore(db_path)
        # 立即初始化数据库
        asyncio.run(self._async_store.initialize())

    def append(self, event: EventBase) -> None:
        """同步追加事件"""
        asyncio.run(self._async_store.append(event))

    def append_many(self, events: Iterable[EventBase]) -> None:
        """同步批量追加事件"""
        asyncio.run(self._async_store.append_many(events))

    def read_all(self) -> list[EventBase]:
        """同步读取所有事件"""
        return asyncio.run(self._async_store.read_all())

    def filter_by_visibility(self, audience: str) -> list[EventBase]:
        """同步按可见性过滤事件"""
        return asyncio.run(self._async_store.filter_by_visibility(audience))


# 保持旧的类名以实现向后兼容
class EventStore(SyncEventStoreWrapper):
    """已弃用：旧版同步事件存储器的向后兼容包装器。内部使用异步存储。"""
    pass


class GlobalEventStore(SyncEventStoreWrapper):
    """控制器专用的全局事件时间线存储的向后兼容包装器。内部使用异步存储。"""

    def __init__(self, file_path: str | Path) -> None:
        # 将旧的 JSON 文件路径改为新的数据库路径
        db_path = Path(file_path).with_suffix('.db')
        self._async_store = BaseGlobalEventStore(db_path)
        # 立即初始化数据库
        asyncio.run(self._async_store.initialize())

    def get_events_by_game_id(self, game_id: str) -> list[EventBase]:
        """按游戏ID获取事件"""
        return asyncio.run(self._async_store.get_events_by_game_id(game_id))

    def get_events_by_type(self, event_type: str) -> list[EventBase]:
        """按事件类型获取事件"""
        return asyncio.run(self._async_store.get_events_by_type(event_type))

    def get_events_by_phase(self, game_phase: str) -> list[EventBase]:
        """按游戏阶段获取事件"""
        return asyncio.run(self._async_store.get_events_by_phase(game_phase))


__all__ = ["get_async_store", "EventStore", "SyncEventStoreWrapper", "GlobalEventStore", "BaseAsyncEventStore", "BaseGlobalEventStore"]