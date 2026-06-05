from __future__ import annotations

from llmwiki.metrics.canonicalization import (
    CANONICAL_METRIC_SCHEMA_VERSION,
    METRIC_CANONICALIZATION_REPORT_SCHEMA_VERSION,
    METRIC_COMPARABILITY_GROUP_SCHEMA_VERSION,
    METRIC_RESULT_VALUE_REPAIR_SCHEMA_VERSION,
    METRIC_TIMELINE_READINESS_SCHEMA_VERSION,
    MetricCanonicalizationFilterError,
    build_value_repair,
    normalize_canonical_metric_key,
    validate_limit_offset,
)


def test_metric_canonicalization_schema_versions_and_limit_validation() -> None:
    assert METRIC_CANONICALIZATION_REPORT_SCHEMA_VERSION == "metric_canonicalization_report.v4.7"
    assert CANONICAL_METRIC_SCHEMA_VERSION == "canonical_metric.v4.7"
    assert METRIC_RESULT_VALUE_REPAIR_SCHEMA_VERSION == "metric_result_value_repair.v4.7"
    assert METRIC_COMPARABILITY_GROUP_SCHEMA_VERSION == "metric_comparability_group.v4.7"
    assert METRIC_TIMELINE_READINESS_SCHEMA_VERSION == "metric_timeline_readiness.v4.7"
    assert validate_limit_offset(limit=None, offset=None) == (200, 0, [])

    limit, offset, warnings = validate_limit_offset(limit=5000, offset=2)
    assert limit == 1000
    assert offset == 2
    assert warnings[0]["code"] == "limit_clamped"

    for kwargs in ({"limit": 0, "offset": 0}, {"limit": 10, "offset": -1}):
        try:
            validate_limit_offset(**kwargs)
        except MetricCanonicalizationFilterError:
            pass
        else:
            raise AssertionError("invalid limit/offset must fail")


def test_normalize_canonical_metric_key_keeps_conservative_metric_boundaries() -> None:
    assert normalize_canonical_metric_key("Success Rate") == "success_rate"
    assert normalize_canonical_metric_key("success-rate") == "success_rate"
    assert normalize_canonical_metric_key("  Avg. Score ") == "avg_score"
    assert normalize_canonical_metric_key("accuracy") == "accuracy"
    assert normalize_canonical_metric_key("success rate") != normalize_canonical_metric_key("accuracy")


def test_value_repair_suggests_only_parseable_values_and_rejects_placeholders() -> None:
    row = {
        "result_id": "res_1",
        "metric_name": "Success Rate",
        "metric_value": "",
        "metric_unit": "",
        "metric_raw_value": "not reported",
        "claim_text": "The method reaches 42.1% success rate on OSWorld.",
        "context_preview": "Table 1 shows a success rate of 42.1%.",
    }

    repair = build_value_repair(row)

    assert repair is not None
    assert repair["schema_version"] == "metric_result_value_repair.v4.7"
    assert repair["result_id"] == "res_1"
    assert repair["suggested_metric_value"] == "42.1"
    assert repair["suggested_metric_unit"] == "%"
    assert repair["value_scale"] == "percent"
    assert repair["repair_status"] == "suggested"

    placeholder_only = dict(row, claim_text="No value is reported.", context_preview="See table.", metric_raw_value="N/A")
    assert build_value_repair(placeholder_only)["repair_status"] == "not_repairable"


def test_value_repair_warns_on_multiple_conflicting_numbers() -> None:
    row = {
        "result_id": "res_multi",
        "metric_name": "Success Rate",
        "metric_value": "",
        "metric_unit": "",
        "metric_raw_value": "",
        "claim_text": "The paper reports 41.0% and 42.0% success rate.",
        "context_preview": "",
    }

    repair = build_value_repair(row)

    assert repair["repair_status"] == "not_repairable"
    assert any(warning["code"] == "multiple_numeric_candidates" for warning in repair["warnings"])
