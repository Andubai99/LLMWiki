from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..corpus.inventory import build_inventory
from ..db import catalog_path, connect, schema_status
from ..workspace import utc_now


METRIC_TIMELINE_SCHEMA_VERSION = "metric_timeline.v4.4"
METRIC_TIMELINE_ITEM_SCHEMA_VERSION = "metric_timeline_item.v4.4"
METRIC_LIST_SCHEMA_VERSION = "metric_list.v4.4"

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class TimelineFilterError(ValueError):
    """Invalid metric timeline filter."""


class TimelineCatalogError(RuntimeError):
    """Catalog is unavailable or incompatible with V4.4 timeline queries."""


@dataclass
class MetricTimelineResponse:
    root: str
    query: dict[str, Any]
    items: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = METRIC_TIMELINE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "generated_at": self.generated_at,
            "query": self.query,
            "item_count": len(self.items),
            "warning_count": len(self.warnings),
            "items": self.items,
            "warnings": self.warnings,
        }


@dataclass
class MetricListResponse:
    root: str
    query: dict[str, Any]
    metrics: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = METRIC_LIST_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "generated_at": self.generated_at,
            "query": self.query,
            "metric_count": len(self.metrics),
            "warning_count": len(self.warnings),
            "metrics": self.metrics,
            "warnings": self.warnings,
        }


def normalize_timeline_key(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").casefold().strip())
    text = text.replace("_", "")
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE)


def display_key(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold().strip())


def matches_filter(value: str, query: str | None) -> bool:
    if not query:
        return True
    return display_key(value) == display_key(query) or normalize_timeline_key(value) == normalize_timeline_key(query)


def validate_limit_offset(limit: int | None, offset: int | None) -> tuple[int, int, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    resolved_limit = DEFAULT_LIMIT if limit is None else int(limit)
    resolved_offset = 0 if offset is None else int(offset)
    if resolved_limit <= 0:
        raise TimelineFilterError("invalid limit: must be positive")
    if resolved_offset < 0:
        raise TimelineFilterError("invalid offset: must be >= 0")
    if resolved_limit > MAX_LIMIT:
        warnings.append(
            {
                "code": "limit_clamped",
                "message": f"Limit clamped from {resolved_limit} to {MAX_LIMIT}.",
            }
        )
        resolved_limit = MAX_LIMIT
    return resolved_limit, resolved_offset, warnings


def build_metric_list(
    root: Path,
    *,
    query: str | None = None,
    dataset: str | None = None,
    task: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> MetricListResponse:
    root = root.resolve()
    resolved_limit, resolved_offset, warnings = validate_limit_offset(limit, offset)
    rows, row_warnings = load_joined_metric_rows(root)
    warnings.extend(row_warnings)
    rows = [
        row
        for row in rows
        if matches_filter(row["metric_name"], query)
        and matches_filter(row["dataset"], dataset)
        and matches_filter(row["task"], task)
    ]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = normalize_timeline_key(row["metric_name"])
        if key:
            grouped[key].append(row)

    metrics = [metric_group_payload(key, group) for key, group in grouped.items()]
    metrics.sort(
        key=lambda item: (
            -int(item["row_count"]),
            -int(item["source_count"]),
            str(item["metric_name"]).casefold(),
            str(item["normalized_metric"]),
        )
    )
    metrics = metrics[resolved_offset : resolved_offset + resolved_limit]
    return MetricListResponse(
        root=root.as_posix(),
        query={
            "query": query or "",
            "dataset": dataset or "",
            "task": task or "",
            "limit": resolved_limit,
            "offset": resolved_offset,
        },
        metrics=metrics,
        warnings=warnings,
    )


def build_metric_timeline(
    root: Path,
    *,
    metric: str,
    dataset: str | None = None,
    task: str | None = None,
    method: str | None = None,
    source_id: str | None = None,
    paper_id: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> MetricTimelineResponse:
    root = root.resolve()
    resolved_limit, resolved_offset, warnings = validate_limit_offset(limit, offset)
    if year_from is not None and year_to is not None and year_from > year_to:
        raise TimelineFilterError("invalid year range: year-from must be <= year-to")
    rows, row_warnings = load_joined_metric_rows(root)
    warnings.extend(row_warnings)
    matched: list[dict[str, Any]] = []
    missing_year_skipped = 0
    for row in rows:
        if not matches_filter(row["metric_name"], metric):
            continue
        if not matches_filter(row["dataset"], dataset):
            continue
        if not matches_filter(row["task"], task):
            continue
        if not matches_filter(row["method"], method):
            continue
        if source_id and row["source_id"] != source_id:
            continue
        if paper_id and row["paper_id"] != paper_id:
            continue
        timeline_year = row["timeline_year"]
        if year_from is not None or year_to is not None:
            if timeline_year is None:
                missing_year_skipped += 1
                continue
            if year_from is not None and timeline_year < year_from:
                continue
            if year_to is not None and timeline_year > year_to:
                continue
        matched.append(row)

    warnings.extend(metric_variant_warnings(matched))
    warnings.extend(duplicate_warnings(matched))
    if missing_year_skipped:
        warnings.append(
            {
                "code": "missing_year",
                "message": f"{missing_year_skipped} rows skipped because timeline year is missing.",
            }
        )

    matched.sort(key=timeline_sort_key)
    paged = matched[resolved_offset : resolved_offset + resolved_limit]
    items = [timeline_item(row) for row in paged]
    if not items:
        warnings.append(
            {
                "code": "no_catalog_backed_result",
                "message": f"No catalog-backed result claim found for metric: {metric}",
            }
        )

    return MetricTimelineResponse(
        root=root.as_posix(),
        query={
            "metric": metric,
            "normalized_metric": normalize_timeline_key(metric),
            "dataset": dataset or "",
            "task": task or "",
            "method": method or "",
            "source_id": source_id or "",
            "paper_id": paper_id or "",
            "year_from": year_from,
            "year_to": year_to,
            "limit": resolved_limit,
            "offset": resolved_offset,
        },
        items=items,
        warnings=warnings,
    )


def load_joined_metric_rows(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ok, problems = schema_status(catalog_path(root))
    if not ok:
        raise TimelineCatalogError("; ".join(problems) or "catalog unavailable")

    paper_by_source = {paper["source_id"]: paper for paper in build_inventory(root).to_dict()["papers"]}
    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    with connect(catalog_path(root)) as conn:
        raw_rows = conn.execute(
            """
            select
                mr.*,
                c.claim_id as joined_claim_id,
                c.claim_text as joined_claim_text,
                c.citation_locator as joined_citation_locator,
                c.confidence_status as joined_confidence_status,
                s.source_id as joined_source_id,
                s.title as source_title,
                s.imported_at as source_imported_at,
                p.path as catalog_page_path
            from metric_results mr
            left join claims c
                on c.claim_id = mr.claim_id
                and c.source_id = mr.source_id
            left join sources s
                on s.source_id = mr.source_id
            left join pages p
                on p.page_type = 'source'
                and (p.page_id = mr.source_id or p.path = 'wiki/sources/' || mr.source_id || '.md')
            order by mr.created_at, mr.result_id
            """
        ).fetchall()

    for row in raw_rows:
        data = dict(row)
        if not data.get("joined_claim_id"):
            warnings.append(
                {
                    "code": "missing_claim_join",
                    "message": f"Metric result does not join to a formal claim: {data.get('result_id') or ''}",
                    "result_id": data.get("result_id") or "",
                    "claim_id": data.get("claim_id") or "",
                    "source_id": data.get("source_id") or "",
                }
            )
            continue
        if not data.get("joined_source_id"):
            warnings.append(
                {
                    "code": "missing_source_join",
                    "message": f"Metric result does not join to a source: {data.get('result_id') or ''}",
                    "result_id": data.get("result_id") or "",
                    "claim_id": data.get("claim_id") or "",
                    "source_id": data.get("source_id") or "",
                }
            )
            continue
        paper = paper_by_source.get(str(data.get("paper_id") or data.get("source_id") or ""), {})
        rows.append(normalize_row(data, paper, warnings))
    return rows, warnings


def normalize_row(data: dict[str, Any], paper: dict[str, Any], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    row = dict(data)
    row["paper_title"] = str(paper.get("title") or row.get("source_title") or "")
    row["authors"] = list(paper.get("authors") or [])
    row["year"] = paper.get("year")
    row["doi"] = str(paper.get("doi") or "")
    row["arxiv_id"] = str(paper.get("arxiv_id") or "")
    row["page_path"] = str(paper.get("page_path") or row.get("catalog_page_path") or "")
    row["source_title"] = str(row.get("source_title") or row["paper_title"])
    row["evidence_block_ids"] = parse_json_list(row, "evidence_block_ids", warnings)
    row["evidence_pages"] = parse_json_list(row, "evidence_pages", warnings)
    row["warnings"] = parse_json_list(row, "warnings", warnings)
    row["reported_year"] = row.get("reported_year")
    row["timeline_year"] = row.get("reported_year") if row.get("reported_year") is not None else row.get("year")
    return row


def parse_json_list(row: dict[str, Any], field_name: str, warnings: list[dict[str, Any]]) -> list[Any]:
    value = row.get(field_name)
    if value in (None, ""):
        return []
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError as exc:
        warnings.append(
            {
                "code": "malformed_metric_result_json",
                "message": f"Malformed JSON field {field_name} for {row.get('result_id') or ''}: {exc.msg}",
                "result_id": row.get("result_id") or "",
                "claim_id": row.get("claim_id") or "",
                "source_id": row.get("source_id") or "",
            }
        )
        return []
    if isinstance(data, list):
        return data
    warnings.append(
        {
            "code": "malformed_metric_result_json",
            "message": f"Expected list JSON field {field_name} for {row.get('result_id') or ''}",
            "result_id": row.get("result_id") or "",
            "claim_id": row.get("claim_id") or "",
            "source_id": row.get("source_id") or "",
        }
    )
    return []


def metric_group_payload(key: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    display_counts = Counter(str(row.get("metric_name") or "") for row in rows)
    metric_name = sorted(display_counts, key=lambda name: (-display_counts[name], name.casefold(), name))[0]
    years = [row["timeline_year"] for row in rows if row.get("timeline_year") is not None]
    sorted_rows = sorted(rows, key=timeline_sort_key)
    return {
        "metric_name": metric_name,
        "normalized_metric": key,
        "row_count": len(rows),
        "source_count": len({row["source_id"] for row in rows}),
        "paper_count": len({row["paper_id"] for row in rows}),
        "dataset_count": len({row["dataset"] for row in rows if row.get("dataset")}),
        "task_count": len({row["task"] for row in rows if row.get("task")}),
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "example_result_id": sorted_rows[0]["result_id"] if sorted_rows else "",
        "example_claim_id": sorted_rows[0]["claim_id"] if sorted_rows else "",
        "warnings": metric_variant_warnings(rows),
    }


def timeline_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": METRIC_TIMELINE_ITEM_SCHEMA_VERSION,
        "result_id": str(row.get("result_id") or ""),
        "claim_id": str(row.get("claim_id") or ""),
        "source_id": str(row.get("source_id") or ""),
        "paper_id": str(row.get("paper_id") or ""),
        "source_title": str(row.get("source_title") or ""),
        "paper_title": str(row.get("paper_title") or ""),
        "authors": list(row.get("authors") or []),
        "year": row.get("year"),
        "reported_year": row.get("reported_year"),
        "timeline_year": row.get("timeline_year"),
        "doi": str(row.get("doi") or ""),
        "arxiv_id": str(row.get("arxiv_id") or ""),
        "page_path": str(row.get("page_path") or ""),
        "claim_text": str(row.get("claim_text") or ""),
        "citation_locator": str(row.get("citation_locator") or ""),
        "confidence_status": str(row.get("confidence_status") or ""),
        "method": str(row.get("method") or ""),
        "dataset": str(row.get("dataset") or ""),
        "task": str(row.get("task") or ""),
        "metric_name": str(row.get("metric_name") or ""),
        "metric_value": str(row.get("metric_value") or ""),
        "metric_unit": str(row.get("metric_unit") or ""),
        "metric_raw_value": str(row.get("metric_raw_value") or ""),
        "metric_direction": str(row.get("metric_direction") or ""),
        "baseline": str(row.get("baseline") or ""),
        "comparison_value": str(row.get("comparison_value") or ""),
        "setting": str(row.get("setting") or ""),
        "is_main_result": bool(row["is_main_result"]) if row.get("is_main_result") is not None else None,
        "value_normalization_status": str(row.get("value_normalization_status") or ""),
        "extraction_origin": str(row.get("extraction_origin") or ""),
        "evidence_block_ids": list(row.get("evidence_block_ids") or []),
        "evidence_pages": list(row.get("evidence_pages") or []),
        "warnings": list(row.get("warnings") or []),
        "created_at": str(row.get("created_at") or ""),
    }


def metric_variant_warnings(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    variants_by_key: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        metric_name = str(row.get("metric_name") or "")
        key = normalize_timeline_key(metric_name)
        if key:
            variants_by_key[key].add(metric_name)
    warnings: list[dict[str, Any]] = []
    for key, variants in sorted(variants_by_key.items()):
        if len(variants) > 1:
            ordered = sorted(variants, key=lambda value: (value.casefold(), value))
            warnings.append(
                {
                    "code": "ambiguous_metric_variants",
                    "message": f"Metric variants share normalized key: {', '.join(ordered)}",
                }
            )
    return warnings


def duplicate_warnings(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = str(row.get("metric_value") or row.get("metric_raw_value") or "")
        key = (
            str(row.get("source_id") or ""),
            normalize_timeline_key(str(row.get("metric_name") or "")),
            normalize_timeline_key(str(row.get("method") or "")),
            normalize_timeline_key(str(row.get("dataset") or "")),
            normalize_timeline_key(str(row.get("task") or "")),
            value.casefold(),
            str(row.get("citation_locator") or ""),
        )
        grouped[key].append(row)
    warnings: list[dict[str, Any]] = []
    for group in grouped.values():
        if len(group) <= 1:
            continue
        result_ids = sorted(str(row.get("result_id") or "") for row in group)
        warnings.append(
            {
                "code": "duplicate_result_candidate",
                "message": f"Duplicate-looking metric result rows: {', '.join(result_ids)}",
                "result_id": result_ids[0],
                "details": {"result_ids": result_ids},
            }
        )
    return warnings


def timeline_sort_key(row: dict[str, Any]) -> tuple[int, int, str, str, str]:
    year = row.get("timeline_year")
    return (
        1 if year is None else 0,
        int(year) if year is not None else 9999,
        str(row.get("source_title") or row.get("paper_title") or "").casefold(),
        str(row.get("source_id") or ""),
        str(row.get("result_id") or ""),
    )
