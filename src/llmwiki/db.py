from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from pathlib import Path
from typing import Iterator


REQUIRED_SCHEMA: dict[str, tuple[str, ...]] = {
    "sources": (
        "source_id",
        "title",
        "source_type",
        "raw_path",
        "normalized_path",
        "sha256",
        "url",
        "imported_at",
        "status",
    ),
    "claims": (
        "claim_id",
        "source_id",
        "claim_text",
        "citation_locator",
        "confidence_status",
        "created_at",
    ),
    "aliases": ("alias", "target_type", "target_id", "normalized_alias"),
    "pages": ("page_id", "path", "page_type", "title", "aliases", "updated_at"),
    "links": ("from_page", "to_page", "link_type"),
    "relationships": (
        "subject_id",
        "object_id",
        "relationship_type",
        "evidence_claim_id",
        "source_id",
    ),
    "ingest_runs": ("run_id", "source_id", "status", "created_at", "applied_at"),
    "metric_results": (
        "result_id",
        "schema_version",
        "claim_id",
        "source_id",
        "paper_id",
        "claim_text",
        "citation_locator",
        "confidence_status",
        "evidence_block_ids",
        "evidence_pages",
        "evidence_section_path",
        "evidence_block_roles",
        "extraction_origin",
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
        "reported_year",
        "is_main_result",
        "value_normalization_status",
        "warnings",
        "created_at",
    ),
}


RELATIONSHIP_TYPES = ("supports", "contradicts", "refines", "contains", "similar_to")


def catalog_path(root: Path) -> Path:
    return root / "state" / "catalog.sqlite"


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("pragma temp_store = memory")
        conn.execute("pragma foreign_keys = on")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(
            """
            create table if not exists sources (
                source_id text primary key,
                title text not null,
                source_type text not null,
                raw_path text not null,
                normalized_path text not null,
                sha256 text not null unique,
                url text,
                imported_at text not null,
                status text not null
            );

            create table if not exists claims (
                claim_id text primary key,
                source_id text not null,
                claim_text text not null,
                citation_locator text,
                confidence_status text not null,
                created_at text not null
            );

            create table if not exists aliases (
                alias text not null,
                target_type text not null,
                target_id text not null,
                normalized_alias text not null
            );

            create table if not exists pages (
                page_id text primary key,
                path text not null unique,
                page_type text not null,
                title text not null,
                aliases text not null,
                updated_at text not null
            );

            create table if not exists links (
                from_page text not null,
                to_page text not null,
                link_type text not null
            );

            create table if not exists relationships (
                subject_id text not null,
                object_id text not null,
                relationship_type text not null
                    check (relationship_type in ('supports', 'contradicts', 'refines', 'contains', 'similar_to')),
                evidence_claim_id text,
                source_id text
            );

            create table if not exists ingest_runs (
                run_id text primary key,
                source_id text not null,
                status text not null,
                created_at text not null,
                applied_at text
            );

            create table if not exists metric_results (
                result_id text primary key,
                schema_version text not null,
                claim_id text not null,
                source_id text not null,
                paper_id text not null,
                claim_text text not null,
                citation_locator text not null,
                confidence_status text not null,
                evidence_block_ids text not null,
                evidence_pages text not null,
                evidence_section_path text not null,
                evidence_block_roles text not null,
                extraction_origin text not null,
                method text not null,
                dataset text not null,
                task text not null,
                metric_name text not null,
                metric_value text not null,
                metric_unit text not null,
                metric_raw_value text not null,
                metric_direction text not null,
                baseline text not null,
                comparison_value text not null,
                setting text not null,
                reported_year integer,
                is_main_result integer,
                value_normalization_status text not null,
                warnings text not null,
                created_at text not null
            );

            create virtual table if not exists claims_fts using fts5(
                claim_id unindexed,
                claim_text,
                source_id unindexed,
                citation_locator unindexed
            );

            create index if not exists idx_sources_sha256 on sources(sha256);
            create index if not exists idx_claims_source on claims(source_id);
            create index if not exists idx_aliases_normalized on aliases(normalized_alias);
            create index if not exists idx_pages_type on pages(page_type);
            create index if not exists idx_relationship_type on relationships(relationship_type);
            create index if not exists idx_metric_results_claim on metric_results(claim_id);
            create index if not exists idx_metric_results_source on metric_results(source_id);
            create index if not exists idx_metric_results_paper on metric_results(paper_id);
            create index if not exists idx_metric_results_metric on metric_results(metric_name);
            create index if not exists idx_metric_results_dataset_task on metric_results(dataset, task);
            """
        )


def schema_status(db_path: Path) -> tuple[bool, list[str]]:
    if not db_path.exists():
        return False, [f"missing {db_path}"]

    problems: list[str] = []
    with connect(db_path) as conn:
        rows = conn.execute(
            "select name from sqlite_master where type in ('table', 'view')"
        ).fetchall()
        tables = {row["name"] for row in rows}
        for table, expected_columns in REQUIRED_SCHEMA.items():
            if table not in tables:
                problems.append(f"missing table {table}")
                continue
            columns = tuple(
                row["name"] for row in conn.execute(f"pragma table_info({table})")
            )
            if columns != expected_columns:
                problems.append(
                    f"table {table} columns differ: {', '.join(columns)}"
                )
    return not problems, problems
