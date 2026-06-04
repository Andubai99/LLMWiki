from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..corpus.inventory import build_inventory
from ..db import catalog_path, connect, schema_status
from ..metrics.timeline import matches_filter
from ..workspace import utc_now


RESULT_EVIDENCE_SCHEMA_VERSION = "result_evidence_quality.v4.5"
RESULT_EVIDENCE_ITEM_SCHEMA_VERSION = "result_evidence_item.v4.5"

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
CONTEXT_PREVIEW_CHARS = 500
MAX_SIDECAR_LINES = 20000


class ResultEvidenceFilterError(ValueError):
    """Invalid result evidence eval filter."""


class ResultEvidenceCatalogError(RuntimeError):
    """Catalog is unavailable or incompatible with V4.5 result evidence eval."""


@dataclass
class ResultEvidenceQualityResponse:
    root: str
    query: dict[str, Any]
    summary: dict[str, Any]
    items: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = RESULT_EVIDENCE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "generated_at": self.generated_at,
            "query": self.query,
            "summary": self.summary,
            "item_count": len(self.items),
            "warning_count": len(self.warnings),
            "items": self.items,
            "warnings": self.warnings,
        }


def validate_limit_offset(limit: int | None, offset: int | None) -> tuple[int, int, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    resolved_limit = DEFAULT_LIMIT if limit is None else int(limit)
    resolved_offset = 0 if offset is None else int(offset)
    if resolved_limit <= 0:
        raise ResultEvidenceFilterError("invalid limit: must be positive")
    if resolved_offset < 0:
        raise ResultEvidenceFilterError("invalid offset: must be >= 0")
    if resolved_limit > MAX_LIMIT:
        warnings.append(
            {
                "code": "limit_clamped",
                "severity": "warning",
                "message": f"Limit clamped from {resolved_limit} to {MAX_LIMIT}.",
            }
        )
        resolved_limit = MAX_LIMIT
    return resolved_limit, resolved_offset, warnings


def build_result_evidence_quality(
    root: Path,
    *,
    source_id: str | None = None,
    paper_id: str | None = None,
    metric: str | None = None,
    dataset: str | None = None,
    task: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> ResultEvidenceQualityResponse:
    root = root.resolve()
    resolved_limit, resolved_offset, warnings = validate_limit_offset(limit, offset)
    rows = load_metric_result_rows(root)
    paper_by_source = load_paper_display_metadata(root, warnings)
    parser_diagnostics = load_parser_diagnostics(root, rows)

    filtered: list[dict[str, Any]] = []
    for row in rows:
        if source_id and row["source_id"] != source_id:
            continue
        if paper_id and row["paper_id"] != paper_id:
            continue
        if not matches_filter(row["metric_name"], metric):
            continue
        if not matches_filter(row["dataset"], dataset):
            continue
        if not matches_filter(row["task"], task):
            continue
        filtered.append(row)

    items = [
        build_item(root, row, paper_by_source.get(row["paper_id"]) or paper_by_source.get(row["source_id"]) or {}, parser_diagnostics)
        for row in filtered
    ]
    if not items:
        warnings.append(
            {
                "code": "no_catalog_backed_result",
                "severity": "warning",
                "message": "No catalog-backed metric result rows matched the query.",
            }
        )
    summary = build_summary(items, parser_diagnostics)
    paged_items = items[resolved_offset : resolved_offset + resolved_limit]
    return ResultEvidenceQualityResponse(
        root=root.as_posix(),
        query={
            "source_id": source_id or "",
            "paper_id": paper_id or "",
            "metric": metric or "",
            "dataset": dataset or "",
            "task": task or "",
            "limit": resolved_limit,
            "offset": resolved_offset,
        },
        summary=summary,
        items=paged_items,
        warnings=warnings,
    )


def load_metric_result_rows(root: Path) -> list[dict[str, Any]]:
    ok, problems = schema_status(catalog_path(root))
    if not ok:
        raise ResultEvidenceCatalogError("; ".join(problems) or "catalog unavailable")

    with connect(catalog_path(root)) as conn:
        raw_rows = conn.execute(
            """
            select
                mr.rowid as metric_rowid,
                mr.*,
                c.claim_id as joined_claim_id,
                c.claim_text as joined_claim_text,
                c.citation_locator as joined_citation_locator,
                c.confidence_status as joined_confidence_status,
                s.source_id as joined_source_id,
                s.title as source_title,
                s.source_type as source_type,
                s.normalized_path as source_normalized_path,
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
            order by mr.rowid
            """
        ).fetchall()
    return [normalize_row(dict(row)) for row in raw_rows]


def normalize_row(data: dict[str, Any]) -> dict[str, Any]:
    row = dict(data)
    for key in (
        "result_id",
        "schema_version",
        "claim_id",
        "source_id",
        "paper_id",
        "claim_text",
        "citation_locator",
        "confidence_status",
        "method",
        "dataset",
        "task",
        "metric_name",
        "metric_value",
        "metric_unit",
        "metric_raw_value",
        "metric_direction",
        "baseline",
        "comparison_value",
        "setting",
        "value_normalization_status",
        "extraction_origin",
        "source_title",
        "source_type",
        "source_normalized_path",
        "catalog_page_path",
    ):
        row[key] = str(row.get(key) or "")
    row["warnings"] = parse_json_field(row, "warnings", [])
    row["evidence_block_ids"] = parse_json_field(row, "evidence_block_ids", [])
    row["evidence_pages"] = parse_json_field(row, "evidence_pages", [])
    row["evidence_block_roles"] = parse_json_field(row, "evidence_block_roles", {})
    return row


def parse_json_field(row: dict[str, Any], field_name: str, fallback: Any) -> Any:
    value = row.get(field_name)
    if value in (None, ""):
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def load_paper_display_metadata(root: Path, warnings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    try:
        inventory = build_inventory(root).to_dict()
    except Exception as exc:
        warnings.append(
            {
                "code": "inventory_metadata_unavailable",
                "severity": "warning",
                "message": f"Paper inventory metadata unavailable: {exc}",
            }
        )
        return {}
    return {str(paper.get("paper_id") or paper.get("source_id") or ""): paper for paper in inventory.get("papers", [])}


def load_parser_diagnostics(root: Path, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    diagnostics: dict[str, dict[str, Any]] = {}
    for source_id in sorted({row["source_id"] for row in rows if row.get("source_id")}):
        metadata_path = root / "sources" / "metadata" / f"{source_id}.json"
        if not path_is_under(metadata_path, root / "sources" / "metadata") or not metadata_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            diagnostics[source_id] = {"metadata_status": "malformed", "fallback": False, "warning_count": 1}
            continue
        fallback = bool(metadata.get("parser_backend_fallback_from"))
        parser_warnings = list(metadata.get("parser_backend_warnings") or [])
        parser_quality = metadata.get("parser_quality") if isinstance(metadata.get("parser_quality"), dict) else {}
        warning_count = int(parser_quality.get("warning_count") or 0) + len(parser_warnings)
        if fallback or warning_count or parser_quality.get("issues"):
            diagnostics[source_id] = {
                "metadata_status": "available",
                "fallback": fallback,
                "warning_count": warning_count,
                "parser_backend": str(metadata.get("parser_backend") or ""),
                "parser_backend_fallback_from": str(metadata.get("parser_backend_fallback_from") or ""),
            }
    return diagnostics


def build_item(
    root: Path,
    row: dict[str, Any],
    paper: dict[str, Any],
    parser_diagnostics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    if not row.get("joined_claim_id"):
        diagnostics.append(diagnostic("missing_claim_join", "error", f"Missing formal claim join for {row['result_id']}."))
    if not row.get("joined_source_id"):
        diagnostics.append(diagnostic("missing_source_join", "error", f"Missing source join for {row['result_id']}."))
    if not row.get("metric_value"):
        diagnostics.append(diagnostic("missing_metric_value", "warning", f"Missing normalized metric value for {row['result_id']}."))
    if not row.get("method"):
        diagnostics.append(diagnostic("missing_method", "warning", f"Missing method for {row['result_id']}."))
    if not row.get("dataset"):
        diagnostics.append(diagnostic("missing_dataset", "warning", f"Missing dataset for {row['result_id']}."))
    if not row.get("task"):
        diagnostics.append(diagnostic("missing_task", "warning", f"Missing task for {row['result_id']}."))
    if not row.get("baseline"):
        diagnostics.append(diagnostic("missing_baseline", "info", f"Missing baseline for {row['result_id']}."))

    if row["source_id"] in parser_diagnostics:
        source_diag = parser_diagnostics[row["source_id"]]
        if source_diag.get("fallback"):
            diagnostics.append(
                diagnostic(
                    "parser_fallback_observed",
                    "warning",
                    f"Parser fallback observed for source {row['source_id']}.",
                )
            )
        elif source_diag.get("warning_count"):
            diagnostics.append(
                diagnostic(
                    "parser_warning_observed",
                    "warning",
                    f"Parser warnings observed for source {row['source_id']}.",
                )
            )

    if row.get("joined_claim_id") and row.get("joined_source_id"):
        locator_context = resolve_locator_for_row(root, row)
    else:
        locator_context = unresolved_context(
            [diagnostic("join_unavailable_for_locator", "error", "Locator context skipped because claim or source join is missing.")]
        )
    diagnostics.extend(locator_context.pop("diagnostics", []))

    paper_title = str(paper.get("title") or row.get("source_title") or "")
    item = {
        "schema_version": RESULT_EVIDENCE_ITEM_SCHEMA_VERSION,
        "result_id": row["result_id"],
        "claim_id": row["claim_id"],
        "source_id": row["source_id"],
        "paper_id": row["paper_id"],
        "source_type": row["source_type"],
        "source_title": row["source_title"] or paper_title,
        "paper_title": paper_title,
        "authors": list(paper.get("authors") or []),
        "year": paper.get("year"),
        "doi": str(paper.get("doi") or ""),
        "arxiv_id": str(paper.get("arxiv_id") or ""),
        "page_path": str(paper.get("page_path") or row.get("catalog_page_path") or ""),
        "claim_text": row["claim_text"],
        "citation_locator": row["citation_locator"],
        "confidence_status": row["confidence_status"],
        "method": row["method"],
        "dataset": row["dataset"],
        "task": row["task"],
        "metric_name": row["metric_name"],
        "metric_value": row["metric_value"],
        "metric_unit": row["metric_unit"],
        "metric_raw_value": row["metric_raw_value"],
        "metric_direction": row["metric_direction"],
        "baseline": row["baseline"],
        "comparison_value": row["comparison_value"],
        "setting": row["setting"],
        "reported_year": row.get("reported_year"),
        "is_main_result": bool(row["is_main_result"]) if row.get("is_main_result") is not None else None,
        "value_normalization_status": row["value_normalization_status"],
        "extraction_origin": row["extraction_origin"],
        "evidence_block_ids": list(row.get("evidence_block_ids") or []),
        "evidence_pages": list(row.get("evidence_pages") or []),
        "warnings": list(row.get("warnings") or []),
        **locator_context,
        "diagnostics": diagnostics,
    }
    return item


def resolve_locator_for_row(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    source_type = row.get("source_type")
    if source_type == "pdf":
        return resolve_pdf_locator(root, row["source_id"], row["citation_locator"])
    return resolve_line_locator(
        root,
        source_id=row["source_id"],
        normalized_path=row.get("source_normalized_path") or "",
        locator=row["citation_locator"],
    )


def resolve_pdf_locator(root: Path, source_id: str, locator: str) -> dict[str, Any]:
    page_match = re.search(r"(?:^|;)page:(\d+)(?:;|$)", locator or "")
    block_match = re.search(r"(?:^|;)block:([^;]+)(?:;|$)", locator or "")
    if not page_match or not block_match:
        return unresolved_context([diagnostic("unsupported_locator", "error", f"Unsupported PDF locator: {locator}")])
    page = int(page_match.group(1))
    block_id = block_match.group(1).strip()
    if not block_id:
        return unresolved_context([diagnostic("unsupported_locator", "error", f"Unsupported PDF locator: {locator}")])

    block_path = root.resolve() / "sources" / "blocks" / f"{source_id}.jsonl"
    if not path_is_under(block_path, root.resolve() / "sources" / "blocks") or not block_path.exists():
        return unresolved_context([diagnostic("missing_block_sidecar", "error", f"Missing block sidecar for {source_id}.")])

    malformed_count = 0
    with block_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number > MAX_SIDECAR_LINES:
                return unresolved_context(
                    [diagnostic("block_sidecar_scan_limit", "error", f"Block sidecar scan limit exceeded for {source_id}.")]
                )
            if not line.strip():
                continue
            try:
                block = json.loads(line)
            except json.JSONDecodeError:
                malformed_count += 1
                continue
            if str(block.get("block_id") or "") != block_id:
                continue
            if str(block.get("source_id") or source_id) != source_id:
                return unresolved_context(
                    [diagnostic("cross_source_block", "error", f"Block {block_id} belongs to another source.")]
                )
            page_start = block.get("page_start")
            page_end = block.get("page_end") if block.get("page_end") is not None else page_start
            if page_start is not None and page_end is not None and not (int(page_start) <= page <= int(page_end)):
                return unresolved_context([diagnostic("page_mismatch", "error", f"Block {block_id} is not on page {page}.")])
            text = block_text(block)
            diagnostics = []
            if malformed_count:
                diagnostics.append(
                    diagnostic("malformed_block_sidecar", "warning", f"{malformed_count} malformed block rows skipped.")
                )
            return {
                "locator_status": "resolved",
                "context_status": "available" if text else "missing",
                "context_preview": clip_context(text),
                "context_page": page,
                "context_block_id": block_id,
                "context_block_role": str(block.get("block_type") or block.get("content_role") or ""),
                "context_content_role": str(block.get("content_role") or ""),
                "context_section_path": list(block.get("section_path") or []),
                "diagnostics": diagnostics,
            }
    diagnostics = []
    if malformed_count:
        diagnostics.append(diagnostic("malformed_block_sidecar", "warning", f"{malformed_count} malformed block rows skipped."))
    diagnostics.append(diagnostic("missing_block_id", "error", f"Block id not found: {block_id}"))
    return unresolved_context(diagnostics)


def resolve_line_locator(root: Path, *, source_id: str, normalized_path: str, locator: str) -> dict[str, Any]:
    match = re.fullmatch(r"line:(\d+)", (locator or "").strip())
    if not match:
        return unresolved_context([diagnostic("unsupported_locator", "error", f"Unsupported line locator: {locator}")])
    line_number = int(match.group(1))
    normalized_root = root.resolve() / "sources" / "normalized"
    path = (root.resolve() / normalized_path).resolve()
    if not path_is_under(path, normalized_root) or not path.exists() or not path.is_file():
        return unresolved_context(
            [diagnostic("missing_normalized_source", "error", f"Missing bounded normalized source for {source_id}.")]
        )
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return unresolved_context([diagnostic("missing_normalized_source", "error", f"Cannot read normalized source: {exc}")])
    if line_number < 1 or line_number > len(lines):
        return unresolved_context([diagnostic("line_out_of_range", "error", f"Line {line_number} is outside normalized source.")])
    start = max(0, line_number - 3)
    end = min(len(lines), line_number + 2)
    preview = "\n".join(lines[start:end])
    return {
        "locator_status": "resolved",
        "context_status": "available" if preview else "missing",
        "context_preview": clip_context(preview),
        "context_page": None,
        "context_block_id": "",
        "context_block_role": "",
        "context_content_role": "",
        "context_section_path": [],
        "diagnostics": [],
    }


def block_text(block: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("text_clean", "text_raw", "table_markdown", "markdown"):
        value = str(block.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)
    return "\n".join(parts)


def unresolved_context(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "locator_status": "unresolved",
        "context_status": "missing",
        "context_preview": "",
        "context_page": None,
        "context_block_id": "",
        "context_block_role": "",
        "context_content_role": "",
        "context_section_path": [],
        "diagnostics": diagnostics,
    }


def build_summary(items: list[dict[str, Any]], parser_diagnostics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    diagnostic_counts: dict[str, int] = {}
    warning_count = 0
    error_count = 0
    info_count = 0
    for item in items:
        for item_diagnostic in item["diagnostics"]:
            code = str(item_diagnostic.get("code") or "")
            diagnostic_counts[code] = diagnostic_counts.get(code, 0) + 1
            severity = item_diagnostic.get("severity")
            if severity == "error":
                error_count += 1
            elif severity == "warning":
                warning_count += 1
            else:
                info_count += 1
    return {
        "source_count": len({item["source_id"] for item in items if item.get("source_id")}),
        "paper_count": len({item["paper_id"] for item in items if item.get("paper_id")}),
        "metric_result_count": len(items),
        "joined_result_count": sum(1 for item in items if not has_diagnostic(item, "missing_claim_join") and not has_diagnostic(item, "missing_source_join")),
        "resolvable_locator_count": sum(1 for item in items if item["locator_status"] == "resolved"),
        "context_available_count": sum(1 for item in items if item["context_status"] == "available"),
        "pdf_result_count": sum(1 for item in items if item["source_type"] == "pdf"),
        "markdown_result_count": sum(1 for item in items if item["source_type"] not in {"", "pdf"}),
        "table_result_count": sum(1 for item in items if item["context_block_role"] == "table"),
        "caption_result_count": sum(1 for item in items if item["context_block_role"] == "caption"),
        "missing_normalized_value_count": sum(1 for item in items if not item["metric_value"]),
        "missing_method_count": sum(1 for item in items if not item["method"]),
        "missing_dataset_count": sum(1 for item in items if not item["dataset"]),
        "missing_task_count": sum(1 for item in items if not item["task"]),
        "missing_baseline_count": sum(1 for item in items if not item["baseline"]),
        "parser_diagnostic_source_count": len(parser_diagnostics),
        "warning_count": warning_count,
        "error_count": error_count,
        "info_count": info_count,
        "diagnostic_counts": dict(sorted(diagnostic_counts.items())),
    }


def has_diagnostic(item: dict[str, Any], code: str) -> bool:
    return any(diagnostic.get("code") == code for diagnostic in item.get("diagnostics", []))


def diagnostic(code: str, severity: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message}


def clip_context(value: str) -> str:
    compact = (value or "").strip()
    if len(compact) <= CONTEXT_PREVIEW_CHARS:
        return compact
    return compact[: CONTEXT_PREVIEW_CHARS - 3].rstrip() + "..."


def path_is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def format_result_evidence_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_result_evidence_quality(response: ResultEvidenceQualityResponse) -> str:
    payload = response.to_dict()
    summary = payload["summary"]
    lines = [
        "Result evidence quality",
        f"Metric results: {summary['metric_result_count']}",
        f"Joined results: {summary['joined_result_count']}",
        f"Resolvable locators: {summary['resolvable_locator_count']}",
        f"Context available: {summary['context_available_count']}",
        f"Warnings: {summary['warning_count']}",
        f"Errors: {summary['error_count']}",
        "",
        "Result | Metric | Value | Source | Locator | Context | Diagnostics",
    ]
    if not payload["items"]:
        lines.append("none | | | | | |")
    for item in payload["items"]:
        diagnostic_codes = ",".join(str(diagnostic.get("code") or "") for diagnostic in item["diagnostics"])
        value = item["metric_raw_value"] or item["metric_value"]
        lines.append(
            " | ".join(
                [
                    clip_text(item["result_id"], 18),
                    clip_text(item["metric_name"], 18),
                    clip_text(value, 12),
                    clip_text(item["source_id"], 16),
                    clip_text(item["citation_locator"], 28),
                    item["context_status"],
                    clip_text(diagnostic_codes, 38),
                ]
            )
        )
    if payload["warnings"]:
        lines.extend(["", "Warnings:"])
        for warning in payload["warnings"]:
            lines.append(f"- {warning.get('message') or warning.get('code')}")
    return "\n".join(lines)


def clip_text(value: object, max_chars: int) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
