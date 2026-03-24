"""枚举类型定义模块。

为事件系统提供严格的类型约束，防止AI输出幻觉问题。
"""

from enum import Enum
from typing import List


class GamePhase(Enum):
    """游戏阶段枚举"""
    SETUP = "setup"           # 游戏设置阶段
    DAY_1 = "day_1"           # 第一天讨论阶段
    NIGHT_1 = "night_1"       # 第一夜行动阶段
    DAY_2 = "day_2"           # 第二天讨论阶段
    NIGHT_2 = "night_2"       # 第二夜行动阶段
    DAY_3 = "day_3"           # 第三天讨论阶段
    NIGHT_3 = "night_3"       # 第三夜行动阶段
    DAY_4 = "day_4"
    NIGHT_4 = "night_4"
    DAY_5 = "day_5"
    NIGHT_5 = "night_5"
    DAY_6 = "day_6"
    NIGHT_6 = "night_6"
    DAY_7 = "day_7"
    NIGHT_7 = "night_7"
    DAY_8 = "day_8"
    NIGHT_8 = "night_8"
    DAY_9 = "day_9"
    NIGHT_9 = "night_9"
    DAY_10 = "day_10"
    NIGHT_10 = "night_10"
    DAY_11 = "day_11"
    NIGHT_11 = "night_11"
    DAY_12 = "day_12"
    NIGHT_12 = "night_12"
    POST_GAME = "post_game"   # 游戏结束阶段


class ActionType(Enum):
    """动作类型枚举"""
    SPEAK = "speak"           # 发言
    VOTE = "vote"             # 投票
    INSPECT = "inspect"       # 查验（预言家）
    KILL = "kill"             # 击杀（狼人）
    PROTECT = "protect"       # 保护（守卫）
    SKIP = "skip"             # 跳过
    POISON = "poison"         # 毒杀（女巫）
    HEAL = "heal"             # 救治（女巫）
    HUNT = "hunt"             # 猎杀（猎人）


class RoleType(Enum):
    """角色类型枚举"""
    VILLAGER = "villager"     # 平民
    WEREWOLF = "werewolf"     # 狼人
    SEER = "seer"             # 预言家
    GUARD = "guard"           # 守卫
    WITCH = "witch"           # 女巫
    HUNTER = "hunter"         # 猎人
    SYSTEM_JUDGE = "system_judge"  # 系统法官
