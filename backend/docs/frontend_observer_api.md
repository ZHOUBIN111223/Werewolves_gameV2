# Observer API 文档

面向对象：React 前端 / 3D 观战前端

用途：读取狼人杀对局的列表、快照、时间线、增量事件和统计信息。

当前 API 为只读接口，数据来源于后端持久化的事件库。

## 1. 启动方式

启动 FastAPI 服务：

```bash
uvicorn src.api.main:app --reload
```

默认地址：

- Base URL: `http://127.0.0.1:8000`
- 健康检查: `GET /health`
- Swagger UI: `GET /docs`
- OpenAPI JSON: `GET /openapi.json`

## 2. 前端推荐接入流程

如果你要做 React 3D 观战前端，建议按下面流程读数据：

1. 用 `GET /api/matches` 拉取对局列表。
2. 用户选中某局后，用 `GET /api/matches/{match_id}` 拉取初始快照。
3. 初始化完成后，用 `GET /api/matches/{match_id}/events?after_seq=...` 轮询增量事件。
4. 如果要做回放模式，用 `GET /api/matches/{match_id}/timeline` 拉完整时间线。
5. 如果要做面板统计、热力图、调试面板，用 `GET /api/matches/{match_id}/stats`。

对应到 3D 场景：

- `match.phase` / `match.current_subphase`：控制场景阶段、灯光、UI 状态
- `players`：控制玩家站位、存活状态、发言高亮、投票箭头
- `recent_events` / `/events`：驱动动画和过场
- `/timeline`：驱动回放时间轴
- `/stats`：驱动数据面板，不建议作为主场景实时渲染的唯一来源

## 3. 通用约定

### 3.1 时间序号

事件里有两个近似相同的字段：

- `seq`
- `ts`

两者当前都来自后端事件存储里的单调递增时间戳，可当作事件序号使用。

轮询增量事件时，前端应该使用 `next_seq` 作为下一次请求的 `after_seq`。

### 3.2 可见性

每个事件都有：

```json
"visibility": ["all"]
```

或：

```json
"visibility": ["player_0"]
```

说明：

- `["all"]`：公开事件，适合观战前端直接展示
- `["controller"]`：仅控制器可见，通常不应该直接给公开观战前端
- `["player_x"]`：某个玩家私有信息

如果前端是公开观战模式，建议查询时加上：

```text
visible_to=all
```

这样可以避免把私有夜间信息直接暴露到前端。

### 3.3 错误响应

当对局不存在时，接口返回：

```json
{
  "detail": "match not found: game_xxx"
}
```

HTTP 状态码为 `404`。

## 4. 接口列表

## 4.1 健康检查

### `GET /health`

返回：

```json
{
  "status": "ok"
}
```

用途：

- 前端检查后端是否在线
- 容器或代理做存活探针

## 4.2 对局列表

### `GET /api/matches`

返回类型：`MatchListResponse`

示例：

```json
{
  "items": [
    {
      "match_id": "game_1_141118",
      "phase": "post_game",
      "status": "finished",
      "winner": "werewolves",
      "total_events": 169,
      "last_seq": 1774592256833187700
    }
  ]
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `match_id` | `string` | 对局 ID |
| `phase` | `string` | 当前阶段，如 `day_1`、`night_1`、`post_game` |
| `status` | `string` | `running` 或 `finished` |
| `winner` | `string \| null` | 胜者阵营，未结束时可能为空 |
| `total_events` | `number` | 当前已落盘事件数量 |
| `last_seq` | `number` | 该局最后一条事件的序号 |

前端用途：

- 左侧对局列表
- 大厅页
- 历史回放入口

## 4.3 对局快照

### `GET /api/matches/{match_id}`

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `recent_limit` | `number` | `20` | 返回最近多少条事件，范围 `1-100` |

返回类型：`MatchSnapshotResponse`

示例：

```json
{
  "match": {
    "match_id": "game_1_141118",
    "status": "finished",
    "phase": "post_game",
    "current_subphase": "seer",
    "alive_players_count": 2,
    "total_players": 6,
    "current_speaker": "player_0",
    "focus_target": "player_3",
    "winner": "werewolves",
    "game_ended": true
  },
  "players": [
    {
      "id": "player_0",
      "seat_no": 1,
      "name": "player_0",
      "alive": true,
      "role": null,
      "camp": null,
      "suspicion": 0,
      "vote_target": null,
      "is_speaking": false,
      "accent": null
    }
  ],
  "recent_events": []
}
```

`match` 字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `match_id` | `string` | 对局 ID |
| `status` | `string` | `running` / `finished` |
| `phase` | `string` | 当前阶段 |
| `current_subphase` | `string \| null` | 当前子阶段，例如 `discussion`、`voting`、`seer` |
| `alive_players_count` | `number` | 当前存活人数 |
| `total_players` | `number` | 总人数 |
| `current_speaker` | `string \| null` | 当前发言者 |
| `focus_target` | `string \| null` | 最近焦点目标，通常是投票目标或被淘汰者 |
| `winner` | `string \| null` | 胜者阵营 |
| `game_ended` | `boolean` | 是否已结束 |

`players` 字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `string` | 玩家 ID |
| `seat_no` | `number` | 座位号，从 `1` 开始 |
| `name` | `string` | 展示名，当前等于 `id` |
| `alive` | `boolean` | 是否存活 |
| `vote_target` | `string \| null` | 当前白天轮次下的投票目标 |
| `is_speaking` | `boolean` | 是否正在发言 |

前端用途：

- 进入对局时的一次性初始化
- 3D 座位布局
- 玩家模型存活状态初始化
- 当前话语权高亮

## 4.4 完整时间线

### `GET /api/matches/{match_id}/timeline`

查询参数，全部可选：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `event_type` | `string` | 事件类型过滤：`system` / `action` / `observation` |
| `phase` | `string` | 阶段过滤，例如 `day_1` |
| `actor` | `string` | 行动玩家过滤，例如 `player_0` |
| `system_name` | `string` | 系统事件名过滤，例如 `vote_recorded` |
| `visible_to` | `string` | 可见性过滤，例如 `all`、`controller`、`player_0` |

返回类型：`EventDTO[]`

示例：

```json
[
  {
    "event_id": "8b0b31f3-8d14-4d44-a3d8-13bcd5f0fd66",
    "match_id": "game_1_141118",
    "seq": 1774591878232931900,
    "type": "system",
    "phase": "setup",
    "visibility": ["all"],
    "ts": 1774591878232931900,
    "payload": {
      "message": "game_started",
      "players": ["player_0", "player_1", "player_2", "player_3", "player_4", "player_5"]
    },
    "actor": null,
    "action_type": null,
    "system_name": "game_started"
  }
]
```

前端用途：

- 完整回放
- 调试工具
- 开发期事件检查器

注意：

- 这是全量时间线，不适合高频轮询
- 实时更新请优先用 `/events`

## 4.5 增量事件

### `GET /api/matches/{match_id}/events`

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `after_seq` | `number` | `0` | 只返回序号大于该值的事件 |
| `limit` | `number` | `100` | 最多返回多少条，范围 `1-500` |
| `event_type` | `string` | `null` | 事件类型过滤 |
| `phase` | `string` | `null` | 阶段过滤 |
| `actor` | `string` | `null` | 行动玩家过滤 |
| `system_name` | `string` | `null` | 系统事件名过滤 |
| `visible_to` | `string` | `null` | 可见性过滤 |

返回类型：`EventListResponse`

示例：

```json
{
  "match_id": "game_1_141118",
  "next_seq": 1774591896174800800,
  "has_more": true,
  "events": [
    {
      "event_id": "2c4bc8f4-b31b-42b1-bc5e-47fcfaafbc77",
      "match_id": "game_1_141118",
      "seq": 1774591896089726500,
      "type": "action",
      "phase": "night_1",
      "visibility": ["all"],
      "ts": 1774591896089726500,
      "payload": {
        "request_kind": "night_action",
        "target": "player_1"
      },
      "actor": "player_3",
      "action_type": "inspect",
      "system_name": null
    }
  ]
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `match_id` | `string` | 对局 ID |
| `next_seq` | `number` | 下一次轮询时建议带回去的 `after_seq` |
| `has_more` | `boolean` | 当前结果是否被 `limit` 截断 |
| `events` | `EventDTO[]` | 本次返回的事件列表 |

前端推荐轮询方式：

```ts
let afterSeq = snapshot.recent_events.at(-1)?.seq ?? 0;

async function poll() {
  const res = await fetch(`/api/matches/${matchId}/events?after_seq=${afterSeq}&visible_to=all`);
  const data = await res.json();

  for (const event of data.events) {
    applyEventToScene(event);
  }

  afterSeq = data.next_seq;
}
```

建议：

- 公开观战：`visible_to=all`
- 调试控制台：可不带 `visible_to`
- 轮询周期：`500ms - 1500ms`

## 4.6 对局统计

### `GET /api/matches/{match_id}/stats`

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `visible_to` | `string` | `null` | 只统计对某个身份可见的事件 |

返回类型：`MatchStatsResponse`

示例：

```json
{
  "match_id": "game_1_141118",
  "total_events": 169,
  "first_seq": 1774591878232931900,
  "last_seq": 1774592256833187700,
  "counts_by_type": {
    "system": 133,
    "action": 36
  },
  "counts_by_phase": {
    "day_1": 43,
    "night_1": 17
  },
  "counts_by_system_name": {
    "action_requested": 36,
    "speech_delivered": 14,
    "vote_recorded": 10
  },
  "counts_by_actor": {
    "player_0": 8,
    "player_1": 7
  }
}
```

前端用途：

- 统计面板
- 侧边栏图表
- 赛后分析页

## 5. EventDTO 字段定义

所有时间线和增量接口里的事件都长这样：

```ts
export interface EventDTO {
  event_id: string;
  match_id: string;
  seq: number;
  type: string;
  phase: string;
  visibility: string[];
  ts: number;
  payload: Record<string, unknown>;
  actor: string | null;
  action_type: string | null;
  system_name: string | null;
}
```

字段解释：

| 字段 | 说明 |
| --- | --- |
| `event_id` | 事件唯一 ID |
| `match_id` | 对局 ID |
| `seq` | 事件序号，适合前端排序和增量拉取 |
| `type` | `system` / `action` / `observation` |
| `phase` | 阶段 |
| `visibility` | 可见性范围 |
| `ts` | 当前与 `seq` 一致，可视为时间戳/序号 |
| `payload` | 事件具体内容 |
| `actor` | 动作发起者，只有 `action` 或部分事件有值 |
| `action_type` | 行动类型，如 `vote` / `kill` / `inspect` |
| `system_name` | 系统事件名 |

## 6. 常见系统事件

下面这些系统事件最适合 3D 观战前端重点接入。

### 6.1 `game_started`

用途：初始化玩家列表

示例 payload：

```json
{
  "message": "game_started",
  "players": ["player_0", "player_1", "player_2", "player_3", "player_4", "player_5"]
}
```

### 6.2 `phase_advanced`

用途：阶段切换，适合驱动场景切换、灯光变化、字幕

示例 payload：

```json
{
  "message": "Phase advanced to night_1",
  "new_phase": "night_1",
  "previous_phase": "setup",
  "subphase": "guard"
}
```

### 6.3 `speaking_order_announced`

用途：展示发言顺序、安排镜头移动

示例 payload：

```json
{
  "badge_holder": "player_2",
  "speaking_order": ["player_2", "player_3", "player_4", "player_5", "player_0", "player_1"]
}
```

### 6.4 `speech_delivered`

用途：角色发言气泡、字幕、口型动画

常见 payload 字段：

- `speaker`
- `content`

### 6.5 `vote_recorded`

用途：展示投票箭头、票型动画

示例 payload：

```json
{
  "voter": "player_0",
  "target": "player_3"
}
```

### 6.6 `player_eliminated`

用途：玩家淘汰动画、角色离场

示例 payload：

```json
{
  "eliminated_player": "player_3",
  "reason": "eliminated by vote"
}
```

### 6.7 `night_deaths_announced`

用途：白天公布昨夜死讯

常见 payload 字段：

- `deaths`

### 6.8 `game_ended`

用途：结算画面、胜利阵营展示

示例 payload：

```json
{
  "winner": "werewolves",
  "final_alive_players": ["player_0", "player_4"]
}
```

## 7. 常见私有事件

这些事件通常不应该直接用于公开观战前端，除非你做的是“裁判视角”或调试后台：

- `action_requested`
- `witch_night_info`
- `inspection_result`
- `night_resolution_completed`
- `heal_success`
- `attack_protected`
- `reflection_recorded`
- `reflection_generated`
- `rule_adherence_observed`

如果你不想暴露私有信息，请统一在请求里带：

```text
visible_to=all
```

## 8. TypeScript 建议类型

```ts
export interface MatchListItem {
  match_id: string;
  phase: string;
  status: "running" | "finished" | string;
  winner: string | null;
  total_events: number;
  last_seq: number;
}

export interface MatchDTO {
  match_id: string;
  status: "running" | "finished" | string;
  phase: string;
  current_subphase: string | null;
  alive_players_count: number;
  total_players: number;
  current_speaker: string | null;
  focus_target: string | null;
  winner: string | null;
  game_ended: boolean;
}

export interface PlayerDTO {
  id: string;
  seat_no: number;
  name: string;
  alive: boolean;
  role: string | null;
  camp: string | null;
  suspicion: number;
  vote_target: string | null;
  is_speaking: boolean;
  accent: string | null;
}

export interface MatchSnapshotResponse {
  match: MatchDTO;
  players: PlayerDTO[];
  recent_events: EventDTO[];
}

export interface EventListResponse {
  match_id: string;
  next_seq: number;
  has_more: boolean;
  events: EventDTO[];
}

export interface MatchStatsResponse {
  match_id: string;
  total_events: number;
  first_seq: number;
  last_seq: number;
  counts_by_type: Record<string, number>;
  counts_by_phase: Record<string, number>;
  counts_by_system_name: Record<string, number>;
  counts_by_actor: Record<string, number>;
}
```

## 9. React 接入建议

### 9.1 页面初始化

推荐：

1. 进入页面先读 `/api/matches`
2. 选中某局后读 `/api/matches/{match_id}?recent_limit=20`
3. 根据 `players` 初始化 3D 座位
4. 根据 `recent_events` 补最近状态
5. 开始轮询 `/events`

### 9.2 实时更新

建议维护一个本地事件应用器：

```ts
function applyEventToScene(event: EventDTO) {
  switch (event.system_name) {
    case "phase_advanced":
      break;
    case "speech_delivered":
      break;
    case "vote_recorded":
      break;
    case "player_eliminated":
      break;
    case "game_ended":
      break;
  }
}
```

### 9.3 回放模式

回放推荐用 `/timeline` 全量拉取后自行播放，不建议回放模式下继续轮询 `/events`。

### 9.4 可见性策略

如果你的前端是公开观战模式，建议默认：

- `/timeline?visible_to=all`
- `/events?visible_to=all`
- `/stats?visible_to=all`

## 10. 当前限制

目前后端还有几个前端需要注意的点：

- 没有 WebSocket，实时更新需要轮询 `/events`
- 没有鉴权
- 没有分页版 `/timeline`
- `src/api/main.py` 里当前没有配置 CORS，中途如果 React 前端跑在不同端口，浏览器可能会拦截跨域请求

如果后面你要直接接 React 开发服务器，下一步通常会补：

1. `CORSMiddleware`
2. 更明确的公开观战视角接口
3. WebSocket 或 SSE 推流
4. 更稳定的事件分类文档
