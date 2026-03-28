"""
狼人杀游戏主入口文件

此文件用于启动狼人杀游戏，配置游戏参数并运行游戏实例。
使用真实的LLM服务进行游戏。
支持运行多局游戏并实现经验传承机制。
"""

import asyncio
import argparse
import os
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from src.controller.controller import Controller
from src.events.event_bus import EventBus
from src.metrics.evaluation import export_run_metrics
from src.monitoring.decision_eval import evaluate_games, export_eval_scores
from src.llm.real_llm import RealLLM  # 使用真实LLM
from config import APIConfig, GameConfig, AppConfig, get_config_for_provider, validate_config


def run_single_game(args, game_num, total_games, llm_service, global_store, evaluation_game_contexts):
    """
    运行单局游戏

    Args:
        args: 命令行参数
        game_num: 当前游戏编号
        total_games: 总游戏数
        llm_service: LLM服务实例
        global_store: 全局事件存储实例

    Returns:
        dict: 游戏结果统计
    """
    print(f"\n========== 第 {game_num}/{total_games} 局游戏开始 ==========")

    game_id = f"game_{game_num}"

    try:
        # 选择游戏配置
        num_players = 6
        if args.game_config == '6_players':
            num_players = 6
        elif args.game_config == '9_players':
            num_players = 9
        elif args.game_config == '12_players':
            num_players = 12

        game_role_config = GameConfig.GAME_ROLES_CONFIG.get(num_players, GameConfig.GAME_ROLES_CONFIG[6])

        # 为本局游戏生成唯一ID
        game_id = f"game_{game_num}_{datetime.now().strftime('%H%M%S')}"

        # 创建事件总线，用于各个组件间的通信
        event_bus = EventBus(global_store=global_store)

        # 创建中央控制器，协调整个游戏流程
        controller = Controller(
            base_dir=os.path.join(AppConfig.STORE_PATH, f"controller_{game_num}"),
            llm_service=llm_service,
            global_store=global_store,
        )

        print(f"正在初始化 {num_players} 人局游戏组件...")
        print(f"游戏角色配置: {list(game_role_config.keys())}")

        import random

        # 生成玩家配置，确保每个玩家都有唯一的ID
        player_id_counter = 0
        players = {}
        for role, count in game_role_config.items():
            for _ in range(count):
                players[f"player_{player_id_counter}"] = role
                player_id_counter += 1

        # 随机打乱角色分配，确保每局游戏中角色随机分配给AI智能体
        player_ids = list(players.keys())
        roles = list(players.values())

        # 如果指定了随机种子，则使用它以确保可重现性
        if hasattr(args, 'random_seed') and args.random_seed is not None:
            random.seed(args.random_seed + game_num)  # 使用游戏编号作为种子的一部分，确保不同游戏之间也是随机的

        random.shuffle(roles)

        # 重新构建玩家字典，保持ID不变但随机分配角色
        players = dict(zip(player_ids, roles))

        print(f"实际分配玩家: {players}")
        evaluation_game_contexts[game_id] = dict(players)

        # 启动游戏
        print("游戏开始！")

        # 运行游戏
        controller.start_game(
            game_id=game_id,
            players=players,
            event_bus=event_bus,  # 传递事件总线
            llm_service=llm_service  # 传递LLM服务
        )

        # 等待游戏结束 - 修复：正确的异步处理方式，避免嵌套事件循环
        import asyncio

        # 创建一个新的事件循环在单独的线程中运行，以确保不会与任何潜在的现有事件循环冲突
        import threading
        import concurrent.futures

        def run_in_fresh_loop():
            """在独立线程中创建并运行全新的事件循环，避免与外部 loop 冲突。"""
            return asyncio.run(run_game_with_async_controller(controller, game_id))

        # 在新线程中运行，确保有一个全新的事件循环
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_in_fresh_loop)
            result = future.result()  # 等待异步游戏完成

        print("游戏结束！")

        # 获取游戏结果
        game_status = controller.get_game_status(game_id)
        winner = game_status.get('winner', 'unknown')

        print(f"获胜方: {winner}")

        # 统计信息
        result = {
            'game_id': game_id,
            'winner': winner,
            'num_players': num_players,
            'roles': game_role_config,
            'reflection_markdown': str(
                controller.base_dir / "reflections" / f"{game_id}_agent_reflections.md"
            ),
            'success': True,
            'error': None
        }

        return result
    except KeyboardInterrupt:
        print(f"\n第 {game_num} 局游戏被用户中断。")
        return {'game_id': game_id, 'success': False, 'error': 'KeyboardInterrupt'}
    except Exception as e:
        error_msg = str(e)
        print(f"第 {game_num} 局游戏运行过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        return {'game_id': game_id, 'success': False, 'error': error_msg}


async def run_game_with_async_controller(controller, game_id):
    """
    辅助函数：在一个事件循环中运行游戏

    Args:
        controller: 游戏控制器
        game_id: 游戏ID
    """
    await controller.run_game_loop(game_id)


def export_run_decision_eval(global_store, game_results, evaluation_game_contexts, output_path):
    successful_eval_contexts = {
        result['game_id']: evaluation_game_contexts[result['game_id']]
        for result in game_results
        if result.get('success') and result.get('game_id') in evaluation_game_contexts
    }
    eval_scores = asyncio.run(evaluate_games(global_store, successful_eval_contexts))
    export_eval_scores(eval_scores, output_path)
    return output_path


def export_run_metric_artifacts(global_store, game_results, evaluation_game_contexts, output_dir, run_metadata):
    successful_eval_contexts = {
        result['game_id']: evaluation_game_contexts[result['game_id']]
        for result in game_results
        if result.get('success') and result.get('game_id') in evaluation_game_contexts
    }
    return asyncio.run(
        export_run_metrics(
            global_store,
            successful_eval_contexts,
            output_dir,
            run_metadata=run_metadata,
        )
    )


def main():
    """
    主函数：初始化并启动狼人杀游戏（支持多局运行）
    """
    try:
        parser = argparse.ArgumentParser(description='狼人杀游戏 - 支持多局连续运行')
        parser.add_argument('--players', type=int, default=6, help='玩家数量 (默认: 6)')
        parser.add_argument('--game-config', type=str, choices=['6_players', '9_players', '12_players'], default='6_players', help='游戏配置 (6_players / 9_players / 12_players)')
        parser.add_argument('--api-provider', type=str, choices=['openai', 'anthropic', 'bailian', 'custom', 'mock'],
                           default=APIConfig.DEFAULT_API_PROVIDER, help=f'API提供商 (默认: {APIConfig.DEFAULT_API_PROVIDER})')
        parser.add_argument('--api-url', type=str, default=None, help='LLM API服务地址')
        parser.add_argument('--api-key', type=str, default=None, help='LLM API密钥')
        parser.add_argument('--model', type=str, default=None, help='LLM模型名称')
        parser.add_argument('--timeout', type=int, default=APIConfig.API_TIMEOUT, help='请求超时时间')
        parser.add_argument('--max-retries', type=int, default=APIConfig.MAX_RETRIES, help='最大重试次数')
        parser.add_argument('--games', type=int, default=3, help='运行游戏局数 (默认: 3)')
        parser.add_argument('--report', action='store_true', help='生成详细报告')
        parser.add_argument('--random-seed', type=int, default=None, help='随机种子，用于复现特定游戏场景 (可选)')
        parser.add_argument('--test-mode', action='store_true', help='使用 MockLLM 运行本地测试')

        args = parser.parse_args()

        print("欢迎来到AI驱动的狼人杀游戏！")
        print(f"计划运行 {args.games} 局游戏...")

        # 验证配置
        if not args.test_mode and args.api_provider != 'mock':  # 仅在非测试模式和非mock模式下验证配置
            try:
                validate_config(args.api_provider)
            except ValueError as e:
                print(f"配置错误: {e}")
                return
        else:
            # 测试模式或mock模式下直接使用MockLLM
            print("运行于测试模式，使用MockLLM...")

        # 根据模式决定使用哪个LLM服务
        if args.test_mode:
            # 测试模式下使用MockLLM
            from src.llm.mock_llm import MockLLM
            llm_service = MockLLM()

            # 创建全局事件存储，用于持久化游戏事件（即使在测试模式下也启用）
            from src.events.async_store import GlobalEventStore
            global_store = GlobalEventStore(db_path=os.path.join(AppConfig.STORE_PATH, f"global_events_test.db"))
        else:
            # 获取对应的API配置
            api_config = get_config_for_provider(args.api_provider)

            # 如果命令行提供了覆盖值，则使用它们
            api_url = args.api_url or api_config.get('base_url') or api_config.get('endpoint')
            api_key = os.getenv("LITELLM_API_KEY", args.api_key or api_config['api_key'])
            model = args.model or api_config['default_model']

            # 检查API密钥是否设置
            if not api_key or api_key.startswith("sk-") and len(api_key) < 20:  # 假设真实API密钥长度应该超过20个字符
                print("警告: 您可能正在使用默认或测试API密钥，建议在环境变量中设置您的个人API密钥")
                print("设置方式: export LITELLM_API_KEY='your_actual_api_key'")

            llm_service = RealLLM(
                api_url=api_url,
                api_key=api_key,
                model=model,
                timeout=args.timeout,
                max_retries=args.max_retries,
            )

            # 创建全局事件存储，用于持久化游戏事件
            from src.events.async_store import GlobalEventStore
            global_store = GlobalEventStore(db_path=os.path.join(AppConfig.STORE_PATH, f"global_events.db"))

        # 存储所有游戏结果
        game_results = []
        evaluation_game_contexts = {}
        start_time = datetime.now()

        print(f"开始连续运行 {args.games} 局游戏...")

        # 运行多局游戏
        for game_num in range(1, args.games + 1):
            try:
                result = run_single_game(
                    args,
                    game_num,
                    args.games,
                    llm_service,
                    global_store,
                    evaluation_game_contexts,
                )
                game_results.append(result)
                print(f"\n----- Game {game_num} Result -----")
                print(json.dumps(result, ensure_ascii=False, indent=2))

                if result['success']:
                    print(f"第 {game_num} 局游戏完成，获胜方: {result['winner']}")
                else:
                    print(f"第 {game_num} 局游戏失败: {result['error']}")

            except Exception as e:
                print(f"运行第 {game_num} 局游戏时发生异常: {e}")

                game_results.append({
                    'game_id': f"game_{game_num}",
                    'success': False,
                    'error': str(e)
                })

        # 统计结果
        total_games = len(game_results)
        successful_games = sum(1 for r in game_results if r['success'])
        failed_games = total_games - successful_games

        # 按获胜方统计
        winner_counts = defaultdict(int)
        for result in game_results:
            if result['success']:
                winner_counts[result['winner']] += 1

        end_time = datetime.now()
        duration = end_time - start_time
        run_timestamp = end_time.strftime('%Y%m%d_%H%M%S')

        print(f"\n========== 多局游戏运行完成 ==========")
        print(f"总耗时: {duration}")
        print(f"总游戏数: {total_games}")
        print(f"成功: {successful_games}, 失败: {failed_games}")
        print(f"获胜方统计:")
        for winner, count in winner_counts.items():
            print(f"  {winner}: {count} 局")

        # 保存结果到文件
        results_file = os.path.join("results", f"game_results_{run_timestamp}.json")
        results_path = Path(results_file)
        results_path.parent.mkdir(parents=True, exist_ok=True)  # 确保目录存在

        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump({
                'summary': {
                    'total_games': total_games,
                    'successful_games': successful_games,
                    'failed_games': failed_games,
                    'duration_seconds': duration.total_seconds(),
                    'start_time': start_time.isoformat(),
                    'end_time': end_time.isoformat(),
                    'winner_counts': dict(winner_counts)
                },
                'details': game_results
            }, f, ensure_ascii=False, indent=2)

        print(f"\n详细结果已保存到: {results_file}")

        eval_scores_path = Path("results") / f"eval_scores_{run_timestamp}.json"
        try:
            export_run_decision_eval(
                global_store,
                game_results,
                evaluation_game_contexts,
                eval_scores_path,
            )
            print(f"评估分数已保存到: {eval_scores_path}")
        except Exception as eval_error:
            print(f"导出评估分数时出现错误: {eval_error}")

        metrics_output_dir = Path("outputs") / "metrics" / run_timestamp
        try:
            metrics_artifacts = export_run_metric_artifacts(
                global_store,
                game_results,
                evaluation_game_contexts,
                metrics_output_dir,
                run_metadata={
                    'run_timestamp': run_timestamp,
                    'total_games': total_games,
                    'successful_games': successful_games,
                    'failed_games': failed_games,
                    'duration_seconds': duration.total_seconds(),
                    'start_time': start_time.isoformat(),
                    'end_time': end_time.isoformat(),
                    'winner_counts': dict(winner_counts)
                },
            )
            print(f"Metrics artifacts saved to: {metrics_artifacts['output_dir']}")
            print(f"Metrics summary file: {metrics_artifacts['summary_json']}")
        except Exception as metrics_error:
            print(f"Failed to export metrics artifacts: {metrics_error}")

        if args.report:
            print("\n======= 详细报告 =======")
            for i, result in enumerate(game_results, 1):
                status = "成功" if result['success'] else "失败"
                print(f"第 {i} 局: {status}", end="")
                if result['success']:
                    print(f", 获胜方: {result['winner']}")
                else:
                    print(f", 错误: {result['error']}")
    except Exception as e:
        print(f"游戏初始化过程中出现严重错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
