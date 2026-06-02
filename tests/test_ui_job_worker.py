from __future__ import annotations

from pathlib import Path
import uuid

from llmwiki.cli import main
from llmwiki.ingestion.pipeline import AddPipelineError, AddPipelineResult


WORKSPACES = Path(".test-workspaces")


def make_workspace() -> Path:
    root = WORKSPACES / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    assert main(["init", "--root", str(root)]) == 0
    return root


def test_run_add_source_job_calls_pipeline_once_on_success(monkeypatch) -> None:
    from llmwiki.ui.actions import run_add_source_job
    from llmwiki.ui.jobs import create_add_source_job, load_jobs

    root = make_workspace()
    job = create_add_source_job(root, "paper.pdf", parser="pypdf")
    calls: list[tuple[Path, str, str | None]] = []

    def fake_add(root_arg: Path, source: str, *, parser_backend: str | None = None):
        calls.append((root_arg, source, parser_backend))
        return AddPipelineResult(
            source_id="src_123",
            title="Paper",
            source_duplicate=False,
            run_id="run_123",
            proposal_engine="llm",
            claim_count=3,
            patch_count=2,
            applied_pages=["wiki/sources/paper.md"],
            warnings=["parser fallback"],
            status="applied",
        )

    monkeypatch.setattr("llmwiki.ui.actions.add_and_process_source", fake_add)

    updated = run_add_source_job(root, job)

    assert calls == [(root.resolve(), "paper.pdf", "pypdf")]
    assert updated.status == "applied"
    assert updated.stage == "applied"
    assert updated.source_id == "src_123"
    assert updated.run_id == "run_123"
    assert updated.result["pipeline_status"] == "applied"
    persisted = load_jobs(root).jobs[0]
    assert persisted.status == "applied"


def test_run_add_source_job_records_already_applied_as_success(monkeypatch) -> None:
    from llmwiki.ui.actions import run_add_source_job
    from llmwiki.ui.jobs import create_add_source_job

    root = make_workspace()
    job = create_add_source_job(root, "paper.pdf")

    def fake_add(root_arg: Path, source: str, *, parser_backend: str | None = None):
        return AddPipelineResult(
            source_id="src_existing",
            title="Paper",
            source_duplicate=True,
            run_id="run_existing",
            proposal_engine="",
            claim_count=0,
            patch_count=0,
            applied_pages=[],
            warnings=[],
            status="already_applied",
        )

    monkeypatch.setattr("llmwiki.ui.actions.add_and_process_source", fake_add)

    updated = run_add_source_job(root, job)

    assert updated.status == "applied"
    assert updated.result["pipeline_status"] == "already_applied"
    assert updated.result["source_duplicate"] is True


def test_run_add_source_job_sanitizes_pipeline_error(monkeypatch) -> None:
    from llmwiki.ui.actions import run_add_source_job
    from llmwiki.ui.jobs import create_add_source_job

    root = make_workspace()
    job = create_add_source_job(root, "paper.pdf")

    def fake_add(root_arg: Path, source: str, *, parser_backend: str | None = None):
        raise AddPipelineError(
            stage="ingest",
            reason="failed with sk-secret config/api-keys.toml",
            source_id="src_failed",
            run_id="run_failed",
        )

    monkeypatch.setattr("llmwiki.ui.actions.add_and_process_source", fake_add)

    updated = run_add_source_job(root, job)

    assert updated.status == "failed"
    assert updated.failure_stage == "ingest"
    assert updated.source_id == "src_failed"
    assert updated.run_id == "run_failed"
    assert "sk-" not in updated.failure_reason
    assert "config/api-keys.toml" not in updated.failure_reason


def test_run_add_source_job_sanitizes_unexpected_exception(monkeypatch) -> None:
    from llmwiki.ui.actions import run_add_source_job
    from llmwiki.ui.jobs import create_add_source_job

    root = make_workspace()
    job = create_add_source_job(root, "paper.pdf")

    def fake_add(root_arg: Path, source: str, *, parser_backend: str | None = None):
        raise RuntimeError("boom sk-secret config/api-keys.toml")

    monkeypatch.setattr("llmwiki.ui.actions.add_and_process_source", fake_add)

    updated = run_add_source_job(root, job)

    assert updated.status == "failed"
    assert updated.failure_stage == "worker"
    assert "Traceback" not in updated.failure_reason
    assert "sk-" not in updated.failure_reason
    assert "config/api-keys.toml" not in updated.failure_reason


def test_ui_job_manager_runs_pending_jobs_fifo() -> None:
    from llmwiki.ui.jobs import UiJobManager, create_add_source_job, load_jobs, update_job

    root = make_workspace()
    first = create_add_source_job(root, "first.md")
    second = create_add_source_job(root, "second.md")
    calls: list[str] = []

    def worker(job):
        calls.append(job.job_id)
        return update_job(root, job, status="applied", stage="applied")

    manager = UiJobManager(root, worker=worker)

    assert manager.run_pending_once() is True
    assert calls == [first.job_id]
    assert [job.status for job in load_jobs(root).jobs if job.job_id == second.job_id] == ["pending"]

    assert manager.run_pending_once() is True
    assert calls == [first.job_id, second.job_id]
    assert manager.run_pending_once() is False


def test_ui_job_manager_does_not_run_jobs_concurrently() -> None:
    from llmwiki.ui.jobs import UiJobManager, create_add_source_job, update_job

    root = make_workspace()
    create_add_source_job(root, "first.md")
    create_add_source_job(root, "second.md")
    active = 0
    max_active = 0

    def worker(job):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        updated = update_job(root, job, status="applied", stage="applied")
        active -= 1
        return updated

    manager = UiJobManager(root, worker=worker)

    assert manager.run_pending_once() is True
    assert manager.run_pending_once() is True
    assert max_active == 1
