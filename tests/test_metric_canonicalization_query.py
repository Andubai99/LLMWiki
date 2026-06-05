from __future__ import annotations

import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.metrics.canonicalization import build_metric_canonicalization_report
from tests.helpers import make_workspace
from tests.test_corpus_results_eval_model import workspace_with_corpus_results
from tests.test_metric_timeline_query import insert_metric_result, insert_source


def workspace_with_canonicalization_cases() -> Path:
    root = workspace_with_corpus_results()
    insert_metric_result(
        root,
        result_id="res_score_a",
        claim_id="clm_score_a",
        source_id="src_pdf",
        metric_name="Score",
        metric_value="10",
        metric_raw_value="10",
        reported_year=2024,
        method="Agent A",
        dataset="OSWorld",
        task="computer use",
    )
    insert_metric_result(
        root,
        result_id="res_score_b",
        claim_id="clm_score_b",
        source_id="src_md",
        metric_name="score",
        metric_value="11",
        metric_raw_value="11",
        reported_year=2025,
        method="Agent B",
        dataset="OSWorld",
        task="computer use",
    )
    return root


def test_metric_canonicalization_report_schema_summary_and_groups() -> None:
    root = workspace_with_canonicalization_cases()

    payload = build_metric_canonicalization_report(root).to_dict()

    assert payload["schema_version"] == "metric_canonicalization_report.v4.7"
    assert payload["query"] == {
        "metric": "",
        "dataset": "",
        "task": "",
        "limit": 200,
        "offset": 0,
    }
    assert payload["summary"]["result_count"] == 6
    assert payload["summary"]["canonical_metric_count_unpaged"] == 3
    assert payload["summary"]["comparability_group_count_unpaged"] >= 3
    assert payload["summary"]["value_repair_count_unpaged"] == 1
    assert payload["summary"]["strict_ready_count"] >= 1
    assert payload["summary"]["ready_after_value_repair_count"] >= 1
    assert payload["summary"]["needs_canonical_review_count"] >= 1

    success = next(metric for metric in payload["canonical_metrics"] if metric["canonical_metric_key"] == "success_rate")
    assert success["schema_version"] == "canonical_metric.v4.7"
    assert success["row_count"] == 3
    assert success["paper_count"] == 2
    assert success["display_name"] == "Success Rate"
    assert "Success Rate" in success["variants"]

    repair = payload["value_repairs"][0]
    assert repair["result_id"] == "res_missing_value"
    assert repair["suggested_metric_value"] == "42.1"
    assert repair["repair_status"] == "suggested"

    ready_after_repair = [
        item for item in payload["timeline_readiness"] if item["readiness_status"] == "ready_after_value_repair"
    ]
    assert ready_after_repair
    assert ready_after_repair[0]["canonical_metric_key"] == "success_rate"
    assert ready_after_repair[0]["blocking_reasons"] == ["missing_value_repair_available"]

    score_review = [
        item
        for item in payload["timeline_readiness"]
        if item["canonical_metric_key"] == "score" and item["readiness_status"] == "needs_canonical_review"
    ]
    assert score_review
    assert "ambiguous_label" in score_review[0]["blocking_reasons"]


def test_metric_canonicalization_filters_paginates_and_keeps_unpaged_counts() -> None:
    root = workspace_with_canonicalization_cases()

    payload = build_metric_canonicalization_report(root, metric="success rate", dataset="osworld", limit=1, offset=0).to_dict()

    assert payload["summary"]["result_count"] == 3
    assert payload["summary"]["canonical_metric_count_unpaged"] == 1
    assert len(payload["canonical_metrics"]) == 1
    assert len(payload["comparability_groups"]) == 1
    assert len(payload["timeline_readiness"]) == 1
    assert payload["canonical_metrics"][0]["canonical_metric_key"] == "success_rate"


def test_metric_canonicalization_empty_initialized_workspace_warns() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    payload = build_metric_canonicalization_report(root).to_dict()

    assert payload["summary"]["result_count"] == 0
    assert payload["canonical_metrics"] == []
    assert payload["comparability_groups"] == []
    assert payload["timeline_readiness"] == []
    assert any(warning["code"] == "no_catalog_backed_result" for warning in payload["warnings"])


def test_metric_canonicalization_missing_join_is_reported_not_repaired() -> None:
    root = workspace_with_canonicalization_cases()
    insert_metric_result(
        root,
        result_id="res_orphan",
        claim_id="clm_orphan",
        source_id="src_pdf",
        metric_name="Success Rate",
        metric_value="50.0",
        metric_raw_value="50.0%",
        reported_year=2025,
        locator="page:2;block:src_pdf_p002_b0001",
    )
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute("delete from claims where claim_id = 'clm_orphan'")

    payload = build_metric_canonicalization_report(root).to_dict()

    assert payload["summary"]["result_count"] == 7
    assert any(warning["code"] == "missing_claim_join" for warning in payload["warnings"])


def test_metric_canonicalization_single_paper_status() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    insert_source(root, source_id="src_single", title="Single Result Paper")
    insert_metric_result(
        root,
        result_id="res_single",
        claim_id="clm_single",
        source_id="src_single",
        metric_name="Completion Rate",
        metric_value="70.0",
        metric_raw_value="70.0%",
        reported_year=2024,
    )

    payload = build_metric_canonicalization_report(root).to_dict()

    readiness = payload["timeline_readiness"][0]
    assert readiness["schema_version"] == "metric_timeline_readiness.v4.7"
    assert readiness["readiness_status"] == "not_ready_single_paper"
    assert readiness["blocking_reasons"] == ["single_paper"]
