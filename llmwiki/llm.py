from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
import tomllib

from .providers.base import BaseLLMProvider


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = True
    provider: str = "openai"
    model: str = "deepseek-v4-pro"
    base_url: str = "https://api.deepseek.com"
    api_key_file: str = "config/api-keys.toml"
    timeout_seconds: int = 60


def load_llm_config(root: Path) -> LLMConfig:
    config_path = main_config_path(root)
    data: dict[str, Any] = {}
    if config_path.exists():
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    llm = data.get("llm", {})
    return LLMConfig(
        enabled=bool(llm.get("enabled", True)),
        provider=str(llm.get("provider", "openai")),
        model=str(llm.get("model", "deepseek-v4-pro")),
        base_url=str(llm.get("base_url", "https://api.deepseek.com")),
        api_key_file=str(llm.get("api_key_file", "config/api-keys.toml")),
        timeout_seconds=int(llm.get("timeout_seconds", 60)),
    )


def main_config_path(root: Path) -> Path:
    current = root / "config" / "config.toml"
    if current.exists():
        return current
    return root / "config.toml"


def override_llm_config(
    config: LLMConfig,
    model: str | None = None,
    base_url: str | None = None,
    timeout_seconds: int | None = None,
) -> LLMConfig:
    updates: dict[str, Any] = {}
    if model:
        updates["model"] = model
    if base_url:
        updates["base_url"] = base_url
    if timeout_seconds is not None:
        updates["timeout_seconds"] = timeout_seconds
    return replace(config, **updates)


def create_provider(config: LLMConfig, root: Path | None = None) -> BaseLLMProvider:
    if config.provider != "openai":
        raise ValueError(f"Unsupported LLM provider: {config.provider}")
    from .providers.openai import OpenAIProvider

    return OpenAIProvider(config, root=root)
