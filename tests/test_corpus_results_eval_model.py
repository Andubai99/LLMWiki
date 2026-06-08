from __future__ import annotations

import sqlite3
from pathlib import Path

from llmwiki.cli import main
from llmwiki.evals.corpus_results import (
    CORPUS_RESULTS_EVAL_SCHEMA_VERSION,
    CORPUS_RESULTS_METRIC_SCHEMA_VERSION,
    CORPUS_RESULTS_PAPER_SCHEMA_VERSION,
    CorpusResultsFilterError,
    build_corpus_results_eval,
    validate_limit_offset,
)
from tests.helpers import make_workspace
from tests.test_metric_timeline_query import insert_metric_result
from tests.test_result_evidence_quality_model import workspace_with_result_evidence


def workspace_with_corpus_results() -> Path:
    root = workspace_with_result_evidence()
    insert_metric_result(
        root,
        result_id="res_md_success",
        claim_id="clm_md_success",
        source_id="src_md",
        metric_name="Success Rate",
        metric_value="44.0",
        metric_raw_value="44.0%",
        reported_year=2025,
        method="Agent B",
        dataset="OSWorld",
        task="computer use",
        locator="line:3",
    )
    return root


def quality_gate(payload: dict, name: str) -> dict:
    for gate in payload["quality_gates"]:
        if gate["name"] == name:
            return gate
    raise AssertionError(f"missing quality gate: {name}")


def test_corpus_results_schema_versions_and_limit_validation() -> None:
    assert CORPUS_RESULTS_EVAL_SCHEMA_VERSION == "corpus_results_eval.v4.6"
    assert CORPUS_RESULTS_PAPER_SCHEMA_VERSION == "corpus_results_paper.v4.6"
    assert CORPUS_RESULTS_METRIC_SCHEMA_VERSION == "corpus_results_metric.v4.6"
    assert validate_limit_offset(limit=None, offset=None) == (200, 0, [])

    limit, offset, warnings = validate_limit_offset(limit=5000, offset=2)
    assert limit == 1000
    assert offset == 2
    assert warnings[0]["code"] == "limit_clamped"

    for kwargs in ({"limit": 0, "offset": 0}, {"limit": 10, "offset": -1}):
        try:
            validate_limit_offset(**kwargs)
        except CorpusResultsFilterError:
            pass
        else:
            raise AssertionError("invalid limit/offset must fail")


def test_corpus_results_summary_papers_metrics_and_quality_gates() -> None:
    root = workspace_with_corpus_results()

    payload = build_corpus_results_eval(root).to_dict()

    assert payload["schema_version"] == "corpus_results_eval.v4.6"
    assert payload["query"] == {
        "metric": "",
        "dataset": "",
        "task": "",
        "limit": 200,
        "offset": 0,
    }
    assert payload["summary"]["source_count"] == 2
    assert payload["summary"]["paper_count"] == 2
    assert payload["summary"]["formal_claim_count"] == 4
    assert payload["summary"]["metric_result_count"] == 4
    assert payload["summary"]["durable_metric_result_count"] == 4
    assert payload["summary"]["joined_result_count"] == 4
    assert payload["summary"]["resolvable_locator_count"] == 4
    assert payload["summary"]["context_available_count"] == 4
    assert payload["summary"]["table_result_count"] == 2
    assert payload["summary"]["caption_result_count"] == 1
    assert payload["summary"]["unique_table_block_count"] == 1
    assert payload["summary"]["unique_caption_block_count"] == 1
    assert payload["summary"]["missing_normalized_value_count"] == 1
    assert payload["summary"]["missing_method_count"] == 1
    assert payload["summary"]["missing_task_count"] == 1
    assert payload["summary"]["parser_backend_result_counts"] == {"pypdf": 2, "unknown": 2}
    assert payload["summary"]["parser_fallback_result_count"] == 2
    assert payload["summary"]["metric_list_count"] == 2
    assert payload["summary"]["timeline_candidate_count"] == 1
    assert payload["summary"]["timeline_candidate_missing_year_count"] == 0
    assert payload["summary"]["paper_count_unpaged"] == 2
    assert payload["summary"]["metric_count_unpaged"] == 2
    assert payload["summary"]["timeline_readiness_count_unpaged"] == 1

    assert quality_gate(payload, "catalog_available")["status"] == "pass"
    assert quality_gate(payload, "no_parser_fallback_results")["status"] == "fail"
    assert quality_gate(payload, "table_evidence_present")["status"] == "pass"
    assert quality_gate(payload, "timeline_candidates_present")["status"] == "pass"

    paper = payload["papers"][0]
    assert paper["schema_version"] == "corpus_results_paper.v4.6"
    assert paper["source_id"] in {"src_pdf", "src_md"}
    assert "metric_result_count" in paper
    assert "formal_claim_count" in paper

    success_metric = next(metric for metric in payload["metrics"] if metric["normalized_metric"] == "successrate")
    assert success_metric["schema_version"] == "corpus_results_metric.v4.6"
    assert success_metric["row_count"] == 3
    assert success_metric["paper_count"] == 2
    assert success_metric["timeline_candidate"] is True

    readiness = payload["timeline_readiness"][0]
    assert readiness["normalized_metric"] == "successrate"
    assert readiness["readiness_status"] == "ready"


def test_corpus_results_filters_and_pagination() -> None:
    root = workspace_with_corpus_results()

    payload = build_corpus_results_eval(root, metric="accuracy", limit=1, offset=0).to_dict()

    assert payload["summary"]["metric_result_count"] == 1
    assert len(payload["papers"]) == 1
    assert len(payload["metrics"]) == 1
    assert payload["metrics"][0]["metric_name"] == "Accuracy"
    assert payload["timeline_readiness"] == []
    assert payload["summary"]["paper_count_unpaged"] == 1
    assert payload["summary"]["metric_count_unpaged"] == 1


def test_corpus_results_empty_initialized_workspace_is_success_with_warning() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    payload = build_corpus_results_eval(root).to_dict()

    assert payload["summary"]["source_count"] == 0
    assert payload["summary"]["metric_result_count"] == 0
    assert payload["papers"] == []
    assert payload["metrics"] == []
    assert any(warning["code"] == "no_corpus_sources" for warning in payload["warnings"])
    assert quality_gate(payload, "corpus_sources_present")["status"] == "warn"


def test_corpus_results_missing_join_is_reported_not_dropped() -> None:
    root = workspace_with_corpus_results()
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

    payload = build_corpus_results_eval(root).to_dict()

    assert payload["summary"]["metric_result_count"] == 5
    assert payload["summary"]["joined_result_count"] == 4
    assert quality_gate(payload, "all_results_joined")["status"] == "fail"
    assert any(warning["code"] == "missing_claim_join" for warning in payload["warnings"])
