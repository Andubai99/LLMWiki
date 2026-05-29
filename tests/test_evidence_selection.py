from __future__ import annotations

from llmwiki.evidence_selection import EvidenceSelectionOptions, select_evidence
from llmwiki.rerankers import RerankedCandidate
from llmwiki.retrievers import RetrievalCandidate


def candidate(
    claim_id: str,
    *,
    source_id: str,
    text: str | None = None,
    score: float,
    confidence: str = "cited",
    page_id: str | None = None,
) -> RerankedCandidate:
    page_id = page_id or source_id
    return RerankedCandidate(
        candidate=RetrievalCandidate(
            claim_id=claim_id,
            source_id=source_id,
            claim_text=text or f"{claim_id} evidence",
            citation_locator="line:1",
            confidence_status=confidence,
            page_id=page_id,
            page_path=f"wiki/sources/{source_id}.md",
            page_type="source",
            raw_score=score,
            retriever_rank=1,
            retrievers=["hybrid"],
            reasons=["bm25_fts"],
            matched_terms=[],
        ),
        candidate_rank=1,
        rerank_score=score,
        rerank_reasons=["deterministic"],
    )


def claim_ids(result) -> list[str]:
    return [item.candidate.claim_id for item in result.selected]


def test_selector_preserves_source_coverage_for_comparison_questions():
    candidates = [
        candidate("clm_a1", source_id="src_a", score=0.99),
        candidate("clm_a2", source_id="src_a", score=0.98),
        candidate("clm_a3", source_id="src_a", score=0.97),
        candidate("clm_b1", source_id="src_b", score=0.5),
    ]

    result = select_evidence(
        candidates,
        relationships=[],
        limit=3,
        options=EvidenceSelectionOptions(max_contexts_per_source=2),
    )

    assert claim_ids(result) == ["clm_a1", "clm_b1", "clm_a2"]
    assert result.diagnostics["source_diversity"] == 2
    assert all(item.coverage_group for item in result.selected)


def test_selector_removes_near_duplicate_claim_text_and_locator():
    candidates = [
        candidate("clm_a1", source_id="src_a", text="same evidence", score=0.9),
        candidate("clm_a2", source_id="src_a", text="same evidence", score=0.89),
        candidate("clm_b1", source_id="src_b", text="different evidence", score=0.5),
    ]

    result = select_evidence(
        candidates,
        relationships=[],
        limit=3,
        options=EvidenceSelectionOptions(max_contexts_per_source=3),
    )

    assert claim_ids(result) == ["clm_a1", "clm_b1"]
    assert result.diagnostics["redundancy_removed"] == 1
    assert any(item.redundancy_group for item in result.selected)


def test_selector_keeps_explicit_contradiction_visible():
    candidates = [
        candidate("clm_primary", source_id="src_a", score=0.95),
        candidate("clm_conflict", source_id="src_b", score=0.2),
        candidate("clm_other", source_id="src_c", score=0.8),
    ]
    relationships = [
        {
            "subject_id": "src_a",
            "object_id": "src_b",
            "relationship_type": "contradicts",
            "evidence_claim_id": "clm_conflict",
            "source_id": "src_b",
        }
    ]

    result = select_evidence(
        candidates,
        relationships=relationships,
        limit=2,
        options=EvidenceSelectionOptions(max_contexts_per_source=2),
    )

    assert "clm_conflict" in claim_ids(result)
    assert any("Contradictory evidence is present" in warning for warning in result.warnings)
    assert result.diagnostics["conflict_evidence_selected"] is True


def test_selector_prefers_cited_evidence_over_weak_with_same_coverage():
    candidates = [
        candidate("clm_weak", source_id="src_a", score=0.99, confidence="weak", page_id="concept_topic"),
        candidate("clm_cited", source_id="src_b", score=0.7, confidence="cited", page_id="concept_topic"),
    ]

    result = select_evidence(
        candidates,
        relationships=[],
        limit=1,
        options=EvidenceSelectionOptions(max_contexts_per_source=2),
    )

    assert claim_ids(result) == ["clm_cited"]
    assert result.selected[0].selection_reason == "best_cited_for_coverage"


def test_selector_outputs_required_context_metadata():
    result = select_evidence(
        [candidate("clm_a", source_id="src_a", score=0.8)],
        relationships=[],
        limit=1,
        options=EvidenceSelectionOptions(),
    )

    selected = result.selected[0]
    assert selected.candidate_rank == 1
    assert selected.rerank_score == 0.8
    assert selected.selection_reason
    assert selected.coverage_group
    assert selected.redundancy_group
