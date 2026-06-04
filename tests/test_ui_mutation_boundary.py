from __future__ import annotations

from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import hashlib
import json
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
            entries.append((child.relative_to(path).as_posix(), child.stat().st_size, hashlib.sha256(child.read_bytes()).hexdigest()))
        elif child.is_dir():
            entries.append((child.relative_to(path).as_posix(), "dir"))
    return ("dir", tuple(entries))


def workspace_fingerprint(root: Path) -> dict[str, tuple]:
    targets = {
        "catalog": root / "state" / "catalog.sqlite",
        "ui_jobs": root / "state" / "ui-jobs",
        "wiki": root / "wiki",
        "staging": root / "staging",
        "sources": root / "sources",
    }
    return {name: fingerprint_path(path) for name, path in targets.items()}


def start_test_server(root: Path):
    from llmwiki.ui.server import UiServerConfig, create_ui_server

    server = create_ui_server(UiServerConfig(root=root, host="127.0.0.1", port=0, action_token="token"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def post_add_source(server, source: str):
    host, port = server.server_address
    request = Request(
        f"http://{host}:{port}/api/sources/add",
        data=json.dumps({"source": source, "parser": "pypdf"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-LLMWiki-UI-Token": "token"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def post_ask(server, question: str):
    host, port = server.server_address
    request = Request(
        f"http://{host}:{port}/api/ask",
        data=json.dumps({"question": question}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-LLMWiki-UI-Token": "token"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def post_json(server, path: str):
    host, port = server.server_address
    request = Request(
        f"http://{host}:{port}{path}",
        data=b"{}",
        headers={"Content-Type": "application/json", "X-LLMWiki-UI-Token": "token"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def forbid_direct_write_surfaces(monkeypatch) -> None:
    def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("UI action layer must not call this surface directly")

    monkeypatch.setattr("llmwiki.ingestion.apply.apply_run", forbidden)
    monkeypatch.setattr("llmwiki.ingestion.ingest.ingest_source", forbidden)
    monkeypatch.setattr("llmwiki.ingestion.sources.import_source", forbidden)
    monkeypatch.setattr("llmwiki.ui.server.run_add_source_job", forbidden)
    monkeypatch.setattr("llmwiki.ui.server.run_ask_job", forbidden, raising=False)
    monkeypatch.setattr("llmwiki.ingestion.apply.apply_run", forbidden)


def test_post_add_source_only_creates_ui_job_file(monkeypatch) -> None:
    forbid_direct_write_surfaces(monkeypatch)
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    (root / "paper.md").write_text("# Paper\n", encoding="utf-8")
    server, thread = start_test_server(root)
    before = workspace_fingerprint(root)
    try:
        status, payload = post_add_source(server, "paper.md")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    after = workspace_fingerprint(root)

    assert status == 202
    assert payload["job"]["status"] == "pending"
    assert after["ui_jobs"] != before["ui_jobs"]
    for key in ["catalog", "wiki", "staging", "sources"]:
        assert after[key] == before[key]


def test_post_ask_only_creates_ui_job_file(monkeypatch) -> None:
    forbid_direct_write_surfaces(monkeypatch)
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root)
    before = workspace_fingerprint(root)
    try:
        status, payload = post_ask(server, "What is OSWorld?")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    after = workspace_fingerprint(root)

    assert status == 202
    assert payload["job"]["job_type"] == "ask_question"
    assert after["ui_jobs"] != before["ui_jobs"]
    for key in ["catalog", "wiki", "staging", "sources"]:
        assert after[key] == before[key]


def test_v3_4_browser_routes_are_not_mutating_post_routes(monkeypatch) -> None:
    from tests.test_ui_browser_api import seed_browser_catalog

    forbid_direct_write_surfaces(monkeypatch)
    root = make_workspace()
    seed_browser_catalog(root)
    server, thread = start_test_server(root)
    try:
        for route in [
            "/api/evidence/claims",
            "/api/evidence/claims/clm_line",
            "/api/evidence/relationships",
            "/api/sources/src_text",
            "/api/pages/concept:fruit",
        ]:
            try:
                post_json(server, route)
            except HTTPError as exc:
                payload = json.loads(exc.read().decode("utf-8"))
                assert exc.code == 404
                assert payload["error"] == "not_found"
            else:  # pragma: no cover - defensive
                raise AssertionError(f"Expected browser POST route to be rejected: {route}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_ask_worker_mutation_is_limited_to_ui_job_state(monkeypatch) -> None:
    from llmwiki.ask.answer import AskResult
    from llmwiki.ui.ask_actions import run_ask_job
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_ask_job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    job = create_ask_job(root, AskUiRequest(question="What is OSWorld?"))
    before = workspace_fingerprint(root)
    monkeypatch.setattr(
        "llmwiki.ui.ask_actions.answer_question",
        lambda root_arg, question, options: AskResult(question=question, status="planned_insufficient_evidence"),
    )

    run_ask_job(root, job)
    after = workspace_fingerprint(root)

    assert after["ui_jobs"] != before["ui_jobs"]
    for key in ["catalog", "wiki", "staging", "sources"]:
        assert after[key] == before[key]


def test_preview_worker_does_not_mutate_workspace_outputs(monkeypatch) -> None:
    from tests.test_ui_synthesis_actions import make_answered_ask_job, make_plan
    from llmwiki.ui.ask_actions import enqueue_synthesis_preview_job, run_synthesis_preview_job

    class FakeManager:
        def enqueue(self, job):
            return job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = make_answered_ask_job(root)
    preview_job = enqueue_synthesis_preview_job(root, ask_job.job_id, {}, FakeManager())
    before = workspace_fingerprint(root)
    monkeypatch.setattr("llmwiki.ui.ask_actions.plan_synthesis_writeback", lambda root_arg, ask_result, options: make_plan())

    run_synthesis_preview_job(root, preview_job)
    after = workspace_fingerprint(root)

    assert after["ui_jobs"] != before["ui_jobs"]
    for key in ["catalog", "wiki", "staging", "sources"]:
        assert after[key] == before[key]


def test_writeback_worker_only_uses_create_synthesis_run(monkeypatch) -> None:
    from llmwiki.synthesis import SynthesisWritebackResult
    from tests.test_ui_synthesis_actions import make_answered_ask_job, make_preview_job
    from llmwiki.ui.ask_actions import enqueue_synthesis_writeback_job, run_synthesis_writeback_job

    class FakeManager:
        def enqueue(self, job):
            return job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = make_answered_ask_job(root)
    make_preview_job(root, ask_job.job_id)
    writeback_job = enqueue_synthesis_writeback_job(root, ask_job.job_id, {"writeback_mode": "auto"}, FakeManager())
    before = workspace_fingerprint(root)
    calls = []

    def fake_create(root_arg, ask_result, plan=None, planning_options=None):
        calls.append((root_arg, ask_result, plan, planning_options))
        return SynthesisWritebackResult(
            run_id="run_synthesis_1",
            pages=["wiki/syntheses/osworld.md"],
            status="applied",
            action=plan.action,
            synthesis_plan=plan.to_dict(),
        )

    monkeypatch.setattr("llmwiki.ui.ask_actions.create_synthesis_run", fake_create)
    monkeypatch.setattr("llmwiki.ingestion.apply.apply_run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct apply forbidden")))
    monkeypatch.setattr("llmwiki.ingestion.ingest.ingest_source", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct ingest forbidden")))

    run_synthesis_writeback_job(root, writeback_job)
    after = workspace_fingerprint(root)

    assert len(calls) == 1
    assert after["ui_jobs"] != before["ui_jobs"]
    for key in ["catalog", "wiki", "staging", "sources"]:
        assert after[key] == before[key]
