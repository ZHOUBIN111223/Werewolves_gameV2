from __future__ import annotations

from fastapi import FastAPI

from src.api.routers.matches import router as matches_router

app = FastAPI(
    title="Werewolves Observer API",
    version="0.1.0",
    description="Read-only observer API for the werewolves multi-agent controller.",
)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(matches_router)
