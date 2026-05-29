from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from typing import Protocol

from .query_analysis import RetrievalQuery
from .vector_index import cosine_similarity, load_vector_index, vector_index_status


@dataclass(frozen=True)
class RetrievalFilters:
    source_id: str | None = None
    page_type: str | None = None
    confidence: str | None = None


@dataclass(frozen=True)
class RetrievalCandidate:
    claim_id: str
    source_id: str
    claim_text: str
    citation_locator: str
    confidence_status: str
    page_id: str
    page_path: str
    page_type: str
    raw_score: float
    retriever_rank: int
    retrievers: list[str]
    reasons: list[str]
    matched_terms: list[str] | None = None


@dataclass(frozen=True)
class RetrieverResult:
    name: str
    candidates: list[RetrievalCandidate]
    diagnostics: dict[str, object] = field(default_factory=dict)


class Retriever(Protocol):
    name: str

    def retrieve(
        self,
        conn,
        query: RetrievalQuery,
        *,
        limit: int,
        filters: RetrievalFilters,
    ) -> RetrieverResult:
        ...


class BM25ClaimRetriever:
    name = "bm25_fts"

    def retrieve(
        self,
        conn,
        query: RetrievalQuery,
        *,
        limit: int,
        filters: RetrievalFilters,
    ) -> RetrieverResult:
        candidates: dict[str, RetrievalCandidate] = {}
        fetch_limit = max(limit * 8, 20)
        terms = searchable_terms(query)
        fts_terms = [term for term in terms if fts_safe(term)]
        if fts_terms:
            fts_query = " OR ".join(quote_fts_term(term) for term in fts_terms)
            try:
                rows = conn.execute(
                    """
                    select c.claim_id, c.source_id, c.claim_text, c.citation_locator,
                           c.confidence_status, bm25(claims_fts) as rank
                    from claims_fts
                    join claims c on c.claim_id = claims_fts.claim_id
                    where claims_fts match ?
                    order by bm25(claims_fts)
                    limit ?
                    """,
                    (fts_query, fetch_limit),
                ).fetchall()
            except Exception:
                rows = []
            for row in rows:
                claim_terms = matched_terms(row_search_text(row), terms)
                candidate = candidate_from_claim_row(
                    conn,
                    row,
                    page_info=source_page_info(conn, str(row["source_id"])),
                    raw_score=relevance_score(1.0, claim_terms, query),
                    retriever=self.name,
                    reasons=["bm25_fts"],
                    matched_terms=claim_terms,
                )
                remember_candidate(candidates, candidate)

        like_terms = terms[:20]
        if like_terms:
            clauses = " or ".join("lower(claim_text) like ? escape '\\'" for _ in like_terms)
            params = [like_pattern(term) for term in like_terms]
            rows = conn.execute(
                f"""
                select claim_id, source_id, claim_text, citation_locator, confidence_status
                from claims
                where {clauses}
                order by created_at, claim_id
                limit ?
                """,
                (*params, fetch_limit),
            ).fetchall()
            for row in rows:
                claim_terms = matched_terms(row_search_text(row), like_terms)
                candidate = candidate_from_claim_row(
                    conn,
                    row,
                    page_info=source_page_info(conn, str(row["source_id"])),
                    raw_score=relevance_score(0.5, claim_terms, query),
                    retriever=self.name,
                    reasons=["like_match"],
                    matched_terms=claim_terms,
                )
                remember_candidate(candidates, candidate)

        return ranked_result(self.name, candidates.values(), limit, filters)


class CatalogTitleAliasRetriever:
    name = "catalog_title_alias"

    def retrieve(
        self,
        conn,
        query: RetrievalQuery,
        *,
        limit: int,
        filters: RetrievalFilters,
    ) -> RetrieverResult:
        candidates: dict[str, RetrievalCandidate] = {}
        page_matches = catalog_page_matches(conn, query)
        for page, reason in page_matches:
            for source_id in source_ids_for_page(conn, page):
                for row in claim_rows_for_source(conn, source_id):
                    claim_terms = matched_terms(row_search_text(row), query.all_terms())
                    base_score = 1.0 if reason.startswith("alias_exact") else 0.8
                    candidate = candidate_from_claim_row(
                        conn,
                        row,
                        page_info=page,
                        raw_score=relevance_score(base_score, claim_terms, query),
                        retriever=self.name,
                        reasons=[reason, "page_source_claims"],
                        matched_terms=claim_terms or query.catalog_terms or query.text_terms,
                    )
                    remember_candidate(candidates, candidate)
        return ranked_result(self.name, candidates.values(), limit, filters)


class ExactFormulaSymbolRetriever:
    name = "exact_formula_symbol"

    def retrieve(
        self,
        conn,
        query: RetrievalQuery,
        *,
        limit: int,
        filters: RetrievalFilters,
    ) -> RetrieverResult:
        candidates: dict[str, RetrievalCandidate] = {}
        spans = unique([*query.exact_spans, *query.formula_spans, *query.symbol_spans])
        for span in spans:
            if not span:
                continue
            rows = conn.execute(
                """
                select distinct c.claim_id, c.source_id, c.claim_text, c.citation_locator, c.confidence_status
                from claims c
                left join sources s on s.source_id = c.source_id
                where lower(c.claim_text) like ? escape '\\'
                   or lower(c.citation_locator) like ? escape '\\'
                   or lower(coalesce(s.title, '')) like ? escape '\\'
                order by c.created_at, c.claim_id
                limit ?
                """,
                (*(like_pattern(span) for _ in range(3)), max(limit * 4, 20)),
            ).fetchall()
            for row in rows:
                claim_terms = matched_terms(row_search_text(row), query.all_terms())
                candidate = candidate_from_claim_row(
                    conn,
                    row,
                    page_info=source_page_info(conn, str(row["source_id"])),
                    raw_score=relevance_score(1.0, claim_terms or [span], query),
                    retriever=self.name,
                    reasons=[f"exact_span:{span}"],
                    matched_terms=claim_terms or [span],
                )
                remember_candidate(candidates, candidate)
            page_rows = conn.execute(
                """
                select distinct p.page_id, p.path, p.page_type, p.title
                from pages p
                left join aliases a on a.target_id = p.page_id
                where lower(p.title) like ? escape '\\'
                   or lower(coalesce(a.alias, '')) like ? escape '\\'
                   or lower(coalesce(a.normalized_alias, '')) like ? escape '\\'
                order by p.page_type, p.title
                limit ?
                """,
                (*(like_pattern(span) for _ in range(3)), max(limit * 2, 20)),
            ).fetchall()
            for page_row in page_rows:
                page = page_dict(page_row)
                for source_id in source_ids_for_page(conn, page):
                    for row in claim_rows_for_source(conn, source_id):
                        claim_terms = matched_terms(row_search_text(row), query.all_terms())
                        candidate = candidate_from_claim_row(
                            conn,
                            row,
                            page_info=page,
                            raw_score=relevance_score(1.0, claim_terms or [span], query),
                            retriever=self.name,
                            reasons=[f"exact_span:{span}", "page_source_claims"],
                            matched_terms=claim_terms or [span],
                        )
                        remember_candidate(candidates, candidate)
        return ranked_result(self.name, candidates.values(), limit, filters)


class GraphRelationshipRetriever:
    name = "graph_relationship"

    def __init__(self, seed_candidates: list[RetrievalCandidate] | None = None) -> None:
        self.seed_candidates = seed_candidates or []

    def retrieve(
        self,
        conn,
        query: RetrievalQuery,
        *,
        limit: int,
        filters: RetrievalFilters,
    ) -> RetrieverResult:
        candidates: dict[str, RetrievalCandidate] = {}
        seed_claim_ids = {candidate.claim_id for candidate in self.seed_candidates}
        seed_source_ids = {candidate.source_id for candidate in self.seed_candidates}
        seed_page_ids = {candidate.page_id for candidate in self.seed_candidates}
        if not (seed_claim_ids or seed_source_ids or seed_page_ids):
            return RetrieverResult(self.name, [])
        placeholders = ", ".join("?" for _ in seed_claim_ids | seed_source_ids | seed_page_ids)
        values = tuple(seed_claim_ids | seed_source_ids | seed_page_ids)
        rows = conn.execute(
            f"""
            select subject_id, object_id, relationship_type, evidence_claim_id, source_id
            from relationships
            where subject_id in ({placeholders})
               or object_id in ({placeholders})
               or evidence_claim_id in ({placeholders})
               or source_id in ({placeholders})
            """,
            values * 4,
        ).fetchall()
        related_claim_ids = {str(row["evidence_claim_id"]) for row in rows if row["evidence_claim_id"]}
        related_source_ids = {str(row["source_id"]) for row in rows if row["source_id"]}
        for source_id in related_source_ids:
            for claim in claim_rows_for_source(conn, source_id):
                related_claim_ids.add(str(claim["claim_id"]))
        for claim_id in related_claim_ids:
            row = conn.execute(
                """
                select claim_id, source_id, claim_text, citation_locator, confidence_status
                from claims
                where claim_id = ?
                """,
                (claim_id,),
            ).fetchone()
            if row is None or str(row["claim_id"]) in seed_claim_ids:
                continue
            candidate = candidate_from_claim_row(
                conn,
                row,
                page_info=source_page_info(conn, str(row["source_id"])),
                raw_score=0.4,
                retriever=self.name,
                reasons=["graph_relationship"],
                matched_terms=[],
            )
            remember_candidate(candidates, candidate)
        return ranked_result(self.name, candidates.values(), limit, filters)


class VectorRetriever:
    name = "vector"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root

    def retrieve(
        self,
        conn,
        query: RetrievalQuery,
        *,
        limit: int,
        filters: RetrievalFilters,
    ) -> RetrieverResult:
        diagnostics: dict[str, object] = {
            "enabled": False,
            "index_present": False,
            "stale": True,
            "query_embedded": False,
            "candidate_count": 0,
            "provider": None,
            "model": None,
            "dimension": None,
            "failure_stage": None,
        }
        if self.root is None:
            diagnostics["failure_stage"] = "no_root"
            return RetrieverResult(self.name, [], diagnostics=diagnostics)

        from . import embeddings

        config = embeddings.load_embedding_config(self.root)
        diagnostics.update(
            {
                "enabled": config.enabled,
                "provider": config.provider,
                "model": config.model,
                "dimension": config.dimension,
            }
        )
        if not config.enabled:
            diagnostics["failure_stage"] = "disabled"
            return RetrieverResult(self.name, [], diagnostics=diagnostics)

        status = vector_index_status(self.root)
        diagnostics.update(
            {
                "index_present": status.index_present,
                "stale": status.stale,
                "provider": status.provider or config.provider,
                "model": status.model or config.model,
                "dimension": status.dimension or config.dimension,
            }
        )
        if not status.index_present:
            diagnostics["failure_stage"] = "missing_index"
            return RetrieverResult(self.name, [], diagnostics=diagnostics)

        try:
            index = load_vector_index(self.root)
        except (OSError, ValueError) as exc:
            diagnostics["failure_stage"] = "index_load_failed"
            diagnostics["warnings"] = [f"Vector retrieval failed: {embeddings.sanitize_embedding_error(str(exc))}"]
            return RetrieverResult(self.name, [], diagnostics=diagnostics)

        try:
            provider = embeddings.create_embedding_provider(config, root=self.root)
            query_vectors = provider.embed_texts([query.original])
        except Exception as exc:
            diagnostics["failure_stage"] = "query_embedding_failed"
            diagnostics["warnings"] = [f"Vector retrieval failed: {embeddings.sanitize_embedding_error(str(exc))}"]
            return RetrieverResult(self.name, [], diagnostics=diagnostics)
        diagnostics["query_embedded"] = True
        if not query_vectors:
            diagnostics["failure_stage"] = "empty_query_vector"
            return RetrieverResult(self.name, [], diagnostics=diagnostics)
        query_vector = query_vectors[0]
        if len(query_vector) != index.manifest.dimension:
            diagnostics["failure_stage"] = "query_dimension_mismatch"
            diagnostics["warnings"] = [
                "Vector retrieval failed: query embedding dimension does not match the local index."
            ]
            return RetrieverResult(self.name, [], diagnostics=diagnostics)

        candidates: dict[str, RetrievalCandidate] = {}
        scored_chunks = []
        for chunk, vector in zip(index.chunks, index.vectors):
            score = cosine_similarity(query_vector, vector)
            if score <= 0:
                continue
            scored_chunks.append((score, chunk))
        scored_chunks.sort(key=lambda item: (-item[0], item[1].chunk_id))

        for score, chunk in scored_chunks[: max(limit * 8, 20)]:
            for candidate in candidates_for_vector_chunk(conn, chunk, score):
                remember_candidate(candidates, candidate)

        result = ranked_result(self.name, candidates.values(), limit, filters)
        diagnostics["candidate_count"] = len(result.candidates)
        return RetrieverResult(self.name, result.candidates, diagnostics=diagnostics)


class HybridRetriever:
    name = "hybrid"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root

    def retrieve(
        self,
        conn,
        query: RetrievalQuery,
        *,
        limit: int,
        filters: RetrievalFilters,
    ) -> RetrieverResult:
        base_results = [
            BM25ClaimRetriever().retrieve(conn, query, limit=limit, filters=filters),
            CatalogTitleAliasRetriever().retrieve(conn, query, limit=limit, filters=filters),
            ExactFormulaSymbolRetriever().retrieve(conn, query, limit=limit, filters=filters),
        ]
        vector_result = VectorRetriever(self.root).retrieve(conn, query, limit=limit, filters=filters)
        seeds = reciprocal_rank_fusion([*base_results, vector_result], rrf_k=60)
        graph_result = GraphRelationshipRetriever(seeds).retrieve(conn, query, limit=limit, filters=filters)
        all_results = [*base_results, vector_result, graph_result]
        fused = reciprocal_rank_fusion(all_results, rrf_k=60)
        returned = apply_filters(fused, filters)[:limit]
        diagnostics = retrieval_diagnostics(all_results, fused)
        warnings = unique(
            warning
            for result in all_results
            for warning in result.diagnostics.get("warnings", [])
        )
        if warnings:
            diagnostics["warnings"] = warnings
        return RetrieverResult(
            self.name,
            returned,
            diagnostics=diagnostics,
        )

    def diagnostics(self, results: list[RetrieverResult], fused: list[RetrievalCandidate]) -> dict[str, object]:
        return retrieval_diagnostics(results, fused)


def reciprocal_rank_fusion(results: list[RetrieverResult], rrf_k: int = 60) -> list[RetrievalCandidate]:
    by_claim: dict[str, RetrievalCandidate] = {}
    scores: dict[str, float] = {}
    for result in results:
        for rank, candidate in enumerate(result.candidates, start=1):
            scores[candidate.claim_id] = scores.get(candidate.claim_id, 0.0) + 1 / (rrf_k + rank)
            existing = by_claim.get(candidate.claim_id)
            if existing is None:
                by_claim[candidate.claim_id] = candidate
                continue
            by_claim[candidate.claim_id] = merge_candidates(existing, candidate)
    fused = [
        replace(candidate, raw_score=round(scores[claim_id], 6), retriever_rank=index + 1)
        for index, (claim_id, candidate) in enumerate(by_claim.items())
    ]
    fused.sort(key=lambda candidate: (-candidate.raw_score, candidate.claim_id))
    return [
        replace(candidate, retriever_rank=index)
        for index, candidate in enumerate(fused, start=1)
    ]


def retrieval_diagnostics(results: list[RetrieverResult], fused: list[RetrievalCandidate]) -> dict[str, object]:
    return {
        "retrievers": {
            result.name: {
                "candidate_count": len(result.candidates),
                "returned_count": len(result.candidates),
            }
            | result.diagnostics
            for result in results
        },
        "fusion": {
            "method": "rrf",
            "rrf_k": 60,
            "candidate_count_before_fusion": sum(len(result.candidates) for result in results),
            "candidate_count_after_fusion": len(fused),
        },
    }


def candidates_for_vector_chunk(conn, chunk, score: float) -> list[RetrievalCandidate]:
    candidates: list[RetrievalCandidate] = []
    if chunk.chunk_type == "claim":
        claim_id = str(chunk.metadata.get("claim_id", ""))
        row = conn.execute(
            """
            select claim_id, source_id, claim_text, citation_locator, confidence_status
            from claims
            where claim_id = ?
            """,
            (claim_id,),
        ).fetchone()
        if row is not None:
            candidates.append(
                candidate_from_claim_row(
                    conn,
                    row,
                    page_info=source_page_info(conn, str(row["source_id"])),
                    raw_score=round(score, 6),
                    retriever="vector",
                    reasons=["vector_semantic"],
                    matched_terms=[],
                )
            )
        return candidates

    source_ids: list[str] = []
    if chunk.chunk_type == "source_title":
        source_id = str(chunk.metadata.get("source_id", ""))
        if source_id:
            source_ids.append(source_id)
    elif chunk.chunk_type == "page_title":
        page = {
            "page_id": str(chunk.metadata.get("page_id", "")),
            "path": str(chunk.metadata.get("page_path", "")),
            "page_type": str(chunk.metadata.get("page_type", "")),
            "title": str(chunk.metadata.get("title", "")),
        }
        source_ids.extend(source_ids_for_page(conn, page))

    for source_id in unique(source_ids):
        for row in claim_rows_for_source(conn, source_id):
            candidates.append(
                candidate_from_claim_row(
                    conn,
                    row,
                    page_info=source_page_info(conn, str(row["source_id"])),
                    raw_score=round(score * 0.8, 6),
                    retriever="vector",
                    reasons=["vector_semantic", f"vector_chunk:{chunk.chunk_type}"],
                    matched_terms=[],
                )
            )
    return candidates


def searchable_terms(query: RetrievalQuery) -> list[str]:
    return unique([*query.text_terms, *query.expanded_terms, *query.catalog_terms, *query.formula_spans])


def catalog_page_matches(conn, query: RetrievalQuery) -> list[tuple[dict[str, str], str]]:
    matches: list[tuple[dict[str, str], str]] = []
    seen: set[tuple[str, str]] = set()
    terms = unique([*query.catalog_terms, *query.text_terms])
    for term in terms:
        normalized = term.casefold()
        rows = conn.execute(
            """
            select p.page_id, p.path, p.page_type, p.title, a.alias, a.normalized_alias
            from aliases a
            join pages p on p.page_id = a.target_id
            where a.normalized_alias = ?
            order by p.page_type, p.title
            """,
            (normalized,),
        ).fetchall()
        for row in rows:
            key = (str(row["page_id"]), f"alias_exact:{term}")
            if key in seen:
                continue
            seen.add(key)
            matches.append((page_dict(row), f"alias_exact:{term}"))
        rows = conn.execute(
            """
            select page_id, path, page_type, title
            from pages
            where lower(title) like ? escape '\\'
            order by page_type, title
            """,
            (like_pattern(term),),
        ).fetchall()
        for row in rows:
            key = (str(row["page_id"]), f"title_match:{term}")
            if key in seen:
                continue
            seen.add(key)
            matches.append((page_dict(row), f"title_match:{term}"))
    return matches


def source_ids_for_page(conn, page: dict[str, str]) -> list[str]:
    page_id = page["page_id"]
    if page["page_type"] == "source":
        return [page_id]
    source_ids = {page_id} if page_id.startswith("src_") else set()
    for row in conn.execute(
        """
        select from_page, to_page from links
        where from_page = ? or to_page = ?
        """,
        (page_id, page_id),
    ).fetchall():
        for value in (str(row["from_page"]), str(row["to_page"])):
            if value.startswith("src_"):
                source_ids.add(value)
    for row in conn.execute(
        """
        select subject_id, object_id, source_id from relationships
        where subject_id = ? or object_id = ? or source_id = ?
        """,
        (page_id, page_id, page_id),
    ).fetchall():
        for value in (str(row["subject_id"]), str(row["object_id"]), str(row["source_id"])):
            if value.startswith("src_"):
                source_ids.add(value)
    return sorted(source_ids)


def claim_rows_for_source(conn, source_id: str):
    return conn.execute(
        """
        select claim_id, source_id, claim_text, citation_locator, confidence_status
        from claims
        where source_id = ?
        order by created_at, claim_id
        """,
        (source_id,),
    ).fetchall()


def candidate_from_claim_row(
    conn,
    row,
    *,
    page_info: dict[str, str],
    raw_score: float,
    retriever: str,
    reasons: list[str],
    matched_terms: list[str],
) -> RetrievalCandidate:
    return RetrievalCandidate(
        claim_id=str(row["claim_id"]),
        source_id=str(row["source_id"]),
        claim_text=str(row["claim_text"]),
        citation_locator=str(row["citation_locator"] or ""),
        confidence_status=str(row["confidence_status"]),
        page_id=page_info["page_id"],
        page_path=page_info["path"],
        page_type=page_info["page_type"],
        raw_score=raw_score,
        retriever_rank=0,
        retrievers=[retriever],
        reasons=unique(reasons),
        matched_terms=unique(matched_terms),
    )


def source_page_info(conn, source_id: str) -> dict[str, str]:
    row = conn.execute(
        "select page_id, path, page_type, title from pages where page_id = ?",
        (source_id,),
    ).fetchone()
    if row is not None:
        return page_dict(row)
    return {
        "page_id": source_id,
        "path": f"wiki/sources/{source_id}.md",
        "page_type": "source",
        "title": source_id,
    }


def page_dict(row) -> dict[str, str]:
    return {
        "page_id": str(row["page_id"]),
        "path": str(row["path"]),
        "page_type": str(row["page_type"]),
        "title": str(row["title"]),
    }


def ranked_result(
    name: str,
    candidates: list[RetrievalCandidate] | tuple[RetrievalCandidate, ...] | object,
    limit: int,
    filters: RetrievalFilters,
) -> RetrieverResult:
    rows = apply_filters(list(candidates), filters)
    rows.sort(key=lambda candidate: (-candidate.raw_score, candidate.claim_id))
    rows = [replace(candidate, retriever_rank=index) for index, candidate in enumerate(rows, start=1)]
    return RetrieverResult(name, rows[:limit])


def apply_filters(candidates: list[RetrievalCandidate], filters: RetrievalFilters) -> list[RetrievalCandidate]:
    return [candidate for candidate in candidates if matches_filters(candidate, filters)]


def matches_filters(candidate: RetrievalCandidate, filters: RetrievalFilters) -> bool:
    if filters.source_id and candidate.source_id != filters.source_id:
        return False
    if filters.page_type and candidate.page_type != filters.page_type:
        return False
    if filters.confidence and candidate.confidence_status != filters.confidence:
        return False
    return True


def remember_candidate(candidates: dict[str, RetrievalCandidate], candidate: RetrievalCandidate) -> None:
    existing = candidates.get(candidate.claim_id)
    if existing is None or candidate.raw_score > existing.raw_score:
        candidates[candidate.claim_id] = candidate
    elif existing is not None:
        candidates[candidate.claim_id] = merge_candidates(existing, candidate)


def merge_candidates(left: RetrievalCandidate, right: RetrievalCandidate) -> RetrievalCandidate:
    chosen = left if left.raw_score >= right.raw_score else right
    return replace(
        chosen,
        raw_score=max(left.raw_score, right.raw_score),
        retrievers=unique([*left.retrievers, *right.retrievers]),
        reasons=unique([*left.reasons, *right.reasons]),
        matched_terms=unique([*(left.matched_terms or []), *(right.matched_terms or [])]),
    )


def row_search_text(row) -> str:
    return f"{row['claim_text']} {row['citation_locator'] or ''}"


def relevance_score(base_score: float, claim_terms: list[str], query: RetrievalQuery) -> float:
    if not claim_terms:
        return base_score
    catalog_terms = set(query.catalog_terms)
    text_terms = set(query.text_terms)
    expanded_terms = set(query.expanded_terms)
    exact_terms = set([*query.formula_spans, *query.symbol_spans])
    score = base_score
    for term in unique(claim_terms):
        if term in expanded_terms:
            score += 0.25
        elif term in text_terms and term not in catalog_terms:
            score += 0.2
        elif term in exact_terms:
            score += 0.2
        elif term in catalog_terms:
            score += 0.05
        elif len(term) >= 2:
            score += 0.03
    return round(min(score, base_score + 1.0), 6)


def matched_terms(text: str, terms: list[str]) -> list[str]:
    folded = text.casefold()
    return [term for term in terms if term.casefold() in folded]


def fts_safe(term: str) -> bool:
    return bool(re.fullmatch(r"[\w\u3400-\u9fff]+", term, flags=re.UNICODE))


def quote_fts_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def like_pattern(term: str) -> str:
    escaped = term.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def unique(items) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
