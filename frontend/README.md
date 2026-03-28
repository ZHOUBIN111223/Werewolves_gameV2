# Werewolf Observer 3D

一个用于观战多智能体狼人杀对局的前端应用，技术栈为 React、Vite 和 Three.js。

## 主要能力

- 3D 营火议事场
- 实时对局切换
- 公开事件流
- 回放时间线
- 战况统计
- Demo 回退
- 前端运行时错误上报

## 目录

```text
frontend/
├─ public/assets/kenney/
├─ src/App.jsx
├─ src/components/WerewolfScene.jsx
├─ src/hooks/useWerewolfObserver.js
├─ src/lib/gameState.js
├─ src/lib/observerApi.js
└─ vite.config.js
```

## 启动

```powershell
npm install
npm run dev
```

默认开发端口通常为 `5173`。

## 后端联调

前端默认通过 Vite 代理访问同级 `../backend`：

- `/api` -> `http://127.0.0.1:8000`
- `/health` -> `http://127.0.0.1:8000`

后端启动方式：

```powershell
cd ../backend
uvicorn src.api.main:app --reload
```

## 当前使用素材

- `survival-kit`
- `board-game-icons`
- `ui-pack`
- `ui-audio`
- `rpg-audio`

## 验证

```powershell
npm run lint
npm run build
```
