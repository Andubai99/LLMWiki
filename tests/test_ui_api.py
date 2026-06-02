from __future__ import annotations

from pathlib import Path
import json
import sqlite3

from llmwiki.cli import main
from llmwiki.ui.models import (
    ConfigStatusResponse,
    UiWarning,
    WorkspaceStatusResponse,
    sanitize_ui_text,
    workspace_relative_path,
)
from tests.helpers import make_workspace


def test_sanitize_ui_text_removes_secret_patterns() -> None:
    sanitized = sanitize_ui_text("sk-abc123 config/api-keys.toml api_key=secret")

    assert "sk-" not in sanitized
    assert "config/api-keys.toml" not in sanitized
    assert "api_key=secret" not in sanitized


def test_response_dataclass_to_dict_is_stable() -> None:
    response = WorkspaceStatusResponse(
        status="ready",
        workspace_root=".",
        initialized=True,
        catalog_present=True,
        catalog_ok=True,
        required_paths={"config/config.toml": True},
        counts={"sources": 1},
        latest_runs=[],
        warnings=[UiWarning(level="warning", message="bounded")],
    )

    assert response.to_dict() == {
        "schema_version": "ui.v3.2",
        "status": "ready",
        "workspace_root": ".",
        "initialized": True,
        "catalog_present": True,
        "catalog_ok": True,
        "required_paths": {"config/config.toml": True},
        "counts": {"sources": 1},
        "latest_runs": [],
        "warnings": [{"level": "warning", "message": "bounded", "category": "general"}],
    }


def test_config_status_to_dict_does_not_expose_secret_values() -> None:
    response = ConfigStatusResponse(
        llm={"enabled": True, "provider": "openai", "model": "deepseek", "api_key_present": True},
        embedding={"enabled": True, "provider": "dashscope", "model": "embed", "api_key_present": False},
        parser={"default_backend": "auto", "fallback_backend": "pypdf", "mineru_available": False},
        vector={"index_present": False, "stale": False},
        warnings=[],
    )

    payload = response.to_dict()

    assert payload["schema_version"] == "ui.v3.2"
    assert "api_key" not in repr(payload).replace("api_key_present", "")


def test_workspace_relative_path_bounds_output(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    inside = root / "wiki" / "index.md"
    outside = tmp_path / "elsewhere.md"

    assert workspace_relative_path(root, inside) == "wiki/index.md"
    assert workspace_relative_path(root, outside) == "[outside-workspace]"


def test_workspace_status_for_initialized_empty_workspace() -> None:
    from llmwiki.ui.api import get_workspace_status

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    response = get_workspace_status(root)
    payload = response.to_dict()

    assert payload["status"] == "initialized_empty"
    assert payload["initialized"] is True
    assert payload["catalog_present"] is True
    assert payload["catalog_ok"] is True
    assert payload["counts"]["sources"] == 0
    assert payload["counts"]["claims"] == 0


def test_workspace_status_for_missing_skeleton() -> None:
    from llmwiki.ui.api import get_workspace_status

    root = make_workspace()

    payload = get_workspace_status(root).to_dict()

    assert payload["status"] == "not_initialized"
    assert payload["initialized"] is False
    assert payload["catalog_present"] is False
    assert payload["warnings"]


def test_workspace_status_for_catalog_with_rows() -> None:
    from llmwiki.ui.api import get_workspace_status

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into sources (
                source_id, title, source_type, raw_path, normalized_path,
                sha256, url, imported_at, status
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("src_ui", "UI Source", "markdown", "sources/raw/src_ui.md", "sources/normalized/src_ui.md", "sha-ui", "", "now", "imported"),
        )

    payload = get_workspace_status(root).to_dict()

    assert payload["status"] == "ready"
    assert payload["counts"]["sources"] == 1


def test_workspace_status_missing_catalog_is_not_fatal() -> None:
    from llmwiki.ui.api import get_workspace_status

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    (root / "state" / "catalog.sqlite").unlink()

    payload = get_workspace_status(root).to_dict()

    assert payload["catalog_present"] is False
    assert payload["status"] == "degraded"
    assert any("catalog" in warning["message"].lower() for warning in payload["warnings"])


def test_workspace_status_does_not_call_mutating_or_provider_functions(monkeypatch) -> None:
    from llmwiki.ui.api import get_workspace_status

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0

    def forbidden(*args, **kwargs):
        raise AssertionError("UI status must be read-only")

    monkeypatch.setattr("llmwiki.llm.create_provider", forbidden)
    monkeypatch.setattr("llmwiki.vector.embeddings.create_embedding_provider", forbidden)
    monkeypatch.setattr("llmwiki.pdf.mineru_runner.run_mineru_command", forbidden)
    monkeypatch.setattr("llmwiki.ingestion.pipeline.add_and_process_source", forbidden)
    monkeypatch.setattr("llmwiki.ingestion.apply.apply_run", forbidden)
    monkeypatch.setattr("llmwiki.lint.lint_workspace", forbidden)

    payload = get_workspace_status(root).to_dict()

    assert payload["initialized"] is True


def seed_ui_catalog(root: Path) -> None:
    with sqlite3.connect(root / "state" / "catalog.sqlite") as conn:
        conn.execute(
            """
            insert into sources (
                source_id, title, source_type, raw_path, normalized_path,
                sha256, url, imported_at, status
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "src_ui",
                "UI Source",
                "pdf",
                "sources/raw/src_ui.pdf",
                "sources/normalized/src_ui.md",
                "sha-ui-api",
                "",
                "2026-06-02T00:00:00Z",
                "imported",
            ),
        )
        conn.execute(
            """
            insert into claims (claim_id, source_id, claim_text, citation_locator, confidence_status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("clm_ui", "src_ui", "UI evidence", "page:1;block:src_ui_p001_b0001", "cited", "now"),
        )
        conn.execute(
            """
            insert into pages (page_id, path, page_type, title, aliases, updated_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("page_ui", "wiki/sources/src_ui.md", "source", "UI Source", "[]", "now"),
        )
        conn.execute(
            """
            insert into ingest_runs (run_id, source_id, status, created_at, applied_at)
            values (?, ?, ?, ?, ?)
            """,
            ("run_ui", "src_ui", "applied", "2026-06-02T00:00:00Z", "2026-06-02T00:01:00Z"),
        )


def test_list_sources_includes_latest_run_and_sidecar_summary() -> None:
    from llmwiki.ui.api import list_sources

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    seed_ui_catalog(root)
    metadata_path = root / "sources" / "metadata" / "src_ui.json"
    metadata_path.write_text(
        json.dumps(
            {
                "source_id": "src_ui",
                "parser_backend": "mineru",
                "parser_backend_fallback_from": "pypdf",
                "metadata_path": "sources/metadata/src_ui.json",
                "blocks_path": "sources/blocks/src_ui.jsonl",
                "chunks_path": "sources/chunks/src_ui.jsonl",
            }
        ),
        encoding="utf-8",
    )
    (root / "sources" / "blocks" / "src_ui.jsonl").write_text("{}", encoding="utf-8")

    payload = [source.to_dict() for source in list_sources(root)]

    assert payload[0]["source_id"] == "src_ui"
    assert payload[0]["latest_run_id"] == "run_ui"
    assert payload[0]["latest_run_status"] == "applied"
    assert payload[0]["latest_job_id"] == ""
    assert payload[0]["latest_job_status"] == ""
    assert payload[0]["parser_backend"] == "mineru"
    assert payload[0]["parser_fallback"] == "pypdf"
    assert payload[0]["sidecars"] == {"metadata": True, "blocks": True, "chunks": False}


def test_list_sources_malformed_sidecar_warns_without_crashing() -> None:
    from llmwiki.ui.api import list_sources

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    seed_ui_catalog(root)
    (root / "sources" / "metadata" / "src_ui.json").write_text("{bad json", encoding="utf-8")

    source = list_sources(root)[0].to_dict()

    assert source["source_id"] == "src_ui"
    assert source["warnings"]
    assert "bad json" not in repr(source)


def test_list_sources_includes_latest_ui_job_summary() -> None:
    from llmwiki.ui.api import list_sources
    from llmwiki.ui.jobs import create_add_source_job, update_job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    seed_ui_catalog(root)
    job = create_add_source_job(root, "sources/raw/src_ui.pdf", parser="auto")
    update_job(root, job, status="applied", stage="applied", source_id="src_ui")

    payload = [source.to_dict() for source in list_sources(root)]

    assert payload[0]["latest_job_id"] == job.job_id
    assert payload[0]["latest_job_status"] == "applied"


def test_list_ui_jobs_and_get_ui_job_return_summaries_and_warnings() -> None:
    from llmwiki.ui.api import get_ui_job, list_ui_jobs
    from llmwiki.ui.jobs import create_add_source_job

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    job = create_add_source_job(root, "paper.pdf", parser="pypdf")
    (root / "state" / "ui-jobs" / "bad.json").write_text("{bad json", encoding="utf-8")

    payload = list_ui_jobs(root).to_dict()
    detail = get_ui_job(root, job.job_id)

    assert payload["schema_version"] == "ui.v3.2"
    assert payload["jobs"][0]["job_id"] == job.job_id
    assert payload["warnings"]
    assert detail is not None
    assert detail.to_dict()["job_id"] == job.job_id
    assert get_ui_job(root, "missing") is None


def test_list_runs_merges_catalog_and_staging_metadata() -> None:
    from llmwiki.ui.api import list_runs

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    seed_ui_catalog(root)
    run_dir = root / "staging" / "run_ui"
    (run_dir / "patches").mkdir(parents=True)
    (run_dir / "patches" / "001.json").write_text("{}", encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": "run_ui",
                "source_id": "src_ui",
                "status": "failed",
                "run_type": "ingest",
                "trigger": "add",
                "failed_stage": "apply",
                "failure_reason": "sk-secret config/api-keys.toml",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "claims.jsonl").write_text('{"claim_id":"clm_ui"}\n', encoding="utf-8")

    payload = [run.to_dict() for run in list_runs(root)]

    assert payload[0]["run_id"] == "run_ui"
    assert payload[0]["run_type"] == "ingest"
    assert payload[0]["trigger"] == "add"
    assert payload[0]["failed_stage"] == "apply"
    assert payload[0]["claim_count"] == 1
    assert payload[0]["patch_count"] == 1
    assert "sk-" not in payload[0]["failure_reason"]
    assert "api-keys.toml" not in payload[0]["failure_reason"]


def test_list_pages_includes_claim_count() -> None:
    from llmwiki.ui.api import list_pages

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    seed_ui_catalog(root)

    payload = [page.to_dict() for page in list_pages(root)]

    assert payload[0]["page_id"] == "page_ui"
    assert payload[0]["claim_count"] == 1


def test_get_config_status_reports_key_presence_without_values(monkeypatch) -> None:
    from llmwiki.ui.api import get_config_status

    root = make_workspace()
    assert main(["init", "--root", str(root)]) == 0
    (root / "config" / "api-keys.toml").write_text(
        "[llm]\napi_key = \"sk-test-secret\"\n\n[embedding]\napi_key = \"embed-secret\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "llmwiki.ui.api.probe_mineru_status",
        lambda config: {"available": False, "command_source": "not_found", "warnings": ["missing"]},
    )

    payload = get_config_status(root).to_dict()

    assert payload["llm"]["api_key_present"] is True
    assert payload["embedding"]["api_key_present"] is True
    assert payload["parser"]["default_backend"] == "auto"
    assert payload["parser"]["mineru_available"] is False
    assert "sk-test-secret" not in repr(payload)
    assert "embed-secret" not in repr(payload)
