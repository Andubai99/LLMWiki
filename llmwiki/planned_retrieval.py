from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .planner import QueryPlan
from .retrieval import retrieve_context


PLANNED_RETRIEVAL_SCHEMA_VERSION = "planned_retrieval.v2.5"


@dataclass(frozen=True)
class PlannedRetrievalResult:
    contexts: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    warnings: list[str]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_retrieval_dict(self, question: str) -> dict[str, Any]:
        return {
            "schema_version": "retrieval.v2.7",
            "question": question,
            "contexts": self.contexts,
            "relationships": self.relationships,
            "warnings": self.warnings,
            "diagnostics": self.diagnostics,
        }


def execute_query_plan(root: Path, plan: QueryPlan, ask_options: Any) -> PlannedRetrievalResult:
    per_subquery: list[dict[str, Any]] = []
    retrievals: list[dict[str, Any]] = []
    for index, subquery in enumerate(plan.subqueries, start=1):
        filters = merged_filters(subquery.filters, ask_options)
        retrieval = retrieve_context(
            root,
            subquery.query,
            limit=int(getattr(ask_options, "limit", 8)),
            source_id=filters["source_id"],
            page_type=filters["page_type"],
            confidence=filters["confidence"],
        )
        retrievals.append(retrieval)
        retrieval["contexts"] = tag_subquery_contexts(
            list(retrieval.get("contexts", [])),
            index=index,
            query=subquery.query,
            purpose=subquery.purpose,
        )
        per_subquery.append(
            {
                "index": index,
                "query": subquery.query,
                "purpose": subquery.purpose,
                "filters": filters,
                "context_count": len(retrieval.get("contexts", [])),
                "diagnostics": retrieval.get("diagnostics", {}),
            }
        )

    max_contexts = max_context_budget(plan, ask_options)
    contexts = merge_planned_contexts(
        [list(retrieval.get("contexts", [])) for retrieval in retrievals],
        max_contexts=max_contexts,
    )
    relationships = merge_relationships(
        [list(retrieval.get("relationships", [])) for retrieval in retrievals]
    )
    warnings = unique([*plan.warnings, *[str(w) for retrieval in retrievals for w in retrieval.get("warnings", [])]])
    diagnostics = {
        "schema_version": PLANNED_RETRIEVAL_SCHEMA_VERSION,
        "subquery_count": len(plan.subqueries),
        "returned_count": len(contexts),
        "relationship_count": len(relationships),
        "subqueries": per_subquery,
    }
    return PlannedRetrievalResult(
        contexts=contexts,
        relationships=relationships,
        warnings=warnings,
        diagnostics=diagnostics,
    )


def merge_planned_contexts(
    context_groups: list[list[dict[str, Any]]],
    *,
    max_contexts: int,
) -> list[dict[str, Any]]:
    by_claim: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for context in round_robin_contexts(context_groups):
        claim_id = str(context.get("claim_id") or "")
        if not claim_id:
            continue
        if claim_id not in by_claim:
            by_claim[claim_id] = dict(context)
            order.append(claim_id)
            continue
        existing = by_claim[claim_id]
        existing["retrieval_reasons"] = unique(
            [
                *list(existing.get("retrieval_reasons", [])),
                *list(context.get("retrieval_reasons", [])),
            ]
        )
        existing["subquery_queries"] = unique(
            [
                *list(existing.get("subquery_queries", [])),
                str(context.get("subquery_query") or ""),
            ]
        )
        existing["subquery_indexes"] = unique(
            [
                *[str(value) for value in existing.get("subquery_indexes", [])],
                str(context.get("subquery_index") or ""),
            ]
        )
        existing["subquery_purposes"] = unique(
            [
                *list(existing.get("subquery_purposes", [])),
                str(context.get("subquery_purpose") or ""),
            ]
        )
        if float(context.get("score") or 0.0) > float(existing.get("score") or 0.0):
            existing["score"] = context.get("score")
    merged = [by_claim[claim_id] for claim_id in order[:max_contexts]]
    for rank, context in enumerate(merged, start=1):
        context["rank"] = rank
    return merged


def tag_subquery_contexts(
    contexts: list[dict[str, Any]],
    *,
    index: int,
    query: str,
    purpose: str,
) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for context in contexts:
        item = dict(context)
        item["subquery_index"] = index
        item["subquery_query"] = query
        item["subquery_purpose"] = purpose
        item["subquery_queries"] = [query]
        item["subquery_indexes"] = [index]
        item["subquery_purposes"] = [purpose] if purpose else []
        tagged.append(item)
    return tagged


def round_robin_contexts(context_groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    max_len = max((len(group) for group in context_groups), default=0)
    for offset in range(max_len):
        for group in context_groups:
            if offset < len(group):
                result.append(group[offset])
    return result


def merge_relationships(relationship_groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    result: list[dict[str, Any]] = []
    for group in relationship_groups:
        for relationship in group:
            item = dict(relationship)
            key = tuple(sorted((str(k), str(v)) for k, v in item.items()))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def merged_filters(filters: dict[str, str | None], ask_options: Any) -> dict[str, str | None]:
    return {
        "source_id": filters.get("source_id") or getattr(ask_options, "source_id", None),
        "page_type": filters.get("page_type") or getattr(ask_options, "page_type", None),
        "confidence": filters.get("confidence") or getattr(ask_options, "confidence", None),
    }


def max_context_budget(plan: QueryPlan, ask_options: Any) -> int:
    limit = int(getattr(ask_options, "limit", 8))
    return min(max(limit, limit * max(len(plan.subqueries), 1)), 32)


def unique(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item)
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
