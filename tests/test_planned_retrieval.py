from __future__ import annotations

from pathlib import Path

from llmwiki.answer import AskOptions
from llmwiki.planned_retrieval import execute_query_plan
from llmwiki.planner import QueryPlan, QuerySubquery, RequiredEvidence
from tests.test_hybrid_retrieval import setup_seeded_workspace


def make_plan(*subqueries: QuerySubquery) -> QueryPlan:
    return QueryPlan(
        schema_version="query_plan.v2.5",
        intent="compare",
        question_summary="比较水果证据。",
        entities=[{"text": "草莓", "role": "candidate_subject", "catalog_refs": ["concept:草莓"], "claim_id": "clm_fake"}],
        concepts=[{"text": "维生素 C", "role": "attribute", "catalog_refs": []}],
        subqueries=list(subqueries),
        required_evidence=[RequiredEvidence(description="per fruit evidence", coverage="per_entity")],
        uncertainties=[],
        warnings=["planner warning"],
    )


def test_execute_query_plan_runs_each_subquery_through_local_retrieve():
    root = setup_seeded_workspace()
    plan = make_plan(
        QuerySubquery(query="草莓 保存", purpose="strawberry storage", filters={"confidence": "cited"}),
        QuerySubquery(query="橙子 维生素 C", purpose="orange vitamin c", filters={"confidence": "cited"}),
    )

    result = execute_query_plan(root, plan, AskOptions(limit=3))

    assert result.contexts
    assert result.diagnostics["schema_version"] == "planned_retrieval.v2.5"
    assert [item["query"] for item in result.diagnostics["subqueries"]] == ["草莓 保存", "橙子 维生素 C"]
    assert any(context["source_id"] == "src_99ab0495789d" for context in result.contexts)
    assert any(context["source_id"] == "src_880c9f8a447c" for context in result.contexts)
    assert "planner warning" in result.warnings


def test_execute_query_plan_deduplicates_contexts_by_claim_id(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_retrieve_context(root: Path, question: str, **kwargs):
        calls.append({"question": question, **kwargs})
        return {
            "contexts": [
                {
                    "rank": 1,
                    "claim_id": "clm_same",
                    "source_id": "src_same",
                    "citation_locator": "line:1",
                    "claim_text": "same evidence",
                    "page_path": "wiki/sources/src_same.md",
                    "page_type": "source",
                    "relationship_type": "supports",
                    "confidence_status": "cited",
                    "score": 1.0,
                    "retrieval_reasons": [f"from:{question}"],
                }
            ],
            "relationships": [],
            "warnings": [],
            "diagnostics": {"returned_count": 1},
        }

    monkeypatch.setattr("llmwiki.planned_retrieval.retrieve_context", fake_retrieve_context)
    root = setup_seeded_workspace()
    plan = make_plan(QuerySubquery(query="one"), QuerySubquery(query="two"))

    result = execute_query_plan(root, plan, AskOptions(limit=5))

    assert [call["question"] for call in calls] == ["one", "two"]
    assert len(result.contexts) == 1
    assert result.contexts[0]["claim_id"] == "clm_same"
    assert result.contexts[0]["retrieval_reasons"] == ["from:one", "from:two"]


def test_execute_query_plan_passes_subquery_filters(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_retrieve_context(root: Path, question: str, **kwargs):
        calls.append({"question": question, **kwargs})
        return {"contexts": [], "relationships": [], "warnings": [], "diagnostics": {"returned_count": 0}}

    monkeypatch.setattr("llmwiki.planned_retrieval.retrieve_context", fake_retrieve_context)
    root = setup_seeded_workspace()
    plan = make_plan(
        QuerySubquery(
            query="橙子 维生素 C",
            filters={"source_id": "src_880c9f8a447c", "page_type": "concept", "confidence": "cited"},
        )
    )

    result = execute_query_plan(root, plan, AskOptions(limit=4, source_id="src_global", confidence="weak"))

    assert calls == [
        {
            "question": "橙子 维生素 C",
            "limit": 4,
            "source_id": "src_880c9f8a447c",
            "page_type": "concept",
            "confidence": "cited",
        }
    ]
    assert result.contexts == []
    assert result.diagnostics["subqueries"][0]["context_count"] == 0


def test_execute_query_plan_does_not_copy_planner_forged_evidence_fields():
    root = setup_seeded_workspace()
    plan = make_plan(QuerySubquery(query="草莓 保存", filters={"confidence": "cited"}))

    result = execute_query_plan(root, plan, AskOptions(limit=2))

    assert result.contexts
    serialized_contexts = str(result.contexts)
    assert "clm_fake" not in serialized_contexts
    assert all("claim_id" in context for context in result.contexts)
    assert all(str(context["claim_id"]).startswith("clm_") for context in result.contexts)


def test_execute_query_plan_no_evidence_returns_empty_contexts_and_diagnostics(monkeypatch):
    def fake_retrieve_context(root: Path, question: str, **kwargs):
        return {
            "contexts": [],
            "relationships": [],
            "warnings": ["No matching claims found."],
            "diagnostics": {"failure_stage": "candidate_miss", "returned_count": 0},
        }

    monkeypatch.setattr("llmwiki.planned_retrieval.retrieve_context", fake_retrieve_context)
    root = setup_seeded_workspace()
    plan = make_plan(QuerySubquery(query="not found"))

    result = execute_query_plan(root, plan, AskOptions(limit=5))

    assert result.contexts == []
    assert result.warnings == ["planner warning", "No matching claims found."]
    assert result.diagnostics["returned_count"] == 0
    assert result.diagnostics["subqueries"][0]["diagnostics"]["failure_stage"] == "candidate_miss"
