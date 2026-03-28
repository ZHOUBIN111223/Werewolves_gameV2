"""FastAPI 应用入口。

该模块提供只读观战 API（Observer API），用于从落盘事件中读取对局状态、
时间线与增量事件，便于前端或外部工具展示/分析。
"""

from __future__ import annotations

from fastapi import FastAPI

from src.api.routers.frontend_logs import router as frontend_logs_router
from src.api.routers.matches import router as matches_router

# 创建 FastAPI 应用实例（路由在下方通过 include_router 注入）。
app = FastAPI(
    title="Werewolves Observer API",
    version="0.1.0",
    description="Read-only observer API for the werewolves multi-agent controller.",
)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    """用于容器/负载均衡探活的简单健康检查接口。"""
    return {"status": "ok"}


# 注入业务路由：对局列表、快照、事件流等。
app.include_router(matches_router)
app.include_router(frontend_logs_router)
