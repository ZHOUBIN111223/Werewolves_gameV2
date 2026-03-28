"""Post-game metrics extraction and export for werewolf matches."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.events.action import Action
from src.events.async_store import GlobalEventStore
from src.events.event import EventBase

GOOD_ROLES = {"villager", "seer", "witch", "guard", "hunter"}
ALL_ROLE_KEYS = ("villager", "seer", "witch", "guard", "hunter", "werewolf")
WINNER_KEYS = ("villagers", "werewolves")


@dataclass
class RatioCounter:
    """Simple numerator / denominator container."""

    numerator: int = 0
    denominator: int = 0

    def record(self, success: bool) -> None:
        self.denominator += 1
        if success:
            self.numerator += 1

    def to_dict(self) -> dict[str, int | float | None]:
        rate = None
        if self.denominator:
            rate = round(self.numerator / self.denominator, 6)
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "rate": rate,
        }


def _phase_value(event: EventBase) -> str:
    phase = getattr(event, "phase", "")
    return phase.value if hasattr(phase, "value") else str(phase)


def _payload(event: EventBase) -> dict[str, Any]:
    payload = getattr(event, "payload", {}) or {}
    return payload if isinstance(payload, dict) else {}


def _action_type_value(action: Action) -> str:
    action_type = getattr(action, "action_type", "")
    return action_type.value if hasattr(action_type, "value") else str(action_type)


def _request_kind(action: Action) -> str:
    return str(_payload(action).get("request_kind", "")).strip()


def _target_player(action: Action) -> str:
    direct_target = str(getattr(action, "target", "")).strip()
    if direct_target:
        return direct_target
    return str(_payload(action).get("target", "")).strip()


def _role_to_side(role: str) -> str:
    return "werewolves" if role == "werewolf" else "villagers"


def _phase_number(phase: str) -> int | None:
    if "_" not in phase:
        return None
    _, raw_value = phase.split("_", 1)
    if not raw_value.isdigit():
        return None
    return int(raw_value)


def _phase_order(phase: str) -> int:
    if phase == "setup":
        return 0
    if phase.startswith("night_"):
        phase_number = _phase_number(phase) or 0
        return (phase_number * 2) - 1
    if phase.startswith("day_"):
        phase_number = _phase_number(phase) or 0
        return phase_number * 2
    if phase == "post_game":
        return 100000
    return 99999


def _completed_days_for_phase(phase: str) -> int:
    phase_number = _phase_number(phase)
    if phase_number is None:
        return 0
    if phase.startswith("night_"):
        return max(phase_number - 1, 0)
    if phase.startswith("day_"):
        return phase_number
    return 0


def _is_early_elimination_phase(phase: str) -> bool:
    phase_number = _phase_number(phase)
    if phase_number is None:
        return False
    if phase.startswith("day_") or phase.startswith("night_"):
        return phase_number <= 2
    return False


def _make_action_record(action: Action, players: Mapping[str, str]) -> dict[str, Any]:
    actor = str(getattr(action, "actor", "")).strip()
    target = _target_player(action)
    actor_role = str(players.get(actor, "")).strip()
    target_role = str(players.get(target, "")).strip()
    return {
        "phase": _phase_value(action),
        "actor": actor,
        "actor_role": actor_role,
        "actor_side": _role_to_side(actor_role) if actor_role else None,
        "action_type": _action_type_value(action),
        "request_kind": _request_kind(action),
        "target": target or None,
        "target_role": target_role or None,
        "target_side": _role_to_side(target_role) if target_role else None,
    }


def _build_game_detail(
    game_id: str,
    players: Mapping[str, str],
    events: list[EventBase],
) -> dict[str, Any]:
    day_votes: dict[str, list[dict[str, Any]]] = {}
    vote_counts_by_phase: dict[str, dict[str, int]] = {}
    executed_by_phase: dict[str, str] = {}
    sheriff_votes: list[dict[str, Any]] = []
    inspections: list[dict[str, Any]] = []
    guard_actions: dict[str, dict[str, Any]] = {}
    heal_actions: dict[str, dict[str, Any]] = {}
    poison_actions: dict[str, dict[str, Any]] = {}
    wolf_kill_actions: dict[str, dict[str, Any]] = {}
    hunter_shots: list[dict[str, Any]] = []
    attack_protected_by_phase: dict[str, list[str]] = {}
    heal_success_by_phase: dict[str, list[str]] = {}
    night_deaths_by_phase: dict[str, list[str]] = {}
    eliminations: list[dict[str, Any]] = []
    elimination_by_player: dict[str, dict[str, Any]] = {}
    winner: str | None = None
    sheriff_result: dict[str, Any] = {}
    final_resolved_phase: str | None = None

    for event in events:
        if isinstance(event, Action):
            action_record = _make_action_record(event, players)
            phase = str(action_record["phase"])
            action_type = str(action_record["action_type"])
            request_kind = str(action_record["request_kind"])

            if request_kind == "day_vote":
                day_votes.setdefault(phase, []).append(action_record)
            elif request_kind == "sheriff_vote":
                sheriff_votes.append(action_record)

            if action_type == "inspect" and action_record["actor_role"] == "seer":
                inspections.append(action_record)
            elif action_type == "protect" and action_record["actor_role"] == "guard":
                guard_actions[phase] = action_record
            elif action_type == "heal" and action_record["actor_role"] == "witch":
                heal_actions[phase] = action_record
            elif action_type == "poison" and action_record["actor_role"] == "witch":
                poison_actions[phase] = action_record
            elif action_type == "kill" and action_record["actor_role"] == "werewolf":
                wolf_kill_actions[phase] = action_record
            elif action_type == "hunt" and action_record["actor_role"] == "hunter":
                hunter_shots.append(action_record)
            continue

        phase = _phase_value(event)
        payload = _payload(event)
        system_name = str(getattr(event, "system_name", "")).strip()

        if system_name == "vote_count_completed":
            raw_counts = payload.get("vote_counts", {}) or {}
            vote_counts_by_phase[phase] = {
                str(player_id): int(count)
                for player_id, count in raw_counts.items()
            }
        elif system_name == "player_eliminated":
            player_id = str(payload.get("eliminated_player", "")).strip()
            role = str(players.get(player_id, "")).strip()
            elimination_record = {
                "phase": phase,
                "player": player_id,
                "role": role or None,
                "side": _role_to_side(role) if role else None,
                "reason": str(payload.get("reason", "")).strip() or None,
                "survival_days": _completed_days_for_phase(phase),
                "is_early_elimination": _is_early_elimination_phase(phase),
            }
            eliminations.append(elimination_record)
            if player_id and player_id not in elimination_by_player:
                elimination_by_player[player_id] = elimination_record
            if elimination_record["reason"] == "eliminated by vote":
                executed_by_phase[phase] = player_id
        elif system_name == "attack_protected":
            attacked_player = str(payload.get("attacked_player", "")).strip()
            if attacked_player:
                attack_protected_by_phase.setdefault(phase, []).append(attacked_player)
        elif system_name == "heal_success":
            saved_player = str(payload.get("saved_player", "")).strip()
            if saved_player:
                heal_success_by_phase.setdefault(phase, []).append(saved_player)
        elif system_name == "night_resolution_completed":
            deaths = [str(player_id) for player_id in payload.get("deaths", []) if player_id]
            night_deaths_by_phase[phase] = deaths
        elif system_name == "sheriff_elected":
            sheriff_result = {
                "phase": phase,
                "sheriff": str(payload.get("sheriff", "")).strip() or None,
                "badge_holder": str(payload.get("badge_holder", "")).strip() or None,
            }
        elif system_name == "game_ended":
            resolved_winner = str(payload.get("winner", "")).strip()
            winner = resolved_winner or winner
        elif system_name == "post_game_finalization_started":
            previous_phase = str(payload.get("previous_phase", "")).strip()
            if previous_phase:
                final_resolved_phase = previous_phase

    for phase, votes in day_votes.items():
        if phase in vote_counts_by_phase:
            continue
        counts: dict[str, int] = {}
        for vote in votes:
            target = str(vote.get("target") or "").strip()
            if target:
                counts[target] = counts.get(target, 0) + 1
        vote_counts_by_phase[phase] = counts

    if final_resolved_phase is None:
        for event in reversed(events):
            phase = _phase_value(event)
            if phase != "post_game":
                final_resolved_phase = phase
                break

    sorted_day_phases = sorted(
        set(day_votes) | set(vote_counts_by_phase) | set(executed_by_phase),
        key=_phase_order,
    )
    day_vote_records: list[dict[str, Any]] = []
    for phase in sorted_day_phases:
        counts = vote_counts_by_phase.get(phase, {})
        executed_player = executed_by_phase.get(phase)
        max_votes = max(counts.values()) if counts else 0
        top_targets = sorted(
            [player_id for player_id, vote_count in counts.items() if vote_count == max_votes and max_votes > 0]
        )
        wolves_under_pressure = [
            player_id for player_id in top_targets if players.get(player_id) == "werewolf"
        ]
        executed_role = str(players.get(executed_player, "")).strip() if executed_player else ""
        day_vote_records.append(
            {
                "phase": phase,
                "votes": day_votes.get(phase, []),
                "vote_counts": counts,
                "max_votes": max_votes,
                "top_targets": top_targets,
                "wolves_under_pressure": wolves_under_pressure,
                "executed_player": executed_player,
                "executed_role": executed_role or None,
                "executed_side": _role_to_side(executed_role) if executed_role else None,
                "no_execution": executed_player is None,
            }
        )

    night_phases = sorted(
        set(guard_actions)
        | set(heal_actions)
        | set(poison_actions)
        | set(wolf_kill_actions)
        | set(night_deaths_by_phase)
        | set(attack_protected_by_phase)
        | set(heal_success_by_phase)
        | {str(item["phase"]) for item in inspections},
        key=_phase_order,
    )
    night_records: list[dict[str, Any]] = []
    for phase in night_phases:
        phase_inspections = [item for item in inspections if item["phase"] == phase]
        night_records.append(
            {
                "phase": phase,
                "guard_protect": guard_actions.get(phase),
                "wolf_kill": wolf_kill_actions.get(phase),
                "witch_heal": heal_actions.get(phase),
                "witch_poison": poison_actions.get(phase),
                "seer_inspects": phase_inspections,
                "attack_protected_targets": attack_protected_by_phase.get(phase, []),
                "heal_success_players": heal_success_by_phase.get(phase, []),
                "night_deaths": night_deaths_by_phase.get(phase, []),
            }
        )

    player_records: list[dict[str, Any]] = []
    completed_days_at_end = _completed_days_for_phase(final_resolved_phase or "setup")
    for player_id, role in players.items():
        elimination = elimination_by_player.get(player_id)
        won = winner is not None and _role_to_side(role) == winner
        player_records.append(
            {
                "player_id": player_id,
                "role": role,
                "side": _role_to_side(role),
                "won": won,
                "alive_to_end": elimination is None,
                "survival_days": elimination["survival_days"] if elimination else completed_days_at_end,
                "elimination": elimination,
            }
        )

    metric_counters: dict[str, RatioCounter] = {
        "witch_poison_accuracy": RatioCounter(),
        "witch_antidote_accuracy": RatioCounter(),
        "guard_protect_accuracy": RatioCounter(),
        "guard_effective_protect_rate": RatioCounter(),
        "seer_identify_accuracy": RatioCounter(),
        "hunter_shot_accuracy": RatioCounter(),
        "wolf_day_vote_accuracy": RatioCounter(),
        "good_day_vote_accuracy": RatioCounter(),
        "good_sheriff_vote_accuracy": RatioCounter(),
        "execution_hit_rate": RatioCounter(),
        "good_misexecution_rate": RatioCounter(),
        "wolf_survival_under_pressure_rate": RatioCounter(),
        "seer_info_conversion_rate": RatioCounter(),
        "early_elimination_rate": RatioCounter(),
    }

    for phase, action_record in sorted(guard_actions.items(), key=lambda item: _phase_order(item[0])):
        target = str(action_record.get("target") or "").strip()
        target_role = str(action_record.get("target_role") or "").strip()
        protected_targets = set(attack_protected_by_phase.get(phase, []))
        metric_counters["guard_protect_accuracy"].record(target_role in GOOD_ROLES)
        metric_counters["guard_effective_protect_rate"].record(target in protected_targets)

    for phase, action_record in sorted(heal_actions.items(), key=lambda item: _phase_order(item[0])):
        target = str(action_record.get("target") or "").strip()
        night_deaths = set(night_deaths_by_phase.get(phase, []))
        metric_counters["witch_antidote_accuracy"].record(target not in night_deaths)

    for action_record in poison_actions.values():
        metric_counters["witch_poison_accuracy"].record(action_record.get("target_role") == "werewolf")

    for action_record in inspections:
        metric_counters["seer_identify_accuracy"].record(action_record.get("target_role") == "werewolf")

    for action_record in hunter_shots:
        metric_counters["hunter_shot_accuracy"].record(action_record.get("target_role") == "werewolf")

    for day_vote_record in day_vote_records:
        for vote in day_vote_record["votes"]:
            actor_role = str(vote.get("actor_role") or "").strip()
            target_role = str(vote.get("target_role") or "").strip()
            if actor_role == "werewolf":
                metric_counters["wolf_day_vote_accuracy"].record(target_role in GOOD_ROLES)
            elif actor_role in GOOD_ROLES:
                metric_counters["good_day_vote_accuracy"].record(target_role == "werewolf")

        executed_player = str(day_vote_record.get("executed_player") or "").strip()
        if executed_player:
            executed_role = str(day_vote_record.get("executed_role") or "").strip()
            metric_counters["execution_hit_rate"].record(executed_role == "werewolf")
            metric_counters["good_misexecution_rate"].record(executed_role in GOOD_ROLES)

        for pressured_wolf in day_vote_record["wolves_under_pressure"]:
            metric_counters["wolf_survival_under_pressure_rate"].record(
                str(day_vote_record.get("executed_player") or "").strip() != pressured_wolf
            )

    for vote in sheriff_votes:
        actor_role = str(vote.get("actor_role") or "").strip()
        target_role = str(vote.get("target_role") or "").strip()
        if actor_role in GOOD_ROLES:
            metric_counters["good_sheriff_vote_accuracy"].record(target_role in GOOD_ROLES)

    inspected_wolves: dict[str, str] = {}
    for action_record in sorted(inspections, key=lambda item: _phase_order(str(item["phase"]))):
        target = str(action_record.get("target") or "").strip()
        if action_record.get("target_role") == "werewolf" and target and target not in inspected_wolves:
            inspected_wolves[target] = str(action_record["phase"])

    for target, inspect_phase in inspected_wolves.items():
        elimination_record = elimination_by_player.get(target)
        converted = bool(
            elimination_record
            and elimination_record.get("reason") == "eliminated by vote"
            and _phase_order(str(elimination_record.get("phase") or "")) > _phase_order(inspect_phase)
        )
        metric_counters["seer_info_conversion_rate"].record(converted)

    total_survival_days = 0
    early_elimination_count = 0
    for player_record in player_records:
        survival_days = int(player_record["survival_days"])
        total_survival_days += survival_days
        was_early = bool(player_record.get("elimination", {}) and player_record["elimination"]["is_early_elimination"])
        metric_counters["early_elimination_rate"].record(was_early)
        if was_early:
            early_elimination_count += 1

    side_totals = {
        "villagers": RatioCounter(),
        "werewolves": RatioCounter(),
    }
    role_totals = {role: RatioCounter() for role in ALL_ROLE_KEYS}
    for player_record in player_records:
        side_totals[player_record["side"]].record(bool(player_record["won"]))
        role_totals[player_record["role"]].record(bool(player_record["won"]))

    role_win_rate = {
        role: counter.to_dict()
        for role, counter in role_totals.items()
        if counter.denominator > 0
    }

    metrics = {
        "overall_win_rate": {
            "winner": winner,
            "completed_games": 1 if winner else 0,
            "villagers": 1 if winner == "villagers" else 0,
            "werewolves": 1 if winner == "werewolves" else 0,
        },
        "side_win_rate": {
            side: counter.to_dict() for side, counter in side_totals.items()
        },
        "role_win_rate": role_win_rate,
        "witch_poison_accuracy": metric_counters["witch_poison_accuracy"].to_dict(),
        "witch_antidote_accuracy": metric_counters["witch_antidote_accuracy"].to_dict(),
        "guard_protect_accuracy": metric_counters["guard_protect_accuracy"].to_dict(),
        "guard_effective_protect_rate": metric_counters["guard_effective_protect_rate"].to_dict(),
        "seer_identify_accuracy": metric_counters["seer_identify_accuracy"].to_dict(),
        "hunter_shot_accuracy": metric_counters["hunter_shot_accuracy"].to_dict(),
        "wolf_day_vote_accuracy": metric_counters["wolf_day_vote_accuracy"].to_dict(),
        "good_day_vote_accuracy": metric_counters["good_day_vote_accuracy"].to_dict(),
        "good_sheriff_vote_accuracy": metric_counters["good_sheriff_vote_accuracy"].to_dict(),
        "execution_hit_rate": metric_counters["execution_hit_rate"].to_dict(),
        "good_misexecution_rate": metric_counters["good_misexecution_rate"].to_dict(),
        "wolf_survival_under_pressure_rate": metric_counters["wolf_survival_under_pressure_rate"].to_dict(),
        "seer_info_conversion_rate": metric_counters["seer_info_conversion_rate"].to_dict(),
        "avg_survival_days": {
            "total_survival_days": total_survival_days,
            "total_players": len(player_records),
            "average": round(total_survival_days / len(player_records), 6) if player_records else None,
        },
        "early_elimination_rate": {
            **metric_counters["early_elimination_rate"].to_dict(),
            "early_elimination_count": early_elimination_count,
        },
    }

    return {
        "game": {
            "game_id": game_id,
            "winner": winner,
            "final_resolved_phase": final_resolved_phase,
            "total_events": len(events),
            "total_players": len(players),
        },
        "players": player_records,
        "raw_records": {
            "day_votes": day_vote_records,
            "sheriff_votes": sheriff_votes,
            "sheriff_result": sheriff_result,
            "night_actions": night_records,
            "inspections": inspections,
            "hunter_shots": hunter_shots,
            "eliminations": eliminations,
        },
        "metrics": metrics,
    }


def _build_run_summary(
    per_game_details: list[dict[str, Any]],
    run_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    overall_wins = {winner: 0 for winner in WINNER_KEYS}
    side_counters = {winner: RatioCounter() for winner in WINNER_KEYS}
    role_counters = {role: RatioCounter() for role in ALL_ROLE_KEYS}

    ratio_metric_names = (
        "witch_poison_accuracy",
        "witch_antidote_accuracy",
        "guard_protect_accuracy",
        "guard_effective_protect_rate",
        "seer_identify_accuracy",
        "hunter_shot_accuracy",
        "wolf_day_vote_accuracy",
        "good_day_vote_accuracy",
        "good_sheriff_vote_accuracy",
        "execution_hit_rate",
        "good_misexecution_rate",
        "wolf_survival_under_pressure_rate",
        "seer_info_conversion_rate",
        "early_elimination_rate",
    )
    aggregated_ratio_metrics = {metric_name: RatioCounter() for metric_name in ratio_metric_names}
    total_survival_days = 0
    total_players = 0

    for detail in per_game_details:
        winner = str(detail.get("game", {}).get("winner") or "").strip()
        if winner in overall_wins:
            overall_wins[winner] += 1

        for player_record in detail.get("players", []):
            side = str(player_record.get("side") or "").strip()
            role = str(player_record.get("role") or "").strip()
            won = bool(player_record.get("won"))
            if side in side_counters:
                side_counters[side].record(won)
            if role in role_counters:
                role_counters[role].record(won)

            total_players += 1
            total_survival_days += int(player_record.get("survival_days", 0) or 0)

        metrics = detail.get("metrics", {})
        for metric_name in ratio_metric_names:
            metric_data = metrics.get(metric_name, {})
            aggregated_ratio_metrics[metric_name].numerator += int(metric_data.get("numerator", 0) or 0)
            aggregated_ratio_metrics[metric_name].denominator += int(metric_data.get("denominator", 0) or 0)

    completed_games = len(per_game_details)
    overall_win_rate = {
        "completed_games": completed_games,
        "by_winner": {
            winner: {
                "wins": win_count,
                "rate": round(win_count / completed_games, 6) if completed_games else None,
            }
            for winner, win_count in overall_wins.items()
        },
    }

    role_win_rate = {
        role: counter.to_dict()
        for role, counter in role_counters.items()
        if counter.denominator > 0
    }

    return {
        "run_metadata": dict(run_metadata or {}),
        "games_evaluated": completed_games,
        "overall_win_rate": overall_win_rate,
        "side_win_rate": {
            side: counter.to_dict() for side, counter in side_counters.items()
        },
        "role_win_rate": role_win_rate,
        "skill_metrics": {
            "witch_poison_accuracy": aggregated_ratio_metrics["witch_poison_accuracy"].to_dict(),
            "witch_antidote_accuracy": aggregated_ratio_metrics["witch_antidote_accuracy"].to_dict(),
            "guard_protect_accuracy": aggregated_ratio_metrics["guard_protect_accuracy"].to_dict(),
            "guard_effective_protect_rate": aggregated_ratio_metrics["guard_effective_protect_rate"].to_dict(),
            "seer_identify_accuracy": aggregated_ratio_metrics["seer_identify_accuracy"].to_dict(),
            "hunter_shot_accuracy": aggregated_ratio_metrics["hunter_shot_accuracy"].to_dict(),
        },
        "vote_metrics": {
            "wolf_day_vote_accuracy": aggregated_ratio_metrics["wolf_day_vote_accuracy"].to_dict(),
            "good_day_vote_accuracy": aggregated_ratio_metrics["good_day_vote_accuracy"].to_dict(),
            "good_sheriff_vote_accuracy": aggregated_ratio_metrics["good_sheriff_vote_accuracy"].to_dict(),
            "execution_hit_rate": aggregated_ratio_metrics["execution_hit_rate"].to_dict(),
            "good_misexecution_rate": aggregated_ratio_metrics["good_misexecution_rate"].to_dict(),
            "wolf_survival_under_pressure_rate": aggregated_ratio_metrics["wolf_survival_under_pressure_rate"].to_dict(),
        },
        "information_and_survival_metrics": {
            "seer_info_conversion_rate": aggregated_ratio_metrics["seer_info_conversion_rate"].to_dict(),
            "avg_survival_days": {
                "total_survival_days": total_survival_days,
                "total_players": total_players,
                "average": round(total_survival_days / total_players, 6) if total_players else None,
            },
            "early_elimination_rate": aggregated_ratio_metrics["early_elimination_rate"].to_dict(),
        },
    }


def _summary_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    overall = summary.get("overall_win_rate", {})
    completed_games = int(overall.get("completed_games", 0) or 0)
    for winner, record in (overall.get("by_winner", {}) or {}).items():
        rows.append(
            {
                "group": "win",
                "metric": "overall_win_rate",
                "key": winner,
                "numerator": int(record.get("wins", 0) or 0),
                "denominator": completed_games,
                "value": record.get("rate"),
            }
        )

    for winner, record in (summary.get("side_win_rate", {}) or {}).items():
        rows.append(
            {
                "group": "win",
                "metric": "side_win_rate",
                "key": winner,
                "numerator": int(record.get("numerator", 0) or 0),
                "denominator": int(record.get("denominator", 0) or 0),
                "value": record.get("rate"),
            }
        )

    for role, record in (summary.get("role_win_rate", {}) or {}).items():
        rows.append(
            {
                "group": "win",
                "metric": "role_win_rate",
                "key": role,
                "numerator": int(record.get("numerator", 0) or 0),
                "denominator": int(record.get("denominator", 0) or 0),
                "value": record.get("rate"),
            }
        )

    for group_name in ("skill_metrics", "vote_metrics", "information_and_survival_metrics"):
        metric_group = summary.get(group_name, {}) or {}
        for metric_name, record in metric_group.items():
            if metric_name == "avg_survival_days":
                rows.append(
                    {
                        "group": "information_and_survival_metrics",
                        "metric": "avg_survival_days",
                        "key": "all_players",
                        "numerator": record.get("total_survival_days"),
                        "denominator": record.get("total_players"),
                        "value": record.get("average"),
                    }
                )
                continue

            rows.append(
                {
                    "group": group_name,
                    "metric": metric_name,
                    "key": "all",
                    "numerator": int(record.get("numerator", 0) or 0),
                    "denominator": int(record.get("denominator", 0) or 0),
                    "value": record.get("rate"),
                }
            )

    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(dict(payload), file, ensure_ascii=False, indent=2)
    return path


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["group", "metric", "key", "numerator", "denominator", "value"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


async def export_run_metrics(
    global_store: GlobalEventStore,
    game_contexts: Mapping[str, Mapping[str, str]],
    output_dir: str | Path,
    run_metadata: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Export per-game metric details and a multi-game summary."""

    base_dir = Path(output_dir)
    per_game_dir = base_dir / "per_game"
    per_game_dir.mkdir(parents=True, exist_ok=True)

    per_game_details: list[dict[str, Any]] = []
    per_game_paths: dict[str, str] = {}

    for game_id, players in game_contexts.items():
        events = await global_store.get_events_by_game_id(game_id)
        detail = _build_game_detail(game_id, players, events)
        detail_path = per_game_dir / f"{game_id}.json"
        _write_json(detail_path, detail)
        per_game_details.append(detail)
        per_game_paths[game_id] = str(detail_path)

    summary = _build_run_summary(per_game_details, run_metadata=run_metadata)
    summary_json_path = _write_json(base_dir / "summary.json", summary)
    summary_csv_path = _write_csv(base_dir / "summary.csv", _summary_rows(summary))

    manifest = {
        "output_dir": str(base_dir),
        "summary_json": str(summary_json_path),
        "summary_csv": str(summary_csv_path),
        "per_game_files": per_game_paths,
    }
    manifest_path = _write_json(base_dir / "manifest.json", manifest)

    return {
        "output_dir": str(base_dir),
        "summary_json": str(summary_json_path),
        "summary_csv": str(summary_csv_path),
        "manifest_json": str(manifest_path),
    }
