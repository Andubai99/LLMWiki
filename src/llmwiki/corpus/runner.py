from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..db import catalog_path, connect
from ..ingestion.pipeline import AddPipelineError, add_and_process_source
from ..workspace import utc_now
from .discovery import DiscoveredSource, discover_sources
from .state import (
    BatchManifest,
    CorpusAttempt,
    CorpusItem,
    append_attempt,
    append_event,
    create_batch_id,
    item_id_for_path,
    list_batch_ids,
    read_attempts,
    read_batch,
    read_items,
    update_counts,
    write_batch,
    write_items,
)


@dataclass
class CorpusCommandResult:
    batch: BatchManifest | None
    items: list[CorpusItem]
    attempts: list[CorpusAttempt]
    dry_run: bool = False
    exit_code: int = 0
    batches: list[BatchManifest] | None = None
    items_by_batch: dict[str, list[CorpusItem]] | None = None


def import_corpus(
    root: Path,
    inputs: list[str],
    *,
    recursive: bool = False,
    list_file: str | None = None,
    dry_run: bool = False,
    fail_fast: bool = False,
    parser_backend: str | None = None,
) -> CorpusCommandResult:
    root = root.resolve()
    discovered = discover_sources(root, inputs, recursive=recursive, list_file=list_file)
    items = initial_items(root, discovered, batch_id="", parser_backend=parser_backend)
    if dry_run:
        batch = BatchManifest(
            batch_id="",
            root=str(root),
            input_paths=inputs,
            status="dry_run",
            item_count=len(items),
            options={
                "recursive": recursive,
                "list_file": list_file or "",
                "fail_fast": fail_fast,
                "parser": parser_backend or "",
            },
        )
        return CorpusCommandResult(batch=batch, items=items, attempts=[], dry_run=True, exit_code=0)

    batch_id = create_batch_id(root, [source.path.as_posix() for source in discovered])
    items = initial_items(root, discovered, batch_id=batch_id, parser_backend=parser_backend)
    batch = BatchManifest(
        batch_id=batch_id,
        root=str(root),
        input_paths=inputs,
        status="running",
        item_count=len(items),
        options={
            "recursive": recursive,
            "list_file": list_file or "",
            "fail_fast": fail_fast,
            "parser": parser_backend or "",
        },
    )
    batch = update_counts(batch, items)
    write_batch(root, batch)
    write_items(root, batch_id, items)
    append_event(root, batch_id=batch_id, event_type="started", message="Corpus import started.")

    try:
        batch, items = process_items(
            root,
            batch,
            items,
            eligible_statuses={"pending"},
            fail_fast=fail_fast,
            parser_backend=parser_backend,
        )
    except KeyboardInterrupt:
        batch, items = mark_interrupted(root, batch, items)
        raise

    attempts = read_attempts(root, batch_id)
    return CorpusCommandResult(
        batch=batch,
        items=items,
        attempts=attempts,
        exit_code=1 if batch.failed_count or batch.interrupted_count else 0,
    )


def retry_corpus(
    root: Path,
    batch_id: str,
    *,
    item_id: str | None = None,
    failed_only: bool = False,
    parser_backend: str | None = None,
) -> CorpusCommandResult:
    root = root.resolve()
    batch = read_batch(root, batch_id)
    items = read_items(root, batch_id)
    statuses = {"failed", "interrupted"} if failed_only or not item_id else {"failed", "interrupted"}
    for item in items:
        if item_id and not matches_item(item, item_id, root):
            continue
        if item.status in statuses:
            item.status = "pending"
            item.failure_reason = ""
            item.updated_at = utc_now()
    batch.status = "running"
    batch.active_item_id = ""
    batch = update_counts(batch, items)
    write_batch(root, batch)
    write_items(root, batch_id, items)
    batch, items = process_items(
        root,
        batch,
        items,
        eligible_statuses={"pending"},
        fail_fast=False,
        parser_backend=parser_backend or str(batch.options.get("parser") or "") or None,
    )
    attempts = read_attempts(root, batch_id)
    return CorpusCommandResult(
        batch=batch,
        items=items,
        attempts=attempts,
        exit_code=1 if batch.failed_count or batch.interrupted_count else 0,
    )


def skip_item(root: Path, batch_id: str, item_id_or_path: str, *, reason: str = "") -> CorpusCommandResult:
    root = root.resolve()
    batch = read_batch(root, batch_id)
    items = read_items(root, batch_id)
    matched = False
    for item in items:
        if not matches_item(item, item_id_or_path, root):
            continue
        matched = True
        if item.status in {"running", "applied", "already_imported"}:
            raise ValueError(f"cannot skip item with status {item.status}")
        item.status = "skipped"
        item.failure_reason = sanitize_text(reason) if reason else ""
        item.updated_at = utc_now()
        append_event(root, batch_id=batch_id, item_id=item.item_id, event_type="skipped", message=item.failure_reason)
        break
    if not matched:
        raise ValueError(f"item not found: {item_id_or_path}")
    batch.status = final_batch_status(items)
    batch.active_item_id = ""
    batch = update_counts(batch, items)
    write_items(root, batch_id, items)
    write_batch(root, batch)
    return CorpusCommandResult(batch=batch, items=items, attempts=read_attempts(root, batch_id), exit_code=0)


def status(root: Path, batch_id: str | None = None) -> CorpusCommandResult:
    root = root.resolve()
    if batch_id:
        batch = read_batch(root, batch_id)
        items = read_items(root, batch_id)
        attempts = read_attempts(root, batch_id)
        return CorpusCommandResult(batch=batch, items=items, attempts=attempts, batches=[batch], items_by_batch={batch_id: items})
    batch_ids = list_batch_ids(root)
    batches = [read_batch(root, value) for value in batch_ids]
    items_by_batch = {batch.batch_id: read_items(root, batch.batch_id) for batch in batches}
    return CorpusCommandResult(batch=None, items=[], attempts=[], batches=batches, items_by_batch=items_by_batch)


def initial_items(
    root: Path,
    discovered: list[DiscoveredSource],
    *,
    batch_id: str,
    parser_backend: str | None,
) -> list[CorpusItem]:
    items: list[CorpusItem] = []
    for source in discovered:
        source_id, already_applied, warning = already_imported_status(root, source.path)
        status = "already_imported" if already_applied else "pending"
        warnings = [warning] if warning else []
        items.append(
            CorpusItem(
                batch_id=batch_id,
                item_id=item_id_for_path(root, source.path),
                source_path=source.path.resolve().as_posix(),
                source_kind=source.source_kind,
                status=status,
                source_id=source_id,
                parser_requested=parser_backend or "",
                warnings=warnings,
            )
        )
    return items


def process_items(
    root: Path,
    batch: BatchManifest,
    items: list[CorpusItem],
    *,
    eligible_statuses: set[str],
    fail_fast: bool,
    parser_backend: str | None,
) -> tuple[BatchManifest, list[CorpusItem]]:
    for item in items:
        if item.status not in eligible_statuses:
            continue
        batch.active_item_id = item.item_id
        item.status = "running"
        item.updated_at = utc_now()
        batch = update_counts(batch, items)
        write_items(root, batch.batch_id, items)
        write_batch(root, batch)

        attempt = CorpusAttempt(
            batch_id=batch.batch_id,
            item_id=item.item_id,
            attempt_id=f"{item.item_id}_attempt_{item.attempt_count + 1:03d}",
            status="running",
            parser_requested=parser_backend or item.parser_requested,
        )
        try:
            result = add_and_process_source(
                root,
                item.source_path,
                parser_backend=parser_backend or None,
            )
            item.source_id = result.source_id
            item.latest_run_id = result.run_id
            item.status = "already_imported" if result.status == "already_applied" else "applied"
            item.failure_reason = ""
            item.warnings = [*item.warnings, *result.warnings]
            attempt.status = item.status
            attempt.source_id = result.source_id
            attempt.run_id = result.run_id
            attempt.ended_at = utc_now()
        except AddPipelineError as exc:
            item.status = "failed"
            item.source_id = exc.source_id or item.source_id
            item.latest_run_id = exc.run_id or item.latest_run_id
            item.failure_reason = sanitize_text(exc.reason)
            attempt.status = "failed"
            attempt.source_id = exc.source_id or ""
            attempt.run_id = exc.run_id or ""
            attempt.failure_stage = exc.stage
            attempt.failure_reason = item.failure_reason
            attempt.ended_at = utc_now()
        item.attempt_count += 1
        item.updated_at = utc_now()
        append_attempt(root, attempt)
        append_event(root, batch_id=batch.batch_id, item_id=item.item_id, event_type=item.status, message=item.failure_reason or item.status)
        batch.active_item_id = ""
        batch.status = "running"
        batch = update_counts(batch, items)
        write_items(root, batch.batch_id, items)
        write_batch(root, batch)
        if fail_fast and item.status == "failed":
            break

    batch.status = final_batch_status(items)
    batch.active_item_id = ""
    batch = update_counts(batch, items)
    write_items(root, batch.batch_id, items)
    write_batch(root, batch)
    append_event(root, batch_id=batch.batch_id, event_type=batch.status, message=f"Corpus batch {batch.status}.")
    return batch, items


def mark_interrupted(root: Path, batch: BatchManifest, items: list[CorpusItem]) -> tuple[BatchManifest, list[CorpusItem]]:
    for item in items:
        if item.item_id == batch.active_item_id or item.status == "running":
            item.status = "interrupted"
            item.updated_at = utc_now()
            break
    batch.status = "interrupted"
    batch = update_counts(batch, items)
    write_items(root, batch.batch_id, items)
    write_batch(root, batch)
    append_event(root, batch_id=batch.batch_id, item_id=batch.active_item_id, event_type="interrupted", message="Corpus import interrupted.")
    return batch, items


def final_batch_status(items: list[CorpusItem]) -> str:
    if any(item.status in {"failed", "interrupted"} for item in items):
        return "completed_with_failures"
    if any(item.status in {"pending", "running"} for item in items):
        return "interrupted"
    return "completed"


def matches_item(item: CorpusItem, value: str, root: Path) -> bool:
    if item.item_id == value:
        return True
    path = Path(value)
    candidates = {item.source_path, Path(item.source_path).name}
    if path.is_absolute():
        candidates.add(path.resolve().as_posix())
    else:
        candidates.add((root / path).resolve().as_posix())
    return value in candidates


def already_imported_status(root: Path, path: Path) -> tuple[str, bool, str]:
    db_path = catalog_path(root)
    if not db_path.exists():
        return "", False, ""
    digest = sha256_file(path)
    try:
        with connect(db_path) as conn:
            row = conn.execute("select source_id from sources where sha256 = ?", (digest,)).fetchone()
            if row is None:
                return "", False, ""
            source_id = str(row["source_id"])
            applied = conn.execute(
                "select run_id from ingest_runs where source_id = ? and status = 'applied' limit 1",
                (source_id,),
            ).fetchone()
            if applied is not None:
                return source_id, True, ""
            return source_id, False, f"Existing source {source_id} is not applied; queueing for import."
    except Exception as exc:
        return "", False, f"Could not check duplicate status: {sanitize_text(str(exc))}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_text(text: str) -> str:
    cleaned = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", text)
    cleaned = re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)[^ \n\r\t]+", r"\1[redacted]", cleaned)
    return cleaned
