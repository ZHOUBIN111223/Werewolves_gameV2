"""Offline decision-accuracy evaluation for multi-game runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from src.enums import ActionType
from src.events.action import Action
from src.events.async_store import GlobalEventStore
from src.events.event import EventBase

GOOD_ROLES = {"villager", "seer", "witch", "guard", "hunter"}
GOD_ROLES = {"seer", "witch", "guard", "hunter"}

METRIC_KEYS = (
    "witch_poison_accuracy",
    "witch_heal_accuracy",
    "guard_protect_accuracy",
    "guard_protect_god_accuracy",
    "seer_inspect_hit_rate",
    "hunter_shot_accuracy",
    "werewolf_night_kill_accuracy",
    "werewolf_day_vote_accuracy",
    "good_day_vote_accuracy",
    "good_sheriff_vote_accuracy",
)


@dataclass
class RatioCounter:
    """Track numerator and denominator for a single accuracy metric."""

    total: int = 0
    correct: int = 0

    def record(self, is_correct: bool) -> None:
        self.total += 1
        if is_correct:
            self.correct += 1

    def score(self) -> float | None:
        if self.total == 0:
            return None
        return round(self.correct / self.total, 6)


@dataclass
class DecisionEvalAccumulator:
    """Accumulate decision-accuracy counters across many games."""

    counters: dict[str, RatioCounter] = field(
        default_factory=lambda: {metric: RatioCounter() for metric in METRIC_KEYS}
    )

    def record(self, metric: str, is_correct: bool) -> None:
        self.counters[metric].record(is_correct)

    def to_scores(self) -> dict[str, float | None]:
        return {metric: counter.score() for metric, counter in self.counters.items()}


def _phase_value(event: EventBase) -> str:
    phase = getattr(event, "phase", "")
    return phase.value if hasattr(phase, "value") else str(phase)


def _action_type_value(action: Action) -> str:
    action_type = getattr(action, "action_type", "")
    return action_type.value if hasattr(action_type, "value") else str(action_type)


def _request_kind(action: Action) -> str:
    payload = getattr(action, "payload", {}) or {}
    return str(payload.get("request_kind", "")).strip()


def _target_player(action: Action) -> str:
    direct_target = str(getattr(action, "target", "")).strip()
    if direct_target:
        return direct_target
    payload = getattr(action, "payload", {}) or {}
    return str(payload.get("target", "")).strip()


def _is_good(role: str) -> bool:
    return role in GOOD_ROLES


def _is_god(role: str) -> bool:
    return role in GOD_ROLES


def _collect_self_kill_heal_exclusions(events: list[EventBase]) -> set[tuple[str, str]]:
    """Return (phase, target) pairs where the healed target self-killed as a werewolf."""

    exclusions: set[tuple[str, str]] = set()
    for event in events:
        if getattr(event, "event_type", "") != "system":
            continue
        if getattr(event, "system_name", "") != "kill_attempted":
            continue

        payload = getattr(event, "payload", {}) or {}
        killer = str(payload.get("killer", "")).strip()
        target = str(payload.get("target", "")).strip()
        if killer and target and killer == target:
            exclusions.add((_phase_value(event), target))

    return exclusions


def _evaluate_single_game(
    events: list[EventBase],
    players: Mapping[str, str],
    accumulator: DecisionEvalAccumulator,
) -> None:
    self_kill_heal_exclusions = _collect_self_kill_heal_exclusions(events)

    for event in events:
        if not isinstance(event, Action):
            continue

        actor = str(getattr(event, "actor", "")).strip()
        target = _target_player(event)
        actor_role = str(players.get(actor, "")).strip()
        target_role = str(players.get(target, "")).strip()
        action_type = _action_type_value(event)
        request_kind = _request_kind(event)

        if not actor_role:
            continue

        if action_type == ActionType.POISON.value and actor_role == "witch" and target:
            accumulator.record("witch_poison_accuracy", target_role == "werewolf")
            continue

        if action_type == ActionType.HEAL.value and actor_role == "witch" and target:
            if (_phase_value(event), target) in self_kill_heal_exclusions:
                continue
            accumulator.record("witch_heal_accuracy", _is_good(target_role))
            continue

        if action_type == ActionType.PROTECT.value and actor_role == "guard" and target:
            accumulator.record("guard_protect_accuracy", _is_good(target_role))
            accumulator.record("guard_protect_god_accuracy", _is_god(target_role))
            continue

        if action_type == ActionType.INSPECT.value and actor_role == "seer" and target:
            accumulator.record("seer_inspect_hit_rate", target_role == "werewolf")
            continue

        if action_type == ActionType.HUNT.value and actor_role == "hunter" and target:
            accumulator.record("hunter_shot_accuracy", target_role == "werewolf")
            continue

        if action_type == ActionType.KILL.value and actor_role == "werewolf" and target:
            accumulator.record("werewolf_night_kill_accuracy", _is_good(target_role))
            continue

        if action_type != ActionType.VOTE.value or not target:
            continue

        if request_kind == "day_vote":
            if actor_role == "werewolf":
                accumulator.record("werewolf_day_vote_accuracy", _is_good(target_role))
            elif _is_good(actor_role):
                accumulator.record("good_day_vote_accuracy", target_role == "werewolf")
            continue

        if request_kind == "sheriff_vote" and _is_good(actor_role):
            accumulator.record("good_sheriff_vote_accuracy", _is_good(target_role))


async def evaluate_games(
    global_store: GlobalEventStore,
    game_contexts: Mapping[str, Mapping[str, str]],
) -> dict[str, float | None]:
    """Evaluate all successful games from the current run."""

    accumulator = DecisionEvalAccumulator()
    for game_id, players in game_contexts.items():
        events = await global_store.get_events_by_game_id(game_id)
        _evaluate_single_game(events, players, accumulator)
    return accumulator.to_scores()


def export_eval_scores(scores: Mapping[str, float | None], output_path: str | Path) -> Path:
    """Persist the minimal score-only JSON artifact."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(dict(scores), file, ensure_ascii=False, indent=2)
    return path
