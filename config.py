"""Project configuration helpers."""

from __future__ import annotations

import os
from typing import Any, Dict


def _looks_like_valid_api_key(value: str) -> bool:
    value = str(value or "").strip()
    return bool(value) and not (value.startswith("sk-") and len(value) < 20)


class APIConfig:
    """API-level defaults."""

    DEFAULT_API_PROVIDER = os.getenv("DEFAULT_API_PROVIDER", "openai")

    CUSTOM_LLM_ENDPOINT = os.getenv(
        "CUSTOM_LLM_ENDPOINT",
        os.getenv("CUSTOM_BASE_URL", "http://localhost:8000/v1"),
    )
    CUSTOM_LLM_API_KEY = os.getenv(
        "CUSTOM_LLM_API_KEY",
        os.getenv("LITELLM_API_KEY", os.getenv("CUSTOM_API_KEY", "")),
    )
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")

    BAILIAN_ENDPOINT = os.getenv(
        "BAILIAN_ENDPOINT",
        "https://coding.dashscope.aliyuncs.com/v1",
    )
    BAILIAN_API_KEY = os.getenv("BAILIAN_API_KEY", "")
    BAILIAN_DEFAULT_MODEL = os.getenv("BAILIAN_DEFAULT_MODEL", "glm-5")

    API_TIMEOUT = int(os.getenv("API_TIMEOUT", "60"))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1000"))


class GameConfig:
    """Game role setups."""

    GAME_ROLES_CONFIG = {
        6: {
            "werewolf": 2,
            "seer": 1,
            "witch": 1,
            "hunter": 1,
            "villager": 1,
        },
        9: {
            "werewolf": 3,
            "seer": 1,
            "witch": 1,
            "hunter": 1,
            "villager": 3,
        },
        12: {
            "werewolf": 4,
            "seer": 1,
            "witch": 1,
            "hunter": 1,
            "guard": 1,
            "villager": 4,
        },
    }


class AppConfig:
    """Application paths and logging defaults."""

    STORE_PATH = os.getenv("STORE_PATH", "./store_data")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_PATH = os.getenv("LOG_PATH", "./logs")


def get_config_for_provider(provider: str) -> Dict[str, Any]:
    """Return normalized configuration for the requested provider."""

    configs = {
        "openai": {
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "default_model": os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini"),
            "endpoint": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        },
        "anthropic": {
            "base_url": os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
            "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
            "default_model": os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-3-haiku-20240307"),
            "endpoint": os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
        },
        "bailian": {
            "base_url": os.getenv(
                "BAILIAN_ENDPOINT",
                "https://coding.dashscope.aliyuncs.com/v1",
            ),
            "api_key": os.getenv("BAILIAN_API_KEY", ""),
            "default_model": os.getenv("BAILIAN_DEFAULT_MODEL", "glm-5"),
            "endpoint": os.getenv(
                "BAILIAN_ENDPOINT",
                "https://coding.dashscope.aliyuncs.com/v1",
            ),
        },
        "custom": {
            "base_url": os.getenv(
                "CUSTOM_BASE_URL",
                os.getenv("CUSTOM_LLM_ENDPOINT", "http://localhost:8000/v1"),
            ),
            "api_key": os.getenv(
                "CUSTOM_API_KEY",
                os.getenv("LITELLM_API_KEY", os.getenv("CUSTOM_LLM_API_KEY", "")),
            ),
            "default_model": os.getenv("CUSTOM_DEFAULT_MODEL", "custom-model"),
            "endpoint": os.getenv(
                "CUSTOM_BASE_URL",
                os.getenv("CUSTOM_LLM_ENDPOINT", "http://localhost:8000/v1"),
            ),
        },
        "mock": {
            "base_url": "http://mock-server",
            "api_key": "mock-key",
            "default_model": "mock-model",
            "endpoint": "http://mock-server",
        },
    }

    return configs.get(provider, configs["openai"])


def validate_config(api_provider: str | None = None) -> bool:
    """Validate configuration and ensure runtime directories exist."""

    api_provider = api_provider or os.getenv("DEFAULT_API_PROVIDER", "openai")
    config = get_config_for_provider(api_provider)

    if api_provider == "mock":
        pass
    elif api_provider == "custom":
        api_key = os.getenv("LITELLM_API_KEY", config["api_key"])
        if not _looks_like_valid_api_key(api_key):
            raise ValueError("API密钥未正确设置。对于 custom 提供者，请配置有效的 LITELLM_API_KEY。")
    else:
        api_key = config["api_key"]
        if not _looks_like_valid_api_key(api_key):
            raise ValueError(
                f"API密钥未正确设置。对于 {api_provider} 提供者，请配置有效的 API 密钥。"
            )

    os.makedirs(AppConfig.STORE_PATH, exist_ok=True)
    os.makedirs(AppConfig.LOG_PATH, exist_ok=True)
    return True
