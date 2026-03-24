"""Agent 私有记忆存储。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class MemoryItem:
    """描述 Agent 的单条私有记忆。"""

    memory_type: str
    content: str
    game_id: str
    phase: str
    role: str
    confidence: float = 1.0
    tags: list[str] = field(default_factory=list)
    item_id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """转成可落盘字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryItem":
        """从字典恢复记忆对象。"""
        return cls(**data)


@dataclass(slots=True)
class ReflectionArtifact:
    """结构化盘后反思结果。"""

    mistakes: list[str]
    correct_reads: list[str]
    useful_signals: list[str]
    bad_patterns: list[str]
    strategy_rules: list[str]
    confidence: float

    def to_memory_items(self, game_id: str, phase: str, role: str) -> list[MemoryItem]:
        """将反思结果转换为可跨局复用的记忆条目。"""
        items: list[MemoryItem] = []
        for rule in self.strategy_rules:
            items.append(
                MemoryItem(
                    memory_type="reflection",
                    content=rule,
                    game_id=game_id,
                    phase=phase,
                    role=role,
                    confidence=self.confidence,
                    tags=["strategy_rule", role],
                )
            )
        return items


class AgentMemoryStore:
    """按 Agent 独立保存 JSON 私有记忆。"""

    def __init__(self, root_dir: str | Path, agent_id: str) -> None:
        self.agent_id = agent_id
        self.file_path = Path(root_dir) / agent_id / "memory.json"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.write_text("[]", encoding="utf-8")

    def append(self, item: MemoryItem) -> None:
        """追加单条记忆。"""
        items = self._load_raw()
        items.append(item.to_dict())
        self._save_raw(items)

    def append_many(self, items: list[MemoryItem]) -> None:
        """批量追加记忆。"""
        raw = self._load_raw()
        raw.extend(item.to_dict() for item in items)
        self._save_raw(raw)

    def read_all(self) -> list[MemoryItem]:
        """读取所有私有记忆。"""
        return [MemoryItem.from_dict(item) for item in self._load_raw()]

    def recent(self, limit: int = 5, memory_types: list[str] | None = None) -> list[MemoryItem]:
        """读取最近记忆，可按类型过滤。"""
        items = self.read_all()
        if memory_types:
            items = [item for item in items if item.memory_type in memory_types]
        return items[-limit:]

    def retrieve_speech_content(self, game_id: str, phase: str, limit: int = 10) -> list[MemoryItem]:
        """检索特定游戏和阶段的发言内容。

        Args:
            game_id: 游戏ID
            phase: 游戏阶段
            limit: 返回的最大条目数

        Returns:
            list[MemoryItem]: 匹配的发言内容记忆条目
        """
        items = [
            item for item in self.read_all()
            if item.memory_type == "speech" and item.game_id == game_id and item.phase == phase
        ]
        # 按时间顺序返回最新的发言
        items.sort(key=lambda x: x.item_id, reverse=True)
        return items[:limit]

    def retrieve_strategy_rules(self, role: str, limit: int = 3) -> list[MemoryItem]:
        """Retrieve reusable strategy rules for the given role."""
        items = [
            item
            for item in self.read_all()
            if (
                item.memory_type == "reflection"
                or "strategy_rule" in item.tags
            )
            and (item.role == role or role in item.tags)
        ]
        items.sort(key=lambda item: (item.confidence, item.item_id), reverse=True)
        return items[:limit]

    def append_speech(self, content: str, game_id: str, phase: str, speaker: str) -> None:
        """添加发言内容到记忆中。

        Args:
            content: 发言内容
            game_id: 游戏ID
            phase: 游戏阶段
            speaker: 发言者ID
        """
        speech_item = MemoryItem(
            memory_type="speech",
            content=content,
            game_id=game_id,
            phase=phase,
            role=speaker,  # 使用role字段存储发言者信息
            confidence=1.0,
            tags=["speech", "discussion"],
        )
        self.append(speech_item)

    def _load_raw(self) -> list[dict[str, Any]]:
        """读取原始 JSON。"""
        return json.loads(self.file_path.read_text(encoding="utf-8"))

    def _save_raw(self, items: list[dict[str, Any]]) -> None:
        """保存原始 JSON。"""
        self.file_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
