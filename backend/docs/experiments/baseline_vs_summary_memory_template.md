# Baseline vs Summary-Memory 对比实验模板

## 1. 实验目标

- 实验名称：
- 日期：
- 分支 / 提交：
- 执行人：
- 对比对象：
  - `baseline`：旧版记忆系统
  - `summary-memory`：摘要型双层记忆系统

本实验用于回答两个问题：

1. 摘要记忆是否提升了对局表现与稳定性。
2. 摘要记忆是否降低了提示词噪声、反思延迟和长期记忆污染。

---

## 2. 实验假设

- `H1`：`summary-memory` 的胜率、规则遵守率、决策质量不低于 `baseline`。
- `H2`：`summary-memory` 的平均 prompt 上下文长度、反思失败率、长期记忆冗余度低于 `baseline`。
- `H3`：`summary-memory` 更适合跨局积累可迁移策略，而不是堆积局内事实噪声。

---

## 3. 实验配置

### 3.1 公共配置

| 项目 | 值 |
| --- | --- |
| 模型 |  |
| API 提供方 |  |
| 游戏配置 | `6_players` / `9_players` / `12_players` |
| 总局数 |  |
| 随机种子策略 | 例如：固定种子集合 |
| 运行时间范围 |  |
| 代码版本 |  |

### 3.2 变量控制

| 维度 | baseline | summary-memory |
| --- | --- | --- |
| 记忆系统 | 旧版 | 摘要型 |
| 模型 |  |  |
| 温度 / timeout |  |  |
| 游戏配置 |  |  |
| 玩家角色分布 |  |  |
| 评估脚本 |  |  |

要求：

- 除记忆系统外，其余变量尽量保持一致。
- 使用相同的种子集合或同分布随机种子。
- 结果目录分开保存，避免文件互相覆盖。

---

## 4. 输出目录

建议按如下结构保存：

```text
results/
  experiments/
    baseline/
      game_results_*.json
      eval_scores_*.json
      memory_reports/
    summary_memory/
      game_results_*.json
      eval_scores_*.json
      memory_reports/
outputs/
  metrics/
    baseline/
    summary_memory/
```

---

## 5. 核心指标

### 5.1 对局表现

| 指标 | baseline | summary-memory | 备注 |
| --- | --- | --- | --- |
| 总局数 |  |  |  |
| 成功完成局数 |  |  | 是否中途异常 |
| 胜率 |  |  | 可按阵营拆分 |
| 狼人胜率 |  |  |  |
| 好人胜率 |  |  |  |

### 5.2 行为质量

| 指标 | baseline | summary-memory | 备注 |
| --- | --- | --- | --- |
| Rule adherence 总体 |  |  |  |
| Agent 原始输出合规率 |  |  |  |
| Controller 纠偏后合规率 |  |  |  |
| Judge 最终裁定合规率 |  |  |  |
| 决策评估分 |  |  | 读取 `eval_scores` |

### 5.3 记忆质量

| 指标 | baseline | summary-memory | 备注 |
| --- | --- | --- | --- |
| 每局新增长期记忆条数 |  |  |  |
| 可迁移规则条数 |  |  | `strategy_rule` |
| 反模式条数 |  |  | `anti_pattern` |
| 局内事实冗余程度 |  |  | 主观或脚本统计 |
| 跨局污染风险 |  |  | 主观评审 |

### 5.4 成本与稳定性

| 指标 | baseline | summary-memory | 备注 |
| --- | --- | --- | --- |
| 平均 action prompt 长度 |  |  | 可按 token / 字符 |
| 平均 reflection prompt 长度 |  |  |  |
| reflection 超时次数 |  |  |  |
| reflection fallback 次数 |  |  |  |
| 运行总耗时 |  |  |  |
| 单局平均耗时 |  |  |  |

---

## 6. 单局样例对比

建议抽取 2 到 3 局代表性对局做质性分析。

### 样例 A

- `baseline` 对局 ID：
- `summary-memory` 对局 ID：
- 现象：
- 关键差异：
- 结论：

### 样例 B

- `baseline` 对局 ID：
- `summary-memory` 对局 ID：
- 现象：
- 关键差异：
- 结论：

---

## 7. 记忆与反思专项分析

### 7.1 局内记忆

- `baseline` 是否存在 observation/factual 过量堆积：
- `summary-memory` 的阶段摘要是否覆盖了投票、身份声明、怀疑链：
- 是否出现跨局串味：

### 7.2 局后反思

| 项目 | baseline | summary-memory |
| --- | --- | --- |
| 反思成功率 |  |  |
| 反思 fallback 率 |  |  |
| 反思是否可提炼规则 |  |  |
| 反思内容是否重复 |  |  |

### 7.3 长期记忆演化

- 哪些规则被重复写入：
- 哪些规则真正可迁移：
- 哪些内容属于局内噪声，不应跨局保留：

---

## 8. 风险与偏差

- 样本量是否足够：
- 模型波动是否影响结论：
- 随机角色分布是否造成偏差：
- 是否存在 API 超时或 fallback 干扰：
- 是否存在日志缺失、结果未落盘等工程问题：

---

## 9. 实验结论

### 9.1 定量结论

- 

### 9.2 定性结论

- 

### 9.3 最终判断

- 是否保留 `summary-memory` 作为默认方案：
- 是否继续保留 `baseline` 作为对照：
- 下一步要优化的点：

---

## 10. 后续动作

1. 增加自动统计脚本，直接汇总 `results` 与 `memory reports`。
2. 给摘要记忆增加覆盖率指标，例如投票、声明、死亡信息是否被摘要命中。
3. 对长期记忆做周期性去重与 consolidation。
