"""LLM 适配层导出。"""

from .mock_llm import MockLLM
from .real_llm import RealLLM

__all__ = ["MockLLM", "RealLLM"]
