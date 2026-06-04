from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..db import RELATIONSHIP_TYPES, catalog_path, schema_status
from .browser_models import (
    ClaimDetailResponse,
    ClaimListResponse,
    ClaimSummary,
    PageDetailResponse,
    RelationshipListResponse,
    RelationshipSummary,
    SourceDetailResponse,
)
from .jobs import load_jobs
from .models import UiWarning, sanitize_ui_text, workspace_relative_path


DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_MARKDOWN_CHARS = 120_000
MAX_CONTEXT_CHARS = 4_000
MAX_SIDECAR_BYTES = 5 * 1024 * 1024
ALLOWED_METADATA_KEYS = (
    "parser_backend",
    "parser_backend_fallback_from",
    "page_count",
    "block_count",
    "chunk_count",
    "metadata_path",
    "blocks_path",
    "chunks_path",
)


class UiBrowserError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = sanitize_ui_text(message)
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
        }


def get_source_detail(root: Path, source_id: str) -> SourceDetailResponse:
    root = root.resolve()
    source_id = validate_id(source_id, "source_id")
    with open_catalog(root) as conn:
        source_row = fetch_one(
            conn,
            """
            select source_id, title, source_type, raw_path, normalized_path,
                   sha256, url, imported_at, status
            from sources
            where source_id = ?
            """,
            (source_id,),
            missing=f"Source not found: {source_id}",
        )
        metadata, metadata_warnings = read_metadata_summary(root, source_id)
        claims = claims_for_source(conn, root, source_id, limit=MAX_LIMIT)
        relationships = relationship_summaries(
            conn,
            """
            select subject_id, object_id, relationship_type, evidence_claim_id, source_id
            from relationships
            where source_id = ?
            order by relationship_type, subject_id, object_id, evidence_claim_id
            limit ?
            """,
            (source_id, MAX_LIMIT),
        )
        return SourceDetailResponse(
            source=source_dict(root, source_row),
            latest_run=latest_run_for_source(conn, source_id),
            latest_job=latest_job_for_source(root, source_id),
            source_page=source_page_for_source(conn, root, source_id),
            sidecars=sidecar_summary(root, source_id),
            metadata=metadata,
            claim_counts=claim_counts_for_source(conn, source_id),
            claims=claims,
            relationships=relationships,
            warnings=metadata_warnings,
        )


def get_page_detail(root: Path, page_id: str) -> PageDetailResponse:
    root = root.resolve()
    page_id = validate_id(page_id, "page_id")
    warnings: list[UiWarning] = []
    with open_catalog(root) as conn:
        page_row = fetch_one(
            conn,
            "select page_id, path, page_type, title, aliases, updated_at from pages where page_id = ?",
            (page_id,),
            missing=f"Page not found: {page_id}",
        )
        aliases = parse_aliases(str(page_row["aliases"]), warnings)
        markdown, markdown_truncated, markdown_warnings = read_page_markdown(root, str(page_row["path"]))
        warnings.extend(markdown_warnings)
        outgoing = link_rows(conn, root, "from_page", page_id)
        incoming = link_rows(conn, root, "to_page", page_id)
        relationships = relationships_for_page(conn, page_id)
        related_claims = claims_for_page(conn, root, page_id, str(page_row["page_type"]))
        related_sources = related_source_ids(page_id, outgoing, incoming, relationships)
        return PageDetailResponse(
            page=page_dict(root, page_row),
            aliases=aliases,
            markdown=markdown,
            markdown_truncated=markdown_truncated,
            markdown_is_evidence=False,
            outgoing_links=outgoing,
            incoming_links=incoming,
            related_source_ids=related_sources,
            related_claims=related_claims,
            relationships=relationships,
            warnings=warnings,
        )


def list_claims(
    root: Path,
    *,
    query: str = "",
    source_id: str = "",
    page_id: str = "",
    page_type: str = "",
    confidence: str = "",
    relationship_type: str = "",
    limit: int | str = DEFAULT_LIMIT,
    offset: int | str = 0,
) -> ClaimListResponse:
    root = root.resolve()
    parsed_limit = parse_limit(limit)
    parsed_offset = parse_offset(offset)
    query = validate_filter_text(query, "query", max_chars=200)
    source_id = validate_optional_id(source_id, "source_id")
    page_id = validate_optional_id(page_id, "page_id")
    page_type = validate_filter_text(page_type, "page_type", max_chars=80)
    confidence = validate_filter_text(confidence, "confidence", max_chars=80)
    relationship_type = validate_relationship_type(relationship_type)

    where, params = claim_filter_sql(
        query=query,
        source_id=source_id,
        page_id=page_id,
        page_type=page_type,
        confidence=confidence,
        relationship_type=relationship_type,
    )
    with open_catalog(root) as conn:
        total = int(
            conn.execute(
                f"select count(distinct c.claim_id) from claims c left join sources s on s.source_id = c.source_id {where}",
                params,
            ).fetchone()[0]
        )
        rows = conn.execute(
            f"""
            select distinct c.claim_id, c.source_id, c.claim_text, c.citation_locator,
                            c.confidence_status, c.created_at, s.title as source_title
            from claims c
            left join sources s on s.source_id = c.source_id
            {where}
            order by c.created_at desc, c.claim_id
            limit ? offset ?
            """,
            (*params, parsed_limit, parsed_offset),
        ).fetchall()
        return ClaimListResponse(
            claims=[claim_summary(conn, root, row) for row in rows],
            total=total,
            limit=parsed_limit,
            offset=parsed_offset,
        )


def get_claim_detail(root: Path, claim_id: str) -> ClaimDetailResponse:
    root = root.resolve()
    claim_id = validate_id(claim_id, "claim_id")
    warnings: list[UiWarning] = []
    with open_catalog(root) as conn:
        row = fetch_one(
            conn,
            """
            select c.claim_id, c.source_id, c.claim_text, c.citation_locator,
                   c.confidence_status, c.created_at, s.title as source_title
            from claims c
            left join sources s on s.source_id = c.source_id
            where c.claim_id = ?
            """,
            (claim_id,),
            missing=f"Claim not found: {claim_id}",
        )
        source = source_for_claim(conn, root, str(row["source_id"]))
        source_page = source_page_for_source(conn, root, str(row["source_id"]))
        relationships = relationships_for_claim(conn, claim_id)
        candidate_pages = candidate_pages_for_claim(conn, root, row, relationships, source_page)
        locator_context, locator_warnings = resolve_locator_context(root, source, row)
        warnings.extend(locator_warnings)
        return ClaimDetailResponse(
            claim=claim_dict(row),
            source=source,
            source_page=source_page,
            candidate_pages=candidate_pages,
            relationships=relationships,
            locator_context=locator_context,
            warnings=warnings,
        )


def list_relationships(
    root: Path,
    *,
    source_id: str = "",
    page_id: str = "",
    claim_id: str = "",
    relationship_type: str = "",
    limit: int | str = DEFAULT_LIMIT,
    offset: int | str = 0,
) -> RelationshipListResponse:
    root = root.resolve()
    parsed_limit = parse_limit(limit)
    parsed_offset = parse_offset(offset)
    source_id = validate_optional_id(source_id, "source_id")
    page_id = validate_optional_id(page_id, "page_id")
    claim_id = validate_optional_id(claim_id, "claim_id")
    relationship_type = validate_relationship_type(relationship_type)

    clauses: list[str] = []
    params: list[str] = []
    if source_id:
        clauses.append("source_id = ?")
        params.append(source_id)
    if page_id:
        clauses.append("(subject_id = ? or object_id = ?)")
        params.extend([page_id, page_id])
    if claim_id:
        clauses.append("(evidence_claim_id = ? or subject_id = ? or object_id = ?)")
        params.extend([claim_id, claim_id, claim_id])
    if relationship_type:
        clauses.append("relationship_type = ?")
        params.append(relationship_type)
    where = f"where {' and '.join(clauses)}" if clauses else ""

    with open_catalog(root) as conn:
        total = int(conn.execute(f"select count(*) from relationships {where}", tuple(params)).fetchone()[0])
        relationships = relationship_summaries(
            conn,
            f"""
            select subject_id, object_id, relationship_type, evidence_claim_id, source_id
            from relationships
            {where}
            order by relationship_type, subject_id, object_id, evidence_claim_id
            limit ? offset ?
            """,
            (*params, parsed_limit, parsed_offset),
        )
        return RelationshipListResponse(
            relationships=relationships,
            total=total,
            limit=parsed_limit,
            offset=parsed_offset,
        )


@contextmanager
def open_catalog(root: Path) -> Iterator[sqlite3.Connection]:
    db_path = catalog_path(root)
    ok, problems = schema_status(db_path)
    if not ok:
        message = "Catalog database is unavailable."
        if problems:
            message = f"{message} {sanitize_ui_text('; '.join(problems), max_chars=160)}"
        raise UiBrowserError("catalog_unavailable", message, status_code=409)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


def fetch_one(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...], *, missing: str) -> sqlite3.Row:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise UiBrowserError("not_found", missing, status_code=404)
    return row


def validate_id(value: str, name: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 240 or any(char in text for char in ("/", "\\", "\x00")) or text in {".", ".."}:
        raise UiBrowserError("invalid_request", f"Invalid {name}.", status_code=400)
    return text


def validate_optional_id(value: str, name: str) -> str:
    text = str(value or "").strip()
    return validate_id(text, name) if text else ""


def validate_filter_text(value: str, name: str, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) > max_chars or "\x00" in text:
        raise UiBrowserError("invalid_request", f"Invalid {name}.", status_code=400)
    return text


def validate_relationship_type(value: str) -> str:
    text = validate_filter_text(value, "relationship_type", max_chars=80)
    if text and text not in RELATIONSHIP_TYPES:
        raise UiBrowserError("invalid_request", "Invalid relationship_type.", status_code=400)
    return text


def parse_limit(value: int | str) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise UiBrowserError("invalid_request", "Invalid limit.", status_code=400)
    if limit < 1 or limit > MAX_LIMIT:
        raise UiBrowserError("invalid_request", "Invalid limit.", status_code=400)
    return limit


def parse_offset(value: int | str) -> int:
    try:
        offset = int(value)
    except (TypeError, ValueError):
        raise UiBrowserError("invalid_request", "Invalid offset.", status_code=400)
    if offset < 0:
        raise UiBrowserError("invalid_request", "Invalid offset.", status_code=400)
    return offset


def claim_filter_sql(
    *,
    query: str,
    source_id: str,
    page_id: str,
    page_type: str,
    confidence: str,
    relationship_type: str,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if query:
        pattern = f"%{escape_like(query)}%"
        clauses.append("(c.claim_text like ? escape '\\' or c.citation_locator like ? escape '\\')")
        params.extend([pattern, pattern])
    if source_id:
        clauses.append("c.source_id = ?")
        params.append(source_id)
    if confidence:
        clauses.append("c.confidence_status = ?")
        params.append(confidence)
    if relationship_type:
        clauses.append(
            """
            exists (
              select 1 from relationships r
              where r.evidence_claim_id = c.claim_id
                and r.relationship_type = ?
            )
            """
        )
        params.append(relationship_type)
    if page_id:
        clauses.append(
            """
            (
              c.source_id = ?
              or exists (
                select 1 from relationships r
                where r.evidence_claim_id = c.claim_id
                  and (r.subject_id = ? or r.object_id = ?)
              )
            )
            """
        )
        params.extend([page_id, page_id, page_id])
    if page_type:
        clauses.append(
            """
            (
              exists (
                select 1 from pages p
                where (p.page_id = c.source_id or p.path = 'wiki/sources/' || c.source_id || '.md')
                  and p.page_type = ?
              )
              or exists (
                select 1 from relationships r
                join pages p on p.page_id = r.subject_id or p.page_id = r.object_id
                where r.evidence_claim_id = c.claim_id
                  and p.page_type = ?
              )
            )
            """
        )
        params.extend([page_type, page_type])
    where = f"where {' and '.join(clauses)}" if clauses else ""
    return where, tuple(params)


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def source_dict(root: Path, row: sqlite3.Row) -> dict[str, Any]:
    return {
        "source_id": str(row["source_id"]),
        "title": str(row["title"]),
        "source_type": str(row["source_type"]),
        "raw_path": workspace_relative_path(root, str(row["raw_path"])),
        "normalized_path": workspace_relative_path(root, str(row["normalized_path"])),
        "sha256": str(row["sha256"]),
        "url": str(row["url"] or ""),
        "imported_at": str(row["imported_at"]),
        "status": str(row["status"]),
    }


def source_for_claim(conn: sqlite3.Connection, root: Path, source_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        select source_id, title, source_type, raw_path, normalized_path,
               sha256, url, imported_at, status
        from sources
        where source_id = ?
        """,
        (source_id,),
    ).fetchone()
    return source_dict(root, row) if row is not None else {"source_id": source_id}


def page_dict(root: Path, row: sqlite3.Row) -> dict[str, Any]:
    return {
        "page_id": str(row["page_id"]),
        "path": workspace_relative_path(root, str(row["path"])),
        "page_type": str(row["page_type"]),
        "title": str(row["title"]),
        "updated_at": str(row["updated_at"]),
    }


def claim_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "claim_id": str(row["claim_id"]),
        "source_id": str(row["source_id"]),
        "source_title": str(row["source_title"] or ""),
        "claim_text": str(row["claim_text"]),
        "citation_locator": str(row["citation_locator"] or ""),
        "confidence_status": str(row["confidence_status"]),
        "created_at": str(row["created_at"]),
    }


def claim_summary(conn: sqlite3.Connection, root: Path, row: sqlite3.Row) -> ClaimSummary:
    claim_id = str(row["claim_id"])
    return ClaimSummary(
        claim_id=claim_id,
        claim_text=str(row["claim_text"]),
        source_id=str(row["source_id"]),
        source_title=str(row["source_title"] or ""),
        citation_locator=str(row["citation_locator"] or ""),
        confidence_status=str(row["confidence_status"]),
        created_at=str(row["created_at"]),
        page=source_page_for_source(conn, root, str(row["source_id"])),
        relationship_types=relationship_types_for_claim(conn, claim_id),
    )


def source_page_for_source(conn: sqlite3.Connection, root: Path, source_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        select page_id, path, page_type, title, aliases, updated_at
        from pages
        where page_id = ?
           or path = ?
        order by case when page_id = ? then 0 else 1 end
        limit 1
        """,
        (source_id, f"wiki/sources/{source_id}.md", source_id),
    ).fetchone()
    return page_dict(root, row) if row is not None else {}


def latest_run_for_source(conn: sqlite3.Connection, source_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        select run_id, source_id, status, created_at, applied_at
        from ingest_runs
        where source_id = ?
        order by created_at desc, run_id
        limit 1
        """,
        (source_id,),
    ).fetchone()
    return {key: str(row[key] or "") for key in row.keys()} if row is not None else {}


def latest_job_for_source(root: Path, source_id: str) -> dict[str, Any]:
    for job in load_jobs(root).jobs:
        if job.source_id == source_id:
            return {
                "job_id": job.job_id,
                "job_type": job.job_type,
                "status": job.status,
                "stage": job.stage,
                "created_at": job.created_at,
                "finished_at": job.finished_at or "",
            }
    return {}


def sidecar_summary(root: Path, source_id: str) -> dict[str, bool]:
    return {
        "metadata": (root / "sources" / "metadata" / f"{source_id}.json").exists(),
        "blocks": (root / "sources" / "blocks" / f"{source_id}.jsonl").exists(),
        "chunks": (root / "sources" / "chunks" / f"{source_id}.jsonl").exists(),
    }


def read_metadata_summary(root: Path, source_id: str) -> tuple[dict[str, Any], list[UiWarning]]:
    path = root / "sources" / "metadata" / f"{source_id}.json"
    if not path.exists():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, [UiWarning(level="warning", category="sidecar", message=f"Malformed metadata sidecar for {source_id}.")]
    if not isinstance(data, dict):
        return {}, [UiWarning(level="warning", category="sidecar", message=f"Metadata sidecar for {source_id} is not an object.")]
    return {key: data[key] for key in ALLOWED_METADATA_KEYS if key in data}, []


def claim_counts_for_source(conn: sqlite3.Connection, source_id: str) -> dict[str, int]:
    rows = conn.execute(
        """
        select confidence_status, count(*) as count
        from claims
        where source_id = ?
        group by confidence_status
        order by confidence_status
        """,
        (source_id,),
    ).fetchall()
    return {str(row["confidence_status"]): int(row["count"]) for row in rows}


def claims_for_source(conn: sqlite3.Connection, root: Path, source_id: str, *, limit: int) -> list[ClaimSummary]:
    rows = conn.execute(
        """
        select c.claim_id, c.source_id, c.claim_text, c.citation_locator,
               c.confidence_status, c.created_at, s.title as source_title
        from claims c
        left join sources s on s.source_id = c.source_id
        where c.source_id = ?
        order by c.created_at desc, c.claim_id
        limit ?
        """,
        (source_id, limit),
    ).fetchall()
    return [claim_summary(conn, root, row) for row in rows]


def claims_for_page(conn: sqlite3.Connection, root: Path, page_id: str, page_type: str) -> list[ClaimSummary]:
    claim_ids: set[str] = set()
    if page_type == "source" or page_id.startswith("src_"):
        claim_ids.update(
            str(row["claim_id"])
            for row in conn.execute("select claim_id from claims where source_id = ?", (page_id,)).fetchall()
        )
    claim_ids.update(
        str(row["evidence_claim_id"])
        for row in conn.execute(
            """
            select evidence_claim_id
            from relationships
            where evidence_claim_id is not null
              and (subject_id = ? or object_id = ?)
            """,
            (page_id, page_id),
        ).fetchall()
        if row["evidence_claim_id"]
    )
    if not claim_ids:
        return []
    placeholders = ", ".join("?" for _ in claim_ids)
    rows = conn.execute(
        f"""
        select c.claim_id, c.source_id, c.claim_text, c.citation_locator,
               c.confidence_status, c.created_at, s.title as source_title
        from claims c
        left join sources s on s.source_id = c.source_id
        where c.claim_id in ({placeholders})
        order by c.created_at desc, c.claim_id
        limit ?
        """,
        (*sorted(claim_ids), MAX_LIMIT),
    ).fetchall()
    return [claim_summary(conn, root, row) for row in rows]


def relationship_types_for_claim(conn: sqlite3.Connection, claim_id: str) -> list[str]:
    rows = conn.execute(
        """
        select distinct relationship_type
        from relationships
        where evidence_claim_id = ? or subject_id = ? or object_id = ?
        order by relationship_type
        """,
        (claim_id, claim_id, claim_id),
    ).fetchall()
    return [str(row["relationship_type"]) for row in rows]


def relationship_summaries(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> list[RelationshipSummary]:
    return [relationship_summary(conn, row) for row in conn.execute(sql, params).fetchall()]


def relationship_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> RelationshipSummary:
    evidence_claim_id = str(row["evidence_claim_id"] or "")
    source_id = str(row["source_id"] or "")
    return RelationshipSummary(
        subject_id=str(row["subject_id"]),
        object_id=str(row["object_id"]),
        relationship_type=str(row["relationship_type"]),
        evidence_claim_id=evidence_claim_id,
        source_id=source_id,
        subject_title=title_for_id(conn, str(row["subject_id"])),
        object_title=title_for_id(conn, str(row["object_id"])),
        evidence_claim_text=claim_text_for_id(conn, evidence_claim_id),
        source_title=source_title_for_id(conn, source_id),
    )


def relationships_for_page(conn: sqlite3.Connection, page_id: str) -> list[RelationshipSummary]:
    return relationship_summaries(
        conn,
        """
        select subject_id, object_id, relationship_type, evidence_claim_id, source_id
        from relationships
        where subject_id = ? or object_id = ?
        order by relationship_type, subject_id, object_id, evidence_claim_id
        limit ?
        """,
        (page_id, page_id, MAX_LIMIT),
    )


def relationships_for_claim(conn: sqlite3.Connection, claim_id: str) -> list[RelationshipSummary]:
    return relationship_summaries(
        conn,
        """
        select subject_id, object_id, relationship_type, evidence_claim_id, source_id
        from relationships
        where evidence_claim_id = ? or subject_id = ? or object_id = ?
        order by relationship_type, subject_id, object_id, evidence_claim_id
        limit ?
        """,
        (claim_id, claim_id, claim_id, MAX_LIMIT),
    )


def title_for_id(conn: sqlite3.Connection, value: str) -> str:
    if not value:
        return ""
    row = conn.execute("select title from pages where page_id = ?", (value,)).fetchone()
    if row is not None:
        return str(row["title"])
    row = conn.execute("select title from sources where source_id = ?", (value,)).fetchone()
    if row is not None:
        return str(row["title"])
    return ""


def source_title_for_id(conn: sqlite3.Connection, source_id: str) -> str:
    if not source_id:
        return ""
    row = conn.execute("select title from sources where source_id = ?", (source_id,)).fetchone()
    return str(row["title"]) if row is not None else ""


def claim_text_for_id(conn: sqlite3.Connection, claim_id: str) -> str:
    if not claim_id:
        return ""
    row = conn.execute("select claim_text from claims where claim_id = ?", (claim_id,)).fetchone()
    return str(row["claim_text"]) if row is not None else ""


def link_rows(conn: sqlite3.Connection, root: Path, column: str, page_id: str) -> list[dict[str, Any]]:
    if column not in {"from_page", "to_page"}:
        raise ValueError("invalid link direction")
    rows = conn.execute(
        f"select from_page, to_page, link_type from links where {column} = ? order by link_type, from_page, to_page limit ?",
        (page_id, MAX_LIMIT),
    ).fetchall()
    links: list[dict[str, Any]] = []
    for row in rows:
        links.append(
            {
                "from_page": str(row["from_page"]),
                "to_page": str(row["to_page"]),
                "link_type": str(row["link_type"]),
                "from_title": title_for_id(conn, str(row["from_page"])),
                "to_title": title_for_id(conn, str(row["to_page"])),
            }
        )
    return links


def related_source_ids(
    page_id: str,
    outgoing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    relationships: list[RelationshipSummary],
) -> list[str]:
    values: set[str] = set()
    if page_id.startswith("src_"):
        values.add(page_id)
    for link in [*outgoing, *incoming]:
        for key in ("from_page", "to_page"):
            value = str(link.get(key) or "")
            if value.startswith("src_"):
                values.add(value)
    for relationship in relationships:
        for value in (relationship.source_id, relationship.subject_id, relationship.object_id):
            if value.startswith("src_"):
                values.add(value)
    return sorted(values)


def parse_aliases(raw_aliases: str, warnings: list[UiWarning]) -> list[str]:
    try:
        value = json.loads(raw_aliases or "[]")
    except json.JSONDecodeError:
        warnings.append(UiWarning(level="warning", category="catalog", message="Malformed page aliases."))
        return []
    if not isinstance(value, list):
        warnings.append(UiWarning(level="warning", category="catalog", message="Page aliases are not a list."))
        return []
    return [str(item) for item in value if str(item).strip()]


def read_page_markdown(root: Path, page_path: str) -> tuple[str, bool, list[UiWarning]]:
    warnings: list[UiWarning] = []
    resolved = safe_path(root, page_path, root / "wiki")
    if resolved is None:
        warnings.append(UiWarning(level="warning", category="path", message="Page path is outside the workspace wiki directory."))
        return "", False, warnings
    if not resolved.exists():
        warnings.append(UiWarning(level="warning", category="path", message="Wiki page file is missing."))
        return "", False, warnings
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError:
        warnings.append(UiWarning(level="warning", category="path", message="Wiki page file could not be read."))
        return "", False, warnings
    truncated = len(text) > MAX_MARKDOWN_CHARS
    return text[:MAX_MARKDOWN_CHARS], truncated, warnings


def candidate_pages_for_claim(
    conn: sqlite3.Connection,
    root: Path,
    claim_row: sqlite3.Row,
    relationships: list[RelationshipSummary],
    source_page: dict[str, Any],
) -> list[dict[str, Any]]:
    page_ids: set[str] = set()
    if source_page.get("page_id"):
        page_ids.add(str(source_page["page_id"]))
    for relationship in relationships:
        for value in (relationship.subject_id, relationship.object_id):
            if value:
                page_ids.add(value)
    if not page_ids:
        return []
    placeholders = ", ".join("?" for _ in page_ids)
    rows = conn.execute(
        f"select page_id, path, page_type, title, aliases, updated_at from pages where page_id in ({placeholders}) order by page_type, title",
        tuple(sorted(page_ids)),
    ).fetchall()
    return [page_dict(root, row) for row in rows]


def resolve_locator_context(root: Path, source: dict[str, Any], claim_row: sqlite3.Row) -> tuple[dict[str, Any], list[UiWarning]]:
    locator = str(claim_row["citation_locator"] or "")
    source_id = str(claim_row["source_id"])
    if line_match := re.fullmatch(r"line:(\d+)", locator.strip()):
        return resolve_line_context(root, source, locator, int(line_match.group(1)))
    if block_match := re.search(r"(?:^|;)block:([^;]+)", locator):
        page_match = re.search(r"(?:^|;)page:(\d+)", locator)
        page = int(page_match.group(1)) if page_match else 0
        return resolve_pdf_block_context(root, source_id, locator, block_match.group(1), page)
    return (
        {
            "status": "unsupported_locator",
            "kind": "",
            "locator": locator,
            "text": "",
        },
        [UiWarning(level="warning", category="locator", message="Unsupported citation locator.")],
    )


def resolve_line_context(root: Path, source: dict[str, Any], locator: str, line_number: int) -> tuple[dict[str, Any], list[UiWarning]]:
    normalized_path = source.get("normalized_path") or ""
    resolved = safe_path(root, str(normalized_path), root / "sources" / "normalized")
    if resolved is None:
        return (
            {"status": "outside_workspace", "kind": "line", "locator": locator, "text": ""},
            [UiWarning(level="warning", category="path", message="Normalized source path is outside sources/normalized.")],
        )
    if not resolved.exists():
        return (
            {"status": "missing_context", "kind": "line", "locator": locator, "text": ""},
            [UiWarning(level="warning", category="locator", message="Normalized source file is missing.")],
        )
    try:
        lines = resolved.read_text(encoding="utf-8").splitlines()
    except OSError:
        return (
            {"status": "missing_context", "kind": "line", "locator": locator, "text": ""},
            [UiWarning(level="warning", category="locator", message="Normalized source file could not be read.")],
        )
    if line_number < 1 or line_number > len(lines):
        return (
            {"status": "missing_context", "kind": "line", "locator": locator, "text": ""},
            [UiWarning(level="warning", category="locator", message="Line locator is outside the normalized source file.")],
        )
    start = max(1, line_number - 2)
    end = min(len(lines), line_number + 2)
    text = "\n".join(f"{index}: {lines[index - 1]}" for index in range(start, end + 1))
    return (
        {
            "status": "resolved",
            "kind": "line",
            "locator": locator,
            "start_line": start,
            "end_line": end,
            "text": text[:MAX_CONTEXT_CHARS],
        },
        [],
    )


def resolve_pdf_block_context(
    root: Path,
    source_id: str,
    locator: str,
    block_id: str,
    page: int,
) -> tuple[dict[str, Any], list[UiWarning]]:
    path = root / "sources" / "blocks" / f"{source_id}.jsonl"
    if not path.exists():
        return (
            {"status": "missing_sidecar", "kind": "pdf_block", "locator": locator, "block_id": block_id, "text": ""},
            [UiWarning(level="warning", category="sidecar", message="Blocks sidecar is missing.")],
        )
    try:
        if path.stat().st_size > MAX_SIDECAR_BYTES:
            return (
                {"status": "sidecar_too_large", "kind": "pdf_block", "locator": locator, "block_id": block_id, "text": ""},
                [UiWarning(level="warning", category="sidecar", message="Blocks sidecar is too large for UI context lookup.")],
            )
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    return (
                        {"status": "malformed_sidecar", "kind": "pdf_block", "locator": locator, "block_id": block_id, "text": ""},
                        [UiWarning(level="warning", category="sidecar", message="Malformed blocks sidecar.")],
                    )
                if isinstance(data, dict) and str(data.get("block_id") or "") == block_id:
                    text = str(data.get("text_clean") or data.get("text_raw") or data.get("markdown") or data.get("table_markdown") or "")
                    return (
                        {
                            "status": "resolved",
                            "kind": "pdf_block",
                            "locator": locator,
                            "block_id": block_id,
                            "page": int(data.get("page_start") or page or 0),
                            "block_type": str(data.get("block_type") or ""),
                            "section_path": [str(item) for item in data.get("section_path") or []],
                            "text": text[:MAX_CONTEXT_CHARS],
                        },
                        [],
                    )
    except OSError:
        return (
            {"status": "missing_sidecar", "kind": "pdf_block", "locator": locator, "block_id": block_id, "text": ""},
            [UiWarning(level="warning", category="sidecar", message="Blocks sidecar could not be read.")],
        )
    return (
        {"status": "missing_block", "kind": "pdf_block", "locator": locator, "block_id": block_id, "text": ""},
        [UiWarning(level="warning", category="locator", message="Referenced PDF block was not found.")],
    )


def safe_path(root: Path, value: str, allowed_root: Path) -> Path | None:
    root = root.resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(allowed_root.resolve())
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved
