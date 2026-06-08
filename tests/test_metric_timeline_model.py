from __future__ import annotations

from llmwiki.metrics.timeline import (
    METRIC_LIST_SCHEMA_VERSION,
    METRIC_TIMELINE_ITEM_SCHEMA_VERSION,
    METRIC_TIMELINE_SCHEMA_VERSION,
    TimelineFilterError,
    normalize_timeline_key,
    validate_limit_offset,
)


def test_metric_timeline_schema_versions_are_fixed() -> None:
    assert METRIC_TIMELINE_SCHEMA_VERSION == "metric_timeline.v4.4"
    assert METRIC_TIMELINE_ITEM_SCHEMA_VERSION == "metric_timeline_item.v4.4"
    assert METRIC_LIST_SCHEMA_VERSION == "metric_list.v4.4"


def test_normalize_timeline_key_is_unicode_casefolded_and_punctuation_insensitive() -> None:
    assert normalize_timeline_key(" Success-Rate ") == "successrate"
    assert normalize_timeline_key("SUCCESS   RATE") == "successrate"
    assert normalize_timeline_key("F1-score") == "f1score"
    assert normalize_timeline_key("任务 成功率") == "任务成功率"


def test_validate_limit_offset_clamps_limit_and_rejects_invalid_values() -> None:
    assert validate_limit_offset(limit=None, offset=None) == (100, 0, [])

    limit, offset, warnings = validate_limit_offset(limit=999, offset=2)
    assert limit == 500
    assert offset == 2
    assert warnings[0]["code"] == "limit_clamped"

    for kwargs in ({"limit": 0, "offset": 0}, {"limit": 10, "offset": -1}):
        try:
            validate_limit_offset(**kwargs)
        except TimelineFilterError as exc:
            assert "invalid" in str(exc).casefold()
        else:
            raise AssertionError("invalid limit/offset must fail")
