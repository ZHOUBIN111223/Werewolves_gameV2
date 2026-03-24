"""Agent package exports."""

from __future__ import annotations

from .agent_store import AgentStore
from .memory_store import AgentMemoryStore, MemoryItem, ReflectionArtifact

__all__ = [
    "BaseAgent",
    "WitchAgent",
    "AgentStore",
    "AgentMemoryStore",
    "MemoryItem",
    "ReflectionArtifact",
]


def __getattr__(name: str):
    """Resolve heavier agent imports lazily to avoid package import cycles."""
    if name == "BaseAgent":
        from .base_agent import BaseAgent

        return BaseAgent

    if name == "WitchAgent":
        try:
            from .witch_agent import WitchAgent
        except ImportError:
            return None
        return WitchAgent

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
