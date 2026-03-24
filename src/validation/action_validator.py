"""Validation helpers for model-generated action payloads."""

from __future__ import annotations

import random
from typing import Any, Dict

from src.enums import ActionType, GamePhase
from src.events.action import Action


TARGETED_ACTIONS = {
    ActionType.VOTE,
    ActionType.KILL,
    ActionType.INSPECT,
    ActionType.PROTECT,
    ActionType.POISON,
    ActionType.HEAL,
}


def validate_and_create_action(
    game_id: str,
    phase: str,
    actor: str,
    action_data: Dict[str, Any],
    alive_players: list[str] | None = None,
) -> Action:
    """Validate raw action data and create a normalized Action object."""
    action_type_str = str(action_data.get("action_type", "")).strip().lower()
    target = str(action_data.get("target", "")).strip()
    reasoning_summary = str(action_data.get("reasoning_summary", "")).strip()
    public_speech = str(action_data.get("public_speech", "")).strip()

    try:
        action_type = ActionType(action_type_str)
    except ValueError:
        action_type = ActionType.SPEAK if "day" in str(phase).lower() else ActionType.SKIP

    if action_type == ActionType.SPEAK and not public_speech:
        public_speech = "我先听听大家的想法。"

    if alive_players and action_type in TARGETED_ACTIONS:
        if target not in alive_players:
            valid_targets = [player_id for player_id in alive_players if player_id != actor]
            target = random.choice(valid_targets) if valid_targets else ""

    phase_enum = GamePhase(phase) if isinstance(phase, str) else phase
    phase_str = phase_enum.value if isinstance(phase_enum, GamePhase) else str(phase_enum)

    if "day" in phase_str and action_type == ActionType.SKIP:
        action_type = ActionType.SPEAK
        if not public_speech:
            public_speech = "我先听听大家的想法。"

    return Action(
        game_id=game_id,
        phase=phase_enum,
        visibility=["controller"],
        payload={
            "source": "agent_decision",
            "action_type": action_type.value,
            "target": target,
            "reasoning_summary": reasoning_summary,
            "public_speech": public_speech,
        },
        actor=actor,
        action_type=action_type,
        target=target,
        reasoning_summary=reasoning_summary,
        public_speech=public_speech,
    )


def validate_action_for_phase(
    action: Action,
    alive_players: list[str] | None = None,
) -> tuple[bool, str]:
    """Validate whether an action is legal for the current phase."""
    phase = str(action.phase).lower()

    if "day" in phase:
        if action.action_type == ActionType.SKIP:
            return False, "day phase does not allow skip"
        if action.action_type not in [ActionType.SPEAK, ActionType.VOTE]:
            return False, f"day phase does not support {action.action_type.value}"

    if alive_players and action.action_type in TARGETED_ACTIONS:
        if action.target not in alive_players:
            return False, f"target player {action.target} is not alive"

    return True, "ok"
