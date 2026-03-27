"""中央协调器，负责基于 EventBus 编排游戏流程。"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

from config import AppConfig
from src.agents.agent_store import AgentStore
from src.agents.base_agent import BaseAgent
from src.agents.memory_store import AgentMemoryStore
from src.controller.judge import GameState, Judge
from src.enums import ActionType, GamePhase
from src.events.action import Action
from src.events.async_store import GlobalEventStore
from src.events.event import EventBase
from src.events.event_bus import EventBus
from src.events.observation import Observation
from src.events.system_event import SystemEvent
from src.llm.mock_llm import MockLLM
from src.monitoring.rule_adherence import (
    build_agent_layer_record,
    build_controller_layer_record,
    build_judge_layer_record,
    localize_rule_adherence_record,
    summarize_rule_adherence_records,
)
from src.validation.action_validator import normalize_public_speech

FINAL_PHASES = {GamePhase.POST_GAME}


class Controller:
    """中央协调器：Judge 负责规则，Controller 负责总线驱动的流程编排。"""

    def __init__(self, base_dir: str | Path, llm_service=None) -> None:
        """创建 Controller。

        Args:
            base_dir: 本局/本轮运行的落盘目录（用于 AgentStore、全局事件库等）。
            llm_service: 可选的 LLM 实现（默认使用 MockLLM）。
        """
        self.base_dir = Path(base_dir)
        self.agent_data_dir = self.base_dir / "agents"
        self.llm = llm_service if llm_service is not None else MockLLM()
        self.global_store = GlobalEventStore(self.base_dir / "global_events.json")
        self._initialize_async_components()

    def _initialize_async_components(self):
        """初始化异步组件与运行时状态。

        说明：GlobalEventStore 使用异步初始化；此处兼容“已有事件循环”和“无事件循环”
        两种运行方式（例如脚本/线程中调用）。
        """
        async def init_global_store():
            """初始化全局事件存储（异步）。"""
            await self.global_store.initialize()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(init_global_store())
        else:
            loop.create_task(init_global_store())

        self.judge = Judge()
        self.event_bus: Optional[EventBus] = None
        self._agents: Dict[str, BaseAgent] = {}
        self._agent_stores: Dict[str, AgentStore] = {}
        self._memory_stores: Dict[str, AgentMemoryStore] = {}
        self._active_games: Dict[str, GameState] = {}
        self._bootstrapped_games: set[str] = set()
        self._start_published_games: set[str] = set()
        self._controller_action_queue: asyncio.Queue[Action] = asyncio.Queue()

    def create_agent(self, agent_id: str, role: str, game_id: str) -> BaseAgent:
        """创建并注册一个 Agent（含其可见事件存储与私有记忆存储）。"""
        agent_store = AgentStore(self.agent_data_dir, agent_id, game_id)
        memory_store = AgentMemoryStore(self.agent_data_dir, agent_id)
        agent = BaseAgent(
            agent_id=agent_id,
            role=role,
            agent_store=agent_store,
            memory_store=memory_store,
            llm=self.llm,
        )
        self._agents[agent_id] = agent
        self._agent_stores[agent_id] = agent_store
        self._memory_stores[agent_id] = memory_store
        return agent

    async def initialize_game_async(self, game_id: str, players: Dict[str, str]) -> GameState:
        """异步初始化对局：重置缓存并为每个玩家创建 Agent。"""
        self._agents.clear()
        self._agent_stores.clear()
        self._memory_stores.clear()

        game_state = self.judge.initialize_game(game_id, players)
        self._active_games[game_id] = game_state

        for agent_id, role in players.items():
            await asyncio.to_thread(self.create_agent, agent_id, role, game_id)

        return game_state

    def initialize_game(self, game_id: str, players: Dict[str, str]) -> GameState:
        """同步初始化对局：重置缓存并为每个玩家创建 Agent。"""
        self._agents.clear()
        self._agent_stores.clear()
        self._memory_stores.clear()

        game_state = self.judge.initialize_game(game_id, players)
        self._active_games[game_id] = game_state

        for agent_id, role in players.items():
            self.create_agent(agent_id, role, game_id)

        return game_state

    def start_game(self, game_id: str, players: Dict[str, str], event_bus=None, llm_service=None) -> None:
        """启动对局（完成初始化，但不直接跑循环）。

        实际的阶段推进由 `run_game_loop()` 驱动。
        """
        if llm_service is not None:
            self.llm = llm_service
        if event_bus is not None:
            self.event_bus = event_bus

        self.initialize_game(game_id, players)

    async def _publish_event(self, event: EventBase) -> None:
        """发布单条事件：优先走 EventBus，否则直接写入全局事件存储。"""
        if self.event_bus is not None:
            await self.event_bus.publish_async(event)
        else:
            await self.global_store.append(event)

    async def _publish_events(self, events: List[EventBase]) -> None:
        """顺序发布多条事件。"""
        for event in events:
            await self._publish_event(event)

    async def _handle_controller_action_event(self, event: EventBase) -> None:
        """订阅回调：将 Action 事件推入 Controller 内部队列，供等待方消费。"""
        if isinstance(event, Action):
            await self._controller_action_queue.put(event)

    async def _record_agent_observation(self, agent_id: str, event: EventBase) -> None:
        """将全局事件裁剪成 Observation，并写入对应 Agent 的可见存储与记忆。"""
        observation = Observation.from_event(event, observer=agent_id)
        agent_store = self._agent_stores.get(agent_id)
        agent = self._agents.get(agent_id)
        if not agent_store or not agent:
            return

        await asyncio.to_thread(agent_store.append_observation, observation)

        phase_value = event.phase.value if hasattr(event.phase, "value") else str(event.phase)
        await asyncio.to_thread(
            agent.remember_fact,
            event.game_id,
            phase_value,
            f"观察到事件: {observation.payload}",
        )

        if isinstance(event, SystemEvent) and event.system_name == "speech_delivered":
            speaker = event.payload.get("speaker")
            content = event.payload.get("content")
            if speaker and content:
                await asyncio.to_thread(
                    agent.memory_store.append_speech,
                    content,
                    event.game_id,
                    phase_value,
                    speaker,
                )

    def _build_agent_handler(self, agent_id: str) -> Callable[[EventBase], Awaitable[None]]:
        """为指定 Agent 构建订阅回调。

        该回调会：
        - 记录该 Agent 可见的 Observation
        - 当收到 action_requested 且 actor 匹配时，触发 Agent 决策并发布 Action
        """
        async def handler(event: EventBase) -> None:
            """订阅回调主体：记录观察并响应 action_requested。"""
            await self._record_agent_observation(agent_id, event)

            if not isinstance(event, SystemEvent):
                return
            if event.system_name != "action_requested":
                return
            if event.payload.get("actor") != agent_id:
                return

            game_state = self._active_games.get(event.game_id)
            if not game_state or game_state.game_ended:
                return

            request_kind = event.payload.get("request_kind", "")
            try:
                action = await self._decide_action_via_agent(
                    agent_id,
                    game_state,
                    request_kind=request_kind,
                )
                action = self._normalize_requested_action(action, game_state, request_kind)
                await self._publish_event(action)
            except Exception as exc:
                await self._publish_event(
                    SystemEvent(
                        game_id=event.game_id,
                        phase=game_state.current_phase,
                        visibility=["controller"],
                        payload={"actor": agent_id, "request_kind": request_kind, "error": str(exc)},
                        system_name="agent_action_failed",
                    )
                )

        return handler

    async def _ensure_event_bus_ready(self, game_id: str) -> None:
        """确保 EventBus 订阅关系已建立（controller 与各 agent 的订阅）。"""
        if self.event_bus is None:
            raise RuntimeError("Controller requires an EventBus for the current architecture")

        if game_id in self._bootstrapped_games:
            return

        await self.event_bus.subscribe_async(
            subscriber_id=f"controller:{game_id}",
            handler=self._handle_controller_action_event,
            event_types=["action"],
            visibility_scope="controller",
        )

        for agent_id in self._agents:
            await self.event_bus.subscribe_async(
                subscriber_id=f"agent:{game_id}:{agent_id}",
                handler=self._build_agent_handler(agent_id),
                visibility_scope=agent_id,
            )

        self._bootstrapped_games.add(game_id)

    async def _publish_game_started(self, game_id: str) -> None:
        """发布 game_started 事件（每局只发布一次）。"""
        if game_id in self._start_published_games:
            return

        game_state = self._active_games[game_id]
        start_event = SystemEvent(
            game_id=game_id,
            phase=GamePhase.SETUP,
            visibility=["all"],
            payload={"message": "game_started", "players": list(game_state.players.keys())},
            system_name="game_started",
        )
        await self._publish_event(start_event)
        self._start_published_games.add(game_id)

    async def _decide_action_via_agent(
        self,
        agent_id: str,
        game_state: GameState,
        *,
        request_kind: str,
    ) -> Action:
        """通过 Agent 在后台线程中决策下一步 Action。"""
        agent = self._agents[agent_id]
        return await asyncio.to_thread(
            agent.decide_action,
            game_state.game_id,
            game_state.current_phase.value,
            game_state.alive_players[:],
        )

    async def _wait_for_action(self, game_id: str, actor_id: str, timeout_seconds: float = 20.0) -> Action:
        """等待来自指定 actor 的 Action（从 Controller 内部队列消费）。"""
        while True:
            action = await asyncio.wait_for(self._controller_action_queue.get(), timeout=timeout_seconds)
            if action.game_id == game_id and action.actor == actor_id:
                return action

    async def _request_action(
        self,
        game_state: GameState,
        actor_id: str,
        request_kind: str,
        allowed_actions: List[str],
    ) -> Action:
        """向指定 actor 发起行动请求，并等待其返回 Action。"""
        request_event = SystemEvent(
            game_id=game_state.game_id,
            phase=game_state.current_phase,
            visibility=[actor_id],
            payload={
                "message": "action_requested",
                "actor": actor_id,
                "role": game_state.players.get(actor_id, ""),
                "request_kind": request_kind,
                "allowed_actions": allowed_actions,
                "alive_players": game_state.alive_players[:],
                "available_targets": self._available_targets_for_request(
                    game_state,
                    actor_id,
                    request_kind,
                ),
                "last_guard_target": game_state.last_guard_target_by_guard.get(actor_id),
                "sheriff_candidates": list(game_state.sheriff_candidates),
                "subphase": game_state.current_subphase,
            },
            system_name="action_requested",
        )
        await self._publish_event(request_event)

        try:
            action = await self._wait_for_action(game_state.game_id, actor_id)
        except asyncio.TimeoutError:
            timeout_event = SystemEvent(
                game_id=game_state.game_id,
                phase=game_state.current_phase,
                visibility=["controller"],
                payload={"actor": actor_id, "request_kind": request_kind},
                system_name="action_request_timeout",
            )
            await self._publish_event(timeout_event)
            raise RuntimeError(f"Timed out waiting for action from {actor_id} during {request_kind}")

        action = self._normalize_requested_action(action, game_state, request_kind)
        await self._record_action_rule_layers(game_state, action)
        return action

    async def _apply_action(self, action: Action) -> List[EventBase]:
        """将 Action 提交给 Judge 处理并发布结果事件。"""
        if action.game_id not in self._active_games:
            events = [
                SystemEvent(
                    game_id=action.game_id,
                    phase=GamePhase.SETUP,
                    visibility=["controller"],
                    payload={"error": f"Game {action.game_id} not found", "action_id": action.event_id},
                    system_name="invalid_game",
                )
            ]
            await self._publish_events(events)
            return events

        game_state = self._active_games[action.game_id]
        request_kind = str(action.payload.get("request_kind", "")) if action.payload else ""
        is_valid, error_msg = self.judge.validate_action(action, game_state)
        await self._record_judge_rule_layer(
            game_state,
            action,
            request_kind,
            is_valid=is_valid,
            judge_reason=error_msg,
        )
        events = self.judge.process_action(action, game_state)
        await self._publish_events(events)
        return events

    async def _advance_phase(self, game_id: str) -> List[EventBase]:
        """推进阶段：调用 Judge.advance_phase 并发布产生的事件。"""
        if game_id not in self._active_games:
            return []

        events = self.judge.advance_phase(game_id)
        await self._publish_events(events)
        return events

    async def _publish_witch_night_info(self, game_state: GameState) -> None:
        """在女巫夜晚行动前，私下告知其当夜刀口信息（如有）。"""
        witches = [pid for pid in game_state.alive_players if game_state.players.get(pid) == "witch"]
        if not witches or not game_state.kills_pending:
            return

        event = SystemEvent(
            game_id=game_state.game_id,
            phase=game_state.current_phase,
            visibility=[witches[0]],
            payload={
                "message": "witch_night_info",
                "attacked_player": game_state.kills_pending[0],
            },
            system_name="witch_night_info",
        )
        await self._publish_event(event)

    def _allowed_actions_for_request(
        self,
        game_state: GameState,
        actor_id: str,
        request_kind: str,
    ) -> List[str]:
        """根据 request_kind 与角色能力计算允许的动作列表。"""
        if request_kind in {"day_speak", "sheriff_campaign_speak", "last_words"}:
            return ["speak"]
        if request_kind in {"day_vote", "sheriff_vote"}:
            return ["vote"]
        if request_kind == "badge_transfer":
            return ["vote", "skip"]

        role = game_state.players.get(actor_id, "")
        if role == "guard":
            return ["protect"]
        if role == "werewolf":
            return ["kill"]
        if role == "seer":
            return ["inspect"]
        if role == "witch":
            allowed_actions: List[str] = []
            if game_state.kills_pending and not game_state.heal_used.get(actor_id, False):
                allowed_actions.append("heal")
            if not game_state.poison_used.get(actor_id, False):
                allowed_actions.append("poison")
            allowed_actions.append("skip")
            return allowed_actions
        return ["skip"]

    def _available_targets_for_request(
        self,
        game_state: GameState,
        actor_id: str,
        request_kind: str,
    ) -> List[str]:
        """Return a request-specific target pool for prompt construction."""
        if request_kind in {"day_speak", "sheriff_campaign_speak", "last_words"}:
            return []
        if request_kind in {"day_vote", "badge_transfer"}:
            return [
                player_id
                for player_id in game_state.alive_players
                if player_id != actor_id
            ]
        if request_kind == "sheriff_vote":
            return [
                player_id
                for player_id in game_state.sheriff_candidates
                if player_id in game_state.alive_players and player_id != actor_id
            ]
        if request_kind == "night_action" and game_state.players.get(actor_id, "") == "guard":
            forbidden_target = game_state.last_guard_target_by_guard.get(actor_id)
            return [
                player_id
                for player_id in game_state.alive_players
                if player_id != forbidden_target
            ]
        return game_state.alive_players[:]

    def _select_sheriff_candidates(self, game_state: GameState) -> List[str]:
        """为警长竞选挑选候选人（简化的概率策略）。"""
        if len(game_state.alive_players) <= 1:
            return []

        role_probability = {
            "seer": 0.8,
            "hunter": 0.65,
            "guard": 0.5,
            "witch": 0.5,
            "werewolf": 0.45,
            "villager": 0.35,
        }
        candidates = [
            player_id
            for player_id in game_state.alive_players
            if random.random() < role_probability.get(game_state.players.get(player_id, ""), 0.4)
        ]
        if len(candidates) < 2:
            remaining = [player_id for player_id in game_state.alive_players if player_id not in candidates]
            random.shuffle(remaining)
            candidates.extend(remaining[: 2 - len(candidates)])
        if len(candidates) > 4:
            candidates = random.sample(candidates, 4)
        return candidates

    def _build_day_speaking_order(self, game_state: GameState) -> List[str]:
        """构建白天发言顺序（若有警徽，随机选择从警徽左右开始）。"""
        alive_in_seat_order = [
            player_id for player_id in game_state.seat_order if player_id in game_state.alive_players
        ]
        if not alive_in_seat_order:
            return []
        if not game_state.badge_holder_id or game_state.badge_holder_id not in alive_in_seat_order:
            return alive_in_seat_order

        direction = random.choice(["left", "right"])
        badge_index = alive_in_seat_order.index(game_state.badge_holder_id)
        if direction == "left":
            order = alive_in_seat_order[badge_index + 1 :] + alive_in_seat_order[: badge_index + 1]
        else:
            reversed_alive = list(reversed(alive_in_seat_order))
            reversed_index = reversed_alive.index(game_state.badge_holder_id)
            order = reversed_alive[reversed_index + 1 :] + reversed_alive[: reversed_index + 1]
        game_state.speaking_order = order
        return order

    async def _announce_daybreak(self, game_state: GameState) -> None:
        """发布天亮公告：公布昨夜死亡名单或平安夜。"""
        deaths = game_state.last_night_deaths[:]
        if deaths:
            await self._publish_event(
                SystemEvent(
                    game_id=game_state.game_id,
                    phase=game_state.current_phase,
                    visibility=["all"],
                    payload={"message": f"天亮了，昨夜死亡玩家: {deaths}", "deaths": deaths},
                    system_name="night_deaths_announced",
                )
            )
        else:
            await self._publish_event(
                SystemEvent(
                    game_id=game_state.game_id,
                    phase=game_state.current_phase,
                    visibility=["all"],
                    payload={"message": "天亮了，昨夜是平安夜", "deaths": []},
                    system_name="night_peaceful",
                )
            )

    async def _run_sheriff_election(self, game_state: GameState) -> None:
        """运行警长竞选流程：竞选发言 -> 投票 -> 结算。"""
        candidates = self._select_sheriff_candidates(game_state)
        game_state.sheriff_candidates = candidates
        await self._publish_event(
            SystemEvent(
                game_id=game_state.game_id,
                phase=game_state.current_phase,
                visibility=["all"],
                payload={"candidates": candidates},
                system_name="sheriff_election_started",
            )
        )
        if not candidates:
            return

        game_state.current_subphase = "sheriff_campaign"
        for agent_id in candidates:
            action = await self._request_action(
                game_state,
                agent_id,
                request_kind="sheriff_campaign_speak",
                allowed_actions=self._allowed_actions_for_request(game_state, agent_id, "sheriff_campaign_speak"),
            )
            await self._apply_action(action)

        voters = [player_id for player_id in game_state.alive_players if player_id not in candidates]
        game_state.current_subphase = "sheriff_voting"
        for agent_id in voters:
            action = await self._request_action(
                game_state,
                agent_id,
                request_kind="sheriff_vote",
                allowed_actions=self._allowed_actions_for_request(game_state, agent_id, "sheriff_vote"),
            )
            await self._apply_action(action)

        await self._publish_events(self.judge.resolve_sheriff_election(game_state))

    async def _run_last_words(
        self,
        game_state: GameState,
        speaker_ids: List[str],
        *,
        reason: str,
    ) -> None:
        """运行遗言流程：逐个请求发言，并记录失败事件。"""
        game_state.current_subphase = "last_words"
        for speaker_id in speaker_ids:
            if speaker_id not in game_state.players:
                continue

            await self._publish_event(
                SystemEvent(
                    game_id=game_state.game_id,
                    phase=game_state.current_phase,
                    visibility=["all"],
                    payload={"speaker": speaker_id, "reason": reason},
                    system_name="last_words_announced",
                )
            )

            try:
                action = await self._request_action(
                    game_state,
                    speaker_id,
                    request_kind="last_words",
                    allowed_actions=self._allowed_actions_for_request(game_state, speaker_id, "last_words"),
                )
            except Exception as exc:
                await self._publish_event(
                    SystemEvent(
                        game_id=game_state.game_id,
                        phase=game_state.current_phase,
                        visibility=["controller"],
                        payload={"speaker": speaker_id, "reason": reason, "error": str(exc)},
                        system_name="last_words_failed",
                    )
                )
                continue

            await self._apply_action(action)
            game_state.pending_last_words_reasons.pop(speaker_id, None)

    async def _resolve_pending_badge_transfer(self, game_state: GameState) -> None:
        """处理“警徽待转移”状态：向持徽者发起 badge_transfer 请求并提交到 Judge。"""
        from_player = game_state.pending_badge_transfer_from
        if not from_player:
            return

        alive_targets = [player_id for player_id in game_state.alive_players if player_id != from_player]
        await self._publish_event(
            SystemEvent(
                game_id=game_state.game_id,
                phase=game_state.current_phase,
                visibility=[from_player],
                payload={
                    "message": "badge_transfer_requested",
                    "actor": from_player,
                    "request_kind": "badge_transfer",
                    "alive_players": alive_targets,
                    "allowed_actions": ["vote", "skip"],
                },
                system_name="badge_transfer_requested",
            )
        )

        transfer_target: str | None = None
        if alive_targets:
            try:
                action = await self._request_action(
                    game_state,
                    from_player,
                    request_kind="badge_transfer",
                    allowed_actions=self._allowed_actions_for_request(game_state, from_player, "badge_transfer"),
                )
                normalized_action = self._normalize_badge_transfer_action(action, game_state)
                if normalized_action.action_type == ActionType.VOTE:
                    transfer_target = normalized_action.target
            except Exception as exc:
                await self._publish_event(
                    SystemEvent(
                        game_id=game_state.game_id,
                        phase=game_state.current_phase,
                        visibility=["controller"],
                        payload={"from_player": from_player, "error": str(exc)},
                        system_name="badge_transfer_failed",
                    )
                )

        await self._publish_events(
            self.judge.finalize_badge_transfer(game_state, from_player, transfer_target)
        )

    def _select_random_alive_other_than(
        self,
        game_state: GameState,
        exclude_id: str,
        *,
        excluded_ids: Optional[set[str]] = None,
    ) -> str | None:
        """从存活玩家中随机选择一个目标（排除指定玩家与可选的 excluded_ids）。"""
        excluded = set(excluded_ids or set())
        if exclude_id:
            excluded.add(exclude_id)
        alive_others = [p for p in game_state.alive_players if p not in excluded]
        return random.choice(alive_others) if alive_others else None

    def _rebuild_action(
        self,
        action: Action,
        *,
        action_type: Optional[ActionType] = None,
        target: Optional[str] = None,
        reasoning_summary: Optional[str] = None,
        public_speech: Optional[str] = None,
    ) -> Action:
        """基于原 Action 重建一个新 Action（用于纠偏/规范化）。"""
        resolved_action_type = action_type or action.action_type
        resolved_target = target if target is not None else action.target
        resolved_reasoning_summary = (
            reasoning_summary if reasoning_summary is not None else action.reasoning_summary
        )
        resolved_public_speech = (
            public_speech if public_speech is not None else action.public_speech
        )
        payload = dict(action.payload)
        payload.update(
            {
                "action_type": resolved_action_type.value,
                "target": resolved_target,
                "reasoning_summary": resolved_reasoning_summary,
                "public_speech": resolved_public_speech,
            }
        )
        return Action(
            game_id=action.game_id,
            phase=action.phase,
            visibility=["controller"],
            payload=payload,
            event_id=action.event_id,
            actor=action.actor,
            action_type=resolved_action_type,
            target=resolved_target,
            reasoning_summary=resolved_reasoning_summary,
            public_speech=resolved_public_speech,
            timestamp=action.timestamp,
            sequence_num=action.sequence_num,
            version=action.version,
        )

    def _build_rule_monitor_context(
        self,
        game_state: GameState,
        actor_id: str,
        request_kind: str,
        allowed_actions: Optional[List[str]] = None,
    ) -> dict[str, object]:
        resolved_allowed_actions = [
            str(item)
            for item in (allowed_actions or self._allowed_actions_for_request(game_state, actor_id, request_kind))
            if item
        ]
        return {
            "actor": actor_id,
            "role": game_state.players.get(actor_id, ""),
            "phase": game_state.current_phase.value,
            "subphase": game_state.current_subphase,
            "request_kind": request_kind,
            "allowed_actions": resolved_allowed_actions,
            "alive_players": game_state.alive_players[:],
            "players": dict(game_state.players),
            "sheriff_candidates": list(game_state.sheriff_candidates),
            "kills_pending": list(game_state.kills_pending),
            "heal_used": bool(game_state.heal_used.get(actor_id, False)),
            "poison_used": bool(game_state.poison_used.get(actor_id, False)),
            "last_guard_target": game_state.last_guard_target_by_guard.get(actor_id),
        }

    def _has_controller_rule_monitor(self, action: Action, request_kind: str) -> bool:
        payload = action.payload or {}
        rule_monitor = payload.get("rule_monitor", {})
        controller_record = rule_monitor.get("controller", {})
        return bool(controller_record) and controller_record.get("request_kind") == request_kind

    async def _record_rule_adherence_record(
        self,
        game_state: GameState,
        record: dict[str, object],
    ) -> None:
        action_id = str(record.get("action_id", "")).strip()
        layer = str(record.get("layer", "")).strip()
        if not action_id or not layer:
            return

        record_key = f"{action_id}:{layer}"
        if record_key in game_state.rule_adherence_record_keys:
            return

        game_state.rule_adherence_record_keys.add(record_key)
        game_state.rule_adherence_all_records.append(record)
        if bool(record.get("adhered", False)):
            return

        localized_record = localize_rule_adherence_record(record)
        game_state.rule_adherence_records.append(localized_record)
        await self._publish_event(
            SystemEvent(
                game_id=game_state.game_id,
                phase=game_state.current_phase,
                visibility=["controller"],
                payload=localized_record,
                system_name="rule_adherence_observed",
            )
        )

    async def _record_action_rule_layers(self, game_state: GameState, action: Action) -> None:
        payload = action.payload or {}
        rule_monitor = payload.get("rule_monitor", {})
        for layer_name in ("agent", "controller"):
            layer_record = rule_monitor.get(layer_name)
            if isinstance(layer_record, dict):
                await self._record_rule_adherence_record(game_state, layer_record)

    async def _record_judge_rule_layer(
        self,
        game_state: GameState,
        action: Action,
        request_kind: str,
        *,
        is_valid: bool,
        judge_reason: str,
    ) -> None:
        allowed_actions = []
        if action.payload:
            allowed_actions = [str(item) for item in action.payload.get("allowed_actions", []) if item]
        context = self._build_rule_monitor_context(
            game_state,
            action.actor,
            request_kind,
            allowed_actions=allowed_actions or None,
        )
        judge_record = build_judge_layer_record(
            action=action,
            context=context,
            is_valid=is_valid,
            judge_reason=judge_reason,
        )
        await self._record_rule_adherence_record(game_state, judge_record)

    def _write_rule_adherence_summary(self, game_state: GameState) -> Path:
        summary = summarize_rule_adherence_records(
            game_state.rule_adherence_all_records,
            non_adherence_records=game_state.rule_adherence_records,
        )
        output_path = self.base_dir / f"rule_adherence_{game_state.game_id}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "游戏ID": game_state.game_id,
                    "生成时间": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    **summary,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        return output_path

    async def _publish_rule_adherence_summary(self, game_state: GameState) -> Path:
        """Persist and publish the rule-adherence summary before optional post-game work."""
        summary_path = self._write_rule_adherence_summary(game_state)
        summary = summarize_rule_adherence_records(
            game_state.rule_adherence_all_records,
            non_adherence_records=game_state.rule_adherence_records,
        )
        await self._publish_event(
            SystemEvent(
                game_id=game_state.game_id,
                phase=GamePhase.POST_GAME,
                visibility=["controller"],
                payload={
                    "summary_file": str(summary_path),
                    "summary": summary,
                },
                system_name="rule_adherence_summary_generated",
            )
        )
        return summary_path

    def _normalize_day_speech_action(self, action: Action) -> Action:
        """规范化白天发言 Action：强制为 SPEAK，清空 target，并确保有可用发言文本。"""
        public_speech = action.public_speech.strip() or action.reasoning_summary.strip() or "我先听听大家的想法。"
        return self._rebuild_action(
            action,
            action_type=ActionType.SPEAK,
            target="",
            public_speech=public_speech,
        )

    def _normalize_day_speech_action_for_request(
        self,
        action: Action,
        game_state: GameState,
    ) -> Action:
        """按白天发言规则纠偏 public_speech，避免指向非存活玩家或缺少理由。"""
        public_speech = normalize_public_speech(
            action.public_speech.strip() or action.reasoning_summary.strip() or "",
            game_state.alive_players[:],
            action.actor,
        )
        return self._rebuild_action(
            action,
            action_type=ActionType.SPEAK,
            target="",
            public_speech=public_speech,
        )

    def _normalize_day_vote_action(self, action: Action, game_state: GameState) -> Action:
        """规范化白天投票 Action：确保投票给存活且非自己的目标。"""
        target = action.target
        if (
            action.action_type != ActionType.VOTE
            or target not in game_state.alive_players
            or target == action.actor
        ):
            target = self._select_random_alive_other_than(game_state, action.actor)

        if not target:
            raise ValueError(f"No valid day vote target for {action.actor}")

        return self._rebuild_action(action, action_type=ActionType.VOTE, target=target, public_speech="")

    def _normalize_sheriff_vote_action(self, action: Action, game_state: GameState) -> Action:
        """规范化警长投票 Action：确保目标为候选人且非自己。"""
        candidates = [
            candidate for candidate in game_state.sheriff_candidates if candidate in game_state.alive_players
        ]
        target = action.target
        if (
            action.action_type != ActionType.VOTE
            or target not in candidates
            or target == action.actor
        ):
            valid_targets = [candidate for candidate in candidates if candidate != action.actor]
            target = random.choice(valid_targets) if valid_targets else ""

        if not target:
            raise ValueError(f"No valid sheriff vote target for {action.actor}")

        return self._rebuild_action(action, action_type=ActionType.VOTE, target=target, public_speech="")

    def _normalize_badge_transfer_action(self, action: Action, game_state: GameState) -> Action:
        """规范化警徽转移 Action：只接受对存活其他玩家的 vote，其余保持原样。"""
        valid_targets = [
            player_id
            for player_id in game_state.alive_players
            if player_id != action.actor
        ]
        if action.action_type == ActionType.VOTE and action.target in valid_targets:
            return self._rebuild_action(action, action_type=ActionType.VOTE, target=action.target, public_speech="")
        return action

    def _normalize_night_action(self, action: Action, game_state: GameState) -> Optional[Action]:
        """规范化夜晚技能 Action：根据角色强制动作类型与合法目标。"""
        role = game_state.players[action.actor]

        if role == "werewolf":
            target = action.target
            invalid_target = (
                action.action_type != ActionType.KILL
                or target not in game_state.alive_players
                or target == action.actor
                or game_state.players.get(target) == "werewolf"
            )
            if invalid_target:
                target = self._select_random_alive_other_than(
                    game_state,
                    action.actor,
                    excluded_ids={pid for pid in game_state.alive_players if game_state.players.get(pid) == "werewolf"},
                )
            if not target:
                return self._rebuild_action(action, action_type=ActionType.SKIP, target="", public_speech="")
            return self._rebuild_action(action, action_type=ActionType.KILL, target=target, public_speech="")

        if role == "seer":
            target = action.target
            if action.action_type != ActionType.INSPECT or target not in game_state.alive_players or target == action.actor:
                target = self._select_random_alive_other_than(game_state, action.actor)
            if not target:
                return self._rebuild_action(action, action_type=ActionType.SKIP, target="", public_speech="")
            return self._rebuild_action(action, action_type=ActionType.INSPECT, target=target, public_speech="")

        if role == "guard":
            target = action.target
            forbidden_target = game_state.last_guard_target_by_guard.get(action.actor)
            invalid_target = (
                action.action_type != ActionType.PROTECT
                or target not in game_state.alive_players
                or target == forbidden_target
            )
            if invalid_target:
                excluded_ids = {forbidden_target} if forbidden_target else set()
                candidates = [pid for pid in game_state.alive_players if pid not in excluded_ids]
                if not candidates:
                    return self._rebuild_action(action, action_type=ActionType.SKIP, target="", public_speech="")
                target = random.choice(candidates)
            return self._rebuild_action(action, action_type=ActionType.PROTECT, target=target, public_speech="")

        if role == "witch":
            if action.action_type == ActionType.HEAL:
                if not game_state.heal_used.get(action.actor, False) and game_state.kills_pending:
                    return self._rebuild_action(
                        action,
                        action_type=ActionType.HEAL,
                        target=game_state.kills_pending[0],
                        public_speech="",
                    )
                return self._rebuild_action(action, action_type=ActionType.SKIP, target="", public_speech="")

            if action.action_type == ActionType.POISON and not game_state.poison_used.get(action.actor, False):
                target = action.target
                if target not in game_state.alive_players or target == action.actor:
                    target = self._select_random_alive_other_than(game_state, action.actor)
                if target:
                    return self._rebuild_action(action, action_type=ActionType.POISON, target=target, public_speech="")

            return self._rebuild_action(action, action_type=ActionType.SKIP, target="", public_speech="")

        return self._rebuild_action(action, action_type=ActionType.SKIP, target="", public_speech="")

    def _normalize_requested_action(self, action: Action, game_state: GameState, request_kind: str) -> Action:
        """按 request_kind 选择对应的纠偏策略，将 Agent 输出规范化为可执行 Action。"""
        if self._has_controller_rule_monitor(action, request_kind):
            return action

        original_action = action
        if request_kind in {"day_speak", "sheriff_campaign_speak", "last_words"}:
            normalized_action = self._normalize_day_speech_action_for_request(action, game_state)
        elif request_kind == "sheriff_vote":
            normalized_action = self._normalize_sheriff_vote_action(action, game_state)
        elif request_kind == "badge_transfer":
            normalized_action = self._normalize_badge_transfer_action(action, game_state)
        elif request_kind == "day_vote":
            normalized_action = self._normalize_day_vote_action(action, game_state)
        else:
            normalized_action = self._normalize_night_action(action, game_state)

        allowed_actions = []
        if original_action.payload:
            allowed_actions = [str(item) for item in original_action.payload.get("allowed_actions", []) if item]
        context = self._build_rule_monitor_context(
            game_state,
            original_action.actor,
            request_kind,
            allowed_actions=allowed_actions or None,
        )
        rule_monitor = dict(normalized_action.payload.get("rule_monitor", {}))
        if "agent" not in rule_monitor:
            raw_output = original_action.payload.get("raw_llm_output") if original_action.payload else None
            rule_monitor["agent"] = build_agent_layer_record(
                action=original_action,
                raw_output=raw_output,
                context=context,
            )
        rule_monitor["controller"] = build_controller_layer_record(
            before_action=original_action,
            after_action=normalized_action,
            context=context,
        )
        normalized_action.payload["rule_monitor"] = rule_monitor
        return normalized_action

    @staticmethod
    def _markdown_bullets(items: list[str], empty_text: str = "无") -> list[str]:
        normalized_items = [str(item).strip() for item in items if str(item).strip()]
        if not normalized_items:
            return [f"- {empty_text}"]
        return [f"- {item}" for item in normalized_items]

    def _export_reflections_markdown(
        self,
        game_state: GameState,
        reflection_entries: list[dict[str, object]],
    ) -> Path:
        reflections_dir = self.base_dir / "reflections"
        reflections_dir.mkdir(parents=True, exist_ok=True)
        output_path = reflections_dir / f"{game_state.game_id}_agent_reflections.md"

        lines = [
            f"# {game_state.game_id} Agent Reflections",
            "",
            f"- Winner: {game_state.winner or 'unknown'}",
            f"- Alive Players At End: {', '.join(game_state.alive_players) if game_state.alive_players else 'none'}",
            "",
        ]

        for entry in reflection_entries:
            agent_id = str(entry.get("agent_id", "")).strip()
            role = str(entry.get("role", "")).strip()
            outcome = str(entry.get("outcome", "")).strip()
            status = str(entry.get("status", "")).strip()

            lines.extend(
                [
                    f"## {agent_id}",
                    "",
                    f"- Role: {role or 'unknown'}",
                    f"- Outcome: {outcome or 'unknown'}",
                    f"- Reflection Status: {status or 'unknown'}",
                ]
            )

            if status == "recorded":
                lines.append(f"- Confidence: {entry.get('confidence', '')}")
                lines.append("")
                lines.append("### Mistakes")
                lines.extend(self._markdown_bullets(list(entry.get("mistakes", []))))
                lines.append("")
                lines.append("### Correct Reads")
                lines.extend(self._markdown_bullets(list(entry.get("correct_reads", []))))
                lines.append("")
                lines.append("### Useful Signals")
                lines.extend(self._markdown_bullets(list(entry.get("useful_signals", []))))
                lines.append("")
                lines.append("### Bad Patterns")
                lines.extend(self._markdown_bullets(list(entry.get("bad_patterns", []))))
                lines.append("")
                lines.append("### Strategy Rules")
                lines.extend(self._markdown_bullets(list(entry.get("strategy_rules", []))))
            else:
                reason = str(entry.get("reason", "")).strip()
                error = str(entry.get("error", "")).strip()
                if reason:
                    lines.append(f"- Reason: {reason}")
                if error:
                    lines.append(f"- Error: {error}")

            lines.append("")

        output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return output_path

    async def end_game_async(self, game_id: str) -> None:
        """结束对局并生成复盘（Reflection）事件。

        流程：
        - 确保 winner 已被确定（必要时按当前状态补算）
        - 为每个 Agent 调用 reflect() 生成复盘策略，并写入其记忆存储
        - 发布 reflection_recorded / reflection_generated 等系统事件
        """
        if game_id not in self._active_games:
            return

        game_state = self._active_games[game_id]
        if not game_state.game_ended or not game_state.winner:
            winner, game_ended = self.judge.check_victory_conditions(game_state)
            if game_ended and winner:
                game_state.game_ended = True
                game_state.winner = winner

        revealed_truth = {agent_id: game_state.players[agent_id] for agent_id in game_state.players}
        outcome_by_agent = {}
        for agent_id, role in game_state.players.items():
            if game_state.winner == "werewolves":
                outcome_by_agent[agent_id] = "win" if role == "werewolf" else "lose"
            elif game_state.winner == "villagers":
                outcome_by_agent[agent_id] = "win" if role != "werewolf" else "lose"
            else:
                outcome_by_agent[agent_id] = "unknown"

        await self._publish_rule_adherence_summary(game_state)
        reflection_deadline = (
            asyncio.get_running_loop().time()
            + max(int(AppConfig.POST_GAME_TOTAL_TIMEOUT_SECONDS), 0)
        )
        reflection_entries: list[dict[str, object]] = []

        for agent_id, agent in self._agents.items():
            memory_store = self._memory_stores.get(agent_id)
            if not memory_store:
                reflection_entries.append(
                    {
                        "agent_id": agent_id,
                        "role": agent.role,
                        "outcome": outcome_by_agent.get(agent_id, "unknown"),
                        "status": "missing_memory_store",
                    }
                )
                continue

            remaining_budget = reflection_deadline - asyncio.get_running_loop().time()
            if remaining_budget <= 0:
                reflection_entries.append(
                    {
                        "agent_id": agent_id,
                        "role": agent.role,
                        "outcome": outcome_by_agent.get(agent_id, "unknown"),
                        "status": "skipped",
                        "reason": "post_game_reflection_budget_exhausted",
                    }
                )
                await self._publish_event(
                    SystemEvent(
                        game_id=game_id,
                        phase=GamePhase.POST_GAME,
                        visibility=["controller"],
                        payload={
                            "agent_id": agent_id,
                            "reason": "post_game_reflection_budget_exhausted",
                            "timeout_seconds": int(AppConfig.POST_GAME_TOTAL_TIMEOUT_SECONDS),
                        },
                        system_name="reflection_skipped",
                    )
                )
                continue

            try:
                artifact = await asyncio.to_thread(
                    agent.reflect,
                    game_id,
                    revealed_truth,
                    outcome_by_agent.get(agent_id, "unknown"),
                )
            except Exception as exc:
                await self._publish_event(
                    SystemEvent(
                        game_id=game_id,
                        phase=GamePhase.POST_GAME,
                        visibility=["controller"],
                        payload={"agent_id": agent_id, "error": str(exc)},
                        system_name="reflection_failed",
                    )
                )
                reflection_entries.append(
                    {
                        "agent_id": agent_id,
                        "role": agent.role,
                        "outcome": outcome_by_agent.get(agent_id, "unknown"),
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                continue

            await asyncio.to_thread(
                memory_store.append_many,
                artifact.to_memory_items(game_id=game_id, phase="post_game", role=agent.role),
            )
            reflection_entries.append(
                {
                    "agent_id": agent_id,
                    "role": agent.role,
                    "outcome": outcome_by_agent.get(agent_id, "unknown"),
                    "status": "recorded",
                    "mistakes": list(artifact.mistakes),
                    "correct_reads": list(artifact.correct_reads),
                    "useful_signals": list(artifact.useful_signals),
                    "bad_patterns": list(artifact.bad_patterns),
                    "strategy_rules": list(artifact.strategy_rules),
                    "confidence": float(artifact.confidence),
                }
            )
            await self._publish_event(
                SystemEvent(
                    game_id=game_id,
                    phase=GamePhase.POST_GAME,
                    visibility=["controller"],
                    payload={
                        "agent_id": agent_id,
                        "role": agent.role,
                        "outcome": outcome_by_agent.get(agent_id, "unknown"),
                        "mistakes": list(artifact.mistakes),
                        "correct_reads": list(artifact.correct_reads),
                        "useful_signals": list(artifact.useful_signals),
                        "bad_patterns": list(artifact.bad_patterns),
                        "strategy_rules": list(artifact.strategy_rules),
                        "confidence": float(artifact.confidence),
                    },
                    system_name="reflection_recorded",
                )
            )
            await self._publish_event(
                SystemEvent(
                    game_id=game_id,
                    phase=GamePhase.POST_GAME,
                    visibility=["controller"],
                    payload={"agent_id": agent_id, "strategy_rule_count": len(artifact.strategy_rules)},
                    system_name="reflection_generated",
                )
            )

        reflection_md_path = await asyncio.to_thread(
            self._export_reflections_markdown,
            game_state,
            reflection_entries,
        )
        await self._publish_event(
            SystemEvent(
                game_id=game_id,
                phase=GamePhase.POST_GAME,
                visibility=["controller"],
                payload={"path": str(reflection_md_path)},
                system_name="reflection_markdown_exported",
            )
        )

        print(f"游戏 {game_id} 结束，获胜方: {game_state.winner}")
        print(f"存活玩家: {self.judge.get_alive_players(game_id)}")

    def end_game(self, game_id: str) -> None:
        """同步结束对局（在无运行事件循环时可用）。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.end_game_async(game_id))
            return
        raise RuntimeError("end_game 不能在已运行的事件循环中同步调用")

    def get_game_status(self, game_id: str) -> Dict:
        """代理到 Judge.get_game_status。"""
        return self.judge.get_game_status(game_id)

    def get_alive_players(self, game_id: str) -> List[str]:
        """代理到 Judge.get_alive_players。"""
        return self.judge.get_alive_players(game_id)

    async def run_game_loop(self, game_id: str, max_steps: int = 500) -> None:
        """运行对局主循环（阶段推进 + 请求行动 + 应用行动）。

        Args:
            game_id: 对局 ID
            max_steps: 最大循环步数，防止异常状态导致无限循环
        """
        await self._ensure_event_bus_ready(game_id)
        await self._publish_game_started(game_id)

        finalization_started = False

        for _ in range(max_steps):
            # 读取当前对局状态；若被外部移除则结束循环。
            game_state = self._active_games.get(game_id)
            if not game_state:
                break

            if game_state.current_phase in FINAL_PHASES:
                # 结算阶段：生成复盘并退出主循环。
                if not finalization_started:
                    finalization_started = True
                    await self.end_game_async(game_id)
                break

            alive_players = self.get_alive_players(game_id)
            if len(alive_players) <= 1:
                # 存活玩家过少时直接推进阶段，让 Judge 结算胜负/进入结算。
                await self._advance_phase(game_id)
                continue

            if game_state.current_phase == GamePhase.SETUP:
                # 初始化阶段：直接进入第一个夜晚。
                await self._advance_phase(game_id)
                await asyncio.sleep(0.05)
                continue

            if game_state.current_phase.value.startswith("day_"):
                # 白天流程：天亮公告 -> 讨论发言 -> 投票 ->（如需）遗言。
                if game_state.current_subphase == "daybreak":
                    if game_state.current_phase == GamePhase.DAY_1 and not game_state.badge_holder_id:
                        await self._run_sheriff_election(game_state)

                    await self._announce_daybreak(game_state)

                    if game_state.pending_badge_transfer_from:
                        await self._resolve_pending_badge_transfer(game_state)

                    if game_state.current_phase == GamePhase.DAY_1 and game_state.pending_first_day_last_words:
                        await self._run_last_words(
                            game_state,
                            game_state.pending_first_day_last_words[:],
                            reason="first_night_death",
                        )
                        game_state.pending_first_day_last_words = []

                    game_state.current_subphase = "discussion"

                if game_state.current_subphase == "discussion":
                    # 讨论阶段：按发言顺序逐个请求发言。
                    speaking_order = self._build_day_speaking_order(game_state)
                    await self._publish_event(
                        SystemEvent(
                            game_id=game_state.game_id,
                            phase=game_state.current_phase,
                            visibility=["all"],
                            payload={
                                "badge_holder": game_state.badge_holder_id,
                                "speaking_order": speaking_order,
                            },
                            system_name="speaking_order_announced",
                        )
                    )
                    for agent_id in speaking_order:
                        action = await self._request_action(
                            game_state,
                            agent_id,
                            request_kind="day_speak",
                            allowed_actions=self._allowed_actions_for_request(game_state, agent_id, "day_speak"),
                        )
                        await self._apply_action(action)

                    game_state.current_subphase = "voting"
                    # 投票阶段：每个存活玩家都需要投票。
                    current_alive_players = self.get_alive_players(game_id)
                    for agent_id in current_alive_players:
                        action = await self._request_action(
                            game_state,
                            agent_id,
                            request_kind="day_vote",
                            allowed_actions=self._allowed_actions_for_request(game_state, agent_id, "day_vote"),
                        )
                        await self._apply_action(action)

                elif game_state.current_subphase == "last_words":
                    # 遗言阶段：处理警徽转移与待执行的遗言列表。
                    if game_state.pending_badge_transfer_from:
                        await self._resolve_pending_badge_transfer(game_state)

                    if game_state.pending_vote_last_words:
                        primary_speaker = game_state.pending_vote_last_words[0]
                        await self._run_last_words(
                            game_state,
                            game_state.pending_vote_last_words[:],
                            reason=game_state.pending_last_words_reasons.get(primary_speaker, "vote_elimination"),
                        )
                        game_state.pending_vote_last_words = []

                    game_state.current_subphase = "last_words_complete"

            elif game_state.current_phase.value.startswith("night_"):
                # 夜晚流程：按技能顺序依次请求动作（同一角色多名时只取第一个）。
                role_order = ["guard", "werewolf", "witch", "seer"]
                for role in role_order:
                    alive_role_players = [
                        pid for pid in self.get_alive_players(game_id) if game_state.players.get(pid) == role
                    ]
                    if not alive_role_players:
                        continue

                    actor_id = alive_role_players[0]
                    game_state.current_subphase = role

                    if role == "witch":
                        await self._publish_witch_night_info(game_state)

                    action = await self._request_action(
                        game_state,
                        actor_id,
                        request_kind="night_action",
                        allowed_actions=self._allowed_actions_for_request(game_state, actor_id, "night_action"),
                    )
                    await self._apply_action(action)

            # 每回合结束后推进阶段，并短暂 sleep 以让事件处理/输出更平滑。
            await self._advance_phase(game_id)
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError(f"Game loop exceeded max_steps={max_steps}")
