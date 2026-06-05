from __future__ import annotations

from llmwiki.metrics.repair import (
    METRIC_REPAIR_DECISION_SCHEMA_VERSION,
    METRIC_REPAIR_PLAN_SCHEMA_VERSION,
    METRIC_REPAIR_PROJECTION_SCHEMA_VERSION,
    METRIC_REPAIR_PROPOSAL_SCHEMA_VERSION,
    METRIC_REPAIR_RUN_SCHEMA_VERSION,
    METRIC_REPAIR_WARNING_SCHEMA_VERSION,
    MetricRepairFilterError,
    proposal_id_for_payload,
    review_risk_for_alias,
    validate_limit_offset,
)


def test_metric_repair_schema_versions_and_limit_validation() -> None:
    assert METRIC_REPAIR_PLAN_SCHEMA_VERSION == "metric_repair_plan.v4.8"
    assert METRIC_REPAIR_PROPOSAL_SCHEMA_VERSION == "metric_repair_proposal.v4.8"
    assert METRIC_REPAIR_DECISION_SCHEMA_VERSION == "metric_repair_review_decision.v4.8"
    assert METRIC_REPAIR_PROJECTION_SCHEMA_VERSION == "metric_repair_projection.v4.8"
    assert METRIC_REPAIR_WARNING_SCHEMA_VERSION == "metric_repair_warning.v4.8"
    assert METRIC_REPAIR_RUN_SCHEMA_VERSION == "metric_repair_run.v4.8"
    assert validate_limit_offset(limit=None, offset=None) == (200, 0, [])

    limit, offset, warnings = validate_limit_offset(limit=5000, offset=2)
    assert limit == 1000
    assert offset == 2
    assert warnings[0]["code"] == "limit_clamped"

    for kwargs in ({"limit": 0, "offset": 0}, {"limit": 10, "offset": -1}):
        try:
            validate_limit_offset(**kwargs)
        except MetricRepairFilterError:
            pass
        else:
            raise AssertionError("invalid limit/offset must fail")


def test_proposal_id_is_deterministic_from_canonical_payload() -> None:
    left = {
        "proposal_type": "metric_value_from_v47_suggestion",
        "target": {"result_id": "res_a", "claim_id": "clm_a"},
        "suggested": {"metric_value": "42.1", "metric_unit": "%"},
    }
    right = {
        "suggested": {"metric_unit": "%", "metric_value": "42.1"},
        "target": {"claim_id": "clm_a", "result_id": "res_a"},
        "proposal_type": "metric_value_from_v47_suggestion",
    }

    proposal_id = proposal_id_for_payload(left)

    assert proposal_id == proposal_id_for_payload(right)
    assert proposal_id.startswith("mrp_")
    assert len(proposal_id) == 16


def test_alias_risk_detects_split_words_and_safe_lexical_variants() -> None:
    assert review_risk_for_alias("ScreenSpot-Pro", "ScreenSpot Pro") == "low"
    assert review_risk_for_alias("computer use", "computer-use") == "low"
    assert review_risk_for_alias("OSWorld", "OSWorld full test") == "high"
    assert review_risk_for_alias("GUI grounding", "GUI automation") == "medium"
