"""Base agent implementation shared by all game roles."""

from __future__ import annotations

from abc import ABC
from copy import deepcopy

from config import AppConfig
from src.agents.agent_store import AgentStore
from src.agents.memory_store import AgentMemoryStore, MemoryItem, ReflectionArtifact
from src.enums import ActionType, GamePhase
from src.events.action import Action
from src.events.event import EventBase
from src.llm.mock_llm import MockLLM
from src.prompts.builders import (
    build_action_prompt,
    build_phase_specific_prompt,
    build_reflection_prompt,
    build_request_specific_prompt,
    build_role_specific_prompt,
)
from src.validation.action_validator import validate_and_create_action


class BaseAgent(ABC):
    """Common agent behavior for all roles."""

    def __init__(
        self,
        agent_id: str,
        role: str,
        agent_store: AgentStore,
        memory_store: AgentMemoryStore,
        llm: MockLLM,
    ) -> None:
        """创建一个基础 Agent 实例。

        说明：
        - AgentStore：保存该 Agent “可见”的事件（Observation）
        - AgentMemoryStore：保存该 Agent 的私有记忆（事实/假设/发言/复盘策略等）
        - llm：用于根据 prompt 生成下一步动作（可为 Mock 或真实实现）
        """
        self.agent_id = agent_id
        self.role = role
        self.agent_store = agent_store
        self.memory_store = memory_store
        self.llm = llm

        if role == "witch":
            # 女巫一次性资源（解药/毒药）使用状态，避免重复使用。
            self.heal_used = False
            self.poison_used = False

    def remember_fact(self, game_id: str, phase: str | GamePhase, content: str) -> None:
        """Store a factual memory item."""
        phase_str = phase.value if isinstance(phase, GamePhase) else phase
        self.memory_store.append(
            MemoryItem(
                memory_type="factual",
                content=content,
                game_id=game_id,
                phase=phase_str,
                role=self.role,
                confidence=1.0,
                tags=["fact"],
            )
        )

    def remember_hypothesis(
        self,
        game_id: str,
        phase: str | GamePhase,
        content: str,
        confidence: float,
    ) -> None:
        """Store a hypothesis memory item."""
        phase_str = phase.value if isinstance(phase, GamePhase) else phase
        self.memory_store.append(
            MemoryItem(
                memory_type="hypothesis",
                content=content,
                game_id=game_id,
                phase=phase_str,
                role=self.role,
                confidence=confidence,
                tags=["hypothesis"],
            )
        )

    def decide_action(
        self, game_id: str, phase: str, alive_players: list[str] | None = None
    ) -> Action:
        """Build a unified prompt and ask the model for the next action."""
        visible_events = self.agent_store.read_all()
        request_context = self._extract_request_context(visible_events)
        short_memories = self.memory_store.recent(
            limit=5,
            memory_types=["factual", "hypothesis", "episodic"],
        )
        speech_memories = self.memory_store.retrieve_speech_content(
            game_id=game_id,
            phase=phase,
            limit=10,
        )
        strategy_rules = self.memory_store.retrieve_strategy_rules(
            role=self.role,
            limit=3,
        )

        prompt = build_action_prompt(
            game_id=game_id,
            role=self.role,
            phase=phase,
            visible_events=visible_events,
            short_memories=short_memories,
            strategy_rules=strategy_rules,
            alive_players=alive_players,
            speech_memories=speech_memories,
            actor_id=self.agent_id,
        )
        prompt = build_role_specific_prompt(self.role, prompt)
        prompt = build_phase_specific_prompt(phase, prompt)
        prompt.update(request_context)
        prompt.update(
            build_request_specific_prompt(
                request_kind=str(request_context.get("request_kind", "")),
                role=self.role,
                actor_id=self.agent_id,
                alive_players=list(prompt.get("alive_players", []) or []),
                available_targets=list(request_context.get("available_targets", []) or []),
                sheriff_candidates=list(request_context.get("sheriff_candidates", []) or []),
                last_guard_target=str(request_context.get("last_guard_target", "") or ""),
            )
        )

        result = self.llm.invoke(prompt)
        action = validate_and_create_action(
            game_id=game_id,
            phase=phase,
            actor=self.agent_id,
            action_data=result,
            alive_players=alive_players,
        )
        action.payload.update(
            {
                "raw_llm_output": deepcopy(result),
                "request_kind": str(request_context.get("request_kind", "")),
                "current_subphase": str(request_context.get("current_subphase", "")),
                "allowed_actions": list(request_context.get("available_actions", [])),
                "available_targets": list(request_context.get("available_targets", [])),
            }
        )
        return action

    def _extract_request_context(self, visible_events: list[object]) -> dict[str, object]:
        """从最近的 action_requested 系统事件中提取请求上下文。

        Controller 会向指定 actor 发送 action_requested 事件，其中包含：
        - request_kind: 当前请求的子类型（如 day_vote / night_action）
        - allowed_actions: 本次允许的动作枚举
        - alive_players: 当前存活玩家列表（用于限定可选目标）
        - subphase: 更细粒度的子阶段（用于 prompt 约束）
        """
        for event in reversed(visible_events):
            payload = getattr(event, "payload", {}) or {}
            if payload.get("message") != "action_requested":
                continue
            if payload.get("actor") != self.agent_id:
                continue

            request_kind = str(payload.get("request_kind", "")).strip()
            allowed_actions = [str(item) for item in payload.get("allowed_actions", []) if item]
            available_targets = [
                str(item)
                for item in payload.get("available_targets", payload.get("alive_players", []))
                if item
            ]
            sheriff_candidates = [
                str(item) for item in payload.get("sheriff_candidates", []) if item
            ]
            last_guard_target = str(payload.get("last_guard_target", "") or "").strip()
            subphase = str(payload.get("subphase", "")).strip()
            context: dict[str, object] = {
                "request_kind": request_kind,
                "current_subphase": subphase,
            }
            if allowed_actions:
                context["available_actions"] = allowed_actions
                context["mandatory_action"] = (
                    f"当前请求类型是 {request_kind or 'unknown'}，只允许这些动作: {allowed_actions}"
                )
            if available_targets:
                context["available_targets"] = available_targets
            if sheriff_candidates:
                context["sheriff_candidates"] = sheriff_candidates
            if last_guard_target:
                context["last_guard_target"] = last_guard_target
            return context
        return {}

    def _enforce_mandatory_actions(
        self,
        action_type: ActionType,
        phase: str,
        alive_players: list[str],
        target: str,
    ) -> ActionType:
        """Enforce mandatory actions based on role and phase."""
        if (
            action_type == ActionType.SKIP
            and "night" in phase
            and self.role in ["werewolf", "seer", "guard", "witch"]
        ):
            if self.role == "werewolf":
                return ActionType.KILL
            if self.role == "seer":
                return ActionType.INSPECT
            if self.role == "guard":
                return ActionType.PROTECT
            if self.role == "witch":
                pass

        if (
            action_type == ActionType.SKIP
            and "night" not in phase
            and alive_players
            and len(alive_players) > 1
        ):
            other_players = [player_id for player_id in alive_players if player_id != self.agent_id]
            if other_players:
                import random

                if random.random() > 0.5:
                    return ActionType.VOTE
                return ActionType.SPEAK
            return ActionType.SPEAK

        if (
            action_type == ActionType.SKIP
            and "night" not in phase
            and alive_players
            and len(alive_players) > 1
        ):
            import random

            if random.random() < 0.3:
                return ActionType.SPEAK

        return action_type

    def _select_reflection_visible_events(
        self,
        visible_events: list[EventBase],
    ) -> list[EventBase]:
        """Keep the post-game reflection prompt bounded to recent, game-relevant events."""
        max_events = max(int(AppConfig.REFLECTION_MAX_VISIBLE_EVENTS), 0)
        if max_events == 0:
            return []
        return visible_events[-max_events:]

    def _select_reflection_memories(self, game_id: str) -> list[MemoryItem]:
        """Limit reflection memories to the current game plus a small set of strategy rules."""
        all_memories = self.memory_store.read_all()
        game_memories = [item for item in all_memories if item.game_id == game_id]
        max_game_memories = max(int(AppConfig.REFLECTION_MAX_MEMORIES), 0)
        selected_game_memories = game_memories[-max_game_memories:] if max_game_memories else []

        max_strategy_rules = max(int(AppConfig.REFLECTION_MAX_STRATEGY_RULES), 0)
        strategy_rules = self.memory_store.retrieve_strategy_rules(
            role=self.role,
            limit=max_strategy_rules,
        )
        selected_ids = {item.item_id for item in selected_game_memories}
        for item in strategy_rules:
            if item.item_id not in selected_ids:
                selected_game_memories.append(item)
                selected_ids.add(item.item_id)

        return selected_game_memories

    def reflect(
        self,
        game_id: str,
        revealed_truth: dict[str, object],
        outcome: str,
    ) -> ReflectionArtifact:
        """Build and persist a post-game reflection artifact."""
        visible_events = self._select_reflection_visible_events(self.agent_store.read_all())
        memories = self._select_reflection_memories(game_id)
        prompt = build_reflection_prompt(
            role=self.role,
            game_id=game_id,
            visible_events=visible_events,
            memories=memories,
            revealed_truth=revealed_truth,
            outcome=outcome,
        )
        result = self.llm.invoke(prompt)
        artifact = ReflectionArtifact(
            mistakes=list(result["mistakes"]),
            correct_reads=list(result["correct_reads"]),
            useful_signals=list(result["useful_signals"]),
            bad_patterns=list(result["bad_patterns"]),
            strategy_rules=list(result["strategy_rules"]),
            confidence=float(result["confidence"]),
        )
        return artifact
