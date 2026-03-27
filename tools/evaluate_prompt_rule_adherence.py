"""评估 Prompt 规则遵循率的离线脚本。

该脚本通过构造若干“单回合切片”场景（Scenario），复用现有 Judge / Agent /
LLM 调用链，并发运行多次采样，统计模型输出是否遵循：
- allowed_actions / request_kind 的动作约束
- 目标选择是否合法（不自刀、不刀队友、不投死人等）
- 输出字段是否齐全且可规范化

产物：
- 终端报告（按场景与总体统计）
- 可选 HTML 报告（包含分布与失败样本摘要）
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

# 将项目根目录加入 sys.path，便于以脚本方式直接运行时正确导入 src/ 与 config.py。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import AppConfig, get_config_for_provider, validate_config
from src.agents.agent_store import AgentStore
from src.agents.base_agent import BaseAgent
from src.agents.memory_store import AgentMemoryStore
from src.controller.judge import GameState, Judge
from src.enums import GamePhase
from src.events.observation import Observation
from src.events.system_event import SystemEvent
from src.llm.mock_llm import MockLLM
from src.llm.real_llm import RealLLM


StateSetup = Callable[[GameState], None]


@dataclass(frozen=True)
class ScenarioDefinition:
    """单回合评估场景定义。"""

    name: str
    description: str
    players: dict[str, str]
    actor_id: str
    phase: GamePhase
    subphase: str
    request_kind: str
    allowed_actions: tuple[str, ...]
    state_setup: StateSetup


@dataclass(frozen=True)
class RunResult:
    """一次运行（单次采样）的结果摘要。"""

    scenario_name: str
    success: bool
    error_code: str | None
    normalized_fields: tuple[str, ...]


class RecordingLLM:
    """包裹一个真实/Mock LLM，并记录最近一次 prompt 与返回值（便于失败样本分析）。"""

    def __init__(self, inner_llm: object) -> None:
        """创建记录型 LLM 包装器。"""
        self._inner_llm = inner_llm
        self.last_prompt: dict[str, object] | None = None
        self.last_result: dict[str, object] | None = None

    def invoke(self, prompt: dict[str, object]) -> dict[str, object]:
        """透传调用，并拷贝记录输入/输出，避免后续被意外修改。"""
        self.last_prompt = copy.deepcopy(prompt)
        result = self._inner_llm.invoke(prompt)
        self.last_result = copy.deepcopy(result)
        return result


def _setup_werewolf_night_kill(state: GameState) -> None:
    """场景：夜晚狼人刀人。"""
    state.current_phase = GamePhase.NIGHT_2
    state.current_subphase = "werewolf"
    state.alive_players = ["player_0", "player_1", "player_2", "player_4", "player_5"]
    state.night_actions_taken = {}


def _setup_guard_night_protect(state: GameState) -> None:
    """场景：夜晚守卫保护（上一晚已守过目标，测试是否重复守护）。"""
    state.current_phase = GamePhase.NIGHT_2
    state.current_subphase = "guard"
    state.alive_players = ["player_0", "player_1", "player_2", "player_3", "player_4", "player_5"]
    state.last_guard_target_by_guard["player_0"] = "player_2"
    state.night_actions_taken = {}


def _setup_witch_night_heal(state: GameState) -> None:
    """场景：夜晚女巫救人（已知刀口）。"""
    state.current_phase = GamePhase.NIGHT_2
    state.current_subphase = "witch"
    state.alive_players = ["player_0", "player_1", "player_2", "player_3", "player_4", "player_5"]
    state.kills_pending = ["player_2"]
    state.night_actions_taken = {}


def _setup_villager_day_vote(state: GameState) -> None:
    """场景：白天平民投票。"""
    state.current_phase = GamePhase.DAY_2
    state.current_subphase = "voting"
    state.alive_players = ["player_0", "player_1", "player_2", "player_4", "player_5"]
    state.day_resolution_complete = False
    state.phase_votes[state.current_phase.value] = {}


SCENARIOS: dict[str, ScenarioDefinition] = {
    "werewolf_night_kill": ScenarioDefinition(
        name="werewolf_night_kill",
        description="夜晚狼人刀人，场上双狼都存活，测试是否会自刀、刀队友或跳过。",
        players={
            "player_0": "werewolf",
            "player_1": "werewolf",
            "player_2": "seer",
            "player_3": "witch",
            "player_4": "hunter",
            "player_5": "villager",
        },
        actor_id="player_0",
        phase=GamePhase.NIGHT_2,
        subphase="werewolf",
        request_kind="night_action",
        allowed_actions=("kill",),
        state_setup=_setup_werewolf_night_kill,
    ),
    "guard_night_protect": ScenarioDefinition(
        name="guard_night_protect",
        description="夜晚守卫行动，上一晚已守过 player_2，测试是否会连续守同一人或非法跳过。",
        players={
            "player_0": "guard",
            "player_1": "werewolf",
            "player_2": "seer",
            "player_3": "witch",
            "player_4": "hunter",
            "player_5": "villager",
        },
        actor_id="player_0",
        phase=GamePhase.NIGHT_2,
        subphase="guard",
        request_kind="night_action",
        allowed_actions=("protect",),
        state_setup=_setup_guard_night_protect,
    ),
    "witch_night_heal": ScenarioDefinition(
        name="witch_night_heal",
        description="夜晚女巫已知今夜刀口为 player_2，测试是否会救错人、毒自己或非法动作。",
        players={
            "player_0": "werewolf",
            "player_1": "seer",
            "player_2": "hunter",
            "player_3": "witch",
            "player_4": "villager",
            "player_5": "villager",
        },
        actor_id="player_3",
        phase=GamePhase.NIGHT_2,
        subphase="witch",
        request_kind="night_action",
        allowed_actions=("heal", "poison", "skip"),
        state_setup=_setup_witch_night_heal,
    ),
    "villager_day_vote": ScenarioDefinition(
        name="villager_day_vote",
        description="白天投票回合，测试平民是否会自票、弃票或投给死人。",
        players={
            "player_0": "werewolf",
            "player_1": "werewolf",
            "player_2": "seer",
            "player_3": "witch",
            "player_4": "hunter",
            "player_5": "villager",
        },
        actor_id="player_5",
        phase=GamePhase.DAY_2,
        subphase="voting",
        request_kind="day_vote",
        allowed_actions=("vote",),
        state_setup=_setup_villager_day_vote,
    ),
}


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="并发评估单回合 Prompt 规则遵循率，只复用现有 Agent 与 Judge。"
    )
    parser.add_argument(
        "--scenario",
        nargs="+",
        default=["werewolf_night_kill"],
        choices=[*SCENARIOS.keys(), "all"],
        help="要评估的切片场景，默认 werewolf_night_kill。",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=50,
        help="每个场景执行次数，默认 50。",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=50,
        help="并发度，默认 50。",
    )
    parser.add_argument(
        "--api-provider",
        type=str,
        choices=["openai", "anthropic", "bailian", "custom", "mock"],
        default="openai",
        help="LLM 提供方，默认 openai。",
    )
    parser.add_argument("--api-url", type=str, default=None, help="覆盖默认 API 地址。")
    parser.add_argument("--api-key", type=str, default=None, help="覆盖默认 API Key。")
    parser.add_argument("--model", type=str, default=None, help="覆盖默认模型名。")
    parser.add_argument("--timeout", type=int, default=60, help="请求超时秒数，默认 60。")
    parser.add_argument("--max-retries", type=int, default=3, help="最大重试次数，默认 3。")
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="使用 MockLLM 跑本地联调，不走真实模型。",
    )
    parser.add_argument(
        "--work-root",
        type=str,
        default=str(Path(AppConfig.STORE_PATH) / "prompt_eval"),
        help="临时工作目录根路径。",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default=str(Path("results") / "prompt_eval"),
        help="评估报告输出目录，默认 results/prompt_eval。",
    )
    parser.add_argument(
        "--report-prefix",
        type=str,
        default="prompt_rule_adherence",
        help="评估报告文件名前缀。",
    )
    return parser.parse_args()


def _resolve_scenarios(raw_names: list[str]) -> list[ScenarioDefinition]:
    """将用户输入的场景名解析为 ScenarioDefinition 列表。"""
    if "all" in raw_names:
        return list(SCENARIOS.values())
    return [SCENARIOS[name] for name in raw_names]


def _build_llm_factory(args: argparse.Namespace) -> tuple[str, Callable[[], object]]:
    """根据参数构建 LLM 工厂函数（便于多进程/多线程复用）。"""
    if args.test_mode or args.api_provider == "mock":
        return "mock", MockLLM

    validate_config(args.api_provider)
    provider_config = get_config_for_provider(args.api_provider)
    api_url = args.api_url or provider_config.get("base_url") or provider_config.get("endpoint")
    api_key = args.api_key or provider_config["api_key"]
    model = args.model or provider_config["default_model"]

    def factory() -> RealLLM:
        """按当前参数创建一个 RealLLM 实例（每次调用返回新实例）。"""
        return RealLLM(
            api_url=api_url,
            api_key=api_key,
            model=model,
            timeout=args.timeout,
            max_retries=args.max_retries,
        )

    return f"{args.api_provider}:{model}", factory


def _record_event_for_agent(agent: BaseAgent, event: SystemEvent) -> None:
    """将系统事件写入 Agent 的可见事件与记忆（用于构造上下文）。"""
    observation = Observation.from_event(event, observer=agent.agent_id)
    agent.agent_store.append_observation(observation)
    agent.remember_fact(
        event.game_id,
        event.phase.value,
        f"观察到事件: {observation.payload}",
    )

    if event.system_name == "speech_delivered":
        speaker = str(event.payload.get("speaker", "")).strip()
        content = str(event.payload.get("content", "")).strip()
        if speaker and content:
            agent.memory_store.append_speech(
                content=content,
                game_id=event.game_id,
                phase=event.phase.value,
                speaker=speaker,
            )


def _build_request_event(
    scenario: ScenarioDefinition,
    game_id: str,
    state: GameState,
) -> SystemEvent:
    """构造 action_requested 系统事件，模拟 Controller 对指定 actor 的请求。"""
    last_guard_target = state.last_guard_target_by_guard.get(scenario.actor_id)
    available_targets = state.alive_players[:]
    if (
        scenario.request_kind == "night_action"
        and scenario.players[scenario.actor_id] == "guard"
        and last_guard_target
    ):
        available_targets = [
            player_id for player_id in available_targets if player_id != last_guard_target
        ]

    return SystemEvent(
        game_id=game_id,
        phase=state.current_phase,
        visibility=[scenario.actor_id],
        payload={
            "message": "action_requested",
            "actor": scenario.actor_id,
            "role": scenario.players[scenario.actor_id],
            "request_kind": scenario.request_kind,
            "allowed_actions": list(scenario.allowed_actions),
            "alive_players": state.alive_players[:],
            "available_targets": available_targets,
            "last_guard_target": last_guard_target,
            "subphase": state.current_subphase,
        },
        system_name="action_requested",
    )


def _normalized_fields(raw_result: dict[str, object] | None, action) -> tuple[str, ...]:
    """对比 LLM 原始输出与最终 Action，返回被纠偏/规范化的字段名列表。"""
    if not raw_result:
        return ()

    changed_fields: list[str] = []
    raw_action_type = str(raw_result.get("action_type", "") or "").strip().lower()
    raw_target = str(raw_result.get("target", "") or "").strip()
    raw_reasoning = str(raw_result.get("reasoning_summary", "") or "").strip()
    raw_public_speech = str(raw_result.get("public_speech", "") or "").strip()

    if raw_action_type != action.action_type.value:
        changed_fields.append("action_type")
    if raw_target != action.target:
        changed_fields.append("target")
    if raw_reasoning != action.reasoning_summary:
        changed_fields.append("reasoning_summary")
    if raw_public_speech != action.public_speech:
        changed_fields.append("public_speech")

    return tuple(changed_fields)


def _evaluate_once(
    scenario: ScenarioDefinition,
    llm_factory: Callable[[], object],
    run_index: int,
    work_root: Path,
) -> RunResult:
    """执行单次场景评估（单回合一次采样）。"""
    game_id = f"prompt_eval_{scenario.name}_{run_index:03d}"

    with TemporaryDirectory(
        dir=work_root,
        prefix=f"{scenario.name}_{run_index:03d}_",
    ) as temp_dir:
        judge = Judge()
        state = judge.initialize_game(game_id, dict(scenario.players))
        scenario.state_setup(state)

        llm = RecordingLLM(llm_factory())
        agent_root = Path(temp_dir) / "agents"
        agent_store = AgentStore(agent_root, scenario.actor_id, game_id)
        memory_store = AgentMemoryStore(agent_root, scenario.actor_id)
        agent = BaseAgent(
            agent_id=scenario.actor_id,
            role=scenario.players[scenario.actor_id],
            agent_store=agent_store,
            memory_store=memory_store,
            llm=llm,
        )

        request_event = _build_request_event(scenario, game_id, state)
        _record_event_for_agent(agent, request_event)

        try:
            action = agent.decide_action(
                game_id=game_id,
                phase=state.current_phase.value,
                alive_players=state.alive_players[:],
            )
        except Exception as exc:
            return RunResult(
                scenario_name=scenario.name,
                success=False,
                error_code=f"{type(exc).__name__}: {exc}",
                normalized_fields=(),
            )

        normalized_fields = _normalized_fields(llm.last_result, action)
        events = judge.process_action(action, state)
        validation_failures = [
            event
            for event in events
            if isinstance(event, SystemEvent) and event.system_name == "action_validation_failed"
        ]
        if validation_failures:
            error_text = str(validation_failures[0].payload.get("error", "unknown_validation_failed"))
            return RunResult(
                scenario_name=scenario.name,
                success=False,
                error_code=error_text,
                normalized_fields=normalized_fields,
            )

        return RunResult(
            scenario_name=scenario.name,
            success=True,
            error_code=None,
            normalized_fields=normalized_fields,
        )


async def _evaluate_scenario(
    scenario: ScenarioDefinition,
    runs: int,
    concurrency: int,
    llm_factory: Callable[[], object],
    work_root: Path,
) -> list[RunResult]:
    """并发执行某个场景的多次采样。"""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def worker(run_index: int) -> RunResult:
        """单个并发 worker：在线程池中执行一次 _evaluate_once。"""
        async with semaphore:
            return await asyncio.to_thread(
                _evaluate_once,
                scenario,
                llm_factory,
                run_index,
                work_root,
            )

    tasks = [worker(run_index) for run_index in range(1, runs + 1)]
    return await asyncio.gather(*tasks)


def _print_scenario_report(scenario: ScenarioDefinition, results: list[RunResult]) -> None:
    """在终端打印单个场景的统计报告。"""
    total_runs = len(results)
    success_runs = sum(1 for result in results if result.success)
    adherence_rate = (success_runs / total_runs) if total_runs else 0.0
    error_distribution = Counter(result.error_code for result in results if result.error_code)
    normalized_runs = [result for result in results if result.normalized_fields]
    normalized_field_distribution = Counter(
        field
        for result in normalized_runs
        for field in result.normalized_fields
    )

    print(f"\n场景: {scenario.name}")
    print(f"说明: {scenario.description}")
    print(f"总测试次数: {total_runs}")
    print(f"规则遵循率: {adherence_rate:.2%} ({success_runs}/{total_runs})")
    print(f"原生解析发生纠偏: {len(normalized_runs)} 次 ({(len(normalized_runs) / total_runs):.2%})")

    print("错误分布:")
    if error_distribution:
        for error_code, count in error_distribution.most_common():
            print(f"  {error_code}: {count}")
    else:
        print("  无")

    print("纠偏字段分布:")
    if normalized_field_distribution:
        for field, count in normalized_field_distribution.most_common():
            print(f"  {field}: {count}")
    else:
        print("  无")


def _print_overall_report(all_results: list[RunResult]) -> None:
    """在终端打印多个场景合并后的总体统计报告。"""
    total_runs = len(all_results)
    success_runs = sum(1 for result in all_results if result.success)
    adherence_rate = (success_runs / total_runs) if total_runs else 0.0
    error_distribution = Counter(result.error_code for result in all_results if result.error_code)

    print("\n总体汇总:")
    print(f"总测试次数: {total_runs}")
    print(f"规则遵循率: {adherence_rate:.2%} ({success_runs}/{total_runs})")
    print("错误分布:")
    if error_distribution:
        for error_code, count in error_distribution.most_common():
            print(f"  {error_code}: {count}")
    else:
        print("  无")


def _summarize_results(results: list[RunResult]) -> dict[str, object]:
    """将 RunResult 列表汇总为可序列化的统计数据。"""
    total_runs = len(results)
    success_runs = sum(1 for result in results if result.success)
    error_distribution = Counter(result.error_code for result in results if result.error_code)
    normalized_runs = [result for result in results if result.normalized_fields]
    normalized_field_distribution = Counter(
        field
        for result in normalized_runs
        for field in result.normalized_fields
    )
    return {
        "total_runs": total_runs,
        "success_runs": success_runs,
        "failed_runs": total_runs - success_runs,
        "adherence_rate": (success_runs / total_runs) if total_runs else 0.0,
        "normalized_runs": len(normalized_runs),
        "normalized_rate": (len(normalized_runs) / total_runs) if total_runs else 0.0,
        "error_distribution": dict(error_distribution),
        "normalized_field_distribution": dict(normalized_field_distribution),
    }


def _build_report_data(
    args: argparse.Namespace,
    llm_label: str,
    scenarios: list[ScenarioDefinition],
    scenario_results_map: dict[str, list[RunResult]],
) -> dict[str, object]:
    """将运行结果组装成可序列化的报告数据结构（JSON/HTML 共用）。"""
    all_results = [result for results in scenario_results_map.values() for result in results]
    scenario_reports: list[dict[str, object]] = []
    for scenario in scenarios:
        results = scenario_results_map[scenario.name]
        scenario_reports.append(
            {
                "name": scenario.name,
                "description": scenario.description,
                "actor_id": scenario.actor_id,
                "phase": scenario.phase.value,
                "subphase": scenario.subphase,
                "request_kind": scenario.request_kind,
                "allowed_actions": list(scenario.allowed_actions),
                "summary": _summarize_results(results),
                "runs": [
                    {
                        "scenario_name": result.scenario_name,
                        "success": result.success,
                        "error_code": result.error_code,
                        "normalized_fields": list(result.normalized_fields),
                    }
                    for result in results
                ],
            }
        )

    return {
        "generated_at": datetime.now().isoformat(),
        "llm_label": llm_label,
        "args": {
            "scenario": list(args.scenario),
            "runs": args.runs,
            "concurrency": args.concurrency,
            "api_provider": args.api_provider,
            "model": args.model,
            "test_mode": args.test_mode,
        },
        "overall_summary": _summarize_results(all_results),
        "scenarios": scenario_reports,
    }


def _render_distribution_rows(distribution: dict[str, int]) -> str:
    """将分布字典渲染为 HTML 表格的 <tr> 行字符串。"""
    if not distribution:
        return '<tr><td colspan="3">无</td></tr>'

    max_value = max(distribution.values())
    rows: list[str] = []
    for label, count in sorted(distribution.items(), key=lambda item: item[1], reverse=True):
        width = 0.0 if max_value == 0 else (count / max_value) * 100
        rows.append(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{count}</td>"
            f"<td><div class=\"bar-track\"><div class=\"bar-fill\" style=\"width:{width:.2f}%\"></div></div></td>"
            "</tr>"
        )
    return "".join(rows)


def _render_scenario_cards(scenarios: list[dict[str, object]]) -> str:
    """将每个场景的统计信息渲染为 HTML 卡片列表。"""
    cards: list[str] = []
    for scenario in scenarios:
        summary = scenario["summary"]
        cards.append(
            "<section class=\"scenario-card\">"
            f"<h2>{escape(str(scenario['name']))}</h2>"
            f"<p class=\"scenario-desc\">{escape(str(scenario['description']))}</p>"
            "<div class=\"metrics-grid\">"
            f"<div class=\"metric\"><span>总测试次数</span><strong>{summary['total_runs']}</strong></div>"
            f"<div class=\"metric\"><span>规则遵循率</span><strong>{summary['adherence_rate']:.2%}</strong></div>"
            f"<div class=\"metric\"><span>成功次数</span><strong>{summary['success_runs']}</strong></div>"
            f"<div class=\"metric\"><span>解析纠偏率</span><strong>{summary['normalized_rate']:.2%}</strong></div>"
            "</div>"
            "<div class=\"meta-line\">"
            f"<span>Actor: {escape(str(scenario['actor_id']))}</span>"
            f"<span>Phase: {escape(str(scenario['phase']))}</span>"
            f"<span>Subphase: {escape(str(scenario['subphase']))}</span>"
            f"<span>Request: {escape(str(scenario['request_kind']))}</span>"
            f"<span>Allowed: {escape(', '.join(scenario['allowed_actions']))}</span>"
            "</div>"
            "<div class=\"tables\">"
            "<div class=\"table-card\">"
            "<h3>错误分布</h3>"
            "<table><thead><tr><th>错误码</th><th>次数</th><th>占比</th></tr></thead><tbody>"
            f"{_render_distribution_rows(summary['error_distribution'])}"
            "</tbody></table>"
            "</div>"
            "<div class=\"table-card\">"
            "<h3>纠偏字段分布</h3>"
            "<table><thead><tr><th>字段</th><th>次数</th><th>占比</th></tr></thead><tbody>"
            f"{_render_distribution_rows(summary['normalized_field_distribution'])}"
            "</tbody></table>"
            "</div>"
            "</div>"
            "</section>"
        )
    return "".join(cards)


def _render_html_report(report_data: dict[str, object]) -> str:
    """渲染完整的 HTML 报告页面。"""
    overall = report_data["overall_summary"]
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Prompt Rule Adherence Report</title>
  <style>
    :root {{
      --bg: #f4efe7;
      --panel: #fffdf8;
      --ink: #1e2430;
      --muted: #6c7483;
      --line: #ded6c8;
      --accent: #0f766e;
      --accent-soft: #cdebe6;
      --danger: #b42318;
      --shadow: 0 12px 40px rgba(20, 26, 35, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(15,118,110,0.12), transparent 28%),
        linear-gradient(180deg, #f8f4ed 0%, var(--bg) 100%);
      color: var(--ink);
    }}
    .page {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 28px;
      box-shadow: var(--shadow);
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: 34px;
      line-height: 1.1;
    }}
    .hero p {{
      margin: 6px 0;
      color: var(--muted);
    }}
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 14px;
      margin-top: 22px;
    }}
    .metric {{
      background: #fcfaf6;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
    }}
    .metric strong {{
      font-size: 28px;
      font-weight: 700;
    }}
    .scenario-card {{
      margin-top: 20px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 24px;
      box-shadow: var(--shadow);
    }}
    .scenario-card h2, .table-card h3 {{
      margin: 0 0 10px;
    }}
    .scenario-desc {{
      margin: 0;
      color: var(--muted);
    }}
    .meta-line {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
      color: var(--muted);
      font-size: 13px;
    }}
    .tables {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
      margin-top: 18px;
    }}
    .table-card {{
      background: #fcfaf6;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-top: 1px solid var(--line);
      vertical-align: middle;
      font-size: 14px;
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
      border-top: none;
    }}
    .bar-track {{
      width: 100%;
      height: 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      overflow: hidden;
    }}
    .bar-fill {{
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--accent), #14b8a6);
    }}
    .footer {{
      margin-top: 18px;
      color: var(--muted);
      font-size: 13px;
    }}
    .danger {{
      color: var(--danger);
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>Prompt Rule Adherence Report</h1>
      <p>生成时间: {escape(str(report_data['generated_at']))}</p>
      <p>评估模型: {escape(str(report_data['llm_label']))}</p>
      <p>场景: {escape(', '.join(report_data['args']['scenario']))} | 每场景执行: {report_data['args']['runs']} | 并发度: {report_data['args']['concurrency']}</p>
      <div class="metrics-grid">
        <div class="metric"><span>总测试次数</span><strong>{overall['total_runs']}</strong></div>
        <div class="metric"><span>规则遵循率</span><strong>{overall['adherence_rate']:.2%}</strong></div>
        <div class="metric"><span>成功次数</span><strong>{overall['success_runs']}</strong></div>
        <div class="metric"><span>失败次数</span><strong class="danger">{overall['failed_runs']}</strong></div>
        <div class="metric"><span>解析纠偏次数</span><strong>{overall['normalized_runs']}</strong></div>
        <div class="metric"><span>解析纠偏率</span><strong>{overall['normalized_rate']:.2%}</strong></div>
      </div>
      <p class="footer">该报告基于项目现有 BaseAgent + Judge 单步切片评估链路生成，没有启动完整游戏循环。</p>
    </section>
    {_render_scenario_cards(report_data['scenarios'])}
  </main>
</body>
</html>
"""


def _write_reports(
    report_data: dict[str, object],
    report_dir: Path,
    report_prefix: str,
) -> tuple[Path, Path]:
    """将报告数据写出为 JSON 与 HTML 文件，并返回其绝对路径。"""
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"{report_prefix}_{timestamp}.json"
    html_path = report_dir / f"{report_prefix}_{timestamp}.html"
    json_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(_render_html_report(report_data), encoding="utf-8")
    return json_path.resolve(), html_path.resolve()


async def async_main() -> None:
    """异步主流程：并发跑完所有场景并写出报告。"""
    args = parse_args()
    scenarios = _resolve_scenarios(args.scenario)
    work_root = Path(args.work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    llm_label, llm_factory = _build_llm_factory(args)

    print(f"评估模型: {llm_label}")
    print(f"场景数量: {len(scenarios)}")
    print(f"每场景执行次数: {args.runs}")
    print(f"并发度: {args.concurrency}")

    scenario_results_map: dict[str, list[RunResult]] = {}
    for scenario in scenarios:
        results = await _evaluate_scenario(
            scenario=scenario,
            runs=args.runs,
            concurrency=args.concurrency,
            llm_factory=llm_factory,
            work_root=work_root,
        )
        scenario_results_map[scenario.name] = results
        _print_scenario_report(scenario, results)

    all_results = [result for results in scenario_results_map.values() for result in results]
    if len(scenarios) > 1:
        _print_overall_report(all_results)

    report_data = _build_report_data(args, llm_label, scenarios, scenario_results_map)
    json_path, html_path = _write_reports(
        report_data=report_data,
        report_dir=Path(args.report_dir),
        report_prefix=args.report_prefix,
    )
    print(f"\nJSON 报告: {json_path}")
    print(f"HTML 报告: {html_path}")


def main() -> None:
    """同步入口：包装运行 async_main。"""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
