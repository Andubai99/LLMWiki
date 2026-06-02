from __future__ import annotations

from pathlib import Path
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
        "schema_version": "ui.v3.1",
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

    assert payload["schema_version"] == "ui.v3.1"
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
