"""Agent private memory storage."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.events.event import EventBase
from src.events.system_event import SystemEvent

SUMMARY_MAX_PHASE_LINES = 12
SUMMARY_MAX_PHASE_SUMMARIES = 6
SUMMARY_MAX_KEY_FACTS = 12
SUMMARY_MAX_CLAIMS = 8
SUMMARY_MAX_OPEN_QUESTIONS = 6
SUMMARY_MAX_RECENT_SPEECHES = 8


def _trim_text(value: str, max_length: int = 140) -> str:
    """Collapse whitespace and keep summary lines compact."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1].rstrip()}..."


def _dedupe_keep_order(items: list[str], *, limit: int | None = None) -> list[str]:
    """Deduplicate string items while preserving the latest useful order."""
    merged: list[str] = []
    for item in items:
        normalized = str(item or "").strip()
        if not normalized or normalized in merged:
            continue
        merged.append(normalized)
    if limit is None or len(merged) <= limit:
        return merged
    return merged[-limit:]


@dataclass(slots=True)
class MemoryItem:
    """Single long-term memory item."""

    memory_type: str
    content: str
    game_id: str
    phase: str
    role: str
    confidence: float = 1.0
    tags: list[str] = field(default_factory=list)
    item_id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """Convert to a serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryItem":
        """Restore from a dictionary."""
        return cls(**data)


@dataclass(slots=True)
class ReflectionArtifact:
    """Structured post-game reflection result."""

    mistakes: list[str]
    correct_reads: list[str]
    useful_signals: list[str]
    bad_patterns: list[str]
    strategy_rules: list[str]
    confidence: float
    source: str = "model"
    fallback_reason: str = ""

    def to_memory_items(self, game_id: str, phase: str, role: str) -> list[MemoryItem]:
        """Convert reusable reflection rules into long-term memory items."""
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
        for pattern in self.bad_patterns:
            items.append(
                MemoryItem(
                    memory_type="reflection",
                    content=f"避免: {pattern}",
                    game_id=game_id,
                    phase=phase,
                    role=role,
                    confidence=self.confidence,
                    tags=["anti_pattern", role],
                )
            )
        return items


@dataclass(slots=True)
class SummarySpeech:
    """Recent speech excerpt used by the summary memory system."""

    speaker: str
    phase: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SummarySpeech":
        return cls(**data)


@dataclass(slots=True)
class PhaseSummary:
    """Summary snapshot for one completed phase."""

    phase: str
    summary_lines: list[str] = field(default_factory=list)
    item_id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhaseSummary":
        return cls(**data)


@dataclass(slots=True)
class GameSummary:
    """Persistent per-game summary state."""

    game_id: str
    current_phase: str = ""
    current_request_kind: str = ""
    alive_players: list[str] = field(default_factory=list)
    current_focus: list[str] = field(default_factory=list)
    key_facts: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    recent_speeches: list[SummarySpeech] = field(default_factory=list)
    pending_phase_lines: list[str] = field(default_factory=list)
    phase_summaries: list[PhaseSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "current_phase": self.current_phase,
            "current_request_kind": self.current_request_kind,
            "alive_players": list(self.alive_players),
            "current_focus": list(self.current_focus),
            "key_facts": list(self.key_facts),
            "claims": list(self.claims),
            "open_questions": list(self.open_questions),
            "recent_speeches": [speech.to_dict() for speech in self.recent_speeches],
            "pending_phase_lines": list(self.pending_phase_lines),
            "phase_summaries": [summary.to_dict() for summary in self.phase_summaries],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GameSummary":
        return cls(
            game_id=str(data.get("game_id", "")).strip(),
            current_phase=str(data.get("current_phase", "")).strip(),
            current_request_kind=str(data.get("current_request_kind", "")).strip(),
            alive_players=[str(item) for item in data.get("alive_players", []) if item],
            current_focus=[str(item) for item in data.get("current_focus", []) if item],
            key_facts=[str(item) for item in data.get("key_facts", []) if item],
            claims=[str(item) for item in data.get("claims", []) if item],
            open_questions=[str(item) for item in data.get("open_questions", []) if item],
            recent_speeches=[
                SummarySpeech.from_dict(item)
                for item in data.get("recent_speeches", [])
                if isinstance(item, dict)
            ],
            pending_phase_lines=[str(item) for item in data.get("pending_phase_lines", []) if item],
            phase_summaries=[
                PhaseSummary.from_dict(item)
                for item in data.get("phase_summaries", [])
                if isinstance(item, dict)
            ],
        )


class AgentMemoryStore:
    """Store long-term strategy memory plus per-game summary memory."""

    ROLE_CLAIM_PATTERNS = {
        "seer": re.compile(r"(我是|我就是|我为|跳|起跳).{0,4}(预言家)"),
        "witch": re.compile(r"(我是|我就是|我为|跳|起跳).{0,4}(女巫)"),
        "guard": re.compile(r"(我是|我就是|我为|跳|起跳).{0,4}(守卫)"),
        "hunter": re.compile(r"(我是|我就是|我为|跳|起跳).{0,4}(猎人)"),
        "villager": re.compile(r"(我是|我就是|我为).{0,4}(村民)"),
        "werewolf": re.compile(r"(我是|我就是|我为).{0,4}(狼人)"),
    }

    def __init__(self, root_dir: str | Path, agent_id: str) -> None:
        """Create and initialize the agent memory files."""
        self.agent_id = agent_id
        agent_dir = Path(root_dir) / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = agent_dir / "memory.json"
        self.summary_file_path = agent_dir / "summary_memory.json"
        self._summary_cache: dict[str, GameSummary] | None = None
        self._summary_dirty = False
        if not self.file_path.exists():
            self.file_path.write_text("[]", encoding="utf-8")
        if not self.summary_file_path.exists():
            self.summary_file_path.write_text('{"games": {}}', encoding="utf-8")

    def append(self, item: MemoryItem) -> None:
        """Append one long-term memory item."""
        items = self._load_raw()
        items.append(item.to_dict())
        self._save_raw(items)

    def append_many(self, items: list[MemoryItem]) -> None:
        """Append long-term memory items in batch."""
        raw = self._load_raw()
        raw.extend(item.to_dict() for item in items)
        self._save_raw(raw)

    def read_all(self) -> list[MemoryItem]:
        """Read all long-term memory items."""
        return [MemoryItem.from_dict(item) for item in self._load_raw()]

    def recent(self, limit: int = 5, memory_types: list[str] | None = None) -> list[MemoryItem]:
        """Read recent long-term memories, optionally filtered by type."""
        items = self.read_all()
        if memory_types:
            items = [item for item in items if item.memory_type in memory_types]
        return items[-limit:]

    def append_summary_note(
        self,
        game_id: str,
        phase: str,
        content: str,
        *,
        note_type: str,
    ) -> None:
        """Append a compact note to the current game's summary state."""
        if not game_id or not str(content or "").strip():
            return
        summaries = self._load_summary_games()
        summary = summaries.setdefault(game_id, GameSummary(game_id=game_id))
        self._roll_phase(summary, phase)
        line = f"{note_type}: {_trim_text(content)}"
        self._append_phase_line(summary, line)
        if note_type == "hypothesis":
            summary.open_questions = _dedupe_keep_order(
                [*summary.open_questions, _trim_text(content)],
                limit=SUMMARY_MAX_OPEN_QUESTIONS,
            )
        summaries[game_id] = summary
        self._save_summary_games(summaries, force=True)

    def record_event(self, event: EventBase) -> None:
        """Update per-game summary memory from one visible event."""
        if not event.game_id:
            return

        phase = self._phase_to_str(event.phase)
        summaries = self._load_summary_games()
        summary = summaries.setdefault(event.game_id, GameSummary(game_id=event.game_id))
        self._roll_phase(summary, phase)

        payload = getattr(event, "payload", {}) or {}
        self._maybe_update_alive_players(summary, payload)

        if isinstance(event, SystemEvent):
            self._record_system_event(summary, phase, event.system_name, payload)

        summaries[event.game_id] = summary
        should_flush = isinstance(event, SystemEvent) and self._should_flush_summary(event.system_name)
        self._save_summary_games(summaries, force=should_flush)

    def retrieve_speech_content(self, game_id: str, phase: str, limit: int = 10) -> list[MemoryItem]:
        """Compatibility helper for legacy callers that want current-game speech context."""
        speeches = self.retrieve_recent_speeches(game_id=game_id, limit=limit)
        if not phase:
            return speeches
        filtered = [item for item in speeches if item.phase == phase]
        return filtered[-limit:]

    def retrieve_recent_speeches(self, game_id: str, limit: int = 8) -> list[MemoryItem]:
        """Return recent in-game speeches as prompt-ready memory items."""
        if limit <= 0:
            return []
        summary = self._load_summary_games().get(game_id)
        if not summary:
            return []
        items: list[MemoryItem] = []
        for speech in summary.recent_speeches[-limit:]:
            items.append(
                MemoryItem(
                    memory_type="speech",
                    content=speech.content,
                    game_id=game_id,
                    phase=speech.phase,
                    role=speech.speaker,
                    confidence=1.0,
                    tags=["speech", "discussion"],
                )
            )
        return items

    def retrieve_summary_memories(
        self,
        game_id: str,
        *,
        limit: int = 10,
        include_open_questions: bool = True,
        include_focus: bool = True,
    ) -> list[MemoryItem]:
        """Build prompt-ready summary memories for the current game only."""
        if limit <= 0:
            return []

        summary = self._load_summary_games().get(game_id)
        if not summary:
            return []

        lines: list[str] = []
        if include_focus and summary.current_focus:
            lines.extend(f"当前任务: {item}" for item in summary.current_focus)
        if summary.alive_players:
            lines.append(f"当前存活玩家: {', '.join(summary.alive_players)}")
        if summary.current_request_kind:
            lines.append(f"当前请求类型: {summary.current_request_kind}")
        lines.extend(f"身份声明: {item}" for item in summary.claims[-4:])
        lines.extend(f"关键事实: {item}" for item in summary.key_facts[-5:])
        for phase_summary in summary.phase_summaries[-2:]:
            if not phase_summary.summary_lines:
                continue
            merged = "；".join(phase_summary.summary_lines[:4])
            lines.append(f"{phase_summary.phase} 摘要: {merged}")
        lines.extend(f"本阶段线索: {item}" for item in summary.pending_phase_lines[-3:])
        if include_open_questions:
            lines.extend(f"待确认: {item}" for item in summary.open_questions[-3:])

        prompt_lines = _dedupe_keep_order(lines, limit=limit)
        return [
            MemoryItem(
                memory_type="summary",
                content=line,
                game_id=game_id,
                phase=summary.current_phase or "",
                role=self.agent_id,
                confidence=1.0,
                tags=["summary"],
            )
            for line in prompt_lines
        ]

    def retrieve_reflection_memories(
        self,
        game_id: str,
        *,
        role: str,
        limit_summary_items: int,
        limit_strategy_rules: int,
    ) -> list[MemoryItem]:
        """Return compact summary context plus reusable strategy rules for reflection."""
        summary_items = self.retrieve_summary_memories(
            game_id,
            limit=max(limit_summary_items, 0),
            include_open_questions=False,
            include_focus=False,
        )
        strategy_rules = self.retrieve_strategy_rules(role=role, limit=max(limit_strategy_rules, 0))
        selected_ids = {item.item_id for item in summary_items}
        for item in strategy_rules:
            if item.item_id not in selected_ids:
                summary_items.append(item)
                selected_ids.add(item.item_id)
        return summary_items

    def retrieve_strategy_rules(self, role: str, limit: int = 3) -> list[MemoryItem]:
        """Retrieve reusable strategy rules for the given role."""
        items = [
            item
            for item in self.read_all()
            if (
                item.memory_type == "reflection"
                or "strategy_rule" in item.tags
                or "anti_pattern" in item.tags
            )
            and (item.role == role or role in item.tags)
        ]
        items.sort(key=lambda item: (item.confidence, item.item_id), reverse=True)
        return items[:limit]

    def append_speech(self, content: str, game_id: str, phase: str, speaker: str) -> None:
        """Compatibility helper used by legacy evaluation tools."""
        if not content or not game_id:
            return
        summaries = self._load_summary_games()
        summary = summaries.setdefault(game_id, GameSummary(game_id=game_id))
        self._roll_phase(summary, phase)
        self._record_speech(summary, phase, speaker, content)
        summaries[game_id] = summary
        self._save_summary_games(summaries, force=True)

    def _record_system_event(
        self,
        summary: GameSummary,
        phase: str,
        system_name: str,
        payload: dict[str, Any],
    ) -> None:
        if system_name == "action_requested":
            request_kind = str(payload.get("request_kind", "")).strip()
            summary.current_request_kind = request_kind
            focus_line = self._request_focus_line(request_kind, payload)
            if focus_line:
                summary.current_focus = [focus_line]
            return

        if system_name == "speech_delivered":
            self._record_speech(
                summary,
                phase,
                str(payload.get("speaker", "")).strip(),
                str(payload.get("content", "")).strip(),
            )
            return

        line = self._system_event_to_line(system_name, payload)
        if line:
            self._append_phase_line(summary, line)
            if self._promote_to_key_fact(system_name):
                summary.key_facts = _dedupe_keep_order(
                    [*summary.key_facts, line],
                    limit=SUMMARY_MAX_KEY_FACTS,
                )

    def _record_speech(self, summary: GameSummary, phase: str, speaker: str, content: str) -> None:
        if not speaker or not content:
            return
        compact_content = _trim_text(content, max_length=180)
        summary.recent_speeches.append(
            SummarySpeech(
                speaker=speaker,
                phase=phase,
                content=compact_content,
            )
        )
        summary.recent_speeches = summary.recent_speeches[-SUMMARY_MAX_RECENT_SPEECHES:]
        self._append_phase_line(summary, f"{speaker} 发言: {compact_content}")

        claim = self._extract_role_claim(speaker, compact_content)
        if claim:
            summary.claims = _dedupe_keep_order(
                [*summary.claims, claim],
                limit=SUMMARY_MAX_CLAIMS,
            )

    def _extract_role_claim(self, speaker: str, content: str) -> str:
        for role, pattern in self.ROLE_CLAIM_PATTERNS.items():
            if pattern.search(content):
                return f"{speaker} 自称 {role}"
        return ""

    def _request_focus_line(self, request_kind: str, payload: dict[str, Any]) -> str:
        available_targets = [str(item) for item in payload.get("available_targets", []) if item]
        if request_kind == "day_speak":
            return "白天发言，优先输出可复述的怀疑链和投票依据。"
        if request_kind == "day_vote":
            if available_targets:
                return f"白天投票，只能从这些目标中选择: {', '.join(available_targets)}"
            return "白天投票，只能在合法存活目标中选择。"
        if request_kind == "night_action":
            allowed_actions = [str(item) for item in payload.get("allowed_actions", []) if item]
            if allowed_actions:
                return f"夜间行动，只能执行这些动作: {', '.join(allowed_actions)}"
            return "夜间行动，遵守角色技能约束。"
        if request_kind == "sheriff_campaign_speak":
            return "警长竞选发言，需要说明带队思路和判断标准。"
        if request_kind == "sheriff_vote":
            if available_targets:
                return f"警长投票，只能投给候选人: {', '.join(available_targets)}"
            return "警长投票，只能投给合法候选人。"
        if request_kind == "last_words":
            return "遗言发言，优先留下关键身份判断和票型复盘。"
        if request_kind == "badge_transfer":
            return "警徽移交，只能在存活玩家中选择接警徽对象或放弃。"
        return ""

    def _promote_to_key_fact(self, system_name: str) -> bool:
        return system_name in {
            "inspection_result",
            "sheriff_elected",
            "badge_transferred",
            "badge_destroyed",
            "night_deaths_announced",
            "night_peaceful",
            "player_eliminated",
            "game_ended",
        }

    def _should_flush_summary(self, system_name: str) -> bool:
        return system_name in {
            "action_requested",
            "phase_advanced",
            "sheriff_elected",
            "player_eliminated",
            "night_deaths_announced",
            "night_peaceful",
            "game_ended",
        }

    def _system_event_to_line(self, system_name: str, payload: dict[str, Any]) -> str:
        if system_name == "vote_recorded":
            voter = payload.get("voter")
            target = payload.get("target")
            if voter and target:
                return f"{voter} 投票给 {target}"

        if system_name == "sheriff_vote_recorded":
            voter = payload.get("voter")
            target = payload.get("target")
            if voter and target:
                return f"{voter} 将警长票投给 {target}"

        if system_name == "vote_count_completed":
            vote_counts = payload.get("vote_counts")
            if vote_counts:
                return f"白天票型统计: {vote_counts}"

        if system_name == "sheriff_vote_count_completed":
            vote_counts = payload.get("vote_counts")
            if vote_counts:
                return f"警长票型统计: {vote_counts}"

        if system_name == "inspection_result":
            result = payload.get("result")
            if result:
                return f"查验结果: {_trim_text(result)}"

        if system_name == "night_deaths_announced":
            deaths = payload.get("deaths", [])
            return f"昨夜死亡玩家: {', '.join(str(item) for item in deaths) or '无'}"

        if system_name == "night_peaceful":
            return "昨夜是平安夜"

        if system_name == "player_eliminated":
            player = payload.get("eliminated_player")
            reason = payload.get("reason")
            if player:
                return f"{player} 出局，原因: {reason or 'unknown'}"

        if system_name == "sheriff_elected":
            sheriff = payload.get("sheriff")
            if sheriff:
                return f"{sheriff} 当选警长"

        if system_name == "sheriff_election_tied":
            tied_candidates = payload.get("tied_candidates", [])
            return f"警长竞选平票: {', '.join(str(item) for item in tied_candidates) or '无'}"

        if system_name == "sheriff_vacant":
            return "本局没有警长"

        if system_name == "badge_transferred":
            badge_holder = payload.get("badge_holder")
            if badge_holder:
                return f"警徽转移给 {badge_holder}"

        if system_name == "badge_destroyed":
            return "警徽已被撕毁"

        if system_name == "heal_success":
            saved_player = payload.get("saved_player")
            if saved_player:
                return f"{saved_player} 被救下"

        if system_name == "attack_protected":
            attacked_player = payload.get("attacked_player")
            guard = payload.get("guard")
            if attacked_player and guard:
                return f"{guard} 成功守护 {attacked_player}"

        if system_name == "last_words_pending":
            speakers = payload.get("speakers", [])
            if speakers:
                return f"等待遗言玩家: {', '.join(str(item) for item in speakers)}"

        if system_name == "last_words_announced":
            speaker = payload.get("speaker")
            if speaker:
                return f"{speaker} 开始发表遗言"

        if system_name == "sheriff_election_started":
            candidates = payload.get("candidates", [])
            if candidates:
                return f"警长候选人: {', '.join(str(item) for item in candidates)}"

        if system_name == "witch_night_info":
            attacked_player = payload.get("attacked_player")
            if attacked_player:
                return f"女巫夜间获知被刀目标: {attacked_player}"

        if system_name == "game_ended":
            winner = payload.get("winner")
            return f"游戏结束，获胜方: {winner or 'unknown'}"

        return ""

    def _maybe_update_alive_players(self, summary: GameSummary, payload: dict[str, Any]) -> None:
        alive_players = payload.get("alive_players")
        if isinstance(alive_players, list):
            summary.alive_players = [str(player_id) for player_id in alive_players if player_id]
            return

        final_alive_players = payload.get("final_alive_players")
        if isinstance(final_alive_players, list):
            summary.alive_players = [str(player_id) for player_id in final_alive_players if player_id]
            return

        eliminated_player = str(payload.get("eliminated_player", "")).strip()
        if eliminated_player and summary.alive_players:
            summary.alive_players = [
                player_id for player_id in summary.alive_players if player_id != eliminated_player
            ]

        deaths = payload.get("deaths")
        if isinstance(deaths, list) and deaths and summary.alive_players:
            death_set = {str(player_id) for player_id in deaths if player_id}
            summary.alive_players = [
                player_id for player_id in summary.alive_players if player_id not in death_set
            ]

    def _append_phase_line(self, summary: GameSummary, line: str) -> None:
        summary.pending_phase_lines = _dedupe_keep_order(
            [*summary.pending_phase_lines, _trim_text(line)],
            limit=SUMMARY_MAX_PHASE_LINES,
        )

    def _roll_phase(self, summary: GameSummary, phase: str) -> None:
        if not phase:
            return
        if not summary.current_phase:
            summary.current_phase = phase
            return
        if summary.current_phase == phase:
            return
        self._finalize_phase(summary)
        summary.current_phase = phase
        summary.current_request_kind = ""
        summary.current_focus = []
        summary.pending_phase_lines = []

    def _finalize_phase(self, summary: GameSummary) -> None:
        if not summary.current_phase:
            return
        lines = _dedupe_keep_order(summary.pending_phase_lines, limit=SUMMARY_MAX_PHASE_LINES)
        if not lines:
            return
        summary.phase_summaries.append(
            PhaseSummary(
                phase=summary.current_phase,
                summary_lines=lines,
            )
        )
        summary.phase_summaries = summary.phase_summaries[-SUMMARY_MAX_PHASE_SUMMARIES:]

    def _load_raw(self) -> list[dict[str, Any]]:
        """Read raw long-term memory JSON."""
        return json.loads(self.file_path.read_text(encoding="utf-8"))

    def _save_raw(self, items: list[dict[str, Any]]) -> None:
        """Write raw long-term memory JSON."""
        self.file_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_summary_games(self) -> dict[str, GameSummary]:
        if self._summary_cache is not None:
            return self._summary_cache
        raw = json.loads(self.summary_file_path.read_text(encoding="utf-8"))
        game_payloads = raw.get("games", {}) if isinstance(raw, dict) else {}
        summaries: dict[str, GameSummary] = {}
        for game_id, payload in game_payloads.items():
            if isinstance(payload, dict):
                summaries[str(game_id)] = GameSummary.from_dict(payload)
        self._summary_cache = summaries
        return summaries

    def _save_summary_games(self, summaries: dict[str, GameSummary], *, force: bool) -> None:
        self._summary_cache = summaries
        self._summary_dirty = True
        if not force:
            return
        payload = {
            "games": {
                game_id: summary.to_dict()
                for game_id, summary in summaries.items()
            }
        }
        self.summary_file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._summary_dirty = False

    @staticmethod
    def _phase_to_str(phase: Any) -> str:
        return phase.value if hasattr(phase, "value") else str(phase or "")
