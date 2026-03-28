# Werewolves Game V2

一个基于多智能体和大模型的狼人杀模拟项目，包含：

- 命令行对局运行入口
- 事件持久化存储
- 赛后复盘与指标导出
- FastAPI 观战 API

## 功能

- 支持 `6 / 9 / 12` 人配置
- 支持 `openai`、`anthropic`、`bailian`、`custom`、`mock` 五类模型提供方
- 所有对局事件落盘到 SQLite
- 提供对局列表、快照、时间线、增量事件、统计接口
- 支持导出可读对局记录、评估结果和指标产物

## 环境要求

- Python `3.11+`
- 已安装 [requirements.txt](C:/Users/周彬/Desktop/agent/Werewolves_gameV2/requirements.txt) 中依赖

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 本地测试模式

不依赖真实模型，适合验证流程：

```bash
python main.py --test-mode --games 1 --game-config 6_players
```

### 2. 使用百炼运行真实对局

先配置环境变量：

```powershell
$env:BAILIAN_API_KEY="your_bailian_api_key"
$env:BAILIAN_ENDPOINT="https://coding.dashscope.aliyuncs.com/v1"
$env:BAILIAN_DEFAULT_MODEL="qwen3-max-2026-01-23"
```

再启动一局真实对局：

```bash
python main.py --api-provider bailian --model qwen3-max-2026-01-23 --games 1 --game-config 6_players
```

也可以显式覆盖地址和 Key：

```bash
python main.py --api-provider bailian --api-url https://coding.dashscope.aliyuncs.com/v1 --api-key your_bailian_api_key --model qwen3-max-2026-01-23 --games 1 --game-config 6_players
```

说明：

- 默认事件库路径由 `STORE_PATH` 控制，默认是 `./store_data`
- 真实模型运行时，建议把 `API_TIMEOUT` 提高到 `90-120` 秒以减少超时
- 如果你要把真实运行和测试运行分开，建议单独指定 `STORE_PATH`

示例：

```powershell
$env:STORE_PATH="./store_data/bailian_live"
$env:LOG_PATH="./logs/bailian_live"
python main.py --api-provider bailian --model qwen3-max-2026-01-23 --games 1 --game-config 6_players
```

## 常用环境变量

### 通用

- `STORE_PATH`
- `LOG_PATH`
- `API_TIMEOUT`
- `MAX_RETRIES`

### OpenAI

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_DEFAULT_MODEL`

### Anthropic

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_DEFAULT_MODEL`

### Bailian

- `BAILIAN_API_KEY`
- `BAILIAN_ENDPOINT`
- `BAILIAN_DEFAULT_MODEL`

### Custom

- `CUSTOM_BASE_URL`
- `CUSTOM_API_KEY`
- `CUSTOM_DEFAULT_MODEL`
- `LITELLM_API_KEY`

## 观战 API

启动 API：

```bash
uvicorn src.api.main:app --reload
```

默认地址：

- Base URL: `http://127.0.0.1:8000`
- 健康检查: `GET /health`
- Swagger UI: `GET /docs`
- OpenAPI: `GET /openapi.json`

### 核心接口

```text
GET /health
GET /api/matches
GET /api/matches/{match_id}
GET /api/matches/{match_id}/timeline
GET /api/matches/{match_id}/events
GET /api/matches/{match_id}/stats
```

### 常用查询参数

`/timeline` 和 `/events` 支持：

- `event_type`
- `phase`
- `actor`
- `system_name`
- `visible_to`

`/events` 额外支持：

- `after_seq`
- `limit`

### 前端接入文档

React / 3D 观战前端请看：

- [frontend_observer_api.md](C:/Users/周彬/Desktop/agent/Werewolves_gameV2/docs/frontend_observer_api.md)

这份文档包含：

- 接口用途
- 参数和返回结构
- 常见系统事件
- TypeScript 类型建议
- React 轮询接入方式

## 事件存储

项目当前使用 SQLite 作为事件库。

默认数据库：

- 真实运行：`store_data/global_events.db`
- 如果你单独设置了 `STORE_PATH`，数据库会写到对应目录下的 `global_events.db`

事件存储支持：

- 对局列表
- 按局读取完整时间线
- 按 `after_seq` 增量读取
- 按 `event_type / phase / actor / system_name / visible_to` 过滤
- 单局聚合统计

## 导出可读对局记录

先跑出至少一局游戏，再执行：

```bash
python tools/export_readable_game_record.py --db store_data/global_events.db --output examples/sample_game_record.txt
```

如果你使用了自定义 `STORE_PATH`，请把 `--db` 指向对应目录下的数据库文件。

例如：

```bash
python tools/export_readable_game_record.py --db store_data/bailian_live/global_events.db --output examples/sample_game_record.txt
```

## 运行产物

运行后通常会生成：

- `store_data/...`：事件库、controller 数据、agent 数据
- `logs/...`：LLM trace 和日志
- `results/...`：对局结果、评估分数
- `outputs/metrics/...`：指标导出结果

## 项目结构

```text
.
├── main.py
├── config.py
├── requirements.txt
├── docs/
├── tools/
├── examples/
├── docker/
├── tests/
└── src/
```

关键目录：

- [src/api](C:/Users/周彬/Desktop/agent/Werewolves_gameV2/src/api)
- [src/events](C:/Users/周彬/Desktop/agent/Werewolves_gameV2/src/events)
- [src/controller](C:/Users/周彬/Desktop/agent/Werewolves_gameV2/src/controller)
- [docs](C:/Users/周彬/Desktop/agent/Werewolves_gameV2/docs)

## 当前已验证内容

我已经本地验证过以下内容：

- 使用百炼配置启动一局真实对局
- 生成真实事件库
- 启动 FastAPI 观战 API
- 验证 `/health`
- 验证 `/api/matches`
- 验证 `/api/matches/{match_id}`
- 验证 `/api/matches/{match_id}/timeline`
- 验证 `/api/matches/{match_id}/events`
- 验证 `/api/matches/{match_id}/stats`

## 注意事项

- 当前实时观战使用轮询 `/events`，还没有 WebSocket
- 当前 API 默认没有配置 CORS；如果前端和后端不在同一端口，通常需要补 `CORSMiddleware`
- 公开观战前端建议统一带 `visible_to=all`，避免把私有事件直接暴露给前端
