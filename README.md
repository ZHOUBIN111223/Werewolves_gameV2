# Werewolf Web Workspace

一个整理后的单仓工作区，包含狼人杀模拟后端和 3D 观战前端。

## 目录

```text
Werewolf_web/
├─ backend/          # 多智能体狼人杀后端与观战 API
├─ frontend/         # React + Three.js 3D 观战前端
├─ scripts/          # 一键启动 / 停止脚本
├─ start-stack.cmd
├─ stop-stack.cmd
├─ .gitignore
└─ README.md
```

运行生成物和本地依赖不再作为源码提交，包括：

- `.runtime`
- `frontend/node_modules`
- `frontend/dist`
- `backend/store_data`
- `backend/logs`
- `backend/results`

## 快速启动

一键启动：

```powershell
.\start-stack.cmd
```

一键停止：

```powershell
.\stop-stack.cmd
```

默认行为：

- 启动后端观战 API：`http://127.0.0.1:8000`
- 启动前端开发服务：`http://127.0.0.1:5173` 到 `5177` 中的空闲端口
- 如果本机环境中存在 `BAILIAN_API_KEY`，会默认自动拉起一局新的 Bailian 对局
- 如果没有 `BAILIAN_API_KEY`，脚本只启动前后端，不会强行开真局

手动要求启动真局：

```powershell
$env:BAILIAN_API_KEY="your_key"
.\start-stack.cmd -RunLiveGame
```

## 手动开发

前端：

```powershell
cd frontend
npm install
npm run dev
```

后端：

```powershell
cd backend
pip install -r requirements.txt
uvicorn src.api.main:app --reload
```

## 关键入口

- [App.jsx](C:/Users/周彬/Desktop/Werewolf_web/frontend/src/App.jsx)
- [WerewolfScene.jsx](C:/Users/周彬/Desktop/Werewolf_web/frontend/src/components/WerewolfScene.jsx)
- [useWerewolfObserver.js](C:/Users/周彬/Desktop/Werewolf_web/frontend/src/hooks/useWerewolfObserver.js)
- [main.py](C:/Users/周彬/Desktop/Werewolf_web/backend/src/api/main.py)
- [frontend_observer_api.md](C:/Users/周彬/Desktop/Werewolf_web/backend/docs/frontend_observer_api.md)

## Git 提交策略

这个工作区适合作为 `ZHOUBIN111223/Werewolves_gameV2` 的下一版分支提交：

- 保留旧版本历史
- 不直接覆盖原始 `main`
- 通过新分支承载 `frontend + backend` 的整合版本
