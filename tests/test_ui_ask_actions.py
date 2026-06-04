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


def test_run_ask_job_calls_answer_question_and_stores_compact_result(monkeypatch) -> None:
    from llmwiki.ask.answer import AnswerCitation, AskOptions, AskResult
    from llmwiki.ui.ask_actions import run_ask_job
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_ask_job, load_jobs

    root = make_workspace()
    job = create_ask_job(
        root,
        AskUiRequest(
            question="What is OSWorld?",
            limit=5,
            source_id="src_osworld",
            page_type="source",
            confidence="cited",
        ),
    )
    calls = []

    def fake_answer_question(call_root: Path, question: str, options: AskOptions) -> AskResult:
        calls.append((call_root, question, options))
        return AskResult(
            question=question,
            status="answered",
            answer="OSWorld is a benchmark.",
            analysis="It evaluates GUI agents.",
            citations=[
                AnswerCitation(
                    claim_id="claim_1",
                    source_id="src_osworld",
                    citation_locator="page:1;block:src_osworld_p001_b0001",
                    page_path="wiki/sources/osworld.md",
                )
            ],
            warnings=["warning"],
            uncertainties=["uncertain"],
            conflicts=["conflict"],
            suggested_title="OSWorld",
            contexts=[
                {
                    "claim_id": "claim_1",
                    "source_id": "src_osworld",
                    "citation_locator": "page:1;block:src_osworld_p001_b0001",
                    "page_path": "wiki/sources/osworld.md",
                    "claim_text": "OSWorld evaluates GUI agents.",
                }
            ],
            relationships=[{"relationship_type": "supports", "source_id": "src_osworld"}],
            planning={"schema_version": "query_plan.v2.5", "status": "planned"},
        )

    monkeypatch.setattr("llmwiki.ui.ask_actions.answer_question", fake_answer_question)

    updated = run_ask_job(root, job)
    stored = load_jobs(root).jobs[0]

    assert updated.status == "applied"
    assert updated.result["answer_status"] == "answered"
    assert updated.result["citations"][0]["claim_id"] == "claim_1"
    assert updated.result["contexts"][0]["claim_id"] == "claim_1"
    assert updated.result["planning"]["status"] == "planned"
    assert stored.result == updated.result
    assert len(calls) == 1
    assert calls[0][1] == "What is OSWorld?"
    assert calls[0][2].limit == 5
    assert calls[0][2].source_id == "src_osworld"


def test_run_ask_job_stores_non_answered_domain_status_as_success(monkeypatch) -> None:
    from llmwiki.ask.answer import AskOptions, AskResult
    from llmwiki.ui.ask_actions import run_ask_job
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_ask_job

    root = make_workspace()
    job = create_ask_job(root, AskUiRequest(question="No evidence?"))

    def fake_answer_question(call_root: Path, question: str, options: AskOptions) -> AskResult:
        return AskResult(
            question=question,
            status="planned_insufficient_evidence",
            warnings=["No matching claims found."],
            planning={"status": "planned_insufficient_evidence"},
        )

    monkeypatch.setattr("llmwiki.ui.ask_actions.answer_question", fake_answer_question)

    updated = run_ask_job(root, job)

    assert updated.status == "applied"
    assert updated.result["answer_status"] == "planned_insufficient_evidence"
    assert updated.result["warnings"] == ["No matching claims found."]


def test_run_ask_job_preserves_llm_failure_status(monkeypatch) -> None:
    from llmwiki.ask.answer import AskOptions, AskResult
    from llmwiki.ui.ask_actions import run_ask_job
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_ask_job

    root = make_workspace()
    job = create_ask_job(root, AskUiRequest(question="Bad answer?"))

    def fake_answer_question(call_root: Path, question: str, options: AskOptions) -> AskResult:
        return AskResult(question=question, status="llm_failed", error="sk-secret config/api-keys.toml")

    monkeypatch.setattr("llmwiki.ui.ask_actions.answer_question", fake_answer_question)

    updated = run_ask_job(root, job)

    assert updated.status == "applied"
    assert updated.result["answer_status"] == "llm_failed"
    assert "sk-" not in repr(updated.to_dict())
    assert "config/api-keys.toml" not in repr(updated.to_dict())


def test_run_ask_job_unexpected_exception_marks_job_failed(monkeypatch) -> None:
    from llmwiki.ask.answer import AskOptions
    from llmwiki.ui.ask_actions import run_ask_job
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_ask_job

    root = make_workspace()
    job = create_ask_job(root, AskUiRequest(question="Crash?"))

    def fake_answer_question(call_root: Path, question: str, options: AskOptions):
        raise RuntimeError("boom sk-secret config/api-keys.toml")

    monkeypatch.setattr("llmwiki.ui.ask_actions.answer_question", fake_answer_question)

    updated = run_ask_job(root, job)

    assert updated.status == "failed"
    assert updated.failure_stage == "ask"
    assert "sk-" not in repr(updated.to_dict())
    assert "config/api-keys.toml" not in repr(updated.to_dict())
