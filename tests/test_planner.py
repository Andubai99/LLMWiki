from __future__ import annotations

import json

from llmwiki.planner import PlanningOptions, plan_question
from tests.test_hybrid_retrieval import setup_seeded_workspace


class FakePlannerProvider:
    def __init__(self, responses: list[str], calls: list[list[dict[str, str]]]) -> None:
        self.responses = responses
        self.calls = calls

    def complete(self, messages: list[dict[str, str]], schema=None) -> dict[str, object]:
        self.calls.append(messages)
        content = self.responses.pop(0)
        return {
            "provider": "openai",
            "model": "deepseek-v4-pro",
            "content": content,
            "finish_reason": "stop",
            "usage": {"total_tokens": 12},
        }


def patch_planner_provider(monkeypatch, *payloads: dict[str, object] | str) -> list[list[dict[str, str]]]:
    calls: list[list[dict[str, str]]] = []
    responses = [payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False) for payload in payloads]

    def fake_create_provider(config, root=None):
        return FakePlannerProvider(responses, calls)

    monkeypatch.setattr("llmwiki.planner.create_provider", fake_create_provider)
    return calls


def valid_plan_payload() -> dict[str, object]:
    return {
        "schema_version": "query_plan.v2.5",
        "intent": "compare",
        "question_summary": "Compare fruit vitamin C evidence.",
        "entities": [
            {
                "text": "strawberry",
                "role": "candidate_subject",
                "catalog_refs": [],
            }
        ],
        "concepts": [
            {
                "text": "vitamin C",
                "role": "attribute",
                "catalog_refs": [],
            }
        ],
        "subqueries": [
            {
                "query": "strawberry vitamin C",
                "purpose": "find strawberry vitamin C evidence",
                "filters": {"source_id": None, "page_type": None, "confidence": "cited"},
                "required": True,
            },
            {
                "query": "orange vitamin C",
                "purpose": "find orange vitamin C evidence",
                "filters": {"source_id": "src_880c9f8a447c", "page_type": None, "confidence": "cited"},
                "required": True,
            },
        ],
        "required_evidence": [
            {
                "description": "Evidence about vitamin C for each candidate fruit when available.",
                "coverage": "per_entity",
            }
        ],
        "uncertainties": [],
        "warnings": [],
    }


def test_plan_question_parses_valid_query_plan(monkeypatch):
    root = setup_seeded_workspace()
    calls = patch_planner_provider(monkeypatch, valid_plan_payload())

    result = plan_question(root, "Which fruit is best for vitamin C?", PlanningOptions(limit=5))

    assert result.status == "planned"
    assert result.plan is not None
    assert result.plan.schema_version == "query_plan.v2.5"
    assert result.plan.intent == "compare"
    assert [subquery.query for subquery in result.plan.subqueries] == [
        "strawberry vitamin C",
        "orange vitamin C",
    ]
    assert result.plan.subqueries[1].filters["source_id"] == "src_880c9f8a447c"
    assert calls
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "config/api-keys.toml" not in serialized
    assert "sk-test-secret-should-not-print" not in serialized


def test_plan_question_repairs_malformed_json_once(monkeypatch):
    root = setup_seeded_workspace()
    calls = patch_planner_provider(monkeypatch, "not json", valid_plan_payload())

    result = plan_question(root, "Which fruit is best for vitamin C?", PlanningOptions())

    assert result.status == "planned"
    assert result.plan is not None
    assert len(calls) == 2
    assert "Return valid JSON only" in calls[1][-1]["content"]


def test_plan_question_repairs_invalid_schema_once(monkeypatch):
    root = setup_seeded_workspace()
    invalid_payload = valid_plan_payload()
    invalid_payload["subqueries"] = ["strawberry vitamin C"]
    calls = patch_planner_provider(monkeypatch, invalid_payload, valid_plan_payload())

    result = plan_question(root, "Which fruit is best for vitamin C?", PlanningOptions())

    assert result.status == "planned"
    assert result.plan is not None
    assert len(calls) == 2
    assert "failed validation" in calls[1][-1]["content"]


def test_plan_question_repairs_invalid_confidence_filter_once(monkeypatch):
    root = setup_seeded_workspace()
    invalid_payload = valid_plan_payload()
    invalid_payload["subqueries"][0]["filters"]["confidence"] = "high"  # type: ignore[index]
    calls = patch_planner_provider(monkeypatch, invalid_payload, valid_plan_payload())

    result = plan_question(root, "Which fruit is best for vitamin C?", PlanningOptions())

    assert result.status == "planned"
    assert result.plan is not None
    assert len(calls) == 2
    repair_prompt = calls[1][-1]["content"]
    assert "Invalid confidence in planner filters: high" in repair_prompt
    assert "null" in repair_prompt
    assert "cited" in repair_prompt
    assert "weak" in repair_prompt
    assert result.plan.subqueries[0].filters["confidence"] == "cited"


def test_plan_question_returns_invalid_when_confidence_filter_repair_fails(monkeypatch):
    root = setup_seeded_workspace()
    invalid_payload = valid_plan_payload()
    invalid_payload["subqueries"][0]["filters"]["confidence"] = "high"  # type: ignore[index]
    still_invalid = valid_plan_payload()
    still_invalid["subqueries"][0]["filters"]["confidence"] = "high"  # type: ignore[index]
    calls = patch_planner_provider(monkeypatch, invalid_payload, still_invalid)

    result = plan_question(root, "Which fruit is best for vitamin C?", PlanningOptions())

    assert result.status == "planning_invalid"
    assert result.plan is None
    assert len(calls) == 2
    assert "Invalid confidence" in result.error


def test_plan_question_repairs_unknown_source_filter_once(monkeypatch):
    root = setup_seeded_workspace()
    invalid_payload = valid_plan_payload()
    invalid_payload["subqueries"][0]["filters"]["source_id"] = "src_missing"  # type: ignore[index]
    calls = patch_planner_provider(monkeypatch, invalid_payload, valid_plan_payload())

    result = plan_question(root, "Which fruit is best for vitamin C?", PlanningOptions())

    assert result.status == "planned"
    assert result.plan is not None
    assert len(calls) == 2
    assert "Unknown source_id in planner filters: src_missing" in calls[1][-1]["content"]


def test_plan_question_returns_invalid_when_repair_fails(monkeypatch):
    root = setup_seeded_workspace()
    calls = patch_planner_provider(monkeypatch, "{bad", "{still bad")

    result = plan_question(root, "Which fruit is best for vitamin C?", PlanningOptions())

    assert result.status == "planning_invalid"
    assert result.plan is None
    assert len(calls) == 2
    assert result.error


def test_plan_question_rejects_unknown_catalog_references(monkeypatch):
    root = setup_seeded_workspace()
    payload = valid_plan_payload()
    payload["entities"][0]["catalog_refs"] = ["concept:missing"]  # type: ignore[index]
    patch_planner_provider(monkeypatch, payload)

    result = plan_question(root, "Which fruit is best for vitamin C?", PlanningOptions())

    assert result.status == "planning_invalid"
    assert "unknown" in result.error.casefold()


def test_plan_question_rejects_forged_evidence_fields(monkeypatch):
    root = setup_seeded_workspace()
    payload = valid_plan_payload()
    payload["subqueries"][0]["claim_id"] = "clm_fake"  # type: ignore[index]
    payload["subqueries"][0]["citation_locator"] = "line:999"  # type: ignore[index]
    payload["subqueries"][0]["page_path"] = "wiki/sources/fake.md"  # type: ignore[index]
    payload["subqueries"][0]["score"] = 1.0  # type: ignore[index]
    patch_planner_provider(monkeypatch, payload)

    result = plan_question(root, "Which fruit is best for vitamin C?", PlanningOptions())

    assert result.status == "planning_invalid"
    assert "forbidden evidence field" in result.error


def test_plan_question_sanitizes_secret_like_errors(monkeypatch):
    root = setup_seeded_workspace()

    def fake_create_provider(config, root=None):
        raise ValueError("bad config/api-keys.toml sk-test-secret-should-not-print")

    monkeypatch.setattr("llmwiki.planner.create_provider", fake_create_provider)

    result = plan_question(root, "Which fruit is best for vitamin C?", PlanningOptions())
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)

    assert result.status == "planning_failed"
    assert "config/api-keys.toml" not in serialized
    assert "sk-test-secret-should-not-print" not in serialized
