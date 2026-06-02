from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Protocol
import tomllib

from .llm import main_config_path
from .retrievers import RetrievalCandidate
from .vector_index import cosine_similarity, load_vector_index, vector_index_status


FORBIDDEN_LLM_EVIDENCE_FIELDS = {
    "claim_id",
    "source_id",
    "citation_locator",
    "page_path",
    "page_id",
    "score",
}


@dataclass(frozen=True)
class RerankingOptions:
    enabled: bool = True
    method: str = "embedding"
    fallback_method: str = "deterministic"
    candidate_pool_limit: int = 80
    max_contexts_per_source: int = 3
    llm_reranker_enabled: bool = False


@dataclass(frozen=True)
class RerankedCandidate:
    candidate: RetrievalCandidate
    candidate_rank: int
    rerank_score: float
    rerank_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RerankResult:
    method: str
    candidates: list[RerankedCandidate]
    fallback_used: bool = False
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


class RerankerError(RuntimeError):
    pass


class RerankerValidationError(RerankerError):
    pass


class LLMRerankProvider(Protocol):
    def complete(self, messages: list[dict[str, str]], schema: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


def load_reranking_options(root: Path) -> RerankingOptions:
    config_path = main_config_path(root)
    if not config_path.exists():
        return RerankingOptions()
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    reranking = data.get("reranking", {})
    return RerankingOptions(
        enabled=bool(reranking.get("enabled", True)),
        method=str(reranking.get("default_method", "embedding")),
        fallback_method=str(reranking.get("fallback_method", "deterministic")),
        candidate_pool_limit=int(reranking.get("candidate_pool_limit", 80)),
        max_contexts_per_source=int(reranking.get("max_contexts_per_source", 3)),
        llm_reranker_enabled=bool(reranking.get("llm_reranker_enabled", False)),
    )


class DeterministicReranker:
    method = "deterministic"

    def rerank(
        self,
        question: str,
        candidates: list[RetrievalCandidate],
        options: RerankingOptions | None = None,
    ) -> RerankResult:
        duplicate_indexes = duplicate_index_by_claim_text(candidates)
        scored: list[RerankedCandidate] = []
        for candidate in candidates:
            score = deterministic_score(candidate)
            reasons = ["deterministic"]
            if candidate.confidence_status == "cited":
                reasons.append("cited_evidence")
            elif candidate.confidence_status in {"weak", "uncited"}:
                reasons.append("weak_evidence_penalty")
            if duplicate_indexes.get(candidate.claim_id, 0) > 0:
                score *= 0.7
                reasons.append("duplicate_penalty")
            scored.append(
                RerankedCandidate(
                    candidate=candidate,
                    candidate_rank=max(int(candidate.retriever_rank or 0), 1),
                    rerank_score=round(score, 6),
                    rerank_reasons=unique(reasons),
                )
            )
        scored.sort(
            key=lambda item: (
                -item.rerank_score,
                item.candidate.retriever_rank,
                item.candidate.claim_id,
            )
        )
        return RerankResult(
            method=self.method,
            candidates=scored,
            diagnostics={
                "method": self.method,
                "candidate_count": len(candidates),
                "returned_count": len(scored),
            },
        )


class EmbeddingReranker:
    method = "embedding"

    def __init__(self, root: Path) -> None:
        self.root = root

    def rerank(
        self,
        question: str,
        candidates: list[RetrievalCandidate],
        options: RerankingOptions | None = None,
    ) -> RerankResult:
        if not candidates:
            return RerankResult(method=self.method, candidates=[])

        from . import embeddings

        config = embeddings.load_embedding_config(self.root)
        status = vector_index_status(self.root)
        if not config.enabled:
            raise RerankerError("Embedding reranker is disabled.")
        if not status.index_present:
            raise RerankerError("Embedding reranker index is missing.")
        try:
            index = load_vector_index(self.root)
            provider = embeddings.create_embedding_provider(config, root=self.root)
            query_vectors = provider.embed_texts([question])
        except Exception as exc:
            raise RerankerError(embeddings.sanitize_embedding_error(str(exc))) from exc
        if not query_vectors:
            raise RerankerError("Embedding reranker query embedding is empty.")
        query_vector = query_vectors[0]
        if len(query_vector) != index.manifest.dimension:
            raise RerankerError("Embedding reranker query dimension does not match index.")

        claim_vectors: dict[str, list[float]] = {}
        for chunk, vector in zip(index.chunks, index.vectors):
            if chunk.chunk_type != "claim":
                continue
            claim_id = str(chunk.metadata.get("claim_id") or "")
            if claim_id:
                claim_vectors[claim_id] = vector

        deterministic = DeterministicReranker().rerank(
            question,
            candidates,
            options or RerankingOptions(method=self.method),
        )
        deterministic_by_claim = {item.candidate.claim_id: item.rerank_score for item in deterministic.candidates}
        max_deterministic = max(deterministic_by_claim.values() or [1.0])
        scored: list[RerankedCandidate] = []
        for candidate in candidates:
            similarity = 0.0
            reasons = ["embedding_rerank"]
            vector = claim_vectors.get(candidate.claim_id)
            if vector is not None:
                similarity = max(0.0, cosine_similarity(query_vector, vector))
                reasons.append("embedding_similarity")
            deterministic_component = deterministic_by_claim.get(candidate.claim_id, deterministic_score(candidate))
            normalized_deterministic = deterministic_component / max_deterministic if max_deterministic else 0.0
            score = (0.65 * similarity) + (0.35 * normalized_deterministic)
            scored.append(
                RerankedCandidate(
                    candidate=candidate,
                    candidate_rank=max(int(candidate.retriever_rank or 0), 1),
                    rerank_score=round(score, 6),
                    rerank_reasons=unique(reasons),
                )
            )
        scored.sort(
            key=lambda item: (
                -item.rerank_score,
                item.candidate.retriever_rank,
                item.candidate.claim_id,
            )
        )
        return RerankResult(
            method=self.method,
            candidates=scored,
            diagnostics={
                "method": self.method,
                "candidate_count": len(candidates),
                "returned_count": len(scored),
                "provider": index.manifest.provider,
                "model": index.manifest.model,
                "dimension": index.manifest.dimension,
            },
        )


class LLMReranker:
    method = "llm"

    def __init__(self, provider: LLMRerankProvider) -> None:
        self.provider = provider

    def rerank(
        self,
        question: str,
        candidates: list[RetrievalCandidate],
        options: RerankingOptions | None = None,
    ) -> RerankResult:
        candidate_ids = {candidate.claim_id for candidate in candidates}
        response = self.provider.complete(
            [
                {
                    "role": "system",
                    "content": "Rank local evidence candidates by relevance. Do not output evidence fields.",
                },
                {
                    "role": "user",
                    "content": str(
                        {
                            "question": question,
                            "candidate_ids": sorted(candidate_ids),
                        }
                    ),
                },
            ],
            schema=llm_reranker_schema(),
        )
        rankings = response.get("rankings")
        if not isinstance(rankings, list):
            raise RerankerValidationError("LLM reranker response is missing rankings.")
        validate_no_forged_evidence_fields(rankings)
        by_claim = {candidate.claim_id: candidate for candidate in candidates}
        scored: list[RerankedCandidate] = []
        used: set[str] = set()
        for item in rankings:
            if not isinstance(item, dict):
                raise RerankerValidationError("LLM reranker ranking item is invalid.")
            candidate_id = str(item.get("candidate_id") or "")
            if candidate_id not in candidate_ids:
                raise RerankerValidationError(f"LLM reranker referenced unknown candidate: {candidate_id}")
            used.add(candidate_id)
            try:
                score = float(item.get("relevance_score", item.get("relevance", 0.0)))
            except (TypeError, ValueError) as exc:
                raise RerankerValidationError("LLM reranker score is invalid.") from exc
            reason = str(item.get("reason") or "llm_rerank")
            candidate = by_claim[candidate_id]
            scored.append(
                RerankedCandidate(
                    candidate=candidate,
                    candidate_rank=max(int(candidate.retriever_rank or 0), 1),
                    rerank_score=round(score, 6),
                    rerank_reasons=unique(["llm_rerank", reason]),
                )
            )
        for candidate in candidates:
            if candidate.claim_id in used:
                continue
            scored.append(
                RerankedCandidate(
                    candidate=candidate,
                    candidate_rank=max(int(candidate.retriever_rank or 0), 1),
                    rerank_score=0.0,
                    rerank_reasons=["llm_unranked"],
                )
            )
        scored.sort(key=lambda item: (-item.rerank_score, item.candidate.retriever_rank, item.candidate.claim_id))
        return RerankResult(method=self.method, candidates=scored)


def rerank_candidates(
    root: Path,
    question: str,
    candidates: list[RetrievalCandidate],
    options: RerankingOptions | None = None,
) -> RerankResult:
    options = options or load_reranking_options(root)
    if not options.enabled:
        return DeterministicReranker().rerank(question, candidates, options)
    if options.method == "deterministic":
        return DeterministicReranker().rerank(question, candidates, options)
    if options.method == "embedding":
        try:
            return EmbeddingReranker(root).rerank(question, candidates, options)
        except RerankerError as exc:
            sanitized = sanitize_reranker_error(str(exc))
            warnings = [] if is_quiet_embedding_fallback(sanitized) else [sanitized]
            fallback = DeterministicReranker().rerank(question, candidates, options)
            return RerankResult(
                method=fallback.method,
                candidates=fallback.candidates,
                fallback_used=True,
                warnings=warnings,
                diagnostics={
                    **fallback.diagnostics,
                    "requested_method": "embedding",
                    "fallback_method": fallback.method,
                    "failure_stage": "embedding_rerank_failed",
                    "failure_reason": sanitized,
                },
            )
    if options.method == "llm":
        if not options.llm_reranker_enabled:
            fallback = DeterministicReranker().rerank(question, candidates, options)
            return RerankResult(
                method=fallback.method,
                candidates=fallback.candidates,
                fallback_used=True,
                warnings=["LLM reranker is disabled; used deterministic reranker."],
                diagnostics={**fallback.diagnostics, "requested_method": "llm"},
            )
        raise RerankerError("LLM reranker provider is not configured for this call.")
    return DeterministicReranker().rerank(question, candidates, options)


def deterministic_score(candidate: RetrievalCandidate) -> float:
    raw = max(0.0, min(float(candidate.raw_score), 1.0))
    rank_bonus = 1.0 / (max(int(candidate.retriever_rank or 1), 1) + 1)
    score = (0.65 * raw) + (0.2 * rank_bonus)
    if candidate.confidence_status == "cited":
        score += 0.18
    elif candidate.confidence_status in {"weak", "uncited"}:
        score -= 0.18
    if candidate.citation_locator:
        score += 0.04
    if "vector" in candidate.retrievers:
        score += 0.03
    return max(0.0, score)


def duplicate_index_by_claim_text(candidates: list[RetrievalCandidate]) -> dict[str, int]:
    groups: dict[str, list[RetrievalCandidate]] = {}
    for candidate in candidates:
        groups.setdefault(normalize_claim_text(candidate.claim_text), []).append(candidate)
    indexes: dict[str, int] = {}
    for group in groups.values():
        group.sort(key=lambda item: (-float(item.raw_score), int(item.retriever_rank or 1), item.claim_id))
        for index, candidate in enumerate(group):
            indexes[candidate.claim_id] = index
    return indexes


def validate_no_forged_evidence_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in FORBIDDEN_LLM_EVIDENCE_FIELDS:
                raise RerankerValidationError(f"LLM reranker output forbidden evidence field: {key}")
            validate_no_forged_evidence_fields(item)
    elif isinstance(value, list):
        for item in value:
            validate_no_forged_evidence_fields(item)


def llm_reranker_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["rankings"],
        "properties": {
            "rankings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["candidate_id", "relevance_score", "reason"],
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "relevance_score": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }


def normalize_claim_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def sanitize_reranker_error(message: str) -> str:
    safe = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-[redacted]", message)
    safe = safe.replace("config/api-keys.toml", "[api-key-file]")
    safe = safe.replace("config\\api-keys.toml", "[api-key-file]")
    return safe


def is_quiet_embedding_fallback(message: str) -> bool:
    folded = message.casefold()
    return "index is missing" in folded or "disabled" in folded


def unique(items: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
