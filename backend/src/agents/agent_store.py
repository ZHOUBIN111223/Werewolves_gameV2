"""Agent 可见事件存储。"""

from __future__ import annotations

from pathlib import Path

from src.events.observation import Observation
from src.events.store import EventStore


class AgentStore(EventStore):
    """按 Agent 独立保存局内可见 Observation。"""

    def __init__(self, root_dir: str | Path, agent_id: str, game_id: str) -> None:
        """创建指定 Agent + 对局的观察事件存储。

        Observation 会落盘到：
        `<root_dir>/<agent_id>/<game_id>_observations.json`。
        """
        self.agent_id = agent_id
        self.game_id = game_id
        file_path = Path(root_dir) / agent_id / f"{game_id}_observations.json"
        super().__init__(file_path)

    def append_observation(self, observation: Observation) -> None:
        """写入单条可见观察事件。"""
        if observation.observer != self.agent_id:
            raise ValueError("不能把其他 Agent 的观察写入当前 AgentStore")
        self.append(observation)
