from __future__ import annotations

from llmwiki.research.relationships import build_research_graph_run, build_research_synthesis_response
from tests.test_metric_repair_query import workspace_with_metric_repair_cases
from tests.test_research_relationship_cli import FakeResearchProvider


def test_research_synthesis_uses_only_staged_edge_evidence(monkeypatch) -> None:
    root = workspace_with_metric_repair_cases()
    monkeypatch.setattr("llmwiki.research.relationships.create_provider", lambda config, root=None: FakeResearchProvider())
    run = build_research_graph_run(root, source_id="src_pdf")

    payload = build_research_synthesis_response(root, run.relationship_run_id).to_dict()

    assert payload["schema_version"] == "research_synthesis.v5.0"
    assert payload["relationship_run_id"] == run.relationship_run_id
    assert payload["synthesis"]
    assert payload["evidence_refs"]
    assert all(ref["claim_id"] and ref["source_id"] and ref["citation_locator"] for ref in payload["evidence_refs"])
    assert payload["summary"]["synthesis_item_count"] >= 1
    assert payload["summary"]["synthesis_evidence_ref_count"] == len(payload["evidence_refs"])
