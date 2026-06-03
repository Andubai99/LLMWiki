from __future__ import annotations

from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import uuid

from llmwiki.cli import main


WORKSPACES = Path(".test-workspaces")


def make_workspace() -> Path:
    root = WORKSPACES / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def start_test_server(root: Path):
    from llmwiki.ui.server import UiServerConfig, create_ui_server

    server = create_ui_server(UiServerConfig(root=root, host="127.0.0.1", port=0))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def read_url(server, path: str) -> tuple[int, str, str]:
    host, port = server.server_address
    with urlopen(f"http://{host}:{port}{path}", timeout=5) as response:
        body = response.read().decode("utf-8")
        return response.status, response.headers.get("Content-Type", ""), body


def post_url(server, path: str, body: bytes = b"{}") -> tuple[int, str, str]:
    host, port = server.server_address
    request = Request(f"http://{host}:{port}{path}", data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    with urlopen(request, timeout=5) as response:
        payload = response.read().decode("utf-8")
        return response.status, response.headers.get("Content-Type", ""), payload


def test_server_serves_status_json_on_localhost() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root)
    try:
        status, content_type, body = read_url(server, "/api/status")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    payload = json.loads(body)
    assert status == 200
    assert "application/json" in content_type
    assert payload["schema_version"] == "ui.v3.4"
    assert payload["initialized"] is True


def test_server_serves_v3_4_browser_get_routes_without_token() -> None:
    from tests.test_ui_browser_api import seed_browser_catalog

    root = make_workspace()
    seed_browser_catalog(root)
    server, thread = start_test_server(root)
    try:
        source_status, _, source_body = read_url(server, "/api/sources/src_pdf")
        page_status, _, page_body = read_url(server, "/api/pages/concept:fruit")
        claim_list_status, _, claim_list_body = read_url(server, "/api/evidence/claims?query=storage&confidence=cited")
        claim_status, _, claim_body = read_url(server, "/api/evidence/claims/clm_pdf")
        relationship_status, _, relationship_body = read_url(server, "/api/evidence/relationships?claim_id=clm_pdf")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert source_status == 200
    assert json.loads(source_body)["source"]["source_id"] == "src_pdf"
    assert page_status == 200
    assert json.loads(page_body)["page"]["page_id"] == "concept:fruit"
    assert claim_list_status == 200
    assert json.loads(claim_list_body)["claims"][0]["claim_id"] == "clm_line"
    assert claim_status == 200
    assert json.loads(claim_body)["claim"]["claim_id"] == "clm_pdf"
    assert relationship_status == 200
    assert json.loads(relationship_body)["relationships"][0]["relationship_type"] == "contradicts"


def test_server_browser_routes_return_stable_errors() -> None:
    from tests.test_ui_browser_api import seed_browser_catalog

    root = make_workspace()
    seed_browser_catalog(root)
    server, thread = start_test_server(root)
    try:
        for route, code, error in [
            ("/api/sources/missing", 404, "not_found"),
            ("/api/evidence/claims?limit=201", 400, "invalid_request"),
        ]:
            try:
                read_url(server, route)
            except HTTPError as exc:
                body = exc.read().decode("utf-8")
                payload = json.loads(body)
                assert exc.code == code
                assert payload["error"] == error
                assert payload["schema_version"] == "ui.v3.4"
            else:  # pragma: no cover - defensive
                raise AssertionError(f"Expected HTTP {code} for {route}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_server_browser_routes_report_catalog_unavailable() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    (root / "state" / "catalog.sqlite").unlink()
    server, thread = start_test_server(root)
    try:
        try:
            read_url(server, "/api/evidence/claims")
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            payload = json.loads(body)
            assert exc.code == 409
            assert payload["error"] == "catalog_unavailable"
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 409")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_server_does_not_add_v3_4_browser_post_routes() -> None:
    from tests.test_ui_browser_api import seed_browser_catalog

    root = make_workspace()
    seed_browser_catalog(root)
    server, thread = start_test_server(root)
    try:
        try:
            post_url(server, "/api/evidence/claims")
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            payload = json.loads(body)
            assert exc.code == 404
            assert payload["error"] == "not_found"
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_server_returns_json_404_for_unknown_api_route() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root)
    try:
        try:
            read_url(server, "/api/unknown")
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            payload = json.loads(body)
            assert exc.code == 404
            assert payload["error"] == "not_found"
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_server_serves_static_index_and_js() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root)
    try:
        index_status, index_type, index_body = read_url(server, "/")
        js_status, js_type, js_body = read_url(server, "/static/app.js")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert index_status == 200
    assert "text/html" in index_type
    assert "dashboard-root" in index_body
    assert js_status == 200
    assert "javascript" in js_type
    assert "/api/status" in js_body


def test_api_error_response_is_sanitized(monkeypatch) -> None:
    import llmwiki.ui.server as ui_server

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    def explode(root: Path):
        raise RuntimeError("Traceback sk-secret config/api-keys.toml")

    monkeypatch.setattr(ui_server, "get_workspace_status", explode)
    server, thread = start_test_server(root)
    try:
        try:
            read_url(server, "/api/status")
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            payload = json.loads(body)
            assert exc.code == 500
            assert payload["error"] == "internal_error"
            assert "Traceback" not in body
            assert "sk-" not in body
            assert "config/api-keys.toml" not in body
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 500")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_serve_ui_starts_and_stops_job_manager(monkeypatch, tmp_path: Path) -> None:
    import llmwiki.ui.server as ui_server

    events: list[str] = []

    class FakeJobManager:
        def start(self) -> None:
            events.append("start")

        def stop(self) -> None:
            events.append("stop")

    class FakeServer:
        server_address = ("127.0.0.1", 8765)

        def __init__(self) -> None:
            self.job_manager = FakeJobManager()

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            self.job_manager.stop()

    monkeypatch.setattr(ui_server, "create_ui_server", lambda config: FakeServer())
    monkeypatch.setattr(ui_server.webbrowser, "open", lambda url: (_ for _ in ()).throw(AssertionError("browser should not open")))

    ui_server.serve_ui(tmp_path, open_browser=False)

    assert events == ["start", "stop"]


def test_dispatch_ui_job_supports_v3_3_job_types(monkeypatch, tmp_path: Path) -> None:
    import llmwiki.ui.server as ui_server
    from llmwiki.ui.jobs import UiJob

    calls: list[str] = []

    monkeypatch.setattr(ui_server, "run_add_source_job", lambda root, job: calls.append(f"add:{job.job_id}") or job)
    monkeypatch.setattr(ui_server, "run_ask_job", lambda root, job: calls.append(f"ask:{job.job_id}") or job, raising=False)
    monkeypatch.setattr(ui_server, "run_synthesis_preview_job", lambda root, job: calls.append(f"preview:{job.job_id}") or job, raising=False)
    monkeypatch.setattr(ui_server, "run_synthesis_writeback_job", lambda root, job: calls.append(f"writeback:{job.job_id}") or job, raising=False)

    for job_type in ["add_source", "ask_question", "synthesis_preview", "synthesis_writeback"]:
        ui_server.dispatch_ui_job(tmp_path, UiJob(job_id=f"job_{job_type}", job_type=job_type))

    assert calls == [
        "add:job_add_source",
        "ask:job_ask_question",
        "preview:job_synthesis_preview",
        "writeback:job_synthesis_writeback",
    ]
