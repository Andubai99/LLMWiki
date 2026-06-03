from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..db import catalog_path, connect
from ..workspace import utc_now
from .identity import (
    DuplicateWarning,
    PaperIdentity,
    basename_text,
    doi_candidates,
    first_arxiv_id,
    first_doi,
    first_value_with_source,
    infer_year,
    normalize_title_key,
)
from .state import list_batch_ids, read_items


INVENTORY_SCHEMA_VERSION = "corpus_inventory.v4.2"


@dataclass
class BatchInventoryItem:
    batch_id: str
    item_id: str
    source_path: str
    source_kind: str
    status: str
    source_id: str = ""
    latest_run_id: str = ""
    parser_requested: str = ""
    parser_backend: str = ""
    attempt_count: int = 0
    failure_reason: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CorpusInventory:
    root: str
    papers: list[PaperIdentity]
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    batch_items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = INVENTORY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        warning_count = len(self.warnings) + sum(len(paper.warnings) + len(paper.duplicate_warnings) for paper in self.papers)
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "generated_at": self.generated_at,
            "paper_count": len(self.papers),
            "warning_count": warning_count,
            "papers": [paper.to_dict() for paper in self.papers],
            "duplicates": self.duplicates,
            "batch_items": self.batch_items,
            "warnings": self.warnings,
        }


def build_inventory(root: Path) -> CorpusInventory:
    root = root.resolve()
    warnings: list[str] = []
    papers: list[PaperIdentity] = []
    db_path = catalog_path(root)
    if db_path.exists():
        with connect(db_path) as conn:
            rows = conn.execute(
                """
                select source_id, title, source_type, raw_path, normalized_path,
                       sha256, url, imported_at, status
                from sources
                order by source_id
                """
            ).fetchall()
            for row in rows:
                page = conn.execute(
                    """
                    select page_id, path
                    from pages
                    where page_type = 'source' and (page_id = ? or path = ?)
                    order by updated_at desc
                    limit 1
                    """,
                    (row["source_id"], f"wiki/sources/{row['source_id']}.md"),
                ).fetchone()
                run = conn.execute(
                    """
                    select run_id, status
                    from ingest_runs
                    where source_id = ?
                    order by applied_at desc, created_at desc
                    limit 1
                    """,
                    (row["source_id"],),
                ).fetchone()
                papers.append(
                    build_paper_identity(
                        root,
                        source=dict(row),
                        page=dict(page) if page else {},
                        run=dict(run) if run else {},
                    )
                )
    else:
        warnings.append(f"missing catalog: {workspace_relative(root, db_path)}")

    duplicates = duplicate_warnings(papers)
    attach_duplicate_warnings(papers, duplicates)
    return CorpusInventory(
        root=root.as_posix(),
        papers=papers,
        duplicates=[warning.to_dict() for warning in duplicates],
        batch_items=batch_inventory_items(root),
        warnings=warnings,
    )


def build_paper_identity(
    root: Path,
    *,
    source: dict[str, Any],
    page: dict[str, Any],
    run: dict[str, Any],
) -> PaperIdentity:
    source_id = str(source["source_id"])
    raw_path = workspace_relative(root, root / str(source["raw_path"]))
    normalized_path = workspace_relative(root, root / str(source["normalized_path"]))
    metadata, metadata_status, metadata_warnings = read_metadata(root, source_id)
    normalized_text, normalized_warning = read_bounded_text(root, normalized_path, root / "sources" / "normalized", limit=12000)

    warnings = [*metadata_warnings]
    if normalized_warning:
        warnings.append(normalized_warning)

    paper_identity = metadata.get("paper_identity", {}) if isinstance(metadata.get("paper_identity"), dict) else {}
    authors = clean_string_list(metadata.get("authors") or paper_identity.get("authors"))
    authors_source = "pdf_metadata" if authors else "unknown"
    venue_or_status = str(paper_identity.get("venue_or_status") or "").strip()
    venue_source = "pdf_metadata" if venue_or_status else "unknown"

    metadata_path = f"sources/metadata/{source_id}.json" if (root / "sources" / "metadata" / f"{source_id}.json").exists() else ""
    blocks_path = f"sources/blocks/{source_id}.jsonl" if (root / "sources" / "blocks" / f"{source_id}.jsonl").exists() else str(metadata.get("blocks_path") or "")
    chunks_path = f"sources/chunks/{source_id}.jsonl" if (root / "sources" / "chunks" / f"{source_id}.jsonl").exists() else str(metadata.get("chunks_path") or "")
    blocks_path = workspace_relative(root, root / blocks_path) if blocks_path else ""
    chunks_path = workspace_relative(root, root / chunks_path) if chunks_path else ""

    raw_filename = basename_text(raw_path)
    metadata_filename = str(metadata.get("filename") or "")
    url = str(source.get("url") or "")
    metadata_text = " ".join(flatten_metadata_strings(metadata))
    arxiv_id, arxiv_source = first_value_with_source(
        [
            ("filename", raw_filename),
            ("pdf_metadata", metadata_filename),
            ("url", url),
            ("pdf_metadata", metadata_text),
            ("normalized_source", normalized_text),
        ],
        first_arxiv_id,
    )
    doi, doi_source = first_value_with_source(
        [
            ("pdf_metadata", metadata_text),
            ("normalized_source", normalized_text),
            ("filename", raw_filename),
            ("pdf_metadata", metadata_filename),
            ("url", url),
        ],
        first_doi,
    )
    all_dois = doi_candidates(metadata_text, normalized_text, raw_filename, metadata_filename, url)
    if len(all_dois) > 1:
        warnings.append(f"Multiple DOI candidates found: {', '.join(all_dois)}")

    year, year_source = infer_year([venue_or_status, metadata_text, normalized_text, str(source.get("title") or "")], arxiv_id)
    title_quality = metadata.get("title_quality", {}) if isinstance(metadata.get("title_quality"), dict) else {}
    title_confidence = title_confidence_from_quality(title_quality, str(source.get("title") or ""))

    identity_status = identity_status_for(str(source.get("source_type") or ""), metadata_status, str(source.get("title") or ""), year, doi, arxiv_id)
    parser_quality = metadata.get("parser_quality", {}) if isinstance(metadata.get("parser_quality"), dict) else {}

    return PaperIdentity(
        source_id=source_id,
        paper_id=source_id,
        source_type=str(source.get("source_type") or ""),
        title=str(source.get("title") or ""),
        title_source="catalog",
        title_confidence=title_confidence,
        authors=authors,
        authors_source=authors_source,
        year=year,
        year_source=year_source,
        venue_or_status=venue_or_status,
        venue_or_status_source=venue_source,
        doi=doi,
        doi_source=doi_source,
        arxiv_id=arxiv_id,
        arxiv_id_source=arxiv_source,
        sha256=str(source.get("sha256") or ""),
        raw_path=raw_path,
        normalized_path=normalized_path,
        metadata_path=metadata_path,
        blocks_path=blocks_path,
        chunks_path=chunks_path,
        page_id=str(page.get("page_id") or ""),
        page_path=workspace_relative(root, root / str(page.get("path") or "")) if page.get("path") else "",
        applied_run_id=str(run.get("run_id") or ""),
        applied_status=str(run.get("status") or ""),
        imported_at=str(source.get("imported_at") or ""),
        parser_backend=str(metadata.get("parser_backend") or ""),
        parser_backend_fallback_from=str(metadata.get("parser_backend_fallback_from") or ""),
        parser_quality=parser_quality,
        identity_status=identity_status,
        warnings=warnings,
    )


def read_metadata(root: Path, source_id: str) -> tuple[dict[str, Any], str, list[str]]:
    path = root / "sources" / "metadata" / f"{source_id}.json"
    if not path.exists():
        return {}, "missing", [f"Missing metadata sidecar: sources/metadata/{source_id}.json"]
    if not is_within(path.resolve(), (root / "sources" / "metadata").resolve()):
        return {}, "malformed", [f"Metadata sidecar path is outside sources/metadata: {source_id}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, "malformed", [f"Malformed metadata sidecar for {source_id}: {sanitize_text(str(exc))}"]
    if not isinstance(data, dict):
        return {}, "malformed", [f"Malformed metadata sidecar for {source_id}: expected object"]
    return data, "ok", []


def read_bounded_text(root: Path, path_value: str, allowed_dir: Path, *, limit: int) -> tuple[str, str]:
    if not path_value:
        return "", ""
    path = root / path_value
    resolved = path.resolve()
    if not is_within(resolved, allowed_dir.resolve()):
        return "", f"Path is outside allowed directory: {path_value}"
    if not resolved.exists():
        return "", ""
    try:
        return resolved.read_text(encoding="utf-8", errors="replace")[:limit], ""
    except OSError as exc:
        return "", f"Failed to read {path_value}: {sanitize_text(str(exc))}"


def batch_inventory_items(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for batch_id in list_batch_ids(root):
        for item in read_items(root, batch_id):
            result.append(
                BatchInventoryItem(
                    batch_id=batch_id,
                    item_id=item.item_id,
                    source_path=item.source_path,
                    source_kind=item.source_kind,
                    status=item.status,
                    source_id=item.source_id,
                    latest_run_id=item.latest_run_id,
                    parser_requested=item.parser_requested,
                    parser_backend=item.parser_backend,
                    attempt_count=item.attempt_count,
                    failure_reason=item.failure_reason,
                    warnings=item.warnings,
                ).to_dict()
            )
    return result


def duplicate_warnings(papers: list[PaperIdentity]) -> list[DuplicateWarning]:
    warnings: list[DuplicateWarning] = []
    add_pair_warnings(warnings, papers, "sha256", "same sha256", "exact")
    add_pair_warnings(warnings, papers, "doi", "same DOI", "high")
    add_pair_warnings(warnings, papers, "arxiv_id", "same arxiv_id", "high")
    add_title_author_year_warnings(warnings, papers)
    add_title_warnings(warnings, papers)
    return warnings


def add_pair_warnings(
    warnings: list[DuplicateWarning],
    papers: list[PaperIdentity],
    attr: str,
    reason: str,
    confidence: str,
) -> None:
    groups: dict[str, list[PaperIdentity]] = {}
    for paper in papers:
        value = str(getattr(paper, attr) or "")
        if value:
            groups.setdefault(value, []).append(paper)
    for value, group in groups.items():
        for left, right in pairs(group):
            warnings.append(DuplicateWarning("likely_duplicate", left.source_id, right.source_id, reason, value, confidence))


def add_title_author_year_warnings(warnings: list[DuplicateWarning], papers: list[PaperIdentity]) -> None:
    groups: dict[str, list[PaperIdentity]] = {}
    for paper in papers:
        title = normalize_title_key(paper.title)
        first_author = paper.authors[0].casefold() if paper.authors else ""
        if title and first_author and paper.year:
            groups.setdefault(f"{title}|{first_author}|{paper.year}", []).append(paper)
    for value, group in groups.items():
        for left, right in pairs(group):
            warnings.append(DuplicateWarning("likely_duplicate", left.source_id, right.source_id, "same title, first author, and year", value, "medium"))


def add_title_warnings(warnings: list[DuplicateWarning], papers: list[PaperIdentity]) -> None:
    groups: dict[str, list[PaperIdentity]] = {}
    for paper in papers:
        title = normalize_title_key(paper.title)
        if title:
            groups.setdefault(title, []).append(paper)
    for value, group in groups.items():
        for left, right in pairs(group):
            warnings.append(DuplicateWarning("likely_duplicate", left.source_id, right.source_id, "same normalized title", value, "low"))


def attach_duplicate_warnings(papers: list[PaperIdentity], warnings: list[DuplicateWarning]) -> None:
    by_id = {paper.source_id: paper for paper in papers}
    for warning in warnings:
        payload = warning.to_dict()
        if warning.source_id in by_id:
            by_id[warning.source_id].duplicate_warnings.append(payload)
        if warning.other_source_id in by_id:
            by_id[warning.other_source_id].duplicate_warnings.append(payload)


def pairs(group: list[PaperIdentity]) -> list[tuple[PaperIdentity, PaperIdentity]]:
    return [(group[i], group[j]) for i in range(len(group)) for j in range(i + 1, len(group))]


def identity_status_for(source_type: str, metadata_status: str, title: str, year: int | None, doi: str, arxiv_id: str) -> str:
    if source_type != "pdf":
        return "not_paper"
    if metadata_status == "malformed":
        return "malformed_metadata"
    if metadata_status == "missing":
        return "missing_metadata"
    if title and (year is not None or doi or arxiv_id):
        return "complete"
    return "partial"


def title_confidence_from_quality(title_quality: dict[str, Any], title: str) -> str:
    if not title:
        return "low"
    try:
        score = float(title_quality.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    if score >= 0.7:
        return "high"
    if score >= 0.3:
        return "medium"
    return "medium"


def flatten_metadata_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(flatten_metadata_strings(item))
        return result
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            if str(key).startswith("parser_command_") or str(key).endswith("_snippet"):
                continue
            result.extend(flatten_metadata_strings(item))
        return result
    return []


def clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def workspace_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return ""


def is_within(path: Path, parent: Path) -> bool:
    try:
        os.path.commonpath([str(path), str(parent)])
    except ValueError:
        return False
    return os.path.commonpath([str(path), str(parent)]) == str(parent)


def sanitize_text(text: str) -> str:
    return re_sub_secret(text or "")


def re_sub_secret(text: str) -> str:
    import re

    return re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", text)
