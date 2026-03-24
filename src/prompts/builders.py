"""Structured prompt builders used by agents."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.memory_store import MemoryItem
from src.events.event import EventBase


def _event_summary(event: EventBase) -> str:
    """Convert an event into a compact, stable summary string."""
    return f"[{event.phase}] {event.event_type}: {event.payload}"


def _merge_unique_strings(existing: list[str], extra: list[str]) -> list[str]:
    """Merge string lists while preserving order and removing duplicates."""
    merged: list[str] = []
    for item in [*existing, *extra]:
        if item and item not in merged:
            merged.append(item)
    return merged


def build_action_prompt(
    game_id: str,
    role: str,
    phase: str,
    visible_events: list[EventBase],
    short_memories: list[MemoryItem],
    strategy_rules: list[MemoryItem],
    alive_players: list[str] | None = None,
    speech_memories: list[MemoryItem] | None = None,
    actor_id: str | None = None,
) -> dict[str, object]:
    """Build the common action prompt context shared by all roles."""
    base_prompt: dict[str, object] = {
        "prompt_type": "action",
        "game_id": game_id,
        "role": role,
        "phase": phase,
        "visible_events": [_event_summary(event) for event in visible_events],
        "short_memories": [memory.content for memory in short_memories],
        "strategy_rules": [memory.content for memory in strategy_rules[:3]],
        "output_schema": {
            "action_type": "动作类型，必须是 speak|vote|inspect|kill|protect|poison|heal|skip|hunt 之一",
            "target": '目标玩家 ID，不需要目标时输出空字符串 ""',
            "reasoning_summary": "内部推理摘要，仅供模型内部使用",
            "public_speech": "公开发言内容；当 action_type 为 speak 时必须非空",
        },
        "output_format": "严格输出一个合法 JSON 对象，包含 action_type、target、reasoning_summary、public_speech 四个字段。",
    }

    if alive_players:
        base_prompt["alive_players"] = alive_players
        base_prompt["available_targets"] = alive_players

    if speech_memories:
        base_prompt["speech_content"] = [
            f"{memory.role}: {memory.content}" for memory in speech_memories
        ]

    role_instructions = {
        "werewolf": "你是狼人，需要隐藏身份、制造误导，并寻找对狼人阵营最有利的行动。",
        "villager": "你是村民，需要通过发言、倾听和投票找出狼人。",
        "seer": "你是预言家，夜晚可以查验身份，白天需要考虑如何安全地利用查验结果。",
        "guard": "你是守卫，夜晚可以保护关键玩家，白天通过观察辅助判断局势。",
        "witch": "你是女巫，拥有解药和毒药，需要谨慎分配资源。",
        "hunter": "你是猎人，被放逐或击杀时可能触发开枪能力，白天发言需要尽量保留价值。",
    }
    base_prompt["role_instructions"] = role_instructions.get(
        role, f"你是 {role} 角色，请根据当前局势做出最合理的行动。"
    )

    other_alive_players = [
        player_id for player_id in (alive_players or []) if player_id != actor_id
    ]

    if "night" in phase:
        base_prompt["phase_instructions"] = "现在是夜晚阶段，只有允许行动的角色可以使用技能，其余角色通常应选择 skip。"
        mandatory_actions = {
            "werewolf": f"你必须从以下目标中选择击杀对象：{other_alive_players or ['其他存活玩家']}",
            "seer": f"你必须从以下目标中选择查验对象：{other_alive_players or ['其他存活玩家']}",
            "guard": f"你需要决定今夜保护谁：{alive_players or ['存活玩家']}",
            "witch": "你需要在 heal、poison、skip 中做出选择，并结合今晚信息判断是否用药。",
        }
        base_prompt["mandatory_action"] = mandatory_actions.get(
            role, "当前角色在夜晚通常无需主动操作，可根据规则选择 skip。"
        )
    else:
        base_prompt["phase_instructions"] = "现在是白天阶段，你必须参与讨论或投票，不能持续跳过。"
        base_prompt["mandatory_action"] = (
            "白天必须在 speak 或 vote 中做出选择。优先给出清晰公开发言；"
            f"如需投票，请从这些存活玩家中选择：{alive_players or ['存活玩家']}。"
        )
        base_prompt["daytime_requirement"] = "白天不允许返回 skip，必须发言或投票。"

    base_prompt["format_requirements"] = {
        "output_must_be_valid_json": True,
        "required_fields": [
            "action_type",
            "target",
            "reasoning_summary",
            "public_speech",
        ],
        "action_type_enum_values": [
            "speak",
            "vote",
            "inspect",
            "kill",
            "protect",
            "skip",
            "poison",
            "heal",
            "hunt",
        ],
    }

    return base_prompt


def build_reflection_prompt(
    role: str,
    game_id: str,
    visible_events: list[EventBase],
    memories: list[MemoryItem],
    revealed_truth: dict[str, object],
    outcome: str,
) -> dict[str, object]:
    """Build the post-game reflection prompt context."""
    return {
        "prompt_type": "reflection",
        "role": role,
        "game_id": game_id,
        "visible_events": [_event_summary(event) for event in visible_events],
        "memories": [memory.content for memory in memories],
        "revealed_truth": revealed_truth,
        "outcome": outcome,
        "output_schema": [
            "mistakes",
            "correct_reads",
            "useful_signals",
            "bad_patterns",
            "strategy_rules",
            "confidence",
        ],
        "instructions": f"请以 {role} 的视角复盘这局游戏，总结判断正确与失误的原因，并提炼可复用的策略。",
    }


def build_role_specific_prompt(role: str, base_context: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay role-specific identity and guidance on top of the common prompt."""
    role_profiles = {
        "werewolf": {
            "identity": "你是狼人阵营成员，目标是通过伪装、误导和夜间击杀推动狼人获胜。",
            "abilities": ["夜间击杀", "隐藏身份", "误导讨论"],
            "role_instruction": "作为狼人，你需要平衡白天伪装和夜晚击杀收益，避免留下过于明显的痕迹。",
            "behavior_tips": [
                "白天发言保持稳定逻辑，不要过度激进。",
                "优先攻击对狼人威胁最大的角色或玩家。",
                "思考夜间行动如何影响第二天舆论。",
            ],
        },
        "villager": {
            "identity": "你是普通村民，目标是通过公开讨论和投票找出所有狼人。",
            "abilities": ["白天发言", "投票放逐"],
            "role_instruction": "作为村民，你没有夜间技能，白天的发言质量和投票判断就是你的核心价值。",
            "behavior_tips": [
                "优先关注发言前后不一致和刻意模糊立场的玩家。",
                "尽量给出明确怀疑链，而不是泛泛表态。",
                "投票时保持逻辑闭环，避免随大流。",
            ],
        },
        "seer": {
            "identity": "你是预言家，拥有夜间查验他人身份的能力。",
            "abilities": ["夜间查验身份"],
            "role_instruction": "作为预言家，你需要兼顾查验收益、身份安全和白天带队价值。",
            "behavior_tips": [
                "优先查验对白天局势影响最大的玩家。",
                "权衡何时公开身份和查验结果最有利。",
                "公开信息时提前准备好完整逻辑链。",
            ],
        },
        "guard": {
            "identity": "你是守卫，拥有夜间保护目标的能力。",
            "abilities": ["夜间保护玩家"],
            "role_instruction": "作为守卫，你需要根据白天信息判断谁最值得保护，同时避免保护思路被狼人轻易猜到。",
            "behavior_tips": [
                "优先考虑保护高价值神职或核心发言位。",
                "结合前一晚局势调整守护目标。",
                "注意连续守护限制，不要给出非法选择。",
            ],
        },
        "witch": {
            "identity": "你是女巫，拥有一次解药和一次毒药。",
            "abilities": ["使用解药", "使用毒药"],
            "role_instruction": "作为女巫，你需要把药剂收益最大化，并谨慎控制自己的身份暴露风险。",
            "behavior_tips": [
                "解药优先保留给能显著改变局势的目标。",
                "毒药使用前确认收益大于身份风险。",
                "记录药剂使用状态，避免重复决策错误。",
            ],
        },
        "hunter": {
            "identity": "你是猎人，被击杀或放逐时可能触发带人能力。",
            "abilities": ["白天发言", "死亡时开枪"],
            "role_instruction": "作为猎人，你需要在白天积累可信度，并在关键时刻保留反制价值。",
            "behavior_tips": [
                "不要轻易暴露自己，除非能明显提升好人收益。",
                "关注谁最像高价值狼刀位或悍跳位。",
                "发言尽量留下清晰判断，方便后续利用。",
            ],
        },
    }

    role_info = role_profiles.get(
        role,
        {
            "identity": f"你是 {role} 角色。",
            "abilities": ["参与游戏流程"],
            "role_instruction": f"作为 {role}，请结合身份目标和当前局势做出最优行动。",
            "behavior_tips": ["保持逻辑一致，并根据新信息及时修正判断。"],
        },
    )

    merged_context = dict(base_context)
    merged_context["role_identity"] = role_info["identity"]
    merged_context["role_abilities"] = role_info["abilities"]
    merged_context["role_instruction"] = role_info["role_instruction"]
    merged_context["behavior_tips"] = role_info["behavior_tips"]
    merged_context["specific_guidance"] = _merge_unique_strings(
        list(merged_context.get("specific_guidance", [])),
        list(role_info["behavior_tips"]),
    )
    return merged_context


def build_phase_specific_prompt(phase: str, base_context: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay phase-specific guidance on top of the current prompt."""
    is_night = "night" in phase
    default_available_actions = (
        {
            "werewolf": ["kill"],
            "seer": ["inspect"],
            "guard": ["protect"],
            "witch": ["heal", "poison", "skip"],
            "others": ["skip"],
        }
        if is_night
        else {"all": ["speak", "vote"]}
    )
    phase_context = {
        "phase_type": "night" if is_night else "day",
        "phase_description": (
            "夜晚阶段，只有具备夜间技能的角色可以行动，其他玩家通常只能等待结果。"
            if is_night
            else "白天阶段，所有存活玩家都应通过发言、表态和投票推动局势。"
        ),
        "available_actions": base_context.get("available_actions", default_available_actions),
        "timing_note": (
            "夜晚信息有限，重点是正确使用技能并为下一个白天创造信息差。"
            if is_night
            else "白天信息会快速扩散，重点是公开逻辑、推动站队并形成投票结果。"
        ),
        "phase_specific_guidance": (
            [
                "夜晚优先考虑技能收益和身份安全的平衡。",
                "如果当前角色没有夜间技能，应避免输出与规则冲突的动作。",
            ]
            if is_night
            else [
                "白天优先输出可公开复述的逻辑，而不是只给结论。",
                "投票前确认你的怀疑对象与公开发言保持一致。",
            ]
        ),
    }

    merged_context = dict(base_context)
    merged_context.update(phase_context)
    merged_context["specific_guidance"] = _merge_unique_strings(
        list(merged_context.get("specific_guidance", [])),
        list(phase_context["phase_specific_guidance"]),
    )
    return merged_context
