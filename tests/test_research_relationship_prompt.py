from __future__ import annotations

import json

from llmwiki.research.relationship_prompt import build_research_relationship_messages, research_relationship_schema
from llmwiki.research.relationships import validate_relationship_edges


def sample_relationship_bundle() -> dict:
    return {
        "schema_version": "research_relationship_bundle.v5.0",
        "bundle_id": "rrb_sample",
        "bundle_type": "same_metric_bundle",
        "candidate_relationship_types": ["same_metric", "same_benchmark", "not_comparable"],
        "topic": "computer use",
        "result_rows": [
            {
                "result_id": "res_a",
                "claim_id": "clm_a",
                "source_id": "src_a",
                "paper_id": "src_a",
                "citation_locator": "page:1;block:src_a_p001_b0001",
                "metric_name": "Success Rate",
                "dataset": "OSWorld",
                "task": "computer use",
                "method": "Agent A",
                "metric_value": "42.0",
                "metric_raw_value": "42.0%",
                "result_role": "main_result",
            }
        ],
        "context_refs": [
            {
                "result_id": "res_a",
                "claim_id": "clm_a",
                "source_id": "src_a",
                "paper_id": "src_a",
                "citation_locator": "page:1;block:src_a_p001_b0001",
                "page_path": "wiki/sources/src_a.md",
                "context_preview": "Agent A reports 42.0% success rate on OSWorld.",
            }
        ],
        "paper_identities": [{"source_id": "src_a", "paper_id": "src_a", "title": "Paper A", "year": 2024}],
        "warnings": [],
    }


def test_research_relationship_prompt_requires_source_backed_edges() -> None:
    bundle = sample_relationship_bundle()

    messages = build_research_relationship_messages(bundle)
    schema = research_relationship_schema()

    assert schema["type"] == "object"
    assert "edges" in schema["properties"]
    assert "not_comparable" in messages[0]["content"]
    assert "Do not invent" in messages[0]["content"]
    assert "relationship bundle:\n" in messages[-1]["content"]
    assert json.loads(messages[-1]["content"].split("relationship bundle:\n", 1)[1])["bundle_id"] == "rrb_sample"
    assert "parser diagnostics" not in messages[-1]["content"].casefold()


def test_research_relationship_edge_validation_rejects_fabricated_refs() -> None:
    bundle = sample_relationship_bundle()
    llm_payload = {
        "edges": [
            {
                "relationship_type": "same_metric",
                "subject": {"entity_type": "paper", "entity_id": "src_a", "label": "Paper A"},
                "object": {"entity_type": "metric", "entity_id": "success_rate", "label": "success rate"},
                "decision_status": "auto_accepted",
                "confidence": "high",
                "comparability_status": "comparable",
                "rationale": "The bundle cites the same metric.",
                "evidence_refs": [
                    {
                        "result_id": "res_fake",
                        "claim_id": "clm_fake",
                        "source_id": "src_a",
                        "paper_id": "src_a",
                        "citation_locator": "page:99;block:fake",
                    }
                ],
                "warnings": [],
            }
        ]
    }

    edges, warnings = validate_relationship_edges(bundle, llm_payload)

    assert edges == []
    assert any(warning["code"] == "fabricated_evidence_ref" for warning in warnings)


def test_research_relationship_edge_validation_fills_empty_subject_object_from_bundle() -> None:
    bundle = sample_relationship_bundle()
    row = bundle["result_rows"][0]
    llm_payload = {
        "edges": [
            {
                "relationship_type": "same_metric",
                "subject": {},
                "object": {},
                "decision_status": "auto_accepted",
                "confidence": "high",
                "comparability_status": "comparable",
                "rationale": "",
                "evidence_refs": [
                    {
                        "result_id": row["result_id"],
                        "claim_id": row["claim_id"],
                        "source_id": row["source_id"],
                        "paper_id": row["paper_id"],
                        "citation_locator": row["citation_locator"],
                    }
                ],
                "warnings": [],
            }
        ]
    }

    edges, warnings = validate_relationship_edges(bundle, llm_payload)

    assert warnings == []
    assert edges[0]["subject"]["entity_type"] == "paper"
    assert edges[0]["subject"]["entity_id"] == "src_a"
    assert edges[0]["object"]["entity_type"] == "metric"
    assert edges[0]["object"]["label"] == "Success Rate"
    assert edges[0]["rationale"]


def test_research_relationship_edge_validation_defaults_auto_accepted_confidence_to_medium() -> None:
    bundle = sample_relationship_bundle()
    row = bundle["result_rows"][0]
    llm_payload = {
        "edges": [
            {
                "relationship_type": "same_metric",
                "subject": {"entity_type": "paper", "entity_id": "src_a", "label": "Paper A"},
                "object": {"entity_type": "metric", "entity_id": "success_rate", "label": "success rate"},
                "decision_status": "auto_accepted",
                "comparability_status": "comparable",
                "evidence_refs": [
                    {
                        "result_id": row["result_id"],
                        "claim_id": row["claim_id"],
                        "source_id": row["source_id"],
                        "paper_id": row["paper_id"],
                        "citation_locator": row["citation_locator"],
                    }
                ],
            }
        ]
    }

    edges, warnings = validate_relationship_edges(bundle, llm_payload)

    assert edges[0]["confidence"] == "medium"
    assert any(warning["code"] == "missing_confidence_defaulted" for warning in warnings)
