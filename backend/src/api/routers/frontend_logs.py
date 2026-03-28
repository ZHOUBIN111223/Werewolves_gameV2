"""HTTP routes for frontend runtime logs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from src.api.schemas.runtime_log import FrontendLogIn, FrontendLogTailResponse, FrontendLogWriteResponse
from src.api.services.frontend_log_service import FrontendLogService


router = APIRouter(prefix="/api/frontend-logs", tags=["frontend-logs"])
_frontend_log_service = FrontendLogService()


def get_frontend_log_service() -> FrontendLogService:
    return _frontend_log_service


@router.post("", response_model=FrontendLogWriteResponse, status_code=status.HTTP_201_CREATED)
async def write_frontend_log(
    payload: FrontendLogIn,
    service: FrontendLogService = Depends(get_frontend_log_service),
) -> FrontendLogWriteResponse:
    record = await service.append(payload)
    return FrontendLogWriteResponse(id=record.id, path=str(service.log_file))


@router.get("", response_model=FrontendLogTailResponse)
async def get_frontend_logs(
    limit: int = Query(default=50, ge=1, le=200),
    service: FrontendLogService = Depends(get_frontend_log_service),
) -> FrontendLogTailResponse:
    return FrontendLogTailResponse(path=str(service.log_file), items=await service.tail(limit=limit))
