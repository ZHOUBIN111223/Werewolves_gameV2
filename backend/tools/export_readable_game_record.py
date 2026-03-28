"""导出可读的狼人杀对局记录。

该脚本读取 SQLite 事件库（`store_data/global_events*.db`），将指定 game_id 的事件
整理成适合人类阅读的文本，方便快速回放与排查对局流程。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


# 角色英文标识 -> 中文展示名
ROLE_LABELS = {
    "villager": "村民",
    "werewolf": "狼人",
    "seer": "预言家",
    "witch": "女巫",
    "guard": "守卫",
    "hunter": "猎人",
}

# 复盘结果标签 -> 中文展示名
OUTCOME_LABELS = {
    "win": "胜利",
    "lose": "失败",
    "unknown": "未知",
}

# 胜者阵营 -> 中文展示名
WINNER_LABELS = {
    "werewolves": "狼人阵营",
    "villagers": "好人阵营",
    "unknown": "未知",
}

# 某些 phase 名称在展示时需要更友好的标题
PHASE_NAME_OVERRIDES = {
    "setup": "准备阶段",
    "post_game": "结算阶段",
}


def player_sort_key(player_id: str) -> tuple[int, str]:
    """玩家 ID 的排序键。

    规则：
    - `player_数字` 按数字从小到大排序
    - 其他 ID 放到末尾，保持字典序
    """
    if player_id.startswith("player_"):
        suffix = player_id.split("_", 1)[1]
        if suffix.isdigit():
            return int(suffix), player_id
    return 10**9, player_id


def phase_sort_key(phase: str) -> tuple[int, int]:
    """phase 的排序键，用于按对局流程输出。"""
    if phase == "setup":
        return (0, 0)
    if phase == "post_game":
        return (10**9, 0)
    if phase.startswith("night_"):
        number = int(phase.split("_", 1)[1])
        return (number, 0)
    if phase.startswith("day_"):
        number = int(phase.split("_", 1)[1])
        return (number, 1)
    return (10**8, 0)


def phase_title(phase: str) -> str:
    """将内部 phase 名称转换为更易读的标题。"""
    if phase in PHASE_NAME_OVERRIDES:
        return PHASE_NAME_OVERRIDES[phase]
    if phase.startswith("night_"):
        return f"第{phase.split('_', 1)[1]}夜"
    if phase.startswith("day_"):
        return f"第{phase.split('_', 1)[1]}天"
    return phase


def format_vote_counts(vote_counts: dict[str, int]) -> str:
    """将投票统计字典格式化为一行文本。"""
    items = sorted(vote_counts.items(), key=lambda item: player_sort_key(item[0]))
    return "，".join(f"{player}: {votes}票" for player, votes in items)


def fetch_events(db_path: Path, game_id: str) -> list[dict[str, Any]]:
    """从 SQLite 事件库中读取指定对局的原始事件记录。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT phase, event_type, actor, action_type, system_name, payload, timestamp, sequence_num, id
            FROM events
            WHERE game_id = ?
            ORDER BY timestamp ASC, sequence_num ASC, id ASC
            """,
            (game_id,),
        ).fetchall()
    finally:
        conn.close()

    events: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload"]) if row["payload"] else {}
        events.append(
            {
                "phase": row["phase"],
                "event_type": row["event_type"],
                "actor": row["actor"],
                "action_type": row["action_type"],
                "system_name": row["system_name"],
                "payload": payload,
            }
        )
    return events


def choose_game_id(db_path: Path, requested_game_id: str | None) -> str:
    """选择要导出的 game_id。

    - 若显式传入 requested_game_id，则校验其存在
    - 否则默认导出数据库中最新的一局（按 timestamp/sequence/id 排序）
    """
    conn = sqlite3.connect(db_path)
    try:
        if requested_game_id:
            exists = conn.execute(
                "SELECT 1 FROM events WHERE game_id = ? LIMIT 1",
                (requested_game_id,),
            ).fetchone()
            if not exists:
                raise SystemExit(f"未找到 game_id={requested_game_id} 的对局数据。")
            return requested_game_id

        row = conn.execute(
            """
            SELECT game_id
            FROM events
            GROUP BY game_id
            ORDER BY MAX(timestamp) DESC, MAX(sequence_num) DESC, MAX(id) DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise SystemExit("数据库中没有可导出的对局数据。")
    return str(row[0])


def extract_roles_and_outcomes(events: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """从复盘事件中提取每个玩家的身份与胜负（复盘视角）。"""
    result: dict[str, dict[str, str]] = {}
    for event in events:
        if event["system_name"] != "reflection_recorded":
            continue
        payload = event["payload"]
        agent_id = str(payload.get("agent_id", "")).strip()
        if not agent_id:
            continue
        result[agent_id] = {
            "role": str(payload.get("role", "")).strip(),
            "outcome": str(payload.get("outcome", "unknown")).strip(),
        }
    return dict(sorted(result.items(), key=lambda item: player_sort_key(item[0])))


def extract_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """提取对局摘要：玩家列表、胜者与最终存活。"""
    players: list[str] = []
    winner = "unknown"
    final_alive_players: list[str] = []

    for event in events:
        if event["system_name"] == "game_started":
            players = [str(player) for player in event["payload"].get("players", [])]
        if event["system_name"] == "game_ended":
            winner = str(event["payload"].get("winner", "unknown"))
            final_alive_players = [
                str(player) for player in event["payload"].get("final_alive_players", [])
            ]

    return {
        "players": sorted(players, key=player_sort_key),
        "winner": winner,
        "final_alive_players": sorted(final_alive_players, key=player_sort_key),
    }


def render_event(event: dict[str, Any]) -> str | None:
    """将单条事件渲染为可读文本（仅处理关心的 system 事件）。"""
    system_name = event["system_name"]
    payload = event["payload"]

    if system_name == "game_started":
        players = "、".join(str(player) for player in payload.get("players", []))
        return f"玩家列表：{players}"
    if system_name == "sheriff_election_started":
        candidates = "、".join(str(player) for player in payload.get("candidates", []))
        return f"警长竞选开始，候选人：{candidates}"
    if system_name == "speaking_order_announced":
        order = " -> ".join(str(player) for player in payload.get("speaking_order", []))
        badge_holder = payload.get("badge_holder")
        if badge_holder:
            return f"发言顺序：{order}（警徽持有者：{badge_holder}）"
        return f"发言顺序：{order}"
    if system_name == "speech_delivered":
        return f"{payload.get('speaker', '未知玩家')} 发言：{payload.get('content', '')}"
    if system_name == "sheriff_vote_recorded":
        return f"警长投票：{payload.get('voter')} -> {payload.get('target')}"
    if system_name == "sheriff_elected":
        return f"警长当选：{payload.get('sheriff')}"
    if system_name == "sheriff_election_tied":
        tied = "、".join(str(player) for player in payload.get("tied_candidates", []))
        return f"警长竞选平票：{tied}（{payload.get('votes', 0)}票）"
    if system_name == "sheriff_vacant":
        return "本局没有警长"
    if system_name == "kill_attempted":
        return f"夜间行动：狼人 {payload.get('killer')} 尝试击杀 {payload.get('target')}"
    if system_name == "protection_used":
        return f"夜间行动：守卫 {payload.get('guard')} 守护了 {payload.get('protected_player')}"
    if system_name == "attack_protected":
        return f"夜间结果：{payload.get('attacked_player')} 被守卫 {payload.get('guard')} 成功保护"
    if system_name == "heal_used":
        return f"夜间行动：女巫 {payload.get('witch')} 使用解药救下 {payload.get('healed_player')}"
    if system_name == "poison_used":
        return f"夜间行动：女巫 {payload.get('witch')} 毒杀了 {payload.get('poisoned_player')}"
    if system_name == "inspection_result":
        role = ROLE_LABELS.get(str(payload.get("role", "")), str(payload.get("role", "")))
        return f"夜间行动：预言家查验 {payload.get('target')}，结果是 {role}"
    if system_name == "night_peaceful":
        return "白天公告：昨夜是平安夜"
    if system_name == "night_deaths_announced":
        deaths = "、".join(str(player) for player in payload.get("deaths", []))
        return f"白天公告：昨夜死亡玩家为 {deaths}"
    if system_name == "vote_recorded":
        return f"放逐投票：{payload.get('voter')} -> {payload.get('target')}"
    if system_name == "vote_count_completed":
        vote_counts = payload.get("vote_counts", {})
        if isinstance(vote_counts, dict):
            return f"票型统计：{format_vote_counts(vote_counts)}"
    if system_name == "tie_no_elimination":
        tied_players = "、".join(str(player) for player in payload.get("tied_players", []))
        return f"放逐结果：平票，无人出局（{tied_players}）"
    if system_name == "player_eliminated":
        return f"玩家出局：{payload.get('eliminated_player')}（原因：{payload.get('reason')}）"
    if system_name == "last_words_announced":
        return f"遗言环节：{payload.get('speaker')} 发言（原因：{payload.get('reason')}）"
    if system_name == "badge_transfer_pending":
        return f"警徽待转移：{payload.get('from_player')}"
    if system_name == "badge_transferred":
        return f"警徽转移：{payload.get('from_player')} -> {payload.get('to_player')}"
    if system_name == "badge_destroyed":
        return f"警徽销毁：原持有者 {payload.get('departed_player')}"
    if system_name == "game_ended":
        winner = WINNER_LABELS.get(str(payload.get("winner", "unknown")), str(payload.get("winner", "unknown")))
        alive_players = "、".join(str(player) for player in payload.get("final_alive_players", []))
        return f"游戏结束：{winner} 获胜，最终存活玩家：{alive_players}"
    return None


def render_record(db_path: Path, game_id: str) -> str:
    """渲染整个对局为文本记录。"""
    events = fetch_events(db_path, game_id)
    summary = extract_summary(events)
    roles_and_outcomes = extract_roles_and_outcomes(events)

    phase_entries: dict[str, list[str]] = {}
    for event in events:
        text = render_event(event)
        if not text:
            continue
        phase_entries.setdefault(str(event["phase"]), []).append(text)

    lines: list[str] = []
    lines.append("狼人杀对局记录")
    lines.append("=" * 40)
    lines.append(f"游戏 ID：{game_id}")
    lines.append(f"数据源：{db_path}")
    lines.append("说明：本记录基于事件库自动导出，包含公开流程与复盘可见的夜间动作。")
    lines.append("")
    lines.append("对局摘要")
    lines.append("-" * 40)
    lines.append(f"玩家数量：{len(summary['players'])}")
    lines.append(
        f"获胜方：{WINNER_LABELS.get(summary['winner'], summary['winner'])}"
    )
    lines.append(
        "最终存活："
        + ("、".join(summary["final_alive_players"]) if summary["final_alive_players"] else "无")
    )
    lines.append("")

    if roles_and_outcomes:
        lines.append("身份表（复盘视角）")
        lines.append("-" * 40)
        for player_id, info in roles_and_outcomes.items():
            role = ROLE_LABELS.get(info["role"], info["role"])
            outcome = OUTCOME_LABELS.get(info["outcome"], info["outcome"])
            lines.append(f"{player_id}：{role}，结果：{outcome}")
        lines.append("")

    lines.append("过程记录")
    lines.append("-" * 40)
    for phase in sorted(phase_entries, key=phase_sort_key):
        lines.append(f"[{phase_title(phase)}]")
        for entry in phase_entries[phase]:
            lines.append(f"- {entry}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    """CLI 入口：解析参数并写出导出文件。"""
    parser = argparse.ArgumentParser(description="导出狼人杀对局的可读文本记录")
    parser.add_argument(
        "--db",
        default="store_data/global_events_test.db",
        help="SQLite 事件库路径",
    )
    parser.add_argument(
        "--game-id",
        default=None,
        help="要导出的 game_id，默认导出最新一局",
    )
    parser.add_argument(
        "--output",
        default="examples/sample_game_record.txt",
        help="输出文本文件路径",
    )
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    game_id = choose_game_id(db_path, args.game_id)
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_record(db_path, game_id), encoding="utf-8")
    print(f"已导出对局记录：{output_path}")


if __name__ == "__main__":
    main()
