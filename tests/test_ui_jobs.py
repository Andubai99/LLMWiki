from __future__ import annotations

import json
from pathlib import Path
import re
import uuid

from llmwiki.cli import main


WORKSPACES = Path(".test-workspaces")


def make_workspace() -> Path:
    root = WORKSPACES / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_ui_job_to_dict_has_stable_schema_and_sanitizes() -> None:
    from llmwiki.ui.jobs import UiJob

    job = UiJob(
        job_id="job_test",
        job_type="add_source",
        status="failed",
        source_input="docs/example.md",
        source_kind="local_path",
        requested_parser="auto",
        created_at="2026-06-02T00:00:00+00:00",
        stage="ingest",
        question="sk-secret question",
        ask_options={"source_id": "src_1", "note": "config/api-keys.toml"},
        parent_job_id="job_parent",
        writeback_mode="auto",
        failure_reason="sk-secret config/api-keys.toml",
    )

    payload = job.to_dict()

    assert payload["schema_version"] == "ui_job.v3.3"
    assert payload["job_id"] == "job_test"
    assert payload["status"] == "failed"
    assert payload["parent_job_id"] == "job_parent"
    assert payload["writeback_mode"] == "auto"
    assert "sk-" not in repr(payload)
    assert "config/api-keys.toml" not in repr(payload)


def test_create_add_source_job_persists_pending_job() -> None:
    from llmwiki.ui.jobs import create_add_source_job, job_path

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    job = create_add_source_job(root, "docs/papers/a.pdf", parser="auto")
    payload = json.loads(job_path(root, job.job_id).read_text(encoding="utf-8"))

    assert re.match(r"job_\d{8}_\d{6}_[a-f0-9]{8}", job.job_id)
    assert job.status == "pending"
    assert job.stage == "queued"
    assert job.source_kind == "local_path"
    assert payload["schema_version"] == "ui_job.v3.3"
    assert payload["requested_parser"] == "auto"


def test_v3_2_job_json_still_loads() -> None:
    from llmwiki.ui.jobs import job_path, load_jobs

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    path = job_path(root, "job_v32")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "ui_job.v3.2",
                "job_id": "job_v32",
                "job_type": "add_source",
                "status": "pending",
                "source_input": "docs/a.pdf",
                "source_kind": "local_path",
                "created_at": "2026-06-02T00:00:00+00:00",
                "stage": "queued",
            }
        ),
        encoding="utf-8",
    )

    result = load_jobs(root)

    assert result.jobs[0].job_id == "job_v32"
    assert result.jobs[0].question == ""
    assert result.jobs[0].ask_options == {}
    assert result.jobs[0].parent_job_id == ""
    assert result.jobs[0].writeback_mode == ""


def test_create_ask_job_persists_question_and_options() -> None:
    from llmwiki.ui.ask_models import AskUiRequest
    from llmwiki.ui.jobs import create_ask_job, job_path

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    job = create_ask_job(
        root,
        AskUiRequest(
            question="What is OSWorld?",
            limit=12,
            source_id="src_osworld",
            page_type="source",
            confidence="cited",
        ),
    )
    payload = json.loads(job_path(root, job.job_id).read_text(encoding="utf-8"))

    assert job.job_type == "ask_question"
    assert job.question == "What is OSWorld?"
    assert job.ask_options == {
        "limit": 12,
        "source_id": "src_osworld",
        "page_type": "source",
        "confidence": "cited",
    }
    assert payload["question"] == "What is OSWorld?"
    assert payload["ask_options"]["limit"] == 12


def test_create_synthesis_jobs_persist_parent_and_mode() -> None:
    from llmwiki.ui.jobs import (
        create_synthesis_preview_job,
        create_synthesis_writeback_job,
        job_path,
    )

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    preview = create_synthesis_preview_job(root, "job_ask")
    writeback = create_synthesis_writeback_job(root, "job_ask", writeback_mode="update")
    preview_payload = json.loads(job_path(root, preview.job_id).read_text(encoding="utf-8"))
    writeback_payload = json.loads(job_path(root, writeback.job_id).read_text(encoding="utf-8"))

    assert preview.job_type == "synthesis_preview"
    assert preview.parent_job_id == "job_ask"
    assert writeback.job_type == "synthesis_writeback"
    assert writeback.parent_job_id == "job_ask"
    assert writeback.writeback_mode == "update"
    assert preview_payload["parent_job_id"] == "job_ask"
    assert writeback_payload["writeback_mode"] == "update"


def test_load_jobs_sorts_by_created_at_desc_and_reports_malformed() -> None:
    from llmwiki.ui.jobs import UiJob, load_jobs, save_job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    save_job(root, UiJob(job_id="job_old", created_at="2026-06-02T00:00:00+00:00"))
    save_job(root, UiJob(job_id="job_new", created_at="2026-06-02T01:00:00+00:00"))
    (root / "state" / "ui-jobs" / "bad.json").write_text("{bad json", encoding="utf-8")

    result = load_jobs(root)

    assert [job.job_id for job in result.jobs] == ["job_new", "job_old"]
    assert result.warnings
    assert "bad json" not in repr(result.to_dict())


def test_mark_stale_running_jobs_interrupted() -> None:
    from llmwiki.ui.jobs import UiJob, load_jobs, mark_stale_running_jobs_interrupted, save_job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    save_job(root, UiJob(job_id="job_running", status="running", stage="running"))

    changed = mark_stale_running_jobs_interrupted(root)
    result = load_jobs(root)

    assert changed == 1
    assert result.jobs[0].status == "interrupted"
    assert result.jobs[0].stage == "interrupted"
    assert result.jobs[0].warnings


def test_prune_jobs_keeps_recent_jobs() -> None:
    from llmwiki.ui.jobs import UiJob, load_jobs, prune_jobs, save_job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    for index in range(205):
        save_job(
            root,
            UiJob(
                job_id=f"job_{index:03d}",
                created_at=f"2026-06-02T00:{index // 60:02d}:{index % 60:02d}+00:00",
            ),
        )

    removed = prune_jobs(root, keep=200)
    result = load_jobs(root)

    assert removed == 5
    assert len(result.jobs) == 200
    assert result.jobs[0].job_id == "job_204"
    assert result.jobs[-1].job_id == "job_005"
