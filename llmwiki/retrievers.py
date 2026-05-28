from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Protocol

from .query_analysis import RetrievalQuery


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
                candidate = candidate_from_claim_row(
                    conn,
                    row,
                    page_info=source_page_info(conn, str(row["source_id"])),
                    raw_score=1.0,
                    retriever=self.name,
                    reasons=["bm25_fts"],
                    matched_terms=matched_terms(str(row["claim_text"]), terms),
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
                candidate = candidate_from_claim_row(
                    conn,
                    row,
                    page_info=source_page_info(conn, str(row["source_id"])),
                    raw_score=0.5,
                    retriever=self.name,
                    reasons=["like_match"],
                    matched_terms=matched_terms(str(row["claim_text"]), like_terms),
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
                    candidate = candidate_from_claim_row(
                        conn,
                        row,
                        page_info=page,
                        raw_score=1.0 if reason.startswith("alias_exact") else 0.8,
                        retriever=self.name,
                        reasons=[reason, "page_source_claims"],
                        matched_terms=query.catalog_terms or query.text_terms,
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
                left join pages p on p.page_id = c.source_id or p.page_id in (
                    select target_id from aliases where target_id = p.page_id
                )
                left join aliases a on a.target_id = p.page_id
                where lower(c.claim_text) like ? escape '\\'
                   or lower(c.citation_locator) like ? escape '\\'
                   or lower(coalesce(s.title, '')) like ? escape '\\'
                   or lower(coalesce(p.title, '')) like ? escape '\\'
                   or lower(coalesce(a.alias, '')) like ? escape '\\'
                order by c.created_at, c.claim_id
                limit ?
                """,
                (*(like_pattern(span) for _ in range(5)), max(limit * 4, 20)),
            ).fetchall()
            for row in rows:
                candidate = candidate_from_claim_row(
                    conn,
                    row,
                    page_info=source_page_info(conn, str(row["source_id"])),
                    raw_score=1.0,
                    retriever=self.name,
                    reasons=[f"exact_span:{span}"],
                    matched_terms=[span],
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


class HybridRetriever:
    name = "hybrid"

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
        seeds = reciprocal_rank_fusion(base_results, rrf_k=60)
        graph_result = GraphRelationshipRetriever(seeds).retrieve(conn, query, limit=limit, filters=filters)
        all_results = [*base_results, graph_result]
        fused = reciprocal_rank_fusion(all_results, rrf_k=60)
        return RetrieverResult(self.name, apply_filters(fused, filters)[:limit])

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
            for result in results
        },
        "fusion": {
            "method": "rrf",
            "rrf_k": 60,
            "candidate_count_before_fusion": sum(len(result.candidates) for result in results),
            "candidate_count_after_fusion": len(fused),
        },
    }


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
