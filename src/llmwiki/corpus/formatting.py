from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .state import BatchManifest, CorpusAttempt, CorpusItem


def batch_payload(
    batch: BatchManifest,
    items: list[CorpusItem],
    attempts: list[CorpusAttempt] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "batch": batch.to_dict(),
        "items": [item.to_dict() for item in items],
    }
    if attempts is not None:
        payload["attempts"] = [asdict(attempt) for attempt in attempts]
    return payload


def format_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_import_summary(batch: BatchManifest, items: list[CorpusItem], *, dry_run: bool = False) -> str:
    lines = [
        f"Batch: {batch.batch_id or '(dry-run)'}",
        f"Status: {batch.status}",
        f"Dry run: {str(dry_run).lower()}",
    ]
    if dry_run:
        lines.append(f"Would queue: {len(items)}")
    else:
        lines.extend(
            [
                f"Items: {batch.item_count}",
                f"Applied: {batch.applied_count}",
                f"Already imported: {batch.already_imported_count}",
                f"Failed: {batch.failed_count}",
                f"Skipped: {batch.skipped_count}",
                f"Interrupted: {batch.interrupted_count}",
            ]
        )
    if items:
        lines.append("Sources:")
        for item in items:
            extra = f" run_id={item.latest_run_id}" if item.latest_run_id else ""
            reason = f" reason={item.failure_reason}" if item.failure_reason else ""
            lines.append(f"- {item.status} {item.source_path}{extra}{reason}")
    else:
        lines.append("Sources: none")
    if batch.batch_id and not dry_run:
        lines.append(f"Debug: llmwiki corpus status {batch.batch_id} --root .")
    return "\n".join(lines)


def format_status_summary(batches: list[BatchManifest], items_by_batch: dict[str, list[CorpusItem]]) -> str:
    if not batches:
        return "No corpus batches."
    lines: list[str] = []
    for batch in batches:
        lines.append(f"Batch: {batch.batch_id}")
        lines.append(f"- status: {batch.status}")
        lines.append(f"- items: {batch.item_count}")
        lines.append(f"- applied: {batch.applied_count}")
        lines.append(f"- failed: {batch.failed_count}")
        items = items_by_batch.get(batch.batch_id, [])
        if items:
            lines.append("Items:")
            for item in items:
                reason = f" reason={item.failure_reason}" if item.failure_reason else ""
                run = f" run_id={item.latest_run_id}" if item.latest_run_id else ""
                lines.append(f"- {item.item_id} {item.status} {item.source_path}{run}{reason}")
    return "\n".join(lines)
