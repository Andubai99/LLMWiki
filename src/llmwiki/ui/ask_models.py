from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AskUiRequest:
    question: str
    limit: int = 8
    source_id: str | None = None
    page_type: str | None = None
    confidence: str | None = None
