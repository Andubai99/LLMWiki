from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .rerankers import RerankedCandidate
from .retrievers import RetrievalCandidate


CONFLICT_WARNING = "Contradictory evidence is present; expose the conflict instead of resolving it silently."


@dataclass(frozen=True)
class EvidenceSelectionOptions:
    max_contexts_per_source: int = 3
    mode: str = "broad"
    mode_reason: str = ""
    dominant_coverage_group: str | None = None
    min_focused_cited: int = 3


@dataclass(frozen=True)
class SelectedEvidence:
    candidate: RetrievalCandidate
    candidate_rank: int
    rerank_score: float
    rerank_reasons: list[str]
    selection_reason: str
    coverage_group: str
    redundancy_group: str


@dataclass(frozen=True)
class EvidenceSelectionResult:
    selected: list[SelectedEvidence]
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def select_evidence(
    candidates: list[RerankedCandidate],
    *,
    relationships: list[dict[str, Any]],
    limit: int,
    options: EvidenceSelectionOptions | None = None,
) -> EvidenceSelectionResult:
    options = options or EvidenceSelectionOptions()
    limit = max(0, int(limit))
    if limit == 0 or not candidates:
        return EvidenceSelectionResult(
            selected=[],
            diagnostics={
                "mode": normalize_mode(options.mode),
                "mode_reason": options.mode_reason,
                "dominant_coverage_group": options.dominant_coverage_group,
                "outside_group_selected_count": 0,
                "missing_required_coverage": [],
                "candidate_count": len(candidates),
                "selected_count": 0,
                "source_diversity": 0,
                "redundancy_removed": 0,
                "conflict_evidence_selected": False,
            },
        )

    best_by_claim = dedupe_by_claim(candidates)
    ranked = sorted(
        best_by_claim.values(),
        key=lambda item: (-item.rerank_score, item.candidate.retriever_rank, item.candidate.claim_id),
    )
    ranked, redundancy_removed = remove_redundant_candidates(ranked)

    selected: list[SelectedEvidence] = []
    selected_claims: set[str] = set()
    selected_redundancy: set[str] = set()
    per_source: dict[str, int] = {}
    conflict_claim_ids = contradiction_claim_ids(relationships)
    mode = "conflict" if conflict_claim_ids else normalize_mode(options.mode)
    dominant_coverage_group = options.dominant_coverage_group or infer_dominant_coverage_group(ranked)
    missing_required_coverage: list[str] = []
    warnings: list[str] = []

    if mode == "conflict":
        warnings.append(CONFLICT_WARNING)
        top = ranked[0]
        add_selected(
            selected,
            selected_claims,
            selected_redundancy,
            per_source,
            top,
            "top_reranked",
            options,
            force=True,
        )
        for item in ranked:
            if item.candidate.claim_id in conflict_claim_ids:
                add_selected(
                    selected,
                    selected_claims,
                    selected_redundancy,
                    per_source,
                    item,
                    "conflict_evidence",
                    options,
                    force=True,
                )
            if len(selected) >= limit:
                break

    if mode == "focused":
        selected_focused = select_focused_evidence(
            ranked,
            selected,
            selected_claims,
            selected_redundancy,
            per_source,
            dominant_coverage_group,
            limit,
            options,
        )
        if not selected_focused:
            missing_required_coverage.append(dominant_coverage_group or "unknown")
    else:
        fill_by_coverage_then_score(
            ranked,
            selected,
            selected_claims,
            selected_redundancy,
            per_source,
            limit,
            options,
        )

    selected = selected[:limit]
    for item in selected:
        if item.candidate.confidence_status in {"weak", "uncited"}:
            warnings.append("Retrieved weak/uncited evidence; do not treat it as strong evidence.")
            break

    return EvidenceSelectionResult(
        selected=selected,
        warnings=unique(warnings),
        diagnostics={
            "candidate_count": len(candidates),
            "deduped_candidate_count": len(best_by_claim),
            "selected_count": len(selected),
            "mode": mode,
            "mode_reason": options.mode_reason,
            "dominant_coverage_group": dominant_coverage_group,
            "outside_group_selected_count": count_outside_group(selected, dominant_coverage_group),
            "missing_required_coverage": missing_required_coverage,
            "source_diversity": len({item.candidate.source_id for item in selected}),
            "coverage_group_count": len({item.coverage_group for item in selected}),
            "redundancy_removed": redundancy_removed,
            "conflict_candidate_count": len(conflict_claim_ids),
            "conflict_evidence_selected": any(
                item.candidate.claim_id in conflict_claim_ids for item in selected
            ),
            "weak_evidence_selected": any(
                item.candidate.confidence_status in {"weak", "uncited"} for item in selected
            ),
        },
    )


def select_focused_evidence(
    ranked: list[RerankedCandidate],
    selected: list[SelectedEvidence],
    selected_claims: set[str],
    selected_redundancy: set[str],
    per_source: dict[str, int],
    dominant_coverage_group: str | None,
    limit: int,
    options: EvidenceSelectionOptions,
) -> bool:
    if not dominant_coverage_group:
        return False
    focused_items = [item for item in ranked if coverage_group_for(item.candidate) == dominant_coverage_group]
    cited_focused = [item for item in focused_items if item.candidate.confidence_status == "cited"]
    required_count = min(limit, max(1, int(options.min_focused_cited)))
    enough_focused_evidence = len(cited_focused) >= required_count
    pool = cited_focused or focused_items
    for item in pool:
        if len(selected) >= limit:
            break
        add_selected(
            selected,
            selected_claims,
            selected_redundancy,
            per_source,
            item,
            "focused_dominant_group",
            options,
            force=enough_focused_evidence,
        )
    if enough_focused_evidence:
        return True
    for item in ranked:
        if len(selected) >= limit:
            break
        if coverage_group_for(item.candidate) == dominant_coverage_group:
            continue
        add_selected(
            selected,
            selected_claims,
            selected_redundancy,
            per_source,
            item,
            "fill_after_focused_evidence_exhausted",
            options,
        )
    return False


def fill_by_coverage_then_score(
    ranked: list[RerankedCandidate],
    selected: list[SelectedEvidence],
    selected_claims: set[str],
    selected_redundancy: set[str],
    per_source: dict[str, int],
    limit: int,
    options: EvidenceSelectionOptions,
) -> None:
    for item in best_per_coverage_group(ranked):
        if len(selected) >= limit:
            break
        reason = "best_cited_for_coverage" if item.candidate.confidence_status == "cited" else "best_for_coverage"
        add_selected(
            selected,
            selected_claims,
            selected_redundancy,
            per_source,
            item,
            reason,
            options,
        )

    for item in ranked:
        if len(selected) >= limit:
            break
        add_selected(
            selected,
            selected_claims,
            selected_redundancy,
            per_source,
            item,
            "fill_by_rerank_score",
            options,
        )


def add_selected(
    selected: list[SelectedEvidence],
    selected_claims: set[str],
    selected_redundancy: set[str],
    per_source: dict[str, int],
    item: RerankedCandidate,
    reason: str,
    options: EvidenceSelectionOptions,
    *,
    force: bool = False,
) -> bool:
    candidate = item.candidate
    if candidate.claim_id in selected_claims:
        return False
    redundancy_group = redundancy_group_for(candidate)
    if redundancy_group in selected_redundancy:
        return False
    if not force and per_source.get(candidate.source_id, 0) >= options.max_contexts_per_source:
        return False
    selected_claims.add(candidate.claim_id)
    selected_redundancy.add(redundancy_group)
    per_source[candidate.source_id] = per_source.get(candidate.source_id, 0) + 1
    selected.append(
        SelectedEvidence(
            candidate=candidate,
            candidate_rank=item.candidate_rank,
            rerank_score=item.rerank_score,
            rerank_reasons=item.rerank_reasons,
            selection_reason=reason,
            coverage_group=coverage_group_for(candidate),
            redundancy_group=redundancy_group,
        )
    )
    return True


def dedupe_by_claim(candidates: list[RerankedCandidate]) -> dict[str, RerankedCandidate]:
    best: dict[str, RerankedCandidate] = {}
    for item in candidates:
        claim_id = item.candidate.claim_id
        existing = best.get(claim_id)
        if existing is None or item.rerank_score > existing.rerank_score:
            best[claim_id] = item
    return best


def remove_redundant_candidates(candidates: list[RerankedCandidate]) -> tuple[list[RerankedCandidate], int]:
    seen: set[str] = set()
    result: list[RerankedCandidate] = []
    removed = 0
    for item in candidates:
        group = redundancy_group_for(item.candidate)
        if group in seen:
            removed += 1
            continue
        seen.add(group)
        result.append(item)
    return result, removed


def best_per_coverage_group(candidates: list[RerankedCandidate]) -> list[RerankedCandidate]:
    groups: dict[str, list[RerankedCandidate]] = {}
    group_order: list[str] = []
    for item in candidates:
        group = coverage_group_for(item.candidate)
        if group not in groups:
            group_order.append(group)
            groups[group] = []
        groups[group].append(item)

    result: list[RerankedCandidate] = []
    for group in group_order:
        items = groups[group]
        cited = [item for item in items if item.candidate.confidence_status == "cited"]
        pool = cited or items
        pool.sort(key=lambda item: (-item.rerank_score, item.candidate.claim_id))
        result.append(pool[0])
    return result


def contradiction_claim_ids(relationships: list[dict[str, Any]]) -> set[str]:
    claim_ids: set[str] = set()
    for relationship in relationships:
        if str(relationship.get("relationship_type") or "") != "contradicts":
            continue
        evidence_claim_id = str(relationship.get("evidence_claim_id") or "")
        if evidence_claim_id:
            claim_ids.add(evidence_claim_id)
    return claim_ids


def normalize_mode(mode: str) -> str:
    value = str(mode or "broad")
    if value in {"focused", "comparison", "conflict", "broad"}:
        return value
    return "broad"


def infer_dominant_coverage_group(candidates: list[RerankedCandidate]) -> str | None:
    if not candidates:
        return None
    return coverage_group_for(candidates[0].candidate)


def count_outside_group(selected: list[SelectedEvidence], dominant_coverage_group: str | None) -> int:
    if not dominant_coverage_group:
        return 0
    return sum(1 for item in selected if item.coverage_group != dominant_coverage_group)


def coverage_group_for(candidate: RetrievalCandidate) -> str:
    subquery_index = getattr(candidate, "subquery_index", None)
    if subquery_index is not None:
        return f"subquery:{subquery_index}"
    if candidate.page_id and not candidate.page_id.startswith("src_"):
        return f"page:{candidate.page_id}"
    return f"source:{candidate.source_id}"


def redundancy_group_for(candidate: RetrievalCandidate) -> str:
    text = re.sub(r"\s+", " ", candidate.claim_text.casefold()).strip()
    return text or f"claim:{candidate.claim_id}"


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item)
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
