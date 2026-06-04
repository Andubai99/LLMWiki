from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import UiResponse, UiWarning


@dataclass(frozen=True)
class ClaimSummary:
    claim_id: str = ""
    claim_text: str = ""
    source_id: str = ""
    source_title: str = ""
    citation_locator: str = ""
    confidence_status: str = ""
    created_at: str = ""
    page: dict[str, Any] = field(default_factory=dict)
    relationship_types: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RelationshipSummary:
    subject_id: str = ""
    object_id: str = ""
    relationship_type: str = ""
    evidence_claim_id: str = ""
    source_id: str = ""
    subject_title: str = ""
    object_title: str = ""
    evidence_claim_text: str = ""
    source_title: str = ""


@dataclass(frozen=True)
class SourceDetailResponse(UiResponse):
    source: dict[str, Any] = field(default_factory=dict)
    latest_run: dict[str, Any] = field(default_factory=dict)
    latest_job: dict[str, Any] = field(default_factory=dict)
    source_page: dict[str, Any] = field(default_factory=dict)
    sidecars: dict[str, bool] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    claim_counts: dict[str, int] = field(default_factory=dict)
    claims: list[ClaimSummary] = field(default_factory=list)
    relationships: list[RelationshipSummary] = field(default_factory=list)
    warnings: list[UiWarning] = field(default_factory=list)


@dataclass(frozen=True)
class PageDetailResponse(UiResponse):
    page: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    markdown: str = ""
    markdown_truncated: bool = False
    markdown_is_evidence: bool = False
    outgoing_links: list[dict[str, Any]] = field(default_factory=list)
    incoming_links: list[dict[str, Any]] = field(default_factory=list)
    related_source_ids: list[str] = field(default_factory=list)
    related_claims: list[ClaimSummary] = field(default_factory=list)
    relationships: list[RelationshipSummary] = field(default_factory=list)
    warnings: list[UiWarning] = field(default_factory=list)


@dataclass(frozen=True)
class ClaimListResponse(UiResponse):
    claims: list[ClaimSummary] = field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    warnings: list[UiWarning] = field(default_factory=list)


@dataclass(frozen=True)
class ClaimDetailResponse(UiResponse):
    claim: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    source_page: dict[str, Any] = field(default_factory=dict)
    candidate_pages: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[RelationshipSummary] = field(default_factory=list)
    locator_context: dict[str, Any] = field(default_factory=dict)
    warnings: list[UiWarning] = field(default_factory=list)


@dataclass(frozen=True)
class RelationshipListResponse(UiResponse):
    relationships: list[RelationshipSummary] = field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    warnings: list[UiWarning] = field(default_factory=list)
