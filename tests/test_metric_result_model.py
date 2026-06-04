from __future__ import annotations

from llmwiki.ingestion.metric_results import (
    METRIC_RESULT_SCHEMA_VERSION,
    MetricResultClaim,
    assign_metric_result_ids,
    dedupe_metric_results,
    normalize_metric_value,
)


def test_metric_result_schema_defaults_and_serialization() -> None:
    result = MetricResultClaim(
        result_id="res_clm_src_pdf_001_001",
        claim_id="clm_src_pdf_001",
        source_id="src_pdf",
        paper_id="src_pdf",
        claim_text="The paper reports 92.3% accuracy on BenchmarkX.",
        citation_locator="page:4;block:src_pdf_p004_b0012;section:Results",
        confidence_status="cited",
        extraction_origin="table",
        metric_name="accuracy",
        metric_value="92.3",
        metric_unit="%",
        metric_raw_value="92.3%",
        created_at="2026-06-04T00:00:00+00:00",
        evidence_block_ids=["src_pdf_p004_b0012"],
        evidence_pages=[4],
        evidence_section_path=["Results"],
        evidence_block_roles=["table"],
        method="MethodA",
        dataset="BenchmarkX",
        task="desktop task",
        metric_direction="higher_is_better",
        value_normalization_status="normalized",
    )

    payload = result.to_dict()

    assert payload["schema_version"] == METRIC_RESULT_SCHEMA_VERSION
    assert payload["result_id"] == "res_clm_src_pdf_001_001"
    assert payload["claim_id"] == "clm_src_pdf_001"
    assert payload["paper_id"] == "src_pdf"
    assert payload["baseline"] == ""
    assert payload["comparison_value"] == ""
    assert payload["setting"] == ""
    assert payload["reported_year"] is None
    assert payload["is_main_result"] is None
    assert payload["warnings"] == []


def test_metric_value_normalization_is_conservative() -> None:
    assert normalize_metric_value("92.3%") == {
        "metric_value": "92.3",
        "metric_unit": "%",
        "metric_raw_value": "92.3%",
        "value_normalization_status": "normalized",
    }
    assert normalize_metric_value("24 ms") == {
        "metric_value": "24",
        "metric_unit": "ms",
        "metric_raw_value": "24 ms",
        "value_normalization_status": "normalized",
    }
    assert normalize_metric_value("+3.4 points") == {
        "metric_value": "3.4",
        "metric_unit": "points",
        "metric_raw_value": "+3.4 points",
        "value_normalization_status": "normalized",
    }
    assert normalize_metric_value("roughly state of the art") == {
        "metric_value": "",
        "metric_unit": "",
        "metric_raw_value": "roughly state of the art",
        "value_normalization_status": "raw_only",
    }
    assert normalize_metric_value("") == {
        "metric_value": "",
        "metric_unit": "",
        "metric_raw_value": "",
        "value_normalization_status": "missing",
    }


def test_assign_metric_result_ids_happens_after_claim_ids_are_known() -> None:
    result = MetricResultClaim(
        result_id="",
        claim_id="clm_src_pdf_llm_001",
        source_id="src_pdf",
        paper_id="src_pdf",
        claim_text="MethodA reaches 92.3% accuracy on BenchmarkX.",
        citation_locator="page:4;block:src_pdf_p004_b0012;section:Results",
        confidence_status="cited",
        extraction_origin="table",
        metric_name="accuracy",
        metric_raw_value="92.3%",
        created_at="2026-06-04T00:00:00+00:00",
        evidence_block_ids=["src_pdf_p004_b0012"],
        evidence_pages=[4],
        evidence_section_path=["Results"],
        evidence_block_roles=["table"],
    )

    assigned = assign_metric_result_ids([result])

    assert assigned[0].result_id == "res_clm_src_pdf_llm_001_001"


def test_dedupe_metric_results_keeps_distinct_metrics_for_same_claim() -> None:
    base = MetricResultClaim(
        result_id="",
        claim_id="clm_src_pdf_llm_001",
        source_id="src_pdf",
        paper_id="src_pdf",
        claim_text="MethodA reports 92.3% accuracy and 91.0 F1 on BenchmarkX.",
        citation_locator="page:4;block:src_pdf_p004_b0012;section:Results",
        confidence_status="cited",
        extraction_origin="table",
        metric_name="accuracy",
        metric_raw_value="92.3%",
        metric_value="92.3",
        metric_unit="%",
        created_at="2026-06-04T00:00:00+00:00",
        evidence_block_ids=["src_pdf_p004_b0012"],
        evidence_pages=[4],
        evidence_section_path=["Results"],
        evidence_block_roles=["table"],
        method="MethodA",
        dataset="BenchmarkX",
    )
    duplicate = base
    distinct = MetricResultClaim(
        **{
            **base.to_dict(),
            "result_id": "",
            "metric_name": "F1",
            "metric_raw_value": "91.0",
            "metric_value": "91.0",
            "metric_unit": "",
        }
    )

    deduped = dedupe_metric_results([base, duplicate, distinct])

    assert len(deduped) == 2
    assert {result.metric_name for result in deduped} == {"accuracy", "F1"}
