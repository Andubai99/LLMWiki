from __future__ import annotations

from llmwiki.research.relationships import build_research_relationship_dry_run
from tests.test_metric_repair_query import workspace_with_metric_repair_cases


def test_research_relationship_dry_run_builds_bounded_bundles() -> None:
    root = workspace_with_metric_repair_cases()

    payload = build_research_relationship_dry_run(root, metric="success rate", max_results_per_bundle=3).to_dict()

    assert payload["schema_version"] == "research_relationship_run.v5.0"
    assert payload["mode"] == "dry_run"
    assert payload["relationship_run_id"] == ""
    assert payload["summary"]["metric_result_count"] >= 3
    assert payload["summary"]["relationship_bundle_count"] >= 1
    assert payload["summary"]["estimated_prompt_tokens"] > 0
    assert payload["relationship_bundles"]

    bundle = payload["relationship_bundles"][0]
    assert bundle["schema_version"] == "research_relationship_bundle.v5.0"
    assert bundle["bundle_id"].startswith("rrb_")
    assert bundle["bundle_type"] in {
        "same_benchmark_bundle",
        "same_metric_bundle",
        "baseline_comparison_bundle",
        "not_comparable_bundle",
        "topic_cluster_bundle",
    }
    assert bundle["candidate_relationship_types"]
    assert bundle["result_rows"]
    assert bundle["context_refs"]
    assert all(ref["source_id"] and ref["paper_id"] and ref["citation_locator"] for ref in bundle["context_refs"])
    assert all(row["result_id"] and row["claim_id"] and row["source_id"] for row in bundle["result_rows"])
    assert "raw prompt" not in str(bundle).casefold()


def test_research_relationship_dry_run_filters_source_and_relationship_type() -> None:
    root = workspace_with_metric_repair_cases()

    payload = build_research_relationship_dry_run(root, source_id="src_pdf", relationship_type="same_metric").to_dict()

    assert payload["summary"]["metric_result_count"] > 0
    assert {
        row["source_id"]
        for bundle in payload["relationship_bundles"]
        for row in bundle["result_rows"]
    } == {"src_pdf"}
    assert all("same_metric" in bundle["candidate_relationship_types"] for bundle in payload["relationship_bundles"])


def test_research_relationship_dry_run_empty_workspace_warns() -> None:
    from llmwiki.cli import main
    from tests.helpers import make_workspace

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    payload = build_research_relationship_dry_run(root).to_dict()

    assert payload["summary"]["relationship_bundle_count"] == 0
    assert payload["relationship_bundles"] == []
    assert any(warning["code"] == "no_relationship_bundles" for warning in payload["warnings"])
