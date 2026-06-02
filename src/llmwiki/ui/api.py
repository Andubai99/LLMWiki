from __future__ import annotations

import sqlite3
from pathlib import Path

from ..db import REQUIRED_SCHEMA, catalog_path, schema_status
from ..workspace import REQUIRED_PATHS, check_workspace
from .models import UiWarning, WorkspaceStatusResponse, sanitize_ui_text


CATALOG_COUNT_TABLES = (
    "sources",
    "claims",
    "pages",
    "relationships",
    "ingest_runs",
)


def get_workspace_status(root: Path) -> WorkspaceStatusResponse:
    root = root.resolve()
    warnings: list[UiWarning] = []
    required_paths = {path: (root / path).exists() for path in REQUIRED_PATHS}
    workspace_check = check_workspace(root)
    catalog = catalog_path(root)
    catalog_present = catalog.exists()
    catalog_ok = False
    counts = {table: 0 for table in CATALOG_COUNT_TABLES}
    latest_runs: list[dict[str, object]] = []

    if catalog_present:
        try:
            catalog_ok, schema_problems = schema_status(catalog)
            warnings.extend(
                UiWarning(level="warning", category="catalog", message=problem)
                for problem in schema_problems
            )
            if catalog_ok:
                counts = read_catalog_counts(catalog)
                latest_runs = read_latest_runs(catalog)
        except (OSError, sqlite3.Error) as exc:
            warnings.append(UiWarning(level="error", category="catalog", message=sanitize_ui_text(exc)))
    else:
        warnings.append(UiWarning(level="warning", category="catalog", message="Catalog database is missing."))

    if not workspace_check.ok:
        for missing in workspace_check.missing:
            warnings.append(UiWarning(level="warning", category="workspace", message=f"Missing required path: {missing}"))

    initialized = all(required_paths.get(path, False) for path in REQUIRED_PATHS if path != "state/catalog.sqlite")
    status = workspace_status(initialized=initialized, catalog_present=catalog_present, catalog_ok=catalog_ok, counts=counts, warnings=warnings)

    return WorkspaceStatusResponse(
        status=status,
        workspace_root=root.as_posix(),
        initialized=initialized,
        catalog_present=catalog_present,
        catalog_ok=catalog_ok,
        required_paths=required_paths,
        counts=counts,
        latest_runs=latest_runs,
        warnings=warnings,
    )


def workspace_status(
    *,
    initialized: bool,
    catalog_present: bool,
    catalog_ok: bool,
    counts: dict[str, int],
    warnings: list[UiWarning],
) -> str:
    if not initialized:
        return "not_initialized"
    if not catalog_present or not catalog_ok:
        return "degraded"
    if any(warning.level == "error" for warning in warnings):
        return "error"
    if any(warning.level == "warning" for warning in warnings if warning.category != "workspace"):
        return "degraded"
    if counts.get("sources", 0) == 0 and counts.get("pages", 0) == 0 and counts.get("claims", 0) == 0:
        return "initialized_empty"
    return "ready"


def read_catalog_counts(db_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with sqlite3.connect(db_path) as conn:
        for table in CATALOG_COUNT_TABLES:
            if table not in REQUIRED_SCHEMA:
                counts[table] = 0
                continue
            try:
                counts[table] = int(conn.execute(f"select count(*) from {table}").fetchone()[0])
            except sqlite3.Error:
                counts[table] = 0
    return counts


def read_latest_runs(db_path: Path, limit: int = 5) -> list[dict[str, object]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                select run_id, source_id, status, created_at, applied_at
                from ingest_runs
                order by created_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.Error:
            return []
    return [
        {
            "run_id": str(row["run_id"]),
            "source_id": str(row["source_id"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "applied_at": str(row["applied_at"] or ""),
        }
        for row in rows
    ]
