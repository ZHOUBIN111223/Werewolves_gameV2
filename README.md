# Werewolves Game V2

一个基于多智能体和大模型的狼人杀模拟项目，包含命令行对局入口和只读观战 API。

## 功能

- 支持 6 / 9 / 12 人配置
- 支持 `openai`、`anthropic`、`bailian`、`custom`、`mock` 五种模型提供方
- 支持事件流、记忆存储、赛后复盘
- 提供 FastAPI 观战接口

## 环境要求

- Python 3.11+
- 已安装 `requirements.txt` 中依赖

## 安装

```bash
pip install -r requirements.txt
```

## 运行

本地测试模式：

```bash
python main.py --test-mode --games 1 --game-config 6_players
```

使用真实模型：

```bash
python main.py --api-provider openai --model gpt-4o-mini --games 1 --game-config 6_players
```

常用环境变量：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_DEFAULT_MODEL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_DEFAULT_MODEL`
- `BAILIAN_API_KEY`
- `BAILIAN_ENDPOINT`
- `BAILIAN_DEFAULT_MODEL`
- `CUSTOM_BASE_URL`
- `LITELLM_API_KEY`
- `STORE_PATH`
- `LOG_PATH`

## 观战 API

```bash
uvicorn src.api.main:app --reload
```

默认健康检查：

```text
GET /health
```

## 导出可读对局记录

先运行一局游戏，再执行：

```bash
python tools/export_readable_game_record.py --db store_data/global_events_test.db --output examples/sample_game_record.txt
```

默认会导出数据库里的最新一局，并生成 UTF-8 编码的纯文本记录，适合直接提交到仓库中查看。

## 项目结构

```text
.
├── main.py
├── config.py
├── requirements.txt
├── tools/
├── examples/
├── docker/
└── src/
```

运行生成的日志、结果和本地存储目录已加入 `.gitignore`，不会再被提交。
