from __future__ import annotations

import json
from typing import Any

from .timeline import MetricListResponse, MetricTimelineResponse


def format_metric_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def metric_list_payload(response: MetricListResponse) -> dict[str, Any]:
    return response.to_dict()


def metric_timeline_payload(response: MetricTimelineResponse) -> dict[str, Any]:
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
