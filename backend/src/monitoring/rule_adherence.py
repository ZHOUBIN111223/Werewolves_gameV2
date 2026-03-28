"""Utilities for recording runtime rule-adherence across execution layers."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any

from src.enums import ActionType
from src.events.action import Action
from src.validation.action_validator import normalize_public_speech


SPEECH_REQUEST_KINDS = {"day_speak", "sheriff_campaign_speak", "last_words"}
TARGETED_ACTION_TYPES = {
    ActionType.VOTE.value,
    ActionType.KILL.value,
    ActionType.INSPECT.value,
    ActionType.PROTECT.value,
    ActionType.POISON.value,
    ActionType.HEAL.value,
}
VALID_ACTION_TYPES = {member.value for member in ActionType}
MONITORED_FIELDS = ("action_type", "target", "reasoning_summary", "public_speech")

LAYER_LABELS = {
    "agent": "Agent原始输出",
    "controller": "Controller纠偏结果",
    "judge": "Judge最终裁决",
}
ROLE_LABELS = {
    "villager": "平民",
    "werewolf": "狼人",
    "seer": "预言家",
    "guard": "守卫",
    "witch": "女巫",
    "hunter": "猎人",
}
REQUEST_KIND_LABELS = {
    "night_action": "夜间行动",
    "day_speak": "白天发言",
    "day_vote": "白天投票",
    "sheriff_campaign_speak": "警长竞选发言",
    "sheriff_vote": "警长投票",
    "last_words": "遗言发言",
    "badge_transfer": "警徽移交",
}
SUBPHASE_LABELS = {
    "setup": "准备阶段",
    "daybreak": "天亮公布",
    "discussion": "讨论发言",
    "voting": "白天投票",
    "last_words": "遗言阶段",
    "last_words_complete": "遗言完成",
    "guard": "守卫行动",
    "werewolf": "狼人行动",
    "witch": "女巫行动",
    "seer": "预言家行动",
    "sheriff_campaign": "警长竞选发言",
    "sheriff_voting": "警长投票",
    "post_game": "结算阶段",
}
ACTION_LABELS = {
    ActionType.SPEAK.value: "发言",
    ActionType.VOTE.value: "投票",
    ActionType.INSPECT.value: "查验",
    ActionType.KILL.value: "击杀",
    ActionType.PROTECT.value: "守护",
    ActionType.SKIP.value: "跳过",
    ActionType.POISON.value: "毒杀",
    ActionType.HEAL.value: "救人",
    ActionType.HUNT.value: "开枪",
}
FIELD_LABELS = {
    "action_type": "动作类型",
    "target": "目标",
    "reasoning_summary": "思考摘要",
    "public_speech": "公开发言",
}
VIOLATION_LABELS = {
    "missing_action_type": "缺少动作类型",
    "invalid_action_type": "动作类型不合法",
    "action_not_allowed_for_request": "动作不在当前请求允许范围内",
    "speech_request_requires_speak": "当前请求必须返回发言动作",
    "empty_public_speech": "发言内容为空",
    "public_speech_needs_normalization": "发言内容需要纠偏后才符合规则",
    "speech_should_not_target_player": "发言动作不应携带目标玩家",
    "day_vote_requires_vote": "白天投票请求必须返回投票动作",
    "missing_vote_target": "缺少投票目标",
    "self_vote_not_allowed": "不能投票给自己",
    "vote_target_not_alive": "投票目标不是存活玩家",
    "sheriff_vote_requires_vote": "警长投票请求必须返回投票动作",
    "missing_sheriff_vote_target": "缺少警长投票目标",
    "sheriff_vote_target_not_candidate": "警长投票目标不是候选人",
    "badge_transfer_requires_vote_or_skip": "警徽移交只能选择移交或放弃",
    "missing_badge_transfer_target": "缺少警徽移交目标",
    "self_badge_transfer_not_allowed": "警徽不能移交给自己",
    "badge_transfer_target_not_alive": "警徽移交目标不是存活玩家",
    "missing_target": "缺少目标玩家",
    "target_not_alive": "目标玩家不是存活玩家",
    "werewolf_must_kill": "狼人夜间必须执行击杀动作",
    "werewolf_cannot_target_self": "狼人不能以自己为目标",
    "werewolf_cannot_target_teammate": "狼人不能以狼人队友为目标",
    "seer_must_inspect": "预言家夜间必须执行查验动作",
    "seer_cannot_target_self": "预言家不能查验自己",
    "guard_must_protect": "守卫夜间必须执行守护动作",
    "guard_cannot_repeat_target": "守卫不能连续两晚守同一名玩家",
    "witch_heal_already_used": "女巫的解药已经使用过",
    "witch_heal_target_not_attacked": "女巫只能救当晚被击杀的玩家",
    "witch_poison_already_used": "女巫的毒药已经使用过",
    "witch_cannot_poison_self": "女巫不能毒自己",
    "witch_action_must_be_heal_poison_or_skip": "女巫夜间只能选择救人、毒人或跳过",
    "role_without_night_skill_must_skip": "当前角色没有夜间技能时只能跳过",
    "skip_should_not_include_target": "跳过动作不应携带目标玩家",
    "missing_raw_llm_output": "缺少原始模型输出，无法判断原始遵守情况",
    "judge_rejected_action": "法官判定该动作不合法",
}
JUDGE_REASON_LABELS = {
    "player does not exist": "玩家不存在",
    "dead player cannot act": "死亡玩家不能行动",
    "current subphase only allows speak": "当前子阶段只允许发言",
    "current subphase only allows valid vote": "当前子阶段只允许有效投票",
    "sheriff vote target must be a candidate": "警长投票目标必须是候选人",
    "cannot vote for dead player": "不能投给已死亡玩家",
    "day phase only allows speak or vote": "白天阶段只允许发言或投票",
    "werewolf can only kill another alive non-werewolf": "狼人只能击杀其他存活的非狼人玩家",
    "seer can only inspect another alive player": "预言家只能查验其他存活玩家",
    "guard can only protect a valid alive target and cannot repeat": "守卫只能守护合法的存活目标，且不能连续守同一人",
    "witch can only act once with heal, poison, or skip": "女巫每晚只能行动一次，且只能选择救人、毒人或跳过",
    "witch can only heal tonight's attacked player": "女巫只能救当晚被击杀的玩家",
    "witch poison target must be another alive player": "女巫毒药目标必须是其他存活玩家",
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _snapshot_raw_output(raw_output: Any) -> dict[str, Any]:
    if isinstance(raw_output, dict):
        return {
            "action_type": _as_text(raw_output.get("action_type", "")).lower(),
            "target": _as_text(raw_output.get("target", "")),
            "reasoning_summary": _as_text(raw_output.get("reasoning_summary", "")),
            "public_speech": _as_text(raw_output.get("public_speech", "")),
            "raw_output": deepcopy(raw_output),
        }

    return {
        "action_type": "",
        "target": "",
        "reasoning_summary": "",
        "public_speech": "",
        "raw_output": raw_output,
    }


def _snapshot_action(action: Action) -> dict[str, str]:
    return {
        "action_type": action.action_type.value,
        "target": _as_text(action.target),
        "reasoning_summary": _as_text(action.reasoning_summary),
        "public_speech": _as_text(action.public_speech),
    }


def _diff_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return [field for field in MONITORED_FIELDS if _as_text(before.get(field, "")) != _as_text(after.get(field, ""))]


def _sorted_unique(items: list[str]) -> list[str]:
    return sorted({item for item in items if item})


def _label_layer(layer: str) -> str:
    return LAYER_LABELS.get(layer, layer or "未知层级")


def _label_role(role: str) -> str:
    return ROLE_LABELS.get(role, role or "未知角色")


def _label_request_kind(request_kind: str) -> str:
    return REQUEST_KIND_LABELS.get(request_kind, request_kind or "未知请求")


def _label_subphase(subphase: str) -> str:
    return SUBPHASE_LABELS.get(subphase, subphase or "未知子阶段")


def _label_phase(phase: str) -> str:
    if phase == "setup":
        return "准备阶段"
    if phase == "post_game":
        return "结算阶段"
    if phase.startswith("day_"):
        return f"第{phase.split('_', 1)[1]}天"
    if phase.startswith("night_"):
        return f"第{phase.split('_', 1)[1]}夜"
    return phase or "未知阶段"


def _label_action_type(action_type: str) -> str:
    return ACTION_LABELS.get(action_type, action_type or "未知动作")


def _label_field(field_name: str) -> str:
    return FIELD_LABELS.get(field_name, field_name)


def _label_violation(reason: str) -> str:
    if reason in VIOLATION_LABELS:
        return VIOLATION_LABELS[reason]
    if reason in JUDGE_REASON_LABELS:
        return JUDGE_REASON_LABELS[reason]
    if reason.endswith(" can only skip at night"):
        role = reason[: -len(" can only skip at night")]
        return f"{_label_role(role)}在夜间没有可执行技能时只能跳过"
    return reason


def _format_probability(probability: float) -> str:
    return f"{probability:.2%}"


def _evaluate_snapshot(
    snapshot: dict[str, Any],
    *,
    actor: str,
    role: str,
    request_kind: str,
    allowed_actions: list[str],
    alive_players: list[str],
    players: dict[str, str],
    sheriff_candidates: list[str],
    kills_pending: list[str],
    heal_used: bool,
    poison_used: bool,
    last_guard_target: str | None,
) -> list[str]:
    action_type = _as_text(snapshot.get("action_type", "")).lower()
    target = _as_text(snapshot.get("target", ""))
    public_speech = _as_text(snapshot.get("public_speech", ""))
    violations: list[str] = []

    if not action_type:
        violations.append("missing_action_type")
    elif action_type not in VALID_ACTION_TYPES:
        violations.append("invalid_action_type")

    if allowed_actions and action_type and action_type not in allowed_actions:
        violations.append("action_not_allowed_for_request")

    if request_kind in SPEECH_REQUEST_KINDS:
        if action_type != ActionType.SPEAK.value:
            violations.append("speech_request_requires_speak")
        if not public_speech:
            violations.append("empty_public_speech")
        elif normalize_public_speech(public_speech, alive_players, actor) != public_speech:
            violations.append("public_speech_needs_normalization")
        if target:
            violations.append("speech_should_not_target_player")
        return _sorted_unique(violations)

    if request_kind == "day_vote":
        if action_type != ActionType.VOTE.value:
            violations.append("day_vote_requires_vote")
        if not target:
            violations.append("missing_vote_target")
        elif target == actor:
            violations.append("self_vote_not_allowed")
        elif target not in alive_players:
            violations.append("vote_target_not_alive")
        return _sorted_unique(violations)

    if request_kind == "sheriff_vote":
        if action_type != ActionType.VOTE.value:
            violations.append("sheriff_vote_requires_vote")
        if not target:
            violations.append("missing_sheriff_vote_target")
        elif target == actor:
            violations.append("self_vote_not_allowed")
        elif target not in sheriff_candidates:
            violations.append("sheriff_vote_target_not_candidate")
        return _sorted_unique(violations)

    if request_kind == "badge_transfer":
        if action_type == ActionType.SKIP.value:
            return _sorted_unique(violations)
        if action_type != ActionType.VOTE.value:
            violations.append("badge_transfer_requires_vote_or_skip")
        if not target:
            violations.append("missing_badge_transfer_target")
        elif target == actor:
            violations.append("self_badge_transfer_not_allowed")
        elif target not in alive_players:
            violations.append("badge_transfer_target_not_alive")
        return _sorted_unique(violations)

    if action_type in TARGETED_ACTION_TYPES and not target:
        violations.append("missing_target")
    elif target and action_type in TARGETED_ACTION_TYPES and target not in alive_players:
        violations.append("target_not_alive")

    if role == "werewolf":
        if action_type != ActionType.KILL.value:
            violations.append("werewolf_must_kill")
        elif target == actor:
            violations.append("werewolf_cannot_target_self")
        elif target and players.get(target) == "werewolf":
            violations.append("werewolf_cannot_target_teammate")
        return _sorted_unique(violations)

    if role == "seer":
        if action_type != ActionType.INSPECT.value:
            violations.append("seer_must_inspect")
        elif target == actor:
            violations.append("seer_cannot_target_self")
        return _sorted_unique(violations)

    if role == "guard":
        if action_type != ActionType.PROTECT.value:
            violations.append("guard_must_protect")
        elif target and target == last_guard_target:
            violations.append("guard_cannot_repeat_target")
        return _sorted_unique(violations)

    if role == "witch":
        if action_type == ActionType.HEAL.value:
            if heal_used:
                violations.append("witch_heal_already_used")
            if target not in kills_pending:
                violations.append("witch_heal_target_not_attacked")
            return _sorted_unique(violations)

        if action_type == ActionType.POISON.value:
            if poison_used:
                violations.append("witch_poison_already_used")
            if target == actor:
                violations.append("witch_cannot_poison_self")
            return _sorted_unique(violations)

        if action_type != ActionType.SKIP.value:
            violations.append("witch_action_must_be_heal_poison_or_skip")
        return _sorted_unique(violations)

    if action_type != ActionType.SKIP.value:
        violations.append("role_without_night_skill_must_skip")
    if target:
        violations.append("skip_should_not_include_target")
    return _sorted_unique(violations)


def _base_record(
    *,
    layer: str,
    action_id: str,
    actor: str,
    role: str,
    phase: str,
    subphase: str,
    request_kind: str,
    observed_action: dict[str, Any],
    final_action: dict[str, Any],
    violations: list[str],
    corrected_fields: list[str],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "layer": layer,
        "action_id": action_id,
        "actor": actor,
        "role": role,
        "phase": phase,
        "subphase": subphase,
        "request_kind": request_kind,
        "adhered": not violations and not corrected_fields,
        "violations": violations,
        "correction_applied": bool(corrected_fields),
        "corrected_fields": corrected_fields,
        "observed_action": observed_action,
        "final_action": final_action,
        "details": details or {},
    }


def build_agent_layer_record(
    *,
    action: Action,
    raw_output: Any,
    context: dict[str, Any],
) -> dict[str, Any]:
    raw_snapshot = _snapshot_raw_output(raw_output)
    validated_snapshot = _snapshot_action(action)
    violations = _evaluate_snapshot(
        raw_snapshot,
        actor=str(context.get("actor", "")),
        role=str(context.get("role", "")),
        request_kind=str(context.get("request_kind", "")),
        allowed_actions=list(context.get("allowed_actions", [])),
        alive_players=list(context.get("alive_players", [])),
        players=dict(context.get("players", {})),
        sheriff_candidates=list(context.get("sheriff_candidates", [])),
        kills_pending=list(context.get("kills_pending", [])),
        heal_used=bool(context.get("heal_used", False)),
        poison_used=bool(context.get("poison_used", False)),
        last_guard_target=context.get("last_guard_target"),
    )
    if raw_output is None:
        violations = _sorted_unique([*violations, "missing_raw_llm_output"])
    corrected_fields = _diff_fields(raw_snapshot, validated_snapshot)
    return _base_record(
        layer="agent",
        action_id=action.event_id,
        actor=str(context.get("actor", "")),
        role=str(context.get("role", "")),
        phase=str(context.get("phase", "")),
        subphase=str(context.get("subphase", "")),
        request_kind=str(context.get("request_kind", "")),
        observed_action={key: raw_snapshot[key] for key in MONITORED_FIELDS},
        final_action=validated_snapshot,
        violations=violations,
        corrected_fields=corrected_fields,
        details={"raw_output": deepcopy(raw_snapshot.get("raw_output"))},
    )


def build_controller_layer_record(
    *,
    before_action: Action,
    after_action: Action,
    context: dict[str, Any],
) -> dict[str, Any]:
    observed_snapshot = _snapshot_action(before_action)
    final_snapshot = _snapshot_action(after_action)
    violations = _evaluate_snapshot(
        observed_snapshot,
        actor=str(context.get("actor", "")),
        role=str(context.get("role", "")),
        request_kind=str(context.get("request_kind", "")),
        allowed_actions=list(context.get("allowed_actions", [])),
        alive_players=list(context.get("alive_players", [])),
        players=dict(context.get("players", {})),
        sheriff_candidates=list(context.get("sheriff_candidates", [])),
        kills_pending=list(context.get("kills_pending", [])),
        heal_used=bool(context.get("heal_used", False)),
        poison_used=bool(context.get("poison_used", False)),
        last_guard_target=context.get("last_guard_target"),
    )
    corrected_fields = _diff_fields(observed_snapshot, final_snapshot)
    return _base_record(
        layer="controller",
        action_id=after_action.event_id,
        actor=str(context.get("actor", "")),
        role=str(context.get("role", "")),
        phase=str(context.get("phase", "")),
        subphase=str(context.get("subphase", "")),
        request_kind=str(context.get("request_kind", "")),
        observed_action=observed_snapshot,
        final_action=final_snapshot,
        violations=violations,
        corrected_fields=corrected_fields,
    )


def build_judge_layer_record(
    *,
    action: Action,
    context: dict[str, Any],
    is_valid: bool,
    judge_reason: str,
) -> dict[str, Any]:
    snapshot = _snapshot_action(action)
    violations = [] if is_valid else [judge_reason or "judge_rejected_action"]
    return _base_record(
        layer="judge",
        action_id=action.event_id,
        actor=str(context.get("actor", "")),
        role=str(context.get("role", "")),
        phase=str(context.get("phase", "")),
        subphase=str(context.get("subphase", "")),
        request_kind=str(context.get("request_kind", "")),
        observed_action=snapshot,
        final_action=snapshot,
        violations=violations,
        corrected_fields=[],
        details={"judge_reason": judge_reason},
    )


def _localize_action_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "动作类型": _label_action_type(_as_text(snapshot.get("action_type", "")).lower()),
        "目标": _as_text(snapshot.get("target", "")),
        "思考摘要": _as_text(snapshot.get("reasoning_summary", "")),
        "公开发言": _as_text(snapshot.get("public_speech", "")),
    }


def localize_rule_adherence_record(record: dict[str, Any]) -> dict[str, Any]:
    localized: dict[str, Any] = {
        "层级": _label_layer(_as_text(record.get("layer", ""))),
        "动作ID": _as_text(record.get("action_id", "")),
        "玩家": _as_text(record.get("actor", "")),
        "角色": _label_role(_as_text(record.get("role", ""))),
        "阶段": _label_phase(_as_text(record.get("phase", ""))),
        "子阶段": _label_subphase(_as_text(record.get("subphase", ""))),
        "请求类型": _label_request_kind(_as_text(record.get("request_kind", ""))),
        "是否遵守规则": bool(record.get("adhered", False)),
        "原始动作": _localize_action_snapshot(dict(record.get("observed_action", {}))),
        "最终动作": _localize_action_snapshot(dict(record.get("final_action", {}))),
    }

    violations = [_label_violation(_as_text(item)) for item in record.get("violations", []) if item]
    if violations:
        localized["不遵守原因"] = violations

    if bool(record.get("correction_applied", False)):
        localized["是否发生纠偏"] = True
        localized["纠偏字段"] = [
            _label_field(_as_text(field_name))
            for field_name in record.get("corrected_fields", [])
            if field_name
        ]

    details = dict(record.get("details", {}))
    localized_details: dict[str, Any] = {}
    if "raw_output" in details and details["raw_output"] is not None:
        raw_output = details["raw_output"]
        if isinstance(raw_output, dict):
            localized_details["原始LLM输出"] = _localize_action_snapshot(raw_output)
        else:
            localized_details["原始LLM输出"] = raw_output
    if details.get("judge_reason"):
        localized_details["法官判定"] = _label_violation(_as_text(details["judge_reason"]))
    if localized_details:
        localized["补充信息"] = localized_details

    return localized


def _create_bucket() -> dict[str, Any]:
    return {"total": 0, "adhered": 0, "violation_counts": Counter()}


def _update_bucket(bucket: dict[str, Any], record: dict[str, Any]) -> None:
    bucket["total"] += 1
    if bool(record.get("adhered", False)):
        bucket["adhered"] += 1
    bucket["violation_counts"].update(
        [_label_violation(_as_text(item)) for item in record.get("violations", []) if item]
    )


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    total = int(bucket["total"])
    adhered = int(bucket["adhered"])
    not_adhered = total - adhered
    probability = (adhered / total) if total else 0.0
    result: dict[str, Any] = {
        "总次数": total,
        "遵守次数": adhered,
        "不遵守次数": not_adhered,
        "遵守规则概率": probability,
        "遵守规则概率文本": _format_probability(probability),
    }
    if bucket["violation_counts"]:
        result["不遵守情况计数"] = dict(
            sorted(bucket["violation_counts"].items(), key=lambda item: (-item[1], item[0]))
        )
    return result


def summarize_rule_adherence_records(
    records: list[dict[str, Any]],
    non_adherence_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    overall: dict[str, dict[str, Any]] = defaultdict(_create_bucket)
    by_role: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(_create_bucket))
    by_request_kind: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(_create_bucket))

    for record in records:
        layer = _as_text(record.get("layer", "")) or "unknown"
        role = _as_text(record.get("role", "")) or "unknown"
        request_kind = _as_text(record.get("request_kind", "")) or "unknown"

        _update_bucket(overall[layer], record)
        _update_bucket(by_role[role][layer], record)
        _update_bucket(by_request_kind[request_kind][layer], record)

    localized_non_adherence_records = list(non_adherence_records or [])
    if not localized_non_adherence_records:
        localized_non_adherence_records = [
            localize_rule_adherence_record(record)
            for record in records
            if not bool(record.get("adhered", False))
        ]

    summary: dict[str, Any] = {
        "总动作数": len({str(record.get("action_id", "")) for record in records if record.get("action_id")}),
        "总层级判定次数": len(records),
        "各层遵守规则概率": {
            _label_layer(layer): _finalize_bucket(bucket)
            for layer, bucket in sorted(overall.items(), key=lambda item: _label_layer(item[0]))
        },
        "按角色统计": {
            _label_role(role): {
                _label_layer(layer): _finalize_bucket(bucket)
                for layer, bucket in sorted(layer_buckets.items(), key=lambda item: _label_layer(item[0]))
            }
            for role, layer_buckets in sorted(by_role.items(), key=lambda item: _label_role(item[0]))
        },
        "按请求类型统计": {
            _label_request_kind(request_kind): {
                _label_layer(layer): _finalize_bucket(bucket)
                for layer, bucket in sorted(layer_buckets.items(), key=lambda item: _label_layer(item[0]))
            }
            for request_kind, layer_buckets in sorted(
                by_request_kind.items(), key=lambda item: _label_request_kind(item[0])
            )
        },
        "不遵守记录数": len(localized_non_adherence_records),
    }
    if localized_non_adherence_records:
        summary["不遵守记录"] = localized_non_adherence_records
    return summary
