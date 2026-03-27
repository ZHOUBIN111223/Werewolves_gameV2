"""Validation helpers for model-generated action payloads."""

from __future__ import annotations

import random
from typing import Any

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

GENERIC_SPEECH_MARKERS = (
    "我先听听大家的想法",
    "我先听大家的发言",
    "再给出判断",
    "继续观察",
    "先听发言",
)


def _build_safe_public_speech(alive_players: list[str] | None, actor: str) -> str:
    """生成安全兜底发言：保持自然，并把重心放在可继续回应的玩家上。"""
    other_alive_players = [
        player_id for player_id in (alive_players or []) if player_id != actor
    ]
    if other_alive_players:
        players_text = "、".join(other_alive_players)
        return (
            "我会继续结合前面的发言、投票和夜间结果盘逻辑。"
            f"现在场上还能继续回应的人有{players_text}，我更想听他们怎么解释关键轮次的站边和票型。"
        )
    return "我会继续结合前面的发言、投票和夜间结果盘逻辑，再看场上解释是否前后一致。"


def _looks_generic_speech(public_speech: str) -> bool:
    """判断发言是否过于泛泛/空洞（用于触发兜底纠偏）。"""
    normalized_text = public_speech.replace(" ", "")
    if len(normalized_text) < 10:
        return True
    return any(marker in normalized_text for marker in GENERIC_SPEECH_MARKERS)


def normalize_public_speech(
    public_speech: str,
    alive_players: list[str] | None,
    actor: str,
) -> str:
    """Conservatively normalize empty or空洞发言，保留自然的复盘内容。"""
    if not public_speech or _looks_generic_speech(public_speech):
        return _build_safe_public_speech(alive_players, actor)

    return public_speech


def validate_and_create_action(
    game_id: str,
    phase: str,
    actor: str,
    action_data: dict[str, Any],
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

    if alive_players and action_type in TARGETED_ACTIONS:
        if target not in alive_players:
            valid_targets = [player_id for player_id in alive_players if player_id != actor]
            target = random.choice(valid_targets) if valid_targets else ""

    phase_enum = GamePhase(phase) if isinstance(phase, str) else phase

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
