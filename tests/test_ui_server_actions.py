from __future__ import annotations

from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json

from llmwiki.cli import main
from tests.helpers import make_workspace


def start_test_server(root: Path, *, token: str = "test-token"):
    from llmwiki.ui.server import UiServerConfig, create_ui_server

    server = create_ui_server(UiServerConfig(root=root, host="127.0.0.1", port=0, action_token=token))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def read_json(server, path: str) -> tuple[int, dict[str, object], object]:
    host, port = server.server_address
    with urlopen(f"http://{host}:{port}{path}", timeout=5) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body), response.headers


def post_json(server, path: str, payload: object, *, token: str | None = None):
    host, port = server.server_address
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-LLMWiki-UI-Token"] = token
    request = Request(f"http://{host}:{port}{path}", data=data, headers=headers, method="POST")
    with urlopen(request, timeout=5) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body), response.headers


def post_raw(server, path: str, body: bytes, *, token: str | None = None):
    host, port = server.server_address
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-LLMWiki-UI-Token"] = token
    request = Request(f"http://{host}:{port}{path}", data=body, headers=headers, method="POST")
    with urlopen(request, timeout=5) as response:
        text = response.read().decode("utf-8")
        return response.status, json.loads(text), response.headers


def stop_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_session_endpoint_returns_action_token_and_supported_actions() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root, token="abc123")
    try:
        status, payload, headers = read_json(server, "/api/session")
    finally:
        stop_server(server, thread)

    assert status == 200
    assert payload["schema_version"] == "ui.v3.2"
    assert payload["action_token"] == "abc123"
    assert "add_source" in payload["supported_actions"]
    assert "Access-Control-Allow-Origin" not in headers


def test_jobs_endpoint_returns_json() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root)
    try:
        status, payload, _ = read_json(server, "/api/jobs")
    finally:
        stop_server(server, thread)

    assert status == 200
    assert payload["schema_version"] == "ui.v3.2"
    assert payload["jobs"] == []


def test_job_detail_endpoint_returns_json_or_404() -> None:
    from llmwiki.ui.jobs import create_add_source_job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    job = create_add_source_job(root, "paper.pdf")
    server, thread = start_test_server(root)
    try:
        status, payload, _ = read_json(server, f"/api/jobs/{job.job_id}")
        try:
            read_json(server, "/api/jobs/missing")
        except HTTPError as exc:
            missing_payload = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 404
            assert missing_payload["error"] == "not_found"
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 404")
    finally:
        stop_server(server, thread)

    assert status == 200
    assert payload["job_id"] == job.job_id


def test_post_add_source_requires_action_token() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root, token="abc123")
    try:
        for token in (None, "wrong"):
            try:
                post_json(server, "/api/sources/add", {"source": "paper.pdf"}, token=token)
            except HTTPError as exc:
                payload = json.loads(exc.read().decode("utf-8"))
                assert exc.code == 403
                assert payload["error"] == "forbidden"
            else:  # pragma: no cover - defensive
                raise AssertionError("Expected HTTP 403")
    finally:
        stop_server(server, thread)


def test_post_add_source_with_valid_token_enqueues_job() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    (root / "paper.pdf").write_text("fake", encoding="utf-8")
    server, thread = start_test_server(root, token="abc123")
    try:
        status, payload, _ = post_json(
            server,
            "/api/sources/add",
            {"source": "paper.pdf", "parser": "pypdf"},
            token="abc123",
        )
        jobs_status, jobs_payload, _ = read_json(server, "/api/jobs")
    finally:
        stop_server(server, thread)

    assert status == 202
    assert payload["schema_version"] == "ui.v3.2"
    assert payload["job"]["status"] == "pending"
    assert jobs_status == 200
    assert jobs_payload["jobs"][0]["job_id"] == payload["job"]["job_id"]


def test_post_add_source_invalid_json_returns_400() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root, token="abc123")
    try:
        try:
            post_raw(server, "/api/sources/add", b"{bad", token="abc123")
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            payload = json.loads(body)
            assert exc.code == 400
            assert payload["error"] == "invalid_json"
            assert "Traceback" not in body
            assert "sk-" not in body
            assert "config/api-keys.toml" not in body
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 400")
    finally:
        stop_server(server, thread)


def test_post_failure_response_is_sanitized() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root, token="abc123")
    try:
        try:
            post_json(server, "/api/sources/add", {"source": "config/api-keys.toml"}, token="abc123")
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            assert exc.code == 400
            assert "Traceback" not in body
            assert "sk-" not in body
            assert "config/api-keys.toml" not in body
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 400")
    finally:
        stop_server(server, thread)
