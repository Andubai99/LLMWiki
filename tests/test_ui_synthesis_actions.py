from __future__ import annotations

from pathlib import Path

from llmwiki.cli import main
from tests.helpers import make_workspace


def answered_ask_result() -> dict[str, object]:
    return {
        "question": "What is OSWorld?",
        "answer": "OSWorld is a benchmark.",
        "analysis": "It evaluates GUI agents.",
        "answer_status": "answered",
        "citations": [
            {
                "claim_id": "claim_1",
                "source_id": "src_osworld",
                "citation_locator": "page:1;block:src_osworld_p001_b0001",
                "page_path": "wiki/sources/osworld.md",
            }
        ],
        "warnings": ["warning"],
        "uncertainties": [],
        "conflicts": [],
        "planning": {"status": "planned"},
        "contexts": [
            {
                "claim_id": "claim_1",
                "source_id": "src_osworld",
                "citation_locator": "page:1;block:src_osworld_p001_b0001",
                "page_path": "wiki/sources/osworld.md",
            }
        ],
        "relationships": [],
        "suggested_title": "OSWorld",
        "error": "",
    }


def make_answered_ask_job(root: Path):
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_ask_job, update_job

    job = create_ask_job(root, AskUiRequest(question="What is OSWorld?"))
    return update_job(root, job, status="applied", stage="answered", result=answered_ask_result())


def make_plan(action: str = "create", status: str = "planned"):
    from llmwiki.synthesis.planner import SynthesisEvidenceItem, SynthesisPlan

    return SynthesisPlan(
        schema_version="synthesis_plan.v2.8",
        status=status,
        action=action,
        target_page_id="synthesis-osworld",
        target_path="wiki/syntheses/osworld.md",
        title="OSWorld",
        topic_key="osworld",
        evidence=[
            SynthesisEvidenceItem(
                role="supports",
                claim_id="claim_1",
                source_id="src_osworld",
                citation_locator="page:1;block:src_osworld_p001_b0001",
                page_path="wiki/sources/osworld.md",
            )
        ],
        sections={"scope": "OSWorld scope"},
        warnings=["review warning"] if action == "needs_review" else [],
    )


def test_synthesis_preview_requires_existing_answered_ask_job() -> None:
    from llmwiki.ui.ask_actions import AskUiActionError, enqueue_synthesis_preview_job

    class FakeManager:
        def enqueue(self, job):
            return job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    try:
        enqueue_synthesis_preview_job(root, "missing", {}, FakeManager())
    except AskUiActionError as exc:
        assert exc.code == "ask_job_not_found"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected AskUiActionError")


def test_synthesis_preview_rejects_non_answered_ask_job() -> None:
    from llmwiki.ui.ask_actions import AskUiActionError, enqueue_synthesis_preview_job
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_ask_job, update_job

    class FakeManager:
        def enqueue(self, job):
            return job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    job = create_ask_job(root, AskUiRequest(question="No evidence?"))
    update_job(root, job, status="applied", result={"answer_status": "planned_insufficient_evidence"})

    try:
        enqueue_synthesis_preview_job(root, job.job_id, {}, FakeManager())
    except AskUiActionError as exc:
        assert exc.code == "ask_job_not_answered"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected AskUiActionError")


def test_run_synthesis_preview_job_stores_plan_preview(monkeypatch) -> None:
    from llmwiki.ask.answer import AskResult
    from llmwiki.synthesis.planner import SynthesisPlanningOptions
    from llmwiki.ui.ask_actions import enqueue_synthesis_preview_job, run_synthesis_preview_job
    from llmwiki.ui.jobs import load_jobs

    class FakeManager:
        def enqueue(self, job):
            return job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = make_answered_ask_job(root)
    preview_job = enqueue_synthesis_preview_job(root, ask_job.job_id, {}, FakeManager())
    calls = []

    def fake_plan(root_arg: Path, ask_result: AskResult, options: SynthesisPlanningOptions):
        calls.append((root_arg, ask_result, options))
        return make_plan()

    monkeypatch.setattr("llmwiki.ui.ask_actions.plan_synthesis_writeback", fake_plan)

    updated = run_synthesis_preview_job(root, preview_job)
    stored = [job for job in load_jobs(root).jobs if job.job_id == updated.job_id][0]

    assert updated.status == "applied"
    assert updated.result["preview_status"] == "planned"
    assert updated.result["action"] == "create"
    assert updated.result["target_path"] == "wiki/syntheses/osworld.md"
    assert updated.result["evidence_claim_ids"] == ["claim_1"]
    assert "Synthesis proposal:" in str(updated.result["preview_text"])
    assert stored.result == updated.result
    assert len(calls) == 1
    assert calls[0][1].status == "answered"
    assert calls[0][1].citations[0].claim_id == "claim_1"


def test_synthesis_preview_needs_review_is_stored_without_staging(monkeypatch) -> None:
    from llmwiki.ui.ask_actions import enqueue_synthesis_preview_job, run_synthesis_preview_job

    class FakeManager:
        def enqueue(self, job):
            return job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = make_answered_ask_job(root)
    preview_job = enqueue_synthesis_preview_job(root, ask_job.job_id, {}, FakeManager())
    before = sorted((root / "staging").glob("*"))

    monkeypatch.setattr(
        "llmwiki.ui.ask_actions.plan_synthesis_writeback",
        lambda root_arg, ask_result, options: make_plan(action="needs_review", status="needs_review"),
    )

    updated = run_synthesis_preview_job(root, preview_job)
    after = sorted((root / "staging").glob("*"))

    assert updated.status == "applied"
    assert updated.result["preview_status"] == "needs_review"
    assert updated.result["action"] == "needs_review"
    assert before == after


def test_synthesis_preview_planning_failure_is_sanitized(monkeypatch) -> None:
    from llmwiki.synthesis.planner import SynthesisPlanningError
    from llmwiki.ui.ask_actions import enqueue_synthesis_preview_job, run_synthesis_preview_job

    class FakeManager:
        def enqueue(self, job):
            return job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    ask_job = make_answered_ask_job(root)
    preview_job = enqueue_synthesis_preview_job(root, ask_job.job_id, {}, FakeManager())

    def fail(*args, **kwargs):
        raise SynthesisPlanningError("bad sk-secret config/api-keys.toml")

    monkeypatch.setattr("llmwiki.ui.ask_actions.plan_synthesis_writeback", fail)

    updated = run_synthesis_preview_job(root, preview_job)

    assert updated.status == "failed"
    assert updated.failure_stage == "synthesis_preview"
    assert "sk-" not in repr(updated.to_dict())
    assert "config/api-keys.toml" not in repr(updated.to_dict())
