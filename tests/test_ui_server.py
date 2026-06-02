from __future__ import annotations

from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen
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
    assert payload["schema_version"] == "ui.v3.2"
    assert payload["initialized"] is True


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
