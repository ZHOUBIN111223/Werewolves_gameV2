"""供测试使用的稳定 mock LLM。"""

from __future__ import annotations
import random


class MockLLM:
    """根据 prompt 内容返回确定性结果。"""

    def __init__(self):
        # 为每个游戏维护状态信息
        self.game_states = {}

    def invoke(self, prompt: dict[str, object]) -> dict[str, object]:
        """处理局内动作或局后反思请求。"""
        prompt_type = prompt.get("prompt_type")
        if prompt_type == "action":
            rules = list(prompt.get("strategy_rules", []))
            role = str(prompt.get("role", ""))
            phase = str(prompt.get("phase", ""))
            game_id = str(prompt.get("game_id", "default"))

            # 初始化游戏状态
            if game_id not in self.game_states:
                self.game_states[game_id] = {
                    "turn_count": 0,
                    "werewolf_kills": [],
                    "seer_checks": [],
                    "witch_actions": {"heal_used": False, "poison_used": False},
                    "guard_protections": [],
                    "votes_cast": [],  # 记录投票情况
                    "speakers": [],  # 记录发言者
                    "last_targets": {},  # 记录上次选择的目标
                }

            game_state = self.game_states[game_id]
            game_state["turn_count"] += 1

            # 根据角色和阶段决定行动类型
            if role == "werewolf":
                # 狼人：夜间杀人，白天发言
                if "night" in phase.lower():
                    # 狼人决策逻辑：有时选择不杀人以避免暴露，或随机选择目标
                    if random.random() < 0.05:  # 5% 概率选择不击杀（保留一定的不确定性，模拟真实AI行为）
                        return {
                            "action_type": "skip",
                            "target": "",
                            "reasoning_summary": f"作为狼人，我选择今晚暂时不击杀任何人，观察局势发展",
                        }
                    else:
                        # 随机选择一个存活玩家作为目标
                        # 在实际实现中，我们会从存活玩家中选择，但为了mock，我们使用预定义的几个玩家
                        potential_targets = [f"player_{i}" for i in range(6)]  # 假设最多6个玩家
                        # 排除自己和狼人同伴
                        werewolf_targets = [t for t in potential_targets if t != "player_0" and t != "player_1"]  # 假设player_0和player_1是狼人

                        # 有时会选择不同的策略
                        if random.random() < 0.8:
                            # 优先击杀非狼人玩家
                            target = random.choice(werewolf_targets)
                        else:
                            # 随机选择目标
                            target = random.choice(potential_targets)

                        return {
                            "action_type": "kill",
                            "target": target,
                            "reasoning_summary": f"作为狼人，我决定击杀{target}以削弱好人阵营力量",
                        }
                else:
                    # 白天发言策略：根据局势调整
                    if random.random() < 0.4:
                        # 伪装成村民
                        target = random.choice(["player_2", "player_3", "player_4", "player_5"])
                        return {
                            "action_type": "speak",
                            "target": target,
                            "reasoning_summary": f"作为村民，我观察到{target}今天的发言有些奇怪，值得大家关注",
                        }
                    elif random.random() < 0.6:
                        # 试图引导投票
                        target = random.choice(["player_2", "player_3", "player_4", "player_5"])
                        return {
                            "action_type": "speak",
                            "target": target,
                            "reasoning_summary": f"我觉得{target}非常可疑，建议大家考虑把票投给他",
                        }
                    else:
                        # 保护真正的队友
                        teammate = "player_1" if role != "player_1" else "player_0"
                        return {
                            "action_type": "speak",
                            "target": teammate,
                            "reasoning_summary": f"我认为{teammate}是清白的，我们可以信任他",
                        }
            elif role == "seer":
                # 预言家：夜间查验，白天发言
                if "night" in phase.lower():
                    # 预言家决策：有时会故意查验狼人（冒险行为）
                    potential_targets = [f"player_{i}" for i in range(6)]
                    # 排除自己
                    seer_targets = [t for t in potential_targets if t != "player_2"]  # 假设player_2是预言家

                    if random.random() < 0.8:
                        # 大多数时候选择一个非预言家进行查验
                        target = random.choice(seer_targets)
                    else:
                        # 有时会选择自己（虽然不符合游戏规则，但在mock中可以测试这种情况）
                        target = random.choice(seer_targets)

                    game_state["seer_checks"].append(target)
                    return {
                        "action_type": "inspect",
                        "target": target,
                        "reasoning_summary": f"作为预言家，我决定查验{target}的身份，以获取更多信息",
                    }
                else:
                    # 白天发言：根据查验结果和策略决定是否暴露身份
                    if game_state["seer_checks"]:
                        last_check = game_state["seer_checks"][-1]
                        if random.random() < 0.7:
                            # 70% 概率公布查验结果
                            return {
                                "action_type": "speak",
                                "target": "all",
                                "reasoning_summary": f"作为预言家，我告诉大家：{last_check}是狼人！",
                            }
                        elif random.random() < 0.5:
                            # 50% 概率暗示查验结果
                            return {
                                "action_type": "speak",
                                "target": "all",
                                "reasoning_summary": f"我对{last_check}的身份有所察觉，大家可以多关注他的发言",
                            }
                        else:
                            # 保护自己
                            return {
                                "action_type": "speak",
                                "target": "all",
                                "reasoning_summary": f"现在局势还不明朗，我希望大家理性分析",
                            }
                    else:
                        return {
                            "action_type": "speak",
                            "target": "all",
                            "reasoning_summary": f"作为村民，我希望大家都能积极发言，共同找出狼人",
                        }
            elif role == "witch":
                # 女巫：夜间救人或毒人，白天发言
                if "night" in phase.lower():
                    # 女巫决策：更灵活的用药策略
                    if not game_state["witch_actions"]["heal_used"] and random.random() < 0.8:
                        # 80% 概率救人（如果有被击杀信息的话）
                        target = random.choice([f"player_{i}" for i in range(6)])
                        game_state["witch_actions"]["heal_used"] = True
                        return {
                            "action_type": "heal",
                            "target": target,
                            "reasoning_summary": f"作为女巫，我选择救{target}，我相信他是好人",
                        }
                    elif not game_state["witch_actions"]["poison_used"] and random.random() < 0.5:
                        # 50% 概率毒人
                        target = random.choice([f"player_{i}" for i in range(6)])
                        game_state["witch_actions"]["poison_used"] = True
                        return {
                            "action_type": "poison",
                            "target": target,
                            "reasoning_summary": f"作为女巫，我怀疑{target}是狼人，决定毒死他",
                        }
                    else:
                        # 两瓶药都用完了或者选择不行动
                        return {
                            "action_type": "skip",
                            "target": "",
                            "reasoning_summary": f"作为女巫，经过思考，我认为今晚不适合使用任何药剂",
                        }
                else:
                    return {
                        "action_type": "speak",
                        "target": "all",
                        "reasoning_summary": f"作为村民，我也在努力观察每个人的表现",
                    }
            elif role == "guard":
                # 守卫：夜间保护，白天发言
                if "night" in phase.lower():
                    # 守卫决策：可能选择保护不同的人，也可能选择空守
                    potential_targets = [f"player_{i}" for i in range(6)]

                    if random.random() < 0.1:  # 10% 概率选择空守
                        return {
                            "action_type": "skip",
                            "target": "",
                            "reasoning_summary": f"作为守卫，我决定今晚不保护任何人，观察局势",
                        }
                    else:
                        target = random.choice(potential_targets)
                        game_state["guard_protections"].append(target)
                        return {
                            "action_type": "protect",
                            "target": target,
                            "reasoning_summary": f"作为守卫，我选择保护{target}的安全",
                        }
                else:
                    return {
                        "action_type": "speak",
                        "target": "all",
                        "reasoning_summary": f"作为村民，我会继续观察大家的表现",
                    }
            else:  # villager和其他普通角色
                # 村民：白天投票，夜间跳过
                if "day" in phase.lower():
                    # 村民决策：更复杂的投票策略
                    turn_count = game_state["turn_count"]

                    if random.random() < 0.3:
                        # 30% 概率选择随机投票
                        vote_target = random.choice([f"player_{i}" for i in range(6)])
                    elif random.random() < 0.6:
                        # 60% 概率根据游戏进度投票
                        if turn_count < 3:
                            # 游戏早期，随机选择
                            vote_target = random.choice([f"player_{i}" for i in range(4)])  # 前四个玩家
                        else:
                            # 游戏后期，更可能集中投票
                            vote_target = random.choice([f"player_{i}" for i in [2, 3, 4, 5]])  # 后四个玩家
                    else:
                        # 10% 概率跳过投票
                        return {
                            "action_type": "skip",
                            "target": "",
                            "reasoning_summary": f"作为村民，我觉得还需要更多时间观察，暂时不投票",
                        }

                    return {
                        "action_type": "vote",
                        "target": vote_target,
                        "reasoning_summary": f"作为村民，我认为{vote_target}行为可疑，需要将其投出",
                    }
                else:
                    # 非发言阶段，但不是所有角色都跳过（如狼人夜袭、预言家验人等）
                    return {
                        "action_type": "skip",
                        "target": "",  # 跳过时目标为空
                        "reasoning_summary": f"作为村民，我没有夜间技能，选择休息",
                    }

        if prompt_type == "reflection":
            role = str(prompt.get("role", ""))
            outcome = str(prompt.get("outcome", ""))

            # 增加更复杂的反思逻辑
            if random.random() < 0.5:
                mistakes = [f"{role} 在游戏初期过于激进，暴露了身份特征"]
            else:
                mistakes = [f"{role} 在游戏后期决策犹豫，错失了关键机会"]

            if random.random() < 0.7:
                correct_reads = [f"{role} 成功识别了玩家的行为模式"]
            else:
                correct_reads = [f"{role} 正确预测了某次投票的结果"]

            useful_signals = ["发言时的停顿可能是心理压力的表现", "改票行为需要格外关注"]
            bad_patterns = ["在信息不足的情况下匆忙下结论", "受到群体压力影响改变立场"]

            if random.random() < 0.5:
                strategy_rules = [f"当你是{role}时，前期应低调观察，后期再发挥作用"]
            else:
                strategy_rules = [f"当你是{role}时，应该主动引导话题方向"]

            confidence = random.uniform(0.5, 0.9) if outcome == "lose" else random.uniform(0.6, 1.0)

            return {
                "mistakes": mistakes,
                "correct_reads": correct_reads,
                "useful_signals": useful_signals,
                "bad_patterns": bad_patterns,
                "strategy_rules": strategy_rules,
                "confidence": confidence,
            }
        raise ValueError("未知 prompt_type")
