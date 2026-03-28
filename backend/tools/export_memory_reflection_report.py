"""Export a Chinese markdown report for one game's memory and reflection process."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _truncate(value: Any, limit: int = 320) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _flat_bullets(items: list[Any], empty_text: str = "无") -> list[str]:
    normalized = [_text(item) for item in items if _text(item)]
    if not normalized:
        return [f"- {empty_text}"]
    return [f"- {item}" for item in normalized]


def _section(title: str, items: list[Any], empty_text: str = "无") -> list[str]:
    return [f"### {title}", *_flat_bullets(items, empty_text), ""]


def _collect_reflection_traces(trace_root: Path, game_id: str) -> list[dict[str, Any]]:
    game_trace_root = trace_root / game_id
    if not game_trace_root.exists():
        return []

    traces: list[dict[str, Any]] = []
    for meta_path in sorted(game_trace_root.rglob("meta.json")):
        meta = _load_json(meta_path, {})
        if meta.get("prompt_type") != "reflection":
            continue
        trace_dir = meta_path.parent
        status_payload = _load_json(trace_dir / "status.json", {})
        error_payload = _load_json(trace_dir / "error.json", {})
        if status_payload:
            trace_status = _text(status_payload.get("status"), "unknown")
        elif error_payload:
            trace_status = _text(error_payload.get("status"), "error")
        else:
            trace_status = "pending"
        traces.append(
            {
                "dir_name": trace_dir.name,
                "meta": meta,
                "prompt": _load_json(trace_dir / "prompt.json", {}),
                "messages": _load_json(trace_dir / "messages.json", []),
                "validated": _load_json(trace_dir / "validated_response.json", {}),
                "default_response": _load_json(trace_dir / "default_response.json", {}),
                "status": status_payload,
                "error": error_payload,
                "trace_status": trace_status,
            }
        )
    return traces


def _collect_agent_report(agent_dir: Path, game_id: str) -> dict[str, Any]:
    memory_items = _load_json(agent_dir / "memory.json", [])
    summary_payload = _load_json(agent_dir / "summary_memory.json", {"games": {}})
    summary_game = (summary_payload.get("games", {}) or {}).get(game_id, {})

    relevant_long_term = [
        item
        for item in memory_items
        if _text(item.get("game_id")) == game_id
    ]
    reusable_rules = [
        item
        for item in memory_items
        if "strategy_rule" in (item.get("tags") or [])
        or "anti_pattern" in (item.get("tags") or [])
    ]

    return {
        "agent_id": agent_dir.name,
        "summary": summary_game,
        "relevant_long_term": relevant_long_term,
        "reusable_rules": reusable_rules[-10:],
    }


def _render_phase_summaries(phase_summaries: list[dict[str, Any]]) -> list[str]:
    lines = ["### 阶段摘要"]
    if not phase_summaries:
        lines.append("- 无")
        lines.append("")
        return lines

    for item in phase_summaries:
        phase = _text(item.get("phase"), "unknown")
        summary_lines = item.get("summary_lines", []) or []
        if summary_lines:
            for entry in summary_lines:
                lines.append(f"- [{phase}] {_text(entry)}")
        else:
            lines.append(f"- [{phase}] 无")
    lines.append("")
    return lines


def _render_recent_speeches(recent_speeches: list[dict[str, Any]]) -> list[str]:
    lines = ["### 最近发言摘录"]
    if not recent_speeches:
        lines.append("- 无")
        lines.append("")
        return lines

    for speech in recent_speeches:
        speaker = _text(speech.get("speaker"), "unknown")
        phase = _text(speech.get("phase"), "unknown")
        content = _text(speech.get("content"), "无内容")
        lines.append(f"- [{phase}] {speaker}: {content}")
    lines.append("")
    return lines


def _render_memory_items(title: str, items: list[dict[str, Any]]) -> list[str]:
    lines = [f"### {title}"]
    if not items:
        lines.append("- 无")
        lines.append("")
        return lines

    for item in items:
        memory_type = _text(item.get("memory_type"), "unknown")
        confidence = item.get("confidence", 1.0)
        tags = ", ".join(str(tag) for tag in item.get("tags", []) or []) or "无"
        content = _text(item.get("content"), "无内容")
        lines.append(f"- 类型: {memory_type} | 置信度: {confidence} | 标签: {tags}")
        lines.append(f"- 内容: {content}")
    lines.append("")
    return lines


def _render_reflection_trace(trace: dict[str, Any], index: int) -> list[str]:
    meta = trace["meta"]
    prompt = trace["prompt"]
    validated = trace["validated"]
    default_response = trace["default_response"]
    error = trace["error"]

    lines = [
        f"### Trace {index}",
        f"- 状态: {_text(trace.get('trace_status'), 'unknown')}",
        f"- 目录: {_text(trace.get('dir_name'), 'unknown')}",
        f"- 角色: {_text(meta.get('role'), 'unknown')}",
        f"- 模型: {_text(meta.get('model'), 'unknown')}",
        f"- 时间: {_text(meta.get('timestamp_utc'), 'unknown')}",
        "",
    ]

    lines.extend(_section("反思输入记忆", list(prompt.get("memories", []) or [])))

    visible_events = list(prompt.get("visible_events", []) or [])
    lines.extend(
        _section(
            "反思输入事件",
            [_truncate(event, 220) for event in visible_events],
        )
    )

    if validated:
        lines.extend(_section("Mistakes", list(validated.get("mistakes", []) or [])))
        lines.extend(_section("Correct Reads", list(validated.get("correct_reads", []) or [])))
        lines.extend(_section("Useful Signals", list(validated.get("useful_signals", []) or [])))
        lines.extend(_section("Bad Patterns", list(validated.get("bad_patterns", []) or [])))
        lines.extend(_section("Strategy Rules", list(validated.get("strategy_rules", []) or [])))
        lines.append(f"- Confidence: {validated.get('confidence', '')}")
        lines.append("")
    elif default_response:
        lines.append("#### 默认回退输出")
        lines.append("```json")
        lines.append(json.dumps(default_response, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")

    if error:
        lines.extend(
            [
                "#### 错误信息",
                f"- 错误类型: {_text(error.get('error_type'), 'unknown')}",
                f"- 错误消息: {_text(error.get('error_message'), 'unknown')}",
                "",
            ]
        )

    return lines


def build_report(
    controller_dir: Path,
    game_id: str,
    output_path: Path,
    trace_root: Path,
) -> Path:
    reflections_path = controller_dir / "reflections" / f"{game_id}_agent_reflections.md"
    reflections_text = reflections_path.read_text(encoding="utf-8") if reflections_path.exists() else ""

    agent_root = controller_dir / "agents"
    agent_reports = []
    if agent_root.exists():
        for agent_dir in sorted(path for path in agent_root.iterdir() if path.is_dir()):
            report = _collect_agent_report(agent_dir, game_id)
            if report["summary"] or report["relevant_long_term"]:
                agent_reports.append(report)

    reflection_traces = _collect_reflection_traces(trace_root, game_id)
    success_count = sum(1 for trace in reflection_traces if trace["trace_status"] == "success")
    error_count = sum(1 for trace in reflection_traces if trace["trace_status"] == "error")
    pending_count = sum(1 for trace in reflection_traces if trace["trace_status"] == "pending")

    lines: list[str] = [
        f"# {game_id} 记忆与反思报告",
        "",
        "## 说明",
        "- 本报告使用中文整理该局的摘要记忆、长期记忆和赛后反思过程。",
        "- 局内摘要来自 `summary_memory.json`。",
        "- 长期记忆来自 `memory.json`。",
        "- 赛后反思过程来自 LLM reflection trace；如果反思超时或未完成，也会原样记录。",
        "",
        "## Reflection Trace 总览",
        f"- 总数: {len(reflection_traces)}",
        f"- 成功: {success_count}",
        f"- 错误: {error_count}",
        f"- 未完成: {pending_count}",
        "",
    ]

    if reflections_text:
        lines.extend(
            [
                "## Controller 导出的赛后反思",
                "",
                "```md",
                reflections_text.rstrip(),
                "```",
                "",
            ]
        )

    for agent_report in agent_reports:
        summary = agent_report["summary"] or {}
        lines.extend(
            [
                f"## {agent_report['agent_id']}",
                "",
                f"- 当前阶段: {_text(summary.get('current_phase'), '无')}",
                f"- 当前请求: {_text(summary.get('current_request_kind'), '无')}",
                "",
            ]
        )
        lines.extend(_section("当前任务焦点", list(summary.get("current_focus", []) or [])))
        lines.extend(_section("存活玩家", list(summary.get("alive_players", []) or [])))
        lines.extend(_section("关键事实", list(summary.get("key_facts", []) or [])))
        lines.extend(_section("身份声明", list(summary.get("claims", []) or [])))
        lines.extend(_section("待确认问题", list(summary.get("open_questions", []) or [])))
        lines.extend(_render_phase_summaries(list(summary.get("phase_summaries", []) or [])))
        lines.extend(_render_recent_speeches(list(summary.get("recent_speeches", []) or [])))
        lines.extend(_render_memory_items("本局写入的长期记忆", agent_report["relevant_long_term"]))
        lines.extend(_render_memory_items("当前可复用长期规则", agent_report["reusable_rules"]))

    lines.append("## Reflection Trace 详情")
    if reflection_traces:
        for index, trace in enumerate(reflection_traces, start=1):
            lines.extend(_render_reflection_trace(trace, index))
    else:
        lines.extend(["- 未找到该局的 reflection trace。", ""])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="导出单局记忆与反思 Markdown 报告")
    parser.add_argument("--controller-dir", required=True, help="controller 目录，例如 store_data/controller_1")
    parser.add_argument("--game-id", required=True, help="目标对局 ID")
    parser.add_argument("--output", required=True, help="输出 Markdown 文件路径")
    parser.add_argument(
        "--trace-root",
        default="logs/llm_traces",
        help="LLM trace 根目录，默认 logs/llm_traces",
    )
    args = parser.parse_args()

    output_path = build_report(
        controller_dir=Path(args.controller_dir),
        game_id=args.game_id,
        output_path=Path(args.output),
        trace_root=Path(args.trace_root),
    )
    print(str(output_path))


if __name__ == "__main__":
    main()
