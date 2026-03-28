"""Persistence helpers for frontend runtime logs."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import aiofiles
from pydantic import ValidationError

from config import AppConfig
from src.api.schemas.runtime_log import FrontendLogIn, FrontendLogRecord


class FrontendLogService:
    """Append-only JSONL storage for frontend runtime logs."""

    def __init__(self, log_dir: str | Path | None = None) -> None:
        self._log_dir = Path(log_dir) if log_dir is not None else Path(AppConfig.LOG_PATH) / "frontend_runtime"
        self._log_file = self._log_dir / "frontend-runtime.jsonl"

    @property
    def log_file(self) -> Path:
        return self._log_file

    async def append(self, entry: FrontendLogIn) -> FrontendLogRecord:
        self._log_dir.mkdir(parents=True, exist_ok=True)

        record = FrontendLogRecord(
            id=uuid4().hex,
            server_time=datetime.now(timezone.utc),
            **entry.model_dump(),
        )

        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n"
        async with aiofiles.open(self._log_file, "a", encoding="utf-8") as handle:
            await handle.write(line)

        return record

    async def tail(self, limit: int = 50) -> list[FrontendLogRecord]:
        if not self._log_file.exists():
            return []

        text = await asyncio.to_thread(self._log_file.read_text, encoding="utf-8")
        items: list[FrontendLogRecord] = []

        for line in text.splitlines()[-limit:]:
            if not line.strip():
                continue

            try:
                items.append(FrontendLogRecord.model_validate_json(line))
            except ValidationError:
                continue

        return items
