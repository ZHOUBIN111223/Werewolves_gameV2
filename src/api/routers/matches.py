"""对局（Match）相关的 HTTP 路由。

这些端点均为只读：从持久化事件存储中读取对局列表、对局快照以及事件时间线。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.schemas.event import EventDTO, EventListResponse
from src.api.schemas.match import MatchListResponse, MatchSnapshotResponse
from src.api.services.observer_service import MatchNotFoundError, ObserverService

# 路由前缀统一以 /api/matches 开头，便于前端按资源访问。
router = APIRouter(prefix="/api/matches", tags=["matches"])

# 以模块级单例的方式复用 ObserverService，避免每个请求重复初始化存储连接配置。
_observer_service = ObserverService()


def get_observer_service() -> ObserverService:
    """FastAPI 依赖注入：提供 ObserverService 单例。"""
    return _observer_service


@router.get("", response_model=MatchListResponse)
async def list_matches(service: ObserverService = Depends(get_observer_service)) -> MatchListResponse:
    """列出当前存储中可用的所有对局。"""
    return await service.list_matches()


@router.get("/{match_id}", response_model=MatchSnapshotResponse)
async def get_match_snapshot(
    match_id: str,
    recent_limit: int = Query(default=20, ge=1, le=100),
    service: ObserverService = Depends(get_observer_service),
) -> MatchSnapshotResponse:
    """获取对局快照（对局元信息 + 玩家列表 + 最近 N 条事件）。"""
    try:
        return await service.get_match_snapshot(match_id, recent_limit=recent_limit)
    except MatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"match not found: {exc}") from exc


@router.get("/{match_id}/timeline", response_model=list[EventDTO])
async def get_match_timeline(
    match_id: str,
    service: ObserverService = Depends(get_observer_service),
) -> list[EventDTO]:
    """获取对局完整事件时间线（按发生顺序）。"""
    try:
        return await service.get_timeline(match_id)
    except MatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"match not found: {exc}") from exc


@router.get("/{match_id}/events", response_model=EventListResponse)
async def get_match_events(
    match_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: ObserverService = Depends(get_observer_service),
) -> EventListResponse:
    """获取对局增量事件（用于轮询/分页）。

    Args:
        match_id: 对局 ID
        after_seq: 只返回序号（timestamp）大于该值的事件
        limit: 本次最多返回多少条事件
    """
    try:
        return await service.get_events_after(match_id, after_seq=after_seq, limit=limit)
    except MatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"match not found: {exc}") from exc
