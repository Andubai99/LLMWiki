from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider cannot complete a request safely."""


class BaseLLMProvider(ABC):
    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError
