from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..evals.result_evidence import (
    ResultEvidenceCatalogError,
    ResultEvidenceFilterError,
    build_result_evidence_quality,
    has_diagnostic,
)
from ..workspace import utc_now


METRIC_CANONICALIZATION_REPORT_SCHEMA_VERSION = "metric_canonicalization_report.v4.7"
CANONICAL_METRIC_SCHEMA_VERSION = "canonical_metric.v4.7"
METRIC_RESULT_VALUE_REPAIR_SCHEMA_VERSION = "metric_result_value_repair.v4.7"
METRIC_COMPARABILITY_GROUP_SCHEMA_VERSION = "metric_comparability_group.v4.7"
METRIC_TIMELINE_READINESS_SCHEMA_VERSION = "metric_timeline_readiness.v4.7"
METRIC_CANONICALIZATION_WARNING_SCHEMA_VERSION = "metric_canonicalization_warning.v4.7"

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000

VAGUE_LABEL_KEYS = {
    "avg",
    "average",
    "overall",
    "score",
    "result",
    "metric",
    "value",
    "performance",
}
PLACEHOLDER_VALUES = {
    "",
    "-",
    "n/a",
    "na",
    "none",
    "null",
    "not available",
    "not applicable",
    "not reported",
    "see table",
    "unknown",
}


class MetricCanonicalizationFilterError(ValueError):
    """Invalid V4.7 metric canonicalization filter."""


class MetricCanonicalizationCatalogError(RuntimeError):
    """Catalog is unavailable or incompatible with V4.7 canonicalization."""


@dataclass
class MetricCanonicalizationReport:
    root: str
    query: dict[str, Any]
    summary: dict[str, Any]
    canonical_metrics: list[dict[str, Any]]
    comparability_groups: list[dict[str, Any]]
    timeline_readiness: list[dict[str, Any]]
    value_repairs: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = METRIC_CANONICALIZATION_REPORT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "generated_at": self.generated_at,
            "query": self.query,
            "summary": self.summary,
            "canonical_metric_count": len(self.canonical_metrics),
            "comparability_group_count": len(self.comparability_groups),
            "timeline_readiness_count": len(self.timeline_readiness),
            "value_repair_count": len(self.value_repairs),
            "warning_count": len(self.warnings),
            "canonical_metrics": self.canonical_metrics,
            "comparability_groups": self.comparability_groups,
            "timeline_readiness": self.timeline_readiness,
            "value_repairs": self.value_repairs,
            "warnings": self.warnings,
        }


def validate_limit_offset(limit: int | None, offset: int | None) -> tuple[int, int, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    resolved_limit = DEFAULT_LIMIT if limit is None else int(limit)
    resolved_offset = 0 if offset is None else int(offset)
    if resolved_limit <= 0:
        raise MetricCanonicalizationFilterError("invalid limit: must be positive")
    if resolved_offset < 0:
        raise MetricCanonicalizationFilterError("invalid offset: must be >= 0")
    if resolved_limit > MAX_LIMIT:
        warnings.append(warning("limit_clamped", f"Limit clamped from {resolved_limit} to {MAX_LIMIT}."))
        resolved_limit = MAX_LIMIT
    return resolved_limit, resolved_offset, warnings


def build_metric_canonicalization_report(
    root: Path,
    *,
    metric: str | None = None,
    dataset: str | None = None,
    task: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> MetricCanonicalizationReport:
    root = root.resolve()
    resolved_limit, resolved_offset, warnings = validate_limit_offset(limit, offset)
    try:
        evidence = build_result_evidence_quality(
            root,
            metric=metric,
            dataset=dataset,
            task=task,
            limit=MAX_LIMIT,
            offset=0,
        )
    except (ResultEvidenceCatalogError, ResultEvidenceFilterError) as exc:
        raise MetricCanonicalizationCatalogError(str(exc)) from exc
    evidence_payload = evidence.to_dict()
    warnings.extend(evidence_payload["warnings"])
    items = list(evidence_payload["items"])
    warnings.extend(item_diagnostic_warnings(items))

    repair_by_result_id: dict[str, dict[str, Any]] = {}
    value_repairs: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("metric_value") or "").strip():
            continue
        repair = build_value_repair(item)
        repair_by_result_id[str(item.get("result_id") or "")] = repair
        if repair["repair_status"] == "suggested":
            value_repairs.append(repair)

    canonical_metrics = build_canonical_metrics(items)
    comparability_groups = build_comparability_groups(items, repair_by_result_id)
    timeline_readiness = build_timeline_readiness(canonical_metrics, comparability_groups)
    warnings.extend(canonicalization_warnings(canonical_metrics, timeline_readiness, value_repairs))

    summary = build_summary(
        evidence_payload["summary"],
        items,
        canonical_metrics,
        comparability_groups,
        timeline_readiness,
        value_repairs,
        warnings,
    )
    return MetricCanonicalizationReport(
        root=root.as_posix(),
        query={
            "metric": metric or "",
            "dataset": dataset or "",
            "task": task or "",
            "limit": resolved_limit,
            "offset": resolved_offset,
        },
        summary=summary,
        canonical_metrics=page(canonical_metrics, resolved_limit, resolved_offset),
        comparability_groups=page(comparability_groups, resolved_limit, resolved_offset),
        timeline_readiness=page(timeline_readiness, resolved_limit, resolved_offset),
        value_repairs=page(value_repairs, resolved_limit, resolved_offset),
        warnings=dedupe_warnings(warnings),
    )


def normalize_canonical_metric_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("&", " and ")
    tokens = re.findall(r"[\w]+", text, flags=re.UNICODE)
    normalized_tokens = [normalize_token(token) for token in tokens if token]
    return "_".join(token for token in normalized_tokens if token)


def normalize_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token


def build_value_repair(row: dict[str, Any]) -> dict[str, Any]:
    result_id = str(row.get("result_id") or "")
    warnings: list[dict[str, Any]] = []
    for source_key in ("metric_raw_value", "claim_text", "context_preview"):
        text = str(row.get(source_key) or "")
        candidates, source_warnings = parse_value_candidates(
            text,
            metric_name=str(row.get("metric_name") or ""),
            source=source_key,
        )
        warnings.extend(source_warnings)
        if not candidates:
            continue
        unique = unique_candidates(candidates)
        if len(unique) > 1:
            warnings.append(
                warning(
                    "multiple_numeric_candidates",
                    f"Multiple numeric candidates found for {result_id}; no value repair suggested.",
                    severity="warning",
                    result_id=result_id,
                )
            )
            return value_repair_payload(result_id, row, "not_repairable", "", "", "", source_key, warnings)
        candidate = unique[0]
        confidence = "high" if source_key == "metric_raw_value" else "medium"
        return value_repair_payload(
            result_id,
            row,
            "suggested",
            candidate["value"],
            candidate["unit"],
            candidate["value_scale"],
            source_key,
            warnings,
            confidence=confidence,
            raw_candidate=candidate["raw"],
        )
    if is_placeholder_value(str(row.get("metric_raw_value") or "")):
        warnings.append(warning("placeholder_value", f"Placeholder metric value for {result_id}.", result_id=result_id))
    return value_repair_payload(result_id, row, "not_repairable", "", "", "", "", warnings)


def value_repair_payload(
    result_id: str,
    row: dict[str, Any],
    repair_status: str,
    suggested_value: str,
    suggested_unit: str,
    value_scale: str,
    suggestion_source: str,
    warnings: list[dict[str, Any]],
    *,
    confidence: str = "",
    raw_candidate: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": METRIC_RESULT_VALUE_REPAIR_SCHEMA_VERSION,
        "result_id": result_id,
        "claim_id": str(row.get("claim_id") or ""),
        "source_id": str(row.get("source_id") or ""),
        "paper_id": str(row.get("paper_id") or ""),
        "metric_name": str(row.get("metric_name") or ""),
        "metric_raw_value": str(row.get("metric_raw_value") or ""),
        "repair_status": repair_status,
        "suggested_metric_value": suggested_value,
        "suggested_metric_unit": suggested_unit,
        "suggested_metric_raw_value": raw_candidate,
        "value_scale": value_scale,
        "suggestion_source": suggestion_source,
        "repair_confidence": confidence,
        "warnings": dedupe_warnings(warnings),
    }


def parse_value_candidates(text: str, *, metric_name: str, source: str) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    compact = " ".join(str(text or "").split())
    if is_placeholder_value(compact):
        return [], [warning("placeholder_value", f"Placeholder value in {source}.")]
    if not compact:
        return [], []

    candidates: list[dict[str, str]] = []
    candidates.extend(parse_percent_values(compact))
    candidates.extend(parse_ratio_values(compact))
    candidates.extend(parse_time_values(compact))
    candidates.extend(parse_cost_values(compact))
    if not candidates:
        candidates.extend(parse_count_values(compact, metric_name=metric_name))
    return candidates, []


def parse_percent_values(text: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    pattern = re.compile(r"(?<![\w.])([-+]?\d+(?:\.\d+)?)\s*(%|percent|percentage points?)", re.IGNORECASE)
    for match in pattern.finditer(text):
        results.append({"value": normalize_number(match.group(1)), "unit": "%", "value_scale": "percent", "raw": match.group(0)})
    return results


def parse_ratio_values(text: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    pattern = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)(?![\w.])")
    for match in pattern.finditer(text):
        denominator = float(match.group(2))
        if denominator == 0:
            continue
        value = float(match.group(1)) / denominator
        results.append({"value": normalize_number(str(value)), "unit": "", "value_scale": "ratio", "raw": match.group(0)})
    return results


def parse_time_values(text: str) -> list[dict[str, str]]:
    unit_map = {
        "s": "s",
        "sec": "s",
        "second": "s",
        "seconds": "s",
        "min": "min",
        "minute": "min",
        "minutes": "min",
        "h": "h",
        "hr": "h",
        "hour": "h",
        "hours": "h",
    }
    pattern = re.compile(
        r"(?<![\w.])([-+]?\d+(?:\.\d+)?)\s*(s|sec|seconds?|min|minutes?|h|hr|hours?)(?![\w.])",
        re.IGNORECASE,
    )
    return [
        {
            "value": normalize_number(match.group(1)),
            "unit": unit_map[match.group(2).casefold()],
            "value_scale": "time",
            "raw": match.group(0),
        }
        for match in pattern.finditer(text)
    ]


def parse_cost_values(text: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for match in re.finditer(r"\$\s*([-+]?\d+(?:\.\d+)?)", text):
        results.append({"value": normalize_number(match.group(1)), "unit": "USD", "value_scale": "cost", "raw": match.group(0)})
    for match in re.finditer(r"(?<![\w.])([-+]?\d+(?:\.\d+)?)\s*(usd|dollars?)(?![\w.])", text, re.IGNORECASE):
        results.append({"value": normalize_number(match.group(1)), "unit": "USD", "value_scale": "cost", "raw": match.group(0)})
    return results


def parse_count_values(text: str, *, metric_name: str) -> list[dict[str, str]]:
    metric_key = normalize_canonical_metric_key(metric_name)
    count_like = any(token in metric_key.split("_") for token in ("count", "number", "step", "task", "episode"))
    if not count_like:
        return []
    results: list[dict[str, str]] = []
    for match in re.finditer(r"(?<![\w.])([-+]?\d+(?:\.\d+)?)(?![\w.%/])", text):
        results.append({"value": normalize_number(match.group(1)), "unit": "", "value_scale": "count", "raw": match.group(0)})
    return results


def normalize_number(value: str) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return (f"{number:.12g}").rstrip("0").rstrip(".")


def unique_candidates(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, str]] = []
    for candidate in candidates:
        key = (candidate["value"], candidate["unit"], candidate["value_scale"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def is_placeholder_value(value: str) -> bool:
    text = " ".join(str(value or "").strip().casefold().split())
    return text in PLACEHOLDER_VALUES


def build_canonical_metrics(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        key = normalize_canonical_metric_key(str(item.get("metric_name") or ""))
        if key:
            groups[key].append(item)

    payloads: list[dict[str, Any]] = []
    for key, group_items in groups.items():
        variants = sorted({str(item.get("metric_name") or "") for item in group_items if item.get("metric_name")}, key=str.casefold)
        display_name = choose_display_name([str(item.get("metric_name") or "") for item in group_items])
        warnings: list[dict[str, Any]] = []
        if is_vague_metric_key(key):
            warnings.append(warning("ambiguous_label", f"Metric label needs canonical review: {display_name}."))
        elif len(variants) > 1:
            warnings.append(warning("metric_variant_grouped", f"Metric variants grouped conservatively: {', '.join(variants)}."))
        payloads.append(
            {
                "schema_version": CANONICAL_METRIC_SCHEMA_VERSION,
                "canonical_metric_key": key,
                "display_name": display_name,
                "variants": variants,
                "row_count": len(group_items),
                "source_count": len({item["source_id"] for item in group_items if item.get("source_id")}),
                "paper_count": len({item["paper_id"] for item in group_items if item.get("paper_id")}),
                "dataset_count": len({normalize_dimension(item.get("dataset")) for item in group_items if item.get("dataset")}),
                "task_count": len({normalize_dimension(item.get("task")) for item in group_items if item.get("task")}),
                "year_count": len({item.get("reported_year") for item in group_items if item.get("reported_year") is not None}),
                "missing_value_count": sum(1 for item in group_items if not item.get("metric_value")),
                "warnings": warnings,
            }
        )
    return sorted(payloads, key=lambda item: (-int(item["row_count"]), str(item["canonical_metric_key"])))


def build_comparability_groups(
    items: list[dict[str, Any]],
    repair_by_result_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        key = comparability_group_key(item, repair_by_result_id.get(str(item.get("result_id") or "")))
        if key:
            groups[key].append(item)

    payloads: list[dict[str, Any]] = []
    for key, group_items in groups.items():
        first = group_items[0]
        repairs = [repair_by_result_id[str(item.get("result_id") or "")] for item in group_items if str(item.get("result_id") or "") in repair_by_result_id]
        suggested_repairs = [repair for repair in repairs if repair["repair_status"] == "suggested"]
        canonical_key = normalize_canonical_metric_key(str(first.get("metric_name") or ""))
        status, blocking_reasons, warnings = readiness_for_group(canonical_key, group_items, suggested_repairs)
        payloads.append(
            {
                "schema_version": METRIC_COMPARABILITY_GROUP_SCHEMA_VERSION,
                "comparability_group_key": key,
                "canonical_metric_key": canonical_key,
                "display_name": choose_display_name([str(item.get("metric_name") or "") for item in group_items]),
                "dataset": str(first.get("dataset") or ""),
                "task": str(first.get("task") or ""),
                "metric_unit": effective_unit(first, repair_by_result_id.get(str(first.get("result_id") or ""))),
                "metric_direction": str(first.get("metric_direction") or ""),
                "value_scale": effective_value_scale(first, repair_by_result_id.get(str(first.get("result_id") or ""))),
                "row_count": len(group_items),
                "source_count": len({item["source_id"] for item in group_items if item.get("source_id")}),
                "paper_count": len({item["paper_id"] for item in group_items if item.get("paper_id")}),
                "year_count": len({item.get("reported_year") for item in group_items if item.get("reported_year") is not None}),
                "missing_value_count": sum(1 for item in group_items if not item.get("metric_value")),
                "value_repair_suggestion_count": len(suggested_repairs),
                "readiness_status": status,
                "blocking_reasons": blocking_reasons,
                "warnings": warnings,
            }
        )
    return sorted(payloads, key=lambda item: (-int(item["row_count"]), str(item["comparability_group_key"])))


def comparability_group_key(item: dict[str, Any], repair: dict[str, Any] | None) -> str:
    metric_key = normalize_canonical_metric_key(str(item.get("metric_name") or ""))
    if not metric_key:
        return ""
    parts = [
        metric_key,
        normalize_dimension(item.get("dataset")),
        normalize_dimension(item.get("task")),
        normalize_dimension(effective_unit(item, repair)),
        normalize_dimension(item.get("metric_direction")),
        normalize_dimension(effective_value_scale(item, repair)),
    ]
    return "|".join(parts)


def effective_unit(item: dict[str, Any], repair: dict[str, Any] | None) -> str:
    if str(item.get("metric_unit") or "").strip():
        return str(item.get("metric_unit") or "")
    if repair and repair.get("repair_status") == "suggested":
        return str(repair.get("suggested_metric_unit") or "")
    return ""


def effective_value_scale(item: dict[str, Any], repair: dict[str, Any] | None) -> str:
    if repair and repair.get("repair_status") == "suggested":
        return str(repair.get("value_scale") or "")
    unit = str(item.get("metric_unit") or "").strip().casefold()
    value = str(item.get("metric_value") or "").strip()
    raw_value = str(item.get("metric_raw_value") or "").strip()
    if unit == "%":
        return "percent"
    if unit in {"s", "sec", "second", "seconds", "min", "minute", "minutes", "h", "hr", "hour", "hours"}:
        return "time"
    if unit in {"usd", "$"}:
        return "cost"
    if "/" in raw_value:
        return "ratio"
    if value:
        return "raw_number"
    return ""


def readiness_for_group(
    canonical_key: str,
    items: list[dict[str, Any]],
    suggested_repairs: list[dict[str, Any]],
) -> tuple[str, list[str], list[dict[str, Any]]]:
    if not items:
        return "not_ready_empty", ["empty"], []
    paper_count = len({item.get("paper_id") for item in items if item.get("paper_id")})
    if paper_count < 2:
        return "not_ready_single_paper", ["single_paper"], []
    if is_vague_metric_key(canonical_key):
        return "needs_canonical_review", ["ambiguous_label"], [
            warning("ambiguous_label", f"Metric key {canonical_key} needs canonical review.")
        ]
    year_count = len({item.get("reported_year") for item in items if item.get("reported_year") is not None})
    if year_count < 2:
        return "needs_year_repair", ["missing_year"], []
    missing_value_count = sum(1 for item in items if not item.get("metric_value"))
    if missing_value_count:
        if missing_value_count == len(suggested_repairs):
            return "ready_after_value_repair", ["missing_value_repair_available"], []
        return "needs_value_repair", ["missing_value"], []
    return "strict_ready", [], []


def build_timeline_readiness(
    canonical_metrics: list[dict[str, Any]],
    comparability_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    readiness: list[dict[str, Any]] = [
        {
            "schema_version": METRIC_TIMELINE_READINESS_SCHEMA_VERSION,
            "canonical_metric_key": str(group["canonical_metric_key"]),
            "display_name": str(group["display_name"]),
            "comparability_group_key": str(group["comparability_group_key"]),
            "dataset": str(group["dataset"]),
            "task": str(group["task"]),
            "metric_unit": str(group["metric_unit"]),
            "metric_direction": str(group["metric_direction"]),
            "value_scale": str(group["value_scale"]),
            "row_count": int(group["row_count"]),
            "paper_count": int(group["paper_count"]),
            "year_count": int(group["year_count"]),
            "missing_value_count": int(group["missing_value_count"]),
            "value_repair_suggestion_count": int(group["value_repair_suggestion_count"]),
            "readiness_status": str(group["readiness_status"]),
            "blocking_reasons": list(group["blocking_reasons"]),
            "warnings": list(group["warnings"]),
        }
        for group in comparability_groups
    ]
    grouped_by_metric: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in comparability_groups:
        grouped_by_metric[str(group["canonical_metric_key"])].append(group)
    for metric in canonical_metrics:
        key = str(metric["canonical_metric_key"])
        groups = grouped_by_metric.get(key, [])
        normal_group_count = sum(1 for group in groups if int(group["paper_count"]) >= 2)
        has_ready_group = any(
            group["readiness_status"] in {"strict_ready", "ready_after_value_repair"} for group in groups
        )
        if int(metric["paper_count"]) >= 2 and normal_group_count > 1 and not has_ready_group:
            readiness.append(
                {
                    "schema_version": METRIC_TIMELINE_READINESS_SCHEMA_VERSION,
                    "canonical_metric_key": key,
                    "display_name": str(metric["display_name"]),
                    "comparability_group_key": "",
                    "dataset": "",
                    "task": "",
                    "metric_unit": "",
                    "metric_direction": "",
                    "value_scale": "",
                    "row_count": int(metric["row_count"]),
                    "paper_count": int(metric["paper_count"]),
                    "year_count": int(metric["year_count"]),
                    "missing_value_count": int(metric["missing_value_count"]),
                    "value_repair_suggestion_count": 0,
                    "readiness_status": "discoverable_not_comparable",
                    "blocking_reasons": ["multiple_incompatible_groups"],
                    "warnings": [warning("discoverable_not_comparable", f"Metric {key} spans incompatible groups.")],
                }
            )
    return sorted(readiness, key=lambda item: readiness_sort_key(item))


def readiness_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    priority = {
        "strict_ready": 0,
        "ready_after_value_repair": 1,
        "discoverable_not_comparable": 2,
        "needs_canonical_review": 3,
        "needs_value_repair": 4,
        "needs_year_repair": 5,
        "not_ready_single_paper": 6,
        "not_ready_empty": 7,
    }
    return (
        priority.get(str(item.get("readiness_status") or ""), 99),
        -int(item.get("row_count") or 0),
        str(item.get("canonical_metric_key") or ""),
    )


def build_summary(
    evidence_summary: dict[str, Any],
    items: list[dict[str, Any]],
    canonical_metrics: list[dict[str, Any]],
    comparability_groups: list[dict[str, Any]],
    timeline_readiness: list[dict[str, Any]],
    value_repairs: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    readiness_counts = Counter(str(item["readiness_status"]) for item in timeline_readiness)
    return {
        "result_count": int(evidence_summary.get("metric_result_count") or len(items)),
        "joined_result_count": int(evidence_summary.get("joined_result_count") or 0),
        "resolvable_locator_count": int(evidence_summary.get("resolvable_locator_count") or 0),
        "context_available_count": int(evidence_summary.get("context_available_count") or 0),
        "source_count": int(evidence_summary.get("source_count") or 0),
        "paper_count": int(evidence_summary.get("paper_count") or 0),
        "canonical_metric_count_unpaged": len(canonical_metrics),
        "comparability_group_count_unpaged": len(comparability_groups),
        "timeline_readiness_count_unpaged": len(timeline_readiness),
        "value_repair_count_unpaged": len(value_repairs),
        "strict_ready_count": readiness_counts.get("strict_ready", 0),
        "ready_after_value_repair_count": readiness_counts.get("ready_after_value_repair", 0),
        "discoverable_not_comparable_count": readiness_counts.get("discoverable_not_comparable", 0),
        "needs_canonical_review_count": readiness_counts.get("needs_canonical_review", 0),
        "needs_value_repair_count": readiness_counts.get("needs_value_repair", 0),
        "needs_year_repair_count": readiness_counts.get("needs_year_repair", 0),
        "not_ready_single_paper_count": readiness_counts.get("not_ready_single_paper", 0),
        "not_ready_empty_count": readiness_counts.get("not_ready_empty", 0),
        "missing_normalized_value_count": int(evidence_summary.get("missing_normalized_value_count") or 0),
        "parser_backend_result_counts": dict(evidence_summary.get("parser_backend_result_counts") or {}),
        "parser_fallback_result_count": int(evidence_summary.get("parser_fallback_result_count") or 0),
        "result_error_count": int(evidence_summary.get("error_count") or 0),
        "warning_count": len(dedupe_warnings(warnings)),
    }


def choose_display_name(values: list[str]) -> str:
    filtered = [value for value in values if value]
    if not filtered:
        return ""
    counts = Counter(filtered)
    return sorted(counts, key=lambda value: (-counts[value], value.casefold(), value))[0]


def normalize_dimension(value: Any) -> str:
    return normalize_canonical_metric_key(str(value or "")) or "unknown"


def is_vague_metric_key(key: str) -> bool:
    tokens = set((key or "").split("_"))
    return bool(tokens) and tokens <= VAGUE_LABEL_KEYS


def item_diagnostic_warnings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in items:
        for diagnostic_item in item.get("diagnostics", []):
            code = str(diagnostic_item.get("code") or "")
            if not code:
                continue
            warnings.append(
                warning(
                    code,
                    str(diagnostic_item.get("message") or code),
                    severity=str(diagnostic_item.get("severity") or "warning"),
                    result_id=str(item.get("result_id") or ""),
                )
            )
        if has_diagnostic(item, "missing_claim_join") or has_diagnostic(item, "missing_source_join"):
            warnings.append(
                warning(
                    "join_unavailable_for_repair",
                    f"Result {item.get('result_id')} is excluded from durable repair suggestions.",
                    severity="warning",
                    result_id=str(item.get("result_id") or ""),
                )
            )
    return warnings


def canonicalization_warnings(
    canonical_metrics: list[dict[str, Any]],
    timeline_readiness: list[dict[str, Any]],
    value_repairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for metric in canonical_metrics:
        warnings.extend(metric.get("warnings") or [])
    for item in timeline_readiness:
        warnings.extend(item.get("warnings") or [])
    for repair in value_repairs:
        warnings.extend(repair.get("warnings") or [])
    return warnings


def warning(code: str, message: str, *, severity: str = "warning", result_id: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": METRIC_CANONICALIZATION_WARNING_SCHEMA_VERSION,
        "code": code,
        "severity": severity,
        "message": message,
    }
    if result_id:
        payload["result_id"] = result_id
    return payload


def dedupe_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in warnings:
        code = str(item.get("code") or "")
        message = str(item.get("message") or "")
        result_id = str(item.get("result_id") or "")
        key = (code, message, result_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def page(items: list[dict[str, Any]], limit: int, offset: int) -> list[dict[str, Any]]:
    return items[offset : offset + limit]
