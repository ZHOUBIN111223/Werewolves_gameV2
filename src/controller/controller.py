"""中央协调器，负责基于 EventBus 编排游戏流程。"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

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

FINAL_PHASES = {GamePhase.POST_GAME}


class Controller:
    """中央协调器：Judge 负责规则，Controller 负责总线驱动的流程编排。"""

    def __init__(self, base_dir: str | Path, llm_service=None) -> None:
        self.base_dir = Path(base_dir)
        self.agent_data_dir = self.base_dir / "agents"
        self.llm = llm_service if llm_service is not None else MockLLM()
        self.global_store = GlobalEventStore(self.base_dir / "global_events.json")
        self._initialize_async_components()

    def _initialize_async_components(self):
        async def init_global_store():
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
        self._agents.clear()
        self._agent_stores.clear()
        self._memory_stores.clear()

        game_state = self.judge.initialize_game(game_id, players)
        self._active_games[game_id] = game_state

        for agent_id, role in players.items():
            await asyncio.to_thread(self.create_agent, agent_id, role, game_id)

        return game_state

    def initialize_game(self, game_id: str, players: Dict[str, str]) -> GameState:
        self._agents.clear()
        self._agent_stores.clear()
        self._memory_stores.clear()

        game_state = self.judge.initialize_game(game_id, players)
        self._active_games[game_id] = game_state

        for agent_id, role in players.items():
            self.create_agent(agent_id, role, game_id)

        return game_state

    def start_game(self, game_id: str, players: Dict[str, str], event_bus=None, llm_service=None) -> None:
        if llm_service is not None:
            self.llm = llm_service
        if event_bus is not None:
            self.event_bus = event_bus

        self.initialize_game(game_id, players)

    async def _publish_event(self, event: EventBase) -> None:
        if self.event_bus is not None:
            await self.event_bus.publish_async(event)
        else:
            await self.global_store.append(event)

    async def _publish_events(self, events: List[EventBase]) -> None:
        for event in events:
            await self._publish_event(event)

    async def _handle_controller_action_event(self, event: EventBase) -> None:
        if isinstance(event, Action):
            await self._controller_action_queue.put(event)

    async def _record_agent_observation(self, agent_id: str, event: EventBase) -> None:
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
        async def handler(event: EventBase) -> None:
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
        agent = self._agents[agent_id]
        return await asyncio.to_thread(
            agent.decide_action,
            game_state.game_id,
            game_state.current_phase.value,
            game_state.alive_players[:],
        )

    async def _wait_for_action(self, game_id: str, actor_id: str, timeout_seconds: float = 20.0) -> Action:
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

        return self._normalize_requested_action(action, game_state, request_kind)

    async def _apply_action(self, action: Action) -> List[EventBase]:
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
        events = self.judge.process_action(action, game_state)
        await self._publish_events(events)
        return events

    async def _advance_phase(self, game_id: str) -> List[EventBase]:
        if game_id not in self._active_games:
            return []

        events = self.judge.advance_phase(game_id)
        await self._publish_events(events)
        return events

    async def _publish_witch_night_info(self, game_state: GameState) -> None:
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

    def _select_sheriff_candidates(self, game_state: GameState) -> List[str]:
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
            actor=action.actor,
            action_type=resolved_action_type,
            target=resolved_target,
            reasoning_summary=resolved_reasoning_summary,
            public_speech=resolved_public_speech,
            timestamp=action.timestamp,
        )

    def _normalize_day_speech_action(self, action: Action) -> Action:
        public_speech = action.public_speech.strip() or action.reasoning_summary.strip() or "我先听听大家的想法。"
        return self._rebuild_action(
            action,
            action_type=ActionType.SPEAK,
            target="",
            public_speech=public_speech,
        )

    def _normalize_day_vote_action(self, action: Action, game_state: GameState) -> Action:
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
        valid_targets = [
            player_id
            for player_id in game_state.alive_players
            if player_id != action.actor
        ]
        if action.action_type == ActionType.VOTE and action.target in valid_targets:
            return self._rebuild_action(action, action_type=ActionType.VOTE, target=action.target, public_speech="")
        return action

    def _normalize_night_action(self, action: Action, game_state: GameState) -> Optional[Action]:
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
        if request_kind in {"day_speak", "sheriff_campaign_speak", "last_words"}:
            return self._normalize_day_speech_action(action)
        if request_kind == "sheriff_vote":
            return self._normalize_sheriff_vote_action(action, game_state)
        if request_kind == "badge_transfer":
            return self._normalize_badge_transfer_action(action, game_state)
        if request_kind == "day_vote":
            return self._normalize_day_vote_action(action, game_state)

        normalized_night_action = self._normalize_night_action(action, game_state)
        return normalized_night_action

    async def end_game_async(self, game_id: str) -> None:
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

        for agent_id, agent in self._agents.items():
            memory_store = self._memory_stores.get(agent_id)
            if not memory_store:
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
                continue

            await asyncio.to_thread(
                memory_store.append_many,
                artifact.to_memory_items(game_id=game_id, phase="post_game", role=agent.role),
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

        print(f"游戏 {game_id} 结束，获胜方: {game_state.winner}")
        print(f"存活玩家: {self.judge.get_alive_players(game_id)}")

    def end_game(self, game_id: str) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.end_game_async(game_id))
            return
        raise RuntimeError("end_game 不能在已运行的事件循环中同步调用")

    def get_game_status(self, game_id: str) -> Dict:
        return self.judge.get_game_status(game_id)

    def get_alive_players(self, game_id: str) -> List[str]:
        return self.judge.get_alive_players(game_id)

    async def run_game_loop(self, game_id: str, max_steps: int = 500) -> None:
        await self._ensure_event_bus_ready(game_id)
        await self._publish_game_started(game_id)

        finalization_started = False

        for _ in range(max_steps):
            game_state = self._active_games.get(game_id)
            if not game_state:
                break

            if game_state.current_phase in FINAL_PHASES:
                if not finalization_started:
                    finalization_started = True
                    await self.end_game_async(game_id)
                break

            alive_players = self.get_alive_players(game_id)
            if len(alive_players) <= 1:
                await self._advance_phase(game_id)
                continue

            if game_state.current_phase == GamePhase.SETUP:
                await self._advance_phase(game_id)
                await asyncio.sleep(0.05)
                continue

            if game_state.current_phase.value.startswith("day_"):
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

            await self._advance_phase(game_id)
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError(f"Game loop exceeded max_steps={max_steps}")
