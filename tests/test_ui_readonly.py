from __future__ import annotations

from pathlib import Path
from threading import Thread
from urllib.request import urlopen
import hashlib
import uuid

from llmwiki.cli import main


WORKSPACES = Path(".test-workspaces")


def make_workspace() -> Path:
    root = WORKSPACES / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def fingerprint_path(path: Path) -> tuple:
    if not path.exists():
        return ("missing",)
    if path.is_file():
        return ("file", path.name, hashlib.sha256(path.read_bytes()).hexdigest())
    entries = []
    for child in sorted(path.rglob("*")):
        if child.is_file():
            entries.append(
                (
                    child.relative_to(path).as_posix(),
                    child.stat().st_size,
                    hashlib.sha256(child.read_bytes()).hexdigest(),
                )
            )
        elif child.is_dir():
            entries.append((child.relative_to(path).as_posix(), "dir"))
    return ("dir", tuple(entries))


def workspace_fingerprint(root: Path) -> dict[str, tuple]:
    targets = {
        "catalog": root / "state" / "catalog.sqlite",
        "ui_jobs": root / "state" / "ui-jobs",
        "wiki_index": root / "wiki" / "index.md",
        "wiki_log": root / "wiki" / "log.md",
        "staging": root / "staging",
        "sources": root / "sources",
    }
    return {name: fingerprint_path(path) for name, path in targets.items()}


def forbid_runtime_work(monkeypatch) -> None:
    def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("UI dashboard must not call runtime work")

    monkeypatch.setattr("llmwiki.ingestion.pipeline.add_and_process_source", forbidden)
    monkeypatch.setattr("llmwiki.ingestion.ingest.ingest_source", forbidden)
    monkeypatch.setattr("llmwiki.ingestion.apply.apply_run", forbidden)
    monkeypatch.setattr("llmwiki.lint.lint_workspace", forbidden)
    monkeypatch.setattr("llmwiki.retrieval.eval.evaluate_retrieval", forbidden)
    monkeypatch.setattr("llmwiki.pdf.quality.evaluate_pdf_quality", forbidden)
    monkeypatch.setattr("llmwiki.pdf.mineru_runner.run_mineru_command", forbidden)
    monkeypatch.setattr("llmwiki.llm.create_provider", forbidden)
    monkeypatch.setattr("llmwiki.vector.embeddings.create_embedding_provider", forbidden)
    monkeypatch.setattr("llmwiki.ui.ask_actions.answer_question", forbidden)
    monkeypatch.setattr("llmwiki.ui.ask_actions.plan_synthesis_writeback", forbidden)
    monkeypatch.setattr("llmwiki.ui.ask_actions.create_synthesis_run", forbidden)


def start_test_server(root: Path):
    from llmwiki.ui.server import UiServerConfig, create_ui_server

    server = create_ui_server(UiServerConfig(root=root, host="127.0.0.1", port=0))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_ui_api_functions_do_not_mutate_workspace(monkeypatch) -> None:
    from llmwiki.ui.api import (
        get_ask_job,
        get_config_status,
        get_ui_job,
        get_workspace_status,
        list_ask_jobs,
        list_pages,
        list_runs,
        list_sources,
        list_ui_jobs,
    )
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_add_source_job, create_ask_job

    forbid_runtime_work(monkeypatch)
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    job = create_add_source_job(root, "paper.pdf")
    ask_job = create_ask_job(root, AskUiRequest(question="What is OSWorld?"))
    before = workspace_fingerprint(root)

    get_workspace_status(root)
    list_sources(root)
    list_runs(root)
    list_pages(root)
    get_config_status(root)
    list_ui_jobs(root)
    get_ui_job(root, job.job_id)
    list_ask_jobs(root)
    get_ask_job(root, ask_job.job_id)

    assert workspace_fingerprint(root) == before


def test_ui_http_api_routes_do_not_mutate_workspace(monkeypatch) -> None:
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_add_source_job, create_ask_job

    forbid_runtime_work(monkeypatch)
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    job = create_add_source_job(root, "paper.pdf")
    ask_job = create_ask_job(root, AskUiRequest(question="What is OSWorld?"))
    before = workspace_fingerprint(root)
    server, thread = start_test_server(root)
    host, port = server.server_address
    try:
        for route in [
            "/api/session",
            "/api/status",
            "/api/sources",
            "/api/runs",
            "/api/pages",
            "/api/config",
            "/api/jobs",
            f"/api/jobs/{job.job_id}",
            "/api/ask/jobs",
            f"/api/ask/jobs/{ask_job.job_id}",
        ]:
            with urlopen(f"http://{host}:{port}{route}", timeout=5) as response:
                assert response.status == 200
                response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert workspace_fingerprint(root) == before
