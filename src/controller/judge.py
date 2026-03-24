from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.enums import ActionType, GamePhase
from src.events.action import Action
from src.events.event import EventBase
from src.events.system_event import SystemEvent

GOD_ROLES = {"seer", "witch", "hunter", "guard"}


@dataclass
class GameState:
    game_id: str
    current_phase: GamePhase
    players: Dict[str, str]
    alive_players: List[str]
    seat_order: List[str]
    phase_votes: Dict[str, Dict[str, str]]
    inspection_results: Dict[str, str]
    protected_players: Dict[str, str]
    kills_pending: List[str]
    poisonings_pending: List[str]
    heals_pending: List[str]
    heal_used: Dict[str, bool]
    poison_used: Dict[str, bool]
    protection_used: Dict[str, bool]
    game_ended: bool = False
    winner: Optional[str] = None
    speaking_order: List[str] = field(default_factory=list)
    sheriff_id: Optional[str] = None
    badge_holder_id: Optional[str] = None
    badge_destroyed: bool = False
    sheriff_candidates: List[str] = field(default_factory=list)
    sheriff_votes: Dict[str, str] = field(default_factory=dict)
    current_subphase: str = "setup"
    last_guard_target_by_guard: Dict[str, Optional[str]] = field(default_factory=dict)
    night_actions_taken: Dict[str, str] = field(default_factory=dict)
    last_night_deaths: List[str] = field(default_factory=list)
    pending_first_day_last_words: List[str] = field(default_factory=list)
    pending_vote_last_words: List[str] = field(default_factory=list)
    pending_last_words_reasons: Dict[str, str] = field(default_factory=dict)
    day_resolution_complete: bool = False
    pending_badge_transfer_from: Optional[str] = None
    pending_badge_transfer_to: Optional[str] = None
    pending_badge_destroy_notice: bool = False


class Judge:
    FINAL_PHASES = {GamePhase.POST_GAME}

    def __init__(self) -> None:
        self._game_states: Dict[str, GameState] = {}

    def get_state(self, game_id: str) -> Optional[GameState]:
        return self._game_states.get(game_id)

    def initialize_game(self, game_id: str, players: Dict[str, str]) -> GameState:
        seat_order = list(players.keys())
        state = GameState(
            game_id=game_id,
            current_phase=GamePhase.SETUP,
            players=players,
            alive_players=seat_order[:],
            seat_order=seat_order[:],
            phase_votes={},
            inspection_results={},
            protected_players={},
            kills_pending=[],
            poisonings_pending=[],
            heals_pending=[],
            heal_used={player_id: False for player_id in players},
            poison_used={player_id: False for player_id in players},
            protection_used={player_id: False for player_id in players},
            speaking_order=seat_order[:],
            last_guard_target_by_guard={player_id: None for player_id in players},
        )
        self._game_states[game_id] = state
        return state

    def _is_day_phase(self, phase: GamePhase) -> bool:
        return phase.value.startswith("day_")

    def _is_night_phase(self, phase: GamePhase) -> bool:
        return phase.value.startswith("night_")

    def _prepare_day_state(self, state: GameState) -> None:
        state.speaking_order = [player_id for player_id in state.seat_order if player_id in state.alive_players]
        state.current_subphase = "daybreak"
        state.sheriff_candidates = []
        state.sheriff_votes = {}
        state.day_resolution_complete = False
        state.pending_vote_last_words = []

    def _prepare_night_state(self, state: GameState) -> None:
        state.protected_players = {}
        state.kills_pending = []
        state.poisonings_pending = []
        state.heals_pending = []
        state.protection_used = {player_id: False for player_id in state.players}
        state.night_actions_taken = {}
        state.last_night_deaths = []
        state.current_subphase = "guard"

    def _get_next_phase(self, current_phase: GamePhase) -> GamePhase:
        if current_phase == GamePhase.SETUP:
            return GamePhase.NIGHT_1
        phase_name, round_no_str = current_phase.value.split("_")
        round_no = int(round_no_str)
        if phase_name == "day":
            return GamePhase(f"night_{round_no + 1}")
        try:
            return GamePhase(f"day_{round_no}")
        except ValueError:
            return GamePhase.POST_GAME

    def _choose_badge_successor(self, state: GameState, departed_player: str) -> Optional[str]:
        if departed_player not in state.seat_order:
            return next(iter(state.alive_players), None)
        departed_index = state.seat_order.index(departed_player)
        for offset in range(1, len(state.seat_order) + 1):
            candidate = state.seat_order[(departed_index + offset) % len(state.seat_order)]
            if candidate in state.alive_players:
                return candidate
        return None

    def _handle_badge_departure(
        self,
        state: GameState,
        departed_player: str,
        visibility: List[str],
        events: List[EventBase],
    ) -> None:
        if state.badge_holder_id != departed_player:
            return
        state.sheriff_id = None
        state.badge_holder_id = None
        state.badge_destroyed = False
        state.pending_badge_transfer_from = departed_player
        state.pending_badge_transfer_to = None
        state.pending_badge_destroy_notice = False
        events.append(
            SystemEvent(
                game_id=state.game_id,
                phase=state.current_phase,
                visibility=["controller"],
                payload={"from_player": departed_player, "visibility": visibility},
                system_name="badge_transfer_pending",
            )
        )

    def finalize_badge_transfer(
        self,
        state: GameState,
        from_player: str,
        target_player: Optional[str],
    ) -> List[EventBase]:
        state.pending_badge_transfer_from = None
        state.pending_badge_transfer_to = None
        state.pending_badge_destroy_notice = False

        if target_player and target_player in state.alive_players and target_player != from_player:
            state.sheriff_id = target_player
            state.badge_holder_id = target_player
            state.badge_destroyed = False
            return [
                SystemEvent(
                    game_id=state.game_id,
                    phase=state.current_phase,
                    visibility=["all"],
                    payload={
                        "from_player": from_player,
                        "to_player": target_player,
                        "badge_holder": target_player,
                    },
                    system_name="badge_transferred",
                )
            ]

        state.sheriff_id = None
        state.badge_holder_id = None
        state.badge_destroyed = True
        return [
            SystemEvent(
                game_id=state.game_id,
                phase=state.current_phase,
                visibility=["all"],
                payload={"departed_player": from_player},
                system_name="badge_destroyed",
            )
        ]

    def validate_action(self, action: Action, state: GameState) -> tuple[bool, str]:
        if action.actor not in state.players:
            return False, "player does not exist"
        if action.actor not in state.alive_players and state.current_subphase != "last_words":
            return False, "dead player cannot act"
        if self._is_day_phase(state.current_phase):
            if state.current_subphase in {"discussion", "sheriff_campaign", "last_words"}:
                return (action.action_type == ActionType.SPEAK, "current subphase only allows speak")
            if state.current_subphase in {"voting", "sheriff_voting"}:
                if action.action_type != ActionType.VOTE or not action.target or action.target == action.actor:
                    return False, "current subphase only allows valid vote"
                if state.current_subphase == "sheriff_voting" and action.target not in state.sheriff_candidates:
                    return False, "sheriff vote target must be a candidate"
                if state.current_subphase == "voting" and action.target not in state.alive_players:
                    return False, "cannot vote for dead player"
                return True, ""
            return action.action_type in [ActionType.SPEAK, ActionType.VOTE], "day phase only allows speak or vote"
        role = state.players[action.actor]
        already_acted = action.actor in state.night_actions_taken
        if role == "werewolf":
            valid = not already_acted and action.action_type == ActionType.KILL and action.target in state.alive_players and action.target != action.actor and state.players.get(action.target) != "werewolf"
            return valid, "werewolf can only kill another alive non-werewolf"
        if role == "seer":
            valid = not already_acted and action.action_type == ActionType.INSPECT and action.target in state.alive_players and action.target != action.actor
            return valid, "seer can only inspect another alive player"
        if role == "guard":
            valid = not already_acted and action.action_type == ActionType.PROTECT and action.target in state.alive_players and state.last_guard_target_by_guard.get(action.actor) != action.target
            return valid, "guard can only protect a valid alive target and cannot repeat"
        if role == "witch":
            if already_acted or action.action_type not in [ActionType.HEAL, ActionType.POISON, ActionType.SKIP]:
                return False, "witch can only act once with heal, poison, or skip"
            if action.action_type == ActionType.HEAL:
                return (not state.heal_used.get(action.actor, False) and action.target in state.kills_pending), "witch can only heal tonight's attacked player"
            if action.action_type == ActionType.POISON:
                return (not state.poison_used.get(action.actor, False) and action.target in state.alive_players and action.target != action.actor), "witch poison target must be another alive player"
            return True, ""
        return action.action_type == ActionType.SKIP, f"{role} can only skip at night"

    def process_action(self, action: Action, state: GameState) -> List[EventBase]:
        is_valid, error_msg = self.validate_action(action, state)
        if not is_valid:
            return [
                SystemEvent(
                    game_id=action.game_id,
                    phase=state.current_phase,
                    visibility=["controller"],
                    payload={"error": error_msg, "action_id": action.event_id},
                    system_name="action_validation_failed",
                )
            ]

        if action.action_type == ActionType.VOTE:
            if state.current_subphase == "sheriff_voting":
                state.sheriff_votes[action.actor] = action.target
                return [
                    SystemEvent(
                        game_id=action.game_id,
                        phase=state.current_phase,
                        visibility=["all"],
                        payload={"voter": action.actor, "target": action.target},
                        system_name="sheriff_vote_recorded",
                    )
                ]

            state.phase_votes.setdefault(action.phase.value, {})
            state.phase_votes[action.phase.value][action.actor] = action.target
            return [
                SystemEvent(
                    game_id=action.game_id,
                    phase=state.current_phase,
                    visibility=["all"],
                    payload={"message": f"{action.actor} voted for {action.target}", "voter": action.actor, "target": action.target},
                    system_name="vote_recorded",
                )
            ]

        if action.action_type == ActionType.INSPECT:
            target_role = state.players[action.target]
            state.inspection_results[action.actor] = target_role
            state.night_actions_taken[action.actor] = action.action_type.value
            return [
                SystemEvent(
                    game_id=action.game_id,
                    phase=state.current_phase,
                    visibility=[action.actor],
                    payload={"result": f"{action.target} is {target_role}", "target": action.target, "role": target_role},
                    system_name="inspection_result",
                )
            ]

        if action.action_type == ActionType.KILL:
            state.kills_pending = [action.target]
            state.night_actions_taken[action.actor] = action.action_type.value
            return [
                SystemEvent(
                    game_id=action.game_id,
                    phase=state.current_phase,
                    visibility=["controller"],
                    payload={"killer": action.actor, "target": action.target},
                    system_name="kill_attempted",
                )
            ]

        if action.action_type == ActionType.PROTECT:
            state.protection_used[action.actor] = True
            state.protected_players[action.target] = action.actor
            state.last_guard_target_by_guard[action.actor] = action.target
            state.night_actions_taken[action.actor] = action.action_type.value
            return [
                SystemEvent(
                    game_id=action.game_id,
                    phase=state.current_phase,
                    visibility=["controller"],
                    payload={"guard": action.actor, "protected_player": action.target},
                    system_name="protection_used",
                )
            ]

        if action.action_type == ActionType.POISON:
            state.poisonings_pending.append(action.target)
            state.poison_used[action.actor] = True
            state.night_actions_taken[action.actor] = action.action_type.value
            return [
                SystemEvent(
                    game_id=action.game_id,
                    phase=state.current_phase,
                    visibility=["controller"],
                    payload={"witch": action.actor, "poisoned_player": action.target},
                    system_name="poison_used",
                )
            ]

        if action.action_type == ActionType.HEAL:
            state.heals_pending.append(action.target)
            state.heal_used[action.actor] = True
            state.night_actions_taken[action.actor] = action.action_type.value
            return [
                SystemEvent(
                    game_id=action.game_id,
                    phase=state.current_phase,
                    visibility=["controller"],
                    payload={"witch": action.actor, "healed_player": action.target},
                    system_name="heal_used",
                )
            ]

        if action.action_type == ActionType.SPEAK:
            content = action.public_speech.strip() or "我先听听大家的想法。"
            return [
                SystemEvent(
                    game_id=action.game_id,
                    phase=state.current_phase,
                    visibility=["all"],
                    payload={"speaker": action.actor, "content": content},
                    system_name="speech_delivered",
                )
            ]

        if self._is_night_phase(state.current_phase):
            state.night_actions_taken[action.actor] = action.action_type.value
        return [
            SystemEvent(
                game_id=action.game_id,
                phase=state.current_phase,
                visibility=["controller"],
                payload={"actor": action.actor, "action_type": action.action_type.value},
                system_name="action_skipped",
            )
        ]

    def count_votes(self, state: GameState) -> Dict[str, int]:
        votes = state.phase_votes.get(state.current_phase.value, {})
        counts = {player_id: 0 for player_id in state.alive_players}
        for target in votes.values():
            if target in counts:
                counts[target] += 1
        return counts

    def count_sheriff_votes(self, state: GameState) -> Dict[str, int]:
        counts = {player_id: 0 for player_id in state.sheriff_candidates}
        for target in state.sheriff_votes.values():
            if target in counts:
                counts[target] += 1
        return counts

    def eliminate_player(self, state: GameState, player_to_eliminate: str, *, reason: str = "eliminated", visibility: Optional[List[str]] = None) -> List[EventBase]:
        events: List[EventBase] = []
        event_visibility = visibility or ["all"]
        if player_to_eliminate not in state.alive_players:
            return [
                SystemEvent(
                    game_id=state.game_id,
                    phase=state.current_phase,
                    visibility=["controller"],
                    payload={"message": f"Attempted to eliminate {player_to_eliminate} who is not alive", "player_id": player_to_eliminate},
                    system_name="elimination_failed",
                )
            ]

        state.alive_players.remove(player_to_eliminate)
        events.append(
            SystemEvent(
                game_id=state.game_id,
                phase=state.current_phase,
                visibility=event_visibility,
                payload={"message": f"{player_to_eliminate} was {reason}", "eliminated_player": player_to_eliminate, "reason": reason},
                system_name="player_eliminated",
            )
        )
        self._handle_badge_departure(state, player_to_eliminate, event_visibility, events)
        return events

    def resolve_sheriff_election(self, state: GameState) -> List[EventBase]:
        vote_counts = self.count_sheriff_votes(state)
        events: List[EventBase] = [
            SystemEvent(
                game_id=state.game_id,
                phase=state.current_phase,
                visibility=["all"],
                payload={"vote_counts": vote_counts, "candidates": state.sheriff_candidates},
                system_name="sheriff_vote_count_completed",
            )
        ]
        if not state.sheriff_candidates or not vote_counts:
            state.sheriff_id = None
            state.badge_holder_id = None
            state.sheriff_votes = {}
            events.append(
                SystemEvent(
                    game_id=state.game_id,
                    phase=state.current_phase,
                    visibility=["all"],
                    payload={"message": "No sheriff elected"},
                    system_name="sheriff_vacant",
                )
            )
            return events

        max_votes = max(vote_counts.values())
        winners = [player_id for player_id, votes in vote_counts.items() if votes == max_votes]
        if max_votes == 0 or len(winners) != 1:
            state.sheriff_id = None
            state.badge_holder_id = None
            state.sheriff_votes = {}
            events.append(
                SystemEvent(
                    game_id=state.game_id,
                    phase=state.current_phase,
                    visibility=["all"],
                    payload={"tied_candidates": winners, "votes": max_votes},
                    system_name="sheriff_election_tied",
                )
            )
            return events

        sheriff_id = winners[0]
        state.sheriff_id = sheriff_id
        state.badge_holder_id = sheriff_id
        state.badge_destroyed = False
        state.sheriff_votes = {}
        events.append(
            SystemEvent(
                game_id=state.game_id,
                phase=state.current_phase,
                visibility=["all"],
                payload={"sheriff": sheriff_id, "badge_holder": sheriff_id},
                system_name="sheriff_elected",
            )
        )
        return events

    def check_victory_conditions(self, state: GameState) -> tuple[Optional[str], bool]:
        werewolves_alive = [player_id for player_id in state.alive_players if state.players[player_id] == "werewolf"]
        villagers_alive = [player_id for player_id in state.alive_players if state.players[player_id] == "villager"]
        gods_alive = [player_id for player_id in state.alive_players if state.players[player_id] in GOD_ROLES]
        if not werewolves_alive:
            return "villagers", True
        if not villagers_alive or not gods_alive:
            return "werewolves", True
        return None, False

    def _resolve_post_game_outcome(self, state: GameState) -> tuple[str, str]:
        winner, game_ended = self.check_victory_conditions(state)
        if game_ended and winner:
            return winner, "standard_victory"
        surviving_werewolves = [player_id for player_id in state.alive_players if state.players.get(player_id) == "werewolf"]
        if surviving_werewolves:
            return "werewolves", "post_game_fallback_werewolves"
        return "villagers", "post_game_fallback_villagers"

    def _finalize_post_game(self, state: GameState, events: List[EventBase], previous_phase: GamePhase) -> List[EventBase]:
        winner, resolution_reason = self._resolve_post_game_outcome(state)
        state.current_phase = GamePhase.POST_GAME
        state.current_subphase = "post_game"
        state.game_ended = True
        state.winner = winner
        events.append(
            SystemEvent(
                game_id=state.game_id,
                phase=GamePhase.POST_GAME,
                visibility=["all"],
                payload={"message": "Entered POST_GAME and forced finalization", "previous_phase": previous_phase.value, "resolution_reason": resolution_reason, "alive_players": state.alive_players},
                system_name="post_game_finalization_started",
            )
        )
        events.append(
            SystemEvent(
                game_id=state.game_id,
                phase=GamePhase.POST_GAME,
                visibility=["all"],
                payload={"message": f"Game ended. Winner: {state.winner}", "winner": state.winner, "resolution_reason": resolution_reason, "final_alive_players": state.alive_players},
                system_name="game_ended",
            )
        )
        return events

    def advance_phase(self, game_id: str) -> List[EventBase]:
        state = self._game_states[game_id]
        current_phase = state.current_phase
        events: List[EventBase] = [
            SystemEvent(
                game_id=game_id,
                phase=current_phase,
                visibility=["all"],
                payload={"message": f"Starting phase processing for {current_phase.value}", "current_phase": current_phase.value, "alive_players": state.alive_players},
                system_name="phase_processing_started",
            )
        ]

        if current_phase in self.FINAL_PHASES:
            return self._finalize_post_game(state, events, current_phase)

        if self._is_day_phase(current_phase):
            if not state.day_resolution_complete:
                state.current_subphase = "vote_resolution"
                vote_counts = self.count_votes(state)
                if vote_counts:
                    events.append(SystemEvent(game_id=game_id, phase=current_phase, visibility=["all"], payload={"message": f"Vote counts: {vote_counts}", "vote_counts": vote_counts}, system_name="vote_count_completed"))
                    max_votes = max(vote_counts.values())
                    players_with_max_votes = [player_id for player_id, votes in vote_counts.items() if votes == max_votes]
                    if max_votes == 0 or len(players_with_max_votes) > 1:
                        events.append(SystemEvent(game_id=game_id, phase=current_phase, visibility=["all"], payload={"message": f"No elimination due to tie votes: {players_with_max_votes}", "tied_players": players_with_max_votes, "votes": max_votes}, system_name="tie_no_elimination"))
                    else:
                        eliminated_player = players_with_max_votes[0]
                        events.extend(self.eliminate_player(state, eliminated_player, reason="eliminated by vote", visibility=["all"]))
                        state.pending_vote_last_words = [eliminated_player]
                        state.pending_last_words_reasons[eliminated_player] = "vote_elimination"
                        state.current_subphase = "last_words"
                        events.append(
                            SystemEvent(
                                game_id=game_id,
                                phase=current_phase,
                                visibility=["all"],
                                payload={"speakers": state.pending_vote_last_words[:], "reason": "vote_elimination"},
                                system_name="last_words_pending",
                            )
                        )
                else:
                    events.append(SystemEvent(game_id=game_id, phase=current_phase, visibility=["all"], payload={"message": "No votes recorded in this phase"}, system_name="no_votes_recorded"))

                state.phase_votes[current_phase.value] = {}
                state.day_resolution_complete = True

                if state.pending_vote_last_words:
                    winner, game_ended = self.check_victory_conditions(state)
                    if game_ended:
                        state.winner = winner
                    return events

        elif self._is_night_phase(current_phase):
            state.current_subphase = "resolve_night"
            night_deaths: List[str] = []

            for heal_target in list(dict.fromkeys(state.heals_pending)):
                if heal_target in state.kills_pending:
                    state.kills_pending.remove(heal_target)
                    events.append(SystemEvent(game_id=game_id, phase=current_phase, visibility=["controller"], payload={"saved_player": heal_target}, system_name="heal_success"))

            for poison_target in list(dict.fromkeys(state.poisonings_pending)):
                if poison_target in state.alive_players:
                    events.extend(self.eliminate_player(state, poison_target, reason="night death", visibility=["controller"]))
                    night_deaths.append(poison_target)

            for kill_target in list(dict.fromkeys(state.kills_pending)):
                if kill_target not in state.alive_players:
                    continue
                if kill_target in state.protected_players:
                    events.append(SystemEvent(game_id=game_id, phase=current_phase, visibility=["controller"], payload={"attacked_player": kill_target, "guard": state.protected_players[kill_target]}, system_name="attack_protected"))
                    continue
                events.extend(self.eliminate_player(state, kill_target, reason="night death", visibility=["controller"]))
                night_deaths.append(kill_target)

            state.last_night_deaths = night_deaths[:]
            if current_phase == GamePhase.NIGHT_1:
                state.pending_first_day_last_words = night_deaths[:]
                for player_id in night_deaths:
                    state.pending_last_words_reasons[player_id] = "first_night_death"
            events.append(SystemEvent(game_id=game_id, phase=current_phase, visibility=["controller"], payload={"deaths": night_deaths}, system_name="night_resolution_completed"))
            state.kills_pending.clear()
            state.poisonings_pending.clear()
            state.heals_pending.clear()
            state.night_actions_taken = {}

        winner, game_ended = self.check_victory_conditions(state)
        if game_ended:
            state.winner = winner
            return self._finalize_post_game(state, events, current_phase)

        next_phase = self._get_next_phase(current_phase)
        state.current_phase = next_phase
        if self._is_day_phase(next_phase):
            self._prepare_day_state(state)
        elif self._is_night_phase(next_phase):
            self._prepare_night_state(state)

        events.append(SystemEvent(game_id=game_id, phase=state.current_phase, visibility=["all"], payload={"message": f"Phase advanced to {state.current_phase.value}", "new_phase": state.current_phase.value, "previous_phase": current_phase.value, "subphase": state.current_subphase}, system_name="phase_advanced"))
        if next_phase in self.FINAL_PHASES:
            return self._finalize_post_game(state, events, current_phase)
        events.append(SystemEvent(game_id=game_id, phase=state.current_phase, visibility=["all"], payload={"message": f"Completed phase processing for {current_phase.value}, now in {state.current_phase.value}", "current_phase": state.current_phase.value, "previous_phase": current_phase.value, "alive_players": state.alive_players}, system_name="phase_processing_completed"))
        return events

    def get_alive_players(self, game_id: str) -> List[str]:
        state = self._game_states.get(game_id)
        return state.alive_players[:] if state else []

    def get_game_status(self, game_id: str) -> Dict:
        state = self._game_states.get(game_id)
        if not state:
            return {}
        return {
            "game_id": state.game_id,
            "current_phase": state.current_phase.value,
            "current_subphase": state.current_subphase,
            "alive_players_count": len(state.alive_players),
            "alive_players": state.alive_players,
            "total_players": len(state.players),
            "game_ended": state.game_ended,
            "winner": state.winner,
            "sheriff_id": state.sheriff_id,
            "badge_holder_id": state.badge_holder_id,
            "pending_first_day_last_words": state.pending_first_day_last_words,
            "pending_vote_last_words": state.pending_vote_last_words,
            "pending_badge_transfer_from": state.pending_badge_transfer_from,
        }
