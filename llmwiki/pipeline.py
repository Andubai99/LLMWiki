from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .apply import apply_run, read_patches
from .db import catalog_path, connect
from .ingest import ingest_source
from .sources import import_source
from .workspace import utc_now


@dataclass(frozen=True)
class AddPipelineResult:
    source_id: str
    title: str
    source_duplicate: bool
    run_id: str
    proposal_engine: str
    claim_count: int
    patch_count: int
    applied_pages: list[str]
    warnings: list[str]
    status: str


class AddPipelineError(Exception):
    def __init__(
        self,
        *,
        stage: str,
        reason: str,
        source_id: str | None = None,
        run_id: str | None = None,
        debug_command: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.stage = stage
        self.source_id = source_id
        self.run_id = run_id
        self.reason = reason
        self.debug_command = debug_command


def add_and_process_source(root: Path, locator: str) -> AddPipelineResult:
    root = root.resolve()
    try:
        source = import_source(root, locator)
    except FileNotFoundError as exc:
        raise AddPipelineError(stage="import", reason=f"Source not found: {locator}") from exc
    except Exception as exc:
        raise AddPipelineError(stage="import", reason=sanitize_error(exc)) from exc

    applied = applied_run_for_source(root, source.source_id)
    if source.duplicate and applied:
        return AddPipelineResult(
            source_id=source.source_id,
            title=source.title,
            source_duplicate=True,
            run_id=applied["run_id"],
            proposal_engine="",
            claim_count=0,
            patch_count=0,
            applied_pages=applied_pages_for_run(root, applied["run_id"]),
            warnings=[],
            status="already_applied",
        )

    run_id: str | None = None
    try:
        ingest = ingest_source(root, source.source_id, require_llm=True, trigger="add")
        run_id = ingest.run_id
    except Exception as exc:
        raise AddPipelineError(
            stage="ingest",
            source_id=source.source_id,
            reason=sanitize_error(exc),
        ) from exc

    try:
        applied_pages = staged_patch_targets(root, run_id)
        apply_run(root, run_id)
    except Exception as exc:
        mark_run_failed(root, run_id, "apply", sanitize_error(exc))
        raise AddPipelineError(
            stage="apply",
            source_id=source.source_id,
            run_id=run_id,
            reason=sanitize_error(exc),
            debug_command=f"llmwiki review {run_id} --detail --root .",
        ) from exc

    return AddPipelineResult(
        source_id=source.source_id,
        title=source.title,
        source_duplicate=source.duplicate,
        run_id=run_id,
        proposal_engine=ingest.proposal_engine,
        claim_count=ingest.claim_count,
        patch_count=ingest.patch_count,
        applied_pages=applied_pages,
        warnings=[],
        status="applied",
    )


def applied_run_for_source(root: Path, source_id: str) -> dict[str, str] | None:
    with connect(catalog_path(root)) as conn:
        row = conn.execute(
            """
            select run_id, status
            from ingest_runs
            where source_id = ? and status = 'applied'
            order by applied_at desc, created_at desc
            limit 1
            """,
            (source_id,),
        ).fetchone()
    return dict(row) if row else None


def applied_pages_for_run(root: Path, run_id: str) -> list[str]:
    run_dir = root / "staging" / run_id
    if not run_dir.exists():
        return []
    return [str(patch.get("target_path")) for patch in read_patches(run_dir / "patches")]


def staged_patch_targets(root: Path, run_id: str) -> list[str]:
    run_dir = root / "staging" / run_id
    return [str(patch.get("target_path")) for patch in read_patches(run_dir / "patches")]


def mark_run_failed(root: Path, run_id: str, stage: str, reason: str) -> None:
    manifest_path = root / "staging" / run_id / "run.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "failed"
    manifest["failed_at"] = utc_now()
    manifest["failed_stage"] = stage
    manifest["failure_reason"] = reason
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sanitize_error(exc: BaseException) -> str:
    text = str(exc)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", text)
    return text or exc.__class__.__name__
