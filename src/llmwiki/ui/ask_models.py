from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AskUiRequest:
    question: str
    limit: int = 8
    source_id: str | None = None
    page_type: str | None = None
    confidence: str | None = None


@dataclass(frozen=True)
class SynthesisPreviewRequest:
    writeback_mode: str = "auto"


@dataclass(frozen=True)
class SynthesisWritebackRequest:
    writeback_mode: str = "auto"
    preview_job_id: str = ""
