from __future__ import annotations

import pytest

from llmwiki.rerankers import (
    DeterministicReranker,
    LLMReranker,
    RerankedCandidate,
    RerankerValidationError,
    RerankingOptions,
    rerank_candidates,
)
from llmwiki.retrievers import RetrievalCandidate
from tests.test_vector_retrieval import FakeEmbeddingProvider, seed_vector_workspace, write_fake_index


def candidate(
    claim_id: str,
    *,
    source_id: str = "src_a",
    text: str | None = None,
    raw_score: float = 0.5,
    rank: int = 1,
    confidence: str = "cited",
    reasons: list[str] | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        claim_id=claim_id,
        source_id=source_id,
        claim_text=text or f"{claim_id} evidence",
        citation_locator="line:1",
        confidence_status=confidence,
        page_id=source_id,
        page_path=f"wiki/sources/{source_id}.md",
        page_type="source",
        raw_score=raw_score,
        retriever_rank=rank,
        retrievers=["hybrid"],
        reasons=reasons or ["bm25_fts"],
        matched_terms=["storage"],
    )


def test_deterministic_reranker_is_stable_and_prefers_cited_evidence():
    weak_top_rank = candidate("clm_weak", raw_score=0.9, rank=1, confidence="weak")
    cited_lower_rank = candidate("clm_cited", raw_score=0.8, rank=2, confidence="cited")

    result = DeterministicReranker().rerank(
        "generic question",
        [weak_top_rank, cited_lower_rank],
        RerankingOptions(method="deterministic"),
    )

    assert result.method == "deterministic"
    assert [item.candidate.claim_id for item in result.candidates] == ["clm_cited", "clm_weak"]
    assert all(item.candidate_rank > 0 for item in result.candidates)
    assert result.candidates[0].rerank_score > result.candidates[1].rerank_score


def test_deterministic_reranker_penalizes_near_duplicate_evidence():
    original = candidate("clm_original", raw_score=0.8, rank=1, text="same storage evidence")
    duplicate = candidate("clm_duplicate", raw_score=0.8, rank=2, text="same storage evidence")

    result = DeterministicReranker().rerank(
        "generic question",
        [duplicate, original],
        RerankingOptions(method="deterministic"),
    )

    scores = {item.candidate.claim_id: item.rerank_score for item in result.candidates}
    assert scores["clm_original"] > scores["clm_duplicate"]
    assert any("duplicate_penalty" in item.rerank_reasons for item in result.candidates)


def test_embedding_reranker_uses_claim_vectors_to_promote_semantic_match(monkeypatch):
    root = seed_vector_workspace()
    write_fake_index(root)
    monkeypatch.setattr(
        "llmwiki.embeddings.create_embedding_provider",
        lambda config, root=None: FakeEmbeddingProvider([1.0, 0.0]),
    )
    storage = candidate(
        "claim_strawberry_storage",
        source_id="src_strawberry",
        text="Store strawberries in the refrigerator and eat them soon after purchase.",
        raw_score=0.2,
        rank=2,
        reasons=["vector_semantic"],
    )
    vitamin = candidate(
        "claim_strawberry_vitamin",
        source_id="src_strawberry",
        text="Strawberries contain vitamin C.",
        raw_score=0.9,
        rank=1,
    )

    result = rerank_candidates(
        root,
        "spoil prevention after shopping",
        [vitamin, storage],
        RerankingOptions(method="embedding", fallback_method="deterministic"),
    )

    assert result.method == "embedding"
    assert result.candidates[0].candidate.claim_id == "claim_strawberry_storage"
    assert "embedding_similarity" in result.candidates[0].rerank_reasons


def test_embedding_reranker_falls_back_to_deterministic_without_index(monkeypatch):
    root = seed_vector_workspace()

    def fail_provider(*args, **kwargs):
        raise AssertionError("missing vector index must not call embedding provider")

    monkeypatch.setattr("llmwiki.embeddings.create_embedding_provider", fail_provider)

    result = rerank_candidates(
        root,
        "vitamin C",
        [candidate("claim_strawberry_vitamin")],
        RerankingOptions(method="embedding", fallback_method="deterministic"),
    )

    assert result.method == "deterministic"
    assert result.fallback_used is True
    assert result.warnings == []
    assert result.diagnostics["failure_stage"] == "embedding_rerank_failed"


def test_llm_reranker_rejects_forged_evidence_fields():
    class FakeProvider:
        def complete(self, messages, schema=None):
            return {
                "rankings": [
                    {
                        "candidate_id": "clm_a",
                        "score": 0.9,
                        "reason": "looks relevant",
                        "claim_id": "clm_forged",
                    }
                ]
            }

    with pytest.raises(RerankerValidationError):
        LLMReranker(FakeProvider()).rerank(
            "generic question",
            [candidate("clm_a")],
            RerankingOptions(method="llm"),
        )


def test_reranked_candidate_exposes_required_context_metadata():
    item = RerankedCandidate(
        candidate=candidate("clm_a"),
        candidate_rank=3,
        rerank_score=0.75,
        rerank_reasons=["deterministic"],
    )

    assert item.candidate.claim_id == "clm_a"
    assert item.candidate_rank == 3
    assert item.rerank_score == 0.75
