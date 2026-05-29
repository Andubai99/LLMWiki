from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .db import catalog_path, connect
from .query_analysis import analyze_query
from .retrievers import HybridRetriever, RetrievalCandidate, RetrievalFilters


RELATIONSHIP_PRIORITY = ("contradicts", "supports", "refines", "contains", "similar_to")


def retrieve_context(
    root: Path,
    question: str,
    limit: int = 8,
    source_id: str | None = None,
    page_type: str | None = None,
    confidence: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    limit = max(0, limit)
    result: dict[str, Any] = {
        "schema_version": "retrieval.v2.6",
        "question": question,
        "contexts": [],
        "relationships": [],
        "warnings": [],
        "diagnostics": {
            "query_terms": [],
            "candidate_count": 0,
            "returned_count": 0,
            "failure_stage": None,
        },
    }
    if limit == 0:
        result["warnings"].append("Limit is 0; no contexts returned.")
        return result
    with connect(catalog_path(root)) as conn:
        query = analyze_query(question, catalog_terms=load_catalog_terms(conn))
        query_terms = query.all_terms()
        result["diagnostics"]["query_terms"] = query_terms
        result["diagnostics"]["query_features"] = query.diagnostics()
        if not query_terms:
            result["warnings"].append("Question produced no searchable terms.")
            result["diagnostics"]["failure_stage"] = "no_terms"
            return result

        hybrid_result = HybridRetriever(root=root).retrieve(
            conn,
            query,
            limit=max(limit * 4, limit),
            filters=RetrievalFilters(source_id=source_id, page_type=page_type, confidence=confidence),
        )
        result["diagnostics"].update(hybrid_result.diagnostics)
        for warning in hybrid_result.diagnostics.get("warnings", []):
            add_warning(result, str(warning))
        candidate_rows = hybrid_result.candidates
        result["diagnostics"]["candidate_count"] = int(
            result["diagnostics"].get("fusion", {}).get("candidate_count_after_fusion", len(candidate_rows))
        )
        relationships_by_key: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
        contexts: list[dict[str, Any]] = []
        for row in candidate_rows:
            claim_id = row.claim_id
            row_source_id = row.source_id
            relationships = load_relationships(conn, claim_id, row_source_id)

            relationship_type = best_relationship_type(relationships, claim_id)
            context = context_from_candidate(row, len(contexts) + 1, relationship_type)
            contexts.append(context)

            for relationship in relationships:
                if should_include_relationship(relationship, claim_id, row_source_id):
                    key = (
                        str(relationship["subject_id"]),
                        str(relationship["object_id"]),
                        str(relationship["relationship_type"]),
                        str(relationship["evidence_claim_id"]),
                        str(relationship["source_id"]),
                    )
                    relationships_by_key[key] = dict(relationship)

            if not context["citation_locator"] or row.confidence_status in {"weak", "uncited"}:
                add_warning(
                    result,
                    "Retrieved weak/uncited evidence; do not treat it as strong evidence.",
                )

            if relationship_type == "contradicts":
                add_warning(
                    result,
                    "Contradictory evidence is present; expose the conflict instead of resolving it silently.",
                )

            if len(contexts) >= limit:
                break

    result["contexts"] = contexts
    result["diagnostics"]["returned_count"] = len(contexts)
    result["relationships"] = sorted(
        relationships_by_key.values(),
        key=lambda item: (
            str(item["relationship_type"]),
            str(item["subject_id"]),
            str(item["object_id"]),
            str(item["evidence_claim_id"]),
        ),
    )
    if not contexts:
        result["warnings"].append("No matching claims found.")
        if result["diagnostics"]["candidate_count"] == 0:
            result["diagnostics"]["failure_stage"] = "candidate_miss"
        else:
            result["diagnostics"]["failure_stage"] = "ranking_miss"
    elif any(item["relationship_type"] == "contradicts" for item in result["relationships"]):
        add_warning(
            result,
            "Contradictory evidence is present; expose the conflict instead of resolving it silently.",
        )
    return result


def load_catalog_terms(conn) -> list[str]:
    terms: list[str] = []
    for row in conn.execute("select title from pages").fetchall():
        terms.append(str(row["title"]))
    for row in conn.execute("select alias, normalized_alias from aliases").fetchall():
        terms.append(str(row["alias"]))
        terms.append(str(row["normalized_alias"]))
    for row in conn.execute("select title from sources").fetchall():
        terms.append(str(row["title"]))
    return list(dict.fromkeys(term for term in terms if term.strip()))


def context_from_candidate(
    candidate: RetrievalCandidate,
    rank: int,
    relationship_type: str,
) -> dict[str, Any]:
    return {
        "rank": rank,
        "claim_id": candidate.claim_id,
        "source_id": candidate.source_id,
        "citation_locator": candidate.citation_locator,
        "claim_text": candidate.claim_text,
        "page_path": candidate.page_path,
        "page_type": candidate.page_type,
        "relationship_type": relationship_type,
        "confidence_status": candidate.confidence_status,
        "score": float(candidate.raw_score),
        "retrieval_reasons": candidate.reasons,
    }


def candidate_claims(
    conn,
    terms: list[str],
    scoring_terms: list[str],
    source_id: str | None,
    confidence: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    fetch_limit = max(limit * 8, 20)
    ascii_terms = [term for term in terms if re.fullmatch(r"[a-z0-9_]{2,}", term)]
    if ascii_terms:
        fts_query = " OR ".join(ascii_terms)
        try:
            rows = conn.execute(
                """
                select
                    c.claim_id,
                    c.source_id,
                    c.claim_text,
                    c.citation_locator,
                    c.confidence_status,
                    bm25(claims_fts) as rank
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
            score = 0.45 + lexical_score(str(row["claim_text"]), scoring_terms)
            remember_candidate(candidates, row, score)

    if terms:
        clauses = " or ".join("lower(claim_text) like ? escape '\\'" for _ in terms)
        params = [like_pattern(term) for term in terms]
        rows = conn.execute(
            f"""
            select claim_id, source_id, claim_text, citation_locator, confidence_status
            from claims
            where {clauses}
            order by created_at
            limit ?
            """,
            (*params, fetch_limit),
        ).fetchall()
        for row in rows:
            score = 0.2 + lexical_score(str(row["claim_text"]), scoring_terms)
            remember_candidate(candidates, row, score)

    rows = [row for row in candidates.values() if matches_filters(row, source_id, confidence)]
    rows.sort(key=lambda row: (-float(row["score"]), str(row["claim_id"])))
    return rows


def remember_candidate(candidates: dict[str, dict[str, Any]], row, score: float) -> None:
    claim_id = str(row["claim_id"])
    current = candidates.get(claim_id)
    candidate = {
        "claim_id": claim_id,
        "source_id": str(row["source_id"]),
        "claim_text": str(row["claim_text"]),
        "citation_locator": str(row["citation_locator"] or ""),
        "confidence_status": str(row["confidence_status"]),
        "score": round(min(1.0, max(score, 0.0)), 4),
    }
    if current is None or candidate["score"] > current["score"]:
        candidates[claim_id] = candidate


def matches_filters(row: dict[str, Any], source_id: str | None, confidence: str | None) -> bool:
    if source_id and row["source_id"] != source_id:
        return False
    if confidence and row["confidence_status"] != confidence:
        return False
    return True


def expanded_terms(question: str) -> list[str]:
    terms = base_terms(question)
    folded = question.casefold()
    if "rag" in terms or "retrieval augmented generation" in folded:
        terms.extend(["rag", "retrieval", "augmented", "generation", "retrieval augmented generation"])
    if "retrievalaugmentedgeneration" in "".join(terms):
        terms.extend(["rag", "retrieval", "augmented", "generation"])
    return list(dict.fromkeys(term for term in terms if term.strip()))


def base_terms(question: str) -> list[str]:
    folded = question.casefold()
    terms = re.findall(r"[a-z0-9_]{2,}", folded)
    terms.extend(re.findall(r"[\u3400-\u9fff]{2,}", folded))
    return list(dict.fromkeys(term for term in terms if term.strip()))


def lexical_score(text: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    folded = text.casefold()
    hits = 0
    for term in terms:
        if term.casefold() in folded:
            hits += 1
    return min(0.55, hits / max(len(terms), 1))


def like_pattern(term: str) -> str:
    escaped = term.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def load_relationships(conn, claim_id: str, source_id: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        select subject_id, object_id, relationship_type, evidence_claim_id, source_id
        from relationships
        where evidence_claim_id = ? or source_id = ?
        """,
        (claim_id, source_id),
    ).fetchall()
    return [dict(row) for row in rows]


def best_relationship_type(relationships: list[dict[str, str]], claim_id: str) -> str:
    exact = [row for row in relationships if row.get("evidence_claim_id") == claim_id]
    rows = exact or relationships
    for relationship_type in RELATIONSHIP_PRIORITY:
        if any(row.get("relationship_type") == relationship_type for row in rows):
            return relationship_type
    return "supports"


def should_include_relationship(
    relationship: dict[str, str],
    claim_id: str,
    source_id: str,
) -> bool:
    return (
        relationship.get("evidence_claim_id") == claim_id
        or relationship.get("relationship_type") == "contradicts"
        or relationship.get("source_id") == source_id
    )


def select_page_path(
    conn,
    relationships: list[dict[str, str]],
    source_id: str,
    page_type: str | None,
) -> str | None:
    page_info = select_page_info(conn, relationships, source_id, page_type)
    return str(page_info["path"]) if page_info else None


def select_page_info(
    conn,
    relationships: list[dict[str, str]],
    source_id: str,
    page_type: str | None,
) -> dict[str, str] | None:
    page_ids = {source_id}
    for relationship in relationships:
        page_ids.add(str(relationship["subject_id"]))
        page_ids.add(str(relationship["object_id"]))
    placeholders = ", ".join("?" for _ in page_ids)
    if not placeholders:
        return None
    rows = conn.execute(
        f"""
        select page_id, path, page_type
        from pages
        where page_id in ({placeholders})
        order by case page_type
            when 'source' then 0
            when 'concept' then 1
            when 'entity' then 2
            when 'synthesis' then 3
            else 4
        end, path
        """,
        tuple(page_ids),
    ).fetchall()
    pages = [dict(row) for row in rows]
    if page_type:
        for page in pages:
            if page["page_type"] == page_type:
                return page
        return None
    for page in pages:
        if page["page_type"] == "source":
            return page
    return pages[0] if pages else None


def add_warning(result: dict[str, Any], warning: str) -> None:
    if warning not in result["warnings"]:
        result["warnings"].append(warning)


def format_retrieval_prompt(result: dict[str, Any]) -> str:
    lines = [
        "Question:",
        str(result["question"]),
        "",
        "Evidence:",
    ]
    contexts = result.get("contexts", [])
    if contexts:
        for index, context in enumerate(contexts, start=1):
            lines.extend(
                [
                    f"{index}. claim_id: {context['claim_id']}",
                    f"   source_id: {context['source_id']}",
                    f"   citation_locator: {context['citation_locator']}",
                    f"   page_path: {context['page_path']}",
                    f"   relationship_type: {context['relationship_type']}",
                    f"   score: {context['score']}",
                    f"   claim: {context['claim_text']}",
                ]
            )
    else:
        lines.append("- No matching claims found.")

    lines.extend(["", "Relationships:"])
    relationships = result.get("relationships", [])
    if relationships:
        for relationship in relationships:
            lines.append(
                "- "
                f"{relationship['relationship_type']}: "
                f"{relationship['subject_id']} -> {relationship['object_id']} "
                f"(evidence_claim_id={relationship['evidence_claim_id']}, "
                f"source_id={relationship['source_id']})"
            )
    else:
        lines.append("- No relationships returned.")

    lines.extend(["", "Warnings:"])
    warnings = result.get("warnings", [])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "Answer constraints:",
            "- Only answer from the evidence above.",
            "- Key conclusions must cite source_id + citation_locator.",
            "- If evidence is insufficient, say insufficient evidence.",
            "- If contradicts relationships are present, expose the conflict and do not silently choose a winner.",
            "- Do not fabricate sources, locators, claim_ids, pages, or relationships.",
            "- weak/uncited claims are not strong evidence.",
        ]
    )
    return "\n".join(lines)
