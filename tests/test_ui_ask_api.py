from __future__ import annotations

import json
from urllib.error import HTTPError

from llmwiki.cli import main
from tests.helpers import make_workspace
from tests.test_ui_server_actions import post_json, post_raw, read_json, start_test_server, stop_server


def test_post_ask_requires_action_token() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root, token="abc123")
    try:
        for token in (None, "wrong"):
            try:
                post_json(server, "/api/ask", {"question": "What is OSWorld?"}, token=token)
            except HTTPError as exc:
                payload = json.loads(exc.read().decode("utf-8"))
                assert exc.code == 403
                assert payload["error"] == "forbidden"
            else:  # pragma: no cover - defensive
                raise AssertionError("Expected HTTP 403")
    finally:
        stop_server(server, thread)


def test_post_ask_with_valid_token_queues_job() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root, token="abc123")
    try:
        status, payload, headers = post_json(
            server,
            "/api/ask",
            {"question": "What is OSWorld?", "limit": 5, "confidence": "cited"},
            token="abc123",
        )
    finally:
        stop_server(server, thread)

    assert status == 202
    assert payload["schema_version"] == "ui.v3.3"
    assert payload["job"]["job_type"] == "ask_question"
    assert payload["job"]["question"] == "What is OSWorld?"
    assert payload["job"]["ask_options"]["limit"] == 5
    assert "Access-Control-Allow-Origin" not in headers


def test_post_ask_invalid_json_returns_400() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root, token="abc123")
    try:
        try:
            post_raw(server, "/api/ask", b"{bad", token="abc123")
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


def test_get_ask_jobs_returns_ask_jobs_only() -> None:
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_add_source_job, create_ask_job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    add_job = create_add_source_job(root, "paper.pdf")
    ask_job = create_ask_job(root, AskUiRequest(question="What is OSWorld?"))
    server, thread = start_test_server(root)
    try:
        status, payload, _ = read_json(server, "/api/ask/jobs")
    finally:
        stop_server(server, thread)

    assert status == 200
    assert payload["schema_version"] == "ui.v3.3"
    assert [job["job_id"] for job in payload["jobs"]] == [ask_job.job_id]
    assert add_job.job_id not in repr(payload)


def test_get_ask_job_detail_or_404() -> None:
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_ask_job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = create_ask_job(root, AskUiRequest(question="What is OSWorld?"))
    server, thread = start_test_server(root)
    try:
        status, payload, _ = read_json(server, f"/api/ask/jobs/{ask_job.job_id}")
        try:
            read_json(server, "/api/ask/jobs/missing")
        except HTTPError as exc:
            missing_payload = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 404
            assert missing_payload["error"] == "not_found"
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 404")
    finally:
        stop_server(server, thread)

    assert status == 200
    assert payload["job_id"] == ask_job.job_id
    assert payload["question"] == "What is OSWorld?"


def test_session_endpoint_includes_ask_supported_actions() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root, token="abc123")
    try:
        status, payload, _ = read_json(server, "/api/session")
    finally:
        stop_server(server, thread)

    assert status == 200
    assert payload["schema_version"] == "ui.v3.3"
    assert payload["supported_actions"] == [
        "add_source",
        "ask_question",
        "synthesis_preview",
        "synthesis_writeback",
    ]


def test_post_ask_validation_failure_is_sanitized() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root, token="abc123")
    try:
        try:
            post_json(server, "/api/ask", {"question": "bad\u0000sk-secret config/api-keys.toml"}, token="abc123")
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
