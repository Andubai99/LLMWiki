from __future__ import annotations

import json
from urllib.error import HTTPError

from llmwiki.cli import main
from tests.helpers import make_workspace
from tests.test_ui_server_actions import post_json, read_json, start_test_server, stop_server
from tests.test_ui_synthesis_actions import make_answered_ask_job, make_preview_job


def test_post_synthesis_preview_requires_token() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = make_answered_ask_job(root)
    server, thread = start_test_server(root, token="abc123")
    try:
        for token in (None, "wrong"):
            try:
                post_json(server, f"/api/ask/{ask_job.job_id}/synthesis/preview", {}, token=token)
            except HTTPError as exc:
                payload = json.loads(exc.read().decode("utf-8"))
                assert exc.code == 403
                assert payload["error"] == "forbidden"
            else:  # pragma: no cover - defensive
                raise AssertionError("Expected HTTP 403")
    finally:
        stop_server(server, thread)


def test_post_synthesis_preview_unknown_ask_job_returns_404() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root, token="abc123")
    try:
        try:
            post_json(server, "/api/ask/missing/synthesis/preview", {}, token="abc123")
        except HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 404
            assert payload["error"] == "ask_job_not_found"
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 404")
    finally:
        stop_server(server, thread)


def test_post_synthesis_preview_rejects_non_answered_ask_job() -> None:
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_ask_job, update_job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = create_ask_job(root, AskUiRequest(question="No evidence?"))
    update_job(root, ask_job, status="applied", result={"answer_status": "planned_insufficient_evidence"})
    server, thread = start_test_server(root, token="abc123")
    try:
        try:
            post_json(server, f"/api/ask/{ask_job.job_id}/synthesis/preview", {}, token="abc123")
        except HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert payload["error"] == "ask_job_not_answered"
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 400")
    finally:
        stop_server(server, thread)


def test_post_synthesis_preview_valid_answered_job_queues_preview() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = make_answered_ask_job(root)
    server, thread = start_test_server(root, token="abc123")
    try:
        status, payload, _ = post_json(
            server,
            f"/api/ask/{ask_job.job_id}/synthesis/preview",
            {},
            token="abc123",
        )
        jobs_status, jobs_payload, _ = read_json(server, "/api/jobs")
    finally:
        stop_server(server, thread)

    assert status == 202
    assert payload["schema_version"] == "ui.v3.4"
    assert payload["job"]["job_type"] == "synthesis_preview"
    assert payload["job"]["parent_job_id"] == ask_job.job_id
    assert jobs_status == 200
    assert payload["job"]["job_id"] in [job["job_id"] for job in jobs_payload["jobs"]]


def test_post_synthesis_preview_failure_response_is_sanitized() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    server, thread = start_test_server(root, token="abc123")
    try:
        try:
            post_json(server, "/api/ask/sk-secret-config-api-keys/synthesis/preview", {}, token="abc123")
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            assert exc.code == 404
            assert "Traceback" not in body
            assert "sk-" not in body
            assert "config/api-keys.toml" not in body
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 404")
    finally:
        stop_server(server, thread)


def test_post_synthesis_writeback_requires_token() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = make_answered_ask_job(root)
    make_preview_job(root, ask_job.job_id)
    server, thread = start_test_server(root, token="abc123")
    try:
        for token in (None, "wrong"):
            try:
                post_json(server, f"/api/ask/{ask_job.job_id}/synthesis/writeback", {"writeback_mode": "auto"}, token=token)
            except HTTPError as exc:
                payload = json.loads(exc.read().decode("utf-8"))
                assert exc.code == 403
                assert payload["error"] == "forbidden"
            else:  # pragma: no cover - defensive
                raise AssertionError("Expected HTTP 403")
    finally:
        stop_server(server, thread)


def test_post_synthesis_writeback_invalid_mode_returns_400() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = make_answered_ask_job(root)
    make_preview_job(root, ask_job.job_id)
    server, thread = start_test_server(root, token="abc123")
    try:
        try:
            post_json(server, f"/api/ask/{ask_job.job_id}/synthesis/writeback", {"writeback_mode": "bad"}, token="abc123")
        except HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert payload["error"] == "invalid_writeback_mode"
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 400")
    finally:
        stop_server(server, thread)


def test_post_synthesis_writeback_missing_preview_returns_400() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = make_answered_ask_job(root)
    server, thread = start_test_server(root, token="abc123")
    try:
        try:
            post_json(server, f"/api/ask/{ask_job.job_id}/synthesis/writeback", {"writeback_mode": "auto"}, token="abc123")
        except HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert payload["error"] == "synthesis_preview_required"
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected HTTP 400")
    finally:
        stop_server(server, thread)


def test_post_synthesis_writeback_valid_request_queues_job() -> None:
    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = make_answered_ask_job(root)
    make_preview_job(root, ask_job.job_id)
    server, thread = start_test_server(root, token="abc123")
    try:
        status, payload, _ = post_json(
            server,
            f"/api/ask/{ask_job.job_id}/synthesis/writeback",
            {"writeback_mode": "update"},
            token="abc123",
        )
    finally:
        stop_server(server, thread)

    assert status == 202
    assert payload["schema_version"] == "ui.v3.4"
    assert payload["job"]["job_type"] == "synthesis_writeback"
    assert payload["job"]["parent_job_id"] == ask_job.job_id
    assert payload["job"]["writeback_mode"] == "update"
