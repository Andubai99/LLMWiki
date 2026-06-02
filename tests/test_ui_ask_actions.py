from __future__ import annotations

from pathlib import Path
import uuid

from llmwiki.cli import main


WORKSPACES = Path(".test-workspaces")


def make_workspace() -> Path:
    root = WORKSPACES / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    assert main(["init", "--root", str(root)]) == 0
    return root


def test_validate_ask_request_rejects_empty_question() -> None:
    from llmwiki.ui.ask_actions import AskUiActionError, validate_ask_request

    root = make_workspace()

    try:
        validate_ask_request(root, {"question": "   "})
    except AskUiActionError as exc:
        assert exc.code == "invalid_question"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected AskUiActionError")


def test_validate_ask_request_rejects_control_characters() -> None:
    from llmwiki.ui.ask_actions import AskUiActionError, validate_ask_request

    root = make_workspace()

    try:
        validate_ask_request(root, {"question": "What is OSWorld?\u0000"})
    except AskUiActionError as exc:
        assert exc.code == "invalid_question"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected AskUiActionError")


def test_validate_ask_request_rejects_invalid_limit() -> None:
    from llmwiki.ui.ask_actions import AskUiActionError, validate_ask_request

    root = make_workspace()

    for limit in (0, 21, "not-a-number"):
        try:
            validate_ask_request(root, {"question": "What is OSWorld?", "limit": limit})
        except AskUiActionError as exc:
            assert exc.code == "invalid_limit"
        else:  # pragma: no cover - defensive
            raise AssertionError(f"Expected AskUiActionError for limit={limit!r}")


def test_validate_ask_request_rejects_invalid_confidence() -> None:
    from llmwiki.ui.ask_actions import AskUiActionError, validate_ask_request

    root = make_workspace()

    try:
        validate_ask_request(root, {"question": "What is OSWorld?", "confidence": "high"})
    except AskUiActionError as exc:
        assert exc.code == "invalid_confidence"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected AskUiActionError")


def test_validate_ask_request_defaults_minimal_request() -> None:
    from llmwiki.ui.ask_actions import validate_ask_request

    root = make_workspace()

    request = validate_ask_request(root, {"question": "What is OSWorld?"})

    assert request.question == "What is OSWorld?"
    assert request.limit == 8
    assert request.source_id is None
    assert request.page_type is None
    assert request.confidence is None


def test_validate_ask_request_preserves_filters() -> None:
    from llmwiki.ui.ask_actions import validate_ask_request

    root = make_workspace()

    request = validate_ask_request(
        root,
        {
            "question": "What is OSWorld?",
            "limit": "12",
            "source_id": "src_osworld",
            "page_type": "source",
            "confidence": "cited",
        },
    )

    assert request.limit == 12
    assert request.source_id == "src_osworld"
    assert request.page_type == "source"
    assert request.confidence == "cited"


def test_ask_validation_error_sanitizes_secret_values() -> None:
    from llmwiki.ui.ask_actions import AskUiActionError

    error = AskUiActionError("invalid_question", "bad sk-secret config/api-keys.toml")
    payload = error.to_dict()

    assert "sk-" not in repr(payload)
    assert "config/api-keys.toml" not in repr(payload)
