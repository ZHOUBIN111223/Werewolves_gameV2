# 决策准确率评估模块改造计划

## 目标

在不改动现有狼人杀核心流程的前提下，为 `main.py` 增加一个赛后汇总评估模块，针对一次多局运行中的所有“目标导向型行为”输出最终正确率，并自动保存为极简 JSON 文件。

## 非侵入式实现原则

1. 不改写 `Controller` / `Judge` 的核心裁决与流程推进逻辑。
2. 不在技能处理分支中插入新的博弈规则。
3. 优先复用现有全局事件账本 `GlobalEventStore`，在每局结束后按 `game_id` 回放事件并离线计算。
4. 仅在 `main.py` 增加接线逻辑：
   - 保存本次运行内每局的真实身份映射 `players`
   - 调用评估器读取事件账本
   - 导出 `eval_scores.json`

## 现有代码可复用的数据源

### 1. 真实身份

来源：`run_single_game()` 中已经生成了 `players: Dict[player_id, role]`。

用途：

- 判断目标是否为狼人
- 判断目标是否为好人阵营
- 判断目标是否为神职
- 判断“真预言家”

### 2. 行为事件

来源：`EventBus.publish_async()` 会把所有 `Action` / `SystemEvent` 持久化到 `GlobalEventStore`。

关键可复用事件：

- `Action(action_type=poison|heal|protect|inspect|kill|vote)`
- `SystemEvent(system_name=kill_attempted)`
- `SystemEvent(system_name=vote_recorded)`
- `SystemEvent(system_name=sheriff_vote_recorded)`

### 3. 请求类型区分

来源：`Action.payload["request_kind"]`

用途：

- 区分 `day_vote` 与 `sheriff_vote`
- 排除 `badge_transfer`
- 保证只统计真正的目标行为

## 评估口径

定义：

- 概率 = 正确次数 / 触发总次数
- 若某指标本次多局运行中从未触发，则输出 `null`

阵营定义：

- 狼人阵营：`werewolf`
- 好人阵营：除 `werewolf` 外的全部角色
- 神职：`seer`、`witch`、`guard`、`hunter`

### 1. 神职阵营目标行为

#### 女巫毒药准确率

- 分母：所有已执行的 `poison` 动作
- 分子：目标真实身份为 `werewolf`

#### 女巫解药准确率

- 分母：所有已执行的 `heal` 动作，排除“救了自刀狼”的情况
- 分子：目标属于好人阵营
- “救了自刀狼”判定：
  - 同一夜同一 `phase`
  - 存在 `kill_attempted`
  - 且 `killer == target == healed_player`
- 说明：
  - 当前规则里狼人本就不能刀自己，这种情况理论上不会出现
  - 仍保留该排除逻辑，保证评估口径符合需求，也兼容未来规则变动

#### 守卫守护准确率

- 分母：所有已执行的 `protect` 动作
- 分子：目标属于好人阵营

#### 守卫守护神职命中率（进阶）

- 分母：所有已执行的 `protect` 动作
- 分子：目标真实身份属于 `seer|witch|guard|hunter`

#### 预言家查验命中率

- 分母：所有已执行的 `inspect` 动作
- 分子：目标真实身份为 `werewolf`

#### 猎人开枪准确率

- 分母：所有已执行的 `hunt` 动作
- 分子：目标真实身份为 `werewolf`
- 风险说明：
  - 当前代码库中 `ActionType.HUNT` 已定义，但 `Controller/Judge` 尚未实现猎人开枪流程
  - 因此本次实现只做旁路监听，不新增猎人技能逻辑
  - 如果当前运行没有真实 `hunt` 事件，则输出 `null`

### 2. 狼人阵营目标行为

#### 狼人夜晚刀人准确率

- 分母：狼人已执行的 `kill` 动作
- 分子：目标属于好人阵营

#### 狼人白天冲票准确率

- 分母：狼人阵营在 `day_vote` 请求下执行的 `vote`
- 分子：投票目标属于好人阵营

### 3. 全体 / 平民阵营公共行为

#### 好人白天放逐投票准确率

- 分母：好人阵营在 `day_vote` 请求下执行的 `vote`
- 分子：投票目标真实身份为 `werewolf`

#### 好人警长投票准确率

- 分母：好人阵营在 `sheriff_vote` 请求下执行的 `vote`
- 分子：投票目标属于好人阵营
- 说明：
  - “真预言家”天然包含在好人阵营内
  - 该口径与需求中的“真预言家或好人阵营”一致

## 改动位置

### `main.py`

新增职责：

1. 在每局生成身份后，把 `{game_id: players}` 记录到本次运行的评估上下文
2. 在全部对局结束后，调用评估模块读取 `GlobalEventStore` 中本次运行涉及的 `game_id`
3. 将最终结果导出为：
   - `results/eval_scores.json`

### 新增评估模块

建议新增文件：`src/monitoring/decision_eval.py`

职责：

1. 定义评估指标累加器
2. 读取单局事件流并回放统计
3. 汇总多局结果
4. 输出极简 JSON 字典

## 实现步骤

1. 在 `main.py` 中为本次运行维护 `evaluation_game_contexts`
2. 新增 `decision_eval.py`
3. 提供核心接口：
   - `evaluate_games(global_store, game_contexts) -> dict`
   - `export_eval_scores(scores, output_path) -> None`
4. 在 `main.py` 多局循环结束后执行评估导出
5. 保持原有 `game_results_*.json` 输出不变

## 验证方式

1. 使用 `--test-mode` 跑至少 1 局，确认不会破坏原有游戏流程
2. 检查 `results/eval_scores.json` 是否只包含最终分数字段
3. 检查未触发指标是否为 `null`
4. 重点确认：
   - `day_vote` 与 `sheriff_vote` 不混淆
   - 好人 / 狼人阵营判断准确
   - 女巫解药排除条件不会误计普通救人
