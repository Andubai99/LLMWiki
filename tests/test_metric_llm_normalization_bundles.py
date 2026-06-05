from __future__ import annotations

from llmwiki.metrics.llm_normalization import build_metric_normalization_dry_run
from tests.test_metric_repair_query import workspace_with_metric_repair_cases


def test_metric_normalization_dry_run_builds_bounded_evidence_bundles() -> None:
    root = workspace_with_metric_repair_cases()

    payload = build_metric_normalization_dry_run(root, metric="success rate", max_results_per_group=3).to_dict()

    assert payload["schema_version"] == "metric_normalization_run.v4.9"
    assert payload["mode"] == "dry_run"
    assert payload["summary"]["result_count"] >= 3
    assert payload["summary"]["evidence_bundle_count"] >= 1
    assert payload["summary"]["estimated_prompt_tokens"] > 0
    assert payload["evidence_bundles"]

    bundle = payload["evidence_bundles"][0]
    assert bundle["schema_version"] == "metric_evidence_bundle.v4.9"
    assert bundle["bundle_id"].startswith("meb_")
    assert bundle["result_count"] <= 3
    assert bundle["candidate_group_key"]
    assert bundle["paper_identities"]
    assert bundle["result_rows"]
    assert bundle["context_refs"]
    assert all(ref["citation_locator"] for ref in bundle["context_refs"])
    assert all(row["result_id"] and row["claim_id"] and row["source_id"] for row in bundle["result_rows"])
    assert "raw prompt" not in str(bundle).casefold()


def test_metric_normalization_dry_run_filters_source_and_paper() -> None:
    root = workspace_with_metric_repair_cases()

    payload = build_metric_normalization_dry_run(root, source_id="src_pdf", paper_id="src_pdf").to_dict()

    assert payload["summary"]["result_count"] > 0
    assert {
        row["source_id"]
        for bundle in payload["evidence_bundles"]
        for row in bundle["result_rows"]
    } == {"src_pdf"}
