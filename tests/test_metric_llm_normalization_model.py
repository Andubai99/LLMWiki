from __future__ import annotations

import pytest

from llmwiki.metrics.llm_normalization import (
    DECISION_CONFIDENCES,
    DECISION_STATUSES,
    METRIC_EVIDENCE_BUNDLE_SCHEMA_VERSION,
    METRIC_NORMALIZATION_DECISION_SCHEMA_VERSION,
    METRIC_NORMALIZATION_RUN_SCHEMA_VERSION,
    METRIC_NORMALIZATION_WARNING_SCHEMA_VERSION,
    METRIC_TIMELINE_GROUP_SCHEMA_VERSION,
    METRIC_TIMELINE_POINT_SCHEMA_VERSION,
    METRIC_TIMELINE_SYNTHESIS_SCHEMA_VERSION,
    MetricNormalizationFilterError,
    validate_limit_offset,
)


def test_metric_llm_normalization_schema_versions_and_limit_validation() -> None:
    assert METRIC_NORMALIZATION_RUN_SCHEMA_VERSION == "metric_normalization_run.v4.9"
    assert METRIC_EVIDENCE_BUNDLE_SCHEMA_VERSION == "metric_evidence_bundle.v4.9"
    assert METRIC_NORMALIZATION_DECISION_SCHEMA_VERSION == "metric_normalization_decision.v4.9"
    assert METRIC_TIMELINE_GROUP_SCHEMA_VERSION == "metric_timeline_group.v4.9"
    assert METRIC_TIMELINE_POINT_SCHEMA_VERSION == "metric_timeline_point.v4.9"
    assert METRIC_TIMELINE_SYNTHESIS_SCHEMA_VERSION == "metric_timeline_synthesis.v4.9"
    assert METRIC_NORMALIZATION_WARNING_SCHEMA_VERSION == "metric_normalization_warning.v4.9"
    assert DECISION_STATUSES == {"auto_accepted", "needs_review", "blocked", "conflict", "insufficient_evidence"}
    assert DECISION_CONFIDENCES == {"high", "medium", "low"}
    assert validate_limit_offset(limit=None, offset=None) == (200, 0, [])

    limit, offset, warnings = validate_limit_offset(limit=5000, offset=2)
    assert limit == 1000
    assert offset == 2
    assert warnings[0]["code"] == "limit_clamped"

    for kwargs in ({"limit": 0, "offset": 0}, {"limit": 10, "offset": -1}):
        with pytest.raises(MetricNormalizationFilterError):
            validate_limit_offset(**kwargs)
