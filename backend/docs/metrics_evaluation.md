# Metrics Evaluation

## 新增文件

- `src/metrics/__init__.py`
- `src/metrics/evaluation/__init__.py`
- `src/metrics/evaluation/analyzer.py`
- `docs/metrics_evaluation.md`

## 修改的旧文件

- `main.py`
  目的：在多局运行结束后，调用独立的赛后评估导出器，把逐局明细和多局汇总写入新的指标目录。

## 接入方式

- 不改游戏主循环规则。
- 不改角色技能逻辑。
- 不改对话逻辑。
- 不改胜负判定逻辑。
- 不改行动与调度逻辑。
- 指标系统只读取现有 `Action` 与 `SystemEvent` 事件流，按局做赛后分析。

## 代码落点识别

- 游戏主循环：`src/controller/controller.py` 的 `run_game_loop`
- 阶段推进：`src/controller/judge.py` 的 `advance_phase`
- 投票记录：
  - 白天投票写入：`src/controller/judge.py` 的 `process_action`，事件 `vote_recorded`
  - 警长投票写入：`src/controller/judge.py` 的 `process_action`，事件 `sheriff_vote_recorded`
- 技能使用记录：
  - 狼刀：`kill_attempted`
  - 守卫：`protection_used`
  - 女巫解药：`heal_used`
  - 女巫毒药：`poison_used`
  - 预言家查验：`inspection_result`
- 死亡 / 淘汰记录：`player_eliminated`
- 胜负判定：
  - 判定函数：`src/controller/judge.py` 的 `check_victory_conditions`
  - 最终落盘事件：`game_ended`

## 输出目录

- 新目录：`outputs/metrics/<run_timestamp>/`
- 逐局明细：`outputs/metrics/<run_timestamp>/per_game/<game_id>.json`
- 多局汇总 JSON：`outputs/metrics/<run_timestamp>/summary.json`
- 多局汇总 CSV：`outputs/metrics/<run_timestamp>/summary.csv`
- 导出清单：`outputs/metrics/<run_timestamp>/manifest.json`

## 指标计算方式

### A. 胜负指标

- `overall_win_rate`
  - 统计口径：按局统计。
  - 结果形式：`villagers` / `werewolves` 各自赢下的局数与占比。

- `side_win_rate`
  - 统计口径：按玩家实例统计。
  - 计算方式：某阵营玩家实例中，最终获胜的实例数 / 该阵营总实例数。

- `role_win_rate`
  - 统计口径：按角色实例统计。
  - 计算方式：某角色实例中，最终获胜的实例数 / 该角色总实例数。

### B. 技能命中指标

- `witch_poison_accuracy`
  - 分母：女巫使用毒药次数。
  - 分子：被毒目标是狼人。

- `witch_antidote_accuracy`
  - 分母：女巫使用解药次数。
  - 分子：被救目标没有出现在该夜最终死亡名单里。

- `guard_protect_accuracy`
  - 分母：守卫守护次数。
  - 分子：守护目标属于好人阵营。

- `guard_effective_protect_rate`
  - 分母：守卫守护次数。
  - 分子：该夜出现 `attack_protected`，且被挡刀目标就是守护目标。

- `seer_identify_accuracy`
  - 分母：预言家查验次数。
  - 分子：查验目标是狼人。

- `hunter_shot_accuracy`
  - 分母：猎人开枪次数。
  - 分子：开枪目标是狼人。
  - 说明：当前项目里没有新增猎人开枪主流程；如果没有 `hunt` 动作，分母为 0，结果为 `null`。

### C. 投票与处决指标

- `wolf_day_vote_accuracy`
  - 分母：狼人白天投票次数。
  - 分子：投票目标属于好人阵营。

- `good_day_vote_accuracy`
  - 分母：好人白天投票次数。
  - 分子：投票目标是狼人。

- `good_sheriff_vote_accuracy`
  - 分母：好人警长投票次数。
  - 分子：投票目标属于好人阵营。

- `execution_hit_rate`
  - 分母：发生“白天放逐成功”的天数。
  - 分子：被白天放逐的玩家是狼人。

- `good_misexecution_rate`
  - 分母：发生“白天放逐成功”的天数。
  - 分子：被白天放逐的玩家属于好人阵营。

- `wolf_survival_under_pressure_rate`
  - 分母：白天票型中，获得当日最高票且因此进入“抗推压力位”的狼人次数。
  - 分子：该狼人最终没有在当天被放逐。
  - 说明：平票无人出局也算狼人抗推成功。

### D. 信息与生存指标

- `seer_info_conversion_rate`
  - 分母：预言家首次查到的狼人目标数。
  - 分子：这些狼人之后被白天投票放逐的数量。
  - 说明：这里把“信息利用”限定为“查到狼人后，最终转化为白天放逐结果”。

- `avg_survival_days`
  - 统计口径：按玩家实例统计平均存活天数。
  - 计数规则：
    - 在 `night_1` 出局记为 0 天。
    - 在 `day_1` 出局记为 1 天。
    - 在 `night_2` 出局记为 1 天。
    - 在 `day_2` 出局记为 2 天。
    - 存活到对局结束的玩家，按最终结算前阶段折算。

- `early_elimination_rate`
  - 分母：全部玩家实例数。
  - 分子：在 `night_1`、`day_1`、`night_2`、`day_2` 出局的玩家数。
  - 说明：原需求“首日/前两日”存在歧义，这里统一按“前两天窗口”统计，并在输出中固定这一口径。

## 逐局文件内容

- 对局基础信息：`game_id`、`winner`、最终结算前阶段、事件总数
- 玩家级结果：角色、阵营、是否获胜、存活天数、出局原因
- 原始统计记录：
  - 白天投票明细与票数汇总
  - 警长投票明细
  - 夜间技能动作明细
  - 查验记录
  - 死亡 / 放逐记录
- 逐局指标结果

## 汇总文件内容

- `summary.json`
  - 保留所有聚合指标的分子、分母、rate
- `summary.csv`
  - 扁平化输出，便于批量实验后直接表格分析

## 最小侵入式说明

- 新增模块完全独立。
- 旧逻辑只需要在 `main.py` 的赛后汇总位置增加一次导出调用。
- 所有指标都基于已有事件日志回放，不往现有规则代码里塞新的判定分支。
