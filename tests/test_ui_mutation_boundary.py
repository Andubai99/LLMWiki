from __future__ import annotations

from pathlib import Path
from threading import Thread
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


def forbid_direct_write_surfaces(monkeypatch) -> None:
    def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("UI action layer must not call this surface directly")

    monkeypatch.setattr("llmwiki.ingestion.apply.apply_run", forbidden)
    monkeypatch.setattr("llmwiki.ingestion.ingest.ingest_source", forbidden)
    monkeypatch.setattr("llmwiki.ingestion.sources.import_source", forbidden)
    monkeypatch.setattr("llmwiki.ui.server.run_add_source_job", forbidden)


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
