"""异步事件存储实现，基于SQLite数据库。"""
import aiosqlite
import asyncio
from pathlib import Path
from typing import Iterable, List, Dict, Any, Optional
from contextlib import asynccontextmanager
import json
from datetime import datetime

from .action import Action
from .event import EventBase
from .observation import Observation
from .system_event import SystemEvent
from src.enums import ActionType, GamePhase


_EVENT_TYPE_MAP = {
    "action": Action,
    "observation": Observation,
    "system": SystemEvent,
}


class AsyncEventStore:
    """异步事件存储器，基于SQLite数据库实现高性能存储和查询。"""

    def __init__(self, db_path: str | Path) -> None:
        """创建异步事件存储，并记录数据库路径。"""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self) -> None:
        """初始化数据库表结构并设置WAL模式"""
        if not self._initialized:
            async with aiosqlite.connect(self.db_path) as db:
                # 设置WAL模式以提高并发性能
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
                await db.execute("PRAGMA cache_size=1000")
                await db.execute("PRAGMA temp_store=memory")

                # 创建events表
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE NOT NULL,
                        game_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        phase TEXT NOT NULL,
                        visibility TEXT NOT NULL,
                        actor TEXT,
                        action_type TEXT,
                        system_name TEXT,
                        payload TEXT NOT NULL,
                        timestamp INTEGER NOT NULL,
                        sequence_num INTEGER DEFAULT 0,
                        version INTEGER DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # 检查是否存在sequence_num列，如果不存在则添加（以防旧版本数据库）
                cursor = await db.execute("PRAGMA table_info(events)")
                columns = [column[1] for column in await cursor.fetchall()]
                if 'sequence_num' not in columns:
                    await db.execute("ALTER TABLE events ADD COLUMN sequence_num INTEGER DEFAULT 0")

                # 创建索引
                await db.execute("CREATE INDEX IF NOT EXISTS idx_events_game_id ON events(game_id)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_events_phase ON events(phase)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_events_sequence ON events(sequence_num)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_events_event_id ON events(event_id)")

                await db.commit()
            self._initialized = True

    async def __aenter__(self):
        if not self._initialized:
            await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # 自动清理资源
        pass

    async def append(self, event: EventBase) -> None:
        """异步添加单个事件"""
        if not self._initialized:
            await self.initialize()

        serialized_event = self._serialize_event(event)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO events
                (event_id, game_id, event_type, phase, visibility, actor, action_type, system_name, payload, timestamp, sequence_num, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    serialized_event["event_id"],
                    serialized_event["game_id"],
                    serialized_event["event_type"],
                    serialized_event["phase"],
                    json.dumps(serialized_event["visibility"]),
                    serialized_event.get("actor"),
                    serialized_event.get("action_type"),
                    serialized_event.get("system_name"),  # 新增 system_name 字段
                    json.dumps(serialized_event["payload"]),
                    serialized_event["timestamp"],  # 使用整数时间戳
                    serialized_event.get("sequence_num", 0),  # 新增序列号
                    serialized_event["version"]
                )
            )
            await db.commit()

    async def append_many(self, events: Iterable[EventBase]) -> None:
        """批量异步添加事件"""
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                for event in events:
                    serialized_event = self._serialize_event(event)
                    await db.execute(
                        """
                        INSERT INTO events
                        (event_id, game_id, event_type, phase, visibility, actor, action_type, system_name, payload, timestamp, sequence_num, version)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            serialized_event["event_id"],
                            serialized_event["game_id"],
                            serialized_event["event_type"],
                            serialized_event["phase"],
                            json.dumps(serialized_event["visibility"]),
                            serialized_event.get("actor"),
                            serialized_event.get("action_type"),
                            serialized_event.get("system_name"),  # 新增 system_name 字段
                            json.dumps(serialized_event["payload"]),
                            serialized_event["timestamp"],  # 使用整数时间戳
                            serialized_event.get("sequence_num", 0),  # 新增序列号
                            serialized_event["version"]
                        )
                    )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def read_all(self) -> list[EventBase]:
        """读取所有事件"""
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT * FROM events ORDER BY timestamp ASC, sequence_num ASC, id ASC")
            rows = await cursor.fetchall()

        events = []
        for row in rows:
            event_dict = self._row_to_dict(row)
            events.append(self._deserialize_event(event_dict))
        return events

    async def filter_by_visibility(self, audience: str) -> list[EventBase]:
        """按可见性过滤事件"""
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            # 使用 SQLite 的 json 函数进行精确匹配
            cursor = await db.execute(
                """
                SELECT * FROM events
                WHERE ('all' IN (SELECT value FROM json_each(visibility)))
                   OR (? IN (SELECT value FROM json_each(visibility)))
                ORDER BY timestamp ASC, sequence_num ASC, id ASC
                """,
                (audience,)
            )
            rows = await cursor.fetchall()

        events = []
        for row in rows:
            event_dict = self._row_to_dict(row)
            events.append(self._deserialize_event(event_dict))
        return events

    def _serialize_event(self, event: EventBase) -> dict[str, Any]:
        """序列化事件对象"""
        data = event.model_dump()

        # 将枚举转换为字符串值以便JSON序列化
        if hasattr(event, 'phase') and hasattr(event.phase, 'value'):
            data['phase'] = event.phase.value

        if hasattr(event, 'action_type') and hasattr(event.action_type, 'value'):
            data['action_type'] = event.action_type.value

        return data

    def _deserialize_event(self, data: dict[str, Any]) -> EventBase:
        """反序列化事件对象"""
        event_type = str(data.get("event_type", ""))
        event_cls = _EVENT_TYPE_MAP.get(event_type, EventBase)

        # 将字符串值转换回枚举实例
        if 'phase' in data and isinstance(data['phase'], str):
            try:
                data['phase'] = GamePhase(data['phase'])
            except ValueError:
                pass

        if 'action_type' in data and isinstance(data['action_type'], str):
            try:
                data['action_type'] = ActionType(data['action_type'])
            except ValueError:
                pass

        if event_type == "action" and issubclass(event_cls, Action):
            if 'action_type' in data and isinstance(data['action_type'], str):
                try:
                    data['action_type'] = ActionType(data['action_type'])
                except ValueError:
                    pass

        return event_cls.model_validate(data)

    def _row_to_dict(self, row) -> dict[str, Any]:
        """将数据库行转换为字典"""
        columns = [
            'id', 'event_id', 'game_id', 'event_type', 'phase',
            'visibility', 'actor', 'action_type', 'system_name', 'payload', 'timestamp', 'sequence_num', 'version', 'created_at'
        ]
        row_dict = dict(zip(columns, row))

        # 反序列化JSON字段
        row_dict['visibility'] = json.loads(row_dict['visibility'])

        # 只有当 payload 存在且非空时才反序列化
        if row_dict['payload']:
            row_dict['payload'] = json.loads(row_dict['payload'])
        else:
            row_dict['payload'] = {}

        return row_dict


class GlobalEventStore(AsyncEventStore):
    """控制器专用的全局事件时间线存储"""

    async def get_events_by_game_id(self, game_id: str) -> list[EventBase]:
        """按游戏ID获取事件"""
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM events WHERE game_id = ? ORDER BY timestamp ASC, sequence_num ASC, id ASC",
                (game_id,)
            )
            rows = await cursor.fetchall()

        events = []
        for row in rows:
            event_dict = self._row_to_dict(row)
            events.append(self._deserialize_event(event_dict))
        return events

    async def get_events_by_type(self, event_type: str) -> list[EventBase]:
        """按事件类型获取事件"""
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM events WHERE event_type = ? ORDER BY timestamp ASC, sequence_num ASC, id ASC",
                (event_type,)
            )
            rows = await cursor.fetchall()

        events = []
        for row in rows:
            event_dict = self._row_to_dict(row)
            events.append(self._deserialize_event(event_dict))
        return events

    async def get_events_by_phase(self, game_phase: str) -> list[EventBase]:
        """按游戏阶段获取事件"""
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM events WHERE phase = ? ORDER BY timestamp ASC, sequence_num ASC, id ASC",
                (game_phase,)
            )
            rows = await cursor.fetchall()

        events = []
        for row in rows:
            event_dict = self._row_to_dict(row)
            events.append(self._deserialize_event(event_dict))
        return events

    async def list_game_ids(self) -> list[str]:
        """Return known game ids ordered by latest activity first."""
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT game_id
                FROM events
                GROUP BY game_id
                ORDER BY MAX(timestamp) DESC, MAX(sequence_num) DESC, MAX(id) DESC
                """
            )
            rows = await cursor.fetchall()

        return [row[0] for row in rows]

    async def get_events_after_timestamp(
        self,
        game_id: str,
        after_timestamp: int,
        limit: int = 100,
    ) -> list[EventBase]:
        """Return later events for a single game."""
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM events
                WHERE game_id = ?
                  AND timestamp > ?
                ORDER BY timestamp ASC, sequence_num ASC, id ASC
                LIMIT ?
                """,
                (game_id, after_timestamp, limit),
            )
            rows = await cursor.fetchall()

        events = []
        for row in rows:
            event_dict = self._row_to_dict(row)
            events.append(self._deserialize_event(event_dict))
        return events
