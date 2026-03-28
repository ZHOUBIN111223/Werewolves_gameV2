"""Structured prompt builders used by agents."""

from __future__ import annotations

from typing import Any

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

    current_alive_players = list(alive_players or [])
    other_alive_players = [
        player_id for player_id in current_alive_players if player_id != actor_id
    ]
    speech_rules = [
        "白天发言可以引用已出局玩家、夜间死亡、历史发言和投票记录来复盘局势。",
        "当前点名怀疑、站边或拉票对象应以存活玩家为主，不要把已出局玩家当成当前票出目标。",
        "如果怀疑某位玩家，尽量自然结合关键时间点、投票记录、发言矛盾或夜间结果说明依据。",
        "证据不足时可以保留不确定性，不要为了凑格式硬编理由。",
    ]

    base_prompt: dict[str, object] = {
        "prompt_type": "action",
        "game_id": game_id,
        "role": role,
        "phase": phase,
        "visible_events": [_event_summary(event) for event in visible_events],
        "short_memories": [memory.content for memory in short_memories],
        "strategy_rules": [memory.content for memory in strategy_rules[:3]],
        "alive_players": current_alive_players,
        "other_alive_players": other_alive_players,
        "available_targets": current_alive_players,
        "alive_player_summary": (
            f"当前存活玩家: {', '.join(current_alive_players)}"
            if current_alive_players
            else "当前没有可操作的存活玩家列表"
        ),
        "speech_rules": speech_rules,
        "output_schema": {
            "action_type": "必须是 speak|vote|inspect|kill|protect|poison|heal|skip|hunt 之一",
            "target": '目标玩家 ID；不需要目标时输出空字符串 ""',
            "reasoning_summary": "内部推理摘要，不公开展示",
            "public_speech": "公开发言内容；当 action_type 为 speak 时必须为非空中文句子",
        },
        "output_format": (
            "严格输出一个合法 JSON 对象，只包含 "
            "action_type、target、reasoning_summary、public_speech 四个字段。"
        ),
        "specific_guidance": speech_rules[:],
    }

    if speech_memories:
        base_prompt["speech_content"] = [
            f"{memory.role}: {memory.content}" for memory in speech_memories
        ]

    if "night" in phase:
        base_prompt["phase_instructions"] = (
            "现在是夜晚阶段，只有具备夜间技能的角色可以行动，其他角色通常应选择 skip。"
        )
        mandatory_actions = {
            "werewolf": f"你必须从这些存活玩家中选择击杀目标: {other_alive_players or ['其他存活玩家']}",
            "seer": f"你必须从这些存活玩家中选择查验目标: {other_alive_players or ['其他存活玩家']}",
            "guard": f"你需要决定今夜保护谁: {current_alive_players or ['存活玩家']}",
            "witch": "你需要在 heal、poison、skip 中做出选择，并结合今夜信息判断是否用药。",
        }
        base_prompt["mandatory_action"] = mandatory_actions.get(
            role,
            "当前角色在夜晚通常无需主动操作，可按规则选择 skip。",
        )
    else:
        base_prompt["phase_instructions"] = (
            "现在是白天阶段，你必须参与讨论或投票，不能持续跳过。"
        )
        base_prompt["mandatory_action"] = (
            "白天必须在 speak 或 vote 中做出选择。"
            f"如需投票，只能从这些存活玩家中选择: {current_alive_players or ['存活玩家']}。"
        )
        base_prompt["daytime_requirement"] = (
            "白天不允许返回 skip；若选择发言，应自然说明判断依据，并尽量与后续投票逻辑保持一致。"
        )

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


def build_request_specific_prompt(
    request_kind: str,
    role: str | None = None,
    actor_id: str | None = None,
    alive_players: list[str] | None = None,
    available_targets: list[str] | None = None,
    sheriff_candidates: list[str] | None = None,
    last_guard_target: str | None = None,
) -> dict[str, object]:
    """Build hard constraints for the current request."""

    request_kind = str(request_kind or "").strip()
    current_alive_players = [player_id for player_id in (alive_players or []) if player_id]
    legal_targets = [player_id for player_id in (available_targets or []) if player_id]
    legal_sheriff_targets = [player_id for player_id in (sheriff_candidates or []) if player_id]
    fallback_vote_targets = [
        player_id
        for player_id in current_alive_players
        if player_id and player_id != actor_id
    ]

    if request_kind == "sheriff_vote" and not legal_targets:
        legal_targets = [
            player_id for player_id in legal_sheriff_targets if player_id != actor_id
        ]
    if request_kind == "day_vote" and not legal_targets:
        legal_targets = fallback_vote_targets[:]

    example_suspect = fallback_vote_targets[0] if fallback_vote_targets else ""
    example_vote_target = legal_targets[0] if legal_targets else example_suspect
    example_speak = (
        "我会继续结合前面的发言、投票和夜间结果盘逻辑，先听听场上几个人对关键回合的解释。"
        if not example_suspect
        else (
            f"我现在更关注 {example_suspect}。"
            f"前面他的站边和投票没有完全对上，我想继续听他解释关键轮次为什么这么选。"
        )
    )

    shared_prompt: dict[str, object] = {
        "request_priority_note": (
            "当前这一组请求级约束，高于通用阶段提示。"
            "生成结果时必须优先满足 hard_constraints。"
        ),
        "response_checklist": [
            "先检查 must_action_type，再决定动作类型。",
            "检查 target 是必须为空，还是必须从 available_targets 中选择。",
            "检查 public_speech 是必须为空，还是必须非空。",
            "如果任何字段与 hard_constraints 冲突，先修正后再输出。",
        ],
    }

    if request_kind in {"day_speak", "sheriff_campaign_speak", "last_words"}:
        decision_task_map = {
            "day_speak": "你当前处于白天发言请求，这一轮只能返回发言动作。",
            "sheriff_campaign_speak": "你当前处于警长竞选发言请求，这一轮只能返回发言动作。",
            "last_words": "你当前处于遗言请求，这一轮只能返回发言动作。",
        }
        speech_rule_map = {
            "day_speak": "public_speech 必须是 2 到 4 句自然中文，不能为空。",
            "sheriff_campaign_speak": (
                "public_speech 必须是 2 到 4 句自然中文，"
                "并且应包含竞选立场、观察重点或带队思路。"
            ),
            "last_words": "public_speech 必须是非空中文遗言。",
        }
        shared_prompt.update(
            {
                "decision_task": decision_task_map[request_kind],
                "available_targets": [],
                "hard_constraints": {
                    "request_kind": request_kind,
                    "must_action_type": "speak",
                    "allowed_action_types": ["speak"],
                    "forbidden_action_types": [
                        "vote",
                        "inspect",
                        "kill",
                        "protect",
                        "poison",
                        "heal",
                        "skip",
                        "hunt",
                    ],
                    "target_rule": 'target 必须严格等于 ""，不能填写任何玩家 ID，也不能填写 "all"。',
                    "speech_rule": speech_rule_map[request_kind],
                    "scope_rule": "允许引用已出局玩家、夜间死亡和历史事件做复盘依据；但当前点名怀疑、站边或拉票对象应以存活玩家为主。",
                    "reason_rule": "如果你怀疑某位玩家，请自然结合关键时间点、投票记录、发言矛盾或夜间结果说明依据，不要生硬凑格式。",
                },
                "output_example": {
                    "action_type": "speak",
                    "target": "",
                    "reasoning_summary": (
                        f"我想继续给 {example_suspect} 施压并观察他的解释。"
                        if example_suspect
                        else "我想继续对比其他人的站边和票型，再决定重点怀疑对象。"
                    ),
                    "public_speech": example_speak,
                },
                "negative_example": {
                    "why_wrong": "这是发言请求。返回 vote，或者在 speak 里携带 target，都是不合法的。",
                    "bad_output": {
                        "action_type": "vote",
                        "target": example_suspect,
                        "reasoning_summary": "我想先投票再说。",
                        "public_speech": "",
                    },
                },
            }
        )
        return shared_prompt

    if request_kind == "day_vote":
        shared_prompt.update(
            {
                "decision_task": "你当前处于白天投票请求，这一轮必须返回投票动作。",
                "available_targets": legal_targets,
                "hard_constraints": {
                    "request_kind": request_kind,
                    "must_action_type": "vote",
                    "allowed_action_types": ["vote"],
                    "forbidden_action_types": [
                        "speak",
                        "inspect",
                        "kill",
                        "protect",
                        "poison",
                        "heal",
                        "skip",
                        "hunt",
                    ],
                    "target_rule": "target 必须从 available_targets 中选择一个玩家 ID，并且不能投给自己。",
                    "speech_rule": '投票请求下，public_speech 必须严格等于 ""。',
                    "consistency_rule": "投票最好与既有公开立场保持一致，但最终输出仍然只能是投票 JSON。",
                },
                "output_example": {
                    "action_type": "vote",
                    "target": example_vote_target,
                    "reasoning_summary": (
                        f"基于发言和票型，我当前最怀疑 {example_vote_target}。"
                        if example_vote_target
                        else "我需要从当前合法目标里选出最可疑的人。"
                    ),
                    "public_speech": "",
                },
                "negative_example": {
                    "why_wrong": "这是投票请求。返回 speak 是不合法的。",
                    "bad_output": {
                        "action_type": "speak",
                        "target": "",
                        "reasoning_summary": "我还想先多解释一点。",
                        "public_speech": "我还想再听一轮发言。",
                    },
                },
            }
        )
        return shared_prompt

    if request_kind == "sheriff_vote":
        sheriff_vote_targets = legal_targets or [
            player_id for player_id in legal_sheriff_targets if player_id != actor_id
        ]
        shared_prompt.update(
            {
                "decision_task": "你当前处于警长投票请求，这一轮必须投给警长候选人。",
                "available_targets": sheriff_vote_targets,
                "vote_candidates": sheriff_vote_targets,
                "hard_constraints": {
                    "request_kind": request_kind,
                    "must_action_type": "vote",
                    "allowed_action_types": ["vote"],
                    "forbidden_action_types": [
                        "speak",
                        "inspect",
                        "kill",
                        "protect",
                        "poison",
                        "heal",
                        "skip",
                        "hunt",
                    ],
                    "target_rule": "target 必须从 vote_candidates 中选择一个玩家 ID，并且不能投给自己。",
                    "speech_rule": '投票请求下，public_speech 必须严格等于 ""。',
                },
                "output_example": {
                    "action_type": "vote",
                    "target": sheriff_vote_targets[0] if sheriff_vote_targets else "",
                    "reasoning_summary": "我更倾向于支持判断和带队更稳定的候选人。",
                    "public_speech": "",
                },
                "negative_example": {
                    "why_wrong": "这是警长投票请求，target 必须是候选人。",
                    "bad_output": {
                        "action_type": "vote",
                        "target": example_suspect,
                        "reasoning_summary": "我想支持这个人。",
                        "public_speech": "",
                    },
                },
            }
        )
        return shared_prompt

    if request_kind == "night_action" and role == "guard":
        guard_available_targets = legal_targets or current_alive_players[:]
        forbidden_targets = [last_guard_target] if last_guard_target else []
        target_rule = "target must be selected from available_targets."
        if last_guard_target:
            target_rule = (
                "target must be selected from available_targets and must not equal "
                "last_guard_target."
            )
        shared_prompt.update(
            {
                "decision_task": "You are resolving the guard's night protection request.",
                "available_targets": guard_available_targets,
                "forbidden_targets": forbidden_targets,
                "guard_memory": {
                    "last_guard_target": last_guard_target or "",
                },
                "hard_constraints": {
                    "request_kind": request_kind,
                    "must_action_type": "protect",
                    "allowed_action_types": ["protect"],
                    "forbidden_action_types": [
                        "speak",
                        "vote",
                        "inspect",
                        "kill",
                        "poison",
                        "heal",
                        "skip",
                        "hunt",
                    ],
                    "target_rule": target_rule,
                    "repeat_rule": (
                        "You protected "
                        f"{last_guard_target} last night and cannot protect the same player "
                        "on consecutive nights."
                        if last_guard_target
                        else "Do not output an illegal repeated protection target."
                    ),
                    "speech_rule": 'public_speech must be exactly "" for night protection.',
                },
                "output_example": {
                    "action_type": "protect",
                    "target": guard_available_targets[0] if guard_available_targets else "",
                    "reasoning_summary": "I should protect the strongest surviving good-side target while obeying the no-repeat rule.",
                    "public_speech": "",
                },
                "negative_example": {
                    "why_wrong": (
                        "This is a guard night action. Repeating last_guard_target or returning skip is illegal."
                    ),
                    "bad_output": {
                        "action_type": "protect",
                        "target": last_guard_target or "",
                        "reasoning_summary": "I will repeat the same protection target.",
                        "public_speech": "",
                    },
                },
            }
        )
        return shared_prompt

    return {}


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
        "instructions": (
            f"请以 {role} 的视角复盘这局游戏，总结判断正确与失误的原因，并提炼可复用策略。"
        ),
    }


def build_role_specific_prompt(role: str, base_context: dict[str, Any]) -> dict[str, Any]:
    """Overlay role-specific identity and guidance on top of the common prompt."""
    role_profiles = {
        "werewolf": {
            "identity": "你是狼人阵营成员，目标是通过伪装、误导和夜间击杀推动狼人获胜。",
            "abilities": ["夜间击杀", "隐藏身份", "误导讨论"],
            "role_instruction": "作为狼人，你需要平衡白天伪装和夜晚击杀收益，避免留下过于明显的痕迹。",
            "behavior_tips": [
                "白天发言保持稳定逻辑，不要过度激进。",
                "优先攻击对狼人威胁最大的角色或玩家。",
                "思考夜间行动如何影响下一天的舆论。",
            ],
        },
        "villager": {
            "identity": "你是普通村民，目标是通过公开讨论和投票找出所有狼人。",
            "abilities": ["白天发言", "投票放逐"],
            "role_instruction": "作为村民，你没有夜间技能，白天发言质量和投票判断就是你的核心价值。",
            "behavior_tips": [
                "优先关注发言前后不一致和刻意模糊立场的玩家。",
                "尽量给出清晰怀疑链，而不是泛泛表态。",
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
                "公开信息时提前准备完整逻辑链。",
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
            "identity": "你是女巫，拥有一瓶解药和一瓶毒药。",
            "abilities": ["使用解药", "使用毒药"],
            "role_instruction": "作为女巫，你需要把药剂收益最大化，并谨慎控制自己的身份暴露风险。",
            "behavior_tips": [
                "解药优先留给能显著改变局势的目标。",
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


def build_phase_specific_prompt(phase: str, base_context: dict[str, Any]) -> dict[str, Any]:
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
            "夜晚信息有限，重点是正确使用技能，并为下一天创造信息差。"
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
                "可以引用已出局玩家和历史事件复盘，但当前投票与施压对象必须保持合法。",
                "怀疑某位玩家时，自然结合关键回合、票型或发言矛盾说明依据。",
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
