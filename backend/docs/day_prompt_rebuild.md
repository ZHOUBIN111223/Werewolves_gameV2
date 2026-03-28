# 白天发言与投票 Prompt 重构建议

## 1. 目的

这份文档只讨论白天相关请求的提示词构建，包括：

- `day_speak`
- `sheriff_campaign_speak`
- `day_vote`
- `sheriff_vote`

目标不是先改代码，而是先把 Prompt 结构整理清楚，重点解决下面几类高频问题：

- 发言回合输出了 `vote`
- 投票回合输出了 `speak`
- `speak` 动作里带了 `target`
- 发言内容为空
- 投票目标不合法

基于 `rule_adherence_game_1_114058.json` 的现象，白天阶段的问题最集中在“请求类型”和“动作格式”不匹配，而不是夜间技能逻辑本身。

另一个需要单独注意的点是：有些 `Controller纠偏结果` 里的 `final_action` 看起来已经合法，但仍被记录成不合规。这说明除了 Prompt 问题，规则监控或记账逻辑里也可能有残留问题。这个文档先只聚焦 Prompt。

## 2. 当前 Prompt 链路

当前实现链路如下：

1. `src/controller/controller.py`
   Controller 根据 `request_kind` 生成 `allowed_actions`，并通过 `action_requested` 事件发给 Agent。
2. `src/agents/base_agent.py`
   `BaseAgent.decide_action()` 调用 `build_action_prompt()`，再把 `request_context` 合并进去。
3. `src/prompts/builders.py`
   `build_action_prompt()` 先生成一个通用 Prompt。
4. `src/prompts/builders.py`
   `build_role_specific_prompt()` 叠加角色信息。
5. `src/prompts/builders.py`
   `build_phase_specific_prompt()` 再叠加白天/夜晚阶段信息。
6. `src/llm/real_llm.py`
   `_build_messages()` 把整个 Prompt JSON 作为 user message 发给模型，同时给一个通用 system prompt。

当前模型实际看到的内容，本质上是：

- 一个通用 system prompt
- 一个 JSON user payload

也就是说，白天发言和白天投票的约束，并不是通过独立模板明确表达的，而是散落在多个字段里共同暗示给模型。

## 3. 当前结构为什么容易出错

### 3.1 白天阶段提示过于宽泛

在 `build_action_prompt()` 里，白天被统一描述为：

- 白天必须在 `speak` 或 `vote` 中做选择

这句话对“白天阶段”成立，但对“当前请求”不一定成立。

例如：

- `day_speak` 这一轮其实只能 `speak`
- `day_vote` 这一轮其实只能 `vote`
- `sheriff_campaign_speak` 这一轮其实也只能 `speak`
- `sheriff_vote` 这一轮其实也只能 `vote`

如果 system prompt 和 base prompt 持续告诉模型“白天可以 speak 或 vote”，而 request-level 约束只是作为附加字段出现，模型就很容易按阶段语义做决定，而不是按当前请求做决定。

### 3.2 约束分散，没有单一的硬约束块

现在与请求相关的限制分散在这些字段里：

- `request_kind`
- `available_actions`
- `mandatory_action`
- `phase_instructions`
- `daytime_requirement`
- `specific_guidance`

这会带来两个问题：

- 模型不知道哪个字段优先级最高
- 同一件事被重复但表达不完全一致，容易相互稀释

### 3.3 输出 schema 过于泛化

当前 `output_schema` 永远允许看到完整动作集合：

- `speak`
- `vote`
- `inspect`
- `kill`
- `protect`
- `poison`
- `heal`
- `skip`
- `hunt`

这对统一接口有好处，但对白天请求的动作约束不够强。模型会认为“这些动作都在总表里，只要我选一个看起来合理的即可”，而不是“本轮只允许一种动作类型”。

### 3.4 缺少 request-specific 正反例

当前 system prompt 会说“尊重 request_kind 和 available_actions”，但没有明确给模型下面这种强绑定规则：

- 如果 `request_kind=day_speak`，那么 `action_type` 必须是 `speak`
- 如果 `request_kind=day_speak`，那么 `target` 必须是 `""`
- 如果 `request_kind=day_vote`，那么 `action_type` 必须是 `vote`
- 如果 `request_kind=day_vote`，那么 `public_speech` 必须是 `""`

模型没有被要求在输出前做一次“请求类型 -> 输出结构”的映射检查。

### 3.5 发言规则和投票规则混在一起

对白天来说，“说什么”和“做什么”是两套不同约束：

- 发言请求关注 `public_speech`
- 投票请求关注 `target`

当前 Prompt 更像是把两套规则都放进同一个大篮子里，让模型自己判断当前该用哪套。这对大模型并不稳。

### 3.6 中英混合不是主因，但会放大问题

目前 system prompt 主要是英文，user payload 主要是中文。这个本身不一定错，但当规则本来就分散时，中英切换会进一步降低“硬约束”的清晰度。这里更稳妥的做法是让 system prompt 直接使用和 payload 一致的表达方式，或者至少把 request-level 约束写得非常机械、明确。

## 4. 重构原则

建议把“白天阶段 Prompt”改成“请求级 Prompt”。

核心原则如下：

- 阶段信息只能做背景，不能替代当前请求约束。
- 每次请求只描述本轮唯一合法的动作结构。
- `request_kind` 必须直接映射成 `must_action_type`。
- `hard_constraints` 必须单独成块，并且优先级最高。
- 发言请求和投票请求分别给不同模板，不共享同一套动作描述。
- 对 speak 类请求，要明确要求 `target=""`。
- 对 vote 类请求，要明确要求 `public_speech=""`。
- 给模型提供一条正确示例和一条错误示例，降低“看起来合理但结构错误”的概率。
- 要求模型在内部先检查“动作类型、目标字段、公开发言字段”三项，再输出 JSON。

## 5. 推荐的新 Prompt Payload 结构

建议在现有 JSON Prompt 上增加一个 request-specific block，而不是只靠 `available_actions` 暗示。

推荐结构如下：

```json
{
  "prompt_type": "action",
  "game_id": "game_xxx",
  "role": "villager",
  "phase": "day_1",
  "request_kind": "day_speak",
  "current_subphase": "discussion",
  "alive_players": ["player_0", "player_1", "player_2", "player_3"],
  "available_targets": ["player_0", "player_1", "player_2", "player_3"],
  "visible_events": [],
  "short_memories": [],
  "speech_content": [],
  "role_instruction": "...",
  "specific_guidance": [],
  "decision_task": "你当前处于白天发言请求，本轮只能发言，不能投票。",
  "hard_constraints": {
    "must_action_type": "speak",
    "allowed_action_types": ["speak"],
    "forbidden_action_types": ["vote", "inspect", "kill", "protect", "poison", "heal", "skip", "hunt"],
    "target_rule": "target 必须为 \"\"，不能填写 any player id，也不能填写 all。",
    "speech_rule": "public_speech 必须是 2 到 4 句自然中文，不能为空。",
    "scope_rule": "只能围绕存活玩家讨论和怀疑。",
    "reason_rule": "如果点名怀疑某位玩家，至少给两条可验证理由。"
  },
  "output_schema": {
    "action_type": "固定为 speak",
    "target": "固定为空字符串",
    "reasoning_summary": "简短内部推理摘要",
    "public_speech": "必填"
  },
  "output_example": {
    "action_type": "speak",
    "target": "",
    "reasoning_summary": "我更关注 player_2 和 player_3 的站边差异",
    "public_speech": "我现在更关注 player_2 和 player_3。第一，player_2 前后站边变化太快。第二，player_3 在关键发言点回避了对票型的解释。"
  },
  "negative_example": {
    "why_wrong": "这是发言回合，不允许投票，也不允许 speak 时携带 target。",
    "bad_output": {
      "action_type": "vote",
      "target": "player_2",
      "reasoning_summary": "我想先投他",
      "public_speech": ""
    }
  }
}
```

重点不是字段名必须完全一样，而是要把“唯一合法动作结构”变成显式信息，而不是暗示信息。

## 6. 四类白天请求的推荐模板

### 6.1 `day_speak`

建议模板：

- `decision_task`: 你当前处于白天发言请求，本轮只能发言。
- `must_action_type`: `speak`
- `target_rule`: `target=""`
- `speech_rule`: `public_speech` 必须非空，建议 2 到 4 句中文
- `scope_rule`: 只能讨论当前存活玩家
- `reason_rule`: 如果点名怀疑，至少给两条理由

不应该再向模型强调“白天可以 speak 或 vote”，因为这轮不是一个开放选择题。

### 6.2 `sheriff_campaign_speak`

建议模板：

- `decision_task`: 你当前处于警长竞选发言，本轮只能发言，不能投票。
- `must_action_type`: `speak`
- `target_rule`: `target=""`
- `speech_rule`: 发言必须包含竞选立场、观察重点或带队思路
- `scope_rule`: 只能围绕当前存活玩家和当前局势展开

这类请求和普通白天发言的结构一致，但内容语义不同。不要复用完全相同的任务描述。

### 6.3 `day_vote`

建议模板：

- `decision_task`: 你当前处于白天投票请求，本轮必须投票。
- `must_action_type`: `vote`
- `allowed_action_types`: `["vote"]`
- `target_rule`: `target` 必须从当前存活且不等于自己的玩家中选择
- `speech_rule`: `public_speech=""`
- `consistency_rule`: 票型应尽量与已有公开立场一致，但最终输出只能是投票 JSON

对投票请求，Prompt 里不要再鼓励模型输出公开发言，更不要给出“若你想表达怀疑可以先 speak”的空间。

### 6.4 `sheriff_vote`

建议模板：

- `decision_task`: 你当前处于警长投票请求，本轮必须投票给候选人。
- `must_action_type`: `vote`
- `target_rule`: `target` 必须从 `sheriff_candidates` 中选择，且不能投自己
- `speech_rule`: `public_speech=""`

这里必须额外给模型一个明确字段，例如：

```json
{
  "vote_candidates": ["player_1", "player_4"]
}
```

不要只给 `alive_players`，否则模型可能投给活人但不是候选人的对象。

## 7. 推荐的 system prompt 写法

当前 system prompt 太泛，建议改成“请求级硬约束优先”的版本。

推荐方向如下：

```text
You are an AI player in a Werewolf game.
Return exactly one JSON object and nothing else.

You are handling exactly one request.
The field hard_constraints has the highest priority and must be obeyed exactly.

Follow these rules before output:
1. Check must_action_type first.
2. Check whether target must be empty or must be chosen from the allowed list.
3. Check whether public_speech must be empty or non-empty.
4. If any field conflicts with hard_constraints, fix it before output.

If must_action_type is speak:
- action_type must be "speak"
- target must be ""
- public_speech must be a non-empty Chinese speech

If must_action_type is vote:
- action_type must be "vote"
- target must be a legal player id from the allowed target list
- public_speech must be ""

Do not output explanations, markdown, or extra text.
```

这个 system prompt 的重点不是优雅，而是机械、不可误读。

## 8. 推荐把约束从“软提醒”改成“硬结构”

建议新增这些字段：

- `decision_task`
- `hard_constraints`
- `output_example`
- `negative_example`
- `vote_candidates`

建议弱化这些字段对白天请求的主导作用：

- 泛化的 `phase_instructions`
- 泛化的 `mandatory_action`
- “白天必须在 speak 或 vote 中做选择”这类阶段级描述

阶段级描述可以保留，但只能做背景，不应该再成为白天请求的主导约束。

## 9. 推荐的代码改造落点

### 9.1 `src/prompts/builders.py`

建议新增一个专门的函数，例如：

```python
def build_request_specific_prompt(
    request_kind: str,
    actor_id: str,
    alive_players: list[str],
    available_targets: list[str],
    sheriff_candidates: list[str] | None = None,
) -> dict[str, object]:
    ...
```

这个函数只做一件事：把 `request_kind` 映射成唯一合法的输出结构。

建议让它输出：

- `decision_task`
- `hard_constraints`
- `output_example`
- `negative_example`
- `vote_candidates`

### 9.2 `src/agents/base_agent.py`

建议在 `prompt.update(request_context)` 之后，追加 request-specific builder：

```python
prompt.update(build_request_specific_prompt(...))
```

顺序上，应当让 request-specific 约束覆盖 phase-level 的泛化描述。

### 9.3 `src/llm/real_llm.py`

建议让 `_build_messages()` 的 system prompt 明确声明：

- `hard_constraints` 最高优先级
- speak 和 vote 的字段要求不同
- 输出前必须先检查 `action_type / target / public_speech`

如果还要进一步压错误率，可以按 `request_kind` 注入 one-shot example，而不是只有一版通用 system prompt。

## 10. 最小可落地版本

如果不想一次改太多，最小版本建议先做这四件事：

1. 去掉白天通用 Prompt 里“白天必须在 speak 或 vote 中做选择”这类开放式描述。
2. 新增 `hard_constraints.must_action_type`。
3. 对 `day_speak` 和 `sheriff_campaign_speak` 明确要求 `target=""` 且 `public_speech` 非空。
4. 对 `day_vote` 和 `sheriff_vote` 明确要求 `public_speech=""` 且 `target` 来自合法列表。

只做这四件事，通常就能显著减少“发言回合输出 vote”以及“发言动作携带 target”这两类错误。

## 11. 一句话结论

当前问题的根因不是模型“不懂狼人杀”，而是 Prompt 还停留在“白天阶段提示”层，而没有真正收敛到“当前请求的唯一合法动作结构”。要改善白天发言和投票混淆，最有效的办法不是继续加泛化规则，而是把 `request_kind -> 输出结构` 做成硬约束模板。
