from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..corpus.inventory import build_inventory
from ..db import catalog_path, connect
from ..metrics.timeline import matches_filter, normalize_timeline_key
from ..workspace import utc_now
from .result_evidence import (
    ResultEvidenceCatalogError,
    build_item,
    build_summary,
    clip_text,
    has_diagnostic,
    load_metric_result_rows,
    load_parser_diagnostics,
)


CORPUS_RESULTS_EVAL_SCHEMA_VERSION = "corpus_results_eval.v4.6"
CORPUS_RESULTS_PAPER_SCHEMA_VERSION = "corpus_results_paper.v4.6"
CORPUS_RESULTS_METRIC_SCHEMA_VERSION = "corpus_results_metric.v4.6"
CORPUS_RESULTS_WARNING_SCHEMA_VERSION = "corpus_results_warning.v4.6"

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000


class CorpusResultsFilterError(ValueError):
    """Invalid corpus results eval filter."""


class CorpusResultsCatalogError(RuntimeError):
    """Catalog is unavailable or incompatible with V4.6 corpus results eval."""


@dataclass
class CorpusResultsEvalResponse:
    root: str
    query: dict[str, Any]
    summary: dict[str, Any]
    quality_gates: list[dict[str, Any]]
    papers: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    timeline_readiness: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = CORPUS_RESULTS_EVAL_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "generated_at": self.generated_at,
            "query": self.query,
            "summary": self.summary,
            "quality_gates": self.quality_gates,
            "papers": self.papers,
            "metrics": self.metrics,
            "timeline_readiness": self.timeline_readiness,
            "warnings": self.warnings,
        }


def validate_limit_offset(limit: int | None, offset: int | None) -> tuple[int, int, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    resolved_limit = DEFAULT_LIMIT if limit is None else int(limit)
    resolved_offset = 0 if offset is None else int(offset)
    if resolved_limit <= 0:
        raise CorpusResultsFilterError("invalid limit: must be positive")
    if resolved_offset < 0:
        raise CorpusResultsFilterError("invalid offset: must be >= 0")
    if resolved_limit > MAX_LIMIT:
        warnings.append(warning("limit_clamped", "warning", f"Limit clamped from {resolved_limit} to {MAX_LIMIT}."))
        resolved_limit = MAX_LIMIT
    return resolved_limit, resolved_offset, warnings


def build_corpus_results_eval(
    root: Path,
    *,
    metric: str | None = None,
    dataset: str | None = None,
    task: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> CorpusResultsEvalResponse:
    root = root.resolve()
    resolved_limit, resolved_offset, warnings = validate_limit_offset(limit, offset)
    try:
        inventory = build_inventory(root).to_dict()
        rows = load_metric_result_rows(root)
    except ResultEvidenceCatalogError as exc:
        raise CorpusResultsCatalogError(str(exc)) from exc

    paper_by_id = {
        str(paper.get("paper_id") or paper.get("source_id") or ""): paper
        for paper in inventory.get("papers", [])
    }
    parser_diagnostics = load_parser_diagnostics(root, rows)
    filtered_rows = [
        row
        for row in rows
        if matches_filter(row["metric_name"], metric)
        and matches_filter(row["dataset"], dataset)
        and matches_filter(row["task"], task)
    ]
    items = [
        build_item(
            root,
            row,
            paper_by_id.get(row["paper_id"]) or paper_by_id.get(row["source_id"]) or {},
            parser_diagnostics,
        )
        for row in filtered_rows
    ]
    result_summary = build_summary(items, parser_diagnostics)
    warnings.extend(inventory_warnings(inventory))
    warnings.extend(item_diagnostic_warnings(items))
    if not inventory.get("papers"):
        warnings.append(warning("no_corpus_sources", "warning", "No catalog-backed corpus sources found."))
    if not items:
        warnings.append(warning("no_catalog_backed_result", "warning", "No catalog-backed metric result rows matched the query."))

    formal_claim_count = count_formal_claims(root, items)
    paper_entries = build_paper_entries(inventory, items)
    metric_entries = build_metric_entries(items)
    timeline_entries = build_timeline_readiness(metric_entries, warnings)
    summary = build_corpus_summary(
        inventory=inventory,
        result_summary=result_summary,
        items=items,
        formal_claim_count=formal_claim_count,
        paper_entries=paper_entries,
        metric_entries=metric_entries,
        timeline_entries=timeline_entries,
        warnings=warnings,
    )
    quality_gates = build_quality_gates(summary)

    return CorpusResultsEvalResponse(
        root=root.as_posix(),
        query={
            "metric": metric or "",
            "dataset": dataset or "",
            "task": task or "",
            "limit": resolved_limit,
            "offset": resolved_offset,
        },
        summary=summary,
        quality_gates=quality_gates,
        papers=page_list(paper_entries, resolved_limit, resolved_offset),
        metrics=page_list(metric_entries, resolved_limit, resolved_offset),
        timeline_readiness=page_list(timeline_entries, resolved_limit, resolved_offset),
        warnings=warnings,
    )


def inventory_warnings(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in inventory.get("warnings", []):
        result.append(warning("inventory_warning", "warning", str(message)))
    for paper in inventory.get("papers", []):
        source_id = str(paper.get("source_id") or "")
        for message in paper.get("warnings", []):
            result.append(warning("paper_identity_warning", "warning", str(message), source_id=source_id))
        for duplicate in paper.get("duplicate_warnings", []):
            result.append(
                warning(
                    str(duplicate.get("code") or "likely_duplicate"),
                    "warning",
                    str(duplicate.get("reason") or "Likely duplicate paper."),
                    source_id=source_id,
                    details=duplicate,
                )
            )
    return result


def item_diagnostic_warnings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        for diagnostic in item.get("diagnostics", []):
            severity = str(diagnostic.get("severity") or "warning")
            if severity not in {"warning", "error"}:
                continue
            result.append(
                warning(
                    str(diagnostic.get("code") or "result_diagnostic"),
                    severity,
                    str(diagnostic.get("message") or diagnostic.get("code") or ""),
                    result_id=str(item.get("result_id") or ""),
                    claim_id=str(item.get("claim_id") or ""),
                    source_id=str(item.get("source_id") or ""),
                )
            )
    return result


def count_formal_claims(root: Path, items: list[dict[str, Any]]) -> int:
    claim_ids = sorted(
        {
            str(item.get("claim_id") or "")
            for item in items
            if item.get("claim_id") and not has_diagnostic(item, "missing_claim_join")
        }
    )
    if not claim_ids:
        return 0
    placeholders = ",".join("?" for _ in claim_ids)
    with connect(catalog_path(root)) as conn:
        row = conn.execute(f"select count(*) as count from claims where claim_id in ({placeholders})", claim_ids).fetchone()
    return int(row["count"] if row else 0)


def build_paper_entries(inventory: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items_by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        key = str(item.get("paper_id") or item.get("source_id") or "")
        if key:
            items_by_paper[key].append(item)

    papers: list[dict[str, Any]] = []
    inventory_papers = {
        str(paper.get("paper_id") or paper.get("source_id") or ""): paper
        for paper in inventory.get("papers", [])
    }
    for paper_id, paper_items in items_by_paper.items():
        inventory_paper = inventory_papers.get(paper_id, {})
        papers.append(paper_payload(paper_id, inventory_paper, paper_items))
    papers.sort(key=lambda paper: (-paper["metric_result_count"], str(paper["title"]).casefold(), str(paper["source_id"])))
    return papers


def paper_payload(paper_id: str, paper: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    item_summary = build_item_counts(items)
    source_id = str(paper.get("source_id") or items[0].get("source_id") or paper_id)
    return {
        "schema_version": CORPUS_RESULTS_PAPER_SCHEMA_VERSION,
        "source_id": source_id,
        "paper_id": paper_id,
        "title": str(paper.get("title") or items[0].get("paper_title") or items[0].get("source_title") or ""),
        "year": paper.get("year") if paper else items[0].get("year"),
        "doi": str(paper.get("doi") or ""),
        "arxiv_id": str(paper.get("arxiv_id") or ""),
        "source_type": str(paper.get("source_type") or items[0].get("source_type") or ""),
        "parser_backend": str(paper.get("parser_backend") or items[0].get("parser_backend") or ""),
        "parser_backend_fallback_from": str(
            paper.get("parser_backend_fallback_from") or items[0].get("parser_backend_fallback_from") or ""
        ),
        "page_path": str(paper.get("page_path") or items[0].get("page_path") or ""),
        "formal_claim_count": len(
            {
                item["claim_id"]
                for item in items
                if item.get("claim_id") and not has_diagnostic(item, "missing_claim_join")
            }
        ),
        **item_summary,
        "metric_count": len({normalize_timeline_key(str(item.get("metric_name") or "")) for item in items if item.get("metric_name")}),
        "timeline_candidate_metric_count": len(
            [
                metric
                for metric in build_metric_entries(items)
                if metric["timeline_candidate"]
            ]
        ),
        "warnings": paper_warning_codes(items),
    }


def build_metric_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        key = normalize_timeline_key(str(item.get("metric_name") or ""))
        if key:
            groups[key].append(item)
    metrics = [metric_payload(key, group) for key, group in groups.items()]
    metrics.sort(
        key=lambda metric: (
            -int(metric["row_count"]),
            -int(metric["paper_count"]),
            str(metric["metric_name"]).casefold(),
            str(metric["normalized_metric"]),
        )
    )
    return metrics


def metric_payload(key: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(item.get("metric_name") or "") for item in items)
    metric_name = sorted(counts, key=lambda name: (-counts[name], name.casefold(), name))[0]
    years = [timeline_year(item) for item in items if timeline_year(item) is not None]
    item_summary = build_item_counts(items)
    row_count = len(items)
    paper_count = len({item["paper_id"] for item in items if item.get("paper_id")})
    dated_count = len(years)
    return {
        "schema_version": CORPUS_RESULTS_METRIC_SCHEMA_VERSION,
        "metric_name": metric_name,
        "normalized_metric": key,
        "row_count": row_count,
        "source_count": len({item["source_id"] for item in items if item.get("source_id")}),
        "paper_count": paper_count,
        "dataset_count": len({item["dataset"] for item in items if item.get("dataset")}),
        "task_count": len({item["task"] for item in items if item.get("task")}),
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "dated_row_count": dated_count,
        "missing_year_count": row_count - dated_count,
        "timeline_candidate": row_count >= 2 and paper_count >= 2,
        **item_summary,
        "example_result_id": str(sorted(items, key=item_sort_key)[0].get("result_id") or ""),
        "example_claim_id": str(sorted(items, key=item_sort_key)[0].get("claim_id") or ""),
        "warnings": metric_warning_codes(items),
    }


def build_timeline_readiness(metric_entries: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeline_entries: list[dict[str, Any]] = []
    for metric in metric_entries:
        if not metric["timeline_candidate"]:
            continue
        entry = dict(metric)
        status = "ready"
        if int(metric["dated_row_count"]) < 2:
            status = "needs_year_repair"
            warnings.append(
                warning(
                    "timeline_candidate_needs_year_repair",
                    "warning",
                    f"Timeline candidate has fewer than two dated rows: {metric['metric_name']}",
                    details={"normalized_metric": metric["normalized_metric"]},
                )
            )
        entry["readiness_status"] = status
        timeline_entries.append(entry)
    timeline_entries.sort(
        key=lambda metric: (
            0 if metric["readiness_status"] == "ready" else 1,
            -int(metric["row_count"]),
            str(metric["metric_name"]).casefold(),
        )
    )
    return timeline_entries


def build_corpus_summary(
    *,
    inventory: dict[str, Any],
    result_summary: dict[str, Any],
    items: list[dict[str, Any]],
    formal_claim_count: int,
    paper_entries: list[dict[str, Any]],
    metric_entries: list[dict[str, Any]],
    timeline_entries: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    batch_items = list(inventory.get("batch_items") or [])
    table_blocks, caption_blocks = unique_role_blocks(items)
    summary = dict(result_summary)
    summary.update(
        {
            "source_count": len({paper.get("source_id") for paper in inventory.get("papers", []) if paper.get("source_id")}),
            "paper_count": int(inventory.get("paper_count") or len(inventory.get("papers", []))),
            "batch_item_count": len(batch_items),
            "batch_applied_count": sum(1 for item in batch_items if item.get("status") in {"applied", "already_imported"}),
            "batch_failed_count": sum(1 for item in batch_items if item.get("status") in {"failed", "interrupted"}),
            "batch_pending_count": sum(1 for item in batch_items if item.get("status") in {"pending", "running"}),
            "formal_claim_count": formal_claim_count,
            "durable_metric_result_count": int(result_summary.get("metric_result_count") or 0),
            "unique_table_block_count": len(table_blocks),
            "unique_caption_block_count": len(caption_blocks),
            "metric_list_count": len(metric_entries),
            "timeline_candidate_count": len(timeline_entries),
            "missing_year_count": sum(int(metric["missing_year_count"]) for metric in metric_entries),
            "timeline_candidate_missing_year_count": sum(1 for metric in timeline_entries if int(metric["missing_year_count"]) > 0),
            "paper_count_unpaged": len(paper_entries),
            "metric_count_unpaged": len(metric_entries),
            "timeline_readiness_count_unpaged": len(timeline_entries),
            "warning_count": len([item for item in warnings if item.get("severity") == "warning"]),
            "error_count": int(result_summary.get("error_count") or 0)
            + len([item for item in warnings if item.get("severity") == "error" and item.get("code") not in {"missing_claim_join", "missing_source_join"}]),
        }
    )
    return summary


def build_quality_gates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        gate("catalog_available", "pass", "Catalog schema is available."),
        gate(
            "corpus_sources_present",
            "pass" if summary["source_count"] > 0 else "warn",
            f"Corpus sources: {summary['source_count']}.",
            observed=summary["source_count"],
            threshold=">0",
        ),
        batch_gate(summary),
        gate(
            "no_parser_fallback_results",
            "pass" if summary["parser_fallback_result_count"] == 0 else "fail",
            f"Parser fallback result rows: {summary['parser_fallback_result_count']}.",
            observed=summary["parser_fallback_result_count"],
            threshold=0,
        ),
        gate(
            "metric_results_present",
            "pass" if summary["metric_result_count"] > 0 else "warn",
            f"Metric result rows: {summary['metric_result_count']}.",
            observed=summary["metric_result_count"],
            threshold=">0",
        ),
        all_count_gate(summary, "all_results_joined", "joined_result_count", "metric_result_count"),
        all_count_gate(summary, "all_locators_resolvable", "resolvable_locator_count", "metric_result_count"),
        all_count_gate(summary, "context_available", "context_available_count", "metric_result_count"),
        gate(
            "no_result_errors",
            "pass" if summary["error_count"] == 0 else "fail",
            f"Result evidence errors: {summary['error_count']}.",
            observed=summary["error_count"],
            threshold=0,
        ),
        core_fields_gate(summary),
        gate(
            "table_evidence_present",
            "pass" if summary["table_result_count"] > 0 else "warn",
            f"Table-backed result rows: {summary['table_result_count']}.",
            observed=summary["table_result_count"],
            threshold=">0",
        ),
        gate(
            "timeline_candidates_present",
            "pass" if summary["timeline_candidate_count"] > 0 else "warn",
            f"Timeline candidates: {summary['timeline_candidate_count']}.",
            observed=summary["timeline_candidate_count"],
            threshold=">0",
        ),
    ]


def batch_gate(summary: dict[str, Any]) -> dict[str, Any]:
    total = int(summary["batch_item_count"])
    failed = int(summary["batch_failed_count"])
    pending = int(summary["batch_pending_count"])
    if failed:
        status = "fail"
    elif pending:
        status = "warn"
    else:
        status = "pass"
    return gate(
        "all_batch_items_applied",
        status,
        f"Batch items: {total}; failed/interrupted: {failed}; pending/running: {pending}.",
        observed={"total": total, "failed": failed, "pending": pending},
        threshold="no failed/interrupted/pending/running",
    )


def all_count_gate(summary: dict[str, Any], name: str, observed_key: str, total_key: str) -> dict[str, Any]:
    observed = int(summary[observed_key])
    total = int(summary[total_key])
    status = "pass" if observed == total else "fail"
    return gate(name, status, f"{observed_key}: {observed}/{total}.", observed=observed, threshold=total)


def core_fields_gate(summary: dict[str, Any]) -> dict[str, Any]:
    missing = {
        "method": int(summary["missing_method_count"]),
        "dataset": int(summary["missing_dataset_count"]),
        "task": int(summary["missing_task_count"]),
        "value": int(summary["missing_normalized_value_count"]),
    }
    status = "pass" if all(value == 0 for value in missing.values()) else "warn"
    return gate("core_fields_usable", status, f"Missing core fields: {missing}.", observed=missing, threshold=0)


def build_item_counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "metric_result_count": len(items),
        "joined_result_count": sum(
            1 for item in items if not has_diagnostic(item, "missing_claim_join") and not has_diagnostic(item, "missing_source_join")
        ),
        "resolvable_locator_count": sum(1 for item in items if item["locator_status"] == "resolved"),
        "context_available_count": sum(1 for item in items if item["context_status"] == "available"),
        "table_result_count": sum(1 for item in items if item_has_role(item, "table")),
        "caption_result_count": sum(1 for item in items if item_has_role(item, "caption")),
        "result_text_context_count": sum(1 for item in items if item_has_any_role(item, {"paragraph", "text", "content"})),
        "missing_normalized_value_count": sum(1 for item in items if not item["metric_value"]),
        "missing_method_count": sum(1 for item in items if not item["method"]),
        "missing_dataset_count": sum(1 for item in items if not item["dataset"]),
        "missing_task_count": sum(1 for item in items if not item["task"]),
        "missing_baseline_count": sum(1 for item in items if not item["baseline"]),
    }


def unique_role_blocks(items: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    tables: set[str] = set()
    captions: set[str] = set()
    for item in items:
        block_ids = [str(block_id or "") for block_id in item.get("evidence_block_ids", [])]
        roles = [str(role or "").casefold() for role in item.get("evidence_block_roles", [])]
        for index, block_id in enumerate(block_ids):
            if not block_id:
                continue
            role = roles[index] if index < len(roles) else ""
            if "table" in role:
                tables.add(block_id)
            if "caption" in role:
                captions.add(block_id)
    return tables, captions


def item_has_role(item: dict[str, Any], role: str) -> bool:
    return item_has_any_role(item, {role})


def item_has_any_role(item: dict[str, Any], roles: set[str]) -> bool:
    wanted = {role.casefold() for role in roles}
    item_roles = {str(role or "").casefold() for role in item.get("evidence_block_roles", [])}
    context_role = str(item.get("context_block_role") or "").casefold()
    return context_role in wanted or bool(item_roles & wanted)


def paper_warning_codes(items: list[dict[str, Any]]) -> list[str]:
    return sorted({str(diagnostic.get("code") or "") for item in items for diagnostic in item.get("diagnostics", []) if diagnostic.get("code")})


def metric_warning_codes(items: list[dict[str, Any]]) -> list[str]:
    codes = paper_warning_codes(items)
    variants = {str(item.get("metric_name") or "") for item in items}
    if len(variants) > 1:
        codes.append("ambiguous_metric_variants")
    return sorted(set(codes))


def timeline_year(item: dict[str, Any]) -> int | None:
    value = item.get("reported_year")
    if value is None:
        value = item.get("year")
    if value is None or value == "":
        return None
    return int(value)


def item_sort_key(item: dict[str, Any]) -> tuple[int, int, str, str, str]:
    year = timeline_year(item)
    return (
        1 if year is None else 0,
        year if year is not None else 9999,
        str(item.get("paper_title") or item.get("source_title") or "").casefold(),
        str(item.get("source_id") or ""),
        str(item.get("result_id") or ""),
    )


def page_list(items: list[dict[str, Any]], limit: int, offset: int) -> list[dict[str, Any]]:
    return items[offset : offset + limit]


def warning(
    code: str,
    severity: str,
    message: str,
    *,
    result_id: str = "",
    claim_id: str = "",
    source_id: str = "",
    details: Any | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": CORPUS_RESULTS_WARNING_SCHEMA_VERSION,
        "code": code,
        "severity": severity,
        "message": message,
    }
    if result_id:
        payload["result_id"] = result_id
    if claim_id:
        payload["claim_id"] = claim_id
    if source_id:
        payload["source_id"] = source_id
    if details is not None:
        payload["details"] = details
    return payload


def gate(
    name: str,
    status: str,
    message: str,
    *,
    observed: Any | None = None,
    threshold: Any | None = None,
) -> dict[str, Any]:
    payload = {"name": name, "status": status, "message": message}
    if observed is not None:
        payload["observed"] = observed
    if threshold is not None:
        payload["threshold"] = threshold
    return payload


def format_corpus_results_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_corpus_results(response: CorpusResultsEvalResponse) -> str:
    payload = response.to_dict()
    summary = payload["summary"]
    lines = [
        "Corpus results acceptance",
        f"Sources: {summary['source_count']}",
        f"Papers: {summary['paper_count']}",
        f"Formal claims: {summary['formal_claim_count']}",
        f"Metric results: {summary['metric_result_count']}",
        f"Timeline candidates: {summary['timeline_candidate_count']}",
        f"Warnings: {summary['warning_count']}",
        f"Errors: {summary['error_count']}",
        "",
        "Quality gates",
    ]
    for quality_gate in payload["quality_gates"]:
        lines.append(f"- {quality_gate['name']}: {quality_gate['status']} - {quality_gate['message']}")

    lines.extend(["", "Top papers", "Paper | Results | Claims | Table | Caption | Missing value"])
    if not payload["papers"]:
        lines.append("none | 0 | 0 | 0 | 0 | 0")
    for paper in payload["papers"]:
        lines.append(
            " | ".join(
                [
                    clip_text(paper["title"] or paper["source_id"], 34),
                    str(paper["metric_result_count"]),
                    str(paper["formal_claim_count"]),
                    str(paper["table_result_count"]),
                    str(paper["caption_result_count"]),
                    str(paper["missing_normalized_value_count"]),
                ]
            )
        )

    lines.extend(["", "Top metrics", "Metric | Rows | Papers | Timeline | Table | Caption | Missing value"])
    if not payload["metrics"]:
        lines.append("none | 0 | 0 | | 0 | 0 | 0")
    for metric in payload["metrics"]:
        lines.append(
            " | ".join(
                [
                    clip_text(metric["metric_name"], 28),
                    str(metric["row_count"]),
                    str(metric["paper_count"]),
                    "yes" if metric["timeline_candidate"] else "no",
                    str(metric["table_result_count"]),
                    str(metric["caption_result_count"]),
                    str(metric["missing_normalized_value_count"]),
                ]
            )
        )

    lines.extend(["", "Timeline readiness", "Metric | Rows | Papers | Dated rows | Status"])
    if not payload["timeline_readiness"]:
        lines.append("none | 0 | 0 | 0 |")
    for metric in payload["timeline_readiness"]:
        lines.append(
            " | ".join(
                [
                    clip_text(metric["metric_name"], 28),
                    str(metric["row_count"]),
                    str(metric["paper_count"]),
                    str(metric["dated_row_count"]),
                    metric["readiness_status"],
                ]
            )
        )

    if payload["warnings"]:
        lines.extend(["", "Warnings:"])
        for item in payload["warnings"][:20]:
            lines.append(f"- {item.get('code')}: {item.get('message')}")
        if len(payload["warnings"]) > 20:
            lines.append(f"- ... {len(payload['warnings']) - 20} more warnings")
    return "\n".join(lines)
