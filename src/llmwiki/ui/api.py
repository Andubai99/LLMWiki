from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import tomllib
from typing import Any

from ..db import REQUIRED_SCHEMA, catalog_path, schema_status
from ..llm import load_llm_config
from ..pdf.mineru_runner import probe_mineru_status
from ..pdf.parser_backends import load_pdf_parser_config
from ..vector.embeddings import load_embedding_config
from ..vector.index import vector_index_status
from ..workspace import REQUIRED_PATHS, check_workspace
from .models import (
    ConfigStatusResponse,
    PageSummary,
    RunSummary,
    SourceSummary,
    UiWarning,
    WorkspaceStatusResponse,
    sanitize_ui_text,
    workspace_relative_path,
)


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


def list_sources(root: Path, limit: int = 100) -> list[SourceSummary]:
    root = root.resolve()
    db_path = catalog_path(root)
    if not db_path.exists():
        return []
    latest_runs = latest_run_by_source(db_path)
    sources: list[SourceSummary] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                select source_id, title, source_type, raw_path, normalized_path, status
                from sources
                order by imported_at desc, source_id
                limit ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.Error:
            return []
    for row in rows:
        source_id = str(row["source_id"])
        metadata, metadata_warnings = read_source_metadata(root, source_id)
        sidecars = {
            "metadata": (root / "sources" / "metadata" / f"{source_id}.json").exists(),
            "blocks": (root / "sources" / "blocks" / f"{source_id}.jsonl").exists(),
            "chunks": (root / "sources" / "chunks" / f"{source_id}.jsonl").exists(),
        }
        latest = latest_runs.get(source_id, {})
        sources.append(
            SourceSummary(
                source_id=source_id,
                title=str(row["title"]),
                source_type=str(row["source_type"]),
                raw_path=workspace_relative_path(root, str(row["raw_path"])),
                normalized_path=workspace_relative_path(root, str(row["normalized_path"])),
                status=str(row["status"]),
                latest_run_id=str(latest.get("run_id", "")),
                latest_run_status=str(latest.get("status", "")),
                parser_backend=str(metadata.get("parser_backend", "")),
                parser_fallback=str(metadata.get("parser_backend_fallback_from", "")),
                sidecars=sidecars,
                warnings=metadata_warnings,
            )
        )
    return sources


def list_runs(root: Path, limit: int = 50) -> list[RunSummary]:
    root = root.resolve()
    catalog_runs = catalog_run_rows(root, limit=limit)
    staging_runs = staging_run_rows(root)
    run_ids = sorted(
        set(catalog_runs) | set(staging_runs),
        key=lambda run_id: str(staging_runs.get(run_id, {}).get("created_at") or catalog_runs.get(run_id, {}).get("created_at") or ""),
        reverse=True,
    )[:limit]
    results: list[RunSummary] = []
    for run_id in run_ids:
        catalog_row = catalog_runs.get(run_id, {})
        staging_row = staging_runs.get(run_id, {})
        run_dir = root / "staging" / run_id
        results.append(
            RunSummary(
                run_id=run_id,
                source_id=str(staging_row.get("source_id") or catalog_row.get("source_id") or ""),
                status=str(staging_row.get("status") or catalog_row.get("status") or ""),
                run_type=str(staging_row.get("run_type") or ""),
                trigger=str(staging_row.get("trigger") or ""),
                created_at=str(staging_row.get("created_at") or catalog_row.get("created_at") or ""),
                applied_at=str(staging_row.get("applied_at") or catalog_row.get("applied_at") or ""),
                failed_stage=str(staging_row.get("failed_stage") or ""),
                failure_reason=sanitize_ui_text(staging_row.get("failure_reason") or "", max_chars=240),
                claim_count=count_jsonl(run_dir / "claims.jsonl"),
                patch_count=count_patch_files(run_dir),
            )
        )
    return results


def list_pages(root: Path, limit: int = 200) -> list[PageSummary]:
    root = root.resolve()
    db_path = catalog_path(root)
    if not db_path.exists():
        return []
    claim_counts = claim_count_by_source(db_path)
    pages: list[PageSummary] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                select page_id, path, page_type, title
                from pages
                order by page_type, title
                limit ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.Error:
            return []
    for row in rows:
        page_id = str(row["page_id"])
        page_path = str(row["path"])
        source_id = source_id_for_page(page_id, page_path)
        pages.append(
            PageSummary(
                page_id=page_id,
                title=str(row["title"]),
                page_type=str(row["page_type"]),
                path=workspace_relative_path(root, page_path),
                source_id=source_id,
                claim_count=claim_counts.get(source_id, 0),
            )
        )
    return pages


def get_config_status(root: Path) -> ConfigStatusResponse:
    root = root.resolve()
    warnings: list[UiWarning] = []
    llm_config = load_llm_config(root)
    embedding_config = load_embedding_config(root)
    parser_config = load_pdf_parser_config(root)
    key_data = read_api_key_presence(root / "config" / "api-keys.toml")
    try:
        mineru_status = probe_mineru_status(parser_config)
    except Exception as exc:
        mineru_status = {"available": False, "warnings": [sanitize_ui_text(exc)]}
    try:
        vector_status = vector_index_status(root).to_dict()
    except Exception as exc:
        vector_status = {"index_present": False, "stale": False, "reason": sanitize_ui_text(exc)}
        warnings.append(UiWarning(level="warning", category="vector", message=exc))
    parser = {
        "default_backend": parser_config.default_backend,
        "fallback_backend": parser_config.fallback_backend,
        "mineru_enabled": parser_config.mineru_enabled,
        "mineru_available": bool(mineru_status.get("available", False)),
        "mineru_command_source": str(mineru_status.get("command_source", "")),
    }
    return ConfigStatusResponse(
        llm={
            "enabled": llm_config.enabled,
            "provider": llm_config.provider,
            "model": llm_config.model,
            "api_key_present": key_data.get("llm", False),
        },
        embedding={
            "enabled": embedding_config.enabled,
            "provider": embedding_config.provider,
            "model": embedding_config.model,
            "api_key_present": key_data.get("embedding", False),
        },
        parser=parser,
        vector=vector_status,
        warnings=warnings,
    )


def latest_run_by_source(db_path: Path) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                select run_id, source_id, status, created_at, applied_at
                from ingest_runs
                order by created_at desc
                """
            ).fetchall()
        except sqlite3.Error:
            return {}
    for row in rows:
        source_id = str(row["source_id"])
        if source_id not in latest:
            latest[source_id] = {key: str(row[key] or "") for key in row.keys()}
    return latest


def read_source_metadata(root: Path, source_id: str) -> tuple[dict[str, Any], list[UiWarning]]:
    path = root / "sources" / "metadata" / f"{source_id}.json"
    if not path.exists():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [UiWarning(level="warning", category="sidecar", message=f"Malformed metadata sidecar for {source_id}: {sanitize_ui_text(exc)}")]
    if not isinstance(data, dict):
        return {}, [UiWarning(level="warning", category="sidecar", message=f"Metadata sidecar for {source_id} is not an object.")]
    return data, []


def catalog_run_rows(root: Path, limit: int) -> dict[str, dict[str, Any]]:
    db_path = catalog_path(root)
    if not db_path.exists():
        return {}
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
            return {}
    return {str(row["run_id"]): {key: row[key] for key in row.keys()} for row in rows}


def staging_run_rows(root: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    staging_root = root / "staging"
    if not staging_root.exists():
        return rows
    for run_json in sorted(staging_root.glob("*/run.json"), reverse=True):
        try:
            payload = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        run_id = str(payload.get("run_id") or run_json.parent.name)
        rows[run_id] = payload
    return rows


def count_jsonl(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def count_patch_files(run_dir: Path) -> int:
    patches = run_dir / "patches"
    if not patches.exists():
        return 0
    return sum(1 for path in patches.glob("*.json") if path.is_file())


def claim_count_by_source(db_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "select source_id, count(*) as claim_count from claims group by source_id"
            ).fetchall()
        except sqlite3.Error:
            return counts
    for row in rows:
        counts[str(row["source_id"])] = int(row["claim_count"])
    return counts


def source_id_for_page(page_id: str, page_path: str) -> str:
    if page_id.startswith("src_"):
        return page_id
    path = Path(page_path.replace("\\", "/"))
    parts = path.parts
    if len(parts) >= 3 and parts[-3] == "wiki" and parts[-2] == "sources":
        return path.stem
    return ""


def read_api_key_presence(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {"llm": False, "embedding": False}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {"llm": False, "embedding": False}
    return {
        "llm": bool(str(data.get("llm", {}).get("api_key", "")).strip()),
        "embedding": bool(str(data.get("embedding", {}).get("api_key", "")).strip()),
    }
