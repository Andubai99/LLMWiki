from __future__ import annotations

import json
from typing import Any

from .canonicalization import MetricCanonicalizationReport
from .repair import MetricRepairPlan
from .timeline import MetricListResponse, MetricTimelineResponse


def format_metric_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def metric_list_payload(response: MetricListResponse) -> dict[str, Any]:
    return response.to_dict()


def metric_timeline_payload(response: MetricTimelineResponse) -> dict[str, Any]:
    return response.to_dict()


def metric_canonicalization_payload(response: MetricCanonicalizationReport) -> dict[str, Any]:
    return response.to_dict()


def metric_repair_payload(response: MetricRepairPlan) -> dict[str, Any]:
    return response.to_dict()


def format_metric_list(response: MetricListResponse) -> str:
    payload = response.to_dict()
    lines = [
        "Metric list",
        f"Metrics: {payload['metric_count']}",
        f"Warnings: {payload['warning_count']}",
        "",
        "Metric | Rows | Sources | Papers | Year range",
    ]
    metrics = payload["metrics"]
    if not metrics:
        lines.append("none | 0 | 0 | 0 |")
    for metric in metrics:
        year_min = metric["year_min"]
        year_max = metric["year_max"]
        year_range = ""
        if year_min is not None and year_max is not None:
            year_range = f"{year_min}-{year_max}"
        lines.append(
            " | ".join(
                [
                    clip(str(metric["metric_name"]), 32),
                    str(metric["row_count"]),
                    str(metric["source_count"]),
                    str(metric["paper_count"]),
                    year_range,
                ]
            )
        )
    warning_lines = warning_text_lines(payload["warnings"])
    if warning_lines:
        lines.extend(["", "Warnings:", *warning_lines])
    return "\n".join(lines)


def format_metric_repair_plan(response: MetricRepairPlan) -> str:
    return format_metric_repair_response(response, title="Metric repair plan")


def format_metric_repair_status(response: MetricRepairPlan) -> str:
    return format_metric_repair_response(response, title="Metric repair status")


def format_metric_repair_response(response: MetricRepairPlan, *, title: str) -> str:
    payload = response.to_dict()
    summary = payload["summary"]
    lines = [
        title,
        f"Run: {payload.get('repair_run_id') or 'none'}",
        f"Proposals: {summary.get('proposal_count_unpaged', summary.get('proposal_count', 0))}",
        f"Year repairs: {summary.get('year_repair_proposal_count', 0)}",
        f"Value repairs: {summary.get('value_repair_proposal_count', 0)}",
        f"Metric alias reviews: {summary.get('metric_alias_review_count', 0)}",
        f"Dataset alias reviews: {summary.get('dataset_alias_review_count', 0)}",
        f"Task alias reviews: {summary.get('task_alias_review_count', 0)}",
        f"Blocked vague labels: {summary.get('blocked_vague_label_count', 0)}",
        f"Decisions: {summary.get('decision_count', 0)}",
        "",
        "Projected readiness",
        "Group | Current | Projected | Required proposals",
    ]
    projections = payload["projections"]
    if not projections:
        lines.append("none | | | 0")
    for projection in projections[:20]:
        lines.append(
            " | ".join(
                [
                    clip(str(projection["comparability_group_key"]), 36),
                    str(projection["current_readiness_status"]),
                    str(projection["projected_readiness_status"]),
                    str(len(projection.get("required_proposal_ids") or [])),
                ]
            )
        )

    lines.extend(["", "Top proposals", "Proposal | Type | Status | Risk | Title"])
    proposals = payload["proposals"]
    if not proposals:
        lines.append("none | | | |")
    for proposal in proposals[:20]:
        lines.append(
            " | ".join(
                [
                    clip(str(proposal["proposal_id"]), 18),
                    clip(str(proposal["proposal_type"]), 32),
                    str(proposal["review_status"]),
                    str(proposal["risk_level"]),
                    clip(str(proposal["title"]), 42),
                ]
            )
        )
    warning_lines = warning_text_lines(payload["warnings"])
    if warning_lines:
        lines.extend(["", "Warnings:", *warning_lines[:30]])
    return "\n".join(lines)


def format_metric_canonicalization(response: MetricCanonicalizationReport) -> str:
    payload = response.to_dict()
    summary = payload["summary"]
    query = payload["query"]
    filters = [
        f"{name}={query[name]}"
        for name in ("metric", "dataset", "task")
        if query.get(name)
    ]
    lines = [
        "Metric canonicalization",
        f"Filters: {' '.join(filters) if filters else 'none'}",
        f"Results: {summary['result_count']}",
        f"Canonical metrics: {summary['canonical_metric_count_unpaged']}",
        f"Comparability groups: {summary['comparability_group_count_unpaged']}",
        f"Timeline readiness: strict_ready={summary['strict_ready_count']} ready_after_value_repair={summary['ready_after_value_repair_count']} needs_review={summary['needs_canonical_review_count']}",
        f"Value repairs: {summary['value_repair_count_unpaged']}",
        "",
        "Canonical metric | Rows | Papers | Missing values | Warnings",
    ]
    metrics = payload["canonical_metrics"]
    if not metrics:
        lines.append("none | 0 | 0 | 0 |")
    for metric in metrics[:20]:
        warning_codes = ", ".join(str(warning.get("code") or "") for warning in metric.get("warnings", []))
        lines.append(
            " | ".join(
                [
                    clip(str(metric["display_name"]), 32),
                    str(metric["row_count"]),
                    str(metric["paper_count"]),
                    str(metric["missing_value_count"]),
                    clip(warning_codes, 24),
                ]
            )
        )

    lines.extend(
        [
            "",
            "Timeline readiness",
            "Status | Metric | Dataset | Task | Rows | Papers | Reasons",
        ]
    )
    readiness = payload["timeline_readiness"]
    if not readiness:
        lines.append("not_ready_empty | none | | | 0 | 0 | empty")
    for item in readiness[:20]:
        lines.append(
            " | ".join(
                [
                    str(item["readiness_status"]),
                    clip(str(item["display_name"]), 24),
                    clip(str(item["dataset"]), 18),
                    clip(str(item["task"]), 18),
                    str(item["row_count"]),
                    str(item["paper_count"]),
                    clip(", ".join(item.get("blocking_reasons") or []), 30),
                ]
            )
        )

    repairs = payload["value_repairs"]
    lines.extend(["", "Value repairs", "Result | Metric | Suggested value | Source | Confidence"])
    if not repairs:
        lines.append("none | | | |")
    for repair in repairs[:20]:
        value = repair["suggested_metric_value"]
        unit = repair["suggested_metric_unit"]
        if value and unit and unit not in value:
            value = f"{value}{unit}"
        lines.append(
            " | ".join(
                [
                    clip(str(repair["result_id"]), 18),
                    clip(str(repair["metric_name"]), 24),
                    clip(str(value), 16),
                    str(repair["suggestion_source"]),
                    str(repair["repair_confidence"]),
                ]
            )
        )

    warning_lines = warning_text_lines(payload["warnings"])
    if warning_lines:
        lines.extend(["", "Warnings:", *warning_lines[:30]])
    return "\n".join(lines)


def format_metric_timeline(response: MetricTimelineResponse) -> str:
    payload = response.to_dict()
    query = payload["query"]
    filters = [
        f"{name}={query[name]}"
        for name in ("dataset", "task", "method", "source_id", "paper_id")
        if query.get(name)
    ]
    year_from = query.get("year_from")
    year_to = query.get("year_to")
    if year_from is not None or year_to is not None:
        filters.append(f"year={year_from or ''}-{year_to or ''}")

    lines = [
        f"Metric timeline: {query['metric']}",
        f"Filters: {' '.join(filters) if filters else 'none'}",
        f"Rows: {payload['item_count']}",
        "",
        "Year | Paper | Method | Dataset | Task | Metric | Value | Baseline | Claim | Locator",
    ]
    items = payload["items"]
    if not items:
        lines.append("none | | | | | | | | |")
    for item in items:
        value = item["metric_raw_value"] or item["metric_value"]
        if item["metric_unit"] and item["metric_value"] and item["metric_unit"] not in value:
            value = f"{item['metric_value']}{item['metric_unit']}"
        lines.append(
            " | ".join(
                [
                    str(item["timeline_year"] or ""),
                    clip(str(item["paper_title"] or item["source_title"]), 32),
                    clip(str(item["method"]), 18),
                    clip(str(item["dataset"]), 18),
                    clip(str(item["task"]), 18),
                    clip(str(item["metric_name"]), 18),
                    clip(str(value), 12),
                    clip(str(item["baseline"]), 16),
                    clip(str(item["claim_id"]), 16),
                    clip(str(item["citation_locator"]), 28),
                ]
            )
        )
    warning_lines = warning_text_lines(payload["warnings"])
    if warning_lines:
        lines.extend(["", "Warnings:", *warning_lines])
    return "\n".join(lines)


def warning_text_lines(warnings: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for warning in warnings:
        message = str(warning.get("message") or warning.get("code") or "")
        if message:
            lines.append(f"- {message}")
    return lines


def clip(value: str, max_chars: int) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
